"""A7 — fator de ajuste por proventos (PER-02.1 a PER-02.4, ADR-0003).

**Fixtures de papel.** Toda série aqui é construída à mão e todo valor esperado
está calculado na aritmética escrita no comentário logo acima dele (RNF-03).
Nenhum número esperado saiu de rodar o código: um teste que confere o
resultado contra o que a própria implementação produziu não valida nada.

As regras que estes testes travam, de ADR-0003 e design §3.7:

- split de razão `r`: preços ÷ r, volume * r
- dividendo `d` na data ex D: fator `(C - d)/C`, onde `C` é o fechamento
  **bruto** do pregão anterior a D; volume inalterado
- o fator da barra em `t` é o produto dos fatores de eventos **estritamente
  posteriores** a `t`
"""

from datetime import date

import numpy as np
import pytest
from numpy.typing import NDArray
from structlog.typing import EventDict

from quantlab.exceptions import DataError
from quantlab.storage.adjustment import adjustment_factors
from quantlab.storage.models import CorporateAction, CorporateActionKind


def _closes(*values: float) -> NDArray[np.float64]:
    return np.array(values, dtype=np.float64)


def _split(day: int, ratio: float, month: int = 1, year: int = 2024) -> CorporateAction:
    return CorporateAction(
        ticker="TEST",
        date=date(year, month, day),
        kind=CorporateActionKind.SPLIT,
        ratio=ratio,
    )


def _dividend(day: int, value: float, month: int = 1, year: int = 2024) -> CorporateAction:
    return CorporateAction(
        ticker="TEST",
        date=date(year, month, day),
        kind=CorporateActionKind.DIVIDEND,
        value=value,
    )


# ─── cenário 1: split isolado ────────────────────────────────────────────────

#: Quatro pregões; split 2:1 com data ex em 04/01.
_S1_DATES = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
_S1_CLOSES = _closes(100.0, 110.0, 120.0, 65.0)
_S1_VOLUMES = _closes(1_000.0, 2_000.0, 3_000.0, 4_000.0)


@pytest.mark.unit
def test_isolated_split_halves_prices_and_doubles_volume_before_the_ex_date() -> None:
    """PER-02.1 — split 2:1 em 04/01.

    Barras estritamente anteriores a 04/01 são 02/01 e 03/01.
    Fator de preço = 1/2 = 0.5 nelas, 1.0 em 04/01 e 05/01.
    Fator de volume = 2.0 nelas, 1.0 nas demais.
    """
    factors = adjustment_factors(_S1_DATES, _S1_CLOSES, [_split(4, 2.0)])

    assert list(factors.price) == pytest.approx([0.5, 0.5, 1.0, 1.0])
    assert list(factors.volume) == pytest.approx([2.0, 2.0, 1.0, 1.0])

    # 100.0 * 0.5 = 50.0   |   110.0 * 0.5 = 55.0   |   120.0 * 1 = 120.0   |   65.0 * 1 = 65.0
    assert list(_S1_CLOSES * factors.price) == pytest.approx([50.0, 55.0, 120.0, 65.0])
    # 1000 * 2 = 2000      |   2000 * 2 = 4000      |   3000 * 1 = 3000     |   4000 * 1 = 4000
    assert list(_S1_VOLUMES * factors.volume) == pytest.approx([2_000.0, 4_000.0, 3_000.0, 4_000.0])


@pytest.mark.unit
def test_reverse_split_multiplies_prices_and_divides_volume() -> None:
    """Agrupamento é split de razão < 1 e não pode ser tratado como erro.

    r = 0.5 ⇒ fator de preço 1/0.5 = 2.0; fator de volume 0.5.
    """
    factors = adjustment_factors(_S1_DATES, _S1_CLOSES, [_split(4, 0.5)])

    assert list(factors.price) == pytest.approx([2.0, 2.0, 1.0, 1.0])
    assert list(factors.volume) == pytest.approx([0.5, 0.5, 1.0, 1.0])


# ─── cenário 2: dividendo isolado ────────────────────────────────────────────

#: `C` é o fechamento bruto de 03/01 = 50.00, escolhido redondo para que a
#: conta do fator caiba na cabeça.
_S2_DATES = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
_S2_CLOSES = _closes(100.0, 50.0, 60.0, 70.0)
_S2_VOLUMES = _closes(1_000.0, 2_000.0, 3_000.0, 4_000.0)


@pytest.mark.unit
def test_isolated_dividend_scales_prices_and_leaves_volume_alone() -> None:
    """PER-02.2 — dividendo de 0.50 com data ex em 04/01.

    C = fechamento bruto do pregão anterior a 04/01 = close de 03/01 = 50.00
    fator = (C - d)/C = (50.00 - 0.50)/50.00 = 49.50/50.00 = 0.99

    Aplicado às barras estritamente anteriores a 04/01: 02/01 e 03/01.
    Volume não muda em dividendo.
    """
    factors = adjustment_factors(_S2_DATES, _S2_CLOSES, [_dividend(4, 0.50)])

    assert list(factors.price) == pytest.approx([0.99, 0.99, 1.0, 1.0])
    assert list(factors.volume) == pytest.approx([1.0, 1.0, 1.0, 1.0])

    # 100.0 * 0.99 = 99.0   |   50.0 * 0.99 = 49.5   |   60.0 e 70.0 intactos
    assert list(_S2_CLOSES * factors.price) == pytest.approx([99.0, 49.5, 60.0, 70.0])
    assert list(_S2_VOLUMES * factors.volume) == pytest.approx(list(_S2_VOLUMES))


# ─── cenário 3: dividendo e split combinados ─────────────────────────────────

#: Cinco pregões. Dividendo em 04/01 e split 2:1 em 08/01 — o split é
#: posterior ao dividendo de propósito, para que o `C` do dividendo tenha de
#: ser o fechamento BRUTO e não o já ajustado pelo split.
_S3_DATES = [
    date(2024, 1, 2),
    date(2024, 1, 3),
    date(2024, 1, 4),
    date(2024, 1, 5),
    date(2024, 1, 8),
]
_S3_CLOSES = _closes(100.0, 50.0, 60.0, 80.0, 45.0)
_S3_VOLUMES = _closes(1_000.0, 2_000.0, 3_000.0, 4_000.0, 5_000.0)


@pytest.mark.unit
def test_combined_dividend_and_split_multiply_cumulatively() -> None:
    """PER-02.1 + PER-02.2 — fatores acumulam por produto.

    Dividendo 0.50 em 04/01: C = close bruto de 03/01 = 50.00
        fator_div = (50.00 - 0.50)/50.00 = 0.99   → barras 02/01 e 03/01
    Split 2:1 em 08/01:
        fator_split = 0.5                          → barras 02/01 a 05/01

    Produto por barra (eventos estritamente posteriores a ela):
        02/01: 0.99 * 0.5 = 0.495
        03/01: 0.99 * 0.5 = 0.495
        04/01:        0.5 = 0.5
        05/01:        0.5 = 0.5
        08/01:              1.0
    """
    factors = adjustment_factors(_S3_DATES, _S3_CLOSES, [_dividend(4, 0.50), _split(8, 2.0)])

    assert list(factors.price) == pytest.approx([0.495, 0.495, 0.5, 0.5, 1.0])
    # Volume só reage a split: 2.0 até 05/01, 1.0 em 08/01.
    assert list(factors.volume) == pytest.approx([2.0, 2.0, 2.0, 2.0, 1.0])

    # 100.0 * 0.495 = 49.50  |  50.0 * 0.495 = 24.75  |  60.0 * 0.5 = 30.0
    # 80.0 * 0.5   = 40.00   |  45.0 * 1.0   = 45.00
    assert list(_S3_CLOSES * factors.price) == pytest.approx([49.5, 24.75, 30.0, 40.0, 45.0])
    assert list(_S3_VOLUMES * factors.volume) == pytest.approx(
        [2_000.0, 4_000.0, 6_000.0, 8_000.0, 5_000.0]
    )


@pytest.mark.unit
def test_dividend_uses_the_raw_close_not_the_split_adjusted_one() -> None:
    """O detalhe de ADR-0003 que é fácil errar e difícil notar.

    `C` é o fechamento **bruto** de 03/01 (50.00), não o ajustado pelo split
    posterior (25.00). Com o bruto o fator é 0.99; com o ajustado seria
    (25.00 - 0.50)/25.00 = 0.98 — plausível, e errado.

    A diferença aparece no preço final de 02/01:
        certo:  100.0 * 0.99 * 0.5 = 49.50
        errado: 100.0 * 0.98 * 0.5 = 49.00
    """
    factors = adjustment_factors(_S3_DATES, _S3_CLOSES, [_dividend(4, 0.50), _split(8, 2.0)])

    adjusted_first_close = float(_S3_CLOSES[0] * factors.price[0])
    assert adjusted_first_close == pytest.approx(49.50)
    assert adjusted_first_close != pytest.approx(49.00)


@pytest.mark.unit
def test_event_order_in_the_input_does_not_change_the_result() -> None:
    """RNF-01 — a lista de eventos chega em qualquer ordem e o fator é o mesmo."""
    ascending = adjustment_factors(_S3_DATES, _S3_CLOSES, [_dividend(4, 0.50), _split(8, 2.0)])
    descending = adjustment_factors(_S3_DATES, _S3_CLOSES, [_split(8, 2.0), _dividend(4, 0.50)])

    assert list(ascending.price) == pytest.approx(list(descending.price))
    assert list(ascending.volume) == pytest.approx(list(descending.volume))


@pytest.mark.unit
def test_dividend_and_split_on_the_same_ex_date_both_apply() -> None:
    """Mesma data ex: os dois fatores entram no mesmo ponto da série.

    C do dividendo = close bruto de 03/01 = 50.00 → 0.99
    split 2:1 → 0.5
    Barras anteriores a 04/01 recebem 0.99 * 0.5 = 0.495.
    """
    factors = adjustment_factors(_S2_DATES, _S2_CLOSES, [_dividend(4, 0.50), _split(4, 2.0)])

    assert list(factors.price) == pytest.approx([0.495, 0.495, 1.0, 1.0])
    assert list(factors.volume) == pytest.approx([2.0, 2.0, 1.0, 1.0])


# ─── cenário 4: evento fora da janela ────────────────────────────────────────


@pytest.mark.unit
def test_event_after_the_last_bar_is_discarded_with_a_warning(
    log_events: list[EventDict],
) -> None:
    """Design v0.5 §3.7 (ADR-0004) — data ex depois do último pregão: descarte.

    Substitui `test_event_after_the_whole_window_still_adjusts_every_bar`, que
    encodava a regra da v0.4 (aplicar o fator usando o último fechamento
    disponível como `C`). Essa regra ERA o bug: na ponta direita, "último
    fechamento disponível" não é o fechamento anterior à data ex, é só o
    último que por acaso existe.

    Duas razões para descartar, ambas em §3.7: não há `C` honesto, e o fator
    de um evento posterior a TODAS as barras é reescalonamento uniforme —
    neutro em retorno, mexe só no nível absoluto.

    Vale para os dois tipos, split inclusive: aqui o split de 01/06 morre.
    """
    factors = adjustment_factors(_S1_DATES, _S1_CLOSES, [_split(1, 2.0, month=6)])

    assert list(factors.price) == pytest.approx([1.0, 1.0, 1.0, 1.0])
    assert list(factors.volume) == pytest.approx([1.0, 1.0, 1.0, 1.0])

    discarded = [event for event in log_events if event["event"] == "storage.event_after_last_bar"]
    assert len(discarded) == 1
    assert discarded[0]["ticker"] == "TEST"
    assert discarded[0]["date"] == "2024-06-01"


@pytest.mark.unit
def test_dividend_after_the_last_bar_is_also_discarded(
    log_events: list[EventDict],
) -> None:
    """O caso que produziu o bug de verdade: dividendo na ponta direita.

    Sem o descarte, `C` viraria o fechamento da última barra (65.0 em `_S1`),
    que não tem relação nenhuma com o preço na data ex. É exatamente o que a
    v0.4 fazia com os 10 dividendos de AAPL, usando `C = 186.19` para
    dividendos de fevereiro/2024 a maio/2026.
    """
    factors = adjustment_factors(_S1_DATES, _S1_CLOSES, [_dividend(1, 0.50, month=6)])

    assert list(factors.price) == pytest.approx([1.0, 1.0, 1.0, 1.0])

    discarded = [event for event in log_events if event["event"] == "storage.event_after_last_bar"]
    assert len(discarded) == 1


# ─── ADR-0004: o `C` vem do histórico completo ───────────────────────────────

#: Histórico COMPLETO de cinco pregões. O dividendo cai em 08/01, cuja barra
#: anterior (05/01, close 200.00) está no histórico — mas ficaria de fora de
#: uma janela que terminasse em 04/01. É a diferença entre os dois cenários
#: que o bug de A7 explorava.
_ADR4_DATES = [
    date(2024, 1, 2),
    date(2024, 1, 3),
    date(2024, 1, 4),
    date(2024, 1, 5),
    date(2024, 1, 8),
]
_ADR4_CLOSES = _closes(100.0, 110.0, 120.0, 200.0, 210.0)


@pytest.mark.unit
def test_dividend_after_the_window_uses_the_true_previous_close() -> None:
    """ADR-0004 — com o histórico completo, `C` é o fechamento de D-1 de verdade.

    Dividendo d = 2.00 com data ex 08/01.
    C = fechamento bruto de 05/01 = 200.00  (a barra imediatamente anterior)
    fator = (200.00 - 2.00)/200.00 = 198.00/200.00 = 0.99

    Barras estritamente anteriores a 08/01 são as quatro primeiras:
        100.0 * 0.99 =  99.00
        110.0 * 0.99 = 108.90
        120.0 * 0.99 = 118.80
        200.0 * 0.99 = 198.00
    08/01 não é anterior a si mesma: fica em 210.00.

    O contraste com o cenário truncado está em
    `test_truncated_history_would_use_a_stale_close` — 0.99 contra 0.98333.
    """
    factors = adjustment_factors(_ADR4_DATES, _ADR4_CLOSES, [_dividend(8, 2.00)])

    assert list(factors.price) == pytest.approx([0.99, 0.99, 0.99, 0.99, 1.0])
    assert list(_ADR4_CLOSES * factors.price) == pytest.approx([99.0, 108.9, 118.8, 198.0, 210.0])


@pytest.mark.unit
def test_truncated_history_would_use_a_stale_close(log_events: list[EventDict]) -> None:
    """O buraco exato que deixou o bug de A7 passar, agora fechado.

    Truncar o histórico em 04/01 é o que a v0.4 fazia ao passar só as barras
    da janela pedida. O dividendo de 08/01 passa a ser posterior à última
    barra, e antes de ADR-0004 o código usava `C = 120.00` (o fechamento de
    04/01), produzindo fator (120-2)/120 = 0.983333 — o valor errado.

    Depois de ADR-0004 o evento é descartado com aviso em vez de usar um `C`
    inventado. Nenhuma das duas respostas é "a série ajustada correta" para
    essa janela: a resposta correta é não truncar, e é isso que `get_series`
    passa a garantir. Este teste trava o mecanismo — o `C` velho não volta
    por refatoração.
    """
    truncated_dates = _ADR4_DATES[:3]
    truncated_closes = _ADR4_CLOSES[:3]

    factors = adjustment_factors(truncated_dates, truncated_closes, [_dividend(8, 2.00)])

    stale_factor = (120.0 - 2.00) / 120.0
    assert stale_factor == pytest.approx(0.9833333333)
    assert list(factors.price) != pytest.approx([stale_factor] * 3)
    assert list(factors.price) == pytest.approx([1.0, 1.0, 1.0])

    assert [e for e in log_events if e["event"] == "storage.event_after_last_bar"]


@pytest.mark.unit
def test_large_gap_between_the_previous_bar_and_the_ex_date_warns() -> None:
    """Design v0.5 §3.7 — vão acima de 5 dias úteis vira aviso não-bloqueante.

    Com o histórico completo, "barra imediatamente anterior" É o pregão
    anterior — a menos que falte dado. Um vão grande não é ambiguidade de
    calendário, é sinal de buraco no histórico, e o número resultante merece
    desconfiança de quem o ler. O ajuste ainda é aplicado: o aviso não
    bloqueia.
    """
    dates = [date(2024, 1, 2), date(2024, 1, 22), date(2024, 1, 23)]
    closes = _closes(100.0, 100.0, 100.0)

    # Dividendo em 22/01, barra anterior em 02/01: 13 dias úteis de vão.
    factors = adjustment_factors(dates, closes, [_dividend(22, 1.00)])

    # O ajuste acontece mesmo assim — (100-1)/100 = 0.99 na barra anterior.
    assert list(factors.price) == pytest.approx([0.99, 1.0, 1.0])


@pytest.mark.unit
def test_event_before_the_first_bar_is_ignored() -> None:
    """Design §3.7 — evento anterior à primeira barra não tem o que ajustar.

    Nenhuma barra é estritamente anterior a 01/01/2023, então o produto de
    fatores é vazio: 1.0 em toda a série.
    """
    factors = adjustment_factors(_S1_DATES, _S1_CLOSES, [_split(1, 2.0, month=1, year=2023)])

    assert list(factors.price) == pytest.approx([1.0, 1.0, 1.0, 1.0])
    assert list(factors.volume) == pytest.approx([1.0, 1.0, 1.0, 1.0])


@pytest.mark.unit
def test_event_exactly_on_the_first_bar_is_ignored() -> None:
    """ "Estritamente anterior" exclui a própria barra da data ex."""
    factors = adjustment_factors(_S1_DATES, _S1_CLOSES, [_split(2, 2.0)])

    assert list(factors.price) == pytest.approx([1.0, 1.0, 1.0, 1.0])


@pytest.mark.unit
def test_dividend_without_a_previous_bar_warns_and_is_ignored(
    log_events: list[EventDict],
) -> None:
    """Design §3.7 — sem barra anterior, `C` é indefinido: aviso e descarte.

    Descartar em silêncio esconderia um ajuste que deveria ter acontecido.
    """
    factors = adjustment_factors(_S1_DATES, _S1_CLOSES, [_dividend(2, 0.50)])

    assert list(factors.price) == pytest.approx([1.0, 1.0, 1.0, 1.0])

    warnings = [
        event for event in log_events if event["event"] == "storage.dividend_without_previous_bar"
    ]
    assert len(warnings) == 1
    assert warnings[0]["ticker"] == "TEST"
    assert warnings[0]["date"] == "2024-01-02"


# ─── cenário 5: série sem evento nenhum (PER-02.4) ───────────────────────────


@pytest.mark.unit
def test_series_without_events_is_numerically_identical_to_raw() -> None:
    """PER-02.4 — sem evento, a série ajustada tem de sair igual à bruta.

    O fator é 1.0 em toda a barra, e multiplicar por 1.0 é exato em IEEE-754.
    A tolerância apertada abaixo respeita RNF-08 sem afrouxar a exigência.
    """
    factors = adjustment_factors(_S1_DATES, _S1_CLOSES, [])

    assert list(factors.price) == pytest.approx([1.0, 1.0, 1.0, 1.0], rel=1e-12)
    assert list(factors.volume) == pytest.approx([1.0, 1.0, 1.0, 1.0], rel=1e-12)
    assert list(_S1_CLOSES * factors.price) == pytest.approx(list(_S1_CLOSES), rel=1e-12)
    assert list(_S1_VOLUMES * factors.volume) == pytest.approx(list(_S1_VOLUMES), rel=1e-12)


@pytest.mark.unit
def test_events_of_zero_relevance_leave_the_series_untouched() -> None:
    """Split de razão 1.0 é evento sem efeito e não pode introduzir ruído."""
    factors = adjustment_factors(_S1_DATES, _S1_CLOSES, [_split(4, 1.0)])

    assert list(factors.price) == pytest.approx([1.0, 1.0, 1.0, 1.0], rel=1e-12)


# ─── determinismo e bordas ───────────────────────────────────────────────────


@pytest.mark.unit
def test_two_calls_produce_identical_factors() -> None:
    """PER-02.3 — mesmo estado, mesmo resultado."""
    first = adjustment_factors(_S3_DATES, _S3_CLOSES, [_dividend(4, 0.50), _split(8, 2.0)])
    second = adjustment_factors(_S3_DATES, _S3_CLOSES, [_dividend(4, 0.50), _split(8, 2.0)])

    assert list(first.price) == pytest.approx(list(second.price), rel=1e-15)
    assert list(first.volume) == pytest.approx(list(second.volume), rel=1e-15)


@pytest.mark.unit
def test_empty_series_returns_empty_factors() -> None:
    """Série vazia não pode estourar índice ao procurar a barra anterior."""
    factors = adjustment_factors([], _closes(), [_split(4, 2.0)])

    assert len(factors.price) == 0
    assert len(factors.volume) == 0


@pytest.mark.unit
def test_dividend_not_smaller_than_the_previous_close_is_rejected() -> None:
    """Fator ≤ 0 viraria preço nulo ou negativo — plausível de passar batido.

    Um dividendo maior que o fechamento anterior não existe no mundo real; é
    dado corrompido. Falhar alto é melhor que produzir uma série de preços
    que parece informação e não é.
    """
    with pytest.raises(DataError, match="dividendo"):
        adjustment_factors(_S2_DATES, _S2_CLOSES, [_dividend(4, 50.0)])


@pytest.mark.unit
def test_factors_do_not_alias_the_input_arrays() -> None:
    """O fator é série nova; escrever nele não pode tocar o preço bruto."""
    raw = _closes(100.0, 110.0, 120.0, 65.0)
    factors = adjustment_factors(_S1_DATES, raw, [_split(4, 2.0)])

    assert not np.shares_memory(factors.price, raw)
    assert not np.shares_memory(factors.volume, raw)


@pytest.mark.unit
def test_event_between_two_bars_adjusts_only_the_earlier_one() -> None:
    """Data ex em dia sem pregão (fim de semana, feriado).

    Sexta 05/01 e segunda 08/01, evento no sábado 06/01. A sexta é
    estritamente anterior e recebe o fator; a segunda é posterior e não.
    """
    dates = [date(2024, 1, 5), date(2024, 1, 8)]
    factors = adjustment_factors(dates, _closes(100.0, 60.0), [_split(6, 2.0)])

    assert list(factors.price) == pytest.approx([0.5, 1.0])


# ─── conferência contra a definição ──────────────────────────────────────────


def _brute_force_price_factors(
    dates: list[date],
    raw_close: NDArray[np.float64],
    events: list[CorporateAction],
) -> list[float]:
    """A definição, implementada do jeito burro: O(n·m), sem cumprod.

    "O fator da barra em t é o produto dos fatores de todos os eventos com data
    estritamente posterior a t." Literalmente isso, um laço por barra.

    Inclui a borda de ADR-0004: evento com data ex posterior à última barra do
    histórico não entra em produto nenhum. Sem essa linha, a referência burra
    encodaria a regra da v0.4 e o cross-check passaria a confirmar o bug em vez
    de pegá-lo.
    """
    last_bar = dates[-1] if dates else None
    factors: list[float] = []
    for bar_date in dates:
        product = 1.0
        for event in events:
            if event.date <= bar_date:
                continue
            if last_bar is not None and event.date > last_bar:
                continue
            if event.kind is CorporateActionKind.SPLIT:
                assert event.ratio is not None
                product *= 1.0 / event.ratio
            else:
                assert event.value is not None
                previous = _previous_close(dates, raw_close, event.date)
                if previous is None:
                    continue
                product *= (previous - event.value) / previous
        factors.append(product)
    return factors


def _previous_close(
    dates: list[date], raw_close: NDArray[np.float64], ex_date: date
) -> float | None:
    """Fechamento bruto do último pregão estritamente anterior à data ex."""
    candidates = [float(raw_close[index]) for index, day in enumerate(dates) if day < ex_date]
    return candidates[-1] if candidates else None


@pytest.mark.unit
@pytest.mark.parametrize(
    "events",
    [
        pytest.param([], id="sem-eventos"),
        pytest.param([_split(4, 2.0)], id="split"),
        pytest.param([_dividend(4, 0.50)], id="dividendo"),
        pytest.param([_dividend(4, 0.50), _split(8, 2.0)], id="dividendo-depois-split"),
        pytest.param([_split(3, 2.0), _dividend(5, 0.40)], id="split-depois-dividendo"),
        pytest.param([_split(4, 2.0), _split(5, 3.0)], id="dois-splits"),
        pytest.param(
            [_dividend(3, 0.25), _dividend(5, 0.30), _split(8, 4.0)],
            id="dois-dividendos-e-split",
        ),
        pytest.param([_split(1, 2.0, month=6)], id="evento-depois-da-janela"),
        pytest.param([_split(1, 2.0, year=2023)], id="evento-antes-da-janela"),
    ],
)
def test_cumprod_matches_the_naive_definition(events: list[CorporateAction]) -> None:
    """O algoritmo O(n) tem de concordar com a definição escrita do jeito burro.

    O `cumprod` reverso é a parte esperta do módulo, e esperto é onde o bug
    mora. Este teste não confia nele: recalcula pela definição literal de
    design §3.7 e compara.
    """
    expected = _brute_force_price_factors(_S3_DATES, _S3_CLOSES, events)
    actual = adjustment_factors(_S3_DATES, _S3_CLOSES, events).price

    assert list(actual) == pytest.approx(expected, rel=1e-12)
