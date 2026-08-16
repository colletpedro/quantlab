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
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum

from quantlab.engine.conditional import ConditionalIntent, OrderKind, Side
from quantlab.engine.liquidity import participation_cap
from quantlab.engine.margin import BorrowFeeModel, MarginCallOrder
from quantlab.engine.portfolio import Portfolio, Position, Trade, TradeOrigin
from quantlab.engine.sizing import Sizer, SizingInputs
from quantlab.engine.slippage import SlippageModel
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError
from quantlab.logging import get_logger

__all__ = ["BarSlice", "Broker", "ConvertedOrder", "CostModel", "CutStage", "PendingOrder"]

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
class BarSlice:
    """Barra de execução do PRÓPRIO ativo (T08, emenda §3.5).

    `date` é naive (RNF-07): o gap de pregões no Trade é `bar.date -
    decision_date`, em dias corridos, como na Fase 1 (ENG-01.5).
    Pré-condição: preços > 0 (validados pelo `Validator` na ingestão;
    o broker rejeita preço ≤ 0 com `EngineError`).
    """

    date: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class PendingOrder:
    """Ordem pendente por ativo (design §3.5) — criada por `Broker.place` (T07).

    `intent_seq` distingue intenções; o par de um bracket compartilha
    `decision_date` e `intent_seq` (SIG-01.3). `side` (emenda T08) define
    compra vs venda — necessário porque um LIMIT pode ser entrada (BUY) ou
    take-profit (SELL). `cut_reason` carrega do convert para o Trade
    (CA-01.3).
    """

    ticker: str
    kind: OrderKind
    side: Side
    limit: float | None
    stop: float | None
    qty: int
    decision_date: date
    intent_seq: int
    bracket: bool
    cut_reason: CutStage | None = None
    #: ordem sintética do rebalance (SIZ-03/T11a); MARKET SELL só existe aqui
    rebalance: bool = False


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


@dataclass(slots=True)
class MechanismCounters:
    """Contadores de mecanismo do engine (MET-05/P6, emenda T16).

    Bloco "contadores de mecanismo" do relatório — incrementados APENAS pelo
    engine (design §3.8), nunca pelo relatório. `stops_triggered` e
    `intrabar_ambiguities` são derivados pelo laço (T16) dos trades de
    execução (``origin == TradeOrigin.STOP`` / ``ambiguous`` — 1 trade por
    ocorrência, ADR-0007/D2); `unfilled_cash_orders` é incrementado aqui no
    broker, onde o evento acontece: o `convert` (nem 1 ação após custos) e o
    `execute_pending` (caixa insuficiente na barra de execução) — Q5/POR-01.2.
    Mutável de propósito: é um acumulador do run; o resultado o carrega por
    referência (``BacktestResultMulti.counters``).
    """

    stops_triggered: int = 0
    intrabar_ambiguities: int = 0
    unfilled_cash_orders: int = 0
    #: 2b (T03, RF-SHT-03 CA-03.4) — ENTER_SHORT bloqueado por indisponibilidade
    #: de aluguel; contado no `convert`, onde o evento acontece (dono §3.7).
    borrow_rejections: int = 0
    #: 2b (T08b, RF-MRG-02 CA-02.3) — nº de trades de liquidação forçada
    #: (origin=MARGIN_CALL); DERIVADO pelo laço dos fills do
    #: `execute_margin_calls` (dono §3.7 — o relatório só reporta).
    margin_calls: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "stops_triggered": self.stops_triggered,
            "intrabar_ambiguities": self.intrabar_ambiguities,
            "unfilled_cash_orders": self.unfilled_cash_orders,
            "borrow_rejections": self.borrow_rejections,
            "margin_calls": self.margin_calls,
        }


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
        origin: TradeOrigin | None = None,
        ambiguous: bool | None = None,
    ) -> Trade | None:
        """ENG-02.2 + decisão D3 — liquida a posição inteira, volta a 100% caixa.

        `origin` (2a, T08; 2b, T01 — `TradeOrigin`): MARKET/LIMIT/STOP —
        auditoria do ENG-01.2 (ORD-04.4). `ambiguous` (T09): ``None`` preserva o flag da entrada;
        ``True``/``False`` força — a ambiguidade intrabarra é da SAÍDA
        (ADR-0007). `None` preserva o caminho da Fase 1.
        """
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
            origin=origin,
            ambiguous=ambiguous,
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
        origin: TradeOrigin | None = None,
        ambiguous: bool | None = None,
        rebalance: bool | None = None,
    ) -> Trade:
        """Substitui o `Trade` aberto pela versão fechada.

        `Trade` é congelado (design §4.5), então fechar é criar outro e trocar
        na lista — não mutar. Guardar o índice em vez de anexar mantém a ordem
        cronológica dos trades, que é o que o relatório e `hit_rate` esperam.
        `origin` (2a, T08) é o tipo de ordem que fechou a posição; `ambiguous`
        (T09) força o flag quando ``not None`` (a ambiguidade é da saída),
        senão preserva o da entrada.
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
                    origin=origin,
                    cut_reason=candidate.cut_reason,
                    ambiguous=ambiguous if ambiguous is not None else candidate.ambiguous,
                    rebalance=rebalance if rebalance is not None else candidate.rebalance,
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
        counters: MechanismCounters | None = None,
        borrow: BorrowFeeModel | None = None,
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
            if intent not in (Signal.ENTER, Signal.ENTER_SHORT):
                raise EngineError(
                    "convert só recebe intenções de ENTER/ENTER_SHORT; EXIT/EXIT_SHORT "
                    "passam por cancel_all + saída ao próximo open (T07/T08a)."
                )
            short = intent is Signal.ENTER_SHORT  # 2b (T02, D3) — direção no sinal
            kind = OrderKind.MARKET
            limit: float | None = None
            stop: float | None = None
            bracket = False
        else:
            if intent.signal not in (Signal.ENTER, Signal.ENTER_SHORT):
                raise EngineError(
                    "convert só recebe intenções de ENTER/ENTER_SHORT; bracket de saída "
                    "é ciclo de vida (T07)."
                )
            short = intent.signal is Signal.ENTER_SHORT  # 2b (T02, D3)
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
            if bracket and kind is OrderKind.STOP and intent.bracket is not None:
                # 2b (T07): no bracket de ENTRADA por buy-stop, o `limit` do
                # ConvertedOrder carrega o SELL-STOP protetor (S_s) — overload
                # documentado: o par são os dois preços (limit/stop) e o kind
                # discrimina qual é o gatilho de entrada (aqui `stop` = S_e).
                limit = intent.bracket.stop

        if short and borrow is not None and not borrow.is_available(ticker, decision_date):
            # 2b (T03, RF-SHT-03 CA-03.4 direita): aluguel indisponível ⇒ a
            # ordem NÃO executa, logada e contada (borrow_rejections) — o
            # evento acontece aqui no convert (dono §3.7).
            if counters is not None:
                counters.borrow_rejections += 1
            _log.info(
                "engine.borrow_unavailable",
                ticker=ticker,
                date=decision_date.isoformat(),
            )
            return None

        if short and kind is not OrderKind.MARKET:
            # 2b (T06): ENTER_SHORT só existe a MERCADO — limite/stop de VENDA
            # para abrir short não é constructo da fase (o buy-stop é compra;
            # sell-stop é saída protetora). Guard de direção: place() montaria
            # side=BUY e um LIMIT/STOP de short viraria entrada LONG em silêncio.
            raise EngineError(
                "convert: ENTER_SHORT só existe a mercado (MARKET) na 2b — "
                "limite/stop de venda para abrir short não é constructo da fase."
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
        # 2b (T02, D3): ENTER_SHORT aplica a fração como MAGNITUDE e o alvo vira
        # NEGATIVO — a direção é do sinal, nunca do sizer (SHT-01.2).
        fraction = sizer.target_fraction(ticker, inputs)
        qty = inputs.equity * fraction / ref_price
        if short:
            qty = -qty
        cut: CutStage | None = None

        # CAP — teto de participação (SLP-03.3), mesmo helper da T02. O teto
        # opera sobre a MAGNITUDE do alvo (quantidades são discretas); se o teto
        # reduz, o corte é CAP — e a comparação é em unidades inteiras. Vale
        # para short igualmente (SHT-02.3 — mesma regra e motivo).
        if adv is not None:
            magnitude = abs(qty)
            capped = participation_cap(max(1, int(magnitude)), adv, cap)
            if capped < int(magnitude):
                qty = int(math.copysign(float(capped), qty))
                cut = CutStage.CAP

        # INTEIRAS — conversão em quantidade inteira (SIZ-01.2), com o sinal
        # preservado (copysign).
        whole = math.floor(abs(qty))
        if whole < abs(qty):
            cut = CutStage.INTEGER
        qty = int(math.copysign(float(whole), qty)) if whole else 0

        if abs(qty) < 1:
            _log.info(
                "engine.order_below_one_share",
                ticker=ticker,
                date=decision_date.isoformat(),
                qty=qty,
                cut=cut.value if cut is not None else None,
            )
            return None

        # CAIXA/CUSTOS — reduce-until-fits (CST-01.2), forma fechada. Para
        # ENTER (long) o caixa é o limite (2a, preservado). Para ENTER_SHORT a
        # VENDA CREDITA caixa (o limite não é o caixa — é a margem, checada no
        # laço, T04/T08a); a etapa existe na mesma sequência (R1) mas não corta
        # por caixa — decisão local documentada (RF-SHT-02).
        fitted = (
            _affordable_quantity(inputs.cash, ref_price, cost_model) if qty > 0 else int(abs(qty))
        )
        if fitted < 1:
            if counters is not None:
                counters.unfilled_cash_orders += 1
            _log.info(
                "engine.insufficient_cash",
                ticker=ticker,
                date=decision_date.isoformat(),
                cash=inputs.cash,
                price=ref_price,
            )
            return None
        if fitted < abs(qty):
            qty = int(math.copysign(float(fitted), qty))
            cut = CutStage.CASH

        notional = abs(qty) * ref_price
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
            EngineError: `bracket` sem `kind = LIMIT`/`STOP` ou sem os dois
                preços (ordem malformada — erro de programação).
        """
        if order.bracket:
            if order.kind is OrderKind.STOP:
                # 2b (T07): bracket de ENTRADA por buy-stop — par (buy-stop
                # S_e + sell-stop protetor S_s), mesmos intent_seq/decision_date.
                # `order.stop` = S_e (gatilho de entrada, convert), `order.limit`
                # = S_s (o protetor — overload documentado no convert).
                if order.limit is None or order.stop is None:
                    raise EngineError(
                        "place: bracket de buy-stop malformado — exige stop (S_e) "
                        "e limit carregando o protetor (S_s)."
                    )
                store.place(
                    PendingOrder(
                        ticker=order.ticker,
                        kind=OrderKind.STOP,
                        side=Side.BUY,
                        limit=None,
                        stop=order.stop,
                        qty=order.qty,
                        decision_date=order.decision_date,
                        intent_seq=order.intent_seq,
                        bracket=True,
                        cut_reason=order.cut_reason,
                    )
                )
                store.place(
                    PendingOrder(
                        ticker=order.ticker,
                        kind=OrderKind.STOP,
                        side=Side.SELL,
                        limit=None,
                        stop=order.limit,
                        qty=order.qty,
                        decision_date=order.decision_date,
                        intent_seq=order.intent_seq,
                        bracket=True,
                        cut_reason=order.cut_reason,
                    )
                )
                return
            if order.kind is not OrderKind.LIMIT or order.limit is None or order.stop is None:
                raise EngineError(
                    "place: ordem bracket malformada — exige kind=LIMIT com limit e stop."
                )
            store.place(
                PendingOrder(
                    ticker=order.ticker,
                    kind=OrderKind.LIMIT,
                    side=Side.BUY,
                    limit=order.limit,
                    stop=None,
                    qty=order.qty,
                    decision_date=order.decision_date,
                    intent_seq=order.intent_seq,
                    bracket=True,
                    cut_reason=order.cut_reason,
                )
            )
            store.place(
                PendingOrder(
                    ticker=order.ticker,
                    kind=OrderKind.STOP,
                    side=Side.SELL,
                    limit=None,
                    stop=order.stop,
                    qty=order.qty,
                    decision_date=order.decision_date,
                    intent_seq=order.intent_seq,
                    bracket=True,
                    cut_reason=order.cut_reason,
                )
            )
            return

        # 2b (emenda T08a, SHT-01.2/02.1): `ConvertedOrder.qty` carrega o
        # SINAL do alvo (negativo em ENTER_SHORT); o side é DERIVADO aqui e o
        # `PendingOrder.qty` vira a MAGNITUDE positiva — a negatividade nasce
        # no Position/Trade (o executor short usa `order.qty` como magnitude).
        if order.qty > 0:
            side = Side.BUY
            qty = order.qty
        else:
            side = Side.SELL
            qty = -order.qty
        store.place(
            PendingOrder(
                ticker=order.ticker,
                kind=order.kind,
                side=side,
                limit=order.limit,
                stop=order.stop,
                qty=qty,
                decision_date=order.decision_date,
                intent_seq=order.intent_seq,
                bracket=False,
                cut_reason=order.cut_reason,
            )
        )

    def cancel_all(self, store: PendingBook, ticker: str) -> None:
        """EXIT cancela TODAS as pendentes do ativo, incluindo stops (ORD-04.1)."""

        store.cancel_all(ticker)

    def execute_pending(
        self,
        store: PendingBook,
        ticker: str,
        bar: BarSlice,
        portfolio: Portfolio,
        cost_model: CostModel,
        slippage: SlippageModel,
        adv: float | None,
        counters: MechanismCounters | None = None,
    ) -> list[Trade]:
        """Executa as pendentes de X contra a barra do PRÓPRIO ativo (T08).

        Regras de preço (design §3.5, emenda T08):

        - MARKET (BUY): ``open`` + slippage (SLP-04.1); a quantidade é
          cortada para caber no caixa (invariante ``cash >= 0``); sem caixa
          para 1 ação ⇒ não preenche, logada e consumida;
        - LIMIT BUY: ``low <= L`` ⇒ preenche a ``min(L, open)``; senão
          CANCELA ao fim da barra (ORD-01.1/01.3) — SEM slippage, o limite
          nunca é violado (SLP-04.2);
        - LIMIT SELL (take-profit): ``high >= L`` ⇒ preenche a
          ``max(L, open)``; senão cancela (ORD-01.2);
        - STOP (SELL-stop): só com posição aberta (ORD-02.2); ``low <= S`` ⇒
          vira mercado a ``min(S, open)`` + slippage (ORD-02.1/SLP-04.4),
          vende a posição inteira (D3); não disparado ⇒ PERMANECE pendente
          (persiste entre barras); sem posição ⇒ permanece (nunca ativa).

        Custos debitados do caixa, FORA do preço de execução (SLP-04.3);
        `origin` no Trade (auditoria do ENG-01.2, ORD-04.4); gap de pregões
        = ``bar.date - decision_date`` (Fase 1). Brackets (pares limite+stop
        da mesma intenção) resolvem a ambiguidade intrabarra por pior caso
        (ADR-0007/D2, `ambiguous=True`; sem stop órfão). O atendimento
        alfabético entre ativos é de T11b.

        Returns:
            Trades criados (entradas e saídas executadas nesta barra).

        Raises:
            EngineError: preço não positivo ou barra malformada.
        """
        if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
            raise EngineError(f"execute_pending: barra com preço não positivo em {ticker}.")
        if bar.high < bar.low:
            raise EngineError(f"execute_pending: barra malformada (high < low) em {ticker}.")

        trades: list[Trade] = []
        remaining: list[PendingOrder] = []
        consumed_seq: set[int] = set()

        for order in store.pending_for(ticker):
            if order.intent_seq in consumed_seq:
                continue  # par de bracket já resolvido acima

            if order.bracket and order.kind is OrderKind.STOP and order.side is Side.BUY:
                # 2b (T07): bracket de ENTRADA por buy-stop — par (buy-stop
                # S_e + sell-stop protetor S_s), resolvido JUNTO (ADR-0007
                # estendido: pior caso quando ambos tocam na mesma barra).
                partner = next(
                    (
                        o
                        for o in store.pending_for(ticker)
                        if o.intent_seq == order.intent_seq
                        and o.kind is OrderKind.STOP
                        and o.side is Side.SELL
                    ),
                    None,
                )
                consumed_seq.add(order.intent_seq)
                self._execute_entry_buy_stop_bracket(
                    store,
                    ticker,
                    order,
                    partner,
                    bar,
                    portfolio,
                    cost_model,
                    slippage,
                    adv,
                    trades,
                    remaining,
                    counters,
                )
                continue

            if order.bracket and order.kind is OrderKind.LIMIT:
                # O par de bracket (mesma intenção) é resolvido JUNTO — a
                # ambiguidade intrabarra (ADR-0007/D2) e o "sem stop órfão"
                # dependem de enxergar os dois lados na mesma barra.
                partner = next(
                    (
                        o
                        for o in store.pending_for(ticker)
                        if o.intent_seq == order.intent_seq and o.kind is OrderKind.STOP
                    ),
                    None,
                )
                consumed_seq.add(order.intent_seq)
                if order.side is Side.BUY:
                    position = portfolio.positions.get(ticker)
                    if position is not None and position.quantity < 0:
                        # 2b (T07): bracket SHORT de saída (TP buy-limit + SL
                        # buy-stop sobre posição short) — pior caso coberto no
                        # SL, nunca no TP (CA-06.2).
                        self._execute_short_exit_bracket(
                            store,
                            ticker,
                            order,
                            partner,
                            bar,
                            portfolio,
                            cost_model,
                            slippage,
                            adv,
                            trades,
                            remaining,
                            counters,
                        )
                    else:
                        self._execute_entry_bracket(
                            store,
                            ticker,
                            order,
                            partner,
                            bar,
                            portfolio,
                            cost_model,
                            slippage,
                            adv,
                            trades,
                            remaining,
                            counters,
                        )
                else:
                    self._execute_exit_bracket(
                        store,
                        ticker,
                        order,
                        partner,
                        bar,
                        portfolio,
                        cost_model,
                        slippage,
                        adv,
                        trades,
                        remaining,
                        counters,
                    )
                continue

            if order.side is Side.BUY and order.kind is OrderKind.STOP:
                # 2b (T06): buy-stop — `high >= S` ⇒ compra a `max(S, open)` +
                # slippage de compra (CA-05.1); não disparado ⇒ PERMANECE
                # pendente (CA-05.2); nunca debita caixa antes (CA-05.3).
                # Ativação por side x ENG-05 (tabela §3.5): flat ⇒ entrada
                # long; LONG aberta ⇒ guard ignora e CONSUME; SHORT aberta ⇒
                # cobertura do stop-loss (reduz |qty|, nunca cruza).
                executed, persist = self._execute_buy_stop(
                    store,
                    ticker,
                    order,
                    bar,
                    portfolio,
                    cost_model,
                    slippage,
                    adv,
                    counters=counters,
                )
                if executed is not None:
                    trades.append(executed)
                if persist:
                    remaining.append(order)
                continue

            if order.side is Side.BUY:
                executed = self._execute_entry(
                    store,
                    ticker,
                    order,
                    bar,
                    portfolio,
                    cost_model,
                    slippage,
                    adv,
                    counters=counters,
                )
                if executed is not None:
                    trades.append(executed)
                # Entrada é consumida: preencheu ou foi cancelada/descartada.
                continue

            # side == SELL
            if order.kind is OrderKind.STOP:
                stop_price = order.stop
                if stop_price is None:
                    raise EngineError(
                        f"execute_pending: stop pendente sem preço em {ticker} — "
                        "ordem malformada (programming error)."
                    )
                position = portfolio.positions.get(ticker)
                if position is None or position.quantity < 0:
                    # ORD-02.2: sem posição aberta, o stop NUNCA ativa — e
                    # permanece pendente (protege a entrada quando ela encher).
                    # 2b (T02): com posição SHORT aberta também permanece —
                    # "vender mais short" sem intenção ENTER_SHORT não existe
                    # (espelho do ORD-02.2, tabela de ativação por side §3.5).
                    remaining.append(order)
                    continue
                if bar.low <= stop_price:
                    ref = min(stop_price, bar.open)
                    price = slippage.execution_price(ref, Side.SELL, position.quantity, adv)
                    closed = self.sell(
                        portfolio,
                        ticker=ticker,
                        price=price,
                        execution_date=bar.date,
                        decision_date=order.decision_date,
                        origin=TradeOrigin.STOP,
                    )
                    assert closed is not None  # posição existe — sell nunca devolve None aqui
                    trades.append(closed)
                    # Stop disparado é consumido.
                else:
                    remaining.append(order)  # persiste entre barras
                continue

            if order.kind is OrderKind.LIMIT:
                limit_price = order.limit
                if limit_price is None:
                    raise EngineError(
                        f"execute_pending: limite de venda sem preço em {ticker} — "
                        "ordem malformada (programming error)."
                    )
                position = portfolio.positions.get(ticker)
                if position is not None and position.quantity < 0:
                    # 2b: LIMIT de venda só existe como take-profit de LONG; com
                    # short aberto seria "vender mais short" via limite — não é
                    # constructo da 2b (short entra a mercado por ENTER_SHORT).
                    raise EngineError(
                        f"execute_pending: limite de venda em {ticker} com posição "
                        "short aberta — take-profit de short é buy-limit (T02/RF-SHT-02)."
                    )
                if bar.high >= limit_price:
                    price = max(limit_price, bar.open)  # ORD-01.2, sem slippage
                    closed = self.sell(
                        portfolio,
                        ticker=ticker,
                        price=price,
                        execution_date=bar.date,
                        decision_date=order.decision_date,
                        origin=TradeOrigin.LIMIT,
                    )
                    assert closed is not None  # posição existe — sell nunca devolve None aqui
                    trades.append(closed)
                # Senão cancela ao fim da barra (Q2/ORD-01.3) — consumida.
                continue

            # kind == MARKET com side SELL: ENTER_SHORT (2b, T02 — abre a
            # descoberto) ou ordem SINTÉTICA de rebalance (2a, T11a). De sinal,
            # MARKET de venda da 2a só existia como rebalance; com a 2b o
            # ENTER_SHORT é o caminho real (SHT-02.1).
            if order.rebalance:
                position = portfolio.positions.get(ticker)
                if position is not None:
                    price = slippage.execution_price(bar.open, Side.SELL, position.quantity, adv)
                    closed = self._close_partial(
                        portfolio,
                        ticker=ticker,
                        qty=order.qty,
                        price=price,
                        execution_date=bar.date,
                        decision_date=order.decision_date,
                        origin=TradeOrigin.MARKET,
                        rebalance=True,
                    )
                    if closed is not None:
                        trades.append(closed)
                # sem posição (já saiu por stop/EXIT no mesmo barra): consumida,
                # nada a vender
                continue
            executed = self._execute_entry_short(
                store,
                ticker,
                order,
                bar,
                portfolio,
                cost_model,
                slippage,
                adv,
                counters=counters,
            )
            if executed is not None:
                trades.append(executed)
            # Entrada short é consumida (abriu ou foi ignorada pelo guard).
            continue

        store.orders[ticker] = remaining
        return trades

    def _execute_entry_bracket(
        self,
        store: PendingBook,
        ticker: str,
        limit_order: PendingOrder,
        stop_order: PendingOrder | None,
        bar: BarSlice,
        portfolio: Portfolio,
        cost_model: CostModel,
        slippage: SlippageModel,
        adv: float | None,
        trades: list[Trade],
        remaining: list[PendingOrder],
        counters: MechanismCounters | None = None,
    ) -> None:
        """Bracket de ENTRADA (limite de compra L + sell-stop S) — ADR-0007/D2.

        - ``low <= S`` (⇒ ``low <= L``, pois ``S < L``): AMBIGUIDADE — a
          posição **abre em L** e **fecha no stop S** na mesma barra (fills
          nos preços das ordens, sem slippage — tabela D2); perda realizada
          ``(L - S)`` x qty + custos, fica **flat**, `ambiguous=True`;
        - só o limite tocado (``low <= L``, ``low > S``): entra em
          ``min(L, open)`` (regra normal) e o stop PERMANECE vivo;
        - ``low > L``: o limite CANCELA ao fim da barra (Q2) e o stop do
          MESMO par sai junto — sem stop órfão (a intenção morreu).

        O par é sempre consumido; nunca "ambos executam" (ORD-03.3).
        """
        limit_price = limit_order.limit
        stop_price = stop_order.stop if stop_order is not None else None
        if limit_price is None or stop_price is None:
            raise EngineError(
                f"execute_pending: bracket de entrada malformado em {ticker} — "
                "par sem limite ou sem stop (programming error)."
            )

        if bar.low <= stop_price:
            # Pior caso: abre em L, fecha em S na mesma barra.
            entry = self._execute_entry(
                store,
                ticker,
                limit_order,
                bar,
                portfolio,
                cost_model,
                slippage,
                adv,
                forced_price=limit_price,
                ambiguous=True,
                counters=counters,
            )
            if entry is not None:
                closed = self.sell(
                    portfolio,
                    ticker=ticker,
                    price=stop_price,
                    execution_date=bar.date,
                    decision_date=limit_order.decision_date,
                    origin=TradeOrigin.STOP,
                    ambiguous=True,
                )
                assert closed is not None  # posição acabou de abrir
                trades.append(closed)  # o fechado substituiu o aberto no portfolio
            # Sem caixa para 1 ação: nada abre; o par morre igualmente.
            return

        if bar.low <= limit_price:
            # Só o limite tocou: entrada normal; o stop segue protegendo.
            entry = self._execute_entry(
                store,
                ticker,
                limit_order,
                bar,
                portfolio,
                cost_model,
                slippage,
                adv,
                counters=counters,
            )
            if entry is not None:
                trades.append(entry)
                if stop_order is not None:
                    remaining.append(stop_order)
            return

        # low > L: limite cancela (Q2) — o par inteiro sai (sem stop órfão).

    def _execute_exit_bracket(
        self,
        store: PendingBook,
        ticker: str,
        tp_order: PendingOrder,
        stop_order: PendingOrder | None,
        bar: BarSlice,
        portfolio: Portfolio,
        cost_model: CostModel,
        slippage: SlippageModel,
        adv: float | None,
        trades: list[Trade],
        remaining: list[PendingOrder],
        counters: MechanismCounters | None = None,
    ) -> None:
        """Bracket de SAÍDA (take-profit limite de venda TP + sell-stop S)
        sobre posição aberta — ADR-0007/D2.

        - ``high >= TP`` E ``low <= S``: AMBIGUIDADE — o **stop preenche em
          S** (pior que o TP, preço da ordem, sem slippage), `ambiguous=True`;
          o TP NÃO preenche (nunca ambos executam — ORD-03.3);
        - só o TP tocado: preenche em ``max(TP, open)`` (ORD-01.2) e o stop
          sai junto (posição fechada);
        - só o stop tocado: dispara em ``min(S, open)`` + slippage (regra
          normal, ORD-02.1) e o TP sai junto (cancela ao fim da barra, Q2);
        - nenhum tocado: o TP cancela (Q2) e o stop PERMANECE protegendo.
        """
        tp_price = tp_order.limit
        stop_price = stop_order.stop if stop_order is not None else None
        if tp_price is None or stop_price is None:
            raise EngineError(
                f"execute_pending: bracket de saída malformado em {ticker} — "
                "par sem limite ou sem stop (programming error)."
            )

        if bar.low <= stop_price and bar.high >= tp_price:
            closed = self.sell(
                portfolio,
                ticker=ticker,
                price=stop_price,
                execution_date=bar.date,
                decision_date=tp_order.decision_date,
                origin=TradeOrigin.STOP,
                ambiguous=True,
            )
            assert closed is not None  # posição aberta (pré-condição do par)
            trades.append(closed)
            return

        if bar.high >= tp_price:
            # Só o take-profit tocou: preenche; o par se completa (sem stop
            # sobre posição já fechada).
            closed = self.sell(
                portfolio,
                ticker=ticker,
                price=max(tp_price, bar.open),
                execution_date=bar.date,
                decision_date=tp_order.decision_date,
                origin=TradeOrigin.LIMIT,
            )
            assert closed is not None  # posição aberta (pré-condição do par)
            trades.append(closed)
            return

        if bar.low <= stop_price:
            # Só o stop tocou: regra normal do sell-stop (min(S, open) +
            # slippage); o TP cancela ao fim da barra (Q2).
            position = portfolio.positions.get(ticker)
            assert position is not None  # posição aberta (pré-condição do par)
            ref = min(stop_price, bar.open)
            price = slippage.execution_price(ref, Side.SELL, position.quantity, adv)
            closed = self.sell(
                portfolio,
                ticker=ticker,
                price=price,
                execution_date=bar.date,
                decision_date=tp_order.decision_date,
                origin=TradeOrigin.STOP,
            )
            assert closed is not None
            trades.append(closed)
            return

        # Nenhum tocado: TP cancela (Q2); o stop persiste protegendo.
        if stop_order is not None:
            remaining.append(stop_order)

    def _execute_entry_buy_stop_bracket(
        self,
        store: PendingBook,
        ticker: str,
        buy_stop: PendingOrder,
        stop_order: PendingOrder | None,
        bar: BarSlice,
        portfolio: Portfolio,
        cost_model: CostModel,
        slippage: SlippageModel,
        adv: float | None,
        trades: list[Trade],
        remaining: list[PendingOrder],
        counters: MechanismCounters | None = None,
    ) -> None:
        """Bracket de ENTRADA por buy-stop (S_e + sell-stop protetor S_s,
        S_s < S_e) — ADR-0007 estendido (2b, T07, RF-ORD-06 CA-06.1).

        - ambos tocados (``high >= S_e`` E ``low <= S_s``): AMBIGUIDADE — a
          posição **abre no buy-stop S_e** e **fecha no sell-stop S_s na
          mesma barra** (fills nos preços das ordens, sem slippage — tabela
          D2 do design §4); perda realizada ``(S_e - S_s) x qty + custos``,
          fica **flat**, `ambiguous=True`;
        - só o buy-stop tocou: entrada normal (``max(S_e, open)`` + slippage
          de compra, regra do ORD-05) e o protetor PERMANECE pendente;
        - buy-stop não disparou: o PAR PERMANECE pendente — o buy-stop é
          entrada condicional PERSISTENTE (CA-05.2) e o sell-stop continua
          incapaz de ativar sem posição (ORD-02.2): sem stop órfão, o par
          anda junto (design §4, herança T09);
        - guard ENG-05 (emenda P1): posição LONG aberta ⇒ ignora e CONSUME
          o par inteiro (nunca duas posições do mesmo sinal).

        O par é sempre consumido do book; nunca "ambos executam" na
        sequência favorável (CA-03.3).
        """
        position = portfolio.positions.get(ticker)
        if position is not None and position.quantity > 0:
            _log.info(
                "engine.enter_with_open_position",
                ticker=ticker,
                date=bar.date.isoformat(),
            )
            return  # guard consome o par inteiro
        entry_price = buy_stop.stop
        stop_price = stop_order.stop if stop_order is not None else None
        if entry_price is None or stop_price is None:
            raise EngineError(
                f"execute_pending: bracket de buy-stop malformado em {ticker} — "
                "par sem gatilho ou sem protetor (programming error)."
            )

        if bar.high >= entry_price and bar.low <= stop_price:
            # Pior caso: abre em S_e, fecha em S_s na mesma barra.
            entry = self._execute_entry(
                store,
                ticker,
                buy_stop,
                bar,
                portfolio,
                cost_model,
                slippage,
                adv,
                forced_price=entry_price,
                ambiguous=True,
                counters=counters,
            )
            if entry is not None:
                closed = self.sell(
                    portfolio,
                    ticker=ticker,
                    price=stop_price,
                    execution_date=bar.date,
                    decision_date=buy_stop.decision_date,
                    origin=TradeOrigin.STOP,
                    ambiguous=True,
                )
                assert closed is not None  # posição acabou de abrir
                trades.append(closed)  # o fechado substituiu o aberto no portfolio
            # Sem caixa para 1 ação: nada abre; o par morre igualmente.
            return

        if bar.high >= entry_price:
            # Só o buy-stop tocou: entrada normal (regra do ORD-05: max(S_e,
            # open) + slippage de COMPRA) — `_execute_entry` não aceita kind
            # STOP direto (barrado por convert), então o preço já slipado é
            # passado como forced_price; o protetor segue vivo.
            dispatch = max(entry_price, bar.open)
            slipped = slippage.execution_price(dispatch, Side.BUY, buy_stop.qty, adv)
            entry = self._execute_entry(
                store,
                ticker,
                buy_stop,
                bar,
                portfolio,
                cost_model,
                slippage,
                adv,
                forced_price=slipped,
                counters=counters,
            )
            if entry is not None:
                trades.append(entry)
                if stop_order is not None:
                    remaining.append(stop_order)
            # Entrada sem caixa (None): a intenção morre — o par sai junto.
            return

        # Buy-stop não disparou: o par permanece pendente (CA-05.2 + sem
        # stop órfão — o sell-stop nunca ativa sem posição, ORD-02.2).
        remaining.append(buy_stop)
        if stop_order is not None:
            remaining.append(stop_order)

    def _execute_short_exit_bracket(
        self,
        store: PendingBook,
        ticker: str,
        tp_order: PendingOrder,
        stop_order: PendingOrder | None,
        bar: BarSlice,
        portfolio: Portfolio,
        cost_model: CostModel,
        slippage: SlippageModel,
        adv: float | None,
        trades: list[Trade],
        remaining: list[PendingOrder],
        counters: MechanismCounters | None = None,
    ) -> None:
        """Bracket de SAÍDA de short (take-profit buy-limit TP + stop-loss
        buy-stop SL, SL > TP) sobre posição short aberta — ADR-0007 estendido
        (2b, T07, RF-ORD-06 CA-06.2).

        - ``high >= SL`` E ``low <= TP``: AMBIGUIDADE — o short é **coberto
          no buy-stop SL** (pior caso, preço da ordem, sem slippage),
          `ambiguous=True`; o limite NUNCA preenche (CA-06.2 — nunca ambos
          executam, CA-03.3);
        - só o SL tocou (``high >= SL``, ``low > TP``): cobertura a
          ``max(SL, open)`` + slippage de compra (regra do ORD-05); o TP
          cancela ao fim da barra (Q2);
        - só o TP tocou (``low <= TP``, ``high < SL``): cobertura a
          ``min(TP, open)`` (limite nunca violado, SLP-04.2); o SL cancela
          (posição fechada);
        - nenhum tocado: o TP cancela (Q2) e o SL PERMANECE protegendo
          (espelho do bracket de saída da 2a).
        """
        tp_price = tp_order.limit
        stop_price = stop_order.stop if stop_order is not None else None
        if tp_price is None or stop_price is None:
            raise EngineError(
                f"execute_pending: bracket short malformado em {ticker} — "
                "par sem take-profit ou sem stop-loss (programming error)."
            )

        if bar.high >= stop_price and bar.low <= tp_price:
            closed = self.cover(
                portfolio,
                ticker=ticker,
                price=stop_price,
                execution_date=bar.date,
                decision_date=tp_order.decision_date,
                origin=TradeOrigin.STOP,
                ambiguous=True,
            )
            assert closed is not None  # posição short aberta (pré-condição do par)
            trades.append(closed)
            return

        if bar.high >= stop_price:
            # Só o stop-loss tocou: regra normal do buy-stop (max(SL, open) +
            # slippage de compra); o TP cancela ao fim da barra (Q2).
            assert stop_order is not None  # stop_price derivou de stop_order (guard acima)
            ref = max(stop_price, bar.open)
            price = slippage.execution_price(ref, Side.BUY, stop_order.qty, adv)
            closed = self.cover(
                portfolio,
                ticker=ticker,
                price=price,
                execution_date=bar.date,
                decision_date=tp_order.decision_date,
                origin=TradeOrigin.STOP,
            )
            assert closed is not None
            trades.append(closed)
            return

        if bar.low <= tp_price:
            # Só o take-profit tocou: cobertura a min(TP, open) — o limite
            # nunca é violado (SLP-04.2); o SL cancela (posição fechada).
            closed = self.cover(
                portfolio,
                ticker=ticker,
                price=min(tp_price, bar.open),
                execution_date=bar.date,
                decision_date=tp_order.decision_date,
                origin=TradeOrigin.LIMIT,
            )
            assert closed is not None
            trades.append(closed)
            return

        # Nenhum tocado: TP cancela (Q2); o SL persiste protegendo.
        if stop_order is not None:
            remaining.append(stop_order)

    def _close_partial(
        self,
        portfolio: Portfolio,
        *,
        ticker: str,
        qty: int,
        price: float,
        execution_date: date,
        decision_date: date,
        origin: TradeOrigin | None = None,
        rebalance: bool = True,
        ambiguous: bool | None = None,
    ) -> Trade | None:
        """Redução PARCIAL da posição aberta — venda de LONG (rebalance, 2a) ou
        COBERTURA de SHORT (2b, T02).

        O modelo de Trade da Fase 1 é round-trip com quantidade fixa; a
        redução parcial divide a operação em dois trades: o trecho FECHADO
        fecha agora (entry/exit completos, custos rateados pelo trecho) e o
        trecho restante continua aberto com a quantidade reduzida
        (``dataclasses.replace`` na lista de trades + substituição da
        `Position` no dicionário — os dois objetos são frozen, o estado
        mutável é o portfolio).

        2b (T02): sinal-ciente. `qty` é sempre a MAGNITUDE fechada; long ⇒
        venda (caixa += notional - custo, quantity do trecho fechado POSITIVA),
        short ⇒ cobertura (caixa -= notional + custo, quantity do trecho
        fechado NEGATIVA — SHT-02.2, nunca cruza de sinal). `qty` maior que a
        posição reduz a posição inteira (clamp); `qty < 1` ou posição
        inexistente ⇒ ``None`` (ordem consumida sem efeito). Custos debitados
        do caixa, fora do preço (SLP-04.3).
        """
        position = portfolio.positions.get(ticker)
        if position is None or qty < 1:
            return None
        sign = 1 if position.quantity > 0 else -1
        qty = min(qty, abs(position.quantity))

        open_index = next(
            (
                i
                for i in range(len(portfolio.trades) - 1, -1, -1)
                if portfolio.trades[i].ticker == ticker and portfolio.trades[i].is_open
            ),
            None,
        )
        if open_index is None:
            raise EngineError(
                f"_close_partial: posição em {ticker} sem trade aberto correspondente "
                "— erro de programação (invariante do portfolio)."
            )
        open_trade = portfolio.trades[open_index]

        notional = qty * price
        cost = self._costs.cost_for(notional)
        if sign > 0:
            portfolio.cash += notional - cost  # long: venda
        else:
            portfolio.cash -= notional + cost  # short: cobertura (compra)

        remaining = position.quantity - sign * qty
        if remaining == 0:
            # Ajuste cobre a posição inteira — fecha como a `sell`/`cover`.
            del portfolio.positions[ticker]
            closed = self._close_trade(
                portfolio,
                ticker=ticker,
                price=price,
                cost=cost,
                execution_date=execution_date,
                decision_date=decision_date,
                origin=origin,
                rebalance=rebalance,
                ambiguous=ambiguous,
            )
        else:
            portfolio.positions[ticker] = Position(
                ticker=ticker,
                quantity=remaining,
                entry_price=position.entry_price,
                entry_date=position.entry_date,
            )
            # Rateia o custo de entrada pelos dois trechos (identidade de
            # conciliação fecha: soma dos entry_cost = total pago).
            share = qty / (abs(position.quantity) or 1)
            portfolio.trades[open_index] = replace(
                open_trade,
                quantity=remaining,
                entry_cost=open_trade.entry_cost * (1.0 - share),
            )
            closed = Trade(
                ticker=ticker,
                entry_date=open_trade.entry_date,
                entry_price=open_trade.entry_price,
                entry_decision_date=open_trade.entry_decision_date,
                quantity=sign * qty,
                entry_cost=open_trade.entry_cost * share,
                entry_gap_days=open_trade.entry_gap_days,
                exit_date=execution_date,
                exit_price=price,
                exit_cost=cost,
                exit_gap_days=(execution_date - decision_date).days,
                exit_decision_date=decision_date,
                origin=origin,
                cut_reason=open_trade.cut_reason,
                ambiguous=ambiguous if ambiguous is not None else open_trade.ambiguous,
                rebalance=rebalance,
            )
            portfolio.trades.append(closed)

        portfolio.check_invariants()
        return closed

    def _execute_entry(
        self,
        store: PendingBook,
        ticker: str,
        order: PendingOrder,
        bar: BarSlice,
        portfolio: Portfolio,
        cost_model: CostModel,
        slippage: SlippageModel,
        adv: float | None,
        forced_price: float | None = None,
        ambiguous: bool = False,
        counters: MechanismCounters | None = None,
    ) -> Trade | None:
        """Executa uma entrada (BUY) — mercado ou limite — e a consome.

        Preço: MARKET ⇒ ``open`` + slippage (SLP-04.1); LIMIT ⇒
        ``min(L, open)`` quando ``low <= L``, senão cancela ao fim da barra
        (ORD-01.1/01.3) sem slippage (SLP-04.2). `forced_price` (T09) impõe
        o preço da ordem na ambiguidade intrabarra (abre em L, ADR-0007);
        `ambiguous` marca o trade (entrada do pior caso). A quantidade é
        cortada para caber no caixa após o custo (``cash >= 0``); se o corte
        acontece aqui, o `cut_reason` vira CASH (a última etapa que cortou).
        """
        position = portfolio.positions.get(ticker)
        if position is not None and position.quantity < 0:
            # 2b (T02): BUY sobre posição SHORT aberta é COBERTURA — compra
            # que reduz |qty| até 0, NUNCA cruza de sinal (SHT-02.2). Cobre
            # também o buy-limit de take-profit do bracket short (CA-02.4).
            return self._execute_cover(
                store,
                ticker,
                order,
                bar,
                portfolio,
                cost_model,
                slippage,
                adv,
                counters=counters,
            )
        if position is not None and not order.rebalance:
            # ENG-05 da Fase 1: ENTER com posição aberta é ignorado e logado.
            # Exceção: ordem SINTÉTICA de rebalance (SIZ-03/T11a) ajusta uma
            # posição EXISTENTE — o guard não se aplica.
            _log.info(
                "engine.enter_with_open_position",
                ticker=ticker,
                date=bar.date.isoformat(),
            )
            return None

        if forced_price is not None:
            price = forced_price
        elif order.kind is OrderKind.MARKET:
            price = slippage.execution_price(bar.open, Side.BUY, order.qty, adv)
        elif order.kind is OrderKind.LIMIT:
            limit_price = order.limit
            if limit_price is None:
                raise EngineError(
                    f"execute_pending: limite de compra sem preço em {ticker} — "
                    "ordem malformada (programming error)."
                )
            if bar.low > limit_price:
                _log.info(
                    "engine.limit_not_filled_cancelled",
                    ticker=ticker,
                    date=bar.date.isoformat(),
                    limit=limit_price,
                    low=bar.low,
                )
                return None
            price = min(limit_price, bar.open)  # SLP-04.2: preço <= L
        else:
            raise EngineError(  # pragma: no cover - barrado por convert (buy-stop)
                f"execute_pending: entrada {order.kind} inválida em {ticker}."
            )

        qty = min(order.qty, _affordable_quantity(portfolio.cash, price, cost_model))
        if qty < 1:
            if counters is not None:
                counters.unfilled_cash_orders += 1
            _log.info(
                "engine.insufficient_cash",
                ticker=ticker,
                date=bar.date.isoformat(),
                cash=portfolio.cash,
                price=price,
            )
            return None

        cut_reason = order.cut_reason
        if qty < order.qty:
            cut_reason = CutStage.CASH  # o corte de caixa na execução é o último

        notional = qty * price
        cost = cost_model.cost_for(notional)
        portfolio.cash -= notional + cost
        portfolio.positions[ticker] = Position(
            ticker=ticker,
            quantity=qty,
            entry_price=price,
            entry_date=bar.date,
        )
        trade = Trade(
            ticker=ticker,
            entry_date=bar.date,
            entry_price=price,
            entry_decision_date=order.decision_date,
            quantity=qty,
            entry_cost=cost,
            entry_gap_days=(bar.date - order.decision_date).days,
            origin=TradeOrigin(order.kind.value),  # valores idênticos — compat 2a (T01)
            cut_reason=cut_reason,
            ambiguous=ambiguous,
            rebalance=order.rebalance,
        )
        portfolio.trades.append(trade)
        portfolio.check_invariants()
        return trade

    def _execute_entry_short(
        self,
        store: PendingBook,
        ticker: str,
        order: PendingOrder,
        bar: BarSlice,
        portfolio: Portfolio,
        cost_model: CostModel,
        slippage: SlippageModel,
        adv: float | None,
        counters: MechanismCounters | None = None,
    ) -> Trade | None:
        """Abre uma posição SHORT a mercado (2b, T02 — SHT-02.1).

        Venda a ``open`` com slippage de VENDA (``open x (1 - bps)`` — direção
        desfavorável ao vendedor), abrindo ``qty < 0``; custos debitados do
        caixa (SLP-04.3), fora do preço. A venda CREDITA o caixa (proceeds -
        custo) — o limite é a margem (laço, T04/T08a), não o caixa.

        Guard (decisão local, ENG-05 da Fase 1 estendido): com posição LONG
        aberta no ticker, o ENTER_SHORT é ignorado e CONSUMIDO (log) — o
        modelo não cruza de sinal num único trade; a estratégia deve EXIT
        antes de ENTER_SHORT. Com short aberto, idem (uma posição por ticker,
        sem média de preço — espelho do ENTER da 2a).
        """
        if ticker in portfolio.positions:
            _log.info(
                "engine.enter_short_with_open_position",
                ticker=ticker,
                date=bar.date.isoformat(),
            )
            return None

        price = slippage.execution_price(bar.open, Side.SELL, order.qty, adv)
        qty = order.qty
        cut_reason = order.cut_reason

        notional = qty * price
        cost = cost_model.cost_for(notional)
        portfolio.cash += notional - cost
        portfolio.positions[ticker] = Position(
            ticker=ticker,
            quantity=-qty,
            entry_price=price,
            entry_date=bar.date,
        )
        trade = Trade(
            ticker=ticker,
            entry_date=bar.date,
            entry_price=price,
            entry_decision_date=order.decision_date,
            quantity=-qty,
            entry_cost=cost,
            entry_gap_days=(bar.date - order.decision_date).days,
            origin=TradeOrigin.MARKET,
            cut_reason=cut_reason,
        )
        portfolio.trades.append(trade)
        portfolio.check_invariants()
        return trade

    def _execute_buy_stop(
        self,
        store: PendingBook,
        ticker: str,
        order: PendingOrder,
        bar: BarSlice,
        portfolio: Portfolio,
        cost_model: CostModel,
        slippage: SlippageModel,
        adv: float | None,
        counters: MechanismCounters | None = None,
    ) -> tuple[Trade | None, bool]:
        """Buy-stop (2b, T06 — RF-ORD-05) — devolve ``(trade, persistir)``.

        Dispara quando ``high[i] >= S`` e executa a ``max(S, open[i])`` com
        slippage de COMPRA (CA-05.1); não disparado ⇒ PERMANECE pendente para
        a próxima barra do próprio ativo (CA-05.2, ADR-0002); nunca debita
        caixa antes de disparar (CA-05.3).

        Ativação por side x guard ENG-05 (emenda P1, tabela §3.5):
        - posição LONG aberta ⇒ guard ignora e CONSUME (log, como ENTER) —
          nunca duas posições do mesmo sinal;
        - posição SHORT aberta ⇒ ativa como COBERTURA do stop-loss (reduz
          |qty| até 0, nunca cruza — SHT-02.2; ORD-06/CA-06.2);
        - flat ⇒ entrada long.
        """
        position = portfolio.positions.get(ticker)
        if position is not None and position.quantity > 0:
            _log.info(
                "engine.enter_with_open_position",
                ticker=ticker,
                date=bar.date.isoformat(),
            )
            return None, False  # consumida pelo guard
        stop_price = order.stop
        if stop_price is None:
            raise EngineError(
                f"execute_pending: buy-stop sem preço em {ticker} — "
                "ordem malformada (programming error)."
            )
        if bar.high < stop_price:
            return None, True  # não disparou — persiste (CA-05.2)
        dispatch_price = max(stop_price, bar.open)  # CA-05.1
        if position is not None and position.quantity < 0:
            return (
                self._execute_cover(
                    store,
                    ticker,
                    order,
                    bar,
                    portfolio,
                    cost_model,
                    slippage,
                    adv,
                    forced_ref=dispatch_price,
                    counters=counters,
                ),
                False,
            )
        slipped = slippage.execution_price(dispatch_price, Side.BUY, order.qty, adv)
        return (
            self._execute_entry(
                store,
                ticker,
                order,
                bar,
                portfolio,
                cost_model,
                slippage,
                adv,
                forced_price=slipped,
                counters=counters,
            ),
            False,
        )

    def _execute_cover(
        self,
        store: PendingBook,
        ticker: str,
        order: PendingOrder,
        bar: BarSlice,
        portfolio: Portfolio,
        cost_model: CostModel,
        slippage: SlippageModel,
        adv: float | None,
        forced_ref: float | None = None,
        counters: MechanismCounters | None = None,
    ) -> Trade | None:
        """Cobertura de posição short — compra que reduz |qty| até 0 (2b, T02).

        Preço: MARKET ⇒ ``open`` + slippage de COMPRA (``open x (1 + bps)`` —
        SHT-02.2); LIMIT BUY ⇒ ``min(L, open)`` quando ``low <= L``, senão
        CANCELA ao fim da barra — o limite NUNCA é violado (CA-02.4/SLP-04.2);
        `forced_ref` (T06) impõe a referência do buy-stop disparado
        (``max(S, open)`` + slippage, SLP-04.4). A quantidade é limitada por
        ``|posição|`` (nunca cruza de sinal — SHT-02.2) e pelo caixa após
        custos (a cobertura consome caixa).
        """
        if order.kind is OrderKind.LIMIT and forced_ref is None:
            limit_price = order.limit
            if limit_price is None:
                raise EngineError(
                    f"execute_pending: limite de compra sem preço em {ticker} — "
                    "ordem malformada (programming error)."
                )
            if bar.low > limit_price:
                _log.info(
                    "engine.limit_not_filled_cancelled",
                    ticker=ticker,
                    date=bar.date.isoformat(),
                    limit=limit_price,
                    low=bar.low,
                )
                return None
            price = min(limit_price, bar.open)  # SLP-04.2 — nunca viola o limite
        else:
            ref = forced_ref if forced_ref is not None else bar.open
            price = slippage.execution_price(ref, Side.BUY, order.qty, adv)

        position = portfolio.positions.get(ticker)
        if position is None or position.quantity >= 0:  # pragma: no cover - guardado pelo chamador
            raise EngineError(
                f"_execute_cover: {ticker} sem posição short aberta — erro de programação."
            )

        qty = min(order.qty, abs(position.quantity))
        qty = min(qty, _affordable_quantity(portfolio.cash, price, cost_model))
        if qty < 1:
            if counters is not None:
                counters.unfilled_cash_orders += 1
            _log.info(
                "engine.insufficient_cash",
                ticker=ticker,
                date=bar.date.isoformat(),
                cash=portfolio.cash,
                price=price,
            )
            return None

        origin = TradeOrigin(order.kind.value)
        return self._close_partial(
            portfolio,
            ticker=ticker,
            qty=qty,
            price=price,
            execution_date=bar.date,
            decision_date=order.decision_date,
            origin=origin,
        )

    def execute_margin_calls(
        self,
        plan: tuple[MarginCallOrder, ...],
        bar: BarSlice,
        portfolio: Portfolio,
        cost_model: CostModel,
        slippage: SlippageModel,
    ) -> list[Trade]:
        """Executa a liquidação forçada do ativo no open do PRÓPRIO ativo
        (2b, T05 — RF-MRG-02/D2, ADR-0002/ADR-0009).

        Cada ordem do plano vira trade com ``origin = MARGIN_CALL``
        (CA-02.3): long ⇒ SELL a mercado (slippage de venda), short ⇒ BUY a
        mercado (cobertura integral, slippage de compra). Liquidação é
        INTEGRAL por ativo (`qty == |posição|` — MRG-02). Custos fora do
        preço (SLP-04.3). Determinístico (CA-02.4 — o plano vem pronto do
        laço, em ordem alfabética; aqui só a execução).

        Raises:
            EngineError: ativo sem posição, `qty` ≠ |posição| (não-integral)
                ou `side` incoerente com o sinal — erro de programação (§3.8).
        """
        if bar.open <= 0:
            raise EngineError(f"execute_margin_calls: open não positivo em {bar.date}.")
        trades: list[Trade] = []
        for order in plan:
            position = portfolio.positions.get(order.ticker)
            if position is None:
                raise EngineError(
                    f"execute_margin_calls: {order.ticker} sem posição aberta — "
                    "plano de liquidação malformado (programming error)."
                )
            if order.qty != abs(position.quantity):
                raise EngineError(
                    f"execute_margin_calls: {order.ticker} plano {order.qty} ≠ "
                    f"|posição| {abs(position.quantity)} — liquidação é INTEGRAL (MRG-02)."
                )
            expected = Side.SELL if position.quantity > 0 else Side.BUY
            if order.side is not expected:
                raise EngineError(
                    f"execute_margin_calls: side {order.side} incoerente com a posição "
                    f"{position.quantity} em {order.ticker} (programming error)."
                )
            price = slippage.execution_price(bar.open, order.side, order.qty, None)
            if position.quantity > 0:
                closed = self.sell(
                    portfolio,
                    ticker=order.ticker,
                    price=price,
                    execution_date=bar.date,
                    decision_date=order.decision_date,
                    origin=TradeOrigin.MARGIN_CALL,
                )
            else:
                closed = self.cover(
                    portfolio,
                    ticker=order.ticker,
                    price=price,
                    execution_date=bar.date,
                    decision_date=order.decision_date,
                    origin=TradeOrigin.MARGIN_CALL,
                )
            assert closed is not None  # posição existia — nunca None aqui
            trades.append(closed)
        return trades

    def cover(
        self,
        portfolio: Portfolio,
        *,
        ticker: str,
        price: float,
        execution_date: date,
        decision_date: date,
        origin: TradeOrigin | None = None,
        ambiguous: bool | None = None,
    ) -> Trade | None:
        """Cobertura INTEGRAL da posição short (2b, T02 — EXIT_SHORT do laço).

        Espelho da ``sell`` da Fase 1 para o lado negativo: compra que zera a
        posição short, debitando notional + custo do caixa. `origin` default
        MARKET (EXIT_SHORT vai por cancel_all + cobertura ao open — T08a);
        `ambiguous` (T07) força o flag na cobertura ambígua do pior caso
        (ADR-0007).
        """
        position = portfolio.positions.get(ticker)
        if position is None or position.quantity >= 0:
            raise EngineError(
                f"Cobertura de {ticker} sem posição short aberta. EXIT_SHORT sem "
                "short é erro de domínio (SHT-01.3/CA-01.3) — erro de programação."
            )

        notional = abs(position.quantity) * price
        cost = self._costs.cost_for(notional)
        portfolio.cash -= notional + cost
        del portfolio.positions[ticker]

        closed = self._close_trade(
            portfolio,
            ticker=ticker,
            price=price,
            cost=cost,
            execution_date=execution_date,
            decision_date=decision_date,
            origin=origin,
            ambiguous=ambiguous,
        )
        portfolio.check_invariants()
        return closed
