"""Hash determinístico da série consumida — PER-03.1, design §3.8.

SHA-256 sobre uma representação canônica: linhas ordenadas por data, cada
campo numérico com **6 casas decimais fixas**, separador fixo, sem localização.

O arredondamento explícito não é cosmético. Sem ele, diferenças de última casa
entre plataformas — ou entre duas ordens de operação que a IEEE-754 não
garante equivalentes — produziriam hashes distintos para a mesma série, e a
reprodutibilidade que o hash existe para provar seria justamente o que ele
quebraria.

Seis casas resolvem por folga o que PER-03.1 precisa distinguir: um centésimo
de centavo (0.0001) muda o hash.
"""

import hashlib
from collections.abc import Sequence
from datetime import date

import numpy as np
from numpy.typing import NDArray

from quantlab.exceptions import DataError

__all__ = ["DECIMAL_PLACES", "series_hash"]

#: Casas decimais da representação canônica. Design §3.8.
DECIMAL_PLACES = 6

#: Separadores fixos. Explícitos porque mudá-los muda todo hash já gravado.
_FIELD_SEPARATOR = "|"
_ROW_SEPARATOR = "\n"

#: `f"{-0.0:.6f}"` devolve "-0.000000", que difere de "0.000000" e produziria
#: hashes distintos para valores numericamente iguais. Zero negativo não
#: deveria aparecer em preço, mas é exatamente o tipo de diferença de última
#: casa que §3.8 quer neutralizar.
_NEGATIVE_ZERO = f"{-0.0:.{DECIMAL_PLACES}f}"
_POSITIVE_ZERO = f"{0.0:.{DECIMAL_PLACES}f}"


def _format(value: float) -> str:
    """Um número na forma canônica: ponto decimal, 6 casas, sem separador de milhar.

    `format` com `.6f` é independente de locale — `str.format` não consulta
    `LC_NUMERIC`, ao contrário de `locale.format_string`.
    """
    text = f"{float(value):.{DECIMAL_PLACES}f}"
    return _POSITIVE_ZERO if text == _NEGATIVE_ZERO else text


def series_hash(
    dates: Sequence[date],
    open_: NDArray[np.float64],
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
) -> str:
    """SHA-256 hexadecimal da série, em representação canônica.

    A data entra em ISO-8601 (``AAAA-MM-DD``); os cinco campos numéricos, com
    6 casas fixas. Ticker e flag de ajuste **não** entram: §3.8 define o hash
    sobre as linhas da série, e os dois já são registrados à parte no
    relatório.

    Raises:
        DataError: Se os arrays não tiverem todos o mesmo comprimento — hash
            de série desalinhada seria um número sem significado.
    """
    lengths = {len(dates), len(open_), len(high), len(low), len(close), len(volume)}
    if len(lengths) > 1:
        raise DataError(f"Série desalinhada ao calcular o hash: comprimentos {sorted(lengths)}.")

    digest = hashlib.sha256()
    for index, bar_date in enumerate(dates):
        row = _FIELD_SEPARATOR.join(
            (
                bar_date.isoformat(),
                _format(open_[index]),
                _format(high[index]),
                _format(low[index]),
                _format(close[index]),
                _format(volume[index]),
            )
        )
        digest.update(row.encode("utf-8"))
        digest.update(_ROW_SEPARATOR.encode("utf-8"))
    return digest.hexdigest()
