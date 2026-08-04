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

from quantlab.engine.backtest import run_backtest
from quantlab.engine.broker import CostModel
from quantlab.engine.market_view import MarketView
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries

_FREE = CostModel(fixed=0.0, rate=0.0)


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
