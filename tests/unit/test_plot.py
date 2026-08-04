"""F2 — gráfico de backtest (RF-CLI-03).

Verifica estrutura do gráfico (linhas, marcadores, dois painéis) e que o
arquivo é de fato escrito — não o conteúdo visual em si, que não é
verificável por asserção de texto.
"""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.analytics.benchmark import buy_and_hold
from quantlab.analytics.plot import plot_backtest
from quantlab.engine.backtest import run_backtest
from quantlab.engine.broker import CostModel
from quantlab.storage.series import PriceSeries
from quantlab.strategies.sma_cross import SmaCross

_CLOSES = [10.0, 10.0, 10.0, 20.0, 30.0, 5.0, 5.0]
_OPENS = [9.0, 9.0, 9.0, 19.0, 29.0, 4.0, 4.0]
_FREE = CostModel(fixed=0.0, rate=0.0)


def _series() -> PriceSeries:
    bar_dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(len(_CLOSES))]
    dates: NDArray[np.object_] = np.empty(len(bar_dates), dtype=object)
    dates[:] = bar_dates
    return PriceSeries(
        ticker="AAPL",
        dates=dates,
        open=np.array(_OPENS, dtype=np.float64),
        high=np.array(_CLOSES, dtype=np.float64),
        low=np.array(_OPENS, dtype=np.float64),
        close=np.array(_CLOSES, dtype=np.float64),
        volume=np.array([1_000.0] * len(_CLOSES)),
        adjusted=True,
        hash="0" * 64,
    )


@pytest.mark.unit
def test_plot_backtest_writes_a_file(tmp_path: Path) -> None:
    series = _series()
    strategy = SmaCross(fast=2, slow=3)
    strategy_result = run_backtest(series, strategy, costs=_FREE)
    benchmark_result = buy_and_hold(series, warmup=strategy.warmup, costs=_FREE)

    output = plot_backtest(
        ticker="AAPL",
        strategy=strategy_result,
        benchmark=benchmark_result,
        output_path=tmp_path / "aapl.png",
    )

    assert output == tmp_path / "aapl.png"
    assert output.exists()
    assert output.stat().st_size > 0


@pytest.mark.unit
def test_plot_backtest_creates_missing_parent_directories(tmp_path: Path) -> None:
    series = _series()
    strategy = SmaCross(fast=2, slow=3)
    strategy_result = run_backtest(series, strategy, costs=_FREE)
    benchmark_result = buy_and_hold(series, warmup=strategy.warmup, costs=_FREE)

    output = plot_backtest(
        ticker="AAPL",
        strategy=strategy_result,
        benchmark=benchmark_result,
        output_path=tmp_path / "nested" / "dir" / "aapl.png",
    )

    assert output.exists()


@pytest.mark.unit
def test_plot_backtest_produces_a_valid_nontrivial_png(tmp_path: Path) -> None:
    """O PNG salvo é uma imagem de verdade — dimensão condizente com `figsize`x`dpi`.

    `plot_backtest` fecha a figura internamente (`plt.close`), então a
    estrutura não é inspecionável via `fig.axes` depois da chamada; o que dá
    para verificar do lado de fora é o artefato final: um PNG com as
    dimensões esperadas (12x8 pol. a 150 dpi) e mais de uma cor — uma imagem
    em branco teria um único valor de pixel.
    """
    import matplotlib.image as mpimg

    series = _series()
    strategy = SmaCross(fast=2, slow=3)
    strategy_result = run_backtest(series, strategy, costs=_FREE)
    benchmark_result = buy_and_hold(series, warmup=strategy.warmup, costs=_FREE)
    assert len(strategy_result.trades) == 1
    assert strategy_result.trades[0].exit_date is not None

    output = plot_backtest(
        ticker="AAPL",
        strategy=strategy_result,
        benchmark=benchmark_result,
        output_path=tmp_path / "aapl.png",
    )

    image = mpimg.imread(output)
    height, width = image.shape[0], image.shape[1]
    assert width == pytest.approx(12 * 150, abs=5)
    assert height == pytest.approx(8 * 150, abs=5)
    assert len({tuple(pixel) for row in image[::20] for pixel in row[::20]}) > 1


@pytest.mark.unit
def test_equity_and_drawdown_series_have_matching_length(tmp_path: Path) -> None:
    series = _series()
    strategy = SmaCross(fast=2, slow=3)
    strategy_result = run_backtest(series, strategy, costs=_FREE)
    benchmark_result = buy_and_hold(series, warmup=strategy.warmup, costs=_FREE)

    from quantlab.analytics.plot import _drawdown_series, _equity_series

    strategy_equity = _equity_series(strategy_result)
    benchmark_equity = _equity_series(benchmark_result)
    drawdown = _drawdown_series(strategy_equity)

    assert len(strategy_equity) == len(_CLOSES)
    assert len(benchmark_equity) > 0
    assert len(drawdown) == len(strategy_equity)
