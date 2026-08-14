"""B1 — cliente de dados de mercado: retry, timeout e a regra de ING-04.2.

Unitários, com `FakeProvider` (tests/support.py). Nenhum teste do projeto —
unitário ou de integração — toca rede (RNF-06 vale para a suíte inteira);
é por isso que `ResilientProvider` é testado envolvendo um fake, nunca
`YFinanceProvider`.
"""

from datetime import date

import pandas as pd
import pytest

from quantlab.exceptions import DataError
from quantlab.ingestion.provider import RawCorporateActions
from quantlab.ingestion.resilient_provider import ResilientProvider
from quantlab.ingestion.yfinance_provider import _back_out_splits
from quantlab.storage.adjustment import adjustment_factors
from quantlab.storage.models import CorporateAction, CorporateActionKind
from tests.support import FakeProvider

_START = date(2024, 1, 1)
_END = date(2024, 1, 31)


def _prices_df(rows: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0] * rows,
            "High": [101.0] * rows,
            "Low": [99.0] * rows,
            "Close": [100.5] * rows,
            "Volume": [1_000] * rows,
        }
    )


def _no_sleep(_seconds: float) -> None:
    """Sleep injetável que não dorme — testes de retry não podem esperar de verdade."""


@pytest.mark.unit
def test_successful_fetch_passes_through_untouched() -> None:
    """Caminho feliz: o dado do provedor chega ao chamador sem alteração."""
    expected = _prices_df()
    provider = FakeProvider(prices={"AAPL": expected})
    resilient = ResilientProvider(provider, sleep=_no_sleep)

    result = resilient.fetch_prices("AAPL", _START, _END)

    pd.testing.assert_frame_equal(result, expected)


@pytest.mark.unit
def test_transient_failure_is_retried_and_eventually_succeeds() -> None:
    """Erro nas duas primeiras tentativas, sucesso na terceira."""
    attempts = {"count": 0}
    expected = _prices_df()

    def flaky() -> pd.DataFrame:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("rede instável")
        return expected

    provider = FakeProvider(prices={"AAPL": flaky})
    resilient = ResilientProvider(provider, retries=3, sleep=_no_sleep)

    result = resilient.fetch_prices("AAPL", _START, _END)

    pd.testing.assert_frame_equal(result, expected)
    assert attempts["count"] == 3


@pytest.mark.unit
def test_exhausted_retries_raise_data_error() -> None:
    """Depois de `retries` tentativas, a falha vira `DataError`, não a exceção original."""

    def always_fails() -> pd.DataFrame:
        raise ConnectionError("rede fora do ar")

    provider = FakeProvider(prices={"AAPL": always_fails})
    resilient = ResilientProvider(provider, retries=3, sleep=_no_sleep)

    with pytest.raises(DataError, match="3x"):
        resilient.fetch_prices("AAPL", _START, _END)


@pytest.mark.unit
def test_retry_uses_exponential_backoff() -> None:
    """O backoff dobra a cada tentativa — prova de que não é um sleep fixo."""
    sleeps: list[float] = []

    def always_fails() -> pd.DataFrame:
        raise ConnectionError("rede fora do ar")

    provider = FakeProvider(prices={"AAPL": always_fails})
    resilient = ResilientProvider(provider, retries=4, backoff_seconds=1.0, sleep=sleeps.append)

    with pytest.raises(DataError):
        resilient.fetch_prices("AAPL", _START, _END)

    # 3 sleeps entre 4 tentativas: 1.0, 2.0, 4.0 — nenhum sleep após a última.
    assert sleeps == [1.0, 2.0, 4.0]


@pytest.mark.unit
def test_empty_price_response_is_a_failure_not_zero_bars() -> None:
    """ING-04.2 — resposta vazia é falha explícita, nunca sucesso com zero barras."""
    provider = FakeProvider(
        prices={"XYZ": pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])}
    )
    resilient = ResilientProvider(provider, sleep=_no_sleep)

    with pytest.raises(DataError, match="vazia"):
        resilient.fetch_prices("XYZ", _START, _END)


@pytest.mark.unit
def test_empty_price_response_is_not_retried() -> None:
    """Resposta vazia é determinística — repetir a chamada não ajudaria."""
    provider = FakeProvider(
        prices={"XYZ": pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])}
    )
    resilient = ResilientProvider(provider, retries=5, sleep=_no_sleep)

    with pytest.raises(DataError):
        resilient.fetch_prices("XYZ", _START, _END)

    assert len(provider.price_calls) == 1


@pytest.mark.unit
def test_empty_corporate_actions_is_not_a_failure() -> None:
    """Ausência de dividendo/split é legítima — só preço vazio é ING-04.2."""
    provider = FakeProvider(prices={"BRK-B": _prices_df()})
    resilient = ResilientProvider(provider, sleep=_no_sleep)

    result = resilient.fetch_corporate_actions("BRK-B")

    assert result.dividends.empty
    assert result.splits.empty


@pytest.mark.unit
def test_corporate_actions_have_no_window_argument() -> None:
    """ING-02.3 — a assinatura não aceita start/end; é histórico completo sempre."""
    provider = FakeProvider(
        corporate_actions={
            "AAPL": RawCorporateActions(
                dividends=pd.Series([0.24], index=[pd.Timestamp("2024-01-15")]),
                splits=pd.Series(dtype=float),
            )
        }
    )
    resilient = ResilientProvider(provider, sleep=_no_sleep)

    result = resilient.fetch_corporate_actions("AAPL")

    assert list(result.dividends) == [0.24]


@pytest.mark.unit
def test_corporate_actions_are_also_retried_on_transient_failure() -> None:
    """A resiliência cobre os dois métodos do protocolo, não só preços."""
    attempts = {"count": 0}
    expected = RawCorporateActions(dividends=pd.Series(dtype=float), splits=pd.Series(dtype=float))

    def flaky(_ticker: str) -> RawCorporateActions:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise TimeoutError("provedor lento")
        return expected

    provider = FakeProvider(prices={}, corporate_actions={})
    # Substitui o método para simular a falha, já que o construtor de
    # FakeProvider só aceita valores prontos para corporate_actions.
    provider.fetch_corporate_actions = flaky  # type: ignore[assignment]
    resilient = ResilientProvider(provider, retries=2, sleep=_no_sleep)

    result = resilient.fetch_corporate_actions("AAPL")

    assert result is expected
    assert attempts["count"] == 2


@pytest.mark.unit
def test_retries_must_be_at_least_one() -> None:
    """retries=0 nunca chamaria o provedor — configuração sem sentido."""
    with pytest.raises(ValueError, match="retries"):
        ResilientProvider(FakeProvider(), retries=0)


# ─── back-out dos splits (v0.10 — bug real de dupla contagem da Fase 2a) ───


def _split_adj_frame(close: list[float]) -> pd.DataFrame:
    """Frame split-ajustado no formato que o yfinance devolve (auto_adjust=False)."""
    return pd.DataFrame(
        {
            "Open": close,
            "High": [c * 1.01 for c in close],
            "Low": [c * 0.99 for c in close],
            "Close": close,
            "Volume": [1_000] * len(close),
        }
    )


@pytest.mark.unit
def test_back_out_splits_recovers_raw_closed_form() -> None:
    """Forma fechada: split 4:1 no meio — barras anteriores dobram de valor... 4x.

    Split-ajustado [10, 11, 10, 11] (o yfinance já dividiu as duas primeiras
    barras por 4); bruto recuperado [40, 44, 10, 11]; volume intacto.
    """
    prices = _split_adj_frame([10.0, 11.0, 10.0, 11.0])
    splits = pd.Series([0.0, 0.0, 4.0, 0.0], index=prices.index)

    raw = _back_out_splits(prices, splits)

    assert list(raw["Close"]) == pytest.approx([40.0, 44.0, 10.0, 11.0])
    assert list(raw["Open"]) == pytest.approx([40.0, 44.0, 10.0, 11.0])
    assert list(raw["Volume"]) == [1_000] * 4  # volume é como negociado, intocado


@pytest.mark.unit
def test_back_out_splits_multiple_splits_apply_suffix_product() -> None:
    """Dois splits (2:1 em d2, 4:1 em d3): o fator é o produto dos posteriores.

    Bruto [80, 40, 10]; split-ajustado [10, 10, 10] (80/(2x4), 40/4, 10).
    """
    prices = _split_adj_frame([10.0, 10.0, 10.0])
    splits = pd.Series([0.0, 2.0, 4.0], index=prices.index)

    raw = _back_out_splits(prices, splits)

    assert list(raw["Close"]) == pytest.approx([80.0, 40.0, 10.0])


@pytest.mark.unit
def test_back_out_splits_round_trips_with_storage_adjustment() -> None:
    """Back-out e o ajuste do §3.7 são inversos exatos (round-trip a 1e-9).

    O que o yfinance entregou (split-ajustado) entra; o que o engine consome
    (ajustado por `get_series`) é igual ao original — a dupla contagem some.
    """
    from datetime import date as _date

    dates = [_date(2024, 1, i) for i in range(1, 5)]
    split_adj_close = [10.0, 11.0, 10.0, 11.0]
    prices = _split_adj_frame(split_adj_close)
    prices.index = dates
    splits = pd.Series([0.0, 0.0, 4.0, 0.0], index=dates)

    raw = _back_out_splits(prices, splits)
    factors = adjustment_factors(
        dates,
        raw["Close"].to_numpy(dtype="float64"),
        [
            CorporateAction(
                ticker="AAPL", date=_date(2024, 1, 3), kind=CorporateActionKind.SPLIT, ratio=4.0
            )
        ],
    )
    adjusted = raw["Close"].to_numpy(dtype="float64") * factors.price

    assert list(adjusted) == pytest.approx(split_adj_close, rel=1e-9)


@pytest.mark.unit
def test_back_out_splits_without_splits_is_identity() -> None:
    """Sem split (incluindo NaN na coluna), o frame sai intacto."""
    prices = _split_adj_frame([10.0, 11.0, 12.0])
    splits = pd.Series([0.0, float("nan"), 0.0], index=prices.index)

    raw = _back_out_splits(prices, splits)

    pd.testing.assert_frame_equal(raw, prices)


@pytest.mark.unit
def test_back_out_splits_does_not_mutate_input() -> None:
    """Função pura: o frame de entrada fica intacto (RNF-01)."""
    prices = _split_adj_frame([10.0, 11.0, 10.0, 11.0])
    splits = pd.Series([0.0, 0.0, 4.0, 0.0], index=prices.index)
    before = prices.copy(deep=True)

    _back_out_splits(prices, splits)

    pd.testing.assert_frame_equal(prices, before)
