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
from quantlab.engine.market_view import MarketView
from quantlab.engine.portfolio import Portfolio, Trade, TradeOrigin
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

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1] if self.equity_curve else self.initial_cash

    @property
    def n_bars(self) -> int:
        return len(self.dates)


def run_backtest_multi(
    series: dict[str, PriceSeries],
    strategies: Mapping[str, Strategy | ConditionalStrategy],
    *,
    initial_cash: float = 100_000.0,
    costs: CostModel | None = None,
    slippage: SlippageModel | None = None,
    cap: float = 0.10,
    sizer: Sizer | None = None,
) -> BacktestResultMulti:
    """Roda N estratégias (uma por ativo) sobre o calendário-união, barra a barra.

    ────────────────────────────────────────────────────────────────────────
    **INVARIANTE — a ordem das operações dentro de cada data-união `u`**
    (extensão da §4.3 da Fase 1, preservada por ativo):

      1. **Executar** as pendentes de X ao open da barra do PRÓPRIO ativo
         (ADR-0002 por ativo — POR-05.3), e a saída pendente de um EXIT da
         barra anterior de X (venda ao open, origin=MARKET);
      2. **Marcar a mercado** pelo último close conhecido (POR-02.2) e
         registrar a equity de `u`;
      1b. **Rebalance** (só se sizer == EqualWeightOpen): k mudou ⇒ eventos
         com limiar em pp (SIZ-03.3) para o próximo open do próprio ativo;
      3. **Consultar** as estratégias por ÚLTIMO (i ≥ warmup), MarketView
         só com barras do próprio ativo (POR-03.1/05.1).

    **Por que a ordem importa (Fase 1 §4.3, estendido):** executar antes de
    marcar garante que a equity de `u` reflete a posição real ao fim de `u`;
    executar antes de consultar garante que nenhuma decisão de `u` executa em
    `u` (ADR-0002 em código). Uma inversão em refatoração reintroduz lookahead
    e o teste de mutação ENG-01.2 (T12) quebra. Entre marcar e consultar a
    ordem é livre por ativo (consulta sem efeito colateral — ENG-05.2),
    travada por teste. As fases rodam em ordem alfabética por ativo
    (determinismo RNF-01 + caixa compartilhado POR-01.2).

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
    broker = Broker(cost_model)
    calendar = UnionCalendar.build(series)
    portfolio = Portfolio(cash=initial_cash)

    warmup: dict[str, int] = {t: strategies[t].warmup for t in tickers if t in strategies}
    pending_dead: dict[str, int] = {t: 0 for t in tickers}
    exit_pending: dict[str, date] = {}
    equity_curve: list[float] = []
    intent_seq = 0
    # MET-05/P6 (T16): contadores de mecanismo — stops/ambiguidades derivados
    # dos fills, não-atendidas por caixa contadas no broker (convert/execução).
    counters = MechanismCounters()

    for u in range(len(calendar.dates)):
        u_date = calendar.dates[u]
        k_before = len(portfolio.positions)

        # ── 1. EXECUTAR (alfabético; ADR-0002 por ativo — POR-05.3) ────────
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
        if isinstance(sizer_model, EqualWeightOpen) and k_now >= 1 and k_now != k_before:
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

        # ── 3. CONSULTAR (alfabético; MarketView do próprio ativo) ──────────
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

    # POR-02.3: posição aberta cuja série terminou antes do fim da união é
    # travada — marcada pelo último close (passo 2 já usa last_known até o
    # fim), nunca liquidada, reportada no resultado (determinístico: sorted).
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
    )
