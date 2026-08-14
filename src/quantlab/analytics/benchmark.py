"""Benchmark buy-and-hold — E2, design §5.1/§7, RF-ANA-02 + RF-MET-02 (Fase 2a).

Reaproveita `BacktestResult`/`EquityPoint` do engine em vez de inventar um
tipo paralelo: o benchmark é um backtest de uma estratégia só (compra e
segura), e as métricas de E1, o relatório de E3 e `reconciles()` do próprio
engine já sabem ler essa forma.

O multi-ativo (`buy_and_hold_multi`, RF-MET-02/S6) HERDA as regras de
entrada por construção: roda o `run_backtest_multi` com uma estratégia de
papel buy-and-hold e o sizer `FixedOneOverN` — custos, cap de participação,
slippage e o atendimento alfabético do caixa compartilhado vêm do mesmo
pipeline do broker que a estratégia usa, não de uma reimplementação.
"""

from quantlab.engine.backtest import (
    BacktestResult,
    BacktestResultMulti,
    EquityPoint,
    run_backtest_multi,
)
from quantlab.engine.broker import Broker, CostModel
from quantlab.engine.market_view import MarketView
from quantlab.engine.portfolio import Portfolio
from quantlab.engine.sizing import FixedOneOverN
from quantlab.engine.slippage import SlippageModel
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries

__all__ = ["buy_and_hold", "buy_and_hold_multi"]


def buy_and_hold(
    series: PriceSeries,
    *,
    warmup: int,
    initial_cash: float = 100_000.0,
    costs: CostModel | None = None,
) -> BacktestResult:
    """ANA-02.1/02.2 — compra ao `open[warmup + 1]`, mesmos custos de entrada.

    `warmup` é o `first_tradable_index` da estratégia comparada: ela só emite
    sinal a partir dali, logo só executaria a partir de `warmup + 1` (ADR-0002).
    Começar o benchmark na mesma barra é o que design §5.1 exige — comparar
    períodos diferentes mediria duas coisas diferentes e chamaria de uma só.

    A janela de equity resultante cobre `[warmup + 1, fim]`, exatamente o
    sufixo da equity curve de uma estratégia com o mesmo `warmup` rodando
    sobre a mesma série (`run_backtest(...).equity_curve[warmup + 1:]`).
    """
    if warmup < 0:
        raise EngineError(f"warmup negativo ({warmup}) para o benchmark.")

    entry_index = warmup + 1
    if entry_index >= len(series):
        raise EngineError(
            f"Série com {len(series)} barras não tem barra para o benchmark entrar "
            f"em open[{entry_index}] (warmup={warmup})."
        )

    broker = Broker(costs)
    portfolio = Portfolio(cash=initial_cash)
    ticker = series.ticker

    broker.buy(
        portfolio,
        ticker=ticker,
        price=float(series.open[entry_index]),
        execution_date=series.dates[entry_index],
        decision_date=series.dates[warmup],
    )

    equity_curve: list[EquityPoint] = []
    for index in range(entry_index, len(series)):
        close_price = float(series.close[index])
        position = portfolio.positions.get(ticker)
        position_value = position.market_value(close_price) if position is not None else 0.0
        equity_curve.append(
            EquityPoint(
                date=series.dates[index],
                equity=portfolio.cash + position_value,
                cash=portfolio.cash,
                position_value=position_value,
            )
        )

    final = equity_curve[-1]
    return BacktestResult(
        ticker=ticker,
        equity_curve=equity_curve,
        trades=portfolio.trades,
        initial_cash=initial_cash,
        final_equity=final.equity,
        warmup=warmup,
        costs=broker.costs,
        series_hash=series.hash,
        pending_order=None,
        last_ingested_at=series.last_ingested_at,
    )


class _BuyAndHold:
    """Estratégia de papel do benchmark multi (RF-MET-02/S6, T15).

    Emite `ENTER` na PRIMEIRA barra do próprio ativo (`warmup = 0`); a
    execução acontece ao open da PRÓXIMA barra do próprio ativo (ADR-0002 por
    ativo — a primeira barra NEGOCIÁVEL, MET-02.2/CA-02.2) e depois nunca
    mais emite nada: buy-and-hold puro, sem rebalance (MET-02.4). O estado de
    emissão é determinístico (uma emissão por instância, ordem fixa do laço).
    """

    def __init__(self) -> None:
        self._entered = False

    @property
    def warmup(self) -> int:
        return 0

    def on_bar(self, view: MarketView) -> Signal | None:
        if not self._entered:
            self._entered = True
            return Signal.ENTER
        return None


def buy_and_hold_multi(
    series: dict[str, PriceSeries],
    n: int,
    *,
    initial_cash: float = 100_000.0,
    costs: CostModel | None = None,
    slippage: SlippageModel | None = None,
    cap: float = 0.10,
) -> BacktestResultMulti:
    """Benchmark 1/N comprada-e-segurada sobre os N ativos do run (RF-MET-02).

    Compra cada ativo na primeira barra negociável do PRÓPRIO ativo (MET-02.2)
    e segura até o fim. HERDA TODAS as regras de entrada por construção
    (MET-02.1): em vez de reimplementar custos/slippage/cap, roda o
    `run_backtest_multi` com uma estratégia de papel buy-and-hold e o sizer
    `FixedOneOverN(n)` — o pipeline do broker (convert em 4 etapas, cap de
    participação, execução MARKET ao open com slippage, caixa compartilhado
    alfabético) é exatamente o da estratégia. Caixa ocioso não investido e
    SEM rebalanceamento (MET-02.4); deslistagem travada e reportada no
    resultado (MET-02.3). Mesmo `N` do run (P3): `n == len(series)` — o
    conjunto passado ao backtest É o universo.
    """
    if n < 1:
        raise EngineError(f"buy_and_hold_multi: N={n} < 1 — exige n ≥ 1 (P3/RF-MET-02).")
    if not series:
        raise EngineError("buy_and_hold_multi: universo vazio (RF-MET-02).")
    if n != len(series):
        raise EngineError(
            f"buy_and_hold_multi: N={n} mas o universo tem {len(series)} ativos — "
            "o N do run É o conjunto passado ao backtest (P3)."
        )
    strategies = {ticker: _BuyAndHold() for ticker in series}
    return run_backtest_multi(
        series,
        strategies,
        initial_cash=initial_cash,
        costs=costs,
        slippage=slippage,
        cap=cap,
        sizer=FixedOneOverN(n=n),
    )
