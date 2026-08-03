"""Objetos de domínio que a camada de persistência lê e escreve.

Todos usam ``datetime.date`` — data-calendário naive, RNF-07. A tradução para
o ``datetime`` que o BSON exige acontece **só** em
:mod:`quantlab.storage.repository`; nenhum tipo aqui carrega hora ou timezone.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from quantlab.exceptions import DataError

__all__ = [
    "Bar",
    "CorporateAction",
    "CorporateActionKind",
    "QuarantinedBar",
]


class CorporateActionKind(StrEnum):
    """Tipo de evento corporativo — design §3.2.

    ``StrEnum`` porque o valor vai direto para o documento Mongo e volta dele
    como string; sem isso, a serialização precisaria de conversão manual nas
    duas pontas.
    """

    DIVIDEND = "dividend"
    SPLIT = "split"


@dataclass(frozen=True, slots=True)
class Bar:
    """Uma barra diária **bruta** — design §3.1.

    Bruta é o ponto: ADR-0003 manda persistir o não-ajustado. Nenhum campo
    aqui recebe fator de provento.
    """

    ticker: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True, slots=True)
class CorporateAction:
    """Dividendo ou split — design §3.2.

    ``value`` existe se e somente se for dividendo; ``ratio``, se e somente se
    for split. A validação é no construtor porque um evento meio preenchido
    corromperia o fator de ajuste de forma silenciosa e plausível.
    """

    ticker: str
    date: date
    kind: CorporateActionKind
    value: float | None = None
    ratio: float | None = None

    def __post_init__(self) -> None:
        if self.kind is CorporateActionKind.DIVIDEND:
            if self.value is None or self.ratio is not None:
                raise DataError(
                    f"Dividendo em {self.ticker} {self.date.isoformat()} precisa de `value` "
                    "e não pode ter `ratio`."
                )
            if self.value <= 0:
                raise DataError(
                    f"Dividendo em {self.ticker} {self.date.isoformat()} tem valor não "
                    f"positivo ({self.value})."
                )
        else:
            if self.ratio is None or self.value is not None:
                raise DataError(
                    f"Split em {self.ticker} {self.date.isoformat()} precisa de `ratio` "
                    "e não pode ter `value`."
                )
            if self.ratio <= 0:
                raise DataError(
                    f"Split em {self.ticker} {self.date.isoformat()} tem razão não "
                    f"positiva ({self.ratio})."
                )


@dataclass(frozen=True, slots=True)
class QuarantinedBar:
    """Barra rejeitada pela validação — design §3.3.

    Guarda o payload **bruto** como veio do provedor: quarentena serve para
    diagnóstico, e diagnóstico precisa do dado original, não de uma versão já
    interpretada por quem rejeitou.
    """

    ticker: str
    date: date
    raw: dict[str, Any]
    reasons: tuple[str, ...]
    ingestion_run_id: str | None = None

    def __post_init__(self) -> None:
        if not self.reasons:
            raise DataError(
                f"Barra quarentenada de {self.ticker} {self.date.isoformat()} sem nenhuma "
                "razão de rejeição. Quarentena sem motivo é dado perdido."
            )
