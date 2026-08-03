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

from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray

from quantlab.exceptions import DataError

__all__ = ["PriceSeries"]


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
