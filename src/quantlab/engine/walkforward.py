"""Walk-forward — folds, grade e seleção (T10) + run_walkforward (T11a) — design §3.6, ADR-0011.

O protocolo da Fase 2b: otimização in-sample por grade EXPLÍCITA de
parâmetros + avaliação out-of-sample honesta, com o viés de múltiplos
testes (MHT) declarado. `run_walkforward` (T11a) roda `run_backtest_multi`
como CAIXA PRETA por fold (design §2) — cada run IS/OOS herda TODAS as
regras de execução do run único (custos, slippage, cap, margem, borrow,
sizer), sem reimplementar o laço.

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
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from typing import Any, Literal

import numpy as np

from quantlab.engine.backtest import BacktestResultMulti, run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.margin import BorrowFeeModel, MarginModel
from quantlab.engine.sizing import Sizer
from quantlab.engine.slippage import SlippageModel
from quantlab.engine.strategy import Strategy
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries

__all__ = [
    "PER_FOLD_BUDGET_S",
    "TOTAL_BUDGET_MARGIN_S",
    "BudgetReport",
    "Fold",
    "FoldMetrics",
    "FoldResult",
    "ParameterGrid",
    "WalkForwardResult",
    "build_folds",
    "measure_walkforward",
    "run_walkforward",
    "sharpe_annualized_rf0",
]

#: Pregões por ano na anualização — MESMA convenção da 2a
#: (`_TRADING_DAYS_PER_YEAR` em analytics/metrics.py, RF-MET-04/P4). O helper
#: mora aqui com a constante própria porque engine não importa analytics (a
#: direção é analytics -> engine; sem ciclo) — e a fonte única garante que
#: as duas constantes nunca divergem (uma é a outra, via delegação).
_TRADING_DAYS_PER_YEAR = 252

#: Design §3.6 (RNF-10/WFK-05 CA-05.1): orçamento por fold — IS+OOS de 20
#: ativos x janela em 30 s. Declarado AQUI (constante do engine); o limite
#: vira bloqueio no CI na T12b.
PER_FOLD_BUDGET_S = 30.0

#: Margem DECLARADA do orçamento total (design §3.6: "n_folds x 30 s +
#: margem declarada"). Decisão local T11a (registrada no tasks): 10 s fixos.
TOTAL_BUDGET_MARGIN_S = 10.0


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


@dataclass(frozen=True)
class FoldMetrics:
    """Métricas de um fold — design §3.6 (emenda T11a: `sharpe_is` é None-able).

    - ``sharpe_is``: Sharpe anualizado rf=0 da equity IS com os params
      SELECIONADOS — a métrica de seleção (R5/CA-02.3). `None` sse NENHUMA
      combinação do grid produziu Sharpe computável (fundo quebrado no IS ou
      série sem desvio) — R6, nunca NaN.
    - ``ret_oos`` / ``sharpe_oos`` / ``max_dd_oos``: métricas do segmento
      OOS do fold; `None` sse o fundo quebrou no fold (MRG-03/R6) ou o
      segmento é curto demais para o retorno ser definido.

    A struct é compartilhada entre `FoldResult.is_metrics` (carrega
    ``sharpe_is``; campos OOS `None`) e `FoldResult.oos_metrics` (carrega os
    campos OOS; ``sharpe_is`` `None`) — schema declarado do design §3.6.
    """

    sharpe_is: float | None
    ret_oos: float | None
    sharpe_oos: float | None
    max_dd_oos: float | None


@dataclass(frozen=True)
class FoldResult:
    """Resultado de um fold — design §3.6, CA-02.2.

    ``selected_params`` são os usados no OOS DESTE fold (nunca de outro):
    a seleção roda sobre a janela IS do próprio fold (CA-02.2).
    """

    fold: Fold
    selected_params: dict[str, float]
    is_metrics: FoldMetrics
    oos_metrics: FoldMetrics


@dataclass(frozen=True)
class WalkForwardResult:
    """Resultado do walk-forward — design §3.6, CA-03.1.

    - ``oos_equity``: CONCATENAÇÃO EXATA dos segmentos OOS (CA-03.1) — o
      segmento do fold f é a equity do run OOS composto de f a partir do
      primeiro dia útil após ``is_end`` (``equity_curve[tail_len:]``); os
      folds se justapõem sem sobreposição (CA-01.2), então a concatenação é
      a curva OOS inteira da janela avaliada.
    - ``broken_fund``: algum fold quebrou o fundo ⇒ métricas `None` e
      exclusão de comparação automática (CA-03.3); a equity NEGATIVA real
      permanece na concatenação (ADR-0011).
    - ``grid_size`` e ``n_folds``: declarados no MHT (CA-06.2).
    """

    folds: tuple[FoldResult, ...]
    oos_equity: tuple[float, ...]
    oos_dates: tuple[date, ...]
    broken_fund: bool
    grid_size: int
    n_folds: int


@dataclass(frozen=True)
class BudgetReport:
    """Relatório do harness de orçamento (RNF-10/WFK-05 CA-05.1).

    Tempos MEDIDOS em segundos de parede (``per_fold_s`` alinhado aos folds,
    ``total_s``); orçamentos DECLARADOS (por fold 30 s; total ``n_folds x 30
    s + margem``, design §3.6). ``within_budget`` = todos os folds dentro do
    orçamento por fold E o total dentro do orçamento total. A medição é do
    harness; o orçamento vira LIMITE no CI (T12b).
    """

    per_fold_budget_s: float
    total_budget_s: float
    per_fold_s: tuple[float, ...]
    total_s: float
    within_budget: bool


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


def run_walkforward(
    series: dict[str, PriceSeries],
    strategy_factory: Callable[[dict[str, float]], Strategy],
    grid: ParameterGrid,
    folds: tuple[Fold, ...],
    *,
    initial_cash: float = 100_000.0,
    costs: CostModel | None = None,
    slippage: SlippageModel | None = None,
    cap: float = 0.10,
    margin: MarginModel | None = None,
    borrow: BorrowFeeModel | None = None,
    sizer: Sizer | None = None,
    warmup: int,
    on_fold_complete: Callable[[int, float], None] | None = None,
) -> WalkForwardResult:
    """CAIXA PRETA por fold (design §2/§3.6, ADR-0011): roda o walk-forward
    inteiro — seleção IS por fold + avaliação OOS honesta com concatenação.

    1. **IS (seleção, R5/CA-02.3):** para cada fold, as séries são TRUNCADAS
       em ``is_end`` (a fronteira é do ARRAY — CA-01.1) e a grade inteira é
       rodada; escolhe a combinação de maior ``sharpe_annualized_rf0`` sobre
       a equity IS (determinístico: empate desempatado pela ordem do grid;
       Sharpe `None` vale menos que qualquer Sharpe computável — decisão
       local T11a).
    2. **OOS (R4/CA-01.3):** série composta = CAUDA DO IS (últimas
       ``min(warmup, n_is)`` barras <= ``is_end``, dados IS — histórico puro)
       + segmento OOS; roda `run_backtest_multi` com a MESMA configuração do
       run único (herança por construção) e os params selecionados no IS DO
       MESMO fold (CA-02.2). O laço consulta a estratégia só em ``i >= warmup``
       e, com ``len(cauda) = warmup``, a primeira barra consultada é a
       primeira barra OOS — a estratégia NUNCA trade a cauda (CA-01.3).
    3. **Concatenação (CA-03.1):** ``oos_equity = equity_curve[tail_len:]``
       de cada fold, na ordem — os segmentos se justapõem sem sobreposição.

    Pré-condições (design §3.8): ``series`` e ``folds`` não vazios;
    ``warmup >= 0``; folds válidos (disjuntos, ``oos_start`` = dia útil
    seguinte a ``is_end``); ``strategy.warmup == warmup`` para TODAS as
    combinações do grid (senão o corte da cauda desalinha com o gate de
    consulta); janela IS de cada fold >= ``warmup``. Tudo ⇒ `EngineError`
    nomeado.

    Args:
        on_fold_complete: callback opcional ``(fold_index, elapsed_s)``
            invocado ao fim de CADA fold (IS+OOS) — a instrumentação do
            harness de orçamento (CA-05.1); não altera o resultado.
    """
    if not series:
        raise EngineError(
            "run_walkforward: universo vazio — precisa de ao menos um ativo (design §3.6)."
        )
    if not folds:
        raise EngineError(
            "run_walkforward: folds vazio — precisa de ao menos um fold (design §3.6)."
        )
    if warmup < 0:
        raise EngineError(f"run_walkforward: warmup={warmup} < 0 (design §3.6).")

    _validate_folds(folds)

    # Pré-condição strategy.warmup == warmup: a cauda tem len == warmup; se a
    # estratégia consultar num gate diferente, o corte da cauda desalinha com
    # o primeiro bar OOS (a primeira barra consultada deixaria de ser a
    # primeira barra OOS). Vale para TODAS as combinações do grid — o
    # "warmup base" do run é único (design §3.6).
    for params in grid.params:
        probe = strategy_factory(params)
        if probe.warmup != warmup:
            raise EngineError(
                f"run_walkforward: strategy.warmup={probe.warmup} != warmup={warmup} "
                f"para params {params} — o gate de consulta desalinharia com a "
                "cauda do IS (len == warmup); declare warmup == strategy.warmup "
                "(design §3.6/§3.8)."
            )

    # Janela IS de cada fold >= warmup: sem isso a estratégia não teria
    # histórico para aquecer os indicadores dentro do próprio IS.
    for fold in folds:
        is_days = _business_day_count(fold.is_start, fold.is_end)
        if is_days < warmup:
            raise EngineError(
                f"run_walkforward: janela IS do fold [{fold.is_start}, {fold.is_end}] "
                f"tem {is_days} dias úteis < warmup={warmup} (design §3.6/§3.8)."
            )

    tickers = tuple(sorted(series))
    fold_results: list[FoldResult] = []
    oos_equity: list[float] = []
    oos_dates: list[date] = []
    broken_fund = False

    for fold_index, fold in enumerate(folds):
        started = time.perf_counter()

        # 1. IS — séries truncadas no fim do IS (CA-01.1), grade inteira,
        #    seleção por sharpe_annualized_rf0 (R5).
        is_series = {t: _truncate_series(series[t], fold.is_end) for t in tickers}
        selected_params, sharpe_is = _select_params(
            is_series,
            strategy_factory,
            grid,
            initial_cash=initial_cash,
            costs=costs,
            slippage=slippage,
            cap=cap,
            margin=margin,
            borrow=borrow,
            sizer=sizer,
        )

        # 2. OOS — série composta (cauda do IS + segmento OOS), MESMA
        #    configuração, params do IS DO MESMO fold (CA-02.2).
        oos_series, tail_len = _build_composite_series(series, tickers, fold, warmup)
        oos_strategies = {t: strategy_factory(selected_params) for t in tickers}
        oos_result = run_backtest_multi(
            oos_series,
            oos_strategies,
            initial_cash=initial_cash,
            costs=costs,
            slippage=slippage,
            cap=cap,
            sizer=sizer,
            margin=margin,
            borrow=borrow,
        )
        segment_equity = oos_result.equity_curve[tail_len:]
        segment_dates = oos_result.dates[tail_len:]
        oos_equity.extend(segment_equity)
        oos_dates.extend(segment_dates)
        broken_fund = broken_fund or oos_result.broken_fund

        is_metrics = FoldMetrics(
            sharpe_is=sharpe_is, ret_oos=None, sharpe_oos=None, max_dd_oos=None
        )
        oos_metrics = _fold_oos_metrics(segment_equity, oos_result.broken_fund)
        fold_results.append(
            FoldResult(
                fold=fold,
                selected_params=selected_params,
                is_metrics=is_metrics,
                oos_metrics=oos_metrics,
            )
        )

        if on_fold_complete is not None:
            on_fold_complete(fold_index, time.perf_counter() - started)

    return WalkForwardResult(
        folds=tuple(fold_results),
        oos_equity=tuple(oos_equity),
        oos_dates=tuple(oos_dates),
        broken_fund=broken_fund,
        grid_size=grid.grid_size,
        n_folds=len(fold_results),
    )


def measure_walkforward(
    *,
    per_fold_budget_s: float = PER_FOLD_BUDGET_S,
    total_margin_s: float = TOTAL_BUDGET_MARGIN_S,
    **run_kwargs: Any,
) -> tuple[WalkForwardResult, BudgetReport]:
    """Harness de orçamento (RNF-10/WFK-05 CA-05.1): roda `run_walkforward`
    medindo o tempo por fold (IS+OOS) e total contra os orçamentos declarados
    (design §3.6: por fold 30 s; total ``n_folds x 30 s + margem``).

    `run_kwargs` é repassado INTEGRALMENTE a `run_walkforward` (mesmas
    regras, mesmo resultado — a medição nunca altera o run). O tempo por fold
    usa o callback de instrumentação do `run_walkforward`: UMA única passada,
    sem re-execução — medir com re-run dobraria o trabalho e mentiria o
    custo. `on_fold_complete` é reservado pelo harness.

    Args:
        per_fold_budget_s: orçamento declarado por fold, em segundos.
        total_margin_s: margem declarada do orçamento total.
    """
    per_fold_s: list[float] = []
    total_started = time.perf_counter()

    def _on_fold_complete(fold_index: int, elapsed_s: float) -> None:
        per_fold_s.append(elapsed_s)

    result = run_walkforward(**run_kwargs, on_fold_complete=_on_fold_complete)
    total_s = time.perf_counter() - total_started

    total_budget_s = result.n_folds * per_fold_budget_s + total_margin_s
    within_budget = all(t <= per_fold_budget_s for t in per_fold_s) and total_s <= total_budget_s
    report = BudgetReport(
        per_fold_budget_s=per_fold_budget_s,
        total_budget_s=total_budget_s,
        per_fold_s=tuple(per_fold_s),
        total_s=total_s,
        within_budget=within_budget,
    )
    return result, report


def _validate_folds(folds: tuple[Fold, ...]) -> None:
    """Valida os invariantes de fold que o corte/slice assumem (design §3.6/CA-01.2)."""
    for fold in folds:
        if not (fold.is_start <= fold.is_end < fold.oos_start <= fold.oos_end):
            raise EngineError(
                f"run_walkforward: fold inválido {fold} — esperado "
                "is_start <= is_end < oos_start <= oos_end (design §3.6)."
            )
        if _add_business_days(fold.is_end, 1) != fold.oos_start:
            raise EngineError(
                f"run_walkforward: fold inválido {fold} — oos_start deve ser o "
                "dia útil seguinte a is_end (tile exato do OOS, design §3.6/CA-01.2)."
            )


def _select_params(
    is_series: dict[str, PriceSeries],
    strategy_factory: Callable[[dict[str, float]], Strategy],
    grid: ParameterGrid,
    *,
    initial_cash: float,
    costs: CostModel | None,
    slippage: SlippageModel | None,
    cap: float,
    margin: MarginModel | None,
    borrow: BorrowFeeModel | None,
    sizer: Sizer | None,
) -> tuple[dict[str, float], float | None]:
    """Seleção IS (R5/CA-02.3): roda a grade inteira sobre a janela IS e
    escolhe a combinação de maior `sharpe_annualized_rf0` da equity IS.

    Determinístico (RNF-01): empate desempatado pela ORDEM do grid — a
    primeira combinação com o máximo vence (comparação estrita ``>``); Sharpe
    `None` (fundo quebrado no IS, ou série sem desvio) vale menos que
    qualquer Sharpe computável e só substitui outro `None` se aparecer antes
    (primeiro `None` vence). Decisão local T11a (registrada no tasks).
    """
    best_params: dict[str, float] | None = None
    best_sharpe: float | None = None
    for params in grid.params:
        strategies = {t: strategy_factory(params) for t in is_series}
        result = run_backtest_multi(
            is_series,
            strategies,
            initial_cash=initial_cash,
            costs=costs,
            slippage=slippage,
            cap=cap,
            sizer=sizer,
            margin=margin,
            borrow=borrow,
        )
        sharpe = _sharpe_of_equity(result)
        if best_params is None or (
            sharpe is not None and (best_sharpe is None or sharpe > best_sharpe)
        ):
            best_params = params
            best_sharpe = sharpe
    assert best_params is not None  # grid não-vazio (ParameterGrid valida)
    return best_params, best_sharpe


def _sharpe_of_equity(result: BacktestResultMulti) -> float | None:
    """Sharpe anualizado rf=0 da equity do run — `None` sse o fundo quebrou
    (equity não positiva ⇒ retornos indefinidos; R6/MRG-03)."""
    if result.broken_fund:
        return None
    return sharpe_annualized_rf0(_equity_returns(result.equity_curve))


def _equity_returns(equity: Sequence[float]) -> list[float]:
    """Retornos barra a barra da equity — ``e_{i+1}/e_i - 1`` (sem pandas, RNF-07)."""
    return [cur / prev - 1.0 for prev, cur in pairwise(equity)]


def _fold_oos_metrics(segment_equity: Sequence[float], broken: bool) -> FoldMetrics:
    """Métricas do segmento OOS do fold. `None` sse o fundo quebrou no fold
    (MRG-03/R6 — a equity NEGATIVA real permanece na concatenação) ou o
    segmento é curto demais para retorno definido."""
    if broken or len(segment_equity) < 2 or any(e <= 0 for e in segment_equity):
        return FoldMetrics(sharpe_is=None, ret_oos=None, sharpe_oos=None, max_dd_oos=None)
    returns = [cur / prev - 1.0 for prev, cur in pairwise(segment_equity)]
    return FoldMetrics(
        sharpe_is=None,
        ret_oos=float(segment_equity[-1] / segment_equity[0] - 1.0),
        sharpe_oos=sharpe_annualized_rf0(returns),
        max_dd_oos=_max_drawdown_magnitude(segment_equity),
    )


def _max_drawdown_magnitude(equity: Sequence[float]) -> float:
    """Magnitude da maior queda pico-a-vale — mesma definição da analytics
    `max_drawdown` (pico CORRENTE no denominador), sem pandas."""
    running_peak = equity[0]
    worst = 0.0
    for value in equity:
        if value > running_peak:
            running_peak = value
        dd = (value - running_peak) / running_peak
        if dd < worst:
            worst = dd
    return abs(worst)


def _truncate_series(series: PriceSeries, end_date: date) -> PriceSeries:
    """Série cortada no fim do IS — barras com ``date <= end_date`` (CA-01.1)."""
    keep = np.array([d <= end_date for d in series.dates])
    return _slice_series(series, keep)


def _slice_series(series: PriceSeries, keep: np.ndarray) -> PriceSeries:
    """Nova `PriceSeries` com as barras selecionadas pelo mask booleano ``keep``."""
    return PriceSeries(
        ticker=series.ticker,
        dates=series.dates[keep],
        open=series.open[keep],
        high=series.high[keep],
        low=series.low[keep],
        close=series.close[keep],
        volume=series.volume[keep],
        adjusted=series.adjusted,
        hash=series.hash,
        last_ingested_at=series.last_ingested_at,
    )


def _build_composite_series(
    series: dict[str, PriceSeries],
    tickers: tuple[str, ...],
    fold: Fold,
    warmup: int,
) -> tuple[dict[str, PriceSeries], int]:
    """Série composta do OOS (emenda P1, design §3.6): CAUDA do IS — as
    últimas ``min(warmup, n_is)`` barras <= ``is_end``, dados IS — + segmento
    OOS (``[oos_start, oos_end]``). Devolve também ``tail_len`` = nº de
    datas-união do bloco da cauda (datas <= ``is_end``) — o corte de
    ``equity_curve[tail_len:]`` da concatenação exata (CA-03.1).

    A cauda entra como HISTÓRICO PURO: o laço consulta a estratégia só em
    ``i >= warmup`` e, com ``len(cauda) = warmup``, a primeira barra
    consultada é a primeira barra OOS — a estratégia nunca trade a cauda
    (CA-01.3). Ativo com menos de ``warmup`` barras no IS degrada com
    segurança: a cauda fica mais curta e as primeiras barras OOS desse ativo
    entram como aquecimento adicional (nunca lookahead — decisão local T11a,
    registrada no tasks).
    """
    composite: dict[str, PriceSeries] = {}
    for ticker in tickers:
        own_dates = series[ticker].dates.tolist()
        is_bars = [d for d in own_dates if d <= fold.is_end]
        tail = is_bars[-warmup:] if warmup > 0 else []
        oos_bars = [d for d in own_dates if fold.oos_start <= d <= fold.oos_end]
        composite[ticker] = _series_with_dates(series[ticker], tail + oos_bars)

    union_dates = sorted({d for own in composite.values() for d in own.dates.tolist()})
    tail_len = sum(1 for d in union_dates if d <= fold.is_end)
    return composite, tail_len


def _series_with_dates(series: PriceSeries, dates: list[date]) -> PriceSeries:
    """Nova `PriceSeries` com exatamente as datas pedidas (devem existir na série)."""
    position = {d: i for i, d in enumerate(series.dates.tolist())}
    idx = np.array([position[d] for d in dates], dtype=np.int64)
    return PriceSeries(
        ticker=series.ticker,
        dates=series.dates[idx],
        open=series.open[idx],
        high=series.high[idx],
        low=series.low[idx],
        close=series.close[idx],
        volume=series.volume[idx],
        adjusted=series.adjusted,
        hash=series.hash,
        last_ingested_at=series.last_ingested_at,
    )


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
