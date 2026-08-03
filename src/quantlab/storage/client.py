"""Conexão com o MongoDB e ciclo de vida do cliente (ADR-0001).

Sem nenhuma lógica de domínio: este módulo abre, verifica e fecha conexão.
O que se faz com ela é assunto de :mod:`quantlab.storage.repository`.

Timeouts são explícitos de propósito. O default do driver para seleção de
servidor é 30 s, o que transforma "Mongo não está no ar" numa espera longa
sem explicação — o oposto de uma mensagem acionável.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError

from quantlab.config import Settings, get_settings
from quantlab.exceptions import DataError
from quantlab.logging import get_logger

__all__ = [
    "MongoClientType",
    "MongoCollection",
    "MongoDatabase",
    "MongoDocument",
    "check_connection",
    "create_client",
    "mongo_database",
]

#: Tipo do documento que o driver devolve. Alias para não repetir o genérico
#: em cada assinatura de storage/.
MongoDocument = dict[str, Any]
MongoClientType = MongoClient[MongoDocument]
MongoDatabase = Database[MongoDocument]
MongoCollection = Collection[MongoDocument]

_log = get_logger(__name__)

#: Quanto esperar para eleger um servidor antes de desistir. Curto porque a
#: falha esperada em desenvolvimento é "esqueci o `make up`", e essa merece
#: resposta imediata.
SERVER_SELECTION_TIMEOUT_MS = 5_000
CONNECT_TIMEOUT_MS = 5_000
SOCKET_TIMEOUT_MS = 30_000

#: Pool pequeno: a Fase 1 é single-process e não tem concorrência real.
MAX_POOL_SIZE = 10
MIN_POOL_SIZE = 0


def create_client(settings: Settings | None = None) -> MongoClientType:
    """Cria o cliente a partir de ``Settings.mongo_uri``.

    Não estabelece conexão — o driver é lazy. Use :func:`check_connection`
    quando quiser que uma falha apareça agora, e não na primeira consulta.
    """
    resolved = settings if settings is not None else get_settings()
    return MongoClient(
        resolved.mongo_uri,
        serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
        connectTimeoutMS=CONNECT_TIMEOUT_MS,
        socketTimeoutMS=SOCKET_TIMEOUT_MS,
        maxPoolSize=MAX_POOL_SIZE,
        minPoolSize=MIN_POOL_SIZE,
        # RNF-07: datas voltam do driver como naive; a conversão para
        # `datetime.date` é feita no repositório, e só lá.
        tz_aware=False,
    )


def check_connection(client: MongoClientType) -> None:
    """Faz ping no servidor. Levanta ``DataError`` acionável se não responder."""
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        raise DataError(
            "Não foi possível conectar ao MongoDB. Verifique se o container "
            "está no ar (`make up`) e se QUANTLAB_MONGO_URI aponta para ele "
            f"com as credenciais certas. Erro do driver: {exc}"
        ) from exc


@contextmanager
def mongo_database(settings: Settings | None = None) -> Iterator[MongoDatabase]:
    """Abre o banco configurado, verifica a conexão e fecha ao sair.

    O fechamento é determinístico: acontece no ``finally``, inclusive quando o
    bloco levanta. Depender do garbage collector deixaria conexões penduradas
    entre testes.
    """
    resolved = settings if settings is not None else get_settings()
    client = create_client(resolved)
    try:
        check_connection(client)
        _log.debug("mongo.connected", database=resolved.mongo_db)
        yield client[resolved.mongo_db]
    finally:
        client.close()
        _log.debug("mongo.closed", database=resolved.mongo_db)
