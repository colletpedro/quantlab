"""T02 — liquidez (design §3.3/§3.8, RF-SLP-03).

Fixtures de papel com derivação auditável (RNF-03): volumes 1..25 e o
resultado de cada janela é calculado à mão no teste — se o código "usar
barra futura", o número deixa de bater.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from quantlab.engine.liquidity import adv, participation_cap
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries


def _series(volumes: list[float], ticker: str = "AAA4") -> PriceSeries:
    """Série sintética mínima: preços constantes, volumes dados (RNF-03)."""
    count = len(volumes)
    prices = np.full(count, 10.0)
    dates: list[date] = [date(2024, 1, 1 + i) for i in range(count)]
    return PriceSeries(
        ticker=ticker,
        dates=np.array(dates, dtype=object),
        open=prices.copy(),
        high=prices.copy(),
        low=prices.copy(),
        close=prices.copy(),
        volume=np.array(volumes, dtype=np.float64),
        adjusted=True,
        hash="test-hash",
    )


# ─── janela de ADV do próprio ativo (CA-03.1/Q3) ────────────────────────────


@pytest.mark.unit
def test_adv_window_is_20_sessions_of_own_asset() -> None:
    """SLP-03.1 — média dos 20 pregões do PRÓPRIO ativo terminando em `i`.

    Derivação auditável: volumes 1..25.
    - em i=24: janela [5, 24] = volumes 6..25 ⇒ média (6+25)/2 = 15.5.
    - em i=19: janela [0, 19] = volumes 1..20 ⇒ média (1+20)/2 = 10.5.
    Se a barra 20 (futura em relação a i=19) vazasse, a média seria 11.0.
    """
    series = _series([float(v) for v in range(1, 26)])

    assert adv(series, 24) == pytest.approx(15.5)
    assert adv(series, 19) == pytest.approx(10.5)

    # O próprio ativo: outra série com perfil de volume totalmente distinto
    # não entra no número de AAA4 — a função só enxerga a série recebida.
    other = _series([1000.0 + v for v in range(1, 26)], ticker="BBBB3")
    assert adv(series, 24) == pytest.approx(15.5)
    assert adv(other, 24) == pytest.approx(1015.5)

    # Janela customizada: 5 pregões terminando em i=24 ⇒ volumes 21..25 ⇒ 23.0.
    assert adv(series, 24, window=5) == pytest.approx(23.0)


@pytest.mark.unit
def test_adv_insufficient_history_returns_none() -> None:
    """SLP-03.2 — None sse a janela pedida excede o histórico até `i`."""
    series = _series([float(v) for v in range(1, 11)])  # 10 barras

    # Com 10 barras e janela 20, NENHUMA barra tem histórico suficiente.
    assert adv(series, 9) is None

    # Janela 10: exatamente no limite na última barra ⇒ valor; antes ⇒ None.
    assert adv(series, 9, window=10) == pytest.approx(5.5)
    assert adv(series, 8, window=10) is None

    # Janela 1: a própria barra basta, em qualquer posição.
    assert adv(series, 0, window=1) == pytest.approx(1.0)


@pytest.mark.unit
def test_adv_domain_errors_raise_engine_error() -> None:
    """Pré-condições §3.8 — índice fora da série e janela < 1 são EngineError."""
    series = _series([float(v) for v in range(1, 6)])

    with pytest.raises(EngineError):
        adv(series, 5)  # i == len
    with pytest.raises(EngineError):
        adv(series, -1)  # i negativo
    with pytest.raises(EngineError):
        adv(series, 0, window=0)  # janela nula

    # Série vazia: nenhum índice é válido.
    empty = _series([])
    with pytest.raises(EngineError):
        adv(empty, 0)


# ─── cap de participação em entradas (CA-03.3/03.4/03.5) ─────────────────────


@pytest.mark.unit
def test_cap_applies_to_entries_only_and_subshare_cancels() -> None:
    """SLP-03.3/03.5 — teto floor(cap x ADV); sub-parte inteira ⇒ 0 (sem ordem).

    O chamador (broker, T06) é quem decide não gerar a ordem quando o
    resultado é 0 e logar o evento; aqui o contrato é o valor devolvido.
    """
    adv_value = 10_000.0

    # qty > cap x ADV (1000) ⇒ reduzido ao teto exato.
    assert participation_cap(5_000, adv_value) == 1_000
    # qty ≤ teto ⇒ intacto (nunca devolve mais do que o pedido).
    assert participation_cap(999, adv_value) == 999
    assert participation_cap(1_000, adv_value) == 1_000

    # Teto fracionário arredonda para baixo: 10% de 1_005 = 100.5 ⇒ 100.
    assert participation_cap(500, 1_005.0) == 100

    # cap x ADV < 1 ⇒ 0 — a ordem não pode ser formada (SLP-03.5).
    assert participation_cap(5, 9.0) == 0
    assert participation_cap(1, 0.5) == 0


@pytest.mark.unit
def test_cap_monotonic_in_qty() -> None:
    """Monotonicidade — pedir mais nunca devolve um teto menor."""
    adv_value = 10_000.0
    previous = 0
    for qty in range(1, 12_000, 1_337):
        capped = participation_cap(qty, adv_value)
        assert capped >= previous, f"cap quebrou monotonicidade em qty={qty}"
        previous = capped
    assert participation_cap(11_000, adv_value) == 1_000


@pytest.mark.unit
def test_cap_domain_errors_raise_engine_error() -> None:
    """Pré-condições §3.8 — qty < 1, adv ≤ 0 e cap fora de (0, 1] são EngineError."""
    with pytest.raises(EngineError):
        participation_cap(0, 10_000.0)
    with pytest.raises(EngineError):
        participation_cap(1, 0.0)
    with pytest.raises(EngineError):
        participation_cap(1, -5.0)
    with pytest.raises(EngineError):
        participation_cap(1, 10_000.0, cap=0.0)
    with pytest.raises(EngineError):
        participation_cap(1, 10_000.0, cap=1.5)
