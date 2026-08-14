# Changelog das specs

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versionamento por spec, não global.

## 2026-08-14

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
