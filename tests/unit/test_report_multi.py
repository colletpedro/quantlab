"""T16 — relatório multi-ativo (RF-MET-03/05, RF-CON-02, design §7).

Run de papel com os TRÊS contadores de mecanismo acendendo (MET-05):
A — bracket de entrada AMBÍGUO (limite 10.5 + stop 9.5, low 9.0 toca os dois:
   abre em L, fecha em S na mesma barra — stop disparado + 1 ambiguidade);
B — bracket de entrada normal (limite toca em 9.7, stop 9.5 dispara na barra
   seguinte: 1 stop, 0 ambiguidade);
C — entrada a mercado convertida (ref 10) que NA EXECUÇÃO explode para
   open 100_000: nem 1 ação cabe no caixa compartilhado — 1 não-atendida.

O relatório NÃO conta nada: reporta o `MechanismCounters` que o engine
agregou (design §3.8 — "contagens incrementadas apenas pelo engine").
Fixtures de papel com derivação auditável (RNF-03); benchmark 1/N no mesmo
universo/N (P3).
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.analytics.benchmark import buy_and_hold_multi
from quantlab.analytics.report import BacktestReportMulti
from quantlab.engine.backtest import run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.conditional import Bracket, ConditionalIntent, OrderKind
from quantlab.engine.market_view import MarketView
from quantlab.engine.slippage import FixedBps
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries

_FREE = CostModel(fixed=0.0, rate=0.0)
_NO_SLIP = FixedBps(bps=0.0)
_D0 = date(2024, 1, 1)


def _series(prices: list[float], *, ticker: str) -> PriceSeries:
    """Série de papel: open = close = high = low = `prices` (RNF-03)."""
    dates = [_D0 + timedelta(days=i) for i in range(len(prices))]
    date_array: NDArray[np.object_] = np.empty(len(dates), dtype=object)
    date_array[:] = dates
    values = np.array(prices, dtype=np.float64)
    return PriceSeries(
        ticker=ticker,
        dates=date_array,
        open=values,
        high=values,
        low=values,
        close=values,
        volume=np.array([1_000.0] * len(prices)),
        adjusted=True,
        hash="0" * 64,
    )


@dataclass
class PaperCond:
    """Estratégia de papel que emite por índice: `Signal` ou `ConditionalIntent`
    (bracket na mesma intenção — SIG-01.2)."""

    script: dict[int, Signal | ConditionalIntent]
    warmup: int = 0

    def on_bar(self, view: MarketView) -> Signal | ConditionalIntent | None:
        return self.script.get(view.i)


def _run_with_counters() -> BacktestReportMulti:
    """Run de 3 ativos que acende os três contadores (ver docstring do módulo)."""
    series = {
        "A": _series([10.0, 9.0], ticker="A"),  # ambiguidade do bracket de entrada
        "B": _series([10.0, 9.7, 9.0], ticker="B"),  # entrada normal + stop na 2ª barra
        "C": _series([10.0, 100_000.0], ticker="C"),  # não-atendida por caixa
    }
    strategies = {
        "A": PaperCond(
            {
                0: ConditionalIntent(
                    Signal.ENTER,
                    OrderKind.LIMIT,
                    limit=10.5,
                    bracket=Bracket(limit=10.5, stop=9.5),
                )
            }
        ),
        "B": PaperCond(
            {
                0: ConditionalIntent(
                    Signal.ENTER,
                    OrderKind.LIMIT,
                    limit=9.8,
                    bracket=Bracket(limit=9.8, stop=9.5),
                )
            }
        ),
        "C": PaperCond({0: Signal.ENTER}),
    }
    run = run_backtest_multi(
        series,
        strategies,
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
    )
    benchmark = buy_and_hold_multi(
        series, n=3, initial_cash=100_000.0, costs=_FREE, slippage=_NO_SLIP, cap=0.10
    )
    return BacktestReportMulti.build(
        strategy=run, benchmark=benchmark, strategy_name="paper", strategy_params={}
    )


# ─── MET-05: contadores de mecanismo ─────────────────────────────────────────


@pytest.mark.unit
def test_report_mechanism_counters_block() -> None:
    """CA-05.1/05.2/05.3 — o bloco reporta as três categorias com as contagens
    que o ENGINE agregou (o relatório não conta nada por conta própria)."""
    report = _run_with_counters()

    assert report.counters.stops_triggered == 2  # A (bracket ambíguo) + B (stop na 2ª barra)
    assert report.counters.intrabar_ambiguities == 1  # A
    assert report.counters.unfilled_cash_orders == 1  # C

    block = report.to_dict()["mechanism_counters"]
    assert block == {
        "stops_triggered": 2,
        "intrabar_ambiguities": 1,
        "unfilled_cash_orders": 1,
        "borrow_rejections": 0,  # 2b (T03) — novo contador, zero sem shorts
    }


# ─── MET-03.1: vieses ampliados (constante literal) ──────────────────────────


@pytest.mark.unit
def test_bias_section_includes_conditional_items() -> None:
    """CA-03.1 — a seção fixa contém os 5 itens novos do RF-MET-03, sempre
    (nenhum caminho do `build` omite o bloco)."""
    report = _run_with_counters()

    biases = "\n".join(report.to_dict()["biases"])
    assert "Ambiguidade intrabarra resolvida por pior caso" in biases
    assert "Slippage modelado mas não calibrado" in biases
    assert "Sem impacto permanente de mercado" in biases
    assert "Fill integral ao preço limite é otimista" in biases
    assert "qualquer regra de atendimento é seleção com viés" in biases
    # Itens da Fase 1 preservados (regressão da seção fixa).
    assert "Survivorship bias" in biases


# ─── RF-CON-02: seção run reconstruível do JSON ──────────────────────────────


@pytest.mark.unit
def test_full_run_configuration_is_reconstructible_from_the_json_alone() -> None:
    """CA-02.2 (multi-ativo) — universo, capital, custos/slippage/cap,
    n_barras e datas efetivas no JSON; reconstruível sem o nome do arquivo."""
    report = _run_with_counters()
    payload = report.to_dict()

    assert payload["universe"] == {
        "n": 3,
        "tickers": ["A", "B", "C"],
        # C converteu mas NÃO preencheu (caixa na execução) — nunca negociou (R2).
        "never_traded": ["C"],
        "delisted": [],
    }
    run_block = payload["run"]
    assert run_block["initial_capital"] == 100_000.0
    assert run_block["n_bars"] == 3  # união d0..d2
    assert run_block["effective_start"] == _D0.isoformat()
    assert run_block["effective_end"] == (_D0 + timedelta(days=2)).isoformat()
    assert run_block["pending_dead"] == {"A": 0, "B": 0, "C": 0}
    assumptions = payload["assumptions"]
    assert assumptions["costs"] == {"fixed": 0.0, "rate": 0.0, "min_cost": 0.0}
    assert assumptions["participation_cap"] == 0.10
    assert "slippage" in assumptions  # str(FixedBps(bps=0.0)) — determinístico

    # Estratégia e benchmark lado a lado (CA-02.1), mesmas definições.
    assert set(payload["strategy"]) == set(payload["benchmark"])


# ─── SIZ-02.2/R2: caixa ocioso e nunca-negociados ────────────────────────────


@pytest.mark.unit
def test_idle_cash_and_never_traded_reported() -> None:
    """Caixa ocioso reportado (SIZ-02.2) e ativo do run nunca-negociado
    reportado com contribuição zero (R2)."""
    series = {
        "A": _series([10.0] * 4, ticker="A"),
        "B": _series([20.0] * 4, ticker="B"),
        "C": _series([], ticker="C"),  # nunca-negociado: série vazia (R2)
    }
    run = run_backtest_multi(
        series,
        {"A": PaperCond({0: Signal.ENTER}), "B": PaperCond({0: Signal.ENTER})},
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
    )
    benchmark = buy_and_hold_multi(
        series, n=3, initial_cash=100_000.0, costs=_FREE, slippage=_NO_SLIP, cap=0.10
    )
    report = BacktestReportMulti.build(
        strategy=run, benchmark=benchmark, strategy_name="paper", strategy_params={}
    )

    assert report.idle_cash > 0  # 1/N por ativo deixou o resto parado
    assert report.never_traded == ("C",)
    assert report.to_dict()["universe"]["never_traded"] == ["C"]


# ─── SLP-01.3: slippage/custo zero ⇒ irrealismo ──────────────────────────────


@pytest.mark.unit
def test_zero_slippage_warns_unrealistic() -> None:
    """SLP-01.3 — slippage zerado sinaliza irrealismo (aviso condicional)."""
    report = _run_with_counters()

    assert any("Slippage configurado como zero" in w for w in report.warnings)
    assert any("resultados irrealistas" in w for w in report.warnings)


# ─── P3 / determinismo ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_multi_report_requires_same_n() -> None:
    """P3 — estratégia e benchmark com N diferente é erro de programação.

    Como ambos derivam o N do mesmo dict, a divergência é um erro de programa
    — simulada com `replace` (não é um estado alcançável pelo pipeline).
    """
    series = {"A": _series([10.0] * 4, ticker="A")}
    run = run_backtest_multi(
        series, {"A": PaperCond({0: Signal.ENTER})}, initial_cash=100_000.0, costs=_FREE
    )
    benchmark = buy_and_hold_multi(series, n=1, initial_cash=100_000.0, costs=_FREE)
    bogus_benchmark = replace(benchmark, n=2)

    with pytest.raises(EngineError):
        BacktestReportMulti.build(
            strategy=run, benchmark=bogus_benchmark, strategy_name="paper", strategy_params={}
        )


@pytest.mark.unit
def test_multi_report_is_deterministic() -> None:
    """RNF-01 — mesmos runs, mesmos dicionários serializados."""
    r1 = _run_with_counters()
    r2 = _run_with_counters()

    assert r1.to_dict() == r2.to_dict()


@pytest.mark.unit
def test_multi_report_to_text_includes_counters_and_universe() -> None:
    """A saída de texto leva o mesmo dado do JSON: universo, contadores e
    premissas (a mesma informação, dois formatos — Fase 1 §5.2)."""
    text = _run_with_counters().to_text()

    assert "Backtest multi-ativo — 3 ativos (A, B, C)" in text
    assert "stops disparados: 2" in text
    assert "ambiguidades intrabarra: 1" in text
    assert "ordens não atendidas por caixa: 1" in text
    assert "cap de participação: 10%" in text
    assert "Vieses conhecidos:" in text
