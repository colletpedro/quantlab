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
from quantlab.engine.margin import (
    BorrowFeeModel,
    MarginModel,
    margin_requirement,
    margin_utilization,
)
from quantlab.engine.portfolio import Position
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


# ─── T04 — margem: invariante e utilização (RF-MRG-01, ADR-0009) ─────────────


def _position(ticker: str, quantity: int) -> Position:
    return Position(ticker=ticker, quantity=quantity, entry_price=100.0, entry_date=_DECIDED)


@pytest.mark.unit
def test_margin_requirement_uses_absolute_qty() -> None:
    """CA-01.1 — a margem usa Σ|qty| x close x factor (valores ABSOLUTOS),
    nunca a soma algébrica: long e short NÃO se cancelam."""
    positions = {"AAA": _position("AAA", 100), "BBB": _position("BBB", -50)}
    closes = {"AAA": 100.0, "BBB": 200.0}
    model = MarginModel()  # factor default 1.0

    requirement = margin_requirement(positions, closes, model)

    assert requirement == pytest.approx(100 * 100.0 + 50 * 200.0)  # 10.000 + 10.000
    assert requirement != pytest.approx(100 * 100.0 - 50 * 200.0)  # soma algébrica = 0


@pytest.mark.unit
def test_margin_invariant_reduces_to_cash_ge_zero_long_only() -> None:
    """CA-01.2 — regressão da 2a: com apenas longs e factor 1.0,
    ``equity >= margem`` é exatamente ``cash >= 0``."""
    positions = {"AAA": _position("AAA", 100)}
    closes = {"AAA": 100.0}
    model = MarginModel()

    requirement = margin_requirement(positions, closes, model)
    # equity = cash 50 + posição 100 x 100 = 10.050; margem = 10.000.
    equity = 10_050.0
    assert equity - requirement == pytest.approx(50.0)  # = cash
    # equity >= margem ⇔ cash >= 0, com folga exata de 1 centavo.
    assert (equity >= requirement) is (50.0 >= 0.0)


@pytest.mark.unit
def test_margin_factor_default_1_0_exact_formula() -> None:
    """CA-01.5 — `margin_factor` default 1.0, explícito e configurável: o
    valor segue EXATAMENTE Σ|qty| x close x factor (R3)."""
    positions = {"AAA": _position("AAA", -200)}
    closes = {"AAA": 50.0}

    assert MarginModel().factor == 1.0  # default explícito
    assert margin_requirement(positions, closes, MarginModel()) == pytest.approx(200 * 50.0)
    assert margin_requirement(positions, closes, MarginModel(factor=1.5)) == pytest.approx(
        200 * 50.0 * 1.5
    )


@pytest.mark.unit
def test_margin_utilization_none_on_nonpositive_equity() -> None:
    """R6 — utilização com equity <= 0 é `None` explícito, nunca NaN (o fundo
    quebrado deriva None — MRG-03 CA-03.2)."""
    assert margin_utilization(equity=0.0, requirement=100.0) is None
    assert margin_utilization(equity=-500.0, requirement=100.0) is None
    assert margin_utilization(equity=1_000.0, requirement=250.0) == pytest.approx(0.25)


@pytest.mark.unit
def test_margin_factor_non_positive_raises_engine_error() -> None:
    """§3.8 — factor <= 0 é erro de configuração (EngineError)."""
    with pytest.raises(EngineError):
        MarginModel(factor=0.0)
    with pytest.raises(EngineError):
        MarginModel(factor=-1.0)


@pytest.mark.unit
def test_margin_requirement_domain_errors() -> None:
    """§3.8 — closes incompleto ou preço não positivo são erro de programa."""
    positions = {"AAA": _position("AAA", 100), "BBB": _position("BBB", -50)}
    with pytest.raises(EngineError):
        margin_requirement(positions, {"AAA": 100.0}, MarginModel())  # falta BBB
    with pytest.raises(EngineError):
        margin_requirement(positions, {"AAA": 0.0, "BBB": 200.0}, MarginModel())
