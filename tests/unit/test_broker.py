"""C4 — `Broker` e custos (ENG-02.1 a ENG-02.3, ENG-03.1, ENG-03.2).

**Escrito antes da implementação**, como a tarefa manda. A fixture que importa
é `test_ignoring_the_cost_would_produce_negative_cash`: ela é construída para
que a conta ingênua (`q = caixa // preço`) estoure o caixa, e é o único jeito
de provar que o custo entrou no cálculo do tamanho em vez de ser debitado
depois. Design §4.4 chama esse erro pelo nome.
"""

from datetime import date

import pytest
from structlog.typing import EventDict

from quantlab.engine.broker import Broker, CostModel
from quantlab.engine.portfolio import Portfolio
from quantlab.exceptions import EngineError

_TICKER = "TEST"
_TODAY = date(2024, 1, 3)
_DECIDED = date(2024, 1, 2)


# ─── modelo de custo (ENG-03.1, decisão D2) ──────────────────────────────────


@pytest.mark.unit
def test_default_cost_is_one_bps_plus_one_dollar() -> None:
    """Decisão D2 do requirements: 1 bps sobre o notional + USD 1 por trade.

    Sobre um notional de 10.000: 10.000 * 0.0001 = 1.00, mais 1.00 fixo = 2.00.
    """
    assert CostModel().cost_for(10_000.0) == pytest.approx(2.0)


@pytest.mark.unit
def test_zero_cost_model_charges_nothing() -> None:
    """ENG-03.2 — custo zero é configurável (e o relatório sinaliza, em E3)."""
    assert CostModel(fixed=0.0, rate=0.0).cost_for(10_000.0) == pytest.approx(0.0)


@pytest.mark.unit
def test_cost_scales_with_the_notional() -> None:
    model = CostModel(fixed=1.0, rate=0.0001)
    assert model.cost_for(0.0) == pytest.approx(1.0)
    assert model.cost_for(100_000.0) == pytest.approx(11.0)


# ─── ENG-02.1: quantidade máxima COM custo ───────────────────────────────────


@pytest.mark.unit
def test_ignoring_the_cost_would_produce_negative_cash() -> None:
    """A fixture central de C4 — design §4.4 diz que é o erro a vigiar.

    Caixa 1_000.00, preço 100.00, custo fixo de 1.00 e 0% variável.

    Conta ingênua:  q = 1000 // 100 = 10  ->  10 * 100 = 1000.00 de notional
                    + 1.00 de custo = 1001.00  ->  CAIXA -1.00. Negativo.
    Conta correta:  q = 9  ->  9 * 100 = 900.00 + 1.00 = 901.00
                    ->  caixa 99.00. Positivo.

    Se a implementação ignorar o custo no dimensionamento, este teste falha em
    dois lugares ao mesmo tempo: a quantidade vira 10 e o caixa vira negativo.
    """
    broker = Broker(CostModel(fixed=1.0, rate=0.0))
    portfolio = Portfolio(cash=1_000.0)

    quantity = broker.max_affordable_quantity(portfolio.cash, price=100.0)

    assert quantity == 9, "ignorou o custo no cálculo do tamanho"

    broker.buy(
        portfolio,
        ticker=_TICKER,
        price=100.0,
        execution_date=_TODAY,
        decision_date=_DECIDED,
    )
    assert portfolio.cash == pytest.approx(99.0)
    assert portfolio.cash >= 0
    portfolio.check_invariants()


@pytest.mark.unit
def test_exact_fit_spends_the_cash_to_zero() -> None:
    """Caixa 1_001.00 com o mesmo custo compra as 10 e zera: 1000 + 1 = 1001."""
    broker = Broker(CostModel(fixed=1.0, rate=0.0))
    portfolio = Portfolio(cash=1_001.0)

    assert broker.max_affordable_quantity(portfolio.cash, price=100.0) == 10

    broker.buy(
        portfolio, ticker=_TICKER, price=100.0, execution_date=_TODAY, decision_date=_DECIDED
    )
    assert portfolio.cash == pytest.approx(0.0)
    portfolio.check_invariants()


@pytest.mark.unit
def test_variable_cost_also_enters_the_sizing() -> None:
    """Com 1 bps, o custo depende de q — a conta não é uma divisão simples.

    Caixa 1_000.00, preço 100.00, custo = 1.00 + 0.0001 * notional.
    q = 9:  900.00 + 1.00 + 0.09  =  901.09   <= 1000  OK
    q = 10: 1000.00 + 1.00 + 0.10 = 1001.10   >  1000  estoura
    """
    broker = Broker(CostModel(fixed=1.0, rate=0.0001))

    assert broker.max_affordable_quantity(1_000.0, price=100.0) == 9


# ─── ENG-02.3: quantidade zero ───────────────────────────────────────────────


@pytest.mark.unit
def test_insufficient_cash_for_one_share_buys_nothing(log_events: list[EventDict]) -> None:
    """ENG-02.3 — nenhuma ordem é gerada, e o evento é logado."""
    broker = Broker(CostModel(fixed=1.0, rate=0.0))
    portfolio = Portfolio(cash=50.0)

    executed = broker.buy(
        portfolio, ticker=_TICKER, price=100.0, execution_date=_TODAY, decision_date=_DECIDED
    )

    assert executed is None
    assert portfolio.positions == {}
    assert portfolio.trades == []
    assert portfolio.cash == pytest.approx(50.0)
    assert [e for e in log_events if e["event"] == "engine.insufficient_cash"]


@pytest.mark.unit
def test_cash_exactly_one_cent_short_buys_nothing() -> None:
    """Preço 100.00 + custo 1.00 = 101.00; com 100.99 não dá para uma ação."""
    broker = Broker(CostModel(fixed=1.0, rate=0.0))
    assert broker.max_affordable_quantity(100.99, price=100.0) == 0


# ─── ENG-03.1: custo debitado e registrado ───────────────────────────────────


@pytest.mark.unit
def test_entry_cost_is_debited_and_recorded_on_the_trade() -> None:
    broker = Broker(CostModel(fixed=1.0, rate=0.0001))
    portfolio = Portfolio(cash=10_000.0)

    trade = broker.buy(
        portfolio, ticker=_TICKER, price=100.0, execution_date=_TODAY, decision_date=_DECIDED
    )

    assert trade is not None
    # q = 99: 9900.00 + 1.00 + 0.99 = 9901.99  <= 10000  cabe
    # q = 100: 10000.00 + 1.00 + 1.00 = 10002.00  >  10000  estoura
    assert trade.quantity == 99
    assert trade.entry_cost == pytest.approx(1.99)
    assert portfolio.cash == pytest.approx(98.01)
    portfolio.check_invariants()


@pytest.mark.unit
def test_zero_cost_model_leaves_cash_untouched_beyond_the_notional() -> None:
    """ENG-03.2 — sem custo, o caixa cai exatamente o notional."""
    broker = Broker(CostModel(fixed=0.0, rate=0.0))
    portfolio = Portfolio(cash=1_000.0)

    trade = broker.buy(
        portfolio, ticker=_TICKER, price=100.0, execution_date=_TODAY, decision_date=_DECIDED
    )

    assert trade is not None
    assert trade.quantity == 10
    assert trade.entry_cost == pytest.approx(0.0)
    assert portfolio.cash == pytest.approx(0.0)


# ─── ENG-02.2: saída liquida a posição inteira ───────────────────────────────


@pytest.mark.unit
def test_sell_liquidates_the_whole_position() -> None:
    """ENG-02.2 + decisão D3 — volta a 100% caixa, sem short."""
    broker = Broker(CostModel(fixed=1.0, rate=0.0))
    portfolio = Portfolio(cash=1_000.0)
    broker.buy(
        portfolio, ticker=_TICKER, price=100.0, execution_date=_TODAY, decision_date=_DECIDED
    )

    closed = broker.sell(
        portfolio,
        ticker=_TICKER,
        price=110.0,
        execution_date=date(2024, 1, 10),
        decision_date=date(2024, 1, 9),
    )

    assert closed is not None
    assert portfolio.positions == {}
    # 9 ações compradas a 100 (caixa 99.00), vendidas a 110 = 990.00, -1.00 custo
    assert portfolio.cash == pytest.approx(99.0 + 990.0 - 1.0)
    assert closed.exit_price == pytest.approx(110.0)
    assert closed.exit_cost == pytest.approx(1.0)
    assert closed.is_open is False
    portfolio.check_invariants()


@pytest.mark.unit
def test_realized_pnl_is_gross_of_costs() -> None:
    """Design §4.6 — PnL realizado é BRUTO; custos entram no termo próprio."""
    broker = Broker(CostModel(fixed=1.0, rate=0.0))
    portfolio = Portfolio(cash=1_000.0)
    broker.buy(
        portfolio, ticker=_TICKER, price=100.0, execution_date=_TODAY, decision_date=_DECIDED
    )
    closed = broker.sell(
        portfolio,
        ticker=_TICKER,
        price=110.0,
        execution_date=date(2024, 1, 10),
        decision_date=date(2024, 1, 9),
    )

    assert closed is not None
    # (110 - 100) * 9 = 90.00, BRUTO. Os 2.00 de custo não entram aqui.
    assert closed.realized_pnl == pytest.approx(90.0)
    assert closed.total_cost == pytest.approx(2.0)


@pytest.mark.unit
def test_selling_without_a_position_is_rejected() -> None:
    """Erro de programação: o laço só manda vender se há posição."""
    broker = Broker(CostModel())
    portfolio = Portfolio(cash=1_000.0)

    with pytest.raises(EngineError, match="sem posição"):
        broker.sell(
            portfolio,
            ticker=_TICKER,
            price=100.0,
            execution_date=_TODAY,
            decision_date=_DECIDED,
        )


# ─── gap de execução (ENG-01.5) ──────────────────────────────────────────────


@pytest.mark.unit
def test_entry_gap_days_records_calendar_distance_from_the_decision() -> None:
    """ENG-01.5 — o gap fica no trade, auditável, em dias CORRIDOS.

    Decisão na sexta 05/01, execução na segunda 08/01: 3 dias corridos.
    Dias corridos e não úteis de propósito: o que interessa a quem audita é
    quanto tempo real passou entre ver o fechamento e pagar a abertura.
    """
    broker = Broker(CostModel(fixed=0.0, rate=0.0))
    portfolio = Portfolio(cash=1_000.0)

    trade = broker.buy(
        portfolio,
        ticker=_TICKER,
        price=100.0,
        execution_date=date(2024, 1, 8),
        decision_date=date(2024, 1, 5),
    )

    assert trade is not None
    assert trade.entry_decision_date == date(2024, 1, 5)
    assert trade.entry_date == date(2024, 1, 8)
    assert trade.entry_gap_days == 3
