"""T04 — sizing (design §3.4/§3.8, ADR-0008, RF-SIZ-01/02/03/04).

Fixtures de papel (RNF-03): o alvo é fração pura, calculada à mão.
"""

from __future__ import annotations

import pytest

from quantlab.engine.sizing import (
    EqualWeightOpen,
    FixedOneOverN,
    SizingInputs,
    rebalance_deviation_pp,
)
from quantlab.exceptions import EngineError


def _inputs(n: int, positions: dict[str, int] | None = None) -> SizingInputs:
    return SizingInputs(
        equity=10_000.0,
        cash=10_000.0,
        n=n,
        positions=positions or {},
    )


# ─── FixedOneOverN — 1/N, N do run (SIZ-02.1/02.3, ADR-0008) ────────────────


@pytest.mark.unit
def test_target_is_equity_over_n_fixed_and_n1_is_allin() -> None:
    """CA-02.1/CA-02.3 — `FixedOneOverN(20)` ⇒ 0.05; `FixedOneOverN(1)` ⇒ 1.0.

    N fixado no run, independente de posições abertas (SIZ-02.1).
    """
    assert FixedOneOverN(n=20).target_fraction("AAA4", _inputs(n=20)) == pytest.approx(0.05)
    assert FixedOneOverN(n=4).target_fraction("AAA4", _inputs(n=4)) == pytest.approx(0.25)
    assert FixedOneOverN(n=1).target_fraction("AAA4", _inputs(n=1)) == pytest.approx(1.0)

    # O alvo não depende do que está aberto: com 3 posições abertas, 1/4 segue.
    assert FixedOneOverN(n=4).target_fraction(
        "AAA4", _inputs(n=4, positions={"AAA4": 10, "BBBB3": 10, "CCCC2": 10})
    ) == pytest.approx(0.25)


@pytest.mark.unit
def test_sizer_returns_fraction_never_quantity() -> None:
    """SIZ-04.2 — a política devolve fração do patrimônio, nunca quantidade.

    equity = 10.000, alvo 1/4 ⇒ 0.25, não 2500 ações (e nem 250).
    """
    target = FixedOneOverN(n=4).target_fraction("AAA4", _inputs(n=4))
    assert target == pytest.approx(0.25)
    assert 0.0 < target <= 1.0
    # Um sizer que "convertesse" para quantidade daria 2.500 — nunca aparece aqui.
    assert target != pytest.approx(2_500.0)


# ─── EqualWeightOpen — 1/k (SIZ-03.1) ───────────────────────────────────────


@pytest.mark.unit
def test_equal_weight_open_is_one_over_k() -> None:
    """CA-03.1 — k posições abertas ⇒ alvo 1/k."""
    policy = EqualWeightOpen()
    three = _inputs(n=20, positions={"AAA4": 100, "BBBB3": 100, "CCCC2": 100})
    assert policy.target_fraction("AAA4", three) == pytest.approx(1.0 / 3.0)

    two = _inputs(n=20, positions={"AAA4": 100, "BBBB3": 100})
    assert policy.target_fraction("AAA4", two) == pytest.approx(0.5)


@pytest.mark.unit
def test_rebalance_threshold_gates_the_adjustment() -> None:
    """CA-03.3 — desvio |w - 1/k| em pp; < 1 pp (default) ⇒ nenhum rebalance.

    k = 4 ⇒ alvo 1/4 = 25%. Desvio de 0,4 pp ⇒ abaixo do limiar (sem giro);
    de 1,2 pp ⇒ acima (rebalance); exatamente 1,0 pp ⇒ no limiar (dispara).
    """
    assert rebalance_deviation_pp(weight_fraction=0.254, k=4) == pytest.approx(0.4)
    assert rebalance_deviation_pp(weight_fraction=0.262, k=4) == pytest.approx(1.2)

    threshold_pp = EqualWeightOpen().threshold_pp  # default 1.0
    assert rebalance_deviation_pp(0.254, k=4) < threshold_pp  # sem trade
    assert rebalance_deviation_pp(0.262, k=4) >= threshold_pp  # trade
    assert rebalance_deviation_pp(0.25, k=4) == pytest.approx(0.0)  # no alvo


@pytest.mark.unit
def test_sizing_is_deterministic() -> None:
    """RNF-01 — mesma entrada ⇒ mesmo alvo, por construção (funções puras)."""
    inputs = _inputs(n=20, positions={"AAA4": 100, "BBBB3": 100})

    first = FixedOneOverN(n=20).target_fraction("AAA4", inputs)
    second = FixedOneOverN(n=20).target_fraction("AAA4", inputs)
    assert first == second == pytest.approx(0.05)

    policy = EqualWeightOpen()
    assert policy.target_fraction("AAA4", inputs) == policy.target_fraction("AAA4", inputs)


# ─── erros de domínio (§3.8 — EngineError) ──────────────────────────────────


@pytest.mark.unit
def test_sizing_domain_errors_raise_engine_error() -> None:
    """§3.8 — n < 1, k = 0, threshold < 0 e peso fora de [0, 1] são EngineError."""
    with pytest.raises(EngineError):
        FixedOneOverN(n=0)
    with pytest.raises(EngineError):
        FixedOneOverN(n=-2)

    empty = _inputs(n=20)  # sem posições abertas
    with pytest.raises(EngineError):
        EqualWeightOpen().target_fraction("AAA4", empty)

    with pytest.raises(EngineError):
        EqualWeightOpen(threshold_pp=-0.5)

    with pytest.raises(EngineError):
        rebalance_deviation_pp(weight_fraction=1.5, k=4)
    with pytest.raises(EngineError):
        rebalance_deviation_pp(weight_fraction=0.25, k=0)
