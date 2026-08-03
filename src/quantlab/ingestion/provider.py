"""Contrato entre a ingestão e qualquer fonte de dados de mercado — B1.

`YFinanceProvider` (`yfinance_provider.py`) é a implementação real. Os testes
usam `FakeProvider` (`tests/support.py`), que nunca toca rede — RNF-06 vale
para a suíte inteira, não só para `make test`.

**Sem normalização aqui.** O provedor devolve exatamente o que a fonte
devolveu — `pd.Timestamp`, tz-aware ou não. A conversão para `datetime.date`
é fronteira de `ingestion/normalizer.py` (B2), não deste módulo.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd

__all__ = ["MarketDataProvider", "RawCorporateActions"]


@dataclass(frozen=True, slots=True)
class RawCorporateActions:
    """Dividendos e splits de um ticker, sobre o **histórico completo** (ING-02.3).

    Índices são `pd.Timestamp` (a forma como yfinance devolve), ainda não
    normalizados. `dividends`: valor por ação. `splits`: razão (2.0 = 2:1).
    Qualquer um dos dois pode ser uma série vazia — ausência de evento é
    legítima, ao contrário de OHLCV vazio (ver `MarketDataProvider.fetch_prices`).
    """

    dividends: pd.Series
    splits: pd.Series


class MarketDataProvider(Protocol):
    """O que a ingestão precisa de uma fonte de dados de mercado."""

    def fetch_prices(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """OHLCV bruto na janela ``[start, end]``, sem ajuste (ADR-0003).

        Colunas: ``Open``, ``High``, ``Low``, ``Close``, ``Volume``. Índice:
        datas do pregão, possivelmente tz-aware. Resposta vazia é tratada como
        falha por quem envolve o provedor (`ResilientProvider`, ING-04.2) —
        este método só busca e devolve, não decide o que é falha.
        """
        ...

    def fetch_corporate_actions(self, ticker: str) -> RawCorporateActions:
        """Dividendos e splits do **histórico completo** do ticker.

        Nunca aceita janela: um split fora do intervalo pedido para os preços
        ainda afeta os preços dentro dele (ING-02.3, ADR-0003).
        """
        ...
