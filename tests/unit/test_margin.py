"""T03 — BorrowFeeModel (RF-SHT-03, ADR-0010) e disponibilidade de aluguel.

Forma fechada do fee diário (CA-03.1), incidência só com short aberto
(CA-03.2 — o débito por dia é do laço, T08a; aqui o contrato) e os dois
lados da disponibilidade (CA-03.4 — default ilimitado nunca bloqueia;
restrito bloqueia, loga e conta no convert). Fixtures de papel (RNF-03).
"""

from datetime import date

import pytest

from quantlab.engine.broker import Broker, CostModel, MechanismCounters
from quantlab.engine.conditional import OrderKind
from quantlab.engine.margin import BorrowFeeModel
from quantlab.engine.sizing import FixedOneOverN, SizingInputs
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError

_DECIDED = date(2024, 1, 2)


@pytest.mark.unit
def test_borrow_fee_closed_form_10_days() -> None:
    """CA-03.1 — short de 1.000 ações a $100 por 10 pregões, fee 0,50% a.a.:
    custo total = Σ_d |qty| x close_d x 0,005/252, em forma fechada."""
    model = BorrowFeeModel()  # fee_annual default 0,50% a.a.
    closes = [100.0 + d for d in range(10)]  # 100..109

    total = sum(model.daily_fee(qty=1_000.0, close=c) for c in closes)
    expected = sum(1_000.0 * c * 0.005 / 252.0 for c in closes)

    assert total == pytest.approx(expected)
    assert total == pytest.approx(1_000.0 * (0.005 / 252.0) * sum(closes))


@pytest.mark.unit
def test_borrow_fee_requires_open_short() -> None:
    """CA-03.2 — o fee incide só com posição short ABERTA: qty == 0 (já
    coberta) não tem fee; close não positivo é erro de domínio (§3.8)."""
    model = BorrowFeeModel()
    with pytest.raises(EngineError):
        model.daily_fee(qty=0.0, close=100.0)
    with pytest.raises(EngineError):
        model.daily_fee(qty=-100.0, close=0.0)


@pytest.mark.unit
def test_borrow_availability_unlimited_default_never_blocks() -> None:
    """CA-03.4 (lado esquerdo) — com o default, a disponibilidade NUNCA
    bloqueia: is_available é True para qualquer ativo/qualquer data."""
    model = BorrowFeeModel()
    assert model.unlimited is True
    for ticker in ("AAPL", "NENHUMA"):
        assert model.is_available(ticker, _DECIDED) is True


@pytest.mark.unit
def test_borrow_restricted_blocks_short_and_logs() -> None:
    """CA-03.4 (lado direito) — `unlimited=False` + ativo indisponível ⇒ o
    ENTER_SHORT não executa, é logado e CONTADO (borrow_rejections, no
    convert — dono §3.7). Ativo disponível segue livre."""
    borrow = BorrowFeeModel(unlimited=False, unavailable=frozenset({"AAA"}))
    assert borrow.is_available("AAA", _DECIDED) is False
    assert borrow.is_available("BBB", _DECIDED) is True

    broker = Broker()
    counters = MechanismCounters()
    inputs = SizingInputs(
        equity=100_000.0,
        cash=100_000.0,
        n=1,
        last_close={"AAA": 100.0},
    )
    converted = broker.convert(
        intent=Signal.ENTER_SHORT,
        ticker="AAA",
        inputs=inputs,
        sizer=FixedOneOverN(n=1),
        adv=None,
        cost_model=CostModel(),
        cap=0.10,
        decision_date=_DECIDED,
        intent_seq=1,
        counters=counters,
        borrow=borrow,
    )
    assert converted is None  # bloqueado
    assert counters.borrow_rejections == 1

    # Sem modelo (2a — o laço só passa o borrow a partir da T08a), nada bloqueia.
    converted_free = broker.convert(
        intent=Signal.ENTER_SHORT,
        ticker="AAA",
        inputs=inputs,
        sizer=FixedOneOverN(n=1),
        adv=None,
        cost_model=CostModel(),
        cap=0.10,
        decision_date=_DECIDED,
        intent_seq=2,
    )
    assert converted_free is not None
    assert converted_free.qty == -1_000


@pytest.mark.unit
def test_borrow_fee_model_rejects_negative_fee() -> None:
    """§3.8 — fee anual negativo é erro de configuração (EngineError)."""
    with pytest.raises(EngineError):
        BorrowFeeModel(fee_annual=-0.01)


@pytest.mark.unit
def test_convert_ignores_order_kind_of_blocked_short() -> None:
    """CA-03.4 — o bloqueio vale para QUALQUER kind de entrada short
    (MARKET/LIMIT/STOP): a disponibilidade é checada antes do sizing."""
    borrow = BorrowFeeModel(unlimited=False, unavailable=frozenset({"AAA"}))
    broker = Broker()
    counters = MechanismCounters()
    inputs = SizingInputs(
        equity=100_000.0,
        cash=100_000.0,
        n=1,
        last_close={"AAA": 100.0},
    )
    from quantlab.engine.conditional import ConditionalIntent

    intent = ConditionalIntent(Signal.ENTER_SHORT, OrderKind.LIMIT, limit=95.0)
    converted = broker.convert(
        intent=intent,
        ticker="AAA",
        inputs=inputs,
        sizer=FixedOneOverN(n=1),
        adv=None,
        cost_model=CostModel(),
        cap=0.10,
        decision_date=_DECIDED,
        intent_seq=1,
        counters=counters,
        borrow=borrow,
    )
    assert converted is None
    assert counters.borrow_rejections == 1
