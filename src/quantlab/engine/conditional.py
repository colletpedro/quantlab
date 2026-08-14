"""Contratos de execução condicional — T01, design §3.2/§3.8, RF-SIG-01.

O vocabulário que o broker (T06/T08) e o laço (T11) vão consumir. Nada aqui
executa ordem: a estratégia continua emitindo **intenção** (ENG-05.2), e o
que esta intenção pode carregar além de `Signal` é o que este módulo define —
tipo de ordem, preço de limite/stop e o par bracket na mesma intenção.

`Signal`/`Strategy` da Fase 1 ficam intocados (SIG-01.1): `ConditionalStrategy`
é um Protocol **opcional**, e uma estratégia que só devolve `Signal` também o
satisfaz — o engine aceita os dois, sem alterar `engine/strategy.py`.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from quantlab.engine.market_view import MarketView
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError

__all__ = ["Bracket", "ConditionalIntent", "ConditionalStrategy", "OrderKind", "Side"]


class OrderKind(StrEnum):
    """Tipo de ordem que uma intenção condicional pode carregar — design §3.2.

    `StrEnum` para que o valor sobreviva a `backtest_runs` (§3.5) e volte de lá
    sem conversão manual — mesma razão de `Signal` e `CorporateActionKind`.
    """

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class Side(StrEnum):
    """Lado da execução — vocabulário de execução (T01; design §3.3 importa daqui)."""

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Bracket:
    """Par limite + stop derivados da MESMA intenção (SIG-01.2, ADR-0007).

    Pré-condição: ``0 < stop < limit``. Vale nos dois sentidos de ADR-0007 —
    bracket de entrada (limite de compra acima do stop protetor) e bracket de
    saída (take-profit acima do stop sobre posição aberta).
    """

    limit: float
    stop: float

    def __post_init__(self) -> None:
        if not (0 < self.stop < self.limit):
            raise EngineError(
                f"Bracket inválido: exige 0 < stop < limit, recebeu "
                f"stop={self.stop}, limit={self.limit}."
            )


@dataclass(frozen=True)
class ConditionalIntent:
    """Intenção condicional — o que a estratégia devolve além de `Signal`.

    Coerência tipada (design §3.8, emendada na T01):

    - ``order_type == LIMIT`` ⇔ ``limit`` presente
    - ``order_type == STOP`` ⇔ ``stop`` presente
    - ``order_type == MARKET`` ⇒ sem ``limit`` nem ``stop``
    - ``bracket`` presente ⇒ ``order_type == LIMIT`` e ``limit == bracket.limit``
      — o par limite + stop vive na MESMA intenção (SIG-01.2); o stop protetor
      está em ``bracket.stop``

    Pós-condição: as ordens derivadas desta intenção compartilham o mesmo
    `decision_date` (SIG-01.3) — decisão do engine (T06/T08), não deste contrato.
    """

    signal: Signal
    order_type: OrderKind
    limit: float | None = None
    stop: float | None = None
    bracket: Bracket | None = None

    def __post_init__(self) -> None:
        if self.order_type is OrderKind.LIMIT:
            if self.limit is None:
                raise EngineError("order_type=LIMIT exige limit.")
        elif self.limit is not None:
            raise EngineError("limit presente exige order_type=LIMIT.")

        if self.order_type is OrderKind.STOP:
            if self.stop is None:
                raise EngineError("order_type=STOP exige stop.")
        elif self.stop is not None:
            raise EngineError("stop presente exige order_type=STOP.")

        if self.bracket is not None:
            if self.order_type is not OrderKind.LIMIT:
                raise EngineError("bracket exige order_type=LIMIT.")
            if self.limit is None or self.limit != self.bracket.limit:
                raise EngineError(
                    "bracket exige limit espelhando bracket.limit na mesma intenção (SIG-01.2)."
                )


@runtime_checkable
class ConditionalStrategy(Protocol):
    """Protocolo opcional de estratégia com ordens condicionais (SIG-01.1).

    Uma estratégia da Fase 1 (que devolve apenas ``Signal | None``) também
    satisfaz este protocolo estruturalmente — a união `Signal |
    ConditionalIntent | None` engloba `Signal | None` — e `runtime_checkable`
    permite `isinstance` para diagnóstico. O engine não checa: ele chama.
    """

    @property
    def warmup(self) -> int:
        """Barras consumidas antes de a estratégia poder decidir — mesmo contrato da Fase 1."""

        ...

    def on_bar(self, view: MarketView) -> Signal | ConditionalIntent | None:
        """Decide com a informação disponível até a barra corrente.

        `None` = nada a fazer; `Signal` = decisão simples da Fase 1;
        `ConditionalIntent` = decisão com tipo de ordem e preços de
        limite/stop (bracket na mesma intenção). A estratégia não escolhe
        quando executa — ADR-0002 escolhe.
        """

        ...
