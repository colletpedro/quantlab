# Fase 2a — Execução realista e alocação — Design técnico

**Status:** aprovada — gate check 2 concluído
**Versão:** 0.1
**Data:** 2026-08-14
**Requisitos de origem:** `specs/fase-2a-requirements.md` v0.2
**Próximo gate:** `specs/fase-2a-tasks.md`
**ADRs vinculantes:** 0001, 0002, 0003, 0004 (Fase 1); 0005, 0006, 0007, 0008 (aceitos)

> **Convenção de referência:** critérios de aceitação são citados com prefixo da família de requisito — `SLP-03.1` significa CA-03.1 de RF-SLP-03; `ORD-04.3` significa CA-04.3 de RF-ORD-04. Mesma convenção do design v0.9 da Fase 1.

---

## 1. Princípio organizador

O requisito pode ser satisfeito por convenção (quem escreveu lembrou) ou por construção (o código não consegue fazer errado). A Fase 2a mantém a postura da Fase 1: construção onde dá, teste nomeado onde a construção não é possível.

**Por construção nesta fase:**

1. **Anti-lookahead por ativo.** A estratégia de X recebe apenas a `MarketView` do array de X (Fase 1, §4.1) — com a instância por ativo (POR-03.1), o calendário-união jamais aparece para a estratégia: a sequência que ela vê é idêntica à de um run single-asset de X (POR-05.1).
2. **Calendário-união imutável e pré-computado** (decisão D1 da revisão). `bar_index` por ativo alinhado à união, construído em uma passada O(total) — não existe caminho de código que faça busca O(n²) por (data, ativo): a estrutura não tem API de consulta por data, só índice de união.
3. **Fronteira de instante.** Os módulos novos (`calendar`, `liquidity`, `slippage`, `sizing`, `conditional`) e o `broker` estendido não importam `datetime`/`timezone` — a regra do design Fase 1 §3.6 vale sem exceção.
4. **Stop só com posição aberta** (ORD-02.2). A ativação do sell-stop é condicionada no broker, não por convenção da estratégia: um stop cuja entrada nunca preencheu não tem como ativar.

**Por teste nomeado:** o restante — execução condicional vincula-se a ordem preexistente (ENG-01.2 parte 2), fronteira de mutação por ativo, pior caso intrabarra (ADR-0007), invariantes `cash ≥ 0`, `qty ≥ 0`, `k ≤ N`, conciliação multi-ativo, determinismo, RNF-04. Cada um com teste nomeado em §10.

`Signal`/`Strategy` da Fase 1 ficam **intocados** (SIG-01.1): a extensão é um Protocol novo, `ConditionalStrategy`, não uma mudança de contrato.

**Portador de garantia por RF (checklist do gate 2):** nenhum RF fica sem portador explícito — por construção ou por teste nomeado.

| RF | Garantia | Portador |
|---|---|---|
| RF-SLP-01 | por contrato + teste | `test_pluggable_slippage_model_requires_no_broker_change` (CA-01.2); relatório de irrealismo → `test_zero_slippage_declared_unrealistic` (CA-01.3) |
| RF-SLP-02 | por teste (fórmula fechada) | `test_fixed_bps_execution_price` (CA-02.1) |
| RF-SLP-03 | janela de ADV por construção (`adv` pura) + testes | `test_adv_window_is_20_sessions_of_own_asset` (CA-03.1); `test_slippage_monotonic_in_participation`; `test_cap_applies_to_entries_only_and_subshare_cancels` (CA-03.3–03.5) |
| RF-SLP-04 | por construção no broker | `test_limit_price_never_violated_and_market_slippage_only` (CA-04.1/04.2); `test_costs_debited_from_cash_not_in_execution_price` (CA-04.3) |
| RF-ORD-01 | por construção (regra de preenchimento no broker) | `test_limit_fills_at_min_or_max_of_limit_and_open` (CA-01.1/01.2); `test_limit_cancels_at_end_of_bar` (CA-01.3) |
| RF-ORD-02 | por construção (ativação condicionada a posição) | `test_stop_never_activates_without_open_position` (CA-02.2); `test_stop_triggers_market_at_min_stop_open` (CA-02.1) |
| RF-ORD-03 | por teste (pior caso registrado) | `test_intrabar_ambiguity_entry_bracket_worst_case` (CA-03.1/03.3); `test_intrabar_ambiguity_exit_bracket_worst_case` |
| RF-ORD-04 | ciclo de vida por construção no broker + testes | `test_second_entry_sees_cash_already_debited` (CA-04.3); `test_last_intention_wins_replaces_pending` (CA-04.2); `test_exit_cancels_all_pending_including_stops` (CA-04.1); ENG-01.2 parte 2 (CA-04.4) |
| RF-SIG-01 | retrocompatibilidade por construção (Protocol opcional) | `test_fase1_strategy_runs_unchanged_multi_asset` (CA-01.1); `test_bracket_carries_limit_and_stop_in_same_intention` (CA-01.2/01.3) |
| RF-CST-01 | sequência de corte por construção no `convert` | `test_cut_sequence_order_and_reason_recorded` (CA-01.2/01.3) |
| RF-SIZ-01 | plugabilidade por contrato | `test_new_sizer_policy_requires_no_engine_change` (CA-01.1); inteiras cobertas por `test_cut_sequence_order_and_reason_recorded` (CA-01.2) |
| RF-SIZ-02 | por construção (N fixado) + testes | `test_target_is_equity_over_n_fixed_and_n1_is_allin` (CA-02.1/02.3); `test_never_traded_asset_contributes_zero_and_reconciles` (CA-02.4); `test_idle_cash_reported_not_reallocated` (CA-02.2) |
| RF-SIZ-03 | gatilho de k por construção no engine | `test_no_rebalance_without_k_change` (CA-03.1/03.4); `test_rebalance_threshold_pp_gates_adjustment` (CA-03.3); `test_rebalance_trades_counted_separately_from_signal` (CA-03.2) |
| RF-SIZ-04 | fração por contrato; k ≤ N por asserção | `test_sizer_returns_fraction_not_quantity` (CA-04.2); `test_open_positions_never_exceed_n` (CA-04.3) |
| RF-POR-01 | caixa único por construção; atendimento alfabético por construção + teste | `test_alphabetical_serving_with_insufficient_cash` (CA-01.2); contagem → `test_report_mechanism_counters_block` (MET-05) |
| RF-POR-02 | calendário por construção (imutável); mark-to-market por construção | `test_union_calendar_matches_naive_lookup` (CA-02.1); `test_asset_without_bar_is_marked_with_last_close` (CA-02.2); `test_delisted_position_is_locked_and_reported` (CA-02.3); `test_market_view_contains_only_own_asset_bars` (CA-02.4) |
| RF-POR-03 | instâncias independentes por construção | `test_n_independent_strategy_instances_each_see_own_asset` (CA-03.1); `test_fase1_strategy_runs_unchanged_multi_asset` (CA-03.2) |
| RF-POR-04 | invariantes por asserção no laço | `test_equity_identity_multi_asset` (CA-04.1); `test_reconciliation_multi_asset_20_assets` (CA-04.2); `test_cash_and_quantity_never_negative_multi` (CA-04.3) |
| RF-POR-05 | índice por ativo por construção; fronteira por teste | `test_pending_order_executes_at_next_bar_of_own_asset` (CA-05.3); `test_mutation_frontier_is_per_asset` (CA-05.4) |
| RF-MET-01 | por teste | `test_contributions_per_asset_reconcile_with_total_pnl` (CA-01.1); CA-01.2 → fórmulas de RF-MET-04 |
| RF-MET-02 | benchmark por construção (função dedicada) | `test_benchmark_buys_at_first_tradable_bar_per_asset_with_entry_rules` (CA-02.1/02.2); `test_delisted_position_is_locked_and_reported` (CA-02.3) |
| RF-MET-03 | por construção (constante literal) | `test_bias_section_includes_conditional_items` (CA-03.1) |
| RF-MET-04 | por teste (fórmulas fechadas) | `test_turnover_and_exposure_closed_form_fixture` (CA-04.1/04.3/04.4); `test_same_definitions_strategy_and_benchmark` (CA-04.2) |
| RF-MET-05 | por construção (bloco no relatório) | `test_report_mechanism_counters_block` (CA-05.1–05.3) |
| RF-RNF-01 (herança) | por teste/CI | `test_architecture_timezone_imports` (RNF-07); `test_rnf04_harness_measures_compute_only` (CA-01.3); `test_ci_coverage_floor_85` (RNF-02); `test_multi_asset_run_is_deterministic` (RNF-01) |
| RF-CON-01/02/03 (baseline §7) | verificado — S8 | testes da Fase 1 + `docs/STATE.md` 2026-08-06 (não reaberto) |

## 2. Arquitetura

```
 storage/ ── get_series(por ticker) ──▶ PriceSeries × N ──┐
                                                          ▼
   strategies/ ── Signal | ConditionalIntent ──▶ engine/  (multi-ativo)
        ▲         (instância por ativo)            │
        │  MarketView(i próprio do ativo)          │ calendar.py  (UnionCalendar — D1)
        └──────────────────────────────────────────┤
                                                   ▼
            engine/: backtest loop │ broker.py (estendido) │ portfolio.py (estendido)
                     │ calendar.py │ liquidity.py │ slippage.py │ sizing.py │ conditional.py
                     │ (todos dentro de engine/ — D3)
                                                   │ BacktestResult (N ativos)
                                                   ▼
            analytics/: metrics.py (turnover/exposição/contribuição)
                     │ benchmark.py (buy_and_hold_multi) │ report.py (contadores + vieses)
                                                   ▼
            Report (seção "run" ampliada) ──▶ CLI + JSON  (PNG fora do harness RNF-04 — D3)
```

Dependências apontam para dentro, como na Fase 1: `engine/` recebe `PriceSeries` já materializadas e nunca toca Mongo; `strategies/` só conhece contratos. Os módulos novos vivem dentro de `engine/` (decisão D3) — a cobertura de RNF-02 continua sendo `engine/` + `analytics/` ≥ 85%, sem novos pacotes-raiz.

## 3. Contratos tipados

### 3.1 `UnionCalendar` — `engine/calendar.py` (novo, D1)

```python
@dataclass(frozen=True)
class UnionCalendar:
    dates: tuple[date, ...]                     # união ordenada — merge em UMA passada O(total)
    bar_index: dict[str, NDArray[np.int64]]     # por ativo, alinhado a dates: índice do PRÓPRIO array
                                                # na data-união u; -1 sse o ativo não tem barra em u (POR-05.1)
    last_known: dict[str, NDArray[np.int64]]    # por ativo: último índice ≥ 0 com date ≤ dates[u]
                                                # (último close conhecido — POR-02.2); derivado na mesma passada

    @staticmethod
    def build(series: dict[str, PriceSeries]) -> UnionCalendar: ...   # função pura, sem estado mutável

    def has_bar_at(self, ticker: str, u: int) -> bool: ...            # O(1)
    def bar_index_at(self, ticker: str, u: int) -> int | None: ...    # O(1); None sse -1 (POR-05.1)
    def last_known_index_at(self, ticker: str, u: int) -> int | None: ...  # O(1); None sse o ativo ainda não tem barra
```

> **Nomes dos métodos de consulta com sufixo `_at` (emenda T05):** o campo `bar_index` (dict de arrays) e uma consulta não podem dividir o mesmo nome numa classe Python — o método viraria o "default" do campo no dataclass (TypeError na construção). O acesso a campo (`bar_index[X][u]`, usado no fluxo de §4) permanece; as consultas são `has_bar_at`/`bar_index_at`/`last_known_index_at`.

- **Pré-computado e imutável (D1):** os arrays são construídos uma vez por run, em uma passada de merge (algoritmo em §5); `frozen=True` + `flags.writeable = False` nos arrays, mesma política de imutabilidade da `PriceSeries` (design Fase 1 §3.7). **Não há ponteiros mutáveis**: o laço apenas lê índices.
- **Complexidade por construção, não por disciplina:** não existe método que busque "data → ativo"; toda consulta é por índice de união. O guard de O(total) vira **teste de propriedade** (§10), não teste de sequência de chamadas (D1).
- **Memória declarada:** 2 arrays `int64` de tamanho D por ativo (20 ativos × ~2.900 datas × 8 B × 2 ≈ 930 KB) — irrelevante frente ao volume que ADR-0001 dimensiona; a imutabilidade compensa a cópia única.

### 3.2 Estratégias condicionais — `engine/conditional.py` (novo)

```python
class Signal(Enum):                     # intocado — Fase 1
    ENTER = "enter"
    EXIT  = "exit"

class OrderKind(Enum):
    MARKET = "market"
    LIMIT  = "limit"
    STOP   = "stop"

class Side(Enum):                       # vocabulário de execução — T01 (conditional.py); §3.3 importa daqui
    BUY = "buy"
    SELL = "sell"

@dataclass(frozen=True)
class Bracket:
    limit: float    # limite de entrada
    stop: float     # sell-stop protetor — par na MESMA intenção (SIG-01.2)

@dataclass(frozen=True)
class ConditionalIntent:
    signal: Signal
    order_type: OrderKind
    limit: float | None = None      # presente sse order_type == LIMIT
    stop: float | None = None       # presente sse order_type == STOP
    bracket: Bracket | None = None  # presente sse intenção é bracket (limite + stop juntos)

class Strategy(Protocol):            # intocado — Fase 1
    @property
    def warmup(self) -> int: ...
    def on_bar(self, view: MarketView) -> Signal | None: ...

class ConditionalStrategy(Protocol): # opcional — retrocompatível (SIG-01.1)
    @property
    def warmup(self) -> int: ...
    def on_bar(self, view: MarketView) -> Signal | ConditionalIntent | None: ...
```

- **Retrocompatibilidade por construção:** o engine aceita ambos os Protocols; uma estratégia da Fase 1 devolve `Signal`, e o fluxo de conversão a trata como intenção `MARKET` (SIG-01.1). Nenhuma linha de `strategy.py` muda.
- **Pré-condições de `ConditionalIntent`:** `LIMIT` ⇒ `limit` presente; `STOP` ⇒ `stop` presente; `bracket` presente ⇒ par `(limit, stop)` juntos, derivados da mesma intenção (SIG-01.2) — ordens dele compartilham o mesmo `decision_date` (SIG-01.3).
- **Escopo P2:** `STOP` é sempre sell-stop protetor de posição longa; buy-stop e entradas condicionais de compra não existem nesta fase.

### 3.3 Slippage e liquidez — `engine/slippage.py` + `engine/liquidity.py` (novos)

```python
# Side (BUY/SELL) — definido em engine/conditional.py (§3.2); importado aqui.

class SlippageModel(Protocol):
    def execution_price(self, ref: float, side: Side, qty: int, adv: float | None) -> float: ...
    # aplicado SÓ a ordens a mercado e a stops convertidos em mercado (SLP-04.1/04.4)
    # limite NUNCA é violado (SLP-04.2); custos NUNCA entram no preço de execução (SLP-04.3)

@dataclass(frozen=True)
class FixedBps(SlippageModel):
    bps: float
    # execução = ref × (1 ± bps/10000) — SLP-02.1

@dataclass(frozen=True)
class Participation(SlippageModel):
    bps: float = 1.0   # componente base — default determinístico, configurável (ADR-0006)
    k: float = 1.0     # sensibilidade à participação — DEFAULT DETERMINÍSTICO k = 1.0, configurável (ADR-0006)
    # FORMA FUNCIONAL CRAVADA (C2 / ADR-0006):
    #   slippage_bps = bps × (1 + k × q/ADV)     [linear em q/ADV até o cap]
    #   execução = ref × (1 ± slippage_bps/10000)
    # adv is None ⇒ recai em FixedBps com aviso (SLP-03.2), sem falhar
```

```python
# engine/liquidity.py
def adv(series: PriceSeries, i: int, window: int = 20) -> float | None:
    """Média de volume dos 20 pregões do PRÓPRIO ativo terminando na barra i (SLP-03.1).
       None sse histórico insuficiente na janela (SLP-03.2)."""

def participation_cap(qty: int, adv: float, cap: float = 0.10) -> int:
    """Corta a QUANTIDADE de ENTRADA ao teto cap × ADV (SLP-03.3).
       Saídas NÃO passam por aqui — saída integral, D3 da Fase 1 (SLP-03.4).
       Resultado < 1 ⇒ o broker não gera ordem e loga o evento (SLP-03.5)."""
```

- **Separação corte × slippage de preço (SLP-04):** o cap reduz quantidade; o modelo de slippage altera preço; custos debitam do caixa. São três mecanismos, três etapas, registrados separadamente no trade.

### 3.4 Sizing — `engine/sizing.py` (novo)

```python
@dataclass(frozen=True)
class SizingInputs:
    equity: float
    cash: float
    positions: dict[str, int]         # por ativo: ticker → QUANTIDADE (T04)
    last_close: dict[str, float]      # por ativo
    n: int                            # ativos do RUN, fixado no início (SIZ-02.1/P3)

class Sizer(Protocol):
    def target_fraction(self, ticker: str, inputs: SizingInputs) -> float: ...  # devolve FRAÇÃO (SIZ-04.2)

@dataclass(frozen=True)
class FixedOneOverN(Sizer):           # default (ADR-0008)
    n: int
    def target_fraction(self, ticker, inputs) -> float:
        return 1.0 / self.n           # N=1 ⇒ 1.0 = all-in (SIZ-02.3)

@dataclass(frozen=True)
class EqualWeightOpen(Sizer):         # opcional, configurável (SIZ-03)
    threshold_pp: float = 1.0         # limiar |w − 1/k| em pp absolutos do patrimônio (SIZ-03.3)
    def target_fraction(self, ticker, inputs) -> float:
        k = len(inputs.positions)     # posições abertas distintas
        return 1.0 / k                # 1/k (SIZ-03.1); k=0 ⇒ EngineError (1/0 indefinido)

# helper PURO de limiar (SIZ-03.3) — o gatilho (≥ threshold_pp, só em mudança de k) é do laço (T11a)
def rebalance_deviation_pp(weight_fraction: float, k: int) -> float:
    """Desvio |w − 1/k| em pp absolutos do patrimônio."""
```

- **`SizingInputs.positions` é `dict[str, int]` (ticker → quantidade), não `dict[str, Position]` (emenda T04):** o `Position` da Fase 1 (`engine/portfolio.py`) carrega `entry_price`/`entry_date` que o sizer nunca consome — arrastaria data para o módulo folha sem necessidade. O broker (T06) constrói o `SizingInputs` extraindo a quantidade do `Portfolio`; a conversão de fração em quantidade é do broker (SIZ-01.2).
- **Invariante `k ≤ N` (SIZ-04.3):** checada a cada barra pelo laço (§4), como erro de programação — nunca mais posições abertas que ativos no run.

### 3.5 Broker e ciclo de vida de ordens — `engine/broker.py` (estendido)

```python
class CutStage(StrEnum):            # etapa da sequência que cortou (CST-01.3/R1)
    SIZING = "sizing"
    CAP    = "cap"
    INTEGER = "integer"
    CASH   = "cash"

@dataclass(frozen=True)
class ConvertedOrder:               # resultado da conversão — T06 (emenda §3.5)
    ticker: str
    kind: OrderKind
    limit: float | None             # presente sse LIMIT
    stop: float | None              # presente sse STOP
    qty: int
    ref_price: float                # = last_close[ticker] — estimativa na decisão (T06)
    decision_date: date             # base da auditoria do ENG-01.2 (ORD-04.4)
    intent_seq: int                 # "última intenção vence" (ORD-04.2) — do laço (T11a)
    cut_reason: CutStage | None     # última etapa que reduziu; None sse nenhum corte
    est_cost: float                 # custo estimado (max(f + p·N, m)) no ref_price
    bracket: bool                   # originado de bracket — T07 deriva o par stop (ADR-0007)

@dataclass(frozen=True)
class PendingOrder:
    ticker: str
    kind: OrderKind
    limit: float | None       # presente sse LIMIT
    stop: float | None        # presente sse STOP
    qty: int
    decision_date: date       # base da auditoria do ENG-01.2 (ORD-04.4)
    intent_seq: int           # "última intenção vence" (ORD-04.2)
    bracket: bool             # originado de bracket (resolução de ambiguidade — ADR-0007)

class Broker:
    def convert(self, intent: Signal | ConditionalIntent, ticker: str,
                inputs: SizingInputs, sizer: Sizer, adv: float | None,
                cost_model: CostModel, cap: float,
                decision_date: date, intent_seq: int) -> ConvertedOrder | None:
        """SEQUÊNCIA FIXA (R1/CST-01.3):
           SIZING → CAP DE PARTICIPAÇÃO (SLP-03) → CONVERSÃO EM INTEIRAS (SIZ-01.2)
           → AJUSTE POR CAIXA/CUSTOS (CST-01.2).
           A etapa que cortou é registrada no trade (cut_reason).
           Função PURA (não toca o portfolio); None ⇒ sem ordem (CST-01.2/SLP-03.5).
           decision_date/intent_seq vêm do laço — convert permanece pura."""
    def place(self, order: ConvertedOrder) -> None:
        """Sem reserva de caixa (ORD-04.3): a ordem usa o caixa disponível na hora da execução.
           Última intenção vence (ORD-04.2): place substitui pendentes anteriores do ativo."""
    def execute_pending(self, ticker: str, bar: BarSlice, adv: float | None) -> list[Trade]:
        """Executa pendentes de X no open da barra do PRÓPRIO ativo (POR-05.3 — ADR-0002 por ativo):
           - MARKET → open, com slippage de preço (SLP-04.1)
           - LIMIT  → low ≤ L ? min(L, open) : não executa e CANCELA ao fim da barra (ORD-01.1/01.3)
           - STOP   → (posição aberta) low ≤ S ? vira mercado a min(S, open) + slippage (ORD-02.1);
                      sem posição aberta, nunca ativa (ORD-02.2)
           - Ambiguidade intrabarra → pior caso (ADR-0007/D2), Trade.ambiguous = True
           - Caixa insuficiente para múltiplas ordens → atendimento alfabético por ticker,
             não-atendida logada e contada (POR-01.2/MET-05)"""
    def cancel_all(self, ticker: str) -> None:
        """EXIT cancela TODAS as pendentes do ativo, incluindo stops (ORD-04.1)."""
```

- **`CostModel` estendido (emenda T06):** o da Fase 1 (`fixed + rate×notional`) ganha `min_cost: float = 0.0` e `cost_for(N) = max(fixed + rate×N, min_cost)` — CA-01.1. Default `m = 0` preserva exatamente o comportamento da Fase 1 (D2: 1 bps + USD 1).
- **`ref_price = last_close[ticker]` (escolha documentada, T06):** sizing, caixa e custo estimado usam o último close **conhecido na decisão**; a execução acontece no open da próxima barra do próprio ativo (ADR-0002) com slippage — o preço final é do T08, e o `est_cost` é estimativa. Preço de execução nunca negativo; `ref_price ≤ 0` ⇒ `EngineError`.
- **Caixa/custos = reduce-until-fits em forma fechada (decisão T06):** a desigualdade `q·p + max(f + r·q·p, m) ≤ cash` é linear por partes; resolve-se nos dois candidatos (`⌊(cash−f)/(p(1+r))⌋` e `⌊(cash−m)/p⌋`, validados com o custo real) — mesmo resultado do laço decremental, sem risco de O(q) (mesmo princípio do `max_affordable_quantity` da Fase 1).

### 3.6 Portfolio e Trade — estendidos

```python
class Portfolio:
    cash: float
    positions: dict[str, Position]              # por ativo — modelo N desde a Fase 1 (D4)
    trades: list[Trade]
    pending: dict[str, list[PendingOrder]]      # por ativo — ADR-0002 por ativo (POR-05.3)
    def market_to_market(self, close_by_ticker: dict[str, float]) -> None: ...
```

```python
@dataclass(frozen=True)
class Trade:                       # Fase 1 + 3 campos novos
    ticker: str
    entry_date: date;  entry_price: float;  entry_decision_date: date
    exit_date: date | None;  exit_price: float | None;  exit_decision_date: date | None
    quantity: int
    entry_cost: float;  exit_cost: float
    entry_gap_days: int;  exit_gap_days: int | None
    origin: OrderKind | None       # market | limit | stop — auditoria do ENG-01.2 (ORD-04.4)
    cut_reason: CutStage | None    # SIZING | CAP | INTEGER | CASH — motivo do corte (CST-01.3/R1)
    ambiguous: bool                # ambiguidade intrabarra (ORD-03.1/03.3)
```

### 3.7 Fronteira de instante — §3.6 da Fase 1 estendido (RNF-07)

| Camada | Tipo de data | Responsável pela conversão |
|---|---|---|
| yfinance | `pd.Timestamp`, às vezes tz-aware | — |
| `ingestion/normalizer.py` | converte para `datetime.date` | **fronteira de entrada** |
| domínio (`engine/`, `analytics/`, `strategies/`, módulos novos) | `datetime.date` sempre | nunca converte |
| `storage/repository.py` | `date` ⇄ `datetime` 00:00 UTC | **fronteira de saída** |

Regra mantida na íntegra: **a classe `datetime` e o aparato de fuso (`timezone`, `tzinfo`, `UTC`) só podem aparecer em `ingestion/normalizer.py` e `storage/repository.py`**; `date`/`timedelta` são livres. Os módulos novos — `calendar.py`, `liquidity.py`, `slippage.py`, `sizing.py`, `conditional.py` e o `broker.py` estendido — **não tocam o aparato de fuso**. `current_execution_date()` continua o único ponto de leitura do relógio (RF-CON-01). O teste de arquitetura existente é estendido a esses módulos e permanece bloqueante no CI.

### 3.8 Contratos — pré/pós-condições por interface (checklist do gate 2)

| Interface | Pré-condições | Pós-condições | Exceções |
|---|---|---|---|
| `UnionCalendar.build(series)` | `series` não vazio; datas de cada série ordenadas e sem duplicata | `dates` = união ordenada; `bar_index[X][u] = -1` sse X sem barra em `dates[u]`; `last_known` = último índice ≥ 0 à esquerda; arrays imutáveis (`writeable=False`) | `EngineError` se `series` vazio |
| `UnionCalendar.has_bar_at/bar_index_at/last_known_index_at(ticker, u)` | `ticker ∈ series`; `0 ≤ u < len(dates)` | O(1); `bar_index_at` devolve índice do próprio array ou `None` (POR-05.1); `last_known_index_at` devolve `None` sse o ativo ainda não tem barra (POR-02.2) | `KeyError` se ticker fora do run; `EngineError` se `u` fora de `[0, len(dates))` |
| `ConditionalStrategy.on_bar(view)` | `view.i ≥ warmup`; `view` contém apenas barras do próprio ativo (POR-02.4) | devolve `Signal`/`ConditionalIntent`/`None`; sem acesso a caixa/posição/trades (ENG-05.2); sem efeito colateral sobre a carteira | — |
| `ConditionalIntent` | `LIMIT` ⇔ `limit` presente; `STOP` ⇔ `stop` presente; `MARKET` ⇒ sem `limit`/`stop`; `bracket` ⇒ `order_type = LIMIT` e `limit = bracket.limit` (par na mesma intenção — SIG-01.2) | ordens derivadas compartilham o `decision_date` da intenção (SIG-01.3) | `EngineError` se pré-condição violada (construtor) |
| `Bracket` | `0 < stop < limit` (entrada: limite de compra acima do stop protetor; saída: take-profit acima do stop — ADR-0007) | — | `EngineError` se violado |
| `SlippageModel.execution_price(ref, side, qty, adv)` | `ref > 0`; `qty ≥ 1` | preço na direção desfavorável ao executor; aplicado SÓ a ordens a mercado e a stops convertidos (SLP-04.1/04.4); limite nunca violado (SLP-04.2); custos fora do preço (SLP-04.3) | `EngineError` se `ref ≤ 0` ou `qty < 1` |
| `FixedBps` | `bps ≥ 0` | `ref × (1 ± bps/10000)` (SLP-02.1) | `EngineError` se `bps < 0` |
| `Participation` | `bps ≥ 0`; `k ≥ 0`; `adv > 0` ou `None` | `ref × (1 ± bps(1 + k·q/ADV)/10000)` (C2/ADR-0006); `adv is None` ⇒ comportamento de `FixedBps` + aviso (SLP-03.2) | `EngineError` se `bps < 0`, `k < 0` ou `adv ≤ 0` |
| `adv(series, i, window=20)` | `0 ≤ i < len(series)`; `window ≥ 1` | média de volume dos últimos `window` pregões do próprio ativo terminando em `i`; `None` sse histórico insuficiente (SLP-03.1/03.2) | — |
| `participation_cap(qty, adv, cap=0.10)` | `qty ≥ 1`; `adv > 0`; `0 < cap ≤ 1` | `min(qty, ⌊cap × adv⌋)`; resultado `< 1` ⇒ chamador não gera ordem e loga (SLP-03.5); nunca chamada para saídas (SLP-03.4) | — |
| `Sizer.target_fraction(ticker, inputs)` | `ticker ∈ inputs.positions ∪ universo`; `inputs.n ≥ 1` | fração em `(0, 1]`; `FixedOneOverN` ⇒ `1/n`; conversão em quantidade é do broker (SIZ-01.2) | — |
| `CostModel.cost_for(notional)` | `notional ≥ 0`; `fixed, rate, min_cost ≥ 0` | `max(fixed + rate×notional, min_cost)` (CST-01 CA-01.1) | `EngineError` se algum parâmetro < 0 |
| `Broker.convert(intent, ticker, inputs, sizer, adv, cost_model, cap, decision_date, intent_seq)` | intenção de ENTRADA válida (3.2); `ticker ∈ inputs.last_close`; `ref_price > 0`; `inputs` coerentes | aplica a sequência fixa SIZING → CAP → INTEIRAS → CAIXA/CUSTOS (R1/CST-01.3); `cut_reason` = última etapa que reduziu; `ConvertedOrder | None` (None ⇒ sem ordem, logado — CST-01.2/SLP-03.5); função pura; sem reserva de caixa (ORD-04.3) | `EngineError` se `ticker` sem last_close, `ref_price ≤ 0` ou intenção de saída |
| `ConvertedOrder` | campos coerentes com o `kind` (3.2) | `qty ≥ 1`; `est_cost` = custo no `ref_price`; imutável | — |
| `Broker.place(order)` | ordem já convertida | pendente registrada por ativo; substitui pendentes anteriores do ativo (última intenção vence — ORD-04.2) | — |
| `Broker.execute_pending(ticker, bar, adv)` | `bar` é a próxima barra do próprio ativo (ADR-0002 por ativo, POR-05.3) | mercado ao open; limite a `min/max(L, open)` ou cancelado ao fim da barra (ORD-01.1/01.3); stop a `min(S, open)` com slippage (ORD-02.1); pior caso intrabarra registrado (ADR-0007); atendimento alfabético (POR-01.2); caixa nunca negativo | — |
| `Broker.cancel_all(ticker)` | — | todas as pendentes do ativo canceladas, incluindo stops (ORD-04.1) | — |
| `Portfolio.market_to_market(close_by_ticker)` | `close_by_ticker` cobre todos os ativos com posição (último close conhecido — POR-02.2) | equity consistente com a identidade de POR-04.1 | — |
| `Trade` | campos obrigatórios preenchidos na criação | `origin`/`cut_reason`/`ambiguous` auditáveis (ORD-04.4/CST-01.3/ORD-03.1) | — |
| `MechanismCounters` | — | contagens incrementadas apenas pelo engine, categorias próprias (MET-05) | — |
| `buy_and_hold_multi(series, n, cost_cfg, slippage, cap)` | mesmo universo/N do run (P3); mesmas regras de entrada | compra cada ativo na primeira barra negociável do próprio ativo; caixa ocioso; sem rebalance; deslistagem travada (MET-02.1–02.4) | — |
| `turnover_annualized(trades, equity_daily, n_bars)` | `n_bars ≥ 1`; `equity_daily` alinhada à série | valor = fórmula fechada de RF-MET-04; mesma definição para estratégia e benchmark (MET-04.1/04.2/04.3) | — |
| `avg_exposure(daily_notional, equity_daily)` | séries alinhadas; `equity > 0` | média diária de `(Σ qtyᵢ · closeᵢ) / equity` (MET-04.4) | — |
| `contribution_per_asset(trades)` | — | soma concilia com o PnL total (MET-01.1) | — |

## 4. Fluxo da barra multi-ativo — §4.3 da Fase 1 estendido

Para cada índice-união `u` em `0..D-1` (em cada fase, ativos processados em **ordem alfabética** — determinismo e caixa compartilhado):

```
1. EXECUTAR — para cada X com bar_index[X][u] ≥ 0 (alfabético):
       i = bar_index[X][u]
       trades += broker.execute_pending(X, barra_i, adv(X, i))
       # limite não preenchido cancela ao fim da barra (Q2/ORD-01.3)
       # decisão da barra i de X executa no open[i+1] de X (ADR-0002 por ativo — POR-05.3)

2. MARCAR A MERCADO:
       equity[u] = cash + Σ_X qty[X] × close_conhecido(X, u)
       # close[i] se barra em u; senão último close conhecido (last_known — POR-02.2)
       # posição travada (deslistagem) entra pelo último close conhecido (POR-02.3)

3. CONSULTAR — para cada X com bar_index[X][u] ≥ 0 e i ≥ warmup (alfabético):
       intent = strategies[X].on_bar(MarketView_X(i))
       # EXIT     → broker.cancel_all(X) (ORD-04.1); saída ao open da próxima barra de X
       # ENTER    → convert (sizing→cap→inteiras→caixa/custos) → place (última intenção vence — ORD-04.2)
       # ENG-01.4 POR ATIVO (C1): se i é a ÚLTIMA barra da série de X, a intenção MORRE pendente
       #   (não existe "próxima barra de X") e é reportada como pendente no relatório

4. INVARIANTES a cada barra (erro de programação, não condição de mercado):
       cash ≥ 0; qty[X] ≥ 0 ∀X; k ≤ N (POR-04.3, SIZ-04.3)
```

**Restrições herdadas da Fase 1 (§4.3 do design v0.9), preservadas por ativo:** executar antes de marcar (equity de `u` reflete a posição real) e executar antes de consultar (ADR-0002 em código; nenhuma decisão de `u` executa em `u`). A ordem entre marcar e consultar é livre por ativo — a premissa de que a consulta não tem efeito colateral é travada por teste estendido ao multi-ativo (§10). Uma inversão de 1-antes-de-2 ou 1-antes-de-3 em refatoração derruba ENG-01.2.

**Ambiguidade intrabarra — ADR-0007 / D2, aplicada a TODOS os brackets:**

| Cenário | Resolução | `Trade.ambiguous` |
|---|---|---|
| Bracket de **entrada** (limite L + stop S), ambos tocados na mesma barra | Posição **abre em L** e **fecha no stop S** na mesma barra ⇒ perda realizada `(L − S + custos)`, fica **flat** | `True` |
| Bracket de **saída** (take-profit limite + stop sobre posição aberta), ambos tocados | O **stop preenche em S** (pior que o limite) | `True` |

Ambos os casos incrementam `MechanismCounters.intrabar_ambiguities` (MET-05). Stop só fica vivo **após a entrada preencher** (ORD-02.2).

## 5. Calendário-união — algoritmo e complexidade (D1)

**Construção em uma passada.** `UnionCalendar.build(series)`:

1. Merge das `N` listas de datas ordenadas → `dates` (união), O(D).
2. Para cada ativo X, percorre a união com um cursor sobre `series[X].dates` que só avança: `bar_index[X][u] = cursor` sse `dates[u] == series[X].dates[cursor]`, senão `-1`; `last_known[X][u]` = último valor ≥ 0 de `bar_index[X]` à esquerda (cummax na mesma passada).

Custo total: O(D + Σ|série_X|) = **O(total de barras + união)** — uma passada, sem busca binária por (data, ativo). O `bar_index`/`last_known` são arrays imutáveis; o laço só lê.

**Guard de O(total) — teste de propriedade (D1):** a garantia de complexidade é **estrutural** (a API não oferece consulta por data), então o teste não vigia sequência de chamadas — ele prova a propriedade: (i) `build` é função pura (mesmo input ⇒ estrutura idêntica); (ii) para todo `u` e `X`, `bar_index[X][u]` bate com a busca ingênua por `(data, ativo)` em fixture pequena (paridade de corretude); (iii) o custo de `build` escala linearmente com o total de barras em fixture de propriedade (guarda de regressão de complexidade). Testes em §10.

**Decisões locais:** ativo com série que começa depois do início da união tem `-1`/`None` até sua primeira barra (IPO — nunca barra fabricada, POR-02.2); ativo deslistado mantém `last_known` constante no resto da união (posição travada, POR-02.3); ativo do run sem nenhuma barra na janela tem `bar_index` todo `-1` — conta no `N`, nunca recebe alvo, contribui zero e é reportado não-negociado (SIZ-02.4/R2).

## 6. Conciliação estendida — POR-04.2 + §4.6 da Fase 1

```
pnl_realizado(trade)       = (saída − entrada) × quantidade          [BRUTO — custos fora]
custo_total                = Σ (entry_cost + exit_cost)              [uma única vez, termo próprio]
pnl_nao_realizado(ativo i) = (último_close_conhecido_i − entrada_i) × quantidade_i
                             [inclui posição travada — POR-02.3]
equity_final − equity_inicial ≡ Σ_i pnl_realizado_i + Σ_i pnl_nao_realizado_i − custo_total
```

- Soma sobre os **N ativos do run**, incluindo o nunca-negociado (contribui zero, sem buraco — R2).
- Verificação com `math.isclose(rel_tol=1e-9)`, conforme RNF-08. Nunca igualdade exata.
- Contribuições por ativo (MET-01.1) somam ao PnL total — mesma identidade, fatiada por ticker.
- Invariantes da barra: `cash ≥ 0`, `qty_i ≥ 0` (POR-04.3), `k ≤ N` (SIZ-04.3).

## 7. Analytics — métricas, benchmark, relatório

```python
# analytics/metrics.py (estendido) — fórmulas de RF-MET-04, MESMAS para estratégia e benchmark (MET-04.2)
def turnover_annualized(trades: list[Trade], equity_daily: Series, n_bars: int) -> float:
    """(Σ|notional_compra| + Σ|notional_venda|) / (2 × patrimônio_médio) × (252 / n_barras)"""
def avg_exposure(daily_notional: Series, equity_daily: Series) -> float:
    """média diária de (Σ qtyᵢ × closeᵢ) / equity"""
def contribution_per_asset(trades: list[Trade]) -> dict[str, float]: ...

# analytics/benchmark.py (estendido) — S6
def buy_and_hold_multi(series: dict[str, PriceSeries], n: int,
                       cost_cfg, slippage: SlippageModel, cap: float) -> BacktestResult:
    """compra cada ativo na primeira barra negociável do PRÓPRIO ativo (MET-02.2);
       herda TODAS as regras de entrada: custos, slippage, cap (MET-02.1);
       mesmo N do run (P3); caixa ocioso; sem rebalance (MET-02.4);
       deslistagem travada e reportada (MET-02.3)"""

# analytics/report.py (estendido)
@dataclass(frozen=True)
class MechanismCounters:            # bloco "contadores de mecanismo" (MET-05/P6)
    stops_triggered: int            # categoria própria (P6)
    intrabar_ambiguities: int       # ORD-03.2 — incrementado pelo pior caso (ADR-0007/D2)
    unfilled_cash_orders: int       # Q5 / POR-01.2
```

- **Seção "run" ampliada (RF-CON-02 continua valendo, multi-ativo):** universo (`N`, lista de tickers), capital inicial, custos/slippage/cap configurados, `n_barras`, datas efetivas de início/fim, contagem de pendentes mortas (ENG-01.4 por ativo).
- **Seção fixa de vieses ampliada (MET-03.1):** itens da Fase 1 preservados + ambiguidade intrabarra resolvida por pior caso; slippage modelado mas não calibrado contra execuções reais; sem impacto permanente de mercado; **fill integral ao preço limite é otimista** (a ordem pode não preencher ou preencher parcialmente — S2); **atendimento alfabético com caixa insuficiente é determinístico e neutro, mas qualquer regra de atendimento é seleção com viés** (Q5). Constante literal no código, como na Fase 1 §5.2.
- Slippage/custo zerados continuam sinalizando irrealismo (SLP-01.3, ENG-03.2).

**Harness do RNF-04 (P5/D3) — escopo declarado na spec (RF-RNF-01 CA-01.3):** a medição dos 30 s cobre `get_series × N` + run multi-ativo + `buy_and_hold_multi` + `report.build()`, excluindo ingestão (I/O Mongo) e renderização de PNG. O harness é um teste nomeado (§10) que documenta o escopo medido — o relatório declara a exclusão.

## 8. Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Merge do calendário degenerar para O(n²) em refatoração | Alto — estoura RNF-04 silenciosamente | API por índice de união (não existe consulta por data); teste de propriedade de linearidade + paridade com busca ingênua (§10) |
| Ordem de execução × consulta invertida (multi-ativo) | Alto — reintroduz lookahead | ENG-01.2 partes 1 e 2 quebram; docstring do laço declara a sequência como invariante |
| `datetime` vazando por módulos novos | Médio — reaparece em comparação de datas | Teste de arquitetura estendido a `calendar/liquidity/slippage/sizing/conditional/broker`, bloqueante no CI |
| Dupla contagem de custos na conciliação (PnL líquido em vez de bruto) | Médio | Definição explícita (§6): PnL bruto, custos no termo próprio |
| "Última intenção vence" mal implementada (ordem antiga executa) | Alto — trade fantasma | `intent_seq` + teste nomeado (§10) |
| Stop ativando sem posição (bracket sem entrada) | Médio | ORD-02.2 por construção no broker + teste nomeado |
| Forma funcional do slippage ambígua ⇒ gate 3 não-determinístico | Médio | ADR-0006 crava `slippage_bps = bps × (1 + k × q/ADV)` (C2) + teste de fórmula fechada |
| Arrays do calendário (D×N) pressionando memória | Baixo | Medido: ~930 KB p/ 20×2.900; imutabilidade paga a cópia única |

## 9. Decisões fechadas nesta versão

As quatro decisões de peso viraram ADRs — ver **ADR-0005** (execução condicional e fronteira de mutação), **ADR-0006** (modelo de slippage), **ADR-0007** (resolução da ambiguidade intrabarra), **ADR-0008** (política de sizing default). Decisões locais, com alternativas descartadas:

**D1 — Calendário-união imutável (local, referenciada no ADR-0005/§5).**
- **Escolha:** arrays `bar_index`/`last_known` pré-computados e imutáveis, merge em uma passada.
- **Alternativa descartada — ponteiros mutáveis por ativo:** economia de memória (zero cópia), e o laço só avança. Descartada porque imutabilidade de dados é política do projeto (design Fase 1 §3.7) e o guard de complexidade viraria teste de sequência de chamadas — frágil a refatoração. O custo de ~930 KB é medido e aceito.

**D2 — Pior caso intrabarra para todos os brackets (ADR-0007).** Entrada abre em L e fecha no stop S na mesma barra (perda `L − S + custos`, flat); saída preenche no stop. Ambos com `ambiguous=True` e contados.

**D3 — Layout e medição.** Módulos novos dentro de `engine/` (RNF-02 inalterada: `engine/` + `analytics/` ≥ 85%); harness do RNF-04 = `get_series×N` + run + benchmark + `report.build()`, excluindo ingestão e PNG, escopo declarado na spec (RF-RNF-01 CA-01.3).
- **Alternativa descartada — pacotes-raiz `broker/`, `slippage/`, `sizing/`:** superfície de pacotes mais limpa, mas fragmenta a contagem de cobertura de RNF-02 e amplia a superfície de testes de arquitetura sem ganho de isolamento (os módulos não têm dependência externa própria).

**Decisões locais de fluxo (alternativa única razoável, registrada por clareza):**
- Pendentes por ativo no `Portfolio` (não fila global) — consequência direta do ADR-0002 por ativo (POR-05.3).
- Fases do laço em ordem alfabética — ordem de execução importa (caixa compartilhado, POR-01.2); ordem de consulta é indiferente (ENG-05.2) e alfabética apenas por determinismo.

## 10. Invariantes e testes nomeados (gate 2)

| Invariante | Como é garantido | Teste que prova |
|---|---|---|
| Anti-lookahead em ordens condicionais (ENG-01.2 parte 1 / ADR-0005) | MarketView por ativo + execução no próximo open do próprio ativo | `test_eng_012_mutation_does_not_change_conditional_intent` |
| Execução de limite/stop vincula-se a ordem preexistente (ENG-01.2 parte 2 / ADR-0005) | `decision_date` no `Trade` (ORD-04.4) | `test_eng_012_execution_binds_to_order_via_decision_date` |
| Fronteira de mutação por ativo (POR-05.4 / ADR-0005) | Instâncias independentes, arrays por ativo | `test_mutation_frontier_is_per_asset` |
| ADR-0002 por ativo (POR-05.3) | Pendente por ativo executa no open da próxima barra do próprio ativo | `test_pending_order_executes_at_next_bar_of_own_asset` |
| ENG-01.4 por ativo (C1) | Intenção na última barra da série de X morre pendente e é reportada | `test_last_bar_intention_dies_pending_per_asset` |
| Calendário-união correto (POR-02.1) | Merge em uma passada; paridade com busca ingênua | `test_union_calendar_matches_naive_lookup` |
| Merge O(total), sem O(n²) (D1/RNF-04) | Estrutura imutável por índice de união; propriedade de linearidade | `test_union_calendar_build_is_pure_and_linear` |
| Sem barra ⇒ sem decisão/execução, mark-to-market (POR-02.2) | `bar_index == -1` ⇒ skip; `last_known` para marcar | `test_asset_without_bar_is_marked_with_last_close` |
| Deslistagem travada (POR-02.3 / MET-02.3) | Posição marcada pelo último close, reportada, nunca liquidada | `test_delisted_position_is_locked_and_reported` |
| Ativo sem barra contribui zero (SIZ-02.4/R2) | `bar_index` todo `-1`; nunca recebe alvo; contado no N | `test_never_traded_asset_contributes_zero_and_reconciles` |
| Identidade de equity (POR-04.1) | Invariante checada no laço | `test_equity_identity_multi_asset` |
| Conciliação multi-ativo (POR-04.2) | Identidade §6 com `isclose(1e-9)` | `test_reconciliation_multi_asset_20_assets` |
| `cash ≥ 0`, `qty ≥ 0` (POR-04.3) | Guard no laço, erro de programação | `test_cash_and_quantity_never_negative_multi` |
| `k ≤ N` (SIZ-04.3) | Guard no laço | `test_open_positions_never_exceed_n` |
| Sem reserva de caixa (ORD-04.3) | `place` usa o caixa no momento da execução | `test_second_entry_sees_cash_already_debited` |
| Última intenção vence (ORD-04.2) | `intent_seq` substitui pendentes anteriores | `test_last_intention_wins_replaces_pending` |
| EXIT cancela todas as pendentes (ORD-04.1) | `cancel_all` inclui stops | `test_exit_cancels_all_pending_including_stops` |
| Limite cancela ao fim da barra (ORD-01.3/Q2) | Cancelamento na execução da barra | `test_limit_cancels_at_end_of_bar` |
| Stop só com posição aberta (ORD-02.2) | Condição no broker, por construção | `test_stop_never_activates_without_open_position` |
| Pior caso intrabarra — entrada (ADR-0007/D2) | Abre em L e fecha no stop na mesma barra, flat | `test_intrabar_ambiguity_entry_bracket_worst_case` |
| Pior caso intrabarra — saída (ADR-0007/D2) | Stop preenche em S, pior que o limite | `test_intrabar_ambiguity_exit_bracket_worst_case` |
| Slippage só a mercado / limite nunca violado (SLP-04.1/04.2) | Regra no broker | `test_limit_price_never_violated_and_market_slippage_only` |
| Forma funcional do slippage (C2/ADR-0006) | Fórmula fechada `bps × (1 + k·q/ADV)` | `test_participation_slippage_matches_closed_form` |
| Monotonicidade do slippage (SLP-03.1) | Função linear em q/ADV | `test_slippage_monotonic_in_participation` |
| Fallback sem ADV (SLP-03.2) | Recai em `FixedBps` com aviso | `test_participation_falls_back_to_fixed_with_warning` |
| Cap só em entradas, corte < 1 ação (SLP-03.3–03.5) | `participation_cap` + regra no broker | `test_cap_applies_to_entries_only_and_subshare_cancels` |
| Sequência de corte fixa + motivo (CST-01.3/R1) | `convert` em 4 etapas, `cut_reason` no trade | `test_cut_sequence_order_and_reason_recorded` |
| 1/N com N do run; N=1 ⇒ all-in (SIZ-02.1/02.3/P3) | `FixedOneOverN` com N fixado | `test_target_is_equity_over_n_fixed_and_n1_is_allin` |
| Caixa ocioso reportado, não realocado (SIZ-02.2) | Sem trades de realocação; exposto no relatório | `test_idle_cash_reported_not_reallocated` |
| Rebalance só por mudança de k (SIZ-03.1/03.4/S4) | Gatilho no engine, limiar em pp | `test_no_rebalance_without_k_change` |
| Sizer devolve fração (SIZ-04.2) | Contrato do protocolo | `test_sizer_returns_fraction_not_quantity` |
| Benchmark por ativo, mesmas regras (MET-02.1–02.4/S6) | `buy_and_hold_multi` | `test_benchmark_buys_at_first_tradable_bar_per_asset_with_entry_rules` |
| Fórmulas de turnover/exposição (MET-04.1–04.4/P4) | Fórmulas fechadas, mesmas definições | `test_turnover_and_exposure_closed_form_fixture`; `test_same_definitions_strategy_and_benchmark` |
| Contadores de mecanismo (MET-05.1–05.3/P6) | Bloco no relatório, categorias próprias | `test_report_mechanism_counters_block` |
| Vieses ampliados (MET-03.1) | Constante literal no relatório | `test_bias_section_includes_conditional_items` |
| Fronteira de instante (RNF-07) | Imports restritos aos módulos novos | `test_architecture_timezone_imports` — estendido, bloqueante |
| Determinismo multi-ativo (RNF-01) | Sem aleatoriedade; alfabético; datas fixas | `test_multi_asset_run_is_deterministic` |
| RNF-04 mede só o cômputo (P5/D3/RF-RNF-01 CA-01.3) | Harness com escopo declarado | `test_rnf04_harness_measures_compute_only` |
| Equity independe do sinal da barra (Fase 1, estendido) | Consulta sem efeito colateral (ENG-05.2) | `test_equity_of_bar_does_not_depend_on_signal_multi_asset` |

### 10.1 Testes nomeados complementares (adicionados no checklist do gate 2)

Fecham a cobertura RF × teste nomeado dos 25 RFs novos da v0.2: todo RF passa a ter, no mínimo, um teste nomeado direto.

| RF / CA | Teste nomeado |
|---|---|
| SLP-01 (CA-01.2) | `test_pluggable_slippage_model_requires_no_broker_change` |
| SLP-01 (CA-01.3) | `test_zero_slippage_declared_unrealistic` |
| SLP-02 (CA-02.1) | `test_fixed_bps_execution_price` |
| SLP-03 (CA-03.1, janela) | `test_adv_window_is_20_sessions_of_own_asset` |
| SLP-04 (CA-04.3) | `test_costs_debited_from_cash_not_in_execution_price` |
| ORD-01 (CA-01.1/01.2) | `test_limit_fills_at_min_or_max_of_limit_and_open` |
| ORD-02 (CA-02.1) | `test_stop_triggers_market_at_min_stop_open` |
| SIG-01 (CA-01.1) / POR-03 (CA-03.2) | `test_fase1_strategy_runs_unchanged_multi_asset` |
| SIG-01 (CA-01.2/01.3) | `test_bracket_carries_limit_and_stop_in_same_intention` |
| SIZ-01 (CA-01.1) | `test_new_sizer_policy_requires_no_engine_change` |
| SIZ-03 (CA-03.2) | `test_rebalance_trades_counted_separately_from_signal` |
| SIZ-03 (CA-03.3) | `test_rebalance_threshold_pp_gates_adjustment` |
| POR-01 (CA-01.2) | `test_alphabetical_serving_with_insufficient_cash` |
| POR-02 (CA-02.4) | `test_market_view_contains_only_own_asset_bars` |
| POR-03 (CA-03.1) | `test_n_independent_strategy_instances_each_see_own_asset` |
| MET-01 (CA-01.1) | `test_contributions_per_asset_reconcile_with_total_pnl` |
| RNF-02 (85%) | `test_ci_coverage_floor_85` |

## 11. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.1 | 2026-08-14 | Rascunho inicial — gate 2. Esboço aprovado na revisão conjunta com as decisões D1–D4 e correções C1–C2: calendário-união com arrays pré-computados imutáveis (D1); pior caso intrabarra para todos os brackets, entrada e saída (D2); módulos novos dentro de `engine/` e harness do RNF-04 declarado (D3); ADRs 0005–0008 propostos (D4); ENG-01.4 por ativo reafirmado no fluxo da barra (C1); forma funcional do slippage cravada no ADR-0006 (C2). |
| 0.1 (emenda do gate 2) | 2026-08-14 | Checklist do gate 2 executado antes da aprovação; pendências resolvidas como emenda da mesma versão: §3.8 contratos de pré/pós-condições por interface; §10.1 testes nomeados complementares por RF (17); §1 tabela RF × garantia (construção/teste); default determinístico `k = 1.0` no ADR-0006. |
