"""`Broker` e modelo de custo — C4, design §4.4.

O broker é quem transforma **intenção** em **execução**: a estratégia disse
`ENTER`, o broker decide quantas ações cabem e debita o custo. Essa fronteira
é o que permite trocar o esquema de sizing na Fase 2 sem tocar em estratégia
nenhuma (design §4.2).

**O erro que design §4.4 manda vigiar:** calcular a quantidade ignorando o
custo. `q = caixa // preço` parece certo e produz caixa negativo assim que o
custo é debitado — silenciosamente, porque o número resultante ainda parece um
número. A conta correta resolve `q*p + custo(q*p) <= caixa`, e a fixture
`test_ignoring_the_cost_would_produce_negative_cash` existe só para provar que
ela foi feita.
"""

from dataclasses import dataclass
from datetime import date

from quantlab.engine.portfolio import Portfolio, Position, Trade
from quantlab.exceptions import EngineError
from quantlab.logging import get_logger

__all__ = ["Broker", "CostModel"]

_log = get_logger(__name__)

#: Decisão D2 do requirements: 1 bps sobre o notional + USD 1 fixo por trade.
#: Corretoras de varejo nos EUA hoje cobram zero comissão, mas custo zero
#: mascara estratégia de giro alto — o default conservador força a estratégia
#: a pagar pelo giro.
_DEFAULT_FIXED = 1.0
_DEFAULT_RATE = 0.0001


@dataclass(frozen=True, slots=True)
class CostModel:
    """Custo de transação: valor fixo por trade + percentual sobre o notional."""

    fixed: float = _DEFAULT_FIXED
    rate: float = _DEFAULT_RATE

    def __post_init__(self) -> None:
        if self.fixed < 0 or self.rate < 0:
            raise EngineError(f"Custo não pode ser negativo: fixed={self.fixed}, rate={self.rate}.")

    @property
    def is_zero(self) -> bool:
        """ENG-03.2 — o relatório precisa sinalizar que os números são irrealistas."""
        return self.fixed == 0.0 and self.rate == 0.0

    def cost_for(self, notional: float) -> float:
        return self.fixed + self.rate * notional


class Broker:
    """Executa ordens a mercado ao preço dado, debitando custo do caixa."""

    __slots__ = ("_costs",)

    def __init__(self, costs: CostModel | None = None) -> None:
        self._costs = costs if costs is not None else CostModel()

    @property
    def costs(self) -> CostModel:
        return self._costs

    def max_affordable_quantity(self, cash: float, price: float) -> int:
        """Maior quantidade inteira que cabe no caixa **depois do custo**.

        Resolve ``q*p + fixed + rate*q*p <= cash``, ou seja
        ``q <= (cash - fixed) / (p * (1 + rate))``. Fecha para baixo, porque
        não há fracionário (premissa 3).

        Faz a conta fechada em vez de iterar: `rate` é linear no notional, o
        que torna a desigualdade solúvel direto. Um laço decrementando `q`
        daria o mesmo número e seria O(q).
        """
        if price <= 0:
            raise EngineError(f"Preço de execução não positivo: {price}.")

        affordable = cash - self._costs.fixed
        if affordable <= 0:
            return 0

        quantity = int(affordable // (price * (1.0 + self._costs.rate)))
        return max(quantity, 0)

    def buy(
        self,
        portfolio: Portfolio,
        *,
        ticker: str,
        price: float,
        execution_date: date,
        decision_date: date,
    ) -> Trade | None:
        """ENG-02.1 — all-in: compra o máximo de ações inteiras que o caixa permite.

        Devolve ``None`` quando não cabe nem uma ação (ENG-02.3): nenhuma ordem
        é gerada e o evento é logado. Um caixa que não compra uma ação não é
        erro — é uma estratégia que ficou pequena demais depois de perdas, e o
        relatório precisa poder mostrar isso.
        """
        if ticker in portfolio.positions:
            # ENG-05 / decisão Q2: ENTER com posição aberta é ignorado e logado.
            _log.info(
                "engine.enter_with_open_position", ticker=ticker, date=execution_date.isoformat()
            )
            return None

        quantity = self.max_affordable_quantity(portfolio.cash, price)
        if quantity == 0:
            _log.info(
                "engine.insufficient_cash",
                ticker=ticker,
                date=execution_date.isoformat(),
                cash=portfolio.cash,
                price=price,
            )
            return None

        notional = quantity * price
        cost = self._costs.cost_for(notional)

        portfolio.cash -= notional + cost
        portfolio.positions[ticker] = Position(
            ticker=ticker,
            quantity=quantity,
            entry_price=price,
            entry_date=execution_date,
        )
        trade = Trade(
            ticker=ticker,
            entry_date=execution_date,
            entry_price=price,
            entry_decision_date=decision_date,
            quantity=quantity,
            entry_cost=cost,
            entry_gap_days=(execution_date - decision_date).days,
        )
        portfolio.trades.append(trade)
        portfolio.check_invariants()
        return trade

    def sell(
        self,
        portfolio: Portfolio,
        *,
        ticker: str,
        price: float,
        execution_date: date,
        decision_date: date,
    ) -> Trade | None:
        """ENG-02.2 + decisão D3 — liquida a posição inteira, volta a 100% caixa."""
        position = portfolio.positions.get(ticker)
        if position is None:
            raise EngineError(
                f"Venda de {ticker} sem posição aberta. O laço de barras só deveria "
                "mandar vender com posição — isto é erro de programação."
            )

        notional = position.quantity * price
        cost = self._costs.cost_for(notional)
        portfolio.cash += notional - cost
        del portfolio.positions[ticker]

        closed = self._close_trade(
            portfolio,
            ticker=ticker,
            price=price,
            cost=cost,
            execution_date=execution_date,
            decision_date=decision_date,
        )
        portfolio.check_invariants()
        return closed

    def _close_trade(
        self,
        portfolio: Portfolio,
        *,
        ticker: str,
        price: float,
        cost: float,
        execution_date: date,
        decision_date: date,
    ) -> Trade:
        """Substitui o `Trade` aberto pela versão fechada.

        `Trade` é congelado (design §4.5), então fechar é criar outro e trocar
        na lista — não mutar. Guardar o índice em vez de anexar mantém a ordem
        cronológica dos trades, que é o que o relatório e `hit_rate` esperam.
        """
        for index in range(len(portfolio.trades) - 1, -1, -1):
            candidate = portfolio.trades[index]
            if candidate.ticker == ticker and candidate.is_open:
                closed = Trade(
                    ticker=candidate.ticker,
                    entry_date=candidate.entry_date,
                    entry_price=candidate.entry_price,
                    entry_decision_date=candidate.entry_decision_date,
                    quantity=candidate.quantity,
                    entry_cost=candidate.entry_cost,
                    entry_gap_days=candidate.entry_gap_days,
                    exit_date=execution_date,
                    exit_price=price,
                    exit_cost=cost,
                    exit_gap_days=(execution_date - decision_date).days,
                    exit_decision_date=decision_date,
                )
                portfolio.trades[index] = closed
                return closed

        raise EngineError(  # pragma: no cover - barrado por `sell`
            f"Posição em {ticker} sem `Trade` aberto correspondente."
        )
