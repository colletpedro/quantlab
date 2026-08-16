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
    BarSlice,
    Broker,
    ConvertedOrder,
    CostModel,
    CutStage,
    PendingBook,
    PendingOrder,
)
from quantlab.engine.conditional import Bracket, ConditionalIntent, OrderKind, Side
from quantlab.engine.margin import BrokenFundState, MarginCallOrder
from quantlab.engine.portfolio import Portfolio, Position, Trade, TradeOrigin
from quantlab.engine.sizing import FixedOneOverN, SizingInputs
from quantlab.engine.slippage import FixedBps
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
    """§3.8 — saída, ticker sem last_close e ref_price ≤ 0 são erro de
    programação (EngineError). (Regressão documentada T06: buy-stop DEIXOU de
    ser erro — vira kind de entrada válido na 2b; coberto por
    `test_convert_accepts_buy_stop`.)"""
    broker = Broker()
    base = _inputs(equity=100_000.0, cash=100_000.0, n=1, last_close={_TICKER: 10.0})

    with pytest.raises(EngineError):
        _convert(broker, Signal.EXIT, base)
    with pytest.raises(EngineError):
        _convert(broker, ConditionalIntent(Signal.EXIT, OrderKind.MARKET), base)
    # 2b: ENTER_SHORT só existe a mercado — limite/stop de venda não é
    # constructo da fase (guard de direção, T06).
    with pytest.raises(EngineError):
        _convert(broker, ConditionalIntent(Signal.ENTER_SHORT, OrderKind.STOP, stop=11.0), base)
    with pytest.raises(EngineError):
        _convert(broker, ConditionalIntent(Signal.ENTER_SHORT, OrderKind.LIMIT, limit=11.0), base)

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


# ─── T08 — execução mercado/limite/stop (RF-ORD-01/02, RF-SLP-04) ────────────

_EXEC = date(2024, 1, 4)  # gap 2 dias vs _DECIDED (2024-01-02)


def _bar(*, open_: float = 10.0, high: float = 11.0, low: float = 9.0) -> BarSlice:
    return BarSlice(date=_EXEC, open=open_, high=high, low=low, close=10.5)


def _pending(
    kind: OrderKind = OrderKind.MARKET,
    *,
    side: Side = Side.BUY,
    limit: float | None = None,
    stop: float | None = None,
    qty: int = 100,
    seq: int = 1,
    bracket: bool = False,
) -> PendingOrder:
    return PendingOrder(
        ticker=_TICKER,
        kind=kind,
        side=side,
        limit=limit,
        stop=stop,
        qty=qty,
        decision_date=_DECIDED,
        intent_seq=seq,
        bracket=bracket,
    )


def _run(
    broker: Broker,
    book: PendingBook,
    portfolio: Portfolio,
    bar: BarSlice,
    *,
    cost_model: CostModel | None = None,
    slippage: FixedBps | None = None,
) -> list[Trade]:
    return broker.execute_pending(
        store=book,
        ticker=_TICKER,
        bar=bar,
        portfolio=portfolio,
        cost_model=cost_model or CostModel(),
        slippage=slippage or FixedBps(),
        adv=None,
    )


@pytest.mark.unit
def test_market_executes_at_open_with_slippage() -> None:
    """SLP-04.1 — compra a mercado ao open com slippage (forma fechada).

    open 10.00, FixedBps(1.0) ⇒ 10.001 (1 bps = 0,01%); custo
    1 + 1e-4·1000.10 = 1.10001 debitado do caixa; gap 2 dias corridos
    (2024-01-02 → 2024-01-04).
    """
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(qty=100))

    trades = _run(broker, book, portfolio, _bar())

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_price == pytest.approx(10.001)
    assert trade.entry_cost == pytest.approx(1.10001)
    assert trade.origin == TradeOrigin.MARKET
    assert trade.entry_gap_days == 2
    assert portfolio.cash == pytest.approx(2_000.0 - 1_000.1 - 1.10001)
    assert portfolio.positions[_TICKER].quantity == 100
    assert book.pending_for(_TICKER) == ()  # consumida


@pytest.mark.unit
def test_limit_fills_at_min_of_limit_and_open_and_cancels_otherwise() -> None:
    """ORD-01.1/01.3 — compra a limite: low ≤ L ⇒ min(L, open), SEM slippage;
    senão cancela ao fim da barra (nada fica no book)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(OrderKind.LIMIT, limit=9.5, qty=100))

    # low 9.40 ≤ 9.50 ⇒ preenche a 9.50 — preço exato, sem bps (limite intacto).
    trades = _run(broker, book, portfolio, _bar(low=9.4))
    assert len(trades) == 1
    assert trades[0].entry_price == pytest.approx(9.5)
    assert trades[0].origin == TradeOrigin.LIMIT

    # low 9.60 > 9.50 ⇒ cancela: sem trade, sem posição, book vazio.
    book2 = PendingBook()
    portfolio2 = Portfolio(cash=2_000.0)
    book2.place(_pending(OrderKind.LIMIT, limit=9.5, qty=100))
    trades2 = _run(broker, book2, portfolio2, _bar(low=9.6, open_=10.0))
    assert trades2 == []
    assert portfolio2.positions == {}
    assert book2.pending_for(_TICKER) == ()


@pytest.mark.unit
def test_limit_never_violated_on_either_side() -> None:
    """SLP-04.2 — preço de preenchimento ≤ L na compra e ≥ L na venda
    (take-profit); nunca ultrapassa o limite, em nenhuma direção."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(OrderKind.LIMIT, limit=9.5, qty=100))

    # Gap de compra: open 10.00 > L, low toca 9.4 ⇒ preenche a 9.50 (nunca 10.01).
    trades = _run(broker, book, portfolio, _bar(open_=10.0, low=9.4))
    assert trades[0].entry_price == pytest.approx(9.5)
    assert trades[0].entry_price <= 9.5

    # Venda (take-profit): abre posição, LIMIT de venda L=12, high toca 12.5 ⇒
    # preenche a max(12, open 11) = 12.00 — nunca abaixo de L.
    book2 = PendingBook()
    portfolio2 = Portfolio(cash=2_000.0)
    broker.buy(
        portfolio2,
        ticker=_TICKER,
        price=10.0,
        execution_date=_EXEC,
        decision_date=_DECIDED,
    )
    book2.place(_pending(OrderKind.LIMIT, side=Side.SELL, limit=12.0, qty=100))
    trades2 = _run(broker, book2, portfolio2, _bar(open_=11.0, high=12.5))
    assert len(trades2) == 1
    exit_price = trades2[0].exit_price
    assert exit_price is not None
    assert exit_price == pytest.approx(12.0)
    assert exit_price >= 12.0
    assert trades2[0].origin == TradeOrigin.LIMIT
    assert portfolio2.positions == {}  # saída integral (D3)


@pytest.mark.unit
def test_sell_stop_triggers_at_min_of_stop_and_open_with_slippage() -> None:
    """ORD-02.1/SLP-04.4 — stop com posição: low ≤ S ⇒ vira mercado a
    min(S, open) COM slippage (venda mais barata)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.buy(
        portfolio,
        ticker=_TICKER,
        price=10.0,
        execution_date=_DECIDED,
        decision_date=_DECIDED,
    )
    book.place(_pending(OrderKind.STOP, side=Side.SELL, stop=9.0, qty=1_000))

    # low 8.50 <= 9.00 ⇒ ref = min(9.0, open 9.5) = 9.0 ⇒ vende a 9.0x(1-1e-4).
    trades = _run(broker, book, portfolio, _bar(open_=9.5, low=8.5))
    assert len(trades) == 1
    assert trades[0].exit_price == pytest.approx(9.0 * (1 - 1e-4))
    assert trades[0].origin == TradeOrigin.STOP
    assert portfolio.positions == {}  # stop vende a posição inteira (D3)
    assert book.pending_for(_TICKER) == ()  # disparado ⇒ consumido


@pytest.mark.unit
def test_stop_does_not_activate_without_position() -> None:
    """ORD-02.2 — stop sem posição aberta NUNCA ativa e permanece pendente."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(OrderKind.STOP, side=Side.SELL, stop=9.0))

    trades = _run(broker, book, portfolio, _bar(open_=9.5, low=8.5))
    assert trades == []
    assert book.pending_for(_TICKER) == (_pending(OrderKind.STOP, side=Side.SELL, stop=9.0),)


@pytest.mark.unit
def test_stop_persists_when_not_triggered() -> None:
    """Stop não disparado (low > S) PERMANECE pendente — persiste entre barras."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.buy(
        portfolio,
        ticker=_TICKER,
        price=10.0,
        execution_date=_DECIDED,
        decision_date=_DECIDED,
    )
    book.place(_pending(OrderKind.STOP, side=Side.SELL, stop=9.0))

    trades = _run(broker, book, portfolio, _bar(open_=10.0, low=9.5))  # low > S
    assert trades == []
    assert len(book.pending_for(_TICKER)) == 1
    assert portfolio.positions[_TICKER].quantity > 0


@pytest.mark.unit
def test_costs_debited_from_cash_not_in_execution_price() -> None:
    """SLP-04.3 — o preço do Trade é LIMPO (10.001, sem custo embutido); o
    custo 1.10001 sai do caixa em etapa própria."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(qty=100))

    trades = _run(broker, book, portfolio, _bar())
    trade = trades[0]
    assert trade.entry_price == pytest.approx(10.001)  # preço limpo, sem custo embutido
    assert trade.entry_cost == pytest.approx(1.10001)
    expected_debit = 100 * 10.001 + 1.10001
    assert portfolio.cash == pytest.approx(2_000.0 - expected_debit)


@pytest.mark.unit
def test_execution_is_deterministic() -> None:
    """RNF-01 — mesma entrada (book/portfolio/barra) ⇒ mesmos trades."""
    broker = Broker()

    def run_once() -> tuple[list[Trade], float]:
        book = PendingBook()
        portfolio = Portfolio(cash=2_000.0)
        book.place(_pending(OrderKind.LIMIT, limit=9.5, qty=100))
        trades = _run(broker, book, portfolio, _bar(open_=10.0, low=9.4))
        return trades, portfolio.cash

    first_trades, first_cash = run_once()
    second_trades, second_cash = run_once()
    assert first_trades == second_trades
    assert first_cash == pytest.approx(second_cash)


@pytest.mark.unit
def test_execution_domain_errors_raise_engine_error() -> None:
    """§3.8 — preço não positivo e MARKET de venda são EngineError."""
    broker = Broker()

    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(qty=100))
    with pytest.raises(EngineError):
        _run(broker, book, portfolio, _bar(open_=0.0))

    # 2b (T02) — MARKET SELL sem rebalance DEIXOU de ser erro: é a entrada
    # short (ENTER_SHORT, SHT-02.1). Regressão documentada no tasks 2b T02.
    book2 = PendingBook()
    portfolio2 = Portfolio(cash=2_000.0)
    book2.place(_pending(OrderKind.MARKET, side=Side.SELL, qty=100))
    shorts = _run(broker, book2, portfolio2, _bar())
    assert len(shorts) == 1
    assert shorts[0].quantity == -100

    # Barra malformada (high < low) e ordens sem preço são erro de programa.
    book3 = PendingBook()
    portfolio3 = Portfolio(cash=2_000.0)
    book3.place(_pending(qty=100))
    with pytest.raises(EngineError):
        _run(broker, book3, portfolio3, _bar(high=8.0, low=9.0))

    book4 = PendingBook()
    portfolio4 = Portfolio(cash=2_000.0)
    book4.place(_pending(OrderKind.STOP, side=Side.SELL))  # stop sem preço
    with pytest.raises(EngineError):
        _run(broker, book4, portfolio4, _bar(low=8.0))

    book5 = PendingBook()
    portfolio5 = Portfolio(cash=2_000.0)
    book5.place(_pending(OrderKind.LIMIT, side=Side.SELL))  # limite sem preço
    with pytest.raises(EngineError):
        _run(broker, book5, portfolio5, _bar())

    book6 = PendingBook()
    portfolio6 = Portfolio(cash=2_000.0)
    book6.place(_pending(OrderKind.LIMIT))  # limite de compra sem preço
    with pytest.raises(EngineError):
        _run(broker, book6, portfolio6, _bar())


@pytest.mark.unit
def test_enter_with_open_position_is_ignored_and_consumed(
    log_events: list[EventDict],
) -> None:
    """ENG-05 (Fase 1) — ENTER com posição aberta é ignorado e logado;
    a pendente é consumida (não pode executar depois)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.buy(
        portfolio,
        ticker=_TICKER,
        price=10.0,
        execution_date=_DECIDED,
        decision_date=_DECIDED,
    )
    book.place(_pending(qty=100))

    trades = _run(broker, book, portfolio, _bar())
    assert trades == []
    assert book.pending_for(_TICKER) == ()
    assert any(event["event"] == "engine.enter_with_open_position" for event in log_events)


@pytest.mark.unit
def test_insufficient_cash_at_execution_leaves_order_unfilled(
    log_events: list[EventDict],
) -> None:
    """CST-01.2 na execução — sem caixa para 1 ação ao preço da barra ⇒ a
    ordem não preenche, é consumida e o evento é logado."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=1.0)  # custo fixo 1.0 consome tudo
    book.place(_pending(qty=100))

    trades = _run(broker, book, portfolio, _bar())
    assert trades == []
    assert portfolio.positions == {}
    assert book.pending_for(_TICKER) == ()
    assert any(event["event"] == "engine.insufficient_cash" for event in log_events)


# ─── T09 — ambiguidade intrabarra por pior caso (ADR-0007/D2, RF-ORD-03) ─────


def _bracket_order(qty: int = 100, seq: int = 1) -> ConvertedOrder:
    """Ordem convertida de bracket de entrada (par L + S na mesma intenção)."""
    return _converted(kind=OrderKind.LIMIT, limit=10.5, stop=9.5, qty=qty, seq=seq, bracket=True)


@pytest.mark.unit
def test_intrabar_ambiguity_entry_bracket_worst_case() -> None:
    """ADR-0007/D2 — par L=10.5 + S=9.5, ambos tocados (low 9.0 ≤ S): abre em
    L, fecha em S na mesma barra, flat, ambiguous=True.

    Forma fechada: entrada 100 x 10.5 = 1_050 (custo 1.105); saída 100 x 9.5 =
    950 (custo 1.095); caixa = 2_000 - 100 - 2.20 = 1_897.80; perda
    realizada (S-L) x qty = -100, bruta de custos.
    """
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.place(book, _bracket_order())

    trades = _run(broker, book, portfolio, _bar(open_=10.0, low=9.0, high=10.0))

    assert len(trades) == 1  # só o fechado — o aberto foi substituído
    trade = trades[0]
    assert trade.entry_price == pytest.approx(10.5)  # abre em L (não min(L, open))
    assert trade.exit_price is not None
    assert trade.exit_price == pytest.approx(9.5)  # fecha em S, sem slippage
    assert trade.ambiguous is True
    assert trade.realized_pnl == pytest.approx(-100.0)  # (S - L) x qty
    assert trade.entry_cost == pytest.approx(1.105)
    assert trade.exit_cost == pytest.approx(1.095)
    assert portfolio.positions == {}  # flat
    assert portfolio.cash == pytest.approx(2_000.0 - 100.0 - 2.20)
    assert book.pending_for(_TICKER) == ()  # par consumido — nunca "ambos executam"


@pytest.mark.unit
def test_intrabar_ambiguity_exit_bracket_worst_case() -> None:
    """ADR-0007/D2 — take-profit TP=12 + stop S=9 sobre posição aberta, ambos
    tocados (high 12.5 ≥ TP, low 8.5 ≤ S): o STOP preenche em S (pior que TP),
    ambiguous=True; o TP NÃO preenche (sem dupla contagem)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.buy(
        portfolio,
        ticker=_TICKER,
        price=10.0,
        execution_date=_DECIDED,
        decision_date=_DECIDED,
    )
    opened = portfolio.positions[_TICKER]
    # Par de saída: LIMIT venda (take-profit) + STOP venda, mesma intenção;
    # os DOIS membros do par carregam bracket=True (mesmo contrato do place).
    book.place(_pending(OrderKind.LIMIT, side=Side.SELL, limit=12.0, seq=3, bracket=True))
    book.place(
        PendingOrder(
            ticker=_TICKER,
            kind=OrderKind.STOP,
            side=Side.SELL,
            limit=None,
            stop=9.0,
            qty=opened.quantity,
            decision_date=_DECIDED,
            intent_seq=3,
            bracket=True,
        )
    )

    trades = _run(broker, book, portfolio, _bar(open_=11.0, high=12.5, low=8.5))

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_price is not None
    assert trade.exit_price == pytest.approx(9.0)  # o stop em S — não max(12, open)
    assert trade.ambiguous is True
    assert trade.origin == TradeOrigin.STOP
    assert portfolio.positions == {}  # uma única saída — sem "ambos executam"
    assert book.pending_for(_TICKER) == ()
    # Caixa: uma venda só (qty x 9 - custo), não TP + stop.
    expected = 2_000.0 - opened.quantity * 10.0 - (1 + 1e-4 * opened.quantity * 10.0)
    expected += opened.quantity * 9.0 - (1 + 1e-4 * opened.quantity * 9.0)
    assert portfolio.cash == pytest.approx(expected)


@pytest.mark.unit
def test_entry_bracket_limit_cancels_and_stop_leaves_with_it() -> None:
    """Q2 + sem stop órfão — low > L: o limite da entrada cancela ao fim da
    barra e o stop do MESMO par sai do book junto (a intenção morreu; nada
    fica esperando uma posição que nunca abriu)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.place(book, _bracket_order())  # L=10.5, S=9.5

    trades = _run(broker, book, portfolio, _bar(open_=11.0, low=10.8, high=11.0))

    assert trades == []
    assert portfolio.positions == {}
    assert book.pending_for(_TICKER) == ()  # par inteiro consumido — sem stop órfão


@pytest.mark.unit
def test_entry_bracket_limit_only_fills_and_stop_survives() -> None:
    """ORD-02.2 — só o limite toca (low ≤ L, low > S): entra em min(L, open)
    e o stop do par PERMANECE protegendo a posição recém-aberta."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.place(book, _bracket_order())  # L=10.5, S=9.5

    trades = _run(broker, book, portfolio, _bar(open_=10.0, low=10.0, high=10.5))

    assert len(trades) == 1
    assert trades[0].entry_price == pytest.approx(10.0)  # min(10.5, open 10.0)
    assert trades[0].ambiguous is False
    assert portfolio.positions[_TICKER].quantity == 100
    surviving = book.pending_for(_TICKER)
    assert len(surviving) == 1
    assert surviving[0].kind is OrderKind.STOP  # segue vivo
    assert surviving[0].stop == pytest.approx(9.5)


@pytest.mark.unit
def test_intrabar_ambiguity_is_deterministic() -> None:
    """RNF-01 — mesma entrada ⇒ mesmo resultado (pior caso fixo, sem sorteio)."""
    broker = Broker()

    def run_once() -> tuple[list[Trade], float]:
        book = PendingBook()
        portfolio = Portfolio(cash=2_000.0)
        broker.place(book, _bracket_order())
        trades = _run(broker, book, portfolio, _bar(open_=10.0, low=9.0, high=10.0))
        return trades, portfolio.cash

    first_trades, first_cash = run_once()
    second_trades, second_cash = run_once()
    assert first_trades == second_trades
    assert first_cash == pytest.approx(second_cash)


@pytest.mark.unit
def test_bracket_malformed_raises_engine_error() -> None:
    """§3.8 — par de bracket sem preços (limite ou stop) é EngineError."""
    broker = Broker()

    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(OrderKind.LIMIT, limit=10.5, seq=1, bracket=True))  # sem parceiro
    with pytest.raises(EngineError):
        _run(broker, book, portfolio, _bar(open_=10.0, low=9.0, high=10.0))


@pytest.mark.unit
def test_entry_bracket_ambiguity_without_cash_pair_dies() -> None:
    """ADR-0007/D2 — pior caso sem caixa para 1 ação: nada abre, nada fecha,
    e o par inteiro é consumido (a intenção morreu — sem stop órfão)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=1.0)  # nem 1 ação a 10.5 cabe
    broker.place(book, _bracket_order())

    trades = _run(broker, book, portfolio, _bar(open_=10.0, low=9.0, high=10.0))

    assert trades == []
    assert portfolio.positions == {}
    assert book.pending_for(_TICKER) == ()


@pytest.mark.unit
def test_exit_bracket_only_tp_touched() -> None:
    """ADR-0007/D2 — só o take-profit toca (high >= TP, low > S): preenche em
    max(TP, open), sem ambiguidade; o stop sai junto (posição fechada)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.buy(
        portfolio,
        ticker=_TICKER,
        price=10.0,
        execution_date=_DECIDED,
        decision_date=_DECIDED,
    )
    opened = portfolio.positions[_TICKER]
    book.place(_pending(OrderKind.LIMIT, side=Side.SELL, limit=12.0, seq=3, bracket=True))
    book.place(
        PendingOrder(
            ticker=_TICKER,
            kind=OrderKind.STOP,
            side=Side.SELL,
            limit=None,
            stop=9.0,
            qty=opened.quantity,
            decision_date=_DECIDED,
            intent_seq=3,
            bracket=True,
        )
    )

    trades = _run(broker, book, portfolio, _bar(open_=11.0, high=12.5, low=9.5))

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_price == pytest.approx(12.0)  # max(TP, open), sem slippage
    assert trade.ambiguous is False
    assert trade.origin == TradeOrigin.LIMIT
    assert portfolio.positions == {}
    assert book.pending_for(_TICKER) == ()  # par completo — sem stop sobre posição fechada


@pytest.mark.unit
def test_exit_bracket_only_stop_touched() -> None:
    """ADR-0007/D2 — só o stop toca (high < TP, low <= S): regra normal do
    sell-stop (min(S, open) + slippage); o TP cancela ao fim da barra (Q2)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.buy(
        portfolio,
        ticker=_TICKER,
        price=10.0,
        execution_date=_DECIDED,
        decision_date=_DECIDED,
    )
    opened = portfolio.positions[_TICKER]
    book.place(_pending(OrderKind.LIMIT, side=Side.SELL, limit=12.0, seq=3, bracket=True))
    book.place(
        PendingOrder(
            ticker=_TICKER,
            kind=OrderKind.STOP,
            side=Side.SELL,
            limit=None,
            stop=9.0,
            qty=opened.quantity,
            decision_date=_DECIDED,
            intent_seq=3,
            bracket=True,
        )
    )

    trades = _run(broker, book, portfolio, _bar(open_=9.4, high=11.0, low=8.5))

    assert len(trades) == 1
    trade = trades[0]
    # min(S, open) = min(9.0, 9.4) = 9.0, venda: 9.0 x (1 - 1e-4) = 8.9991
    assert trade.exit_price == pytest.approx(9.0 * (1 - 1e-4))
    assert trade.ambiguous is False
    assert trade.origin == TradeOrigin.STOP
    assert portfolio.positions == {}
    assert book.pending_for(_TICKER) == ()  # TP cancelado, par completo


@pytest.mark.unit
def test_exit_bracket_none_touched_tp_cancels_stop_survives() -> None:
    """Q2/ORD-01.3 — nenhum preço tocado: o take-profit CANCELA ao fim da
    barra e o stop PERMANECE protegendo a posição aberta."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.buy(
        portfolio,
        ticker=_TICKER,
        price=10.0,
        execution_date=_DECIDED,
        decision_date=_DECIDED,
    )
    opened = portfolio.positions[_TICKER]
    book.place(_pending(OrderKind.LIMIT, side=Side.SELL, limit=12.0, seq=3, bracket=True))
    book.place(
        PendingOrder(
            ticker=_TICKER,
            kind=OrderKind.STOP,
            side=Side.SELL,
            limit=None,
            stop=9.0,
            qty=opened.quantity,
            decision_date=_DECIDED,
            intent_seq=3,
            bracket=True,
        )
    )

    trades = _run(broker, book, portfolio, _bar(open_=11.0, high=11.5, low=10.5))

    assert trades == []
    assert portfolio.positions[_TICKER].quantity == opened.quantity  # posição intacta
    surviving = book.pending_for(_TICKER)
    assert len(surviving) == 1
    assert surviving[0].kind is OrderKind.STOP  # TP cancelado, stop vivo
    assert surviving[0].stop == pytest.approx(9.0)


@pytest.mark.unit
def test_exit_bracket_malformed_raises_engine_error() -> None:
    """§3.8 — par de SAÍDA sem o parceiro stop é EngineError."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.buy(
        portfolio,
        ticker=_TICKER,
        price=10.0,
        execution_date=_DECIDED,
        decision_date=_DECIDED,
    )
    book.place(_pending(OrderKind.LIMIT, side=Side.SELL, limit=12.0, seq=3, bracket=True))
    with pytest.raises(EngineError):
        _run(broker, book, portfolio, _bar(open_=11.0, high=12.5, low=8.5))


@pytest.mark.unit
def test_rebalance_market_sell_closes_partial() -> None:
    """SIZ-03/T11a — ordem sintética de rebalance (MARKET SELL) faz venda
    PARCIAL ao open com slippage (SLP-04.1): o trecho vendido fecha, o
    restante fica aberto com quantidade reduzida e o custo de entrada é
    rateado (identidade de conciliação preservada)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    opened = broker.buy(
        portfolio, ticker=_TICKER, price=10.0, execution_date=_DECIDED, decision_date=_DECIDED
    )
    assert opened is not None
    original_entry_cost = opened.entry_cost
    book.place(
        PendingOrder(
            ticker=_TICKER,
            kind=OrderKind.MARKET,
            side=Side.SELL,
            limit=None,
            stop=None,
            qty=40,
            decision_date=_DECIDED,
            intent_seq=2,
            bracket=False,
            rebalance=True,
        )
    )

    trades = _run(broker, book, portfolio, _bar(open_=11.0, high=11.0, low=9.0))

    assert len(trades) == 1
    closed = trades[0]
    assert closed.quantity == 40
    assert closed.rebalance is True
    assert closed.origin == TradeOrigin.MARKET
    assert closed.entry_price == pytest.approx(10.0)
    assert closed.exit_price == pytest.approx(11.0 * (1 - 1e-4))  # slippage na venda
    remaining = portfolio.positions[_TICKER]
    assert remaining.quantity == opened.quantity - 40
    open_trade = portfolio.open_trade
    assert open_trade is not None
    assert open_trade.quantity == opened.quantity - 40
    # Custo de entrada rateado: trecho vendido + restante = total pago.
    assert closed.entry_cost + open_trade.entry_cost == pytest.approx(original_entry_cost)
    # Caixa: sobra da compra + crédito da venda de 40 a ~11.0 menos o custo.
    assert closed.exit_price is not None
    assert portfolio.cash == pytest.approx(
        (2_000.0 - opened.quantity * 10.0 - original_entry_cost)
        + 40 * closed.exit_price
        - closed.exit_cost
    )


@pytest.mark.unit
def test_rebalance_market_sell_whole_position_and_consumed_without_position() -> None:
    """SIZ-03/T11a — ajuste de rebalance que cobre a posição inteira fecha
    como a `sell` da Fase 1 (rebalance=True); sem posição, a ordem é
    consumida sem efeito."""
    broker = Broker()

    # Cobre a posição inteira (qty 999 > 100): fecha tudo.
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.buy(
        portfolio, ticker=_TICKER, price=10.0, execution_date=_DECIDED, decision_date=_DECIDED
    )
    book.place(
        PendingOrder(
            ticker=_TICKER,
            kind=OrderKind.MARKET,
            side=Side.SELL,
            limit=None,
            stop=None,
            qty=999,
            decision_date=_DECIDED,
            intent_seq=2,
            bracket=False,
            rebalance=True,
        )
    )
    trades = _run(broker, book, portfolio, _bar(open_=11.0, high=11.0, low=9.0))
    assert len(trades) == 1
    assert trades[0].rebalance is True
    assert portfolio.positions == {}  # flat

    # Sem posição: consumida, nada a vender.
    book2 = PendingBook()
    portfolio2 = Portfolio(cash=2_000.0)
    book2.place(
        PendingOrder(
            ticker=_TICKER,
            kind=OrderKind.MARKET,
            side=Side.SELL,
            limit=None,
            stop=None,
            qty=50,
            decision_date=_DECIDED,
            intent_seq=2,
            bracket=False,
            rebalance=True,
        )
    )
    trades2 = _run(broker, book2, portfolio2, _bar())
    assert trades2 == []
    assert book2.pending_for(_TICKER) == ()


# ─── T02 — execução short e cobertura (RF-SHT-02) ─────────────────────────────


@pytest.mark.unit
def test_convert_enter_short_yields_negative_qty() -> None:
    """SHT-01.2/D3 (T02) — ENTER_SHORT: o sizer devolve a magnitude e o alvo
    vira NEGATIVO, pela MESMA sequencia fixa da 2a (SIZING > CAP > INTEIRAS >
    CAIXA/CUSTOS)."""
    broker = Broker()
    base = _inputs(equity=100_000.0, cash=100_000.0, n=1, last_close={_TICKER: 100.0})
    converted = _convert(broker, Signal.ENTER_SHORT, base)
    assert converted is not None
    assert converted.qty == -1_000  # magnitude 1.0 * equity / 100 = 1000, sinal -
    assert converted.kind is OrderKind.MARKET
    assert converted.ref_price == 100.0


@pytest.mark.unit
def test_short_opens_at_market_with_sell_slippage() -> None:
    """CA-02.1 — venda a descoberto a mercado: abre `qty < 0` a
    `open * (1 - bps)` (direcao desfavoravel ao vendedor)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=100_000.0)
    book.place(_pending(qty=1_000, side=Side.SELL))  # MARKET SELL = ENTER_SHORT

    trades = _run(broker, book, portfolio, _bar(open_=100.0))

    assert len(trades) == 1
    trade = trades[0]
    assert trade.quantity == -1_000
    assert trade.entry_price == pytest.approx(100.0 * (1 - 0.0001))  # 99.99
    assert trade.origin == TradeOrigin.MARKET
    position = portfolio.positions[_TICKER]
    assert position.quantity == -1_000
    assert position.entry_price == pytest.approx(99.99)
    # Venda CREDITA o caixa: proceeds - custo (1 + 1e-4*99_990 ~ 10.999).
    assert portfolio.cash == pytest.approx(100_000.0 + 99_990.0 - (1.0 + 9.999))
    assert book.pending_for(_TICKER) == ()  # consumida


@pytest.mark.unit
def test_buy_to_cover_at_market_with_buy_slippage() -> None:
    """CA-02.2 — cobertura a mercado: compra que REDUZ |qty|, preco
    `open * (1 + bps)`; a posicao nunca cruza de sinal (SHT-02.2)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=100_000.0)
    # Abre short de 1000 a 99.99 (venda com slippage).
    book.place(_pending(qty=1_000, side=Side.SELL))
    _run(broker, book, portfolio, _bar(open_=100.0))
    assert portfolio.positions[_TICKER].quantity == -1_000

    # Cobre 400 a mercado: compra a 100 * (1 + 1e-4) = 100.01.
    book.place(_pending(qty=400, side=Side.BUY))
    trades = _run(broker, book, portfolio, _bar(open_=100.0))

    assert len(trades) == 1
    closed = trades[0]
    assert closed.quantity == -400  # trecho fechado mantém o sinal do round-trip
    assert closed.exit_price == pytest.approx(100.01)
    assert portfolio.positions[_TICKER].quantity == -600  # nunca cruza
    # Caixa: -(400 * 100.01 + custo).
    assert portfolio.cash == pytest.approx(
        100_000.0 + 99_990.0 - 9.999 - 1.0 - (400 * 100.01 + 1.0 + 400 * 100.01 * 1e-4)
    )


@pytest.mark.unit
def test_short_entry_respects_participation_cap() -> None:
    """CA-02.3 — o cap de participacao corta a ENTRADA short com o MESMO
    motivo da 2a (cut_reason == CAP)."""
    broker = Broker()
    base = _inputs(equity=100_000.0, cash=100_000.0, n=1, last_close={_TICKER: 100.0})
    converted = _convert(broker, Signal.ENTER_SHORT, base, adv=5_000.0, cap=0.10)
    assert converted is not None
    assert converted.qty == -500  # cap 10% * ADV 5000 = 500 < alvo 1000
    assert converted.cut_reason is CutStage.CAP


@pytest.mark.unit
def test_short_cover_buy_limit_never_violates_limit() -> None:
    """CA-02.4 — cobertura por buy-limit: preenche a `min(L, open)` quando
    low <= L; nunca viola o limite (SLP-04.2)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=200_000.0)
    book.place(_pending(qty=1_000, side=Side.SELL))
    _run(broker, book, portfolio, _bar(open_=100.0))

    # Barra com low 94.0 ≤ 95.0 ⇒ cobre a 95.0 (preço exato, sem bps).
    book.place(_pending(OrderKind.LIMIT, side=Side.BUY, limit=95.0, qty=1_000))
    trades = _run(broker, book, portfolio, _bar(open_=100.0, high=105.0, low=94.0))
    assert len(trades) == 1
    assert trades[0].exit_price == pytest.approx(95.0)
    assert trades[0].origin == TradeOrigin.LIMIT
    assert _TICKER not in portfolio.positions  # cobertura integral

    # Barra com low 96.0 > 95.0 ⇒ cancela ao fim da barra (ordem consumida).
    book.place(_pending(OrderKind.LIMIT, side=Side.BUY, limit=95.0, qty=1_000))
    trades2 = _run(broker, book, portfolio, _bar(open_=100.0, high=105.0, low=96.0))
    assert trades2 == []
    assert book.pending_for(_TICKER) == ()


@pytest.mark.unit
def test_cover_above_position_raises_engine_error() -> None:
    """§3.8 — cobertura sem posição short aberta (flat ou long) é erro de
    domínio (EngineError), nunca silêncio (SHT-01.3/CA-01.3)."""
    broker = Broker()
    portfolio = Portfolio(cash=100_000.0)
    with pytest.raises(EngineError):
        broker.cover(
            portfolio, ticker=_TICKER, price=95.0, execution_date=_EXEC, decision_date=_DECIDED
        )

    portfolio.positions[_TICKER] = Position(
        ticker=_TICKER, quantity=100, entry_price=100.0, entry_date=_DECIDED
    )
    with pytest.raises(EngineError):
        broker.cover(
            portfolio, ticker=_TICKER, price=95.0, execution_date=_EXEC, decision_date=_DECIDED
        )


@pytest.mark.unit
def test_sell_stop_never_activates_over_short() -> None:
    """2b (T02, tabela §3.5) — sell-stop com posição SHORT aberta permanece
    pendente (não existe \"vender mais short\" sem intenção ENTER_SHORT)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=100_000.0)
    book.place(_pending(qty=1_000, side=Side.SELL))
    _run(broker, book, portfolio, _bar(open_=100.0))

    book.place(_pending(OrderKind.STOP, side=Side.SELL, stop=95.0, qty=1_000))
    trades = _run(broker, book, portfolio, _bar(open_=100.0, high=110.0, low=90.0))
    assert trades == []
    assert portfolio.positions[_TICKER].quantity == -1_000  # intacta
    assert len(book.pending_for(_TICKER)) == 1  # stop segue pendente


@pytest.mark.unit
def test_enter_short_with_open_long_is_ignored_and_consumed() -> None:
    """Decisao local (T02, guard ENG-05 estendido) — ENTER_SHORT com LONG
    aberto e ignorado e consumido (o modelo nao cruza de sinal num unico
    trade; a estrategia deve EXIT antes)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=100_000.0)
    book.place(_pending(qty=100, side=Side.BUY))
    _run(broker, book, portfolio, _bar())
    assert portfolio.positions[_TICKER].quantity == 100

    book.place(_pending(qty=1_000, side=Side.SELL))
    trades = _run(broker, book, portfolio, _bar())
    assert trades == []
    assert portfolio.positions[_TICKER].quantity == 100  # long intacto
    assert book.pending_for(_TICKER) == ()  # consumida


# ─── T05 — liquidação forçada e fundo quebrado (RF-MRG-02/03) ────────────────


def _margin_call(ticker: str, side: Side, qty: int, seq: int = 1) -> MarginCallOrder:
    return MarginCallOrder(
        ticker=ticker,
        side=side,
        qty=qty,
        decision_date=_DECIDED,
        intent_seq=seq,
    )


def _run_margin_calls(
    broker: Broker,
    portfolio: Portfolio,
    plan: tuple[MarginCallOrder, ...],
    *,
    bar: BarSlice | None = None,
    cost_model: CostModel | None = None,
) -> list[Trade]:
    return broker.execute_margin_calls(
        plan=plan,
        bar=bar or _bar(),
        portfolio=portfolio,
        cost_model=cost_model or CostModel(),
        slippage=FixedBps(),
    )


@pytest.mark.unit
def test_execute_margin_call_long_sells_at_market_with_costs() -> None:
    """CA-02.3/§3.5 — liquidação de LONG: venda a mercado no open com
    slippage de venda e `origin == MARGIN_CALL` no trade."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(qty=100))  # long
    _run(broker, book, portfolio, _bar())
    assert portfolio.positions[_TICKER].quantity == 100
    cash_before = portfolio.cash

    trades = _run_margin_calls(broker, portfolio, (_margin_call(_TICKER, Side.SELL, 100),))

    assert len(trades) == 1
    closed = trades[0]
    assert closed.origin == TradeOrigin.MARGIN_CALL
    assert closed.exit_price == pytest.approx(10.0 * (1 - 0.0001))  # open x (1 - bps)
    assert _TICKER not in portfolio.positions
    notional = 100 * 10.0 * (1 - 0.0001)
    assert portfolio.cash == pytest.approx(cash_before + notional - CostModel().cost_for(notional))


@pytest.mark.unit
def test_execute_margin_call_short_buys_to_cover() -> None:
    """CA-02.3/§3.5 — liquidação de SHORT: cobertura integral a mercado com
    slippage de compra e `origin == MARGIN_CALL`."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=100_000.0)
    book.place(_pending(qty=1_000, side=Side.SELL))  # short
    _run(broker, book, portfolio, _bar(open_=100.0))
    assert portfolio.positions[_TICKER].quantity == -1_000
    cash_before = portfolio.cash

    trades = _run_margin_calls(
        broker, portfolio, (_margin_call(_TICKER, Side.BUY, 1_000),), bar=_bar(open_=100.0)
    )

    assert len(trades) == 1
    closed = trades[0]
    assert closed.origin == TradeOrigin.MARGIN_CALL
    assert closed.exit_price == pytest.approx(100.0 * (1 + 0.0001))  # open x (1 + bps)
    assert _TICKER not in portfolio.positions
    notional = 1_000 * 100.0 * (1 + 0.0001)
    assert portfolio.cash == pytest.approx(cash_before - notional - CostModel().cost_for(notional))


@pytest.mark.unit
def test_margin_call_plan_validation_errors() -> None:
    """§3.8 — plano malformado é erro de programa: ativo sem posição, qty não
    integral ou side incoerente com o sinal."""
    broker = Broker()
    portfolio = Portfolio(cash=10_000.0)

    with pytest.raises(EngineError):  # sem posição
        _run_margin_calls(broker, portfolio, (_margin_call(_TICKER, Side.SELL, 100),))

    portfolio.positions[_TICKER] = Position(
        ticker=_TICKER, quantity=100, entry_price=10.0, entry_date=_DECIDED
    )
    with pytest.raises(EngineError):  # qty parcial (50 != 100)
        _run_margin_calls(broker, portfolio, (_margin_call(_TICKER, Side.SELL, 50),))
    with pytest.raises(EngineError):  # side incoerente (BUY sobre long)
        _run_margin_calls(broker, portfolio, (_margin_call(_TICKER, Side.BUY, 100),))


@pytest.mark.unit
def test_margin_call_order_rejects_non_positive_qty() -> None:
    """§3.8 — `MarginCallOrder` com qty <= 0 é erro de domínio (integral)."""
    with pytest.raises(EngineError):
        _margin_call(_TICKER, Side.SELL, 0)
    with pytest.raises(EngineError):
        _margin_call(_TICKER, Side.SELL, -10)


@pytest.mark.unit
def test_broken_fund_state_holds_negative_equity() -> None:
    """R6/CA-03.2 — o estado fundo quebrado carrega o valor NEGATIVO real
    (nunca zero fabricado, nunca NaN); métricas de retorno derivam None."""
    state = BrokenFundState(broken=True, final_equity=-1_234.5)
    assert state.broken is True
    assert state.final_equity == pytest.approx(-1_234.5)


# ─── T06 — buy-stop e remoção da barreira P2 (RF-ORD-05) ─────────────────────


@pytest.mark.unit
def test_convert_accepts_buy_stop() -> None:
    """Emenda P1 — a barreira P2 da 2a é removida: STOP vira kind de entrada
    VÁLIDO no convert (buy-stop); o guard que levantava EngineError saiu."""
    broker = Broker()
    base = _inputs(equity=100_000.0, cash=100_000.0, n=1, last_close={_TICKER: 10.0})

    converted = _convert(broker, ConditionalIntent(Signal.ENTER, OrderKind.STOP, stop=11.0), base)

    assert converted is not None
    assert converted.kind is OrderKind.STOP
    assert converted.stop == 11.0


@pytest.mark.unit
def test_buy_stop_executes_at_max_stop_open_with_buy_slippage() -> None:
    """CA-05.1 — buy-stop disparado: compra a `max(S, open)` com slippage de
    compra (SLP-04.4)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(OrderKind.STOP, side=Side.BUY, stop=9.5, qty=100))

    # open 10.00 >= stop 9.5 ⇒ dispatch a max(9.5, 10) = 10, slippage +1 bps.
    trades = _run(broker, book, portfolio, _bar(open_=10.0, high=11.0))

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_price == pytest.approx(10.0 * (1 + 0.0001))
    assert trade.origin == TradeOrigin.STOP
    assert portfolio.positions[_TICKER].quantity == 100
    assert book.pending_for(_TICKER) == ()  # disparado e consumido


@pytest.mark.unit
def test_buy_stop_undispatched_persists_to_next_bar_of_own_asset() -> None:
    """CA-05.2 — buy-stop não disparado PERMANECE pendente para a próxima
    barra do próprio ativo (ADR-0002 por ativo)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(OrderKind.STOP, side=Side.BUY, stop=9.5, qty=100))

    trades = _run(broker, book, portfolio, _bar(open_=9.0, high=9.2))  # high < S

    assert trades == []
    assert _TICKER not in portfolio.positions
    assert len(book.pending_for(_TICKER)) == 1  # segue pendente
    assert portfolio.cash == pytest.approx(2_000.0)  # nada debitado (CA-05.3)


@pytest.mark.unit
def test_buy_stop_never_dispatched_never_debits_cash() -> None:
    """CA-05.3 — buy-stop que nunca dispara não executa e o caixa nunca é
    debitado (sem reserva de caixa — ORD-04.3)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(OrderKind.STOP, side=Side.BUY, stop=9.5, qty=100))

    for _ in range(3):
        _run(broker, book, portfolio, _bar(open_=9.0, high=9.2))

    assert portfolio.cash == pytest.approx(2_000.0)
    assert _TICKER not in portfolio.positions
    assert len(book.pending_for(_TICKER)) == 1


@pytest.mark.unit
def test_buy_stop_with_open_long_is_ignored_and_consumed() -> None:
    """Emenda P1 — guard ENG-05: buy-stop com posição LONG aberta é ignorado e
    CONSUMIDO (nunca duas posições do mesmo sinal)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    book.place(_pending(qty=100))  # long
    _run(broker, book, portfolio, _bar())
    assert portfolio.positions[_TICKER].quantity == 100

    book.place(_pending(OrderKind.STOP, side=Side.BUY, stop=8.0, qty=100))
    trades = _run(broker, book, portfolio, _bar(low=7.0))  # dispararia

    assert trades == []
    assert portfolio.positions[_TICKER].quantity == 100  # long intacto
    assert book.pending_for(_TICKER) == ()  # consumida pelo guard


@pytest.mark.unit
def test_buy_stop_over_short_covers_never_crosses() -> None:
    """Emenda P1 — buy-stop sobre posição SHORT ativa como COBERTURA do
    stop-loss: reduz |qty| até 0, nunca cruza de sinal (SHT-02.2)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=200_000.0)
    book.place(_pending(qty=1_000, side=Side.SELL))  # short
    _run(broker, book, portfolio, _bar(open_=100.0))
    assert portfolio.positions[_TICKER].quantity == -1_000

    # Buy-stop (stop-loss do short) dispara a 105: cobre 400, resta -600.
    book.place(_pending(OrderKind.STOP, side=Side.BUY, stop=105.0, qty=400))
    trades = _run(broker, book, portfolio, _bar(open_=100.0, high=110.0))

    assert len(trades) == 1
    assert trades[0].exit_price == pytest.approx(105.0 * (1 + 0.0001))
    assert portfolio.positions[_TICKER].quantity == -600  # nunca cruza


@pytest.mark.unit
def test_convert_rejects_enter_short_with_stop_or_limit() -> None:
    """T06 (guard de direção) — ENTER_SHORT só existe a mercado; limite/stop
    de venda para abrir short não é constructo da 2b (place() montaria o lado
    errado)."""
    broker = Broker()
    base = _inputs(equity=100_000.0, cash=100_000.0, n=1, last_close={_TICKER: 10.0})
    with pytest.raises(EngineError):
        _convert(broker, ConditionalIntent(Signal.ENTER_SHORT, OrderKind.STOP, stop=11.0), base)
    with pytest.raises(EngineError):
        _convert(broker, ConditionalIntent(Signal.ENTER_SHORT, OrderKind.LIMIT, limit=9.0), base)


# ─── T07 — ambiguidades intrabarra com buy-stop (RF-ORD-06, ADR-0007 estendido) ─


def _buy_stop_bracket_order(
    *, trigger: float, protector: float, qty: int = 100, seq: int = 1
) -> ConvertedOrder:
    """Ordem convertida de bracket de ENTRADA por buy-stop (2b, T07).

    O overload do convert: `stop` = S_e (gatilho do buy-stop), `limit` = S_s
    (o sell-stop protetor — o par na mesma intenção, S_s < S_e).
    """
    return _converted(
        kind=OrderKind.STOP, stop=trigger, limit=protector, qty=qty, seq=seq, bracket=True
    )


@pytest.mark.unit
def test_intrabar_ambiguity_buy_stop_entry_bracket_worst_case() -> None:
    """RF-ORD-06 CA-06.1 (design §4, ADR-0007 estendido) — par buy-stop
    S_e=11.5 + sell-stop protetor S_s=10.5, ambos tocados na mesma barra
    (high 12.0 >= S_e, low 10.0 <= S_s): abre no buy-stop S_e e fecha no
    sell-stop S_s na MESMA barra — flat, ambiguous=True, sem slippage.

    Forma fechada: entrada 100 x 11.5 = 1.150 (custo 1.115); saída 100 x 10.5
    = 1.050 (custo 1.105); caixa = 2.000 - 100 - 2.22 = 1.897,78; perda
    realizada (S_s - S_e) x qty = -100, bruta de custos.
    """
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.place(book, _buy_stop_bracket_order(trigger=11.5, protector=10.5))

    trades = _run(broker, book, portfolio, _bar(open_=11.0, high=12.0, low=10.0))

    assert len(trades) == 1  # só o fechado — o aberto foi substituído
    trade = trades[0]
    assert trade.entry_price == pytest.approx(11.5)  # abre em S_e, sem slippage
    assert trade.exit_price is not None
    assert trade.exit_price == pytest.approx(10.5)  # fecha em S_s, sem slippage
    assert trade.ambiguous is True
    assert trade.origin == TradeOrigin.STOP
    assert trade.realized_pnl == pytest.approx(-100.0)  # (S_s - S_e) x qty
    assert trade.entry_cost == pytest.approx(1.115)
    assert trade.exit_cost == pytest.approx(1.105)
    assert portfolio.positions == {}  # flat
    assert portfolio.cash == pytest.approx(2_000.0 - 100.0 - 2.22)
    assert book.pending_for(_TICKER) == ()  # par consumido — nunca "ambos executam"


@pytest.mark.unit
def test_buy_stop_entry_bracket_only_trigger_fills_and_protector_survives() -> None:
    """RF-ORD-06 (espelho do ORD-02.2) — só o buy-stop toca (high >= S_e,
    low > S_s): entra a max(S_e, open) + slippage de compra e o sell-stop do
    par PERMANECE protegendo a posição recém-aberta (sem stop órfão)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.place(book, _buy_stop_bracket_order(trigger=11.5, protector=10.5))

    # open 11.0, high 12.0 >= 11.5, low 10.8 > 10.5 — só o gatilho tocou.
    trades = _run(broker, book, portfolio, _bar(open_=11.0, high=12.0, low=10.8))

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_price == pytest.approx(11.5 * (1 + 0.0001))  # max(S_e, open) + bps
    assert trade.ambiguous is False
    assert trade.origin == TradeOrigin.STOP
    assert portfolio.positions[_TICKER].quantity == 100
    surviving = book.pending_for(_TICKER)
    assert len(surviving) == 1
    assert surviving[0].kind is OrderKind.STOP
    assert surviving[0].side is Side.SELL
    assert surviving[0].stop == pytest.approx(10.5)  # protetor vivo


@pytest.mark.unit
def test_buy_stop_entry_bracket_pair_persists_until_trigger() -> None:
    """RF-ORD-06 (design §4, sem stop órfão por buy-stop) — enquanto o
    buy-stop não dispara, o PAR permanece pendente junto (o buy-stop é entrada
    condicional persistente — CA-05.2 — e o sell-stop nunca ativa sem posição
    — ORD-02.2). Inclui o caso do sell-stop tocado sem entrada (low <= S_s,
    high < S_e): a intenção não morreu, nada é cancelado."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.place(book, _buy_stop_bracket_order(trigger=11.5, protector=10.5))

    # Nenhum tocado: open 11.0, high 11.2 < 11.5, low 10.8 > 10.5.
    trades = _run(broker, book, portfolio, _bar(open_=11.0, high=11.2, low=10.8))
    assert trades == []
    assert portfolio.positions == {}
    pair = book.pending_for(_TICKER)
    assert len(pair) == 2  # par inteiro permanece
    assert all(p.intent_seq == 1 for p in pair)

    # Sell-stop tocado SEM entrada (low 10.4 <= 10.5, high 11.2 < 11.5): o
    # protetor não ativa (sem posição — ORD-02.2) e o par continua junto.
    trades2 = _run(broker, book, portfolio, _bar(open_=11.0, high=11.2, low=10.4))
    assert trades2 == []
    assert portfolio.positions == {}
    pair2 = book.pending_for(_TICKER)
    assert len(pair2) == 2
    assert {p.side for p in pair2} == {Side.BUY, Side.SELL}


@pytest.mark.unit
def test_intrabar_ambiguity_short_bracket_stop_wins_over_tp() -> None:
    """RF-ORD-06 CA-06.2 (design §4, ADR-0007 estendido) — bracket short
    (take-profit buy-limit TP=95 + stop-loss buy-stop SL=105, SL > TP) sobre
    posição short aberta, ambos tocados (high 110 >= SL, low 90 <= TP): o
    short é COBERTO no buy-stop SL (pior caso, preço da ordem, sem slippage),
    ambiguous=True; o limite NUNCA preenche (CA-03.3 — sem dupla contagem).

    Forma fechada: short abre a 99,99 (100 x (1 - 1e-4)); cobre a 105 ⇒ perda
    realizada (99,99 - 105) x 1.000 = -5.010, bruta de custos.
    """
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=100_000.0)
    # Abre o short a 99,99 (venda com slippage — SHT-02.1).
    book.place(_pending(qty=1_000, side=Side.SELL))
    _run(broker, book, portfolio, _bar(open_=100.0))
    assert portfolio.positions[_TICKER].quantity == -1_000

    # Par de saída do short: TP buy-limit + SL buy-stop, mesma intenção;
    # os DOIS membros carregam bracket=True (mesmo contrato do place).
    book.place(_pending(OrderKind.LIMIT, side=Side.BUY, limit=95.0, qty=1_000, seq=3, bracket=True))
    book.place(
        PendingOrder(
            ticker=_TICKER,
            kind=OrderKind.STOP,
            side=Side.BUY,
            limit=None,
            stop=105.0,
            qty=1_000,
            decision_date=_DECIDED,
            intent_seq=3,
            bracket=True,
        )
    )

    trades = _run(broker, book, portfolio, _bar(open_=100.0, high=110.0, low=90.0))

    assert len(trades) == 1
    trade = trades[0]
    assert trade.exit_price is not None
    assert trade.exit_price == pytest.approx(105.0)  # o SL — nunca o TP (min(95, open))
    assert trade.ambiguous is True
    assert trade.origin == TradeOrigin.STOP
    assert trade.realized_pnl == pytest.approx(-5_010.0)  # (99,99 - 105) x 1.000
    assert portfolio.positions == {}  # flat — uma única cobertura, sem "ambos executam"
    assert book.pending_for(_TICKER) == ()


@pytest.mark.unit
def test_no_double_execution_buy_stop_brackets() -> None:
    """RF-ORD-06 / CA-03.3 (herdado) — nunca \"ambos executam\" na sequência
    favorável: o pior caso resolve com UMA única execução (o fechado), nos
    DOIS brackets com buy-stop (long de entrada e short de saída)."""
    # Bracket long de entrada (S_e=11.5, S_s=10.5), ambos tocados.
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.place(book, _buy_stop_bracket_order(trigger=11.5, protector=10.5))
    trades = _run(broker, book, portfolio, _bar(open_=11.0, high=12.0, low=10.0))
    assert len(trades) == 1  # nunca a entrada + a saída como dois fills separados
    assert portfolio.positions == {}  # flat — uma perda fechada só

    # Bracket short de saída (TP=95, SL=105), ambos tocados.
    broker2 = Broker()
    book2 = PendingBook()
    portfolio2 = Portfolio(cash=100_000.0)
    book2.place(_pending(qty=1_000, side=Side.SELL))
    _run(broker2, book2, portfolio2, _bar(open_=100.0))
    book2.place(
        _pending(OrderKind.LIMIT, side=Side.BUY, limit=95.0, qty=1_000, seq=3, bracket=True)
    )
    book2.place(
        PendingOrder(
            ticker=_TICKER,
            kind=OrderKind.STOP,
            side=Side.BUY,
            limit=None,
            stop=105.0,
            qty=1_000,
            decision_date=_DECIDED,
            intent_seq=3,
            bracket=True,
        )
    )
    trades2 = _run(broker2, book2, portfolio2, _bar(open_=100.0, high=110.0, low=90.0))
    assert len(trades2) == 1  # o SL cobre — o TP nunca preenche junto
    assert portfolio2.positions == {}


@pytest.mark.unit
def test_buy_stop_bracket_no_orphan_stop() -> None:
    """RF-ORD-06 (herança T09 da 2a) — o sell-stop do par de buy-stop NUNCA
    ativa sem posição aberta: mesmo quando `low <= S_s` (tocado), sem o
    buy-stop ter disparado não há trade e o par permanece — sem stop órfão
    esperando uma posição que nunca abriu (design §4)."""
    broker = Broker()
    book = PendingBook()
    portfolio = Portfolio(cash=2_000.0)
    broker.place(book, _buy_stop_bracket_order(trigger=11.5, protector=10.5))

    # low 10.4 <= S_s (10.5) mas high 11.2 < S_e (11.5): o protetor toca mas
    # não há posição — nada executa, o par fica junto.
    trades = _run(broker, book, portfolio, _bar(open_=11.0, high=11.2, low=10.4))

    assert trades == []
    assert portfolio.positions == {}
    pair = book.pending_for(_TICKER)
    assert len(pair) == 2  # sem stop órfão: os DOIS membros continuam no book
    assert {p.side for p in pair} == {Side.BUY, Side.SELL}
