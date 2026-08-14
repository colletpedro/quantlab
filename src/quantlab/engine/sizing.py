"""Position sizing — T04, design §3.4/§3.8, ADR-0008, RF-SIZ-01/02/03/04.

O sizer devolve uma **fração** do patrimônio (SIZ-04.2) — nunca quantidade;
a conversão em quantidade inteira é do broker (T06, sequência de RF-CST-01).
As políticas são funções puras do estado recebido em `SizingInputs`; o laço
(T11a) decide QUANDO consultar (entrada, mudança de `k`) e constrói o
`SizingInputs` a partir do `Portfolio`.

`positions` é ``dict[str, int]`` (ticker → quantidade) — emenda T04 no
design §3.4: o sizer consome só a quantidade aberta; o `Position` da Fase 1
carrega `entry_price`/`entry_date` que aqui seriam peso morto.

Nenhum `datetime`/`timezone` (RNF-07): só aritmética sobre frações.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from quantlab.exceptions import EngineError

__all__ = [
    "EqualWeightOpen",
    "FixedOneOverN",
    "Sizer",
    "SizingInputs",
    "rebalance_deviation_pp",
]


@dataclass(frozen=True)
class SizingInputs:
    """Estado que o sizer recebe (SIZ-04.2) — bag imutável, construído pelo laço.

    - ``equity``: patrimônio atual (caixa + posições marcadas a mercado);
    - ``cash``: caixa disponível;
    - ``positions``: ticker → **quantidade** aberta (não `Position` — T04);
    - ``last_close``: último close conhecido por ativo (mark-to-market);
    - ``n``: ativos do run, fixado no início (SIZ-02.1/P3).
    """

    equity: float
    cash: float
    n: int
    positions: dict[str, int] = field(default_factory=dict)
    last_close: dict[str, float] = field(default_factory=dict)


class Sizer(Protocol):
    """Política de sizing plugável (SIZ-01.1/04.1)."""

    def target_fraction(self, ticker: str, inputs: SizingInputs) -> float:
        """Fração do patrimônio alvo para ``ticker`` (SIZ-04.2), em ``(0, 1]``.

        Nunca devolve quantidade — a conversão é do broker (SIZ-01.2).
        Pré-condição: ``inputs.n ≥ 1`` (e ``k ≥ 1`` para políticas baseadas
        em posições abertas). Raises: ``EngineError`` se violada.
        """

        ...


@dataclass(frozen=True)
class FixedOneOverN(Sizer):
    """Peso fixo ``1/N`` — default (ADR-0008), N do run fixado no início.

    Função pura de ``n``: não consulta mercado nem posições (SIZ-02.1).
    ``N = 1`` degenera em all-in, ``1.0`` (SIZ-02.3/D1). Ativo do run que
    nunca teve barra conta no N mas nunca recebe alvo — o laço (T11a) é
    quem não pergunta por ele; aqui o alvo seria ``1/n`` se perguntado.

    Pré-condição: ``n ≥ 1`` (EngineError caso contrário).
    """

    n: int

    def __post_init__(self) -> None:
        if self.n < 1:
            raise EngineError(f"FixedOneOverN: n {self.n} inválido — exige n ≥ 1.")

    def target_fraction(self, ticker: str, inputs: SizingInputs) -> float:
        return 1.0 / self.n


@dataclass(frozen=True)
class EqualWeightOpen(Sizer):
    """Peso igual entre posições abertas, ``1/k`` — opcional (SIZ-03.1).

    O rebalance é disparado pelo laço (T11a) **apenas** em mudança de ``k``
    (SIZ-03.4) e executa no próximo open (ADR-0002); ``threshold_pp`` é o
    limiar que gateia o ajuste (SIZ-03.3) — o helper puro
    `rebalance_deviation_pp` calcula o desvio, o laço compara.

    Pré-condição: ``k = len(inputs.positions) ≥ 1`` — sem posições abertas,
    ``1/k`` é indefinido (EngineError).
    """

    threshold_pp: float = 1.0

    def __post_init__(self) -> None:
        if self.threshold_pp < 0:
            raise EngineError(
                f"EqualWeightOpen: threshold_pp {self.threshold_pp} inválido — exige ≥ 0."
            )

    def target_fraction(self, ticker: str, inputs: SizingInputs) -> float:
        k = len(inputs.positions)
        if k < 1:
            raise EngineError("EqualWeightOpen: 1/k indefinido — sem posições abertas (k = 0).")
        return 1.0 / k


def rebalance_deviation_pp(weight_fraction: float, k: int) -> float:
    """Desvio ``|w - 1/k|`` em pp absolutos do patrimônio (SIZ-03.3).

    Pré-condições: ``0 ≤ weight_fraction ≤ 1``; ``k ≥ 1``.
    Pós-condição: valor não negativo; ``< threshold_pp`` ⇒ o laço não gera
    rebalance (ruído de preço não gera giro).

    Raises:
        EngineError: se ``weight_fraction`` fora de ``[0, 1]`` ou ``k < 1``.
    """

    if not 0.0 <= weight_fraction <= 1.0:
        raise EngineError(f"rebalance_deviation_pp: peso {weight_fraction} fora de [0, 1].")
    if k < 1:
        raise EngineError(f"rebalance_deviation_pp: k {k} inválido — exige k ≥ 1.")

    return abs(weight_fraction - 1.0 / k) * 100.0
