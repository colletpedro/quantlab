"""T12 — relatório 2b (RF-MET-05/06, RF-MRG-03, RF-WFK-03, design §7).

Estende o `BacktestReportMulti` da 2a com o que a 2b acrescenta: o benchmark
continua sendo o MESMO 1/N long-only da 2a (CA-MET-05.1/05.2 — por
construção, o `buy_and_hold_multi` nunca shorta), a comparação long+short x
long-only da PRÓPRIA estratégia (CA-05.1 — o caller fornece o run long-only;
o relatório só reporta), a seção fixa de vieses 2b (CA-06.1), a seção "run"
com MHT declarado (CA-06.2), o fundo quebrado excluído da comparação
automática (CA-03.3), os shorts travados com categoria própria (CA-05.2) e a
tabela fold a fold do walk-forward (CA-WFK-03.2) com `None` renderizado como
traço claro "—" (R6 — decisão com dono, registrada no tasks T12).

Fixtures de papel com derivação auditável (RNF-03); o run long-only da
mesma estratégia é produzido pelo CALLER (quem chama), descartando os sinais
de short — nunca pelo relatório.
"""

from datetime import date, timedelta

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.analytics.benchmark import buy_and_hold_multi
from quantlab.analytics.report import BacktestReportMulti, WalkForwardReport
from quantlab.engine.backtest import BacktestResultMulti, run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.margin import BorrowFeeModel, MarginModel
from quantlab.engine.market_view import MarketView
from quantlab.engine.sizing import FixedOneOverN, SizingInputs
from quantlab.engine.slippage import FixedBps
from quantlab.engine.strategy import Signal
from quantlab.engine.walkforward import (
    Fold,
    FoldMetrics,
    FoldResult,
    ParameterGrid,
    WalkForwardResult,
    build_folds,
    run_walkforward,
)
from quantlab.storage.series import PriceSeries

_FREE = CostModel(fixed=0.0, rate=0.0)
_NO_SLIP = FixedBps(bps=0.0)
_D0 = date(2024, 1, 1)


def _dates(n: int, start: date = _D0) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def _series(prices: list[float], *, ticker: str, start: date = _D0) -> PriceSeries:
    """Série de papel: open = close = high = low = `prices` (RNF-03)."""
    bar_dates = _dates(len(prices), start=start)
    date_array: NDArray[np.object_] = np.empty(len(bar_dates), dtype=object)
    date_array[:] = bar_dates
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


class _FixedFractionSizer:
    """Sizer de teste: fração fixa por ativo (SIZ-04.2), como o 2a faz no
    test_backtest — controla o notional sem depender de preço."""

    fraction: float

    def __init__(self, fraction: float) -> None:
        self.fraction = fraction

    def target_fraction(self, ticker: str, inputs: SizingInputs) -> float:
        return self.fraction


class _Paper:
    """Estratégia de papel que emite por índice (Signal), como a 2a."""

    script: dict[int, Signal]
    warmup: int = 0

    def __init__(self, script: dict[int, Signal], warmup: int = 0) -> None:
        self.script = script
        self.warmup = warmup

    def on_bar(self, view: MarketView) -> Signal | None:
        return self.script.get(view.i)


def _long_short_run_and_benchmark(
    *, sizer: _FixedFractionSizer | None = None, fee_annual: float = 0.005
) -> tuple[BacktestResultMulti, BacktestResultMulti, dict[str, PriceSeries]]:
    """Run long+short de 2 ativos com margem + o benchmark 1/N do mesmo N.

    A: long all-in (ENTER na barra 0, execução ao open da 1); B: short
    all-in (ENTER_SHORT na barra 0, cobertura ao open da 1) — a 2b abre e
    fecha no MESMO dia de execução, então o run termina flat com a equity
    derivável à mão. `sizer` default FixedFractionSizer(0.9) — 90% da equity
    em cada perna (alavancado com margem factor 2.0).
    """
    series = {
        "A": _series([10.0, 10.0, 11.0, 11.0], ticker="A"),
        "B": _series([10.0, 10.0, 9.0, 9.0], ticker="B"),
    }
    strategies = {
        "A": _Paper({0: Signal.ENTER}),
        "B": _Paper({0: Signal.ENTER_SHORT}),
    }
    run = run_backtest_multi(
        series,
        strategies,
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
        sizer=sizer or _FixedFractionSizer(0.9),
        margin=MarginModel(factor=2.0),
        borrow=BorrowFeeModel(fee_annual=fee_annual),
    )
    benchmark = buy_and_hold_multi(
        series, n=2, initial_cash=100_000.0, costs=_FREE, slippage=_NO_SLIP, cap=0.10
    )
    return run, benchmark, series


def _own_long_only_run(series: dict[str, PriceSeries]) -> BacktestResultMulti:
    """Run long-only da MESMA estratégia — produzido pelo CALLER (CA-05.1).

    Descarta os sinais de short (ENTER_SHORT -> sem sinal): a mesma
    configuração do run long+short, só que long-only — a diferença entre os
    dois runs é exatamente o que os shorts acrescentam.
    """
    strategies = {
        "A": _Paper({0: Signal.ENTER}),
        "B": _Paper({0: Signal.ENTER_SHORT}),
    }
    # O caller "descarta os sinais de short" trocando-os por ausência de
    # sinal — o mesmo contrato da estratégia, sem short.
    strategies["B"] = _Paper({})
    return run_backtest_multi(
        series,
        strategies,
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
        sizer=_FixedFractionSizer(0.9),
        margin=MarginModel(factor=2.0),
        borrow=BorrowFeeModel(fee_annual=0.005),
    )


# ─── RF-MET-05: benchmark 1/N + comparação própria ───────────────────────────


@pytest.mark.unit
def test_report_benchmark_is_1n_long_only_with_long_short_vs_long_only() -> None:
    """CA-MET-05.1 — o benchmark do relatório 2b é o MESMO 1/N long-only da 2a
    (mesma função, mesmo pipeline) e a comparação long+short x long-only da
    PRÓPRIA estratégia aparece quando o caller fornece o run long-only.

    O relatório NUNCA re-roda: recebe o run long-only pronto e só reporta a
    diferença (retorno acumulado/CAGR/Sharpe lado a lado no JSON).
    """
    run, benchmark, series = _long_short_run_and_benchmark()
    own_long_only = _own_long_only_run(series)
    report = BacktestReportMulti.build(
        strategy=run,
        benchmark=benchmark,
        strategy_name="paper",
        strategy_params={},
        strategy_long_only=own_long_only,
    )

    # Benchmark: mesma função da 2a — 1/N long-only, nunca short.
    assert report.benchmark is not None
    assert all(t.quantity >= 0 for t in benchmark.portfolio.trades)
    # Estratégia long+short: B shortou de verdade (a comparação tem o que medir).
    b_trades = [t for t in run.portfolio.trades if t.ticker == "B"]
    assert any(t.quantity < 0 for t in b_trades)

    # Comparação própria presente no JSON (long_short x own_long_only).
    payload = report.to_dict()
    assert "long_only_comparison" in payload
    comparison = payload["long_only_comparison"]
    assert set(comparison) == {"long_short", "own_long_only"}
    assert comparison["long_short"] == report.strategy.to_dict()
    assert comparison["own_long_only"] == report.strategy_long_only.to_dict()  # type: ignore[union-attr]

    # O run long-only não tem trades de short (o que a comparação isola).
    assert all(t.quantity >= 0 for t in own_long_only.portfolio.trades)


@pytest.mark.unit
def test_benchmark_never_shorts() -> None:
    """CA-05.2 — o benchmark do relatório 2b NUNCA shorta, mesmo num run em
    que a estratégia short (por construção: é o `buy_and_hold_multi` da 2a)."""
    run, benchmark, _ = _long_short_run_and_benchmark()
    report = BacktestReportMulti.build(
        strategy=run,
        benchmark=benchmark,
        strategy_name="paper",
        strategy_params={},
    )

    assert all(t.quantity >= 0 for t in benchmark.portfolio.trades)
    assert report.benchmark.num_trades == 2  # 1/N por ativo, só entradas
    assert not benchmark.broken_fund


# ─── RF-MET-06: vieses 2b + seção run com MHT ────────────────────────────────


@pytest.mark.unit
def test_bias_section_includes_2b_items() -> None:
    """CA-06.1 — a seção fixa de vieses do relatório 2b contém os itens
    novos do RF-MET-06, sempre (constante literal, padrão Fase 1 §5.2)."""
    run, benchmark, _ = _long_short_run_and_benchmark()
    report = BacktestReportMulti.build(
        strategy=run,
        benchmark=benchmark,
        strategy_name="paper",
        strategy_params={},
    )

    biases = "\n".join(report.to_dict()["biases"])
    assert "Custo de aluguel não calibrado" in biases
    assert "Disponibilidade de aluguel ilimitada" in biases
    assert "Liquidação forçada alfabética" in biases
    assert "MHT" in biases
    assert "Pior caso intrabarra ampliado" in biases
    # Itens da 2a preservados (regressão da seção fixa).
    assert "Ambiguidade intrabarra resolvida por pior caso" in biases
    assert "Survivorship bias" in biases


@pytest.mark.unit
def test_run_section_reports_mht_metric_grid_folds_reconstructible() -> None:
    """CA-06.2 — a seção "run" do relatório do walk-forward declara o MHT:
    métrica de seleção (Sharpe anualizado rf=0), grid size e nº de folds —
    reconstruível do JSON isolado (RF-CON-02)."""
    series = {
        "A": _series([10.0 + 0.5 * i for i in range(20)], ticker="A"),
        "B": _series([10.0 - 0.4 * i for i in range(20)], ticker="B"),
    }
    folds = build_folds(_D0, _D0 + timedelta(days=19), is_window=10, oos_window=5)
    grid = ParameterGrid(
        params=({"fast": 2.0}, {"fast": 3.0}),
        seed=42,
    )

    def factory(params: dict[str, float]) -> _Paper:
        fast = int(params["fast"])
        return _Paper({fast: Signal.ENTER, fast + 1: Signal.ENTER_SHORT}, warmup=2)

    result = run_walkforward(
        series,
        factory,
        grid,
        folds,
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
        margin=MarginModel(factor=1.0),
        borrow=BorrowFeeModel(fee_annual=0.0),
        sizer=FixedOneOverN(2),
        warmup=2,
    )
    report = WalkForwardReport.build(result)
    payload = report.to_dict()

    assert payload["selection_metric"] == "sharpe_annualized_rf0"
    assert payload["mht"] == {"grid_size": 2, "n_folds": len(folds)}
    assert len(payload["folds"]) == len(folds)
    # Reconstrutível do JSON isolado: só o payload basta para declarar o MHT.
    assert payload["mht"]["grid_size"] == result.grid_size
    assert payload["mht"]["n_folds"] == result.n_folds


# ─── RF-WFK-03: tabela fold a fold (None = traço claro "—", R6) ──────────────


@pytest.mark.unit
def test_report_shows_fold_by_fold_table_with_selected_params() -> None:
    """CA-WFK-03.2 — a tabela fold a fold renderiza por fold: janela IS/OOS,
    params selecionados, sharpe_is e ret_oos — com `None` (fundo quebrado no
    IS/OOS) como traço claro "—", nunca NaN nem string vazia (R6 — decisão
    com dono, registrada no tasks T12)."""
    folds = (
        Fold(
            is_start=_D0,
            is_end=_D0 + timedelta(days=4),
            oos_start=_D0 + timedelta(days=5),
            oos_end=_D0 + timedelta(days=9),
        ),
    )
    result = WalkForwardResult(
        folds=(
            FoldResult(
                fold=folds[0],
                selected_params={"fast": 2.0},
                is_metrics=FoldMetrics(
                    sharpe_is=1.234, ret_oos=None, sharpe_oos=None, max_dd_oos=None
                ),
                oos_metrics=FoldMetrics(
                    sharpe_is=None, ret_oos=None, sharpe_oos=None, max_dd_oos=None
                ),
            ),
        ),
        oos_equity=(100_000.0, 100_500.0),
        oos_dates=(_D0 + timedelta(days=5), _D0 + timedelta(days=6)),
        broken_fund=True,
        grid_size=3,
        n_folds=1,
    )
    report = WalkForwardReport.build(result)
    text = report.to_text()

    assert "Walk-forward — tabela fold a fold" in text
    assert "2024-01-01..2024-01-05" in text  # janela IS
    assert "2024-01-06..2024-01-10" in text  # janela OOS
    assert "fast=2" in text  # params selecionados
    assert "1.2340" in text  # sharpe_is computável
    assert "—" in text  # ret_oos None -> traço claro (R6)
    assert "Fundo quebrado em algum fold" in text  # CA-03.3 declarado

    payload = report.to_dict()
    assert payload["folds"][0]["selected_params"] == {"fast": 2.0}
    assert payload["folds"][0]["sharpe_is"] == 1.234
    assert payload["folds"][0]["ret_oos"] is None  # nunca NaN
    assert payload["broken_fund"] is True


# ─── RF-MRG-03: fundo quebrado — None explícito + exclusão de comparação ─────


@pytest.mark.unit
def test_broken_fund_result_excluded_from_auto_comparison() -> None:
    """CA-03.3 — fundo quebrado EXCLUI a comparação automática estratégia x
    benchmark: flag `comparison_excluded` no relatório (a leitura exige
    decisão de quem lê)."""
    # Short all-in que GAPA: cobertura no open drena o caixa para NEGATIVO.
    series = {"A": _series([10.0, 10.0, 30.0, 30.0], ticker="A")}
    run = run_backtest_multi(
        series,
        {"A": _Paper({0: Signal.ENTER_SHORT})},
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        sizer=FixedOneOverN(1),
        margin=MarginModel(factor=2.0),
        borrow=BorrowFeeModel(fee_annual=0.0),
    )
    benchmark = buy_and_hold_multi(
        series, n=1, initial_cash=100_000.0, costs=_FREE, slippage=_NO_SLIP, cap=0.10
    )
    report = BacktestReportMulti.build(
        strategy=run,
        benchmark=benchmark,
        strategy_name="paper",
        strategy_params={},
    )

    assert run.broken_fund is True
    assert report.broken_fund is True
    assert report.comparison_excluded is True
    assert report.to_dict()["comparison_excluded"] is True
    assert "EXCLUÍDA" in report.to_text()  # declarado no texto, não escondido


@pytest.mark.unit
def test_broken_fund_metrics_are_explicit_none_never_nan() -> None:
    """CA-03.2 — fundo quebrado: CAGR/Sharpe = None explícito (nunca NaN),
    e a alavancagem (turnover/exposições/utilização de margem) também None —
    a equity negativa real não vira retorno fabricado."""
    series = {"A": _series([10.0, 10.0, 30.0, 30.0], ticker="A")}
    run = run_backtest_multi(
        series,
        {"A": _Paper({0: Signal.ENTER_SHORT})},
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        sizer=FixedOneOverN(1),
        margin=MarginModel(factor=2.0),
        borrow=BorrowFeeModel(fee_annual=0.0),
    )
    benchmark = buy_and_hold_multi(
        series, n=1, initial_cash=100_000.0, costs=_FREE, slippage=_NO_SLIP, cap=0.10
    )
    report = BacktestReportMulti.build(
        strategy=run,
        benchmark=benchmark,
        strategy_name="paper",
        strategy_params={},
    )

    assert report.broken_fund is True
    strategy = report.strategy
    assert strategy.cumulative_return is None
    assert strategy.cagr is None
    assert strategy.sharpe is None
    # Alavancagem: None explícito (R6) — nunca média parcial fabricada.
    assert report.turnover is None
    assert report.gross_exposure is None
    assert report.net_exposure is None
    assert report.margin_utilization is None
    # Serialização: None (JSON null), nunca NaN.
    payload = report.to_dict()
    assert payload["strategy"]["cumulative_return"] is None
    assert payload["alavancagem"]["turnover_annualized"] is None
    # A contagem de trades e o drawdown continuam sendo fatos do run.
    assert strategy.num_trades == 1  # a cobertura forçada executou
    assert strategy.max_drawdown.magnitude > 0
    # Benchmark (não quebrado) segue com métricas numéricas.
    assert report.benchmark.cumulative_return is not None


# ─── CA-05.2 do SHT-05: shorts travados com categoria própria ────────────────


@pytest.mark.unit
def test_report_flags_locked_short_position() -> None:
    """CA-05.2 (SHT-05) — posição short ABERTA num ativo deslistado (série
    terminou antes do fim da união) é travada e reportada com categoria
    própria `locked_shorts` — nunca liquidada a preço inventado."""
    # Fator de margem 1.0 com pernas de 40% da equity: requirement = 80k <=
    # equity — o short de B NÃO é liquidado por margem; a série de B termina
    # antes da união e a posição fica ABERTA (travada, marcada pelo último
    # close) — o cenário do CA-05.2.
    series = {
        "A": _series([10.0] * 6, ticker="A"),
        "B": _series([10.0] * 3, ticker="B", start=_D0 + timedelta(days=1)),
    }
    run = run_backtest_multi(
        series,
        {"A": _Paper({0: Signal.ENTER}), "B": _Paper({0: Signal.ENTER_SHORT})},
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        cap=0.10,
        sizer=_FixedFractionSizer(0.4),
        margin=MarginModel(factor=1.0),
        borrow=BorrowFeeModel(fee_annual=0.0),
    )
    benchmark = buy_and_hold_multi(
        series, n=2, initial_cash=100_000.0, costs=_FREE, slippage=_NO_SLIP, cap=0.10
    )
    report = BacktestReportMulti.build(
        strategy=run,
        benchmark=benchmark,
        strategy_name="paper",
        strategy_params={},
    )

    assert "B" in run.delisted  # série de B terminou antes da união
    assert report.locked_shorts == ("B",)  # categoria própria (CA-05.2)
    assert report.to_dict()["universe"]["locked_shorts"] == ["B"]
    assert "B" in report.to_text()  # declarado no texto do relatório


# ─── RF-MRG-02 CA-02.3 + RF-SHT-03 CA-03.3: contadores e borrow fee no bloco ─


@pytest.mark.unit
def test_report_counts_margin_call_origin_trades() -> None:
    """CA-MRG-02.3 — o relatório REPORT o contador `margin_calls` que o laço
    agregou (dono §3.7): 1 por trade de liquidação com origin = MARGIN_CALL.
    O bloco de mecanismo carrega a contagem e o texto também."""
    series = {"A": _series([10.0, 10.0, 12.0, 12.0], ticker="A")}
    run = run_backtest_multi(
        series,
        {"A": _Paper({0: Signal.ENTER})},
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        sizer=FixedOneOverN(1),
        margin=MarginModel(factor=2.0),
        borrow=BorrowFeeModel(fee_annual=0.0),
    )
    benchmark = buy_and_hold_multi(
        series, n=1, initial_cash=100_000.0, costs=_FREE, slippage=_NO_SLIP, cap=0.10
    )
    report = BacktestReportMulti.build(
        strategy=run,
        benchmark=benchmark,
        strategy_name="paper",
        strategy_params={},
    )

    assert run.counters.margin_calls == 1  # o engine contou (T08b)
    assert report.counters.margin_calls == 1  # o relatório reporta o MESMO valor
    assert report.to_dict()["mechanism_counters"]["margin_calls"] == 1
    assert "liquidações por margem: 1" in report.to_text()


@pytest.mark.unit
def test_report_borrow_fee_own_category() -> None:
    """CA-03.3 (SHT-03) — o borrow fee é reportado em categoria PRÓPRIA
    (`borrow_fees`), nunca dentro de custos — o relatório espelha o termo
    próprio da conciliação (§6), sem dupla contagem."""
    series = {"A": _series([10.0, 10.0, 9.0, 9.0], ticker="A")}
    run = run_backtest_multi(
        series,
        {"A": _Paper({0: Signal.ENTER_SHORT, 1: Signal.EXIT_SHORT})},
        initial_cash=100_000.0,
        costs=_FREE,
        slippage=_NO_SLIP,
        sizer=FixedOneOverN(1),
        margin=MarginModel(factor=1.0),
        borrow=BorrowFeeModel(fee_annual=0.50),  # fee alto para o valor ser material
    )
    benchmark = buy_and_hold_multi(
        series, n=1, initial_cash=100_000.0, costs=_FREE, slippage=_NO_SLIP, cap=0.10
    )
    report = BacktestReportMulti.build(
        strategy=run,
        benchmark=benchmark,
        strategy_name="paper",
        strategy_params={},
    )

    assert report.borrow_fees > 0
    payload = report.to_dict()
    assert payload["borrow_fees"] == pytest.approx(run.borrow_fees)
    # Categoria própria: custos do run não absorvem o fee (zero custos aqui).
    assert payload["assumptions"]["costs"]["rate"] == 0.0
    assert "borrow fees pagos" in report.to_text()
