# ADR-0005 — Execução condicional e fronteira de mutação (ENG-01.2 em duas partes)

**Status:** aceito
**Data:** 2026-08-14
**Contexto de decisão:** Fase 2a — engine

## Contexto

O teste de ENG-01.2 da Fase 1 prova a invariante anti-lookahead mutando arbitrariamente as barras posteriores à última decisão e verificando que o conjunto de trades não muda. Ele foi escrito para o mundo single-asset com ordens a mercado, executadas no `open` do pregão seguinte (ADR-0002).

A Fase 2a introduz dois elementos que o teste da Fase 1 não cobre:

1. **Ordens condicionais** (limite e stop, incluindo bracket — RF-SIG-01). A intenção emitida pela estratégia agora carrega preços de limite/stop que são parte da decisão. Uma mutação de barras futuras pode alterar o preço de limite/stop que a estratégia emite — e isso é lookahead de decisão.
2. **Ordens pendentes entre barras do mesmo ativo.** Com o calendário-união (RF-POR-02/RF-POR-05), uma ordem decidida na barra `i` de X executa no `open[i+1]` de X — potencialmente várias datas-união depois. A fila de pendentes é um vetor de lookahead novo: uma execução que não se vincula a uma ordem preexistente (com data de decisão anterior à barra de execução) seria lookahead de execução pela fila, o mesmo problema que ADR-0002 previne via a barra.

Além disso, a fronteira de mutação muda de natureza: com N ativos, mutar o futuro do ativo X não pode alterar as decisões nem as execuções de X **nem de nenhum outro ativo** (RF-POR-05 CA-05.4).

## Decisão

O ENG-01.2 é reformulado em duas partes independentes, e a fronteira de mutação é por ativo:

- **Parte 1 (decisão):** mutação de barras futuras não altera a **intenção** emitida pela estratégia — sinais e preços de limite/stop.
- **Parte 2 (execução):** toda execução originada por limite/stop **vincula-se a uma ordem preexistente**, confirmada via `decision_date` gravado no Trade anterior à barra de execução.
- **Fronteira:** mutar barras futuras do ativo X não altera intenções nem execuções de X nem de qualquer outro ativo (POR-05.4).

Wording do DoD (requisitos v0.2, literal): "Teste de mutação anti-lookahead (ENG-01.2) reformulado para ordens condicionais e passado: mutação de barras futuras não altera a intenção emitida pela estratégia (sinais e preços de limite/stop); e toda execução originada por limite/stop vincula-se a uma ordem preexistente, confirmada via `decision_date` gravado no Trade anterior à barra de execução."

## Justificativa

- **As duas partes são modos de falha independentes.** A parte 1 pega lookahead de decisão (a estratégia vendo futuro e emitindo limite/stop diferente); a parte 2 pega lookahead de execução (a fila de pendentes executando a preço que a decisão original não conhecia). Um único teste não discrimina qual das duas quebrou.
- **`decision_date` já existe.** O campo nasce em `PendingOrder` (design Fase 1 §4.5, `entry_decision_date`/`exit_decision_date`) e é promovido ao `Trade` (RF-ORD-04 CA-04.4) — a parte 2 é auditoria, não invenção de dado novo.
- **Fronteira por ativo é consequência do desenho, não imposição:** a estratégia de X só vê o array de X (instância por ativo, POR-03.1) e o acoplamento entre ativos é só via caixa (execução), nunca via decisão. O teste confirma o desenho — mesmo papel do ENG-01.2 na Fase 1.
- **Cara de reverter:** altera o critério de aceitação da fase anterior (o teste que prova a invariante central). Por isso vira ADR, não parágrafo de design.

## Alternativas descartadas

**Manter o teste da Fase 1 inalterado e somar um teste novo para condicionais.** Preserva o passado intacto e é o caminho de menor atrito. Descartada porque o teste antigo, com ordens a mercado single-asset, deixaria de ser o critério da fase: ele não cobriria ordens condicionais nem a fronteira por ativo, e o repositório ficaria com dois "critérios de aceitação" com pesos ambíguos. Voltaria a ser a resposta certa se a Fase 2a tivesse mantido ordens a mercado — não foi o caso.

**Reformular em uma parte só (apenas mutação de intenções).** Mais simples e suficiente para lookahead de decisão. Descartada porque deixa a execução condicional sem auditoria: uma ordem de stop que executasse sem vínculo a ordem preexistente (ex.: preço de gatilho recalculado na execução) passaria no teste.

**Só emendar no design, sem ADR.** Menos burocracia e o texto da emenda seria idêntico. Descartada porque esconde que a semântica do invariante de teste da Fase 1 mudou — exatamente o tipo de decisão que o ADR existe para registrar; a mudança afeta o critério de aceitação de uma fase já aprovada.

## Consequências

- O teste da Fase 1 (`test_eng_012_...` original, ordens a mercado) é **substituído** pelo par de testes das partes 1 e 2 — não convive com eles como critério duplicado.
- `Trade` ganha `origin` (market | limit | stop) e `decision_date` auditable (RF-ORD-04 CA-04.4) — o relatório pode reconstruir a cadeia decisão → ordem → execução.
- O DoD do requirements v0.2 usa o wording literal desta decisão.
- Toda refatoração do laço multi-ativo que inverta executar-antes-de-consultar derruba a parte 1; toda mudança no ciclo de vida de pendentes que solte execução sem `decision_date` anterior derruba a parte 2.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| Mutação de barras futuras não altera intenção (sinais e preços de limite/stop) | `test_eng_012_mutation_does_not_change_conditional_intent` |
| Execução de limite/stop vincula-se a ordem preexistente via `decision_date` anterior à barra de execução | `test_eng_012_execution_binds_to_order_via_decision_date` |
| Fronteira de mutação por ativo (POR-05.4) | `test_mutation_frontier_is_per_asset` |

## Revisitar quando

A Fase 2b introduzir entradas condicionais de compra (buy-stop): a fronteira de mutação precisa ser reauditada para o novo tipo de ordem, e a parte 2 ganha um caso novo (ordem condicional de entrada nunca exercitada). Gatilho: início do design da 2b.
