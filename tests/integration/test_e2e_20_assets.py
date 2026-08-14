"""E2E (T18) — run real de 20 ativos x 10 anos sobre o universo do
`config/universe.yml` (DoD v0.2).

Fecha dois itens do Definition of Done sobre dados REAIS do repositório:

- **Conciliação de CA-04.2 (RF-POR-04) passa no run de 20 ativos** — a
  identidade de §6 (`final - inicial ≡ Σ realizado bruto + Σ não-realizado
  - Σ custos`) fecha com `math.isclose(rel_tol=1e-9)` no run real;
- **Determinismo (RNF-01)** — dois runs idênticos produzem a mesma equity
  curve, os mesmos trades e os mesmos contadores de mecanismo.

Marcado `integration` (exige MongoDB no ar com as 20 séries ingeridas —
`make up` + ingestão; RNF-06 mantém `make test` offline). O teste só LÊ o
banco: nenhuma escrita, nenhum banco descartável — os dados reais são
imutáveis durante a leitura.
"""

from datetime import date

import pytest

from quantlab.analytics.benchmark import buy_and_hold_multi
from quantlab.analytics.metrics import reconcile_multi
from quantlab.config import Settings, get_settings
from quantlab.engine.backtest import BacktestResultMulti, run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.sizing import FixedOneOverN
from quantlab.engine.slippage import FixedBps
from quantlab.storage.client import mongo_database
from quantlab.storage.repository import MongoRepository
from quantlab.storage.series import PriceSeries
from quantlab.strategies.sma_cross import SmaCross
from quantlab.universe import load_default_universe

_FROM = date(2015, 1, 1)
_FAST = 20
_SLOW = 50


def _run_once(
    settings: Settings,
    tickers: list[str],
    series: dict[str, PriceSeries],
) -> BacktestResultMulti:
    strategies = {ticker: SmaCross(fast=_FAST, slow=_SLOW) for ticker in tickers}
    return run_backtest_multi(
        series,
        strategies,
        initial_cash=settings.initial_capital,
        costs=CostModel(),
        slippage=FixedBps(bps=1.0),
        cap=0.10,
        sizer=FixedOneOverN(n=len(tickers)),
    )


@pytest.mark.integration
def test_multi_asset_run_is_deterministic_and_reconciles() -> None:
    """DoD: determinismo (RNF-01) e conciliação CA-04.2 no run real de 20 ativos."""
    settings = get_settings()
    tickers = load_default_universe(settings.universe_path)
    assert len(tickers) == 20, "o universo do run do DoD é o de 20 ativos (config/universe.yml)"

    with mongo_database(settings) as database:
        repository = MongoRepository(database)
        series = {ticker: repository.get_series(ticker, start=_FROM) for ticker in tickers}
    assert len(series) == 20

    run1 = _run_once(settings, tickers, series)
    run2 = _run_once(settings, tickers, series)

    # RNF-01 — determinismo: equity, trades e contadores idênticos.
    assert run1.equity_curve == run2.equity_curve
    trades1 = [
        (t.ticker, t.quantity, t.entry_price, t.exit_price, t.origin) for t in run1.portfolio.trades
    ]
    trades2 = [
        (t.ticker, t.quantity, t.entry_price, t.exit_price, t.origin) for t in run2.portfolio.trades
    ]
    assert trades1 == trades2
    assert run1.counters.to_dict() == run2.counters.to_dict()

    # CA-04.2 — a identidade multi-ativo fecha no run real (isclose 1e-9).
    reconciliation = reconcile_multi(run1)
    assert reconciliation.reconciles, (
        f"conciliação não fechou no run real: final {reconciliation.final_equity} "
        f"vs inicial {reconciliation.initial_equity} + realizado "
        f"{reconciliation.realized_pnl} + não-realizado "
        f"{reconciliation.unrealized_pnl} - custos {reconciliation.total_costs}"
    )

    # Benchmark 1/N no MESMO universo/N e com as MESMAS regras (P3/S6).
    benchmark = buy_and_hold_multi(
        series,
        n=len(tickers),
        initial_cash=settings.initial_capital,
        costs=CostModel(),
        slippage=FixedBps(bps=1.0),
        cap=0.10,
    )
    assert benchmark.n == run1.n
    assert benchmark.equity_curve  # janela não vazia — comparável (Fase 1 §5.1)
