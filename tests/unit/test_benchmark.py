"""E2 — Benchmark buy-and-hold alinhado (ANA-02.1, ANA-02.2, design §5.1).

Séries de papel (RNF-03). O teste que mais importa aqui não é o valor de uma
métrica — é que a janela de equity do benchmark seja *idêntica*, barra a
barra, ao sufixo comparável da janela da estratégia. Comparar períodos
diferentes invalidaria qualquer número que viesse depois.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.analytics.benchmark import buy_and_hold
from quantlab.engine.backtest import run_backtest
from quantlab.engine.broker import CostModel
from quantlab.engine.market_view import MarketView
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries

_FREE = CostModel(fixed=0.0, rate=0.0)


def _series(opens: list[float], closes: list[float]) -> PriceSeries:
    bar_dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(len(opens))]
    dates: NDArray[np.object_] = np.empty(len(bar_dates), dtype=object)
    dates[:] = bar_dates
    return PriceSeries(
        ticker="TEST",
        dates=dates,
        open=np.array(opens, dtype=np.float64),
        high=np.array(closes, dtype=np.float64),
        low=np.array(opens, dtype=np.float64),
        close=np.array(closes, dtype=np.float64),
        volume=np.array([1_000.0] * len(opens)),
        adjusted=True,
        hash="0" * 64,
    )


@dataclass
class NeverTrades:
    """Só serve para dar um `warmup` ao `run_backtest` de comparação."""

    warmup: int = 2

    def on_bar(self, view: MarketView) -> Signal | None:
        return None


# ─── ANA-02.1: entra em open[warmup + 1], custos de entrada aplicados ────────


@pytest.mark.unit
def test_buys_at_the_open_of_warmup_plus_one_with_entry_costs() -> None:
    """warmup=2: a primeira barra elegível para a estratégia é i=2, então o
    benchmark entra em open[3].

    open[3] = 50.0, custo fixo 1.0 (sem `rate`): quantidade máxima inteira
    resolve `q*50 + 1 <= 10_000` -> `q <= 199.98` -> `q = 199`.
    notional = 199*50 = 9_950.0; custo = 1.0; caixa final na entrada = 10_000
    - 9_950 - 1 = 49.0.
    """
    opens = [10.0, 10.0, 10.0, 50.0, 60.0]
    closes = [10.0, 10.0, 10.0, 55.0, 65.0]
    series = _series(opens, closes)

    result = buy_and_hold(
        series, warmup=2, initial_cash=10_000.0, costs=CostModel(fixed=1.0, rate=0.0)
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_date == series.dates[3]
    assert trade.entry_price == pytest.approx(50.0)
    assert trade.quantity == 199
    assert trade.entry_cost == pytest.approx(1.0)
    assert result.equity_curve[0].cash == pytest.approx(49.0)


@pytest.mark.unit
def test_holds_to_the_end_marked_at_each_close() -> None:
    """Sem custo: caixa 100, open[3]=50 -> q=2, caixa vira 0.

    close[3]=55 marca a posição em 2*55=110 (equity=110, caixa=0).
    close[4]=65 marca a posição em 2*65=130 (equity=130, caixa=0).
    """
    opens = [10.0, 10.0, 10.0, 50.0, 60.0]
    closes = [10.0, 10.0, 10.0, 55.0, 65.0]
    series = _series(opens, closes)

    result = buy_and_hold(series, warmup=2, initial_cash=100.0, costs=_FREE)

    assert len(result.equity_curve) == 2  # índices 3 e 4
    assert result.equity_curve[0].date == series.dates[3]
    assert result.equity_curve[0].equity == pytest.approx(110.0)
    assert result.equity_curve[1].date == series.dates[4]
    assert result.equity_curve[1].equity == pytest.approx(130.0)


# ─── ANA-02.2: mesma janela de equity que a estratégia comparada ────────────


@pytest.mark.unit
def test_shares_the_exact_equity_window_with_a_strategy_of_the_same_warmup() -> None:
    """A janela do benchmark é, barra a barra, o sufixo `[warmup+1:]` da
    estratégia comparada — não uma janela parecida, a mesma.
    """
    opens = [10.0, 11.0, 12.0, 50.0, 60.0, 70.0]
    closes = [10.0, 11.0, 12.0, 55.0, 65.0, 75.0]
    series = _series(opens, closes)
    warmup = 2

    strategy_result = run_backtest(series, NeverTrades(warmup=warmup), costs=_FREE)
    benchmark_result = buy_and_hold(series, warmup=warmup, costs=_FREE)

    strategy_window = strategy_result.equity_curve[warmup + 1 :]
    assert [point.date for point in strategy_window] == [
        point.date for point in benchmark_result.equity_curve
    ]
    assert len(strategy_window) == len(benchmark_result.equity_curve)


@pytest.mark.unit
def test_comparing_different_warmups_would_be_comparing_different_periods() -> None:
    """Não é o comportamento sob teste — é a premissa que o teste anterior prova
    valer só quando os `warmup`s coincidem. `warmup` diferente começa em outra
    barra, de propósito: veio de outra estratégia, não é um bug.
    """
    opens = [10.0, 11.0, 12.0, 50.0, 60.0, 70.0]
    closes = [10.0, 11.0, 12.0, 55.0, 65.0, 75.0]
    series = _series(opens, closes)

    benchmark_warmup_1 = buy_and_hold(series, warmup=1, costs=_FREE)
    benchmark_warmup_3 = buy_and_hold(series, warmup=3, costs=_FREE)

    assert benchmark_warmup_1.equity_curve[0].date != benchmark_warmup_3.equity_curve[0].date


# ─── bordas ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_no_bar_available_for_entry_raises() -> None:
    opens = [10.0, 11.0, 12.0]
    closes = [10.0, 11.0, 12.0]
    series = _series(opens, closes)

    with pytest.raises(EngineError, match="não tem barra"):
        buy_and_hold(series, warmup=2, costs=_FREE)


@pytest.mark.unit
def test_negative_warmup_raises() -> None:
    series = _series([10.0, 11.0], [10.0, 11.0])

    with pytest.raises(EngineError, match="warmup negativo"):
        buy_and_hold(series, warmup=-1, costs=_FREE)


@pytest.mark.unit
def test_result_reconciles() -> None:
    opens = [10.0, 11.0, 12.0, 50.0, 60.0]
    closes = [10.0, 11.0, 12.0, 55.0, 65.0]
    series = _series(opens, closes)

    result = buy_and_hold(series, warmup=2, initial_cash=10_000.0, costs=CostModel())

    assert result.reconciles()
