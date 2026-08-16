# Fase 2b — Venda a descoberto, margem e walk-forward — Plano de tarefas

**Status:** em revisão — gate 3
**Versão:** 0.1
**Data:** 2026-08-14
**Design de origem:** `specs/fase-2b-design.md` v0.1 (aprovado, emenda P1)
**Requisitos de origem:** `specs/fase-2b-requirements.md` v0.2 (aprovada, gate 1)

> Último gate antes da implementação. Uma tarefa boa aqui cabe em um commit,
> tem critério de verificação objetivo e não depende de nada que ainda não
> exista. Comandos de verificação são os do `Makefile` (`make check` =
> lint + typecheck + test, espelhando o job "quality" do CI). Cobertura é
> `pytest --cov` com `fail_under` em `pyproject.toml` (85 hoje, RNF-02 da 2b
> estende o escopo aos módulos novos — margin e walkforward).
>
> **Regra vigente da sessão:** após CADA tarefa — commit (só os arquivos da
> tarefa, sem `git add .`) + push + CI verde — antes de reportar "concluída".
> O CI é o gate 4 automatizado do merge.
>
> **Regressões documentadas (esperadas e aceitas):**
> - T06 remove a barreira P2 da 2a no `convert` (STOP vira kind de entrada
>   válido — buy-stop). O teste 2a `test_convert_domain_errors_raise_engine_error`
>   perde o bloco `pytest.raises(EngineError)` do buy-stop (emenda P1 do
>   design §3.5/§3.8). Tudo o mais da 2a permanece verde — regressão zero.
> - T01 altera `Position.__post_init__` (Fase 1 rejeitava `quantity <= 0`):
>   `quantity < 0` passa a ser válido (short, ADR-0009); `quantity == 0`
>   continua inválido. Testes antigos de portfolio que dependem da rejeição
>   de `quantity <= 0` são ajustados para o novo domínio (short) ou mantidos
>   para `== 0`.
> - T08b executa o plano de liquidação no open (passo 1a do design §4), o que
>   a T08a declaradamente não fazia. O teste T08a
>   `test_margin_breach_close_to_open_window_allowed_then_error` é atualizado
>   para o comportamento 2b (a violação no close segue NÃO sendo erro — a
>   janela close→open; o open seguinte liquida a mercado e restaura; o braço
>   "erro" do CA-01.3 — plano esgotado + margem violada com equity >= 0 — é
>   coberto no mesmo teste, agora com gap desfavorável). Tudo o mais de
>   T01–T08a permanece verde — regressão zero.

---

## Ordem de execução

Ordenadas por dependência: uma tarefa só aparece depois de tudo que ela precisa.

```
T01 ──▶ T02 ──▶ T03 ──▶ T04 ──▶ T05 ──▶ T06 ──▶ T07        (contratos → broker)
                                                    │
T01 ──▶ T02 ──▶ T08a ──▶ T08b                        │   (laço 2b)
                     ▲      │
T05 ──▶ T06 ──▶ T07 ─┘      ▼
                       T09 ──▶ T10 ──▶ T11a ──▶ T11b ──▶ T12 ──▶ T12b ──▶ T13
                       (gross/net)  (WF)  (mutação)  (relatório)  (harness)  (E2E)
```

Bloco folha (T01) e broker (T02–T07) têm ordem interna fixa (cada um estende
o anterior); T03/T04/T05 dependem só de T01/T02; T08a/T08b dependem de
T01–T07; T09 depende de T08b; T10–T13 dependem da cadeia completa.

## Resumo

| # | Tarefa | Depende de | RFs cobertos | Estado |
|---|---|---|---|---|
| T01 | Contratos: Signal com direção + Position/Trade qty<0 | — | RF-SHT-01 | ✅ |
| T02 | Execução short e cobertura no broker | T01 | RF-SHT-02 | ✅ |
| T03 | Borrow fee + identidade CA-04.2 + ex-dividendo | T01, T02 | RF-SHT-03, RF-SHT-04 | ✅ |
| T04 | Margem: invariante e utilização | T01 | RF-MRG-01 | ✅ |
| T05 | Liquidação forçada + fundo quebrado | T04 | RF-MRG-02, RF-MRG-03 | ✅ |
| T06 | Buy-stop + barreira P2 removida | T03, T04 | RF-ORD-05 | ✅ |
| T07 | Ambiguidades intrabarra com buy-stop | T06 | RF-ORD-06 | ✅ |
| T08a | Laço 2b — fechamento (fee → margem → MARGIN_CALL → fundo quebrado) | T03, T05 | RF-SHT-03, RF-MRG-01/02/03 | ✅ |
| T08b | Laço 2b — abertura/bordas (executa MARGIN_CALL, contadores, short deslistado) | T06, T07, T08a | RF-MRG-02, RF-SHT-05, RF-ORD-06 | ✅ |
| T09 | Exposição gross/net + turnover | T08b | RF-MRG-04 | ✅ |
| T10 | Folds/grid/seleção + sharpe_annualized_rf0 único | T08b | RF-WFK-01, RF-WFK-02 | ⬜ |
| T11a | run_walkforward + orçamento do WF | T10 | RF-WFK-03, RF-WFK-05 | ⬜ |
| T11b | Mutação ENG-01.2 estendida ao OOS (teste puro) | T11a | RF-WFK-04 | ⬜ |
| T12 | Relatório 2b + benchmark long-only + vieses + herança RNF + ADR-0009 + timezone | T09, T11a | RF-MET-05, RF-MET-06, RF-RNF-02 | ⬜ |
| T12b | Harness RNF-04 2b (WF) + arquitetura + cobertura 85% | T12 | RF-WFK-05, RNF-02, RNF-07 | ⬜ |
| T13 | Run long+short ponta a ponta vs 1/N long-only (DoD) | T12b | DoD | ⬜ |

Estados: ⬜ não iniciada · 🟡 em andamento · ✅ concluída · ⛔ bloqueada

---

## T01 — Contratos: Signal com direção e Position/Trade com qty < 0

**Depende de:** —
**RFs cobertos:** RF-SHT-01 (CA-01.1, CA-01.2, CA-01.3)
**Arquivos:** `src/quantlab/engine/strategy.py` (estendido — `Signal`),
`src/quantlab/engine/portfolio.py` (estendido — `Position`/`Trade`),
`src/quantlab/engine/conditional.py` (estendido — `TradeOrigin`),
`tests/unit/test_strategy.py` (novo), `tests/unit/test_portfolio.py` (estendido),
`tests/unit/test_broker.py` (se preciso — ajustes da regressão documentada)

**Escopo**
`Signal` ganha `ENTER_SHORT`/`EXIT_SHORT` (retrocompatível — estratégia
long-only da 2a emite só ENTER/EXIT e roda idêntica, CA-01.1). `TradeOrigin`
(StrEnum: MARKET/LIMIT/STOP espelhando `OrderKind` + `MARGIN_CALL`); o campo
`Trade.origin` migra para `TradeOrigin` (valores idênticos — compat 2a).
`Position.__post_init__` aceita `quantity < 0` (short; `== 0` continua
inválido — ADR-0009). PnL realizado algébrico já funciona com `qty < 0`
(CA-04.1 da RF-SHT-04, provado aqui no contrato). `EXIT_SHORT` sem posição
short ⇒ `EngineError` (CA-01.3) — decisão do laço (T08a); o contrato declara.

**Fora do escopo**
Execução short/cobertura (T02); borrow fee (T03); margem (T04/T05); laço (T08).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_signal_contract_is_backward_compatible_long_only` (CA-01.1) —
  estratégia que só emite ENTER/EXIT satisfaz o contrato sem mudança
- [ ] `test_enter_short_yields_negative_target_qty` (CA-01.2) — a conversão
  (T02) aplica o sinal; aqui o contrato: `Position(quantity=-100)` válido,
  `Position(quantity=0)` levanta EngineError
- [ ] `test_exit_short_without_open_position_raises_engine_error` (CA-01.3) —
  declarado no contrato (implementação do laço na T08a)
- [ ] `test_trade_origin_migrates_cleanly` — `TradeOrigin.MARKET ==
  OrderKind.MARKET` (valores idênticos); `TradeOrigin.MARGIN_CALL` existe
- [ ] `test_short_roundtrip_pnl_closed_form` (CA-04.1 do RF-SHT-04) —
  `(90 − 100) × (−100) = +1000` em forma fechada no `realized_pnl`

**Riscos**
Médio — mexer no `Position` da Fase 1 é tocar num invariante que o ADR-0009
relaxa; a regressão documentada (testes que rejeitavam `quantity < 0`) precisa
ser ajustada de forma rastreável, nunca silenciosamente.

**Commit**
`feat(engine): direção no contrato de sinal e qty < 0 no Position (RF-SHT-01)` —
por quê: a direção é decisão da estratégia no sinal (D3), e oficializar
`qty < 0` é o primeiro passo formal do relaxamento de invariante coberto pelo
ADR-0009.

---

## T02 — Execução short e cobertura no broker

**Depende de:** T01
**RFs cobertos:** RF-SHT-02 (CA-02.1, CA-02.2, CA-02.3, CA-02.4)
**Arquivos:** `src/quantlab/engine/broker.py` (estendido),
`tests/unit/test_broker.py` (estendido)

**Escopo**
`Broker.convert` ganha o sinal (D3): `ENTER_SHORT` aplica a fração do sizer
como magnitude e o alvo vira negativo (`qty = −⌊fração×equity/ref_price⌋`),
passando pela MESMA sequência fixa da 2a (SIZING → CAP → INTEIRAS →
CAIXA/CUSTOS) e pelo cap de participação (CA-02.3 — mesmo helper e `cut_reason`).
`execute_pending`: MARKET SELL abre short (`qty < 0`, `entry_price` = preço da
venda com slippage de venda — CA-02.1); MARKET BUY sobre short é cobertura
(reduz `|qty|` até 0, nunca cruza — CA-02.2); LIMIT BUY de cobertura nunca
viola o limite (CA-02.4). Saída short é integral (D3 da 2a). Cobertura acima
da posição ⇒ `EngineError` (§3.8).

**Fora do escopo**
Borrow fee (T03); margem (T04); laço (T08).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_short_opens_at_market_with_sell_slippage` (CA-02.1) — forma fechada:
  venda abre `qty < 0` a `open×(1 − bps)`
- [ ] `test_buy_to_cover_at_market_with_buy_slippage` (CA-02.2) — cobertura
  reduz `|qty|`, preço `open×(1 + bps)`, nunca cruza
- [ ] `test_short_entry_respects_participation_cap` (CA-02.3) — corte com
  `cut_reason == CAP` na entrada short
- [ ] `test_short_cover_buy_limit_never_violates_limit` (CA-02.4) — preço de
  preenchimento ≤ limite
- [ ] `test_cover_above_position_raises_engine_error` — §3.8
- [ ] Testes existentes do broker da Fase 1/2a continuam VERDES (regressão zero)

**Riscos**
Alto — o sinal negativo atravessa o pipeline inteiro (sizing→cap→inteiras→
caixa); um `abs()` no lugar errado inverte a direção silenciosamente. O teste
de forma fechada do CA-02.1 é o guard.

**Commit**
`feat(engine): execução de short e cobertura no broker (RF-SHT-02)` — por quê:
vender a descoberto é a primeira regra de execução com `qty < 0`; a cobertura
nunca cruzar de sinal é o invariante que o ADR-0009 passa a vigiar.

---

## T03 — Borrow fee, identidade CA-04.2 e ex-dividendo

**Depende de:** T01, T02
**RFs cobertos:** RF-SHT-03 (CA-03.1, CA-03.2, CA-03.3, CA-03.4), RF-SHT-04
(CA-04.1, CA-04.2, CA-04.3)
**Arquivos:** `src/quantlab/engine/margin.py` (novo — `BorrowFeeModel`),
`src/quantlab/analytics/metrics.py` (estendido — `ReconciliationReport` com
`total_borrow_fees`), `src/quantlab/engine/broker.py` (estendido — checagem
de disponibilidade no convert), `tests/unit/test_margin.py` (novo),
`tests/unit/test_reconciliation.py` (estendido)

**Escopo**
`BorrowFeeModel` (fee_annual default 0,005; unlimited default True;
unavailable frozenset): `daily_fee(qty, close) = |qty|×close×fee/252`
(CA-03.1) e `is_available(ticker, date)` (CA-03.4 — os dois lados). O débito
no close é do laço (T08a); aqui a forma fechada e a identidade. `convert` de
`ENTER_SHORT` checa disponibilidade: indisponível ⇒ `None` + log +
`counters.borrow_rejections += 1` (CA-03.4 direita; contado onde o evento
acontece — §3.7). `ReconciliationReport` ganha `total_borrow_fees` (termo
próprio, uma única vez — §6) e a identidade fecha com `qty < 0` (CA-04.2).
Teste de ex-dividendo: PnL do short atravessando data ex ≡ retorno do preço
ajustado, em forma fechada sobre fixture com fator de ajuste (CA-04.3).

**Fora do escopo**
Débito no laço (T08a); relatório com categoria própria do fee (T12).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_borrow_fee_closed_form_10_days` (CA-03.1) — Σ|qty|×close×0,005/252
  em fixture de papel
- [ ] `test_borrow_fee_only_on_days_with_open_short` (CA-03.2) — declarado no
  contrato (débito do laço prova na T08a)
- [ ] `test_borrow_availability_unlimited_default_never_blocks` **e**
  `test_borrow_restricted_blocks_short_and_logs` (CA-03.4 — os dois lados)
- [ ] `test_reconciliation_closes_with_negative_qty` (CA-04.2) — identidade
  com `qty < 0` e `total_borrow_fees` no termo próprio, isclose 1e-9
- [ ] `test_short_pnl_across_ex_dividend_equals_adjusted_return` (CA-04.3)
- [ ] Cobertura do módulo novo ≥ 85% já neste commit

**Riscos**
Médio — a armadilha da dupla contagem (T13 da 2a) vale também para o fee:
nunca somar `total_borrow_fees` dentro de `total_costs` E no termo próprio.

**Commit**
`feat(engine): borrow fee determinístico e identidade com qty < 0 (RF-SHT-03/04)` —
por quê: o aluguel é custo de carregamento com forma fechada testável, e a
identidade estendida é o que prova que o engine não mente com shorts.

---

## T04 — Margem: invariante e utilização

**Depende de:** T01
**RFs cobertos:** RF-MRG-01 (CA-01.1, CA-01.2, CA-01.3, CA-01.5; CA-01.4 é do
relatório, T12)
**Arquivos:** `src/quantlab/engine/margin.py` (novo — `MarginModel`,
`margin_requirement`, `margin_utilization`), `tests/unit/test_margin.py` (novo)

**Escopo**
`MarginModel(factor=1.0)` — fator único, default 1.0 explícito (R3/CA-01.5),
`factor ≤ 0` ⇒ EngineError. `margin_requirement(positions, closes, model) =
Σ|qtyᵢ|×closeᵢ×factor` — valores ABSOLUTOS, nunca soma algébrica (CA-01.1);
função pura. `margin_utilization(equity, requirement) = requirement/equity`,
`equity ≤ 0` ⇒ `None` explícito (R6). Regressão long-only com factor 1.0:
margem = notional longo ⇒ `equity ≥ margem ⇔ cash ≥ 0` (CA-01.2). A checagem
no laço (com a janela close→open do CA-01.3) é da T08a.

**Fora do escopo**
Liquidação forçada (T05); checagem no laço (T08a); utilização no relatório (T12).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_margin_requirement_uses_absolute_qty` (CA-01.1) — long + short:
  Σ|qty|×close×factor, não soma algébrica
- [ ] `test_margin_invariant_reduces_to_cash_ge_zero_long_only` (CA-01.2) —
  regressão da 2a: equity ≥ notional ⇔ cash ≥ 0
- [ ] `test_margin_factor_default_1_0_exact_formula` (CA-01.5) — valor exato
  com factor default
- [ ] `test_margin_utilization_none_on_nonpositive_equity` — R6 (nunca NaN)
- [ ] `test_margin_factor_non_positive_raises_engine_error` — §3.8
- [ ] Cobertura do módulo novo ≥ 85% já neste commit

**Riscos**
Baixo — funções puras; o risco é o default do fator não ser determinístico
(CA-01.5 trava o valor exato).

**Commit**
`feat(engine): invariante de margem e utilização (RF-MRG-01, ADR-0009)` —
por quê: o invariante da 2b substitui `cash ≥ 0`/`qty ≥ 0` (POR-04.3) e exige
ADR próprio (RNF-09); com factor 1.0 o caso long-only recupera exatamente o
invariante antigo (CA-01.2).

---

## T05 — Liquidação forçada e fundo quebrado

**Depende de:** T04
**RFs cobertos:** RF-MRG-02 (CA-02.1, CA-02.2, CA-02.3, CA-02.4), RF-MRG-03
(CA-03.1, CA-03.2, CA-03.3)
**Arquivos:** `src/quantlab/engine/margin.py` (estendido — `MarginCallOrder`,
`BrokenFundState`), `src/quantlab/engine/broker.py` (estendido —
`execute_margin_calls`), `tests/unit/test_margin.py`, `tests/unit/test_broker.py`

**Escopo**
`MarginCallOrder` (ticker, side — long ⇒ SELL / short ⇒ BUY, qty = |qty atual|
integral, decision_date, intent_seq próprio, reason="margin_call");
`BrokenFundState` (broken, final_equity real negativa). `Broker.execute_margin_calls(
plan, bar, portfolio, cost_model, slippage)` — MARKET no open do próprio ativo
(ADR-0002), `origin = MARGIN_CALL` no Trade (CA-02.3), custos fora do preço,
determinístico (CA-02.4). A seleção alfabética e o laço de re-cheque (CA-02.1),
o cancelamento de pendentes (CA-02.2) e o congelamento (CA-03.1) são do laço
(T08a) — aqui a peça de execução e os tipos.

**Fora do escopo**
Detecção/plano/congelamento no laço (T08a); relatório (CA-03.2 no T12).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_execute_margin_call_long_sells_at_market_with_costs` — long
  liquidado no open com slippage e `origin == MARGIN_CALL`
- [ ] `test_execute_margin_call_short_buys_to_cover` — cobertura da posição
  short
- [ ] `test_margin_call_order_integral_qty_and_engine_errors` — §3.8 (qty ≤ 0,
  ativo sem posição)
- [ ] `test_broken_fund_state_holds_negative_equity` — R6 (valor real, nunca
  zero fabricado)
- [ ] Cobertura ≥ 85% no módulo novo

**Riscos**
Médio — a liquidação é o único caminho do engine que gera trade sem intenção
de estratégia; `origin = MARGIN_CALL` é o que a torna auditável (CA-02.3).

**Commit**
`feat(engine): liquidação forçada determinística e estado fundo quebrado (RF-MRG-02/03)` —
por quê: a liquidação é a correção automática do novo invariante de margem, e
o estado fundo quebrado precisa de representação explícita (`None`, nunca NaN —
R6).

---

## T06 — Buy-stop e remoção da barreira P2

**Depende de:** T03, T04
**RFs cobertos:** RF-ORD-05 (CA-05.1, CA-05.2, CA-05.3) + emenda P1 (guard
ENG-05 por side, `test_convert_accepts_buy_stop`)
**Arquivos:** `src/quantlab/engine/broker.py` (estendido),
`tests/unit/test_broker.py` (estendido)

**Escopo**
`convert` passa a aceitar `OrderKind.STOP` como kind de entrada (buy-stop —
barreira P2 da 2a REMOVIDA, emenda P1); o guard que levantava EngineError sai
e o ramo morto de `_execute_entry` vira caminho real. `execute_pending`:
buy-stop (`kind=STOP`, `side=BUY`) dispara quando `high[i] ≥ S` e executa a
`max(S, open[i])` com slippage de compra (CA-05.1); não disparado ⇒ PERMANECE
pendente (CA-05.2); nunca debita caixa antes de disparar (CA-05.3).
**Ativação por side × guard ENG-05 (tabela do design §3.5):** sem posição ⇒
entrada long; posição LONG aberta ⇒ guard ignora e consome (log
`engine.enter_with_open_position`, como ENTER); posição SHORT aberta ⇒ ativa
como COBERTURA (reduz |qty|, nunca cruza — SHT-02.2, guard não se aplica).
sell-stop (2a) permanece: só ativa com LONG; com SHORT ou flat permanece
pendente.

**Fora do escopo**
Ambiguidades intrabarra novas (T07); laço (T08).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_buy_stop_executes_at_max_stop_open_with_buy_slippage` (CA-05.1) —
  forma fechada com slippage de compra
- [ ] `test_buy_stop_undispatched_persists_to_next_bar_of_own_asset` (CA-05.2)
- [ ] `test_buy_stop_never_dispatched_never_debits_cash` (CA-05.3) — sem reserva
- [ ] `test_buy_stop_with_open_long_is_ignored_and_consumed` (guard ENG-05) e
  `test_buy_stop_over_short_covers_never_crosses` (cobertura) — emenda P1
- [ ] `test_convert_accepts_buy_stop` — STOP vira entrada válida no convert
- [ ] Regressão documentada: `test_convert_domain_errors_raise_engine_error`
  perde o bloco do buy-stop (2a) e continua verde

**Riscos**
Alto — buy-stop sem posição abre long; com LONG o guard consome; com SHORT
cobre. A tabela por side (design §3.5) é a fonte; o teste do guard é o guard.

**Commit**
`feat(engine): buy-stop com ativação por side (RF-ORD-05, emenda P1)` — por
quê: o buy-stop espelha o sell-stop (D5) e a remoção da barreira P2 é a
regressão documentada que fecha o adiamento da 2a.

---

## T07 — Ambiguidades intrabarra com buy-stop

**Depende de:** T06
**RFs cobertos:** RF-ORD-06 (CA-06.1, CA-06.2, CA-06.3)
**Arquivos:** `src/quantlab/engine/broker.py` (estendido),
`tests/unit/test_broker.py` (estendido)

**Escopo**
ADR-0007 estendido (tabela do design §4): bracket long de entrada (buy-stop
`S_e` + sell-stop `S_s`, `S_s < S_e`) ambos tocados ⇒ abre em `S_e` e fecha em
`S_s` na mesma barra, perda `(S_e − S_s + custos)`, flat, `ambiguous=True`
(CA-06.1); bracket short (TP buy-limit + SL buy-stop, `SL > TP`) ambos tocados
⇒ o short é coberto no `SL` (pior caso), nunca no TP (CA-06.2). Nunca "ambos
executam" (CA-03.3 da 2a mantido). Trades ambíguos alimentam o contador
(CA-06.3 — agregação no laço, T08b).

**Fora do escopo**
Agregação do contador (T08b); relatório (T12).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_intrabar_ambiguity_buy_stop_entry_bracket_worst_case` (CA-06.1) —
  forma fechada da perda, flat, ambiguous=True
- [ ] `test_intrabar_ambiguity_short_bracket_stop_wins_over_tp` (CA-06.2)
- [ ] `test_no_double_execution_buy_stop_brackets` — nunca "ambos executam"
- [ ] `test_buy_stop_bracket_no_orphan_stop` — o sell-stop do par não ativa
  sem posição (herança T09 da 2a)

**Riscos**
Médio — mesma semântica do ADR-0007 da 2a com os tipos invertidos; o teste de
caixa em forma fechada é o guard.

**Commit**
`feat(engine): pior caso intrabarra com buy-stop (RF-ORD-06, ADR-0007)` — por
quê: o pior caso é a única resolução determinística de ambiguidade (RNF-01) e
o `ambiguous=True` é a auditoria que o relatório conta.

---

## T08a — Laço 2b: fechamento (fee → margem → MARGIN_CALL → fundo quebrado)

**Depende de:** T03, T05
**RFs cobertos:** RF-SHT-03 (CA-03.1, CA-03.2 — débito no close), RF-MRG-01
(CA-01.3 — janela close→open), RF-MRG-02 (CA-02.1, CA-02.2 — plano/limpeza),
RF-MRG-03 (CA-03.1 — congelamento)
**Arquivos:** `src/quantlab/engine/backtest.py` (estendido — laço 2b),
`src/quantlab/engine/portfolio.py` (estendido — `check_invariants` relaxado
via margem), `tests/unit/test_backtest.py` (estendido)

**Escopo**
O laço multi-ativo da 2a vira o laço 2b com a sequência declarada como
invariante (design §4): EXECUTAR (pendentes + liquidações MARGIN_CALL) →
MARCAR (close) → DEBITAR fee (etapa própria, CA-03.1/03.2) → CHECAR MARGEM
(equity < margem ⇒ plano de liquidação alfabético, integral por ativo,
cancelando pendentes do ativo — CA-02.2; violação no close NÃO é erro —
CA-01.3) → CONSULTAR (ENTER_SHORT/EXIT_SHORT processados; EXIT_SHORT sem
posição ⇒ EngineError — CA-01.3 do SHT-01). Fundo quebrado por gap:
cronologia (1) liquida → (2) constata equity < 0 → (3) congela (nenhum trade
novo, pendentes canceladas, intenções descartadas, flag) → (4) métricas None
(R6). `check_invariants` passa a validar `equity ≥ margem` pós-open em vez de
`cash ≥ 0`/`qty ≥ 0` (ADR-0009; assinatura antiga preservada para a Fase 1).

**Fora do escopo**
Execução de MARGIN_CALL no open (T08b); contadores (T08b); short deslistado (T08b).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_borrow_fee_debited_at_close_open_short_only` (CA-03.1/03.2 — o
  débito real no laço, forma fechada)
- [ ] `test_margin_breach_close_to_open_window_allowed_then_error` (CA-01.3)
- [ ] `test_margin_call_plan_alphabetical_and_cancels_pendings` (CA-02.1/02.2 —
  lado do plano; a execução é T08b)
- [ ] `test_broken_fund_freezes_no_new_trades_and_flag` (CA-03.1)
- [ ] `test_exit_short_without_position_raises_engine_error` (SHT-01.3 no laço)
- [ ] Regressão zero da 2a: laço multi-ativo com estratégia long-only produz o
  MESMO resultado (CA-01.1 do SHT-01 no laço)

**Riscos**
Alto — a sequência fechamento (marcar → fee → margem → consultar) é nova e
declarada como invariante; uma inversão derruba a semântica de margem e a
auditoria do ENG-01.2.

**Commit**
`feat(engine): laço 2b — fechamento com fee, margem e fundo quebrado (RF-SHT-03/RF-MRG-01/02/03)` —
por quê: o fechamento da barra é onde o novo invariante de margem passa a ser
vigido e onde o fee ganha etapa própria (CA-03.2), sem reabrir a Fase 1.

---

## T08b — Laço 2b: abertura e bordas

**Depende de:** T06, T07, T08a
**RFs cobertos:** RF-MRG-02 (CA-02.1 — execução no open, re-cheque por ativo;
CA-02.3 — origin MARGIN_CALL), RF-MRG-03 (CA-03.2 — conciliação fechando com
equity negativa), RF-SHT-05 (CA-05.1), RF-ORD-06 (CA-06.3 — contador),
RF-POR-04 da 2a (CA-04.2 — invariantes por barra)
**Arquivos:** `src/quantlab/engine/backtest.py` (estendido),
`tests/unit/test_backtest.py` (estendido)

**Escopo**
Abertura do open: executa o plano de liquidação da véspera (MARGIN_CALL a
mercado — long SELL, short BUY), re-checa a margem após cada ativo liquidado e
interrompe quando restaurada (CA-02.1); `origin = MARGIN_CALL` nos trades
(CA-02.3); plano esgotado + margem violada com equity ≥ 0 ⇒ EngineError
(CA-01.3). `BacktestResultMulti` ganha `broken_fund`, `borrow_fees`, `margin`,
`borrow` (design §3.7) e o laço agrega os contadores novos (`margin_calls` e
`intrabar_ambiguities` derivados dos trades; `borrow_rejections` já contado no
convert, T03). Short deslistado: travado no último close, passivo marcado,
reportado (CA-05.1). Conciliação continua fechando com equity negativa
(CA-03.2 — o teste de reconciliação da T03 roda sobre o run quebrado).

**Fora do escopo**
Relatório (T12); gross/net (T09).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_forced_liquidation_alphabetical_until_margin_restored` (CA-02.1)
- [ ] `test_forced_liquidation_cancels_pending_orders` (CA-02.2, lado execução)
- [ ] `test_margin_call_trades_carry_origin_and_counter` (CA-02.3) — nome do
  TASKS; o design §10 cita `test_report_counts_margin_call_origin_trades`
  (divergência registrada na T08b: prevalece o nome do tasks)
- [ ] `test_forced_liquidation_deterministic_across_runs` (CA-02.4)
- [ ] `test_broken_fund_reconciliation_still_closes` (CA-03.2)
- [ ] `test_short_delisted_position_locked_at_last_close` (CA-05.1)
- [ ] `test_report_counts_buy_stop_ambiguities_in_mechanism_counters` — a
  agregação no laço (CA-06.3; o relatório é T12)
- [ ] `test_broken_fund_gap_liquidation_freezes_at_open` — NOVO, registrado
  aqui (não existia no design §10): cronologia do fundo quebrado por gap da
  emenda P1 (§4 passo 1a) — (1) liquidação integral no open ao preço do gap
  (ADR-0002) → (2) re-cheque constata equity < 0 → (3) congela (flag, sem
  trades novos, pendentes canceladas, intenções descartadas) → (4) equity
  negativa REAL; a conciliação fechando é a CA-03.2 acima

**Riscos**
Alto — o re-cheque por ativo e o congelamento determinístico (alfabético,
RNF-01) são o coração do ADR-0009; o teste de determinismo (CA-02.4) é o guard.

**Commit**
`feat(engine): laço 2b — abertura com liquidação, contadores e bordas (RF-MRG-02/03, RF-SHT-05)` —
por quê: a execução da liquidação no open fecha o ciclo close→open do
ADR-0009, e os contadores derivados pelo laço (dono declarado, §3.7) são o que
o relatório só reporta.

---

## T09 — Exposição gross/net e turnover

**Depende de:** T08b
**RFs cobertos:** RF-MRG-04 (CA-04.1, CA-04.2)
**Arquivos:** `src/quantlab/analytics/metrics.py` (estendido),
`tests/unit/test_metrics.py` (estendido)

**Escopo**
`gross_exposure_avg(daily_gross_notional, equity_daily)` — média diária de
(Σ|qty|×close)/equity, pode exceder 100% (CA-04.2); `net_exposure_avg` —
média diária de (Σ qty×close)/equity, pode ser negativa (CA-04.1);
`margin_utilization_avg` — média diária de margem/equity, `None` se equity ≤ 0
(R6). Turnover da 2a intocado (|notional| já funciona com qty < 0). As
fórmulas usam as MESMAS definições para estratégia e benchmark (MET-04.2 da
2a, herdado). O relatório reporta gross/net lado a lado e alavancagem junto
com utilização (T12).

**Fora do escopo**
Relatório (T12).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_gross_and_net_exposure_formulas_side_by_side` (CA-04.1) — fixture
  de papel com long + short
- [ ] `test_leveraged_gross_gt_100_reported_with_margin_utilization` — valor
  > 100% em forma fechada (CA-04.2; o "reportado" é T12)
- [ ] `test_margin_utilization_avg_none_on_broken_fund` — R6
- [ ] `test_turnover_closed_form_with_shorts` — NOVO, registrado aqui (não
  existia no design §10): turnover com |notional| em forma fechada (short
  x long simétricos por |qty|; a fórmula da 2a fica INTOCADA — design §7)
- [ ] **HARDENING BLOQUEADO — registrado (não há teste):** o guard `not
  broken` do rebalance (SIZ-03, 2a) não tem fixture construtível na 2b. O
  rebalance é LONG-ONLY por construção (`rebalance_deviation_pp` rejeita
  peso fora de [0, 1] — peso de short é negativo ⇒ EngineError no primeiro
  k-change com short no portfolio), e fundo quebrado exige short (equity
  long-only ≥ 0 por construção — o sizing nunca deixa caixa negativo). Logo
  qualquer k-change com short CRASHA antes de qualquer estado quebrado
  alcançável, e o guard `not broken` é inalcançável (defesa em profundidade
  morta). GAP 2b descoberto: EqualWeightOpen × short = EngineError —
  decisão de design para tarefa futura (rebalance com pesos negativos/
  alavancagem não é definido no design §4 passo 2b, que declara o rebalance
  "2a, inalterado")
- [ ] Testes antigos de métricas continuam VERDES (regressão zero)

**Riscos**
Baixo — funções puras; risco de desalinhar gross (|qty|) e net (qty) nos
notionais — o teste lado a lado trava.

**Commit**
`feat(analytics): exposição gross/net e alavancagem (RF-MRG-04)` — por quê: o
leitor vê o risco real (gross) e o direcional (net) sem adivinhar, e a
alavancagem > 100% é explícita (D4).

---

## T10 — Folds, grid, seleção e sharpe_annualized_rf0

**Depende de:** T08b
**RFs cobertos:** RF-WFK-01 (CA-01.1, CA-01.2, CA-01.3), RF-WFK-02 (CA-02.1,
CA-02.2, CA-02.3)
**Arquivos:** `src/quantlab/engine/walkforward.py` (novo — `Fold`,
`ParameterGrid`, `build_folds`, `sharpe_annualized_rf0`),
`src/quantlab/analytics/metrics.py` (estendido — `sharpe()` delega ao helper),
`tests/unit/test_walkforward.py` (novo), `tests/unit/test_metrics.py` (estendido)

**Escopo**
`Fold` (is_start/is_end/oos_start/oos_end, disjuntos, união dos OOS cobre a
janela sem sobreposição — CA-01.2); `build_folds(start, end, is_window,
oos_window, anchor="rolling")` — rolling default (D7), anchored configurável;
determinístico. `ParameterGrid(params, seed=None)` — grade determinística por
construção (CA-02.1). `sharpe_annualized_rf0(returns)` — forma fechada ÚNICA
(média/desvio × √252, rf=0), vive no engine e é importada por analytics — o
`sharpe()` da 2a delega (fonte única, emenda P1; série vazia/desvio 0 ⇒ None,
R6). Isolamento estrito por construção: o run IS usa séries truncadas; o guard
de fronteira (acesso além do fim do IS ⇒ EngineError) é testado com a série
truncada (CA-01.1). Warmup do OOS pela cauda do IS (CA-01.3 — mecanismo do
gate i ≥ warmup é da T11a; aqui o contrato e os folds).

**Fora do escopo**
run_walkforward (T11a); orçamento (T11a); mutação (T11b).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_rebalance_with_open_short_raises_engine_error` — NOVO, registrado
  aqui (emenda T09/P0 — não existia no design §10): gatilho de k do
  rebalance com posição short aberta ⇒ EngineError claro (long-only por
  construção, D3); controle long-only verde
- [ ] `test_folds_are_disjoint_and_oos_union_covers_window` (CA-01.2)
- [ ] `test_walkforward_grid_is_deterministic_params_identical` (CA-02.1)
- [ ] `test_is_run_never_indexes_oos_bars_engine_error` (CA-01.1) — série
  truncada: acesso além do fim ⇒ EngineError
- [ ] `test_oos_warmup_uses_is_tail_without_lookahead` (CA-01.3 — contrato:
  cauda ≤ fronteira; mutar OOS não altera a cauda)
- [ ] `test_is_selection_metric_is_annualized_sharpe_rf0_declared` (CA-02.3)
- [ ] `test_sharpe_annualized_rf0_closed_form_and_delegation` — forma fechada
  e `metrics.sharpe()` delegando (sem duas fórmulas)
- [ ] Cobertura do módulo novo ≥ 85% já neste commit

**Riscos**
Médio — o isolamento estrito depende da fronteira ser do ARRAY (truncado), não
da disciplina de quem chama; o guard testável (CA-01.1) é a prova.

**Commit**
`feat(engine): folds, grid determinística e sharpe único rf=0 (RF-WFK-01/02)` —
por quê: folds disjuntos e grade determinística são a base do WF honesto, e o
sharpe único elimina o drift entre seleção IS e relatório (emenda P1).

---

## T11a — run_walkforward e orçamento do WF

**Depende de:** T10
**RFs cobertos:** RF-WFK-03 (CA-03.1, CA-03.2), RF-WFK-05 (CA-05.1)
**Arquivos:** `src/quantlab/engine/walkforward.py` (estendido — `FoldMetrics`,
`FoldResult`, `WalkForwardResult`, `run_walkforward`), `tests/unit/test_walkforward.py`

**Escopo**
`run_walkforward(series, strategy_factory, grid, folds, *, initial_cash,
costs, slippage, cap, margin, borrow, sizer, warmup)` — CAIXA PRETA por fold
(design §2): cada run IS/OOS chama `run_backtest_multi` com a MESMA
configuração do run único (herança por construção). 1. IS: séries truncadas no
fim do IS, corre a grade, seleciona por `sharpe_annualized_rf0` (R5/CA-02.3).
2. OOS: série composta (cauda do IS com `len == warmup` + segmento OOS), a
estratégia nunca é consultada na cauda (gate i ≥ warmup — primeira barra
consultada é o primeiro bar OOS; CA-01.3), `oos_equity = equity_curve[tail_len:]`
(concatenação exata — CA-03.1), pré-condição `strategy.warmup == warmup`
(EngineError). Parâmetros = selecionados no IS do MESMO fold (CA-02.2).
`WalkForwardResult` (folds, oos_equity, oos_dates, broken_fund, grid_size,
n_folds). Harness do orçamento: `measure_walkforward(...)` reporta tempo por
fold e total contra os orçamentos declarados (por fold default 30 s, total
`n_folds×30 s` + margem; séries sintéticas determinísticas com origem
declarada — CA-05.1).

**Fora do escopo**
Mutação (T11b); relatório com tabela fold a fold (T12); harness no CI (T12b).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_walkforward_equity_is_exact_oos_concatenation` (CA-03.1) —
  comparação direta com o run OOS isolado de cada fold
- [ ] `test_oos_uses_params_selected_in_same_fold` (CA-02.2)
- [ ] `test_walkforward_harness_reports_per_fold_and_total_budgets` (CA-05.1)
- [ ] `test_run_walkforward_warmup_mismatch_raises_engine_error` — §3.8
- [ ] Determinismo: dois runs ⇒ mesmos params por fold (RNF-01)

**Riscos**
Alto — o warmup pela cauda (R4) é o ponto mais fácil de errar: se a estratégia
for consultada na cauda, há lookahead; o teste do CA-01.3 e a concatenação
exata (CA-03.1) são os guards.

**Commit**
`feat(engine): walk-forward por caixa preta com orçamento declarado (RF-WFK-03/05)` —
por quê: o WF herda todas as regras de execução por construção (filosofia do
benchmark 1/N) e o orçamento em duas escalas (RNF-10) substitui o "30 s" da 2a
para centenas de runs.

---

## T11b — Mutação ENG-01.2 estendida ao OOS (teste puro)

**Depende de:** T11a
**RFs cobertos:** RF-WFK-04 (CA-04.1, CA-04.2)
**Arquivos:** `tests/unit/test_walkforward.py` (estendido) — **só tests/, zero
mudança em src/**

**Escopo**
Commit de teste puro (ADR-0011): (a) mutar barras OOS não altera os parâmetros
selecionados no IS (CA-04.1); (b) mutar barras futuras do IS não altera
intenções/execuções anteriores, agora incluindo `ENTER_SHORT`/`EXIT_SHORT` e
buy-stop (CA-04.2). O teste de mutação da 2a (single-asset + multi, ordens a
mercado e condicionais) continua passando.

**Fora do escopo**
Qualquer código de engine — se um teste falhar, PARE e reporte o achado (bug
real ⇒ commit próprio; spec errada ⇒ emenda spec-first, CLAUDE.md).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_mutating_oos_does_not_change_is_selected_params` (CA-04.1)
- [ ] `test_mutating_future_is_bars_does_not_change_prior_intentions_long_short_buy_stop` (CA-04.2)
- [ ] Diff do commit = SÓ tests/

**Riscos**
Alto — é o critério de aceitação da fase; se o run_walkforward (T11a) tiver
lookahead, é aqui que aparece.

**Commit**
`test(engine): mutação ENG-01.2 estendida ao OOS (RF-WFK-04, ADR-0011)` — por
quê: o IS nunca indexar o OOS é a claim central do WF; só a mutação prova que
a fronteira é do array e não da disciplina.

---

## T12 — Relatório 2b, benchmark long-only, vieses, herança RNF, timezone

**Depende de:** T09, T11a
**RFs cobertos:** RF-MET-05 (CA-05.1, CA-05.2), RF-MET-06 (CA-06.1, CA-06.2),
RF-RNF-02 (CA-02.1, CA-02.3), RF-SHT-03 (CA-03.3), RF-MRG-02 (CA-02.3 — bloco
de contadores), RF-MRG-03 (CA-03.2/03.3)
**Arquivos:** `src/quantlab/analytics/report.py` (estendido),
`src/quantlab/analytics/benchmark.py` (verificado — INTOCADO),
`src/quantlab/engine/conditional.py` (se preciso — `TradeOrigin` exportado),
`tests/unit/test_report_multi.py` (estendido), `tests/unit/test_benchmark_multi.py`
(estendido), `tests/unit/test_architecture_date_isolation.py` (estendido —
`margin.py` e `walkforward.py` explícitos), `specs/adr/0009-*.md` (verificado)

**Escopo**
`BacktestReportMulti` 2b: contadores novos (`margin_calls`, `borrow_rejections`
no bloco de mecanismo — CA-02.3/CA-03.4); fundo quebrado (flag + CAGR/Sharpe/
turnover/exposição = `None` explícito, nunca NaN — CA-03.2; exclusão de
comparação automática com benchmark — CA-03.3); seção "run" com margem/borrow
configurados, reconstruível do JSON (CA-06.2 — inclui métrica de seleção, grid
size e nº de folds quando há WF); vieses novos na constante literal (CA-06.1:
aluguel não calibrado, aluguel ilimitado, liquidação alfabética com viés, MHT
com métrica/grid/folds, pior caso com buy-stop + itens da 2a); borrow fee em
categoria própria (CA-03.3); alavancagem (gross > 100%) reportada com
utilização de margem (CA-04.2); short travado com categoria própria (CA-05.2).
Benchmark: mesmo `buy_and_hold_multi` da 2a (1/N long-only, nunca short —
CA-05.2) + comparação long+short × long-only da própria estratégia (CA-05.1).
Herança RNF (CA-02.1): os testes de RNF da 2a continuam verdes sobre o run
long+short. ADR-0009 verificado (existe, referenciado na spec — CA-02.3).
Teste de arquitetura estendido a `margin.py`/`walkforward.py` (RNF-07,
bloqueante).

**Fora do escopo**
Harness do WF no CI (T12b); E2E (T13).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_report_counts_margin_call_origin_trades` (CA-02.3)
- [ ] `test_report_borrow_fee_own_category` (CA-03.3)
- [ ] `test_broken_fund_metrics_are_explicit_none_never_nan` (CA-03.2)
- [ ] `test_broken_fund_result_excluded_from_auto_comparison` (CA-03.3)
- [ ] `test_report_benchmark_is_1n_long_only_with_long_short_vs_long_only` (CA-05.1);
  `test_benchmark_never_shorts` (CA-05.2)
- [ ] `test_bias_section_includes_2b_items` (CA-06.1)
- [ ] `test_run_section_reports_mht_metric_grid_folds_reconstructible` (CA-06.2)
- [ ] `test_report_flags_locked_short_position` (CA-05.2 do SHT-05)
- [ ] `test_architecture_timezone_imports` (estendido) — `margin`/`walkforward`
  não importam datetime/timezone (RNF-07, bloqueante)
- [ ] `test_rnf_heritage_tests_pass_on_long_short_run` (CA-02.1)
- [ ] `test_spec_architecture_fails_without_adr_0009` (CA-02.3)
- [ ] Regressão zero: relatório da 2a continua verde

**Riscos**
Médio — o relatório é o único lugar que pode "mentir" sem o engine mentir;
tudo que ele reporta já foi agregado no engine (dono declarado, §3.7) — aqui
só reporta.

**Commit**
`feat(analytics): relatório 2b com contadores, vieses e benchmark long-only (RF-MET-05/06, RF-RNF-02)` —
por quê: contadores, fundo quebrado com None e vieses novos são a leitura
honesta do que shorts/margem/WF acrescentam (D4/R1/R5).

---

## T12b — Harness do RNF-04 2b (WF) + arquitetura + cobertura 85%

**Depende de:** T12
**RFs cobertos:** RF-WFK-05 (CA-05.1 — harness no CI), RNF-02 (CA-02.2),
RNF-07 (arquitetura)
**Arquivos:** `scripts/walkforward_harness.py` (novo), `Makefile` (alvo),
`pyproject.toml` (fail_under 85 estendido a margin/walkforward — verificar que
o escopo já cobre engine/), `.github/workflows/ci.yml` (se preciso),
`tests/unit/test_walkforward.py` (estendido — CA-05.1 no CI)

**Escopo**
Harness do WF (RNF-10): mede `run_walkforward` em duas escalas — por fold
(default 30 s para IS+OOS de 20 ativos × janela) e total (`n_folds×30 s` +
margem) — com escopo declarado (cômputo apenas, sem ingestão/serialização/
PNG); sem base ingerida, séries sintéticas determinísticas com origem
declarada (padrão T17 da 2a). Alvo no Makefile (mediana de N execuções, padrão
da casa). Piso de cobertura: verificar que o `fail_under` de 85 cobre
`engine/margin.py` e `engine/walkforward.py` (RNF-02 CA-02.2).

**Fora do escopo**
E2E (T13).

**Critério de verificação**
- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_walkforward_harness_reports_per_fold_and_total_budgets` (CA-05.1) —
  o harness roda de verdade e reporta ambas as escalas
- [ ] `test_ci_coverage_floor_85_includes_margin_walkforward` (CA-02.2)
- [ ] `make check` com fail_under 85 VERDE (cobertura hoje ~97%, folgada)
- [ ] O harness roda de verdade (medida real registrada, não presumida)

**Riscos**
Baixo — o orçamento por fold vs total é a única coisa nova; o "30 s" da 2a
não se aplica a centenas de runs (RNF-10).

**Commit**
`chore(ci): harness do walk-forward com orçamento por fold e total (RF-WFK-05)` —
por quê: RNF só vale medido e forçado; o orçamento do WF precisa ser declarado
em duas escalas para não virar medição de I/O nem "30 s" impossível.

---

## T13 — Run long+short ponta a ponta vs 1/N long-only (DoD)

**Depende de:** T12b
**RFs cobertos:** Definition of Done da v0.2 (§10)
**Arquivos:** `scripts/e2e_run_2b.py` (novo — runner), `results/` (novos
artefatos), `tests/integration/test_e2e_2b_long_short.py` (novo — hermético,
padrão T18 da 2a), `README.md` (seção de resultados, se a narrativa mudar)

**Escopo**
Run multi-ativo **long+short** ponta a ponta com margem (estratégia com shorts
+ benchmark 1/N long-only), universo de 20 ativos: `get_series×N` →
`run_backtest_multi` (com SmaCross 20/50 estendida para emitir shorts + margem
+ borrow fee) → `buy_and_hold_multi` (1/N long-only, mesmo N/custos/slippage/
cap) → `reconcile_multi` (CA-04.2 fechando com isclose 1e-9, qty negativa e
borrow fees no termo próprio) → relatório 2b persistido em `results/`.
Determinismo: dois runs ⇒ equity/trades/contadores idênticos (teste hermético
no CI, padrão T18 da 2a — dados sintéticos no banco descartável, stack real).
RNF-04 re-medido no run real (meta < 30 s). Resultado honesto reportado como
está — NUNCA ajustar premissa/parâmetro para melhorar número (regra de ouro).

**Fora do escopo**
CLI com flags novas (runner programático basta para o DoD); gráficos.

**Critério de verificação**
- [ ] `make up` + `make test-integration` verde (hermético — CI sobe Mongo
  fresco; dados sintéticos RNF-03 no banco descartável, stack real)
- [ ] Conciliação CA-04.2 passando no run real (isclose 1e-9)
- [ ] Determinismo do run long+short de 20 ativos
- [ ] RNF-04 re-medido < 30 s
- [ ] Resultado persistido em `results/` e COMPARADO contra o 1/N long-only
- [ ] `make check` verde ao final

**Riscos**
Médio — dado real pode expor caso de borda não previsto em fixture; o caminho
é corrigir a spec antes do código, nunca ajustar número.

**Commit**
`chore: run long+short de 20 ativos vs 1/N long-only e commit honesto (DoD 2b)` —
por quê: o objetivo da fase é medir sem mentir; o resultado pode ser derrota
e é reportado como tal.

---

## Encerramento da fase

Só marcar quando todas as tarefas estiverem ✅.

- [ ] Todos os RFs da v0.2 têm ao menos uma tarefa que os cobre (tabela RF → tarefa)
- [ ] Todos os critérios de aceitação citados têm teste correspondente nomeado
- [ ] `make check` verde (lint + mypy --strict + testes com cobertura ≥ 85%)
- [ ] Definition of Done do `fase-2b-requirements.md` §10 integralmente satisfeita
- [ ] `specs/README.md` e `specs/CHANGELOG.md` atualizados

## Tabela RF → tarefa

| RF | Tarefa(s) | CAs exercitados |
|---|---|---|
| RF-SHT-01 | T01 | CA-01.1, CA-01.2, CA-01.3 |
| RF-SHT-02 | T02 | CA-02.1, CA-02.2, CA-02.3, CA-02.4 |
| RF-SHT-03 | T03, T08a, T12 | CA-03.1, CA-03.2, CA-03.3, CA-03.4 |
| RF-SHT-04 | T03 | CA-04.1, CA-04.2, CA-04.3 |
| RF-SHT-05 | T08b, T12 | CA-05.1, CA-05.2 |
| RF-MRG-01 | T04, T08a, T12 | CA-01.1, CA-01.2, CA-01.3, CA-01.4, CA-01.5 |
| RF-MRG-02 | T05, T08a, T08b, T12 | CA-02.1, CA-02.2, CA-02.3, CA-02.4 |
| RF-MRG-03 | T05, T08a, T12 | CA-03.1, CA-03.2, CA-03.3 |
| RF-MRG-04 | T09, T12 | CA-04.1, CA-04.2 |
| RF-ORD-05 | T06 | CA-05.1, CA-05.2, CA-05.3 (+ emenda P1) |
| RF-ORD-06 | T07, T08b | CA-06.1, CA-06.2, CA-06.3 |
| RF-WFK-01 | T10, T11a | CA-01.1, CA-01.2, CA-01.3 |
| RF-WFK-02 | T10, T11a | CA-02.1, CA-02.2, CA-02.3 |
| RF-WFK-03 | T11a, T12 | CA-03.1, CA-03.2 |
| RF-WFK-04 | T11b | CA-04.1, CA-04.2 |
| RF-WFK-05 | T11a, T12b | CA-05.1 |
| RF-MET-05 | T12 | CA-05.1, CA-05.2 |
| RF-MET-06 | T12 | CA-06.1, CA-06.2 |
| RF-RNF-02 | T12, T12b | CA-02.1, CA-02.2, CA-02.3 |

RF-CON-01/02/03 da 2a: verificação HERDADA da Fase 1/2a (baseline verificado,
§7 da spec 2b) — sem tarefa nova; o relatório 2b estende a seção "run"
(RF-MET-06 CA-06.2, T12).

## Mapeamento DoD v0.2 → tarefas

| Item do DoD (§10 da spec) | Tarefa que o satisfaz |
|---|---|
| Run multi-ativo long+short com margem (estratégia com shorts + benchmark 1/N long-only), 20 ativos | T08a/T08b (laço), T12 (benchmark/relatório), T13 (E2E) |
| Conciliação CA-04.2 estendida fechando com isclose 1e-9 (qty negativa, borrow fees no termo próprio) | T03 (identidade), T13 (run real) |
| PnL short × ex-dividendo ≡ retorno ajustado, forma fechada | T03 (CA-04.3) |
| Mutação ENG-01.2 estendida ao OOS passando | T11b (teste puro) |
| Liquidação forçada determinística testada (alfabética, MARGIN_CALL, cancela pendentes, fundo quebrado com None) | T05, T08a/T08b, T12 |
| Buy-stop e ambiguidades novas testadas (pior caso, sem "ambos executam", contadores) | T06, T07, T12 |
| Walk-forward honesto (concatenação OOS) vs 1/N long-only e vs long-only da própria estratégia; warmup pela cauda do IS | T11a, T12, T13 |
| ADRs 0009–0011 escritos | Gate 2 (já entregue — 4faefd5); T12 verifica ADR-0009 (CA-02.3) |
| Cobertura ≥ 85% com módulos novos; CI verde; push a cada etapa | T12b; regra vigente da sessão |
| Resultado honesto com vieses da 2b na seção fixa | T12, T13 |

## Nota sobre a ordem de build

A sequência é dependência-primeiro com três regras de ouro:

1. **Folha antes de consumidor.** T01 (contratos) antecede o broker (T02–T07)
   e o laço (T08); `margin.py` (T03/T04) antecede o laço que o consome (T08a).
   Inverter (ex.: laço antes do broker) forçaria stub de função que a tarefa
   seguinte reescreveria — retrabalho garantido.
2. **Broker antes do laço.** A execução (T02–T07) e a liquidação (T05) são
   peças testáveis isoladamente; o laço (T08) as compõe. Inverter faria o
   laço depender de código ainda em fluxo — o critério 3 do gate 3 ("nenhuma
   dependência inexistente") seria violado.
3. **Analytics depois do engine estável.** T09–T13 consomem o resultado do
   laço (T08b); o WF (T10/T11) roda o `run_backtest_multi` como caixa preta —
   precisa do laço fechado antes. Inverter (WF antes do laço 2b) rodaria o WF
   sobre o engine da 2a e o retrabalho seria total.

Se uma tarefa não couber num commit revisável, divide-se (padrão T11a/T11b da
2a) **sem mudar a tabela RF → tarefa** — a lição está registrada no
`fase-2a-tasks.md` e vale igual aqui.

## Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.1 | 2026-08-14 | Rascunho inicial — gate 3. 16 tarefas em 6 blocos ordenados por dependência (contratos → broker → laço → analytics → WF → E2E), cada uma com RFs/CA, arquivos, testes nomeados do design §10/§10.1, comandos exatos do Makefile, mensagem de commit com o porquê, regressões documentadas (barreira P2; Position qty<0) e o mapeamento DoD → tarefa. |
