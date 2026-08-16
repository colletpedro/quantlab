"""Contrato de estratégia — C2, design §4.2.

Duas peças e nada mais: o que a estratégia pode dizer (`Signal`) e o que ela
precisa implementar (`Strategy`).

**A estratégia recebe apenas a `MarketView`.** Não recebe caixa, posição,
histórico de trades nem configuração de custos — ENG-05.2 por construção: não
há o que consultar. A separação é conceitual antes de ser técnica: a
estratégia emite **intenção**, o engine decide **execução e tamanho**. É isso
que permite trocar o esquema de sizing na Fase 2 sem tocar em estratégia
nenhuma.

`Strategy` é `Protocol` estrutural, como `MarketDataProvider` em `ingestion/`:
uma estratégia nova não herda de nada e o engine a executa sem alteração
(ENG-05.1). O engine depende da forma, não da linhagem.
"""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from quantlab.engine.market_view import MarketView

__all__ = ["Signal", "Strategy"]


class Signal(StrEnum):
    """A intenção que uma estratégia consegue expressar — design §4.2.

    Só duas, e é de propósito: a Fase 1 é long-only, sem sizing (premissas 2 e
    3, decisão D1). "Quanto" não está aqui porque não é decisão da estratégia.

    `StrEnum` para que o valor sobreviva a `backtest_runs` (§3.5) e volte de lá
    sem conversão manual — mesma razão de `CorporateActionKind`.

    **Fase 2b (T01, RF-SHT-01/D3):** `ENTER_SHORT`/`EXIT_SHORT` são
    **opcionais e retrocompatíveis** — uma estratégia long-only (Fase 1/2a)
    emite apenas `ENTER`/`EXIT` e roda sem mudança de comportamento
    (SHT-01.1). A **direção é decisão da estratégia, no sinal** — o sizer
    nunca decide direção (D3); a conversão aplica o sinal (T02).
    """

    ENTER = "enter"
    EXIT = "exit"
    ENTER_SHORT = "enter_short"  # venda a descoberto — alvo NEGATIVO (SHT-01.2)
    EXIT_SHORT = "exit_short"  # cobertura — reduz |qty| até 0, sem cruzar (SHT-01.3)


@runtime_checkable
class Strategy(Protocol):
    """O que o engine exige de uma estratégia. Nada além disto.

    `runtime_checkable` permite `isinstance` para diagnóstico, mas o engine
    não checa: ele chama. Protocolo estrutural existe justamente para que a
    estratégia não precise saber que este arquivo existe.
    """

    @property
    def warmup(self) -> int:
        """Barras consumidas antes de a estratégia poder decidir.

        O engine não chama `on_bar` antes de `i >= warmup` — ENG-06.3 sai de
        graça, sem cada estratégia reimplementar a checagem. Para a SMA cross
        é o período lento.
        """
        ...

    def on_bar(self, view: MarketView) -> Signal | None:
        """Decide com a informação disponível até a barra corrente.

        `None` significa "nada a fazer", que é o caso da esmagadora maioria
        das barras — e é diferente de `EXIT`, que é uma decisão ativa.

        O sinal devolvido em `i` vira ordem pendente para `i + 1` (design
        §4.3). A estratégia não escolhe quando executa; ADR-0002 escolhe.
        """
        ...
