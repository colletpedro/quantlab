# Changelog das specs

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versionamento por spec, não global.

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
