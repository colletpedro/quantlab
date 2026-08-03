"""Configuração da aplicação, lida do ambiente com o prefixo ``QUANTLAB_``.

Os defaults monetários seguem as premissas da spec da Fase 1
(``specs/00-plataforma/fase-1-requirements.md``, seção 6): capital inicial de
100.000 USD (premissa 4) e taxa livre de risco igual a zero (premissa 7).
"""

from functools import lru_cache
from typing import Any

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from quantlab.exceptions import ConfigError

__all__ = ["Settings", "get_settings"]

_MISSING_MONGO_URI_MESSAGE = (
    "QUANTLAB_MONGO_URI não foi definida. Sem ela, o app cairia no default do "
    "driver e poderia conectar silenciosamente a um MongoDB local errado. "
    "Rode `cp .env.example .env` e ajuste a URI antes de continuar."
)


class Settings(BaseSettings):
    """Parâmetros de execução resolvidos a partir do ambiente."""

    model_config = SettingsConfigDict(
        env_prefix="QUANTLAB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    mongo_uri: str = Field(
        description="String de conexão do MongoDB (ADR-0001). Obrigatória: sem "
        "default, para que uma variável ausente nunca conecte, em silêncio, a um "
        "Mongo local sem relação com este projeto.",
    )
    mongo_db: str = Field(
        default="quantlab",
        description="Nome do banco usado para séries, eventos e resultados.",
    )
    log_level: str = Field(
        default="INFO",
        description="Nível mínimo de log emitido por structlog.",
    )
    initial_capital: float = Field(
        default=100_000.0,
        description="Capital inicial do backtest em USD (premissa 4).",
    )
    risk_free_rate: float = Field(
        default=0.0,
        description="Taxa livre de risco anual usada no Sharpe (premissa 7).",
    )
    universe_path: str = Field(
        default="config/universe.yml",
        description="Caminho do universo default de tickers, usado por "
        "`ingest` quando --tickers não é passado (RF-CLI-01 CA-01.1).",
    )

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            missing_mongo_uri = any(
                error["type"] == "missing" and error["loc"] == ("mongo_uri",)
                for error in exc.errors()
            )
            if missing_mongo_uri:
                raise ConfigError(_MISSING_MONGO_URI_MESSAGE) from exc
            raise


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devolve as configurações do processo, resolvidas uma única vez.

    O cache mantém RNF-01 (determinismo): a mesma execução enxerga sempre a
    mesma configuração, mesmo que o ambiente mude no meio do caminho. Testes
    que precisem de outra configuração devem instanciar ``Settings`` direto.
    """
    return Settings()
