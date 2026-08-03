# ADR-0001 — MongoDB como banco primário, em vez de relacional ou colunar

**Status:** aceito
**Data:** 2026-08-03
**Contexto de decisão:** Fase 1 — persistência

## Contexto

O sistema precisa persistir três classes de dados com perfis muito diferentes:

1. **Séries OHLCV** — schema rígido, append-only, alto volume, consultadas por `(ticker, intervalo de datas)`.
2. **Eventos corporativos** — baixo volume, schema simples, mas revisados retroativamente pelo provedor.
3. **Resultados de backtest** — schema irregular por natureza: cada estratégia tem parâmetros próprios, cada execução tem um conjunto diferente de trades, métricas e metadados.

## Decisão

MongoDB como banco primário para as três classes, com índice composto `(ticker, date)` na coleção de barras.

## Justificativa

A escolha é **deliberadamente não-ótima para o item 1** e ótima para o item 3.

Séries OHLCV são o caso de uso canônico de banco relacional ou colunar. Schema fixo, imutável, consultado por range — é exatamente o que TimescaleDB, DuckDB ou Parquet fazem melhor que Mongo, com melhor compressão e melhor performance de agregação.

O que inclina a decisão:

- **Resultados de backtest são heterogêneos.** Cada estratégia introduz parâmetros novos. Em modelo relacional isso vira ou uma tabela com dezenas de colunas nuláveis, ou uma tabela chave-valor, ou migração a cada estratégia nova. Em documento, é o formato natural.
- **Eventos corporativos são revisados retroativamente.** Upsert em documento é mais direto que reconciliação relacional.
- **Volume da fase não estressa nenhuma opção.** 20 tickers × 10 anos ≈ 50 mil documentos. Qualquer banco resolve. A vantagem de performance do colunar só apareceria uma ordem de grandeza acima.
- **Objetivo de portfólio.** A vaga-alvo cita MongoDB explicitamente. Demonstrar competência na ferramenta pedida tem valor direto.

## Alternativas descartadas

**PostgreSQL / TimescaleDB.** Tecnicamente superior para séries temporais: compressão nativa, hypertables, agregações contínuas, e garantias transacionais mais fortes. Descartado por não resolver bem o item 3 sem `jsonb`, e por não ser a ferramenta pedida no alvo. Continua sendo a resposta correta caso o projeto evolua para volume de intraday.

**Parquet + DuckDB.** Provavelmente a melhor escolha técnica pura para este volume e este acesso: custo zero, sem servidor, performance analítica excelente. Descartado porque não persiste bem o item 3 e porque um projeto sem banco servido perde a demonstração de modelagem e indexação — que é justamente o que se quer mostrar.

**Híbrido (Parquet para séries, Mongo para o resto).** Tecnicamente defensável, e o desenho que provavelmente se adotaria em produção. Descartado na Fase 1 por dobrar a superfície operacional antes de existir um engine funcionando. Reavaliar na Fase 2 se performance virar restrição real.

## Consequências

- Agregações analíticas complexas sobre séries serão mais trabalhosas do que em SQL. Mitigado por carregar em DataFrame e agregar em Pandas.
- Não há garantia de schema no banco. Mitigado por validação na fronteira da aplicação (RF-ING-05) e por schema validation do Mongo na coleção de barras.
- O índice composto `(ticker, date)` cobre o padrão de acesso dominante. Índices separados em `ticker` e `date` seriam piores: o composto atende consultas por `ticker` sozinho pelo prefixo, e o índice isolado em `date` teria seletividade baixa.
- A camada de repositório deve isolar o resto do sistema do driver, de modo que uma troca futura de backend não vaze para o engine.

## Nota para defesa em entrevista

A resposta honesta não é "Mongo é melhor para séries temporais" — é falsa. A resposta é: o volume não discrimina as opções, os resultados de backtest são heterogêneos e pesaram na escolha, e o trade-off contra TimescaleDB e Parquet está documentado aqui.
