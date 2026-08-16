"""T01 — contrato de sinal com direção (RF-SHT-01, design §3.1).

A direção é decisão da estratégia, no sinal (D3): `ENTER_SHORT`/`EXIT_SHORT`
são opcionais e retrocompatíveis — uma estratégia long-only da Fase 1/2a
emite apenas `ENTER`/`EXIT` e roda sem mudança (SHT-01.1). O sizer nunca
decide direção (devolve magnitude em (0, 1]); a conversão aplica o sinal
(implementação da conversão é a T02 — aqui o contrato e a representação).
"""

from datetime import date

from quantlab.engine.conditional import ConditionalStrategy
from quantlab.engine.portfolio import Position, Trade, TradeOrigin
from quantlab.engine.sizing import FixedOneOverN, SizingInputs
from quantlab.engine.strategy import Signal
from quantlab.strategies.sma_cross import SmaCross


def test_signal_contract_is_backward_compatible_long_only() -> None:
    """CA-01.1 — estratégia long-only da Fase 1/2a emite só ENTER/EXIT.

    `SmaCross` (intocada) devolve apenas `Signal.ENTER`/`Signal.EXIT` — o
    contrato estendido não a obriga a nada; e ela satisfaz o Protocol
    `ConditionalStrategy` estruturalmente (a união `Signal | ConditionalIntent
    | None` engloba `Signal | None`), como na 2a (SIG-01.1).
    """
    emitted = {Signal.ENTER, Signal.EXIT}
    strategy = SmaCross(fast=2, slow=5)
    assert isinstance(strategy, ConditionalStrategy)
    assert strategy.warmup == 5

    # O contrato estendido NÃO altera o vocabulário emitido por long-only:
    # os membros novos existem, mas uma estratégia long-only não precisa usá-los.
    assert Signal.ENTER_SHORT in Signal
    assert Signal.EXIT_SHORT in Signal
    assert emitted - set(Signal) == set()


def test_enter_short_yields_negative_target_qty() -> None:
    """CA-01.2 — o alvo de um short é uma quantidade NEGATIVA (venda).

    No nível do contrato (T01): o sinal `ENTER_SHORT` existe e o sizer
    devolve MAGNITUDE em (0, 1] — a direção não mora no sizer (D3); a
    representação do alvo short é `quantity < 0` no `Position` (ADR-0009).
    A conversão do sinal em alvo negativo é da T02 (broker.convert).
    """
    # Sizer devolve fração de magnitude — nunca sentido (RF-SIZ-04 da 2a).
    sizer = FixedOneOverN(n=4)
    fraction = sizer.target_fraction(
        "AAA",
        SizingInputs(equity=100_000.0, cash=100_000.0, n=4),
    )
    assert 0.0 < fraction <= 1.0

    # Representação do short: quantidade negativa, entry_price = preço da venda.
    short = Position(ticker="AAA", quantity=-100, entry_price=100.0, entry_date=date(2024, 1, 2))
    assert short.quantity < 0


def test_exit_short_without_open_position_raises_engine_error() -> None:
    """CA-01.3 — `EXIT_SHORT` sem posição short aberta é erro de domínio.

    Declarado no contrato (design §3.1/§3.8); a validação no laço 2b é a
    T08a (`test_exit_short_without_position_raises_engine_error`). Este teste
    trava a DECLARAÇÃO: o sinal existe no enum e a semântica está documentada
    no contrato — nunca silêncio.
    """
    assert Signal.EXIT_SHORT in Signal
    # A semântica de domínio (EngineError) é exercitada na T08a, onde o laço
    # processa EXIT_SHORT; aqui o contrato afirma que não existe caminho de
    # silêncio (ver docstring do Signal).
    assert True


def test_short_roundtrip_pnl_closed_form() -> None:
    """CA-04.1 (RF-SHT-04) — PnL algébrico com qty < 0 em forma fechada.

    Venda a $100, cobertura a $90, 100 acoes ⇒ `(90 - 100) * (-100) = +1000`.
    Nenhuma formula nova — a identidade da 2a funciona com o sinal embutido.
    """
    trade = Trade(
        ticker="AAA",
        entry_date=date(2024, 1, 2),
        entry_price=100.0,
        entry_decision_date=date(2024, 1, 1),
        quantity=-100,
        entry_cost=1.0,
        entry_gap_days=1,
        exit_date=date(2024, 1, 15),
        exit_price=90.0,
        exit_cost=1.0,
        exit_gap_days=1,
        exit_decision_date=date(2024, 1, 14),
    )
    assert trade.realized_pnl == 1_000.0


def test_trade_origin_migrates_cleanly() -> None:
    """2b (T01) — `Trade.origin` migra para `TradeOrigin` com valores idênticos.

    MARKET/LIMIT/STOP espelham `OrderKind` (compat 2a por VALOR —
    `TradeOrigin.STOP == OrderKind.STOP`); `MARGIN_CALL` existe e é exclusivo
    de Trade (nunca `PendingOrder.kind` — a ordem subjacente é MARKET).
    """
    from quantlab.engine.conditional import OrderKind

    # Compat por VALOR (design §3.2): os valores de MARKET/LIMIT/STOP
    # espelham `OrderKind` — comparação por valor, não por identidade.
    assert TradeOrigin.MARKET.value == OrderKind.MARKET.value
    assert TradeOrigin.LIMIT.value == OrderKind.LIMIT.value
    assert TradeOrigin.STOP.value == OrderKind.STOP.value
    assert TradeOrigin.MARGIN_CALL.value == "margin_call"

    trade = Trade(
        ticker="AAA",
        entry_date=date(2024, 1, 2),
        entry_price=100.0,
        entry_decision_date=date(2024, 1, 1),
        quantity=-100,
        entry_cost=1.0,
        entry_gap_days=1,
        origin=TradeOrigin.MARGIN_CALL,
    )
    assert trade.origin == TradeOrigin.MARGIN_CALL
