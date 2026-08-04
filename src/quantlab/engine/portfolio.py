"""`Trade`, `Position` e `Portfolio` — C3, design §4.4 e §4.5.

`Portfolio` modela **N posições desde já** (decisão D4 do requirements), com
N=1 exercitado na Fase 1. O custo marginal de modelar o dicionário agora é
baixo; o custo de retrofit na Fase 2 seria alto.

As invariantes de ENG-04.4 — `cash >= 0` e `quantity >= 0` — são checadas
como **erro de programação, não condição de mercado**: violação levanta
`EngineError`. Um backtest long-only sem alavancagem (premissas 2 e 3) não
tem caminho legítimo para caixa negativo; se apareceu, o cálculo de tamanho
ignorou o custo, que é precisamente o erro que design §4.4 manda vigiar.
"""

from dataclasses import dataclass, field
from datetime import date

from quantlab.exceptions import EngineError

__all__ = ["Portfolio", "Position", "Trade"]


@dataclass(frozen=True, slots=True)
class Trade:
    """Uma operação completa ou ainda aberta — design §4.5.

    `entry_decision_date` e `entry_gap_days` são o que torna o gap de
    ENG-01.5 **auditável**. Guardando a data da decisão junto da data de
    execução, o gap é derivável e verificável a posteriori em vez de sumir
    numa métrica agregada: uma execução com 4 dias corridos de gap depois de
    um feriado longo fica visível no relatório, e quem lê consegue julgar se
    aquele preço de abertura ainda era razoável.
    """

    ticker: str
    entry_date: date
    entry_price: float
    entry_decision_date: date
    quantity: int
    entry_cost: float
    entry_gap_days: int
    exit_date: date | None = None
    exit_price: float | None = None
    exit_cost: float = 0.0
    exit_gap_days: int | None = None
    exit_decision_date: date | None = None

    @property
    def is_open(self) -> bool:
        return self.exit_date is None

    @property
    def realized_pnl(self) -> float:
        """PnL **BRUTO** de custos — design §4.6.

        Bruto de propósito: os custos entram uma única vez, no termo próprio
        da identidade de conciliação. A alternativa (PnL líquido) é igualmente
        defensável, mas convida a subtrair custos duas vezes, e o bug
        resultante é pequeno o bastante para passar despercebido.

        Posição ainda aberta não tem PnL realizado.
        """
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.quantity

    @property
    def total_cost(self) -> float:
        return self.entry_cost + self.exit_cost


@dataclass(frozen=True, slots=True)
class Position:
    """Posição aberta em um ticker. Long-only: `quantity` nunca é negativa."""

    ticker: str
    quantity: int
    entry_price: float
    entry_date: date

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise EngineError(
                f"Posição em {self.ticker} com quantidade {self.quantity}. "
                "A Fase 1 é long-only (premissa 2): posição existe com quantidade > 0, "
                "ou não existe."
            )

    def market_value(self, price: float) -> float:
        return self.quantity * price


@dataclass(slots=True)
class Portfolio:
    """Caixa, posições e trades. Mutável de propósito — é o estado do backtest."""

    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.cash < 0:
            raise EngineError(f"Capital inicial negativo: {self.cash}.")
        self._initial_cash = self.cash

    #: Guardado na construção para a identidade de conciliação de §4.6.
    _initial_cash: float = field(default=0.0, init=False, repr=False)

    @property
    def initial_cash(self) -> float:
        return self._initial_cash

    def equity(self, prices: dict[str, float]) -> float:
        """ENG-04.1 — `equity = caixa + soma(posição * preço de fechamento)`."""
        holdings = sum(
            position.market_value(prices[ticker]) for ticker, position in self.positions.items()
        )
        return self.cash + holdings

    def check_invariants(self) -> None:
        """ENG-04.4 — checada a cada barra pelo laço.

        Erro de programação, não condição de mercado: `Position` já barra
        quantidade não positiva na construção, então o que sobra aqui é o
        caixa. Caixa negativo num backtest sem alavancagem só acontece se o
        cálculo de tamanho ignorou o custo (design §4.4).
        """
        if self.cash < 0:
            raise EngineError(
                f"Caixa negativo: {self.cash}. Num backtest long-only sem alavancagem "
                "isso é erro de programação — provavelmente o custo não entrou no "
                "cálculo da quantidade (design §4.4)."
            )
        for ticker, position in self.positions.items():
            if position.quantity <= 0:
                raise EngineError(f"Posição não positiva em {ticker}: {position.quantity}.")

    @property
    def open_trade(self) -> Trade | None:
        """O trade aberto, se houver. N=1 na Fase 1."""
        for trade in reversed(self.trades):
            if trade.is_open:
                return trade
        return None
