"""Calendário-união — T05, design §3.1/§5, D1, RF-POR-02/05.

Materializa a união das datas do run em arrays **pré-computados e
imutáveis** (D1): nenhum ponteiro mutável, nenhuma consulta por data. O
laço (T11) acorda por data-união e mantém um índice por ativo —
`MarketView.i` indexa o array do PRÓPRIO ativo (POR-05.1).

Construção em uma passada O(total de barras + união): merge k-way das
listas ordenadas de datas, com um cursor por ativo que só avança. O custo
é estrutural — a API não oferece busca por `(data, ativo)`, então não
existe caminho para O(n²) (guarda do RNF-04 de 30 s, teste de propriedade
em §10).

Bordas (nunca fabrica barra — POR-02.2): IPO (série que começa depois da
união tem `-1`/`None` até a primeira barra); halt (buraco no meio deriva
`last_known` do último índice válido); deslistagem (posição travada —
`last_known` constante no resto da união, POR-02.3); ativo sem nenhuma
barra na janela (arrays todos `-1` — conta no `N`, nunca recebe alvo,
contribui zero, R2/SIZ-02.4).

`date` é naive (RNF-07): nenhum `datetime`/`timezone` aqui.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray

from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries

__all__ = ["UnionCalendar"]


@dataclass(frozen=True)
class UnionCalendar:
    """União ordenada das datas do run, com índices por ativo pré-computados.

    - ``dates``: união ordenada e sem duplicata (merge em uma passada);
    - ``bar_index[X]``: alinhado a ``dates`` — índice da barra de X no
      array do PRÓPRIO ativo na data-união ``u``; ``-1`` sse X não tem
      barra em ``u`` (POR-05.1);
    - ``last_known[X]``: último índice ≥ 0 com ``date ≤ dates[u]`` — o
      último close conhecido (POR-02.2); ``-1`` sse X ainda não tem barra.

    Imutável de propósito: arrays com ``writeable=False`` (mesma política
    da `PriceSeries`, design Fase 1 §3.7); o laço apenas lê índices.
    """

    dates: tuple[date, ...]
    bar_index: dict[str, NDArray[np.int64]]
    last_known: dict[str, NDArray[np.int64]]

    @staticmethod
    def build(series: dict[str, PriceSeries]) -> UnionCalendar:
        """Constrói o calendário em uma passada — função pura (RNF-01/D1).

        Pré-condições (design §3.8): ``series`` não vazio; datas de cada
        série ordenadas e sem duplicata.

        Raises:
            EngineError: se ``series`` estiver vazio (run sem ativos).
        """

        if not series:
            raise EngineError(
                "UnionCalendar.build: série vazia — o run precisa de ao menos um ativo."
            )

        # Merge k-way das listas ordenadas de datas → união, com dedupe de
        # datas repetidas entre ativos (uma data-união aparece uma vez).
        merged = heapq.merge(*(s.dates.tolist() for s in series.values()))
        union: list[date] = []
        previous: date | None = None
        for day in merged:
            if day != previous:
                union.append(day)
                previous = day
        dates = tuple(union)
        total = len(dates)

        bar_index: dict[str, NDArray[np.int64]] = {}
        last_known: dict[str, NDArray[np.int64]] = {}
        for ticker, own in series.items():
            own_dates = own.dates
            own_count = len(own_dates)
            per_asset = np.full(total, -1, dtype=np.int64)
            prefix = np.full(total, -1, dtype=np.int64)
            cursor = 0
            last = -1
            for u in range(total):
                if cursor < own_count and own_dates[cursor] == dates[u]:
                    per_asset[u] = cursor
                    last = cursor
                    cursor += 1
                prefix[u] = last
            per_asset.flags.writeable = False
            prefix.flags.writeable = False
            bar_index[ticker] = per_asset
            last_known[ticker] = prefix

        return UnionCalendar(dates=dates, bar_index=bar_index, last_known=last_known)

    def _validate_u(self, u: int) -> None:
        if not 0 <= u < len(self.dates):
            raise EngineError(f"UnionCalendar: índice de união {u} fora de [0, {len(self.dates)}).")

    def has_bar_at(self, ticker: str, u: int) -> bool:
        """O ativo tem barra na data-união ``u``? O(1).

        O nome usa o sufixo ``_at`` (emenda T05): o campo ``bar_index``
        (dict de arrays) não pode dividir nome com uma consulta em Python.
        """

        self._validate_u(u)
        return bool(self.bar_index[ticker][u] >= 0)

    def bar_index_at(self, ticker: str, u: int) -> int | None:
        """Índice da barra de ``ticker`` no array do PRÓPRIO ativo (POR-05.1).

        ``None`` sse o ativo não tem barra em ``u`` (barra não fabricada).
        """

        self._validate_u(u)
        value = int(self.bar_index[ticker][u])
        return None if value < 0 else value

    def last_known_index_at(self, ticker: str, u: int) -> int | None:
        """Último índice do próprio ativo com ``date ≤ dates[u]`` (POR-02.2).

        ``None`` sse o ativo ainda não tem barra (IPO) — sem barra
        fabricada; depois disso, nunca mais ``None`` (inclui deslistagem).
        """

        self._validate_u(u)
        value = int(self.last_known[ticker][u])
        return None if value < 0 else value
