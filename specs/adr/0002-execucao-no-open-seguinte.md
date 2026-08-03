# ADR-0002 — Execução no `open` do pregão seguinte ao sinal

**Status:** aceito
**Data:** 2026-08-03
**Contexto de decisão:** Fase 1 — engine

## Contexto

O engine processa barras diárias. Uma estratégia que usa o fechamento de D para decidir precisa de uma regra explícita sobre quando a ordem é executada. A escolha determina se o backtest mede algo real ou se ele mente.

O erro clássico — e o mais comum em backtests de portfólio publicados no GitHub — é calcular o sinal com o `close` de D e executar ao `close` de D. Isso pressupõe conhecer o fechamento antes do fechamento acontecer. O resultado é um backtest que parece excelente e não é reproduzível ao vivo.

## Decisão

Sinal computado com informação até o fechamento de D é executado ao `open` do próximo pregão disponível.

A invariante é reforçada por construção, não por convenção: o engine expõe à estratégia apenas barras de índice ≤ `i` (CA-01.3), e a ordem gerada em `i` só é elegível a partir de `i+1`.

## Justificativa

- **Implementável ao vivo.** Um operador real vê o fechamento, decide durante a noite e envia ordem na abertura. A regra corresponde a um fluxo executável.
- **Falseável.** Existe um teste que prova a invariante: mutar arbitrariamente as barras posteriores à última decisão e verificar que o conjunto de trades não muda (CA-01.2). Se qualquer lookahead entrar no código, esse teste quebra.
- **Conservadora.** O gap de abertura costuma ser desfavorável a estratégias de momentum de curto prazo. Errar para o lado pessimista é preferível.

## Alternativas descartadas

**Execução ao `close` de D.** Lookahead direto. Descartada.

**Execução ao `close` de D+1.** Também implementável ao vivo e igualmente livre de lookahead. Descartada por afastar a execução da decisão em um dia inteiro sem ganho de realismo, e por ser mais difícil de justificar operacionalmente.

**Execução ao VWAP de D+1.** Mais realista para ordens grandes, que são fatiadas ao longo do dia. Descartada porque exige dados intraday que não estão disponíveis na fase, e porque o tamanho de ordem simulado não justifica fatiamento.

**Execução ao ponto médio `(open + close) / 2` de D+1.** Descartada por não corresponder a nenhum mecanismo real de execução. É uma média que ninguém consegue negociar.

## Consequências

- O `open` de D+1 pode divergir muito do `close` de D em gaps. Isso é realismo, não defeito, e a Fase 1 não modela slippage adicional sobre ele.
- Sinal gerado na última barra da série não é executado (CA-01.4), sendo reportado como pendente.
- Em gap de pregões — feriado prolongado, halt —, a execução ocorre na próxima barra existente, qualquer que seja a distância (CA-01.5). O gap é registrado no trade para permitir auditoria.
- A regra assume execução integral ao preço de abertura, sem impacto de mercado. Premissa válida para tamanhos pequenos em ações líquidas; declarada em todo relatório (RF-ANA-03).

## Nota para defesa em entrevista

Vale conhecer o vocabulário: essa escolha define o *decision lag* do sistema. Em fundos reais o lag é medido e às vezes deliberadamente aumentado, para testar se o alpha da estratégia é robusto ou depende de execução instantânea. Um alpha que morre com um dia de atraso raramente sobrevive a custos reais.
