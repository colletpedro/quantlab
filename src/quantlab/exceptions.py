"""Hierarquia de exceções do quantlab.

Sem lógica: as subclasses existem para que o chamador consiga distinguir a
origem do erro (dado, configuração, execução) sem inspecionar mensagens.
"""

__all__ = ["ConfigError", "DataError", "EngineError", "QuantlabError"]


class QuantlabError(Exception):
    """Raiz de toda exceção levantada deliberadamente pelo quantlab."""


class DataError(QuantlabError):
    """Falha de ingestão, validação ou persistência de dados de mercado."""


class ConfigError(QuantlabError):
    """Configuração ausente, malformada ou inconsistente."""


class EngineError(QuantlabError):
    """Violação de invariante ou falha durante a execução de um backtest."""
