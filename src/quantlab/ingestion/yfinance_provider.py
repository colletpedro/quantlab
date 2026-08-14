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


def _back_out_splits(prices: pd.DataFrame, stock_splits: pd.Series) -> pd.DataFrame:
    """Recupera OHLC **bruto** (pré-split) de um frame split-ajustado (v0.10).

    `auto_adjust=False` do yfinance ainda aplica splits ao OHLC — só deixa
    dividendos fora. O ajuste do §3.7 aplica splits de novo, então gravar o
    frame como veio duplicaria a contagem. A recuperação é o inverso exato
    do ajuste: `raw[t] = split_adj[t] x Π r_i` para splits com data
    estritamente posterior a `t` (sufixo produto da coluna `Stock Splits`).
    Volume não é tocado — vem como negociado.

    Pré: `stock_splits` alinhado ao índice de `prices` (0.0/NaN onde não há
    split, razão r na data ex). Pós: retorna cópia com OHLC bruto; `prices`
    intacto.
    """
    # 1.0 onde não há split (NaN e 0.0 incluídos), razão r onde há.
    ratio = stock_splits.where(stock_splits > 0, 1.0)
    # Sufixo produto: suffix[t] = Π_{i ≥ t} r_i. Dividir pela razão da própria
    # data exclui o split dela → factor[t] = Π_{i > t} r_i, exatamente o
    # inverso do ajuste do §3.7 (barras estritamente anteriores multiplicam
    # por r; a barra da data ex e as posteriores ficam intactas).
    suffix = ratio.iloc[::-1].cumprod().iloc[::-1]
    factor = suffix / ratio
    factor = factor.reindex(prices.index).fillna(1.0)

    out = prices.copy()
    for column in ("Open", "High", "Low", "Close"):
        out[column] = out[column] * factor
    return out


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
            auto_adjust=False,  # ADR-0003 — nunca coletar já ajustado por dividendos
            actions=True,  # v0.10 — precisa da coluna "Stock Splits" p/ o back-out
            timeout=self._timeout,
        )
        # Rows de data ex sem pregão (só evento) vêm com OHLC NaN — fora.
        prices = history[_PRICE_COLUMNS].dropna()
        # auto_adjust=False ainda é SPLIT-ajustado (v0.10 — bug real da Fase 2a):
        # recuperar o bruto pré-split antes de devolver. Sem isso o ajuste do
        # §3.7 aplicaria o split duas vezes.
        return _back_out_splits(prices, history["Stock Splits"])

    def fetch_corporate_actions(self, ticker: str) -> RawCorporateActions:
        # .dividends e .splits do yfinance já cobrem o histórico completo do
        # ticker — não há parâmetro de janela a passar (ING-02.3).
        instrument = yf.Ticker(ticker)
        return RawCorporateActions(
            dividends=instrument.dividends,
            splits=instrument.splits,
        )
