"""Interface de linha de comando do quantlab.

Fase 0 expõe apenas ``version``. Os comandos ``ingest`` e ``backtest``
(RF-CLI-01 e RF-CLI-02) entram quando as specs dos módulos correspondentes
passarem pelo gate de design.
"""

from importlib import metadata

import typer

from quantlab.config import get_settings
from quantlab.logging import configure_logging, get_logger

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


@app.callback()
def main() -> None:
    """Configura o logging antes de qualquer subcomando."""
    configure_logging(get_settings().log_level)


@app.command()
def version() -> None:
    """Mostra a versão instalada do quantlab."""
    log.info("quantlab.version", version=_installed_version())
