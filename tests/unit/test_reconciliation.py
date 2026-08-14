"""T13 — conciliação multi-ativo (POR-04.2/§6, RNF-08) e contribuição por ativo (MET-01.1).

A identidade de design §6 somada sobre os N ativos do run, com PnL realizado
BRUTO (custos no termo próprio), não-realizado pelo último close conhecido
(incluindo posição travada por deslistagem — POR-02.3) e `math.isclose`
(rel_tol=1e-9) — nunca igualdade exata. O erro que a definição bruta evita é a
dupla contagem de custos (PnL líquido no trade E no termo próprio).

Fixtures de papel com derivação auditável (RNF-03); nenhum banco.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.analytics.metrics import contribution_per_asset, reconcile_multi
from quantlab.engine.backtest import BacktestResultMulti, run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.market_view import MarketView
from quantlab.engine.slippage import FixedBps
from quantlab.engine.strategy import Signal
from quantlab.storage.series import PriceSeries

_FREE = CostModel(fixed=0.0, rate=0.0)
_COSTED = CostModel(fixed=1.0, rate=1e-4)
_NO_SLIP = FixedBps(bps=0.0)
_D0 = date(2024, 1, 1)


def _dates(n: int) -> list[date]:
    return [_D0 + timedelta(days=i) for i in range(n)]


def _series(prices: list[float], *, ticker: str, n_bars: int | None = None) -> PriceSeries:
    """Série de papel: open = close = high = low = `prices`; `n_bars` opcional
    para trunca (deslistagem)."""
    values = list(prices)
    if n_bars is not None:
        values = values[:n_bars]
    bar_dates = _dates(len(values))
    date_array: NDArray[np.object_] = np.empty(len(bar_dates), dtype=object)
    date_array[:] = bar_dates
    array = np.array(values, dtype=np.float64)
    return PriceSeries(
        ticker=ticker,
        dates=date_array,
        open=array,
        high=array,
        low=array,
        close=array,
        volume=np.array([1_000.0] * len(values)),
        adjusted=True,
        hash="0" * 64,
    )


@dataclass
class ScriptedStrategy:
    """Emite sinais em índices fixos — laço determinístico e legível."""

    script: dict[int, Signal]
    warmup: int = 0

    def on_bar(self, view: MarketView) -> Signal | None:
        return self.script.get(view.i)


# ─── Fixture de 20 ativos: round trips, abertas, deslistado e nunca-negociado ─


def _run_20_assets(*, costs: CostModel) -> BacktestResultMulti:
    """20 ativos sintéticos: 10 round trips (realizado), 8 abertas
    (não-realizado), 1 deslistado com posição aberta (travada — POR-02.3) e 1
    NUNCA-NEGOCIADO (série vazia — R2/SIZ-02.4, conta no N, contribui zero)."""
    tickers = [f"AAA{i:02d}" for i in range(20)]
    series: dict[str, PriceSeries] = {}
    strategies: dict[str, ScriptedStrategy] = {}
    for i, ticker in enumerate(tickers):
        base = 10.0 + i  # preços CRESCENTES dentro de cada série (PnL > 0 honesto)
        prices = [base + j for j in range(6)]
        if i == 19:  # nunca-negociado: série vazia, sem estratégia
            series[ticker] = _series([], ticker=ticker)
            continue
        if i == 18:  # deslistado: série termina em 4 barras (o run vai a 6)
            series[ticker] = _series(prices, ticker=ticker, n_bars=4)
        else:
            series[ticker] = _series(prices, ticker=ticker)
        if i < 10:  # round trip: realizado
            strategies[ticker] = ScriptedStrategy({0: Signal.ENTER, 3: Signal.EXIT})
        else:  # aberta no fim: não-realizado (inclui o deslistado, i == 18)
            strategies[ticker] = ScriptedStrategy({0: Signal.ENTER})
    return run_backtest_multi(
        series,
        strategies,
        costs=costs,
        slippage=_NO_SLIP,
        initial_cash=100_000.0,
    )


# ─── Identidade multi-ativo (CA-04.2) ────────────────────────────────────────


@pytest.mark.unit
def test_reconciliation_multi_asset_20_assets() -> None:
    """CA-04.2/§6 — a identidade fecha a 1e-9 no run de 20 ativos, incluindo
    o deslistado (não-realizado pelo último close — travada) e o nunca-
    negociado (contribui zero, sem buraco — R2)."""
    result = _run_20_assets(costs=_COSTED)

    report = reconcile_multi(result)

    assert report.reconciles is True
    assert report.initial_equity == pytest.approx(100_000.0)
    assert len(result.portfolio.trades) == 19  # 10 round trips + 9 abertas (AAA10..AAA18)
    assert report.realized_pnl > 0.0  # round trips com PnL positivo (preços sobem)
    assert report.unrealized_pnl > 0.0  # posições abertas marcadas acima do entry
    assert report.total_costs > 0.0  # custos materiais
    assert result.delisted == ("AAA18",)  # a travada entra no não-realizado


@pytest.mark.unit
def test_contributions_per_asset_reconcile_with_total_pnl() -> None:
    """MET-01.1/CA-01.1 — a soma das contribuições por ativo concilia com o
    PnL total (a identidade de §6, fatiada por ticker)."""
    result = _run_20_assets(costs=_COSTED)
    report = reconcile_multi(result)

    contributions = contribution_per_asset(result)

    assert sorted(contributions) == sorted(result.tickers)  # TODOS os N ativos
    total = sum(contributions.values())
    assert math.isclose(
        total,
        report.realized_pnl + report.unrealized_pnl - report.total_costs,
        rel_tol=1e-9,
    )
    assert math.isclose(total, report.final_equity - report.initial_equity, rel_tol=1e-9)
    # O deslistado contribui pelo não-realizado do último close conhecido.
    assert contributions["AAA18"] > 0.0


@pytest.mark.unit
def test_never_traded_asset_contributes_zero_and_reconciles() -> None:
    """SIZ-02.4/R2 — o ativo sem nenhuma barra conta no N, nunca recebe alvo,
    contribui ZERO e a conciliação fecha sem buraco."""
    result = _run_20_assets(costs=_FREE)

    contributions = contribution_per_asset(result)
    report = reconcile_multi(result)

    assert "AAA19" in contributions
    assert contributions["AAA19"] == 0.0
    assert result.tickers == tuple(sorted(result.tickers))  # N inclui o nunca-negociado
    assert report.reconciles is True


# ─── O erro da dupla contagem de custos (§4.6) ───────────────────────────────


@pytest.mark.unit
def test_reconciliation_uses_gross_realized_not_net() -> None:
    """§4.6 — a definição BRUTA é o que evita a dupla contagem: um PnL líquido
    no trade E no termo próprio desfecharia a identidade por 2 x custos."""
    series = {"A": _series([10.0, 10.0, 10.0, 12.0, 12.0, 12.0], ticker="A")}
    result = run_backtest_multi(
        series,
        {"A": ScriptedStrategy({0: Signal.ENTER, 3: Signal.EXIT})},
        costs=_COSTED,
        slippage=_NO_SLIP,
        initial_cash=100_000.0,
    )

    report = reconcile_multi(result)
    trade = result.portfolio.trades[0]

    assert report.reconciles is True
    # Realizado é BRUTO: (saída - entrada) x qty, custos à parte.
    assert report.realized_pnl == pytest.approx(trade.realized_pnl)
    assert report.total_costs == pytest.approx(trade.entry_cost + trade.exit_cost)
    assert report.unrealized_pnl == pytest.approx(0.0)  # round trip completo
    # Se o realizado fosse líquido, a identidade desfecharia por 2 x custos.
    net_realized = trade.realized_pnl - trade.total_cost
    assert not math.isclose(
        report.final_equity - report.initial_equity,
        net_realized + report.unrealized_pnl - report.total_costs,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )
