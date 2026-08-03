"""Fator de ajuste por proventos — ADR-0003, design §3.7.

Função pura: sem banco, sem I/O, sem estado. Recebe a série bruta e os eventos,
devolve os fatores. É o módulo de maior risco do Bloco A, porque um erro aqui
não estoura — ele produz uma série de preços plausível e errada, que corrompe
tudo a jusante parecendo informação.

**A regra.** O fator aplicado à barra em ``t`` é o produto dos fatores de todos
os eventos com data **estritamente posterior** a ``t``:

- split de razão ``r``: preços ÷ r, volume * r
- dividendo ``d`` na data ex D: preços * ``(C - d)/C``, volume inalterado,
  onde ``C`` é o fechamento **bruto** do pregão anterior a D

``C`` ser o fechamento bruto, e não o já ajustado por eventos posteriores, é o
detalhe fácil de errar: usar o ajustado muda o fator e o resultado continua
parecendo razoável. Também é o que torna o cálculo independente da ordem em
que os eventos são processados.

**O algoritmo.** Cada evento deposita seu fator num único ponto da série — o
índice da última barra anterior a ele — e um ``cumprod`` reverso propaga o
produto para trás, em O(n). Sem laço aninhado por barra e evento.
"""

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray

from quantlab.exceptions import DataError
from quantlab.logging import get_logger
from quantlab.storage.models import CorporateAction, CorporateActionKind

__all__ = ["AdjustmentFactors", "adjustment_factors"]

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AdjustmentFactors:
    """Fatores multiplicativos por barra, alinhados com a série de entrada."""

    price: NDArray[np.float64]
    volume: NDArray[np.float64]


def adjustment_factors(
    dates: Sequence[date],
    raw_close: NDArray[np.float64],
    events: Sequence[CorporateAction],
) -> AdjustmentFactors:
    """Calcula o fator de preço e de volume de cada barra.

    Args:
        dates: Datas das barras, em ordem crescente.
        raw_close: Fechamentos **brutos**, alinhados com ``dates``.
        events: Eventos corporativos do **histórico completo** do ticker.
            Passar só os da janela produziria série ajustada apenas no meio
            (ING-02.3).

    Raises:
        DataError: Se um dividendo for maior ou igual ao fechamento anterior,
            o que tornaria o fator nulo ou negativo.
    """
    count = len(dates)
    price_contribution = np.ones(count, dtype=np.float64)
    volume_contribution = np.ones(count, dtype=np.float64)

    if count == 0:
        return AdjustmentFactors(price=price_contribution, volume=volume_contribution)

    bar_dates = list(dates)

    # Ordem fixa por (data, tipo): o produto é comutativo em teoria, mas
    # multiplicação de float não é associativa. Processar sempre na mesma
    # ordem é o que garante resultado bit a bit idêntico entre execuções
    # (RNF-01), independentemente de como a lista chegou.
    for event in sorted(events, key=lambda item: (item.date, item.kind.value)):
        # Primeiro índice cuja data é >= a do evento. `anchor - 1` é, então, a
        # última barra estritamente anterior a ele — o ponto onde o fator
        # entra para que o cumprod reverso o propague para trás.
        anchor = bisect_left(bar_dates, event.date)

        if anchor == 0:
            # Nenhuma barra estritamente anterior: não há o que ajustar.
            if event.kind is CorporateActionKind.DIVIDEND:
                # Aviso porque `C` seria indefinido — descartar em silêncio
                # esconderia um ajuste que deveria ter acontecido.
                _log.warning(
                    "storage.dividend_without_previous_bar",
                    ticker=event.ticker,
                    date=event.date.isoformat(),
                    value=event.value,
                )
            continue

        last_bar_before = anchor - 1

        if event.kind is CorporateActionKind.SPLIT:
            ratio = _require_ratio(event)
            price_contribution[last_bar_before] *= 1.0 / ratio
            volume_contribution[last_bar_before] *= ratio
        else:
            previous_close = float(raw_close[last_bar_before])
            price_contribution[last_bar_before] *= _dividend_factor(event, previous_close)

    # `cumprod` reverso: out[i] = produto de contribution[j] para todo j >= i.
    # É isto que faz cada barra receber os fatores dos eventos posteriores a
    # ela, em uma única passada.
    price = np.ascontiguousarray(np.cumprod(price_contribution[::-1])[::-1])
    volume = np.ascontiguousarray(np.cumprod(volume_contribution[::-1])[::-1])
    return AdjustmentFactors(price=price, volume=volume)


def _require_ratio(event: CorporateAction) -> float:
    """`CorporateAction` já valida; isto satisfaz o tipo sem `assert`."""
    if event.ratio is None:  # pragma: no cover - barrado no construtor
        raise DataError(f"Split sem razão em {event.ticker} {event.date.isoformat()}.")
    return event.ratio


def _dividend_factor(event: CorporateAction, previous_close: float) -> float:
    """Fator ``(C - d)/C``, com ``C`` sendo o fechamento bruto anterior.

    Dividendo maior ou igual a ``C`` não existe no mundo real — é dado
    corrompido. Falhar alto é melhor do que produzir preço nulo ou negativo,
    que passaria pelo resto do sistema parecendo um número.
    """
    if event.value is None:  # pragma: no cover - barrado no construtor
        raise DataError(f"Dividendo sem valor em {event.ticker} {event.date.isoformat()}.")
    if previous_close <= 0.0:
        raise DataError(
            f"Fechamento anterior não positivo ({previous_close}) ao ajustar o dividendo de "
            f"{event.ticker} em {event.date.isoformat()}."
        )
    if event.value >= previous_close:
        raise DataError(
            f"Valor de dividendo ({event.value}) maior ou igual ao fechamento anterior "
            f"({previous_close}) em {event.ticker} {event.date.isoformat()}. O fator de "
            "ajuste seria nulo ou negativo — trate o dado antes de prosseguir."
        )
    return (previous_close - event.value) / previous_close
