"""B6 — lógica de `ingest` (RF-CLI-01), sem Typer nem Mongo.

`run_ingest` é a função que `cli.ingest` delega para depois de resolver
argumentos de CLI e conectar dependências reais — testá-la direto, com
`FakeProvider`/`FakeRepository`, cobre CA-01.1 e o parsing de data sem
precisar de `CliRunner` nem de banco. O teste ponta a ponta de verdade
(`CliRunner` + Mongo real) é `tests/integration/test_cli_ingest.py`.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import typer
import yaml

from quantlab.cli import _parse_date, _resolve_tickers, run_ingest
from quantlab.config import Settings
from quantlab.exceptions import ConfigError
from quantlab.ingestion.resilient_provider import ResilientProvider
from tests.support import FakeProvider, FakeRepository


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


@pytest.mark.unit
def test_parse_date_accepts_iso_format() -> None:
    assert _parse_date("2024-01-02", option="--from") == date(2024, 1, 2)


@pytest.mark.unit
def test_parse_date_rejects_malformed_input() -> None:
    with pytest.raises(typer.BadParameter, match="--from"):
        _parse_date("02/01/2024", option="--from")


@pytest.mark.unit
def test_resolve_tickers_uses_explicit_csv(settings: Settings) -> None:
    assert _resolve_tickers("aapl, msft", settings) == ["AAPL", "MSFT"]


@pytest.mark.unit
def test_resolve_tickers_falls_back_to_default_universe(tmp_path: Path, settings: Settings) -> None:
    """CA-01.1 — sem --tickers, usa o universo default do arquivo de configuração."""
    universe_file = tmp_path / "universe.yml"
    universe_file.write_text(
        yaml.safe_dump({"universe": [{"ticker": "AAPL"}, {"ticker": "MSFT"}]}),
        encoding="utf-8",
    )
    settings_with_universe = Settings(
        _env_file=None, mongo_uri=settings.mongo_uri, universe_path=str(universe_file)
    )

    assert _resolve_tickers(None, settings_with_universe) == ["AAPL", "MSFT"]


@pytest.mark.unit
def test_resolve_tickers_rejects_blank_csv(settings: Settings) -> None:
    with pytest.raises(ConfigError, match="--tickers"):
        _resolve_tickers("  ,  ", settings)


@pytest.mark.unit
def test_run_ingest_end_to_end_with_fakes(settings: Settings) -> None:
    provider = ResilientProvider(FakeProvider(prices={"AAPL": _prices_df()}), sleep=_no_sleep)
    repository = FakeRepository()

    result = run_ingest(
        "AAPL",
        "2024-01-01",
        "2024-01-05",
        settings=settings,
        provider=provider,
        repository=repository,
    )

    assert result.ok
    assert result.succeeded == ("AAPL",)
    assert len(repository.upserted_bars) == 2


@pytest.mark.unit
def test_run_ingest_propagates_ticker_failure(settings: Settings) -> None:
    def broken() -> pd.DataFrame:
        raise ConnectionError("fora do ar")

    provider = ResilientProvider(FakeProvider(prices={"BAD": broken}), sleep=_no_sleep)
    repository = FakeRepository()

    result = run_ingest(
        "BAD",
        "2024-01-01",
        "2024-01-05",
        settings=settings,
        provider=provider,
        repository=repository,
    )

    assert not result.ok
    assert result.failed[0].ticker == "BAD"


@pytest.mark.unit
def test_run_ingest_rejects_malformed_date(settings: Settings) -> None:
    provider = ResilientProvider(FakeProvider(), sleep=_no_sleep)
    repository = FakeRepository()

    with pytest.raises(typer.BadParameter):
        run_ingest(
            "AAPL",
            "not-a-date",
            "2024-01-05",
            settings=settings,
            provider=provider,
            repository=repository,
        )
