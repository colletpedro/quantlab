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

from quantlab.engine.broker import (
    Broker,
    ConvertedOrder,
    CostModel,
    CutStage,
    PendingBook,
)
from quantlab.engine.conditional import Bracket, ConditionalIntent, OrderKind
from quantlab.engine.portfolio import Portfolio
from quantlab.engine.sizing import FixedOneOverN, SizingInputs
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError

_TICKER = "TEST"
_TODAY = date(2024, 1, 3)
_DECIDED = date(2024, 1, 2)


# ─── helpers da T06 (conversão) ──────────────────────────────────────────────


def _inputs(
    equity: float,
    cash: float,
    n: int,
    last_close: dict[str, float],
    positions: dict[str, int] | None = None,
) -> SizingInputs:
    return SizingInputs(
        equity=equity,
        cash=cash,
        n=n,
        last_close=last_close,
        positions=positions or {},
    )


def _convert(
    broker: Broker,
    intent: Signal | ConditionalIntent,
    inputs: SizingInputs,
    *,
    adv: float | None = None,
    cost_model: CostModel | None = None,
    cap: float = 0.10,
    decision_date: date = _DECIDED,
    intent_seq: int = 1,
) -> ConvertedOrder | None:
    return broker.convert(
        intent=intent,
        ticker=_TICKER,
        inputs=inputs,
        sizer=FixedOneOverN(n=inputs.n),
        adv=adv,
        cost_model=cost_model or CostModel(),
        cap=cap,
        decision_date=decision_date,
        intent_seq=intent_seq,
    )


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


# ─── T06 — custo mínimo max(f + p·N, m) (CST-01 CA-01.1) ─────────────────────


@pytest.mark.unit
def test_cost_model_closed_form_max_of_f_plus_pn_and_m() -> None:
    """CA-01.1 — custo = max(f + p·N, m); default m=0 preserva a Fase 1.

    Forma fechada sobre papel:
    - CostModel() (f=1, p=1e-4, m=0): cost_for(10_000) = 1 + 1 = 2.0.
    - CostModel(min_cost=500): cost_for(100) = max(1.01, 500) = 500;
      cost_for(10_000_000) = max(1 + 1_000, 500) = 1_001.
    """
    default = CostModel()
    assert default.cost_for(10_000.0) == pytest.approx(2.0)
    assert default.min_cost == 0.0

    floored = CostModel(min_cost=500.0)
    assert floored.cost_for(100.0) == pytest.approx(500.0)
    assert floored.cost_for(10_000_000.0) == pytest.approx(1_001.0)

    with pytest.raises(EngineError):
        CostModel(min_cost=-1.0)


# ─── T06 — sequência de corte fixa (R1/CST-01.3) ─────────────────────────────


@pytest.mark.unit
def test_cut_sequence_order_and_reason_recorded() -> None:
    """CA-01.3/R1 — sequência SIZING → CAP → INTEIRAS → CAIXA/CUSTOS, com a
    última etapa que cortou registrada em `cut_reason`.

    Fixtures de papel (RNF-03), N=1 (all-in):
    - CAP corta: equity 1e6, ref 10 ⇒ alvo 100_000; adv 50_000, cap 10%
      ⇒ teto 5_000; caixa 1e6 cabe ⇒ qty 5_000, cut CAP, est_cost 6.00.
    - INTEIRAS corta: equity 1e6, ref 30, N=2 ⇒ 16_666.67 ⇒ 16_666,
      caixa 1e6 cabe ⇒ cut INTEGER, qty 16_666.
    - CAIXA corta: alvo 100_000, adv enorme (sem cap), caixa 500_000 ⇒
      q ≤ (500_000-1)/10.001 = 49_994, cut CASH.
    - Ambos cortam (sequência jamais invertida): cap → 5_000 e caixa
      30_000 ⇒ q ≤ (30_000-1)/10.001 = 2_999 ⇒ qty 2_999, cut CASH.
    """
    broker = Broker()

    # CAP
    capped = _convert(
        broker,
        Signal.ENTER,
        _inputs(equity=1_000_000.0, cash=1_000_000.0, n=1, last_close={_TICKER: 10.0}),
        adv=50_000.0,
    )
    assert capped is not None
    assert capped.qty == 5_000
    assert capped.cut_reason is CutStage.CAP
    assert capped.est_cost == pytest.approx(6.0)  # 1 + 1e-4 x 50_000

    # INTEIRAS
    integer = _convert(
        broker,
        Signal.ENTER,
        _inputs(equity=1_000_000.0, cash=1_000_000.0, n=2, last_close={_TICKER: 30.0}),
        adv=1e9,
    )
    assert integer is not None
    assert integer.qty == 16_666
    assert integer.cut_reason is CutStage.INTEGER

    # CAIXA
    cash_cut = _convert(
        broker,
        Signal.ENTER,
        _inputs(equity=1_000_000.0, cash=500_000.0, n=1, last_close={_TICKER: 10.0}),
        adv=1e9,
    )
    assert cash_cut is not None
    assert cash_cut.qty == 49_994
    assert cash_cut.cut_reason is CutStage.CASH

    # CAP + CAIXA — a sequência jamais inverte: o teto vem antes do caixa.
    both = _convert(
        broker,
        Signal.ENTER,
        _inputs(equity=1_000_000.0, cash=30_000.0, n=1, last_close={_TICKER: 10.0}),
        adv=50_000.0,
    )
    assert both is not None
    assert both.qty == 2_999  # min(teto 5_000, caixa 2_999) — cap aplicado primeiro
    assert both.cut_reason is CutStage.CASH  # última etapa que cortou


@pytest.mark.unit
def test_cash_stage_respects_min_cost_piecewise() -> None:
    """CA-01.2 — reduce-until-fits com mínimo m: a região do mínimo domina.

    cash 1_000, price 1, custo f=1, p=1e-4, m=500:
    q·1 + max(1 + 1e-4·q, 500) ≤ 1_000 ⇒ q·1 + 500 ≤ 1_000 ⇒ q = 500.
    O candidato linear (999/1.0001 ≈ 998) é inválido: 998 + 500 > 1_000.
    """
    broker = Broker(CostModel(fixed=1.0, rate=1e-4, min_cost=500.0))
    assert broker.max_affordable_quantity(1_000.0, 1.0) == 500


@pytest.mark.unit
def test_convert_returns_none_and_logs_when_nothing_fits(
    log_events: list[EventDict],
) -> None:
    """CST-01.2/ENG-02.3 — caixa que não compra nem 1 ação ⇒ None + log."""
    broker = Broker()
    order = _convert(
        broker,
        Signal.ENTER,
        _inputs(equity=1_000.0, cash=1.0, n=1, last_close={_TICKER: 10.0}),
    )

    assert order is None
    assert any(event["event"] == "engine.insufficient_cash" for event in log_events)


@pytest.mark.unit
def test_convert_returns_none_and_logs_below_one_share(
    log_events: list[EventDict],
) -> None:
    """SLP-03.5/CST-01.2 — alvo abaixo de 1 ação inteira ⇒ None + log."""
    broker = Broker()
    order = _convert(
        broker,
        Signal.ENTER,
        _inputs(equity=10.0, cash=10.0, n=1, last_close={_TICKER: 100.0}),
    )

    assert order is None
    assert any(event["event"] == "engine.order_below_one_share" for event in log_events)


@pytest.mark.unit
def test_convert_is_deterministic_and_carries_audit_fields() -> None:
    """RNF-01 + ORD-04.2/04.4 — mesma entrada ⇒ mesma ordem; decision_date e
    intent_seq presentes (base da auditoria do ENG-01.2)."""
    broker = Broker()
    inputs = _inputs(equity=100_000.0, cash=100_000.0, n=4, last_close={_TICKER: 10.0})

    first = _convert(broker, Signal.ENTER, inputs, decision_date=_DECIDED, intent_seq=7)
    second = _convert(broker, Signal.ENTER, inputs, decision_date=_DECIDED, intent_seq=7)

    assert first == second
    assert first is not None
    assert first.decision_date == _DECIDED
    assert first.intent_seq == 7


@pytest.mark.unit
def test_convert_maps_kind_limit_stop_and_bracket_from_intent() -> None:
    """SIG-01.2/01.3 — o `ConvertedOrder` carrega o vocabulário da intenção.

    Signal ⇒ MARKET sem preços; ConditionalIntent LIMIT ⇒ kind LIMIT com
    limit; intenção com bracket ⇒ bracket=True e stop = bracket.stop (o par
    vive na mesma intenção; T07 deriva os pendings).
    """
    broker = Broker()
    inputs = _inputs(equity=100_000.0, cash=100_000.0, n=1, last_close={_TICKER: 10.0})

    market = _convert(broker, Signal.ENTER, inputs)
    assert market is not None
    assert market.kind is OrderKind.MARKET
    assert market.limit is None and market.stop is None
    assert market.bracket is False

    limit = _convert(
        broker,
        ConditionalIntent(Signal.ENTER, OrderKind.LIMIT, limit=9.5),
        inputs,
    )
    assert limit is not None
    assert limit.kind is OrderKind.LIMIT
    assert limit.limit == pytest.approx(9.5)
    assert limit.stop is None and limit.bracket is False

    bracket = _convert(
        broker,
        ConditionalIntent(
            Signal.ENTER,
            OrderKind.LIMIT,
            limit=10.5,
            bracket=Bracket(limit=10.5, stop=9.0),
        ),
        inputs,
    )
    assert bracket is not None
    assert bracket.kind is OrderKind.LIMIT
    assert bracket.limit == pytest.approx(10.5)
    assert bracket.stop == pytest.approx(9.0)  # stop do par na mesma intenção
    assert bracket.bracket is True


@pytest.mark.unit
def test_convert_domain_errors_raise_engine_error() -> None:
    """§3.8 — saída, buy-stop (2b), ticker sem last_close e ref_price ≤ 0 são
    erro de programação (EngineError)."""
    broker = Broker()
    base = _inputs(equity=100_000.0, cash=100_000.0, n=1, last_close={_TICKER: 10.0})

    with pytest.raises(EngineError):
        _convert(broker, Signal.EXIT, base)
    with pytest.raises(EngineError):
        _convert(broker, ConditionalIntent(Signal.EXIT, OrderKind.MARKET), base)
    # Buy-stop é escopo da 2b (P2) — ENTER com STOP não existe na 2a.
    with pytest.raises(EngineError):
        _convert(broker, ConditionalIntent(Signal.ENTER, OrderKind.STOP, stop=11.0), base)

    without_close = _inputs(equity=100_000.0, cash=100_000.0, n=1, last_close={})
    with pytest.raises(EngineError):
        _convert(broker, Signal.ENTER, without_close)

    bad_price = _inputs(equity=100_000.0, cash=100_000.0, n=1, last_close={_TICKER: 0.0})
    with pytest.raises(EngineError):
        _convert(broker, Signal.ENTER, bad_price)

    # Guardas do helper de caixa/custos (Fase 1 preservada).
    with pytest.raises(EngineError):
        broker.max_affordable_quantity(1_000.0, 0.0)  # preço não positivo
    assert broker.max_affordable_quantity(-5.0, 10.0) == 0  # caixa negativo ⇒ 0


# ─── T07 — ciclo de vida de ordens (RF-ORD-04/S3) ────────────────────────────


def _converted(
    kind: OrderKind = OrderKind.MARKET,
    *,
    limit: float | None = None,
    stop: float | None = None,
    qty: int = 100,
    seq: int = 1,
    bracket: bool = False,
    ticker: str = _TICKER,
) -> ConvertedOrder:
    return ConvertedOrder(
        ticker=ticker,
        kind=kind,
        limit=limit,
        stop=stop,
        qty=qty,
        ref_price=10.0,
        decision_date=_DECIDED,
        intent_seq=seq,
        cut_reason=None,
        est_cost=2.0,
        bracket=bracket,
    )


@pytest.mark.unit
def test_last_intention_wins_replaces_pending() -> None:
    """ORD-04.2 — a segunda intenção substitui as pendentes do mesmo ativo;
    a ordem antiga jamais fica no book (nunca vai executar)."""
    broker = Broker()
    book = PendingBook()

    broker.place(book, _converted(seq=1))
    assert len(book.pending_for(_TICKER)) == 1

    broker.place(book, _converted(kind=OrderKind.LIMIT, limit=9.5, seq=2))
    pending = book.pending_for(_TICKER)
    assert len(pending) == 1
    assert pending[0].intent_seq == 2
    assert pending[0].kind is OrderKind.LIMIT
    assert pending[0].limit == pytest.approx(9.5)

    # Bracket (seq 3) substitui a intenção 2 e instala o PAR limite+stop.
    broker.place(book, _converted(kind=OrderKind.LIMIT, limit=10.5, stop=9.0, seq=3, bracket=True))
    pair = book.pending_for(_TICKER)
    assert [p.kind for p in pair] == [OrderKind.LIMIT, OrderKind.STOP]
    assert all(p.intent_seq == 3 for p in pair)  # mesma intenção (SIG-01.3)
    assert all(p.decision_date == _DECIDED for p in pair)


@pytest.mark.unit
def test_place_only_touches_the_same_asset_and_is_deterministic() -> None:
    """ORD-04.2 — substituição é por ativo; outros ativos ficam intactos;
    a mesma sequência produz o mesmo book (RNF-01)."""
    broker = Broker()

    first = PendingBook()
    broker.place(first, _converted(seq=1))
    broker.place(first, _converted(ticker="OTHER", seq=5))
    broker.place(first, _converted(kind=OrderKind.LIMIT, limit=9.0, seq=2))
    assert [p.intent_seq for p in first.pending_for(_TICKER)] == [2]
    assert [p.intent_seq for p in first.pending_for("OTHER")] == [5]  # intacto

    second = PendingBook()
    broker.place(second, _converted(seq=1))
    broker.place(second, _converted(ticker="OTHER", seq=5))
    broker.place(second, _converted(kind=OrderKind.LIMIT, limit=9.0, seq=2))
    assert first.pending_for(_TICKER) == second.pending_for(_TICKER)
    assert first.pending_for("OTHER") == second.pending_for("OTHER")


@pytest.mark.unit
def test_place_never_touches_cash() -> None:
    """ORD-04.3 — sem reserva de caixa: `place` não tem caixa nenhuma no
    contrato; duas entradas na mesma barra apenas populam o book, na ordem
    de intenção, sem debitar nada (o caixa entra só na execução — T08)."""
    broker = Broker()
    book = PendingBook()

    broker.place(book, _converted(seq=1))
    broker.place(book, _converted(seq=2))

    assert [p.intent_seq for p in book.pending_for(_TICKER)] == [2]
    assert book.orders == {_TICKER: [book.pending_for(_TICKER)[0]]}


@pytest.mark.unit
def test_exit_cancels_all_pending_including_stops() -> None:
    """ORD-04.1 — EXIT (cancel_all) remove TODAS as pendentes do ativo,
    incluindo o stop do bracket; nada sobra para executar depois."""
    broker = Broker()
    book = PendingBook()
    broker.place(book, _converted(kind=OrderKind.LIMIT, limit=10.5, stop=9.0, seq=1, bracket=True))
    assert len(book.pending_for(_TICKER)) == 2

    broker.cancel_all(book, _TICKER)
    assert book.pending_for(_TICKER) == ()

    # Ativo sem pendentes: cancel_all é no-op, não erro.
    broker.cancel_all(book, "GHOST")


@pytest.mark.unit
def test_pending_lifecycle_domain_errors() -> None:
    """§3.8 — bracket malformado (sem limit/stop) é EngineError."""
    broker = Broker()
    book = PendingBook()

    malformed = _converted(kind=OrderKind.MARKET, bracket=True)
    with pytest.raises(EngineError):
        broker.place(book, malformed)
    assert book.pending_for(_TICKER) == ()
