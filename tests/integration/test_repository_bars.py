"""A4 — escrita de barras com upsert (ING-03.1, ING-03.2, PER-01.1)."""

from datetime import date

import pytest
from structlog.typing import EventDict

from quantlab.storage.client import MongoDatabase
from quantlab.storage.models import Bar
from quantlab.storage.repository import MongoRepository
from quantlab.storage.schema import BARS


def _bar(day: int, close: float = 100.0) -> Bar:
    return Bar(
        ticker="AAPL",
        date=date(2024, 1, day),
        open=99.0,
        high=101.0,
        low=98.0,
        close=close,
        volume=1_000,
    )


@pytest.mark.integration
def test_reingesting_the_same_window_does_not_duplicate(mongo_db: MongoDatabase) -> None:
    """ING-03.1 — reexecutar sobre a mesma janela mantém a contagem."""
    repository = MongoRepository(mongo_db)
    bars = [_bar(day) for day in (2, 3, 4)]

    repository.upsert_bars(bars)
    assert mongo_db[BARS].count_documents({}) == 3

    repository.upsert_bars(bars)
    assert mongo_db[BARS].count_documents({}) == 3


@pytest.mark.integration
def test_first_write_inserts_and_second_matches(mongo_db: MongoDatabase) -> None:
    """A operação é upsert: insere na primeira vez, casa na segunda."""
    repository = MongoRepository(mongo_db)
    bars = [_bar(day) for day in (2, 3)]

    first = repository.upsert_bars(bars)
    assert first.inserted == 2

    second = repository.upsert_bars(bars)
    assert second.inserted == 0
    assert second.matched == 2


@pytest.mark.integration
def test_changed_value_updates_in_place_and_logs_before_and_after(
    mongo_db: MongoDatabase,
    log_events: list[EventDict],
) -> None:
    """ING-03.2 — revisão de preço atualiza e registra valor anterior e novo.

    Uma revisão silenciosa de preço histórico é o que explica um backtest que
    "mudou sozinho"; se ela não for logada, a causa fica invisível.
    """
    repository = MongoRepository(mongo_db)
    repository.upsert_bars([_bar(2, close=100.0)])
    repository.upsert_bars([_bar(2, close=123.45)])

    assert mongo_db[BARS].count_documents({}) == 1
    stored = mongo_db[BARS].find_one({"ticker": "AAPL"})
    assert stored is not None
    assert stored["close"] == pytest.approx(123.45)

    revisions = [event for event in log_events if event["event"] == "storage.bar_revised"]
    assert len(revisions) == 1
    assert revisions[0]["ticker"] == "AAPL"
    assert revisions[0]["date"] == "2024-01-02"
    assert revisions[0]["changes"] == {"close": {"from": 100.0, "to": 123.45}}


@pytest.mark.integration
def test_unchanged_rewrite_does_not_log_a_revision(
    mongo_db: MongoDatabase,
    log_events: list[EventDict],
) -> None:
    """Reescrever o mesmo valor não é revisão e não deve virar aviso.

    Sem isto, cada reingestão encheria o log de ruído e o aviso de verdade
    deixaria de ser lido.
    """
    repository = MongoRepository(mongo_db)
    repository.upsert_bars([_bar(2, close=100.0)])
    repository.upsert_bars([_bar(2, close=100.0)])

    assert [event for event in log_events if event["event"] == "storage.bar_revised"] == []


@pytest.mark.integration
def test_bars_round_trip_as_calendar_dates(mongo_db: MongoDatabase) -> None:
    """O que sai do repositório é `date`, nunca `datetime` (RNF-07)."""
    repository = MongoRepository(mongo_db)
    repository.upsert_bars([_bar(day) for day in (4, 2, 3)])

    stored = repository.get_bars("AAPL")

    assert [bar.date for bar in stored] == [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    assert all(type(bar.date) is date for bar in stored)


@pytest.mark.integration
def test_get_bars_window_is_inclusive_on_both_ends(mongo_db: MongoDatabase) -> None:
    """A janela pedida inclui as duas pontas."""
    repository = MongoRepository(mongo_db)
    repository.upsert_bars([_bar(day) for day in range(2, 9)])

    window = repository.get_bars("AAPL", start=date(2024, 1, 3), end=date(2024, 1, 5))

    assert [bar.date.day for bar in window] == [3, 4, 5]


@pytest.mark.integration
def test_writing_no_bars_is_a_no_op(mongo_db: MongoDatabase) -> None:
    """Lista vazia não deve chegar ao driver, que rejeita bulk_write vazio."""
    repository = MongoRepository(mongo_db)
    report = repository.upsert_bars([])
    assert (report.inserted, report.modified, report.matched) == (0, 0, 0)


@pytest.mark.integration
def test_bars_of_different_tickers_do_not_collide(mongo_db: MongoDatabase) -> None:
    """A chave é `(ticker, date)`: mesma data em tickers diferentes coexiste."""
    repository = MongoRepository(mongo_db)
    aapl = _bar(2, close=100.0)
    msft = Bar(
        ticker="MSFT",
        date=date(2024, 1, 2),
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10,
    )

    repository.upsert_bars([aapl, msft])

    assert mongo_db[BARS].count_documents({}) == 2
    assert len(repository.get_bars("AAPL")) == 1
    assert len(repository.get_bars("MSFT")) == 1
