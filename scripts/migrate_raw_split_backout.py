"""Migração one-off do back-out de splits (design Fase 1 v0.10, §3.7).

Barras ingeridas com `YFinanceProvider` pré-v0.10 estão **split-ajustadas**
gravadas como se fossem bruto (`auto_adjust=False` do yfinance ainda aplica
splits). Esta migração recupera o bruto com a MESMA fórmula do back-out do
provider, sobre o que já está em `bars` — determinístico, sem refetch:

    raw[t] = stored[t] x Π r_i   (splits com data ex estritamente posterior a t)

Volume não é tocado (vem como negociado). **Só migra tickers onde a guarda
acusa dupla contagem agora** (mesmo critério de
`scripts/verify_raw_consistency.py`) — seguro contra re-execução: depois da
migração o ticker deixa de violar e não é mais tocado. Backup dos documentos
em `/tmp` antes de escrever.
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import date, datetime
from typing import Any

from pymongo import UpdateOne

from quantlab.config import get_settings
from quantlab.storage.client import mongo_database
from quantlab.storage.repository import MongoRepository


def _as_date(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


def _closer_to_ratio_than_to_one(observed: float, ratio: float) -> bool:
    """Mesmo critério da guarda (`scripts/verify_raw_consistency.py`)."""
    if observed <= 0.0 or ratio <= 0.0:
        return False
    return abs(math.log(observed) - math.log(ratio)) < abs(math.log(observed))


def split_factors(bars: list[dict[str, Any]], split_ratios: list[tuple[Any, float]]) -> list[float]:
    """Fator por barra: `Π r_i` para splits com data ex estritamente posterior.

    `bars` em ordem crescente de data; `split_ratios` como pares (data ex,
    razão). Barra na data ex NÃO recebe o split dela (preço pós-split);
    barra estritamente anterior recebe. Complexidade O(#splits x #barras) —
    irrelevante para 10 anos.
    """
    factors = [1.0] * len(bars)
    for ex, ratio in split_ratios:
        for i, bar in enumerate(bars):
            if _as_date(bar["date"]) < ex:
                factors[i] *= ratio
            else:
                break
    return factors


def main() -> int:
    settings = get_settings()
    with mongo_database(settings) as database:
        repository = MongoRepository(database)
        collection = database["bars"]
        tickers = sorted(database["corporate_actions"].distinct("ticker"))

        total_bars = 0
        migrated_tickers: list[str] = []
        backup: dict[str, list[dict[str, Any]]] = {}

        for ticker in tickers:
            events = repository.get_corporate_actions(ticker)
            splits = [(e.date, e.ratio) for e in events if e.kind.value == "split"]
            if not splits:
                continue
            raw = repository.get_series(ticker, adjusted=False)
            raw_index = {d: i for i, d in enumerate(raw.dates)}

            # Só migra se a dupla contagem estiver presente AGORA (guarda).
            double_counted = False
            for ex, ratio in splits:
                i = raw_index.get(ex)
                if i is None or i == 0:
                    continue
                observed = float(raw.close[i - 1]) / float(raw.close[i])
                if not _closer_to_ratio_than_to_one(observed, ratio):
                    double_counted = True
                    break
            if not double_counted:
                continue

            bars = list(collection.find({"ticker": ticker}).sort("date", 1))
            if not bars:
                continue
            factors = split_factors(bars, splits)
            touched = [i for i, f in enumerate(factors) if f != 1.0]
            if not touched:
                continue
            migrated_tickers.append(ticker)
            backup[ticker] = [
                {
                    "date": _as_date(b["date"]).isoformat(),
                    "open": b["open"],
                    "high": b["high"],
                    "low": b["low"],
                    "close": b["close"],
                    "volume": b["volume"],
                }
                for b in bars
            ]
            operations = [
                UpdateOne(
                    {"_id": bars[i]["_id"]},
                    {
                        "$set": {
                            "open": bars[i]["open"] * factors[i],
                            "high": bars[i]["high"] * factors[i],
                            "low": bars[i]["low"] * factors[i],
                            "close": bars[i]["close"] * factors[i],
                        }
                    },
                )
                for i in touched
            ]
            result = collection.bulk_write(operations, ordered=False)
            total_bars += result.modified_count

        if not migrated_tickers:
            print("migrate-raw-backout: nada a migrar — nenhum ticker com dupla contagem.")
            return 0

        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = f"/tmp/backtestlab_raw_backout_{stamp}.json"
        with open(backup_path, "w", encoding="utf-8") as handle:
            json.dump(backup, handle, indent=2)

        print(
            f"migrate-raw-backout: {total_bars} barras corrigidas em {', '.join(migrated_tickers)}."
        )
        print(f"backup: {backup_path}")
        print("AGORA RODE `make verify-raw` — a guarda precisa sair OK.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
