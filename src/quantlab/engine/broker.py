"""`Broker`, modelo de custo e ordens — C4/§4.4 da Fase 1 + §3.5/§3.8 da 2a.

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

**Fase 2a (T06):** `convert` aplica a sequência fixa de redução
SIZING → CAP → INTEIRAS → CAIXA/CUSTOS (R1/CST-01.3) e devolve um
`ConvertedOrder` **puro** — não toca o portfolio; a mutação é do laço (T11a).
O custo ganha o mínimo `max(f + p·N, m)` (CA-01.1) com `m = 0` por default,
preservando exatamente o comportamento da Fase 1. Nenhum `datetime`/`timezone`
aqui (RNF-07): `decision_date` é `date` naive.
"""

import math
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from quantlab.engine.conditional import ConditionalIntent, OrderKind
from quantlab.engine.liquidity import participation_cap
from quantlab.engine.portfolio import Portfolio, Position, Trade
from quantlab.engine.sizing import Sizer, SizingInputs
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError
from quantlab.logging import get_logger

__all__ = ["Broker", "ConvertedOrder", "CostModel", "CutStage", "PendingOrder"]

_log = get_logger(__name__)

#: Decisão D2 do requirements: 1 bps sobre o notional + USD 1 fixo por trade.
#: Corretoras de varejo nos EUA hoje cobram zero comissão, mas custo zero
#: mascara estratégia de giro alto — o default conservador força a estratégia
#: a pagar pelo giro. O mínimo `m = 0` (2a) mantém a Fase 1 intacta.
_DEFAULT_FIXED = 1.0
_DEFAULT_RATE = 0.0001
_DEFAULT_MIN_COST = 0.0


class CutStage(StrEnum):
    """Etapa da sequência fixa que causou o corte da quantidade (CST-01.3/R1).

    `SIZING` existe no domínio (uma política pode reduzir o alvo vs. all-in)
    mas `FixedOneOverN` nunca corta no sizing — na prática o corte cai em
    `CAP`, `INTEGER` ou `CASH`. `cut_reason` registra a **última** etapa que
    reduziu (determinístico, sem ambiguidade — R1).
    """

    SIZING = "sizing"
    CAP = "cap"
    INTEGER = "integer"
    CASH = "cash"


@dataclass(frozen=True, slots=True)
class CostModel:
    """Custo de transação: fixo + percentual sobre o notional, com mínimo (CA-01.1).

    ``cost_for(N) = max(fixed + rate·N, min_cost)``. Default ``min_cost = 0``
    reproduz exatamente o modelo da Fase 1 (D2: 1 bps + USD 1).
    """

    fixed: float = _DEFAULT_FIXED
    rate: float = _DEFAULT_RATE
    min_cost: float = _DEFAULT_MIN_COST

    def __post_init__(self) -> None:
        if self.fixed < 0 or self.rate < 0 or self.min_cost < 0:
            raise EngineError(
                f"Custo não pode ser negativo: fixed={self.fixed}, rate={self.rate}, "
                f"min_cost={self.min_cost}."
            )

    @property
    def is_zero(self) -> bool:
        """ENG-03.2 — o relatório precisa sinalizar que os números são irrealistas."""
        return self.fixed == 0.0 and self.rate == 0.0 and self.min_cost == 0.0

    def cost_for(self, notional: float) -> float:
        return max(self.fixed + self.rate * notional, self.min_cost)


#: Tolerância de ponto flutuante na validação dos candidatos do caixa/custos.
#: A desigualdade `q·p + custo <= cash` é resolvida com `//` (floor exato); a
#: revalidação admite 1e-9 para não reprovar uma solução de fronteira.
_FP_TOL = 1e-9


def _affordable_quantity(cash: float, price: float, costs: CostModel) -> int:
    """Reduce-until-fits em forma fechada (design §3.5, T06).

    A desigualdade ``q·p + max(f + r·q·p, m) <= cash`` é linear por partes:

    - região linear (``f + r·q·p >= m``): ``q <= (cash - f) / (p·(1+r))``;
    - região do mínimo (custo = ``m``): ``q <= (cash - m) / p``.

    Cada candidato é validado com o custo real — o máximo dos válidos é a
    resposta exata do laço decremental, sem o custo O(q). `cash < 0` ⇒ 0
    (o laço garante caixa não-negativo; aqui é só robustez).
    """
    if price <= 0:
        raise EngineError(f"Preço de execução não positivo: {price}.")
    if cash < 0:
        return 0

    candidates: list[int] = []
    if cash >= costs.fixed:
        candidates.append(int((cash - costs.fixed) // (price * (1.0 + costs.rate))))
    if cash >= costs.min_cost:
        candidates.append(int((cash - costs.min_cost) // price))

    valid = [
        q for q in candidates if q >= 0 and q * price + costs.cost_for(q * price) <= cash + _FP_TOL
    ]
    return max(valid, default=0)


@dataclass(frozen=True, slots=True)
class ConvertedOrder:
    """Resultado da conversão (T06, design §3.5) — imutável, pronto para `place` (T07).

    ``ref_price`` = último close conhecido na decisão (`inputs.last_close[ticker]`);
    ``est_cost`` é a estimativa de custo nesse preço — o custo real sai na
    execução (T08), com o preço de open + slippage. ``cut_reason`` é a última
    etapa da sequência que reduziu a quantidade (None sse nenhum corte).
    """

    ticker: str
    kind: OrderKind
    limit: float | None
    stop: float | None
    qty: int
    ref_price: float
    decision_date: date
    intent_seq: int
    cut_reason: CutStage | None
    est_cost: float
    bracket: bool


@dataclass(frozen=True, slots=True)
class PendingOrder:
    """Ordem pendente por ativo (design §3.5) — criada por `Broker.place` (T07).

    `intent_seq` distingue intenções; o par de um bracket compartilha
    `decision_date` e `intent_seq` (SIG-01.3).
    """

    ticker: str
    kind: OrderKind
    limit: float | None
    stop: float | None
    qty: int
    decision_date: date
    intent_seq: int
    bracket: bool


@dataclass(slots=True)
class PendingBook:
    """Store de pendentes por ativo (emenda T07, design §3.5).

    O broker é ESTÁTICO: o store é passado como parâmetro (`Broker.place`/
    `Broker.cancel_all`), e a T10 compõe um `PendingBook` no `Portfolio`.
    Nenhum caixa existe aqui — a ordem usa o caixa disponível na hora da
    EXECUÇÃO (T08), sem reserva (ORD-04.3).

    Invariantes:
    - ``orders[ticker]`` nunca tem intenção "vencida" (substituída);
    - o par de um bracket compartilha `intent_seq` (mesma intenção);
    - intenções diferentes têm `intent_seq` crescente (o laço incrementa).
    """

    orders: dict[str, list[PendingOrder]] = field(default_factory=dict)

    def place(self, order: PendingOrder) -> None:
        """Registra a ordem por ativo — última intenção vence (ORD-04.2).

        Pendentes do MESMO ativo com ``intent_seq`` menor são substituídas;
        pendentes de outros ativos ficam intactas; a mesma intenção (par de
        bracket, mesmo seq) convive. Determinístico e sem efeito no caixa.
        """

        current = self.orders.setdefault(order.ticker, [])
        surviving = [p for p in current if p.intent_seq >= order.intent_seq]
        surviving.append(order)
        self.orders[order.ticker] = surviving

    def cancel_all(self, ticker: str) -> None:
        """Remove TODAS as pendentes do ativo, incluindo stops (ORD-04.1).

        Ativo sem pendentes ⇒ no-op (não é erro).
        """

        self.orders.pop(ticker, None)

    def pending_for(self, ticker: str) -> tuple[PendingOrder, ...]:
        """Leitura imutável das pendentes do ativo, em ordem de inserção."""

        return tuple(self.orders.get(ticker, ()))


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

        Resolve ``q·p + max(fixed + rate·q·p, min_cost) <= cash`` — o
        reduce-until-fits em forma fechada (design §3.5, T06): a desigualdade
        é linear por partes, então bastam os dois candidatos de trecho,
        validados com o custo real. Fecha para baixo (premissa 3: sem
        fracionário). Um laço decrementando `q` daria o mesmo número e seria
        O(q) — mesmo princípio do texto original da Fase 1.
        """
        return _affordable_quantity(cash, price, self._costs)

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

    def convert(
        self,
        intent: Signal | ConditionalIntent,
        ticker: str,
        inputs: SizingInputs,
        sizer: Sizer,
        adv: float | None,
        cost_model: CostModel,
        cap: float,
        decision_date: date,
        intent_seq: int,
    ) -> ConvertedOrder | None:
        """Converte a intenção de ENTRADA em ordem pronta para `place` (T06).

        **SEQUÊNCIA FIXA (R1/CST-01.3):** SIZING → CAP (SLP-03) → INTEIRAS
        (SIZ-01.2) → CAIXA/CUSTOS (CST-01.2). A última etapa que reduziu a
        quantidade vira `cut_reason` (determinístico).

        Função **pura**: não toca o portfolio nem o caixa — mutação é do laço
        (T11a); `decision_date`/`intent_seq` vêm do laço (auditoria do
        ENG-01.2, ORD-04.4/04.2). `ref_price` = último close conhecido na
        decisão (`inputs.last_close[ticker]`); a execução real sai no open da
        próxima barra do próprio ativo (ADR-0002, T08).

        Returns:
            `ConvertedOrder` com `qty >= 1`, ou `None` quando não sobra nem
            uma ação (CST-01.2/SLP-03.5) — nesse caso o evento é logado.

        Raises:
            EngineError: intenção de saída, `ticker` sem last_close ou
                `ref_price <= 0` (erro de programação — o laço não pergunta
                por ativo sem barra, R2/SIZ-02.4).
        """
        if isinstance(intent, Signal):
            if intent is not Signal.ENTER:
                raise EngineError(
                    "convert só recebe intenções de ENTER; EXIT passa por cancel_all "
                    "e saída ao próximo open (T07)."
                )
            kind = OrderKind.MARKET
            limit: float | None = None
            stop: float | None = None
            bracket = False
        else:
            if intent.signal is not Signal.ENTER:
                raise EngineError(
                    "convert só recebe intenções de ENTER; bracket de saída é ciclo de vida (T07)."
                )
            kind = intent.order_type
            limit = intent.limit
            # O par limite+stop vive na mesma intenção (SIG-01.2): para
            # bracket, o stop protetor está em `bracket.stop` e o `stop`
            # avulso é None — o ConvertedOrder carrega o valor do par.
            stop = (
                intent.stop
                if intent.stop is not None
                else (intent.bracket.stop if intent.bracket is not None else None)
            )
            bracket = intent.bracket is not None

        if kind is OrderKind.STOP:
            # P2: na 2a o único stop é o sell-stop protetor sobre posição
            # aberta (saída — T08); buy-stop/entrada condicional é a 2b.
            raise EngineError(
                "convert: entrada com STOP (buy-stop) é escopo da Fase 2b (P2). "
                "Na 2a o stop só aparece como sell-stop protetor (T08)."
            )

        ref_price = inputs.last_close.get(ticker)
        if ref_price is None:
            raise EngineError(
                f"convert: {ticker} sem last_close — ativo sem barra na janela "
                "nunca recebe alvo (R2/SIZ-02.4); erro do laço."
            )
        if ref_price <= 0:
            raise EngineError(f"convert: ref_price {ref_price} não positivo para {ticker}.")

        # SIZING — fração do patrimônio (SIZ-04.2) → quantidade alvo (float).
        fraction = sizer.target_fraction(ticker, inputs)
        qty = inputs.equity * fraction / ref_price
        cut: CutStage | None = None

        # CAP — teto de participação (SLP-03.3), mesmo helper da T02. O teto
        # opera sobre a parte inteira do alvo (quantidades são discretas); se
        # o teto reduz, o corte é CAP — e a comparação é em unidades inteiras.
        if adv is not None:
            capped = participation_cap(max(1, int(qty)), adv, cap)
            if capped < int(qty):
                qty = float(capped)
                cut = CutStage.CAP

        # INTEIRAS — conversão em quantidade inteira (SIZ-01.2).
        whole = math.floor(qty)
        if whole < qty:
            cut = CutStage.INTEGER
        qty = whole

        if qty < 1:
            _log.info(
                "engine.order_below_one_share",
                ticker=ticker,
                date=decision_date.isoformat(),
                qty=qty,
                cut=cut.value if cut is not None else None,
            )
            return None

        # CAIXA/CUSTOS — reduce-until-fits (CST-01.2), forma fechada.
        fitted = _affordable_quantity(inputs.cash, ref_price, cost_model)
        if fitted < 1:
            _log.info(
                "engine.insufficient_cash",
                ticker=ticker,
                date=decision_date.isoformat(),
                cash=inputs.cash,
                price=ref_price,
            )
            return None
        if fitted < qty:
            qty = fitted
            cut = CutStage.CASH

        notional = qty * ref_price
        est_cost = cost_model.cost_for(notional)
        return ConvertedOrder(
            ticker=ticker,
            kind=kind,
            limit=limit,
            stop=stop,
            qty=qty,
            ref_price=ref_price,
            decision_date=decision_date,
            intent_seq=intent_seq,
            cut_reason=cut,
            est_cost=est_cost,
            bracket=bracket,
        )

    def place(self, store: PendingBook, order: ConvertedOrder) -> None:
        """Registra a ordem convertida no store (T07, emenda §3.5).

        Broker ESTÁTICO: o `PendingBook` vem por parâmetro; sem reserva de
        caixa (ORD-04.3) — a ordem usa o caixa disponível na EXECUÇÃO (T08).
        Última intenção vence (ORD-04.2): a substituição é do próprio store.

        Bracket ⇒ o PAR nasce aqui (limite + stop protetor, mesmo
        `decision_date`/`intent_seq` — SIG-01.3): o stop fica pendente desde
        já mas só ATIVA com posição aberta (ORD-02.2, T08) — o ADR-0007/D2
        exige o stop vivo durante a barra de entrada para a ambiguidade
        intrabarra (abre em L e fecha no stop na mesma barra).

        Raises:
            EngineError: `bracket` sem `kind = LIMIT` ou sem `limit`/`stop`
                (ordem malformada — erro de programação).
        """
        if order.bracket:
            if order.kind is not OrderKind.LIMIT or order.limit is None or order.stop is None:
                raise EngineError(
                    "place: ordem bracket malformada — exige kind=LIMIT com limit e stop."
                )
            store.place(
                PendingOrder(
                    ticker=order.ticker,
                    kind=OrderKind.LIMIT,
                    limit=order.limit,
                    stop=None,
                    qty=order.qty,
                    decision_date=order.decision_date,
                    intent_seq=order.intent_seq,
                    bracket=True,
                )
            )
            store.place(
                PendingOrder(
                    ticker=order.ticker,
                    kind=OrderKind.STOP,
                    limit=None,
                    stop=order.stop,
                    qty=order.qty,
                    decision_date=order.decision_date,
                    intent_seq=order.intent_seq,
                    bracket=True,
                )
            )
            return

        store.place(
            PendingOrder(
                ticker=order.ticker,
                kind=order.kind,
                limit=order.limit,
                stop=order.stop,
                qty=order.qty,
                decision_date=order.decision_date,
                intent_seq=order.intent_seq,
                bracket=False,
            )
        )

    def cancel_all(self, store: PendingBook, ticker: str) -> None:
        """EXIT cancela TODAS as pendentes do ativo, incluindo stops (ORD-04.1)."""

        store.cancel_all(ticker)
