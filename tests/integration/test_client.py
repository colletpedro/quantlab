"""A1 — conexão, ping e fechamento determinístico."""

import pytest

from quantlab.config import Settings
from quantlab.exceptions import DataError
from quantlab.storage.client import check_connection, create_client, mongo_database


@pytest.mark.integration
def test_connects_pings_and_closes(integration_settings: Settings) -> None:
    """O caminho feliz: conecta, responde ao ping, fecha."""
    client = create_client(integration_settings)
    try:
        check_connection(client)
    finally:
        client.close()


@pytest.mark.integration
def test_mongo_database_yields_configured_database(integration_settings: Settings) -> None:
    """O context manager entrega o banco de `Settings.mongo_db`."""
    with mongo_database(integration_settings) as database:
        assert database.name == integration_settings.mongo_db
        assert database.command("ping")["ok"] == pytest.approx(1.0)


@pytest.mark.integration
def test_unreachable_server_raises_actionable_data_error(
    integration_settings: Settings,
) -> None:
    """Servidor fora do ar vira `DataError` dizendo o que fazer.

    A porta 1 é reservada e não tem Mongo — falha determinística, sem depender
    de nenhuma condição da máquina.
    """
    unreachable = Settings(
        _env_file=None,
        mongo_uri="mongodb://localhost:1/?serverSelectionTimeoutMS=200",
        mongo_db=integration_settings.mongo_db,
    )
    client = create_client(unreachable)
    try:
        with pytest.raises(DataError, match="make up") as exc_info:
            check_connection(client)
        assert "QUANTLAB_MONGO_URI" in str(exc_info.value)
    finally:
        client.close()
