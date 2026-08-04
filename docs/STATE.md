# STATE — mapa do projeto

Este arquivo não existia antes desta sessão (2026-08-04) apesar de o HANDOFF
anterior referenciá-lo como leitura obrigatória. Criado agora, do zero,
refletindo o estado no fim do Bloco D + E. Mantenha-o atualizado a cada
sessão — desatualizado vale menos que ausente.

## Onde estamos

**Fase 1 (MVP): Blocos A, B, C, D e E1-E3 implementados.** Falta o Bloco F
(fechamento): CLI `backtest` + persistência (F1), gráfico (F2), cobertura e
benchmark de performance com código real (F3), README + resultado honesto
(F4).

| Bloco | Escopo | Estado |
|---|---|---|
| A | `storage/` — persistência, ajuste em tempo de leitura | ✅ |
| B | `ingestion/` — coleta, validação, orquestração, CLI `ingest` | ✅ |
| C | `engine/` — `MarketView`, `Strategy`, `Portfolio`, `Broker`, laço de barras | ✅ |
| D | `strategies/` — SMA cross (D1) | ✅ |
| E | `analytics/` — métricas (E1), benchmark (E2), relatório (E3) | ✅ |
| F | CLI `backtest`, gráfico, cobertura/perf, README | ⬜ próximo |

CI: 3 jobs verdes (lint+tipos+testes, integração, auditoria de dependências)
em todo push a `main`. Último run verificado:
[30876286773](https://github.com/colletpedro/quantlab/actions/runs/30876286773).

## Números atuais

- 323 testes totais: 266 unitários (Bloco C) → **310 unitários** depois de D+E,
  57 de integração.
- Cobertura com `make test` (unitários apenas, offline): **97.22%** total.
  - `engine/`: 92-100% por arquivo, nenhum abaixo de 90%.
  - `analytics/`: `metrics.py` 100%, `benchmark.py` 100%, `report.py` 99%.
  - RNF-02 (piso de 80% em `engine/` e `analytics/`) deixou de ser trivial
    pela primeira vez em `analytics/` nesta sessão — folga confortável.

## Invariantes que não são sugestões (ver CLAUDE.md e ADRs)

- **ADR-0002** — execução no `open` do pregão seguinte. Provado por
  `test_mutating_future_bars_does_not_change_trades` (ENG-01.2).
- **ADR-0003** — preço bruto persistido, ajuste em tempo de leitura.
- **ADR-0004** — ajuste materializado sobre o **histórico completo**, depois
  fatiado. Provado por independência de janela
  (`test_two_windows_agree_value_by_value_on_shared_bars`,
  `test_adjusted_values_do_not_depend_on_the_requested_window`). Errata
  datada ao fim do ADR corrige os nomes de teste que a tabela original citava
  errado — corpo do ADR não foi tocado (imutabilidade).
- **ADR-0001** — MongoDB, índice composto `(ticker, date)`.

## O que cada bloco novo entregou

**D1 — SMA cross** (`src/quantlab/strategies/sma_cross.py`). `warmup = slow`
sai de graça do contrato de C2. Validação `fast < slow` na instanciação
(`EngineError`). Fixture de papel com os dois cruzamentos calculados à mão,
incluindo o caso de borda em que o cruzamento de entrada acontece exatamente
na primeira barra elegível (`i = warmup`). Teste ponta a ponta confirma que o
engine roda a estratégia sem alteração nenhuma (ENG-05.1) — se tivesse
exigido, seria sinal de contrato incompleto em C2.

**E1 — métricas** (`src/quantlab/analytics/metrics.py`). Funções puras sobre
`pd.Series`: `sharpe` (`None` nunca `nan` com volatilidade zero ou <2
observações), `max_drawdown` (pico **corrente**, não o do início nem o do
último valor local — `DrawdownResult` com as três datas), `cagr` (dias
corridos entre a primeira e a última data do índice, não contagem de barras),
`hit_rate` (só trades fechados, `None` sem nenhum). Amostra insuficiente
(ANA-01.5) não vive aqui — é responsabilidade do relatório (E3), porque as
funções de métrica precisam continuar puras.

**E2 — benchmark** (`src/quantlab/analytics/benchmark.py`). `buy_and_hold`
reaproveita `BacktestResult`/`EquityPoint` do engine em vez de um tipo
paralelo. Compra ao `open[warmup + 1]`, mesmos custos de entrada. Teste
explícito prova que a janela de equity do benchmark é, barra a barra, o
sufixo `[warmup+1:]` de uma estratégia com o mesmo `warmup`.

**E3 — relatório** (`src/quantlab/analytics/report.py`). `BacktestReport`
com `to_dict()`/`to_json()`/`to_text()`. `BIAS_DISCLOSURE` é tupla literal
com os seis itens de design §5.2 — nenhum caminho de `build()` a omite.
Também cobre, porque o relatório é onde convergem: aviso de custo zerado
(ENG-03.2), aviso de amostra insuficiente (ANA-01.5), tratamento de
dividendo declarado (ENG-04.3), proveniência hash+ingestão (PER-03.1).

## Verificação por mutação (obrigatória em E1 e E2 nesta sessão)

| Módulo | Mutação | Testes que caem |
|---|---|---|
| E1 sharpe | anualizar por √12 em vez de √252 | 3 |
| E1 max_drawdown | medir do início da série em vez do pico corrente | 3 |
| E1 max_drawdown | `>=` → `>` no limiar de recuperação (achado próprio) | 1 (isolado de propósito) |
| E2 benchmark | comprar na barra 0 em vez de `warmup + 1` | 5 de 7 |

Todas restauradas byte a byte, confirmado com `diff`. Nenhuma mutação ficou
sem teste que a derrubasse — diferente do que aconteceu no Bloco C (M1, ordem
2-3 do laço), que é liberdade genuína e está documentada lá.

## Pendências — ambiguidades de spec para a v0.6 (não bloqueiam D/E)

Registradas em HANDOFF.md §6 do Bloco C, avaliadas nesta sessão: nenhuma
bloqueia código já escrito ou a escrever em D/E, porque todas são sobre
decisões *já tomadas* que a documentação ainda não reflete com precisão.

1. **Design §4.3 sugere ordem em três níveis; só duas restrições existem**
   (1-antes-de-2, 1-antes-de-3; a ordem 2-3 é livre). Recomendação: reescrever
   §4.3 para declarar isso explicitamente.
2. **ADR-0004 nomeava testes que não existem** — corrigido nesta sessão via
   errata datada no próprio ADR (commit `1109c7a`). Sem pendência.
3. **Design §4.5 não listava `exit_decision_date`** no struct de `Trade`. Já
   implementado por simetria com `entry_decision_date`. Recomendação:
   atualizar o struct do design.
4. **Design §4.4 não definia o destino de `EXIT` sem posição** no nível do
   laço. Implementado como *consumida* (não fica pendente pra próxima barra,
   porque isso seria lookahead por outro caminho). Recomendação: documentar
   essa escolha em §4.4.

## Próximo passo

**Bloco F — fechamento.** F1 (CLI `backtest` + persistência em
`backtest_runs`) depende só do que já existe: `run_backtest`, `buy_and_hold`,
`BacktestReport.build()`. F2 (gráfico) consome a mesma tripla. F3 vai medir
RNF-04 (10 anos em <5s) pela primeira vez com o pipeline completo, incluindo
a leitura de histórico completo que ADR-0004 introduziu — é o gatilho
concreto de revisitação que o próprio ADR já previu, não suposição.
