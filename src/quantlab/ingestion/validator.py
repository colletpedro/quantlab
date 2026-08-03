"""Validador — decide o que é inválido, antes de qualquer escrita em `bars`.

Design §3.3: as regras de quarentena (ING-05.1) são avaliadas aqui, **antes**
de qualquer escrita. Este módulo só decide — não grava nada. A escrita
(`quarantine_bars`, `upsert_bars`) é responsabilidade de quem orquestra (B4),
via `MongoRepository`. Isso mantém o validador testável sem banco: as regras
são função pura de `list[Bar]` para `ValidationResult`.

Três famílias de regra:

- **ING-05.1 (bloqueante).** `high < low`, `open`/`close` fora de
  `[low, high]`, preço ≤ 0, volume < 0. A barra vai para quarentena, com
  **todas** as razões violadas — não só a primeira.
- **ING-05.2 (aviso).** Gap de pregões maior que 5 dias úteis. A barra em si
  é plausível; o que é suspeito é o contexto, então não quarentena.
- **ING-05.3 (aviso).** Variação de fechamento a fechamento maior que 50% em
  valor absoluto, sem split registrado na data — indício de evento
  corporativo não capturado. Também não quarentena.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise

import numpy as np

from quantlab.logging import get_logger
from quantlab.storage.models import Bar, CorporateAction, CorporateActionKind, QuarantinedBar

__all__ = ["ValidationResult", "validate_bars"]

_log = get_logger(__name__)

#: ING-05.2 — limiar de gap, em dias úteis.
_MAX_GAP_BUSINESS_DAYS = 5

#: ING-05.3 — limiar de variação absoluta de fechamento.
_MAX_ABS_RETURN_WITHOUT_SPLIT = 0.5


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """O que a validação decidiu para um lote de barras de um ticker."""

    valid_bars: list[Bar] = field(default_factory=list)
    quarantined_bars: list[QuarantinedBar] = field(default_factory=list)
    #: Mensagens de ING-05.2/05.3 — não-bloqueantes, registradas no
    #: `ingestion_run` por quem orquestra (B4), não escritas aqui.
    warnings: list[str] = field(default_factory=list)


def validate_bars(
    bars: Sequence[Bar],
    corporate_actions: Sequence[CorporateAction],
    *,
    ingestion_run_id: str | None = None,
) -> ValidationResult:
    """Separa barras válidas de quarentenadas e coleta avisos não-bloqueantes.

    Args:
        bars: Barras de **um** ticker — a função ordena por data
            internamente, mas não mistura tickers diferentes; gap e variação
            não fariam sentido entre séries de papéis distintos.
        corporate_actions: Eventos do mesmo ticker, usados só para checar
            ING-05.3 (variação sem split correspondente). Não precisa ser
            filtrado por janela.
        ingestion_run_id: Referência cruzada gravada em cada
            `QuarantinedBar`, para rastrear a quarentena até o run que a
            produziu (design §3.3).
    """
    ordered = sorted(bars, key=lambda bar: bar.date)
    split_dates = {
        action.date for action in corporate_actions if action.kind is CorporateActionKind.SPLIT
    }

    valid: list[Bar] = []
    quarantined: list[QuarantinedBar] = []

    for bar in ordered:
        reasons = _blocking_reasons(bar)
        if reasons:
            quarantined.append(
                QuarantinedBar(
                    ticker=bar.ticker,
                    date=bar.date,
                    raw={
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    },
                    reasons=tuple(reasons),
                    ingestion_run_id=ingestion_run_id,
                )
            )
        else:
            valid.append(bar)

    # ING-05.2 e ING-05.3 avaliam sequência entre barras VÁLIDAS: uma barra
    # quarentenada não é um pregão presente para fins de gap, e não é um
    # ponto de comparação legítimo para variação.
    warnings = _sequence_warnings(valid, split_dates)

    return ValidationResult(valid_bars=valid, quarantined_bars=quarantined, warnings=warnings)


def _blocking_reasons(bar: Bar) -> list[str]:
    """CA-05.1 — toda regra violada, avaliada de forma independente.

    Independente quer dizer: não para na primeira que falhar. Uma barra com
    `high < low` frequentemente também viola `open`/`close` fora do
    intervalo — as duas razões são reportadas, porque a segunda pode apontar
    qual campo especificamente veio errado do provedor.
    """
    reasons: list[str] = []
    if bar.high < bar.low:
        reasons.append("high_below_low")
    if bar.open > bar.high:
        reasons.append("open_above_high")
    if bar.open < bar.low:
        reasons.append("open_below_low")
    if bar.close > bar.high:
        reasons.append("close_above_high")
    if bar.close < bar.low:
        reasons.append("close_below_low")
    if bar.open <= 0:
        reasons.append("open_not_positive")
    if bar.high <= 0:
        reasons.append("high_not_positive")
    if bar.low <= 0:
        reasons.append("low_not_positive")
    if bar.close <= 0:
        reasons.append("close_not_positive")
    if bar.volume < 0:
        reasons.append("volume_negative")
    return reasons


def _sequence_warnings(valid_bars: Sequence[Bar], split_dates: set[date]) -> list[str]:
    warnings: list[str] = []
    for previous, current in pairwise(valid_bars):
        gap = _business_day_gap(previous.date, current.date)
        if gap > _MAX_GAP_BUSINESS_DAYS:
            message = (
                f"Gap de {gap} dias úteis em {current.ticker} entre "
                f"{previous.date.isoformat()} e {current.date.isoformat()}."
            )
            warnings.append(message)
            _log.warning(
                "ingestion.gap_detected",
                ticker=current.ticker,
                gap_business_days=gap,
                previous_date=previous.date.isoformat(),
                date=current.date.isoformat(),
            )

        # `previous.close > 0` é garantido por `_blocking_reasons`: uma barra
        # com close <= 0 nunca chega a `valid_bars`. Sem divisão por zero.
        variation = abs(current.close - previous.close) / previous.close
        if variation > _MAX_ABS_RETURN_WITHOUT_SPLIT and current.date not in split_dates:
            message = (
                f"Variação de {variation:.1%} em {current.ticker} "
                f"{current.date.isoformat()} sem split registrado na data — "
                "possível evento corporativo não capturado."
            )
            warnings.append(message)
            _log.warning(
                "ingestion.unexplained_variation",
                ticker=current.ticker,
                variation=variation,
                date=current.date.isoformat(),
            )

    return warnings


def _business_day_gap(previous: date, current: date) -> int:
    """Dias úteis estritamente entre duas datas, sem calendário de feriados.

    `np.busday_count` conta dias de semana (seg-sex) em `[begin, end)`. Somar
    um dia a `previous` exclui a própria barra anterior da contagem — o que
    queremos é o que falta *entre* as duas, não incluindo nenhuma delas.

    Feriados não são excluídos: um feriado único (ex.: Ação de Graças) nunca
    passa de 5 dias úteis sozinho, então não dispara falso positivo no
    limiar atual. Uma sequência incomum de feriados poderia; aceito como
    simplificação da fase, sem calendário de pregão dedicado.
    """
    return int(np.busday_count(previous + timedelta(days=1), current))
