"""Interface de linha de comando do quantlab.

`ingest` (RF-CLI-01, Bloco B) entra aqui. `backtest` (RF-CLI-02) fica para o
Bloco F, quando engine e analytics existirem.
"""

from datetime import date
from importlib import metadata

import typer

from quantlab.config import Settings, get_settings
from quantlab.exceptions import ConfigError
from quantlab.ingestion.orchestrator import IngestionRepository, IngestionRunResult, run_ingestion
from quantlab.ingestion.provider import MarketDataProvider
from quantlab.ingestion.resilient_provider import ResilientProvider
from quantlab.ingestion.yfinance_provider import YFinanceProvider
from quantlab.logging import configure_logging, get_logger
from quantlab.storage.client import mongo_database
from quantlab.storage.repository import MongoRepository
from quantlab.storage.schema import ensure_schema
from quantlab.universe import load_default_universe

__all__ = ["app"]

app = typer.Typer(
    name="quantlab",
    help="Plataforma de backtesting de estratégias sistemáticas.",
    no_args_is_help=True,
    add_completion=False,
)

log = get_logger(__name__)


def _installed_version() -> str:
    """Versão do pacote instalado, com fallback quando rodando fora de install."""
    try:
        return metadata.version("quantlab")
    except metadata.PackageNotFoundError:  # pragma: no cover - ambiente não instalado
        return "desconhecida"


def _parse_date(value: str, *, option: str) -> date:
    """AAAA-MM-DD para `date`. Erro de formato vira `typer.BadParameter`."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            f"{option} precisa estar em AAAA-MM-DD, recebeu {value!r}."
        ) from exc


def _resolve_tickers(tickers_csv: str | None, settings: Settings) -> list[str]:
    """`--tickers` explícito, ou o universo default — CA-01.1."""
    if tickers_csv is not None:
        parsed = [item.strip().upper() for item in tickers_csv.split(",") if item.strip()]
        if not parsed:
            raise ConfigError("--tickers foi passado, mas não contém nenhum ticker.")
        return parsed
    return load_default_universe(settings.universe_path)


def _build_provider() -> MarketDataProvider:
    """Provedor real, com resiliência — isolado para que testes substituam por um fake."""
    return ResilientProvider(YFinanceProvider())


def run_ingest(
    tickers_csv: str | None,
    from_date: str,
    to_date: str,
    *,
    settings: Settings,
    provider: MarketDataProvider,
    repository: IngestionRepository,
) -> IngestionRunResult:
    """Lógica de RF-CLI-01, sem Typer nem Mongo — testável direto.

    A resolução de argumentos (data, tickers) e a chamada ao orquestrador
    vivem aqui; `ingest()` abaixo só faz parsing de CLI e conecta as
    dependências reais.
    """
    start = _parse_date(from_date, option="--from")
    end = _parse_date(to_date, option="--to")
    tickers = _resolve_tickers(tickers_csv, settings)
    return run_ingestion(tickers, start, end, provider=provider, repository=repository)


@app.callback()
def main() -> None:
    """Configura o logging antes de qualquer subcomando."""
    configure_logging(get_settings().log_level)


@app.command()
def version() -> None:
    """Mostra a versão instalada do quantlab."""
    log.info("quantlab.version", version=_installed_version())


@app.command()
def ingest(
    tickers: str | None = typer.Option(
        None,
        "--tickers",
        help="Tickers separados por vírgula (ex.: AAPL,MSFT). Sem isto, usa o "
        "universo default de config/universe.yml.",
    ),
    from_date: str = typer.Option(..., "--from", help="Data inicial, AAAA-MM-DD."),
    to_date: str = typer.Option(..., "--to", help="Data final, AAAA-MM-DD."),
) -> None:
    """RF-CLI-01 — ingesta OHLCV bruto e eventos corporativos.

    ```
    python -m quantlab ingest --tickers AAPL,MSFT --from 2015-01-01 --to 2024-12-31
    ```
    """
    settings = get_settings()
    provider = _build_provider()

    with mongo_database(settings) as database:
        ensure_schema(database)
        repository = MongoRepository(database)
        result = run_ingest(
            tickers, from_date, to_date, settings=settings, provider=provider, repository=repository
        )

    log.info(
        "cli.ingest.finished",
        run_id=result.run_id,
        tickers=list(result.tickers),
        succeeded=list(result.succeeded),
        failed=[failure.ticker for failure in result.failed],
        bars_inserted=result.bars_inserted,
        bars_modified=result.bars_modified,
        quarantined_count=result.quarantined_count,
        warning_count=len(result.warnings),
    )
    for failure in result.failed:
        log.error("cli.ingest.ticker_failed", ticker=failure.ticker, error=failure.error)

    if not result.ok:
        # ING-04.1 — código de saída != 0 quando qualquer ticker falhou.
        raise typer.Exit(code=1)
