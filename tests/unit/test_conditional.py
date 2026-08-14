"""T01 — contratos de execução condicional (RF-SIG-01, design §3.2/§3.8).

Módulo folha: apenas tipos e contratos — nada executa ordem (isso é T06/T08).
`Signal`/`Strategy` da Fase 1 ficam intocados (SIG-01.1); este teste não toca
`engine/strategy.py`, e o diff dele é vazio por construção.
"""

from dataclasses import FrozenInstanceError

import pytest

from quantlab.engine.conditional import (
    Bracket,
    ConditionalIntent,
    ConditionalStrategy,
    OrderKind,
    Side,
)
from quantlab.engine.market_view import MarketView
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError

# ─── coerência tipada da intenção (design §3.8) ─────────────────────────────


@pytest.mark.unit
def test_limit_present_iff_order_type_limit() -> None:
    """`LIMIT` ⇔ `limit` presente — e só com `LIMIT`."""
    assert ConditionalIntent(Signal.ENTER, OrderKind.LIMIT, limit=10.0).limit == 10.0

    with pytest.raises(EngineError, match="LIMIT exige limit"):
        ConditionalIntent(Signal.ENTER, OrderKind.LIMIT)

    with pytest.raises(EngineError, match="exige order_type=LIMIT"):
        ConditionalIntent(Signal.ENTER, OrderKind.MARKET, limit=10.0)

    with pytest.raises(EngineError, match="exige order_type=LIMIT"):
        ConditionalIntent(Signal.EXIT, OrderKind.STOP, stop=10.0, limit=12.0)


@pytest.mark.unit
def test_stop_present_iff_order_type_stop() -> None:
    """`STOP` ⇔ `stop` presente — e só com `STOP`."""
    assert ConditionalIntent(Signal.EXIT, OrderKind.STOP, stop=10.0).stop == 10.0

    with pytest.raises(EngineError, match="STOP exige stop"):
        ConditionalIntent(Signal.EXIT, OrderKind.STOP)

    with pytest.raises(EngineError, match="exige order_type=STOP"):
        ConditionalIntent(Signal.ENTER, OrderKind.MARKET, stop=10.0)

    with pytest.raises(EngineError, match="exige order_type=STOP"):
        ConditionalIntent(Signal.ENTER, OrderKind.LIMIT, limit=12.0, stop=10.0)


@pytest.mark.unit
def test_market_order_rejects_conditional_prices() -> None:
    """`MARKET` ⇒ sem `limit` nem `stop` — a intenção a mercado é nua."""
    assert ConditionalIntent(Signal.ENTER, OrderKind.MARKET).limit is None
    assert ConditionalIntent(Signal.ENTER, OrderKind.MARKET).stop is None


# ─── bracket: par na MESMA intenção (SIG-01.2) ──────────────────────────────


@pytest.mark.unit
def test_bracket_carries_limit_and_stop_in_same_intention() -> None:
    """SIG-01.2 — o teste nomeado do design §10.1.

    A intenção carrega o bracket completo e `limit` espelha `bracket.limit`;
    o stop protetor vive em `bracket.stop`. O `decision_date` compartilhado
    (SIG-01.3) é decisão do engine (T06/T08), não deste contrato.
    """
    bracket = Bracket(limit=10.0, stop=9.5)
    intent = ConditionalIntent(
        signal=Signal.ENTER,
        order_type=OrderKind.LIMIT,
        limit=10.0,
        bracket=bracket,
    )

    assert intent.bracket is bracket
    assert intent.bracket.limit == intent.limit == 10.0
    assert intent.bracket.stop == pytest.approx(9.5)


@pytest.mark.unit
def test_bracket_requires_limit_entry_type() -> None:
    """Bracket é limite de entrada (ou take-profit) com stop — nunca STOP puro."""
    with pytest.raises(EngineError, match="bracket exige order_type=LIMIT"):
        ConditionalIntent(
            Signal.ENTER, OrderKind.STOP, stop=9.5, bracket=Bracket(limit=10.0, stop=9.5)
        )


@pytest.mark.unit
def test_bracket_requires_flat_limit_mirroring_bracket_limit() -> None:
    """Dois limites na mesma intenção divergentes são erro — o par é um só."""
    with pytest.raises(EngineError, match="limit espelhando"):
        ConditionalIntent(
            Signal.ENTER,
            OrderKind.LIMIT,
            limit=12.0,
            bracket=Bracket(limit=10.0, stop=9.5),
        )


@pytest.mark.unit
def test_bracket_validation_enforces_stop_below_limit() -> None:
    """Bracket válido exige 0 < stop < limit — entrada e saída (ADR-0007)."""
    assert Bracket(limit=10.0, stop=9.5).limit == 10.0

    for limit, stop in [(10.0, 10.0), (10.0, 10.5), (10.0, 0.0), (10.0, -1.0)]:
        with pytest.raises(EngineError, match="0 < stop < limit"):
            Bracket(limit=limit, stop=stop)


# ─── frozen (dataclass imutável) ────────────────────────────────────────────


@pytest.mark.unit
def test_intent_and_bracket_are_frozen() -> None:
    """Contratos imutáveis — o laço pode compartilhar instâncias sem cópia."""
    intent = ConditionalIntent(Signal.ENTER, OrderKind.LIMIT, limit=10.0)
    bracket = Bracket(limit=10.0, stop=9.5)

    with pytest.raises(FrozenInstanceError):
        intent.limit = 12.0  # type: ignore[misc]  # atribuição em frozen levanta em runtime
    with pytest.raises(FrozenInstanceError):
        bracket.stop = 9.0  # type: ignore[misc]  # atribuição em frozen levanta em runtime


# ─── protocolo opcional (SIG-01.1) ──────────────────────────────────────────


class _SignalOnlyStrategy:
    """Estratégia estilo Fase 1: devolve só `Signal` — satisfaz o protocolo condicional."""

    @property
    def warmup(self) -> int:
        return 5

    def on_bar(self, view: MarketView) -> Signal | None:
        return None


class _ConditionalStrategyImpl:
    """Estratégia condicional: devolve `ConditionalIntent`."""

    @property
    def warmup(self) -> int:
        return 5

    def on_bar(self, view: MarketView) -> Signal | ConditionalIntent | None:
        return None


@pytest.mark.unit
def test_fase1_signal_only_strategy_satisfies_conditional_protocol() -> None:
    """SIG-01.1 — o protocolo condicional é opcional: a Fase 1 continua válida.

    A união `Signal | ConditionalIntent | None` engloba `Signal | None`, então
    uma estratégia da Fase 1 satisfaz o protocolo estruturalmente —
    `runtime_checkable` permite confirmar com `isinstance`. O teste de
    execução sem mudança é T11a; aqui vale o contrato tipado.
    """
    assert isinstance(_SignalOnlyStrategy(), ConditionalStrategy)


@pytest.mark.unit
def test_conditional_strategy_satisfies_protocol() -> None:
    """Uma estratégia que devolve `ConditionalIntent` satisfaz o protocolo."""
    assert isinstance(_ConditionalStrategyImpl(), ConditionalStrategy)


# ─── enum de vocabulário ────────────────────────────────────────────────────


@pytest.mark.unit
def test_order_kind_and_side_are_stable_string_enum_values() -> None:
    """`StrEnum` — valores sobrevivem a `backtest_runs` sem conversão (mesma razão de `Signal`)."""
    assert OrderKind.MARKET.value == "market"
    assert OrderKind.LIMIT.value == "limit"
    assert OrderKind.STOP.value == "stop"
    assert Side.BUY.value == "buy"
    assert Side.SELL.value == "sell"
