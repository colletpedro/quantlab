"""Retry, timeout e a regra de resposta vazia — aplicados por composição.

`ResilientProvider` envolve **qualquer** `MarketDataProvider`: o real
(`YFinanceProvider`) e o de teste (`FakeProvider`) recebem exatamente o mesmo
comportamento de resiliência, sem duplicar a lógica em cada implementação.
É isso que torna B1 testável sem rede — os testes envolvem um `FakeProvider`
programado para falhar N vezes, não uma conexão de verdade que falha.
"""

import time
from collections.abc import Callable
from datetime import date
from typing import TypeVar

import pandas as pd

from quantlab.exceptions import DataError
from quantlab.ingestion.provider import MarketDataProvider, RawCorporateActions
from quantlab.logging import get_logger

__all__ = ["ResilientProvider"]

_log = get_logger(__name__)

_T = TypeVar("_T")

_DEFAULT_RETRIES = 3
_DEFAULT_BACKOFF_SECONDS = 1.0


class ResilientProvider:
    """Envolve um `MarketDataProvider` com retry+backoff e a regra de ING-04.2.

    - **Exceção do provedor** (erro de rede, timeout, HTTP 5xx): retry com
      backoff exponencial, até `retries` tentativas; esgotadas, vira
      `DataError`.
    - **Resposta vazia de preços**: `DataError` **imediata**, sem retry —
      não é uma falha transitória, e tentar de novo não mudaria o resultado
      (ING-04.2: "isso é tratado como falha explícita, não como sucesso com
      zero barras").

    Implementa o mesmo `MarketDataProvider` que envolve — é decorator, não
    subclasse.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        *,
        retries: int = _DEFAULT_RETRIES,
        backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if retries < 1:
            raise ValueError(f"retries precisa ser >= 1, recebeu {retries}.")
        self._provider = provider
        self._retries = retries
        self._backoff_seconds = backoff_seconds
        # Injetável: testes de retry não podem depender de dormir de verdade.
        self._sleep = sleep

    def fetch_prices(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        prices = self._with_retry(
            lambda: self._provider.fetch_prices(ticker, start, end),
            operation="fetch_prices",
            ticker=ticker,
        )
        if prices.empty:
            raise DataError(
                f"Provedor devolveu resposta vazia para {ticker} em "
                f"[{start.isoformat()}, {end.isoformat()}]. Tratado como falha "
                "explícita (ING-04.2), não como sucesso com zero barras."
            )
        return prices

    def fetch_corporate_actions(self, ticker: str) -> RawCorporateActions:
        # Vazio é legítimo aqui: um ticker pode nunca ter pago dividendo nem
        # feito split (ex.: BRK-B). Só a série de preços trata vazio como
        # falha — corporate actions não tem o equivalente de ING-04.2.
        return self._with_retry(
            lambda: self._provider.fetch_corporate_actions(ticker),
            operation="fetch_corporate_actions",
            ticker=ticker,
        )

    def _with_retry(self, call: Callable[[], _T], *, operation: str, ticker: str) -> _T:
        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                return call()
            except Exception as exc:
                last_error = exc
                _log.warning(
                    "ingestion.provider_retry",
                    operation=operation,
                    ticker=ticker,
                    attempt=attempt,
                    retries=self._retries,
                    error=str(exc),
                )
                if attempt < self._retries:
                    # Backoff exponencial: 1x, 2x, 4x... o backoff base.
                    self._sleep(self._backoff_seconds * (2 ** (attempt - 1)))
        raise DataError(
            f"Provedor falhou {self._retries}x para {ticker} em `{operation}`: {last_error}"
        ) from last_error
