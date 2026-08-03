"""Orquestrador de ingestão — B4.

Laço sobre tickers: busca (B1) → normaliza (B2) → valida (B3) → grava
(`storage.MongoRepository`, Bloco A). Falha de **um** ticker não impede os
demais (ING-04.1); o run inteiro é registrado em `ingestion_runs`, com
sucesso e falha por ticker, e o resultado carrega o que a CLI (B6) precisa
para decidir o código de saída.

O `provider` recebido aqui deve já vir envolto em resiliência — normalmente
``ResilientProvider(YFinanceProvider())`` — porque este módulo trata
`DataError` como falha definitiva de um ticker, não como algo a repetir. A
decisão de tentar de novo é do provedor (B1), não do orquestrador.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from quantlab.exceptions import DataError
from quantlab.ingestion.normalizer import normalize_corporate_actions, normalize_prices
from quantlab.ingestion.provider import MarketDataProvider
from quantlab.ingestion.validator import validate_bars
from quantlab.logging import get_logger
from quantlab.storage.models import Bar, CorporateAction, QuarantinedBar
from quantlab.storage.repository import WriteReport

__all__ = ["IngestionRepository", "IngestionRunResult", "TickerFailure", "run_ingestion"]

_log = get_logger(__name__)


class IngestionRepository(Protocol):
    """O que o orquestrador precisa do repositório — recorte de `MongoRepository`.

    Como `MarketDataProvider`, é `Protocol` estrutural: `MongoRepository` já
    implementa isto sem herdar de nada, e os testes unitários usam um fake em
    memória que também implementa sem herdar. `MongoRepository` continua
    tendo mais métodos (`get_series` etc.) que o orquestrador não usa e este
    protocolo não lista.
    """

    def start_ingestion_run(self, tickers: Sequence[str], start: date, end: date) -> str: ...

    def upsert_bars(self, bars: Sequence[Bar]) -> WriteReport: ...

    def upsert_corporate_actions(self, actions: Sequence[CorporateAction]) -> WriteReport: ...

    def quarantine_bars(self, entries: Sequence[QuarantinedBar]) -> int: ...

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
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class TickerFailure:
    """Um ticker que não completou — ING-04.1."""

    ticker: str
    error: str


@dataclass(frozen=True, slots=True)
class IngestionRunResult:
    """O que um run de ingestão produziu, para a CLI decidir saída e mensagem."""

    run_id: str
    tickers: tuple[str, ...]
    succeeded: tuple[str, ...]
    failed: tuple[TickerFailure, ...]
    bars_inserted: int
    bars_modified: int
    quarantined_count: int
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """``False`` se qualquer ticker falhou — ING-04.1 exige saída ≠ 0 nesse caso."""
        return not self.failed


def run_ingestion(
    tickers: Sequence[str],
    start: date,
    end: date,
    *,
    provider: MarketDataProvider,
    repository: IngestionRepository,
) -> IngestionRunResult:
    """Ingesta `tickers` na janela `[start, end]`, ticker por ticker.

    Nunca levanta por falha de **um** ticker: a exceção é capturada, o ticker
    entra em `failed`, e o laço segue para o próximo. Uma exceção que escape
    daqui é bug de programação, não falha de dado — e deve mesmo propagar.
    """
    run_id = repository.start_ingestion_run(tickers=tickers, start=start, end=end)
    _log.info("ingestion.run_started", run_id=run_id, tickers=list(tickers))

    succeeded: list[str] = []
    failed: list[TickerFailure] = []
    all_warnings: list[str] = []
    total_inserted = 0
    total_modified = 0
    total_quarantined = 0

    for ticker in tickers:
        try:
            raw_prices = provider.fetch_prices(ticker, start, end)
            bars = normalize_prices(ticker, raw_prices)

            raw_actions = provider.fetch_corporate_actions(ticker)
            actions = normalize_corporate_actions(ticker, raw_actions)

            result = validate_bars(bars, actions, ingestion_run_id=run_id)

            bar_report = repository.upsert_bars(result.valid_bars)
            repository.upsert_corporate_actions(actions)
            quarantined_count = repository.quarantine_bars(result.quarantined_bars)
        except DataError as exc:
            failed.append(TickerFailure(ticker=ticker, error=str(exc)))
            _log.error("ingestion.ticker_failed", run_id=run_id, ticker=ticker, error=str(exc))
            continue

        total_inserted += bar_report.inserted
        total_modified += bar_report.modified
        total_quarantined += quarantined_count
        all_warnings.extend(f"{ticker}: {message}" for message in result.warnings)
        succeeded.append(ticker)
        _log.info(
            "ingestion.ticker_succeeded",
            run_id=run_id,
            ticker=ticker,
            inserted=bar_report.inserted,
            modified=bar_report.modified,
            quarantined=quarantined_count,
        )

    repository.finish_ingestion_run(
        run_id,
        succeeded=succeeded,
        failed=[failure.ticker for failure in failed],
        bars_inserted=total_inserted,
        bars_modified=total_modified,
        quarantined_count=total_quarantined,
        warnings=all_warnings,
    )
    _log.info(
        "ingestion.run_finished",
        run_id=run_id,
        succeeded=len(succeeded),
        failed=len(failed),
    )

    return IngestionRunResult(
        run_id=run_id,
        tickers=tuple(tickers),
        succeeded=tuple(succeeded),
        failed=tuple(failed),
        bars_inserted=total_inserted,
        bars_modified=total_modified,
        quarantined_count=total_quarantined,
        warnings=tuple(all_warnings),
    )
