"""B4 — orquestrador: unitário com um repositório em memória.

Um `FakeRepository` local (não `MongoRepository`) prova a lógica de
laço/falha/contagem sem precisar de Mongo — o comportamento contra o
repositório real é responsabilidade dos testes de integração
(`tests/integration/test_orchestrator.py`), que usam `FakeProvider` + Mongo
de verdade.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import pytest

from quantlab.ingestion.orchestrator import run_ingestion
from quantlab.ingestion.provider import RawCorporateActions
from quantlab.ingestion.resilient_provider import ResilientProvider
from quantlab.storage.models import Bar, CorporateAction, QuarantinedBar
from quantlab.storage.repository import WriteReport
from tests.support import FakeProvider

_START = date(2024, 1, 1)
_END = date(2024, 1, 5)


def _no_sleep(_seconds: float) -> None:
    """`run_ingestion` espera um provedor já resiliente (`ResilientProvider`),
    exatamente como B6 vai compor na CLI — sem isso, ConnectionError e
    resposta vazia chegariam crus ao orquestrador em vez de virarem
    DataError. O sleep injetável evita que os testes de retry esperem de
    verdade."""


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


@dataclass
class FakeRepository:
    """Registra o que o orquestrador tentou gravar, sem tocar Mongo.

    Implementa a mesma forma que `MongoRepository` expõe ao orquestrador —
    não herda dela, é `Protocol` estrutural implícito, igual a `FakeProvider`
    para `MarketDataProvider`.
    """

    upserted_bars: list[Bar] = field(default_factory=list)
    upserted_actions: list[CorporateAction] = field(default_factory=list)
    quarantined: list[QuarantinedBar] = field(default_factory=list)
    finished_calls: list[dict[str, object]] = field(default_factory=list)
    _next_run_id: str = "run-1"

    def start_ingestion_run(self, tickers: Sequence[str], start: date, end: date) -> str:
        return self._next_run_id

    def upsert_bars(self, bars: Sequence[Bar]) -> WriteReport:
        self.upserted_bars.extend(bars)
        report = WriteReport()
        report.inserted = len(bars)
        return report

    def upsert_corporate_actions(self, actions: Sequence[CorporateAction]) -> WriteReport:
        self.upserted_actions.extend(actions)
        return WriteReport()

    def quarantine_bars(self, entries: Sequence[QuarantinedBar]) -> int:
        self.quarantined.extend(entries)
        return len(entries)

    def finish_ingestion_run(
        self,
        run_id: str,
        *,
        succeeded: Sequence[str],
        failed: Sequence[str],
        bars_inserted: int,
        bars_modified: int,
        quarantined_count: int,
        warnings: Sequence[str],
    ) -> None:
        self.finished_calls.append(
            {
                "run_id": run_id,
                "succeeded": list(succeeded),
                "failed": list(failed),
                "bars_inserted": bars_inserted,
                "bars_modified": bars_modified,
                "quarantined_count": quarantined_count,
                "warnings": list(warnings),
            }
        )


@pytest.mark.unit
def test_all_tickers_succeed() -> None:
    provider = ResilientProvider(
        FakeProvider(prices={"AAPL": _prices_df(), "MSFT": _prices_df()}), sleep=_no_sleep
    )
    repository = FakeRepository()

    result = run_ingestion(["AAPL", "MSFT"], _START, _END, provider=provider, repository=repository)

    assert result.ok
    assert result.succeeded == ("AAPL", "MSFT")
    assert result.failed == ()
    assert result.bars_inserted == 4
    assert len(repository.upserted_bars) == 4


@pytest.mark.unit
def test_one_ticker_failing_does_not_stop_the_others() -> None:
    """ING-04.1 — o ponto central da tarefa."""

    def broken() -> pd.DataFrame:
        raise ConnectionError("provedor fora do ar")

    provider = ResilientProvider(
        FakeProvider(prices={"AAPL": _prices_df(), "BAD": broken, "MSFT": _prices_df()}),
        sleep=_no_sleep,
    )
    repository = FakeRepository()

    result = run_ingestion(
        ["AAPL", "BAD", "MSFT"], _START, _END, provider=provider, repository=repository
    )

    assert not result.ok
    assert result.succeeded == ("AAPL", "MSFT")
    assert [failure.ticker for failure in result.failed] == ["BAD"]
    # As duas barras de AAPL e as duas de MSFT foram gravadas mesmo com BAD
    # no meio da lista.
    assert len(repository.upserted_bars) == 4


@pytest.mark.unit
def test_failure_reason_is_recorded_on_the_result() -> None:
    def broken() -> pd.DataFrame:
        raise ConnectionError("timeout de conexão")

    provider = ResilientProvider(FakeProvider(prices={"BAD": broken}), sleep=_no_sleep)
    repository = FakeRepository()

    result = run_ingestion(["BAD"], _START, _END, provider=provider, repository=repository)

    assert result.failed[0].ticker == "BAD"
    assert "timeout" in result.failed[0].error or "BAD" in result.failed[0].error


@pytest.mark.unit
def test_empty_price_response_counts_as_failure_not_success() -> None:
    """ING-04.2, agora observado do ponto de vista do orquestrador."""
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    provider = ResilientProvider(FakeProvider(prices={"XYZ": empty}), sleep=_no_sleep)
    repository = FakeRepository()

    result = run_ingestion(["XYZ"], _START, _END, provider=provider, repository=repository)

    assert not result.ok
    assert result.succeeded == ()


@pytest.mark.unit
def test_quarantined_bars_do_not_prevent_success() -> None:
    """Uma barra inválida no meio do lote não derruba o ticker inteiro."""
    invalid_and_valid = pd.DataFrame(
        {
            "Open": [100.0, 100.0],
            "High": [101.0, 101.0],
            "Low": [99.0, 99.0],
            "Close": [100.5, -5.0],  # segunda barra: close não-positivo
            "Volume": [1_000, 1_000],
        },
        index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 2), pd.Timestamp(2024, 1, 3)]),
    )
    provider = ResilientProvider(FakeProvider(prices={"XYZ": invalid_and_valid}), sleep=_no_sleep)
    repository = FakeRepository()

    result = run_ingestion(["XYZ"], _START, _END, provider=provider, repository=repository)

    assert result.ok
    assert result.succeeded == ("XYZ",)
    assert result.bars_inserted == 1
    assert result.quarantined_count == 1
    assert len(repository.quarantined) == 1


@pytest.mark.unit
def test_quarantined_bar_carries_the_run_id() -> None:
    invalid = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [-5.0], "Volume": [1_000]},
        index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 2)]),
    )
    provider = ResilientProvider(FakeProvider(prices={"XYZ": invalid}), sleep=_no_sleep)
    repository = FakeRepository()

    run_ingestion(["XYZ"], _START, _END, provider=provider, repository=repository)

    assert repository.quarantined[0].ingestion_run_id == repository._next_run_id


@pytest.mark.unit
def test_warnings_are_prefixed_with_the_ticker() -> None:
    """Gap de pregões (ING-05.2) atravessa até o resultado final, identificável por ticker."""
    gapped = pd.DataFrame(
        {
            "Open": [100.0, 100.0],
            "High": [101.0, 101.0],
            "Low": [99.0, 99.0],
            "Close": [100.5, 100.5],
            "Volume": [1_000, 1_000],
        },
        # 02/01 -> 22/01: gap bem maior que 5 dias úteis.
        index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 2), pd.Timestamp(2024, 1, 22)]),
    )
    provider = ResilientProvider(FakeProvider(prices={"XYZ": gapped}), sleep=_no_sleep)
    repository = FakeRepository()

    result = run_ingestion(["XYZ"], _START, _END, provider=provider, repository=repository)

    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("XYZ:")


@pytest.mark.unit
def test_ingestion_run_is_finished_with_final_counts() -> None:
    provider = ResilientProvider(FakeProvider(prices={"AAPL": _prices_df(rows=3)}), sleep=_no_sleep)
    repository = FakeRepository()

    run_ingestion(["AAPL"], _START, _END, provider=provider, repository=repository)

    assert len(repository.finished_calls) == 1
    call = repository.finished_calls[0]
    assert call["succeeded"] == ["AAPL"]
    assert call["failed"] == []
    assert call["bars_inserted"] == 3


@pytest.mark.unit
def test_corporate_actions_are_persisted_alongside_bars() -> None:
    provider = ResilientProvider(
        FakeProvider(
            prices={"AAPL": _prices_df()},
            corporate_actions={
                "AAPL": RawCorporateActions(
                    dividends=pd.Series([0.24], index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 3)])),
                    splits=pd.Series(dtype=float),
                )
            },
        ),
        sleep=_no_sleep,
    )
    repository = FakeRepository()

    run_ingestion(["AAPL"], _START, _END, provider=provider, repository=repository)

    assert len(repository.upserted_actions) == 1
    assert repository.upserted_actions[0].value == pytest.approx(0.24)


@pytest.mark.unit
def test_empty_ticker_list_produces_a_no_op_run() -> None:
    repository = FakeRepository()
    provider = ResilientProvider(FakeProvider(), sleep=_no_sleep)
    result = run_ingestion([], _START, _END, provider=provider, repository=repository)

    assert result.ok
    assert result.succeeded == ()
    assert result.bars_inserted == 0
    assert len(repository.finished_calls) == 1
