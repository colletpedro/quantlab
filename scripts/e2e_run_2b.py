"""E2E (T13) — run real long+short de 20 ativos x ~10 anos, ponta a ponta (DoD 2b).

Roda a Fase 2b inteira sobre o universo do `config/universe.yml` (dados reais
do repositório): estratégia **SmaCross 20/50 long+short** (T13 —
`SmaCrossLongShort`, a mesma SMA cross da Fase 1 estendida para o lado curto;
SEM otimização — honesta) com `FixedOneOverN(20)`, margem (fator 1.0) e
aluguel (0,50% a.a., disponibilidade ilimitada — vieses declarados) contra
dois parâmetros: o **1/N long-only** (`buy_and_hold_multi`, mesmo
N/custos/slippage/cap — MET-05/CA-05.1) e a **própria estratégia em modo
long-only** (`SmaCross` 20/50 — mesma configuração, sinais de short
descartados). Concilia (CA-04.2 com `qty < 0` e borrow fees no termo
próprio), mede o RNF-04 (run único < 30 s), confirma o determinismo, e
persiste o relatório 2b em `results/fase_2b_run_20_ativos_long_short.json`.

**Regra de ouro do projeto:** o resultado é reportado COMO É. Nenhuma
premissa ou parâmetro é ajustado para melhorar número — se o número for
feio, o número é o resultado. O fundo pode quebrar (RF-MRG-03): aí as
métricas de retorno saem `None` explícito e a comparação automática é
excluída (CA-03.3) — o relatório continua sendo o resultado honesto.

Séries: 2015-01-01 até a última barra ingerida de cada ativo. Nenhum
`datetime`/`timezone` no domínio — a medição usa `time.perf_counter`, de
fora do engine (RNF-07/P5).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from statistics import median
from time import perf_counter

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from quantlab.analytics.benchmark import buy_and_hold_multi  # noqa: E402
from quantlab.analytics.metrics import reconcile_multi  # noqa: E402
from quantlab.analytics.report import BacktestReportMulti  # noqa: E402
from quantlab.config import get_settings  # noqa: E402
from quantlab.engine.backtest import BacktestResultMulti, run_backtest_multi  # noqa: E402
from quantlab.engine.broker import CostModel  # noqa: E402
from quantlab.engine.margin import BorrowFeeModel, MarginModel  # noqa: E402
from quantlab.engine.sizing import FixedOneOverN  # noqa: E402
from quantlab.engine.slippage import FixedBps  # noqa: E402
from quantlab.storage.client import mongo_database  # noqa: E402
from quantlab.storage.repository import MongoRepository  # noqa: E402
from quantlab.strategies.sma_cross import SmaCross  # noqa: E402
from quantlab.strategies.sma_cross_long_short import SmaCrossLongShort  # noqa: E402
from quantlab.universe import load_default_universe  # noqa: E402

_FROM = date(2015, 1, 1)
_FAST = 20
_SLOW = 50
_OUTPUT = _PROJECT_ROOT / "results" / "fase_2b_run_20_ativos_long_short.json"
_REPETITIONS = 3


def _run_long_short(series: dict, initial_cash: float, n: int):
    """Run long+short com margem e aluguel (2b, T08a/T13)."""
    strategies = {ticker: SmaCrossLongShort(fast=_FAST, slow=_SLOW) for ticker in series}
    return run_backtest_multi(
        series,
        strategies,
        initial_cash=initial_cash,
        costs=CostModel(),
        slippage=FixedBps(bps=1.0),
        cap=0.10,
        sizer=FixedOneOverN(n=n),
        margin=MarginModel(),
        borrow=BorrowFeeModel(),
    )


def _run_long_only(series: dict, initial_cash: float, n: int):
    """A MESMA estratégia em modo long-only — sinais de short descartados
    (CA-05.1): `SmaCross` 20/50 é exatamente o `SmaCrossLongShort` com o lado
    curto suprimido (cruzou para cima ⇒ ENTER; para baixo ⇒ EXIT)."""
    strategies = {ticker: SmaCross(fast=_FAST, slow=_SLOW) for ticker in series}
    return run_backtest_multi(
        series,
        strategies,
        initial_cash=initial_cash,
        costs=CostModel(),
        slippage=FixedBps(bps=1.0),
        cap=0.10,
        sizer=FixedOneOverN(n=n),
        margin=MarginModel(),
        borrow=BorrowFeeModel(),
    )


def _is_deterministic(series: dict, initial_cash: float, n: int) -> bool:
    """DoD (RNF-01) — dois runs idênticos: equity, trades e contadores iguais."""
    first = _run_long_short(series, initial_cash, n)
    second = _run_long_short(series, initial_cash, n)
    if first.equity_curve != second.equity_curve:
        return False

    def key(t):
        return (t.ticker, t.quantity, t.entry_price, t.exit_price, t.origin)

    trades1 = [key(t) for t in first.portfolio.trades]
    trades2 = [key(t) for t in second.portfolio.trades]
    return trades1 == trades2 and first.counters.to_dict() == second.counters.to_dict()


def main() -> int:
    settings = get_settings()
    tickers = load_default_universe(settings.universe_path)
    n = len(tickers)

    with mongo_database(settings) as database:
        repository = MongoRepository(database)
        series = {ticker: repository.get_series(ticker, start=_FROM) for ticker in tickers}

    # Cômputo (run long+short + long-only + benchmark) — mediana de N execuções
    # (RNF-04; mede o pipeline inteiro do DoD, escopo declarado).
    times: list[float] = []
    run: BacktestResultMulti | None = None
    long_only_run: BacktestResultMulti | None = None
    benchmark_run: BacktestResultMulti | None = None
    for _ in range(_REPETITIONS):
        start = perf_counter()
        run = _run_long_short(series, settings.initial_capital, n)
        long_only_run = _run_long_only(series, settings.initial_capital, n)
        benchmark_run = buy_and_hold_multi(
            series,
            n=n,
            initial_cash=settings.initial_capital,
            costs=CostModel(),
            slippage=FixedBps(bps=1.0),
            cap=0.10,
        )
        times.append(perf_counter() - start)
    compute_median = median(times)
    assert run is not None and long_only_run is not None and benchmark_run is not None

    deterministic = _is_deterministic(series, settings.initial_capital, n)

    report = BacktestReportMulti.build(
        strategy=run,
        benchmark=benchmark_run,
        strategy_long_only=long_only_run,
        strategy_name="sma-cross-long-short",
        strategy_params={"fast": _FAST, "slow": _SLOW},
        rf=settings.risk_free_rate,
    )

    reconciliation = reconcile_multi(run)
    state = "FECHA (isclose 1e-9)" if reconciliation.reconciles else "NÃO FECHA"

    print("=" * 76)
    print(
        "Fase 2b — run real LONG+SHORT de 20 ativos x ~10 anos "
        f"({run.dates[0]} a {run.dates[-1]}, {len(run.dates)} barras de união)"
    )
    print("=" * 76)
    print(
        f"Conciliação CA-04.2 (qty<0 + borrow no termo próprio): final "
        f"{reconciliation.final_equity:,.2f} = inicial {reconciliation.initial_equity:,.2f} "
        f"+ realizado {reconciliation.realized_pnl:,.2f} + não-realizado "
        f"{reconciliation.unrealized_pnl:,.2f} - custos {reconciliation.total_costs:,.2f} "
        f"- borrow {reconciliation.total_borrow_fees:,.2f} => {state}"
    )
    print(f"Determinismo (RNF-01): {'OK — dois runs idênticos' if deterministic else 'FALHOU'}")
    if run.broken_fund:
        print(
            "⚠️  FUNDO QUEBRADO (RF-MRG-03): métricas de retorno são None explícito "
            "e a comparação automática foi excluída (CA-03.3) — leitura honesta."
        )
    print()

    def pct(value: float | None) -> str:
        return "—" if value is None else f"{value:.2%}"

    def num(value: float | None) -> str:
        return "—" if value is None else f"{value:.4f}"

    print(f"{'':20s}{'long+short':>14s}{'own long-only':>14s}{'benchmark 1/N':>14s}")
    s, lo, b = report.strategy, report.strategy_long_only, report.benchmark
    rows = [
        (
            "retorno acumulado",
            pct(s.cumulative_return),
            pct(lo.cumulative_return),
            pct(b.cumulative_return),
        ),
        ("CAGR", pct(s.cagr), pct(lo.cagr), pct(b.cagr)),
        ("Sharpe (rf=0)", num(s.sharpe), num(lo.sharpe), num(b.sharpe)),
        (
            "max drawdown",
            pct(s.max_drawdown.magnitude),
            pct(lo.max_drawdown.magnitude),
            pct(b.max_drawdown.magnitude),
        ),
        ("trades", f"{s.num_trades:d}", f"{lo.num_trades:d}", f"{b.num_trades:d}"),
        ("turnover anualizado", num(report.turnover), "—", "—"),
        ("exposição gross média", num(report.gross_exposure), "—", "—"),
        ("exposição net média", num(report.net_exposure), "—", "—"),
        ("utilização de margem", num(report.margin_utilization), "—", "—"),
    ]
    for label, sv, lov, bv in rows:
        print(f"  {label:<20s}{sv:>14s}{lov:>14s}{bv:>14s}")
    print(f"  caixa ocioso final      {report.idle_cash:>14,.2f}")
    print(f"  borrow fees totais      {report.borrow_fees:>14,.2f}")
    print()
    print(f"Contadores de mecanismo: {report.counters.to_dict()}")
    print(f"Pendentes mortas (ENG-01.4): {report.pending_dead}")
    print(f"Deslistados (travados): {list(report.delisted) or '-'}")
    print(f"Shorts travados: {list(report.locked_shorts) or '-'}")
    print(f"Nunca negociados: {list(report.never_traded) or '-'}")
    print(
        f"RNF-04 (cômputo, mediana de {_REPETITIONS}): {compute_median:.2f}s < 30s "
        f"=> {'OK' if compute_median < 30.0 else 'FALHOU'}"
    )
    print()

    payload = report.to_dict()
    payload["reconciliation_ca_04_2"] = {
        "initial_equity": reconciliation.initial_equity,
        "final_equity": reconciliation.final_equity,
        "realized_pnl": reconciliation.realized_pnl,
        "unrealized_pnl": reconciliation.unrealized_pnl,
        "total_costs": reconciliation.total_costs,
        "total_borrow_fees": reconciliation.total_borrow_fees,
        "reconciles": reconciliation.reconciles,
    }
    payload["determinism_rnf_01"] = deterministic
    payload["rnf_04_compute_median_s"] = compute_median
    _OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório persistido em {_OUTPUT.relative_to(_PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
