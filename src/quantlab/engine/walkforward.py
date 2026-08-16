"""Walk-forward — folds, grade determinística e métrica de seleção (T10, design §3.6, ADR-0011).

O protocolo da Fase 2b: otimização in-sample por grade EXPLÍCITA de
parâmetros + avaliação out-of-sample honesta, com o viés de múltiplos
testes (MHT) declarado. Este módulo é folha na T10 (só stdlib +
`quantlab.exceptions`): o `run_walkforward` (caixa preta sobre
`run_backtest_multi`) chega na T11a.

Três contratos que moram aqui (emenda P1):

1. **Isolamento IS/OOS por construção (CA-01.1).** O fold entrega ao run IS
   séries TRUNCADAS no fim do IS — a fronteira é do ARRAY, não da disciplina
   de quem chama: `MarketView`/`UnionCalendar` recusam qualquer acesso além
   do fim (EngineError).
2. **Folds disjuntos; união dos OOS cobre a janela (CA-01.2).**
   `oos_start` = dia útil seguinte a `is_end`; os segmentos OOS se justapõem
   sem sobreposição e o último é truncado em `end`.
3. **`sharpe_annualized_rf0` é a ÚNICA implementação do Sharpe (R5).**
   `analytics/metrics.py` importa o helper daqui — a seleção IS e o
   relatório usam a mesma fórmula, sem drift (lição da T14).

`date` é naive (RNF-07): nenhum `datetime`/`timezone` aqui — o teste de
arquitetura (`test_architecture_date_isolation`) varre o pacote inteiro.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from quantlab.exceptions import EngineError

__all__ = ["Fold", "ParameterGrid", "build_folds", "sharpe_annualized_rf0"]

#: Pregões por ano na anualização — MESMA convenção da 2a
#: (`_TRADING_DAYS_PER_YEAR` em analytics/metrics.py, RF-MET-04/P4). O helper
#: mora aqui com a constante própria porque engine não importa analytics (a
#: direção é analytics -> engine; sem ciclo) — e a fonte única garante que
#: as duas constantes nunca divergem (uma é a outra, via delegação).
_TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class Fold:
    """Janelas IS/OOS de um fold — design §3.6, CA-01.2.

    Invariantes (garantidas por `build_folds`):

    - ``is_start <= is_end < oos_start <= oos_end`` — IS e OOS DISJUNTOS
      (``oos_start`` = dia útil seguinte a ``is_end``);
    - a união dos segmentos OOS cobre a janela avaliada SEM sobreposição
      (o último segmento pode ser truncado em ``end``).

    `date` naive (RNF-07).
    """

    is_start: date
    is_end: date
    oos_start: date
    oos_end: date


@dataclass(frozen=True)
class ParameterGrid:
    """Grade EXPLÍCITA de parâmetros — determinística por construção (CA-02.1/RNF-01).

    Combinações declaradas na ordem em que serão varridas (ex.: SmaCross
    {10, 20, ..., 60}): sem amostragem, sem aleatoriedade. `seed` só tem
    papel se um otimizador ESTOCÁSTICO substituir a grade (design §3.6 —
    nesse caso a seed é travada e declarada); a grade default é
    determinística por construção.

    Raises:
        EngineError: ``params`` vazio (design §3.8).
    """

    params: tuple[dict[str, float], ...]
    seed: int | None = None

    def __post_init__(self) -> None:
        if not self.params:
            raise EngineError(
                "ParameterGrid: params vazio — a grade precisa de ao menos "
                "uma combinação (design §3.8)."
            )

    @property
    def grid_size(self) -> int:
        """|grid| — declarado no MHT (CA-06.2)."""
        return len(self.params)


def build_folds(
    start: date,
    end: date,
    is_window: int,
    oos_window: int,
    anchor: Literal["rolling", "anchored"] = "rolling",
) -> tuple[Fold, ...]:
    """Constrói os folds do walk-forward — determinístico (RNF-01), design §3.6.

    Janelas em **dias úteis** (seg-sex; decisão local T10 — o design fala em
    "dia útil seguinte a is_end" e não define a unidade das janelas; dias
    úteis semanais é a única escolha autocontida sem calendário externo, e é
    o que faz o tile do OOS fechar: is_window + oos_window = dias úteis
    contíguos).

    - **rolling** (default, D7 — decisão do autor, R7): janela IS de tamanho
      FIXO deslizando de ``oos_window`` dias úteis a cada fold — janelas de
      seleção comparáveis entre folds;
    - **anchored** (configurável — para MEDIR a diferença): IS começa sempre
      em ``start`` e cresce ``oos_window`` dias úteis por fold.

    Invariantes por fold (CA-01.2): IS e OOS disjuntos (``oos_start`` = dia
    útil seguinte a ``is_end``); a união dos segmentos OOS cobre a janela
    avaliada — de ``start + is_window`` dias úteis até ``end`` — sem
    sobreposição (o último segmento é truncado em ``end``).

    Raises:
        EngineError: ``start > end``; ``is_window < 1`` ou ``oos_window < 1``;
            ``anchor`` fora de {"rolling", "anchored"}; janela com menos de
            ``is_window + 1`` dias úteis (sem espaço para ao menos um fold
            com OOS não-vazio) — design §3.8.
    """
    if start > end:
        raise EngineError(f"build_folds: start={start} > end={end} (design §3.6).")
    if is_window < 1:
        raise EngineError(f"build_folds: is_window={is_window} < 1 (design §3.6).")
    if oos_window < 1:
        raise EngineError(f"build_folds: oos_window={oos_window} < 1 (design §3.6).")
    if anchor not in ("rolling", "anchored"):
        raise EngineError(
            f"build_folds: anchor={anchor!r} — esperado 'rolling' ou 'anchored' (design §3.6)."
        )

    total = _business_day_count(start, end)
    if total < is_window + 1:
        raise EngineError(
            f"build_folds: janela [{start}, {end}] tem {total} dias úteis — "
            f"insuficiente para um fold com IS={is_window} e OOS nao-vazio "
            f"(precisa de ao menos {is_window + 1}) (design §3.6)."
        )

    folds: list[Fold] = []
    fold_index = 0
    while True:
        if anchor == "anchored":
            is_start = start
            is_end = _add_business_days(start, is_window - 1 + fold_index * oos_window)
        else:
            is_start = _add_business_days(start, fold_index * oos_window)
            is_end = _add_business_days(is_start, is_window - 1)
        oos_start = _add_business_days(is_end, 1)
        if oos_start > end:
            break
        oos_end = min(_add_business_days(oos_start, oos_window - 1), end)
        folds.append(Fold(is_start=is_start, is_end=is_end, oos_start=oos_start, oos_end=oos_end))
        if oos_end == end:
            break
        fold_index += 1

    return tuple(folds)


def sharpe_annualized_rf0(returns: Sequence[float]) -> float | None:
    """Sharpe anualizado com ``rf = 0`` — forma fechada ÚNICA (R5, design §3.6/§7).

    ``média(retornos) / desvio-padrão_amostral(retornos) x sqrt(252)``. Vive
    AQUI (engine) e é IMPORTADA por `analytics/metrics.py`: a seleção IS
    (R5) e o relatório (MHT, CA-06.2) usam a MESMA implementação — sem drift
    entre a métrica que escolhe parâmetros e a que o relatório declara
    (emenda P1, lição da T14).

    `None`, nunca `NaN` (R6): série vazia, menos de duas observações (sem
    desvio-padrão definido) ou desvio-padrão zero devolvem `None` explícito.
    `NaN` se propagaria em silêncio por qualquer agregação a jusante; `None`
    estoura no primeiro uso aritmético.

    Args:
        returns: série de retornos — qualquer sequência de floats com `len`
            e iteração (lista, tuple ou `pd.Series` via `.tolist()`).

    Returns:
        O Sharpe anualizado, ou `None` nos casos de amostra insuficiente.
    """
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance)
    if std == 0 or math.isnan(std):
        return None
    return float(mean / std * math.sqrt(_TRADING_DAYS_PER_YEAR))


def _add_business_days(day: date, n: int) -> date:
    """``day + n`` dias úteis (seg-sex), com ``n >= 0``. Puro (RNF-01)."""
    result = day
    remaining = n
    while remaining > 0:
        result += timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def _business_day_count(start: date, end: date) -> int:
    """Nº de dias úteis (seg-sex) no intervalo INCLUSIVE ``[start, end]``."""
    count = 0
    day = start
    while day <= end:
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    return count
