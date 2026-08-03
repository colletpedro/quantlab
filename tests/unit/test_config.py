"""Testes de `quantlab.config`.

Cobre a obrigatoriedade de `mongo_uri` (sem default, de propósito — ver
`Settings.mongo_uri`) e o isolamento do cache de `get_settings()` entre testes.
"""

import re

import pytest

from quantlab.config import Settings, get_settings
from quantlab.exceptions import ConfigError

#: Não representa nenhum ambiente real — só satisfaz o campo obrigatório.
_TEST_MONGO_URI = "mongodb://test:test@localhost:27017/?authSource=admin"


@pytest.mark.unit
def test_missing_mongo_uri_raises_config_error(clean_env: pytest.MonkeyPatch) -> None:
    """Sem QUANTLAB_MONGO_URI, o app não deve cair em nenhum default."""
    with pytest.raises(ConfigError, match=re.escape("cp .env.example .env")):
        Settings(_env_file=None)


@pytest.mark.unit
def test_present_mongo_uri_loads_correctly(clean_env: pytest.MonkeyPatch) -> None:
    """Com a variável presente, o valor é carregado sem erro."""
    settings = Settings(_env_file=None, mongo_uri=_TEST_MONGO_URI)
    assert settings.mongo_uri == _TEST_MONGO_URI


@pytest.mark.unit
def test_get_settings_sees_this_tests_own_mongo_uri_a(clean_env: pytest.MonkeyPatch) -> None:
    """Metade 1 do par que prova isolamento do cache entre testes.

    Se `get_settings.cache_clear()` não rodasse em `clean_env`, este teste e
    `..._b` correriam risco de ver o valor um do outro dependendo da ordem de
    coleta do pytest.
    """
    uri = "mongodb://a:a@localhost:27017/?authSource=admin"
    clean_env.setenv("QUANTLAB_MONGO_URI", uri)
    assert get_settings().mongo_uri == uri


@pytest.mark.unit
def test_get_settings_sees_this_tests_own_mongo_uri_b(clean_env: pytest.MonkeyPatch) -> None:
    """Metade 2 do par — ver docstring de `..._a`."""
    uri = "mongodb://b:b@localhost:27017/?authSource=admin"
    clean_env.setenv("QUANTLAB_MONGO_URI", uri)
    assert get_settings().mongo_uri == uri
