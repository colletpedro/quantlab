"""A5 — escrita de eventos corporativos com upsert (ING-02.1, ING-02.2, design §3.2)."""

from datetime import date

import pytest
from structlog.typing import EventDict

from quantlab.storage.client import MongoDatabase
from quantlab.storage.models import CorporateAction, CorporateActionKind
from quantlab.storage.repository import MongoRepository
from quantlab.storage.schema import CORPORATE_ACTIONS


def _dividend(day: int, value: float) -> CorporateAction:
    return CorporateAction(
        ticker="AAPL",
        date=date(2024, 1, day),
        kind=CorporateActionKind.DIVIDEND,
        value=value,
    )


def _split(day: int, ratio: float) -> CorporateAction:
    return CorporateAction(
        ticker="AAPL",
        date=date(2024, 1, day),
        kind=CorporateActionKind.SPLIT,
        ratio=ratio,
    )


@pytest.mark.integration
def test_dividend_and_split_on_the_same_date_coexist(mongo_db: MongoDatabase) -> None:
    """`kind` está na chave exatamente por isto — design §3.2."""
    repository = MongoRepository(mongo_db)

    repository.upsert_corporate_actions([_dividend(15, 0.24), _split(15, 4.0)])

    assert mongo_db[CORPORATE_ACTIONS].count_documents({}) == 2
    stored = repository.get_corporate_actions("AAPL")
    assert {action.kind for action in stored} == {
        CorporateActionKind.DIVIDEND,
        CorporateActionKind.SPLIT,
    }


@pytest.mark.integration
def test_reingesting_the_same_events_does_not_duplicate(mongo_db: MongoDatabase) -> None:
    """ING-02.1 / ING-02.2 — a coleta é reexecutável sem duplicar."""
    repository = MongoRepository(mongo_db)
    events = [_dividend(15, 0.24), _split(20, 2.0)]

    repository.upsert_corporate_actions(events)
    repository.upsert_corporate_actions(events)

    assert mongo_db[CORPORATE_ACTIONS].count_documents({}) == 2


@pytest.mark.integration
def test_retroactive_revision_updates_and_is_logged(
    mongo_db: MongoDatabase,
    log_events: list[EventDict],
) -> None:
    """Design §3.2 — provedor revisa evento retroativamente; atualiza e loga.

    Revisão de evento muda a série ajustada inteira e, com ela, o hash de
    PER-03.1. O log é o que permite rastrear o hash divergente até a causa,
    em vez de tratá-lo como bug.
    """
    repository = MongoRepository(mongo_db)
    repository.upsert_corporate_actions([_dividend(15, 0.24)])
    repository.upsert_corporate_actions([_dividend(15, 0.26)])

    assert mongo_db[CORPORATE_ACTIONS].count_documents({}) == 1
    stored = repository.get_corporate_actions("AAPL")
    assert stored[0].value == pytest.approx(0.26)

    revisions = [
        event for event in log_events if event["event"] == "storage.corporate_action_revised"
    ]
    assert len(revisions) == 1
    assert revisions[0]["from"] == pytest.approx(0.24)
    assert revisions[0]["to"] == pytest.approx(0.26)


@pytest.mark.integration
def test_unchanged_event_does_not_log_a_revision(
    mongo_db: MongoDatabase,
    log_events: list[EventDict],
) -> None:
    """Reescrever o mesmo valor não é revisão."""
    repository = MongoRepository(mongo_db)
    repository.upsert_corporate_actions([_split(20, 4.0)])
    repository.upsert_corporate_actions([_split(20, 4.0)])

    assert [
        event for event in log_events if event["event"] == "storage.corporate_action_revised"
    ] == []


@pytest.mark.integration
def test_events_are_read_over_the_full_history(mongo_db: MongoDatabase) -> None:
    """ING-02.3 — a leitura de eventos não aceita janela, de propósito.

    Um split fora do intervalo pedido ainda afeta os preços dentro dele; se a
    leitura filtrasse por janela, a série sairia ajustada só no meio.
    """
    repository = MongoRepository(mongo_db)
    repository.upsert_corporate_actions(
        [
            CorporateAction(
                ticker="AAPL",
                date=date(2019, 6, 1),
                kind=CorporateActionKind.SPLIT,
                ratio=2.0,
            ),
            _dividend(15, 0.24),
            CorporateAction(
                ticker="AAPL",
                date=date(2030, 1, 1),
                kind=CorporateActionKind.SPLIT,
                ratio=3.0,
            ),
        ]
    )

    stored = repository.get_corporate_actions("AAPL")

    assert [action.date for action in stored] == [
        date(2019, 6, 1),
        date(2024, 1, 15),
        date(2030, 1, 1),
    ]


@pytest.mark.integration
def test_events_of_other_tickers_are_not_returned(mongo_db: MongoDatabase) -> None:
    """Ajustar AAPL com um split da MSFT seria corrupção silenciosa."""
    repository = MongoRepository(mongo_db)
    repository.upsert_corporate_actions(
        [
            _split(20, 4.0),
            CorporateAction(
                ticker="MSFT",
                date=date(2024, 1, 20),
                kind=CorporateActionKind.SPLIT,
                ratio=2.0,
            ),
        ]
    )

    assert len(repository.get_corporate_actions("AAPL")) == 1
    assert len(repository.get_corporate_actions("MSFT")) == 1


@pytest.mark.integration
def test_writing_no_events_is_a_no_op(mongo_db: MongoDatabase) -> None:
    """Lista vazia não chega ao driver, que rejeita bulk_write vazio."""
    repository = MongoRepository(mongo_db)
    report = repository.upsert_corporate_actions([])
    assert (report.inserted, report.modified, report.matched) == (0, 0, 0)


@pytest.mark.integration
def test_stored_event_shape_matches_the_design(mongo_db: MongoDatabase) -> None:
    """Design §3.2 — `value` sse dividendo, `ratio` sse split."""
    repository = MongoRepository(mongo_db)
    repository.upsert_corporate_actions([_dividend(15, 0.24), _split(20, 4.0)])

    dividend = mongo_db[CORPORATE_ACTIONS].find_one({"kind": "dividend"})
    split = mongo_db[CORPORATE_ACTIONS].find_one({"kind": "split"})
    assert dividend is not None and split is not None

    assert dividend["value"] == pytest.approx(0.24)
    assert "ratio" not in dividend
    assert split["ratio"] == pytest.approx(4.0)
    assert "value" not in split
