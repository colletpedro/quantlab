"""A8 — imutabilidade da `PriceSeries` (design §3.7 e §4.1).

Unitários: a `PriceSeries` é value object puro e se constrói sem banco.

O design é explícito em exigir **duas** medidas, não uma. Cada teste aqui
prende uma delas, e mais um prende a rota do `.base` que design §4.1 documenta
como a razão de os arrays-mãe serem marcados na materialização.
"""

from dataclasses import FrozenInstanceError
from datetime import date

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.exceptions import DataError
from quantlab.storage.series import PriceSeries

_DATES = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]


def _series() -> PriceSeries:
    dates: NDArray[np.object_] = np.empty(len(_DATES), dtype=object)
    dates[:] = _DATES
    return PriceSeries(
        ticker="TEST",
        dates=dates,
        open=np.array([100.0, 101.0, 102.0]),
        high=np.array([105.0, 106.0, 107.0]),
        low=np.array([99.0, 100.0, 101.0]),
        close=np.array([104.0, 105.0, 106.0]),
        volume=np.array([1_000.0, 2_000.0, 3_000.0]),
        adjusted=True,
        hash="0" * 64,
    )


@pytest.mark.unit
@pytest.mark.parametrize("field", ["dates", "open", "high", "low", "close", "volume"])
def test_writing_to_any_array_raises(field: str) -> None:
    """A8 — tentativa de escrita em qualquer array levanta `ValueError`."""
    series = _series()
    array: NDArray[np.float64] = getattr(series, field)

    with pytest.raises(ValueError, match="read-only"):
        array[0] = 999.0


@pytest.mark.unit
@pytest.mark.parametrize("field", ["dates", "open", "high", "low", "close", "volume"])
def test_arrays_report_themselves_as_read_only(field: str) -> None:
    """A flag é o mecanismo que design §3.7 especifica, não um efeito colateral."""
    array: NDArray[np.float64] = getattr(_series(), field)
    assert array.flags.writeable is False


@pytest.mark.unit
def test_reassigning_an_attribute_raises() -> None:
    """`frozen=True` — a outra metade da imutabilidade.

    Sem isto, trocar a referência do array inteiro passaria, e a série
    read-only não protegeria nada.
    """
    series = _series()
    with pytest.raises(FrozenInstanceError):
        series.close = np.array([1.0, 2.0, 3.0])  # type: ignore[misc]  # é o que o teste prova


@pytest.mark.unit
def test_slices_inherit_the_read_only_flag() -> None:
    """A fatia que a `MarketView` vai entregar à estratégia também é imutável.

    Uma fatia de numpy é view do array-mãe e herda a flag. É por isso que
    marcar o array-mãe uma vez, na materialização, basta.
    """
    window = _series().close[:2]
    assert window.flags.writeable is False
    with pytest.raises(ValueError, match="read-only"):
        window[0] = 1.0


@pytest.mark.unit
def test_mutation_through_the_base_attribute_is_blocked() -> None:
    """Design §4.1 — a rota do `.base`, que não dá para remover.

    Toda view de numpy expõe `.base`, apontando para o array-mãe completo
    (incluindo o futuro). Marcar o array-mãe como somente leitura não esconde
    o atributo, mas fecha a **mutação** por qualquer caminho.

    A **leitura** do futuro por `.base` continua possível, e o design declara
    isso: é proteção contra acidente, não contra adversário. O teste grava a
    limitação onde ela não se perde.
    """
    series = _series()
    window = series.close[:1]
    parent = window.base

    assert parent is not None
    # A rota existe e enxerga o futuro — isto é a limitação declarada.
    assert len(parent) == 3
    # Mas escrever por ela falha.
    with pytest.raises(ValueError, match="read-only"):
        parent[2] = 999.0


@pytest.mark.unit
def test_misaligned_arrays_are_rejected() -> None:
    """Série com colunas de comprimentos diferentes não é série."""
    dates: NDArray[np.object_] = np.empty(3, dtype=object)
    dates[:] = _DATES

    with pytest.raises(DataError, match="desalinhada"):
        PriceSeries(
            ticker="TEST",
            dates=dates,
            open=np.array([100.0]),
            high=np.array([105.0, 106.0, 107.0]),
            low=np.array([99.0, 100.0, 101.0]),
            close=np.array([104.0, 105.0, 106.0]),
            volume=np.array([1_000.0, 2_000.0, 3_000.0]),
            adjusted=True,
            hash="0" * 64,
        )


@pytest.mark.unit
def test_dates_are_calendar_dates_not_numpy_datetimes() -> None:
    """RNF-07 — `datetime64` reintroduziria instante e fuso pela porta dos fundos."""
    series = _series()
    assert all(type(value) is date for value in series.dates)


@pytest.mark.unit
def test_length_and_bounds_reflect_the_series() -> None:
    """Conveniências de leitura, sem expor os arrays."""
    series = _series()
    assert len(series) == 3
    assert series.start == date(2024, 1, 2)
    assert series.end == date(2024, 1, 4)


@pytest.mark.unit
def test_empty_series_has_no_bounds() -> None:
    """Série vazia devolve `None` em vez de estourar índice."""
    empty = PriceSeries(
        ticker="TEST",
        dates=np.empty(0, dtype=object),
        open=np.array([]),
        high=np.array([]),
        low=np.array([]),
        close=np.array([]),
        volume=np.array([]),
        adjusted=False,
        hash="0" * 64,
    )
    assert len(empty) == 0
    assert empty.start is None
    assert empty.end is None
