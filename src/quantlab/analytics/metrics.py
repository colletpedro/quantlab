"""Métricas de performance — E1, design §5, RF-ANA-01.

Funções puras sobre a equity curve. Nenhuma toca banco ou I/O — nem log: um
`None` vale mais que um aviso emitido de dentro de uma função que precisa
continuar sendo testável com uma série de papel e nada mais (RNF-03). A
checagem de amostra insuficiente (ANA-01.5) é responsabilidade do relatório
(E3), que é quem tem alguém para avisar.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import cast

import pandas as pd

from quantlab.engine.portfolio import Trade

__all__ = ["DrawdownResult", "cagr", "daily_returns", "hit_rate", "max_drawdown", "sharpe"]

_DAYS_PER_YEAR = 365.25


@dataclass(frozen=True, slots=True)
class DrawdownResult:
    """A maior queda pico-a-vale da equity curve — ANA-01.3.

    `magnitude` é a fração positiva da queda (0.25 == -25% do pico). Positiva
    de propósito: "magnitude" sugere tamanho, não sinal, e `-0.0` teria sido
    uma fonte fácil de confusão em comparação (`magnitude > 0.1`).
    """

    magnitude: float
    peak_date: date
    trough_date: date
    recovery_date: date | None

    @property
    def is_recovered(self) -> bool:
        return self.recovery_date is not None


def daily_returns(equity: pd.Series) -> pd.Series:
    """Retorno percentual barra a barra, a partir da equity curve.

    Não está no design §5 nomeada assim, mas `sharpe()` pede "uma série de
    retornos diários" (CA-01.1) e a equity curve é o que o backtest produz —
    alguém precisa converter uma na outra, e a conversão em si não tem por
    que deixar de ser pura.
    """
    return equity.pct_change().dropna()


def sharpe(returns: pd.Series, rf: float = 0.0, periods: int = 252) -> float | None:
    """CA-01.1 — `média(retorno - rf) / desvio-padrão(retorno) x √periods`.

    `None`, nunca `nan` (CA-01.4): desvio-padrão zero ou série curta demais
    para ter desvio-padrão definido (menos de duas observações) devolvem
    `None`. `nan` se propaga em silêncio por qualquer agregação a jusante;
    `None` estoura no primeiro uso aritmético.
    """
    if len(returns) < 2:
        return None
    excess = returns - rf
    std = excess.std(ddof=1)
    if std == 0 or math.isnan(std):
        return None
    return float((excess.mean() / std) * math.sqrt(periods))


def cagr(equity: pd.Series) -> float:
    """Taxa de crescimento anual composta, do primeiro ao último ponto da curva.

    Usa dias corridos entre a primeira e a última data do índice, não número
    de barras — pregões têm gaps de fim de semana e feriado, e `/252` embutido
    superestimaria o tempo decorrido. Sem tempo decorrido (uma única barra, ou
    duas barras na mesma data), não há o que compor: devolve `0.0`.
    """
    if len(equity) < 2:
        return 0.0

    start_date = equity.index[0]
    end_date = equity.index[-1]
    elapsed_days = (end_date - start_date).days
    if elapsed_days <= 0:
        return 0.0

    years = elapsed_days / _DAYS_PER_YEAR
    initial = float(equity.iloc[0])
    final = float(equity.iloc[-1])
    return float((final / initial) ** (1.0 / years) - 1.0)


def max_drawdown(equity: pd.Series) -> DrawdownResult:
    """CA-01.3 — maior queda percentual pico-a-vale, com as três datas.

    O pico usado no denominador é o **pico corrente** (`cummax`), não o
    primeiro valor da série — uma queda depois de um novo máximo é uma queda
    real ainda que a série termine acima de onde começou.
    """
    running_peak = equity.cummax()
    drawdown = (equity - running_peak) / running_peak

    trough_date = cast(date, drawdown.idxmin())
    peak_value = running_peak.loc[trough_date]
    magnitude = abs(float(drawdown.loc[trough_date]))

    up_to_trough = equity.loc[:trough_date]
    peak_date = cast(date, up_to_trough[up_to_trough == peak_value].index[0])

    after_trough = equity.loc[trough_date:]
    recovered = after_trough[after_trough >= peak_value]
    recovery_date = cast(date, recovered.index[0]) if len(recovered) > 0 else None

    return DrawdownResult(
        magnitude=magnitude,
        peak_date=peak_date,
        trough_date=trough_date,
        recovery_date=recovery_date,
    )


def hit_rate(trades: list[Trade]) -> float | None:
    """Fração de trades **fechados** com PnL realizado positivo.

    `None` sem trade fechado nenhum — taxa de acerto de zero observações não
    é `0.0`, é indefinida. Posições ainda abertas não entram: seu resultado
    não é conhecido ainda.
    """
    closed = [trade for trade in trades if not trade.is_open]
    if not closed:
        return None
    wins = sum(1 for trade in closed if trade.realized_pnl > 0)
    return wins / len(closed)
