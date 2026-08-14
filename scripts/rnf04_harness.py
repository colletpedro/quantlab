"""Harness do RNF-04 (Fase 2a, P5/D3) — mede o cômputo de 20 ativos x 10 anos.

**ESCOPO DECLARADO (RF-RNF-01 CA-01.3):** a medição cobre ``get_series x N`` +
``run_backtest_multi`` + ``buy_and_hold_multi`` + ``BacktestReportMulti.build()``
— APENAS o cômputo. **EXCLUÍDOS:** a ingestão (I/O Mongo de gravação e
normalização), a serialização do relatório (``to_json``/``to_dict``) e a
renderização de PNG. A exclusão é declarada aqui e na spec (design §7); o
teste `test_rnf04_harness_measures_compute_only` a prova por construção — o
código cronometrado não chama serialização nem gráfico.

**Meta:** < 30 s para 20 ativos x 10 anos (RNF-04 da v0.2 — supersede os 5 s
da Fase 1, ativo único). Mediana de N execuções (default 5) para amortecer
ruído do primeiro aquecimento.

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
    if total < _TARGET_SECONDS:
        print("RNF-04: OK")
        return 0
    print("RNF-04: FALHOU — acima da meta de 30 s")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
