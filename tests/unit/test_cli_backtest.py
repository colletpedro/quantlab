"""F1 — lógica de `backtest` (RF-CLI-02), sem Typer nem Mongo.

`run_backtest_flow` é a função que `cli.backtest` delega para depois de
resolver argumentos de CLI e conectar dependências reais — testá-la direto,
com `FakeBacktestRepository`, cobre CA-02.1/02.2 sem precisar de `CliRunner`
nem de banco.
"""

from datetime import date, timedelta

import numpy as np
import pytest
import typer
from numpy.typing import NDArray

from quantlab.cli import (
    _build_run_document,
    _parse_optional_date,
    run_backtest_flow,
)
from quantlab.config import Settings
from quantlab.exceptions import DataError
from quantlab.storage.series import PriceSeries
from tests.support import FakeBacktestRepository

#: Mesma fixture de D1: fast=2, slow=3, cruzamento p/ cima em i=3, p/ baixo em i=5.
_CLOSES = [10.0, 10.0, 10.0, 20.0, 30.0, 5.0, 5.0]
_OPENS = [9.0, 9.0, 9.0, 19.0, 29.0, 4.0, 4.0]


def _series(ticker: str = "AAPL") -> PriceSeries:
    bar_dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(len(_CLOSES))]
    dates: NDArray[np.object_] = np.empty(len(bar_dates), dtype=object)
    dates[:] = bar_dates
    return PriceSeries(
        ticker=ticker,
        dates=dates,
        open=np.array(_OPENS, dtype=np.float64),
        high=np.array(_CLOSES, dtype=np.float64),
        low=np.array(_OPENS, dtype=np.float64),
        close=np.array(_CLOSES, dtype=np.float64),
        volume=np.array([1_000.0] * len(_CLOSES)),
        adjusted=True,
        hash="0" * 64,
        last_ingested_at="2024-01-08T00:00:00+00:00",
    )


@pytest.mark.unit
def test_parse_optional_date_none_passes_through() -> None:
    assert _parse_optional_date(None, option="--to") is None


@pytest.mark.unit
def test_parse_optional_date_parses_when_given() -> None:
    assert _parse_optional_date("2024-01-02", option="--to") == date(2024, 1, 2)


@pytest.mark.unit
def test_run_backtest_flow_end_to_end_with_fakes(settings: Settings) -> None:
    repository = FakeBacktestRepository(series_by_ticker={"AAPL": _series()})

    outcome = run_backtest_flow(
        strategy_name="sma_cross",
        ticker="aapl",
        from_date="2024-01-01",
        to_date=None,
        fast=2,
        slow=3,
        settings=settings,
        repository=repository,
    )

    assert outcome.run_id == repository.next_run_id
    assert len(repository.saved_runs) == 1
    assert len(outcome.strategy_result.trades) == 1
    assert outcome.report.ticker == "AAPL"
    # CA-02.1 — as mesmas métricas aparecem lado a lado para o benchmark.
    assert outcome.benchmark_result.trades


@pytest.mark.unit
def test_run_backtest_flow_uppercases_the_ticker(settings: Settings) -> None:
    repository = FakeBacktestRepository(series_by_ticker={"AAPL": _series()})

    outcome = run_backtest_flow(
        strategy_name="sma_cross",
        ticker="aapl",
        from_date="2024-01-01",
        to_date=None,
        fast=2,
        slow=3,
        settings=settings,
        repository=repository,
    )

    assert repository.saved_runs[0]["ticker"] == "AAPL"
    assert outcome.report.ticker == "AAPL"


@pytest.mark.unit
def test_run_backtest_flow_rejects_unknown_strategy(settings: Settings) -> None:
    repository = FakeBacktestRepository(series_by_ticker={"AAPL": _series()})

    with pytest.raises(typer.BadParameter, match="sma_cross"):
        run_backtest_flow(
            strategy_name="does_not_exist",
            ticker="AAPL",
            from_date="2024-01-01",
            to_date=None,
            fast=2,
            slow=3,
            settings=settings,
            repository=repository,
        )


@pytest.mark.unit
def test_run_backtest_flow_propagates_data_error_for_unknown_ticker(settings: Settings) -> None:
    """CA-02.2 — ticker sem dado ingerido falha com mensagem acionável."""
    repository = FakeBacktestRepository(series_by_ticker={})

    with pytest.raises(DataError, match="Nenhuma barra encontrada para MISSING"):
        run_backtest_flow(
            strategy_name="sma_cross",
            ticker="MISSING",
            from_date="2024-01-01",
            to_date=None,
            fast=2,
            slow=3,
            settings=settings,
            repository=repository,
        )


@pytest.mark.unit
def test_run_backtest_flow_rejects_malformed_date(settings: Settings) -> None:
    repository = FakeBacktestRepository(series_by_ticker={"AAPL": _series()})

    with pytest.raises(typer.BadParameter):
        run_backtest_flow(
            strategy_name="sma_cross",
            ticker="AAPL",
            from_date="not-a-date",
            to_date=None,
            fast=2,
            slow=3,
            settings=settings,
            repository=repository,
        )


@pytest.mark.unit
def test_saved_document_carries_trades_and_equity_curve_and_no_ingestion_run_id(
    settings: Settings,
) -> None:
    """design §3.5 (v0.7) — o documento não carrega `ingestion_run_id` (removido)."""
    repository = FakeBacktestRepository(series_by_ticker={"AAPL": _series()})

    run_backtest_flow(
        strategy_name="sma_cross",
        ticker="AAPL",
        from_date="2024-01-01",
        to_date=None,
        fast=2,
        slow=3,
        settings=settings,
        repository=repository,
    )

    document = repository.saved_runs[0]
    assert document["strategy"] == {"name": "sma_cross", "params": {"fast": 2, "slow": 3}}
    assert len(document["strategy_trades"]) == 1
    assert len(document["strategy_equity_curve"]) == len(_CLOSES)
    assert "ingestion_run_id" not in document
    assert document["report"]["provenance"]["series_hash"] == "0" * 64


@pytest.mark.unit
def test_build_run_document_records_costs_and_window() -> None:
    from quantlab.analytics.benchmark import buy_and_hold
    from quantlab.analytics.report import BacktestReport
    from quantlab.engine.backtest import run_backtest
    from quantlab.engine.broker import CostModel
    from quantlab.strategies.sma_cross import SmaCross

    series = _series()
    strategy = SmaCross(fast=2, slow=3)
    costs = CostModel(fixed=1.0, rate=0.0001)
    strategy_result = run_backtest(series, strategy, initial_cash=10_000.0, costs=costs)
    benchmark_result = buy_and_hold(
        series, warmup=strategy.warmup, initial_cash=10_000.0, costs=costs
    )
    report = BacktestReport.build(strategy=strategy_result, benchmark=benchmark_result, rf=0.0)

    document = _build_run_document(
        ticker="AAPL",
        strategy_name="sma_cross",
        strategy_params={"fast": 2, "slow": 3},
        start=date(2024, 1, 1),
        end=None,
        initial_cash=10_000.0,
        costs=costs,
        report=report,
        strategy_result=strategy_result,
        benchmark_result=benchmark_result,
    )

    from quantlab.storage.repository import to_bson_date

    assert document["costs"] == {"fixed": 1.0, "rate": 0.0001}
    assert document["window"] == {"start": to_bson_date(date(2024, 1, 1)), "end": None}
    assert document["initial_capital"] == 10_000.0
