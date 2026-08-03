"""B6 — `python -m quantlab ingest` ponta a ponta: CLI real, Mongo real, provedor falso.

`_build_provider` (quantlab.cli) é substituído por monkeypatch para devolver
um `FakeProvider` — é o único ponto de acesso à rede no comando, e trocá-lo
é o que permite exercitar o parsing de argumentos, o código de saída e a
escrita em Mongo de verdade, sem tocar `yfinance`.
"""

import logging
from collections.abc import Iterator

import pandas as pd
import pytest
import structlog
from typer.testing import CliRunner

import quantlab.cli as cli_module
from quantlab.cli import app
from quantlab.config import Settings, get_settings
from quantlab.ingestion.resilient_provider import ResilientProvider
from quantlab.storage.client import MongoDatabase
from quantlab.storage.schema import BARS, INGESTION_RUNS, QUARANTINED_BARS
from tests.support import FakeProvider


@pytest.fixture(autouse=True)
def _isolate_settings_cache() -> Iterator[None]:
    """Limpa o cache de `get_settings()` depois de cada teste deste arquivo.

    `_env_for` já limpa antes de cada chamada, mas `monkeypatch` só reverte as
    variáveis de ambiente ao fim do teste — o cache de `lru_cache` continuaria
    apontando para o banco descartável deste teste até outra chamada limpá-lo.
    Sem isto, um teste em outro arquivo que chame `get_settings()` sem passar
    por `clean_env` herdaria a configuração deste, quebrando isolamento.
    """
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_logging_config() -> Iterator[None]:
    """Restaura structlog e o root logger do stdlib depois de cada teste.

    `CliRunner().invoke(app, ...)` roda o callback `main()` de verdade, que
    chama `configure_logging()` — e essa função faz `logging.basicConfig(...,
    force=True)`, reconfigurando o root logger GLOBALMENTE para o processo
    inteiro do pytest, não só para este teste. Sem restaurar, os handlers que
    o pytest instala para capturar log ficam substituídos para o resto da
    sessão.

    A causa mais profunda — `cache_logger_on_first_use=True` fazendo
    `BoundLoggerLazyProxy.bind()` sobrescrever `.bind` na própria instância do
    proxy na primeira chamada, permanentemente, ignorando qualquer
    reconfiguração futura — foi corrigida na fonte, em
    `quantlab/logging.py`. `reset_defaults()` aqui é defesa em profundidade;
    sem a correção na fonte, nenhum reset neste fixture teria bastado
    (confirmado enquanto o bug ainda estava só aqui: os testes de A4/A6 que
    dependem de `log_events` falhavam de forma dependente de ordem mesmo com
    o config global restaurado, porque o proxy já monkeypatchado ignora
    `structlog.configure()`/`reset_defaults()` subsequentes).
    """
    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    previous_level = root_logger.level

    yield

    root_logger.handlers = previous_handlers
    root_logger.setLevel(previous_level)
    structlog.reset_defaults()


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


def _patch_provider(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider) -> None:
    monkeypatch.setattr(cli_module, "_build_provider", lambda: ResilientProvider(provider))


def _env_for(monkeypatch: pytest.MonkeyPatch, mongo_uri: str, mongo_db: str) -> None:
    """Aponta o processo do CLI para o banco de teste, do jeito que `Settings` lê: env."""
    monkeypatch.setenv("QUANTLAB_MONGO_URI", mongo_uri)
    monkeypatch.setenv("QUANTLAB_MONGO_DB", mongo_db)
    get_settings.cache_clear()


@pytest.mark.integration
def test_ingest_command_writes_to_mongo_and_exits_zero(
    mongo_db: MongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
    integration_settings: Settings,
) -> None:
    _patch_provider(monkeypatch, FakeProvider(prices={"AAPL": _prices_df(), "MSFT": _prices_df()}))
    _env_for(monkeypatch, integration_settings.mongo_uri, mongo_db.name)

    result = CliRunner().invoke(
        app, ["ingest", "--tickers", "AAPL,MSFT", "--from", "2024-01-01", "--to", "2024-01-05"]
    )

    assert result.exit_code == 0, result.output
    assert mongo_db[BARS].count_documents({}) == 4
    assert mongo_db[INGESTION_RUNS].count_documents({}) == 1


@pytest.mark.integration
def test_ingest_command_exits_nonzero_when_a_ticker_fails(
    mongo_db: MongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
    integration_settings: Settings,
) -> None:
    def broken() -> pd.DataFrame:
        raise ConnectionError("provedor fora do ar")

    _patch_provider(monkeypatch, FakeProvider(prices={"AAPL": _prices_df(), "BAD": broken}))
    _env_for(monkeypatch, integration_settings.mongo_uri, mongo_db.name)

    result = CliRunner().invoke(
        app, ["ingest", "--tickers", "AAPL,BAD", "--from", "2024-01-01", "--to", "2024-01-05"]
    )

    assert result.exit_code != 0
    # AAPL foi gravado mesmo com a falha de BAD (ING-04.1).
    assert mongo_db[BARS].count_documents({"ticker": "AAPL"}) == 2


@pytest.mark.integration
def test_ingest_command_uses_default_universe_without_tickers_flag(
    mongo_db: MongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
    integration_settings: Settings,
) -> None:
    """CA-01.1 — sem --tickers, o comando de verdade usa o universo default."""
    monkeypatch.setattr(cli_module, "load_default_universe", lambda _path: ["AAPL", "MSFT"])
    _patch_provider(monkeypatch, FakeProvider(prices={"AAPL": _prices_df(), "MSFT": _prices_df()}))
    _env_for(monkeypatch, integration_settings.mongo_uri, mongo_db.name)

    result = CliRunner().invoke(app, ["ingest", "--from", "2024-01-01", "--to", "2024-01-05"])

    assert result.exit_code == 0, result.output
    run_doc = mongo_db[INGESTION_RUNS].find_one({})
    assert run_doc is not None
    assert sorted(run_doc["tickers"]) == ["AAPL", "MSFT"]


@pytest.mark.integration
def test_ingest_command_rejects_malformed_date(
    mongo_db: MongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
    integration_settings: Settings,
) -> None:
    _patch_provider(monkeypatch, FakeProvider())
    _env_for(monkeypatch, integration_settings.mongo_uri, mongo_db.name)

    result = CliRunner().invoke(
        app, ["ingest", "--tickers", "AAPL", "--from", "não-é-data", "--to", "2024-01-05"]
    )

    assert result.exit_code != 0
    assert mongo_db[BARS].count_documents({}) == 0


@pytest.mark.integration
def test_ingest_command_quarantines_invalid_bars(
    mongo_db: MongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
    integration_settings: Settings,
) -> None:
    invalid = pd.DataFrame(
        {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [-5.0], "Volume": [1_000]},
        index=pd.DatetimeIndex([pd.Timestamp(2024, 1, 2)]),
    )
    _patch_provider(monkeypatch, FakeProvider(prices={"XYZ": invalid}))
    _env_for(monkeypatch, integration_settings.mongo_uri, mongo_db.name)

    result = CliRunner().invoke(
        app, ["ingest", "--tickers", "XYZ", "--from", "2024-01-01", "--to", "2024-01-05"]
    )

    assert result.exit_code == 0, result.output
    assert mongo_db[BARS].count_documents({"ticker": "XYZ"}) == 0
    assert mongo_db[QUARANTINED_BARS].count_documents({"ticker": "XYZ"}) == 1


@pytest.mark.integration
def test_ingest_command_creates_schema_on_a_fresh_database(
    mongo_db: MongoDatabase,
    monkeypatch: pytest.MonkeyPatch,
    integration_settings: Settings,
) -> None:
    """O comando precisa funcionar contra um Mongo que nunca viu quantlab antes."""
    for name in mongo_db.list_collection_names():
        mongo_db.drop_collection(name)
    assert mongo_db.list_collection_names() == []

    _patch_provider(monkeypatch, FakeProvider(prices={"AAPL": _prices_df()}))
    _env_for(monkeypatch, integration_settings.mongo_uri, mongo_db.name)

    result = CliRunner().invoke(
        app, ["ingest", "--tickers", "AAPL", "--from", "2024-01-01", "--to", "2024-01-05"]
    )

    assert result.exit_code == 0, result.output
    assert mongo_db[BARS].count_documents({}) == 2
