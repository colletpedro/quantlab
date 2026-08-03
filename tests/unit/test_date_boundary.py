"""A3 — fronteira `date` ⇄ `datetime` (RNF-07, design §3.6).

Testes unitários: as funções são puras e não tocam banco.

O ponto destes testes não é que a conversão "funciona" — é que ela é
**estável em datas que costumam quebrar conversão**: virada de ano, virada de
mês, ano bissexto e, principalmente, os dias de mudança de horário de verão.
Se qualquer horário local vazasse para a conversão, um desses casos deslocaria
a data em um dia.
"""

from datetime import UTC, date, datetime, timedelta, timezone
from itertools import pairwise

import pytest

from quantlab.storage.repository import from_bson_date, to_bson_date

#: Datas escolhidas por serem armadilha, não por serem representativas.
_TRICKY_DATES = [
    pytest.param(date(2023, 12, 31), id="ultimo-dia-do-ano"),
    pytest.param(date(2024, 1, 1), id="primeiro-dia-do-ano"),
    pytest.param(date(2024, 2, 29), id="bissexto"),
    pytest.param(date(2024, 3, 10), id="inicio-horario-verao-eua"),
    pytest.param(date(2024, 11, 3), id="fim-horario-verao-eua"),
    pytest.param(date(2024, 3, 31), id="inicio-horario-verao-europa"),
    pytest.param(date(2024, 10, 27), id="fim-horario-verao-europa"),
    pytest.param(date(2024, 6, 30), id="dia-comum"),
]


@pytest.mark.unit
@pytest.mark.parametrize("value", _TRICKY_DATES)
def test_round_trip_preserves_the_calendar_day(value: date) -> None:
    """Ida e volta devolve exatamente o mesmo dia."""
    assert from_bson_date(to_bson_date(value)) == value


@pytest.mark.unit
@pytest.mark.parametrize("value", _TRICKY_DATES)
def test_stored_instant_is_utc_midnight(value: date) -> None:
    """O instante gravado é meia-noite UTC — design §3.1."""
    stored = to_bson_date(value)
    assert (stored.hour, stored.minute, stored.second, stored.microsecond) == (0, 0, 0, 0)
    assert stored.tzinfo is not None
    assert stored.utcoffset() == timedelta(0)


@pytest.mark.unit
@pytest.mark.parametrize("value", _TRICKY_DATES)
def test_naive_datetime_from_driver_round_trips(value: date) -> None:
    """O driver roda com `tz_aware=False`; naive em UTC também precisa voltar certo."""
    naive = datetime(value.year, value.month, value.day)
    assert from_bson_date(naive) == value


@pytest.mark.unit
def test_aware_non_utc_instant_is_normalized_before_becoming_a_day() -> None:
    """Instante aware em outro fuso vira o dia UTC correspondente, não o local.

    23:30 de 14/01 em UTC-5 é 04:30 de 15/01 em UTC. A conversão tem que
    devolver 15, não 14 — é esse deslocamento de um dia que o teste protege.
    """
    aware = datetime(2024, 1, 14, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    assert from_bson_date(aware) == date(2024, 1, 15)


@pytest.mark.unit
def test_conversion_returns_plain_date_not_datetime() -> None:
    """`datetime` é subclasse de `date`; o retorno não pode ser um deles disfarçado."""
    result = from_bson_date(to_bson_date(date(2024, 5, 17)))
    assert type(result) is date


@pytest.mark.unit
def test_consecutive_days_stay_one_day_apart() -> None:
    """Sem salto nem colisão ao atravessar a mudança de horário de verão."""
    start = date(2024, 3, 9)
    instants = [to_bson_date(start + timedelta(days=offset)) for offset in range(4)]
    gaps = {(later - earlier) for earlier, later in pairwise(instants)}
    assert gaps == {timedelta(days=1)}


@pytest.mark.unit
def test_utc_is_the_anchor_regardless_of_machine_timezone() -> None:
    """A conversão não consulta o fuso da máquina em momento nenhum."""
    stored = to_bson_date(date(2024, 7, 4))
    assert stored == datetime(2024, 7, 4, tzinfo=UTC)
