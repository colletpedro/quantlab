"""Implementação real de `MarketDataProvider` sobre a biblioteca yfinance.

Sem retry, sem lógica de resiliência — isso é responsabilidade de
`ResilientProvider`, aplicada por composição em quem monta o provedor (B4):
``ResilientProvider(YFinanceProvider())``. Este módulo só fala com a rede e
devolve o que recebeu.
"""

from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from quantlab.ingestion.provider import RawCorporateActions

__all__ = ["YFinanceProvider"]

#: yfinance não documenta um default confiável de timeout de HTTP; sem um
#: valor explícito, uma requisição pendurada trava a ingestão inteira sem
#: aviso.
_DEFAULT_TIMEOUT_SECONDS = 15.0

_PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


class YFinanceProvider:
    """`MarketDataProvider` sobre `yfinance.Ticker`."""

    def __init__(self, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    def fetch_prices(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        # yfinance trata `end` como exclusivo; RF-CLI-01 pede [start, end]
        # inclusiva, daí o +1 dia.
        history = yf.Ticker(ticker).history(
            start=start,
            end=end + timedelta(days=1),
            auto_adjust=False,  # ADR-0003 — nunca coletar já ajustado
            actions=False,  # eventos vêm de fetch_corporate_actions, sem janela
            timeout=self._timeout,
        )
        prices: pd.DataFrame = history[_PRICE_COLUMNS]
        return prices

    def fetch_corporate_actions(self, ticker: str) -> RawCorporateActions:
        # .dividends e .splits do yfinance já cobrem o histórico completo do
        # ticker — não há parâmetro de janela a passar (ING-02.3).
        instrument = yf.Ticker(ticker)
        return RawCorporateActions(
            dividends=instrument.dividends,
            splits=instrument.splits,
        )
