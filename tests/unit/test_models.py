"""Validação dos objetos de domínio de storage — design §3.2 e §3.3.

Unitários: nenhum toca banco.

A validação está no construtor de propósito. Um evento corporativo meio
preenchido não estoura na hora — ele corrompe o fator de ajuste, e o resultado
é uma série de preços plausível e errada. Esse é o pior tipo de bug que este
projeto pode ter, porque parece informação.
"""

from datetime import date

import pytest

from quantlab.exceptions import DataError
from quantlab.storage.models import CorporateAction, CorporateActionKind, QuarantinedBar


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "kwargs"),
    [
        pytest.param(CorporateActionKind.DIVIDEND, {}, id="dividendo-sem-value"),
        pytest.param(CorporateActionKind.DIVIDEND, {"ratio": 2.0}, id="dividendo-com-ratio"),
        pytest.param(
            CorporateActionKind.DIVIDEND,
            {"value": 0.24, "ratio": 2.0},
            id="dividendo-com-os-dois",
        ),
        pytest.param(CorporateActionKind.SPLIT, {}, id="split-sem-ratio"),
        pytest.param(CorporateActionKind.SPLIT, {"value": 0.24}, id="split-com-value"),
        pytest.param(CorporateActionKind.DIVIDEND, {"value": 0.0}, id="dividendo-zero"),
        pytest.param(CorporateActionKind.DIVIDEND, {"value": -0.1}, id="dividendo-negativo"),
        pytest.param(CorporateActionKind.SPLIT, {"ratio": 0.0}, id="split-razao-zero"),
        pytest.param(CorporateActionKind.SPLIT, {"ratio": -1.0}, id="split-razao-negativa"),
    ],
)
def test_malformed_event_is_rejected_at_construction(
    kind: CorporateActionKind, kwargs: dict[str, float]
) -> None:
    """Nenhum evento inconsistente chega vivo ao cálculo do fator."""
    with pytest.raises(DataError):
        CorporateAction(ticker="AAPL", date=date(2024, 1, 15), kind=kind, **kwargs)


@pytest.mark.unit
def test_well_formed_events_are_accepted() -> None:
    """A validação não pode ser tão zelosa que rejeite o caso legítimo."""
    dividend = CorporateAction(
        ticker="AAPL",
        date=date(2024, 1, 15),
        kind=CorporateActionKind.DIVIDEND,
        value=0.24,
    )
    split = CorporateAction(
        ticker="AAPL",
        date=date(2020, 8, 31),
        kind=CorporateActionKind.SPLIT,
        ratio=4.0,
    )

    assert dividend.value == pytest.approx(0.24)
    assert dividend.ratio is None
    assert split.ratio == pytest.approx(4.0)
    assert split.value is None


@pytest.mark.unit
def test_split_ratio_below_one_is_valid() -> None:
    """Agrupamento é split de razão < 1 e não pode ser confundido com erro."""
    grouping = CorporateAction(
        ticker="XYZ",
        date=date(2024, 3, 1),
        kind=CorporateActionKind.SPLIT,
        ratio=0.1,
    )
    assert grouping.ratio == pytest.approx(0.1)


@pytest.mark.unit
def test_quarantined_bar_requires_at_least_one_reason() -> None:
    """Quarentena sem motivo é dado perdido: some do `bars` sem explicar por quê."""
    with pytest.raises(DataError, match="razão"):
        QuarantinedBar(
            ticker="XYZ",
            date=date(2024, 1, 2),
            raw={"close": -1.0},
            reasons=(),
        )


@pytest.mark.unit
def test_quarantined_bar_keeps_every_reason() -> None:
    """Design §3.3 — todas as regras violadas, não só a primeira."""
    entry = QuarantinedBar(
        ticker="XYZ",
        date=date(2024, 1, 2),
        raw={"open": 5.0, "high": 1.0, "low": 2.0, "close": -1.0},
        reasons=("high_below_low", "close_not_positive", "open_above_high"),
    )
    assert len(entry.reasons) == 3
