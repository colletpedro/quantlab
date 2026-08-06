"""B3 — validador: quarentena (ING-05.1) e avisos não-bloqueantes (ING-05.2, ING-05.3).

Unitários, função pura — nenhum banco. Cada regra de CA-05.1 tem sua própria
fixture, isolada das demais, para que uma falha aponte exatamente qual regra
quebrou.
"""

from dataclasses import replace
from datetime import date

import pytest

from quantlab.ingestion.validator import validate_bars
from quantlab.storage.models import Bar, CorporateAction, CorporateActionKind

#: `as_of` fixo, bem depois de qualquer data usada nas fixtures deste
#: arquivo (todas em 2024-01) — nenhum teste de ING-05.x/CA-05.1 deve ser
#: afetado pelo descarte de RF-CON-01 sem pedir isso explicitamente.
_AS_OF = date(2024, 2, 1)


def _bar(
    day: int,
    *,
    open_: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 102.0,
    volume: int = 1_000,
    ticker: str = "XYZ",
) -> Bar:
    return Bar(
        ticker=ticker,
        date=date(2024, 1, day),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


@pytest.mark.unit
def test_plausible_bar_is_valid_with_no_reasons() -> None:
    result = validate_bars([_bar(2)], [], as_of=_AS_OF)
    assert result.valid_bars == [_bar(2)]
    assert result.quarantined_bars == []
    assert result.warnings == []


# ─── CA-05.1 — cada regra isolada ────────────────────────────────────────────


@pytest.mark.unit
def test_high_below_low_is_quarantined() -> None:
    """`high < low` torna o intervalo inválido: open/close (100/102, os
    defaults de `_bar`) inevitavelmente também caem fora dele — não é
    possível isolar só esta regra sem violar as outras, e é exatamente o
    comportamento certo (ver `test_all_violated_rules_are_reported...`).
    """
    result = validate_bars([_bar(2, high=90.0, low=95.0)], [], as_of=_AS_OF)
    assert result.valid_bars == []
    assert "high_below_low" in result.quarantined_bars[0].reasons


@pytest.mark.unit
def test_open_above_high_is_quarantined() -> None:
    result = validate_bars([_bar(2, open_=110.0, high=105.0, low=95.0)], [], as_of=_AS_OF)
    assert result.quarantined_bars[0].reasons == ("open_above_high",)


@pytest.mark.unit
def test_open_below_low_is_quarantined() -> None:
    result = validate_bars([_bar(2, open_=80.0, high=105.0, low=95.0)], [], as_of=_AS_OF)
    assert result.quarantined_bars[0].reasons == ("open_below_low",)


@pytest.mark.unit
def test_close_above_high_is_quarantined() -> None:
    result = validate_bars([_bar(2, close=110.0, high=105.0, low=95.0)], [], as_of=_AS_OF)
    assert result.quarantined_bars[0].reasons == ("close_above_high",)


@pytest.mark.unit
def test_close_below_low_is_quarantined() -> None:
    result = validate_bars([_bar(2, close=80.0, high=105.0, low=95.0)], [], as_of=_AS_OF)
    assert result.quarantined_bars[0].reasons == ("close_below_low",)


@pytest.mark.unit
def test_non_positive_open_is_quarantined() -> None:
    result = validate_bars([replace(_bar(2), open=0.0)], [], as_of=_AS_OF)
    assert "open_not_positive" in result.quarantined_bars[0].reasons


@pytest.mark.unit
def test_non_positive_high_is_quarantined() -> None:
    result = validate_bars([replace(_bar(2), high=0.0)], [], as_of=_AS_OF)
    assert "high_not_positive" in result.quarantined_bars[0].reasons


@pytest.mark.unit
def test_non_positive_low_is_quarantined() -> None:
    result = validate_bars([replace(_bar(2), low=-5.0)], [], as_of=_AS_OF)
    assert "low_not_positive" in result.quarantined_bars[0].reasons


@pytest.mark.unit
def test_non_positive_close_is_quarantined() -> None:
    result = validate_bars([replace(_bar(2), close=0.0)], [], as_of=_AS_OF)
    assert "close_not_positive" in result.quarantined_bars[0].reasons


@pytest.mark.unit
def test_negative_volume_is_quarantined() -> None:
    result = validate_bars([_bar(2, volume=-100)], [], as_of=_AS_OF)
    assert result.quarantined_bars[0].reasons == ("volume_negative",)


_NON_FINITE_BARS = {
    "open": lambda value: _bar(2, open_=value),
    "high": lambda value: _bar(2, high=value),
    "low": lambda value: _bar(2, low=value),
    "close": lambda value: _bar(2, close=value),
}


@pytest.mark.unit
@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_nan_price_is_quarantined(field: str) -> None:
    """v1.1 CA-05.1 — `NaN` não aciona nenhuma comparação de desigualdade.

    Antes desta regra, `close=nan` (ou qualquer outro preço) não violava
    `high < low`, `fora de [low, high]` nem `preço <= 0` — todas essas
    comparações devolvem `False` para `nan`, então a barra passava como
    válida. É o bug real que a ingestão de F4 expôs contra o yfinance.
    """
    bar = _NON_FINITE_BARS[field](float("nan"))
    result = validate_bars([bar], [], as_of=_AS_OF)

    assert result.valid_bars == []
    assert result.quarantined_bars[0].reasons == ("non_finite_price",)


@pytest.mark.unit
@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_infinite_price_is_quarantined(field: str) -> None:
    bar = _NON_FINITE_BARS[field](float("inf"))
    result = validate_bars([bar], [], as_of=_AS_OF)

    assert result.valid_bars == []
    assert result.quarantined_bars[0].reasons == ("non_finite_price",)


@pytest.mark.unit
def test_nan_price_and_negative_volume_report_both_reasons() -> None:
    """`non_finite_price` não engole outras razões independentes — só as de
    intervalo/sinal de preço, que seriam redundantes com ela."""
    bar = replace(_bar(2), close=float("nan"), volume=-1)
    result = validate_bars([bar], [], as_of=_AS_OF)

    assert set(result.quarantined_bars[0].reasons) == {"non_finite_price", "volume_negative"}


@pytest.mark.unit
def test_all_violated_rules_are_reported_not_just_the_first() -> None:
    """O ponto central de design §3.3: nenhuma regra é reportada isoladamente
    se mais de uma falhar na mesma barra.

    high < low (90 < 95) também força open (100, default de `_bar`) a violar
    `open_above_high`; close (200) viola `close_above_high` por conta própria;
    e volume é negativo. Quatro razões, todas presentes ao mesmo tempo.
    """
    bar = _bar(2, high=90.0, low=95.0, close=200.0, volume=-1)
    result = validate_bars([bar], [], as_of=_AS_OF)

    reasons = set(result.quarantined_bars[0].reasons)
    assert reasons == {
        "high_below_low",
        "open_above_high",
        "close_above_high",
        "volume_negative",
    }


@pytest.mark.unit
def test_quarantined_bar_carries_the_raw_values_and_run_id() -> None:
    bar = _bar(2, volume=-1)
    result = validate_bars([bar], [], ingestion_run_id="run-123", as_of=_AS_OF)

    entry = result.quarantined_bars[0]
    assert entry.raw == {"open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": -1}
    assert entry.ingestion_run_id == "run-123"
    assert entry.ticker == "XYZ"
    assert entry.date == date(2024, 1, 2)


@pytest.mark.unit
def test_quarantined_bar_does_not_appear_among_valid_bars() -> None:
    good = _bar(2)
    bad = _bar(3, volume=-1)
    result = validate_bars([good, bad], [], as_of=_AS_OF)

    assert result.valid_bars == [good]
    assert len(result.quarantined_bars) == 1


# ─── ING-05.2 — gap de pregões ────────────────────────────────────────────────


@pytest.mark.unit
def test_consecutive_trading_days_produce_no_gap_warning() -> None:
    result = validate_bars([_bar(2), _bar(3), _bar(4)], [], as_of=_AS_OF)
    assert result.warnings == []
    assert len(result.valid_bars) == 3


@pytest.mark.unit
def test_weekend_between_friday_and_monday_is_not_a_gap() -> None:
    """05/01/2024 é sexta; 08/01/2024 é segunda. Fim de semana não é gap."""
    result = validate_bars([_bar(5), _bar(8)], [], as_of=_AS_OF)
    assert result.warnings == []


@pytest.mark.unit
def test_gap_over_five_business_days_warns_but_does_not_quarantine() -> None:
    """Uma semana inteira faltando (4 dias úteis) não passa do limiar de 5;
    duas semanas (9 dias úteis) passa."""
    # 02/01/2024 é terça; 22/01/2024 é segunda, 3 semanas depois.
    bars = [
        _bar(2),
        Bar(
            ticker="XYZ",
            date=date(2024, 1, 22),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1_000,
        ),
    ]
    result = validate_bars(bars, [], as_of=_AS_OF)

    assert len(result.warnings) == 1
    assert "dias úteis" in result.warnings[0]
    # O aviso não é bloqueante — as duas barras continuam válidas.
    assert len(result.valid_bars) == 2
    assert result.quarantined_bars == []


@pytest.mark.unit
def test_gap_warning_is_not_raised_for_a_quarantined_neighbor() -> None:
    """Uma barra quarentenada não conta como pregão presente para fins de gap."""
    good_first = _bar(2)
    invalid_middle = _bar(3, volume=-1)
    good_last = _bar(4)
    result = validate_bars([good_first, invalid_middle, good_last], [], as_of=_AS_OF)

    # 02/01 -> 04/01 é gap de 1 dia útil (03/01), abaixo do limiar de 5.
    assert result.warnings == []
    assert result.valid_bars == [good_first, good_last]


# ─── ING-05.3 — variação sem split ────────────────────────────────────────────


@pytest.mark.unit
def test_large_variation_without_split_warns() -> None:
    bars = [_bar(2, close=100.0), _bar(3, close=45.0, open_=45.0, high=50.0, low=40.0)]
    result = validate_bars(bars, [], as_of=_AS_OF)

    assert len(result.warnings) == 1
    assert "Variação" in result.warnings[0]
    assert len(result.valid_bars) == 2


@pytest.mark.unit
def test_large_variation_with_split_on_the_date_does_not_warn() -> None:
    """A queda de preço É esperada quando há split registrado naquela data."""
    bars = [_bar(2, close=100.0), _bar(3, close=45.0, open_=45.0, high=50.0, low=40.0)]
    split = CorporateAction(
        ticker="XYZ", date=date(2024, 1, 3), kind=CorporateActionKind.SPLIT, ratio=2.0
    )

    result = validate_bars(bars, [split], as_of=_AS_OF)

    assert result.warnings == []


@pytest.mark.unit
def test_small_variation_does_not_warn() -> None:
    bars = [_bar(2, close=100.0), _bar(3, close=103.0, open_=101.0, high=104.0, low=99.0)]
    result = validate_bars(bars, [], as_of=_AS_OF)
    assert result.warnings == []


@pytest.mark.unit
def test_dividend_on_the_date_does_not_suppress_the_variation_warning() -> None:
    """Só SPLIT suspende o aviso (ING-05.3 fala em 'split registrado');
    um dividendo de magnitude normal não explica queda de 50%."""
    bars = [_bar(2, close=100.0), _bar(3, close=45.0, open_=45.0, high=50.0, low=40.0)]
    dividend = CorporateAction(
        ticker="XYZ", date=date(2024, 1, 3), kind=CorporateActionKind.DIVIDEND, value=0.5
    )

    result = validate_bars(bars, [dividend], as_of=_AS_OF)

    assert len(result.warnings) == 1


# ─── ordenação ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_bars_out_of_order_are_sorted_before_sequence_checks() -> None:
    """Entrada fora de ordem não pode inventar um gap ou variação falsos."""
    out_of_order = [_bar(4), _bar(2), _bar(3)]
    result = validate_bars(out_of_order, [], as_of=_AS_OF)

    assert [bar.date for bar in result.valid_bars] == [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
    ]
    assert result.warnings == []


# ─── RF-CON-01 (v0.9) — descarte de sessão em formação ───────────────────────


@pytest.mark.unit
def test_bar_dated_today_is_discarded_not_quarantined() -> None:
    """Sessão em formação: data == as_of. Não é dado inválido, é incompleto."""
    today_bar = _bar(2, close=float("nan"))  # também violaria non_finite_price
    result = validate_bars([today_bar], [], as_of=date(2024, 1, 2))

    assert result.discarded_bars == [today_bar]
    assert result.valid_bars == []
    assert result.quarantined_bars == []  # não quarentenada, mesmo com close=nan
    assert len(result.warnings) == 1
    assert "descartada" in result.warnings[0]


@pytest.mark.unit
def test_bar_dated_after_as_of_is_also_discarded() -> None:
    """`>=`, não só `==` — cobre relógio do provedor à frente do da ingestão."""
    future_bar = _bar(3)
    result = validate_bars([future_bar], [], as_of=date(2024, 1, 2))

    assert result.discarded_bars == [future_bar]
    assert result.valid_bars == []


@pytest.mark.unit
def test_bar_dated_before_as_of_is_not_discarded() -> None:
    """A barra do pregão anterior — já fechada — segue o caminho normal."""
    closed_bar = _bar(2)
    result = validate_bars([closed_bar], [], as_of=date(2024, 1, 3))

    assert result.discarded_bars == []
    assert result.valid_bars == [closed_bar]


@pytest.mark.unit
def test_discarded_bar_is_excluded_from_gap_and_variation_checks() -> None:
    """Uma barra descartada não é pregão presente: não conta para ING-05.2/05.3,
    mesma regra que já vale para barra quarentenada."""
    closed = _bar(2)
    in_progress = _bar(3)  # seria o próximo pregão, mas ainda está em formação
    result = validate_bars([closed, in_progress], [], as_of=date(2024, 1, 3))

    assert result.valid_bars == [closed]
    assert result.discarded_bars == [in_progress]
    # Só o aviso de descarte, nenhum gap/variação inventado contra uma barra
    # que não deveria ter sido comparada.
    assert len(result.warnings) == 1
    assert "descartada" in result.warnings[0]


@pytest.mark.unit
def test_multiple_discarded_bars_are_all_counted() -> None:
    result = validate_bars([_bar(2), _bar(3)], [], as_of=date(2024, 1, 1))

    assert len(result.discarded_bars) == 2
    assert result.valid_bars == []
    assert len(result.warnings) == 2
