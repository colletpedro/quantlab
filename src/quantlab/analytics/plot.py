"""Gráfico de backtest — F2, RF-CLI-03.

Painel superior: equity da estratégia e do benchmark, com marcações de
entrada (▲) e saída (▼) dos trades da estratégia. Painel inferior: drawdown
da estratégia. Salvo em arquivo — o backend `Agg` é fixado antes de importar
`pyplot` porque o CLI roda sem display, e o backend interativo default falha
(ou trava) num ambiente sem um.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from quantlab.engine.backtest import BacktestResult

__all__ = ["plot_backtest"]


def _equity_series(result: BacktestResult) -> pd.Series:
    return pd.Series(
        [point.equity for point in result.equity_curve],
        index=[point.date for point in result.equity_curve],
    )


def _drawdown_series(equity: pd.Series) -> pd.Series:
    """Drawdown barra a barra, para o painel — não o resumo de `metrics.max_drawdown`.

    Duplica duas linhas de `analytics/metrics.py` (pico corrente via `cummax`)
    em vez de importar de lá: `max_drawdown()` devolve o resumo escalar de um
    `DrawdownResult`, não a série completa que o painel precisa desenhar. Two
    linhas puras não justificam uma função nova compartilhada.
    """
    running_peak = equity.cummax()
    return (equity - running_peak) / running_peak


def plot_backtest(
    *,
    ticker: str,
    strategy: BacktestResult,
    benchmark: BacktestResult,
    output_path: str | Path,
) -> Path:
    """RF-CLI-03 — equity (estratégia x benchmark) no painel superior, drawdown no inferior.

    Marca entrada e saída de cada trade **fechado** da estratégia; um trade
    ainda aberto ao fim da série não tem `exit_date` e não recebe marcador de
    saída (é o mesmo caso que `BacktestResult.unrealized_pnl` documenta).
    """
    strategy_equity = _equity_series(strategy)
    benchmark_equity = _equity_series(benchmark)
    drawdown = _drawdown_series(strategy_equity)

    fig, (ax_equity, ax_drawdown) = plt.subplots(
        2, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [2, 1]}, sharex=False
    )

    ax_equity.plot(
        strategy_equity.index, strategy_equity.to_numpy(), label="Estratégia", color="tab:blue"
    )
    ax_equity.plot(
        benchmark_equity.index,
        benchmark_equity.to_numpy(),
        label="Buy & hold",
        color="tab:gray",
        linestyle="--",
    )

    entry_dates = [trade.entry_date for trade in strategy.trades]
    entry_values = [strategy_equity.loc[d] for d in entry_dates]
    if entry_dates:
        ax_equity.scatter(
            entry_dates,
            entry_values,
            marker="^",
            color="tab:green",
            s=80,
            zorder=3,
            label="Entrada",
        )

    exit_dates = [trade.exit_date for trade in strategy.trades if trade.exit_date is not None]
    exit_values = [strategy_equity.loc[d] for d in exit_dates]
    if exit_dates:
        ax_equity.scatter(
            exit_dates, exit_values, marker="v", color="tab:red", s=80, zorder=3, label="Saída"
        )

    ax_equity.set_ylabel("Equity (USD)")
    ax_equity.set_title(f"{ticker} — estratégia vs. buy & hold")
    ax_equity.legend(loc="upper left")
    ax_equity.grid(alpha=0.3)

    ax_drawdown.fill_between(
        drawdown.index, drawdown.to_numpy() * 100.0, 0.0, color="tab:red", alpha=0.4
    )
    ax_drawdown.set_ylabel("Drawdown (%)")
    ax_drawdown.set_xlabel("Data")
    ax_drawdown.grid(alpha=0.3)

    fig.tight_layout()

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=150)
    plt.close(fig)
    return destination
