"""Interface de linha de comando do quantlab.

`ingest` (RF-CLI-01, Bloco B) e `backtest` (RF-CLI-02, Bloco F) entram aqui.
"""

from datetime import date
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol

import typer

from quantlab.analytics.benchmark import buy_and_hold
from quantlab.analytics.plot import plot_backtest
from quantlab.analytics.report import BacktestReport
from quantlab.config import Settings, get_settings
from quantlab.engine.backtest import BacktestResult, EquityPoint, run_backtest
from quantlab.engine.broker import CostModel
from quantlab.engine.portfolio import Trade
from quantlab.exceptions import ConfigError, DataError, EngineError
from quantlab.ingestion.orchestrator import IngestionRepository, IngestionRunResult, run_ingestion
from quantlab.ingestion.provider import MarketDataProvider
from quantlab.ingestion.resilient_provider import ResilientProvider
from quantlab.ingestion.yfinance_provider import YFinanceProvider
from quantlab.logging import configure_logging, get_logger
from quantlab.storage.client import mongo_database
from quantlab.storage.repository import MongoRepository, to_bson_date
from quantlab.storage.schema import ensure_schema
from quantlab.storage.series import PriceSeries
from quantlab.strategies.sma_cross import SmaCross
from quantlab.universe import load_default_universe

__all__ = ["app"]

#: Fase 1 só tem uma estratégia. O registro existe para que `--strategy`
#: falhe com mensagem acionável em vez de `AttributeError`, e para não
#: precisar de `if/elif` no dia em que uma segunda entrar (Fase 2).
_STRATEGIES = frozenset({"sma_cross"})

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


def _parse_optional_date(value: str | None, *, option: str) -> date | None:
    """Como `_parse_date`, mas `None` passa direto — janela sem tampa superior."""
    if value is None:
        return None
    return _parse_date(value, option=option)


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


# ─── backtest — RF-CLI-02, Bloco F ───────────────────────────────────────────

#: D5 do requirements — janela default de backtest: ~10 anos, cobrindo o
#: choque de 2020. `--to` sem default: `None` significa "sem tampa superior",
#: que `get_series` já interpreta como "até a última barra disponível".
_DEFAULT_FROM = "2015-01-01"


def _trade_to_dict(trade: Trade) -> dict[str, Any]:
    return {
        "ticker": trade.ticker,
        "entry_date": trade.entry_date.isoformat(),
        "entry_price": trade.entry_price,
        "entry_decision_date": trade.entry_decision_date.isoformat(),
        "quantity": trade.quantity,
        "entry_cost": trade.entry_cost,
        "entry_gap_days": trade.entry_gap_days,
        "exit_date": trade.exit_date.isoformat() if trade.exit_date is not None else None,
        "exit_price": trade.exit_price,
        "exit_cost": trade.exit_cost,
        "exit_gap_days": trade.exit_gap_days,
        "exit_decision_date": (
            trade.exit_decision_date.isoformat() if trade.exit_decision_date is not None else None
        ),
    }


def _equity_point_to_dict(point: EquityPoint) -> dict[str, Any]:
    return {
        "date": point.date.isoformat(),
        "equity": point.equity,
        "cash": point.cash,
        "position_value": point.position_value,
    }


def _build_run_document(
    *,
    ticker: str,
    strategy_name: str,
    strategy_params: dict[str, Any],
    start: date,
    end: date | None,
    initial_cash: float,
    costs: CostModel,
    report: BacktestReport,
    strategy_result: BacktestResult,
    benchmark_result: BacktestResult,
) -> dict[str, Any]:
    """Monta o documento de `backtest_runs` — design §3.5.

    `storage/` não sabe o que é `BacktestReport`; montar o documento é
    trabalho da camada que conhece os dois lados (CLI), não do repositório,
    que só grava o que recebe.
    """
    return {
        "ticker": ticker,
        "strategy": {"name": strategy_name, "params": strategy_params},
        "window": {
            "start": to_bson_date(start),
            "end": to_bson_date(end) if end is not None else None,
        },
        "initial_capital": initial_cash,
        "costs": {"fixed": costs.fixed, "rate": costs.rate},
        "report": report.to_dict(),
        "strategy_trades": [_trade_to_dict(trade) for trade in strategy_result.trades],
        "strategy_equity_curve": [
            _equity_point_to_dict(point) for point in strategy_result.equity_curve
        ],
        "benchmark_trades": [_trade_to_dict(trade) for trade in benchmark_result.trades],
        "benchmark_equity_curve": [
            _equity_point_to_dict(point) for point in benchmark_result.equity_curve
        ],
        "quantlab_version": _installed_version(),
    }


class BacktestRepository(Protocol):
    """O que `run_backtest_flow` precisa do repositório — recorte de `MongoRepository`.

    Mesmo padrão de `IngestionRepository` em `ingestion/orchestrator.py`:
    `Protocol` estrutural, para que testes unitários usem um fake em memória
    sem herdar de `MongoRepository` nem tocar Mongo de verdade.
    """

    def get_series(
        self, ticker: str, start: date | None = None, end: date | None = None
    ) -> PriceSeries: ...

    def save_backtest_run(self, document: dict[str, Any]) -> str: ...


class BacktestOutcome:
    """O que `run_backtest_flow` produz — testável sem Typer nem Mongo real."""

    __slots__ = ("benchmark_result", "report", "run_id", "strategy_result")

    def __init__(
        self,
        *,
        report: BacktestReport,
        strategy_result: BacktestResult,
        benchmark_result: BacktestResult,
        run_id: str,
    ) -> None:
        self.report = report
        self.strategy_result = strategy_result
        self.benchmark_result = benchmark_result
        self.run_id = run_id


def run_backtest_flow(
    *,
    strategy_name: str,
    ticker: str,
    from_date: str,
    to_date: str | None,
    fast: int,
    slow: int,
    settings: Settings,
    repository: BacktestRepository,
) -> BacktestOutcome:
    """Lógica de RF-CLI-02, sem Typer nem gráfico — testável direto.

    Mesma separação de `run_ingest`: resolução de argumentos e orquestração
    de engine/analytics/persistência vivem aqui; `backtest()` abaixo só faz
    parsing de CLI, imprime e desenha o gráfico.
    """
    if strategy_name not in _STRATEGIES:
        raise typer.BadParameter(
            f"Estratégia desconhecida: {strategy_name!r}. Disponíveis: {sorted(_STRATEGIES)}."
        )

    start = _parse_date(from_date, option="--from")
    end = _parse_optional_date(to_date, option="--to")
    ticker = ticker.strip().upper()

    strategy = SmaCross(fast=fast, slow=slow)
    # CA-02.2 — ticker sem dado ingerido levanta DataError com mensagem
    # acionável, propagada por get_series/build_price_series.
    series = repository.get_series(ticker, start=start, end=end)

    costs = CostModel()
    strategy_result = run_backtest(
        series, strategy, initial_cash=settings.initial_capital, costs=costs
    )
    benchmark_result = buy_and_hold(
        series, warmup=strategy.warmup, initial_cash=settings.initial_capital, costs=costs
    )
    report = BacktestReport.build(
        strategy=strategy_result,
        benchmark=benchmark_result,
        strategy_name=strategy_name,
        strategy_params={"fast": fast, "slow": slow},
        rf=settings.risk_free_rate,
    )

    document = _build_run_document(
        ticker=ticker,
        strategy_name=strategy_name,
        strategy_params={"fast": fast, "slow": slow},
        start=start,
        end=end,
        initial_cash=settings.initial_capital,
        costs=costs,
        report=report,
        strategy_result=strategy_result,
        benchmark_result=benchmark_result,
    )
    run_id = repository.save_backtest_run(document)

    return BacktestOutcome(
        report=report,
        strategy_result=strategy_result,
        benchmark_result=benchmark_result,
        run_id=run_id,
    )


@app.command()
def backtest(
    strategy: str = typer.Option(
        "sma_cross", "--strategy", help="Estratégia. Só `sma_cross` na Fase 1."
    ),
    ticker: str = typer.Option(..., "--ticker", help="Ticker único (ex.: AAPL)."),
    from_date: str = typer.Option(
        _DEFAULT_FROM, "--from", help="Data inicial, AAAA-MM-DD (default: D5, 2015-01-01)."
    ),
    to_date: str | None = typer.Option(
        None, "--to", help="Data final, AAAA-MM-DD. Sem isto, vai até a última barra disponível."
    ),
    fast: int = typer.Option(20, "--fast", help="Período rápido da SMA cross."),
    slow: int = typer.Option(50, "--slow", help="Período lento da SMA cross."),
    output_dir: str = typer.Option(
        "results", "--output-dir", help="Diretório para o gráfico (.png) e o relatório (.json)."
    ),
) -> None:
    """RF-CLI-02 — roda um backtest, imprime o relatório e salva o gráfico.

    ```
    python -m quantlab backtest --strategy sma_cross --ticker AAPL \\
        --from 2015-01-01 --fast 20 --slow 50
    ```
    """
    settings = get_settings()

    with mongo_database(settings) as database:
        ensure_schema(database)
        repository = MongoRepository(database)
        try:
            outcome = run_backtest_flow(
                strategy_name=strategy,
                ticker=ticker,
                from_date=from_date,
                to_date=to_date,
                fast=fast,
                slow=slow,
                settings=settings,
                repository=repository,
            )
        except (DataError, EngineError) as exc:
            # CA-02.2 — ticker sem dado ingerido (ou outra falha de execução)
            # falha com mensagem acionável e código de saída != 0.
            log.error("cli.backtest.failed", ticker=ticker, error=str(exc))
            typer.echo(f"Backtest falhou: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    typer.echo(outcome.report.to_text())  # CA-02.1 — relatório impresso no CLI

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    base_name = f"{ticker.upper()}_{strategy}_{fast}_{slow}"

    plot_path = plot_backtest(
        ticker=ticker.upper(),
        strategy=outcome.strategy_result,
        benchmark=outcome.benchmark_result,
        output_path=destination / f"{base_name}.png",
    )
    report_path = destination / f"{base_name}.json"
    report_path.write_text(outcome.report.to_json(), encoding="utf-8")

    log.info(
        "cli.backtest.finished",
        ticker=ticker.upper(),
        run_id=outcome.run_id,
        plot=str(plot_path),
        report=str(report_path),
    )
