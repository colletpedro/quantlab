"""Margem e custo de aluguel — 2b (T03: `BorrowFeeModel`; T04: `MarginModel`).

`BorrowFeeModel` (RF-SHT-03, ADR-0010) é o custo de CARREGAMENTO de posição
short: determinístico, anualizado, debitado diariamente sobre o notional
short — ``|qty| x close x fee_annual / 252`` (SHT-03 CA-03.1). O débito
acontece no CLOSE, em etapa própria (laço, T08a) — aqui mora a forma fechada
e a disponibilidade de aluguel.

Disponibilidade (R1): default **ilimitada** (`unlimited=True`) — nenhum short
é bloqueado (CA-03.4, lado esquerdo); com `unlimited=False`, ativo em
`unavailable` na data não executa e o evento é logado e contado no `convert`
(CA-03.4, lado direito — `MechanismCounters.borrow_rejections`).

Nenhum `datetime`/`timezone` (RNF-07): `decision_date` é `date` naive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from quantlab.exceptions import EngineError

if TYPE_CHECKING:  # mypy apenas — evita ciclo em runtime
    from quantlab.engine.portfolio import Position

__all__ = ["BorrowFeeModel", "MarginModel", "margin_requirement", "margin_utilization"]


@dataclass(frozen=True)
class MarginModel:
    """Fator único de margem (RF-MRG-01/D1, ADR-0009, R3).

    ``margin_requirement = Σ|qty_i| x close_i x factor`` — valores ABSOLUTOS,
    nunca soma algébrica (MRG-01 CA-01.1). Fator ÚNICO para long e short é
    uma **simplificação declarada** (R3); a equivalência com dois níveis
    (fator long x fator short) está documentada como alternativa descartada
    no ADR-0009 e na spec §8.1. Default **1.0 explícito e configurável**
    (CA-01.5). Com apenas longs e factor 1.0, a margem é o notional longo e o
    invariante ``equity >= margem`` reduz exatamente a ``cash >= 0`` —
    regressão long-only (CA-01.2).
    """

    factor: float = 1.0

    def __post_init__(self) -> None:
        if self.factor <= 0:
            raise EngineError(f"MarginModel: factor {self.factor} inválido — exige > 0 (ADR-0009).")


def margin_requirement(
    positions: dict[str, Position],
    closes: dict[str, float],
    model: MarginModel,
) -> float:
    """Exigência de margem — ``Σ_i |qty_i| x close_i x factor`` (MRG-01 CA-01.1).

    Função PURA (só lê). Valores ABSOLUTOS: longs e shorts somam (nunca se
    cancelam — a soma algébrica seria a armadilha). Long-only com factor 1.0
    ⇒ notional longo ⇒ ``equity >= margem ⇔ cash >= 0`` (CA-01.2 — regressão).

    Raises:
        EngineError: `closes` incompleto (faltou ativo com posição) ou preço
            não positivo — erro de programação (o laço garante a pré-condição
            de `market_to_market` a cada barra, §3.8).
    """
    missing = sorted(set(positions) - set(closes))
    if missing:
        raise EngineError(
            f"margin_requirement: faltou último close conhecido para {missing} "
            "— o laço deve passar o close de todos os ativos com posição (§3.8)."
        )
    bad = sorted(t for t, c in closes.items() if c <= 0)
    if bad:
        raise EngineError(f"margin_requirement: close não positivo em {bad} (§3.8).")
    total = 0.0
    for ticker, position in positions.items():
        total += abs(position.quantity) * closes[ticker] * model.factor
    return total


def margin_utilization(equity: float, requirement: float) -> float | None:
    """Utilização de margem — ``requirement / equity`` (MRG-01 CA-01.4).

    ``equity <= 0`` ⇒ ``None`` explícito (R6 — nunca NaN, nunca zero
    fabricado; o fundo quebrado deriva `None`, MRG-03 CA-03.2).
    """
    if equity <= 0:
        return None
    return requirement / equity


@dataclass(frozen=True)
class BorrowFeeModel:
    """Modelo determinístico de custo de aluguel (ADR-0010, RF-SHT-03).

    - ``fee_annual``: default **0,50% a.a.** — premissa NÃO calibrada (viés
      declarado em RF-MET-06/CA-06.1, R1).
    - ``unlimited``: default **True** — a disponibilidade nunca bloqueia
      (CA-03.4 esquerda). ``False`` habilita a restrição por ticker.
    - ``unavailable``: ativos indisponíveis para aluguel (restrição
      configurável; sem granularidade por data — decisão local documentada:
      não há dado de indisponibilidade temporal ingerido, a restrição é por
      ticker, determinística).
    """

    fee_annual: float = 0.005
    unlimited: bool = True
    unavailable: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.fee_annual < 0:
            raise EngineError(
                f"BorrowFeeModel: fee_annual {self.fee_annual} negativo — exige >= 0."
            )

    def daily_fee(self, qty: float, close: float) -> float:
        """Fee diário do notional short — ``|qty| x close x fee_annual / 252``.

        Forma fechada de SHT-03 CA-03.1. Pré-condições: ``close > 0`` e
        ``qty != 0`` (não existe fee sobre posição zerada — CA-03.2: o dia em
        que a posição já foi coberta não paga fee; o laço só chama com short
        aberto no close). Raises: `EngineError` se violadas.
        """
        if close <= 0:
            raise EngineError(f"BorrowFeeModel.daily_fee: close {close} não positivo.")
        if qty == 0:
            raise EngineError("BorrowFeeModel.daily_fee: qty == 0 — fee só sobre short aberto.")
        return abs(qty) * close * self.fee_annual / 252.0

    def is_available(self, ticker: str, decision_date: date) -> bool:
        """Disponibilidade de aluguel na data (CA-03.4).

        ``unlimited=True`` (default) ⇒ sempre True — a disponibilidade NUNCA
        bloqueia (lado esquerdo do CA-03.4). ``unlimited=False`` ⇒ True sse
        ``ticker not in unavailable`` (lado direito). `decision_date` faz
        parte da assinatura do design §3.4 mas não discrimina por data (a
        restrição é por ticker — decisão local documentada acima).
        """
        if self.unlimited:
            return True
        return ticker not in self.unavailable
