"""B2 — fronteira de entrada: `pd.Timestamp` vira `datetime.date` (ING-01.3).

Unitários, sem banco e sem provedor real — fixtures de `pd.DataFrame`/`pd.Series`
construídas à mão, exatamente como B1 constrói `pd.DataFrame` em `FakeProvider`.
"""

from datetime import UTC, date, timezone

import pandas as pd
import pytest

from quantlab.exceptions import DataError
from quantlab.ingestion.normalizer import (
    normalize_corporate_actions,
    normalize_prices,
    normalize_timestamp,
)
from quantlab.ingestion.provider import RawCorporateActions
from quantlab.storage.models import CorporateActionKind


@pytest.mark.unit
def test_naive_and_tz_aware_timestamps_produce_the_same_date() -> None:
    """O critério de verificação que B2 pede explicitamente."""
    naive = pd.Timestamp(2024, 1, 2)
    # -05:00 é o offset de US/Eastern no inverno (sem DST) — o caso comum
    # para o índice de preços diários que yfinance devolve.
    aware = pd.Timestamp(2024, 1, 2, tz=timezone(pd.Timedelta(hours=-5)))

    assert normalize_timestamp(naive) == normalize_timestamp(aware) == date(2024, 1, 2)


@pytest.mark.unit
def test_positive_offset_crossing_midnight_lands_on_the_utc_day() -> None:
    """O caso que justifica converter para UTC antes de descartar a hora.

    00:30 do dia 2 em UTC+9 é 15:30 do dia 1 em UTC — offset positivo
    SUBTRAI horas na conversão para UTC, então o dia pode retroceder. Sem
    converter para UTC primeiro, `.date()` ingenuamente devolveria o dia 2 —
    um dia adiantado em relação ao que fica gravado. Ainda que o universo
    desta fase seja só americano (offsets negativos, onde isso não acontece
    na prática), a função precisa estar certa de qualquer forma.
    """
    early_local = pd.Timestamp(2024, 1, 2, 0, 30, tz=timezone(pd.Timedelta(hours=9)))
    assert normalize_timestamp(early_local) == date(2024, 1, 1)


@pytest.mark.unit
def test_utc_timestamp_round_trips_to_the_same_day() -> None:
    utc_ts = pd.Timestamp(2024, 6, 15, 12, 0, tz=UTC)
    assert normalize_timestamp(utc_ts) == date(2024, 6, 15)


@pytest.mark.unit
def test_normalize_prices_converts_every_row() -> None:
    """DataFrame bruto de duas barras vira duas `Bar`, na ordem, com data certa."""
    raw = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [105.0, 106.0],
            "Low": [99.0, 100.0],
            "Close": [104.0, 105.0],
            "Volume": [1_000, 2_000],
        },
        index=pd.DatetimeIndex(
            [
                pd.Timestamp(2024, 1, 2, tz=timezone(pd.Timedelta(hours=-5))),
                pd.Timestamp(2024, 1, 3, tz=timezone(pd.Timedelta(hours=-5))),
            ]
        ),
    )

    bars = normalize_prices("aapl", raw)

    assert [bar.date for bar in bars] == [date(2024, 1, 2), date(2024, 1, 3)]
    assert [bar.close for bar in bars] == [104.0, 105.0]
    assert [bar.volume for bar in bars] == [1_000, 2_000]


@pytest.mark.unit
def test_normalize_prices_uppercases_the_ticker() -> None:
    """A fronteira de entrada canonicaliza o ticker; storage/ nunca precisa decidir caixa."""
    raw = pd.DataFrame(
        {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1]},
        index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 2)]),
    )

    bars = normalize_prices("aapl", raw)

    assert bars[0].ticker == "AAPL"


@pytest.mark.unit
def test_normalize_prices_of_an_empty_frame_is_an_empty_list() -> None:
    """Vazio aqui não é ING-04.2 — essa regra é do provedor (B1), não da normalização."""
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    assert normalize_prices("AAPL", empty) == []


@pytest.mark.unit
def test_normalize_prices_preserves_implausible_values() -> None:
    """Valor implausível atravessa intacto — decidir é trabalho do validador (B3)."""
    raw = pd.DataFrame(
        {"Open": [10.0], "High": [5.0], "Low": [8.0], "Close": [-1.0], "Volume": [-100]},
        index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 2)]),
    )

    bars = normalize_prices("XYZ", raw)

    assert bars[0].high == 5.0
    assert bars[0].low == 8.0
    assert bars[0].close == -1.0
    assert bars[0].volume == -100


@pytest.mark.unit
def test_normalize_corporate_actions_converts_dividends_and_splits() -> None:
    raw = RawCorporateActions(
        dividends=pd.Series([0.24], index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 15, tz=UTC)])),
        splits=pd.Series([4.0], index=pd.DatetimeIndex([pd.Timestamp(2020, 8, 31, tz=UTC)])),
    )

    actions = normalize_corporate_actions("aapl", raw)

    kinds = {action.kind for action in actions}
    assert kinds == {CorporateActionKind.DIVIDEND, CorporateActionKind.SPLIT}
    dividend = next(a for a in actions if a.kind is CorporateActionKind.DIVIDEND)
    split = next(a for a in actions if a.kind is CorporateActionKind.SPLIT)
    assert dividend.date == date(2024, 1, 15)
    assert dividend.value == pytest.approx(0.24)
    assert split.date == date(2020, 8, 31)
    assert split.ratio == pytest.approx(4.0)
    assert dividend.ticker == "AAPL"


@pytest.mark.unit
def test_normalize_corporate_actions_drops_zero_magnitude_events() -> None:
    """Zero residual do yfinance não é um evento — e viraria DataError se não filtrado."""
    raw = RawCorporateActions(
        dividends=pd.Series([0.0], index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 15)])),
        splits=pd.Series([0.0], index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 20)])),
    )

    assert normalize_corporate_actions("XYZ", raw) == []


@pytest.mark.unit
def test_normalize_corporate_actions_of_empty_series_is_empty_list() -> None:
    raw = RawCorporateActions(dividends=pd.Series(dtype=float), splits=pd.Series(dtype=float))
    assert normalize_corporate_actions("XYZ", raw) == []


@pytest.mark.unit
def test_malformed_dividend_that_survives_the_zero_filter_still_raises() -> None:
    """Filtrar zero não é filtrar tudo — um dividendo negativo continua batendo em DataError."""
    raw = RawCorporateActions(
        dividends=pd.Series([-0.5], index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 15)])),
        splits=pd.Series(dtype=float),
    )

    with pytest.raises(DataError):
        normalize_corporate_actions("XYZ", raw)
