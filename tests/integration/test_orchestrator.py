"""B4 — orquestrador ponta a ponta: Mongo real, provedor falso.

`FakeProvider` continua sem tocar rede (RNF-06): "integração" aqui é com o
banco, não com a internet.
"""

from datetime import date

import pandas as pd
import pytest
from bson import ObjectId

from quantlab.ingestion.orchestrator import run_ingestion
from quantlab.ingestion.resilient_provider import ResilientProvider
from quantlab.storage.client import MongoDatabase
from quantlab.storage.repository import MongoRepository
from quantlab.storage.schema import BARS, INGESTION_RUNS, QUARANTINED_BARS
from tests.support import FakeProvider

_START = date(2024, 1, 1)
_END = date(2024, 1, 5)


def _no_sleep(_seconds: float) -> None:
    pass


def _prices_df(rows: int = 2) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0] * rows,
            "High": [101.0] * rows,
            "Low": [99.0] * rows,
            "Close": [100.5] * rows,
            "Volume": [1_000] * rows,
        },
        index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 2 + i) for i in range(rows)]),
    )


@pytest.mark.integration
def test_ingestion_writes_bars_and_a_finished_run_document(mongo_db: MongoDatabase) -> None:
    provider = ResilientProvider(
        FakeProvider(prices={"AAPL": _prices_df(), "MSFT": _prices_df()}), sleep=_no_sleep
    )
    repository = MongoRepository(mongo_db)

    result = run_ingestion(["AAPL", "MSFT"], _START, _END, provider=provider, repository=repository)

    assert result.ok
    assert mongo_db[BARS].count_documents({}) == 4

    run_doc = mongo_db[INGESTION_RUNS].find_one({"_id": ObjectId(result.run_id)})
    assert run_doc is not None
    assert run_doc["succeeded"] == ["AAPL", "MSFT"]
    assert run_doc["failed"] == []
    assert run_doc["bars_inserted"] == 4
    assert run_doc["finished_at"] is not None
    assert run_doc["started_at"] is not None


@pytest.mark.integration
def test_ingestion_run_index_serves_lookup_by_ticker(mongo_db: MongoDatabase) -> None:
    """PER-03.1/auditoria — o índice definido em design v0.4 §3.4 é usado de verdade."""
    provider = ResilientProvider(FakeProvider(prices={"AAPL": _prices_df()}), sleep=_no_sleep)
    repository = MongoRepository(mongo_db)

    run_ingestion(["AAPL"], _START, _END, provider=provider, repository=repository)

    plan = mongo_db[INGESTION_RUNS].find({"tickers": "AAPL"}).sort("started_at", -1).explain()
    winning = plan["queryPlanner"]["winningPlan"]
    stages = _plan_stages(winning)
    assert "IXSCAN" in stages, f"esperado IXSCAN, plano foi {stages}"


def _plan_stages(plan: dict[str, object]) -> set[str]:
    stages: set[str] = set()
    pending: list[dict[str, object]] = [plan]
    while pending:
        node = pending.pop()
        stage = node.get("stage")
        if isinstance(stage, str):
            stages.add(stage)
        for key in ("inputStage", "queryPlan"):
            child = node.get(key)
            if isinstance(child, dict):
                pending.append(child)
        children = node.get("inputStages", [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    pending.append(child)
    return stages


@pytest.mark.integration
def test_one_ticker_failure_does_not_stop_the_batch_against_real_mongo(
    mongo_db: MongoDatabase,
) -> None:
    def broken() -> pd.DataFrame:
        raise ConnectionError("provedor fora do ar")

    provider = ResilientProvider(
        FakeProvider(prices={"AAPL": _prices_df(), "BAD": broken}), sleep=_no_sleep
    )
    repository = MongoRepository(mongo_db)

    result = run_ingestion(["AAPL", "BAD"], _START, _END, provider=provider, repository=repository)

    assert not result.ok
    assert result.succeeded == ("AAPL",)
    assert [failure.ticker for failure in result.failed] == ["BAD"]
    # AAPL foi gravado apesar da falha de BAD.
    assert mongo_db[BARS].count_documents({"ticker": "AAPL"}) == 2
    assert mongo_db[BARS].count_documents({"ticker": "BAD"}) == 0


@pytest.mark.integration
def test_invalid_bar_is_quarantined_and_cross_referenced_to_the_run(
    mongo_db: MongoDatabase,
) -> None:
    invalid = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [-5.0], "Volume": [1_000]},
        index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 2)]),
    )
    provider = ResilientProvider(FakeProvider(prices={"XYZ": invalid}), sleep=_no_sleep)
    repository = MongoRepository(mongo_db)

    result = run_ingestion(["XYZ"], _START, _END, provider=provider, repository=repository)

    assert result.ok
    assert mongo_db[BARS].count_documents({"ticker": "XYZ"}) == 0
    quarantined = mongo_db[QUARANTINED_BARS].find_one({"ticker": "XYZ"})
    assert quarantined is not None
    assert quarantined["ingestion_run_id"] == result.run_id
    assert "close_not_positive" in quarantined["reasons"]


@pytest.mark.integration
def test_rerunning_the_same_window_does_not_duplicate_bars(mongo_db: MongoDatabase) -> None:
    """ING-03.1 ponta a ponta — a idempotência de A4 vale através do orquestrador."""
    provider = ResilientProvider(FakeProvider(prices={"AAPL": _prices_df()}), sleep=_no_sleep)
    repository = MongoRepository(mongo_db)

    run_ingestion(["AAPL"], _START, _END, provider=provider, repository=repository)
    run_ingestion(["AAPL"], _START, _END, provider=provider, repository=repository)

    assert mongo_db[BARS].count_documents({"ticker": "AAPL"}) == 2
