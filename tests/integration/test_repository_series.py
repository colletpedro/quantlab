"""A8 — `get_series` ponta a ponta contra Mongo real.

O que só se prova aqui, e não em unitário: os eventos usados no ajuste vêm do
**histórico completo** do ticker, não da janela pedida (ING-02.3, ADR-0003).
"""

from datetime import date

import pytest

from quantlab.exceptions import DataError
from quantlab.storage.client import MongoDatabase
from quantlab.storage.models import Bar, CorporateAction, CorporateActionKind
from quantlab.storage.repository import MongoRepository

#: Quatro pregões com fechamentos redondos, para que o ajuste caiba na cabeça.
_BARS = [
    Bar(
        ticker="AAPL",
        date=date(2024, 1, 2),
        open=99.0,
        high=101.0,
        low=98.0,
        close=100.0,
        volume=1_000,
    ),
    Bar(
        ticker="AAPL",
        date=date(2024, 1, 3),
        open=100.0,
        high=112.0,
        low=99.0,
        close=110.0,
        volume=2_000,
    ),
    Bar(
        ticker="AAPL",
        date=date(2024, 1, 4),
        open=110.0,
        high=122.0,
        low=109.0,
        close=120.0,
        volume=3_000,
    ),
    Bar(
        ticker="AAPL",
        date=date(2024, 1, 5),
        open=120.0,
        high=131.0,
        low=119.0,
        close=130.0,
        volume=4_000,
    ),
]


def _repository(mongo_db: MongoDatabase) -> MongoRepository:
    repository = MongoRepository(mongo_db)
    repository.upsert_bars(_BARS)
    return repository


@pytest.mark.integration
def test_series_without_events_is_identical_raw_and_adjusted(mongo_db: MongoDatabase) -> None:
    """PER-02.4 — sem evento, a leitura ajustada tem de sair igual à bruta."""
    repository = _repository(mongo_db)

    raw = repository.get_series("AAPL", adjusted=False)
    adjusted = repository.get_series("AAPL", adjusted=True)

    assert list(adjusted.close) == pytest.approx(list(raw.close), rel=1e-12)
    assert list(adjusted.volume) == pytest.approx(list(raw.volume), rel=1e-12)
    assert adjusted.hash == raw.hash


@pytest.mark.integration
def test_split_outside_the_requested_window_still_adjusts_inside_it(
    mongo_db: MongoDatabase,
) -> None:
    """ING-02.3 — o ponto de ADR-0003 sobre histórico completo.

    A janela pedida é 02/01 a 03/01. O split tem data ex em 05/01, FORA dela.
    Ainda assim as duas barras da janela são anteriores ao split e têm de ser
    ajustadas: preços / 2, volume * 2.

    Se `get_series` filtrasse eventos pela janela, este teste falharia — e o
    bug seria uma série ajustada só no meio, que passa despercebida.
    """
    repository = _repository(mongo_db)
    repository.upsert_corporate_actions(
        [
            CorporateAction(
                ticker="AAPL",
                date=date(2024, 1, 5),
                kind=CorporateActionKind.SPLIT,
                ratio=2.0,
            )
        ]
    )

    window = repository.get_series("AAPL", start=date(2024, 1, 2), end=date(2024, 1, 3))

    assert len(window) == 2
    # 100.0 / 2 = 50.0   |   110.0 / 2 = 55.0
    assert list(window.close) == pytest.approx([50.0, 55.0])
    # 1000 * 2 = 2000    |   2000 * 2 = 4000
    assert list(window.volume) == pytest.approx([2_000.0, 4_000.0])


@pytest.mark.integration
def test_event_before_the_window_does_not_adjust_bars_after_it(
    mongo_db: MongoDatabase,
) -> None:
    """Só eventos posteriores à barra a afetam — nunca os anteriores."""
    repository = _repository(mongo_db)
    repository.upsert_corporate_actions(
        [
            CorporateAction(
                ticker="AAPL",
                date=date(2023, 6, 1),
                kind=CorporateActionKind.SPLIT,
                ratio=2.0,
            )
        ]
    )

    series = repository.get_series("AAPL")

    assert list(series.close) == pytest.approx([100.0, 110.0, 120.0, 130.0])


@pytest.mark.integration
def test_adjusted_flag_is_carried_on_the_series(mongo_db: MongoDatabase) -> None:
    """O consumidor precisa saber o que recebeu, sem inferir."""
    repository = _repository(mongo_db)

    assert repository.get_series("AAPL", adjusted=True).adjusted is True
    assert repository.get_series("AAPL", adjusted=False).adjusted is False


@pytest.mark.integration
def test_two_reads_of_the_same_state_are_identical(mongo_db: MongoDatabase) -> None:
    """PER-02.3 — mesmo estado de banco, mesmo resultado, mesmo hash."""
    repository = _repository(mongo_db)
    repository.upsert_corporate_actions(
        [
            CorporateAction(
                ticker="AAPL",
                date=date(2024, 1, 4),
                kind=CorporateActionKind.DIVIDEND,
                value=1.10,
            )
        ]
    )

    first = repository.get_series("AAPL")
    second = repository.get_series("AAPL")

    assert first.hash == second.hash
    assert list(first.close) == pytest.approx(list(second.close), rel=1e-15)


@pytest.mark.integration
def test_dividend_uses_the_raw_previous_close_from_the_database(
    mongo_db: MongoDatabase,
) -> None:
    """ADR-0003 ponta a ponta — `C` é o fechamento bruto de 03/01 = 110.0.

    fator = (110.0 - 1.10)/110.0 = 108.90/110.0 = 0.99
    Barras anteriores a 04/01: 02/01 e 03/01.
        100.0 * 0.99 = 99.0
        110.0 * 0.99 = 108.9
    04/01 e 05/01 ficam intactas.
    """
    repository = _repository(mongo_db)
    repository.upsert_corporate_actions(
        [
            CorporateAction(
                ticker="AAPL",
                date=date(2024, 1, 4),
                kind=CorporateActionKind.DIVIDEND,
                value=1.10,
            )
        ]
    )

    series = repository.get_series("AAPL")

    assert list(series.close) == pytest.approx([99.0, 108.9, 120.0, 130.0])
    # Dividendo não mexe em volume.
    assert list(series.volume) == pytest.approx([1_000.0, 2_000.0, 3_000.0, 4_000.0])


@pytest.mark.integration
def test_adjustment_changes_the_hash(mongo_db: MongoDatabase) -> None:
    """Série ajustada e bruta são dados diferentes e não podem colidir no hash."""
    repository = _repository(mongo_db)
    repository.upsert_corporate_actions(
        [
            CorporateAction(
                ticker="AAPL",
                date=date(2024, 1, 5),
                kind=CorporateActionKind.SPLIT,
                ratio=2.0,
            )
        ]
    )

    assert repository.get_series("AAPL", adjusted=True).hash != (
        repository.get_series("AAPL", adjusted=False).hash
    )


@pytest.mark.integration
def test_series_records_the_latest_ingestion_instant(mongo_db: MongoDatabase) -> None:
    """PER-03.1 — o relatório precisa saber de quando é o dado consumido."""
    repository = _repository(mongo_db)

    series = repository.get_series("AAPL")

    assert series.last_ingested_at is not None
    # ISO-8601, não `datetime`: metadado de auditoria não entra em comparação
    # de data e não pode vazar instante para o domínio (RNF-07).
    assert isinstance(series.last_ingested_at, str)
    assert series.last_ingested_at.startswith("20")


@pytest.mark.integration
def test_missing_ticker_fails_with_an_actionable_message(mongo_db: MongoDatabase) -> None:
    """CLI-02.2 exige mensagem acionável; a falha nasce aqui."""
    repository = _repository(mongo_db)

    with pytest.raises(DataError, match="ingestão"):
        repository.get_series("NAO_INGERIDO")


@pytest.mark.integration
def test_series_arrays_are_read_only_end_to_end(mongo_db: MongoDatabase) -> None:
    """A garantia de §3.7 vale para a série que o repositório realmente devolve."""
    series = _repository(mongo_db).get_series("AAPL")

    with pytest.raises(ValueError, match="read-only"):
        series.close[0] = 999.0


@pytest.mark.integration
def test_series_dates_come_back_as_calendar_dates(mongo_db: MongoDatabase) -> None:
    """RNF-07 — nenhum `datetime` atravessa a fronteira do repositório."""
    series = _repository(mongo_db).get_series("AAPL")

    assert [value for value in series.dates] == [bar.date for bar in _BARS]
    assert all(type(value) is date for value in series.dates)
