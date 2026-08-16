"""T10 — walk-forward: folds, grade determinística e sharpe único (design §3.6, ADR-0011).

Fixtures de papel com derivação auditável (RNF-03); datas de calendário
naive (RNF-07). As janelas dos folds cruzam fim de semana de propósito — a
semântica "dia útil" (seg-sex, decisão local T10) só é exercitada se houver
weekend no meio; numa janela seg-sex pura, dias corridos e dias úteis
coincidiriam e o teste passaria "vazio".
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from itertools import pairwise
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from quantlab.analytics.metrics import sharpe
from quantlab.engine.calendar import UnionCalendar
from quantlab.engine.market_view import MarketView
from quantlab.engine.walkforward import (
    ParameterGrid,
    build_folds,
    sharpe_annualized_rf0,
)
from quantlab.exceptions import EngineError, InsufficientHistoryError
from quantlab.storage.series import PriceSeries


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
