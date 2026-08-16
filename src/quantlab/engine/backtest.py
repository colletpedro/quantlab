"""Laço de barras — C5, design §4.3. **A parte mais fácil de errar da fase.**

É aqui que ADR-0002 vira código. A ordem das três operações dentro de cada
barra não é arbitrária, e uma inversão em refatoração futura reintroduz
lookahead sem que nada estoure — o teste de ENG-01.2 é o que quebra.

Nenhuma dependência de banco: recebe uma `PriceSeries` já materializada
(design §2). É o que permite testar o engine inteiro com séries de papel
(RNF-03).
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from quantlab.engine.broker import BarSlice, Broker, CostModel, MechanismCounters
from quantlab.engine.broker import PendingOrder as BrokerPendingOrder
from quantlab.engine.calendar import UnionCalendar
from quantlab.engine.conditional import ConditionalStrategy, OrderKind, Side
from quantlab.engine.liquidity import adv
from quantlab.engine.margin import (
    BorrowFeeModel,
    MarginCallOrder,
    MarginModel,
    margin_requirement,
)
from quantlab.engine.market_view import MarketView
from quantlab.engine.portfolio import Portfolio, Position, Trade, TradeOrigin
from quantlab.engine.sizing import (
    EqualWeightOpen,
    FixedOneOverN,
    Sizer,
    SizingInputs,
    rebalance_deviation_pp,
)
from quantlab.engine.slippage import FixedBps, SlippageModel
from quantlab.engine.strategy import Signal, Strategy
from quantlab.exceptions import EngineError
from quantlab.logging import get_logger
from quantlab.storage.series import PriceSeries

__all__ = [
    "BacktestResult",
    "BacktestResultMulti",
    "EquityPoint",
    "PendingOrder",
    "build_liquidation_plan",
    "run_backtest",
    "run_backtest_multi",
]

_log = get_logger(__name__)

#: Tolerância da identidade de conciliação — design §4.6, RNF-08.
_RECONCILIATION_REL_TOL = 1e-9


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """Um ponto da equity curve, marcado a mercado ao `close` da barra."""

    date: date
    equity: float
    cash: float
    position_value: float


@dataclass(frozen=True, slots=True)
class PendingOrder:
    """Ordem gerada em `decision_index`, elegível a partir de `decision_index + 1`.

    ADR-0002 em uma estrutura: a ordem carrega a data em que foi decidida, e o
    broker registra a distância até a execução no trade (ENG-01.5).
    """

    signal: Signal
    decision_index: int
    decision_date: date


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """O que um backtest produziu. Entrada do Bloco E (analytics)."""

    ticker: str
    equity_curve: list[EquityPoint]
    trades: list[Trade]
    initial_cash: float
    final_equity: float
    warmup: int
    costs: CostModel
    series_hash: str
    #: ENG-01.4 — sinal na última barra não executa e é reportado como pendente.
    pending_order: PendingOrder | None = None
    #: Metadados de reprodutibilidade (PER-03.1).
    last_ingested_at: str | None = None

    @property
    def realized_pnl(self) -> float:
        """Σ PnL realizado, BRUTO de custos (design §4.6)."""
        return sum(trade.realized_pnl for trade in self.trades)

    @property
    def total_costs(self) -> float:
        return sum(trade.total_cost for trade in self.trades)

    @property
    def unrealized_pnl(self) -> float:
        """PnL de posição ainda aberta ao fim, marcada pelo último `close`.

        ENG-02.4 — a posição não é liquidada à força; é marcada a mercado e
        reportada separadamente do realizado.
        """
        if not self.equity_curve:
            return 0.0
        open_trades = [trade for trade in self.trades if trade.is_open]
        if not open_trades:
            return 0.0
        last_price = self._last_close()
        return sum((last_price - trade.entry_price) * trade.quantity for trade in open_trades)

    def _last_close(self) -> float:
        final = self.equity_curve[-1]
        open_quantity = sum(trade.quantity for trade in self.trades if trade.is_open)
        if open_quantity == 0:
            return 0.0
        return final.position_value / open_quantity

    def reconciles(self) -> bool:
        """ENG-04.2 — a identidade de design §4.6.

            equity_final - equity_inicial
                == Σ pnl_realizado + pnl_nao_realizado - custo_total

        `math.isclose(rel_tol=1e-9)` conforme RNF-08. Nunca igualdade exata:
        dinheiro é float e a soma percorre caminhos de arredondamento
        diferentes dos dois lados.
        """
        left = self.final_equity - self.initial_cash
        right = self.realized_pnl + self.unrealized_pnl - self.total_costs
        return math.isclose(left, right, rel_tol=_RECONCILIATION_REL_TOL, abs_tol=1e-9)


@dataclass(slots=True)
class _LoopState:
    """Estado mutável do laço, isolado para o corpo do laço ficar legível."""

    portfolio: Portfolio
    pending: PendingOrder | None = None
    equity_curve: list[EquityPoint] = field(default_factory=list)


def run_backtest(
    series: PriceSeries,
    strategy: Strategy,
    *,
    initial_cash: float = 100_000.0,
    costs: CostModel | None = None,
) -> BacktestResult:
    """Roda a estratégia sobre a série, barra a barra.

    ────────────────────────────────────────────────────────────────────────
    **INVARIANTE — a ordem das três operações dentro de cada barra `i`:**

      1. **Executar a ordem pendente**, se houver, ao ``open[i]``.
      2. **Marcar a mercado** ao ``close[i]`` e registrar o ponto da equity.
      3. **Consultar a estratégia** com ``MarketView(i)``, se ``i >= warmup``.
         Um sinal retornado vira ordem pendente para ``i + 1``.

    **Quais ordens carregam peso, medido por mutação e não suposto:**

    - **Executar antes de marcar** (1 antes de 2) garante que a equity de `i`
      reflita a posição real ao fim de `i`. Marcar antes deixaria a equity um
      dia atrasada em toda barra com execução. Inverter derruba 3 testes.
    - **Executar antes de consultar** (1 antes de 3) garante que nenhuma
      decisão de `i` seja executada em `i`. É literalmente ADR-0002. Executar
      no mesmo índice da decisão derruba 6 testes.
    - **A ordem entre 2 e 3 é livre.** Consultar a estratégia não tem efeito
      colateral sobre a carteira — só devolve um sinal, que vira ordem
      pendente para `i + 1`. É consequência de ENG-05.2, e a mutação que
      inverte 2 e 3 não derruba teste nenhum, de propósito. A numeração acima
      é a ordem em que o código lê melhor, não uma restrição em três níveis.
      `test_the_equity_of_a_bar_does_not_depend_on_the_signal_emitted_on_it`
      trava a premissa: se alguém der efeito colateral a `on_bar`, aquele
      teste quebra e a liberdade some.

    Uma inversão das duas primeiras não estoura nada — produz um backtest
    melhor e falso. O que quebra é o teste de ENG-01.2 (mutação de barras
    futuras), em `tests/unit/test_backtest.py`, o critério de aceitação da
    fase.
    ────────────────────────────────────────────────────────────────────────

    O "próximo pregão disponível" de ENG-01.5 é simplesmente ``i + 1`` no
    array: a série contém só pregões, e gaps de calendário estão implícitos.
    O gap em dias corridos é computado e gravado no trade para auditoria.

    Sinal na última barra não tem ``i + 1``: a ordem morre pendente e é
    reportada como tal (ENG-01.4), sem afetar a contabilidade.
    """
    if len(series) == 0:
        raise EngineError(f"Série vazia para {series.ticker}: nada a backtestar.")

    warmup = strategy.warmup
    if warmup < 0:
        raise EngineError(f"warmup negativo ({warmup}) na estratégia.")

    broker = Broker(costs)
    state = _LoopState(portfolio=Portfolio(cash=initial_cash))
    ticker = series.ticker

    for index in range(len(series)):
        bar_date: date = series.dates[index]

        # ── 1. executar a ordem pendente ao open[i] — ADR-0002 vira código ──
        if state.pending is not None:
            _execute(broker, state, ticker=ticker, index=index, series=series)

        # ── 2. marcar a mercado ao close[i] e registrar a equity ────────────
        close_price = float(series.close[index])
        position = state.portfolio.positions.get(ticker)
        position_value = position.market_value(close_price) if position is not None else 0.0
        state.equity_curve.append(
            EquityPoint(
                date=bar_date,
                equity=state.portfolio.cash + position_value,
                cash=state.portfolio.cash,
                position_value=position_value,
            )
        )
        state.portfolio.check_invariants()

        # ── 3. consultar a estratégia POR ÚLTIMO ────────────────────────────
        if index >= warmup:
            signal = strategy.on_bar(MarketView(series, index))
            if signal is not None:
                state.pending = PendingOrder(
                    signal=signal, decision_index=index, decision_date=bar_date
                )

    final = state.equity_curve[-1]
    return BacktestResult(
        ticker=ticker,
        equity_curve=state.equity_curve,
        trades=state.portfolio.trades,
        initial_cash=initial_cash,
        final_equity=final.equity,
        warmup=warmup,
        costs=broker.costs,
        series_hash=series.hash,
        pending_order=state.pending,
        last_ingested_at=series.last_ingested_at,
    )


def _execute(
    broker: Broker,
    state: _LoopState,
    *,
    ticker: str,
    index: int,
    series: PriceSeries,
) -> None:
    """Passo 1 do laço: preenche a ordem pendente ao ``open[i]``.

    A ordem é consumida mesmo quando não vira trade — `ENTER` com posição
    aberta e `EXIT` sem posição são ignorados e logados (decisão Q2 do
    design), porque cruzamento repetido é condição de mercado, não erro.
    Deixar a ordem pendente nesse caso faria ela ser tentada de novo na
    barra seguinte, com um preço que a decisão não conhecia.
    """
    order = state.pending
    if order is None:  # pragma: no cover - guardado pelo chamador
        return
    state.pending = None

    open_price = float(series.open[index])
    execution_date: date = series.dates[index]

    if order.signal is Signal.ENTER:
        broker.buy(
            state.portfolio,
            ticker=ticker,
            price=open_price,
            execution_date=execution_date,
            decision_date=order.decision_date,
        )
        return

    if ticker not in state.portfolio.positions:
        # Decisão Q2, lado simétrico: EXIT sem posição é ignorado e logado.
        _log.info(
            "engine.exit_without_position",
            ticker=ticker,
            date=execution_date.isoformat(),
        )
        return

    broker.sell(
        state.portfolio,
        ticker=ticker,
        price=open_price,
        execution_date=execution_date,
        decision_date=order.decision_date,
    )


# ─── 2a (T11a): laço multi-ativo calendário-driven ───────────────────────────


@dataclass(frozen=True, slots=True)
class BacktestResultMulti:
    """Resultado do run multi-ativo (emenda T11a, design §3.6).

    ``dates`` é a união do calendário (T05) — a ``equity_curve`` tem um ponto
    por data-união, marcado a mercado após o passo 2 de cada `u` (POR-04.1).
    ``portfolio`` carrega o estado final (caixa, posições, trades, marks e
    pendentes); ``pending_dead`` conta as intenções mortas na última barra de
    cada ativo (ENG-01.4 por ativo — C1).
    """

    dates: tuple[date, ...]
    equity_curve: list[float]
    portfolio: Portfolio
    initial_cash: float
    n: int
    tickers: tuple[str, ...]
    warmup: dict[str, int]
    costs: CostModel
    slippage: SlippageModel
    cap: float
    calendar: UnionCalendar
    pending_dead: dict[str, int]
    #: POR-02.3 (T11b) — posições ABERTAS travadas por deslistagem: série
    #: terminou antes do fim da união. Marcadas pelo último close conhecido,
    #: nunca liquidadas; o relatório (T16) as reporta.
    delisted: tuple[str, ...]
    #: MET-05/P6 (T16) — contadores de mecanismo, agregados pelo laço; o
    #: relatório só reporta (design §3.8).
    counters: MechanismCounters = field(default_factory=MechanismCounters)
    #: 2b (T03, RF-SHT-03): Σ borrow fees debitados no close — termo próprio
    #: da conciliação (§6); acumulado no laço (T08a). Default 0 preserva os
    #: runs long-only da 2a.
    borrow_fees: float = 0.0
    #: 2b (T08a, RF-MRG-03 CA-03.1): fundo quebrado — equity < 0 sem posições
    #: (detectado no close) ou após liquidação total (T08b, cronologia do gap).
    #: Congela o laço (nenhum trade novo, pendentes canceladas, intenções
    #: descartadas); métricas de retorno derivam `None` explícito (R6 — nunca
    #: NaN) e o resultado é excluído de comparações automáticas (CA-03.3).
    broken_fund: bool = False
    #: 2b (T08a): config do run — reconstruível do JSON (RF-CON-02/CA-06.2).
    margin: MarginModel = field(default_factory=MarginModel)
    borrow: BorrowFeeModel = field(default_factory=BorrowFeeModel)

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1] if self.equity_curve else self.initial_cash

    @property
    def n_bars(self) -> int:
        return len(self.dates)


def build_liquidation_plan(
    positions: dict[str, Position],
    closes: dict[str, float],
    model: MarginModel,
    equity: float,
    decision_date: date,
    seq_start: int = 0,
) -> tuple[MarginCallOrder, ...]:
    """Plano de liquidação forçada (RF-MRG-02/D2, ADR-0009) — construído no
    CLOSE pelo laço quando `equity < margem` (CA-01.3: janela close→open).

    Seleção **alfabética por ticker** (MRG-02.4 — nunca preço como critério),
    **integral por ativo** (`qty = |qty_atual|`, nunca parcial — MRG-02):
    itera as posições em ordem alfabética, projeta a restauração a preços de
    close (sem custos — desconhecidos no close; a execução no open re-checa
    a margem a preços reais, CA-01.3) e **para quando a projeção atinge
    `equity >= margem`** (CA-02.1: repete até restaurar). Longs restauram sem
    perder equity (posição vira caixa); shorts reduzem equity E exigência —
    com `factor = 1.0` o plano inclui todos os shorts e a restauração fica
    para o open (CA-01.3). Função PURA e determinística (RNF-01).

    Raises:
        EngineError: `closes` incompleto/preço não positivo (via
            `margin_requirement`) ou posição zerada — erro de programação
            (§3.8).
    """
    req = margin_requirement(positions, closes, model)
    if equity >= req:
        return ()  # defensivo — o chamador só deve chamar com violação
    plan: list[MarginCallOrder] = []
    proj_equity = equity
    proj_req = req
    seq = seq_start
    for ticker in sorted(positions):
        if proj_equity >= proj_req:
            break  # CA-02.1 — restaurado (projeção a preços de close)
        pos = positions[ticker]
        if pos.quantity == 0:
            raise EngineError(
                f"build_liquidation_plan: posição zerada em {ticker} — erro de programação."
            )
        close_p = closes[ticker]
        magnitude = abs(pos.quantity)
        if pos.quantity > 0:
            # Long: vender converte a posição em caixa — equity invariante (sem
            # custos); a exigência cai pelo notional liquidado.
            proj_req -= magnitude * close_p * model.factor
        else:
            # Short: cobrir DEBITA o caixa — equity cai |qty| x close; a
            # exigência cai pelo notional (com factor 1.0 não restaura).
            proj_equity -= magnitude * close_p
            proj_req -= magnitude * close_p * model.factor
        plan.append(
            MarginCallOrder(
                ticker=ticker,
                side=Side.SELL if pos.quantity > 0 else Side.BUY,
                qty=magnitude,
                decision_date=decision_date,
                intent_seq=seq,
            )
        )
        seq += 1
    return tuple(plan)


def run_backtest_multi(
    series: dict[str, PriceSeries],
    strategies: Mapping[str, Strategy | ConditionalStrategy],
    *,
    initial_cash: float = 100_000.0,
    costs: CostModel | None = None,
    slippage: SlippageModel | None = None,
    cap: float = 0.10,
    sizer: Sizer | None = None,
    margin: MarginModel | None = None,
    borrow: BorrowFeeModel | None = None,
) -> BacktestResultMulti:
    """Roda N estratégias (uma por ativo) sobre o calendário-união, barra a barra.

    ────────────────────────────────────────────────────────────────────────
    **INVARIANTE — a ordem das operações dentro de cada data-união `u`**
    (extensão da §4.3 da Fase 1, preservada por ativo; 2b T08a):

      1. **Executar** no open da barra do PRÓPRIO ativo (ADR-0002 por ativo
         — POR-05.3), em duas passadas: (1a) as LIQUIDAÇÕES do plano da
         véspera (2b, T08b — RF-MRG-02): `execute_margin_calls` a mercado no
         open, long → SELL / short → BUY, origin=MARGIN_CALL (CA-02.3),
         re-checando a margem após CADA ativo e interrompendo quando
         restaurada (CA-02.1); plano esgotado + margem violada com equity ≥ 0
         ⇒ EngineError (CA-01.3); liquidação que empurra equity < 0 ⇒ fundo
         quebrado por gap: congela (emenda P1 — CA-03.1); e (1b) as PENDENTES
         regulares — a saída de um EXIT (venda ao open, origin=MARKET) e a
         cobertura de um EXIT_SHORT (compra ao open, T08a);
      2. **Marcar a mercado** pelo último close conhecido (POR-02.2) e
         registrar a equity de `u`;
      2b. **Rebalance** (só se sizer == EqualWeightOpen): k mudou ⇒ eventos
         com limiar em pp (SIZ-03.3) para o próximo open do próprio ativo
         (2a, inalterado);
      3. **Debitar o borrow fee** no close, etapa própria (2b, T08a —
         RF-SHT-03 CA-03.1/03.2): só com short aberto no close;
      4. **Checar margem** (2b, T08a — RF-MRG-01/02): `equity < margem` no
         close ⇒ plano de liquidação alfabético (CA-02.1), integral por ativo,
         cancelando as pendentes dos ativos do plano (CA-02.2); violação no
         close NÃO é erro (CA-01.3 — janela close→open; a execução do plano
         no open é a passada 1a da T08b). Sem posições e equity < 0 ⇒
         **fundo quebrado** (CA-03.1): congela (nenhum trade novo, pendentes
         canceladas, intenções descartadas, flag);
      5. **Consultar** as estratégias por ÚLTIMO (i ≥ warmup; se não
         congelado), MarketView só com barras do próprio ativo (POR-03.1/05.1);
         `EXIT_SHORT` sem posição short aberta ⇒ EngineError (SHT-01.3).

    **Por que a ordem importa (Fase 1 §4.3, estendido):** executar antes de
    marcar garante que a equity de `u` reflete a posição real ao fim de `u`;
    executar antes de consultar garante que nenhuma decisão de `u` executa em
    `u` (ADR-0002 em código). A sequência de fechamento **marcar → fee →
    margem → consultar** é nova e declarada como invariante (design §4): o
    fee usa o close (marcação), a margem usa o caixa pós-fee, e a consulta
    usa o close sem efeito colateral — uma inversão derruba a semântica de
    margem ou a auditoria do ENG-01.2 (T12 da 2b quebra). As fases rodam em
    ordem alfabética por ativo (determinismo RNF-01 + caixa compartilhado
    POR-01.2).

    **ENG-01.4 por ativo (C1):** intenção na ÚLTIMA barra da série de X morre
    pendente (não existe "próxima barra de X") — ENTER não é colocada, EXIT
    não agenda saída; contada em `pending_dead[X]` e reportada (T16).

    **Rebalance (SIZ-03, emenda T11a):** só com `EqualWeightOpen`; dispara
    quando `k` (posições abertas) muda dentro de `u`; alvo 1/k; para cada
    ativo com |w - 1/k| >= threshold_pp gera ordem sintética (MARKET,
    `rebalance=True`, side = sinal do delta) para o próximo open do próprio
    ativo. Roda entre marcar e consultar: a intenção de estratégia do MESMO
    `u` tem intent_seq maior e substitui o ajuste (última intenção vence).
    Com `k = 0` (primeira entrada) a política `EqualWeightOpen` usa a fração
    da default, `1/N` (decisão T11a — o alvo 1/0 é indefinido).
    """
    if not series:
        raise EngineError("run_backtest_multi: universo vazio — precisa de ao menos um ativo.")
    if not strategies:
        raise EngineError("run_backtest_multi: nenhuma estratégia registrada — nada a rodar.")
    unknown = sorted(set(strategies) - set(series))
    if unknown:
        raise EngineError(f"run_backtest_multi: estratégias para ativos fora do run: {unknown}.")
    for ticker, strategy in strategies.items():
        if strategy.warmup < 0:
            raise EngineError(
                f"run_backtest_multi: warmup negativo ({strategy.warmup}) em {ticker}."
            )
    if not 0.0 < cap <= 1.0:
        raise EngineError(f"run_backtest_multi: cap fora de (0, 1]: {cap}.")

    n = len(series)
    tickers = tuple(sorted(series))
    cost_model = costs or CostModel()
    slippage_model = slippage or FixedBps()
    sizer_model = sizer or FixedOneOverN(n)
    margin_model = margin or MarginModel()
    borrow_model = borrow or BorrowFeeModel()
    broker = Broker(cost_model)
    calendar = UnionCalendar.build(series)
    portfolio = Portfolio(cash=initial_cash)

    warmup: dict[str, int] = {t: strategies[t].warmup for t in tickers if t in strategies}
    pending_dead: dict[str, int] = {t: 0 for t in tickers}
    exit_pending: dict[str, date] = {}
    cover_pending: dict[str, date] = {}  # 2b (T08a) — EXIT_SHORT cobre no open
    equity_curve: list[float] = []
    intent_seq = 0
    # MET-05/P6 (T16): contadores de mecanismo — stops/ambiguidades derivados
    # dos fills, não-atendidas por caixa contadas no broker (convert/execução).
    counters = MechanismCounters()
    # 2b (T08a): estado do fechamento — plano de liquidação do close (executa
    # no open do PRÓPRIO ativo, T08b), contador próprio da liquidação (design
    # §3.3), fundo quebrado congelado e Σ borrow fees.
    margin_plan: dict[str, MarginCallOrder] = {}
    margin_seq = 0
    broken = False
    borrow_fees = 0.0

    for u in range(len(calendar.dates)):
        u_date = calendar.dates[u]
        k_before = len(portfolio.positions)

        # ── 1a. LIQUIDAÇÕES — plano da véspera (T08b, RF-MRG-02 CA-02.1/02.3;
        #    ADR-0002 por ativo / ADR-0009) ──────────────────────────────────
        if not broken:
            for ticker in tickers:
                order = margin_plan.get(ticker)
                if order is None:
                    continue
                i = calendar.bar_index_at(ticker, u)
                if i is None:
                    # Borda rara (design §5): ativo do plano sem barra em u — a
                    # liquidação espera a próxima barra do PRÓPRIO ativo; a
                    # ordem permanece no plano (nunca preço inventado).
                    continue
                margin_plan.pop(ticker)
                series_x = series[ticker]
                bar = BarSlice(
                    date=series_x.dates[i],
                    open=float(series_x.open[i]),
                    high=float(series_x.high[i]),
                    low=float(series_x.low[i]),
                    close=float(series_x.close[i]),
                )
                liquidated = broker.execute_margin_calls(
                    (order,), bar, portfolio, cost_model, slippage_model
                )
                # CA-02.3 — dono do contador é o laço (§3.7): 1 trade por
                # liquidação (origin = MARGIN_CALL).
                counters.margin_calls += sum(
                    1 for t in liquidated if t.origin == TradeOrigin.MARGIN_CALL
                )
                # CA-02.1 — re-checa a margem após CADA ativo liquidado, aos
                # preços de execução (caixa pós-liquidação + últimos closes
                # conhecidos), e interrompe quando restaurada.
                equity_now = portfolio.equity()
                requirement = margin_requirement(portfolio.positions, portfolio.marks, margin_model)
                if equity_now < 0:
                    # FUNDO QUEBRADO POR GAP (emenda P1, §4 passo 1a): a
                    # liquidação integral no open, ao preço do gap, empurrou a
                    # equity para NEGATIVO real — congela (CA-03.1): nenhum
                    # trade novo, pendentes canceladas, intenções descartadas.
                    broken = True
                    margin_plan.clear()
                    exit_pending.clear()
                    cover_pending.clear()
                    for t in tickers:
                        portfolio.pending.cancel_all(t)
                    break
                if equity_now >= requirement:
                    margin_plan.clear()  # restaurada — CA-02.1 (interrompe)
                    break
                if not margin_plan:
                    # CA-01.3 — plano esgotado + margem ainda violada com
                    # equity >= 0: violação persistindo após o open é erro de
                    # programação (só o fundo quebrado é saída legítima).
                    raise EngineError(
                        "run_backtest_multi: plano de liquidação esgotado e margem "
                        f"ainda violada após o open de {u_date} (equity {equity_now:.2f} "
                        f"< exigência {requirement:.2f}) — CA-01.3, erro de programação."
                    )

        # ── 1b. PENDENTES regulares (alfabético; ADR-0002 por ativo — POR-05.3) ─
        if not broken:
            for ticker in tickers:
                i = calendar.bar_index_at(ticker, u)
                if i is None:
                    continue
                series_x = series[ticker]
                bar = BarSlice(
                    date=series_x.dates[i],
                    open=float(series_x.open[i]),
                    high=float(series_x.high[i]),
                    low=float(series_x.low[i]),
                    close=float(series_x.close[i]),
                )
                # Saída pendente (EXIT da barra anterior de X): vende ao open.
                if ticker in exit_pending:
                    decision = exit_pending.pop(ticker)
                    if ticker in portfolio.positions:
                        broker.sell(
                            portfolio,
                            ticker=ticker,
                            price=float(series_x.open[i]),
                            execution_date=bar.date,
                            decision_date=decision,
                            origin=TradeOrigin.MARKET,
                        )
                    # EXIT sem posição (Q2) — consumido e logado pelo broker.
                # Cobertura pendente (EXIT_SHORT da barra anterior de X): compra
                # ao open (2b, T08a) — se a posição já foi coberta por outro
                # mecanismo (buy-stop, margem), consumida (Q2 simétrico).
                if ticker in cover_pending:
                    decision = cover_pending.pop(ticker)
                    pos = portfolio.positions.get(ticker)
                    if pos is not None and pos.quantity < 0:
                        broker.cover(
                            portfolio,
                            ticker=ticker,
                            price=float(series_x.open[i]),
                            execution_date=bar.date,
                            decision_date=decision,
                            origin=TradeOrigin.MARKET,
                        )
                filled = broker.execute_pending(
                    store=portfolio.pending,
                    ticker=ticker,
                    bar=bar,
                    portfolio=portfolio,
                    cost_model=cost_model,
                    slippage=slippage_model,
                    adv=adv(series_x, i),
                    counters=counters,
                )
                # MET-05 (T16): 1 trade de venda por stop disparado (origin=STOP,
                # incluindo o stop do bracket ambíguo — T09) e 1 trade ambíguo por
                # ocorrência (ADR-0007/D2).
                counters.stops_triggered += sum(1 for t in filled if t.origin == TradeOrigin.STOP)
                counters.intrabar_ambiguities += sum(1 for t in filled if t.ambiguous)
            portfolio.check_invariants(n)

        # ── 2. MARCAR a mercado pelo último close conhecido (POR-02.2) ──────
        close_by_ticker: dict[str, float] = {}
        for ticker in tickers:
            idx = calendar.bar_index_at(ticker, u)
            if idx is None:
                idx = calendar.last_known_index_at(ticker, u)
            if idx is not None:
                close_by_ticker[ticker] = float(series[ticker].close[idx])
        portfolio.market_to_market(close_by_ticker)
        equity_curve.append(portfolio.equity())
        portfolio.check_invariants(n)

        # ── 1b. REBALANCE (SIZ-03; só EqualWeightOpen; k mudou?) ────────────
        k_now = len(portfolio.positions)
        if (
            not broken
            and isinstance(sizer_model, EqualWeightOpen)
            and k_now >= 1
            and k_now != k_before
        ):
            # Emenda T09/P0 — rebalance é LONG-ONLY por construção (D3): o
            # alvo 1/k é coerente só com posições positivas; gatilho de k com
            # short aberto é CONFIGURAÇÃO inválida ⇒ EngineError claro (não o
            # crash obscuro do rebalance_deviation_pp, peso fora de [0, 1]).
            shorts = sorted(t for t, p in portfolio.positions.items() if p.quantity < 0)
            if shorts:
                raise EngineError(
                    "run_backtest_multi: rebalance (EqualWeightOpen) com posição short "
                    f"aberta em {shorts} — rebalance é long-only por construção (D3); "
                    "use um sizer que não decide direção (ex.: FixedOneOverN)."
                )
            equity_now = portfolio.equity()
            target = 1.0 / k_now
            for ticker, position in sorted(portfolio.positions.items()):
                mark = portfolio.marks[ticker]
                weight = position.quantity * mark / equity_now
                if rebalance_deviation_pp(weight, k_now) >= sizer_model.threshold_pp:
                    target_qty = int(target * equity_now / mark)
                    delta = target_qty - position.quantity
                    if delta != 0:
                        intent_seq += 1
                        portfolio.pending.place(
                            BrokerPendingOrder(
                                ticker=ticker,
                                kind=OrderKind.MARKET,
                                side=Side.BUY if delta > 0 else Side.SELL,
                                limit=None,
                                stop=None,
                                qty=abs(delta),
                                decision_date=u_date,
                                intent_seq=intent_seq,
                                bracket=False,
                                rebalance=True,
                            )
                        )

        # ── 3. DEBITAR BORROW FEE (2b, T08a — etapa própria, RF-SHT-03) ─────
        if not broken:
            for ticker, position in sorted(portfolio.positions.items()):
                if position.quantity < 0:
                    fee = borrow_model.daily_fee(position.quantity, portfolio.marks[ticker])
                    portfolio.cash -= fee  # fora do preço de execução (SLP-04.3)
                    borrow_fees += fee  # dono: o laço (§3.7); termo próprio (§6)

        # ── 4. CHECAR MARGEM (2b, T08a — equity < margem ⇒ plano; close não
        #    é erro — CA-01.3; a execução no open é da T08b) ─────────────────
        if not broken:
            equity_now = portfolio.equity()
            requirement = margin_requirement(portfolio.positions, portfolio.marks, margin_model)
            if equity_now < requirement:
                if not portfolio.positions:
                    # Fundo quebrado: sem posições e equity < 0 (requirement = 0).
                    # Congela: pendentes canceladas, intenções descartadas (CA-03.1).
                    broken = True
                    for t in tickers:
                        portfolio.pending.cancel_all(t)
                else:
                    plan = build_liquidation_plan(
                        portfolio.positions,
                        portfolio.marks,
                        margin_model,
                        equity_now,
                        u_date,
                        margin_seq,
                    )
                    margin_seq += len(plan)
                    for order in plan:
                        margin_plan[order.ticker] = order
                        # CA-02.2 — pendentes do ativo liquidado saem do book.
                        portfolio.pending.cancel_all(order.ticker)

        # ── 5. CONSULTAR (alfabético; MarketView do próprio ativo; se não
        #    congelado — intenções seguintes descartadas, CA-03.1) ──────────
        if not broken:
            for ticker in tickers:
                if ticker not in strategies:
                    continue
                i = calendar.bar_index_at(ticker, u)
                if i is None:
                    continue
                if i < warmup[ticker]:
                    continue
                intent = strategies[ticker].on_bar(MarketView(series[ticker], i))
                if intent is None:
                    continue
                is_last_bar = i == len(series[ticker]) - 1
                # `Signal` da Fase 1 É o enum (sem atributo `.signal`); o
                # `ConditionalIntent` carrega `.signal`. Dispatch por tipo.
                signal = intent if isinstance(intent, Signal) else intent.signal
                if signal is Signal.EXIT_SHORT:
                    # SHT-01.3 — nunca silêncio: EXIT_SHORT sem short é erro de
                    # programação da estratégia (design §3.8).
                    pos = portfolio.positions.get(ticker)
                    if pos is None or pos.quantity >= 0:
                        raise EngineError(
                            f"EXIT_SHORT sem posição short aberta em {ticker} (SHT-01.3)."
                        )
                    broker.cancel_all(portfolio.pending, ticker)
                    if is_last_bar:
                        pending_dead[ticker] += 1  # ENG-01.4 — sem próxima barra
                    else:
                        cover_pending[ticker] = u_date
                    continue
                if signal is Signal.EXIT:
                    broker.cancel_all(portfolio.pending, ticker)
                    if is_last_bar:
                        pending_dead[ticker] += 1  # ENG-01.4 — não há próxima barra p/ a saída
                    else:
                        exit_pending[ticker] = u_date
                    continue
                if is_last_bar:
                    pending_dead[ticker] += 1  # ENG-01.4 — intenção morre pendente
                    continue
                intent_seq += 1
                # Seed da primeira entrada com EqualWeightOpen (k = 0 ⇒ 1/k é
                # indefinido): a fração é a da política default, 1/N (decisão
                # T11a — documentada na docstring do laço).
                effective_sizer = (
                    FixedOneOverN(n)
                    if isinstance(sizer_model, EqualWeightOpen) and not portfolio.positions
                    else sizer_model
                )
                converted = broker.convert(
                    intent,
                    ticker,
                    SizingInputs(
                        equity=portfolio.equity(),
                        cash=portfolio.cash,
                        n=n,
                        positions={t: p.quantity for t, p in portfolio.positions.items()},
                        last_close=dict(portfolio.marks),
                    ),
                    effective_sizer,
                    adv(series[ticker], i),
                    cost_model,
                    cap,
                    decision_date=u_date,
                    intent_seq=intent_seq,
                    counters=counters,
                )
                if converted is not None:
                    broker.place(portfolio.pending, converted)

    # POR-02.3/RF-SHT-05 (T08b): posição ABERTA — long ou SHORT (qty < 0,
    # CA-05.1) — cuja série terminou antes do fim da união é travada: marcada
    # pelo último close (passo 2 já usa last_known até o fim), nunca liquidada
    # a preço inventado, reportada no resultado (determinístico: sorted).
    last_union_date = calendar.dates[-1]
    delisted = tuple(
        sorted(
            t for t in tickers if t in portfolio.positions and series[t].dates[-1] < last_union_date
        )
    )
    return BacktestResultMulti(
        dates=calendar.dates,
        equity_curve=equity_curve,
        portfolio=portfolio,
        initial_cash=initial_cash,
        n=n,
        tickers=tickers,
        warmup=warmup,
        costs=cost_model,
        slippage=slippage_model,
        cap=cap,
        calendar=calendar,
        pending_dead=pending_dead,
        delisted=delisted,
        counters=counters,
        borrow_fees=borrow_fees,  # T08a: acumulado no débito do close
        broken_fund=broken,  # T08a: RF-MRG-03 CA-03.1
        margin=margin_model,
        borrow=borrow_model,
    )
