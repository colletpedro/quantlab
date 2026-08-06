"""Suporte compartilhado entre `tests/unit/` e `tests/integration/`.

Não é suíte de teste — o nome não começa com `test_` de propósito, e pytest
não coleta este arquivo. `pythonpath = ["."]` em `pyproject.toml` é o que
permite `from tests.support import FakeProvider` funcionar sem `tests/`
precisar de `__init__.py`.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from quantlab.exceptions import DataError
from quantlab.ingestion.provider import RawCorporateActions
from quantlab.storage.models import Bar, CorporateAction, QuarantinedBar
from quantlab.storage.repository import WriteReport
from quantlab.storage.series import PriceSeries

__all__ = [
    "FakeBacktestRepository",
    "FakeProvider",
    "FakeRepository",
    "empty_corporate_actions",
]


def empty_corporate_actions() -> RawCorporateActions:
    """O caso comum: ticker sem dividendo nem split registrado."""
    return RawCorporateActions(dividends=pd.Series(dtype=float), splits=pd.Series(dtype=float))


class FakeProvider:
    """`MarketDataProvider` de teste: respostas programadas, zero I/O.

    `MarketDataProvider` é um `Protocol` estrutural — esta classe não herda
    dele, só implementa a mesma forma, exatamente como `YFinanceProvider` faz.

    - `prices`: mapa ticker → `DataFrame`, ou uma função sem argumentos que
      devolve o `DataFrame` (ou levanta) quando chamada. A forma de função é o
      que permite simular falha intermitente: um fake que levanta nas duas
      primeiras chamadas e só devolve dado na terceira, para testar retry sem
      esperar rede de verdade cair.
    - `corporate_actions`: mapa ticker → `RawCorporateActions`. Ticker ausente
      devolve "sem eventos" (`empty_corporate_actions()`), o caso comum — a
      ausência de proventos é legítima e não deveria exigir programação
      explícita em todo teste.
    - Ticker ausente de `prices` levanta `KeyError`: um teste que esqueceu de
      programar um ticker deve falhar alto e apontando a causa, não devolver
      silenciosamente algo genérico.
    """

    def __init__(
        self,
        prices: dict[str, pd.DataFrame | Callable[[], pd.DataFrame]] | None = None,
        corporate_actions: dict[str, RawCorporateActions] | None = None,
    ) -> None:
        self._prices = prices or {}
        self._corporate_actions = corporate_actions or {}
        #: Chamadas recebidas, na ordem — para testes que precisam verificar
        #: *que* o provedor foi chamado, não só o que ele devolveu.
        self.price_calls: list[tuple[str, date, date]] = []
        self.corporate_action_calls: list[str] = []

    def fetch_prices(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        self.price_calls.append((ticker, start, end))
        if ticker not in self._prices:
            raise KeyError(f"FakeProvider sem preços programados para {ticker!r}.")
        entry = self._prices[ticker]
        return entry() if callable(entry) else entry

    def fetch_corporate_actions(self, ticker: str) -> RawCorporateActions:
        self.corporate_action_calls.append(ticker)
        return self._corporate_actions.get(ticker, empty_corporate_actions())


@dataclass
class FakeRepository:
    """`IngestionRepository` de teste: registra o que o orquestrador gravaria.

    Implementa a mesma forma que `orchestrator.IngestionRepository` declara —
    não herda dela, é `Protocol` estrutural, igual a `FakeProvider` para
    `MarketDataProvider`. Usada tanto por `test_orchestrator.py` (B4) quanto
    por testes de CLI (B6) que precisam da lógica de `run_ingest` sem Mongo.
    """

    upserted_bars: list[Bar] = field(default_factory=list)
    upserted_actions: list[CorporateAction] = field(default_factory=list)
    quarantined: list[QuarantinedBar] = field(default_factory=list)
    finished_calls: list[dict[str, object]] = field(default_factory=list)
    next_run_id: str = "run-1"
    #: Data UTC fixa devolvida por `current_execution_date` — RF-CON-01.
    #: Bem à frente de qualquer fixture de teste por default, para que
    #: nenhuma barra de teste seja descartada por acidente sem o teste pedir.
    execution_date: date = date(2999, 1, 1)

    def start_ingestion_run(self, tickers: Sequence[str], start: date, end: date) -> str:
        return self.next_run_id

    def current_execution_date(self) -> date:
        return self.execution_date

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
        discarded_in_progress_count: int,
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
                "discarded_in_progress_count": discarded_in_progress_count,
                "warnings": list(warnings),
            }
        )


@dataclass
class FakeBacktestRepository:
    """`cli.BacktestRepository` de teste: série programada, gravação em memória.

    Mesmo padrão estrutural de `FakeRepository` para `IngestionRepository` —
    implementa a forma que `cli.BacktestRepository` declara, sem herdar dela
    nem tocar Mongo.
    """

    series_by_ticker: dict[str, PriceSeries] = field(default_factory=dict)
    saved_runs: list[dict[str, Any]] = field(default_factory=list)
    next_run_id: str = "run-1"

    def get_series(
        self, ticker: str, start: date | None = None, end: date | None = None
    ) -> PriceSeries:
        if ticker not in self.series_by_ticker:
            # Mesma exceção que `build_price_series` levanta para ticker sem
            # barra nenhuma — o que `cli.run_backtest_flow` precisa propagar
            # para CA-02.2.
            raise DataError(
                f"Nenhuma barra encontrada para {ticker}. Rode a ingestão para {ticker} "
                "antes do backtest."
            )
        return self.series_by_ticker[ticker]

    def save_backtest_run(self, document: dict[str, Any]) -> str:
        self.saved_runs.append(document)
        return self.next_run_id
