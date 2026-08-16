"""E1 — Métricas puras sobre a equity curve (ANA-01.1 a ANA-01.5).

Fixtures de papel, resultado calculado à mão (RNF-03). Nenhum teste aqui
chama outro teste como referência: o número esperado é derivado da fórmula
do design §5, não do que o código produziu.
"""

import math
from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

from quantlab.analytics.metrics import (
    avg_exposure,
    cagr,
    gross_exposure_avg,
    hit_rate,
    margin_utilization_avg,
    max_drawdown,
    net_exposure_avg,
    sharpe,
    turnover_annualized,
)
from quantlab.engine.portfolio import Trade
from quantlab.exceptions import EngineError

# ─── ANA-01.1 / ANA-01.4: Sharpe ──────────────────────────────────────────────


@pytest.mark.unit
def test_sharpe_matches_the_hand_derived_formula() -> None:
    """returns=[0.03, 0.01]: média=0.02, desvio-padrão amostral=|0.03-0.01|/√2.

    média/desvio = 0.02 / (0.02/√2) = √2, então Sharpe = √2 x √252 = √504.
    """
    returns = pd.Series([0.03, 0.01])

    result = sharpe(returns)

    assert result == pytest.approx(math.sqrt(504))


@pytest.mark.unit
def test_sharpe_with_nonzero_risk_free_rate_shifts_the_mean() -> None:
    """Mesma série, `rf=0.01`: excesso vira [0.02, 0.00].

    Subtrair uma constante não muda o desvio-padrão (continua |0.02-0|/√2 =
    0.02/√2), mas desloca a média de 0.02 para 0.01. média/desvio passa a ser
    0.01 / (0.02/√2) = √2/2 = 1/√2, e o Sharpe cai pela metade:
    (1/√2) x √252 = √(252/2) = √126.
    """
    returns = pd.Series([0.03, 0.01])

    result = sharpe(returns, rf=0.01)

    assert result == pytest.approx(math.sqrt(126))


@pytest.mark.unit
def test_sharpe_with_zero_volatility_is_none_not_nan() -> None:
    """CA-01.4 — desvio-padrão zero devolve `None`, nunca `nan`."""
    returns = pd.Series([0.01, 0.01, 0.01, 0.01])

    result = sharpe(returns)

    assert result is None


@pytest.mark.unit
def test_sharpe_with_fewer_than_two_returns_is_none() -> None:
    """Um único retorno não tem desvio-padrão definido."""
    assert sharpe(pd.Series([0.01])) is None
    assert sharpe(pd.Series([], dtype=float)) is None


@pytest.mark.unit
def test_sharpe_uses_252_trading_days_by_default() -> None:
    """Confirma o fator de anualização default sem depender de outro teste."""
    returns = pd.Series([0.03, 0.01])

    assert sharpe(returns) == pytest.approx(math.sqrt(2) * math.sqrt(252))


# ─── ANA-01.3: max drawdown, pico corrente e recuperação ─────────────────────


@pytest.mark.unit
def test_max_drawdown_measures_from_the_running_peak_and_finds_recovery() -> None:
    """100 -> 120 (novo pico) -> 90 (fundo, -25% de 120) -> 110 -> 125 (recupera).

    fundo: (90-120)/120 = -0.25 -> magnitude 0.25
    pico que originou o fundo: 120, em d2
    recuperação: primeira barra em que a equity volta a >= 120, que é d5 (125)
    """
    dates = [date(2024, 1, d) for d in (1, 2, 3, 4, 5)]
    equity = pd.Series([100.0, 120.0, 90.0, 110.0, 125.0], index=dates)

    result = max_drawdown(equity)

    assert result.magnitude == pytest.approx(0.25)
    assert result.peak_date == date(2024, 1, 2)
    assert result.trough_date == date(2024, 1, 3)
    assert result.recovery_date == date(2024, 1, 5)
    assert result.is_recovered


@pytest.mark.unit
def test_max_drawdown_not_recovered_by_the_end_of_the_series() -> None:
    """Mesmo início, mas a série termina em 110 — nunca volta a tocar o pico de 120."""
    dates = [date(2024, 1, d) for d in (1, 2, 3, 4)]
    equity = pd.Series([100.0, 120.0, 90.0, 110.0], index=dates)

    result = max_drawdown(equity)

    assert result.magnitude == pytest.approx(0.25)
    assert result.trough_date == date(2024, 1, 3)
    assert result.recovery_date is None
    assert not result.is_recovered


@pytest.mark.unit
def test_max_drawdown_picks_the_deepest_of_two_drops() -> None:
    """O pico é o **máximo corrente** (cummax), não o último valor local.

    100 -> 120 (pico) -> 90 (-25% de 120) -> 100 (ainda abaixo do pico) ->
    60 -> 80. Como 100 na quarta barra não supera o pico de 120, a referência
    continua 120 até o fim — a queda até 60 é (60-120)/120 = -0.5, mais funda
    que a de 90. Uma implementação que resetasse o pico para o último valor
    local acharia -0.4 (de 100 para 60); é exatamente essa a diferença que a
    fixture isola.
    """
    dates = [date(2024, 1, d) for d in (1, 2, 3, 4, 5, 6)]
    equity = pd.Series([100.0, 120.0, 90.0, 100.0, 60.0, 80.0], index=dates)

    result = max_drawdown(equity)

    assert result.magnitude == pytest.approx(0.5)
    assert result.peak_date == date(2024, 1, 2)
    assert result.trough_date == date(2024, 1, 5)


@pytest.mark.unit
def test_max_drawdown_recovery_is_exactly_on_the_bar_that_reaches_the_peak() -> None:
    """A barra que iguala o pico anterior JÁ conta como recuperação, não a seguinte.

    Isola o limite `>=` de `test_max_drawdown_measures_from_the_running_peak...`:
    aqui a recuperação é uma igualdade exata (125 -> 90 -> 125), não uma
    ultrapassagem.
    """
    dates = [date(2024, 1, d) for d in (1, 2, 3)]
    equity = pd.Series([125.0, 90.0, 125.0], index=dates)

    result = max_drawdown(equity)

    assert result.recovery_date == date(2024, 1, 3)


# ─── CAGR ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cagr_over_exactly_four_years_of_sixteenfold_growth() -> None:
    """2020-01-01 a 2024-01-01 = 1461 dias corridos = 4 anos exatos (365.25 x 4).

    100 -> 1600 é 16x; 16^(1/4) = 2, então CAGR = 2 - 1 = 100%.
    """
    equity = pd.Series(
        [100.0, 1600.0],
        index=[date(2020, 1, 1), date(2024, 1, 1)],
    )

    assert cagr(equity) == pytest.approx(1.0)


@pytest.mark.unit
def test_cagr_with_a_single_point_is_zero() -> None:
    equity = pd.Series([100.0], index=[date(2024, 1, 1)])

    assert cagr(equity) == 0.0


@pytest.mark.unit
def test_cagr_with_no_elapsed_time_is_zero() -> None:
    """Duas barras na mesma data (não deveria acontecer, mas não pode dividir por zero)."""
    equity = pd.Series([100.0, 150.0], index=[date(2024, 1, 1), date(2024, 1, 1)])

    assert cagr(equity) == 0.0


# ─── hit_rate ─────────────────────────────────────────────────────────────


def _closed_trade(entry_price: float, exit_price: float) -> Trade:
    return Trade(
        ticker="TEST",
        entry_date=date(2024, 1, 1),
        entry_price=entry_price,
        entry_decision_date=date(2023, 12, 29),
        quantity=10,
        entry_cost=1.0,
        entry_gap_days=3,
        exit_date=date(2024, 2, 1),
        exit_price=exit_price,
        exit_cost=1.0,
        exit_gap_days=3,
        exit_decision_date=date(2024, 1, 29),
    )


@pytest.mark.unit
def test_hit_rate_counts_only_closed_trades_with_positive_realized_pnl() -> None:
    """3 trades fechados: dois vencedores, um perdedor. Um quarto trade fica aberto."""
    trades = [
        _closed_trade(entry_price=10.0, exit_price=15.0),  # ganhou
        _closed_trade(entry_price=10.0, exit_price=8.0),  # perdeu
        _closed_trade(entry_price=10.0, exit_price=10.01),  # ganhou (pouco, mas > 0)
        replace(_closed_trade(entry_price=10.0, exit_price=999.0), exit_date=None, exit_price=None),
    ]

    assert hit_rate(trades) == pytest.approx(2 / 3)


@pytest.mark.unit
def test_hit_rate_with_no_closed_trades_is_none() -> None:
    open_trade = replace(_closed_trade(10.0, 20.0), exit_date=None, exit_price=None)

    assert hit_rate([open_trade]) is None
    assert hit_rate([]) is None


@pytest.mark.unit
def test_hit_rate_exact_breakeven_does_not_count_as_a_win() -> None:
    """PnL exatamente zero não é vitória — `> 0`, não `>= 0`."""
    breakeven = _closed_trade(entry_price=10.0, exit_price=10.0)

    assert hit_rate([breakeven]) == 0.0


# ─── RF-MET-04 (T14): turnover anualizado e exposição média ───────────────────


def _notional_trade(
    quantity: int, entry_price: float, exit_price: float | None = None, *, rebalance: bool = False
) -> Trade:
    """Trade de papel com notional controlado e custos zero (RNF-03)."""
    return Trade(
        ticker="AAA",
        entry_date=date(2024, 1, 2),
        entry_price=entry_price,
        entry_decision_date=date(2024, 1, 2),
        quantity=quantity,
        entry_cost=0.0,
        entry_gap_days=0,
        exit_date=date(2024, 1, 3) if exit_price is not None else None,
        exit_price=exit_price,
        exit_cost=0.0,
        rebalance=rebalance,
    )


@pytest.mark.unit
def test_turnover_formula_closed_form() -> None:
    """Fórmula fechada do P4/RF-MET-04 (CA-04.1/CA-04.3), derivada à mão.

    T1: 100 x 10.0 (compra 1_000), venda a 11.0 (1_100).
    T2: 50 x 20.0 (compra 1_000), venda a 19.0 (950).
    notional = (1_000 + 1_000) + (1_100 + 950) = 4_050.
    equity = [100_000, 101_000, 99_000] -> média 100_000; n_bars = 3.
    turnover = 4_050 / (2 x 100_000) x (252 / 3) = 0.02025 x 84 = 1.701.
    """
    trades = [
        _notional_trade(100, 10.0, 11.0),
        _notional_trade(50, 20.0, 19.0),
    ]
    equity_daily = pd.Series([100_000.0, 101_000.0, 99_000.0])

    result = turnover_annualized(trades, equity_daily, n_bars=3)

    assert result == pytest.approx(4_050 / (2 * 100_000) * (252 / 3))
    assert result == pytest.approx(1.701)


@pytest.mark.unit
def test_turnover_includes_rebalance_trades() -> None:
    """Decisão T14 (emenda §7): rebalance entra no giro — é notional real.

    T de sinal: 100 x 10.0 -> 11.0 (compra 1_000, venda 1_100).
    T de rebalance: 10 x 30.0 -> 31.0 (compra 300, venda 310).
    notional total = 2_710; equity média 100_000; n_bars = 2.
    turnover = 2_710 / 200_000 x (252 / 2) = 1.7073.
    """
    trades = [
        _notional_trade(100, 10.0, 11.0),
        _notional_trade(10, 30.0, 31.0, rebalance=True),
    ]
    equity_daily = pd.Series([100_000.0, 100_000.0])

    result = turnover_annualized(trades, equity_daily, n_bars=2)

    assert result == pytest.approx(2_710 / (2 * 100_000) * (252 / 2))


@pytest.mark.unit
def test_average_exposure_formula_closed_form() -> None:
    """Média diária de (Σ qty_i x close_i) / equity (CA-04.4).

    notional = [50_000, 40_000, 60_000], equity = 100_000 constante:
    razões [0.5, 0.4, 0.6], média = 0.5.
    """
    daily_notional = pd.Series([50_000.0, 40_000.0, 60_000.0])
    equity_daily = pd.Series([100_000.0, 100_000.0, 100_000.0])

    result = avg_exposure(daily_notional, equity_daily)

    assert result == pytest.approx((0.5 + 0.4 + 0.6) / 3)
    assert result == pytest.approx(0.5)


@pytest.mark.unit
def test_same_definitions_strategy_and_benchmark() -> None:
    """MET-04.2/CA-04.2: esta função é a ÚNICA fonte da fórmula.

    Prova por determinismo (mesma entrada => mesmo valor, sem estado) e por
    escala (CA-04.3): com o mesmo numerador e a mesma média de equity
    (100_500 em 2 e em 4 pontos), dobrar n_bars divide o fator 252/n pela
    metade — o resultado responde só aos parâmetros, sem modo "estratégia"
    vs "benchmark".
    """
    trades = [_notional_trade(100, 10.0, 11.0)]
    base = turnover_annualized(trades, pd.Series([100_000.0, 101_000.0]), n_bars=2)

    assert turnover_annualized(trades, pd.Series([100_000.0, 101_000.0]), n_bars=2) == base
    doubled_window = turnover_annualized(
        trades, pd.Series([100_000.0, 101_000.0, 100_000.0, 101_000.0]), n_bars=4
    )
    assert doubled_window == pytest.approx(base / 2)


@pytest.mark.unit
def test_turnover_domain_errors_raise_engine_error() -> None:
    """Pré/pós do §3.8 (RF-MET-04): n_bars < 1, série vazia/desalinhada,
    patrimônio médio não positivo => EngineError (erro de programação)."""
    trades = [_notional_trade(100, 10.0, 11.0)]
    equity = pd.Series([100_000.0, 100_000.0])

    with pytest.raises(EngineError):
        turnover_annualized(trades, equity, n_bars=0)
    with pytest.raises(EngineError):
        turnover_annualized(trades, pd.Series([], dtype="float64"), n_bars=2)
    with pytest.raises(EngineError):
        turnover_annualized(trades, pd.Series([100_000.0]), n_bars=2)  # 1 != 2
    with pytest.raises(EngineError):
        turnover_annualized(trades, pd.Series([0.0, 0.0]), n_bars=2)  # média 0


@pytest.mark.unit
def test_average_exposure_domain_errors_raise_engine_error() -> None:
    """Séries vazias/desalinhadas (comprimento ou índice) e equity não
    positiva => EngineError (§3.8, RF-MET-04)."""
    notional = pd.Series([50_000.0, 40_000.0])
    equity = pd.Series([100_000.0, 100_000.0])

    with pytest.raises(EngineError):
        avg_exposure(pd.Series([], dtype="float64"), equity)
    with pytest.raises(EngineError):
        avg_exposure(notional, pd.Series([100_000.0]))  # comprimentos diferentes
    with pytest.raises(EngineError):
        avg_exposure(
            pd.Series([50_000.0], index=[date(2024, 1, 1)]),
            pd.Series([100_000.0], index=[date(2024, 1, 2)]),  # índices diferentes
        )
    with pytest.raises(EngineError):
        avg_exposure(notional, pd.Series([100_000.0, 0.0]))  # equity não positiva


# ─── 2b (T09): exposição gross/net e utilização de margem (RF-MRG-04) ─────────


@pytest.mark.unit
def test_gross_and_net_exposure_formulas_side_by_side() -> None:
    """CA-04.1 (RF-MRG-04) — gross e net lado a lado no MESMO run, em forma
    fechada derivada à mão (RNF-03).

    Carteira de papel por dia (long A + short B), equity 10.000 constante:
      dia 1: long 100 x 20 = 2.000, short -100 x 10 = -1.000
             ⇒ gross 3.000 (|2.000| + |-1.000|), net 1.000 (2.000 - 1.000)
      dia 2: long 100 x 25 = 2.500, short -100 x 15 = -1.500
             ⇒ gross 4.000, net 1.000
      dia 3: long 100 x 15 = 1.500, short -100 x 20 = -2.000
             ⇒ gross 3.500, net -500 (short líquido)
    razões gross/equity = [0.3, 0.4, 0.35] ⇒ média 0.35
    razões net/equity   = [0.1, 0.1, -0.05] ⇒ média 0.05
    """
    daily_gross_notional = [3_000.0, 4_000.0, 3_500.0]
    daily_net_notional = [1_000.0, 1_000.0, -500.0]
    equity_daily = [10_000.0, 10_000.0, 10_000.0]

    gross = gross_exposure_avg(daily_gross_notional, equity_daily)
    net = net_exposure_avg(daily_net_notional, equity_daily)

    assert gross == pytest.approx(0.35)
    assert net == pytest.approx(0.05)
    # Determinismo (RNF-01): mesma entrada ⇒ mesmo valor (função pura).
    assert gross_exposure_avg(daily_gross_notional, equity_daily) == gross
    assert net_exposure_avg(daily_net_notional, equity_daily) == net


@pytest.mark.unit
def test_leveraged_gross_gt_100_reported_with_margin_utilization() -> None:
    """CA-04.2 (RF-MRG-04) — gross pode EXCEDER 100% (alavancada com margem):
    a métrica devolve o número > 1 (a renderização lado a lado com a
    utilização é a T12 — "reportado"). Forma fechada à mão:

      dia 1: gross 25.000/10.000 = 2,5; margem 12.500/10.000 = 1,25
      dia 2: gross 20.000/10.000 = 2,0; margem 10.000/10.000 = 1,0
    médias: gross (2,5 + 2,0)/2 = 2,25 (225%); utilização 1,125 (112,5%).
    """
    gross = gross_exposure_avg([25_000.0, 20_000.0], [10_000.0, 10_000.0])
    utilization = margin_utilization_avg([12_500.0, 10_000.0], [10_000.0, 10_000.0])

    assert gross == pytest.approx(2.25)  # 225% > 100% — alavancada
    assert utilization == pytest.approx(1.125)


@pytest.mark.unit
def test_margin_utilization_avg_none_on_broken_fund() -> None:
    """R6 (MRG-01 CA-01.4) — equity <= 0 (fundo quebrado) ⇒ None explícito,
    nunca NaN nem zero fabricado; um único dia quebrado contamina a média
    inteira (nada de média parcial sobre os dias válidos)."""
    assert margin_utilization_avg([10_000.0], [-5_000.0]) is None  # equity negativa
    assert margin_utilization_avg([10_000.0], [0.0]) is None  # equity zero
    assert margin_utilization_avg([10_000.0, 10_000.0], [10_000.0, -1.0]) is None
    # Controle saudável: não é None e o valor fecha.
    assert margin_utilization_avg([10_000.0], [10_000.0]) == pytest.approx(1.0)


@pytest.mark.unit
def test_turnover_closed_form_with_shorts() -> None:
    """RF-MRG-04 — turnover com |notional|: shorts contam IGUAL a longs
    (notional absoluto; a fórmula da 2a já funciona com qty < 0 — design §7,
    turnover 2a INTOCADA). Forma fechada à mão:

    Short de 1.000@100 coberto a 100 ⇒ |notional venda| 100k + |notional
    compra| 100k = 200k; equity média 100k; n_bars = 2 ⇒ turnover =
    200k/(2 x 100k) x (252/2) = 126. O round-trip LONG idêntico (1.000@100
    comprado, vendido a 100) dá o MESMO 126 — simetria por |qty|.
    """
    short = [_notional_trade(-1_000, 100.0, 100.0)]  # qty < 0 (2b, T01)
    long_trip = [_notional_trade(1_000, 100.0, 100.0)]
    equity_daily = pd.Series([100_000.0, 100_000.0])

    short_turnover = turnover_annualized(short, equity_daily, n_bars=2)
    long_turnover = turnover_annualized(long_trip, equity_daily, n_bars=2)

    assert short_turnover == pytest.approx(126.0)
    assert long_turnover == pytest.approx(126.0)  # |qty| — mesma pegada


@pytest.mark.unit
def test_exposure_domain_errors_raise_engine_error() -> None:
    """§3.8 (RF-MRG-04, mesmo padrão da T14) — séries vazias/desalinhadas
    (comprimento) e equity não positiva => EngineError para gross/net; para
    margin_utilization_avg, equity <= 0 é o caso R6 (None), nunca erro."""
    gross = [3_000.0, 4_000.0]
    net = [1_000.0, -500.0]
    req = [12_500.0, 10_000.0]
    equity = [10_000.0, 10_000.0]

    with pytest.raises(EngineError):
        gross_exposure_avg([], equity)
    with pytest.raises(EngineError):
        net_exposure_avg([], equity)
    with pytest.raises(EngineError):
        margin_utilization_avg([], equity)
    with pytest.raises(EngineError):
        gross_exposure_avg(gross, [10_000.0])  # comprimentos diferentes
    with pytest.raises(EngineError):
        net_exposure_avg(net, [10_000.0])
    with pytest.raises(EngineError):
        margin_utilization_avg(req, [10_000.0])
    with pytest.raises(EngineError):
        gross_exposure_avg(gross, [10_000.0, 0.0])  # equity não positiva
    with pytest.raises(EngineError):
        net_exposure_avg(net, [10_000.0, -1.0])
    # margin_utilization_avg com equity <= 0 NÃO é erro — é None (R6).
    assert margin_utilization_avg(req, [10_000.0, 0.0]) is None
