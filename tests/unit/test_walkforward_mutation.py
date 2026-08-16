"""T11b — mutação ENG-01.2 estendida ao walk-forward (ADR-0011, RF-WFK-04).

**COMMIT DE TESTE PURO** — zero mudança em `src/` (o diff deste commit é só
em `tests/`). O teste de mutação da Fase 1/2a (`test_eng_012_conditional.py`)
é estendido ao protocolo walk-forward, com as duas partes do ADR-0011:

- **CA-04.1** — mutar barras OOS não altera os parâmetros selecionados no IS
  (`test_mutating_oos_does_not_change_is_selected_params`): a construção
  trunca as séries do IS em `is_end` (a fronteira é do ARRAY, CA-01.1), então
  barras OOS mutadas não podem vazar para a seleção. A mutação TEM efeito
  onde deve — na equity OOS — e NENHUM no IS.
- **CA-04.2** — mutar barras futuras do IS não altera intenções anteriores,
  incluindo `ENTER_SHORT`/`EXIT_SHORT` e buy-stop
  (`test_mutating_future_is_bars_does_not_change_prior_intentions_long_short_buy_stop`):
  a parte IS é reauditada para os tipos de ordem novos (ADR-0011); a
  estratégia de papel deriva o preço do buy-stop do `close` da barra corrente
  — se o laço vazasse futuro, o preço emitido mudaria com a mutação.

A estratégia de papel registra o que emitiu (sinais E preços de
limite/stop) — a comparação entre runs é a prova. Séries sintéticas com
derivação auditável (RNF-03); datas de calendário naive (RNF-07).

**Discriminação verificada localmente** (mutações de engenharia revertidas;
seção "verificação" do report da T11b): (a) IS sem truncamento em `is_end`
⇒ o teste CA-04.1 FALHA; (b) execução com `decision_date` = data da execução
⇒ o teste CA-04.2 FALHA.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pytest

from quantlab.engine.backtest import run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.conditional import ConditionalIntent, OrderKind
from quantlab.engine.market_view import MarketView
from quantlab.engine.slippage import FixedBps
from quantlab.engine.strategy import Signal
from quantlab.engine.walkforward import Fold, ParameterGrid, build_folds, run_walkforward
from quantlab.storage.series import PriceSeries

_FREE = CostModel(fixed=0.0, rate=0.0)
_NO_SLIP = FixedBps(bps=0.0)
_INITIAL = 100_000.0


def _business_dates(start: date, n: int) -> list[date]:
    """Primeiros `n` dias úteis (seg-sex) a partir de `start`, inclusive."""
    result: list[date] = []
    day = start
    while len(result) < n:
        if day.weekday() < 5:
            result.append(day)
        day += timedelta(days=1)
    return result


def _series_with_closes(ticker: str, dates: list[date], closes: list[float]) -> PriceSeries:
    """Série de papel: open = close = high = low = `closes` (sem gap no laço)."""
    return PriceSeries(
        ticker=ticker,
        dates=np.array(dates, dtype=object),
        open=np.array(closes, dtype=np.float64),
        high=np.array(closes, dtype=np.float64),
        low=np.array(closes, dtype=np.float64),
        close=np.array(closes, dtype=np.float64),
        volume=np.array([1_000.0] * len(closes)),
        adjusted=True,
        hash="test-hash",
    )


def _subset(series: PriceSeries, dates: list[date]) -> PriceSeries:
    """Nova série com exatamente as datas pedidas — re-derivação NAIVE do
    corte do engine (list-based), para os runs isolados do teste."""
    position = {d: i for i, d in enumerate(series.dates.tolist())}
    idx = [position[d] for d in dates]
    return PriceSeries(
        ticker=series.ticker,
        dates=np.array(dates, dtype=object),
        open=np.array([series.open[i] for i in idx], dtype=np.float64),
        high=np.array([series.high[i] for i in idx], dtype=np.float64),
        low=np.array([series.low[i] for i in idx], dtype=np.float64),
        close=np.array([series.close[i] for i in idx], dtype=np.float64),
        volume=np.array([series.volume[i] for i in idx], dtype=np.float64),
        adjusted=series.adjusted,
        hash=series.hash,
    )


def _naive_composite(series: PriceSeries, fold: Fold, warmup: int) -> tuple[PriceSeries, int]:
    """Série composta do OOS re-derivada de forma NAIVE: cauda do IS
    (últimas `warmup` barras <= is_end) + segmento OOS; devolve também
    `tail_len` (para série única, len(cauda))."""
    own_dates = series.dates.tolist()
    is_bars = [d for d in own_dates if d <= fold.is_end]
    tail = is_bars[-warmup:] if warmup > 0 else []
    oos_bars = [d for d in own_dates if fold.oos_start <= d <= fold.oos_end]
    dates = tail + oos_bars
    return _subset(series, dates), sum(1 for d in dates if d <= fold.is_end)


# ─── estratégias de papel ─────────────────────────────────────────────────────


@dataclass
class ScalperStrategy:
    """Compra e vende em barras alternadas (determinístico) — trade em TODO
    bar consultado a partir de `start`, equity sensível a TODA barra lida.

    `start` (params do grid) desloca a paridade da primeira entrada ⇒ preços
    de entrada diferentes ⇒ Sharpe IS diferente por combinação. A seleção é
    determinística; mutar barras que o IS NÃO lê (construção truncada) não a
    altera — e mutar barras que o IS lê (mutação de lookahead) a altera.
    """

    start: int
    warmup: int = 1

    def on_bar(self, view: MarketView) -> Signal | None:
        if view.i < self.start:
            return None
        if (view.i - self.start) % 2 == 0:
            return Signal.ENTER
        return Signal.EXIT


@dataclass
class ShortBuyStopStrategy:
    """Estratégia de papel (CA-04.2) que emite, em índices fixos: ENTER_SHORT,
    EXIT_SHORT (mercado) e um buy-stop com preço DERIVADO do close da barra
    corrente (``close x stop_mult``). REGISTRA o que emitiu — sinais e preços
    de stop — para a comparação entre runs: se o laço vazasse futuro, o preço
    do buy-stop mudaria com a mutação das barras livres.
    """

    stop_mult: float
    observer: list[tuple[int, str, float | None]]
    warmup: int = 1

    def on_bar(self, view: MarketView) -> Signal | ConditionalIntent | None:
        if view.i == 1:
            self.observer.append((view.i, "ENTER_SHORT", None))
            return Signal.ENTER_SHORT
        if view.i == 2:
            self.observer.append((view.i, "EXIT_SHORT", None))
            return Signal.EXIT_SHORT
        if view.i == 3:
            close = float(view.close[-1])
            stop = close * self.stop_mult
            self.observer.append((view.i, "BUY_STOP", stop))
            return ConditionalIntent(signal=Signal.ENTER, order_type=OrderKind.STOP, stop=stop)
        return None


def _scalper_factory(params: dict[str, float]) -> ScalperStrategy:
    return ScalperStrategy(start=int(params["start"]))


def _short_buy_stop_factory(
    observer: list[tuple[int, str, float | None]],
) -> Callable[[dict[str, float]], ShortBuyStopStrategy]:
    """Fábrica cujas instâncias registram as emissões num observer COMPARTILHADO
    — o observer acumula, em ordem determinística, as emissões de TODOS os
    runs do walk-forward (grade IS por fold + OOS por fold)."""

    def factory(params: dict[str, float]) -> ShortBuyStopStrategy:
        return ShortBuyStopStrategy(stop_mult=params["stop_mult"], observer=observer)

    return factory


# ─── CA-04.1: mutar OOS não altera params IS ─────────────────────────────────


@pytest.mark.unit
def test_mutating_oos_does_not_change_is_selected_params() -> None:
    """CA-04.1 / ADR-0011 — mutar barras OOS não altera os params selecionados
    no IS de NENHUM fold, e tem efeito onde deve: na equity OOS.

    Fixture: 50 dias úteis, 2 folds (IS 20 / OOS 15), grid de 2 combinações
    (`start`), estratégia scalper (trade em todo bar consultado ⇒ equity
    sensível a toda barra lida). Cenário A: mutar o OOS do ÚLTIMO fold
    (dias 36-50, livres para TODOS os IS — nenhum IS lê além de `is_end`);
    Cenário B: mutar o OOS do fold 0 (dias 21-35 — livre para o IS do fold 0;
    o fold 1 o lê LEGITIMAMENTE como janela IS rolling, então nada se
    assere sobre o fold 1).
    """
    dates = _business_dates(date(2024, 1, 1), 50)
    closes = [100.0 + i for i in range(50)]
    series = _series_with_closes("AAA", dates, closes)
    folds = build_folds(dates[0], dates[-1], is_window=20, oos_window=15)
    assert len(folds) == 2
    grid = ParameterGrid(({"start": 1.0}, {"start": 2.0}))
    kwargs: dict[str, Any] = dict(
        series={"AAA": series},
        strategy_factory=_scalper_factory,
        grid=grid,
        folds=folds,
        warmup=1,
        initial_cash=_INITIAL,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
    )

    baseline = run_walkforward(**kwargs)
    segment0 = 15  # oos_window — 1 ponto por dia útil

    # ── Cenário A: mutar o OOS do ÚLTIMO fold (dias 36-50) para 1000x ──
    mutated_closes_a = closes[:35] + [c * 1_000.0 for c in closes[35:]]
    mutated_a = run_walkforward(
        **{**kwargs, "series": {"AAA": _series_with_closes("AAA", dates, mutated_closes_a)}}
    )

    # selected_params POR FOLD idênticos — a mutação NÃO vaza para o IS.
    assert [fr.selected_params for fr in mutated_a.folds] == [
        fr.selected_params for fr in baseline.folds
    ]
    assert mutated_a.oos_dates == baseline.oos_dates
    # A mutação TEM efeito onde deve: o segmento do fold 1 (OOS mutado) muda...
    assert mutated_a.oos_equity[segment0:] != pytest.approx(baseline.oos_equity[segment0:])
    # ...e NENHUM onde não deve: o segmento do fold 0 (OOS intacto) é idêntico.
    assert mutated_a.oos_equity[:segment0] == pytest.approx(baseline.oos_equity[:segment0])

    # ── Cenário B: mutar o OOS do fold 0 (dias 21-35) para 1000x ──
    mutated_closes_b = closes[:20] + [c * 1_000.0 for c in closes[20:35]] + closes[35:]
    mutated_b = run_walkforward(
        **{**kwargs, "series": {"AAA": _series_with_closes("AAA", dates, mutated_closes_b)}}
    )

    # O IS do fold 0 (<= is_end = dia 20) não lê o OOS mutado — params estáveis.
    assert mutated_b.folds[0].selected_params == baseline.folds[0].selected_params
    # E o OOS do fold 0 (composto = dia 20 + dias 21-35 mutados) muda.
    assert mutated_b.oos_equity[:segment0] != pytest.approx(baseline.oos_equity[:segment0])


# ─── CA-04.2: mutar futuro do IS não altera intenções (shorts + buy-stop) ────


@pytest.mark.unit
def test_mutating_future_is_bars_does_not_change_prior_intentions_long_short_buy_stop() -> None:
    """CA-04.2 / ADR-0011 — mutar barras futuras do IS não altera as intenções
    emitidas ANTES, incluindo `ENTER_SHORT`/`EXIT_SHORT` e o preço do buy-stop
    (derivado do close corrente).

    Fixture: 50 dias úteis, 2 folds, grid de 1 combinação (a reauditoria de
    intenções não depende de seleção multi-candidata — a seleção
    multi-candidata é o foco do CA-04.1). A estratégia emite nos índices
    1/2/3 (curto, cobertura, buy-stop); as barras LIVRES são as posteriores à
    última decisão + a barra de execução (índices >= 5): mutar os dias 6-15
    (x2) não altera NENHUM emitido — nem o preço do stop.
    """
    dates = _business_dates(date(2024, 1, 1), 50)
    closes = [100.0 + i for i in range(50)]
    series = _series_with_closes("AAA", dates, closes)
    folds = build_folds(dates[0], dates[-1], is_window=20, oos_window=15)
    grid = ParameterGrid(({"stop_mult": 1.05},))

    baseline_obs: list[tuple[int, str, float | None]] = []
    mutated_obs: list[tuple[int, str, float | None]] = []
    kwargs: dict[str, Any] = dict(
        series={"AAA": series},
        strategy_factory=_short_buy_stop_factory(baseline_obs),
        grid=grid,
        folds=folds,
        warmup=1,
        initial_cash=_INITIAL,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
    )
    baseline = run_walkforward(**kwargs)

    # Barras livres: dias 6-15 (índices 5-14) — após a última decisão (3) +
    # a barra de execução (4); fora das caudas OOS dos dois folds.
    mutated_closes = closes[:5] + [c * 2.0 for c in closes[5:15]] + closes[15:]
    run_walkforward(
        **{
            **kwargs,
            "series": {"AAA": _series_with_closes("AAA", dates, mutated_closes)},
            "strategy_factory": _short_buy_stop_factory(mutated_obs),
        }
    )

    # Intenções emitidas IDÊNTICAS — sinais E preços de stop (se o laço
    # vazasse futuro, o close mutado entraria no preço do buy-stop).
    assert baseline_obs == mutated_obs, (
        "as barras futuras do IS mudaram a intenção (sinais ou preços de stop) — "
        "lookahead de decisão no laço"
    )
    # O run IS do fold 0 emitiu exatamente o script, com o preço do buy-stop
    # derivado do close da barra da DECISÃO (103.0 x 1.05) — não do close
    # mutado das barras livres (dias 6-15).
    fold0_is_emissions = baseline_obs[:3]
    assert fold0_is_emissions == [
        (1, "ENTER_SHORT", None),
        (2, "EXIT_SHORT", None),
        (3, "BUY_STOP", pytest.approx(103.0 * 1.05)),
    ]

    # A mutação TEM efeito onde deve: a equity do IS muda (mark-through das
    # barras mutadas — o buy-stop do run mutado preenche em barra diferente).
    scratch: list[tuple[int, str, float | None]] = []
    truncated_base = _subset(series, [d for d in dates if d <= folds[0].is_end])
    truncated_mut = _subset(
        _series_with_closes("AAA", dates, mutated_closes),
        [d for d in dates if d <= folds[0].is_end],
    )
    is_base = run_backtest_multi(
        {"AAA": truncated_base},
        {"AAA": ShortBuyStopStrategy(stop_mult=1.05, observer=scratch)},
        initial_cash=_INITIAL,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
    )
    is_mut = run_backtest_multi(
        {"AAA": truncated_mut},
        {"AAA": ShortBuyStopStrategy(stop_mult=1.05, observer=scratch)},
        initial_cash=_INITIAL,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
    )
    assert is_base.equity_curve != is_mut.equity_curve

    # A execução continua vinculada a decisões ANTERIORES (ADR-0002): trades
    # do OOS isolado do fold 0 (params selecionados) têm decision_date <
    # entry_date — a reauditoria da parte de EXECUÇÃO para os tipos novos.
    selected = baseline.folds[0].selected_params
    composite, _tail_len = _naive_composite(series, folds[0], warmup=1)
    oos_run = run_backtest_multi(
        {"AAA": composite},
        {"AAA": ShortBuyStopStrategy(stop_mult=selected["stop_mult"], observer=scratch)},
        initial_cash=_INITIAL,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
    )
    assert len(oos_run.portfolio.trades) >= 2  # curto + compra pelo buy-stop
    for trade in oos_run.portfolio.trades:
        assert trade.entry_decision_date < trade.entry_date
        if trade.exit_date is not None:
            assert trade.exit_decision_date is not None
            assert trade.exit_decision_date < trade.exit_date
