"""E2E (T18) — run de 20 ativos sobre o universo default (DoD v0.2).

Hermético por convenção do conftest ("nenhum teste toca o banco configurado
em `QUANTLAB_MONGO_DB`; todos usam o banco descartável"): os dados são
**sintéticos determinísticos** (RNF-03, gerador fixado por seed), gravados
no banco descartável via `upsert_bars` e lidos pelo mesmo `get_series` da
produção — o run passa pelo stack real (storage → engine → analytics) com
20 ativos, sem depender de ingestão prévia (o job de integração do CI sobe
um Mongo fresco, sem dados).

Fecha dois itens do Definition of Done sobre um run de 20 ativos:

- **Conciliação de CA-04.2 (RF-POR-04)** — a identidade de §6
  (`final - inicial ≡ Σ realizado bruto + Σ não-realizado - Σ custos`)
  fecha com `math.isclose(rel_tol=1e-9)`;
- **Determinismo (RNF-01)** — dois runs idênticos produzem a mesma equity
  curve, os mesmos trades e os mesmos contadores de mecanismo.

O run REAL de 20 ativos (2015-01-02 a 2026-08-05, base corrigida) foi
verificado e persistido em `results/fase_2a_run_20_ativos.json`
(`scripts/e2e_run_20.py`): conciliação fechando, determinismo confirmado,
RNF-04 0,73 s. Este teste automatiza a guarda dos invariantes no CI — os
tickers do universo servem só de rótulos, os dados são de papel.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from quantlab.analytics.benchmark import buy_and_hold_multi
from quantlab.analytics.metrics import reconcile_multi
from quantlab.config import Settings, get_settings
from quantlab.engine.backtest import BacktestResultMulti, run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.sizing import FixedOneOverN
from quantlab.engine.slippage import FixedBps
from quantlab.storage.client import MongoDatabase
from quantlab.storage.models import Bar
from quantlab.storage.repository import MongoRepository
from quantlab.storage.series import PriceSeries
from quantlab.strategies.sma_cross import SmaCross
from quantlab.universe import load_default_universe

_FROM = date(2015, 1, 1)
_FAST = 20
_SLOW = 50
_BARS_PER_YEAR = 252
_YEARS = 10


def _synthetic_bars(ticker: str, *, seed: int, n_bars: int) -> list[Bar]:
    """Barras sintéticas determinísticas (RNF-03/RNF-01).

    Caminhada aleatória com drift, gerador fixado por seed: mesma entrada =>
    mesmas barras, em qualquer execução e em qualquer máquina. OHLC colado
    ao caminho (ordens são a mercado no run — nenhuma regra depende de
    dentro da barra). `volume` constante alto: o cap de participação (10%
    do ADV) nunca corta, e o teste não testa o cap.
    """
    rng = np.random.default_rng(seed=seed)
    returns = rng.normal(loc=0.0002, scale=0.01, size=n_bars)
    closes = 100.0 * np.exp(np.cumsum(returns))
    return [
        Bar(
            ticker=ticker,
            date=_FROM + timedelta(days=i),
            open=float(closes[i]),
            high=float(closes[i]),
            low=float(closes[i]),
            close=float(closes[i]),
            volume=1_000_000,
        )
        for i in range(n_bars)
    ]


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
def test_multi_asset_run_is_deterministic_and_reconciles(mongo_db: MongoDatabase) -> None:
    """DoD: determinismo (RNF-01) e conciliação CA-04.2 num run de 20 ativos (hermético)."""
    settings = get_settings()
    tickers = load_default_universe(settings.universe_path)
    assert len(tickers) == 20, "o universo do run do DoD é o de 20 ativos (config/universe.yml)"

    repository = MongoRepository(mongo_db)
    n_bars = _YEARS * _BARS_PER_YEAR
    for index, ticker in enumerate(tickers):
        repository.upsert_bars(_synthetic_bars(ticker, seed=index + 1, n_bars=n_bars))

    series = {ticker: repository.get_series(ticker, start=_FROM) for ticker in tickers}
    assert len(series) == 20
    assert all(len(asset.dates) == n_bars for asset in series.values())

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

    # CA-04.2 — a identidade multi-ativo fecha (isclose 1e-9).
    reconciliation = reconcile_multi(run1)
    assert reconciliation.reconciles, (
        f"conciliação não fechou: final {reconciliation.final_equity} "
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
