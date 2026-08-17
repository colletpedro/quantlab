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

from quantlab.analytics.metrics import (
    DrawdownResult,
    cagr,
    daily_returns,
    gross_exposure_avg,
    hit_rate,
    margin_utilization_avg,
    max_drawdown,
    net_exposure_avg,
    turnover_annualized,
)
from quantlab.analytics.metrics import sharpe as _sharpe
from quantlab.engine.backtest import BacktestResult, BacktestResultMulti
from quantlab.engine.broker import CostModel, MechanismCounters
from quantlab.engine.slippage import SlippageModel
from quantlab.engine.walkforward import Fold, WalkForwardResult
from quantlab.exceptions import EngineError

__all__ = [
    "BIAS_DISCLOSURE",
    "BIAS_DISCLOSURE_2B",
    "BIAS_DISCLOSURE_MULTI",
    "BacktestReport",
    "BacktestReportMulti",
    "FoldRow",
    "MetricsSummary",
    "WalkForwardReport",
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

#: CA-06.1 (RF-MET-06, R1/R5) — a seção fixa de vieses do relatório 2b: itens da
#: 2a preservados + os itens novos da 2b. Constante literal, como na Fase 1 §5.2 —
#: nenhum caminho do `BacktestReportMulti.build` nem do `WalkForwardReport.build`
#: omite este bloco. Conteúdo idêntico a design §7/RF-MET-06: aluguel NÃO
#: calibrado (0,50% a.a. é premissa); disponibilidade de aluguel ILIMITADA (sem
#: hard-to-borrow — otimista); liquidação alfabética é seleção com viés; MHT com
#: métrica/grid/folds declarados; pior caso ampliado aos brackets com buy-stop.
BIAS_DISCLOSURE_2B: tuple[str, ...] = (
    *BIAS_DISCLOSURE_MULTI,
    "Custo de aluguel não calibrado — o default de 0,50% a.a. é premissa, não medida.",
    "Disponibilidade de aluguel ilimitada — sem hard-to-borrow; otimista para "
    "estratégias que dependem de short.",
    "Liquidação forçada alfabética é determinística, mas qualquer regra de seleção "
    "é seleção com viés (mesmo argumento do atendimento alfabético da 2a).",
    "MHT — a seleção de parâmetros in-sample é otimista: métrica de seleção "
    "(Sharpe anualizado, rf=0), tamanho da grade e nº de folds declarados.",
    "Pior caso intrabarra ampliado aos brackets com buy-stop.",
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

    #: 2b (T12, R6/MRG-03 CA-03.2): `cumulative_return`/`cagr` são `None` explícito
    #: quando o fundo quebrou (equity negativa — métricas de retorno indefinidas,
    #: nunca NaN); num run normal são sempre floats (regressão 2a intacta).
    cumulative_return: float | None
    cagr: float | None
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
            f"  retorno acumulado      {_cell(self.strategy.cumulative_return, pct=True)}  "
            f"{_cell(self.benchmark.cumulative_return, pct=True)}",
            f"  CAGR                   {_cell(self.strategy.cagr, pct=True)}  "
            f"{_cell(self.benchmark.cagr, pct=True)}",
            f"  Sharpe                 {_cell(self.strategy.sharpe)}  "
            f"{_cell(self.benchmark.sharpe)}",
            f"  max drawdown           {self.strategy.max_drawdown.magnitude:>14.2%}  "
            f"{self.benchmark.max_drawdown.magnitude:>14.2%}",
            f"  trades                 {self.strategy.num_trades:>14d}  "
            f"{self.benchmark.num_trades:>14d}",
            f"  taxa de acerto         {_cell(self.strategy.hit_rate, pct=True)}  "
            f"{_cell(self.benchmark.hit_rate, pct=True)}",
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


def _cell(value: float | None, *, pct: bool = False) -> str:
    """Célula de métrica justificada a 14 colunas — `None` vira "indefinido"
    (R6) e o valor é alinhado como antes da 2b (regressão do texto intacta)."""
    return f"{_format_optional(value, pct=pct):>14}"


def _alavancagem(
    result: BacktestResultMulti,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Turnover + exposições + utilização de margem do run (CA-04.2/CA-01.4).

    Computadas das séries DIÁRIAS que o laço agregou (dono §3.7 — emenda T12):
    `daily_gross_notional`/`daily_net_notional`/`daily_requirement` alinhadas a
    `equity_curve`. Fundo quebrado (equity ≤ 0 em algum dia, ou run congelado)
    ⇒ todos `None` explícito (R6 — métricas que assumem equity positiva nunca
    viram NaN nem média parcial fabricada).
    """
    if result.broken_fund or any(e <= 0 for e in result.equity_curve):
        return None, None, None, None
    equity_daily = pd.Series(result.equity_curve)
    turnover = turnover_annualized(result.portfolio.trades, equity_daily, len(equity_daily))
    gross = gross_exposure_avg(list(result.daily_gross_notional), result.equity_curve)
    net = net_exposure_avg(list(result.daily_net_notional), result.equity_curve)
    margin_util = margin_utilization_avg(list(result.daily_requirement), result.equity_curve)
    return turnover, gross, net, margin_util


def _summarize_multi(result: BacktestResultMulti, rf: float) -> MetricsSummary:
    """Mesmas métricas da Fase 1 sobre o resultado multi (T16).

    A equity curve multi é `list[float]` alinhada a `dates` (uma amostra por
    data-união) — aqui montada na `pd.Series` que as métricas da Fase 1
    consomem. Mesma definição para estratégia e benchmark (MET-04.2).

    2b (T12, MRG-03 CA-03.2/R6): fundo quebrado ⇒ `cumulative_return`/`cagr`/
    `sharpe` = `None` explícito — a equity negativa real não vira retorno
    fabricado nem NaN; `num_trades`/`hit_rate`/`max_drawdown` continuam sendo
    fatos do run (o drawdown da equity real é computável; o relatório ainda
    carrega a flag `broken_fund` e a exclusão de comparação — CA-03.3).
    """

    equity = pd.Series(result.equity_curve, index=list(result.dates))
    if result.broken_fund:
        return MetricsSummary(
            cumulative_return=None,
            cagr=None,
            sharpe=None,
            max_drawdown=max_drawdown(equity),
            num_trades=len(result.portfolio.trades),
            hit_rate=hit_rate(result.portfolio.trades),
        )
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
    # ─── 2b (T12) ─────────────────────────────────────────────────────────────
    #: MRG-03 CA-03.1/03.2 — flag de fundo quebrado + métricas de retorno None.
    broken_fund: bool = False
    #: MRG-03 CA-03.3 — fundo quebrado EXCLUI a comparação automática com o
    #: benchmark (a leitura exige decisão de quem lê; flag declarada).
    comparison_excluded: bool = False
    #: SHT-03 CA-03.3 — borrow fee em categoria própria (nunca dentro de custos).
    borrow_fees: float = 0.0
    #: SHT-05 CA-05.2 — shorts TRAVADOS (série terminou, posição qty < 0)
    #: reportados com categoria própria; longs travados ficam só em `delisted`.
    locked_shorts: tuple[str, ...] = ()
    #: MRG-04 CA-04.2/MRG-01 CA-01.4 — alavancagem: None explícito no fundo
    #: quebrado (R6, métricas que assumem equity positiva).
    turnover: float | None = None
    gross_exposure: float | None = None
    net_exposure: float | None = None
    margin_utilization: float | None = None
    #: MET-05 CA-05.1 — comparação long+short x long-only da PRÓPRIA estratégia
    #: (quem fornece o run long-only é quem chama; o relatório só reporta).
    strategy_long_only: MetricsSummary | None = None
    #: CA-06.2 (RF-CON-02) — config de margem/aluguel do run, reconstruível do
    #: JSON isolado; defaults idênticos aos dos modelos (regressão 2a).
    margin_factor: float = 1.0
    borrow_fee_annual: float = 0.005
    borrow_unlimited: bool = True

    @classmethod
    def build(
        cls,
        *,
        strategy: BacktestResultMulti,
        benchmark: BacktestResultMulti,
        strategy_name: str,
        strategy_params: dict[str, Any],
        rf: float = 0.0,
        strategy_long_only: BacktestResultMulti | None = None,
    ) -> "BacktestReportMulti":
        """CA-02.1/02.2 — métricas lado a lado + configuração reconstruível.

        Exige o MESMO `N` para estratégia e benchmark (P3) — comparar carteiras
        de tamanhos diferentes mediria coisas diferentes. `n_bars` e as datas
        efetivas vêm do calendário-união (um ponto de equity por data-união).
        `never_traded` = ativos do run sem nenhum trade (R2 — contribuem zero).

        2b (T12): `strategy_long_only` opcional (CA-05.1) — o run long-only da
        MESMA estratégia (mesma configuração, sinais de short descartados),
        produzido por quem chama; quando ausente, a seção de comparação não
        existe (regressão 2a). Alavancagem (CA-04.2/CA-01.4) computada das
        séries DIÁRIAS agregadas pelo laço (dono §3.7); fundo quebrado ⇒ None.
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
        turnover, gross, net, margin_util = _alavancagem(strategy)
        locked_shorts = tuple(
            sorted(
                t
                for t in strategy.delisted
                if t in strategy.portfolio.positions
                and strategy.portfolio.positions[t].quantity < 0
            )
        )
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
            broken_fund=strategy.broken_fund,
            comparison_excluded=strategy.broken_fund,
            borrow_fees=strategy.borrow_fees,
            locked_shorts=locked_shorts,
            turnover=turnover,
            gross_exposure=gross,
            net_exposure=net,
            margin_utilization=margin_util,
            strategy_long_only=(
                _summarize_multi(strategy_long_only, rf) if strategy_long_only is not None else None
            ),
            margin_factor=strategy.margin.factor,
            borrow_fee_annual=strategy.borrow.fee_annual,
            borrow_unlimited=strategy.borrow.unlimited,
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
        payload = {
            "universe": {
                "n": self.n,
                "tickers": list(self.tickers),
                "never_traded": list(self.never_traded),
                "delisted": list(self.delisted),
                # 2b (CA-05.2) — shorts travados com categoria própria.
                "locked_shorts": list(self.locked_shorts),
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
                # 2b (T12, CA-06.2) — config de margem/aluguel, reconstruível.
                "margin": {"factor": self.margin_factor},
                "borrow": {
                    "fee_annual": self.borrow_fee_annual,
                    "unlimited": self.borrow_unlimited,
                },
            },
            "mechanism_counters": self.counters.to_dict(),
            # 2b (CA-03.3) — borrow fee em categoria própria (nunca em custos).
            "borrow_fees": self.borrow_fees,
            # 2b (CA-03.2/03.3) — fundo quebrado: flag + exclusão de comparação.
            "broken_fund": self.broken_fund,
            "comparison_excluded": self.comparison_excluded,
            # 2b (CA-04.2/CA-01.4) — alavancagem: None explícito no fundo quebrado.
            "alavancagem": {
                "turnover_annualized": self.turnover,
                "gross_exposure_avg": self.gross_exposure,
                "net_exposure_avg": self.net_exposure,
                "margin_utilization_avg": self.margin_utilization,
            },
            "warnings": list(self.warnings),
            "biases": list(BIAS_DISCLOSURE_2B),
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
        # 2b (CA-05.1) — comparação long+short x long-only da própria estratégia,
        # presente sse o caller forneceu o run long-only (regressão 2a: ausente).
        if self.strategy_long_only is not None:
            payload["long_only_comparison"] = {
                "long_short": self.strategy.to_dict(),
                "own_long_only": self.strategy_long_only.to_dict(),
            }
        return payload

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
            f"  retorno acumulado      {_cell(self.strategy.cumulative_return, pct=True)}  "
            f"{_cell(self.benchmark.cumulative_return, pct=True)}",
            f"  CAGR                   {_cell(self.strategy.cagr, pct=True)}  "
            f"{_cell(self.benchmark.cagr, pct=True)}",
            f"  Sharpe                 {_cell(self.strategy.sharpe)}  "
            f"{_cell(self.benchmark.sharpe)}",
            f"  max drawdown           {self.strategy.max_drawdown.magnitude:>14.2%}  "
            f"{self.benchmark.max_drawdown.magnitude:>14.2%}",
            f"  trades                 {self.strategy.num_trades:>14d}  "
            f"{self.benchmark.num_trades:>14d}",
            f"  taxa de acerto         {_cell(self.strategy.hit_rate, pct=True)}  "
            f"{_cell(self.benchmark.hit_rate, pct=True)}",
            "",
            "Contadores de mecanismo:",
            f"  stops disparados: {self.counters.stops_triggered}",
            f"  ambiguidades intrabarra: {self.counters.intrabar_ambiguities}",
            f"  ordens não atendidas por caixa: {self.counters.unfilled_cash_orders}",
            f"  liquidações por margem: {self.counters.margin_calls}",
            f"  shorts bloqueados por indisponibilidade: {self.counters.borrow_rejections}",
            "",
            "2b:",
            f"  borrow fees pagos: {self.borrow_fees:,.2f}",
            f"  shorts travados (deslistagem): {', '.join(self.locked_shorts) or '-'}",
            f"  fundo quebrado: {'sim' if self.broken_fund else 'não'}",
            (
                "  comparação com benchmark EXCLUÍDA (fundo quebrado)"
                if self.comparison_excluded
                else ""
            ),
            "",
            "Alavancagem:",
            f"  turnover anualizado: {_format_optional(self.turnover)}",
            f"  exposição gross média: {_format_optional(self.gross_exposure, pct=True)}",
            f"  exposição net média: {_format_optional(self.net_exposure, pct=True)}",
            f"  utilização de margem média: {_format_optional(self.margin_utilization, pct=True)}",
            "",
            "Premissas:",
            f"  taxa livre de risco: {self.risk_free_rate:.2%}",
            f"  custos: fixo={self.costs.fixed}, taxa={self.costs.rate}, "
            f"mínimo={self.costs.min_cost}",
            f"  slippage: {self.slippage}",
            f"  cap de participação: {self.cap:.0%}",
            f"  margem: fator={self.margin_factor}",
            f"  aluguel: fee anual={self.borrow_fee_annual:.2%}, "
            f"disponibilidade={'ilimitada' if self.borrow_unlimited else 'restrita'}",
            f"  dividendo: {_DIVIDEND_TREATMENT}",
        ]
        if self.warnings:
            lines.append("")
            lines.append("Avisos:")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        if self.strategy_long_only is not None:
            lines.append("")
            lines.append("Comparação long+short x long-only (própria estratégia):")
            lines.append(
                f"  retorno acumulado      "
                f"{_format_optional(self.strategy.cumulative_return, pct=True):>14}  "
                f"{_format_optional(self.strategy_long_only.cumulative_return, pct=True):>14}"
            )
            lines.append(
                f"  Sharpe                 "
                f"{_format_optional(self.strategy.sharpe):>14}  "
                f"{_format_optional(self.strategy_long_only.sharpe):>14}"
            )
        lines.append("")
        lines.append("Vieses conhecidos:")
        lines.extend(f"  {index}. {bias}" for index, bias in enumerate(BIAS_DISCLOSURE_2B, start=1))
        return "\n".join(lines)


# ─── 2b (T12): relatório do walk-forward — tabela fold a fold (CA-WFK-03.2) ──


@dataclass(frozen=True, slots=True)
class FoldRow:
    """Uma linha da tabela fold a fold do walk-forward — emenda T12, design §7.

    ``sharpe_is`` e ``ret_oos`` são `float | None` (R6 — fundo quebrado no IS
    ou OOS do fold ⇒ None explícito, nunca NaN); a renderização usa traço
    claro "—" (decisão com dono, registrada no tasks T12).
    """

    fold: Fold
    selected_params: dict[str, float]
    sharpe_is: float | None
    ret_oos: float | None


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    """Relatório do walk-forward — emenda T12, design §7 (CA-WFK-03.2).

    Renderiza o `WalkForwardResult`: a tabela fold a fold (janela IS/OOS,
    params selecionados, `sharpe_is`, `ret_oos`) + o bloco fixo de vieses 2b
    (CA-06.1) + os declarativos do MHT (`selection_metric`, `grid_size`,
    `n_folds` — CA-06.2). Construído com `build()`, como os demais.
    """

    selection_metric: str
    grid_size: int
    n_folds: int
    folds: tuple[FoldRow, ...]
    broken_fund: bool
    biases: tuple[str, ...] = BIAS_DISCLOSURE_2B

    @classmethod
    def build(cls, result: WalkForwardResult) -> "WalkForwardReport":
        """CA-WFK-03.2/CA-06.2 — do `WalkForwardResult` ao relatório.

        `selection_metric` é o literal "sharpe_annualized_rf0" (R5 — a métrica
        de seleção IS); `grid_size`/`n_folds` vêm do resultado (CA-06.2 — MHT
        declarado); `broken_fund` herda a flag (CA-03.3 — exclusão de
        comparação automática fica com quem lê, declarada aqui).
        """
        return cls(
            selection_metric="sharpe_annualized_rf0",
            grid_size=result.grid_size,
            n_folds=result.n_folds,
            folds=tuple(
                FoldRow(
                    fold=fr.fold,
                    selected_params=dict(fr.selected_params),
                    sharpe_is=fr.is_metrics.sharpe_is,
                    ret_oos=fr.oos_metrics.ret_oos,
                )
                for fr in result.folds
            ),
            broken_fund=result.broken_fund,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection_metric": self.selection_metric,
            "mht": {"grid_size": self.grid_size, "n_folds": self.n_folds},
            "broken_fund": self.broken_fund,
            "folds": [
                {
                    "fold": {
                        "is": {
                            "start": row.fold.is_start.isoformat(),
                            "end": row.fold.is_end.isoformat(),
                        },
                        "oos": {
                            "start": row.fold.oos_start.isoformat(),
                            "end": row.fold.oos_end.isoformat(),
                        },
                    },
                    "selected_params": dict(row.selected_params),
                    "sharpe_is": row.sharpe_is,
                    "ret_oos": row.ret_oos,
                }
                for row in self.folds
            ],
            "biases": list(self.biases),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = [
            "Walk-forward — tabela fold a fold",
            f"  seleção IS: {self.selection_metric} (MHT: grid_size={self.grid_size}, "
            f"n_folds={self.n_folds})",
            f"  fundo quebrado em algum fold: {'sim' if self.broken_fund else 'não'}",
            "",
            "  fold  janela IS            janela OOS            params            "
            "sharpe_is  ret_oos",
        ]
        for index, row in enumerate(self.folds, start=1):
            is_window = f"{row.fold.is_start.isoformat()}..{row.fold.is_end.isoformat()}"
            oos_window = f"{row.fold.oos_start.isoformat()}..{row.fold.oos_end.isoformat()}"
            params = ",".join(f"{k}={v:g}" for k, v in sorted(row.selected_params.items()))
            sharpe_cell = _format_optional(row.sharpe_is)
            ret_cell = _format_optional(row.ret_oos, pct=True)
            lines.append(
                f"  {index:>4d}  {is_window:<20}  {oos_window:<20}  {params:<18}  "
                f"{sharpe_cell:>9}  {ret_cell:>7}"
            )
        if self.broken_fund:
            lines.append("")
            lines.append(
                "Fundo quebrado em algum fold — comparação automática excluída "
                "(CA-03.3); leia a tabela com decisão própria."
            )
        lines.append("")
        lines.append("Vieses conhecidos:")
        lines.extend(f"  {index}. {bias}" for index, bias in enumerate(self.biases, start=1))
        return "\n".join(lines)
