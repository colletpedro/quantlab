"""Teste de fumaça da Fase 0.

Não valida comportamento de domínio — não existe domínio ainda. Valida que o
pacote importa, que os subpacotes vazios estão no lugar e que o CLI responde.
"""

import importlib

import pytest
from typer.testing import CliRunner

import quantlab
from quantlab.cli import app
from quantlab.config import Settings
from quantlab.exceptions import ConfigError, DataError, EngineError, QuantlabError

_DOMAIN_SUBPACKAGES = (
    "quantlab.ingestion",
    "quantlab.storage",
    "quantlab.engine",
    "quantlab.strategies",
    "quantlab.analytics",
)


@pytest.mark.unit
def test_scaffold_imports_and_cli_answers(settings: Settings) -> None:
    """O esqueleto da Fase 0 está de pé e coerente com a spec."""
    # Os cinco subpacotes de domínio existem e importam, ainda que vazios.
    for name in _DOMAIN_SUBPACKAGES:
        assert importlib.import_module(name) is not None

    # A hierarquia de exceções tem uma raiz única.
    for error in (DataError, ConfigError, EngineError):
        assert issubclass(error, QuantlabError)

    # Defaults monetários vêm das premissas 4 e 7 da spec da Fase 1.
    assert settings.initial_capital == pytest.approx(100_000.0)
    assert settings.risk_free_rate == pytest.approx(0.0)

    # O CLI sobe e o comando `version` reporta a versão do pacote.
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert quantlab.__version__ in result.output
