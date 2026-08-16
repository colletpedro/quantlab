"""C5 e C6 — laço de barras e conciliação (ENG-01.x, ENG-02.4, ENG-04.x).

Séries de papel, sem banco (RNF-03). O teste que importa mais que todos os
outros da fase está aqui: `test_mutating_future_bars_does_not_change_trades`
(ENG-01.2), o critério de aceitação declarado no requirements.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pytest
from numpy.typing import NDArray
from structlog.typing import EventDict

from quantlab.engine.backtest import BacktestResultMulti, run_backtest, run_backtest_multi
from quantlab.engine.broker import CostModel
from quantlab.engine.conditional import ConditionalIntent, OrderKind
from quantlab.engine.market_view import MarketView
from quantlab.engine.portfolio import TradeOrigin
from quantlab.engine.sizing import EqualWeightOpen, SizingInputs
from quantlab.engine.slippage import FixedBps
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries
from quantlab.strategies.sma_cross import SmaCross

_FREE = CostModel(fixed=0.0, rate=0.0)
_NO_SLIP = FixedBps(bps=0.0)
_D0 = date(2024, 1, 1)


def _dates(n: int, start: date = _D0) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def _series(
    opens: list[float],
    closes: list[float],
    *,
    ticker: str = "TEST",
    dates: list[date] | None = None,
) -> PriceSeries:
    """Série de papel: só `open` e `close` importam para o laço."""
    bar_dates = dates or [date(2024, 1, 1) + timedelta(days=i) for i in range(len(opens))]
    date_array: NDArray[np.object_] = np.empty(len(bar_dates), dtype=object)
    date_array[:] = bar_dates
    return PriceSeries(
        ticker=ticker,
        dates=date_array,
        open=np.array(opens, dtype=np.float64),
        high=np.array(closes, dtype=np.float64),
        low=np.array(opens, dtype=np.float64),
        close=np.array(closes, dtype=np.float64),
        volume=np.array([1_000.0] * len(opens)),
        adjusted=True,
        hash="0" * 64,
    )


@dataclass
class ScriptedStrategy:
    """Emite sinais em índices fixos. Torna o laço determinístico e legível."""

    script: dict[int, Signal]
    warmup: int = 0
    seen: list[int] = field(default_factory=list)

    def on_bar(self, view: MarketView) -> Signal | None:
        self.seen.append(view.i)
        return self.script.get(view.i)


@dataclass
class NeverTrades:
    warmup: int = 0

    def on_bar(self, view: MarketView) -> Signal | None:
        return None


# ─── ENG-01.1: execução no open do pregão seguinte ───────────────────────────


@pytest.mark.unit
def test_signal_executes_at_the_next_bars_open() -> None:
    """ENG-01.1 — sinal no fechamento de D executa ao `open` de D+1.

    Sinal no índice 1. O open do índice 2 é 50.0; o close do índice 1
    (onde a decisão foi tomada) é 999.0 e NÃO pode ser o preço de execução.
    """
    series = _series(opens=[10.0, 20.0, 50.0, 60.0], closes=[10.0, 999.0, 50.0, 60.0])
    strategy = ScriptedStrategy(script={1: Signal.ENTER})

    result = run_backtest(series, strategy, initial_cash=1_000.0, costs=_FREE)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(50.0), "executou ao preço errado"
    assert trade.entry_date == date(2024, 1, 3)
    assert trade.entry_decision_date == date(2024, 1, 2)


@pytest.mark.unit
def test_execution_never_happens_on_the_decision_bar() -> None:
    """A decisão de `i` nunca é preenchida em `i` — a ordem do laço garante."""
    series = _series(opens=[10.0, 20.0, 30.0], closes=[10.0, 20.0, 30.0])
    strategy = ScriptedStrategy(script={0: Signal.ENTER})

    result = run_backtest(series, strategy, initial_cash=1_000.0, costs=_FREE)

    # Decidiu em 0, executou em 1 ao open 20.0 — não ao open 10.0 de 0.
    assert result.trades[0].entry_price == pytest.approx(20.0)
    assert result.trades[0].entry_gap_days == 1


# ─── ENG-01.2: O CRITÉRIO DE ACEITAÇÃO DA FASE ───────────────────────────────


@pytest.mark.unit
def test_mutating_future_bars_does_not_change_trades() -> None:
    """**ENG-01.2 — o teste que prova a invariante anti-lookahead.**

    O requirements chama este de "requisito de aceitação da fase", não de
    teste opcional. O procedimento é o que ele descreve literalmente:

      1. roda um backtest;
      2. altera ARBITRARIAMENTE as barras posteriores à última decisão;
      3. reexecuta;
      4. o conjunto de trades executados tem de ser idêntico.

    **Qual barra é livre para mutar, exatamente.** A última decisão é no
    índice 2, e por ADR-0002 ela executa ao `open` do índice 3 — logo a barra
    3 NÃO é livre: o engine tem obrigação de ler o `open` dela, e mudá-lo
    muda o preço de saída legitimamente. As barras verdadeiramente
    posteriores a tudo que influencia o resultado começam no índice 4.

    Escrever a mutação a partir do índice 3 foi o meu primeiro erro aqui, e
    ele é instrutivo: um teste de anti-lookahead cedo demais acusa lookahead
    onde há execução correta. A fronteira é `última decisão + 1`, não
    `última decisão`.

    Índices 4 e 5 viram preços 100x maiores. Se qualquer lookahead entrar no
    código, algum trade muda de preço, de quantidade ou de data.

    Note que a mutação é do LADO DE FORA: as barras futuras mudam de verdade,
    e não é a estratégia que é impedida de olhar. Se o laço consultasse a
    estratégia antes de executar, ou executasse ao close, o resultado
    dependeria desses números e a igualdade abaixo falharia.
    """
    opens = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    closes = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    script = {0: Signal.ENTER, 2: Signal.EXIT}

    baseline = run_backtest(
        _series(opens, closes),
        ScriptedStrategy(script=dict(script)),
        initial_cash=1_000.0,
        costs=_FREE,
    )

    # Índice 3 é a execução da decisão de 2 — preservado. 4 e 5 são livres.
    mutated_opens = [*opens[:4], 5_000.0, 6_000.0]
    mutated_closes = [*closes[:4], 5_000.0, 6_000.0]
    mutated = run_backtest(
        _series(mutated_opens, mutated_closes),
        ScriptedStrategy(script=dict(script)),
        initial_cash=1_000.0,
        costs=_FREE,
    )

    assert baseline.trades == mutated.trades, (
        "as barras posteriores à última decisão mudaram o conjunto de trades — há lookahead no laço"
    )


@pytest.mark.unit
def test_mutating_future_bars_changes_equity_but_not_trades() -> None:
    """O contraponto que impede o teste acima de passar por vacuidade.

    Se o backtest ignorasse as barras futuras por completo, ENG-01.2 passaria
    trivialmente e não provaria nada. A equity DEVE mudar — a posição aberta é
    marcada a mercado pelos preços novos — enquanto os trades não mudam.
    """
    opens = [10.0, 20.0, 30.0, 40.0]
    closes = [10.0, 20.0, 30.0, 40.0]
    script = {0: Signal.ENTER}

    baseline = run_backtest(
        _series(opens, closes),
        ScriptedStrategy(script=dict(script)),
        initial_cash=1_000.0,
        costs=_FREE,
    )
    mutated = run_backtest(
        _series([*opens[:2], 300.0, 400.0], [*closes[:2], 300.0, 400.0]),
        ScriptedStrategy(script=dict(script)),
        initial_cash=1_000.0,
        costs=_FREE,
    )

    assert baseline.trades == mutated.trades
    assert baseline.final_equity != pytest.approx(mutated.final_equity)


# ─── ENG-01.4: sinal na última barra ─────────────────────────────────────────


@pytest.mark.unit
def test_signal_on_the_last_bar_is_reported_as_pending_not_executed() -> None:
    """ENG-01.4 — não há `i+1`: a ordem morre pendente, sem afetar a contabilidade."""
    series = _series(opens=[10.0, 20.0, 30.0], closes=[10.0, 20.0, 30.0])
    strategy = ScriptedStrategy(script={2: Signal.ENTER})

    result = run_backtest(series, strategy, initial_cash=1_000.0, costs=_FREE)

    assert result.trades == []
    assert result.pending_order is not None
    assert result.pending_order.signal is Signal.ENTER
    assert result.pending_order.decision_index == 2
    assert result.final_equity == pytest.approx(1_000.0)


# ─── ENG-01.5: gap de pregões ────────────────────────────────────────────────


@pytest.mark.unit
def test_gap_between_trading_days_is_recorded_on_the_trade() -> None:
    """ENG-01.5 — executa na próxima barra EXISTENTE, e o gap fica auditável.

    Sexta 05/01 decide; a próxima barra é segunda 08/01 (fim de semana no
    meio). Executa em 08/01 e grava 3 dias corridos de gap.
    """
    dates = [date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]
    series = _series(opens=[10.0, 20.0, 30.0], closes=[10.0, 20.0, 30.0], dates=dates)
    strategy = ScriptedStrategy(script={1: Signal.ENTER})

    result = run_backtest(series, strategy, initial_cash=1_000.0, costs=_FREE)

    trade = result.trades[0]
    assert trade.entry_decision_date == date(2024, 1, 5)
    assert trade.entry_date == date(2024, 1, 8)
    assert trade.entry_gap_days == 3


@pytest.mark.unit
def test_long_holiday_gap_is_recorded_whatever_the_distance() -> None:
    """ "Qualquer que seja a distância em dias" — o requirements é literal."""
    dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 2, 15)]
    series = _series(opens=[10.0, 20.0, 30.0], closes=[10.0, 20.0, 30.0], dates=dates)
    strategy = ScriptedStrategy(script={1: Signal.ENTER})

    result = run_backtest(series, strategy, initial_cash=1_000.0, costs=_FREE)

    assert result.trades[0].entry_gap_days == 43


# ─── warmup (ENG-06.3, design §4.2) ──────────────────────────────────────────


@pytest.mark.unit
def test_strategy_is_not_consulted_before_warmup() -> None:
    """ENG-06.3 sai de graça: o laço não chama `on_bar` antes de `i >= warmup`."""
    series = _series(opens=[10.0] * 6, closes=[10.0] * 6)
    strategy = ScriptedStrategy(script={}, warmup=3)

    run_backtest(series, strategy, initial_cash=1_000.0, costs=_FREE)

    assert strategy.seen == [3, 4, 5]


# ─── decisão Q2: ENTER com posição, EXIT sem posição ─────────────────────────


@pytest.mark.unit
def test_enter_with_an_open_position_is_ignored() -> None:
    """Decisão Q2 — cruzamento repetido é condição de mercado, não erro."""
    series = _series(opens=[10.0] * 5, closes=[10.0] * 5)
    strategy = ScriptedStrategy(script={0: Signal.ENTER, 2: Signal.ENTER})

    result = run_backtest(series, strategy, initial_cash=1_000.0, costs=_FREE)

    assert len(result.trades) == 1


@pytest.mark.unit
def test_exit_without_a_position_is_ignored() -> None:
    """Lado simétrico da decisão Q2."""
    series = _series(opens=[10.0] * 4, closes=[10.0] * 4)
    strategy = ScriptedStrategy(script={0: Signal.EXIT})

    result = run_backtest(series, strategy, initial_cash=1_000.0, costs=_FREE)

    assert result.trades == []
    assert result.final_equity == pytest.approx(1_000.0)


# ─── ENG-04.1: equity curve ──────────────────────────────────────────────────


@pytest.mark.unit
def test_equity_is_cash_plus_position_at_the_close_of_every_bar() -> None:
    """ENG-04.1 — em qualquer instante, equity = caixa + posição * close."""
    series = _series(opens=[10.0, 10.0, 10.0], closes=[10.0, 20.0, 30.0])
    strategy = ScriptedStrategy(script={0: Signal.ENTER})

    result = run_backtest(series, strategy, initial_cash=100.0, costs=_FREE)

    assert len(result.equity_curve) == 3
    for point in result.equity_curve:
        assert point.equity == pytest.approx(point.cash + point.position_value)

    # Barra 1: comprou 10 ações a 10.00, caixa 0, close 20 -> equity 200.
    assert result.equity_curve[1].equity == pytest.approx(200.0)
    assert result.equity_curve[2].equity == pytest.approx(300.0)


@pytest.mark.unit
def test_the_equity_of_a_bar_does_not_depend_on_the_signal_emitted_on_it() -> None:
    """Consultar a estratégia não move a carteira — e é isso que torna livre
    a ordem entre os passos 2 e 3 do laço.

    Descoberto por mutação: inverter os passos 2 e 3 (consultar antes de
    marcar) **não derruba teste nenhum**, porque `on_bar` não tem efeito
    colateral sobre o portfolio — só devolve um sinal, que vira ordem
    pendente para a barra seguinte. É consequência de ENG-05.2: a estratégia
    não alcança caixa, posição nem trades.

    A ordem que É carregadora de peso é `executar antes de marcar` (passos 1
    e 2) e `executar antes de consultar` (passos 1 e 3) — as duas com
    mutação que derruba teste.

    Este teste existe para que a premissa deixe de ser implícita: se alguém
    algum dia der efeito colateral a `on_bar`, ele quebra aqui, e a pessoa
    descobre que a ordem 2/3 passou a importar antes de descobrir por um
    número errado no relatório.
    """
    opens = [10.0, 10.0, 10.0]
    closes = [10.0, 20.0, 30.0]

    silent = run_backtest(_series(opens, closes), NeverTrades(), initial_cash=100.0, costs=_FREE)
    # Sinal na ÚLTIMA barra: nunca executa (ENG-01.4), então a única
    # diferença possível seria um efeito colateral da consulta.
    signalling = run_backtest(
        _series(opens, closes),
        ScriptedStrategy(script={2: Signal.ENTER}),
        initial_cash=100.0,
        costs=_FREE,
    )

    assert signalling.pending_order is not None
    assert [point.equity for point in silent.equity_curve] == pytest.approx(
        [point.equity for point in signalling.equity_curve]
    )
    assert [point.cash for point in silent.equity_curve] == pytest.approx(
        [point.cash for point in signalling.equity_curve]
    )


@pytest.mark.unit
def test_equity_reflects_the_execution_of_the_same_bar() -> None:
    """Executar ANTES de marcar: a equity de `i` já reflete a posição de `i`.

    Se o laço marcasse antes de executar, a barra 1 mostraria 100.0 de caixa
    puro em vez dos 200.0 da posição já comprada — a equity ficaria um dia
    atrasada em toda barra com execução.
    """
    series = _series(opens=[10.0, 10.0], closes=[10.0, 20.0])
    strategy = ScriptedStrategy(script={0: Signal.ENTER})

    result = run_backtest(series, strategy, initial_cash=100.0, costs=_FREE)

    assert result.equity_curve[1].position_value == pytest.approx(200.0)
    assert result.equity_curve[1].cash == pytest.approx(0.0)


# ─── C6 / ENG-04.2: conciliação ──────────────────────────────────────────────


@pytest.mark.unit
def test_reconciliation_with_a_closed_trade() -> None:
    """ENG-04.2 — a identidade de design §4.6, caso simples.

    Compra 9 a 10.00 (custo 1.00), vende a 20.00 (custo 1.00).
      realizado    = (20 - 10) * 9 = 90.00   [BRUTO]
      custos       = 2.00
      não realiz.  = 0.00
      equity_final - inicial = 90.00 - 2.00 = 88.00
    """
    series = _series(opens=[10.0, 10.0, 20.0, 20.0], closes=[10.0, 10.0, 20.0, 20.0])
    strategy = ScriptedStrategy(script={0: Signal.ENTER, 1: Signal.EXIT})

    result = run_backtest(
        series, strategy, initial_cash=100.0, costs=CostModel(fixed=1.0, rate=0.0)
    )

    assert result.realized_pnl == pytest.approx(90.0)
    assert result.total_costs == pytest.approx(2.0)
    assert result.unrealized_pnl == pytest.approx(0.0)
    assert result.final_equity - result.initial_cash == pytest.approx(88.0)
    assert result.reconciles()


@pytest.mark.unit
def test_reconciliation_with_a_position_still_open_at_the_end() -> None:
    """ENG-02.4 + ENG-04.2 — cenário obrigatório de C6.

    A posição NÃO é liquidada à força: é marcada a mercado pelo último close
    e reportada separadamente do realizado.

    Compra 9 a 10.00 (custo 1.00). Último close 30.00.
      realizado    = 0.00
      não realiz.  = (30 - 10) * 9 = 180.00
      custos       = 1.00
      equity_final - inicial = 180.00 - 1.00 = 179.00
    """
    series = _series(opens=[10.0, 10.0, 10.0], closes=[10.0, 20.0, 30.0])
    strategy = ScriptedStrategy(script={0: Signal.ENTER})

    result = run_backtest(
        series, strategy, initial_cash=100.0, costs=CostModel(fixed=1.0, rate=0.0)
    )

    assert len(result.trades) == 1
    assert result.trades[0].is_open
    assert result.realized_pnl == pytest.approx(0.0)
    assert result.unrealized_pnl == pytest.approx(180.0)
    assert result.total_costs == pytest.approx(1.0)
    assert result.final_equity - result.initial_cash == pytest.approx(179.0)
    assert result.reconciles()


@pytest.mark.unit
def test_reconciliation_with_a_dividend_during_an_open_position() -> None:
    """ENG-04.3 + ENG-04.2 — o outro cenário obrigatório de C6.

    O dividendo entra via AJUSTE DE PREÇO, não como crédito em caixa
    (premissa 6). Numa série já ajustada, o provento aparece como preço
    relativo — a conciliação não ganha termo novo, e é exatamente isso que
    este teste prova: nenhum caixa aparece do nada.

    Série ajustada com dividendo entre as barras 1 e 2: os fechamentos
    anteriores já vêm multiplicados pelo fator. A identidade fecha igual.
    """
    # Fechamentos já ajustados: 9.90, 19.80 (fator 0.99) e 30.00 depois da ex.
    series = _series(opens=[9.90, 9.90, 9.90], closes=[9.90, 19.80, 30.0])
    strategy = ScriptedStrategy(script={0: Signal.ENTER})

    result = run_backtest(
        series, strategy, initial_cash=100.0, costs=CostModel(fixed=1.0, rate=0.0)
    )

    assert result.reconciles()
    # Nenhum crédito em caixa: o caixa só muda por compra, venda e custo.
    assert result.equity_curve[-1].cash == pytest.approx(result.equity_curve[1].cash)


@pytest.mark.unit
def test_reconciliation_holds_with_no_trades_at_all() -> None:
    """Caso degenerado: sem trade, a identidade vira 0 == 0."""
    series = _series(opens=[10.0, 20.0], closes=[10.0, 20.0])

    result = run_backtest(series, NeverTrades(), initial_cash=100.0, costs=_FREE)

    assert result.trades == []
    assert result.final_equity == pytest.approx(100.0)
    assert result.reconciles()


@pytest.mark.unit
def test_reconciliation_holds_across_several_round_trips() -> None:
    """Vários trades, com custo variável: a identidade não acumula erro."""
    opens = [10.0, 12.0, 15.0, 11.0, 14.0, 18.0, 20.0]
    series = _series(opens=opens, closes=opens)
    strategy = ScriptedStrategy(
        script={0: Signal.ENTER, 1: Signal.EXIT, 2: Signal.ENTER, 4: Signal.EXIT}
    )

    result = run_backtest(
        series, strategy, initial_cash=10_000.0, costs=CostModel(fixed=1.0, rate=0.0001)
    )

    assert len(result.trades) == 2
    assert all(not trade.is_open for trade in result.trades)
    assert result.reconciles()


# ─── invariantes e bordas ────────────────────────────────────────────────────


@pytest.mark.unit
def test_cash_never_goes_negative_across_the_run() -> None:
    """ENG-04.4 — checada a cada barra pelo laço, não só no fim."""
    opens = [100.0, 100.0, 100.0, 100.0]
    series = _series(opens=opens, closes=opens)
    strategy = ScriptedStrategy(script={0: Signal.ENTER, 1: Signal.EXIT, 2: Signal.ENTER})

    result = run_backtest(
        series, strategy, initial_cash=1_000.0, costs=CostModel(fixed=1.0, rate=0.0001)
    )

    for point in result.equity_curve:
        assert point.cash >= 0.0


@pytest.mark.unit
def test_empty_series_is_rejected() -> None:
    series = _series(opens=[], closes=[])

    with pytest.raises(EngineError, match="vazia"):
        run_backtest(series, NeverTrades(), initial_cash=100.0, costs=_FREE)


@pytest.mark.unit
def test_result_carries_the_series_hash_for_reproducibility() -> None:
    """PER-03.1 — o relatório precisa poder citar a série consumida."""
    series = _series(opens=[10.0, 20.0], closes=[10.0, 20.0])

    result = run_backtest(series, NeverTrades(), initial_cash=100.0, costs=_FREE)

    assert result.series_hash == series.hash


@pytest.mark.unit
def test_a_strategy_the_engine_has_never_seen_runs_unchanged() -> None:
    """ENG-05.1 — protocolo estrutural: nada no engine sabe desta classe."""

    class Contrarian:
        """Definida aqui dentro, sem herdar de nada, sem registro."""

        warmup = 1

        def on_bar(self, view: MarketView) -> Signal | None:
            if float(view.close[-1]) < float(view.close[-2]):
                return Signal.ENTER
            return None

    series = _series(opens=[10.0, 9.0, 8.0, 8.0], closes=[10.0, 9.0, 8.0, 8.0])

    result = run_backtest(series, Contrarian(), initial_cash=1_000.0, costs=_FREE)

    assert len(result.trades) == 1
    assert result.reconciles()


@pytest.mark.unit
def test_strategy_cannot_reach_cash_or_positions_through_the_view() -> None:
    """ENG-05.2 — a estratégia não tem o que consultar sobre a carteira."""
    captured: list[MarketView] = []

    class Peeker:
        warmup = 0

        def on_bar(self, view: MarketView) -> Signal | None:
            captured.append(view)
            return None

    series = _series(opens=[10.0, 20.0], closes=[10.0, 20.0])
    run_backtest(series, Peeker(), initial_cash=1_000.0, costs=_FREE)

    view = captured[0]
    for forbidden in ("cash", "positions", "portfolio", "trades", "broker", "costs"):
        assert not hasattr(view, forbidden), forbidden


# ─── 2a (T11a): laço multi-ativo calendário-driven ───────────────────────────


@dataclass
class ScriptedConditional:
    """Emite intenções condicionais em índices fixos (SIG-01 no laço)."""

    script: dict[int, Signal | ConditionalIntent]
    warmup: int = 0

    def on_bar(self, view: MarketView) -> Signal | ConditionalIntent | None:
        return self.script.get(view.i)


@dataclass
class RecordingStrategy:
    """Registra (ticker, data, índice) de cada consulta — prova do MarketView."""

    warmup: int = 0
    seen: list[tuple[str, date, int]] = field(default_factory=list)

    def on_bar(self, view: MarketView) -> Signal | None:
        self.seen.append((view.ticker, view.date, view.i))
        return None


@dataclass
class LastCloseStrategy:
    """Estratégia com estado — prova de instâncias independentes."""

    warmup: int = 0
    last_close: float = 0.0
    series_length: int = 0

    def on_bar(self, view: MarketView) -> Signal | None:
        self.last_close = float(view.close[-1])
        self.series_length = len(view)
        return None


@pytest.mark.unit
def test_pending_order_executes_at_next_bar_of_own_asset() -> None:
    """CA-05.3/POR-05.3 — ADR-0002 por ativo: a pendente de X executa no open
    da PRÓXIMA barra de X, que pode estar várias datas-união depois (B não tem
    barra em d1/d2; a ordem decide em d0 e executa em d3)."""
    series = {
        "A": _series([10, 11, 12, 13], [10, 11, 12, 13], ticker="A", dates=_dates(4)),
        "B": _series([20, 24], [20, 24], ticker="B", dates=[_D0, _D0 + timedelta(days=3)]),
    }
    strategies = {"B": ScriptedStrategy({0: Signal.ENTER})}

    result = run_backtest_multi(series, strategies, costs=_FREE, slippage=_NO_SLIP)

    trades = [t for t in result.portfolio.trades if t.ticker == "B"]
    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_date == _D0 + timedelta(days=3)  # próxima barra DO PRÓPRIO ativo
    assert trade.entry_price == pytest.approx(24.0)  # open de B em d3
    assert trade.entry_decision_date == _D0
    assert trade.entry_gap_days == 3
    assert len(result.equity_curve) == 4  # união [d0, d1, d2, d3]


@pytest.mark.unit
def test_last_bar_intention_dies_pending_per_asset() -> None:
    """ENG-01.4 por ativo (C1) — intenção na ÚLTIMA barra da série morre
    pendente: ENTER não vira ordem, EXIT não agenda saída; contada e
    reportada (não afeta a contabilidade)."""
    series = {"A": _series([10, 11, 12], [10, 11, 12], ticker="A", dates=_dates(3))}

    enter_last = run_backtest_multi(
        series, {"A": ScriptedStrategy({2: Signal.ENTER})}, costs=_FREE, slippage=_NO_SLIP
    )
    assert enter_last.portfolio.trades == []
    assert enter_last.portfolio.pending.pending_for("A") == ()
    assert enter_last.pending_dead == {"A": 1}

    exit_last = run_backtest_multi(
        series,
        {"A": ScriptedStrategy({0: Signal.ENTER, 2: Signal.EXIT})},
        costs=_FREE,
        slippage=_NO_SLIP,
    )
    assert exit_last.pending_dead == {"A": 1}
    assert "A" in exit_last.portfolio.positions  # a saída morreu — posição fica aberta
    assert len(exit_last.portfolio.trades) == 1  # só a entrada


@pytest.mark.unit
def test_market_view_contains_only_own_asset_bars() -> None:
    """CA-05.1/POR-02.4 — a estratégia de X só vê barras do PRÓPRIO ativo: a
    sequência (data, índice) recebida é a da série de X, nunca a da união."""
    series = {
        "A": _series([10, 11, 12, 13], [10, 11, 12, 13], ticker="A", dates=_dates(4)),
        "B": _series([20, 22], [20, 22], ticker="B", dates=[_D0, _D0 + timedelta(days=2)]),
    }
    rec_a = RecordingStrategy()
    rec_b = RecordingStrategy()

    run_backtest_multi(series, {"A": rec_a, "B": rec_b}, costs=_FREE)

    assert all(t == "A" for t, _, _ in rec_a.seen)
    assert [d for _, d, _ in rec_a.seen] == _dates(4)
    assert [i for _, _, i in rec_a.seen] == [0, 1, 2, 3]
    assert all(t == "B" for t, _, _ in rec_b.seen)
    assert [d for _, d, _ in rec_b.seen] == [_D0, _D0 + timedelta(days=2)]
    assert [i for _, _, i in rec_b.seen] == [0, 1]


@pytest.mark.unit
def test_n_independent_strategy_instances_each_see_own_asset() -> None:
    """CA-03.1 — instâncias independentes: o estado de cada estratégia só
    reflete o PRÓPRIO ativo (nada vaza entre elas)."""
    series = {
        "A": _series([10, 11, 12], [10, 11, 12], ticker="A", dates=_dates(3)),
        "B": _series([20, 21, 22], [20, 21, 22], ticker="B", dates=_dates(3)),
    }
    last_a = LastCloseStrategy()
    last_b = LastCloseStrategy()

    run_backtest_multi(series, {"A": last_a, "B": last_b}, costs=_FREE)

    assert last_a.last_close == pytest.approx(12.0)  # close de A
    assert last_a.series_length == 3
    assert last_b.last_close == pytest.approx(22.0)  # close de B
    assert last_b.series_length == 3


@pytest.mark.unit
def test_fase1_strategy_runs_unchanged_multi_asset() -> None:
    """SIG-01.1/CA-03.2 — SmaCross da Fase 1 roda no laço multi-ativo SEM
    mudança: as decisões (datas e preços de entrada/saída) são idênticas às do
    run single-asset; só o TAMANHO difere (sizing 1/N vs all-in da Fase 1)."""
    # Closes que cruzam DENTRO da janela do SmaCross: ENTER em i=3 (fast 11 x
    # slow 10.67, prev 0) e EXIT em i=6 (fast 11.5 x slow 11.67).
    closes_a: list[float] = [10.0, 10.0, 10.0, 12.0, 12.0, 12.0, 11.0, 10.0]
    series_a = _series(closes_a, closes_a, ticker="A", dates=_dates(8))
    closes_b: list[float] = [20.0, 20.0, 20.0, 22.0, 22.0, 22.0, 21.0, 20.0]
    series_b = _series(closes_b, closes_b, ticker="B", dates=_dates(8))
    single = run_backtest(series_a, SmaCross(fast=2, slow=3), costs=_FREE)
    multi = run_backtest_multi(
        {"A": series_a, "B": series_b},
        {"A": SmaCross(fast=2, slow=3)},
        costs=_FREE,
        slippage=_NO_SLIP,
    )

    multi_a = [t for t in multi.portfolio.trades if t.ticker == "A"]
    assert len(single.trades) >= 1  # a fixture cruza de verdade
    assert len(multi_a) == len(single.trades)
    for mt, st in zip(multi_a, single.trades, strict=True):
        assert mt.entry_date == st.entry_date
        assert mt.entry_price == pytest.approx(st.entry_price)
        assert mt.exit_date == st.exit_date
        assert mt.exit_price == pytest.approx(st.exit_price)
    assert multi_a[0].quantity < single.trades[0].quantity  # 1/2 vs all-in


@pytest.mark.unit
def test_open_positions_never_exceed_n() -> None:
    """SIZ-04.3 — com N=2 e os dois ativos entrando, k chega a N=2 sem violar
    o invariante (checado a cada barra pelo laço, erro de programação)."""
    series = {
        "A": _series([10, 11, 12], [10, 11, 12], ticker="A", dates=_dates(3)),
        "B": _series([20, 21, 22], [20, 21, 22], ticker="B", dates=_dates(3)),
    }
    strategies = {
        "A": ScriptedStrategy({0: Signal.ENTER}),
        "B": ScriptedStrategy({0: Signal.ENTER}),
    }

    result = run_backtest_multi(series, strategies, costs=_FREE, slippage=_NO_SLIP)

    assert len(result.portfolio.positions) == 2  # k == N
    result.portfolio.check_invariants(n=2)


@pytest.mark.unit
def test_no_rebalance_without_k_change() -> None:
    """SIZ-03.1/03.4 — EqualWeightOpen: k mudou ⇒ evento de rebalance gerado
    (CA-03.1); k estável com os preços se movendo ⇒ NENHUM rebalance (CA-03.4)."""
    # N=2 para o seed 1/2 (N=1 seria all-in, peso ~1.0, desvio ~0).
    series = {
        "A": _series([10, 11, 12, 13, 14], [10, 11, 12, 13, 14], ticker="A", dates=_dates(5)),
        "B": _series([20, 21, 22, 23, 24], [20, 21, 22, 23, 24], ticker="B", dates=_dates(5)),
    }
    strategies = {"A": ScriptedStrategy({0: Signal.ENTER})}

    result = run_backtest_multi(
        series, strategies, costs=_FREE, slippage=_NO_SLIP, sizer=EqualWeightOpen(threshold_pp=1.0)
    )

    # ENTER (1) + rebalance compra após k 0→1 (2). Depois k=1 estável e os
    # preços sobem (marcação muda) — nenhum trade novo (CA-03.4).
    assert [t.rebalance for t in result.portfolio.trades] == [False, True]
    assert len(result.equity_curve) == 5
    assert result.portfolio.positions["A"].quantity > 0


@pytest.mark.unit
def test_rebalance_threshold_pp_gates_adjustment() -> None:
    """SIZ-03.3 — mesmo cenário, dois limiares: desvio 45 pp < 60 ⇒ nenhum
    trade de rebalance; limiar 1 pp ⇒ trade de rebalance gerado."""
    series = {
        "A": _series([10, 11, 12, 13], [10, 11, 12, 13], ticker="A", dates=_dates(4)),
        "B": _series([20, 21, 22, 23], [20, 21, 22, 23], ticker="B", dates=_dates(4)),
    }
    strategies = {"A": ScriptedStrategy({0: Signal.ENTER})}

    gated = run_backtest_multi(
        series, strategies, costs=_FREE, slippage=_NO_SLIP, sizer=EqualWeightOpen(threshold_pp=60.0)
    )
    active = run_backtest_multi(
        series, strategies, costs=_FREE, slippage=_NO_SLIP, sizer=EqualWeightOpen(threshold_pp=1.0)
    )

    assert len(gated.portfolio.trades) == 1  # só a entrada
    assert gated.portfolio.trades[0].rebalance is False
    assert len(active.portfolio.trades) == 2  # entrada + rebalance
    assert active.portfolio.trades[1].rebalance is True


@pytest.mark.unit
def test_multi_asset_run_is_deterministic() -> None:
    """RNF-01 — mesma entrada ⇒ mesmo resultado: equity, trades, marcas e
    pendentes mortas idênticas em dois runs independentes."""

    def run_once() -> BacktestResultMulti:
        series = {
            "A": _series([10, 11, 12], [10, 11, 12], ticker="A", dates=_dates(3)),
            "B": _series([20, 21, 22], [20, 21, 22], ticker="B", dates=_dates(3)),
        }
        return run_backtest_multi(
            series, {"A": ScriptedStrategy({0: Signal.ENTER})}, costs=_FREE, slippage=_NO_SLIP
        )

    first = run_once()
    second = run_once()
    assert first.equity_curve == second.equity_curve
    assert first.portfolio.trades == second.portfolio.trades
    assert dict(first.portfolio.marks) == dict(second.portfolio.marks)
    assert first.pending_dead == second.pending_dead


@pytest.mark.unit
def test_equity_of_bar_does_not_depend_on_signal_multi_asset() -> None:
    """ENG-05.2 estendido — a consulta não tem efeito colateral: a equity da
    barra de decisão é a mesma com ou sem sinal (o ENTER executa na PRÓXIMA
    barra do próprio ativo — ADR-0002)."""
    # open = close em d0/d1 (equity plana até a decisão); d2 fecha acima do
    # open de execução — o ENTER de d1 compra no open[2]=12 e o close[2]=13
    # muda a equity SÓ a partir da barra seguinte à decisão.
    series = {"A": _series([10, 11, 12, 13], [10, 11, 13, 13], ticker="A", dates=_dates(4))}
    with_signal = run_backtest_multi(
        series, {"A": ScriptedStrategy({1: Signal.ENTER})}, costs=_FREE, slippage=_NO_SLIP
    )
    without = run_backtest_multi(
        series, {"A": ScriptedStrategy({})}, costs=_FREE, slippage=_NO_SLIP
    )

    assert with_signal.equity_curve[:2] == without.equity_curve[:2]
    assert with_signal.equity_curve[2] != without.equity_curve[2]  # só depois da execução


@pytest.mark.unit
def test_conditional_intent_flows_through_the_loop() -> None:
    """SIG-01 no laço — ConditionalIntent(LIMIT) da estratégia vira pendente e
    preenche a min(L, open) na próxima barra do próprio ativo (SLP-04.2)."""
    series = {"A": _series([10, 11, 12, 12], [10, 11, 12, 12], ticker="A", dates=_dates(4))}
    strategies = {
        "A": ScriptedConditional(
            {0: ConditionalIntent(signal=Signal.ENTER, order_type=OrderKind.LIMIT, limit=11.0)}
        )
    }

    result = run_backtest_multi(series, strategies, costs=_FREE, slippage=_NO_SLIP)

    trades = result.portfolio.trades
    assert len(trades) == 1
    assert trades[0].entry_date == _D0 + timedelta(days=1)
    assert trades[0].entry_price == pytest.approx(11.0)  # min(11, open 11) — sem slippage
    assert trades[0].origin == TradeOrigin.LIMIT


@pytest.mark.unit
def test_run_backtest_multi_domain_errors() -> None:
    """§3.8 — pré-condições do laço: universo/estratégias vazios, ticker fora
    do run, warmup negativo e cap fora de (0, 1] são EngineError."""
    series = {"A": _series([10, 11, 12], [10, 11, 12], ticker="A", dates=_dates(3))}

    with pytest.raises(EngineError, match="universo vazio"):
        run_backtest_multi({}, {})
    with pytest.raises(EngineError, match="nenhuma estratégia"):
        run_backtest_multi(series, {})
    with pytest.raises(EngineError, match="fora do run"):
        run_backtest_multi(series, {"Z": ScriptedStrategy({})})
    with pytest.raises(EngineError, match="warmup negativo"):
        run_backtest_multi(series, {"A": ScriptedStrategy({}, warmup=-1)})
    with pytest.raises(EngineError, match="cap fora"):
        run_backtest_multi(series, {"A": ScriptedStrategy({})}, cap=0.0)


# ─── 2a (T11b): último close conhecido, deslistagem e interação de caixa ─────


@dataclass
class FixedFractionSizer:
    """Sizer de teste: fração fixa por ativo (SIZ-04.2) — controla o notional
    para o teste de atendimento alfabético sem depender de preço."""

    fraction: float

    def target_fraction(self, ticker: str, inputs: SizingInputs) -> float:
        return self.fraction


@pytest.mark.unit
def test_asset_without_bar_is_marked_with_last_close() -> None:
    """CA-05.2/POR-02.2 — ativo sem barra na data-união é marcado pelo ÚLTIMO
    CLOSE CONHECIDO (nada de preço inventado nem da data seguinte): em d2, B
    não tem barra e a equity usa close_B(d1) = 21 (usar close(d3) = 22 daria
    102.500, não 100.000)."""
    series = {
        "A": _series([10, 10, 10, 10], [10, 10, 10, 10], ticker="A", dates=_dates(4)),
        # B NÃO tem barra em d2 — buraco no meio da união.
        "B": _series(
            [20, 21, 22],
            [20, 21, 22],
            ticker="B",
            dates=[_D0, _D0 + timedelta(days=1), _D0 + timedelta(days=3)],
        ),
    }
    strategies = {"B": ScriptedStrategy({0: Signal.ENTER})}

    result = run_backtest_multi(series, strategies, costs=_FREE, slippage=_NO_SLIP)

    # B: decide em d0 (ref 20), 1/2 do patrimônio ⇒ 2_500 ações; executa em
    # d1 a 21 ⇒ caixa 47_500.
    assert result.portfolio.positions["B"].quantity == 2_500
    assert result.equity_curve[2] == pytest.approx(47_500.0 + 2_500 * 21.0)  # close de d1
    assert result.equity_curve[3] == pytest.approx(47_500.0 + 2_500 * 22.0)  # barra de d3


@pytest.mark.unit
def test_delisted_position_is_locked_and_reported() -> None:
    """POR-02.3 — série de B termina antes do fim da união com posição aberta:
    posição TRAVADA (marcada pelo último close, nunca liquidada) e REPORTADA
    em `result.delisted`; determinístico."""

    def run_once() -> BacktestResultMulti:
        series = {
            "A": _series([10, 10, 10, 10, 10], [10, 10, 10, 10, 10], ticker="A", dates=_dates(5)),
            # B deslista em d2 — a série termina antes do fim da união (d4).
            "B": _series([20, 21, 22], [20, 21, 22], ticker="B", dates=_dates(3)),
        }
        return run_backtest_multi(
            series, {"B": ScriptedStrategy({0: Signal.ENTER})}, costs=_FREE, slippage=_NO_SLIP
        )

    first = run_once()
    second = run_once()
    assert first.delisted == second.delisted  # determinismo (RNF-01)
    assert first.delisted == ("B",)  # reportada; A (sem posição) não entra
    position = first.portfolio.positions["B"]
    assert position.quantity == 2_500
    # Nunca liquidada: B não tem trade com saída e a posição segue aberta.
    b_trades = [t for t in first.portfolio.trades if t.ticker == "B"]
    assert len(b_trades) == 1
    assert b_trades[0].exit_date is None
    # Marcada pelo último close conhecido até o fim (22), não liquidada.
    assert first.final_equity == pytest.approx(47_500.0 + 2_500 * 22.0)
    assert first.portfolio.marks["B"] == pytest.approx(22.0)


@pytest.mark.unit
def test_second_entry_sees_cash_already_debited(
    log_events: list[EventDict],
) -> None:
    """ORD-04.3 (gate 1) — duas entradas na mesma barra: a primeira (A,
    alfabética) debita o caixa; a SEGUNDA vê o caixa já debitado e não
    preenche (0 ações, evento logado). Rodar B sozinho prova que B
    preencheria com o caixa cheio."""
    # A: 9_000 x 10 = 90_000 (fração 0.9). B: 4 x 20_000 = 80_000 (0.9) —
    # cabe com 100_000, mas NÃO com o caixa pós-A (10_000 < 20_000).
    series = {
        "A": _series([10, 10], [10, 10], ticker="A", dates=_dates(2)),
        "B": _series([20_000, 20_000], [20_000, 20_000], ticker="B", dates=_dates(2)),
    }
    strategies = {
        "A": ScriptedStrategy({0: Signal.ENTER}),
        "B": ScriptedStrategy({0: Signal.ENTER}),
    }

    result = run_backtest_multi(
        series, strategies, costs=_FREE, slippage=_NO_SLIP, sizer=FixedFractionSizer(0.9)
    )

    assert result.portfolio.positions["A"].quantity == 9_000  # atendida primeiro
    assert "B" not in result.portfolio.positions  # não preencheu NADA
    assert [t.ticker for t in result.portfolio.trades] == ["A"]
    assert any(
        e["event"] == "engine.insufficient_cash" and e.get("ticker") == "B" for e in log_events
    )

    # Prova do "já debitado": B sozinho, com o caixa cheio, preenche as 4.
    solo = run_backtest_multi(
        {"B": series["B"]},
        {"B": ScriptedStrategy({0: Signal.ENTER})},
        costs=_FREE,
        slippage=_NO_SLIP,
        sizer=FixedFractionSizer(0.9),
    )
    assert solo.portfolio.positions["B"].quantity == 4


@pytest.mark.unit
def test_alphabetical_serving_with_insufficient_cash() -> None:
    """CA-01.2/POR-01.2 — atendimento ALFABÉTICO com caixa insuficiente: o
    primeiro ticker em ordem alfabética é servido; o segundo fica com o que
    sobra. Runs espelhados (nomes trocados) provam que a regra é a ORDEM do
    nome, não preço/tamanho."""
    cheap = _series([10, 10], [10, 10], ticker="X", dates=_dates(2))  # alvo 9_000
    expensive = _series([20_000, 20_000], [20_000, 20_000], ticker="Y", dates=_dates(2))  # alvo 4

    # Run 1: barato = "A", caro = "B" → A serve 9_000 cheio; B não cabe (0).
    run1 = run_backtest_multi(
        {"A": cheap, "B": expensive},
        {"A": ScriptedStrategy({0: Signal.ENTER}), "B": ScriptedStrategy({0: Signal.ENTER})},
        costs=_FREE,
        slippage=_NO_SLIP,
        sizer=FixedFractionSizer(0.9),
    )
    # Run 2: caro = "A", barato = "B" → A (caro) serve 4 cheio; B (barato)
    # fica com o que sobra (1_000 a 10 com os 10_000 restantes).
    run2 = run_backtest_multi(
        {"A": expensive, "B": cheap},
        {"A": ScriptedStrategy({0: Signal.ENTER}), "B": ScriptedStrategy({0: Signal.ENTER})},
        costs=_FREE,
        slippage=_NO_SLIP,
        sizer=FixedFractionSizer(0.9),
    )

    assert run1.portfolio.positions["A"].quantity == 9_000
    assert "B" not in run1.portfolio.positions
    assert run2.portfolio.positions["A"].quantity == 4  # servido por inteiro
    # A deixou 20_000; B (barato) fica com o restante: 2_000 x 10 (corte CASH).
    assert run2.portfolio.positions["B"].quantity == 2_000
    # Quem ficou com o corte de CAIXA foi SEMPRE o segundo em ordem alfabética
    # (o caro tem corte INTEGER na conversão: 4,5 -> 4 ações).
    assert [t.cut_reason for t in run1.portfolio.trades] == [None]
    assert sorted(
        t.cut_reason.value if t.cut_reason is not None else "" for t in run2.portfolio.trades
    ) == [
        "cash",
        "integer",
    ]
