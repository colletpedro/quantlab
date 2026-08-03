"""Configuração da aplicação, lida do ambiente com o prefixo ``QUANTLAB_``.

Os defaults monetários seguem as premissas da spec da Fase 1
(``specs/00-plataforma/fase-1-requirements.md``, seção 6): capital inicial de
100.000 USD (premissa 4) e taxa livre de risco igual a zero (premissa 7).
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


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
        default="mongodb://localhost:27017",
        description="String de conexão do MongoDB (ADR-0001).",
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devolve as configurações do processo, resolvidas uma única vez.

    O cache mantém RNF-01 (determinismo): a mesma execução enxerga sempre a
    mesma configuração, mesmo que o ambiente mude no meio do caminho. Testes
    que precisem de outra configuração devem instanciar ``Settings`` direto.
    """
    return Settings()
