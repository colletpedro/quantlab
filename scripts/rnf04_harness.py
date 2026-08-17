"""Harness do RNF-04 (Fase 2a, P5/D3) + walk-forward (2b, RNF-10) — mede o
cômputo de 20 ativos x 10 anos.

**ESCOPO DECLARADO (RF-RNF-01 CA-01.3):** a medição do run único cobre
``get_series x N`` + ``run_backtest_multi`` + ``buy_and_hold_multi`` +
``BacktestReportMulti.build()`` — APENAS o cômputo. **EXCLUÍDOS:** a ingestão
(I/O Mongo de gravação e normalização), a serialização do relatório
(``to_json``/``to_dict``) e a renderização de PNG. A exclusão é declarada
aqui e na spec (design §7); o teste `test_rnf04_harness_measures_compute_only`
a prova por construção — o código cronometrado não chama serialização nem
gráfico.

**Walk-forward (2b, RNF-10/WFK-05):** o mesmo escopo de cômputo, em duas
escalas — por fold (IS+OOS) e total — via ``measure_walkforward`` (UMA
passada, sem re-execução; o callback de fold mede o tempo dentro do próprio
run). A janela sintética REPRESENTATIVA é declarada como constante literal
abaixo (20 ativos x ~10 anos de dias úteis, 5 folds, grid 4 combinações,
warmup compatível) — a escolha é declarada para o limite não flakear nem
virar letra morta (design §3.6).

**Meta:** < 30 s para 20 ativos x 10 anos (RNF-04 da v0.2 — supersede os 5 s
da Fase 1, ativo único). Mediana de N execuções (default 5) para amortecer
ruído do primeiro aquecimento. O orçamento do WF é por fold 30 s e total
``n_folds x 30 s + margem`` (RNF-10) — o harness sai com código de saída
NÃO-ZERO se qualquer escala estourar (limite BLOQUEANTE no CI, T12b).

**Sem base ingerida?** O harness cai para séries sintéticas determinísticas
de 10 anos (RNF-03) e REGISTRA a medição como sintética: o número vale como
referência do cômputo puro, não como medição sobre dados reais. Nenhum
`datetime`/`timezone` no domínio — o relógio de parede (`time.perf_counter`)
vive só aqui, no harness (RNF-07).
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from time import perf_counter

import numpy as np
from numpy.typing import NDArray

from quantlab.analytics.benchmark import buy_and_hold_multi
from quantlab.analytics.report import BacktestReportMulti
from quantlab.config import Settings, get_settings
from quantlab.engine.backtest import run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.slippage import FixedBps
from quantlab.engine.walkforward import (
    BudgetReport,
    ParameterGrid,
    WalkForwardResult,
    build_folds,
    measure_walkforward,
)
from quantlab.storage.client import mongo_database
from quantlab.storage.repository import MongoRepository
from quantlab.storage.series import PriceSeries
from quantlab.strategies.sma_cross import SmaCross
from quantlab.universe import load_default_universe

#: Escopo declarado da medição (RF-RNF-01 CA-01.3 / design §7) — constante
#: literal no harness, verificada por `test_rnf04_harness_measures_compute_only`.
SCOPE = (
    "get_series x N + run_backtest_multi + buy_and_hold_multi + "
    "BacktestReportMulti.build() — APENAS o cômputo; exclui ingestão "
    "(I/O Mongo de gravação/normalização), serialização do relatório "
    "(to_json/to_dict) e renderização de PNG (P5)."
)

#: Meta do RNF-04 da v0.2: 20 ativos x 10 anos abaixo de 30 s.
_TARGET_SECONDS = 30.0

#: Barras diárias por ano (aproximação de pregão usada na série sintética).
_BARS_PER_YEAR = 252

_REPETITIONS = 5

# ─── Janela sintética REPRESENTATIVA do walk-forward (T12b, RNF-10) ──────────
# Declarada como constante literal — a escolha é parte do contrato do limite:
# se a janela mudar, o orçamento deixa de valer para o que foi medido.
# 20 ativos x ~10 anos de DIAS ÚTEIS (seg-sex, decisão local T10); 5 folds
# com IS 1260 dias úteis (~5 anos) e OOS 252 (~1 ano); grid 4 combinações de
# SmaCross com slow fixo 20 (warmup = 20 para TODAS as combinações — a
# pré-condição strategy.warmup == warmup do run_walkforward, §3.8).
WF_TICKERS = 20
WF_YEARS = 10
WF_IS_WINDOW = 1260
WF_OOS_WINDOW = 252
WF_GRID_FASTS = (10, 12, 15, 18)
WF_WARMUP = 20


def _synthetic_series(tickers: list[str], *, years: int = 10) -> dict[str, PriceSeries]:
    """Séries sintéticas determinísticas de `years` anos (RNF-03/RNF-01).

    `np.random.default_rng(seed)` fixa o gerador: mesma entrada => mesmas
    séries, em qualquer execução. Caminhada aleatória com drift — barata o
    bastante para o harness medir o cômputo sem depender de banco.
    """
    n_bars = years * _BARS_PER_YEAR
    series: dict[str, PriceSeries] = {}
    for index, ticker in enumerate(tickers):
        rng = np.random.default_rng(seed=index + 1)
        returns = rng.normal(loc=0.0002, scale=0.01, size=n_bars)
        prices = 100.0 * np.exp(np.cumsum(returns))
        first = date(2015, 1, 2)
        dates: NDArray[np.object_] = np.empty(n_bars, dtype=object)
        dates[:] = [first + timedelta(days=i) for i in range(n_bars)]
        values = prices.astype(np.float64)
        series[ticker] = PriceSeries(
            ticker=ticker,
            dates=dates,
            open=values,
            high=values,
            low=values,
            close=values,
            volume=np.full(n_bars, 1_000_000.0),
            adjusted=True,
            hash=f"{ticker}:synthetic",
        )
    return series


def _business_dates(first: date, n: int) -> list[date]:
    """Os primeiros `n` dias úteis (seg-sex) a partir de `first`, inclusive —
    a mesma semântica de "dia útil" que o engine usa nos folds (decisão local
    T10). A janela do WF é declarada em dias úteis; a série sintética precisa
    de barras exatamente nesses dias para o tile dos folds fechar."""
    result: list[date] = []
    day = first
    while len(result) < n:
        if day.weekday() < 5:
            result.append(day)
        day += timedelta(days=1)
    return result


def _synthetic_business_series(tickers: list[str], *, years: int = 10) -> dict[str, PriceSeries]:
    """Séries sintéticas determinísticas de `years` anos de DIAS ÚTEIS (RNF-03).

    A caminhada aleatória é a mesma do `_synthetic_series` (seed por ticker),
    mas as barras caem em dias úteis seg-sex — a janela que o `build_folds`
    assume (decisão local T10). Determinística: mesma entrada, mesmas séries.
    """
    n_bars = years * _BARS_PER_YEAR
    first = date(2015, 1, 2)  # sexta-feira
    bar_dates = _business_dates(first, n_bars)
    series: dict[str, PriceSeries] = {}
    for index, ticker in enumerate(tickers):
        rng = np.random.default_rng(seed=index + 1)
        returns = rng.normal(loc=0.0002, scale=0.01, size=n_bars)
        prices = 100.0 * np.exp(np.cumsum(returns))
        dates: NDArray[np.object_] = np.empty(n_bars, dtype=object)
        dates[:] = bar_dates
        values = prices.astype(np.float64)
        series[ticker] = PriceSeries(
            ticker=ticker,
            dates=dates,
            open=values,
            high=values,
            low=values,
            close=values,
            volume=np.full(n_bars, 1_000_000.0),
            adjusted=True,
            hash=f"{ticker}:synthetic-business",
        )
    return series


def measure_wf(
    tickers: list[str],
    *,
    initial_cash: float = 100_000.0,
    costs: CostModel | None = None,
    slippage: FixedBps | None = None,
    cap: float = 0.10,
) -> tuple[WalkForwardResult, BudgetReport]:
    """Medição do walk-forward (RNF-10/WFK-05) em UMA passada.

    Constrói a janela sintética REPRESENTATIVA declarada (constantes WF_*),
    os folds (5) e o grid (4 combinações de SmaCross com slow=20 fixo —
    warmup 20 para TODAS), e chama `measure_walkforward` do engine — que roda
    `run_walkforward` UMA única vez e mede por fold via callback (sem
    re-execução). Devolve ``(result, BudgetReport)``; o `BudgetReport` já
    compara cada fold com `PER_FOLD_BUDGET_S` (30 s) e o total com
    ``n_folds x 30 s + margem`` — o chamador decide o exit code (T12b).
    """
    series = _synthetic_business_series(tickers, years=WF_YEARS)
    n_bars = WF_YEARS * _BARS_PER_YEAR
    first = date(2015, 1, 2)
    window = _business_dates(first, n_bars)
    folds = build_folds(window[0], window[-1], is_window=WF_IS_WINDOW, oos_window=WF_OOS_WINDOW)
    grid = ParameterGrid(tuple({"fast": float(fast), "slow": 20.0} for fast in WF_GRID_FASTS))

    def factory(params: dict[str, float]) -> SmaCross:
        return SmaCross(fast=int(params["fast"]), slow=int(params["slow"]))

    return measure_walkforward(
        series=series,
        strategy_factory=factory,
        grid=grid,
        folds=folds,
        initial_cash=initial_cash,
        costs=costs,
        slippage=slippage,
        cap=cap,
        warmup=WF_WARMUP,
    )


def measure(
    series: dict[str, PriceSeries],
    strategies: dict[str, SmaCross],
    *,
    initial_cash: float = 100_000.0,
    costs: CostModel | None = None,
    slippage: FixedBps | None = None,
    cap: float = 0.10,
    repetitions: int = _REPETITIONS,
) -> float:
    """Mediana do cômputo puro — run multi + benchmark + relatório, em segundos.

    Nada além disso é cronometrado: sem `get_series` aqui (já lidas), sem
    serialização do relatório, sem gráfico (SCOPE). Determinístico e sem
    relógio no domínio — `perf_counter` vive só nesta função.
    """
    cost_model = costs or CostModel()
    slippage_model = slippage or FixedBps(bps=1.0)
    times: list[float] = []
    for _ in range(repetitions):
        start = perf_counter()
        run = run_backtest_multi(
            series,
            strategies,
            initial_cash=initial_cash,
            costs=cost_model,
            slippage=slippage_model,
            cap=cap,
        )
        benchmark = buy_and_hold_multi(
            series,
            n=len(series),
            initial_cash=initial_cash,
            costs=cost_model,
            slippage=slippage_model,
            cap=cap,
        )
        BacktestReportMulti.build(
            strategy=run,
            benchmark=benchmark,
            strategy_name="sma-cross",
            strategy_params={"fast": _SMA_FAST, "slow": _SMA_SLOW},
        )
        times.append(perf_counter() - start)
    return median(times)


_SMA_FAST = 20
_SMA_SLOW = 50


def main() -> int:
    settings: Settings = get_settings()
    tickers = load_default_universe(settings.universe_path)
    strategies = {ticker: SmaCross(fast=_SMA_FAST, slow=_SMA_SLOW) for ticker in tickers}

    # get_series x N — leitura, parte do escopo; a INGESTÃO (gravação) fica fora.
    series: dict[str, PriceSeries] = {}
    read_time = 0.0
    source = "storage"
    try:
        with mongo_database(settings) as database:
            repository = MongoRepository(database)
            start = perf_counter()
            series = {ticker: repository.get_series(ticker) for ticker in tickers}
            read_time = perf_counter() - start
    except Exception as exc:  # base não ingerida ou indisponível
        series = _synthetic_series(tickers)
        source = f"sintético (RNF-03) — storage indisponível ({exc.__class__.__name__})"

    compute = measure(series, strategies)
    total = read_time + compute

    print(f"RNF-04 harness — {len(tickers)} ativos x ~10 anos")
    print(f"  fonte das séries: {source}")
    print(f"  get_series x N:   {read_time:6.2f}s")
    print(f"  cômputo (mediana de {_REPETITIONS}): {compute:6.2f}s")
    print(f"  total:            {total:6.2f}s  (meta < {_TARGET_SECONDS:.0f}s)")
    print(f"ESCOPO (RF-RNF-01 CA-01.3): {SCOPE}")
    run_ok = total < _TARGET_SECONDS

    # ── RNF-10/WFK-05 (2b, T12b): walk-forward em duas escalas (UMA passada) ─
    _, wf_report = measure_wf(tickers, costs=CostModel(), slippage=FixedBps(bps=1.0), cap=0.10)
    print()
    print(
        f"RNF-10 harness — walk-forward ({len(tickers)} ativos x {WF_YEARS} anos "
        f"úteis, {len(wf_report.per_fold_s)} folds, grid {len(WF_GRID_FASTS)} combinações)"
    )
    print(f"  fonte das séries: sintético determinístico (RNF-03 — {WF_TICKERS} tickers)")
    print(f"  tempo por fold (IS+OOS): {', '.join(f'{t:.2f}s' for t in wf_report.per_fold_s)}")
    folds_ok = all(t <= wf_report.per_fold_budget_s for t in wf_report.per_fold_s)
    print(
        f"  orçamento por fold: {wf_report.per_fold_budget_s:.0f}s "
        f"(todos dentro? {'sim' if folds_ok else 'NÃO'})"
    )
    print(
        f"  total:            {wf_report.total_s:6.2f}s  "
        f"(orçamento {wf_report.total_budget_s:.0f}s = n_folds x 30s + margem)"
    )
    dentro = "sim" if wf_report.within_budget else "NÃO"
    print(f"  dentro do orçamento: {dentro}")
    print(
        "ESCOPO (RNF-10/WFK-05): cômputo apenas — sem ingestão, sem "
        "serialização, sem PNG (padrão P5 da 2a)"
    )
    wf_ok = wf_report.within_budget

    if run_ok and wf_ok:
        print()
        print("RNF-04: OK")
        print("RNF-10: OK")
        return 0
    print()
    if not run_ok:
        print("RNF-04: FALHOU — acima da meta de 30 s")
    if not wf_ok:
        print("RNF-10: FALHOU — walk-forward acima do orçamento por fold ou total")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
