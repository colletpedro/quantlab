"""E2E (T18) — run real de 20 ativos x 10 anos, ponta a ponta (DoD v0.2).

Roda a Fase 2a inteira sobre o universo do `config/universe.yml` (dados reais
do repositório): estratégia SmaCross 20/50 (a MESMA da Fase 1 — honesta, sem
otimização) com `FixedOneOverN(20)` e os defaults da 2a (custos 1 bps + USD 1,
mínimo 0; slippage 1 bps; cap de participação 10%) contra o benchmark 1/N
buy-and-hold. Concilia (CA-04.2), mede o RNF-04, e persiste o
`BacktestReportMulti` em `results/fase_2a_run_20_ativos.json` (padrão da
Fase 1: run -> relatório -> results/).

**Regra de ouro do projeto:** o resultado é reportado COMO É. Nenhuma
premissa ou parâmetro é ajustado para melhorar número — se o número for
feio, o número é o resultado.

Séries: 2015-01-01 até a última barra ingerida de cada ativo (10 anos na
prática). Nenhum `datetime`/`timezone` no domínio — a medição usa
`time.perf_counter`, de fora do engine (RNF-07/P5).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from statistics import median
from time import perf_counter

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from quantlab.analytics.benchmark import buy_and_hold_multi  # noqa: E402
from quantlab.analytics.metrics import (  # noqa: E402
    avg_exposure,
    reconcile_multi,
    turnover_annualized,
)
from quantlab.analytics.report import BacktestReportMulti  # noqa: E402
from quantlab.config import get_settings  # noqa: E402
from quantlab.engine.backtest import run_backtest_multi  # noqa: E402
from quantlab.engine.broker import CostModel  # noqa: E402
from quantlab.engine.sizing import FixedOneOverN  # noqa: E402
from quantlab.engine.slippage import FixedBps  # noqa: E402
from quantlab.storage.client import mongo_database  # noqa: E402
from quantlab.storage.repository import MongoRepository  # noqa: E402
from quantlab.strategies.sma_cross import SmaCross  # noqa: E402
from quantlab.universe import load_default_universe  # noqa: E402

_FROM = date(2015, 1, 1)
_FAST = 20
_SLOW = 50
_OUTPUT = _PROJECT_ROOT / "results" / "fase_2a_run_20_ativos.json"
_REPETITIONS = 3


def _exposure_series(series: dict, result) -> pd.Series:
    """Notional diário (Σ qty_i x close conhecido) por data-união — derivado
    deterministicamente dos trades e do calendário (RNF-03)."""
    calendar = result.calendar
    values: list[float] = []
    for u, u_date in enumerate(result.dates):
        notional = 0.0
        for trade in result.portfolio.trades:
            if trade.entry_date <= u_date and (trade.exit_date is None or trade.exit_date > u_date):
                idx = calendar.last_known_index_at(trade.ticker, u)
                notional += trade.quantity * float(series[trade.ticker].close[idx])
        values.append(notional)
    return pd.Series(values, index=list(result.dates))


def _summary(series: dict, result) -> dict[str, float]:
    """Turnover e exposição média usam as MESMAS funções do engine (RF-MET-04)
    — mesma definição para estratégia e benchmark. CAGR/Sharpe/maxDD saem do
    relatório (MetricsSummary), não daqui."""
    equity = pd.Series(result.equity_curve, index=list(result.dates))
    return {
        "turnover_annualized": turnover_annualized(
            result.portfolio.trades, equity, n_bars=len(result.dates)
        ),
        "avg_exposure": avg_exposure(_exposure_series(series, result), equity),
    }


def main() -> int:
    settings = get_settings()
    tickers = load_default_universe(settings.universe_path)
    strategies = {ticker: SmaCross(fast=_FAST, slow=_SLOW) for ticker in tickers}

    with mongo_database(settings) as database:
        repository = MongoRepository(database)
        series = {ticker: repository.get_series(ticker, start=_FROM) for ticker in tickers}

    costs = CostModel()
    slippage = FixedBps(bps=1.0)
    sizer = FixedOneOverN(n=len(tickers))

    # Cômputo (run + benchmark + relatório) — mediana de N execuções (RNF-04).
    times: list[float] = []
    for _ in range(_REPETITIONS):
        start = perf_counter()
        run = run_backtest_multi(
            series,
            strategies,
            initial_cash=settings.initial_capital,
            costs=costs,
            slippage=slippage,
            cap=0.10,
            sizer=sizer,
        )
        benchmark = buy_and_hold_multi(
            series,
            n=len(tickers),
            initial_cash=settings.initial_capital,
            costs=costs,
            slippage=slippage,
            cap=0.10,
        )
        times.append(perf_counter() - start)
    compute_median = median(times)

    report = BacktestReportMulti.build(
        strategy=run,
        benchmark=benchmark,
        strategy_name="sma-cross",
        strategy_params={"fast": _FAST, "slow": _SLOW},
        rf=settings.risk_free_rate,
    )

    reconciliation = reconcile_multi(run)
    strat_metrics = _summary(series, run)
    bench_metrics = _summary(series, benchmark)

    def row(label: str, strategy_value: str, benchmark_value: str) -> None:
        print(f"  {label:<20s}{strategy_value:>14s}{benchmark_value:>14s}")

    def pct(value: float | None) -> str:
        return "—" if value is None else f"{value:.2%}"

    print("=" * 72)
    print(
        "Fase 2a — run real de 20 ativos x ~10 anos "
        f"({run.dates[0]} a {run.dates[-1]}, {len(run.dates)} barras de união)"
    )
    print("=" * 72)
    state = "FECHA (isclose 1e-9)" if reconciliation.reconciles else "NÃO FECHA"
    print(
        f"Conciliação CA-04.2: final {reconciliation.final_equity:,.2f} = inicial "
        f"{reconciliation.initial_equity:,.2f} + realizado "
        f"{reconciliation.realized_pnl:,.2f} + não-realizado "
        f"{reconciliation.unrealized_pnl:,.2f} - custos "
        f"{reconciliation.total_costs:,.2f} => {state}"
    )
    print()
    print(f"{'':20s}{'estratégia':>14s}{'benchmark 1/N':>14s}")
    row(
        "retorno acumulado",
        pct(report.strategy.cumulative_return),
        pct(report.benchmark.cumulative_return),
    )
    row("CAGR", pct(report.strategy.cagr), pct(report.benchmark.cagr))
    row(
        "Sharpe",
        f"{report.strategy.sharpe:.4f}" if report.strategy.sharpe else "—",
        f"{report.benchmark.sharpe:.4f}" if report.benchmark.sharpe else "—",
    )
    row(
        "max drawdown",
        pct(report.strategy.max_drawdown.magnitude),
        pct(report.benchmark.max_drawdown.magnitude),
    )
    row("trades", f"{report.strategy.num_trades:d}", f"{report.benchmark.num_trades:d}")
    row(
        "turnover anualizado",
        f"{strat_metrics['turnover_annualized']:.2f}",
        f"{bench_metrics['turnover_annualized']:.2f}",
    )
    row("exposição média", pct(strat_metrics["avg_exposure"]), pct(bench_metrics["avg_exposure"]))
    print(f"  caixa ocioso final   {report.idle_cash:>14,.2f}")
    print()
    print(f"Contadores de mecanismo: {report.counters.to_dict()}")
    print(f"Pendentes mortas (ENG-01.4): {report.pending_dead}")
    print(f"Deslistados (travados): {list(report.delisted) or '-'}")
    print(f"Nunca negociados: {list(report.never_traded) or '-'}")
    print(
        f"RNF-04 (cômputo, mediana de {_REPETITIONS}): {compute_median:.2f}s < 30s "
        f"=> {'OK' if compute_median < 30.0 else 'FALHOU'}"
    )
    print()
    print(f"Relatório persistido em {_OUTPUT.relative_to(_PROJECT_ROOT)}")
    _OUTPUT.write_text(report.to_json(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
