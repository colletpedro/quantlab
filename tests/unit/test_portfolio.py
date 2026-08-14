"""C3 — `Trade`, `Position`, `Portfolio` (ENG-04.1, ENG-04.4, decisão D4).

As invariantes de ENG-04.4 são o assunto principal aqui. Elas existem para
pegar **erro de programação**, não condição de mercado: num backtest
long-only sem alavancagem (premissas 2 e 3) não há caminho legítimo para
caixa negativo nem para posição não positiva. Se apareceu, o cálculo de
tamanho ignorou o custo — o erro que design §4.4 nomeia.

Testar o guard é diferente de testar o caminho feliz: o guard só serve se
alguém já provou que ele dispara.
"""

from datetime import date

import pytest

from quantlab.engine.broker import Broker, ConvertedOrder
from quantlab.engine.conditional import OrderKind
from quantlab.engine.portfolio import Portfolio, Position, Trade
from quantlab.exceptions import EngineError

_TICKER = "TEST"
_ENTRY = date(2024, 1, 2)
_EXIT = date(2024, 1, 10)


def _converted(
    kind: OrderKind = OrderKind.MARKET, *, qty: int = 10, seq: int = 1
) -> ConvertedOrder:
    return ConvertedOrder(
        ticker=_TICKER,
        kind=kind,
        limit=None,
        stop=None,
        qty=qty,
        ref_price=100.0,
        decision_date=date(2024, 1, 1),
        intent_seq=seq,
        cut_reason=None,
        est_cost=0.0,
        bracket=False,
    )


def _open_trade(quantity: int = 10, entry_price: float = 100.0) -> Trade:
    return Trade(
        ticker=_TICKER,
        entry_date=_ENTRY,
        entry_price=entry_price,
        entry_decision_date=date(2024, 1, 1),
        quantity=quantity,
        entry_cost=1.0,
        entry_gap_days=1,
    )


# ─── Position ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_position_market_value_is_quantity_times_price() -> None:
    position = Position(ticker=_TICKER, quantity=10, entry_price=100.0, entry_date=_ENTRY)
    assert position.market_value(130.0) == pytest.approx(1_300.0)


@pytest.mark.unit
@pytest.mark.parametrize("quantity", [0, -1, -100])
def test_position_with_non_positive_quantity_is_rejected(quantity: int) -> None:
    """Long-only (premissa 2): posição existe com quantidade > 0, ou não existe.

    Quantidade zero é rejeitada junto com a negativa de propósito — uma
    posição de zero ações não é uma posição, é lixo no dicionário esperando
    virar divisão por zero em `analytics`.
    """
    with pytest.raises(EngineError, match="long-only"):
        Position(ticker=_TICKER, quantity=quantity, entry_price=100.0, entry_date=_ENTRY)


# ─── Trade ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_open_trade_has_no_realized_pnl() -> None:
    """Posição aberta não realizou nada — o PnL dela é não realizado."""
    trade = _open_trade()
    assert trade.is_open
    assert trade.realized_pnl == pytest.approx(0.0)


@pytest.mark.unit
def test_closed_trade_realized_pnl_is_gross_of_costs() -> None:
    """Design §4.6 — BRUTO. (120 - 100) * 10 = 200.00, com 3.00 de custo à parte."""
    closed = Trade(
        ticker=_TICKER,
        entry_date=_ENTRY,
        entry_price=100.0,
        entry_decision_date=date(2024, 1, 1),
        quantity=10,
        entry_cost=1.0,
        entry_gap_days=1,
        exit_date=_EXIT,
        exit_price=120.0,
        exit_cost=2.0,
        exit_gap_days=1,
        exit_decision_date=date(2024, 1, 9),
    )

    assert closed.is_open is False
    assert closed.realized_pnl == pytest.approx(200.0)
    assert closed.total_cost == pytest.approx(3.0)


@pytest.mark.unit
def test_losing_trade_has_negative_realized_pnl() -> None:
    """Um número ruim é um resultado: perda é reportada como perda."""
    closed = Trade(
        ticker=_TICKER,
        entry_date=_ENTRY,
        entry_price=100.0,
        entry_decision_date=date(2024, 1, 1),
        quantity=10,
        entry_cost=1.0,
        entry_gap_days=1,
        exit_date=_EXIT,
        exit_price=80.0,
        exit_cost=1.0,
        exit_gap_days=1,
    )

    assert closed.realized_pnl == pytest.approx(-200.0)


# ─── Portfolio: ENG-04.1 ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_equity_is_cash_when_there_is_no_position() -> None:
    portfolio = Portfolio(cash=1_000.0)
    assert portfolio.equity({}) == pytest.approx(1_000.0)


@pytest.mark.unit
def test_equity_adds_the_position_marked_at_the_given_price() -> None:
    """ENG-04.1 — equity = caixa + posição * preço."""
    portfolio = Portfolio(cash=500.0)
    portfolio.positions[_TICKER] = Position(
        ticker=_TICKER, quantity=10, entry_price=100.0, entry_date=_ENTRY
    )

    assert portfolio.equity({_TICKER: 130.0}) == pytest.approx(500.0 + 1_300.0)


@pytest.mark.unit
def test_equity_sums_across_several_positions() -> None:
    """Decisão D4 — N posições modeladas desde já, ainda que N=1 na Fase 1.

    Exercitar N=2 aqui é o que prova que a estrutura não assume ativo único;
    sem isto, a Fase 2 descobriria a suposição escondida do jeito caro.
    """
    portfolio = Portfolio(cash=100.0)
    portfolio.positions["AAA"] = Position(
        ticker="AAA", quantity=10, entry_price=10.0, entry_date=_ENTRY
    )
    portfolio.positions["BBB"] = Position(
        ticker="BBB", quantity=5, entry_price=20.0, entry_date=_ENTRY
    )

    equity = portfolio.equity({"AAA": 12.0, "BBB": 30.0})

    assert equity == pytest.approx(100.0 + 120.0 + 150.0)


@pytest.mark.unit
def test_initial_cash_is_remembered_for_the_reconciliation() -> None:
    """Design §4.6 precisa do capital inicial mesmo depois do caixa mudar."""
    portfolio = Portfolio(cash=1_000.0)
    portfolio.cash = 42.0

    assert portfolio.initial_cash == pytest.approx(1_000.0)


@pytest.mark.unit
def test_negative_initial_capital_is_rejected() -> None:
    with pytest.raises(EngineError, match="Capital inicial negativo"):
        Portfolio(cash=-1.0)


# ─── Portfolio: ENG-04.4, os guards ──────────────────────────────────────────


@pytest.mark.unit
def test_invariants_pass_on_a_healthy_portfolio() -> None:
    portfolio = Portfolio(cash=100.0)
    portfolio.positions[_TICKER] = Position(
        ticker=_TICKER, quantity=1, entry_price=10.0, entry_date=_ENTRY
    )

    portfolio.check_invariants()


@pytest.mark.unit
def test_negative_cash_raises_and_names_the_likely_cause() -> None:
    """ENG-04.4 — o guard que design §4.4 pede, com a mensagem que ajuda.

    A mensagem cita o custo no cálculo da quantidade de propósito: é a causa
    esmagadoramente mais provável, e dizer isso poupa a quem depura a
    primeira meia hora.
    """
    portfolio = Portfolio(cash=100.0)
    portfolio.cash = -0.01

    with pytest.raises(EngineError, match="custo"):
        portfolio.check_invariants()


@pytest.mark.unit
def test_invariants_catch_a_position_corrupted_after_construction() -> None:
    """`Position` barra na construção; o guard cobre mutação posterior.

    Os dois juntos são o que fecha ENG-04.4: nem nasce inválida, nem fica.
    """
    portfolio = Portfolio(cash=100.0)
    portfolio.positions[_TICKER] = Position(
        ticker=_TICKER, quantity=1, entry_price=10.0, entry_date=_ENTRY
    )
    # `object.__setattr__` fura o `frozen` — é o que uma refatoração
    # desastrada faria por acidente.
    object.__setattr__(portfolio.positions[_TICKER], "quantity", 0)

    with pytest.raises(EngineError, match="não positiva"):
        portfolio.check_invariants()


# ─── Portfolio: trade aberto ─────────────────────────────────────────────────


@pytest.mark.unit
def test_open_trade_is_none_when_there_is_none() -> None:
    assert Portfolio(cash=100.0).open_trade is None


@pytest.mark.unit
def test_open_trade_finds_the_one_still_open() -> None:
    portfolio = Portfolio(cash=100.0)
    closed = Trade(
        ticker=_TICKER,
        entry_date=_ENTRY,
        entry_price=100.0,
        entry_decision_date=date(2024, 1, 1),
        quantity=10,
        entry_cost=1.0,
        entry_gap_days=1,
        exit_date=_EXIT,
        exit_price=110.0,
        exit_cost=1.0,
        exit_gap_days=1,
    )
    still_open = _open_trade(quantity=5)
    portfolio.trades.extend([closed, still_open])

    assert portfolio.open_trade == still_open


@pytest.mark.unit
def test_open_trade_is_none_when_every_trade_is_closed() -> None:
    portfolio = Portfolio(cash=100.0)
    portfolio.trades.append(
        Trade(
            ticker=_TICKER,
            entry_date=_ENTRY,
            entry_price=100.0,
            entry_decision_date=date(2024, 1, 1),
            quantity=10,
            entry_cost=1.0,
            entry_gap_days=1,
            exit_date=_EXIT,
            exit_price=110.0,
            exit_cost=1.0,
            exit_gap_days=1,
        )
    )

    assert portfolio.open_trade is None


# ─── Portfolio: 2a T10 — multi-ativo (POR-01.1, POR-02.2, POR-04.1, POR-04.3) ─


@pytest.mark.unit
def test_shared_cash_single_pool() -> None:
    """POR-01.1 — um caixa ÚNICO compartilhado (nada de caixa por ativo):
    BBB enxerga o pool já debitado pela entrada de AAA, e o crédito de
    fechar AAA reabastece o MESMO pool que BBB depois usa."""
    broker = Broker()
    portfolio = Portfolio(cash=100_000.0)
    first = broker.buy(
        portfolio, ticker="AAA", price=100.0, execution_date=_ENTRY, decision_date=date(2024, 1, 1)
    )
    assert first is not None
    assert portfolio.cash == pytest.approx(100_000.0 - 100.0 * first.quantity - first.entry_cost)
    drained = portfolio.cash

    # AAA foi all-in (Fase 1): o pool está drenado — BBB não cabe 1 ação a 200.
    assert (
        broker.buy(
            portfolio,
            ticker="BBB",
            price=200.0,
            execution_date=_ENTRY,
            decision_date=date(2024, 1, 1),
        )
        is None
    )
    assert portfolio.cash == pytest.approx(drained)  # tentativa sem efeito

    # Fechar AAA credita o MESMO pool; BBB então preenche.
    closed = broker.sell(
        portfolio, ticker="AAA", price=110.0, execution_date=_EXIT, decision_date=date(2024, 1, 9)
    )
    assert closed is not None
    second = broker.buy(
        portfolio, ticker="BBB", price=200.0, execution_date=_ENTRY, decision_date=date(2024, 1, 1)
    )
    assert second is not None
    assert portfolio.cash == pytest.approx(
        drained
        + 110.0 * closed.quantity
        - closed.exit_cost
        - 200.0 * second.quantity
        - second.entry_cost
    )


@pytest.mark.unit
def test_market_to_market_with_last_known_close() -> None:
    """POR-02.2 — marks atualizados pelo último close conhecido; o último
    vence, e ativo sem barra na data mantém o mark anterior (aqui: coberto
    pelo mapa que o laço passa com o last_known)."""
    portfolio = Portfolio(cash=500.0)
    portfolio.positions["AAA"] = Position(
        ticker="AAA", quantity=10, entry_price=100.0, entry_date=_ENTRY
    )
    portfolio.positions["BBB"] = Position(
        ticker="BBB", quantity=5, entry_price=200.0, entry_date=_ENTRY
    )

    portfolio.market_to_market({"AAA": 110.0, "BBB": 205.0})
    portfolio.market_to_market({"AAA": 112.0, "BBB": 205.0})  # AAA tem barra nova

    assert portfolio.marks == {"AAA": 112.0, "BBB": 205.0}
    # Identidade POR-04.1 com os últimos closes conhecidos.
    assert portfolio.equity() == pytest.approx(500.0 + 10 * 112.0 + 5 * 205.0)


@pytest.mark.unit
def test_market_to_market_missing_position_raises() -> None:
    """Pré-condição (§3.8) — o mapa tem que cobrir TODOS os ativos com
    posição; faltou um, a equity silenciosamente ignoraria uma posição."""
    portfolio = Portfolio(cash=500.0)
    portfolio.positions["AAA"] = Position(
        ticker="AAA", quantity=10, entry_price=100.0, entry_date=_ENTRY
    )

    with pytest.raises(EngineError, match="faltou último close"):
        portfolio.market_to_market({"BBB": 205.0})


@pytest.mark.unit
def test_market_to_market_non_positive_close_raises() -> None:
    portfolio = Portfolio(cash=500.0)
    with pytest.raises(EngineError, match="não positivo"):
        portfolio.market_to_market({"AAA": 0.0})


@pytest.mark.unit
def test_equity_identity_multi_asset() -> None:
    """CA-04.1/POR-04.1 — equity = caixa + soma qty_i x último_close_i sobre
    posições múltiplas, derivada de marks (equity() sem argumento)."""
    portfolio = Portfolio(cash=100.0)
    portfolio.positions["AAA"] = Position(
        ticker="AAA", quantity=10, entry_price=10.0, entry_date=_ENTRY
    )
    portfolio.positions["BBB"] = Position(
        ticker="BBB", quantity=5, entry_price=20.0, entry_date=_ENTRY
    )
    portfolio.market_to_market({"AAA": 12.0, "BBB": 30.0})

    # Sem argumento ⇒ marks; com argumento explícito ⇒ Fase 1 preservada.
    assert portfolio.equity() == pytest.approx(100.0 + 120.0 + 150.0)
    assert portfolio.equity({"AAA": 13.0, "BBB": 30.0}) == pytest.approx(100.0 + 130.0 + 150.0)


@pytest.mark.unit
def test_cash_and_quantity_never_negative_multi() -> None:
    """CA-04.3/POR-04.3 — os guards multi-ativo: caixa negativo e posição
    corrompida são erro de programação, com dois ativos abertos."""
    portfolio = Portfolio(cash=100.0)
    portfolio.positions["AAA"] = Position(
        ticker="AAA", quantity=10, entry_price=10.0, entry_date=_ENTRY
    )
    portfolio.positions["BBB"] = Position(
        ticker="BBB", quantity=5, entry_price=20.0, entry_date=_ENTRY
    )

    portfolio.check_invariants()  # saudável

    portfolio.cash = -0.01
    with pytest.raises(EngineError, match="custo"):
        portfolio.check_invariants()
    portfolio.cash = 100.0

    object.__setattr__(portfolio.positions["BBB"], "quantity", 0)
    with pytest.raises(EngineError, match="não positiva"):
        portfolio.check_invariants()


@pytest.mark.unit
def test_k_bounded_by_n() -> None:
    """POR-04.3/SIZ-04.3 — k ≤ N: mais posições abertas que o N do run é
    erro de programação; N < 1 também é erro de domínio."""
    portfolio = Portfolio(cash=100.0)
    portfolio.positions["AAA"] = Position(
        ticker="AAA", quantity=10, entry_price=10.0, entry_date=_ENTRY
    )
    portfolio.positions["BBB"] = Position(
        ticker="BBB", quantity=5, entry_price=20.0, entry_date=_ENTRY
    )

    portfolio.check_invariants(n=2)  # k == N: ok
    with pytest.raises(EngineError, match="excede o N do run"):
        portfolio.check_invariants(n=1)
    with pytest.raises(EngineError, match="N do run inválido"):
        portfolio.check_invariants(n=0)


@pytest.mark.unit
def test_pending_book_composed_into_portfolio() -> None:
    """Emenda T07 — o Portfolio carrega um PendingBook por ativo; place não
    debita caixa (ORD-04.3 — sem reserva)."""
    broker = Broker()
    portfolio = Portfolio(cash=2_000.0)

    broker.place(portfolio.pending, _converted(qty=50))

    pending = portfolio.pending.pending_for(_TICKER)
    assert len(pending) == 1
    assert pending[0].qty == 50
    assert portfolio.cash == pytest.approx(2_000.0)  # nada debitado


@pytest.mark.unit
def test_multi_asset_equity_is_deterministic() -> None:
    """RNF-01 — mesma entrada ⇒ mesma equity, marcas e invariantes."""

    def run_once() -> tuple[float, dict[str, float], int]:
        portfolio = Portfolio(cash=100.0)
        portfolio.positions["AAA"] = Position(
            ticker="AAA", quantity=10, entry_price=10.0, entry_date=_ENTRY
        )
        portfolio.market_to_market({"AAA": 12.0, "BBB": 30.0})
        portfolio.check_invariants(n=2)
        return portfolio.equity(), dict(portfolio.marks), len(portfolio.trades)

    first = run_once()
    second = run_once()
    assert first == second
