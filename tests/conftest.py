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

from quantlab.config import Settings

_ENV_PREFIX = "QUANTLAB_"


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Diretório temporário, já como diretório de trabalho corrente.

    Isola qualquer teste que escreva arquivos e evita que um `.env` do
    repositório seja lido por acidente.
    """
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove toda variável ``QUANTLAB_*`` herdada da máquina.

    Sem isso, a configuração local de quem roda a suíte mudaria o resultado
    dos testes — o oposto de RNF-01.
    """
    for name in [key for key in os.environ if key.startswith(_ENV_PREFIX)]:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def settings(clean_env: pytest.MonkeyPatch) -> Settings:
    """``Settings`` determinístico: sem env da máquina e sem ler ``.env``."""
    return Settings(_env_file=None)
