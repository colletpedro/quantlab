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

from quantlab.engine.backtest import BacktestResultMulti
from quantlab.engine.portfolio import Trade
from quantlab.exceptions import EngineError

__all__ = [
    "DrawdownResult",
    "ReconciliationReport",
    "avg_exposure",
    "cagr",
    "contribution_per_asset",
    "daily_returns",
    "hit_rate",
    "max_drawdown",
    "reconcile_multi",
    "sharpe",
    "turnover_annualized",
]

#: Tolerância da identidade de conciliação multi-ativo — §6, RNF-08.
_RECONCILIATION_REL_TOL = 1e-9

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


# ─── 2a (T13): conciliação multi-ativo (POR-04.2/§6) e contribuição por ativo ─


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Parcelas da identidade de POR-04.2/§6 — emenda T13 (design §6).

    - ``realized_pnl`` é **BRUTO** de custos (design §4.6): os custos entram
      uma única vez, no termo próprio ``total_costs``. Um PnL líquido aqui
      subtrairia custos duas vezes e a identidade fecharia errado por 2 x
      custos — o erro que a definição bruta existe para evitar.
    - ``unrealized_pnl`` usa o último close conhecido por ativo (POR-02.2),
      incluindo a posição TRAVADA por deslistagem (POR-02.3).
    """

    initial_equity: float
    final_equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_costs: float
    #: 2b (T03, RF-SHT-04/§6): custo de aluguel — TERMO PRÓPRIO, entra UMA
    #: única vez na identidade (a armadilha da dupla contagem da T13 vale
    #: também para o fee: nunca somá-lo dentro de `total_costs` E aqui).
    total_borrow_fees: float = 0.0

    @property
    def reconciles(self) -> bool:
        """Identidade de §6: ``final - inicial ≡ Σ realizado + Σ não-realizado
        - Σ custos - Σ borrow_fees`` (2b).

        `math.isclose(rel_tol=1e-9)`, conforme RNF-08 — nunca igualdade exata:
        dinheiro é float e os dois lados percorrem caminhos de arredondamento
        diferentes. Com `qty < 0` o realizado/não-realizado já carrega o sinal
        (SHT-04 CA-04.2).
        """
        left = self.final_equity - self.initial_equity
        right = self.realized_pnl + self.unrealized_pnl - self.total_costs - self.total_borrow_fees
        return math.isclose(left, right, rel_tol=_RECONCILIATION_REL_TOL, abs_tol=1e-9)


@dataclass(frozen=True, slots=True)
class _IdentityParts:
    """Parcelas brutas derivadas dos trades (realizado + custos + não-realizado)."""

    realized: float
    costs: float
    unrealized: float


def _identity_parts(result: BacktestResultMulti) -> _IdentityParts:
    realized = sum(trade.realized_pnl for trade in result.portfolio.trades)
    costs = sum(trade.total_cost for trade in result.portfolio.trades)
    marks = result.portfolio.marks
    unrealized = 0.0
    for trade in result.portfolio.trades:
        if not trade.is_open:
            continue
        mark = marks.get(trade.ticker)
        if mark is None:
            raise EngineError(
                f"reconcile_multi: trade aberto em {trade.ticker} sem último close "
                "conhecido (marks) — erro de programação (POR-02.2)."
            )
        unrealized += (mark - trade.entry_price) * trade.quantity
    return _IdentityParts(realized=realized, costs=costs, unrealized=unrealized)


def reconcile_multi(result: BacktestResultMulti) -> ReconciliationReport:
    """Concilia o run multi-ativo (CA-04.2/§6, emenda T13).

    A identidade soma sobre os **N ativos do run**, incluindo o nunca-
    negociado (contribui zero — R2). `math.isclose(rel_tol=1e-9)` (RNF-08),
    nunca igualdade exata.

    Raises:
        EngineError: trade aberto sem ``marks[ticker]`` (erro de programa —
            o laço garante a pré-condição de `market_to_market` a cada barra).
    """
    parts = _identity_parts(result)
    return ReconciliationReport(
        initial_equity=result.initial_cash,
        final_equity=result.final_equity,
        realized_pnl=parts.realized,
        unrealized_pnl=parts.unrealized,
        total_costs=parts.costs,
        # 2b (T03): termo próprio, acumulado no laço (T08a) — aqui lido do
        # resultado; o teste fecha com o valor em forma fechada (CA-04.2).
        total_borrow_fees=result.borrow_fees,
    )


def contribution_per_asset(result: BacktestResultMulti) -> dict[str, float]:
    """PnL por ativo (MET-01.1/CA-01.1, emenda T13).

    Por ativo: realizado **bruto** - custos alocados por trade + não-
    realizado pelo último close conhecido (inclui posição travada — POR-02.3).
    TODOS os N ativos do run estão no dicionário — o nunca-negociado
    contribui zero (SIZ-02.4/R2), sem buraco. A soma concilia com o PnL total
    (a identidade de §6, fatiada por ticker).
    """
    contribution: dict[str, float] = {ticker: 0.0 for ticker in result.tickers}
    for trade in result.portfolio.trades:
        contribution[trade.ticker] += trade.realized_pnl - trade.total_cost
    for trade in result.portfolio.trades:
        if trade.is_open:
            mark = result.portfolio.marks.get(trade.ticker)
            if mark is None:
                raise EngineError(
                    f"contribution_per_asset: trade aberto em {trade.ticker} sem último close "
                    "conhecido (marks) — erro de programação (POR-02.2)."
                )
            contribution[trade.ticker] += (mark - trade.entry_price) * trade.quantity
    return contribution


#: Pregões por ano na anualização de RF-MET-04/P4 (CA-04.3).
_TRADING_DAYS_PER_YEAR = 252


def turnover_annualized(trades: list[Trade], equity_daily: pd.Series, n_bars: int) -> float:
    """Turnover anualizado — fórmula fechada de RF-MET-04/P4 (emenda T14).

    ``(Σ|notional_compra| + Σ|notional_venda|) / (2 x patrimônio_médio) x (252 / n_barras)``,
    com patrimônio_médio = média aritmética DIÁRIA da equity sobre as n_barras
    (``len(equity_daily) == n_bars`` — séries alinhadas). Notional por trade =
    ``quantity x preço de execução limpo`` (custos fora do preço — SLP-04.3).
    Trades de REBALANCE entram no giro (decisão T14 — são giro real de caixa;
    o relatório os separa por flag, T16). Esta função é a ÚNICA fonte da
    fórmula: a mesma definição vale para estratégia e benchmark (MET-04.2).
    """
    if n_bars < 1:
        raise EngineError(f"turnover_annualized: n_bars={n_bars} < 1 (RF-MET-04).")
    if equity_daily.empty or len(equity_daily) != n_bars:
        raise EngineError(
            "turnover_annualized: equity_daily deve ter exatamente n_bars="
            f"{n_bars} pontos (alinhada à série), recebidos {len(equity_daily)} (RF-MET-04)."
        )
    avg_equity = float(equity_daily.mean())
    if avg_equity <= 0:
        raise EngineError(f"turnover_annualized: patrimônio médio {avg_equity} <= 0 (RF-MET-04).")
    notional_buy = sum(abs(t.quantity * t.entry_price) for t in trades)
    notional_sell = sum(abs(t.quantity * t.exit_price) for t in trades if t.exit_price is not None)
    return (notional_buy + notional_sell) / (2 * avg_equity) * (_TRADING_DAYS_PER_YEAR / n_bars)


def avg_exposure(daily_notional: pd.Series, equity_daily: pd.Series) -> float:
    """Exposição média — média diária de ``(Σ qty_i x close_i) / equity`` (MET-04.4).

    Séries alinhadas = mesmo comprimento E mesmo índice (sem alinhamento
    silencioso do pandas); equity estritamente positiva (divisão definida).
    MESMA definição para estratégia e benchmark (MET-04.2).
    """
    if daily_notional.empty or equity_daily.empty:
        raise EngineError("avg_exposure: séries vazias (RF-MET-04).")
    if len(daily_notional) != len(equity_daily) or not daily_notional.index.equals(
        equity_daily.index
    ):
        raise EngineError("avg_exposure: séries desalinhadas (comprimento ou índice) (RF-MET-04).")
    if (equity_daily <= 0).any():
        raise EngineError("avg_exposure: equity deve ser estritamente positiva (RF-MET-04).")
    return float((daily_notional / equity_daily).mean())
