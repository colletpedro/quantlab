"""Fronteira de entrada — `pd.Timestamp` vira `datetime.date` (design §3.6).

Único ponto de conversão temporal da ingestão (ING-01.3, RNF-07). O que sai
daqui é sempre `datetime.date`; nada a jusante — validador, repositório,
engine — deveria precisar olhar para `pd.Timestamp` de novo.

**Este é um dos dois módulos do projeto autorizados a manipular instante e
fuso** (design v0.3 §3.6, junto com `storage/repository.py`). Um teste de
arquitetura projeto-inteiro (B5) garante isso por varredura de imports.
"""

from datetime import UTC, date

import pandas as pd

from quantlab.ingestion.provider import RawCorporateActions
from quantlab.storage.models import Bar, CorporateAction, CorporateActionKind

__all__ = ["normalize_corporate_actions", "normalize_prices", "normalize_timestamp"]


def normalize_timestamp(value: pd.Timestamp) -> date:
    """`pd.Timestamp`, tz-aware ou naive, vira `datetime.date` em UTC (ING-01.3).

    Um `Timestamp` tz-aware é convertido para UTC antes de descartar a hora.
    Sem isso, um pregão com offset **positivo** (ex.: exchange asiática)
    poderia cair no dia calendário anterior ao cruzar meia-noite na
    conversão. O universo desta fase é inteiramente americano (premissa 8 do
    requirements) e os offsets de exchange americana são sempre negativos —
    na prática o cruzamento nunca acontece —, mas a função está correta
    independentemente disso.
    """
    if value.tzinfo is not None:
        value = value.tz_convert(UTC)
    return value.date()


def normalize_prices(ticker: str, raw: pd.DataFrame) -> list[Bar]:
    """`DataFrame` bruto de `MarketDataProvider.fetch_prices` vira `list[Bar]`.

    Cada linha vira uma `Bar` com a data já normalizada. Os valores em si —
    inclusive os implausíveis — atravessam intactos: decidir o que é inválido
    é trabalho do validador (B3), não da normalização. `Bar` não valida
    `high >= low` nem sinal de preço; só garante os tipos.

    O ticker é canonicalizado para maiúsculas aqui — a fronteira de entrada é
    o lugar certo para essa normalização, para que `storage/` nunca precise
    se perguntar em que caixa um ticker está gravado.
    """
    canonical_ticker = ticker.upper()
    dates = [normalize_timestamp(timestamp) for timestamp in raw.index]
    return [
        Bar(
            ticker=canonical_ticker,
            date=bar_date,
            open=float(raw["Open"].iloc[position]),
            high=float(raw["High"].iloc[position]),
            low=float(raw["Low"].iloc[position]),
            close=float(raw["Close"].iloc[position]),
            volume=int(raw["Volume"].iloc[position]),
        )
        for position, bar_date in enumerate(dates)
    ]


def normalize_corporate_actions(ticker: str, raw: RawCorporateActions) -> list[CorporateAction]:
    """`RawCorporateActions` (índices `pd.Timestamp`) vira `list[CorporateAction]`.

    Dividendos de valor zero e splits de razão zero não deveriam existir no
    dado real, mas yfinance ocasionalmente inclui zeros residuais de datas
    sem evento em `.dividends`/`.splits` (a série é esparsa, não densa — um
    zero explícito é raro, mas construir `CorporateAction` levantaria
    `DataError` do construtor se aparecesse). Filtrados aqui: um evento de
    magnitude zero não é um evento.
    """
    canonical_ticker = ticker.upper()
    actions: list[CorporateAction] = []

    for position, timestamp in enumerate(raw.dividends.index):
        value = float(raw.dividends.iloc[position])
        if value == 0:
            continue
        actions.append(
            CorporateAction(
                ticker=canonical_ticker,
                date=normalize_timestamp(timestamp),
                kind=CorporateActionKind.DIVIDEND,
                value=value,
            )
        )

    for position, timestamp in enumerate(raw.splits.index):
        ratio = float(raw.splits.iloc[position])
        if ratio == 0:
            continue
        actions.append(
            CorporateAction(
                ticker=canonical_ticker,
                date=normalize_timestamp(timestamp),
                kind=CorporateActionKind.SPLIT,
                ratio=ratio,
            )
        )

    return actions
