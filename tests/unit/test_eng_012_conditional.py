"""ENG-01.2 REFORMULADO — duas partes (ADR-0005) + fronteira por ativo.

O teste de mutação da Fase 1 (`test_mutating_future_bars_does_not_change_trades`,
single-asset, ordens a mercado) é substituído pelo par que discrimina os dois
modos de falha que a Fase 2a introduziu (wording literal do DoD v0.2):

- **Parte 1 — lookahead de DECISÃO:** mutação de barras posteriores à última
  decisão não altera a intenção emitida pela estratégia (sinais e preços de
  limite/stop).
- **Parte 2 — lookahead de EXECUÇÃO:** toda execução originada por limite/stop
  vincula-se a uma ordem preexistente, confirmada via `decision_date` gravado
  no Trade **anterior à barra de execução**.
- **Fronteira por ativo (POR-05.4):** mutar o futuro de X não altera intenções
  nem execuções de X **nem de Y**.

A estratégia de papel deriva os preços de limite/stop do `close` da barra
corrente — se o laço vazasse futuro, os preços emitidos mudariam com a mutação
e a igualdade abaixo falharia. Séries sintéticas com derivação auditável
(RNF-03); COMMIT DE TESTE PURO: nada em `src/` muda aqui.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.engine.backtest import run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.conditional import Bracket, ConditionalIntent, OrderKind
from quantlab.engine.market_view import MarketView
from quantlab.engine.portfolio import TradeOrigin
from quantlab.engine.slippage import FixedBps
from quantlab.engine.strategy import Signal
from quantlab.storage.series import PriceSeries

_FREE = CostModel(fixed=0.0, rate=0.0)
_NO_SLIP = FixedBps(bps=0.0)
_D0 = date(2024, 1, 1)


def _dates(n: int) -> list[date]:
    return [_D0 + timedelta(days=i) for i in range(n)]


def _series(prices: list[float], *, ticker: str) -> PriceSeries:
    """Série de papel: open = close = high = low = `prices` (fixture de papel,
    mesma política de `test_backtest._series`)."""
    dates = _dates(len(prices))
    date_array: NDArray[np.object_] = np.empty(len(dates), dtype=object)
    date_array[:] = dates
    values = np.array(prices, dtype=np.float64)
    return PriceSeries(
        ticker=ticker,
        dates=date_array,
        open=values,
        high=values,
        low=values,
        close=values,
        volume=np.array([1_000.0] * len(prices)),
        adjusted=True,
        hash="0" * 64,
    )


@dataclass
class PaperLimitStopStrategy:
    """Estratégia de papel que emite intenções condicionais com preços
    DERIVADOS do close da barra corrente: `limit = close x 1.05`,
    `stop = close x 0.95` (bracket na mesma intenção — SIG-01.2).

    Emite apenas nos índices do `script` e REGISTRA o que emitiu — a
    comparação entre runs é a prova da parte 1: se o laço vazasse futuro, os
    preços mudariam com a mutação das barras livres.
    """

    script: dict[int, bool]
    warmup: int = 0
    bracket: bool = True
    emitted: list[tuple[int, float, float]] = field(default_factory=list)  # (i, limit, stop)

    def on_bar(self, view: MarketView) -> Signal | ConditionalIntent | None:
        i = view.i
        if not self.script.get(i, False):
            return None
        close = float(view.close[-1])
        limit = close * 1.05
        stop = close * 0.95
        self.emitted.append((i, limit, stop))
        if self.bracket:
            return ConditionalIntent(
                signal=Signal.ENTER,
                order_type=OrderKind.LIMIT,
                limit=limit,
                bracket=Bracket(limit=limit, stop=stop),
            )
        return ConditionalIntent(
            signal=Signal.ENTER,
            order_type=OrderKind.LIMIT,
            limit=limit,
        )


# ─── Parte 1: mutação NÃO altera a intenção (sinais e preços de limite/stop) ─


@pytest.mark.unit
def test_eng_012_mutation_does_not_change_conditional_intent() -> None:
    """ENG-01.2 parte 1 / ADR-0005 — mutar barras posteriores à última decisão
    (índices 3..5; a decisão em 1 executa no open de 2, que é lido) não altera
    nem os sinais nem os PREÇOS de limite/stop emitidos, nem os trades.

    Se o laço vazasse futuro, a estratégia derivaria L/S do close mutado
    (1.000 x 1.05 em vez de 10.5) e a igualdade de `emitted` falharia."""
    baseline_strategy = PaperLimitStopStrategy({1: True})
    baseline = run_backtest_multi(
        {"A": _series([10.0] * 6, ticker="A")},
        {"A": baseline_strategy},
        costs=_FREE,
        slippage=_NO_SLIP,
    )

    mutated_strategy = PaperLimitStopStrategy({1: True})
    mutated = run_backtest_multi(
        {"A": _series([10.0, 10.0, 10.0, 1_000.0, 2_000.0, 3_000.0], ticker="A")},
        {"A": mutated_strategy},
        costs=_FREE,
        slippage=_NO_SLIP,
    )

    assert baseline_strategy.emitted == mutated_strategy.emitted, (
        "as barras futuras mudaram a intenção (sinais ou preços de limite/stop) — "
        "lookahead de decisão no laço"
    )
    assert baseline_strategy.emitted == [(1, 10.5, 9.5)]
    assert baseline.portfolio.trades == mutated.portfolio.trades
    assert len(baseline.portfolio.trades) == 1  # entrada do bracket em d2, a 10.0
    assert baseline.portfolio.trades[0].entry_price == pytest.approx(10.0)


# ─── Parte 2: execução vincula-se a ordem preexistente via decision_date ─────


@pytest.mark.unit
def test_eng_012_execution_binds_to_order_via_decision_date() -> None:
    """ENG-01.2 parte 2 / ADR-0005 — todo Trade originado por limite/stop tem
    `origin in {LIMIT, STOP}` e o `decision_date` gravado é ANTERIOR à barra de
    execução (ADR-0002): a execução nunca usa dado posterior à decisão.

    Cenário: A = bracket (entrada LIMIT em d2 a min(10.5, open 10) = 10, o stop
    9.5 dispara em d3 a min(9.5, open 9) = 9 — round trip completo); B = limite
    de compra puro (abre em d2 a min(10.5, 10) = 10 e fica aberta).
    """
    opens_a = [10.0, 10.0, 10.0, 9.0, 9.0, 9.0]
    opens_b = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    result = run_backtest_multi(
        {"A": _series(opens_a, ticker="A"), "B": _series(opens_b, ticker="B")},
        {
            "A": PaperLimitStopStrategy({1: True}),
            "B": PaperLimitStopStrategy({1: True, 5: False}, bracket=False),
        },
        costs=_FREE,
        slippage=_NO_SLIP,
    )

    trades = result.portfolio.trades
    assert len(trades) == 2
    by_ticker = {t.ticker: t for t in trades}

    closed = by_ticker["A"]
    assert closed.origin == TradeOrigin.STOP  # a origem final é a da saída
    assert closed.entry_decision_date == _D0 + timedelta(days=1)  # decisão em d1
    assert closed.entry_date == _D0 + timedelta(days=2)  # execução em d2
    assert closed.entry_decision_date < closed.entry_date
    assert closed.exit_decision_date is not None
    assert closed.exit_decision_date < closed.exit_date  # type: ignore[operator]

    opened = by_ticker["B"]
    assert opened.origin == TradeOrigin.LIMIT
    assert opened.entry_decision_date < opened.entry_date

    # Auditoria sobre TODOS os trades do run: origem condicional + vínculo.
    for trade in trades:
        assert trade.origin in {TradeOrigin.LIMIT, TradeOrigin.STOP}
        assert trade.entry_decision_date < trade.entry_date
        if trade.exit_date is not None:
            assert trade.exit_decision_date is not None
            assert trade.exit_decision_date < trade.exit_date


# ─── Fronteira por ativo (POR-05.4) ──────────────────────────────────────────


@pytest.mark.unit
def test_mutation_frontier_is_per_asset() -> None:
    """POR-05.4 / ADR-0005 — mutar o futuro do ativo X não altera intenções
    nem execuções de X NEM de Y: a fronteira da mutação é por ativo."""
    strat_a_base = PaperLimitStopStrategy({1: True})
    strat_b_base = PaperLimitStopStrategy({1: True})
    baseline = run_backtest_multi(
        {
            "A": _series([10.0] * 6, ticker="A"),
            "B": _series([20.0] * 6, ticker="B"),
        },
        {"A": strat_a_base, "B": strat_b_base},
        costs=_FREE,
        slippage=_NO_SLIP,
    )

    strat_a_mut = PaperLimitStopStrategy({1: True})
    strat_b_mut = PaperLimitStopStrategy({1: True})
    mutated = run_backtest_multi(
        {
            # Só o futuro de A muda (barras 3..5); B fica intacto.
            "A": _series([10.0, 10.0, 10.0, 1_000.0, 2_000.0, 3_000.0], ticker="A"),
            "B": _series([20.0] * 6, ticker="B"),
        },
        {"A": strat_a_mut, "B": strat_b_mut},
        costs=_FREE,
        slippage=_NO_SLIP,
    )

    # Intenções de A e de B idênticas.
    assert strat_a_base.emitted == strat_a_mut.emitted
    assert strat_b_base.emitted == strat_b_mut.emitted
    # Execuções de A e de B idênticas (trades por ativo, na ordem de criação).
    a_base = [t for t in baseline.portfolio.trades if t.ticker == "A"]
    b_base = [t for t in baseline.portfolio.trades if t.ticker == "B"]
    a_mut = [t for t in mutated.portfolio.trades if t.ticker == "A"]
    b_mut = [t for t in mutated.portfolio.trades if t.ticker == "B"]
    assert a_base == a_mut
    assert b_base == b_mut
    assert [t.entry_price for t in a_base] == [pytest.approx(10.0)]
    assert [t.entry_price for t in b_base] == [pytest.approx(20.0)]
