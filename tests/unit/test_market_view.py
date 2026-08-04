"""C1 — `MarketView` (ENG-01.3, design §4.1).

Séries de papel, sem banco (RNF-03). O engine inteiro é testável assim: ele
recebe uma `PriceSeries` já materializada e não conhece MongoDB.
"""

from datetime import date

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.engine.market_view import MarketView
from quantlab.exceptions import EngineError, InsufficientHistoryError
from quantlab.storage.series import PriceSeries

_DATES = [date(2024, 1, day) for day in (2, 3, 4, 5, 8)]


def _series() -> PriceSeries:
    dates: NDArray[np.object_] = np.empty(len(_DATES), dtype=object)
    dates[:] = _DATES
    return PriceSeries(
        ticker="TEST",
        dates=dates,
        open=np.array([10.0, 11.0, 12.0, 13.0, 14.0]),
        high=np.array([15.0, 16.0, 17.0, 18.0, 19.0]),
        low=np.array([5.0, 6.0, 7.0, 8.0, 9.0]),
        close=np.array([100.0, 110.0, 120.0, 130.0, 140.0]),
        volume=np.array([1_000.0, 2_000.0, 3_000.0, 4_000.0, 5_000.0]),
        adjusted=True,
        hash="0" * 64,
    )


# ─── ENG-01.3: a janela para em `i` ──────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("index", [0, 1, 2, 3, 4])
def test_every_accessor_stops_at_the_current_bar(index: int) -> None:
    """O núcleo de ENG-01.3: nenhum acessor devolve barra de índice > i."""
    view = MarketView(_series(), index)

    for field in ("open", "high", "low", "close", "volume", "dates"):
        assert len(getattr(view, field)) == index + 1, field


@pytest.mark.unit
def test_close_returns_exactly_the_past_and_the_present() -> None:
    """Valores conferidos à mão contra a série de papel."""
    view = MarketView(_series(), 2)

    assert list(view.close) == pytest.approx([100.0, 110.0, 120.0])
    assert list(view.open) == pytest.approx([10.0, 11.0, 12.0])
    assert list(view.dates) == [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]


@pytest.mark.unit
def test_current_bar_is_visible_not_hidden() -> None:
    """`i` está DENTRO da janela — a decisão de D usa o fechamento de D.

    ADR-0002 não proíbe usar o fechamento da barra corrente; proíbe
    *executar* nela. Esconder `close[i]` da estratégia quebraria a SMA cross
    sem necessidade.
    """
    view = MarketView(_series(), 1)

    assert float(view.close[-1]) == pytest.approx(110.0)
    assert view.date == date(2024, 1, 3)
    assert len(view) == 2


@pytest.mark.unit
def test_last_bar_of_the_series_sees_everything() -> None:
    view = MarketView(_series(), 4)
    assert len(view.close) == 5


@pytest.mark.unit
def test_index_outside_the_series_is_rejected() -> None:
    for bad in (-1, 5, 99):
        with pytest.raises(EngineError, match="fora da série"):
            MarketView(_series(), bad)


# ─── `last()` ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_last_returns_the_n_most_recent_observations() -> None:
    view = MarketView(_series(), 3)

    assert list(view.last("close", 2)) == pytest.approx([120.0, 130.0])
    assert list(view.last("close", 4)) == pytest.approx([100.0, 110.0, 120.0, 130.0])


@pytest.mark.unit
def test_last_asking_for_more_than_available_raises_insufficient_history() -> None:
    """Design §4.1 — o nome importa: histórico insuficiente, não lookahead.

    Na barra 1 existem 2 barras. Pedir 3 é `warmup` mal declarado, não
    tentativa de ler o futuro — e a mensagem diz exatamente o que ajustar.
    """
    view = MarketView(_series(), 1)

    with pytest.raises(InsufficientHistoryError, match="warmup"):
        view.last("close", 3)


@pytest.mark.unit
def test_insufficient_history_is_an_engine_error() -> None:
    """Pertence à hierarquia do projeto (CLAUDE.md §3), não a `Exception` cru."""
    assert issubclass(InsufficientHistoryError, EngineError)


@pytest.mark.unit
def test_last_exactly_at_the_limit_is_allowed() -> None:
    """`n == i + 1` é o histórico inteiro disponível: legítimo, não erro."""
    view = MarketView(_series(), 2)
    assert len(view.last("close", 3)) == 3


@pytest.mark.unit
def test_last_rejects_unknown_field_by_name() -> None:
    """Typo vira erro nomeado, não `AttributeError` de dentro do numpy."""
    view = MarketView(_series(), 4)

    with pytest.raises(EngineError, match="Campo desconhecido"):
        view.last("clsoe", 2)


@pytest.mark.unit
@pytest.mark.parametrize("n", [0, -1])
def test_last_rejects_non_positive_n(n: int) -> None:
    view = MarketView(_series(), 4)

    with pytest.raises(EngineError, match="n >= 1"):
        view.last("close", n)


# ─── superfície mínima ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_view_does_not_expose_the_series_or_the_max_index_publicly() -> None:
    """Design §4.1 — a API pública não oferece rota para o array completo.

    Não é encapsulamento forte (ver o teste de `.base` abaixo); é a superfície
    pública não convidar ao erro.
    """
    public = {name for name in dir(MarketView) if not name.startswith("_")}

    assert public == {
        "close",
        "date",
        "dates",
        "high",
        "i",
        "last",
        "low",
        "open",
        "ticker",
        "volume",
    }


@pytest.mark.unit
def test_view_rejects_extra_attributes() -> None:
    """`__slots__` — nem a estratégia pendura estado na view por acidente."""
    view = MarketView(_series(), 2)

    with pytest.raises(AttributeError):
        view.smuggled = 42  # type: ignore[attr-defined]  # é o que o teste prova


# ─── a rota do `.base`: a limitação declarada, gravada na suíte ──────────────


@pytest.mark.unit
def test_slices_are_views_not_copies() -> None:
    """Fatiamento na origem é O(1): view, não cópia (design §4.1, item 1).

    Se virasse cópia, o laço de barras passaria a O(n²) em tempo e memória —
    é o custo que a alternativa descartada de §4.1 pagaria.
    """
    series = _series()
    view = MarketView(series, 2)

    assert view.close.base is not None
    assert np.shares_memory(view.close, series.close)


@pytest.mark.unit
def test_mutation_through_base_is_blocked_but_reading_is_not() -> None:
    """ENG-01.3 — o teste que design §4.1 manda escrever, com a claim honesta.

    Toda view de numpy expõe `.base`, apontando para o array-mãe completo —
    incluindo as barras FUTURAS. Não há como remover esse atributo.

    O que o desenho garante, e este teste prova:
      - **mutação** por `.base` falha, porque a `PriceSeries` marcou os
        arrays-mãe como somente leitura na materialização;
      - **leitura** do futuro por `.base` é tecnicamente possível.

    A segunda metade é a limitação declarada de §4.1: proteção contra
    acidente, não contra adversário. Está gravada aqui de propósito — numa
    docstring de design ela se perde; num teste, não. Se a Fase 2 aceitar
    estratégias de terceiros, a alternativa de copiar a fatia volta à mesa e
    este teste é o que muda de assinatura primeiro.
    """
    series = _series()
    view = MarketView(series, 1)

    parent = view.close.base
    assert parent is not None

    # A rota existe e enxerga o futuro — 5 barras, não as 2 da janela.
    assert len(parent) == 5
    assert float(parent[4]) == pytest.approx(140.0)

    # Mas escrever por ela falha, por qualquer caminho.
    with pytest.raises(ValueError, match="read-only"):
        parent[4] = 999.0
    with pytest.raises(ValueError, match="read-only"):
        view.close[0] = 999.0


@pytest.mark.unit
def test_the_view_itself_is_read_only() -> None:
    """A fatia herda a flag do array-mãe — não precisa ser marcada de novo."""
    view = MarketView(_series(), 3)

    for field in ("open", "high", "low", "close", "volume", "dates"):
        assert getattr(view, field).flags.writeable is False, field
