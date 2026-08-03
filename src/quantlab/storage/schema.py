"""Coleções e índices do quantlab — design §3.1 a §3.5.

Idempotente: ``ensure_schema`` pode rodar quantas vezes for. Criar índice já
existente com a mesma especificação é no-op no Mongo, e a criação de coleção
é guardada por consulta prévia.

**Nenhum índice não especificado é criado.** `ingestion_runs` e `backtest_runs`
(design §3.4 e §3.5) não declaram índice; ficam sem, e a lacuna está reportada
no HANDOFF em vez de resolvida por palpite — inventar índice é decidir por
padrão de acesso que ninguém escreveu ainda.
"""

from pymongo import ASCENDING, IndexModel

from quantlab.logging import get_logger
from quantlab.storage.client import MongoDatabase

__all__ = [
    "BACKTEST_RUNS",
    "BARS",
    "COLLECTIONS",
    "CORPORATE_ACTIONS",
    "INGESTION_RUNS",
    "QUARANTINED_BARS",
    "ensure_schema",
]

BARS = "bars"
CORPORATE_ACTIONS = "corporate_actions"
QUARANTINED_BARS = "quarantined_bars"
INGESTION_RUNS = "ingestion_runs"
BACKTEST_RUNS = "backtest_runs"

#: Toda coleção do sistema. A ordem é irrelevante para o Mongo, mas fixa aqui
#: para que a criação seja determinística (RNF-01).
COLLECTIONS = (
    BARS,
    CORPORATE_ACTIONS,
    QUARANTINED_BARS,
    INGESTION_RUNS,
    BACKTEST_RUNS,
)

_log = get_logger(__name__)

#: design §3.1 — único. Serve os três padrões de acesso: ticker + intervalo
#: (dominante), ticker inteiro (pelo prefixo do composto) e a unicidade que
#: torna o upsert de PER-01.1 correto.
#:
#: Índice isolado em `date` **não** é criado: seletividade baixa (20 tickers
#: por data) e nenhuma consulta parte da data sem o ticker.
_BARS_INDEXES = (
    IndexModel(
        [("ticker", ASCENDING), ("date", ASCENDING)], name="ticker_date_unique", unique=True
    ),
)

#: design §3.2 — único, com `kind` na chave porque dividendo e split podem
#: cair na mesma data ex.
_CORPORATE_ACTIONS_INDEXES = (
    IndexModel(
        [("ticker", ASCENDING), ("date", ASCENDING), ("kind", ASCENDING)],
        name="ticker_date_kind_unique",
        unique=True,
    ),
)

#: design §3.3 — **não** único: o mesmo par (ticker, date) pode ser
#: quarentenado em runs diferentes, e o histórico é justamente o que interessa
#: para diagnóstico.
_QUARANTINED_BARS_INDEXES = (
    IndexModel([("ticker", ASCENDING), ("date", ASCENDING)], name="ticker_date"),
)

_INDEXES: dict[str, tuple[IndexModel, ...]] = {
    BARS: _BARS_INDEXES,
    CORPORATE_ACTIONS: _CORPORATE_ACTIONS_INDEXES,
    QUARANTINED_BARS: _QUARANTINED_BARS_INDEXES,
    INGESTION_RUNS: (),
    BACKTEST_RUNS: (),
}


def ensure_schema(database: MongoDatabase) -> None:
    """Cria coleções e índices que faltarem. Seguro para reexecutar."""
    existing = set(database.list_collection_names())

    for name in COLLECTIONS:
        if name not in existing:
            database.create_collection(name)
            _log.info("storage.collection_created", collection=name)

        indexes = _INDEXES[name]
        if indexes:
            created = database[name].create_indexes(list(indexes))
            _log.debug("storage.indexes_ensured", collection=name, indexes=created)
