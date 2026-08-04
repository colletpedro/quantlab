"""Repositório Mongo — a única fronteira entre o domínio e o driver.

**Este é o único módulo de `storage/` que importa `datetime`** (design §3.6).
BSON não tem tipo data-sem-hora: toda data no banco é um instante. A conversão
é inevitável; o que importa é que aconteça em um lugar só, para que RNF-07
("nenhuma comparação de datas envolve timezone") seja verificável por
varredura de imports em vez de por disciplina.

Do lado de fora deste arquivo, data é sempre ``datetime.date``.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime

from bson import ObjectId
from pymongo import UpdateOne

from quantlab.exceptions import DataError
from quantlab.logging import get_logger
from quantlab.storage.client import MongoDatabase, MongoDocument
from quantlab.storage.models import Bar, CorporateAction, CorporateActionKind, QuarantinedBar
from quantlab.storage.schema import (
    BACKTEST_RUNS,
    BARS,
    CORPORATE_ACTIONS,
    INGESTION_RUNS,
    QUARANTINED_BARS,
)
from quantlab.storage.series import PriceSeries, build_price_series

__all__ = [
    "MongoRepository",
    "WriteReport",
    "from_bson_date",
    "to_bson_date",
]

_log = get_logger(__name__)

#: Campos que definem o conteúdo de uma barra. Metadados (`source`,
#: `ingested_at`) ficam de fora: mudança neles não é revisão de dado e não
#: deve disparar o log de alteração de ING-03.2.
_BAR_VALUE_FIELDS = ("open", "high", "low", "close", "volume")


def to_bson_date(value: date) -> datetime:
    """``date`` do domínio para o instante UTC que o BSON guarda.

    Meia-noite UTC, sempre. Sem hora local, sem offset — o instante é um
    detalhe de armazenamento, e ancorá-lo em UTC é o que garante que a volta
    devolva exatamente o mesmo dia em qualquer máquina.
    """
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def from_bson_date(value: datetime) -> date:
    """Instante do BSON de volta para ``date``.

    O driver está configurado com ``tz_aware=False`` e devolve naive em UTC;
    um valor aware ainda assim é normalizado para UTC antes de virar dia, para
    que a função esteja certa independentemente dessa configuração.
    """
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.date()


class WriteReport:
    """Contagem do que uma escrita fez. Mutável de propósito, é acumulador."""

    __slots__ = ("inserted", "matched", "modified")

    def __init__(self) -> None:
        self.matched = 0
        self.inserted = 0
        self.modified = 0

    def __repr__(self) -> str:  # pragma: no cover - conveniência de depuração
        return (
            f"WriteReport(inserted={self.inserted}, modified={self.modified}, "
            f"matched={self.matched})"
        )


class MongoRepository:
    """Acesso a `bars`, `corporate_actions` e `quarantined_bars`.

    Isola o resto do sistema do driver (ADR-0001): fora daqui ninguém importa
    `pymongo`, e o engine recebe apenas value objects.
    """

    def __init__(self, database: MongoDatabase) -> None:
        self._db = database

    # ── escrita ──────────────────────────────────────────────────────────

    def upsert_bars(self, bars: Sequence[Bar], *, source: str = "yfinance") -> WriteReport:
        """Grava barras por `(ticker, date)`, atualizando as que já existem.

        Reexecutar sobre a mesma janela não duplica (ING-03.1): a chave é
        única e a operação é upsert, nunca insert.

        Quando o provedor devolve valor diferente para uma data já gravada, a
        alteração é logada com valor anterior e novo (ING-03.2) — uma revisão
        silenciosa de preço histórico é exatamente o tipo de mudança que
        explica um backtest que "mudou sozinho".
        """
        report = WriteReport()
        if not bars:
            return report

        self._log_bar_revisions(bars)

        now = datetime.now(tz=UTC)
        operations = [
            UpdateOne(
                {"ticker": bar.ticker, "date": to_bson_date(bar.date)},
                {
                    "$set": {
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "source": source,
                        "ingested_at": now,
                    }
                },
                upsert=True,
            )
            for bar in bars
        ]
        result = self._db[BARS].bulk_write(operations, ordered=False)
        report.inserted = result.upserted_count
        report.modified = result.modified_count
        report.matched = result.matched_count
        return report

    def _log_bar_revisions(self, bars: Sequence[Bar]) -> None:
        """Compara com o que já está gravado e loga cada campo que mudou.

        Uma leitura por lote em vez de uma por barra: o `bulk_write` seguinte
        perderia a imagem anterior, e ler antes é o que permite reportar
        "de X para Y" em vez de só "mudou".
        """
        existing = self._existing_bars({(bar.ticker, bar.date) for bar in bars})
        for bar in bars:
            previous = existing.get((bar.ticker, bar.date))
            if previous is None:
                continue
            changes = {
                changed_field: {
                    "from": previous.get(changed_field),
                    "to": getattr(bar, changed_field),
                }
                for changed_field in _BAR_VALUE_FIELDS
                if previous.get(changed_field) != getattr(bar, changed_field)
            }
            if changes:
                _log.warning(
                    "storage.bar_revised",
                    ticker=bar.ticker,
                    date=bar.date.isoformat(),
                    changes=changes,
                )

    def _existing_bars(
        self, keys: Iterable[tuple[str, date]]
    ) -> dict[tuple[str, date], MongoDocument]:
        conditions = [
            {"ticker": ticker, "date": to_bson_date(bar_date)} for ticker, bar_date in keys
        ]
        if not conditions:
            return {}
        found = self._db[BARS].find({"$or": conditions})
        return {(doc["ticker"], from_bson_date(doc["date"])): doc for doc in found}

    def upsert_corporate_actions(self, actions: Sequence[CorporateAction]) -> WriteReport:
        """Grava eventos por `(ticker, date, kind)` — design §3.2.

        `kind` entra na chave porque dividendo e split podem cair na mesma
        data ex. Revisão retroativa do provedor atualiza o documento e é
        logada, mesma política de ING-03.2.
        """
        report = WriteReport()
        if not actions:
            return report

        self._log_action_revisions(actions)

        now = datetime.now(tz=UTC)
        operations = []
        for action in actions:
            payload: MongoDocument = {"ingested_at": now}
            if action.kind is CorporateActionKind.DIVIDEND:
                payload["value"] = action.value
            else:
                payload["ratio"] = action.ratio
            operations.append(
                UpdateOne(
                    {
                        "ticker": action.ticker,
                        "date": to_bson_date(action.date),
                        "kind": action.kind.value,
                    },
                    {"$set": payload},
                    upsert=True,
                )
            )

        result = self._db[CORPORATE_ACTIONS].bulk_write(operations, ordered=False)
        report.inserted = result.upserted_count
        report.modified = result.modified_count
        report.matched = result.matched_count
        return report

    def _log_action_revisions(self, actions: Sequence[CorporateAction]) -> None:
        conditions = [
            {
                "ticker": action.ticker,
                "date": to_bson_date(action.date),
                "kind": action.kind.value,
            }
            for action in actions
        ]
        found = self._db[CORPORATE_ACTIONS].find({"$or": conditions})
        existing = {(doc["ticker"], from_bson_date(doc["date"]), doc["kind"]): doc for doc in found}
        for action in actions:
            previous = existing.get((action.ticker, action.date, action.kind.value))
            if previous is None:
                continue
            amount_field = "value" if action.kind is CorporateActionKind.DIVIDEND else "ratio"
            new_amount = action.value if amount_field == "value" else action.ratio
            if previous.get(amount_field) != new_amount:
                _log.warning(
                    "storage.corporate_action_revised",
                    ticker=action.ticker,
                    date=action.date.isoformat(),
                    kind=action.kind.value,
                    **{"from": previous.get(amount_field), "to": new_amount},
                )

    def quarantine_bars(self, entries: Sequence[QuarantinedBar]) -> int:
        """Grava barras rejeitadas — design §3.3.

        Coleção própria, nunca flag em `bars`: uma barra inválida dentro de
        `bars` seria uma bomba esperando um `find` que esquecesse o filtro.

        Sem upsert e sem chave única: o mesmo `(ticker, date)` pode ser
        quarentenado em runs diferentes, e é justamente esse histórico que
        serve para diagnóstico.
        """
        if not entries:
            return 0

        now = datetime.now(tz=UTC)
        documents: list[MongoDocument] = [
            {
                "ticker": entry.ticker,
                "date": to_bson_date(entry.date),
                "raw": entry.raw,
                "reasons": list(entry.reasons),
                "ingestion_run_id": entry.ingestion_run_id,
                "quarantined_at": now,
            }
            for entry in entries
        ]
        result = self._db[QUARANTINED_BARS].insert_many(documents)
        for entry in entries:
            _log.warning(
                "storage.bar_quarantined",
                ticker=entry.ticker,
                date=entry.date.isoformat(),
                reasons=list(entry.reasons),
            )
        return len(result.inserted_ids)

    def start_ingestion_run(self, tickers: Sequence[str], start: date, end: date) -> str:
        """Abre um `ingestion_run` e devolve seu id — design §3.4.

        O documento é inserido **antes** de qualquer barra ser processada,
        para que o id exista a tempo de ser gravado em cada `QuarantinedBar`
        que a validação produzir (referência cruzada de design §3.3). O
        restante dos campos é preenchido por `finish_ingestion_run`.
        """
        now = datetime.now(tz=UTC)
        document: MongoDocument = {
            "tickers": list(tickers),
            "window_start": to_bson_date(start),
            "window_end": to_bson_date(end),
            "started_at": now,
            "finished_at": None,
            "succeeded": [],
            "failed": [],
            "bars_inserted": 0,
            "bars_modified": 0,
            "quarantined_count": 0,
            "warnings": [],
        }
        result = self._db[INGESTION_RUNS].insert_one(document)
        return str(result.inserted_id)

    def finish_ingestion_run(
        self,
        run_id: str,
        *,
        succeeded: Sequence[str],
        failed: Sequence[str],
        bars_inserted: int,
        bars_modified: int,
        quarantined_count: int,
        warnings: Sequence[str],
    ) -> None:
        """Fecha o `ingestion_run` com as contagens finais — design §3.4."""
        now = datetime.now(tz=UTC)
        self._db[INGESTION_RUNS].update_one(
            {"_id": ObjectId(run_id)},
            {
                "$set": {
                    "finished_at": now,
                    "succeeded": list(succeeded),
                    "failed": list(failed),
                    "bars_inserted": bars_inserted,
                    "bars_modified": bars_modified,
                    "quarantined_count": quarantined_count,
                    "warnings": list(warnings),
                }
            },
        )

    def save_backtest_run(self, document: MongoDocument) -> str:
        """Grava um run em `backtest_runs` — design §3.5, F1.

        Sem upsert: cada execução de `backtest` é um registro novo, não uma
        atualização de um anterior — RF-PER-03 quer poder reproduzir *um*
        backtest passado específico, o que exige manter todos, não só o mais
        recente. O documento em si é montado por quem chama (CLI); este
        método só grava e carimba `created_at`, para não fazer `storage/`
        conhecer o formato de `BacktestReport` nem o CLI tocar `datetime` —
        a classe fica restrita a este arquivo e a `ingestion/normalizer.py`
        (design §3.6).
        """
        stamped: MongoDocument = {**document, "created_at": datetime.now(tz=UTC)}
        result = self._db[BACKTEST_RUNS].insert_one(stamped)
        return str(result.inserted_id)

    # ── leitura ──────────────────────────────────────────────────────────

    def get_bars(
        self,
        ticker: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Bar]:
        """Barras brutas do ticker na janela, ordenadas por data."""
        query: MongoDocument = {"ticker": ticker}
        window: MongoDocument = {}
        if start is not None:
            window["$gte"] = to_bson_date(start)
        if end is not None:
            window["$lte"] = to_bson_date(end)
        if window:
            query["date"] = window

        documents = self._db[BARS].find(query).sort("date", 1)
        return [
            Bar(
                ticker=doc["ticker"],
                date=from_bson_date(doc["date"]),
                open=float(doc["open"]),
                high=float(doc["high"]),
                low=float(doc["low"]),
                close=float(doc["close"]),
                volume=int(doc["volume"]),
            )
            for doc in documents
        ]

    def get_corporate_actions(self, ticker: str) -> list[CorporateAction]:
        """**Todos** os eventos do ticker, sobre o histórico completo.

        Sem janela de propósito (ING-02.3, ADR-0003): um split fora do
        intervalo pedido ainda afeta os preços dentro dele. Filtrar aqui seria
        o bug clássico de série ajustada que só está certa no meio.
        """
        documents = self._db[CORPORATE_ACTIONS].find({"ticker": ticker}).sort("date", 1)
        actions: list[CorporateAction] = []
        for doc in documents:
            kind = CorporateActionKind(doc["kind"])
            actions.append(
                CorporateAction(
                    ticker=doc["ticker"],
                    date=from_bson_date(doc["date"]),
                    kind=kind,
                    value=float(doc["value"]) if kind is CorporateActionKind.DIVIDEND else None,
                    ratio=float(doc["ratio"]) if kind is CorporateActionKind.SPLIT else None,
                )
            )
        return actions

    def last_ingested_at(self, ticker: str, start: date | None, end: date | None) -> str | None:
        """Instante da ingestão mais recente que tocou a janela (PER-03.1).

        Devolvido como string ISO-8601, não `datetime`: é metadado de
        auditoria para o relatório, nunca entra em comparação de data, e
        mantê-lo string impede que um `datetime` escape desta fronteira.
        """
        query: MongoDocument = {"ticker": ticker}
        window: MongoDocument = {}
        if start is not None:
            window["$gte"] = to_bson_date(start)
        if end is not None:
            window["$lte"] = to_bson_date(end)
        if window:
            query["date"] = window

        document = self._db[BARS].find_one(query, sort=[("ingested_at", -1)])
        if document is None:
            return None
        ingested_at = document.get("ingested_at")
        if not isinstance(ingested_at, datetime):
            return None
        if ingested_at.tzinfo is None:
            ingested_at = ingested_at.replace(tzinfo=UTC)
        return ingested_at.isoformat()

    def require_bars(self, ticker: str, bars: Sequence[Bar]) -> None:
        """Falha com mensagem acionável quando o ticker não tem dado ingerido."""
        if not bars:
            raise DataError(
                f"Nenhuma barra encontrada para {ticker} na janela pedida. "
                f"Rode a ingestão para {ticker} antes do backtest."
            )

    def get_series(
        self,
        ticker: str,
        start: date | None = None,
        end: date | None = None,
        adjusted: bool = True,
    ) -> PriceSeries:
        """Materializa a série do ticker, ajustada por proventos por default.

        **ADR-0004 — barras e eventos têm o mesmo escopo: o histórico
        completo.** Este método lê *todas* as barras do ticker, não as da
        janela, e delega a materialização a `build_price_series`, que ajusta
        sobre o histórico inteiro e só então recorta `[start, end]`.

        A v0.4 lia os eventos completos mas as barras filtradas pela janela, e
        essa assimetria era o bug: o `C` de um dividendo posterior ao fim da
        janela virava silenciosamente o último fechamento dela, fazendo o
        valor ajustado de uma barra depender da consulta — e com ele o hash de
        PER-03.1.

        O ajuste continua sendo computado **uma vez por chamada**, e o
        `PriceSeries` vive enquanto durar o backtest: uma travessia por
        backtest, não uma por barra. O custo de ler o histórico inteiro para
        devolver uma janela curta é assumido por ADR-0004 e irrelevante no
        volume que ADR-0001 dimensiona.
        """
        return build_price_series(
            ticker,
            self.get_bars(ticker),
            self.get_corporate_actions(ticker),
            start=start,
            end=end,
            adjusted=adjusted,
            last_ingested_at=self.last_ingested_at(ticker, start, end),
        )
