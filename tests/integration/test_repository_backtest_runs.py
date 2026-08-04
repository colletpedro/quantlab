"""F1 — `backtest_runs` ponta a ponta contra Mongo real (design §3.5, v0.7)."""

from datetime import date

import pytest

from quantlab.storage.client import MongoDatabase
from quantlab.storage.repository import MongoRepository, to_bson_date
from quantlab.storage.schema import BACKTEST_RUNS, ensure_schema


@pytest.mark.integration
def test_save_backtest_run_persists_and_stamps_created_at(mongo_db: MongoDatabase) -> None:
    ensure_schema(mongo_db)
    repository = MongoRepository(mongo_db)

    document = {
        "ticker": "AAPL",
        "strategy": {"name": "sma_cross", "params": {"fast": 20, "slow": 50}},
        "window": {"start": to_bson_date(date(2015, 1, 1)), "end": None},
        "initial_capital": 100_000.0,
    }

    run_id = repository.save_backtest_run(document)

    stored = mongo_db[BACKTEST_RUNS].find_one({"ticker": "AAPL"})
    assert stored is not None
    assert str(stored["_id"]) == run_id
    assert stored["strategy"]["name"] == "sma_cross"
    # `created_at` é carimbado pelo repositório, não pelo chamador (§3.6 —
    # datetime só aparece aqui e em ingestion/normalizer.py).
    assert stored["created_at"] is not None
    assert "created_at" not in document  # o documento original não foi mutado


@pytest.mark.integration
def test_backtest_runs_has_the_ticker_strategy_created_at_index(mongo_db: MongoDatabase) -> None:
    ensure_schema(mongo_db)

    index_names = set(mongo_db[BACKTEST_RUNS].index_information().keys())

    assert "ticker_strategy_created_at" in index_names


@pytest.mark.integration
def test_multiple_runs_of_the_same_ticker_are_all_kept(mongo_db: MongoDatabase) -> None:
    """Sem upsert: cada run é um documento novo (RF-PER-03 quer todos, não só o último)."""
    ensure_schema(mongo_db)
    repository = MongoRepository(mongo_db)

    first = repository.save_backtest_run({"ticker": "MSFT", "strategy": {"name": "sma_cross"}})
    second = repository.save_backtest_run({"ticker": "MSFT", "strategy": {"name": "sma_cross"}})

    assert first != second
    assert mongo_db[BACKTEST_RUNS].count_documents({"ticker": "MSFT"}) == 2
