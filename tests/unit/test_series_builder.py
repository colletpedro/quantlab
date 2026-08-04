"""ADR-0004 — materialização sobre o histórico completo, depois fatiamento.

Offline, com fixtures de papel: `build_price_series` é função pura (histórico
completo + eventos entram, `PriceSeries` fatiada sai), então o invariante de
independência de janela é testável sem Mongo. O mesmo invariante contra banco
real está em `tests/integration/test_repository_series.py`.

Esta separação existe por causa do bug: enquanto a materialização morava
dentro de `MongoRepository.get_series`, só um teste de integração podia
exercitá-la, e nenhum existia para o caso de dividendo pós-janela.
"""

from datetime import date

import pytest
from structlog.typing import EventDict

from quantlab.exceptions import DataError
from quantlab.storage.models import Bar, CorporateAction, CorporateActionKind
from quantlab.storage.series import build_price_series

#: Histórico COMPLETO de cinco pregões, com fechamentos redondos.
#: O dividendo de 08/01 tem sua barra anterior (05/01, close 200.00) dentro do
#: histórico, mas fora de qualquer janela que termine antes de 05/01.
_HISTORY = [
    Bar(
        ticker="TEST",
        date=date(2024, 1, 2),
        open=99.0,
        high=101.0,
        low=98.0,
        close=100.0,
        volume=1_000,
    ),
    Bar(
        ticker="TEST",
        date=date(2024, 1, 3),
        open=105.0,
        high=112.0,
        low=104.0,
        close=110.0,
        volume=2_000,
    ),
    Bar(
        ticker="TEST",
        date=date(2024, 1, 4),
        open=115.0,
        high=122.0,
        low=114.0,
        close=120.0,
        volume=3_000,
    ),
    Bar(
        ticker="TEST",
        date=date(2024, 1, 5),
        open=190.0,
        high=205.0,
        low=189.0,
        close=200.0,
        volume=4_000,
    ),
    Bar(
        ticker="TEST",
        date=date(2024, 1, 8),
        open=205.0,
        high=215.0,
        low=204.0,
        close=210.0,
        volume=5_000,
    ),
]

#: d = 2.00 em 08/01. C = close bruto de 05/01 = 200.00.
#: fator = (200.00 - 2.00)/200.00 = 0.99 nas quatro primeiras barras.
_DIVIDEND = CorporateAction(
    ticker="TEST",
    date=date(2024, 1, 8),
    kind=CorporateActionKind.DIVIDEND,
    value=2.00,
)


@pytest.mark.unit
def test_full_read_uses_the_true_previous_close() -> None:
    """Linha de base: leitura sem janela, valores calculados à mão.

    100.0 * 0.99 =  99.00
    110.0 * 0.99 = 108.90
    120.0 * 0.99 = 118.80
    200.0 * 0.99 = 198.00
    210.0 * 1.00 = 210.00
    """
    series = build_price_series("TEST", _HISTORY, [_DIVIDEND], start=None, end=None)

    assert list(series.close) == pytest.approx([99.0, 108.9, 118.8, 198.0, 210.0])


@pytest.mark.unit
def test_window_that_ends_before_the_ex_date_gets_the_same_values() -> None:
    """O INVARIANTE de ADR-0004, no caso que produziu o bug.

    A janela [02/01, 04/01] termina antes da barra que dá o `C` (05/01). Na
    v0.4 isso fazia `C` virar 120.00 (fechamento de 04/01) e o fator virar
    0.983333, produzindo 98.3333 na primeira barra. Com a materialização
    sobre o histórico completo, a janela não influencia nada: os três
    primeiros valores são exatamente os da leitura completa.
    """
    window = build_price_series(
        "TEST", _HISTORY, [_DIVIDEND], start=date(2024, 1, 2), end=date(2024, 1, 4)
    )

    assert len(window) == 3
    assert list(window.close) == pytest.approx([99.0, 108.9, 118.8])

    # O valor que a v0.4 produzia, para deixar o contraste no teste:
    stale = 100.0 * (120.0 - 2.00) / 120.0
    assert stale == pytest.approx(98.3333333333)
    assert float(window.close[0]) != pytest.approx(stale)


@pytest.mark.unit
def test_two_windows_agree_value_by_value_on_shared_bars() -> None:
    """Independência de janela, enunciada como o design v0.5 §3.7 a enuncia.

    Duas leituras de janelas distintas concordam VALOR A VALOR nas barras que
    compartilham. Antes de ADR-0004 divergiam — medido em AAPL: 0,0437% entre
    uma leitura de 42 barras e uma de 7, com hashes distintos.
    """
    wide = build_price_series("TEST", _HISTORY, [_DIVIDEND], start=None, end=None)
    narrow = build_price_series(
        "TEST", _HISTORY, [_DIVIDEND], start=date(2024, 1, 3), end=date(2024, 1, 5)
    )

    wide_by_date = {d: float(c) for d, c in zip(wide.dates, wide.close, strict=True)}
    shared = [(d, float(c)) for d, c in zip(narrow.dates, narrow.close, strict=True)]

    assert len(shared) == 3
    for bar_date, value in shared:
        assert value == pytest.approx(wide_by_date[bar_date], rel=1e-15)


@pytest.mark.unit
def test_every_field_is_window_independent_not_just_close() -> None:
    """O invariante vale para OHLCV inteiro, não só para o fechamento."""
    wide = build_price_series("TEST", _HISTORY, [_DIVIDEND], start=None, end=None)
    narrow = build_price_series(
        "TEST", _HISTORY, [_DIVIDEND], start=date(2024, 1, 3), end=date(2024, 1, 4)
    )

    offset = 1  # narrow começa na segunda barra do histórico
    for field in ("open", "high", "low", "close", "volume"):
        wide_values = list(getattr(wide, field))[offset : offset + len(narrow)]
        assert list(getattr(narrow, field)) == pytest.approx(wide_values, rel=1e-15), field


@pytest.mark.unit
def test_window_slice_does_not_change_the_hash_of_shared_content() -> None:
    """Duas janelas idênticas em conteúdo produzem o mesmo hash (PER-03.1).

    O hash é da série devolvida, então janelas de tamanhos diferentes têm
    hashes diferentes — o que não pode acontecer é o mesmo recorte mudar de
    hash conforme o caminho pelo qual foi pedido.
    """
    first = build_price_series(
        "TEST", _HISTORY, [_DIVIDEND], start=date(2024, 1, 3), end=date(2024, 1, 4)
    )
    second = build_price_series(
        "TEST", _HISTORY, [_DIVIDEND], start=date(2024, 1, 3), end=date(2024, 1, 4)
    )

    assert first.hash == second.hash


@pytest.mark.unit
def test_raw_read_is_not_adjusted_but_is_still_sliced() -> None:
    """`adjusted=False` devolve o bruto, e o fatiamento continua valendo."""
    window = build_price_series(
        "TEST",
        _HISTORY,
        [_DIVIDEND],
        start=date(2024, 1, 2),
        end=date(2024, 1, 4),
        adjusted=False,
    )

    assert window.adjusted is False
    assert list(window.close) == pytest.approx([100.0, 110.0, 120.0])


@pytest.mark.unit
def test_event_after_the_last_bar_of_the_history_is_discarded(
    log_events: list[EventDict],
) -> None:
    """Design v0.5 §3.7 — na ponta direita do histórico não há `C` honesto."""
    late = CorporateAction(
        ticker="TEST",
        date=date(2024, 6, 1),
        kind=CorporateActionKind.DIVIDEND,
        value=5.00,
    )

    series = build_price_series("TEST", _HISTORY, [late], start=None, end=None)

    assert list(series.close) == pytest.approx([100.0, 110.0, 120.0, 200.0, 210.0])
    assert [e for e in log_events if e["event"] == "storage.event_after_last_bar"]


@pytest.mark.unit
def test_window_with_no_bars_fails_with_an_actionable_message() -> None:
    """Janela fora do histórico é erro de uso, com mensagem que diz o que fazer."""
    with pytest.raises(DataError, match="janela"):
        build_price_series("TEST", _HISTORY, [], start=date(2030, 1, 1), end=date(2030, 12, 31))


@pytest.mark.unit
def test_ticker_without_any_bars_fails_with_an_actionable_message() -> None:
    with pytest.raises(DataError, match="ingestão"):
        build_price_series("TEST", [], [], start=None, end=None)
