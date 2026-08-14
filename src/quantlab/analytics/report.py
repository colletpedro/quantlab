"""`BacktestReport` — E3, design §5.2, ANA-03.1.

Ponto de convergência de tudo que a Fase 1 promete mostrar: as métricas de
E1, lado a lado entre estratégia e benchmark (E2), as premissas que tornam
o número honesto de ler (rf, custos, tratamento de dividendo — ENG-03.2,
ENG-04.3, PER-03.1), e a seção fixa de vieses (ANA-03.1). Renderiza em dois
formatos, texto para o CLI e um dicionário serializável em JSON para
`backtest_runs` — o mesmo dado, duas saídas.
"""

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from quantlab.analytics.metrics import DrawdownResult, cagr, daily_returns, hit_rate, max_drawdown
from quantlab.analytics.metrics import sharpe as _sharpe
from quantlab.engine.backtest import BacktestResult, BacktestResultMulti
from quantlab.engine.broker import CostModel, MechanismCounters
from quantlab.engine.slippage import SlippageModel
from quantlab.exceptions import EngineError

__all__ = [
    "BIAS_DISCLOSURE",
    "BIAS_DISCLOSURE_MULTI",
    "BacktestReport",
    "BacktestReportMulti",
    "MetricsSummary",
]

#: ANA-03.1 — constante literal, não texto montado condicionalmente. Um
#: relatório sem esta seção é impossível de produzir: `BacktestReport.build`
#: não tem um caminho que a omita. Conteúdo idêntico a design §5.2.
BIAS_DISCLOSURE: tuple[str, ...] = (
    "Survivorship bias — universo fixo de sobreviventes; retornos inflados por construção.",
    "Sem slippage — execução integral ao open, sem desvio entre preço observado e preço pago.",
    "Custos simplificados — modelo fixo + bps; sem spread, sem borrow, sem imposto.",
    "Sem impacto de mercado — ordens não movem preço, qualquer tamanho executa.",
    "Granularidade de posição fictícia — quantidades inteiras calculadas sobre preços "
    "ajustados, que não são os preços históricos reais (AAPL pré-split-4:1 aparece a ~1/4 "
    "do preço da época). A restrição de ação inteira, portanto, não corresponde à "
    "restrição que existia historicamente.",
    "Sem correção para múltiplas hipóteses — parâmetros testados repetidamente contra a "
    "mesma amostra inflacionam métricas.",
)

#: MET-03.1 (v0.2, T16) — a seção fixa de vieses do relatório MULTI: itens da
#: Fase 1 preservados + os 5 itens novos do RF-MET-03. Constante literal, como
#: na Fase 1 §5.2 — nenhum caminho do `BacktestReportMulti.build` omite este
#: bloco.
BIAS_DISCLOSURE_MULTI: tuple[str, ...] = (
    *BIAS_DISCLOSURE,
    "Ambiguidade intrabarra resolvida por pior caso — quando limite e stop tocam "
    "na mesma barra, o resultado registrado é o desfavorável (fills nos preços das "
    "ordens, sem slippage — ADR-0007).",
    "Slippage modelado mas não calibrado contra execuções reais — o modelo "
    "(bps fixo + participação) é um parâmetro configurado, não uma medição.",
    "Sem impacto permanente de mercado — o preço não reage ao volume negociado "
    "pelo próprio backtest.",
    "Fill integral ao preço limite é otimista — a ordem pode não preencher ou "
    "preencher parcialmente (S2).",
    "Atendimento alfabético com caixa insuficiente é determinístico e neutro, mas "
    "qualquer regra de atendimento é seleção com viés (Q5).",
)

#: ENG-04.3 — o backtest usa série ajustada (ADR-0003); o provento entra no
#: retorno via preço, nunca como crédito de caixa.
_DIVIDEND_TREATMENT = "ajuste de preço na série (ADR-0003) — sem crédito em caixa"

#: ANA-01.5 — abaixo disto, o relatório avisa que a amostra é curta demais
#: para inferência.
_MIN_SAMPLE_SIZE = 30


@dataclass(frozen=True, slots=True)
class MetricsSummary:
    """As métricas de RF-ANA-01, para um `BacktestResult` — estratégia ou benchmark."""

    cumulative_return: float
    cagr: float
    sharpe: float | None
    max_drawdown: DrawdownResult
    num_trades: int
    hit_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        drawdown = self.max_drawdown
        return {
            "cumulative_return": self.cumulative_return,
            "cagr": self.cagr,
            "sharpe": self.sharpe,
            "max_drawdown": {
                "magnitude": drawdown.magnitude,
                "peak_date": drawdown.peak_date.isoformat(),
                "trough_date": drawdown.trough_date.isoformat(),
                "recovery_date": (
                    drawdown.recovery_date.isoformat() if drawdown.recovery_date else None
                ),
            },
            "num_trades": self.num_trades,
            "hit_rate": self.hit_rate,
        }


def _summarize(result: BacktestResult, rf: float) -> MetricsSummary:
    equity = pd.Series(
        [point.equity for point in result.equity_curve],
        index=[point.date for point in result.equity_curve],
    )
    returns = daily_returns(equity)
    return MetricsSummary(
        cumulative_return=(result.final_equity / result.initial_cash) - 1.0,
        cagr=cagr(equity),
        sharpe=_sharpe(returns, rf=rf),
        max_drawdown=max_drawdown(equity),
        num_trades=len(result.trades),
        hit_rate=hit_rate(result.trades),
    )


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """O relatório completo de um backtest — design §5.2.

    Construído com `build()`, não diretamente: `MetricsSummary` de estratégia
    e benchmark, avisos e provisões dependem de derivar dados de dois
    `BacktestResult`, e um `__init__` posicional convidaria a montar um
    relatório com metade dos campos calculados errado.
    """

    ticker: str
    strategy: MetricsSummary
    benchmark: MetricsSummary
    risk_free_rate: float
    costs: CostModel
    series_hash: str
    last_ingested_at: str | None
    insufficient_sample: bool
    #: RF-CON-02 (v0.9, design §5.2) — o que produziu este run, dentro do
    #: próprio relatório: sem isto, um JSON copiado ou lido fora do
    #: repositório só é rastreável pelo nome do arquivo, que é convenção,
    #: não dado.
    strategy_name: str = ""
    strategy_params: dict[str, Any] = field(default_factory=dict)
    initial_cash: float = 0.0
    bars_consumed: int = 0
    effective_start: str = ""
    effective_end: str = ""

    @classmethod
    def build(
        cls,
        *,
        strategy: BacktestResult,
        benchmark: BacktestResult,
        strategy_name: str,
        strategy_params: dict[str, Any],
        rf: float = 0.0,
    ) -> "BacktestReport":
        """CA-02.1 — as mesmas métricas, lado a lado, de estratégia e benchmark.

        `strategy_name`/`strategy_params` são obrigatórios (v0.9, RF-CON-02):
        sem eles não haveria como o relatório serializado se auto-descrever
        (CA-02.1). `bars_consumed` e as datas efetivas vêm da equity curve da
        estratégia — um ponto por barra consumida pelo laço (design §4.3),
        então `len(strategy.equity_curve)` é exatamente `len(series)`, sem
        precisar que `build()` receba a `PriceSeries` só para isso.
        """
        if not strategy.equity_curve:  # pragma: no cover - run_backtest já recusa série vazia
            raise ValueError("BacktestResult sem equity curve: nada para reportar.")
        return cls(
            ticker=strategy.ticker,
            strategy=_summarize(strategy, rf),
            benchmark=_summarize(benchmark, rf),
            risk_free_rate=rf,
            costs=strategy.costs,
            series_hash=strategy.series_hash,
            last_ingested_at=strategy.last_ingested_at,
            insufficient_sample=len(strategy.equity_curve) < _MIN_SAMPLE_SIZE,
            strategy_name=strategy_name,
            strategy_params=dict(strategy_params),
            initial_cash=strategy.initial_cash,
            bars_consumed=len(strategy.equity_curve),
            effective_start=strategy.equity_curve[0].date.isoformat(),
            effective_end=strategy.equity_curve[-1].date.isoformat(),
        )

    @property
    def warnings(self) -> tuple[str, ...]:
        """Avisos condicionais — não fazem parte da seção fixa de vieses.

        ANA-01.5 (amostra curta) e ENG-03.2 (custo zerado) só aparecem quando
        se aplicam; `BIAS_DISCLOSURE` aparece sempre, incondicionalmente.
        """
        items: list[str] = []
        if self.insufficient_sample:
            items.append(
                f"Amostra insuficiente (< {_MIN_SAMPLE_SIZE} barras de equity) para "
                "inferência estatística confiável."
            )
        if self.costs.is_zero:
            items.append("Custos de transação configurados como zero — resultados irrealistas.")
        return tuple(items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "strategy": self.strategy.to_dict(),
            "benchmark": self.benchmark.to_dict(),
            "assumptions": {
                "risk_free_rate": self.risk_free_rate,
                "costs": {"fixed": self.costs.fixed, "rate": self.costs.rate},
                "dividend_treatment": _DIVIDEND_TREATMENT,
            },
            "warnings": list(self.warnings),
            "biases": list(BIAS_DISCLOSURE),
            "provenance": {
                "series_hash": self.series_hash,
                "last_ingested_at": self.last_ingested_at,
            },
            # RF-CON-02 (v0.9) — CA-02.2: a partir deste bloco sozinho,
            # somado a `assumptions` acima, dá para reconstruir a
            # configuração completa do run sem o nome do arquivo nem
            # `backtest_runs`.
            "run": {
                "strategy": {"name": self.strategy_name, "params": dict(self.strategy_params)},
                "initial_capital": self.initial_cash,
                "bars_consumed": self.bars_consumed,
                "effective_start": self.effective_start,
                "effective_end": self.effective_end,
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = [
            f"Backtest — {self.ticker}",
            f"  estratégia: {self.strategy_name} {self.strategy_params}",
            f"  capital inicial: {self.initial_cash:,.2f}",
            f"  barras consumidas: {self.bars_consumed} "
            f"({self.effective_start} a {self.effective_end})",
            "",
            "Métricas                 estratégia        benchmark",
            f"  retorno acumulado      {self.strategy.cumulative_return:>14.2%}  "
            f"{self.benchmark.cumulative_return:>14.2%}",
            f"  CAGR                   {self.strategy.cagr:>14.2%}  {self.benchmark.cagr:>14.2%}",
            f"  Sharpe                 {_format_optional(self.strategy.sharpe):>14}  "
            f"{_format_optional(self.benchmark.sharpe):>14}",
            f"  max drawdown           {self.strategy.max_drawdown.magnitude:>14.2%}  "
            f"{self.benchmark.max_drawdown.magnitude:>14.2%}",
            f"  trades                 {self.strategy.num_trades:>14d}  "
            f"{self.benchmark.num_trades:>14d}",
            f"  taxa de acerto         {_format_optional(self.strategy.hit_rate, pct=True):>14}  "
            f"{_format_optional(self.benchmark.hit_rate, pct=True):>14}",
            "",
            "Premissas:",
            f"  taxa livre de risco: {self.risk_free_rate:.2%}",
            f"  custos: fixo={self.costs.fixed}, taxa={self.costs.rate}",
            f"  dividendo: {_DIVIDEND_TREATMENT}",
        ]
        if self.warnings:
            lines.append("")
            lines.append("Avisos:")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        lines.append("")
        lines.append("Vieses conhecidos:")
        lines.extend(f"  {index}. {bias}" for index, bias in enumerate(BIAS_DISCLOSURE, start=1))
        lines.append("")
        lines.append(f"Proveniência: hash={self.series_hash}, ingestão={self.last_ingested_at}")
        return "\n".join(lines)


def _format_optional(value: float | None, *, pct: bool = False) -> str:
    if value is None:
        return "indefinido"
    return f"{value:.2%}" if pct else f"{value:.4f}"


def _summarize_multi(result: BacktestResultMulti, rf: float) -> MetricsSummary:
    """Mesmas métricas da Fase 1 sobre o resultado multi (T16).

    A equity curve multi é `list[float]` alinhada a `dates` (uma amostra por
    data-união) — aqui montada na `pd.Series` que as métricas da Fase 1
    consomem. Mesma definição para estratégia e benchmark (MET-04.2).
    """

    equity = pd.Series(result.equity_curve, index=list(result.dates))
    returns = daily_returns(equity)
    return MetricsSummary(
        cumulative_return=(result.equity_curve[-1] / result.initial_cash) - 1.0,
        cagr=cagr(equity),
        sharpe=_sharpe(returns, rf=rf),
        max_drawdown=max_drawdown(equity),
        num_trades=len(result.portfolio.trades),
        hit_rate=hit_rate(result.portfolio.trades),
    )


@dataclass(frozen=True, slots=True)
class BacktestReportMulti:
    """O relatório do run multi-ativo — design §7 (Fase 2a, T16).

    Mesmo espírito do `BacktestReport` da Fase 1, agora sobre o
    `BacktestResultMulti`: métricas lado a lado (estratégia x benchmark 1/N),
    bloco "contadores de mecanismo" (MET-05/P6 — agregado no engine, aqui só
    reportado), seção "run" ampliada com o universo e a configuração
    (RF-CON-02/CA-02.2 — reconstruível do JSON isolado), caixa ocioso e
    nunca-negociados (SIZ-02.2/R2) e a seção fixa de vieses ampliada
    (MET-03.1). Construído com `build()`, como o da Fase 1.
    """

    n: int
    tickers: tuple[str, ...]
    strategy: MetricsSummary
    benchmark: MetricsSummary
    risk_free_rate: float
    costs: CostModel
    slippage: SlippageModel
    cap: float
    initial_cash: float
    n_bars: int
    effective_start: str
    effective_end: str
    counters: MechanismCounters
    pending_dead: dict[str, int]
    delisted: tuple[str, ...]
    idle_cash: float
    never_traded: tuple[str, ...]
    insufficient_sample: bool
    strategy_name: str = ""
    strategy_params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        strategy: BacktestResultMulti,
        benchmark: BacktestResultMulti,
        strategy_name: str,
        strategy_params: dict[str, Any],
        rf: float = 0.0,
    ) -> "BacktestReportMulti":
        """CA-02.1/02.2 — métricas lado a lado + configuração reconstruível.

        Exige o MESMO `N` para estratégia e benchmark (P3) — comparar carteiras
        de tamanhos diferentes mediria coisas diferentes. `n_bars` e as datas
        efetivas vêm do calendário-união (um ponto de equity por data-união).
        `never_traded` = ativos do run sem nenhum trade (R2 — contribuem zero).
        """
        if not strategy.equity_curve:
            raise ValueError("BacktestResultMulti sem equity curve: nada para reportar.")
        if strategy.n != benchmark.n:
            raise EngineError(
                f"Relatório multi exige o MESMO N (P3): estratégia {strategy.n} vs "
                f"benchmark {benchmark.n}."
            )
        traded = {trade.ticker for trade in strategy.portfolio.trades}
        never_traded = tuple(sorted(t for t in strategy.tickers if t not in traded))
        return cls(
            n=strategy.n,
            tickers=strategy.tickers,
            strategy=_summarize_multi(strategy, rf),
            benchmark=_summarize_multi(benchmark, rf),
            risk_free_rate=rf,
            costs=strategy.costs,
            slippage=strategy.slippage,
            cap=strategy.cap,
            initial_cash=strategy.initial_cash,
            n_bars=len(strategy.dates),
            effective_start=strategy.dates[0].isoformat(),
            effective_end=strategy.dates[-1].isoformat(),
            counters=strategy.counters,
            pending_dead=dict(strategy.pending_dead),
            delisted=strategy.delisted,
            idle_cash=strategy.portfolio.cash,
            never_traded=never_traded,
            insufficient_sample=len(strategy.equity_curve) < _MIN_SAMPLE_SIZE,
            strategy_name=strategy_name,
            strategy_params=dict(strategy_params),
        )

    @property
    def warnings(self) -> tuple[str, ...]:
        """Avisos condicionais — amostra curta, custos zero (ENG-03.2) e
        slippage zero (SLP-01.3). A seção fixa de vieses aparece sempre."""
        items: list[str] = []
        if self.insufficient_sample:
            items.append(
                f"Amostra insuficiente (< {_MIN_SAMPLE_SIZE} barras de equity) para "
                "inferência estatística confiável."
            )
        if self.costs.is_zero:
            items.append("Custos de transação configurados como zero — resultados irrealistas.")
        if getattr(self.slippage, "bps", None) == 0:
            items.append("Slippage configurado como zero — resultados irrealistas (SLP-01.3).")
        return tuple(items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "universe": {
                "n": self.n,
                "tickers": list(self.tickers),
                "never_traded": list(self.never_traded),
                "delisted": list(self.delisted),
            },
            "strategy": self.strategy.to_dict(),
            "benchmark": self.benchmark.to_dict(),
            "assumptions": {
                "risk_free_rate": self.risk_free_rate,
                "costs": {
                    "fixed": self.costs.fixed,
                    "rate": self.costs.rate,
                    "min_cost": self.costs.min_cost,
                },
                "slippage": str(self.slippage),
                "participation_cap": self.cap,
                "dividend_treatment": _DIVIDEND_TREATMENT,
            },
            "mechanism_counters": self.counters.to_dict(),
            "warnings": list(self.warnings),
            "biases": list(BIAS_DISCLOSURE_MULTI),
            # RF-CON-02 (CA-02.2) — a partir deste bloco + `assumptions`,
            # o run é reconstruível do JSON sozinho, sem o nome do arquivo.
            "run": {
                "strategy": {"name": self.strategy_name, "params": dict(self.strategy_params)},
                "initial_capital": self.initial_cash,
                "n_bars": self.n_bars,
                "effective_start": self.effective_start,
                "effective_end": self.effective_end,
                "idle_cash": self.idle_cash,
                "pending_dead": dict(self.pending_dead),
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = [
            f"Backtest multi-ativo — {self.n} ativos ({', '.join(self.tickers)})",
            f"  estratégia: {self.strategy_name} {self.strategy_params}",
            f"  capital inicial: {self.initial_cash:,.2f}",
            f"  barras consumidas: {self.n_bars} ({self.effective_start} a {self.effective_end})",
            f"  caixa ocioso final: {self.idle_cash:,.2f}",
            f"  nunca negociados: {', '.join(self.never_traded) or '-'}",
            f"  deslistados (travados): {', '.join(self.delisted) or '-'}",
            "",
            "Métricas                 estratégia        benchmark",
            f"  retorno acumulado      {self.strategy.cumulative_return:>14.2%}  "
            f"{self.benchmark.cumulative_return:>14.2%}",
            f"  CAGR                   {self.strategy.cagr:>14.2%}  {self.benchmark.cagr:>14.2%}",
            f"  Sharpe                 {_format_optional(self.strategy.sharpe):>14}  "
            f"{_format_optional(self.benchmark.sharpe):>14}",
            f"  max drawdown           {self.strategy.max_drawdown.magnitude:>14.2%}  "
            f"{self.benchmark.max_drawdown.magnitude:>14.2%}",
            f"  trades                 {self.strategy.num_trades:>14d}  "
            f"{self.benchmark.num_trades:>14d}",
            f"  taxa de acerto         {_format_optional(self.strategy.hit_rate, pct=True):>14}  "
            f"{_format_optional(self.benchmark.hit_rate, pct=True):>14}",
            "",
            "Contadores de mecanismo:",
            f"  stops disparados: {self.counters.stops_triggered}",
            f"  ambiguidades intrabarra: {self.counters.intrabar_ambiguities}",
            f"  ordens não atendidas por caixa: {self.counters.unfilled_cash_orders}",
            "",
            "Premissas:",
            f"  taxa livre de risco: {self.risk_free_rate:.2%}",
            f"  custos: fixo={self.costs.fixed}, taxa={self.costs.rate}, "
            f"mínimo={self.costs.min_cost}",
            f"  slippage: {self.slippage}",
            f"  cap de participação: {self.cap:.0%}",
            f"  dividendo: {_DIVIDEND_TREATMENT}",
        ]
        if self.warnings:
            lines.append("")
            lines.append("Avisos:")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        lines.append("")
        lines.append("Vieses conhecidos:")
        lines.extend(
            f"  {index}. {bias}" for index, bias in enumerate(BIAS_DISCLOSURE_MULTI, start=1)
        )
        return "\n".join(lines)
