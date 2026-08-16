"""T10 — walk-forward: folds, grade determinística e sharpe único (design §3.6, ADR-0011).

Fixtures de papel com derivação auditável (RNF-03); datas de calendário
naive (RNF-07). As janelas dos folds cruzam fim de semana de propósito — a
semântica "dia útil" (seg-sex, decisão local T10) só é exercitada se houver
weekend no meio; numa janela seg-sex pura, dias corridos e dias úteis
coincidiriam e o teste passaria "vazio".
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from quantlab.analytics.metrics import sharpe
from quantlab.engine.backtest import run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.calendar import UnionCalendar
from quantlab.engine.market_view import MarketView
from quantlab.engine.slippage import FixedBps
from quantlab.engine.strategy import Signal
from quantlab.engine.walkforward import (
    PER_FOLD_BUDGET_S,
    TOTAL_BUDGET_MARGIN_S,
    Fold,
    ParameterGrid,
    build_folds,
    measure_walkforward,
    run_walkforward,
    sharpe_annualized_rf0,
)
from quantlab.exceptions import EngineError, InsufficientHistoryError
from quantlab.storage.series import PriceSeries
from quantlab.strategies.sma_cross import SmaCross

_FREE = CostModel(fixed=0.0, rate=0.0)
_NO_SLIP = FixedBps(bps=0.0)


def _business_dates(start: date, n: int) -> list[date]:
    """Primeiros `n` dias úteis (seg-sex) a partir de `start`, inclusive."""
    result: list[date] = []
    day = start
    while len(result) < n:
        if day.weekday() < 5:
            result.append(day)
        day += timedelta(days=1)
    return result


def _business_day_count(start: date, end: date) -> int:
    """Nº de dias úteis (seg-sex) no intervalo INCLUSIVE [start, end]."""
    count = 0
    day = start
    while day <= end:
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    return count


def _series(ticker: str, dates: list[date]) -> PriceSeries:
    """Série sintética: 1 barra por data, preço constante."""
    count = len(dates)
    return PriceSeries(
        ticker=ticker,
        dates=np.array(dates, dtype=object),
        open=np.full(count, 10.0),
        high=np.full(count, 10.0),
        low=np.full(count, 10.0),
        close=np.full(count, 10.0),
        volume=np.full(count, 1_000.0),
        adjusted=True,
        hash="test-hash",
    )


# ─── CA-01.2: folds disjuntos, união dos OOS cobre a janela ───────────────────


@pytest.mark.unit
def test_folds_are_disjoint_and_oos_union_covers_window() -> None:
    """CA-01.2 — IS/OOS disjuntos por fold; união dos OOS tila a janela sem gap.

    Janela 2024-01-01 (seg) a 2024-03-29 (sex) = 65 dias úteis; is_window=20,
    oos_window=15 ⇒ 3 folds, com o último OOS truncado em `end`.
    Primeiro fold: IS = [01-01, 01-26], OOS = [01-29, 02-16] (spot-checks).
    """
    window = _business_dates(date(2024, 1, 1), 65)
    start, end = window[0], window[-1]
    assert _business_day_count(start, end) == 65

    for anchor in ("rolling", "anchored"):
        folds = build_folds(start, end, is_window=20, oos_window=15, anchor=anchor)

        # 3 folds; janelas com datas esperadas de papel.
        assert len(folds) == 3, anchor
        assert folds[0].is_start == date(2024, 1, 1), anchor
        assert folds[0].is_end == date(2024, 1, 26), anchor
        assert folds[0].oos_start == date(2024, 1, 29), anchor
        assert folds[0].oos_end == date(2024, 2, 16), anchor
        assert folds[-1].oos_end == end, anchor

        for fold in folds:
            # Disjuntos DENTRO do fold: is_end < oos_start, sem dia útil no meio.
            assert fold.is_start <= fold.is_end < fold.oos_start <= fold.oos_end
            assert _add_business_days(fold.is_end, 1) == fold.oos_start

        # OOS sem sobreposição e sem gap entre folds consecutivos.
        for prev, nxt in pairwise(folds):
            assert prev.oos_end < nxt.oos_start
            assert _add_business_days(prev.oos_end, 1) == nxt.oos_start

        # A união dos OOS cobre exatamente a janela avaliada: de start + 20
        # dias úteis até end, sem sobreposição (65 = 20 IS + 45 OOS).
        first_oos_start = _add_business_days(start, 20)
        assert folds[0].oos_start == first_oos_start
        total_oos = sum(_business_day_count(f.oos_start, f.oos_end) for f in folds)
        assert total_oos == 65 - 20

        # rolling: |IS| fixo; anchored: IS sempre ancorado em `start`.
        if anchor == "rolling":
            assert {_business_day_count(f.is_start, f.is_end) for f in folds} == {20}
        else:
            assert all(f.is_start == start for f in folds)
            assert folds[1].is_end == date(2024, 2, 16), anchor


@pytest.mark.unit
def test_build_folds_is_deterministic_across_calls() -> None:
    """RNF-01 — a mesma entrada devolve os MESMOS folds (tuple igual, não só valores)."""
    start, end = date(2024, 1, 1), date(2024, 6, 28)
    assert build_folds(start, end, is_window=40, oos_window=20) == build_folds(
        start, end, is_window=40, oos_window=20
    )
    assert build_folds(start, end, 40, 20, anchor="anchored") == build_folds(
        start, end, 40, 20, anchor="anchored"
    )


@pytest.mark.unit
def test_build_folds_invalid_inputs_raise_engine_error() -> None:
    """§3.8 — fold inválido é EngineError nomeado, nunca valor fabricado."""
    start, end = date(2024, 1, 1), date(2024, 3, 29)

    with pytest.raises(EngineError):
        build_folds(end, start, is_window=20, oos_window=15)  # start > end
    with pytest.raises(EngineError):
        build_folds(start, end, is_window=0, oos_window=15)  # IS vazio
    with pytest.raises(EngineError):
        build_folds(start, end, is_window=20, oos_window=0)  # OOS vazio
    with pytest.raises(EngineError):
        build_folds(start, end, is_window=20, oos_window=15, anchor=cast(Any, "walk"))
    # Janela com espaço só para o IS, sem nenhum dia de OOS.
    with pytest.raises(EngineError):
        build_folds(start, _add_business_days(start, 19), is_window=20, oos_window=5)


# ─── CA-02.1: grade determinística ────────────────────────────────────────────


@pytest.mark.unit
def test_walkforward_grid_is_deterministic_params_identical() -> None:
    """CA-02.1/RNF-01 — grade EXPLÍCITA, varrida na ordem declarada, sem aleatoriedade.

    Duas instâncias com a mesma entrada são idênticas (params na mesma
    ordem); `grid_size` é declarado (MHT — CA-06.2); `seed` é carregada e
    declarada quando um otimizador estocástico a exigir (design §3.6).
    """
    params = ({"fast": 10.0, "slow": 30.0}, {"fast": 20.0, "slow": 60.0})
    a = ParameterGrid(params)
    b = ParameterGrid(params)

    assert a == b
    assert a.params == b.params
    assert a.grid_size == 2
    assert a.seed is None

    seeded = ParameterGrid(params, seed=42)
    assert seeded.seed == 42
    assert seeded == ParameterGrid(params, seed=42)

    with pytest.raises(EngineError):
        ParameterGrid(())  # §3.8 — grade vazia


# ─── CA-01.1: isolamento por construção (fronteira do ARRAY truncado) ─────────


@pytest.mark.unit
def test_is_run_never_indexes_oos_bars_engine_error() -> None:
    """CA-01.1 — o run IS usa séries TRUNCADAS; a fronteira é do array.

    Série de 40 dias úteis truncada no fim do IS (20 primeiros) tem EXATAMENTE
    20 barras: o `UnionCalendar` cobre só a janela IS e o `MarketView` recusa
    qualquer índice além do fim — acessar barras OOS (que só existiriam no
    array completo) é EngineError por construção, não por disciplina de quem
    chama (design §3.6/ADR-0011).
    """
    full_dates = _business_dates(date(2024, 1, 1), 40)
    is_dates = full_dates[:20]  # truncado em is_end — a série OOS NÃO é passada
    series = _series("AAA", is_dates)

    calendar = UnionCalendar.build({"AAA": series})
    assert calendar.dates == tuple(is_dates)  # a janela IS é tudo o que existe

    # 1. União: índice além do fim (a barra OOS teria índice >= len) é EngineError.
    with pytest.raises(EngineError):
        calendar.has_bar_at("AAA", len(is_dates))

    # 2. MarketView: índice == len(series) (a primeira barra OOS) é EngineError.
    with pytest.raises(EngineError):
        MarketView(series, len(is_dates))

    # 3. last(field, n) além do histórico disponível — InsufficientHistoryError.
    with pytest.raises(InsufficientHistoryError):
        MarketView(series, len(is_dates) - 1).last("close", len(is_dates) + 1)


# ─── CA-01.3: warmup do OOS = cauda do IS, sem lookahead (contrato dos folds) ─


@pytest.mark.unit
def test_oos_warmup_uses_is_tail_without_lookahead() -> None:
    """CA-01.3 — a cauda que aquece o OOS é toda <= a fronteira (dados IS).

    Contrato dos folds (o mecanismo do gate i >= warmup é da T11a): a
    fronteira é `oos_start`; os `warmup` dias úteis imediatamente anteriores
    a `oos_start` são TODOS <= `is_end` (dados do IS, <= fronteira — sem
    lookahead, R4) para qualquer warmup <= is_window. E a cauda vem do FOLD,
    não dos dados: `build_folds` é determinístico, então mutar qualquer coisa
    fora do fold não move a fronteira nem troca a cauda (a mutação de dados
    OOS em si é exercitada na T11b, CA-04.1).
    """
    window = _business_dates(date(2024, 1, 1), 65)
    start, end = window[0], window[-1]
    folds = build_folds(start, end, is_window=20, oos_window=15)

    for fold in folds:
        for warmup in (1, 5, 20):  # qualquer cauda <= is_window cabe no IS
            tail = [d for d in window if fold.is_start <= d < fold.oos_start][-warmup:]
            assert len(tail) == warmup, (fold, warmup)
            assert all(day <= fold.is_end for day in tail), (fold, warmup)

    # Determinismo: a cauda é função do fold (is_start..oos_start), não dos dados.
    assert folds == build_folds(start, end, is_window=20, oos_window=15)


# ─── CA-02.3 / R5: métrica de seleção = Sharpe anualizado rf=0, fonte única ──


@pytest.mark.unit
def test_is_selection_metric_is_annualized_sharpe_rf0_declared() -> None:
    """CA-02.3/R5 — a métrica de seleção IS é o Sharpe anualizado com rf=0.

    Forma fechada com retornos de papel (RNF-03): [0.03, 0.01] ->
    media = 0.02, desvio amostral = |0.03 - 0.01| / sqrt(2) = 0.02/sqrt(2);
    media/desvio = sqrt(2); anualizado = sqrt(2) * sqrt(252) = sqrt(504).
    """
    result = sharpe_annualized_rf0([0.03, 0.01])

    assert result == pytest.approx(math.sqrt(504))
    # rf=0 EXPLÍCITO: a seleção e o relatório (metrics.sharpe) concordam.
    assert sharpe(pd.Series([0.03, 0.01])) == pytest.approx(result)


@pytest.mark.unit
def test_sharpe_annualized_rf0_closed_form_and_delegation() -> None:
    """Forma fechada e delegação — uma implementação, dois consumidores (emenda P1).

    `metrics.sharpe()` com os defaults (rf=0, periods=252 — o uso do
    relatório) devolve EXATAMENTE o que `sharpe_annualized_rf0` devolve para
    a mesma série: não há uma segunda fórmula no analytics (sem drift entre
    seleção IS e relatório — lição da T14).
    """
    returns = [0.03, 0.01, -0.02, 0.05, 0.0]
    expected = sharpe_annualized_rf0(returns)

    assert sharpe(pd.Series(returns)) == pytest.approx(expected)

    # None explícito, nunca NaN (R6): série vazia, 1 observação, desvio zero.
    assert sharpe_annualized_rf0([]) is None
    assert sharpe_annualized_rf0([0.01]) is None
    assert sharpe_annualized_rf0([0.02, 0.02, 0.02]) is None
    assert sharpe(pd.Series([], dtype=float)) is None


# ─── helpers locais de teste ──────────────────────────────────────────────────


def _add_business_days(day: date, n: int) -> date:
    """`day + n` dias úteis (seg-sex), n >= 0 — espelha o helper do engine."""
    result = day
    remaining = n
    while remaining > 0:
        result += timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


# ─── T11a — run_walkforward: caixa preta por fold (RF-WFK-03/05) ─────────────


@dataclass
class EnterAtStrategy:
    """Entra long na barra `enter_at` (índice de consulta) e nunca sai.

    Cada params do grid é IDENTIFICÁVEL no OOS pelo trade que produz (data de
    entrada diferente por `enter_at`) — o que permite provar que o OOS rodou
    com os params selecionados no IS DO MESMO fold (CA-02.2).
    """

    enter_at: int
    warmup: int = 1

    def on_bar(self, view: MarketView) -> Signal | None:
        if view.i == self.enter_at:
            return Signal.ENTER
        return None


def _series_with_closes(ticker: str, dates: list[date], closes: Sequence[float]) -> PriceSeries:
    """Série de papel com os closes dados; open = close (sem gap no laço)."""
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
    corte do engine (list-based, sem máscara numpy): se o engine cortar
    errado, esta versão diverge e o teste pega."""
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
    """Série composta do OOS re-derivada de forma NAIVE (list-based): cauda
    do IS (últimas `warmup` barras <= is_end) + segmento OOS; devolve também
    `tail_len` (datas-união <= is_end — para série única, len(cauda))."""
    own_dates = series.dates.tolist()
    is_bars = [d for d in own_dates if d <= fold.is_end]
    tail = is_bars[-warmup:] if warmup > 0 else []
    oos_bars = [d for d in own_dates if fold.oos_start <= d <= fold.oos_end]
    dates = tail + oos_bars
    return _subset(series, dates), sum(1 for d in dates if d <= fold.is_end)


def _naive_is_sharpe(
    series: PriceSeries, fold: Fold, params: dict[str, float], factory: Any
) -> float | None:
    """Seleção IS re-derivada de forma NAIVE: roda o run IS truncado com os
    params dados e devolve `sharpe_annualized_rf0` da equity (None sse fundo
    quebrado) — o contraponto independente do argmax do engine."""
    truncated = _subset(series, [d for d in series.dates.tolist() if d <= fold.is_end])
    result = run_backtest_multi(
        {"AAA": truncated},
        {"AAA": factory(params)},
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
    )
    if result.broken_fund:
        return None
    equity = result.equity_curve
    returns = [equity[i + 1] / equity[i] - 1.0 for i in range(len(equity) - 1)]
    return sharpe_annualized_rf0(returns)


def _sma_factory(params: dict[str, float]) -> SmaCross:
    """Fábrica do SmaCross com warmup fixo = slow (igual em todos os candidatos)."""
    return SmaCross(fast=int(params["fast"]), slow=int(params["slow"]))


def _enter_at_factory(params: dict[str, float]) -> EnterAtStrategy:
    """Fábrica da estratégia scriptada por params."""
    return EnterAtStrategy(enter_at=int(params["enter_at"]))


def _naive_select(
    series: PriceSeries, folds: tuple[Fold, ...], grid: ParameterGrid, factory: Any
) -> list[dict[str, float]]:
    """Argmax independente do sharpe IS por fold — empate pela ordem do grid."""
    selected: list[dict[str, float]] = []
    for fold in folds:
        best_p: dict[str, float] | None = None
        best_s: float | None = None
        for params in grid.params:
            s = _naive_is_sharpe(series, fold, params, factory)
            if best_p is None or (s is not None and (best_s is None or s > best_s)):
                best_p, best_s = params, s
        assert best_p is not None
        selected.append(best_p)
    return selected


@pytest.mark.unit
def test_walkforward_equity_is_exact_oos_concatenation() -> None:
    """CA-03.1 — `oos_equity` é a CONCATENAÇÃO EXATA dos segmentos OOS.

    Cada segmento do walk-forward reproduz o run OOS ISOLADO do fold (mesma
    série composta re-derivada naive, mesmos params, mesma configuração —
    herança por construção) e a união das datas OOS cobre a janela avaliada
    sem sobreposição (CA-01.2 no dado).
    """
    dates = _business_dates(date(2024, 1, 1), 65)
    closes = [100 + 6 * math.sin(i / 2.5) + 2 * math.sin(i / 1.3) for i in range(65)]
    series = _series_with_closes("AAA", dates, closes)
    folds = build_folds(dates[0], dates[-1], is_window=20, oos_window=15)
    grid = ParameterGrid(({"fast": 2.0, "slow": 5.0}, {"fast": 3.0, "slow": 5.0}))
    factory = _sma_factory

    result = run_walkforward(
        {"AAA": series}, factory, grid, folds, warmup=5, costs=_FREE, slippage=_NO_SLIP, cap=0.10
    )

    assert result.n_folds == 3
    assert result.grid_size == 2
    assert len(result.oos_equity) == len(result.oos_dates)
    assert list(result.oos_dates) == [d for d in dates if d >= folds[0].oos_start]

    offset = 0
    for fold_result in result.folds:
        composite, tail_len = _naive_composite(series, fold_result.fold, warmup=5)
        isolated = run_backtest_multi(
            {"AAA": composite},
            {"AAA": factory(fold_result.selected_params)},
            initial_cash=100_000.0,
            costs=_FREE,
            slippage=_NO_SLIP,
            cap=0.10,
        )
        segment = isolated.equity_curve[tail_len:]
        assert segment == pytest.approx(result.oos_equity[offset : offset + len(segment)])
        offset += len(segment)
    assert offset == len(result.oos_equity)


@pytest.mark.unit
def test_oos_uses_params_selected_in_same_fold() -> None:
    """CA-02.2 — o OOS do fold k roda com os params selecionados no IS do fold k.

    A seleção do engine confere com o argmax INDEPENDENTE do sharpe IS por
    fold (re-derivado naive); e o segmento OOS do fold reproduz o run OOS
    isolado com ESSES params — e NÃO reproduz com os params alternativos do
    grid (os trades de cada params são identificáveis pela data de entrada).
    """
    dates = _business_dates(date(2024, 1, 1), 50)
    closes = [
        100,
        101,
        102,
        103,
        100,
        97,
        94,
        97,
        100,
        103,
        106,
        109,
        112,
        115,
        118,
        121,
        124,
        127,
        130,
        133,
        136,
        139,
        142,
        145,
        148,
        151,
        154,
        157,
        160,
        163,
        166,
        169,
        172,
        175,
        178,
        181,
        184,
        187,
        190,
        193,
        196,
        199,
        202,
        205,
        208,
        211,
        214,
        217,
        220,
        223,
    ]
    series = _series_with_closes("AAA", dates, closes)
    folds = build_folds(dates[0], dates[-1], is_window=20, oos_window=15)
    grid = ParameterGrid(({"enter_at": 2.0}, {"enter_at": 5.0}))
    factory = _enter_at_factory

    result = run_walkforward(
        {"AAA": series}, factory, grid, folds, warmup=1, costs=_FREE, slippage=_NO_SLIP, cap=0.10
    )

    assert len(result.folds) == 2
    # Seleção = argmax independente do sharpe IS por fold (R5/CA-02.3).
    naive = _naive_select(series, folds, grid, factory)
    for fold_result, expected in zip(result.folds, naive, strict=True):
        assert fold_result.selected_params == expected

    offset = 0
    for fold_result in result.folds:
        fold = fold_result.fold
        selected = fold_result.selected_params
        composite, tail_len = _naive_composite(series, fold, warmup=1)

        # O segmento OOS do fold reproduz o run OOS ISOLADO com os params selecionados.
        isolated = run_backtest_multi(
            {"AAA": composite},
            {"AAA": factory(selected)},
            initial_cash=100_000.0,
            costs=_FREE,
            slippage=_NO_SLIP,
            cap=0.10,
        )
        segment = isolated.equity_curve[tail_len:]
        assert segment == pytest.approx(result.oos_equity[offset : offset + len(segment)])

        # E NÃO reproduz com o params alternativo — prova que o OOS usou os
        # params do IS DO MESMO fold, não qualquer um do grid.
        other = next(p for p in grid.params if p != selected)
        other_run = run_backtest_multi(
            {"AAA": composite},
            {"AAA": factory(other)},
            initial_cash=100_000.0,
            costs=_FREE,
            slippage=_NO_SLIP,
            cap=0.10,
        )
        other_segment = other_run.equity_curve[tail_len:]
        assert other_segment != pytest.approx(segment)

        offset += len(segment)
    assert offset == len(result.oos_equity)


@pytest.mark.unit
def test_walkforward_is_deterministic_across_runs() -> None:
    """RNF-01 — dois runs com a MESMA entrada produzem params por fold,
    equity OOS e datas OOS IDÊNTICOS (multi-ativo)."""
    dates = _business_dates(date(2024, 1, 1), 65)
    closes = [100 + 6 * math.sin(i / 2.5) + 2 * math.sin(i / 1.3) for i in range(65)]
    series = {
        "AAA": _series_with_closes("AAA", dates, closes),
        "BBB": _series_with_closes("BBB", dates, [c * 1.1 for c in closes]),
    }
    folds = build_folds(dates[0], dates[-1], is_window=20, oos_window=15)
    grid = ParameterGrid(({"fast": 2.0, "slow": 5.0}, {"fast": 3.0, "slow": 5.0}))
    factory = _sma_factory

    kwargs: dict[str, Any] = dict(
        series=series,
        strategy_factory=factory,
        grid=grid,
        folds=folds,
        warmup=5,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
    )
    first = run_walkforward(**kwargs)
    second = run_walkforward(**kwargs)

    assert first == second
    assert [fr.selected_params for fr in first.folds] == [fr.selected_params for fr in second.folds]
    assert first.oos_equity == second.oos_equity
    assert first.oos_dates == second.oos_dates


@pytest.mark.unit
def test_run_walkforward_warmup_mismatch_raises_engine_error() -> None:
    """§3.8 — pré-condições nomeadas: `strategy.warmup != warmup` e janela IS
    menor que o warmup ⇒ EngineError claro (o erro aponta a causa)."""
    dates = _business_dates(date(2024, 1, 1), 50)
    series = {"AAA": _series_with_closes("AAA", dates, [100.0 + i for i in range(50)])}
    folds = build_folds(dates[0], dates[-1], is_window=20, oos_window=15)

    # 1. strategy.warmup != warmup declarado — a cauda desalinha com o gate.
    with pytest.raises(EngineError, match=r"strategy\.warmup=3 != warmup=1"):
        run_walkforward(
            series,
            lambda p: EnterAtStrategy(enter_at=2, warmup=3),
            ParameterGrid(({"enter_at": 2.0},)),
            folds,
            warmup=1,
        )

    # 2. Janela IS < warmup — a estratégia não aquece dentro do próprio IS.
    tiny_is = build_folds(dates[0], dates[-1], is_window=2, oos_window=15)
    with pytest.raises(EngineError, match="janela IS"):
        run_walkforward(
            series,
            lambda p: EnterAtStrategy(enter_at=2, warmup=5),
            ParameterGrid(({"enter_at": 2.0},)),
            tiny_is,
            warmup=5,
        )


@pytest.mark.unit
def test_walkforward_domain_errors_raise_engine_error() -> None:
    """§3.8 — universo vazio, folds vazio e fold artesanal inválido ⇒ EngineError."""
    dates = _business_dates(date(2024, 1, 1), 50)
    series = {"AAA": _series_with_closes("AAA", dates, [100.0 + i for i in range(50)])}
    folds = build_folds(dates[0], dates[-1], is_window=20, oos_window=15)
    grid = ParameterGrid(({"enter_at": 2.0},))
    factory = _enter_at_factory

    with pytest.raises(EngineError, match="universo vazio"):
        run_walkforward({}, factory, grid, folds, warmup=1)
    with pytest.raises(EngineError, match="folds vazio"):
        run_walkforward(series, factory, grid, (), warmup=1)
    with pytest.raises(EngineError, match=r"warmup=.* < 0"):
        run_walkforward(series, factory, grid, folds, warmup=-1)

    # Fold artesanal com oos_start ≠ dia útil seguinte a is_end (tile quebrado).
    bad_fold = Fold(
        is_start=dates[0],
        is_end=dates[19],
        oos_start=_add_business_days(dates[19], 2),
        oos_end=dates[40],
    )
    with pytest.raises(EngineError, match="dia útil seguinte"):
        run_walkforward(series, factory, grid, (bad_fold,), warmup=1)

    # Fold artesanal com is_end >= oos_start (IS/OOS sobrepostos dentro do fold).
    overlapping = Fold(
        is_start=dates[0],
        is_end=dates[30],
        oos_start=dates[20],
        oos_end=dates[40],
    )
    with pytest.raises(EngineError, match="is_start <= is_end < oos_start"):
        run_walkforward(series, factory, grid, (overlapping,), warmup=1)


@pytest.mark.unit
def test_walkforward_harness_reports_per_fold_and_total_budgets() -> None:
    """CA-05.1 — o harness mede o tempo por fold (IS+OOS) e total contra os
    orçamentos DECLARADOS (design §3.6: 30 s por fold; total n_folds x 30 s +
    margem) e o run não é alterado pela medição."""
    dates = _business_dates(date(2024, 1, 1), 65)
    closes = [100 + 6 * math.sin(i / 2.5) + 2 * math.sin(i / 1.3) for i in range(65)]
    series = {"AAA": _series_with_closes("AAA", dates, closes)}
    folds = build_folds(dates[0], dates[-1], is_window=20, oos_window=15)
    grid = ParameterGrid(({"fast": 2.0, "slow": 5.0}, {"fast": 3.0, "slow": 5.0}))
    factory = _sma_factory
    kwargs: dict[str, Any] = dict(
        series=series,
        strategy_factory=factory,
        grid=grid,
        folds=folds,
        warmup=5,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
    )

    result, report = measure_walkforward(**kwargs)

    # A medição nunca altera o run: mesma saída do run puro.
    assert result == run_walkforward(**kwargs)

    assert report.per_fold_budget_s == PER_FOLD_BUDGET_S == 30.0
    assert report.total_budget_s == pytest.approx(result.n_folds * 30.0 + TOTAL_BUDGET_MARGIN_S)
    assert len(report.per_fold_s) == result.n_folds == 3
    assert all(t >= 0 for t in report.per_fold_s)
    assert report.total_s >= sum(report.per_fold_s)  # total inclui overhead entre folds
    assert isinstance(report.within_budget, bool)
    assert report.within_budget  # run minúsculo: segundos muito abaixo de 30 s
