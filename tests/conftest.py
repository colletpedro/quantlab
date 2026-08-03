"""Fixtures de infraestrutura da suíte.

Fase 0 tem apenas o encanamento: diretório temporário e configuração isolada
do ambiente da máquina. Fixtures de domínio — séries OHLCV sintéticas com
resultado calculado no papel (RNF-03) — entram junto com o engine, depois do
gate de design.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from quantlab.config import Settings, get_settings

_ENV_PREFIX = "QUANTLAB_"

#: URI usada só para satisfazer o campo obrigatório em testes que não são
#: sobre `mongo_uri` em si. Nunca aponta para um Mongo real.
TEST_MONGO_URI = "mongodb://test:test@localhost:27017/?authSource=admin"


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Diretório temporário, já como diretório de trabalho corrente.

    Isola qualquer teste que escreva arquivos e evita que um `.env` do
    repositório seja lido por acidente.
    """
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Remove toda variável ``QUANTLAB_*`` herdada da máquina e isola o cache
    de ``get_settings()``.

    ``get_settings()`` usa ``lru_cache``. Sem limpar o cache antes e depois do
    teste, o primeiro teste da suíte a chamá-lo congelaria os valores para
    todos os que vierem depois — o resultado passaria a depender da ordem de
    execução, o oposto de RNF-01.
    """
    for name in [key for key in os.environ if key.startswith(_ENV_PREFIX)]:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


@pytest.fixture
def settings(clean_env: pytest.MonkeyPatch) -> Settings:
    """``Settings`` determinístico: sem env da máquina e sem ler ``.env``.

    ``mongo_uri`` é obrigatório e não representa nenhum ambiente real — é
    fornecido aqui só para satisfazer a validação.
    """
    return Settings(_env_file=None, mongo_uri=TEST_MONGO_URI)
