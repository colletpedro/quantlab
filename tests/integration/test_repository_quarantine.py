"""A6 — coleção de quarentena (ING-05.1, design §3.3).

O que se testa aqui é o **destino**: a barra rejeitada vai para
`quarantined_bars` e não aparece em `bars`. As regras que decidem o que é
inválido são do validador (B3, Bloco B) e não moram em storage.
"""

from datetime import date
from typing import Any

import pytest
from structlog.typing import EventDict

from quantlab.storage.client import MongoDatabase
from quantlab.storage.models import Bar, QuarantinedBar
from quantlab.storage.repository import MongoRepository
from quantlab.storage.schema import BARS, QUARANTINED_BARS

#: Payload como viria do provedor, com `close` acima do `high` e preço
#: negativo — duas violações, de propósito.
_RAW_PAYLOAD: dict[str, Any] = {
    "Open": 10.0,
    "High": 11.0,
    "Low": -2.0,
    "Close": 99.0,
    "Volume": 1000,
    "extra_do_provedor": "campo que o quantlab não conhece",
}


def _entry(reasons: tuple[str, ...], run_id: str | None = "run-1") -> QuarantinedBar:
    return QuarantinedBar(
        ticker="XYZ",
        date=date(2024, 1, 2),
        raw=dict(_RAW_PAYLOAD),
        reasons=reasons,
        ingestion_run_id=run_id,
    )


@pytest.mark.integration
def test_quarantined_bar_does_not_reach_the_bars_collection(mongo_db: MongoDatabase) -> None:
    """O ponto de design §3.3: barra inválida não entra em `bars`.

    Uma barra inválida dentro de `bars` seria uma bomba esperando um `find`
    que esquecesse o filtro.
    """
    repository = MongoRepository(mongo_db)

    repository.quarantine_bars([_entry(("close_above_high", "low_not_positive"))])

    assert mongo_db[QUARANTINED_BARS].count_documents({}) == 1
    assert mongo_db[BARS].count_documents({}) == 0
    assert repository.get_bars("XYZ") == []


@pytest.mark.integration
def test_all_rejection_reasons_are_recorded(mongo_db: MongoDatabase) -> None:
    """Design §3.3 — toda regra violada, não só a primeira."""
    repository = MongoRepository(mongo_db)
    reasons = ("close_above_high", "low_not_positive", "open_outside_range")

    repository.quarantine_bars([_entry(reasons)])

    stored = mongo_db[QUARANTINED_BARS].find_one({"ticker": "XYZ"})
    assert stored is not None
    assert stored["reasons"] == list(reasons)


@pytest.mark.integration
def test_raw_payload_is_preserved_intact(mongo_db: MongoDatabase) -> None:
    """Diagnóstico precisa do dado original, não de uma versão já interpretada."""
    repository = MongoRepository(mongo_db)

    repository.quarantine_bars([_entry(("low_not_positive",))])

    stored = mongo_db[QUARANTINED_BARS].find_one({"ticker": "XYZ"})
    assert stored is not None
    assert stored["raw"] == _RAW_PAYLOAD
    # Inclusive o campo que o quantlab não conhece: descartá-lo esconderia
    # justamente a informação que explicaria a rejeição.
    assert stored["raw"]["extra_do_provedor"] == "campo que o quantlab não conhece"


@pytest.mark.integration
def test_ingestion_run_id_is_recorded(mongo_db: MongoDatabase) -> None:
    """A referência cruzada é o que liga a quarentena ao run que a produziu."""
    repository = MongoRepository(mongo_db)

    repository.quarantine_bars([_entry(("low_not_positive",), run_id="run-42")])

    stored = mongo_db[QUARANTINED_BARS].find_one({"ticker": "XYZ"})
    assert stored is not None
    assert stored["ingestion_run_id"] == "run-42"


@pytest.mark.integration
def test_same_bar_can_be_quarantined_in_different_runs(mongo_db: MongoDatabase) -> None:
    """Sem chave única, de propósito — design §3.3.

    O mesmo `(ticker, date)` reprovando em dois runs é informação: mostra que
    o provedor não corrigiu. Um upsert apagaria essa história.
    """
    repository = MongoRepository(mongo_db)

    repository.quarantine_bars([_entry(("low_not_positive",), run_id="run-1")])
    repository.quarantine_bars([_entry(("low_not_positive",), run_id="run-2")])

    assert mongo_db[QUARANTINED_BARS].count_documents({"ticker": "XYZ"}) == 2
    run_ids = {doc["ingestion_run_id"] for doc in mongo_db[QUARANTINED_BARS].find({})}
    assert run_ids == {"run-1", "run-2"}


@pytest.mark.integration
def test_quarantine_is_logged(mongo_db: MongoDatabase, log_events: list[EventDict]) -> None:
    """Barra descartada em silêncio é dado que some sem ninguém notar."""
    repository = MongoRepository(mongo_db)

    repository.quarantine_bars([_entry(("close_above_high", "low_not_positive"))])

    quarantined = [event for event in log_events if event["event"] == "storage.bar_quarantined"]
    assert len(quarantined) == 1
    assert quarantined[0]["ticker"] == "XYZ"
    assert quarantined[0]["reasons"] == ["close_above_high", "low_not_positive"]


@pytest.mark.integration
def test_quarantine_does_not_disturb_valid_bars(mongo_db: MongoDatabase) -> None:
    """Quarentena não bloqueia o run: as demais barras seguem (design §3.3)."""
    repository = MongoRepository(mongo_db)
    valid = Bar(
        ticker="XYZ",
        date=date(2024, 1, 3),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        volume=1_000,
    )

    repository.quarantine_bars([_entry(("low_not_positive",))])
    repository.upsert_bars([valid])

    assert [bar.date for bar in repository.get_bars("XYZ")] == [date(2024, 1, 3)]
    assert mongo_db[QUARANTINED_BARS].count_documents({}) == 1


@pytest.mark.integration
def test_quarantining_nothing_is_a_no_op(mongo_db: MongoDatabase) -> None:
    """Lista vazia não chega ao driver, que rejeita insert_many vazio."""
    repository = MongoRepository(mongo_db)
    assert repository.quarantine_bars([]) == 0
