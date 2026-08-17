"""E2E (T13) — run long+short de 20 ativos com margem (DoD 2b).

Hermético por convenção do conftest (nenhum teste toca o banco configurado
em `QUANTLAB_MONGO_DB`; todos usam o banco descartável): os dados são
**sintéticos determinísticos** (RNF-03, gerador fixado por seed), gravados
no banco descartável via `upsert_bars` e lidos pelo mesmo `get_series` da
produção — o run passa pelo stack real (storage → engine → analytics) com 20
ativos, sem depender de ingestão prévia (o job de integração do CI sobe um
Mongo fresco, sem dados).

Fecha os itens do Definition of Done v0.2 (§10) sobre um run de 20 ativos:

- **Run long+short com margem** — a estratégia `SmaCrossLongShort` (T13)
  abre shorts de verdade: o teste exige ao menos um trade com `qty < 0`
  (SHT-01.2 — alvo NEGATIVO);
- **Conciliação CA-04.2 estendida (RF-SHT-04)** — a identidade de §6 fecha
  com `math.isclose(rel_tol=1e-9)` num run com `qty` negativa, e os borrow
  fees (RF-SHT-03) entram no termo próprio (`total_borrow_fees` > 0 e fora
  de `total_costs`);
- **Determinismo (RNF-01)** — dois runs idênticos produzem a mesma equity
  curve, os mesmos trades e os mesmos contadores de mecanismo (incluindo
  `margin_calls` — a margem fator 1.0 com o flip sempre-no-mercado exerce o
  caminho de liquidação forçada sem fixture especial);
- **Benchmark 1/N long-only (MET-05/CA-05.2)** — mesmo N do run e
  `benchmark_never_shorts`: nenhum trade do benchmark tem `qty < 0`.

O run REAL de 20 ativos (2015-01-02 a 2026-08-05, base corrigida) foi
verificado e persistido em `results/fase_2b_run_20_ativos_long_short.json`
(`scripts/e2e_run_2b.py`). Este teste automatiza a guarda dos invariantes no
CI — os tickers do universo servem só de rótulos, os dados são de papel.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from quantlab.analytics.benchmark import buy_and_hold_multi
from quantlab.analytics.metrics import reconcile_multi
from quantlab.config import Settings, get_settings
from quantlab.engine.backtest import BacktestResultMulti, run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.margin import BorrowFeeModel, MarginModel
from quantlab.engine.sizing import FixedOneOverN
from quantlab.engine.slippage import FixedBps
from quantlab.storage.client import MongoDatabase
from quantlab.storage.models import Bar
from quantlab.storage.repository import MongoRepository
from quantlab.storage.series import PriceSeries
from quantlab.strategies.sma_cross_long_short import SmaCrossLongShort
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


def _run_long_short_once(
    settings: Settings,
    tickers: list[str],
    series: dict[str, PriceSeries],
) -> BacktestResultMulti:
    strategies = {ticker: SmaCrossLongShort(fast=_FAST, slow=_SLOW) for ticker in tickers}
    return run_backtest_multi(
        series,
        strategies,
        initial_cash=settings.initial_capital,
        costs=CostModel(),
        slippage=FixedBps(bps=1.0),
        cap=0.10,
        sizer=FixedOneOverN(n=len(tickers)),
        margin=MarginModel(),
        borrow=BorrowFeeModel(),
    )


@pytest.mark.integration
def test_long_short_run_is_deterministic_reconciles_and_shorts(mongo_db: MongoDatabase) -> None:
    """DoD 2b: determinismo (RNF-01), conciliação CA-04.2 com qty<0 + borrow
    fees no termo próprio, e shorts de verdade num run de 20 ativos (hermético)."""
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

    run1 = _run_long_short_once(settings, tickers, series)
    run2 = _run_long_short_once(settings, tickers, series)

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

    # SHT-01.2 (T13) — o run abriu shorts de verdade: ao menos um trade qty < 0.
    assert any(t.quantity < 0 for t in run1.portfolio.trades), (
        "o run long+short do DoD precisa ter shorts — SmaCrossLongShort não abriu nenhum"
    )

    # CA-04.2 estendida (RF-SHT-04) — identidade fecha com qty negativa e os
    # borrow fees no termo próprio (RF-SHT-03 CA-03.3: nunca dentro de custos).
    reconciliation = reconcile_multi(run1)
    assert reconciliation.reconciles, (
        f"conciliação não fechou: final {reconciliation.final_equity} "
        f"vs inicial {reconciliation.initial_equity} + realizado "
        f"{reconciliation.realized_pnl} + não-realizado "
        f"{reconciliation.unrealized_pnl} - custos {reconciliation.total_costs} "
        f"- borrow {reconciliation.total_borrow_fees}"
    )
    assert run1.borrow_fees > 0, "shorts abertos por anos deveriam acumular borrow fee"
    assert reconciliation.total_borrow_fees == pytest.approx(run1.borrow_fees)

    # MRG-01 CA-01.4 — a margem foi exercida: liquidação forçada contada no
    # mecanismo (o flip sempre-no-mercado com fator 1.0 gera chamadas reais).
    assert run1.counters.margin_calls > 0, (
        "esperado pelo menos um MARGIN_CALL com o flip sempre-no-mercado e fator 1.0"
    )

    # Benchmark 1/N long-only (MET-05/CA-05.2) — mesmo N do run e NUNCA short.
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
    assert all(t.quantity > 0 for t in benchmark.portfolio.trades), (
        "o benchmark 1/N é long-only por construção — nunca short (CA-05.2)"
    )
