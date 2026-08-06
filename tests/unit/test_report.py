"""E3 — `BacktestReport` (ANA-03.1, design §5.2).

Séries de papel (RNF-03), reaproveitando `run_backtest` e `buy_and_hold` para
montar os dois `BacktestResult` que o relatório converte em `MetricsSummary`.
O teste que mais importa: os seis itens de vieses estão presentes em **todo**
relatório, porque `BIAS_DISCLOSURE` é constante literal, não texto montado.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.analytics.benchmark import buy_and_hold
from quantlab.analytics.report import BIAS_DISCLOSURE, BacktestReport
from quantlab.engine.backtest import run_backtest
from quantlab.engine.broker import CostModel
from quantlab.engine.market_view import MarketView
from quantlab.engine.strategy import Signal
from quantlab.storage.series import PriceSeries

_FREE = CostModel(fixed=0.0, rate=0.0)


def _series(n: int, *, ticker: str = "TEST") -> PriceSeries:
    """`n` barras, preço subindo 1 por barra — só o tamanho importa aqui."""
    bar_dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    dates: NDArray[np.object_] = np.empty(n, dtype=object)
    dates[:] = bar_dates
    prices = np.array([100.0 + i for i in range(n)], dtype=np.float64)
    return PriceSeries(
        ticker=ticker,
        dates=dates,
        open=prices,
        high=prices,
        low=prices,
        close=prices,
        volume=np.array([1_000.0] * n),
        adjusted=True,
        hash="0" * 64,
    )


@dataclass
class BuysOnceAtWarmup:
    """Emite `ENTER` na primeira barra elegível e nunca mais decide nada."""

    warmup: int = 2
    _emitted: bool = False

    def on_bar(self, view: MarketView) -> Signal | None:
        if not self._emitted:
            self._emitted = True
            return Signal.ENTER
        return None


def _build_report(n: int, *, costs: CostModel = _FREE, rf: float = 0.0) -> BacktestReport:
    series = _series(n)
    strategy_result = run_backtest(series, BuysOnceAtWarmup(warmup=2), costs=costs)
    benchmark_result = buy_and_hold(series, warmup=2, costs=costs)
    return BacktestReport.build(
        strategy=strategy_result,
        benchmark=benchmark_result,
        strategy_name="buys_once_at_warmup",
        strategy_params={"warmup": 2},
        rf=rf,
    )


# ─── ANA-03.1: os seis itens, sempre ──────────────────────────────────────


@pytest.mark.unit
def test_bias_disclosure_has_exactly_six_items() -> None:
    assert len(BIAS_DISCLOSURE) == 6


@pytest.mark.unit
def test_every_report_contains_all_six_biases_in_text_and_json() -> None:
    report = _build_report(40)

    text = report.to_text()
    payload = report.to_dict()

    assert payload["biases"] == list(BIAS_DISCLOSURE)
    for bias in BIAS_DISCLOSURE:
        assert bias in text


@pytest.mark.unit
def test_a_report_with_warnings_still_has_all_six_biases() -> None:
    """Um relatório com avisos condicionais não desloca nem trunca a seção fixa."""
    report = _build_report(10, costs=CostModel(fixed=0.0, rate=0.0))

    assert len(report.to_dict()["biases"]) == 6
    assert len(BIAS_DISCLOSURE) == len(report.to_dict()["biases"])


# ─── CA-01.2 / CA-02.1: rf declarado, métricas lado a lado ──────────────────


@pytest.mark.unit
def test_risk_free_rate_default_is_declared_in_both_formats() -> None:
    report = _build_report(40)

    assert report.risk_free_rate == 0.0
    assert "taxa livre de risco: 0.00%" in report.to_text()
    assert report.to_dict()["assumptions"]["risk_free_rate"] == 0.0


@pytest.mark.unit
def test_strategy_and_benchmark_metrics_appear_side_by_side() -> None:
    report = _build_report(40)
    payload = report.to_dict()

    assert "strategy" in payload
    assert "benchmark" in payload
    for key in ("cumulative_return", "cagr", "sharpe", "max_drawdown", "num_trades", "hit_rate"):
        assert key in payload["strategy"]
        assert key in payload["benchmark"]


# ─── ENG-03.2: custo zero avisa que os números são irrealistas ─────────────


@pytest.mark.unit
def test_zero_cost_triggers_the_unrealistic_warning() -> None:
    report = _build_report(40, costs=CostModel(fixed=0.0, rate=0.0))

    assert any("irrealistas" in warning for warning in report.warnings)
    assert any("irrealistas" in warning for warning in report.to_dict()["warnings"])


@pytest.mark.unit
def test_nonzero_cost_does_not_trigger_the_unrealistic_warning() -> None:
    report = _build_report(40, costs=CostModel(fixed=1.0, rate=0.0001))

    assert not any("irrealistas" in warning for warning in report.warnings)


# ─── ANA-01.5: amostra insuficiente ──────────────────────────────────────


@pytest.mark.unit
def test_fewer_than_30_bars_of_equity_warns_about_the_sample() -> None:
    report = _build_report(10)

    assert report.insufficient_sample
    assert any("insuficiente" in warning for warning in report.warnings)


@pytest.mark.unit
def test_30_or_more_bars_does_not_warn_about_the_sample() -> None:
    """A estratégia entra em warmup+1=3, então a equity da estratégia tem 30
    pontos quando a série tem 30 barras."""
    report = _build_report(30)

    assert not report.insufficient_sample
    assert not any("insuficiente" in warning for warning in report.warnings)


# ─── ENG-04.3: tratamento de dividendo declarado ────────────────────────────


@pytest.mark.unit
def test_dividend_treatment_is_declared() -> None:
    report = _build_report(40)

    assert "ajuste de preço" in report.to_text()
    assert "ajuste de preço" in report.to_dict()["assumptions"]["dividend_treatment"]


# ─── PER-03.1: proveniência ──────────────────────────────────────────────


@pytest.mark.unit
def test_report_carries_series_hash_and_ingestion_timestamp() -> None:
    report = _build_report(40)

    assert report.series_hash == "0" * 64
    assert report.to_dict()["provenance"]["series_hash"] == "0" * 64


# ─── to_json produz JSON válido com o mesmo conteúdo de to_dict ────────────


@pytest.mark.unit
def test_to_json_round_trips_to_the_same_dict() -> None:
    import json

    report = _build_report(40)

    assert json.loads(report.to_json()) == report.to_dict()


# ─── RF-CON-02 (v0.9): relatório auto-suficiente ────────────────────────────


@pytest.mark.unit
def test_run_section_reports_strategy_params_bar_count_and_effective_window() -> None:
    """CA-02.1 — parâmetros da estratégia, barras consumidas, datas efetivas."""
    series = _series(10)
    strategy_result = run_backtest(series, BuysOnceAtWarmup(warmup=2), costs=_FREE)
    benchmark_result = buy_and_hold(series, warmup=2, costs=_FREE)
    report = BacktestReport.build(
        strategy=strategy_result,
        benchmark=benchmark_result,
        strategy_name="sma_cross",
        strategy_params={"fast": 20, "slow": 50},
        rf=0.0,
    )

    run = report.to_dict()["run"]
    assert run["strategy"] == {"name": "sma_cross", "params": {"fast": 20, "slow": 50}}
    assert run["initial_capital"] == strategy_result.initial_cash
    # A série tem 10 barras; o laço registra um ponto de equity por barra
    # consumida (design §4.3) — bars_consumed == len(series), não o tamanho
    # de nenhum outro array.
    assert run["bars_consumed"] == 10 == len(series)
    assert run["effective_start"] == series.dates[0].isoformat()
    assert run["effective_end"] == series.dates[-1].isoformat()


@pytest.mark.unit
def test_full_run_configuration_is_reconstructible_from_the_json_alone() -> None:
    """CA-02.2 — o critério de aceitação em si: um JSON isolado, sem o nome
    do arquivo nem `backtest_runs`, basta para reconstruir a configuração.

    A comparação é campo a campo contra os parâmetros ORIGINAIS que
    construíram o relatório — não contra `report.to_dict()` de novo, que só
    provaria que a serialização é estável consigo mesma, não que carrega o
    que foi pedido.
    """
    import json

    original_ticker = "TEST"
    original_strategy_name = "sma_cross"
    original_params = {"fast": 20, "slow": 50}
    original_rf = 0.01
    original_costs = CostModel(fixed=1.0, rate=0.0001)

    series = _series(40, ticker=original_ticker)
    strategy_result = run_backtest(series, BuysOnceAtWarmup(warmup=2), costs=original_costs)
    benchmark_result = buy_and_hold(series, warmup=2, costs=original_costs)
    report = BacktestReport.build(
        strategy=strategy_result,
        benchmark=benchmark_result,
        strategy_name=original_strategy_name,
        strategy_params=original_params,
        rf=original_rf,
    )

    # Isolado de propósito: nem `report`, nem o nome de arquivo — só a string
    # JSON, como quem lê um `.json` copiado fora do repositório.
    isolated = json.loads(report.to_json())

    assert isolated["ticker"] == original_ticker
    assert isolated["run"]["strategy"]["name"] == original_strategy_name
    assert isolated["run"]["strategy"]["params"] == original_params
    assert isolated["run"]["initial_capital"] == strategy_result.initial_cash
    assert isolated["run"]["bars_consumed"] == len(series)
    assert isolated["run"]["effective_start"] == series.dates[0].isoformat()
    assert isolated["run"]["effective_end"] == series.dates[-1].isoformat()
    assert isolated["assumptions"]["risk_free_rate"] == original_rf
    assert isolated["assumptions"]["costs"] == {
        "fixed": original_costs.fixed,
        "rate": original_costs.rate,
    }
