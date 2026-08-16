# Fase 2b — Venda a descoberto, margem e walk-forward — Design técnico

**Status:** em revisão — gate 2
**Versão:** 0.1
**Data:** 2026-08-14
**Requisitos de origem:** `specs/fase-2b-requirements.md` v0.2 (aprovada, gate 1)
**Próximo gate:** `specs/fase-2b-tasks.md`
**ADRs vinculantes:** 0001, 0002, 0003, 0004 (Fase 1); 0005, 0006, 0007, 0008 (2a, aceitos); 0009, 0010, 0011 (2b, propostos neste gate)

> **Convenção de referência:** critérios de aceitação são citados com prefixo da família de requisito — `SHT-03.1` significa CA-03.1 de RF-SHT-03; `MRG-01.5` significa CA-01.5 de RF-MRG-01. Mesma convenção do design v0.1 da 2a.

---

## 1. Princípio organizador

O requisito pode ser satisfeito por convenção (quem escreveu lembrou) ou por construção (o código não consegue fazer errado). A Fase 2b mantém a postura da 2a — construção onde dá, teste nomeado onde a construção não é possível — e adiciona uma regra nova: **o invariante da 2a (`cash ≥ 0`, `qty ≥ 0`, RF-POR-04 CA-04.3) é RELAXADO apenas com ADR próprio** (RNF-09 da 2a) — o ADR-0009.

**Por construção nesta fase:**

1. **Direção no sinal, nunca no sizer (D3).** O `Signal` ganha `ENTER_SHORT`/`EXIT_SHORT`; o sizer continua devolvendo **magnitude** (fração ∈ (0, 1], RF-SIZ-04 da 2a) e a conversão aplica o sinal (ENTRADA → `+`, SHORT → `−`). Uma estratégia long-only da Fase 1/2a emite apenas `ENTER`/`EXIT` e roda idêntica (SHT-01.1) — o contrato é estendido, não reescrito.
2. **Margem por construção (D1/ADR-0009).** `margin_requirement = Σ|qtyᵢ| × closeᵢ × factor` vive em `engine/margin.py` (função pura); o laço checa `equity ≥ margem` no lugar de `cash ≥ 0`/`qty ≥ 0`. Com apenas longs e `factor = 1.0`, a margem reduz exatamente a `cash ≥ 0` — o teste de invariante da 2a passa sem mudança (MRG-01.2, regressão).
3. **Liquidação determinística (D2/ADR-0009).** A seleção da liquidação é **alfabética por ticker** — o critério está no engine, não existe caminho de código que use preço como critério (MRG-02.4/RNF-01). Integral por ativo (nunca parcial dentro de um ativo — MRG-02).
4. **Isolamento estrito IS/OOS (D6/ADR-0011).** Cada fold constrói `PriceSeries`/`UnionCalendar` **truncados no fim do IS** para o run IS; o `MarketView` indexa o array truncado e qualquer acesso além do fim é `EngineError` — a fronteira é do array, não da disciplina de quem chama (WFK-01.1). O walk-forward roda o `run_backtest_multi` da 2a como **caixa preta** por fold — herança por construção, mesma filosofia do benchmark 1/N da T15 (alternativa rejeitada em §2).
5. **Warmup do OOS = cauda do IS (R4).** A avaliação OOS roda sobre a série composta (cauda do IS ≤ fronteira + segmento OOS); mutar o OOS não altera o warmup (WFK-01.3).
6. **Buy-stop espelha o sell-stop (D5).** `OrderKind.STOP` com `side=BUY`; disparo por `high[i] ≥ S`, fill a `max(S, open[i])` com slippage de compra; não disparado ⇒ persiste (ORD-05.2); sem reserva de caixa (ORD-05.3). Sem membro novo no enum — o lado discrimina.
7. **Fronteira de instante (RNF-07).** Os módulos novos (`margin.py`, `walkforward.py`) e os estendidos (`broker`, `portfolio`, `conditional`, `backtest`, `analytics`) não importam `datetime`/`timezone` — a regra do design Fase 1 §3.6 vale sem exceção.

**Por teste nomeado:** o restante — borrow fee em forma fechada, PnL short através de data ex-dividendo ≡ retorno ajustado (SHT-04.3), fundo quebrado com métricas `None` explícito (MRG-03/R6), pior caso intrabarra com buy-stop (ORD-06), mutação OOS não altera parâmetros IS (WFK-04/ADR-0011), conciliação estendida com `qty < 0` e borrow fees, determinismo, RNF-10 (orçamento do WF). Cada um com teste nomeado em §10.

**Portador de garantia por RF (checklist do gate 2):** nenhum RF fica sem portador explícito — por construção ou por teste nomeado.

| RF | Garantia | Portador |
|---|---|---|
| RF-SHT-01 | por construção (enum estendido, conversão aplica o sinal) | `test_signal_contract_is_backward_compatible_long_only` (CA-01.1); `test_enter_short_yields_negative_target_qty` (CA-01.2); `test_exit_short_without_open_position_raises_engine_error` (CA-01.3) |
| RF-SHT-02 | regras de preço por construção no broker | `test_short_opens_at_market_with_sell_slippage` (CA-02.1); `test_buy_to_cover_at_market_with_buy_slippage` (CA-02.2); `test_short_entry_respects_participation_cap` (CA-02.3); `test_short_cover_buy_limit_never_violates_limit` (CA-02.4) |
| RF-SHT-03 | por teste (forma fechada) + por construção (débito no close) | `test_borrow_fee_closed_form_10_days` (CA-03.1); `test_borrow_fee_only_on_days_with_open_short` (CA-03.2); `test_report_borrow_fee_own_category` (CA-03.3); CA-03.4 → `test_borrow_availability_unlimited_default_never_blocks` + `test_borrow_restricted_blocks_short_and_logs` |
| RF-SHT-04 | identidade §6 (fórmula única, vale com `qty < 0`) | `test_short_roundtrip_pnl_closed_form` (CA-04.1); `test_reconciliation_closes_with_negative_qty` (CA-04.2); `test_short_pnl_across_ex_dividend_equals_adjusted_return` (CA-04.3) |
| RF-SHT-05 | por construção (travada no último close) | `test_short_delisted_position_locked_at_last_close` (CA-05.1); `test_report_flags_locked_short_position` (CA-05.2) |
| RF-MRG-01 | invariante por construção no laço | `test_margin_invariant_reduces_to_cash_ge_zero_long_only` (CA-01.2); `test_margin_factor_default_1_0_exact_formula` (CA-01.5); `test_margin_breach_close_to_open_window_allowed_then_error` (CA-01.3) |
| RF-MRG-02 | seleção por construção (alfabética no engine) | `test_forced_liquidation_alphabetical_until_margin_restored` (CA-02.1); `test_forced_liquidation_cancels_pending_orders` (CA-02.2); `test_report_counts_margin_call_origin_trades` (CA-02.3); `test_forced_liquidation_deterministic_across_runs` (CA-02.4) |
| RF-MRG-03 | por construção (congela; `None` explícito, nunca `NaN`) | `test_broken_fund_freezes_no_new_trades_and_flag` (CA-03.1); `test_broken_fund_metrics_are_explicit_none_never_nan` (CA-03.2); `test_broken_fund_result_excluded_from_auto_comparison` (CA-03.3) |
| RF-MRG-04 | por teste (fórmulas fechadas) | `test_gross_and_net_exposure_formulas_side_by_side` (CA-04.1); `test_leveraged_gross_gt_100_reported_with_margin_utilization` (CA-04.2) |
| RF-ORD-05 | por construção no broker (mesma regra do sell-stop) | `test_buy_stop_executes_at_max_stop_open_with_buy_slippage` (CA-05.1); `test_buy_stop_undispatched_persists_to_next_bar_of_own_asset` (CA-05.2); `test_buy_stop_never_dispatched_never_debits_cash` (CA-05.3) |
| RF-ORD-06 | por teste (pior caso registrado, ADR-0007 estendido) | `test_intrabar_ambiguity_buy_stop_entry_bracket_worst_case` (CA-06.1); `test_intrabar_ambiguity_short_bracket_stop_wins_over_tp` (CA-06.2); `test_report_counts_buy_stop_ambiguities_in_mechanism_counters` (CA-06.3) |
| RF-WFK-01 | isolamento por construção (série truncada) | `test_is_run_never_indexes_oos_bars_engine_error` (CA-01.1); `test_folds_are_disjoint_and_oos_union_covers_window` (CA-01.2); `test_oos_warmup_uses_is_tail_without_lookahead` (CA-01.3) |
| RF-WFK-02 | grade por construção (determinística) | `test_walkforward_grid_is_deterministic_params_identical` (CA-02.1); `test_oos_uses_params_selected_in_same_fold` (CA-02.2); `test_is_selection_metric_is_annualized_sharpe_rf0_declared` (CA-02.3) |
| RF-WFK-03 | por construção (concatenação) | `test_walkforward_equity_is_exact_oos_concatenation` (CA-03.1); `test_report_shows_fold_by_fold_table_with_selected_params` (CA-03.2) |
| RF-WFK-04 | por teste de mutação (ADR-0011) | `test_mutating_oos_does_not_change_is_selected_params` (CA-04.1); `test_mutating_future_is_bars_does_not_change_prior_intentions_long_short_buy_stop` (CA-04.2) |
| RF-WFK-05 | por teste (harness com escopo declarado) | `test_walkforward_harness_reports_per_fold_and_total_budgets` (CA-05.1) |
| RF-MET-05 | benchmark por construção (mesmo `buy_and_hold_multi` da 2a) | `test_report_benchmark_is_1n_long_only_with_long_short_vs_long_only` (CA-05.1); `test_benchmark_never_shorts` (CA-05.2) |
| RF-MET-06 | por construção (constante literal) | `test_bias_section_includes_2b_items` (CA-06.1); `test_run_section_reports_mht_metric_grid_folds_reconstructible` (CA-06.2) |
| RF-RNF-02 | por teste/CI | `test_rnf_heritage_tests_pass_on_long_short_run` (CA-02.1); `test_ci_coverage_floor_85_includes_margin_walkforward` (CA-02.2); `test_spec_architecture_fails_without_adr_0009` (CA-02.3) |

## 2. Arquitetura

```
 storage/ ── get_series(por ticker) ──▶ PriceSeries × N ──┐
                                                          ▼
   strategies/ ── Signal | ConditionalIntent ──▶ engine/  (2b — long+short)
        ▲        (ENTER/EXIT/ENTER_SHORT/EXIT_SHORT)       │
        │  MarketView(i próprio do ativo)                  │ calendar.py (UnionCalendar — 2a, intocado)
        └──────────────────────────────────────────────────┤
                                                           ▼
            engine/: backtest.py (laço 2b) │ broker.py (buy-stop, liquidação MARGIN_CALL)
                     │ portfolio.py (qty<0, margem) │ margin.py (NOVO) │ walkforward.py (NOVO)
                     │ conditional.py (Signal estendido) │ (2a: liquidity/slippage/sizing — intocados)
                                                           │ BacktestResultMulti (2b: broken_fund, borrow_fees)
                                                           ▼
            analytics/: metrics.py (gross/net, margem, sharpe_annualized_rf0)
                     │ benchmark.py (1/N long-only — 2a, INTOCADO) │ report.py (2b: contadores, MHT, vieses)
                                                           ▼
            Report (seção "run" ampliada 2b) ──▶ CLI + JSON
```

- **Módulos novos dentro de `engine/`** (mesma regra da 2a, D3): `engine/margin.py` (margem + borrow fee) e `engine/walkforward.py` (WF). A cobertura de RNF-02 da 2b é `engine/` + `analytics/` + módulos novos ≥ 85% (RF-RNF-02 CA-02.2), sem novos pacotes-raiz.
- **Dependências apontam para dentro.** `margin.py` consome tipos de `portfolio.py` e `conditional.py` (Position, Side) — folha. `walkforward.py` consome `backtest.py` (`run_backtest_multi`), `calendar.py`, `conditional.py` e `strategies/`; importa também o helper puro `sharpe_annualized_rf0` que ele mesmo define (§7) — `analytics/metrics.py` importa o helper de `engine/walkforward.py` (analytics já depende de engine; a direção não se inverte). `broker.py` estendido importa de `margin.py` (MarginCallOrder) — margem não importa broker (sem ciclo).
- **WF como caixa preta (decisão da missão §2, registrada):** cada run IS/OOS chama o `run_backtest_multi` da 2a com a MESMA configuração do run único (custos, slippage, cap, margem, borrow fee, sizer) — o WF herda todas as regras de execução por construção, sem reimplementar nada. **Alternativa rejeitada — WF reimplementando o laço** (ex.: parâmetros injetados no meio do loop): economizaria a sobrecarga de N runs, mas duplicaria as regras de execução e abriria uma segunda fonte de lookahead — exatamente o que a filosofia "herança por construção" (benchmark 1/N da T15) evita. O custo de rodar `grid_size × n_folds + n_folds` runs é o que o orçamento do RNF-10 declara e mede (WFK-05), não o que o design esconde.

## 3. Contratos tipados

### 3.1 `Signal` — direção no contrato (D3) — `engine/strategy.py` (estendido)

```python
class Signal(StrEnum):                    # 2a + 2 ações novas — retrocompatível (SHT-01.1)
    ENTER        = "enter"
    EXIT         = "exit"
    ENTER_SHORT  = "enter_short"          # venda a descoberto — alvo NEGATIVO (SHT-01.2)
    EXIT_SHORT   = "exit_short"           # cobertura — reduz |qty| até 0, sem cruzar (SHT-01.3)
```

- **Retrocompatibilidade por construção:** uma estratégia long-only (Fase 1/2a) emite apenas `ENTER`/`EXIT`; o resultado é idêntico ao run equivalente da 2a (SHT-01.1). Nenhuma linha de `strategies/` muda.
- **O sizer NUNCA decide direção (D3):** `target_fraction` devolve magnitude ∈ (0, 1] (RF-SIZ-04 da 2a, intocado); a **conversão** aplica o sinal — `ENTER` → alvo `+`, `ENTER_SHORT` → alvo `−` (SHT-01.2). A direção é decisão da estratégia, no sinal.
- **`EXIT_SHORT` sem posição short aberta ⇒ `EngineError`** (SHT-01.3) — nunca silêncio. `EXIT` sem posição long preserva a semântica da 2a (regressão zero).

### 3.2 `Position` e `Trade` — `engine/portfolio.py` (estendido)

```python
@dataclass
class Position:                    # 2a + oficialização de qty < 0 (D3)
    ticker: str
    quantity: int                  # NEGATIVO = short (SHT-02.1); inteiro sempre (SIZ-01 da 2a); 0 inválido
    entry_price: float             # short: preço da VENDA (sell — o lado da abertura)
    entry_date: date               # naive (RNF-07)

class TradeOrigin(StrEnum):        # origem da execução — auditoria ENG-01.2 / CA-02.3
    MARKET      = "market"         # espelha OrderKind.MARKET (mesmo valor — compat 2a)
    LIMIT       = "limit"
    STOP        = "stop"
    MARGIN_CALL = "margin_call"    # NOVO — liquidação forçada (MRG-02 CA-02.3)

@dataclass(frozen=True)
class Trade:                       # 2a, com origin migrando para TradeOrigin (valores MARKET/LIMIT/STOP idênticos)
    ticker: str
    entry_date: date;  entry_price: float;  entry_decision_date: date
    exit_date: date | None;  exit_price: float | None;  exit_decision_date: date | None
    quantity: int                  # PODE ser negativo (short) — inteiro
    entry_cost: float;  exit_cost: float
    entry_gap_days: int;  exit_gap_days: int | None
    origin: TradeOrigin | None     # market | limit | stop | margin_call (CA-02.3)
    cut_reason: CutStage | None    # 2a (CST-01.3/R1) — intocado
    rebalance: bool = False        # 2a (SIZ-03) — intocado
    ambiguous: bool                # 2a + novas ambiguidades com buy-stop (ORD-06) — intocado na forma
```

- **PnL realizado algébrico (SHT-04.1):** `realized = (exit_price − entry_price) × quantity` funciona com `quantity < 0` — venda a 100, cobertura a 90, 100 ações ⇒ `(90 − 100) × (−100) = +1000`. **Nenhuma fórmula nova** — a identidade de §6 é a da 2a com o sinal já embutido (RF-SHT-04).
- **Entrada short / cobertura:** venda abre `qty < 0` com `entry_price = preço da venda` (com slippage de venda — SHT-02.1); cobertura (compra) reduz `|qty|` até 0 — a posição **nunca cruza de sinal em um único trade** (EXIT_SHORT acima da posição = EngineError, §3.8).
- **`Position.__post_init__` da 2a** (que rejeitava `quantity <= 0`) é **alterado**: `quantity == 0` continua inválido; `quantity < 0` passa a ser válido (short). É o relaxamento formal do invariante `qty ≥ 0` — coberto pelo ADR-0009.

### 3.3 Margem — `engine/margin.py` (novo, D1/ADR-0009)

```python
@dataclass(frozen=True)
class MarginModel:
    factor: float = 1.0            # default 1.0 EXPLÍCITO e configurável (R3/MRG-01 CA-01.5); > 0
    # fator ÚNICO para long e short — simplificação DECLARADA (R3); a equivalência com
    # dois níveis (fator long × fator short) está documentada como alternativa descartada
    # no ADR-0009 e na spec §8.1.

def margin_requirement(positions: dict[str, Position], closes: dict[str, float],
                       model: MarginModel) -> float:
    """Σᵢ |qtyᵢ| × closeᵢ × factor — valores ABSOLUTOS, nunca soma algébrica (MRG-01 CA-01.1).
       Função PURA. Long-only com factor 1.0 ⇒ notional longo ⇒ equity ≥ notional ⇔ cash ≥ 0
       (MRG-01 CA-01.2 — regressão)."""

def margin_utilization(equity: float, requirement: float) -> float | None:
    """requirement / equity (MRG-01 CA-01.4). equity ≤ 0 ⇒ None (indefinido — fundo quebrado, R6);
       nunca NaN, nunca zero fabricado (MRG-03 CA-03.2)."""

@dataclass(frozen=True)
class MarginCallOrder:             # ordem corretiva — detectada no close, executa no open (D2/ADR-0009)
    ticker: str
    side: Side                     # long → SELL; short → BUY (cobertura)
    qty: int                       # INTEGRAL: |qty| atual da posição (MRG-02 — integral por ativo)
    decision_date: date            # close que detectou — auditoria (padrão ORD-04.4 da 2a)
    intent_seq: int                # contador próprio da sequência de liquidação (laço)
    reason: Literal["margin_call"] = "margin_call"   # origin = MARGIN_CALL no Trade (CA-02.3)

@dataclass(frozen=True)
class BrokenFundState:             # MRG-03 / R6
    broken: bool                   # equity < 0 após liquidação total (CA-03.1)
    final_equity: float            # o valor NEGATIVO REAL, reportado como está (CA-03.2)
    # métricas de retorno (CAGR, Sharpe, turnover, exposição) = None EXPLÍCITO — nunca NaN
    # (lição do ING-05.1; R6). A conciliação CONTINUA fechando com a equity negativa.
```

- **Quem muta, quem lê (checklist 3):** `margin_requirement`/`margin_utilization` são puras (só leem). O laço (backtest.py) é o dono da **detecção** (close) e da **aplicação** do congelamento; o broker (`execute_margin_calls`) é o dono da **execução** (open). `MarginModel`/`MarginCallOrder`/`BrokenFundState` são frozen.
- **Invariante (substitui POR-04.3):** `equity ≥ margin_requirement`, válido **após a fase de execução do open** (pós-liquidação). Violação detectada no **close** é evento normal — agenda liquidação (MRG-01 CA-01.3); violação **persistindo após o open seguinte** é erro de programação (CA-01.3). Janela close→open é a única em que o invariante pode ficar pendente.

### 3.4 Borrow fee — `engine/margin.py` (novo, D3/RF-SHT-03, ADR-0010)

```python
@dataclass(frozen=True)
class BorrowFeeModel:
    fee_annual: float = 0.005                    # default 0,50% a.a. — premissa NÃO calibrada (viés declarado, R1/ADR-0010)
    unlimited: bool = True                       # disponibilidade de aluguel — default ILIMITADA (R1); false ⇒ restrição
    unavailable: frozenset[str] = frozenset()    # ativos indisponíveis para aluguel (configurável)

    def daily_fee(self, qty: float, close: float) -> float:
        """|qty| × close × fee_annual / 252 — diária, sobre o notional short (SHT-03 CA-03.1)."""
    def is_available(self, ticker: str, decision_date: date) -> bool:
        """default: sempre True — a disponibilidade NUNCA bloqueia (CA-03.4, lado ilimitado).
           unlimited=False ⇒ ticker ∈ unavailable na data ⇒ False (CA-03.4, lado restrito)."""
```

- **Débito:** no **close**, em **etapa própria** (depois de marcar, antes de checar margem — §4), do caixa. **Nunca entra no preço de execução** (herda SLP-04.3 da 2a). Incide apenas sobre pregões com posição short **aberta no close** (SHT-03 CA-03.2 — não incide sobre o dia em que a posição já foi coberta no open).
- **Categoria própria no relatório** (CA-03.3) e **termo próprio na conciliação** (§6) — nunca misturado com corretagem/slippage.
- **Disponibilidade (R1):** `unlimited=True` (default) ⇒ nenhum short é bloqueado (CA-03.4 esquerda). `unlimited=False` + ativo indisponível na data ⇒ o `ENTER_SHORT` **não executa**, é **logado e contado** (`MechanismCounters.borrow_rejections`, contado no `convert` — CA-03.4 direita).

### 3.5 Broker 2b — `engine/broker.py` (estendido)

```python
# Buy-stop (D5): OrderKind.STOP com side=BUY — SEM membro novo no enum; o lado discrimina.
#   sell-stop: kind=STOP, side=SELL (2a — protetor de long)
#   buy-stop : kind=STOP, side=BUY  (2b — entrada condicional de compra / stop-loss de short)

def execute_pending(self, store: PendingBook, ticker: str, bar: BarSlice,
                    portfolio: Portfolio, cost_model: CostModel,
                    slippage: SlippageModel, adv: float | None) -> list[Trade]:
    """Regras da 2a PRESERVADAS (regressão zero) + extensões 2b:
       - MARKET BUY/SELL → open ± slippage (2a; short = SELL com qty < 0 — SHT-02.1;
         cobertura = BUY reduzindo |qty| — SHT-02.2, sem cruzar)
       - LIMIT → min/max(L, open) ou cancela ao fim da barra (2a); cover short por buy-limit
         NUNCA viola o limite (SHT-02.4)
       - sell-stop → low ≤ S ? min(S, open) + slippage : persiste (2a)
       - BUY-STOP → high ≥ S ? compra a max(S, open) + slippage de compra : PERMANECE pendente
         (ORD-05 CA-05.1/05.2); nunca debita caixa antes de disparar (CA-05.3);
         ativação por side × ENG-05: tabela explícita abaixo (emenda P1)
       - Custos max(f + p·N, m) fora do preço (2a/SLP-04.3); gap registrado (2a);
         origin = TradeOrigin no Trade (auditoria ENG-01.2; MARGIN_CALL só via execute_margin_calls)
       - Ambiguidades intrabarra (par na mesma barra) → pior caso (ADR-0007 estendido — §4),
         Trade.ambiguous = True, contadas no MechanismCounters (ORD-06 CA-06.3)"""

def execute_margin_calls(self, plan: tuple[MarginCallOrder, ...], bar: BarSlice,
                         portfolio: Portfolio, cost_model: CostModel,
                         slippage: SlippageModel) -> list[Trade]:
    """Executa a liquidação forçada do ativo contra o open do PRÓPRIO ativo (ADR-0002):
       cada ordem vira trade com origin = MARGIN_CALL (CA-02.3); custos/slippage como qualquer
       ordem a mercado (herda SLP-04). Determinístico (CA-02.4)."""
```

- **`Broker.convert` ganha o sinal (D3):** para `ENTER_SHORT`, a fração do sizer é aplicada como **magnitude** e o alvo vira negativo (`qty = −⌊fração × equity / ref_price⌋`), passando pela MESMA sequência fixa da 2a (SIZING → CAP → INTEIRAS → CAIXA/CUSTOS, R1) e pelo cap de participação (SHT-02.3 — mesma regra e motivo, `cut_reason`). `ref_price = last_close[ticker]` (2a).
- **Barreira P2 da 2a REMOVIDA (emenda P1 — regressão esperada e documentada):** na 2a, `convert` rejeitava `OrderKind.STOP` com `EngineError` ("buy-stop é escopo da 2b (P2)"). Na 2b o STOP vira **kind VÁLIDO de entrada** (buy-stop, ver regra de ativação abaixo) — o guard é removido e o teste 2a `test_convert_domain_errors_raise_engine_error` (`tests/unit/test_broker.py`) **perde o bloco `pytest.raises(EngineError)` do buy-stop** (regressão intencional do portão 2a, documentada); a intenção STOP ganha teste próprio (`test_convert_accepts_buy_stop`, §10). O ramo morto de `_execute_entry` (entrada STOP ⇒ `EngineError`, pragma "barrado por convert") também desaparece: buy-stop vira caminho real de execução.
- **Ativação por side × guard ENG-05 (emenda P1 — regra explícita para os dois stops):**

  | Ordem pendente | Sem posição | Posição LONG aberta | Posição SHORT aberta |
  |---|---|---|---|
  | sell-stop (STOP, SELL — 2a) | permanece pendente, nunca ativa (ORD-02.2) | **ativa** a `min(S, open)` + slippage venda; vende a posição inteira | permanece pendente, nunca ativa (não existe "vender mais short" sem intenção `ENTER_SHORT` — espelho do ORD-02.2) |
  | buy-stop (STOP, BUY — 2b) | **ativa**: entra long a `max(S, open)` + slippage compra (ORD-05.1) | **guard ENG-05 da Fase 1**: ignorado e **consumido** (log `engine.enter_with_open_position`), como `ENTER` com posição — nunca duas posições do mesmo sinal | **ativa como COBERTURA** (o stop-loss do short, ORD-06): compra que reduz `\|qty\|` até 0, **nunca cruza de sinal** (SHT-02.2) — o guard ENG-05 não se aplica |

  O guard ENG-05 se aplica ao buy-stop **apenas quando o sinal da posição aberta é o MESMO da entrada** (LONG): aí a ordem morre consumida, como o `ENTER` da Fase 1. Sobre SHORT, o buy-stop é a cobertura do stop-loss e executa sempre.
- **Borrow fee × cap:** o fee é custo de carregamento (diário), não custo de transação — o `convert` não o usa; ele entra no caixa no close (§4). A disponibilidade (`BorrowFeeModel.is_available`) é checada no `convert` de `ENTER_SHORT`: indisponível ⇒ `None` + log + `borrow_rejections += 1` (CA-03.4 direita).
- **Débito do fee no caixa:** função do laço (§4), não do broker — o broker não conhece o `BorrowFeeModel`; a conciliação (§6) soma o termo próprio.

### 3.6 Walk-forward — `engine/walkforward.py` (novo, D6/D7/ADR-0011)

```python
@dataclass(frozen=True)
class Fold:
    is_start: date;  is_end: date
    oos_start: date; oos_end: date
    # IS e OOS DISJUNTOS (oos_start = dia útil seguinte a is_end — WFK-01 CA-01.2);
    # a união dos segmentos OOS cobre a janela avaliada SEM sobreposição (CA-01.2).
    # Rolling (default, D7): |IS| fixo; Anchored (configurável): |IS| cresce — para MEDIR a diferença.

@dataclass(frozen=True)
class ParameterGrid:
    params: tuple[dict[str, float], ...]   # combinações EXPLÍCITAS (ex.: SmaCross {10, 20, …, 60})
    seed: int | None = None                # otimizador estocástico ⇒ seed TRAVADO e declarado (RNF-01);
                                           # a grade default é determinística por construção (WFK-02 CA-02.1)

@dataclass(frozen=True)
class FoldMetrics:
    sharpe_is: float                       # Sharpe anualizado, rf=0, sobre a equity IS — MÉTRICA DE SELEÇÃO (R5/WFK-02 CA-02.3)
    ret_oos: float | None                  # retorno do segmento OOS; None sse fundo quebrado no fold (MRG-03/R6)
    sharpe_oos: float | None
    max_dd_oos: float | None

@dataclass(frozen=True)
class FoldResult:
    fold: Fold
    selected_params: dict[str, float]      # usados no OOS DO MESMO fold (WFK-02 CA-02.2), nunca de outro
    is_metrics: FoldMetrics
    oos_metrics: FoldMetrics

@dataclass(frozen=True)
class WalkForwardResult:
    folds: tuple[FoldResult, ...]
    oos_equity: tuple[float, ...]          # CONCATENAÇÃO EXATA dos segmentos OOS (WFK-03 CA-03.1)
    oos_dates: tuple[date, ...]            # naive (RNF-07)
    broken_fund: bool                      # algum fold quebrou o fundo ⇒ métricas None + exclusão de comparação automática (CA-03.3)
    grid_size: int                         # |grid| — declarado no MHT (CA-06.2)
    n_folds: int

def build_folds(start: date, end: date, is_window: int, oos_window: int,
                anchor: Literal["rolling", "anchored"] = "rolling") -> tuple[Fold, ...]:
    """Determinístico (RNF-01). rolling = default (D7 — decisão do autor, R7);
       anchored = configurável para medir a diferença. Fold inválido ⇒ EngineError (§3.8)."""

def run_walkforward(series: dict[str, PriceSeries], strategy_factory: Callable[[dict[str, float]], Strategy],
                    grid: ParameterGrid, folds: tuple[Fold, ...], *,
                    initial_cash: float, costs: CostModel, slippage: SlippageModel, cap: float,
                    margin: MarginModel, borrow: BorrowFeeModel, sizer: Sizer, warmup: int) -> WalkForwardResult:
    """CAIXA PRETA por fold (§2): cada run IS/OOS chama run_backtest_multi com a MESMA configuração
       do run único — herança por construção (filosofia do benchmark 1/N da T15).
       1. IS: séries truncadas no fim do IS → corre a grade → seleciona por sharpe_annualized_rf0
          (R5, WFK-02 CA-02.3) — a série OOS NÃO é passada (isolamento por construção, CA-01.1).
       2. OOS: série composta = CAUDA DO IS (últimas `warmup` barras ≤ fronteira, R4) + segmento OOS,
          rodada como run_backtest_multi com a MESMA instância de estratégia (warmup base = `warmup`).
          MECANISMO (emenda P1): o laço consulta on_bar apenas em i ≥ warmup e, como
          len(cauda) = warmup, a PRIMEIRA barra consultada é o PRIMEIRO bar OOS — a estratégia
          NUNCA é consultada (nem trade) na cauda: a cauda entra SÓ como histórico do MarketView
          (indicadores aquecem), barras ≤ fronteira do IS, sem lookahead (CA-01.3).
          oos_equity = equity_curve[tail_len:] — concatenação exata (CA-03.1); a equity da cauda
          é descartada (aquecimento). Pré-condição: strategy.warmup == warmup, senão o corte da
          cauda desalinha com o gate de consulta (EngineError, §3.8).
          Parâmetros = selecionados no IS DO MESMO fold (CA-02.2).
       3. Concatena os segmentos OOS (CA-03.1)."""

def sharpe_annualized_rf0(returns: Sequence[float]) -> float:
    """Forma fechada ÚNICA — vive AQUI (engine) e é IMPORTADA por analytics/metrics.py:
       seleção IS (R5) e relatório (MHT, CA-06.2) usam a MESMA implementação (sem drift).
       Série vazia ou com desvio 0 ⇒ None explícito (nunca NaN — R6)."""
```

- **Isolamento estrito por construção (CA-01.1):** o fold entrega ao run IS séries **truncadas** (`series[X]` cortada em `is_end`); o `UnionCalendar` do IS cobre só a janela IS; o `MarketView` indexa o array truncado — qualquer acesso além do fim é `EngineError` (guarda de fronteira no próprio array, testável: `test_is_run_never_indexes_oos_bars_engine_error`). Não basta "não passar a série": o acesso é bloqueado por construção.
- **Warmup do OOS (R4, emenda P1):** a cauda do IS entra na série composta do OOS **como histórico puro** — o mecanismo é o próprio gate de warmup do laço (i ≥ warmup com len(cauda) = warmup), sem mecanismo novo: a estratégia nunca trade a cauda, e mutar o OOS não altera a cauda ⇒ não altera o warmup (CA-01.3).
- **Orçamento (RNF-10/WFK-05):** por fold (default 30 s para IS+OOS de 20 ativos × janela) e total (default `n_folds × 30 s` + margem declarada). O harness mede ambos (CA-05.1); sem base ingerida, usa séries sintéticas determinísticas e declara a origem (padrão T17).

### 3.7 Resultado e contadores — estendidos (agregação: dono declarado, checklist 4)

```python
@dataclass(frozen=True)
class MechanismCounters:            # 2a + 2 — incrementados APENAS pelo engine; relatório só reporta (lição da 2a)
    stops_triggered: int            # 2a — derivado dos trades com origin=STOP (laço)
    intrabar_ambiguities: int       # 2a + novas (brackets com buy-stop — ORD-06 CA-06.3) — derivado dos trades ambiguous
    unfilled_cash_orders: int       # 2a — contado no broker (convert/execute_pending)
    margin_calls: int               # 2b — nº de trades de liquidação forçada (origin=MARGIN_CALL) (MRG-02 CA-02.3)
    borrow_rejections: int          # 2b — ENTER_SHORT bloqueado por indisponibilidade (SHT-03 CA-03.4) —
                                    #   contado no broker.convert (como unfilled_cash_orders da 2a)

@dataclass(frozen=True)
class BacktestResultMulti:          # 2a + 2b (campos novos)
    # ... 2a: dates, equity_curve, portfolio, initial_cash, n, tickers, warmup, costs,
    #         slippage, cap, calendar, pending_dead, delisted, counters
    broken_fund: bool               # MRG-03 CA-03.1 — métricas None derivam daqui (R6)
    borrow_fees: float              # Σ fees debitados — termo próprio da conciliação (§6); acumulado no laço
    margin: MarginModel             # config do run (reconstruível do JSON — RF-CON-02/CA-06.2)
    borrow: BorrowFeeModel          # config do run (idem)

@dataclass(frozen=True)
class ReconciliationReport:         # 2a + total_borrow_fees (RF-SHT-04 estende RF-POR-04 CA-04.2)
    initial_equity: float
    final_equity: float
    realized_pnl: float             # Σ bruto (custos FORA — §4.6 da 2a); algebricamente correto com qty < 0
    unrealized_pnl: float           # Σ (último_close − entrada) × qty — inclui travada (2a) e shorts (SHT-04.2)
    total_costs: float              # Σ (entry_cost + exit_cost) — uma única vez, termo próprio (armadilha T13)
    total_borrow_fees: float        # Σ |qty_short| × close × fee/252 (SHT-03) — termo próprio, UMA vez
    @property
    def reconciles(self) -> bool: ...   # math.isclose(rel_tol=1e-9, abs_tol=1e-9); nunca igualdade exata (RNF-08)
```

- **Dono de cada agregação (checklist 4):** `margin_calls` e `intrabar_ambiguities` (novas) são **derivados pelo laço** dos trades de execução (`origin == MARGIN_CALL` / `ambiguous`), como a 2a faz com stops — 1 trade por ocorrência. `borrow_rejections` é **contado no broker.convert** (onde o evento acontece), como `unfilled_cash_orders`. `borrow_fees` é **acumulado no laço** no débito do close. O relatório só reporta.

### 3.9 Fronteira de instante — §3.7 da 2a estendido (RNF-07)

| Camada | Tipo de data | Responsável pela conversão |
|---|---|---|
| yfinance | `pd.Timestamp`, às vezes tz-aware | — |
| `ingestion/normalizer.py` | converte para `datetime.date` | **fronteira de entrada** |
| domínio (`engine/`, `analytics/`, `strategies/`, módulos novos) | `datetime.date` sempre | nunca converte |
| `storage/repository.py` | `date` ⇄ `datetime` 00:00 UTC | **fronteira de saída** |

Regra mantida na íntegra: a classe `datetime` e o aparato de fuso (`timezone`, `tzinfo`, `UTC`) só podem aparecer em `ingestion/normalizer.py` e `storage/repository.py`; `date`/`timedelta` são livres. Os módulos novos — `margin.py`, `walkforward.py` — e os estendidos (`broker`, `portfolio`, `conditional`, `backtest`, `analytics`) **não tocam o aparato de fuso** (nas 2b: `MarginCallOrder.decision_date`, `Fold.*`, `WalkForwardResult.oos_dates` são `date` naive). `current_execution_date()` continua o único ponto de leitura do relógio (RF-CON-01). O teste de arquitetura existente é estendido a `margin.py` e `walkforward.py` e permanece bloqueante no CI.

### 3.8 Exceções — pré/pós-condições por interface (checklist do gate 2)

| Interface | Pré-condições | Pós-condições | Exceções |
|---|---|---|---|
| `Signal` (ENUM) | — | `ENTER_SHORT` ⇒ alvo negativo na conversão; `EXIT_SHORT` ⇒ cobertura (reduz `\|qty\|`, nunca cruza); long-only emite só ENTER/EXIT (SHT-01.1) | `EngineError` se `EXIT_SHORT` sem posição short aberta (SHT-01.3); `EXIT` sem long preserva a 2a |
| `Position` | `quantity != 0`; inteiro | `quantity < 0` válido (short); `entry_price` = preço da venda no short (SHT-02.1) | `EngineError` se `quantity == 0`; `EngineError` se cobertura exceder `\|qty\|` (cruzar) |
| `TradeOrigin` | — | valores MARKET/LIMIT/STOP espelham `OrderKind` (compat 2a); `MARGIN_CALL` só existe como origin de Trade — nunca `PendingOrder.kind` (a ordem subjacente é MARKET) | — |
| `MarginModel` | `factor > 0` | `factor` default 1.0 (R3/CA-01.5) | `EngineError` se `factor ≤ 0` |
| `margin_requirement(positions, closes, model)` | `closes` cobre todas as posições; preços > 0 | `Σ\|qtyᵢ\| × closeᵢ × factor` (valores absolutos — CA-01.1); long-only + factor 1.0 ⇒ notional longo (CA-01.2) | `EngineError` se preço ≤ 0 ou `closes` incompleto |
| `margin_utilization(equity, requirement)` | `requirement ≥ 0` | `requirement / equity`; `equity ≤ 0` ⇒ `None` explícito (R6 — nunca NaN) | — |
| `MarginCallOrder` | `side`/`qty` coerentes com a posição | `qty = \|qty_atual\|` (integral por ativo — MRG-02); `decision_date` = close que detectou; imutável | `EngineError` se ativo sem posição ou `qty ≤ 0` |
| `BrokenFundState` | — | `broken = equity < 0` após liquidação total; métricas = `None` explícito (CA-03.2); conciliação continua fechando (CA-03.2) | — (estado declarado, não exceção) |
| `BorrowFeeModel.daily_fee(qty, close)` | `close > 0`; `qty != 0` | `\|qty\| × close × fee_annual/252` (CA-03.1) | `EngineError` se `close ≤ 0` |
| `BorrowFeeModel.is_available(ticker, decision_date)` | — | `unlimited=True` ⇒ sempre True (CA-03.4 esq.); `unlimited=False` ⇒ `ticker ∉ unavailable` (CA-03.4 dir.) | — |
| `Broker.convert` (2b) | intenção de entrada válida (2a §3.8) + disponibilidade (se SHORT e restrita) | sequência fixa da 2a (SIZING → CAP → INTEIRAS → CAIXA/CUSTOS); alvo negativo em SHORT (SHT-01.2); `cut_reason` registrado; indisponível ⇒ `None` + log + `borrow_rejections += 1` (CA-03.4); **kind STOP (buy-stop) é entrada VÁLIDA — barreira P2 da 2a removida (emenda P1, §3.5)** | `EngineError` se `EXIT_SHORT` sem posição (SHT-01.3) |
| `Broker.execute_pending` (2b) | barra do próprio ativo (ADR-0002); preços > 0 | regras da 2a preservadas + buy-stop (`high ≥ S` ⇒ `max(S, open)` + slippage compra; persiste senão — ORD-05 CA-05.1/05.2); **ativação por side × ENG-05: sem posição ⇒ entrada long; LONG aberta ⇒ ignorada + consumida (guard); SHORT aberta ⇒ cobertura que reduz `\|qty\|`, nunca cruza (SHT-02.2)** (emenda P1); sem reserva (CA-05.3); `origin` no Trade (auditoria) | `EngineError` se preço ≤ 0 ou barra malformada |
| `Broker.execute_margin_calls(plan, bar, portfolio, cost_model, slippage)` | plano do ativo com posição aberta; barra do próprio ativo | liquidação integral a mercado (open) com slippage; `origin = MARGIN_CALL` (CA-02.3); custos fora do preço (SLP-04.3); determinístico (CA-02.4) | `EngineError` se ativo sem posição ou preço ≤ 0 |
| `Fold` | `is_start ≤ is_end < oos_start ≤ oos_end`; janelas dentro da série | IS/OOS disjuntos; união dos OOS cobre a janela sem sobreposição (CA-01.2) | `EngineError` se `is_end ≥ oos_start` ou janelas fora da série |
| `build_folds(...)` | `is_window, oos_window ≥ 1`; `start < end` | folds determinísticos; `anchor="rolling"` default (D7/R7) | `EngineError` se janelas inválidas ou série curta demais |
| `ParameterGrid` | `params` não vazio; `seed` travado se otimizador estocástico | grade determinística (CA-02.1); `grid_size` declarado (MHT — CA-06.2) | `EngineError` se `params` vazio |
| `run_walkforward(...)` | `folds` não vazio; `grid.params` não vazio; séries cobrem a janela | IS nunca indexa OOS (CA-01.1); OOS usa params do mesmo fold (CA-02.2); seleção = `sharpe_annualized_rf0` na equity IS (CA-02.3); resultado = concatenação OOS (CA-03.1); warmup pela cauda do IS (CA-01.3) | `EngineError` se fold inválido, grid vazio, ou acesso IS a barra OOS (construção) |
| `sharpe_annualized_rf0(returns)` | — | forma fechada única (seleção IS e relatório — sem drift); série vazia/desvio 0 ⇒ `None` (R6) | — |
| `WalkForwardResult` | — | `oos_equity` = concatenação exata (CA-03.1); `broken_fund` exclui de comparação automática (CA-03.3); imutável | — |
| `MechanismCounters` | — | incrementados apenas pelo engine; donos declarados (§3.7); relatório só reporta | — |
| `BacktestResultMulti` (2b) | — | `broken_fund`/`borrow_fees`/`margin`/`borrow` presentes e reconstruíveis do JSON (RF-CON-02/CA-06.2) | — |
| `ReconciliationReport` | result de um run 2b | parcelas completas (incl. `total_borrow_fees`, uma única vez); `reconciles` = `isclose(1e-9)` com `qty < 0` (CA-04.2) | `EngineError` se result inválido (erro de programa) |
| Laço 2b (§4) | invariantes da 2a + janela close→open | `equity ≥ margem` pós-open (CA-01.3); fundo quebrado congelado (CA-03.1); determinismo (RNF-01) | `EngineError` se violação persistir após o open (CA-01.3) |

## 4. Fluxo da barra 2b — laço multi-ativo estendido

Para cada índice-união `u` em `0..D-1` (em cada fase, ativos processados em **ordem alfabética** — determinismo e caixa compartilhado). A sequência é **declarada como invariante** (lição T11a): executar antes de marcar, marcar antes de debitar fee, debitar antes de checar margem, checar antes de consultar.

```
1. EXECUTAR — para cada X com bar_index[X][u] ≥ 0 (alfabético):
   i = bar_index[X][u]
   a. LIQUIDAÇÕES (plano da véspera — MRG-02, ADR-0002): se o plano contém X,
      broker.execute_margin_calls(plano[X], barra_i, ...) — MARKET no open[i]:
      long → SELL, short → BUY (cobertura), origin = MARGIN_CALL (CA-02.3);
      após CADA ativo liquidado, o laço re-checa a margem aos preços de execução
      e interrompe quando restaurada (CA-02.1). Plano esgotado + margem ainda
      violada com equity ≥ 0 ⇒ EngineError (CA-01.3). FUNDO QUEBRADO POR GAP —
      cronologia explícita (emenda P1): (1) liquidação integral executada no
      open do próprio ativo, ao preço do GAP (ADR-0002); (2) re-cheque constata
      equity < 0 após liquidar tudo; (3) CONGELA — nenhum trade novo, pendentes
      canceladas, intenções seguintes descartadas, flag = true, equity reportada
      negativa real (CA-03.1); (4) métricas de retorno derivam None explícito
      (R6/CA-03.2 — o relatório §7 nunca emite NaN) e a conciliação continua
      fechando com a equity negativa (CA-03.2). [borda rara: ativo do plano sem
      barra em u ⇒ não liquida nesta u; se ao fim do dia a margem persistir
      violada, é o caminho do CA-01.3]
   b. PENDENTES regulares (se não congelado): broker.execute_pending(...) — MARKET,
      LIMIT, sell-stop (2a) + buy-stop (ORD-05): high[i] ≥ S ⇒ compra a max(S, open[i])
      + slippage de compra (CA-05.1); não disparado ⇒ PERMANECE (CA-05.2); nunca
      debita caixa antes (CA-05.3). Ativação por side × ENG-05 (tabela §3.5, emenda
      P1): sem posição ⇒ entrada long; LONG aberta ⇒ guard ignora e consome (log);
      SHORT aberta ⇒ cobertura do stop-loss (reduz |qty|, nunca cruza — SHT-02.2);
      sell-stop ativa só com LONG (2a ORD-02.2 estendido). Caixa insuficiente ⇒
      atendimento alfabético, não-atendida logada e contada (2a POR-01.2, mantido).
   c. REBALANCE (2a, só EqualWeightOpen) — inalterado.

2. MARCAR A MERCADO (close): equity[u] = cash + Σ_X qty[X] × close_conhecido(X, u)
   — último close conhecido (2a POR-02.2); posição travada entra pelo último close (2a).

3. DEBITAR BORROW FEE (SHT-03, etapa própria): para cada X com short ABERTO no close,
   cash −= BorrowFeeModel.daily_fee(qty_X, close_X); borrow_fees += valor (CA-03.1/03.2);
   NUNCA entra no preço de execução (herda SLP-04.3); categoria própria no relatório (CA-03.3).

4. CHECAR MARGEM (MRG-01): margem = margin_requirement(...); se equity[u] < margem:
   build_liquidation_plan — posições abertas em ordem ALFABÉTICA, INTEGRAL por ativo,
   cancelando as pendentes de cada ativo do plano (CA-02.2) → MarginCallOrder(s) para o
   open da próxima barra do PRÓPRIO ativo (ADR-0002). Violação aqui NÃO é erro (CA-01.3 —
   janela close→open). Se não há posições e equity < 0 ⇒ fundo quebrado (passo 1a).

5. CONSULTAR (se não congelado) — para cada X com bar_index[X][u] ≥ 0 e i ≥ warmup (alfabético):
   intent = strategies[X].on_bar(MarketView_X(i))
   ENTER/ENTER_SHORT → convert (sizing→cap→inteiras→caixa/custos; sinal aplicado aqui — D3)
     → place (última intenção vence — 2a ORD-04.2); indisponível (SHORT restrito) ⇒ None + contado
   EXIT → cancel_all + saída ao open (2a); EXIT_SHORT sem posição short ⇒ EngineError (SHT-01.3)
   ENG-01.4 POR ATIVO (C1 da 2a, mantido): intenção na última barra de X morre pendente e é reportada.

6. INVARIANTES (erro de programação): equity ≥ margem após o passo 1 (exceto fundo quebrado,
   onde vale o congelamento); k ≤ N (2a SIZ-04.3); determinismo (RNF-01); janela close→open
   respeitada (violação detectada no close NÃO é erro; persistir após o open É — CA-01.3).
```

**Restrições herdadas, preservadas por ativo:** executar antes de marcar (equity de `u` reflete a posição real) e executar antes de consultar (ADR-0002 em código). A ordem **marcar → fee → margem → consultar** é nova e declarada como invariante: o fee usa o close (marcação), a margem usa o caixa pós-fee, e a consulta usa o close (sem efeito colateral — ENG-05.2, 2a). Uma inversão de qualquer par derruba a auditoria (ENG-01.2 parte 1) ou a semântica de margem.

**Ambiguidades intrabarra — ADR-0007 estendido (D5/RF-ORD-06):**

| Cenário | Resolução | `Trade.ambiguous` |
|---|---|---|
| Bracket long de **entrada** (buy-stop `S_e` + sell-stop `S_s`, `S_s < S_e`), ambos tocados na mesma barra | Posição **abre no buy-stop `S_e`** e **fecha no sell-stop `S_s` na mesma barra** ⇒ perda realizada `(S_e − S_s + custos)`, fica **flat** (espelha o pior caso de entrada da 2a com os tipos invertidos — CA-06.1) | `True` |
| Bracket short (take-profit buy-limit `TP` + stop-loss buy-stop `SL`, `SL > TP`), ambos tocados | O short é **coberto no buy-stop `SL`** (pior caso), **nunca no limite** (CA-06.2) | `True` |

Ambos incrementam `MechanismCounters.intrabar_ambiguities` (ORD-06 CA-06.3) — mesma contagem da 2a, derivada dos trades com `ambiguous=True`. **Nunca "ambos executam"** (CA-03.3 da 2a mantido): a ambiguidade resolve no pior caso, sem dupla contagem. **Sem stop órfão (herança T09):** o sell-stop de um bracket de entrada só ativa com posição aberta (2a ORD-02.2); no bracket via **buy-stop**, se o buy-stop nunca dispara, o sell-stop do par **permanece pendente junto** (o buy-stop é uma entrada condicional persistente — CA-05.2 — a intenção não morreu); o sell-stop continua incapaz de ativar sem posição. A regra do "stop órfão" (Q2 da 2a) continua valendo para o bracket por **limite**: se o limite cancela ao fim da barra, o stop do mesmo par sai junto.

## 5. Bordas

- **Short com deslistagem (RF-SHT-05):** posição short cuja série termina antes do fim do run ⇒ **travada** no último close conhecido (mesma semântica de POR-02.3 da 2a), passivo marcado na equity, **reportada** com categoria própria (CA-05.1/05.2). Nunca liquidada a preço inventado.
- **Short atravessando data ex-dividendo (SHT-04 CA-04.3):** o PnL da posição short ≡ retorno do preço **ajustado** no período — o modelo de ajuste da Fase 1 (dividendos via preço, premissa 8) é declarado consistente para `qty < 0`; teste de forma fechada (§10), sem reimplementar ajuste.
- **Fundo quebrado por gap (MRG-03/R6):** após liquidar tudo, `equity < 0` ⇒ congela, reporta o valor negativo real, métricas `None` explícito (nunca `NaN` — lição do ING-05.1), conciliação continua fechando (CA-03.2), exclusão de comparações automáticas (CA-03.3).
- **Ativo sem barra na janela (2a R2, mantido):** conta no N, nunca recebe alvo, contribui zero, reportado não-negociado — também vale com shorts (nenhum short de ativo sem barra).
- **Ativo do plano de liquidação sem barra em `u` (borda rara):** a liquidação espera a próxima barra do próprio ativo (ADR-0002 por ativo); se a margem persistir violada após o open seguinte, é o caminho do `EngineError` de CA-01.3 — nunca preço inventado.

## 6. Conciliação estendida — RF-SHT-04 + §4.6 da 2a

```
pnl_realizado(trade)       = (saída − entrada) × quantidade          [BRUTO — custos fora; qty < 0 OK (SHT-04.1)]
pnl_nao_realizado(ativo i) = (último_close_conhecido_i − entrada_i) × quantidade_i
                             [qty pode ser negativo (SHT-04.2); inclui posição travada (2a POR-02.3)]
custo_total                = Σ (entry_cost + exit_cost)              [uma única vez, termo próprio — armadilha T13]
borrow_fees                = Σ_d Σ_i |qty_shortᵢ| × closeᵢ × fee/252  [termo próprio, debitado no close (SHT-03)]
equity_final − equity_inicial ≡ Σ realizado + Σ não_realizado − custo_total − borrow_fees
```

- Soma sobre os **N ativos do run**, incluindo o nunca-negociado (contribui zero — R2 da 2a, mantido).
- Verificação com `math.isclose(rel_tol=1e-9)`, conforme RNF-08. Nunca igualdade exata.
- Fundo quebrado: a identidade fecha com a **equity negativa real** (CA-03.2).
- **`ReconciliationReport` estendido** (§3.7): ganha `total_borrow_fees` — o termo entra **uma única vez** (a armadilha da dupla contagem da T13 vale também para o fee: nunca somar fee dentro de `total_costs` E no termo próprio).

## 7. Analytics — métricas, benchmark, relatório

```python
# analytics/metrics.py (estendido) — fórmulas da 2b, MESMAS definições para estratégia e benchmark onde aplicável
def gross_exposure_avg(daily_gross_notional: Sequence[float], equity_daily: Sequence[float]) -> float:
    """média diária de (Σᵢ |qtyᵢ| × closeᵢ) / equity — pode exceder 100% (alavancada, MRG-04 CA-04.2)."""
def net_exposure_avg(daily_net_notional: Sequence[float], equity_daily: Sequence[float]) -> float:
    """média diária de (Σᵢ qtyᵢ × closeᵢ) / equity — longs e shorts se cancelam; pode ser negativa (MRG-04 CA-04.1)."""
def margin_utilization_avg(daily_requirement: Sequence[float], equity_daily: Sequence[float]) -> float | None:
    """média diária de margem/equity (MRG-01 CA-01.4); equity ≤ 0 ⇒ None (R6)."""
def turnover_annualized(trades, equity_daily, n_bars) -> float:
    """2a INTOCADA — (Σ|notional_compra| + Σ|notional_venda|)/(2×patrimônio_médio)×(252/n_barras);
       |notional| já funciona com qty < 0 (MRG-04)."""
def sharpe_annualized_rf0(returns) -> float:
    """IMPORTADO de engine/walkforward.py — FONTE ÚNICA da forma fechada
       (média/desvio × √252, rf=0 — R5/CA-06.2). Emenda P1: o `sharpe()` da
       Fase 1/2a em analytics/metrics.py (usado pelo relatório, report.py) passa
       a DELEGAR para este helper — uma única implementação, zero drift entre
       seleção IS e relatório (sem duas fórmulas)."""

# analytics/benchmark.py — INTOCADO: buy_and_hold_multi da 2a = 1/N long-only (RF-MET-05 CA-05.1/05.2).
#   O benchmark NUNCA short e NUNCA usa margem — é a mesma função, mesma configuração do run único da 2a.

# analytics/report.py (estendido) — seções 2b:
#   - Contadores: margin_calls, borrow_rejections + 2a (CA-02.3, CA-03.4)
#   - Fundo quebrado: flag + CAGR/Sharpe/turnover/exposição = None explícito (R6/CA-03.2);
#     exclusão de comparação automática com benchmark (CA-03.3)
#   - Seção "run": universo, capital, custos/slippage/cap/margem/borrow configurados, n_barras,
#     datas efetivas, resultado do benchmark 1/N — RECONSTRUÍVEL do JSON isolado (RF-CON-02/CA-06.2);
#     com walk-forward: métrica de seleção (Sharpe anualizado rf=0), grid size e nº de folds (MHT — CA-06.2)
#   - Vieses novos (constante literal, padrão Fase 1 §5.2 — CA-06.1): aluguel NÃO calibrado (default
#     0,50% a.a. é premissa); disponibilidade de aluguel ILIMITADA (sem hard-to-borrow — otimista);
#     liquidação alfabética é determinística mas qualquer regra de seleção é seleção com viés;
#     MHT: seleção IS otimista com métrica/grid/folds declarados; pior caso ampliado aos brackets
#     com buy-stop; + itens da 2a preservados
#   - Alavancagem (gross > 100%) reportada junto com a utilização de margem (CA-04.2)
#   - Borrow fee em categoria própria (CA-03.3); short travado com categoria própria (CA-05.2)
```

**Harness do WF (RNF-10/WFK-05):** mede o walk-forward em duas escalas — por fold (default 30 s para IS+OOS de 20 ativos × janela) e total (`n_folds × 30 s` + margem declarada) — com o escopo declarado (cômputo apenas, padrão T17/P5 da 2a); sem base ingerida, séries sintéticas determinísticas com a origem declarada. O "30 s" do RNF-04 da 2a continua valendo para o **run único** e não se aplica a centenas de runs (RNF-10).

## 8. Decisões D1–D7 — compromisso do design

| # | Decisão (spec v0.2) | Compromisso do design | ADR |
|---|---|---|---|
| D1 | Invariante de margem: `equity ≥ Σ\|qtyᵢ\|×closeᵢ×factor`, factor default 1.0 | §3.3/§3.8 — `MarginModel`, `margin_requirement` pura, checada no laço (§4); regressão long-only (CA-01.2) | **ADR-0009** |
| D2 | Liquidação forçada: close detecta → open executa; alfabética; integral por ativo; cancela pendentes; `origin = MARGIN_CALL`; fundo quebrado congela | §3.3/§3.5/§4 — plano no close, `execute_margin_calls` no open, re-cheque por ativo, `BrokenFundState` com `None` explícito | **ADR-0009** (com D1) |
| D3 | Direção no `Signal`; sizer nunca decide direção | §3.1 — `ENTER_SHORT`/`EXIT_SHORT` retrocompatível; conversão aplica o sinal; fee de aluguel (RF-SHT-03) | contrato (§3.1); fee → **ADR-0010** |
| D4 | Exposição gross/net lado a lado; turnover com `\|notional\|`; alavancagem explícita | §7 — `gross_exposure_avg`/`net_exposure_avg`; turnover 2a intocada (já funciona com `qty < 0`) | fórmulas (RF-MRG-04) |
| D5 | Buy-stop a `max(S, open)` + slippage; pior caso nos brackets com buy-stop | §3.5/§4 — `OrderKind.STOP` com `side=BUY`; tabela de ambiguidades estendida | estende ADR-0007 (RF-ORD-05/06) |
| D6 | Walk-forward: grade determinística; isolamento estrito; resultado = concatenação OOS; MHT declarado; seleção = Sharpe anualizado rf=0 | §3.6/§7 — folds truncados por construção; caixa preta sobre `run_backtest_multi`; `sharpe_annualized_rf0` única | **ADR-0011** |
| D7 | Ancoragem: rolling default; anchored configurável (decisão do autor, R7) | §3.6 — `build_folds(anchor="rolling")` default | **ADR-0011** (com D6) |

## 9. Fora do escopo

Opções, futuros e derivativos; fracionário (quantidades inteiras — SIZ-01 da 2a); múltiplas moedas; impostos; high-frequency / dados intraday; Redis; rebalance por alvo de risco (risk parity); empréstimo com colateral e gestão de garantias real (o modelo de margem da 2b é determinístico de backtest, não sistema de clearing); **hard-to-borrow real** (disponibilidade ilimitada por default, restrição configurável — R1).

## 10. Invariantes e testes nomeados (gate 2)

### 10.1 Invariantes centrais

| Invariante | Como é garantido | Teste que prova |
|---|---|---|
| Direção no Signal retrocompatível (SHT-01.1/D3) | Enum estendido; long-only emite só ENTER/EXIT | `test_signal_contract_is_backward_compatible_long_only` |
| Margem como invariante (MRG-01; substitui POR-04.3) | Checada no laço (§4), pós-open | `test_margin_invariant_reduces_to_cash_ge_zero_long_only`; `test_margin_breach_close_to_open_window_allowed_then_error` |
| Liquidação determinística (MRG-02 CA-02.4) | Seleção alfabética no engine, sem preço como critério | `test_forced_liquidation_deterministic_across_runs` |
| Fundo quebrado: métricas `None` explícito, nunca NaN (R6/CA-03.2) | `BrokenFundState` + relatório | `test_broken_fund_metrics_are_explicit_none_never_nan` |
| Buy-stop = `max(S, open)` + slippage; persiste; sem reserva; ativação por side × ENG-05 (ORD-05, emenda P1) | Regra no broker (espelha sell-stop) | `test_buy_stop_executes_at_max_stop_open_with_buy_slippage`; `test_buy_stop_undispatched_persists_to_next_bar_of_own_asset`; `test_buy_stop_never_dispatched_never_debits_cash`; `test_buy_stop_with_open_long_is_ignored_and_consumed`; `test_buy_stop_over_short_covers_never_crosses` |
| Pior caso intrabarra com buy-stop (ORD-06/ADR-0007 estendido) | Tabela §4, sem "ambos executam" | `test_intrabar_ambiguity_buy_stop_entry_bracket_worst_case`; `test_intrabar_ambiguity_short_bracket_stop_wins_over_tp` |
| Isolamento estrito IS/OOS (WFK-01 CA-01.1) | Série truncada no fold; guard no array | `test_is_run_never_indexes_oos_bars_engine_error` |
| Warmup OOS = cauda do IS (R4) | Série composta (cauda ≤ fronteira) | `test_oos_warmup_uses_is_tail_without_lookahead` |
| Mutação OOS não altera params IS (WFK-04/ADR-0011) | Construção (IS não recebe OOS) + teste de mutação | `test_mutating_oos_does_not_change_is_selected_params` |
| Identidade CA-04.2 com `qty < 0` e borrow fees (SHT-04) | Fórmula única §6; termo próprio | `test_reconciliation_closes_with_negative_qty` |
| PnL short × ex-dividendo ≡ retorno ajustado (SHT-04 CA-04.3) | Modelo de ajuste declarado consistente p/ `qty < 0` | `test_short_pnl_across_ex_dividend_equals_adjusted_return` |
| Determinismo (RNF-01) | Sem aleatoriedade; alfabético; grid determinística | `test_forced_liquidation_deterministic_across_runs`; `test_walkforward_grid_is_deterministic_params_identical` |
| Fronteira de instante (RNF-07) | Imports restritos aos módulos novos e estendidos | `test_architecture_timezone_imports` — estendido a `margin`/`walkforward`, bloqueante |
| Cobertura ≥ 85% com módulos novos (RNF-02 CA-02.2) | `fail_under` no pyproject | `test_ci_coverage_floor_85_includes_margin_walkforward` |
| Nenhum invariante relaxado sem ADR (RNF-09 CA-02.3) | ADR-0009 + teste de arquitetura de specs | `test_spec_architecture_fails_without_adr_0009` |

### 10.2 Mapeamento RF × CA × teste nomeado — os 54 CAs da v0.2

| RF | CA | Teste nomeado que o quebraria |
|---|---|---|
| RF-SHT-01 | CA-01.1 | `test_signal_contract_is_backward_compatible_long_only` |
| | CA-01.2 | `test_enter_short_yields_negative_target_qty` |
| | CA-01.3 | `test_exit_short_without_open_position_raises_engine_error` |
| RF-SHT-02 | CA-02.1 | `test_short_opens_at_market_with_sell_slippage` |
| | CA-02.2 | `test_buy_to_cover_at_market_with_buy_slippage` |
| | CA-02.3 | `test_short_entry_respects_participation_cap` |
| | CA-02.4 | `test_short_cover_buy_limit_never_violates_limit` |
| RF-SHT-03 | CA-03.1 | `test_borrow_fee_closed_form_10_days` |
| | CA-03.2 | `test_borrow_fee_only_on_days_with_open_short` |
| | CA-03.3 | `test_report_borrow_fee_own_category` |
| | CA-03.4 | `test_borrow_availability_unlimited_default_never_blocks` **e** `test_borrow_restricted_blocks_short_and_logs` (os dois lados) |
| RF-SHT-04 | CA-04.1 | `test_short_roundtrip_pnl_closed_form` |
| | CA-04.2 | `test_reconciliation_closes_with_negative_qty` |
| | CA-04.3 | `test_short_pnl_across_ex_dividend_equals_adjusted_return` |
| RF-SHT-05 | CA-05.1 | `test_short_delisted_position_locked_at_last_close` |
| | CA-05.2 | `test_report_flags_locked_short_position` |
| RF-MRG-01 | CA-01.1 | `test_margin_requirement_uses_absolute_qty` |
| | CA-01.2 | `test_margin_invariant_reduces_to_cash_ge_zero_long_only` |
| | CA-01.3 | `test_margin_breach_close_to_open_window_allowed_then_error` |
| | CA-01.4 | `test_report_shows_margin_utilization` |
| | CA-01.5 | `test_margin_factor_default_1_0_exact_formula` |
| RF-MRG-02 | CA-02.1 | `test_forced_liquidation_alphabetical_until_margin_restored` |
| | CA-02.2 | `test_forced_liquidation_cancels_pending_orders` |
| | CA-02.3 | `test_report_counts_margin_call_origin_trades` |
| | CA-02.4 | `test_forced_liquidation_deterministic_across_runs` |
| RF-MRG-03 | CA-03.1 | `test_broken_fund_freezes_no_new_trades_and_flag` |
| | CA-03.2 | `test_broken_fund_metrics_are_explicit_none_never_nan` |
| | CA-03.3 | `test_broken_fund_result_excluded_from_auto_comparison` |
| RF-MRG-04 | CA-04.1 | `test_gross_and_net_exposure_formulas_side_by_side` |
| | CA-04.2 | `test_leveraged_gross_gt_100_reported_with_margin_utilization` |
| RF-ORD-05 | CA-05.1 | `test_buy_stop_executes_at_max_stop_open_with_buy_slippage`; `test_buy_stop_with_open_long_is_ignored_and_consumed` (guard ENG-05); `test_buy_stop_over_short_covers_never_crosses` (cobertura — SHT-02.2) |
| | CA-05.2 | `test_buy_stop_undispatched_persists_to_next_bar_of_own_asset` |
| | CA-05.3 | `test_buy_stop_never_dispatched_never_debits_cash` |
| | (emenda P1) | `test_convert_accepts_buy_stop` (barreira P2 da 2a removida — regressão documentada) |
| RF-ORD-06 | CA-06.1 | `test_intrabar_ambiguity_buy_stop_entry_bracket_worst_case` |
| | CA-06.2 | `test_intrabar_ambiguity_short_bracket_stop_wins_over_tp` |
| | CA-06.3 | `test_report_counts_buy_stop_ambiguities_in_mechanism_counters` |
| RF-WFK-01 | CA-01.1 | `test_is_run_never_indexes_oos_bars_engine_error` |
| | CA-01.2 | `test_folds_are_disjoint_and_oos_union_covers_window` |
| | CA-01.3 | `test_oos_warmup_uses_is_tail_without_lookahead` |
| RF-WFK-02 | CA-02.1 | `test_walkforward_grid_is_deterministic_params_identical` |
| | CA-02.2 | `test_oos_uses_params_selected_in_same_fold` |
| | CA-02.3 | `test_is_selection_metric_is_annualized_sharpe_rf0_declared` |
| RF-WFK-03 | CA-03.1 | `test_walkforward_equity_is_exact_oos_concatenation` |
| | CA-03.2 | `test_report_shows_fold_by_fold_table_with_selected_params` |
| RF-WFK-04 | CA-04.1 | `test_mutating_oos_does_not_change_is_selected_params` |
| | CA-04.2 | `test_mutating_future_is_bars_does_not_change_prior_intentions_long_short_buy_stop` |
| RF-WFK-05 | CA-05.1 | `test_walkforward_harness_reports_per_fold_and_total_budgets` |
| RF-MET-05 | CA-05.1 | `test_report_benchmark_is_1n_long_only_with_long_short_vs_long_only` |
| | CA-05.2 | `test_benchmark_never_shorts` |
| RF-MET-06 | CA-06.1 | `test_bias_section_includes_2b_items` |
| | CA-06.2 | `test_run_section_reports_mht_metric_grid_folds_reconstructible` |
| RF-RNF-02 | CA-02.1 | `test_rnf_heritage_tests_pass_on_long_short_run` |
| | CA-02.2 | `test_ci_coverage_floor_85_includes_margin_walkforward` |
| | CA-02.3 | `test_spec_architecture_fails_without_adr_0009` |

**58 testes nomeados para 54 CAs** — CA-03.4 (aluguel, R1) exige dois testes (os dois lados: default nunca bloqueia; restrito bloqueia e loga); CA-05.1 (buy-stop) ganhou na emenda P1 os testes do guard ENG-05 (ativação por side) e o teste do convert (barreira P2 removida). Todos os 54 CAs mapeados 1:1; nenhum RF sem teste nomeado direto.

## 11. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.1 | 2026-08-14 | Rascunho inicial — gate 2. Design completo no template da 2a (§1–§11): contratos completos com campos/tipos/defaults (§3.1–§3.7), exceções com pré/pós-condições por interface (§3.8), fronteira de instante (§3.9), fluxo da barra 2b com sequência declarada como invariante (§4), bordas (§5), identidade estendida com borrow fees (§6), analytics gross/net + MHT + fundo quebrado (§7), decisões D1–D7 comprometidas com ADRs (§8), 54 CAs mapeados 1:1 (§10). ADRs **0009–0011 propostos** (margem + liquidação; modelo de aluguel; protocolo walk-forward). Emenda spec-first no requirements v0.2 §8: a missão do gate 2 reagrupa os ADRs (D1+D2 → 0009; fee de aluguel → 0010; D6+D7 → 0011) — tabela atualizada para não divergir. |
| 0.1 (emenda P1) | 2026-08-14 | Verificação do gate 2 (P1), sem reabrir o gate 1: (1) regra de ativação por side do buy-stop × guard ENG-05, tabela explícita (§3.5/§3.8/§4 passo 1b); (2) barreira P2 da 2a removida no `convert` (STOP vira kind válido) + regressão documentada do teste 2a `test_convert_domain_errors_raise_engine_error` (§3.5/§3.8, teste novo `test_convert_accepts_buy_stop`); (3) mecanismo do warmup OOS explicitado — cauda como histórico puro via gate i ≥ warmup, `oos_equity = equity_curve[tail_len:]`, pré-condição `strategy.warmup == warmup` (§3.6); (4) fonte única do Sharpe — `metrics.sharpe()` (2a) delega ao helper do engine (§7); (5) cronologia do fundo quebrado por gap no §4 (liquida → constata → congela → métricas None). §10: 58 testes nomeados para 54 CAs. |
