"""Coleções e índices do quantlab — design §3.1 a §3.5.

Idempotente: ``ensure_schema`` pode rodar quantas vezes for. Criar índice já
existente com a mesma especificação é no-op no Mongo, e a criação de coleção
é guardada por consulta prévia.

**Nenhum índice não especificado é criado.** `backtest_runs` (design §3.5)
ganhou índice no Bloco F (F1), no mesmo commit que passou a gravar na
coleção — mesmo padrão que `ingestion_runs` seguiu no Bloco B (B4). Ver
abaixo.
"""

from pymongo import ASCENDING, DESCENDING, IndexModel

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

#: design v0.4 §3.4 — padrão de acesso definido por B4: "qual foi a última
#: ingestão que tocou este ticker" e "runs mais recentes", em qualquer ordem
#: de prioridade. `tickers` é array — o índice em campo array vira multikey
#: no Mongo automaticamente, e a combinação com `started_at` descendente
#: serve às duas consultas com um só índice: igualdade em `tickers` (qualquer
#: posição do array) mais ordenação por `started_at`.
_INGESTION_RUNS_INDEXES = (
    IndexModel([("tickers", ASCENDING), ("started_at", DESCENDING)], name="tickers_started_at"),
)

#: design v0.7 §3.5 — padrão de acesso definido por F1: "quais foram os runs
#: passados deste ticker com esta estratégia, do mais recente para o mais
#: antigo" — é a consulta que RF-PER-03 (reprodutibilidade) pede para
#: localizar o estado de dados que existia quando um backtest específico
#: rodou. `strategy.name` entra na chave composta porque um ticker pode
#: acumular runs de estratégias diferentes, e misturá-las na mesma busca não
#: serve a pergunta "quando eu rodei sma_cross em AAPL pela última vez".
_BACKTEST_RUNS_INDEXES = (
    IndexModel(
        [("ticker", ASCENDING), ("strategy.name", ASCENDING), ("created_at", DESCENDING)],
        name="ticker_strategy_created_at",
    ),
)

_INDEXES: dict[str, tuple[IndexModel, ...]] = {
    BARS: _BARS_INDEXES,
    CORPORATE_ACTIONS: _CORPORATE_ACTIONS_INDEXES,
    QUARANTINED_BARS: _QUARANTINED_BARS_INDEXES,
    INGESTION_RUNS: _INGESTION_RUNS_INDEXES,
    BACKTEST_RUNS: _BACKTEST_RUNS_INDEXES,
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
