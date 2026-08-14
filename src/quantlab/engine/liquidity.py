"""Liquidez — T02, design §3.3/§3.8, RF-SLP-03.

Dois helpers puros sobre `PriceSeries` da Fase 1, sem nenhuma dependência
interna do engine (folha): a janela de ADV do PRÓPRIO ativo e o teto de
participação que corta a **quantidade** de entrada. O corte de preço
(slippage) é outro mecanismo e vive em `engine/slippage.py` (T03) — aqui
não há preço, só volume e quantidade (SLP-04: corte x slippage x custos
são três mecanismos, três etapas).

Nenhum `datetime`/`timezone` (RNF-07): estas funções recebem índices e a
série já materializada; a fronteira de instante mora na ingestão.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries

__all__ = ["adv", "participation_cap"]


def adv(series: PriceSeries, i: int, window: int = 20) -> float | None:
    """Média de volume dos últimos ``window`` pregões do próprio ativo terminando em ``i``.

    Pré-condições (design §3.8): ``0 ≤ i < len(series)``; ``window ≥ 1``.

    Pós-condições (SLP-03.1/03.2):

    - janela = ``[i - window + 1, i]`` — termina na barra de execução e
      nunca usa barra futura (Q3);
    - ``None`` sse histórico insuficiente (menos de ``window`` barras até
      ``i`` inclusive) — o *fallback* para modelo fixo com aviso é
      responsabilidade do `Participation` (T03), não desta função;
    - senão, média aritmética do volume na janela (``float``).

    Raises:
        EngineError: se ``i`` fora de ``[0, len(series))`` ou ``window < 1``.
    """

    count = len(series)
    if not 0 <= i < count:
        raise EngineError(f"adv: índice {i} fora da série com {count} barras.")
    if window < 1:
        raise EngineError(f"adv: janela {window} inválida — exige window ≥ 1.")

    start = i - window + 1
    if start < 0:
        return None

    window_volumes: NDArray[np.float64] = series.volume[start : i + 1]
    return float(np.mean(window_volumes))


def participation_cap(qty: int, adv: float, cap: float = 0.10) -> int:
    """Corta a QUANTIDADE de ENTRADA ao teto ``min(qty, floor(cap x ADV))`` (SLP-03.3).

    Pré-condições (design §3.8): ``qty ≥ 1``; ``adv > 0``; ``0 < cap ≤ 1``.

    Pós-condições:

    - ``min(qty, floor(cap x adv))`` — monotônica: uma quantidade pedida
      maior nunca devolve um teto menor (o resultado nunca excede o pedido);
    - resultado ``< 1`` (ou seja, ``0`` quando ``cap x adv < 1``) ⇒ o
      chamador NÃO gera a ordem e loga o evento (SLP-03.5);
    - esta função NUNCA é chamada para saídas — saída é integral, sem cap
      (SLP-03.4, D3 da Fase 1); responsabilidade do chamador.

    Raises:
        EngineError: se alguma pré-condição for violada.
    """

    if qty < 1:
        raise EngineError(f"participation_cap: qty {qty} inválida — exige qty ≥ 1.")
    if adv <= 0:
        raise EngineError(f"participation_cap: adv {adv} inválido — exige adv > 0.")
    if not 0 < cap <= 1:
        raise EngineError(f"participation_cap: cap {cap} inválido — exige 0 < cap ≤ 1.")

    ceiling = math.floor(cap * adv)
    return min(qty, ceiling)
