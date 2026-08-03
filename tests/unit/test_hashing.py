"""A9 — hash determinístico da série (PER-03.1, design §3.8)."""

from datetime import date

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.exceptions import DataError
from quantlab.storage.hashing import DECIMAL_PLACES, series_hash


def _array(*values: float) -> NDArray[np.float64]:
    return np.array(values, dtype=np.float64)


_DATES = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
_OPEN = _array(100.0, 101.0, 102.0)
_HIGH = _array(105.0, 106.0, 107.0)
_LOW = _array(99.0, 100.0, 101.0)
_CLOSE = _array(104.0, 105.0, 106.0)
_VOLUME = _array(1_000.0, 2_000.0, 3_000.0)


def _hash(close: NDArray[np.float64] | None = None) -> str:
    return series_hash(_DATES, _OPEN, _HIGH, _LOW, _CLOSE if close is None else close, _VOLUME)


@pytest.mark.unit
def test_same_series_produces_the_same_hash() -> None:
    """PER-03.1 — o hash é função só do conteúdo."""
    assert _hash() == _hash()


@pytest.mark.unit
def test_hash_is_stable_across_equal_but_distinct_arrays() -> None:
    """Arrays diferentes com os mesmos números dão o mesmo hash.

    O hash não pode depender de identidade de objeto nem de layout de memória
    — só do que a série contém.
    """
    other = series_hash(
        list(_DATES),
        _array(100.0, 101.0, 102.0),
        _array(105.0, 106.0, 107.0),
        _array(99.0, 100.0, 101.0),
        _array(104.0, 105.0, 106.0),
        _array(1_000.0, 2_000.0, 3_000.0),
    )
    assert other == _hash()


@pytest.mark.unit
def test_one_hundredth_of_a_cent_changes_the_hash() -> None:
    """A verificação que a tarefa A9 pede explicitamente.

    0.0001 é representável nas 6 casas da forma canônica, então a diferença
    sobrevive ao arredondamento e o hash muda.
    """
    nudged = _array(104.0, 105.0 + 0.0001, 106.0)
    assert _hash(nudged) != _hash()


@pytest.mark.unit
def test_difference_below_the_canonical_precision_does_not_change_the_hash() -> None:
    """O outro lado da moeda, e a razão de existir o arredondamento.

    Uma diferença na 12a casa é ruído de ponto flutuante, não mudança de dado.
    Se ela mudasse o hash, a reprodutibilidade que o hash existe para provar
    seria exatamente o que ele quebraria (design §3.8).
    """
    noise = _array(104.0, 105.0 + 1e-12, 106.0)
    assert _hash(noise) == _hash()


@pytest.mark.unit
def test_changing_the_date_changes_the_hash() -> None:
    """A data faz parte da representação canônica."""
    shifted = series_hash(
        [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 5)],
        _OPEN,
        _HIGH,
        _LOW,
        _CLOSE,
        _VOLUME,
    )
    assert shifted != _hash()


@pytest.mark.unit
def test_reordering_rows_changes_the_hash() -> None:
    """A ordem por data é parte da canonicalização, não detalhe de iteração."""
    reversed_series = series_hash(
        list(reversed(_DATES)),
        _OPEN[::-1].copy(),
        _HIGH[::-1].copy(),
        _LOW[::-1].copy(),
        _CLOSE[::-1].copy(),
        _VOLUME[::-1].copy(),
    )
    assert reversed_series != _hash()


@pytest.mark.unit
def test_every_field_participates_in_the_hash() -> None:
    """Um campo fora da canonicalização seria uma mudança invisível ao hash."""
    baseline = _hash()
    bumped = {
        "open": series_hash(_DATES, _array(1.0, 101.0, 102.0), _HIGH, _LOW, _CLOSE, _VOLUME),
        "high": series_hash(_DATES, _OPEN, _array(1.0, 106.0, 107.0), _LOW, _CLOSE, _VOLUME),
        "low": series_hash(_DATES, _OPEN, _HIGH, _array(1.0, 100.0, 101.0), _CLOSE, _VOLUME),
        "close": series_hash(_DATES, _OPEN, _HIGH, _LOW, _array(1.0, 105.0, 106.0), _VOLUME),
        "volume": series_hash(_DATES, _OPEN, _HIGH, _LOW, _CLOSE, _array(1.0, 2_000.0, 3_000.0)),
    }
    for field, digest in bumped.items():
        assert digest != baseline, f"mudar {field} não mudou o hash"
    assert len(set(bumped.values())) == len(bumped), "campos distintos colidiram"


@pytest.mark.unit
def test_negative_zero_hashes_like_positive_zero() -> None:
    """`f"{-0.0:.6f}"` é "-0.000000" e difere de "0.000000".

    Zero negativo não deveria aparecer em preço, mas é exatamente o tipo de
    diferença de última casa que design §3.8 quer neutralizar.
    """
    positive = series_hash(_DATES, _OPEN, _HIGH, _LOW, _array(0.0, 105.0, 106.0), _VOLUME)
    negative = series_hash(_DATES, _OPEN, _HIGH, _LOW, _array(-0.0, 105.0, 106.0), _VOLUME)
    assert positive == negative


@pytest.mark.unit
def test_hash_is_a_sha256_hex_digest() -> None:
    """64 caracteres hexadecimais — SHA-256, como design §3.8 especifica."""
    digest = _hash()
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


@pytest.mark.unit
def test_empty_series_has_a_stable_hash() -> None:
    """Série vazia não estoura e tem hash reprodutível."""
    empty = series_hash([], _array(), _array(), _array(), _array(), _array())
    assert len(empty) == 64
    assert empty == series_hash([], _array(), _array(), _array(), _array(), _array())


@pytest.mark.unit
def test_misaligned_series_is_rejected() -> None:
    """Hash de série desalinhada seria um número sem significado."""
    with pytest.raises(DataError, match="desalinhada"):
        series_hash(_DATES, _OPEN, _HIGH, _LOW, _CLOSE, _array(1_000.0))


@pytest.mark.unit
def test_canonical_precision_is_six_places() -> None:
    """Trava o número que design §3.8 fixa; mudá-lo invalida todo hash gravado."""
    assert DECIMAL_PLACES == 6
