"""A2 — coleções, índices e prova de uso de índice (PER-01.2)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from quantlab.storage.client import MongoDatabase
from quantlab.storage.schema import (
    BARS,
    COLLECTIONS,
    CORPORATE_ACTIONS,
    QUARANTINED_BARS,
    ensure_schema,
)


def _index_keys(database: MongoDatabase, collection: str) -> dict[str, list[tuple[str, int]]]:
    """Mapeia nome do índice para sua chave, ignorando o `_id_` implícito."""
    return {
        index["name"]: list(index["key"].items())
        for index in database[collection].list_indexes()
        if index["name"] != "_id_"
    }


def _unique_index_names(database: MongoDatabase, collection: str) -> set[str]:
    return {
        index["name"] for index in database[collection].list_indexes() if index.get("unique", False)
    }


@pytest.mark.integration
def test_ensure_schema_is_idempotent(mongo_db: MongoDatabase) -> None:
    """Rodar duas vezes não levanta e não duplica índice."""
    ensure_schema(mongo_db)
    first = {name: _index_keys(mongo_db, name) for name in COLLECTIONS}

    ensure_schema(mongo_db)
    second = {name: _index_keys(mongo_db, name) for name in COLLECTIONS}

    assert first == second
    assert set(COLLECTIONS).issubset(set(mongo_db.list_collection_names()))


@pytest.mark.integration
def test_indexes_match_design(mongo_db: MongoDatabase) -> None:
    """Os índices são exatamente os de design 3.1 a 3.3."""
    ensure_schema(mongo_db)

    assert _index_keys(mongo_db, BARS) == {"ticker_date_unique": [("ticker", 1), ("date", 1)]}
    assert _unique_index_names(mongo_db, BARS) == {"ticker_date_unique"}

    assert _index_keys(mongo_db, CORPORATE_ACTIONS) == {
        "ticker_date_kind_unique": [("ticker", 1), ("date", 1), ("kind", 1)]
    }
    assert _unique_index_names(mongo_db, CORPORATE_ACTIONS) == {"ticker_date_kind_unique"}

    # Quarentena guarda histórico: mesmo (ticker, date) pode repetir em runs
    # diferentes, logo o índice existe para consulta mas não é único.
    assert _index_keys(mongo_db, QUARANTINED_BARS) == {"ticker_date": [("ticker", 1), ("date", 1)]}
    assert _unique_index_names(mongo_db, QUARANTINED_BARS) == set()


@pytest.mark.integration
def test_no_standalone_date_index_on_bars(mongo_db: MongoDatabase) -> None:
    """Índice isolado em `date` não é criado — design §3.1 diz por quê."""
    ensure_schema(mongo_db)
    keys = _index_keys(mongo_db, BARS)
    assert [("date", 1)] not in keys.values()


@pytest.mark.integration
def test_bars_unique_index_rejects_duplicate_ticker_date(mongo_db: MongoDatabase) -> None:
    """A unicidade que torna o upsert de PER-01.1 correto é real, não decorativa."""
    ensure_schema(mongo_db)
    document: dict[str, Any] = {
        "ticker": "AAPL",
        "date": datetime(2024, 1, 2, tzinfo=UTC),
        "open": 1.0,
        "high": 1.0,
        "low": 1.0,
        "close": 1.0,
        "volume": 1,
    }
    mongo_db[BARS].insert_one(dict(document))

    with pytest.raises(DuplicateKeyError):
        mongo_db[BARS].insert_one(dict(document))


@pytest.mark.integration
def test_range_query_uses_index_scan(mongo_db: MongoDatabase) -> None:
    """PER-01.2 — consulta por ticker + intervalo usa IXSCAN, não COLLSCAN."""
    ensure_schema(mongo_db)
    mongo_db[BARS].insert_many(
        [
            {
                "ticker": "AAPL",
                "date": datetime(2024, 1, day, tzinfo=UTC),
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": float(day),
                "volume": 100,
            }
            for day in range(1, 29)
        ]
    )

    plan = (
        mongo_db[BARS]
        .find(
            {
                "ticker": "AAPL",
                "date": {
                    "$gte": datetime(2024, 1, 10, tzinfo=UTC),
                    "$lte": datetime(2024, 1, 20, tzinfo=UTC),
                },
            }
        )
        .explain()
    )

    winning = plan["queryPlanner"]["winningPlan"]
    stages = _plan_stages(winning)
    assert "IXSCAN" in stages, f"esperado IXSCAN, plano foi {stages}"
    assert "COLLSCAN" not in stages, f"varredura completa da coleção: {stages}"


def _plan_stages(plan: dict[str, Any]) -> set[str]:
    """Coleta os nomes de estágio de um plano, que o Mongo devolve aninhado."""
    stages: set[str] = set()
    pending: list[dict[str, Any]] = [plan]
    while pending:
        node = pending.pop()
        stage = node.get("stage")
        if isinstance(stage, str):
            stages.add(stage)
        for key in ("inputStage", "queryPlan"):
            child = node.get(key)
            if isinstance(child, dict):
                pending.append(child)
        for child in node.get("inputStages", []):
            if isinstance(child, dict):
                pending.append(child)
    return stages
