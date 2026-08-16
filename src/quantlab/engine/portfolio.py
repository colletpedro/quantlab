"""`Trade`, `Position` e `Portfolio` — C3, design §4.4 e §4.5 (+ 2a §3.6).

`Portfolio` modela **N posições desde já** (decisão D4 do requirements), com
N=1 exercitado na Fase 1. O custo marginal de modelar o dicionário agora é
baixo; o custo de retrofit na Fase 2 seria alto.

As invariantes de ENG-04.4 — `cash >= 0` e `quantity >= 0` — são checadas
como **erro de programação, não condição de mercado**: violação levanta
`EngineError`. Um backtest long-only sem alavancagem (premissas 2 e 3) não
tem caminho legítimo para caixa negativo; se apareceu, o cálculo de tamanho
ignorou o custo, que é precisamente o erro que design §4.4 manda vigiar.

**Fase 2a (T08):** `Trade` ganha `origin`/`cut_reason`/`ambiguous` (design
§3.6) — auditoria do ENG-01.2 (ORD-04.4), motivo do corte (CST-01.3) e
ambiguidade intrabarra (ORD-03/ADR-0007). Os defaults preservam os trades
criados pelos caminhos da Fase 1 (`buy`/`sell`).

**Fase 2a (T10):** `Portfolio` vira multi-ativo de verdade: caixa ÚNICO
compartilhado (POR-01.1), `pending: PendingBook` por ativo (emenda T07),
`marks` (último close conhecido por ativo — POR-02.2) alimentando a
identidade de equity (POR-04.1) e `check_invariants(n)` com o ``k <= N``
(POR-04.3/SIZ-04.3). A Fase 1 continua intacta: `equity(prices)` e
`check_invariants()` sem argumento preservam a assinatura antiga.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from quantlab.exceptions import EngineError

if TYPE_CHECKING:  # mypy apenas — evita ciclo broker ⇄ portfolio em runtime
    from quantlab.engine.broker import CutStage, PendingBook

__all__ = ["Portfolio", "Position", "Trade", "TradeOrigin"]


class TradeOrigin(StrEnum):
    """Origem da execução de um `Trade` — auditoria (2b, T01, design §3.2).

    `MARKET`/`LIMIT`/`STOP` **espelham** `OrderKind` com os MESMOS valores
    (compat 2a — comparação por valor, não por identidade: `TradeOrigin.STOP
    == OrderKind.STOP`); `MARGIN_CALL` é novo e **só existe como origin de
    Trade** — nunca como `PendingOrder.kind` (a ordem subjacente é MARKET,
    ADR-0009/RF-MRG-02 CA-02.3).
    """

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    MARGIN_CALL = "margin_call"


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
    #: Fase 2a (§3.6, T08): origem da execução (auditoria ENG-01.2/ORD-04.4),
    #: etapa do corte no sizing (CST-01.3/R1) e ambiguidade intrabarra
    #: (ORD-03/ADR-0007). Defaults preservam os caminhos da Fase 1.
    origin: TradeOrigin | None = None
    cut_reason: CutStage | None = None
    ambiguous: bool = False
    #: Fase 2a (T11a): trade de rebalanceamento (SIZ-03.2/CA-03.2) — contado
    #: separadamente dos trades de sinal no relatório (T16). Default preserva
    #: os caminhos da Fase 1 e da T08/T09.
    rebalance: bool = False

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
    """Posição aberta em um ticker. Fase 2b: `quantity < 0` = short (D3/ADR-0009).

    O relaxamento de `quantity >= 0` (invariante da 2a, POR-04.3) é coberto
    pelo ADR-0009 (RNF-09): `quantity < 0` passa a ser válido (short);
    `quantity == 0` continua inválido — zero ações não é posição, é lixo no
    dicionário esperando virar divisão por zero em `analytics`.
    """

    ticker: str
    quantity: int
    entry_price: float
    entry_date: date

    def __post_init__(self) -> None:
        if self.quantity == 0:
            raise EngineError(
                f"Posição em {self.ticker} com quantidade 0 — posição existe com "
                "quantidade != 0 (positiva = long, negativa = short, 2b/ADR-0009), "
                "ou não existe."
            )

    def market_value(self, price: float) -> float:
        return self.quantity * price


@dataclass(slots=True)
class Portfolio:
    """Caixa, posições, trades, pendentes e marcas. Mutável de propósito — é o estado do backtest.

    Multi-ativo (2a, T10): um caixa ÚNICO compartilhado (POR-01.1 — nada de
    caixa por ativo), `pending` por ativo (emenda T07: `PendingBook` de
    broker.py) e `marks` = último close conhecido por ativo (POR-02.2). A
    identidade de equity (POR-04.1) deriva de `marks` quando `equity()` é
    chamado sem argumento; a assinatura da Fase 1 (`equity(prices)`) fica
    preservada.
    """

    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    pending: PendingBook = field(init=False, repr=False)  # composto da T07 (broker.py)
    marks: dict[str, float] = field(default_factory=dict)  # último close conhecido (POR-02.2)

    def __post_init__(self) -> None:
        if self.cash < 0:
            raise EngineError(f"Capital inicial negativo: {self.cash}.")
        self._initial_cash = self.cash
        # Import deferido de propósito: broker.py importa este módulo em
        # runtime (assinaturas do Broker), então um import de topo de
        # `PendingBook` fecharia um ciclo de importação. O store vive em
        # broker.py (emenda T07); aqui só se CONSTRÓI o default — e qualquer
        # construção de Portfolio acontece com os dois módulos carregados.
        from quantlab.engine.broker import PendingBook

        self.pending = PendingBook()

    #: Guardado na construção para a identidade de conciliação de §4.6.
    _initial_cash: float = field(default=0.0, init=False, repr=False)

    @property
    def initial_cash(self) -> float:
        return self._initial_cash

    def equity(self, prices: dict[str, float] | None = None) -> float:
        """ENG-04.1/POR-04.1 — `equity = caixa + soma(posição * preço de fechamento)`.

        Fase 1 preservada: com `prices` explícito, usa exatamente esses
        preços. Sem argumento (2a, T10), deriva de `marks` — o último close
        conhecido por ativo (POR-02.2), alimentado por `market_to_market` — e
        cobre os ativos com posição, incluindo o deslistado (marca travada).
        """
        if prices is None:
            prices = self.marks
        holdings = sum(
            position.market_value(prices[ticker]) for ticker, position in self.positions.items()
        )
        return self.cash + holdings

    def market_to_market(self, close_by_ticker: dict[str, float]) -> None:
        """POR-02.2 — atualiza `marks` (último close conhecido por ativo).

        O laço (T11a/T11b) chama uma vez por data-união passando o último
        close conhecido de CADA ativo (o calendário deriva `last_known`);
        para ativo sem barra na data, é o close da última barra válida —
        nunca barra fabricada. Deslistagem = marca travada no último close.

        Pré-condição (erro de programa, não condição de mercado): o mapa
        cobre TODOS os ativos com posição aberta — sem isso a equity
        silenciosamente ignora uma posição (POR-04.1 quebra). Preços não
        positivos são erro de domínio.
        """
        missing = sorted(set(self.positions) - set(close_by_ticker))
        if missing:
            raise EngineError(
                f"market_to_market: faltou último close conhecido para {missing} — "
                "o laço deve passar o last_known de todos os ativos com posição (POR-02.2)."
            )
        bad = sorted(t for t, c in close_by_ticker.items() if c <= 0)
        if bad:
            raise EngineError(f"market_to_market: close não positivo em {bad}.")
        self.marks.update(close_by_ticker)

    def check_invariants(self, n: int | None = None) -> None:
        """ENG-04.4/POR-04.3 — checada a cada barra pelo laço.

        Erro de programação, não condição de mercado: `Position` já barra
        quantidade não positiva na construção, então o que sobra aqui é o
        caixa e o ``k <= N`` (com `n`, o número de posições abertas não pode
        exceder o N do run — SIZ-04.3). Caixa negativo num backtest sem
        alavancagem só acontece se o cálculo de tamanho ignorou o custo
        (design §4.4). A Fase 1 continua intacta: `check_invariants()` sem
        argumento pula o ``k <= N``.
        """
        if n is not None and n < 1:
            raise EngineError(f"check_invariants: N do run inválido: {n}.")
        if self.cash < 0:
            raise EngineError(
                f"Caixa negativo: {self.cash}. Num backtest long-only sem alavancagem "
                "isso é erro de programação — provavelmente o custo não entrou no "
                "cálculo da quantidade (design §4.4)."
            )
        for ticker, position in self.positions.items():
            if position.quantity <= 0:
                raise EngineError(f"Posição não positiva em {ticker}: {position.quantity}.")
        if n is not None and len(self.positions) > n:
            raise EngineError(
                f"Número de posições abertas {len(self.positions)} excede o N do run {n} "
                "(k <= N, SIZ-04.3) — erro de programação do laço."
            )

    @property
    def open_trade(self) -> Trade | None:
        """O trade aberto, se houver. N=1 na Fase 1."""
        for trade in reversed(self.trades):
            if trade.is_open:
                return trade
        return None
