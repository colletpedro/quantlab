"""Suporte compartilhado entre `tests/unit/` e `tests/integration/`.

Não é suíte de teste — o nome não começa com `test_` de propósito, e pytest
não coleta este arquivo. `pythonpath = ["."]` em `pyproject.toml` é o que
permite `from tests.support import FakeProvider` funcionar sem `tests/`
precisar de `__init__.py`.
"""

from collections.abc import Callable
from datetime import date

import pandas as pd

from quantlab.ingestion.provider import RawCorporateActions

__all__ = ["FakeProvider", "empty_corporate_actions"]


def empty_corporate_actions() -> RawCorporateActions:
    """O caso comum: ticker sem dividendo nem split registrado."""
    return RawCorporateActions(dividends=pd.Series(dtype=float), splits=pd.Series(dtype=float))


class FakeProvider:
    """`MarketDataProvider` de teste: respostas programadas, zero I/O.

    `MarketDataProvider` é um `Protocol` estrutural — esta classe não herda
    dele, só implementa a mesma forma, exatamente como `YFinanceProvider` faz.

    - `prices`: mapa ticker → `DataFrame`, ou uma função sem argumentos que
      devolve o `DataFrame` (ou levanta) quando chamada. A forma de função é o
      que permite simular falha intermitente: um fake que levanta nas duas
      primeiras chamadas e só devolve dado na terceira, para testar retry sem
      esperar rede de verdade cair.
    - `corporate_actions`: mapa ticker → `RawCorporateActions`. Ticker ausente
      devolve "sem eventos" (`empty_corporate_actions()`), o caso comum — a
      ausência de proventos é legítima e não deveria exigir programação
      explícita em todo teste.
    - Ticker ausente de `prices` levanta `KeyError`: um teste que esqueceu de
      programar um ticker deve falhar alto e apontando a causa, não devolver
      silenciosamente algo genérico.
    """

    def __init__(
        self,
        prices: dict[str, pd.DataFrame | Callable[[], pd.DataFrame]] | None = None,
        corporate_actions: dict[str, RawCorporateActions] | None = None,
    ) -> None:
        self._prices = prices or {}
        self._corporate_actions = corporate_actions or {}
        #: Chamadas recebidas, na ordem — para testes que precisam verificar
        #: *que* o provedor foi chamado, não só o que ele devolveu.
        self.price_calls: list[tuple[str, date, date]] = []
        self.corporate_action_calls: list[str] = []

    def fetch_prices(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        self.price_calls.append((ticker, start, end))
        if ticker not in self._prices:
            raise KeyError(f"FakeProvider sem preços programados para {ticker!r}.")
        entry = self._prices[ticker]
        return entry() if callable(entry) else entry

    def fetch_corporate_actions(self, ticker: str) -> RawCorporateActions:
        self.corporate_action_calls.append(ticker)
        return self._corporate_actions.get(ticker, empty_corporate_actions())
