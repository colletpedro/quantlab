"""T05 — calendário-união (design §3.1/§5, D1, RF-POR-02/05).

Fixtures de papel com derivação auditável (RNF-03); paridade com busca
ingênua por (data, ativo) em fixture pequena — CA-02.1.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import numpy as np
import pytest

from quantlab.engine.calendar import UnionCalendar
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries


def _series(ticker: str, days: list[int]) -> PriceSeries:
    """Série sintética: 1 barra por dia (dias absolutos desde 2020-01-01)."""
    dates = [date(2020, 1, 1) + timedelta(days=d) for d in days]
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


def _naive_bar_index(own_dates: list[date], day: date) -> int | None:
    """Busca ingênua por (data, ativo) — o contraponto O(n²) da paridade."""
    for j, own_day in enumerate(own_dates):
        if own_day == day:
            return j
    return None


def _naive_last_known(own_dates: list[date], day: date) -> int | None:
    last: int | None = None
    for j, own_day in enumerate(own_dates):
        if own_day <= day:
            last = j
    return last


# ─── paridade com a busca ingênua (CA-02.1) ─────────────────────────────────


@pytest.mark.unit
def test_union_calendar_matches_naive_lookup() -> None:
    """CA-02.1 — `bar_index`/`last_known` batem com busca ingênua (data, ativo).

    Fixture pequena com datas desalinhadas e um IPO: AAA4 começa no dia 2,
    BBBB3 tem um halt (falta o dia 5), CCCC2 cobre a janela toda.
    """
    assets = {
        "AAA4": _series("AAA4", [2, 3, 4, 6, 7]),
        "BBBB3": _series("BBBB3", [0, 1, 2, 3, 4, 6, 7, 8]),
        "CCCC2": _series("CCCC2", [0, 1, 2, 3, 4, 5, 6, 7, 8]),
    }
    calendar = UnionCalendar.build(assets)

    own_dates = {ticker: [d for d in s.dates] for ticker, s in assets.items()}

    for u, day in enumerate(calendar.dates):
        for ticker, own in own_dates.items():
            assert calendar.has_bar_at(ticker, u) == (_naive_bar_index(own, day) is not None)
            assert calendar.bar_index_at(ticker, u) == _naive_bar_index(own, day)
            assert calendar.last_known_index_at(ticker, u) == _naive_last_known(own, day)

    # União ordenada e sem duplicata.
    assert list(calendar.dates) == sorted(set(calendar.dates))
    assert len(calendar.dates) == 9  # dias 0..8


@pytest.mark.unit
def test_bar_index_is_index_of_own_array_not_union() -> None:
    """POR-05.1 — `bar_index` devolve índice do PRÓPRIO ativo, nunca da união.

    AAA4 estreia no dia 2: na data-união u=2, o índice do próprio array é 0
    (não 2) — é o que o `MarketView` de AAA4 usa para fatiar a série dele.
    """
    calendar = UnionCalendar.build(
        {
            "AAA4": _series("AAA4", [2, 3, 4]),
            "BBBB3": _series("BBBB3", [0, 1, 2, 3, 4]),
        }
    )

    u_of_day_2 = calendar.dates.index(date(2020, 1, 3))  # dia 2
    assert calendar.bar_index_at("AAA4", u_of_day_2) == 0
    assert calendar.bar_index_at("BBBB3", u_of_day_2) == 2

    # last_known segue o array próprio: na estreia de AAA4, ainda None antes.
    assert calendar.last_known_index_at("AAA4", u_of_day_2 - 1) is None
    assert calendar.last_known_index_at("AAA4", u_of_day_2) == 0


# ─── bordas (POR-02.2/02.3, SIZ-02.4/R2 — barra nunca fabricada) ────────────


@pytest.mark.unit
def test_borders_ipo_halt_delist_and_never_traded() -> None:
    """Bordas sem fabricar barra: IPO, halt, deslistagem, ativo sem barra."""
    calendar = UnionCalendar.build(
        {
            # IPO: estreia no dia 4.
            "IPO1": _series("IPO1", [4, 5, 6, 7]),
            # Halt: falta o dia 5 (buraco no meio).
            "HLT2": _series("HLT2", [0, 1, 2, 3, 4, 6, 7, 8]),
            # Deslistagem: última barra no dia 5 de 9.
            "DEL3": _series("DEL3", [0, 1, 2, 3, 4, 5]),
            # Nunca negociado na janela (R2/SIZ-02.4): zero barras.
            "ZRO4": _series("ZRO4", []),
            # Testemunha que cobre a janela toda.
            "FULL5": _series("FULL5", list(range(9))),
        }
    )

    u_day = {day: calendar.dates.index(date(2020, 1, 1 + day)) for day in range(9)}

    # IPO — antes da 1ª barra: sem barra, sem last_known.
    assert calendar.bar_index_at("IPO1", u_day[3]) is None
    assert calendar.last_known_index_at("IPO1", u_day[3]) is None
    assert not calendar.has_bar_at("IPO1", u_day[3])
    assert calendar.bar_index_at("IPO1", u_day[4]) == 0

    # Halt — no buraco, last_known deriva do último índice válido (próprio).
    assert calendar.bar_index_at("HLT2", u_day[5]) is None
    assert calendar.last_known_index_at("HLT2", u_day[5]) == 4
    assert calendar.bar_index_at("HLT2", u_day[6]) == 5

    # Deslistagem — depois da última barra, last_known fica na última.
    assert calendar.bar_index_at("DEL3", u_day[7]) is None
    assert calendar.last_known_index_at("DEL3", u_day[7]) == 5
    assert calendar.last_known_index_at("DEL3", u_day[8]) == 5

    # Nunca negociado — nunca barra, nunca last_known (contribui zero).
    for u in range(len(calendar.dates)):
        assert not calendar.has_bar_at("ZRO4", u)
        assert calendar.bar_index_at("ZRO4", u) is None
        assert calendar.last_known_index_at("ZRO4", u) is None


# ─── pureza e linearidade (D1 — guarda do RNF-04) ───────────────────────────


@pytest.mark.unit
def test_union_calendar_build_is_pure_and_linear() -> None:
    """D1 — (i) função pura: mesmo input ⇒ estrutura idêntica; (ii) custo linear.

    (ii) é guarda de regressão de O(n²): 4x o total de barras deve custar
    ≪ 16x (o custo quadrático daria ~16x). Medição com o melhor de 3 e
    folga generosa para não flakear no CI.
    """
    base = {f"T{i:02d}": _series(f"T{i:02d}", list(range(200))) for i in range(10)}
    grown = {f"T{i:02d}": _series(f"T{i:02d}", list(range(800))) for i in range(10)}

    # (i) pureza — duas construções produzem estruturas idênticas.
    first = UnionCalendar.build(base)
    second = UnionCalendar.build(base)
    assert first.dates == second.dates
    for ticker in base:
        assert np.array_equal(first.bar_index[ticker], second.bar_index[ticker])
        assert np.array_equal(first.last_known[ticker], second.last_known[ticker])

    # (ii) linearidade — best-of-3 de cada tamanho.
    def best_of_three(series: dict[str, PriceSeries]) -> float:
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            UnionCalendar.build(series)
            best = min(best, time.perf_counter() - start)
        return best

    time_base = best_of_three(base)
    time_grown = best_of_three(grown)
    # 4x de dados; folga 2.5x sobre o fator 4 esperado (quadrático daria ~16).
    assert time_grown < time_base * 10.0, (
        f"build não escalou linearmente: {time_base:.4f}s → {time_grown:.4f}s (4x dados)"
    )


@pytest.mark.unit
def test_union_calendar_arrays_are_immutable() -> None:
    """D1 — escrita em `bar_index`/`last_known` levanta ValueError."""
    calendar = UnionCalendar.build({"AAA4": _series("AAA4", [0, 1, 2])})

    with pytest.raises(ValueError):
        calendar.bar_index["AAA4"][0] = 99  # array read-only (writeable=False)
    with pytest.raises(ValueError):
        calendar.last_known["AAA4"][0] = 99  # array read-only (writeable=False)


# ─── erros de domínio (§3.8 — EngineError / KeyError) ───────────────────────


@pytest.mark.unit
def test_union_calendar_domain_errors() -> None:
    """§3.8 — série vazia e índice de união fora de [0, len) são EngineError;
    ticker fora do run é KeyError (contrato do design)."""
    with pytest.raises(EngineError):
        UnionCalendar.build({})

    calendar = UnionCalendar.build({"AAA4": _series("AAA4", [0, 1, 2])})

    with pytest.raises(EngineError):
        calendar.has_bar_at("AAA4", -1)
    with pytest.raises(EngineError):
        calendar.bar_index_at("AAA4", len(calendar.dates))
    with pytest.raises(EngineError):
        calendar.last_known_index_at("AAA4", 99)

    with pytest.raises(KeyError):
        calendar.bar_index_at("ZZZZ9", 0)
