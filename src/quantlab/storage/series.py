"""`PriceSeries` — o value object que storage produz e o engine consome.

Design §3.7. Duas medidas de imutabilidade, e são **duas** porque cada uma
cobre o que a outra não cobre:

- ``frozen=True`` impede reatribuir atributos (``series.close = outro``);
- ``flags.writeable = False`` impede mutar o conteúdo dos arrays
  (``series.close[0] = 999``).

Só a primeira deixaria os dados abertos; só a segunda deixaria a referência
aberta. Juntas dão o que a v0.1 do design chamava vagamente de "imutável".

A segunda é também o que fecha a rota do `.base` que design §4.1 documenta:
uma fatia de numpy expõe o array-mãe inteiro — incluindo o futuro — e não há
como remover esse atributo. Marcar o array-mãe como somente leitura na
materialização faz com que a *mutação* por essa rota falhe, qualquer que seja
o caminho. A *leitura* do futuro via `.base` continua tecnicamente possível, e
o design declara isso em vez de fingir o contrário: é proteção contra
acidente, não contra adversário.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray

from quantlab.exceptions import DataError
from quantlab.storage.adjustment import adjustment_factors
from quantlab.storage.hashing import series_hash
from quantlab.storage.models import Bar, CorporateAction

__all__ = ["PriceSeries", "build_price_series"]


@dataclass(frozen=True, slots=True)
class PriceSeries:
    """Série de preços materializada, pronta para o engine.

    ``dates`` é um array de objetos ``datetime.date`` (RNF-07 — nunca
    ``datetime64``, que reintroduziria instante e fuso). Fatiar dates junto
    com os preços é o que permite a `MarketView` do engine expor todos os
    campos pela mesma operação.

    ``volume`` é ``float64`` e não inteiro porque o ajuste por split multiplica
    volume por uma razão que pode não ser inteira; manter inteiro obrigaria a
    truncar em silêncio.
    """

    ticker: str
    dates: NDArray[np.object_]
    open: NDArray[np.float64]
    high: NDArray[np.float64]
    low: NDArray[np.float64]
    close: NDArray[np.float64]
    volume: NDArray[np.float64]
    adjusted: bool
    hash: str
    #: ISO-8601 da ingestão mais recente que tocou a janela (PER-03.1).
    #: Não há `ingestion_run_id` na série (design v0.3 §3.7): uma série
    #: materializada pode atravessar N ingestões, então não existe um valor
    #: singular correto para atribuir a ela.
    last_ingested_at: str | None = None

    def __post_init__(self) -> None:
        arrays = (self.dates, self.open, self.high, self.low, self.close, self.volume)

        lengths = {len(array) for array in arrays}
        if len(lengths) > 1:
            raise DataError(
                f"Série desalinhada para {self.ticker}: comprimentos {sorted(lengths)}."
            )

        # Marcar na materialização, e não no chamador, é o que torna a
        # garantia estrutural: não existe PriceSeries com array gravável,
        # independentemente de quem a construiu.
        for array in arrays:
            array.flags.writeable = False

    def __len__(self) -> int:
        return len(self.dates)

    @property
    def start(self) -> date | None:
        """Primeira data da série, ou ``None`` se vazia."""
        if len(self.dates) == 0:
            return None
        first: date = self.dates[0]
        return first

    @property
    def end(self) -> date | None:
        """Última data da série, ou ``None`` se vazia."""
        if len(self.dates) == 0:
            return None
        last: date = self.dates[-1]
        return last


def build_price_series(
    ticker: str,
    bars: Sequence[Bar],
    events: Sequence[CorporateAction],
    *,
    start: date | None = None,
    end: date | None = None,
    adjusted: bool = True,
    last_ingested_at: str | None = None,
) -> PriceSeries:
    """Materializa a série ajustada sobre o histórico completo e fatia depois.

    **ADR-0004.** ``bars`` é o histórico **completo** do ticker, nunca a
    janela pedida. O ajuste é computado sobre ele inteiro e só então a série
    é recortada para ``[start, end]``. Barras e eventos passam a ter o mesmo
    escopo — a assimetria entre os dois (eventos completos, barras filtradas)
    foi exatamente o bug que ADR-0004 corrige.

    **O invariante que isto garante — independência de janela:** duas
    chamadas com janelas distintas concordam valor a valor nas barras que
    compartilham. O valor ajustado de uma barra é propriedade do dado, nunca
    da consulta. Garantido por construção: o cálculo do fator nunca vê uma
    janela, porque o fatiamento acontece depois dele.

    Função pura, sem I/O e sem conhecer o repositório — é o que permite testar
    o invariante offline, com fixtures de papel (RNF-03). Enquanto esta lógica
    morava dentro de ``MongoRepository.get_series``, só um teste de integração
    podia alcançá-la, e nenhum cobria dividendo posterior à janela.

    Raises:
        DataError: Se o ticker não tem barra nenhuma, ou se a janela pedida
            não intersecta o histórico. As duas mensagens são distintas de
            propósito: a causa e a correção são diferentes.
    """
    if not bars:
        raise DataError(
            f"Nenhuma barra encontrada para {ticker}. "
            f"Rode a ingestão para {ticker} antes do backtest."
        )

    # ── ajuste sobre o histórico COMPLETO ────────────────────────────────
    history_dates = [bar.date for bar in bars]
    open_ = _column(bars, "open")
    high = _column(bars, "high")
    low = _column(bars, "low")
    close = _column(bars, "close")
    volume = _column(bars, "volume")

    if adjusted:
        factors = adjustment_factors(history_dates, close, events)
        open_ = open_ * factors.price
        high = high * factors.price
        low = low * factors.price
        close = close * factors.price
        volume = volume * factors.volume

    # ── e só então o fatiamento ──────────────────────────────────────────
    lo = 0 if start is None else bisect_left(history_dates, start)
    hi = len(history_dates) if end is None else bisect_right(history_dates, end)

    if lo >= hi:
        raise DataError(
            f"Nenhuma barra de {ticker} na janela pedida "
            f"[{start} .. {end}]. O histórico vai de {history_dates[0]} a "
            f"{history_dates[-1]}; ajuste a janela ou rode a ingestão do período."
        )

    window_dates = history_dates[lo:hi]
    date_array: NDArray[np.object_] = np.empty(len(window_dates), dtype=object)
    date_array[:] = window_dates

    # `.copy()` e não view: `PriceSeries` marca o que recebe como somente
    # leitura, e uma view manteria vivo o array-mãe do histórico inteiro —
    # inclusive as barras fora da janela, alcançáveis por `.base`. Fatiar com
    # cópia é o que faz a janela ser de fato uma janela.
    sliced_open = open_[lo:hi].copy()
    sliced_high = high[lo:hi].copy()
    sliced_low = low[lo:hi].copy()
    sliced_close = close[lo:hi].copy()
    sliced_volume = volume[lo:hi].copy()

    return PriceSeries(
        ticker=ticker,
        dates=date_array,
        open=sliced_open,
        high=sliced_high,
        low=sliced_low,
        close=sliced_close,
        volume=sliced_volume,
        adjusted=adjusted,
        hash=series_hash(
            window_dates, sliced_open, sliced_high, sliced_low, sliced_close, sliced_volume
        ),
        last_ingested_at=last_ingested_at,
    )


def _column(bars: Sequence[Bar], field: str) -> NDArray[np.float64]:
    """Extrai um campo das barras como array novo de float64."""
    return np.array([getattr(bar, field) for bar in bars], dtype=np.float64)
