# Fase 2a — Execução realista e alocação — Plano de tarefas

**Status:** aprovada — gate check 3 concluído
**Versão:** 0.1
**Data:** 2026-08-14
**Design de origem:** `specs/fase-2a-design.md` v0.1
**Requisitos de origem:** `specs/fase-2a-requirements.md` v0.2

> Último gate antes da implementação. Uma tarefa boa aqui cabe em um commit,
> tem critério de verificação objetivo e não depende de nada que ainda não
> exista. Comandos de verificação são os do `Makefile` (`make check` =
> lint + typecheck + test, espelhando o job "quality" do CI). Cobertura é
> `pytest --cov` com `fail_under` em `pyproject.toml` (80 hoje; 85 a partir
> da T17, conforme RNF-02).

---

## Ordem de execução

Ordenadas por dependência: uma tarefa só aparece depois de tudo que ela precisa. Blocos 1 (folhas) e o trio T13/T14/T15 têm ordem interna livre.

```
T01 T02 T03 T04 T05     (folhas puras — ordem livre dentro do bloco)

T01 ──┐
T02 ──┼──▶ T06 ─▶ T07 ─▶ T08 ─▶ T09 ──▶ T10 ──▶ T11a ─▶ T11b ─▶ T12
T03 ──┘                     (execute)                       (laço)   (ENG-01.2)
T04 ──▶ T06
T05 ────────────────────────────────▶ T11a
                                          │
     T13 ─▶ T14 ─▶ T15 ─▶ T16 ─▶ T17 ─▶ T18
     (T13/T14/T15 dependem só de T11b — ordem interna livre)
```

## Resumo

| # | Tarefa | Depende de | RFs cobertos | Estado |
|---|---|---|---|---|
| T01 | Contratos de estratégia condicional | — | RF-SIG-01 | ⬜ |
| T02 | ADV e cap de participação | — | RF-SLP-03 | ⬜ |
| T03 | Modelos de slippage (ADR-0006) | — | RF-SLP-01, RF-SLP-02 | ⬜ |
| T04 | Contrato do sizer e política 1/N (ADR-0008) | — | RF-SIZ-01, RF-SIZ-02 | ⬜ |
| T05 | Calendário-união imutável (D1) | — | RF-POR-02, RF-POR-05 | ⬜ |
| T06 | Pipeline de conversão de quantidade (R1) | T02, T04 | RF-CST-01, RF-SIZ-01, RF-SLP-03 | ⬜ |
| T07 | Ciclo de vida de ordens (S3) | T06 | RF-ORD-04 | ⬜ |
| T08 | Execução mercado/limite/stop (SLP-04) | T03, T07 | RF-ORD-01, RF-ORD-02, RF-SLP-04 | ⬜ |
| T09 | Pior caso intrabarra (ADR-0007) | T08 | RF-ORD-03 | ⬜ |
| T10 | Portfolio multi-ativo com invariantes | T06, T08 | RF-POR-01, RF-POR-04 | ⬜ |
| T11a | Laço calendário-driven (executar→marcar→consultar, instâncias, ADR-0002 por ativo, invariantes) | T01, T04, T05, T09, T10 | RF-POR-03, RF-POR-05, RF-SIZ-03, RF-SIZ-04 | ⬜ |
| T11b | Mark-to-market multi-ativo e interação de caixa (alfabético, sem reserva, deslistagem) | T11a | RF-POR-01, RF-POR-02 | ⬜ |
| T12 | ENG-01.2 reformulado em duas partes (ADR-0005) | T11 | RF-POR-05, RF-RNF-01 | ⬜ |
| T13 | Conciliação multi-ativo e contribuições | T11 | RF-POR-04, RF-MET-01 | ⬜ |
| T14 | Métricas de portfólio (P4) | T11 | RF-MET-04, RF-MET-01 | ⬜ |
| T15 | Benchmark 1/N multi-ativo (S6) | T11 | RF-MET-02 | ⬜ |
| T16 | Relatório: contadores, seção run, vieses | T14, T15 | RF-MET-03, RF-MET-05, RF-CON-02 | ⬜ |
| T17 | Harness RNF-04, fronteira de instante, cobertura 85% | T16 | RF-RNF-01, RNF-02, RNF-04, RNF-07 | ⬜ |
| T18 | Run de 20 ativos ponta a ponta e resultado honesto | T17 | DoD | ⬜ |

Estados: ⬜ não iniciada · 🟡 em andamento · ✅ concluída · ⛔ bloqueada

---

## T01 — Definir contratos de estratégia condicional

**Depende de:** —
**RFs cobertos:** RF-SIG-01 (CA-01.1, CA-01.2, CA-01.3, CA-01.4)
**Arquivos:** `src/quantlab/engine/conditional.py` (novo), `tests/unit/test_conditional.py` (novo)

**Escopo**
`OrderKind` (MARKET/LIMIT/STOP), `Bracket` (par limite+stop na mesma intenção), `ConditionalIntent` (validação `LIMIT ⇒ limit`, `STOP ⇒ stop`, `bracket ⇒ par juntos`) e o Protocol `ConditionalStrategy`. `Signal`/`Strategy` da Fase 1 ficam intocados — o módulo novo não altera `engine/strategy.py`.

**Fora do escopo**
Execução de ordens (T08); resolução de ambiguidade intrabarra (T09); comportamento do engine diante do Protocol (T11). A validação de `Bracket` (`0 < stop < limit`) mora aqui, mas a ativação do stop é do broker (T08).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] Teste `tests/unit/test_conditional.py::test_bracket_carries_limit_and_stop_in_same_intention` passa e falha sem este módulo
- [ ] `ConditionalIntent(LIMIT)` sem `limit` levanta `ValueError`; `bracket` sem par completo levanta `ValueError` (CA-01.2)

**Riscos**
Baixo — módulo puro. Risco de escopo: alguém tentar tocar `Strategy` aqui; fora do escopo, fica na T11.

**Commit**
`feat(engine): define ConditionalIntent/Bracket contracts for conditional strategies` — por quê: os metadados de limite/stop precisam viajar na mesma intenção (bracket) sem alterar o contrato `Strategy` da Fase 1 (SIG-01.1).

---

## T02 — Implementar ADV e cap de participação

**Depende de:** —
**RFs cobertos:** RF-SLP-03 (CA-03.1, CA-03.3, CA-03.4, CA-03.5)
**Arquivos:** `src/quantlab/engine/liquidity.py` (novo), `tests/unit/test_liquidity.py` (novo)

**Escopo**
`adv(series, i, window=20)`: média de volume dos 20 pregões do próprio ativo terminando na barra `i` (CA-03.1), `None` com histórico insuficiente (CA-03.2, o fallback é da T03). `participation_cap(qty, adv, cap=0.10)`: corte de quantidade a `⌊cap × ADV⌋` (CA-03.3); nunca chamada para saídas (CA-03.4); resultado `< 1` ⇒ sem ordem, logado (CA-03.5).

**Fora do escopo**
Modelo de slippage de preço (T03); aplicação do cap no pipeline de quantidade (T06); a regra "cap só em entradas" é garantida por quem chama — enforcement no `convert` (T06) e no laço (T11).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `tests/unit/test_liquidity.py::test_adv_window_is_20_sessions_of_own_asset` — fixture com 25 barras: média dos últimos 20, terminando em `i`; janela menor ⇒ `None`
- [ ] `tests/unit/test_liquidity.py::test_cap_applies_to_entries_only_and_subshare_cancels` — cap arredonda para baixo; `cap × ADV < 1` ⇒ 0

**Riscos**
Baixo — função pura. Cuidado com janela que termina em `i` (inclusive) vs `i-1`: a definição é fechada pelo design (§3.3) e pelo teste de papel.

**Commit**
`feat(engine): add ADV window and participation cap helpers` — por quê: a janela de 20 pregões e o cap são por ativo e precedem o broker; sem eles o corte de quantidade não tem base de liquidez (SLP-03).

---

## T03 — Implementar modelos de slippage (ADR-0006)

**Depende de:** —
**RFs cobertos:** RF-SLP-01 (CA-01.1, CA-01.2), RF-SLP-02 (CA-02.1)
**Arquivos:** `src/quantlab/engine/slippage.py` (novo), `tests/unit/test_slippage.py` (novo)

**Escopo**
Protocol `SlippageModel.execution_price(ref, side, qty, adv)`; `FixedBps` (`ref × (1 ± bps/10000)`); `Participation` com a forma funcional cravada do ADR-0006: `slippage_bps = bps × (1 + k × q/ADV)`, defaults determinísticos `bps = 1.0`, `k = 1.0` (configuráveis); `adv is None` ⇒ recai em `FixedBps` com aviso (CA-03.2).

**Fora do escopo**
Aplicação no broker (quem chama e quando — mercado/stops apenas, limite nunca violado) é da T08. O relatório de slippage zero (CA-01.3) é da T16.

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_fixed_bps_execution_price` — fixture de papel: compra `ref × (1 + bps/10000)`, venda `ref × (1 − bps/10000)`
- [ ] `test_participation_slippage_matches_closed_form` — `bps=1.0, k=1.0`, valores de q/ADV: bate com a fórmula fechada
- [ ] `test_slippage_monotonic_in_participation` — q/ADV maior ⇒ preço pior (CA-03.1)
- [ ] `test_participation_falls_back_to_fixed_with_warning` — `adv=None` executa como `FixedBps` e emite aviso (CA-03.2)

**Riscos**
Baixo. Defaults não-determinísticos seriam a falha de gate 3 — o teste de fórmula fechada trava `bps` e `k`.

**Commit**
`feat(engine): add slippage models with fixed functional form (ADR-0006)` — por quê: forma funcional cravada e defaults determinísticos transformam a monotonicidade de CA em teste de igualdade contra valor de papel, fechando o gate 3.

---

## T04 — Implementar contrato do sizer e política 1/N (ADR-0008)

**Depende de:** —
**RFs cobertos:** RF-SIZ-01 (CA-01.1), RF-SIZ-02 (CA-02.1, CA-02.3), RF-SIZ-04 (CA-04.2)
**Arquivos:** `src/quantlab/engine/sizing.py` (novo), `tests/unit/test_sizing.py` (novo)

**Escopo**
`SizingInputs` (patrimônio, caixa, posições, último close por ativo, `n` — com `positions: dict[str, int]` ticker → quantidade, emenda §3.4: o sizer consome só quantidade, nunca `Position` da Fase 1); Protocol `Sizer.target_fraction(ticker, inputs)` devolvendo fração; `FixedOneOverN` (`1/n`, N fixado no run, `N=1 ⇒ 1.0` all-in); `EqualWeightOpen` (`1/k`, `threshold_pp=1.0`) + helper puro `rebalance_deviation_pp` (SIZ-03.3) — só a política, sem o gatilho de rebalance (T11).

**Fora do escopo**
Gatilho de rebalance por mudança de `k` e limiar em pp (T11); conversão de fração em quantidade (T06); invariante `k ≤ N` (T11); ativo sem barra nunca recebe alvo (T11, provado na T13).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_sizer_returns_fraction_not_quantity` — política nova devolve fração; nenhuma conversão aqui (CA-04.2)
- [ ] `test_target_is_equity_over_n_fixed_and_n1_is_allin` — `FixedOneOverN(20)` ⇒ 0.05; `FixedOneOverN(1)` ⇒ 1.0 (CA-02.1, CA-02.3)

**Riscos**
Baixo. `EqualWeightOpen` sem gatilho no engine seria política morta — o "fora do escopo" aponta T11 para não deixar orfã.

**Commit**
`feat(engine): add sizer contract and 1/N default policy (ADR-0008)` — por quê: tamanho é decisão do engine, não da estratégia (ENG-05.2), e o 1/N com N do run é o benchmark neutro e determinístico (P3).

---

## T05 — Implementar calendário-união imutável (D1)

**Depende de:** —
**RFs cobertos:** RF-POR-02 (CA-02.1), RF-POR-05 (CA-05.1)
**Arquivos:** `src/quantlab/engine/calendar.py` (novo), `tests/unit/test_calendar.py` (novo)

**Escopo**
`UnionCalendar.build(series)` — merge em **uma passada** O(total) das datas ordenadas por ativo; `bar_index` por ativo alinhado à união (`-1` sse sem barra na data); `last_known` (cummax da mesma passada); arrays imutáveis (`frozen` + `writeable=False`); acesso O(1) por índice de união.

**Fora do escopo**
Uso no laço (T11); mark-to-market e deslistagem (T11); a fronteira "pendente executa na próxima barra do próprio ativo" é do laço (T11, CA-05.3).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_union_calendar_matches_naive_lookup` — fixture pequena (3 ativos, datas desalinhadas, um IPO): `bar_index`/`last_known` batem com busca ingênua por `(data, ativo)` (CA-02.1)
- [ ] `test_union_calendar_build_is_pure_and_linear` — (i) mesmo input ⇒ estrutura idêntica (função pura); (ii) custo de `build` escala linearmente com o total de barras (guarda de regressão de O(n²), D1)
- [ ] tentativa de escrita em `bar_index[ticker]` levanta `ValueError` (imutabilidade)

**Riscos**
Médio — é a estrutura que RNF-04 depende. O teste de linearidade é de propriedade, não de sequência de chamadas (D1); a API sem consulta por data é o que impede O(n²) por construção.

**Commit**
`feat(engine): add immutable union calendar with per-asset bar indexes` — por quê: RNF-04 (30 s) depende de merge O(total) sem busca por `(data, ativo)`, e imutabilidade é política do projeto (D1).

---

## T06 — Converter intenções pelo pipeline fixo de quantidade (R1)

**Depende de:** T02, T04
**RFs cobertos:** RF-CST-01 (CA-01.2, CA-01.3), RF-SIZ-01 (CA-01.2), RF-SLP-03 (CA-03.3)
**Arquivos:** `src/quantlab/engine/broker.py` (estendido), `src/quantlab/engine/portfolio.py` (estendido — `Trade` com `origin`/`cut_reason`/`ambiguous`), `tests/unit/test_broker.py`, `tests/unit/test_portfolio.py`

**Escopo**
`CutStage` (SIZING/CAP/INTEGER/CASH); `ConvertedOrder` (ticker, kind, limit/stop, qty, `ref_price`, `decision_date`, `intent_seq`, `cut_reason`, `est_cost`, `bracket`); `PendingOrder` (ticker, kind, limit, stop, qty, `decision_date`, `intent_seq`, `bracket`); extensão de `Trade` com `origin`/`cut_reason`/`ambiguous`; `CostModel` com `min_cost=0.0` e `cost_for = max(f + p×N, m)` (CA-01.1); `Broker.convert(intent, ticker, inputs, sizer, adv, cost_model, cap, decision_date, intent_seq) -> ConvertedOrder | None` (emenda §3.5: sizer/decision_date/intent_seq vêm do laço — função pura) aplicando a sequência fixa **SIZING → CAP (SLP-03) → INTEIRAS (SIZ-01.2) → CAIXA/CUSTOS (CST-01.2)** e registrando a última etapa do corte em `cut_reason` (CST-01.3); `ref_price = last_close[ticker]`.

**Fora do escopo**
Regras de preenchimento/limite/stop (T08); ciclo de vida de pendentes — `place`/`cancel_all` (T07); pior caso intrabarra (T09).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_cut_sequence_order_and_reason_recorded` — fixture onde cap corta: `cut_reason == CAP`; onde caixa/custo corta: `cut_reason == CASH`; ordem da sequência jamais invertida (CA-01.3, R1)
- [ ] caixa insuficiente para 1 ação após custos ⇒ nenhuma ordem, evento logado (CA-01.2, ENG-02.3)

**Riscos**
Médio — é a tarefa que materializa R1; a ambiguidade de motivo do corte é exatamente o que a sequência fixa elimina. Teste de mutação da ordem das etapas deve falhar.

**Commit**
`feat(engine): convert intentions through fixed quantity-reduction pipeline` — por quê: sem sequência determinística (SIZING→CAP→INTEIRAS→CAIXA/CUSTOS) o motivo do corte no trade fica ambíguo e a auditoria perde o sentido (R1).

---

## T07 — Implementar ciclo de vida de ordens (S3)

**Depende de:** T06
**RFs cobertos:** RF-ORD-04 (CA-04.1, CA-04.2, CA-04.3, CA-04.4)
**Arquivos:** `src/quantlab/engine/broker.py` (estendido), `tests/unit/test_broker.py`

**Escopo**
`PendingBook` em `broker.py` (emenda §3.5: o store de pendentes vive no broker, broker ESTÁTICO — a T10 compõe no Portfolio); `Broker.place(store, order)` — sem reserva de caixa (CA-04.3); última intenção vence via `intent_seq` (CA-04.2); bracket ⇒ o PAR nasce no place (limite + stop, mesmo `decision_date`/`intent_seq` — SIG-01.3), stop só ATIVA com posição aberta (ORD-02.2, T08); `Broker.cancel_all(store, ticker)` — EXIT cancela TODAS as pendentes do ativo, incluindo stops (CA-04.1); `decision_date` gravado na ordem (CA-04.4, base da auditoria do ENG-01.2).

**Fora do escopo**
Execução de ordens (T08); o teste de "segunda entrada vê caixa já debitado" exige duas entradas na mesma barra — laço (T11); preenchimento de limite/stop (T08).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_last_intention_wins_replaces_pending` — segunda intenção substitui pendentes anteriores; ordem antiga jamais executa (CA-04.2)
- [ ] `test_exit_cancels_all_pending_including_stops` — `EXIT` cancela stop pendente; nada executa depois (CA-04.1)

**Riscos**
Médio — "última intenção vence" mal feita gera trade fantasma (ordem antiga executando); o teste nomeado é o guard.

**Commit**
`feat(engine): add order lifecycle rules (no reserve, last intention wins, EXIT cancels all)` — por quê: a fila de pendentes é um vetor de lookahead novo na 2a; fechar o ciclo de vida por construção é o que impede execução de ordem que a decisão original já abandonou (S3).

---

## T08 — Executar ordens mercado/limite/stop com regras de slippage e custos (SLP-04)

**Depende de:** T03, T07
**RFs cobertos:** RF-ORD-01 (CA-01.1, CA-01.2, CA-01.3), RF-ORD-02 (CA-02.1, CA-02.2), RF-SLP-04 (CA-04.1, CA-04.2, CA-04.3, CA-04.4)
**Arquivos:** `src/quantlab/engine/broker.py` (estendido), `tests/unit/test_broker.py`

**Escopo**
`Broker.execute_pending(ticker, bar, adv)` — mercado ao `open` com slippage (SLP-04.1); limite: `low ≤ L ⇒ min(L, open)`, senão cancela ao fim da barra (ORD-01.1/01.3); stop: com posição aberta e `low ≤ S ⇒` vira mercado a `min(S, open)` com slippage (ORD-02.1), sem posição nunca ativa (ORD-02.2); limite nunca violado (SLP-04.2); custos debitados do caixa, fora do preço de execução (SLP-04.3); broker consome o Protocol `SlippageModel` sem acoplamento (SLP-01.2).

**Fora do escopo**
Pior caso intrabarra (T09); atendimento alfabético com caixa insuficiente entre ativos (T11 — precisa do laço e do caixa compartilhado); pior caso para bracket de saída (T09).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_limit_fills_at_min_or_max_of_limit_and_open` (CA-01.1/01.2); `test_limit_cancels_at_end_of_bar` (CA-01.3)
- [ ] `test_stop_triggers_market_at_min_stop_open` (CA-02.1); `test_stop_never_activates_without_open_position` (CA-02.2)
- [ ] `test_limit_price_never_violated_and_market_slippage_only` (SLP-04.1/04.2); `test_costs_debited_from_cash_not_in_execution_price` (SLP-04.3)
- [ ] `test_pluggable_slippage_model_requires_no_broker_change` — modelo novo roda sem alterar o broker (SLP-01.2)

**Riscos**
Alto — concentra as regras de preço que separam medição honesta de otimismo. Mutação de "limite preenche a preço pior que L" deve derrubar o teste de limite nunca violado.

**Commit**
`feat(engine): execute market/limit/stop orders with slippage and cost rules` — por quê: limite nunca violado e custos fora do preço de execução são o que mantém o "medir sem mentir" da Fase 1 quando ordens condicionais entram (SLP-04).

---

## T09 — Resolver ambiguidade intrabarra por pior caso (ADR-0007)

**Depende de:** T08
**RFs cobertos:** RF-ORD-03 (CA-03.1, CA-03.2, CA-03.3)
**Arquivos:** `src/quantlab/engine/broker.py` (estendido), `tests/unit/test_broker.py`

**Escopo**
Bracket de entrada com limite e stop ambos tocados na mesma barra ⇒ posição abre em L e fecha no stop S (perda `L − S + custos`, flat, `ambiguous=True`); bracket de saída ⇒ stop preenche em S, `ambiguous=True`; não existe caminho "ambos executam" (CA-03.3); ocorrência registrada para o contador (CA-03.2 — exposição no relatório é da T16).

**Fora do escopo**
Bloco "contadores de mecanismo" no relatório (T16); decisão de qual é o pior caso — fechada no ADR-0007.

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_intrabar_ambiguity_entry_bracket_worst_case` — barra com `low ≤ S` e `low ≤ L`: abre em L, fecha no stop, flat, `ambiguous=True`, caixa bate com `L − S + custos` (CA-03.1/03.3)
- [ ] `test_intrabar_ambiguity_exit_bracket_worst_case` — posição aberta, limite e stop tocados: stop preenche em S (CA-03.1)

**Riscos**
Médio — a semântica "abre e fecha na mesma barra" exige cuidado com a contabilidade (posição nasce e morre na mesma barra; equity de `u` reflete o resultado). O teste de caixa fecha isso.

**Commit**
`feat(engine): resolve intrabar ambiguity by worst case (ADR-0007)` — por quê: com barras diárias o caminho intrabarra é desconhecido; o pior caso é determinístico (RNF-01) e declarado no trade, não escondido.

---

## T10 — Estender portfolio para multi-ativo com invariantes

**Depende de:** T06, T08
**RFs cobertos:** RF-POR-01 (CA-01.1), RF-POR-04 (CA-04.1, CA-04.3)
**Arquivos:** `src/quantlab/engine/portfolio.py` (estendido), `tests/unit/test_portfolio.py`

**Escopo**
`Portfolio` com caixa único (CA-01.1), `positions` por ativo, `pending` por ativo, `market_to_market(close_by_ticker)` (último close conhecido); invariantes checadas a cada barra: `cash ≥ 0`, `qty ≥ 0` (CA-04.3).

**Fora do escopo**
Atendimento alfabético com caixa insuficiente (T11); conciliação somando N ativos (T13); invariante `k ≤ N` (T11).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_equity_identity_multi_asset` — `equity = cash + Σ qty×close` com 3 ativos, um sem barra na data (CA-04.1)
- [ ] `test_cash_and_quantity_never_negative_multi` — ordem que levaria caixa a negativo é bloqueada (CA-04.3)

**Riscos**
Médio — o guard de caixa é o que impede o bug clássico de quantidade sem custo. Mutação que ignore o custo deve derrubar o teste.

**Commit**
`feat(engine): extend portfolio to shared-cash multi-asset with invariants` — por quê: caixa único e invariantes por barra são condição de contorno do laço; sem guard, erro de programação vira caixa negativo silencioso (POR-04.3).

---

## T11a — Conduzir o laço calendário-driven (executar → marcar → consultar)

**Depende de:** T01, T04, T05, T09, T10
**RFs cobertos:** RF-POR-03 (CA-03.1, CA-03.2), RF-POR-05 (CA-05.1, CA-05.3), RF-SIZ-03 (CA-03.1, CA-03.3, CA-03.4), RF-SIZ-04 (CA-04.3), RF-RNF-01 (CA-01.1 — determinismo), RF-SIG-01 (CA-01.1 — Fase 1 roda sem mudança)
**Arquivos:** `src/quantlab/engine/backtest.py` (estendido), `tests/unit/test_backtest.py`

**Escopo**
Laço calendário-driven: para cada índice-união `u` — **executar** (pendentes por ativo no open da próxima barra do próprio ativo, ADR-0002 por ativo — CA-05.3; saída pendente de EXIT da barra anterior vende ao open — decisão T11a, emenda §4; MARKET SELL sintético só para rebalance — venda parcial; ENG-01.4 por ativo: intenção na última barra da série morre pendente, contada em `pending_dead` e reportada), **marcar** (equity por `marks` — POR-04.1), **consultar** (instâncias independentes por ativo — CA-03.1; Fase 1 `Strategy` roda sem mudança — SIG-01.1/CA-03.2; `MarketView` só com barras do próprio ativo — CA-05.1/POR-02.4); fases em ordem alfabética; gatilho de rebalance por mudança de `k` com limiar em pp (SIZ-03.1/03.3/03.4) gerando ordens sintéticas `rebalance=True` (emenda §3.5/§3.6: `PendingOrder.rebalance`, `Trade.rebalance`) para o próximo open do próprio ativo; resultado `BacktestResultMulti` (emenda §3.6); invariantes `k ≤ N` (SIZ-04.3), `cash ≥ 0`, `qty ≥ 0`.

**Fora do escopo**
Mark-to-market por último close conhecido, deslistagem e interação de caixa entre ativos (T11b); testes de mutação do ENG-01.2 reformulado (T12); conciliação/métricas/relatório (T13–T16); medição de RNF-04 (T17).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_pending_order_executes_at_next_bar_of_own_asset` (CA-05.3); `test_last_bar_intention_dies_pending_per_asset` (ENG-01.4 por ativo)
- [ ] `test_market_view_contains_only_own_asset_bars` (CA-05.1/POR-02.4)
- [ ] `test_n_independent_strategy_instances_each_see_own_asset` (CA-03.1); `test_fase1_strategy_runs_unchanged_multi_asset` (SIG-01.1/CA-03.2)
- [ ] `test_open_positions_never_exceed_n` (SIZ-04.3); `test_no_rebalance_without_k_change` e `test_rebalance_threshold_pp_gates_adjustment` (SIZ-03)
- [ ] `test_multi_asset_run_is_deterministic` (RNF-01); `test_equity_of_bar_does_not_depend_on_signal_multi_asset` (ENG-05.2 estendido)

**Riscos**
Alto — é o C5 da Fase 2a. Inverter executar-antes-de-consultar reintroduz lookahead (ENG-01.2 parte 1 quebra na T12); a docstring do laço declara a sequência como invariante. Divisão da antiga T11: esta tarefa não resolve interação de caixa entre ativos — isso é T11b, em commit próprio.

**Commit**
`feat(engine): drive multi-asset bar loop over the union calendar` — por quê: ADR-0002 por ativo e instâncias independentes são o que mantém o anti-lookahead por construção quando N ativos dividem um caixa.

---

## T11b — Marcar a mercado multi-ativo e resolver a interação de caixa

**Depende de:** T11a
**RFs cobertos:** RF-POR-02 (CA-02.2, CA-02.3), RF-POR-05 (CA-05.2), RF-POR-01 (CA-01.2), RF-ORD-04 (CA-04.3 — sem reserva de caixa)
**Arquivos:** `src/quantlab/engine/backtest.py` (estendido), `tests/unit/test_backtest.py`

**Escopo**
Mark-to-market por **último close conhecido** para ativo sem barra na data-união (CA-05.2/POR-02.2); deslistagem = posição travada e reportada (POR-02.3 — `BacktestResultMulti.delisted`, emenda §3.6: tickers com posição ABERTA cuja série terminou antes do fim da união; marcadas pelo último close, nunca liquidadas); atendimento **alfabético** com caixa insuficiente, ordem não-atendida logada (CA-01.2); segunda entrada na mesma barra vê o caixa **já debitado** pela primeira (ORD-04.3).

**Fora do escopo**
Laço/instâncias/ADR-0002 por ativo (T11a); contadores de mecanismo no relatório (T16); conciliação somando N ativos (T13); benchmark (T15 — a deslistagem do benchmark repete esta regra).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_asset_without_bar_is_marked_with_last_close` (CA-05.2/POR-02.2)
- [ ] `test_delisted_position_is_locked_and_reported` (POR-02.3 — lado da estratégia)
- [ ] `test_alphabetical_serving_with_insufficient_cash` (CA-01.2)
- [ ] `test_second_entry_sees_cash_already_debited` (ORD-04.3)

**Riscos**
Médio — ordem de atendimento com caixa compartilhado é determinismo puro: alfabética é a regra, qualquer outra quebra o teste. Último close conhecido errado (barra da data seguinte em vez da anterior) quebra o teste de mark-to-market.

**Commit**
`feat(engine): mark multi-asset portfolio and resolve shared-cash serving` — por quê: último close conhecido e atendimento alfabético são o que mantém a equity honesta e o caixa compartilhado determinístico quando ativos sem barra e ordens concorrentes coexistem (POR-01.2/POR-02.2).

---

## T12 — Reformular o teste de mutação ENG-01.2 em duas partes (ADR-0005)

**Depende de:** T11
**RFs cobertos:** RF-POR-05 (CA-05.4), RF-RNF-01 (CA-01.1), ENG-01.2 (DoD — wording literal da v0.2)
**Arquivos:** `tests/unit/test_backtest.py` (estendido), `tests/unit/test_eng_012_conditional.py` (novo)

**Escopo**
Os três testes da parte 2 do ADR-0005: mutação de barras futuras não altera a intenção (sinais e preços de limite/stop); toda execução de limite/stop vincula-se a ordem preexistente via `decision_date` no Trade anterior à barra de execução; fronteira de mutação por ativo. Substitui o teste single-asset da Fase 1 como critério da fase.

**Fora do escopo**
Qualquer código de engine — é commit de teste puro sobre o laço da T11.

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_eng_012_mutation_does_not_change_conditional_intent` — mutar barras futuras (pós-decisão) mantém sinais e preços de limite/stop idênticos
- [ ] `test_eng_012_execution_binds_to_order_via_decision_date` — todo `Trade.origin ∈ {limit, stop}` tem `decision_date` anterior à barra de execução; mutar a fila de pendentes não cria execução nova
- [ ] `test_mutation_frontier_is_per_asset` — mutar futuro de X não altera decisões/execuções de X nem de Y (CA-05.4)
- [ ] os três testes falham sob a mutação correspondente (verificar localmente, não commitar)

**Riscos**
Alto — é o critério de aceitação da fase; se o laço (T11) estiver com lookahead, é aqui que aparece.

**Commit**
`test(engine): reformulate ENG-01.2 mutation test in two parts (ADR-0005)` — por quê: o teste da Fase 1 (ordens a mercado, single-asset) não cobre condicionais nem a fronteira por ativo; o critério da fase muda de forma documentada.

---

## T13 — Conciliar a identidade multi-ativo e contribuições por ativo

**Depende de:** T11
**RFs cobertos:** RF-POR-04 (CA-04.2), RF-MET-01 (CA-01.1), RF-SIZ-02 (CA-02.4 — conciliação sem buraco)
**Arquivos:** `src/quantlab/analytics/metrics.py` (estendido), `tests/unit/test_reconciliation.py` (novo)

**Escopo**
Identidade de design §6: PnL realizado **bruto** por trade, custos uma única vez no termo próprio, não-realizado por ativo pelo último close conhecido (inclui posição travada), soma sobre N ativos com `math.isclose(rel_tol=1e-9)` (CA-04.2); `contribution_per_asset` somando ao PnL total (CA-01.1).

**Fora do escopo**
Turnover/exposição (T14); relatório (T16).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_reconciliation_multi_asset_20_assets` — 20 ativos em fixture sintética, incluindo deslistado e nunca-negociado; identidade fecha a 1e-9 (CA-04.2)
- [ ] `test_contributions_per_asset_reconcile_with_total_pnl` (CA-01.1)
- [ ] `test_never_traded_asset_contributes_zero_and_reconciles` — ativo sem barra no N: contribuição zero, sem buraco (CA-02.4/R2)

**Riscos**
Médio — o erro clássico é subtrair custos duas vezes (PnL líquido); a definição bruta + termo próprio elimina por construção e o teste fecha.

**Commit**
`feat(analytics): reconcile multi-asset identity and per-asset contributions` — por quê: a conciliação somando N ativos com PnL bruto é o que prova que o engine não mente em portfólio (POR-04.2).

---

## T14 — Computar métricas de portfólio (P4)

**Depende de:** T11
**RFs cobertos:** RF-MET-04 (CA-04.1, CA-04.2, CA-04.3, CA-04.4), RF-MET-01 (CA-01.2)
**Arquivos:** `src/quantlab/analytics/metrics.py` (estendido), `tests/unit/test_metrics.py`

**Escopo**
`turnover_annualized` = `(Σ|notional_compra| + Σ|notional_venda|) / (2 × patrimônio_médio) × (252 / n_barras)`; `patrimônio_médio` = média aritmética diária da equity; `avg_exposure` = média diária de `(Σ qtyᵢ × closeᵢ) / equity`; as **mesmas** definições para estratégia e benchmark (CA-04.2).

**Fora do escopo**
Relatório (T16); benchmark (T15).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_turnover_and_exposure_closed_form_fixture` — fixture de papel com trades e equity calculáveis: valor bate com a fórmula fechada (CA-04.1/04.3/04.4)
- [ ] `test_same_definitions_strategy_and_benchmark` — mesmos inputs de patrimônio médio e turnover nos dois (CA-04.2)

**Riscos**
Baixo — funções puras; risco é desalinhar as definições entre estratégia e benchmark, travado pelo teste de paridade.

**Commit**
`feat(analytics): compute portfolio turnover, exposure and per-asset contribution` — por quê: fórmulas fechadas e idênticas entre estratégia e benchmark tornam a comparação interpretável em vez de adivinhada (P4).

---

## T15 — Construir benchmark 1/N multi-ativo (S6)

**Depende de:** T11
**RFs cobertos:** RF-MET-02 (CA-02.1, CA-02.2, CA-02.3, CA-02.4), RF-POR-02 (CA-02.3 — deslistagem no benchmark)
**Arquivos:** `src/quantlab/analytics/benchmark.py` (estendido), `tests/unit/test_benchmark.py`

**Escopo**
`buy_and_hold_multi` — compra **cada ativo** na primeira barra negociável do próprio ativo (CA-02.2); herda **todas** as regras de entrada (custos, slippage, cap) via `Broker.convert/execute` (CA-02.1); mesmo `N` do run (P3); caixa ocioso, sem rebalance (CA-02.4); deslistagem travada e reportada (CA-02.3).

**Fora do escopo**
Métricas (T14); relatório (T16).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_benchmark_buys_at_first_tradable_bar_per_asset_with_entry_rules` — ativo com série tardia compra na primeira barra do próprio ativo, com custos/slippage/cap aplicados (CA-02.1/02.2)
- [ ] `test_delisted_position_is_locked_and_reported` — ativo deslistado no meio: posição travada, mesma regra da estratégia (CA-02.3)

**Riscos**
Médio — benchmark com regras de entrada diferentes da estratégia invalida a comparação; o teste de paridade de regras é o guard.

**Commit**
`feat(analytics): build 1/N multi-asset benchmark inheriting entry rules` — por quê: benchmark justo compra na primeira barra negociável do próprio ativo com as mesmas regras; comparação assimétrica não significa nada (S6).

---

## T16 — Ampliar o relatório: contadores, seção run, vieses

**Depende de:** T14, T15
**RFs cobertos:** RF-MET-05 (CA-05.1, CA-05.2, CA-05.3), RF-MET-03 (CA-03.1), RF-CON-02 (extensão multi-ativo)
**Arquivos:** `src/quantlab/analytics/report.py` (estendido), `tests/unit/test_report.py`

**Escopo**
Bloco "contadores de mecanismo" — `stops_triggered` (categoria própria), `intrabar_ambiguities`, `unfilled_cash_orders` (CA-05.1–05.3); seção "run" ampliada com universo (`N`, tickers) e configuração (CA-02.2/02.1 — extensão do teste da Fase 1); seção fixa de vieses com os itens novos (CA-03.1); trades de rebalance contados separados dos de sinal (SIZ-03.2 — exposição).

**Fora do escopo**
CLI/gráfico (não escopados nesta fase); medição de RNF-04 (T17).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_report_mechanism_counters_block` — fixture com stop disparado, ambiguidade e ordem não atendida: as três categorias presentes no bloco (CA-05.1–05.3)
- [ ] `test_bias_section_includes_conditional_items` — os itens novos de viés presentes na constante literal (CA-03.1)
- [ ] `test_rebalance_trades_counted_separately_from_signal` (SIZ-03.2)
- [ ] extensão de `test_full_run_configuration_is_reconstructible_from_the_json_alone` (Fase 1) — JSON isolado reconstitui `N`, tickers e configuração do run multi-ativo (RF-CON-02)

**Riscos**
Baixo — os contadores dependem de o laço (T11) e a T09 incrementarem corretamente; o teste fecha o vínculo.

**Commit**
`feat(analytics): add mechanism counters and extended biases to report` — por quê: stops, ambiguidades e não-atendidas são auditoria do mecanismo, não métrica de resultado; sem bloco próprio elas somem da leitura (P6).

---

## T17 — Medir RNF-04, estender fronteira de instante e subir cobertura para 85%

**Depende de:** T16
**RFs cobertos:** RF-RNF-01 (CA-01.2, CA-01.3), RNF-02 (85%), RNF-04 (30 s), RNF-07 (fronteira de instante)
**Arquivos:** `pyproject.toml` (fail_under 80 → 85), `.github/workflows/ci.yml`, `tests/unit/test_architecture.py` (estendido), `tests/unit/test_rnf04_harness.py` (novo), `src/quantlab/engine/...` (se o teste de arquitetura expor violação)

**Escopo**
Harness do RNF-04 com escopo declarado (P5): `get_series × N` + run multi-ativo + `buy_and_hold_multi` + `report.build()`, **excluindo** ingestão (I/O Mongo) e renderização de PNG; teste de arquitetura de timezone estendido aos módulos novos (`calendar/liquidity/slippage/sizing/conditional/broker`), bloqueante; `fail_under` para 85 com cobertura em `engine/` e `analytics/` (RNF-02).

**Fora do escopo**
Medição do run real de 20 ativos (T18 — executa o harness contra o universo real).

**Critério de verificação**

- [ ] `make test-unit` verde; `make typecheck` verde
- [ ] `test_rnf04_harness_measures_compute_only` — harness exclui serialização de relatório e renderização de PNG; escopo documentado no teste (CA-01.3)
- [ ] `test_architecture_timezone_imports` (estendido) — `datetime`/`timezone` em qualquer módulo novo faz o teste falhar (RNF-07, bloqueante)
- [ ] `test_ci_coverage_floor_85` — a configuração de cobertura exige ≥ 85% em `engine/` + `analytics/` (RNF-02); `make test` com `fail_under = 85` passa
- [ ] `make check` verde

**Riscos**
Médio — subir o piso pode expor módulos novos sem teste; é o momento de fechar lacunas de cobertura dos blocos anteriores, não de negociar o piso.

**Commit**
`chore(ci): measure RNF-04 compute-only, extend timezone test, enforce 85% coverage` — por quê: RNF só vale medido e forçado; o escopo da medição de 30 s precisa ser declarado para não virar medição de I/O (P5).

---

## T18 — Rodar o run de 20 ativos ponta a ponta e reportar resultado honesto

**Depende de:** T17
**RFs cobertos:** Definition of Done do requirements v0.2 (§10)
**Arquivos:** `src/quantlab/cli.py` ou runner de run multi-ativo (mínimo), `results/` (novos artefatos), `README.md` (seção de resultados/limitações)

**Escopo**
Runner do run multi-ativo sobre o universo completo (`config/universe.yml`, N=20): estratégia vs benchmark `1/N`; persistência do run; relatório com contadores; execução do harness do RNF-04 sobre o run real (só cômputo); commit do resultado como saiu — **incluindo derrota para o buy-and-hold**.

**Fora do escopo**
CLI completa com flags novas (não pedida na v0.2 — runner programático basta para o DoD); gráficos (não escopados).

**Critério de verificação**

- [ ] `make up` + `make test-integration` verde (run real contra Mongo)
- [ ] Run de 20 ativos roda ponta a ponta; conciliação CA-04.2 passa no run real; RNF-04 medido < 30 s no harness declarado
- [ ] Relatório contém: benchmark 1/N lado a lado, contadores de mecanismo, seção run com N=20 e tickers
- [ ] Resultado commitado em `results/` como saiu, com a seção de vieses declarada; README atualizado se a narrativa mudar
- [ ] Checklist de encerramento abaixo integralmente ✅

**Riscos**
Médio — dado real pode expor caso de borda não previsto em fixture (como o `NaN` da Fase 1); o caminho é corrigir a spec antes do código, nunca ajustar número.

**Commit**
`chore: run 20-asset backtest vs 1/N benchmark and commit honest result` — por quê: o objetivo da fase é medir sem mentir; o resultado pode ser derrota e é reportado como tal (DoD).

---

## Encerramento da fase

Só marcar quando todas as tarefas estiverem ✅.

- [ ] Todos os RFs da v0.2 têm ao menos uma tarefa que os cobre (tabela RF → tarefa)
- [ ] Todos os critérios de aceitação citados têm teste correspondente nomeado
- [ ] `make check` verde (lint + mypy --strict + testes com cobertura ≥ 85%)
- [ ] Definition of Done do `fase-2a-requirements.md` §10 integralmente satisfeita
- [ ] `specs/README.md` e `specs/CHANGELOG.md` atualizados

## Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.1 | 2026-08-14 | Rascunho inicial — gate 3. 18 tarefas em 8 blocos ordenados por dependência (folhas → calendário → broker → portfolio → laço → analytics → harness/CI → E2E), cada uma com RFs/CA, arquivos, testes nomeados do design §10/§10.1, comandos exatos do Makefile e mensagem de commit com o porquê. |
| 0.1 (emenda do gate 3) | 2026-08-14 | Checklist do gate 3: T11 dividida em T11a (laço calendário-driven) e T11b (mark-to-market + interação de caixa) para caber em commits revisáveis — sem mudança na tabela RF → tarefa. Status aprovada (gate 3 fechado). |
