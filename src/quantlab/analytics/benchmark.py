"""Benchmark buy-and-hold — E2, design §5.1, RF-ANA-02.

Reaproveita `BacktestResult`/`EquityPoint` do engine em vez de inventar um
tipo paralelo: o benchmark é um backtest de uma estratégia só (compra e
segura), e as métricas de E1, o relatório de E3 e `reconciles()` do próprio
engine já sabem ler essa forma.
"""

from quantlab.engine.backtest import BacktestResult, EquityPoint
from quantlab.engine.broker import Broker, CostModel
from quantlab.engine.portfolio import Portfolio
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries

__all__ = ["buy_and_hold"]


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
