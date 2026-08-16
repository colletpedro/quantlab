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

from quantlab.exceptions import EngineError

__all__ = ["BorrowFeeModel"]


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
