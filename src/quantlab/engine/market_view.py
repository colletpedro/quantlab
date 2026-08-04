"""`MarketView` — a janela que a estratégia enxerga (C1, design §4.1).

É aqui que ADR-0002 deixa de ser convenção e vira construção. A estratégia
recebe **só** este objeto, e este objeto só sabe devolver barras de índice
``<= i``. Não existe caminho normal pelo qual uma estratégia leia o futuro:
não porque quem a escreveu lembrou de não ler, mas porque não há o que ler.

**Os três mecanismos, e o que cada um cobre** (design §4.1):

1. **Fatiamento na origem.** Cada acessor devolve ``array[: i + 1]``. Fatia de
   numpy é *view*, não cópia — O(1), sem penalidade no laço quente.
2. **Arrays-mãe somente leitura.** Toda view expõe ``.base``, que aponta para o
   array completo — incluindo o futuro — e não há como remover esse atributo.
   O que o desenho faz é neutralizar a parte perigosa: a `PriceSeries` marca os
   arrays-mãe com ``writeable=False`` na materialização, então a *mutação* por
   essa rota falha por qualquer caminho.
3. **Superfície mínima.** Esta classe não expõe a `PriceSeries`, o array
   completo nem o índice máximo. ``last(field, n)`` com ``n > i + 1`` levanta
   `InsufficientHistoryError`.

**A claim honesta, repetida aqui porque é onde ela importa:** isto é proteção
contra **acidente**, não contra **adversário**. Python não tem encapsulamento
forte, e uma estratégia que escreva ``view.close.base`` deliberadamente lê o
futuro. O design aceita, declara, e manda o teste de ENG-01.3 exercitar
exatamente esse caminho — a limitação fica gravada onde não se perde: na
suíte, em `tests/unit/test_market_view.py`.
"""

from datetime import date

import numpy as np
from numpy.typing import NDArray

from quantlab.exceptions import EngineError, InsufficientHistoryError
from quantlab.storage.series import PriceSeries

__all__ = ["MarketView"]

#: Campos que `last()` aceita. Frozen set em vez de `getattr` livre: um typo
#: em `last("clsoe", 20)` vira erro nomeado em vez de `AttributeError` cru.
_FIELDS = frozenset({"open", "high", "low", "close", "volume", "dates"})


class MarketView:
    """Janela sobre a série, limitada à barra corrente.

    Construída pelo engine uma vez por barra. A estratégia recebe a instância
    e nada além dela (design §4.2, ENG-05.2): não há caixa, posição, histórico
    de trades nem configuração de custos alcançáveis por aqui.
    """

    # `__slots__` impede que alguém pendure estado na view por acidente — e,
    # de quebra, deixa explícito que a superfície é fechada.
    __slots__ = ("_index", "_series")

    def __init__(self, series: PriceSeries, index: int) -> None:
        if index < 0 or index >= len(series):
            raise EngineError(
                f"Índice de barra fora da série: {index} não está em "
                f"[0, {len(series) - 1}] para {series.ticker}."
            )
        self._series = series
        self._index = index

    @property
    def i(self) -> int:
        """Índice da barra corrente."""
        return self._index

    @property
    def ticker(self) -> str:
        return self._series.ticker

    # ── acessores: sempre `[: i + 1]`, sempre view ───────────────────────

    @property
    def open(self) -> NDArray[np.float64]:
        return self._series.open[: self._index + 1]

    @property
    def high(self) -> NDArray[np.float64]:
        return self._series.high[: self._index + 1]

    @property
    def low(self) -> NDArray[np.float64]:
        return self._series.low[: self._index + 1]

    @property
    def close(self) -> NDArray[np.float64]:
        return self._series.close[: self._index + 1]

    @property
    def volume(self) -> NDArray[np.float64]:
        return self._series.volume[: self._index + 1]

    @property
    def dates(self) -> NDArray[np.object_]:
        return self._series.dates[: self._index + 1]

    @property
    def date(self) -> date:
        """Data da barra corrente."""
        current: date = self._series.dates[self._index]
        return current

    def last(self, field: str, n: int) -> NDArray[np.float64] | NDArray[np.object_]:
        """As ``n`` observações mais recentes de ``field``, terminando em ``i``.

        Raises:
            EngineError: Campo desconhecido, ou ``n`` não positivo.
            InsufficientHistoryError: ``n`` maior que o histórico disponível
                até a barra corrente. Não é tentativa de lookahead — é
                `warmup` mal declarado; ver a docstring da exceção.
        """
        if field not in _FIELDS:
            raise EngineError(
                f"Campo desconhecido em last(): {field!r}. Disponíveis: {sorted(_FIELDS)}."
            )
        if n <= 0:
            raise EngineError(f"last() precisa de n >= 1, recebeu {n}.")

        available = self._index + 1
        if n > available:
            raise InsufficientHistoryError(
                f"last({field!r}, {n}) pediu {n} barras, mas só há {available} "
                f"até o índice {self._index}. Declare warmup >= {n} na estratégia."
            )

        window: NDArray[np.float64] | NDArray[np.object_] = getattr(self, field)[-n:]
        return window

    def __len__(self) -> int:
        """Quantas barras a estratégia pode enxergar agora."""
        return self._index + 1

    def __repr__(self) -> str:  # pragma: no cover - conveniência de depuração
        return f"MarketView({self._series.ticker}, i={self._index}, date={self.date})"
