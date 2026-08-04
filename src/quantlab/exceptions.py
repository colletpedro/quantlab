"""Hierarquia de exceções do quantlab.

Sem lógica: as subclasses existem para que o chamador consiga distinguir a
origem do erro (dado, configuração, execução) sem inspecionar mensagens.
"""

__all__ = [
    "ConfigError",
    "DataError",
    "EngineError",
    "InsufficientHistoryError",
    "QuantlabError",
]


class QuantlabError(Exception):
    """Raiz de toda exceção levantada deliberadamente pelo quantlab."""


class DataError(QuantlabError):
    """Falha de ingestão, validação ou persistência de dados de mercado."""


class ConfigError(QuantlabError):
    """Configuração ausente, malformada ou inconsistente."""


class EngineError(QuantlabError):
    """Violação de invariante ou falha durante a execução de um backtest."""


class InsufficientHistoryError(EngineError):
    """A estratégia pediu mais barras do que existem até a barra corrente.

    Design §4.1 é deliberado sobre este nome: **não** é `LookaheadError`. Uma
    estratégia que pede `last("close", 200)` na barra 50 não está tentando ler
    o futuro — está com o `warmup` mal declarado. O nome aponta a causa certa
    para quem for depurar; chamar de lookahead mandaria a pessoa procurar o
    bug errado.
    """
