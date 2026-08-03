"""Configuração de logging estruturado.

O projeto não usa ``print()``. Toda saída observável passa por structlog, de
modo que o formato seja decidido em um único ponto: JSON quando o processo roda
como serviço, legível por humanos quando roda em desenvolvimento.

A escolha é feita pela variável de ambiente ``QUANTLAB_ENV`` e pode ser
sobrescrita explicitamente pelo parâmetro ``json_logs``.
"""

import logging
import os
import sys

import structlog
from structlog.typing import Processor

__all__ = ["configure_logging", "get_logger"]

#: Ambientes tratados como desenvolvimento — saída colorida e legível.
_DEV_ENVIRONMENTS = frozenset({"dev", "development", "local", "test"})

_DEFAULT_LEVEL = logging.INFO


def _current_environment() -> str:
    return os.getenv("QUANTLAB_ENV", "dev").strip().lower()


def _resolve_level(level: str) -> int:
    """Traduz o nome do nível para o inteiro do stdlib, com fallback em INFO."""
    return logging.getLevelNamesMapping().get(level.strip().upper(), _DEFAULT_LEVEL)


def configure_logging(level: str = "INFO", *, json_logs: bool | None = None) -> None:
    """Configura structlog e a raiz do stdlib ``logging``.

    Args:
        level: Nível mínimo a emitir. Nome inválido cai em ``INFO``.
        json_logs: Força o renderizador. ``None`` decide por ``QUANTLAB_ENV``.
    """
    use_json = _current_environment() not in _DEV_ENVIRONMENTS if json_logs is None else json_logs
    numeric_level = _resolve_level(level)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        # RNF-07: timestamps em UTC, sem depender do fuso da máquina.
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    renderer: Processor
    if use_json:
        processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[*processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Devolve um logger estruturado ligado ao módulo chamador."""
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
