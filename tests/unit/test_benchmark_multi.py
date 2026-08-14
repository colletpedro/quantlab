"""T15 — benchmark 1/N buy-and-hold multi-ativo (RF-MET-02/S6, design §7).

O benchmark HERDA as regras de entrada por construção: roda o
`run_backtest_multi` com uma estratégia de papel buy-and-hold + sizer
`FixedOneOverN` — custos, slippage, cap e o atendimento alfabético do caixa
compartilhado vêm do MESMO pipeline do broker da estratégia. Estes testes
provam a semântica externa (MET-02.1 a 02.4) com fixtures de papel e derivação
à mão (RNF-03): primeira barra negociável do próprio ativo, custos/slippage
aplicados, mesmo N do run (P3), caixa ocioso, sem rebalance, deslistagem
travada e reportada.
"""

from datetime import date, timedelta

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.analytics.benchmark import buy_and_hold_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.slippage import FixedBps
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries

_D0 = date(2024, 1, 1)

#: Custo material para os trades do benchmark: 1 USD + 1 bps de notional.
_COSTED = CostModel(fixed=1.0, rate=1e-4)


def _dates(n: int, start: int = 0) -> list[date]:
    return [_D0 + timedelta(days=start + i) for i in range(n)]


def _series(
    prices: list[float], *, ticker: str, start: int = 0, n_bars: int | None = None
) -> PriceSeries:
    """Série de papel: open = close = high = low = `prices`; `start` desloca
    o IPO (a série começa em `_D0 + start` dias); `n_bars` trunca (deslistagem)."""
    values = list(prices)
    if n_bars is not None:
        values = values[:n_bars]
    bar_dates = _dates(len(values), start=start)
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


# ─── MET-02.1/02.2: primeira barra negociável + regras de entrada aplicadas ──


@pytest.mark.unit
def test_benchmark_buys_at_first_tradable_bar_per_asset_with_entry_rules() -> None:
    """CA-02.1/02.2 — cada ativo é comprado na primeira barra NEGOCIÁVEL do
    próprio ativo (2ª barra: decisão na 1ª, execução ao open da próxima —
    ADR-0002), com custos e slippage aplicados, mesmo N do run (P3).

    A: preços planos 10, barras d1..d5. Decisão d1, execução ao open de d2:
    preço = 10 x 1.0001 = 10.001 (slippage de compra); alvo 1/2 x 100_000 =
    50_000 / ref 10 = 5_000 ações (adv indisponível na 1ª barra — janela de
    20 sem histórico — então o cap não corta; mesma herança da estratégia).
    Custo sobre o notional real de execução: max(1 + 1e-4 x 50_005, 0) =
    6.0005; caixa pós-A = 49_988.9995.

    B: preços planos 20, IPO em d3 (série começa depois do início). Decisão
    d3: alvo 1/2 da equity (caixa + A marcado a 10) / ref 20 => int(2499.725)
    = 2_499 (INTEGER no convert). Na execução ao open de d4 o preço slippado
    20.002 + custo não cabe no caixa compartilhado: reduce-until-fits corta
    para 2_498, cut_reason=CASH — o benchmark HERDA o corte de caixa
    (CST-01.3), como qualquer entrada da estratégia.
    """
    series = {
        "A": _series([10.0] * 5, ticker="A"),
        "B": _series([20.0] * 5, ticker="B", start=2),
    }

    result = buy_and_hold_multi(
        series,
        n=2,
        initial_cash=100_000.0,
        costs=_COSTED,
        slippage=FixedBps(bps=1.0),
        cap=0.10,
    )

    # P3: o N do run é o conjunto passado.
    assert result.n == 2
    assert result.tickers == ("A", "B")

    trades = {t.ticker: t for t in result.portfolio.trades}
    assert set(trades) == {"A", "B"}

    # A: slippage aplicado na compra (open 10 -> 10.001), custo debitado.
    a = trades["A"]
    assert a.entry_price == pytest.approx(10.0 * 1.0001)
    assert a.quantity == 5_000  # alvo 1/2 x 100_000 / 10, sem corte
    assert a.entry_cost == pytest.approx(1.0 + 1e-4 * 5_000 * 10.001)
    assert a.entry_date == _D0 + timedelta(days=1)  # d2: 2ª barra de A

    # B: IPO depois do início — compra na 2ª barra do PRÓPRIO ativo (d4).
    b = trades["B"]
    assert b.entry_price == pytest.approx(20.0 * 1.0001)
    cash_after_a = 100_000.0 - 5_000 * 10.001 - (1.0 + 1e-4 * 5_000 * 10.001)
    target_qty = int(0.5 * (cash_after_a + 5_000 * 10.0) / 20.0)
    assert target_qty == 2_499  # o convert aprovou 2_499 (etapa INTEGER)
    assert b.quantity == 2_498  # caixa na execução cortou 1 ação
    assert b.cut_reason is not None and b.cut_reason.value == "cash"
    assert b.entry_date == _D0 + timedelta(days=3)  # d4: 2ª barra de B

    # Buy-and-hold: posições abertas no fim, nenhuma saída.
    assert all(t.is_open for t in result.portfolio.trades)
    assert result.portfolio.cash > 0  # caixa ocioso (MET-02.4)


# ─── MET-02.4: caixa ocioso e sem rebalance ──────────────────────────────────


@pytest.mark.unit
def test_benchmark_no_rebalance() -> None:
    """CA-02.4 — o benchmark não rebalanceia: exatamente N entradas, nenhum
    trade depois delas, nenhum trade de rebalance, caixa residual ocioso."""
    series = {
        "AAA": _series([10.0] * 6, ticker="AAA"),
        "BBB": _series([20.0] * 6, ticker="BBB", start=1),
    }

    result = buy_and_hold_multi(series, n=2, initial_cash=100_000.0, costs=_COSTED)

    trades = result.portfolio.trades
    assert len(trades) == 2  # só as entradas; nada depois (sem rebalance)
    assert all(not t.rebalance for t in trades)
    assert all(t.is_open for t in trades)
    # Caixa ocioso: 1/N por ativo deixou o resto parado, sem realocação.
    assert result.portfolio.cash > 0
    # Nenhum trade de saída/realocação gerado.
    assert result.portfolio.cash + sum(
        p.quantity * result.portfolio.marks[t] for t, p in result.portfolio.positions.items()
    ) == pytest.approx(result.equity_curve[-1])


# ─── MET-02.3: deslistagem travada e reportada ───────────────────────────────


@pytest.mark.unit
def test_benchmark_delisted_position_is_locked_and_reported() -> None:
    """CA-02.3 — ativo com série terminando antes do fim da união: posição
    comprada fica TRAVADA, marcada pelo último close conhecido, nunca
    liquidada; a ocorrência aparece em `delisted` (igual à regra da
    estratégia, RF-POR-02 CA-02.3)."""
    series = {
        "A": _series([10.0] * 6, ticker="A"),  # d1..d6
        "B": _series([20.0] * 3, ticker="B", start=1),  # d2..d4 — deslista
    }

    result = buy_and_hold_multi(series, n=2, initial_cash=100_000.0, costs=_COSTED)

    assert result.delisted == ("B",)
    trades = {t.ticker: t for t in result.portfolio.trades}
    b = trades["B"]
    assert b.entry_date == _D0 + timedelta(days=2)  # d3: 2ª barra de B
    assert b.is_open  # nunca liquidada
    assert b.exit_price is None
    # Marcada pelo último close conhecido até o fim da união (d6).
    assert result.portfolio.marks["B"] == pytest.approx(20.0)
    assert result.portfolio.positions["B"].quantity == b.quantity


# ─── P3 / domínio / determinismo ─────────────────────────────────────────────


@pytest.mark.unit
def test_benchmark_same_n_as_run_is_required() -> None:
    """P3 — o N do run É o conjunto passado ao backtest: divergência é erro
    de programação (EngineError), nunca um N diferente em silêncio."""
    series = {"A": _series([10.0] * 5, ticker="A"), "B": _series([20.0] * 5, ticker="B")}

    with pytest.raises(EngineError):
        buy_and_hold_multi(series, n=3)  # N != len(series)
    with pytest.raises(EngineError):
        buy_and_hold_multi(series, n=0)
    with pytest.raises(EngineError):
        buy_and_hold_multi({}, n=1)


@pytest.mark.unit
def test_benchmark_is_deterministic() -> None:
    """RNF-01 — mesma entrada, mesmos trades e mesma equity final."""
    series = {
        "A": _series([10.0] * 6, ticker="A"),
        "B": _series([20.0] * 6, ticker="B", start=1),
    }

    r1 = buy_and_hold_multi(series, n=2, initial_cash=100_000.0, costs=_COSTED)
    r2 = buy_and_hold_multi(series, n=2, initial_cash=100_000.0, costs=_COSTED)

    assert r1.equity_curve == r2.equity_curve
    assert [(t.ticker, t.quantity, t.entry_price) for t in r1.portfolio.trades] == [
        (t.ticker, t.quantity, t.entry_price) for t in r2.portfolio.trades
    ]
