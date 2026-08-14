"""Guarda permanente de consistência brutoxsplit (design Fase 1 v0.10, §3.1).

Para todo split em `corporate_actions` com barra no dia ex e na barra
imediatamente anterior, duas propriedades têm de valer:

1. **Relação bruta** (spec §3.1): `close_bruto(anterior) / close_bruto(ex)`
   fica mais perto de `ratio` do que de `1` — dividendo introduz ruído
   pequeno; dupla contagem de splits (o bug v0.10) cola a razão em `1`.
2. **Continuidade do ajustado**: `close_ajustado(anterior) /
   close_ajustado(ex)` fica dentro de ±15% de `1` — o ajuste existe
   exatamente para não haver salto no split; salto de fator `r` ou `1/r`
   indica ajuste errado no raw ou no fator.

Sai com código ≠ 0 se qualquer ticker violar qualquer das duas. Roda sobre
a base real (`make verify-raw`); é a sanidade cruzada do ADR-0003 como
guarda executável, não checagem de desenvolvimento.
"""

from __future__ import annotations

import math
import sys
from datetime import date, datetime
from typing import Any

from quantlab.config import get_settings
from quantlab.storage.client import mongo_database
from quantlab.storage.repository import MongoRepository
from quantlab.storage.schema import CORPORATE_ACTIONS

#: Dividendo entre a barra anterior e a data ex desloca a razão bruta; ±15%
#: acomoda o ruído sem deixar passar salto de split (r ≥ 1.5 ⇒ razão ≤ 0.67
#: ou ≥ 1.5, fora da banda).
_ADJ_RATIO_TOLERANCE = 0.15


def _as_date(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


def _closer_to_ratio_than_to_one(observed: float, ratio: float) -> bool:
    """`observed` fica mais perto de `ratio` do que de `1` (escala log)."""
    if observed <= 0.0 or ratio <= 0.0:
        return False
    return abs(math.log(observed) - math.log(ratio)) < abs(math.log(observed))


def main() -> int:
    settings = get_settings()
    failures: list[str] = []
    checked = 0
    with mongo_database(settings) as database:
        repository = MongoRepository(database)
        tickers = sorted(database[CORPORATE_ACTIONS].distinct("ticker"))
        for ticker in tickers:
            events = repository.get_corporate_actions(ticker)
            splits = [e for e in events if e.kind.value == "split"]
            if not splits:
                continue
            raw = repository.get_series(ticker, adjusted=False)
            adjusted = repository.get_series(ticker, adjusted=True)
            raw_index = {d: i for i, d in enumerate(raw.dates)}
            adj_index = {d: i for i, d in enumerate(adjusted.dates)}
            for split in splits:
                ex = split.date
                if ex not in raw_index or ex not in adj_index:
                    continue  # sem barra no dia ex — nada a checar
                ex_i = raw_index[ex]
                if ex_i == 0:
                    continue
                before_i = ex_i - 1
                obs_raw = float(raw.close[before_i]) / float(raw.close[ex_i])
                obs_adj = float(adjusted.close[before_i]) / float(adjusted.close[ex_i])
                checked += 1
                if not _closer_to_ratio_than_to_one(obs_raw, split.ratio):
                    failures.append(
                        f"{ticker} {ex} r={split.ratio}: razão bruta {obs_raw:.3f} "
                        "(esperado ≈ ratio; ≈1 indica dupla contagem de splits)"
                    )
                elif abs(obs_adj - 1.0) > _ADJ_RATIO_TOLERANCE:
                    failures.append(
                        f"{ticker} {ex} r={split.ratio}: razão ajustada {obs_adj:.3f} "
                        "— salto no ajustado (esperado ≈ 1 ± 15%)"
                    )

    if failures:
        print(f"verify-raw: {len(failures)} violação(ões) em {checked} checagens:")
        for message in failures:
            print(f"  ✗ {message}")
        return 1
    print(f"verify-raw: OK — {checked} fronteiras de split consistentes (bruto x ajustado).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
