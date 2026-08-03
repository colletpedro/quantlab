"""Persistência em MongoDB (RF-PER, ADR-0001, ADR-0003).

Esta camada isola o resto do sistema do driver: fora daqui ninguém importa
`pymongo`, e o engine recebe apenas value objects (`PriceSeries`).

O contrato central é `MongoRepository.get_series`, que devolve a série já
ajustada por proventos em tempo de leitura — ADR-0003 persiste o bruto e
deriva o ajustado, porque o ajuste é função do presente e envelhece.
"""

from quantlab.storage.adjustment import AdjustmentFactors, adjustment_factors
from quantlab.storage.client import (
    MongoClientType,
    MongoCollection,
    MongoDatabase,
    MongoDocument,
    check_connection,
    create_client,
    mongo_database,
)
from quantlab.storage.hashing import series_hash
from quantlab.storage.models import Bar, CorporateAction, CorporateActionKind, QuarantinedBar
from quantlab.storage.repository import MongoRepository, WriteReport
from quantlab.storage.schema import (
    BACKTEST_RUNS,
    BARS,
    COLLECTIONS,
    CORPORATE_ACTIONS,
    INGESTION_RUNS,
    QUARANTINED_BARS,
    ensure_schema,
)
from quantlab.storage.series import PriceSeries

__all__ = [
    "BACKTEST_RUNS",
    "BARS",
    "COLLECTIONS",
    "CORPORATE_ACTIONS",
    "INGESTION_RUNS",
    "QUARANTINED_BARS",
    "AdjustmentFactors",
    "Bar",
    "CorporateAction",
    "CorporateActionKind",
    "MongoClientType",
    "MongoCollection",
    "MongoDatabase",
    "MongoDocument",
    "MongoRepository",
    "PriceSeries",
    "QuarantinedBar",
    "WriteReport",
    "adjustment_factors",
    "check_connection",
    "create_client",
    "ensure_schema",
    "mongo_database",
    "series_hash",
]
