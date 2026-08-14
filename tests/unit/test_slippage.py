"""T03 — slippage (design §3.3/§3.8, ADR-0006, RF-SLP-01/02/04).

Fixtures de papel com derivação auditável (RNF-03): a forma funcional
cravada do ADR-0006 vira teste de igualdade contra valor calculado à mão.
"""

from __future__ import annotations

import pytest
from structlog.typing import EventDict

from quantlab.engine.conditional import Side
from quantlab.engine.slippage import FixedBps, Participation, SlippageModel
from quantlab.exceptions import EngineError

# ─── FixedBps — forma fechada (SLP-02.1) ────────────────────────────────────


@pytest.mark.unit
def test_fixed_bps_execution_price() -> None:
    """SLP-02.1 — compra `ref x (1 + bps/10000)`, venda `ref x (1 - bps/10000)`.

    Default determinístico do ADR-0006: bps = 1.0.
    ref = 100.00 ⇒ compra 100.01, venda 99.99.
    """
    model = FixedBps()

    assert model.execution_price(100.0, Side.BUY, 1, None) == pytest.approx(100.01)
    assert model.execution_price(100.0, Side.SELL, 1, None) == pytest.approx(99.99)

    # bps configurável: 50 bps ⇒ 0.50% de desvio em cada lado.
    model_50 = FixedBps(bps=50.0)
    assert model_50.execution_price(100.0, Side.BUY, 1, None) == pytest.approx(100.5)
    assert model_50.execution_price(100.0, Side.SELL, 1, None) == pytest.approx(99.5)

    # bps = 0 ⇒ preço de referência intacto (modelo nulo).
    zero = FixedBps(bps=0.0)
    assert zero.execution_price(100.0, Side.BUY, 1, None) == pytest.approx(100.0)
    assert zero.execution_price(100.0, Side.SELL, 1, None) == pytest.approx(100.0)


# ─── Participation — forma funcional cravada (ADR-0006/C2) ──────────────────


@pytest.mark.unit
def test_participation_slippage_matches_closed_form() -> None:
    """Forma fechada do ADR-0006: `slippage_bps = bps x (1 + k x q/ADV)`.

    bps = 1.0, k = 1.0, ref = 100.00, qty = 100, adv = 10_000:
    q/ADV = 0.01 ⇒ slippage_bps = 1.01 ⇒ fator = 1.000101.
    Compra = 100.0101; venda = 99.9899.
    """
    model = Participation()  # defaults determinísticos bps = 1.0, k = 1.0

    assert model.execution_price(100.0, Side.BUY, 100, 10_000.0) == pytest.approx(100.0101)
    assert model.execution_price(100.0, Side.SELL, 100, 10_000.0) == pytest.approx(99.9899)

    # k configurável: k = 0 ⇒ só o componente base (vira FixedBps com bps próprio).
    flat = Participation(k=0.0)
    assert flat.execution_price(100.0, Side.BUY, 100, 10_000.0) == pytest.approx(100.01)

    # bps configurável: bps = 2.0 ⇒ slippage_bps = 2.02 ⇒ fator 1.000202.
    stronger = Participation(bps=2.0)
    assert stronger.execution_price(100.0, Side.BUY, 100, 10_000.0) == pytest.approx(100.0202)


@pytest.mark.unit
def test_slippage_monotonic_in_participation() -> None:
    """SLP-03.1 — q/ADV maior ⇒ preço pior (compra mais cara, venda mais barata)."""
    model = Participation()
    low = model.execution_price(100.0, Side.BUY, 100, 10_000.0)  # q/ADV = 0.01
    high = model.execution_price(100.0, Side.BUY, 5_000, 10_000.0)  # q/ADV = 0.50
    assert high > low

    low_sell = model.execution_price(100.0, Side.SELL, 100, 10_000.0)
    high_sell = model.execution_price(100.0, Side.SELL, 5_000, 10_000.0)
    assert high_sell < low_sell

    # Direção desfavorável (SLP-01.1): compra nunca abaixo do ref; venda nunca acima.
    assert low >= 100.0
    assert low_sell <= 100.0


@pytest.mark.unit
def test_participation_falls_back_to_fixed_with_warning(
    log_events: list[EventDict],
) -> None:
    """SLP-03.2 — adv=None executa como FixedBps (bps=1.0) e emite aviso, sem falhar."""
    model = Participation()
    buy_price = model.execution_price(100.0, Side.BUY, 5_000, None)
    sell_price = model.execution_price(100.0, Side.SELL, 5_000, None)

    # Mesmo valor do FixedBps com bps=1.0, nos dois lados.
    assert buy_price == pytest.approx(100.01)
    assert sell_price == pytest.approx(99.99)

    # Um aviso por chamada, com o lado registrado.
    assert len(log_events) == 2
    assert log_events[0]["event"] == "slippage.adv_unavailable_fallback_fixed"
    assert log_events[0]["bps"] == 1.0
    assert log_events[0]["side"] == "buy"
    assert log_events[1]["side"] == "sell"


# ─── erros de domínio (§3.8 — EngineError) ──────────────────────────────────


@pytest.mark.unit
def test_slippage_domain_errors_raise_engine_error() -> None:
    """§3.8 — bps < 0, k < 0, ref ≤ 0, qty < 1 e adv ≤ 0 são EngineError."""
    with pytest.raises(EngineError):
        FixedBps(bps=-1.0)
    with pytest.raises(EngineError):
        Participation(bps=-1.0)
    with pytest.raises(EngineError):
        Participation(k=-1.0)

    fixed = FixedBps()
    participation = Participation()
    with pytest.raises(EngineError):
        fixed.execution_price(0.0, Side.BUY, 1, None)
    with pytest.raises(EngineError):
        fixed.execution_price(100.0, Side.BUY, 0, None)
    with pytest.raises(EngineError):
        participation.execution_price(100.0, Side.BUY, 1, 0.0)  # adv ≤ 0 e não None
    with pytest.raises(EngineError):
        participation.execution_price(-5.0, Side.BUY, 1, 10_000.0)


@pytest.mark.unit
def test_slippage_models_are_runtime_checkable() -> None:
    """O Protocol é `runtime_checkable` — diagnóstico por `isinstance`."""
    assert isinstance(FixedBps(), SlippageModel)
    assert isinstance(Participation(), SlippageModel)
