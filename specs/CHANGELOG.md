# Changelog das specs

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versionamento por spec, não global.

## 2026-08-16

### fase-2b-tasks 0.1 (T13) — Fase 2b implementada

**T13 concluída — o DoD v0.2 está coberto ponta a ponta (T01–T13).**

Run long+short real de 20 ativos × ~10 anos contra o 1/N long-only e contra a
própria estratégia em modo long-only, persistido em
`results/fase_2b_run_20_ativos_long_short.json`: conciliação CA-04.2 fechando
(isclose 1e-9) com `qty < 0` e borrow fees no termo próprio, determinismo
(RNF-01) OK, RNF-04 1,33 s < 30 s. **Resultado honesto: derrota completa do
lado curto** — +6,83% acumulado (0,57% CAGR) vs +217,93% (10,50% CAGR) da
mesma estratégia long-only vs +2.509,09% (32,50% CAGR) do 1/N buy-and-hold;
111 margin calls, USD 2.086,89 de borrow fees, 5 shorts travados.

**Dois casos de borda do caminho short expostos pelo dado real e corrigidos
spec-first (emenda T13 no design §4, sem reabrir o gate 2):** (1) o registro
da equity de `u` passou a acontecer **após** o débito do borrow fee do close —
antes, um short aberto até a última barra deixava o último ponto da curva sem
o fee do último dia e a identidade de §6 abria exatamente nesse valor;
(2) o `EXIT` sobre short (Q2) passou a cobrar custo sobre **|notional|** —
antes, `cost_for` com notional negativo subcobrava e zerava o custo de saída
com `min_cost = 0`. Fixes com testes nomeados novos
(`test_reconciliation_closes_with_short_open_through_last_bar`,
`test_exit_sell_on_short_charges_cost_on_absolute_notional`) e o teste
hermético do E2E (`tests/integration/test_e2e_2b_long_short.py`).

Novos: `strategies/sma_cross_long_short.py`, `scripts/e2e_run_2b.py`,
`tests/integration/test_e2e_2b_long_short.py`, `results/fase_2b_run_20_ativos_long_short.json`.

## 2026-08-14

### fase-2b-tasks 0.1 — em revisão (gate 3)

Plano de tarefas da Fase 2b produzido no formato da 2a: **16 tarefas em 6 blocos** ordenados por dependência (contratos → broker → laço → analytics → walk-forward → E2E), cada uma com RFs/CA, arquivos, testes nomeados do design §10/§10.1, comandos exatos do Makefile (`make test-unit && make typecheck && make check`), critério de verificação objetivo e mensagem de commit com o porquê.

**Divisão validada pelo tech lead do web** — T08 dividida em T08a (fechamento: fee → margem → plano MARGIN_CALL → fundo quebrado) e T08b (abertura/bordas: executa liquidação, contadores, short deslistado); T11 em T11a (run_walkforward + orçamento) e T11b (mutação ENG-01.2 estendida, teste puro); T12b (harness RNF-04 do WF) separada de T12. Tabela RF → tarefa NÃO muda com re-splits (lição da 2a/T11).

**Regressões documentadas** — T06 remove a barreira P2 da 2a no `convert` (buy-stop vira kind válido; `test_convert_domain_errors_raise_engine_error` perde o bloco do buy-stop); T01 aceita `Position(quantity < 0)` (ADR-0009; `== 0` continua inválido).

**Mapeamentos completos** — tabela RF → tarefa (21 RFs novos + RF-CON-01/02/03 marcados como herança da Fase 1/2a, sem tarefa nova), DoD v0.2 → tarefa (cada item do DoD aponta a tarefa que o satisfaz; ADRs 0009–0011 já entregues no gate 2) e nota sobre a ordem de build (folha antes de consumidor; broker antes do laço; analytics/WF depois do engine estável).

### fase-2b-design 0.1 — em revisão (gate 2)

Design técnico v0.1 da Fase 2b produzido no template da 2a (§1–§11) + ADRs **0009–0011 propostos**.

**Estrutura** — §1 princípio organizador com portador de garantia por RF (construção × teste nomeado); §2 arquitetura (módulos novos `engine/margin.py` e `engine/walkforward.py`, WF como caixa preta sobre `run_backtest_multi` — herança por construção, filosofia do benchmark 1/N da T15); §3 contratos COMPLETOS (Signal com `ENTER_SHORT`/`EXIT_SHORT`; Position/Trade com `qty < 0` e `origin = MARGIN_CALL`; MarginModel/MarginCallOrder/BrokenFundState; BorrowFeeModel; Fold/ParameterGrid/WalkForwardResult; MechanismCounters +margin_calls/borrow_rejections; BacktestResultMulti +broken_fund/borrow_fees); §4 fluxo da barra 2b com sequência declarada como invariante (executar → marcar → fee → margem → consultar) e pior caso intrabarra estendido aos brackets com buy-stop; §5 bordas (short deslistado, ex-dividendo); §6 identidade CA-04.2 com `total_borrow_fees`; §7 analytics gross/net + MHT + fundo quebrado com `None` explícito; §9 fora do escopo; §10 os **54 CAs mapeados 1:1** (55 testes — CA-03.4 tem dois lados).

**Checklist anti-lacuna (lição da 2a)** — 1) todo tipo citado no §3 tem bloco próprio com campos/tipos/defaults (nenhum `BarSlice`/`PendingOrder`/`CutStage` só referenciado); 2) toda assinatura completa (parâmetros + retorno + pré/pós em §3.8); 3) imutabilidade/pureza declarada (quem muta: laço/broker/portfolio; quem só lê: margin_requirement, margin_utilization, daily_fee, build_folds, run_walkforward); 4) dono de cada agregação declarado (margin_calls/ambiguidades derivados dos trades pelo laço; borrow_rejections contado no convert; borrow_fees acumulado no laço; relatório só reporta); 5) datas naive, zero datetime/timezone nos módulos novos.

**Emenda spec-first no requirements v0.2 §8** — a missão do gate 2 reagrupa os ADRs: **D1+D2 → ADR-0009** (margem + liquidação + fundo quebrado; a spec tinha D2 → ADR-0010), **fee de aluguel (RF-SHT-03/D3) → ADR-0010**, **D6+D7 → ADR-0011**. Tabela §8 atualizada para não divergir (D1/D2 → 0009; D3 → contrato + 0010; D6/D7 → 0011).

**ADR-0009** — invariante de margem (`equity ≥ Σ|qty|×close×factor`, factor default 1.0, regressão long-only = cash ≥ 0) + liquidação forçada determinística (close detecta → open executa, alfabética, integral por ativo, cancela pendentes, `origin = MARGIN_CALL`) + fundo quebrado congelado com métricas `None` explícito (nunca NaN).

**ADR-0010** — modelo de aluguel: fee diário `|qty| × close × 0,005/252` no close, categoria própria, termo próprio na conciliação; disponibilidade ilimitada default (R1) com restrição configurável (bloqueia short, loga e conta); viés não calibrado declarado.

**ADR-0011** — protocolo walk-forward: isolamento estrito IS/OOS por construção (série truncada, guard no array); warmup do OOS pela cauda do IS (R4); seleção = Sharpe anualizado rf=0 (R5); rolling default (D7/R7) com anchored configurável; mutação ENG-01.2 estendida ao OOS (mutar OOS não altera params IS); WF como caixa preta; orçamento por fold + total (RNF-10).

### fase-2b-design 0.1 — emenda P1 (verificação do gate 2)

Rodada de verificação P1 antes do fechamento do gate 2 (5 itens, todos resolvidos como emenda da própria v0.1 — gate 1 NÃO reaberto):

- **P1.1 — buy-stop × ENG-05:** regra de ativação por side explícita em tabela (§3.5/§3.8/§4 passo 1b) — sem posição ⇒ entrada long; LONG aberta ⇒ guard ENG-05 ignora e **consome** (log); SHORT aberta ⇒ cobertura do stop-loss (reduz \|qty\|, nunca cruza). Sell-stop espelhado: ativa só com LONG (2a ORD-02.2 estendido).
- **P1.2 — barreira P2 da 2a removida:** `convert` passa a aceitar `OrderKind.STOP` (buy-stop) como kind de entrada; o teste 2a `test_convert_domain_errors_raise_engine_error` perde o bloco do buy-stop (regressão esperada e documentada); teste novo `test_convert_accepts_buy_stop`.
- **P1.3 — warmup do OOS:** mecanismo explicitado em `run_walkforward` — cauda do IS entra como histórico puro (gate i ≥ warmup com len(cauda) = warmup ⇒ primeira barra consultada é o primeiro bar OOS; a estratégia nunca trade a cauda); `oos_equity = equity_curve[tail_len:]`; pré-condição `strategy.warmup == warmup`.
- **P1.4 — Sharpe com fonte única:** `sharpe_annualized_rf0` em `engine/walkforward.py` é a ÚNICA implementação; o `sharpe()` da Fase 1/2a em `analytics/metrics.py` (relatório) passa a delegar — zero drift entre seleção IS e relatório.
- **P1.5 — fundo quebrado por gap:** cronologia explícita no §4 — (1) liquida no open do gap → (2) constata equity < 0 → (3) congela (flag, sem trades novos) → (4) métricas None (nunca NaN) com conciliação fechando.

§10 atualizado: **58 testes nomeados para 54 CAs** (+3: guard ENG-05 do buy-stop nos dois lados e convert aceita buy-stop).

### fase-2b-design 0.1 — aprovada (gate 2 fechado)

Checklist final do gate 2 (CONTRIBUTING.md) executado item a item em 2026-08-14, validado pelo tech lead do web:

- **Anti-lacuna 1–5** confirmado no texto real: (1) zero tipo referenciado sem definição (todo tipo do §3 tem bloco próprio com campos/tipos/defaults); (2) zero assinatura incompleta (params de `execute_margin_calls`, `execute_pending` 2b, `build_folds`, `run_walkforward`, `sharpe_annualized_rf0` existem no §3 e são usados no §4); (3) imutabilidade/pureza com dono de mutação declarado (§3.3 "Quem muta, quem lê"); (4) agregações com dono (§3.7 — `margin_calls`/`intrabar_ambiguities` derivadas pelo laço; `borrow_rejections` contado no `convert`; `borrow_fees` acumulado no laço); (5) datas naive (RNF-07, §3.9).
- **§3.8** completa: os DOIS stops com ativação por side (emenda P1); pré/pós de margem, borrow fee, folds e WF em `EngineError`; fronteira de instante §3.9.
- **§10** com os **58 testes nomeados** mapeando os **54 CAs** (CA-03.4 nos dois lados; os 3 testes novos da P1 na tabela).
- **§9** fora do escopo declarado e vazio de pendências.
- **D1–D7** cada decisão comprometida com ADR (0009/0010/0011), sem divergência com a tabela §8 da spec v0.2 — a emenda P1 não reabriu o gate 1 (numeração conferida: D1/D2 → 0009; D3 → contrato + fee → 0010; D4/D5 → fórmulas/ADR-0007 estendido; D6/D7 → 0011).

**ADR-0009 a ADR-0011 — aceitos** (promovidos de propostos a aceitos na aprovação formal do gate 2; cada ADR cita invariantes + testes nomeados e a condição "revisitar quando"; ADR-0011 teve o mecanismo do warmup OOS alinhado à precisão da emenda P1 do design §3.6).

Veredito: **Gate 2 APROVADO — design v0.1 da Fase 2b e ADRs 0009–0011 aceitos. Gate 3 (tarefas → implementação) pode abrir.**

### fase-2b-requirements 0.2 — gate 1 aprovado

Gate 1 da Fase 2b declarado **APROVADO** após checklist validado pelo tech lead do web.

**Checklist (CONTRIBUTING.md)** — (a) todos os **54 CAs** da v0.2 são falseáveis, com teste nomeado por CA (tabela RF × CA × teste no formato de saída do gate 1; atenção aos novos: CA-03.4 aluguel nos dois lados, CA-04.3 short × dividendo em forma fechada, CA-01.5 margin_factor 1.0 exato, CA-02.3 métrica de seleção IS no MHT); (b) seção de questões abertas vazia (Q1–Q6 fechadas em D1–D7); (c) premissas e vieses declarados (aluguel ilimitado + configurável, long-only revogado, sem fracionário, moeda única, vieses de RF-MET-06).

**Correção de contagem** — o total real de CAs é 54 (v0.1: 50; v0.2: +4 de R1/R2/R3/R5); o número "30" citado no checklist era contagem incorreta e foi corrigido no registro.

Gate 2 (design v0.1 + ADRs 0009–0011) pode abrir.

### fase-2b-requirements 0.2 — em revisão

v0.1 revisada pelo tech lead do web; resoluções **R1–R7** aplicadas e promovida de draft para em revisão.

**R1 (RF-SHT/RF-MET-06)** — viés declarado "disponibilidade de aluguel ilimitada (otimista; sem hard-to-borrow)" na seção de vieses; restrição configurável com default ilimitado (RF-SHT-03 CA-03.4: short de ativo indisponível não executa e é logado/contado).

**R2 (RF-SHT-04)** — CA-04.3 novo: PnL de posição short atravessando data ex-dividendo ≡ retorno do preço ajustado (consistência do modelo de ajuste para shorts).

**R3 (RF-MRG-01)** — fator único de margem declarado como simplificação; alternativa de dois níveis (long × short) documentada como descartada (§8.1); default 1.0 explícito e configurável (CA-01.5).

**R4 (RF-WFK-01)** — warmup do OOS pela cauda do IS (dados ≤ fronteira, sem lookahead; CA-01.3); alternativa de descartar as primeiras barras do OOS descartada.

**R5 (RF-WFK-02/RF-MET-06)** — métrica de seleção IS declarada: Sharpe anualizado com rf=0 (CA-02.3), incluída no viés MHT com grid size × folds.

**R6 (RF-MRG-03)** — fundo quebrado: métricas = `None` explícito + flag no relatório, nunca NaN (lição do ING-05.1; CA-03.2).

**R7 (Q6/D7)** — ancoragem dos folds FECHADA pelo autor: rolling (janela IS fixa) como default, anchored configurável para medir a diferença; registrada na tabela de decisões §8 (D7).

§9 Questões em aberto agora **vazia** (Q1–Q5 fechadas na v0.1; Q6 fechada na v0.2).

### fase-2b-requirements 0.1 — draft (em revisão)

Abertura da Fase 2b: spec de requisitos v0.1 em draft, aguardando revisão do tech lead do web e do autor (gate 1).

**Escopo** — venda a descoberto + aluguel (borrow fee); margem (substitui o invariante RF-POR-04 CA-04.3 da 2a por `equity ≥ margem exigida`); buy-stop (adiado da 2a, P2); walk-forward (IS/OOS). Fora: opções, fracionário, múltiplas moedas, imposto, high-frequency.

**Decisões da v0.1 (D1–D6)** — D1 invariante de margem (exige ADR-0009); D2 liquidação forçada determinística (integral por ativo, alfabética, `origin = MARGIN_CALL`, fundo quebrado congelado e reportado); D3 direção no `Signal` (`ENTER_SHORT`/`EXIT_SHORT`, retrocompatível; sizer nunca decide direção); D4 exposição gross/net e turnover com shorts; D5 buy-stop a `max(S, open)` com slippage + pior caso em brackets com buy-stop; D6 walk-forward com grade determinística IS, isolamento estrito IS/OOS e resultado = concatenação OOS.

**Famílias de RFs** — RF-SHT (01–05: contrato, execução, borrow fee, PnL algébrico, deslistagem short); RF-MRG (01–04: margem, liquidação, fundo quebrado, gross/net); RF-ORD-05/06 (buy-stop e ambiguidades, estendem a 2a); RF-WFK (01–05: folds, otimização, concatenação OOS, mutação, orçamento); RF-MET-05/06 (benchmark long-only + vieses MHT/aluguel); RF-RNF-02 (herança e cobertura estendida).

**Questões em aberto (Q1–Q6)** — Q1–Q5 com proposta fechada na v0.1 (confirmar no gate 1); Q6 (ancoragem dos folds: rolling vs anchored) escalada ao autor.

### fase-2a-requirements 0.2 — em revisão

Promovida de 0.1 (draft) para 0.2 (em revisão) após o gate check 1: parecer P2 validado pelo tech lead do web e pendências P1–P6 aprovadas pelo autor do projeto. Reservas R1–R2 incorporadas.

**Decisões fechadas** — Q1–Q5 resolvidas como D1–D5: `1/N` com N do run fixado no início (N=1 ⇒ all-in = D1); limite cancela ao fim da barra (persistência fora da 2a); ADV de 20 pregões do próprio ativo; cap de 10% do ADV só em entradas, saída integral, corte < 1 ação ⇒ sem ordem; atendimento alfabético com contagem de não-atendidas no relatório.

**Requisitos adicionados** — RF-SIG-01 (contrato `ConditionalStrategy`, bracket na mesma intenção, retrocompatível); RF-ORD-04 (ciclo de vida de ordens: sem reserva de caixa, EXIT cancela todas as pendentes do ativo, última intenção vence, `decision_date` no Trade); RF-SLP-04 (separação corte × slippage de preço; limite nunca violado); RF-SIZ-04 (contrato do sizer; fração; invariante k ≤ N); RF-POR-05 (índice por ativo, ADR-0002 por ativo, fronteira de mutação por ativo); RF-MET-04 (fórmulas de turnover/exposição/patrimônio médio); RF-MET-05 (contadores de mecanismo: stops, ambiguidades, não-atendidas); RF-RNF-01 (cláusula de herança de RNFs).

**Critérios e emendas** — RF-SIZ-02 (N do run determinístico, mesmo N no benchmark, ativo sem barra conta no N e contribui zero — R2); RF-SIZ-03 (rebalance só por mudança de k, limiar em pp absolutos, ADR-0002 — S4); RF-ORD-01 (Q2); RF-ORD-02 (sell-stop protetor long-only — P2); RF-ORD-03 (coerente com bracket — S1); RF-SLP-03 (Q3/Q4); RF-POR-01 (Q5); RF-CST-01 (sequência fixa de redução — R1); RF-MET-01/02/03 (fórmulas P4, benchmark por ativo — S6, vieses novos).

**Não funcionais** — RNF-02 supersedido para 85% cobrindo `engine/`, `analytics/` e módulos novos (S7); RNF-04 (30 s) passa a medir só o cômputo, relatório e gráfico fora (P5); RNF-07/08 herdados da Fase 1; RNF-09 novo (invariantes sem ADR).

**Outros** — §7 vira baseline verificado (S8, design v0.9 / STATE.md 2026-08-06), não escopo novo; DoD reformulado com o wording literal do ENG-01.2 (P1), a medição do RNF-04 (P5) e a conciliação CA-04.2 no run de 20 ativos; premissas atualizadas (P2; rf=0 e dividendos via ajuste herdados da Fase 1).

### fase-2a-requirements 0.2 — gate 1 aprovado (com ressalva)

Gate check 1 da Fase 2a declarado **APROVADO COM RESSALVA** após revisão independente do tech lead do web; a ressalva foi resolvida no mesmo commit, sem mudança de semântica.

**Ajuste de redação (ressalva)** — RF-SLP-01 CA-01.1 ganhou cross-reference explícito ao RF-SLP-04 (slippage de preço só em ordens a mercado; limite nunca violado), eliminando a contradição textual entre os dois RFs.

**Checklist do gate 1 (CONTRIBUTING.md)** — (a) todo CA falseável, com teste nomeado por RF — incluídos os dois que faltavam: RF-ORD-04 CA-04.3 (segunda entrada na mesma barra vê o caixa já debitado pela primeira, em ordem alfabética — RF-POR-01 CA-01.2) e RF-SIZ-02 CA-02.2 (1 sinal ativo de 20: relatório expõe o caixa ocioso e nenhum trade de realocação é gerado); (b) seção de questões abertas vazia; (c) premissas e vieses declarados.

Gate 2 (design) pode abrir.

### fase-2a-design 0.1 — em revisão (gate 2)

Rascunho inicial do design técnico da Fase 2a, a partir do esboço aprovado na revisão conjunta com as decisões D1–D4 e correções C1–C2.

**Decisões incorporadas** — D1: calendário-união com arrays `bar_index`/`last_known` pré-computados e imutáveis, merge em uma passada O(total), sem ponteiros mutáveis; guard de complexidade vira teste de propriedade. D2: pior caso intrabarra para todos os brackets — entrada abre em L e fecha no stop S na mesma barra (perda L − S + custos, flat) e saída preenche no stop; ambos com `ambiguous=True` e contados em `MechanismCounters`. D3: módulos novos dentro de `engine/` (calendar/liquidity/slippage/sizing/conditional), RNF-02 segue `engine/` + `analytics/` ≥ 85%; harness do RNF-04 = `get_series×N` + run + `buy_and_hold_multi` + `report.build()`, excluindo ingestão e PNG, escopo declarado na spec. D4: ADRs 0005–0008 escritos no formato da casa (propostos, viram aceitos na aprovação do gate 2).

**Correções incorporadas** — C1: ENG-01.4 por ativo reafirmado no fluxo da barra (intenção na última barra da série de X morre pendente e é reportada). C2: ADR-0006 crava a forma funcional `slippage_bps = bps × (1 + k × q/ADV)`, linear até o cap — monotonicidade é CA (SLP-03.1), não função; fecha o gate 3.

**Estrutura do documento** — princípio organizador, arquitetura, contratos tipados (UnionCalendar, ConditionalIntent, PendingOrder, Trade, SlippageModel, Sizer, Broker, Portfolio), fluxo da barra multi-ativo (§4.3 estendido), calendário-união (algoritmo e complexidade), conciliação estendida, analytics/benchmark/relatório, fronteira de instante (§3.6 estendido), riscos, decisões com alternativas descartadas, testes nomeados por invariante (gate 2).

### ADR-0005 a ADR-0008 — propostos

Execução condicional e fronteira de mutação (ENG-01.2 em duas partes); modelo de slippage (forma funcional cravada); resolução da ambiguidade intrabarra (pior caso); política de sizing default (1/N). Decisões fechadas na revisão conjunta do esboço; status proposto até a aprovação formal do gate 2 (design), quando passam a aceitos.

### fase-2a-design 0.1 — aprovada (gate 2 fechado)

Checklist do gate 2 (CONTRIBUTING.md) executado item a item em 2026-08-14. Pendências identificadas no checklist foram resolvidas como emenda da própria v0.1 (mesma versão, antes da aprovação):

- **Item 1 (interfaces tipadas + contrato)** — adicionada a §3.8 com pré/pós-condições por interface (UnionCalendar; ConditionalStrategy/ConditionalIntent/Bracket; SlippageModel/FixedBps/Participation; adv/participation_cap; Sizer/FixedOneOverN/EqualWeightOpen; Broker/PendingOrder; Portfolio/Trade; MechanismCounters; buy_and_hold_multi; funções de RF-MET-04).
- **Item 2 (testes nomeados)** — adicionados 17 testes nomeados complementares (§10.1) fechando a cobertura RF × teste dos 25 RFs novos; antes, RF-SLP-01/02, SLP-03 (janela), SLP-04 (custos), ORD-01 (preenchimento), ORD-02 (gatilho), SIG-01, SIZ-01, SIZ-03 (limiar/contagem), POR-01 (atendimento), POR-02 (MarketView), POR-03, MET-01 e RNF-02 ficavam sem teste nomeado direto.
- **Item 3 (ADRs)** — ADR-0006 ganhou default determinístico `k = 1.0` (configurável) na Decisão: dois runs com a mesma configuração produzem o mesmo número (RNF-01), fechando o gate 3.
- **Item 4 (construção vs teste)** — adicionada tabela RF × garantia no §1: nenhum RF sem portador de garantia explícito.
- **Itens 5 e 6 (fronteira de instante e harness do RNF-04)** — confirmados sem mudança: §3.7 e §7 já declaravam; escopo do harness casa com RF-RNF-01 CA-01.3.

Veredito: **Gate 2 APROVADO — design v0.1 e ADRs 0005–0008 aceitos. Gate 3 (tarefas → implementação) pode abrir.**

### ADR-0005 a ADR-0008 — aceitos

Promovidos de propostos a aceitos na aprovação formal do gate 2 (design), em 2026-08-14.

### fase-2a-tasks 0.1 — em revisão (gate 3)

Plano de tarefas da Fase 2a em 18 tarefas (T01–T18) e 8 blocos ordenados por dependência: folhas puras (contracts condicionais, liquidez, slippage, sizing), calendário-união imutável (D1), broker (conversão/ciclo de vida/execução/pior caso intrabarra), portfolio multi-ativo, laço sobre o calendário-união, ENG-01.2 reformulado em duas partes (ADR-0005), analytics (conciliação/métricas/benchmark/relatório), harness RNF-04 + fronteira de instante + cobertura 85% (T17), e run de 20 ativos ponta a ponta com resultado honesto (T18).

Cada tarefa carrega RFs/CA cobertos, arquivos, testes nomeados do design §10/§10.1, comandos exatos (`make test-unit`, `make typecheck`, `make check`, `make test-integration`) e mensagem de commit imperativa com o porquê. RF-CON-01/02/03 permanecem verificação herdada da Fase 1 (S8), sem tarefa nova — a T16 estende a seção "run" do relatório para o multi-ativo.

### fase-2a-tasks 0.1 — aprovada (gate 3 fechado)

Checklist do gate 3 (CONTRIBUTING.md) executado item a item em 2026-08-14, com revisão do tech lead do web: (a) granularidade de commit confirmada, com **T11 dividida em T11a** (laço calendário-driven: executar→marcar→consultar, instâncias, ADR-0002 por ativo, invariantes) **e T11b** (mark-to-market por último close conhecido, deslistagem, atendimento alfabético, sem reserva de caixa) — sem mudança na tabela RF → tarefa; (b) critério de verificação objetivo (testes nomeados do design §10/§10.1 + comandos do Makefile) em todas as tarefas; (c) ordem de dependência confirmada (T06≥T02,T04; T08≥T03; T11≥T05,T09,T10; T13–T16≥T11; T17≥T16; T18≥T17); (d) os 25 RFs novos cobertos, RF-CON-01/02/03 herdados sem tarefa nova.

Veredito: **Gate 3 APROVADO — tasks v0.1 aceita. Implementação pode começar commit a commit (gate 4 — checklist de PR — a cada merge).**

### Fase 2a — implementação T01–T18 e E2E (2026-08-14)

Implementação commit a commit (uma tarefa por commit, gate 4 a cada merge): contratos condicionais (T01), liquidez (T02), slippage (T03), sizing (T04), calendário-união (T05), broker (conversão T06, ciclo de vida T07, execução T08, pior caso intrabarra T09), portfolio multi-ativo (T10), laço calendário-driven (T11a) e bordas (T11b), mutação ENG-01.2 em duas partes (T12), conciliação e contribuição (T13), métricas (T14), benchmark 1/N (T15), relatório multi (T16), harness RNF-04 + arquitetura + piso 85% (T17) e E2E (T18). Emendas spec-first ao design 2a e às tasks registradas nos commits `docs` correspondentes.

**E2E do DoD (T18) — resultado honesto e um bug real de dados da Fase 1.** O run real de 20 ativos x ~10 anos (2015-01-02 a 2026-08-05, 2.914 barras de união) revelou **dupla contagem de splits no raw** do pipeline da Fase 1: `YFinanceProvider.fetch_prices` usava `auto_adjust=False`, que no yfinance **ainda aplica splits** ao OHLC, e gravava o resultado em `bars` como se fosse bruto; o ajuste do §3.7 aplicava os splits de novo. Afetados: AAPL, NVDA, GOOGL, AMZN, NEE (splits dentro da janela); sintoma honesto: o benchmark 1/N "comprou" 414.573 ações de NVDA (832x o capital) a preço ajustado de US$ 0,012 (fator 40x aplicado duas vezes). Correção spec-first: emenda do design da Fase 1 (v0.10 — §3.1 define "bruto" como pré-split e cria a guarda permanente de consistência; §3.7 registra o bug e a correção em três partes), back-out dos splits no provider (testes de forma fechada + round-trip com o ajuste do storage), migração determinística de 9.030 barras a partir do próprio `bars` (backup em `/tmp`, idempotente), e `make verify-raw` como guarda executável. Após a correção: **conciliação CA-04.2 fecha (isclose 1e-9)** no run real e o benchmark 1/N retorna +2.509,09% (CAGR 32,50%) vs estratégia sma-cross 20/50 +217,93% (CAGR 10,50%; Sharpe 1,04; maxDD 14,74%; turnover 2,69; exposição 64,22%). Determinismo confirmado em dois runs idênticos; RNF-04 re-medido em 0,73 s (meta < 30 s); resultado persistido em `results/fase_2a_run_20_ativos.json`. Nota de honestidade: 13 tickers reportados como "deslistados" têm a série **truncada pela ingestão** (terminam 2026-07-31; AAPL vai a 2026-08-05) — semântica de POR-02.3 (série terminou antes do fim da união), não deslistagem real de mercado.

### Fechamento da sessão — docs de estado (2026-08-14)

`docs/STATE.md` e o README (seção Resultados) atualizados para o estado da Fase 2a (números finais, bug dos splits, próximo = Fase 2b); lição registrada no `HANDOFF.md` (erro de fator constante × ruído errático — a dupla contagem de splits como o cenário que a sanidade cruzada do ADR-0003 previa, agora guarda executável `make verify-raw`).

### Fase 1 — regeneração dos 20 relatórios sobre a base corrigida (2026-08-14)

Pendência do fechamento resolvida: os 20 relatórios por ticker (SMA 20/50, D5) foram regenerados via CLI sobre a base pós-back-out de splits. Inocuidade confirmada byte a byte: 15 tickers com `series_hash` inalterado e JSON idêntico; 5 afetados (AAPL, NVDA, GOOGL, AMZN, NEE) com hash novo — AAPL também ganhou 3 barras (2026-08-03 a 08-05, re-ingestão de teste do RF-CON-01). **Placar de Sharpe 17/20 → 19/20**: AMZN e GOOGL "venciam" em Sharpe apenas por artefato do split duplicado (B&H inflado); CAGR permaneceu 19/20 (META, único vencedor em ambas). No run corrigido não há trade ≤ 7 dias das datas ex (GOOGL: entrada 4 dias após o split de 07/2022 — sinal real); NVDA 30→29 trades. Efeitos (CAGR estratégia): AAPL 27,08→12,77 (B&H 39,29→22,63); NVDA 96,70→39,28 (B&H 132,40→67,48); GOOGL 14,80→15,59 (B&H 62,73→25,04); AMZN 11,66→11,56 (B&H 64,63→26,50); NEE 18,95→3,75 (B&H 28,59→12,73). README/STATE/HANDOFF atualizados; errata datada adicionada ao RF-CON-03 (baseline §7).

## 2026-08-03

### fase-1-requirements 1.0 — aprovada

Promovida de 0.1 (draft) para 1.0 após gate check 1.

**Decisões fechadas** — Q1–Q5 resolvidas como D1–D5: all-in na entrada, custo default 1 bps + USD 1, retorno a caixa na saída, `Portfolio` modelado para N posições com N=1 em execução, janela default a partir de 2015-01-01.

**Critérios adicionados** — normalização de timezone na ingestão; coleta de eventos corporativos sobre histórico completo; resposta vazia do provedor tratada como falha; detecção de variação extrema sem split registrado; série sem eventos preservada no ajuste; sinal na última barra reportado como pendente; execução sobre gap de pregões; posição aberta ao fim marcada a mercado; invariantes de sinal de caixa e posição; isolamento da estratégia em relação ao estado da carteira; validação `f < s` na SMA cross; Sharpe indefinido com volatilidade zero; aviso de amostra insuficiente; alinhamento do benchmark ao fim do período de aquecimento.

**Não funcionais adicionados** — RNF-07 (datas naive) e RNF-08 (política de ponto flutuante em valores monetários).

**Premissas adicionadas** — moeda única sem conversão cambial; ausência de tributação.

### ADR-0001, ADR-0002, ADR-0003 — aceitos

Banco primário, momento de execução da ordem e estratégia de ajuste por proventos.

## 2026-08-02

### fase-1-requirements 0.1 — draft

Rascunho inicial, com Q1–Q5 em aberto.
