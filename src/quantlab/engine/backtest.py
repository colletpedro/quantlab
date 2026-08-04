"""Laço de barras — C5, design §4.3. **A parte mais fácil de errar da fase.**

É aqui que ADR-0002 vira código. A ordem das três operações dentro de cada
barra não é arbitrária, e uma inversão em refatoração futura reintroduz
lookahead sem que nada estoure — o teste de ENG-01.2 é o que quebra.

Nenhuma dependência de banco: recebe uma `PriceSeries` já materializada
(design §2). É o que permite testar o engine inteiro com séries de papel
(RNF-03).
"""

import math
from dataclasses import dataclass, field
from datetime import date

from quantlab.engine.broker import Broker, CostModel
from quantlab.engine.market_view import MarketView
from quantlab.engine.portfolio import Portfolio, Trade
from quantlab.engine.strategy import Signal, Strategy
from quantlab.exceptions import EngineError
from quantlab.logging import get_logger
from quantlab.storage.series import PriceSeries

__all__ = ["BacktestResult", "EquityPoint", "PendingOrder", "run_backtest"]

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

    A sequência **não é arbitrária**, e cada passo está onde está por uma
    razão que a inversão quebra:

    - **Executar antes de marcar** garante que a equity de `i` reflita a
      posição real ao fim de `i`. Marcar antes deixaria a equity um dia
      atrasada em toda barra com execução.
    - **Consultar por último** garante que nenhuma decisão de `i` seja
      executada em `i`. É literalmente ADR-0002: consultar antes de executar
      permitiria a ordem da barra corrente ser preenchida na barra corrente,
      ao preço que a decisão já conhece.

    Uma inversão aqui não estoura nada — produz um backtest melhor e falso.
    O que quebra é o teste de ENG-01.2 (mutação de barras futuras), em
    `tests/unit/test_backtest.py`, que é o critério de aceitação da fase.
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
