"""Slippage de preço — T03, design §3.3/§3.8, ADR-0006, RF-SLP-01/02/04.

Aplica-se SÓ a ordens a mercado e a stops convertidos em mercado
(SLP-04.1/04.4): quem garante que uma ordem limitada nunca é violada é o
broker (T08), não este módulo. Custos NUNCA entram no preço de execução
(SLP-04.3) — debitam do caixa em etapa própria (RF-CST-01). O corte de
**quantidade** por participação vive em `engine/liquidity.py` (T02) e
ocorre ANTES deste modelo ver o `qty` (R1: SIZING → CAP → INTEIRAS →
CAIXA/CUSTOS).

Nenhum `datetime`/`timezone` (RNF-07): só aritmética sobre `float`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from quantlab.engine.conditional import Side
from quantlab.exceptions import EngineError
from quantlab.logging import get_logger

_log = get_logger(__name__)

__all__ = ["FixedBps", "Participation", "SlippageModel"]


def _validate_execution_inputs(ref: float, qty: int) -> None:
    """Pré-condições comuns de `execution_price` (design §3.8)."""
    if ref <= 0:
        raise EngineError(f"execution_price: ref {ref} inválido — exige ref > 0.")
    if qty < 1:
        raise EngineError(f"execution_price: qty {qty} inválido — exige qty ≥ 1.")


@runtime_checkable
class SlippageModel(Protocol):
    """Modelo de slippage de preço (SLP-01.1 — sempre na direção desfavorável).

    Contrato (SLP-04.1/04.3): aplicado SÓ a ordens a mercado e a stops
    convertidos; limite nunca violado (garantia do broker, T08); custos
    fora do preço de execução.
    """

    def execution_price(self, ref: float, side: Side, qty: int, adv: float | None) -> float:
        """Preço de execução ajustado pelo modelo, na direção desfavorável.

        Pré-condições: ``ref > 0``; ``qty ≥ 1``.
        Pós-condições: compra ⇒ ≥ ``ref``; venda ⇒ ≤ ``ref`` (SLP-01.1).

        Raises:
            EngineError: se ``ref ≤ 0`` ou ``qty < 1``.
        """

        ...


@dataclass(frozen=True)
class FixedBps(SlippageModel):
    """Slippage fixo em pontos-base (SLP-02.1; default do ADR-0006).

    Compra: ``ref x (1 + bps/10000)``; venda: ``ref x (1 - bps/10000)``.
    Pré-condição: ``bps ≥ 0`` (EngineError caso contrário).
    """

    bps: float = 1.0

    def __post_init__(self) -> None:
        if self.bps < 0:
            raise EngineError(f"FixedBps: bps {self.bps} inválido — exige bps ≥ 0.")

    def execution_price(self, ref: float, side: Side, qty: int, adv: float | None) -> float:
        _validate_execution_inputs(ref, qty)
        factor = 1.0 + self.bps / 10_000.0
        if side is Side.BUY:
            return ref * factor
        return ref * (2.0 - factor)


@dataclass(frozen=True)
class Participation(SlippageModel):
    """Slippage por participação no ADV — forma funcional CRAVADA (ADR-0006/C2).

    ``slippage_bps = bps x (1 + k x q/ADV)`` — linear em ``q/ADV`` até o cap
    (o cap é da T02, que entrega o ``qty`` já cortado); preço de execução
    ``ref x (1 +- slippage_bps/10000)`` na direção desfavorável.

    - ``adv is None`` ⇒ recai em `FixedBps` com aviso (SLP-03.2), sem falhar;
    - monotônica em ``q/ADV`` (SLP-03.1): participação maior ⇒ preço pior.

    Pré-condições: ``bps ≥ 0``; ``k ≥ 0``; ``adv > 0`` ou ``None``
    (EngineError caso contrário). Defaults determinísticos ``bps = 1.0`` e
    ``k = 1.0``, configuráveis.
    """

    bps: float = 1.0
    k: float = 1.0

    def __post_init__(self) -> None:
        if self.bps < 0:
            raise EngineError(f"Participation: bps {self.bps} inválido — exige bps ≥ 0.")
        if self.k < 0:
            raise EngineError(f"Participation: k {self.k} inválido — exige k ≥ 0.")

    def execution_price(self, ref: float, side: Side, qty: int, adv: float | None) -> float:
        _validate_execution_inputs(ref, qty)

        if adv is None:
            _log.warning(
                "slippage.adv_unavailable_fallback_fixed",
                bps=self.bps,
                side=side.value,
                qty=qty,
            )
            factor = 1.0 + self.bps / 10_000.0
            if side is Side.BUY:
                return ref * factor
            return ref * (2.0 - factor)

        if adv <= 0:
            raise EngineError(f"Participation: adv {adv} inválido — exige adv > 0 ou None.")

        slippage_bps = self.bps * (1.0 + self.k * (qty / adv))
        factor = 1.0 + slippage_bps / 10_000.0
        if side is Side.BUY:
            return ref * factor
        return ref * (2.0 - factor)
