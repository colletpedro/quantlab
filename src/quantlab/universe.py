"""Universo default de tickers — RF-CLI-01, CA-01.1.

Lido de ``config/universe.yml`` quando o comando ``ingest`` roda sem
``--tickers``. O caminho é configurável via ``Settings.universe_path``
(``QUANTLAB_UNIVERSE_PATH``), não hardcoded — CLAUDE.md §3 proíbe constante
mágica de configuração espalhada pelo código.
"""

from pathlib import Path
from typing import Any

import yaml

from quantlab.exceptions import ConfigError

__all__ = ["load_default_universe"]


def load_default_universe(path: str | Path) -> list[str]:
    """Tickers do universo default, maiúsculos, na ordem do arquivo.

    Raises:
        ConfigError: Arquivo ausente, sem a chave `universe`, ou com uma
            entrada sem `ticker`. Todos os três são erro de configuração, não
            de dado de mercado — não faz sentido tentar ingerir de qualquer
            forma.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise ConfigError(
            f"Arquivo de universo não encontrado em {file_path}. Passe "
            "--tickers explicitamente ou ajuste QUANTLAB_UNIVERSE_PATH."
        )

    with file_path.open(encoding="utf-8") as handle:
        content: Any = yaml.safe_load(handle)

    if not isinstance(content, dict) or "universe" not in content:
        raise ConfigError(f"{file_path} não tem a chave `universe` esperada.")

    tickers: list[str] = []
    for entry in content["universe"]:
        ticker = entry.get("ticker") if isinstance(entry, dict) else None
        if not ticker:
            raise ConfigError(f"Entrada de universo sem `ticker` em {file_path}: {entry!r}.")
        tickers.append(str(ticker).upper())

    if not tickers:
        raise ConfigError(f"{file_path} tem a chave `universe` vazia.")

    return tickers
