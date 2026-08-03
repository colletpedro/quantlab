"""Fixtures dos testes de integração.

Exigem MongoDB no ar (`make up` local, ou o serviço do job de integração no
CI). A suíte default não os coleta — RNF-06 manda `make test` rodar offline.

Nenhum teste toca o banco configurado em `QUANTLAB_MONGO_DB`: todos usam um
banco descartável próprio, derrubado ao fim da sessão. Rodar a suíte não pode
destruir os dados de quem está desenvolvendo.
"""

from collections.abc import Iterator

import pytest

from quantlab.config import Settings, get_settings
from quantlab.storage.client import MongoDatabase, create_client
from quantlab.storage.schema import ensure_schema

#: Banco descartável. Nome fixo (RNF-01) e distinto do de produção.
INTEGRATION_DB_NAME = "quantlab_integration_test"


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    """Configuração real do ambiente, com o banco trocado pelo descartável."""
    base = get_settings()
    return Settings(
        _env_file=None,
        mongo_uri=base.mongo_uri,
        mongo_db=INTEGRATION_DB_NAME,
        log_level=base.log_level,
        initial_capital=base.initial_capital,
        risk_free_rate=base.risk_free_rate,
    )


@pytest.fixture
def mongo_db(integration_settings: Settings) -> Iterator[MongoDatabase]:
    """Banco limpo por teste, com coleções e índices já criados.

    Dropar antes *e* depois: antes porque um teste anterior que morreu no meio
    não deve contaminar este; depois para não deixar resíduo na máquina.
    """
    client = create_client(integration_settings)
    try:
        client.drop_database(INTEGRATION_DB_NAME)
        database = client[INTEGRATION_DB_NAME]
        ensure_schema(database)
        yield database
        client.drop_database(INTEGRATION_DB_NAME)
    finally:
        client.close()
