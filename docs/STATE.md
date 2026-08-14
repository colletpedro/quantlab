# STATE — mapa do projeto

Mantenha-o atualizado a cada sessão — desatualizado vale menos que ausente.

## Onde estamos

**Fase 1 (MVP) concluída.** Todos os blocos A-F implementados, testados, e um
resultado honesto rodado contra dado de mercado real e comprometido em
[`results/`](../results/). Definition of Done da fase (requirements.md §8)
integralmente atendido.

**Consolidação pré-Fase 2 concluída (2026-08-06).** §7 de
`specs/fase-2a-requirements.md` — RF-CON-01, RF-CON-02, RF-CON-03. Design
v0.9 (`specs/00-plataforma/fase-1-design.md`) precede o código. Ver
[HANDOFF.md](../HANDOFF.md) §"Consolidação pré-Fase 2" para o detalhe.

**Fase 2a implementada ponta a ponta (2026-08-14, T01–T18).** Gates 1–3
fechados (requirements v0.2, design v0.1, ADRs 0005–0008, tasks v0.1). DoD
da v0.2 coberto: run multi-ativo de 20 ativos × ~10 anos, conciliação
CA-04.2 fechando (isclose 1e-9), ENG-01.2 reformulado testado por mutação
(ADR-0005), RNF-04 0,73 s < 30 s, cobertura 97,84% ≥ 85% (piso novo),
resultado honesto vs benchmark 1/N persistido em
`results/fase_2a_run_20_ativos.json`.

| Bloco | Escopo | Estado |
|---|---|---|
| A | `storage/` — persistência, ajuste em tempo de leitura | ✅ |
| B | `ingestion/` — coleta, validação, orquestração, CLI `ingest` | ✅ |
| C | `engine/` — `MarketView`, `Strategy`, `Portfolio`, `Broker`, laço de barras | ✅ |
| D | `strategies/` — SMA cross (D1) | ✅ |
| E | `analytics/` — métricas (E1), benchmark (E2), relatório (E3) | ✅ |
| F | CLI `backtest` + persistência (F1), gráfico (F2), RNF-04 + cobertura (F3), README + resultado honesto (F4) | ✅ |
| 2a | `engine/` multi-ativo — conditional, liquidity, slippage, sizing, calendar, broker estendido, portfolio multi, laço calendário-driven | ✅ T01–T11 |
| 2a | garantias — mutação ENG-01.2, conciliação multi, benchmark 1/N, relatório multi, harness RNF-04 + piso 85% | ✅ T12–T18 |

CI: 3 jobs verdes em todo push a `main`. Último run verificado:
[30881248393](https://github.com/colletpedro/quantlab/actions/runs/30881248393).

**Próximo:** Fase 2b — short/margem, buy-stop e entradas condicionais
(declarados fora da 2a), walk-forward, analytics de risco. Nenhuma spec de
Fase 2b escrita ainda; `specs/README.md` tem o roadmap de alto nível.

## Números finais da Fase 1

(Atualizado após a consolidação pré-Fase 2 de 2026-08-06 — ver seção própria
abaixo. Os números originais do fechamento de F4 eram 367/333/60.)

- **401 testes**: 341 unitários (offline), 60 de integração (`make up`).
- Cobertura com `make test` (unitários, offline): **97.12%** total.
  - `engine/`: 92-100% por arquivo.
  - `analytics/`: `metrics.py` e `benchmark.py` 100%, `report.py` 99%,
    `plot.py` 96%. Todos folgados acima do piso de 80% de RNF-02.
- **RNF-04 medido, não presumido:** `get_series` + `run_backtest` +
  `buy_and_hold` + `BacktestReport.build()` sobre 2.912 barras de AAPL
  (~11.5 anos, 2015-01-01 até 2026-07-31) — **mediana 0.051s** de 5 execuções,
  bem abaixo do limite de 5s. Medido isolando o cômputo (sem I/O de
  ingestão nem renderização de gráfico), que é o que a leitura de histórico
  completo de ADR-0004 mais impactaria.
- **Ingestão real do universo completo** (20 tickers, `config/universe.yml`),
  2015-01-01 até a última barra disponível: 55.328 barras inseridas, 0
  tickers falhos, 0 quarentenas no run final (1 quarentena por ticker — o
  pregão do dia corrente, ainda em formação — no run anterior à correção do
  bug de preço não finito, ver abaixo).

## Números finais da Fase 2a

- **471 testes** (unitários offline; 60 de integração com `make up`).
- Cobertura `make check`: **97.84%** total, escopo `engine/` + `analytics/`,
  piso da 2a = **85%** (RNF-02 supersedido — `fail_under` 85 no pyproject).
- **RNF-04 medido no run real completo** (20 ativos × ~10 anos): **0,73 s <
  30 s** (meta). Harness de escopo declarado em `scripts/rnf04_harness.py`
  (`make rnf04`) — mede só o cômputo (P5).
- **Resultado honesto (E2E do DoD):** estratégia sma-cross 20/50 1/N
  +217,93% (CAGR 10,50%; Sharpe 1,04; maxDD 14,74%; 618 trades; turnover
  2,69) vs benchmark 1/N buy-and-hold +2.509,09% (CAGR 32,50%; Sharpe 1,15;
  maxDD 43,00%; 20 trades; turnover 0,01) — mesma assinatura da Fase 1
  (perde em retorno, ganha em drawdown), agora multi-ativo, com
  custos/slippage/cap idênticos nos dois lados.
- Contadores de mecanismo do run: `{stops: 0, ambiguidades: 0,
  não-atendidas: 2}`; caixa ocioso final 85.269,19; 13 tickers com série
  truncada pela ingestão (reportados como deslistados — semântica POR-02.3,
  não deslistagem real).

## Invariantes que não são sugestões (ver CLAUDE.md e ADRs)

- **ADR-0002** — execução no `open` do pregão seguinte.
- **ADR-0003** — preço bruto persistido, ajuste em tempo de leitura. A
  sanidade cruzada (bruto × ajuste) é guarda executável: `make verify-raw`
  (Fase 1 v0.10).
- **ADR-0004** — ajuste materializado sobre o histórico completo, depois
  fatiado. Errata datada ao fim do ADR corrige nomes de teste (não o corpo).
- **ADR-0001** — MongoDB, índice composto `(ticker, date)`. `backtest_runs`
  ganhou índice `{ticker:1, "strategy.name":1, created_at:-1}` em F1.

## Bugs reais encontrados e corrigidos

### (Fase 1, F4) Preço não finito (`NaN`) escapava da validação (ING-05.1)

As regras de quarentena são comparações de desigualdade (`high < low`, fora de
`[low, high]`, `preço ≤ 0`), e `NaN` não satisfaz nenhuma delas nem sua
negação (IEEE 754) — uma barra com `close = nan` passava como válida.
Encontrado rodando a ingestão real de F4: o yfinance devolveu `close = nan`
para o pregão do dia corrente, ainda em formação no momento da consulta.
O sintoma era `retorno acumulado`/`CAGR` = `nan` no relatório sempre que a
posição (estratégia ou benchmark) estava aberta na última barra.

Corrigido em `ingestion/validator.py` (`math.isfinite` em toda comparação de
preço), spec atualizada **antes** do código no mesmo commit (requirements
v1.1, design v0.8 — CLAUDE.md exige isso quando os dois mudam juntos). As
20 barras já gravadas antes da correção foram removidas manualmente do banco
(não há caminho automático: `upsert_bars` só grava `valid_bars`, não some
com uma barra que era válida e passou a ser quarentenada) e a ingestão foi
re-executada, confirmando a quarentena correta de todos os 20 casos.

### (Fase 2a, T18) Dupla contagem de splits no raw — `auto_adjust=False` não é bruto

**O sintoma era "provável demais para ser verdade".** No primeiro E2E do
DoD (20 ativos × ~10 anos), o benchmark 1/N "comprou" 414.573 ações de NVDA
(832× o capital) a preço ajustado de US$ 0,012 e retornou ~870× —
impossível. Diagnóstico: **dupla contagem de splits** —
`YFinanceProvider.fetch_prices` usava `auto_adjust=False`, que no yfinance
**ainda aplica splits** ao OHLC (só exclui dividendos), e gravava o
resultado em `bars` como se fosse bruto; o ajuste do §3.7 aplicava o split
de novo (NVDA ÷40 duas vezes). Afetados exatamente os tickers com split
dentro da janela: **AAPL, NVDA, GOOGL, AMZN, NEE**. A spec estava certa
(ADR-0003: bruto persistido, ajuste em leitura); o código da Fase 1 a
violava.

Correção spec-first (CLAUDE.md), em três partes: emenda do design da Fase 1
(v0.10 — §3.1 define "bruto" como pré-split, como negociado; §3.7 registra o
bug e a correção), back-out dos splits no provider (`raw[t] = split_adj[t] ×
Π rᵢ`, splits com ex estritamente posterior; round-trip com
`adjustment_factors` fechando a 1e-9), e **migração determinística de 9.030
barras** a partir do próprio `bars` (sem refetch, backup em `/tmp`,
idempotente). A sanidade cruzada que o ADR-0003 previa (provedor entregando
ajustado como bruto) virou **guarda executável**: `make verify-raw` falha se
a razão bruta colar em 1 ou se o ajustado saltar fora da data ex.

**Regeneração dos 20 relatórios (2026-08-14).** Os relatórios por ticker da
Fase 1 foram regenerados sobre a base corrigida (CLI, mesmos parâmetros:
SMA 20/50, D5). Inocuidade confirmada byte a byte: os **15 tickers sem
split na janela têm `series_hash` inalterado e JSON idêntico**; os 5
afetados (AAPL, NVDA, GOOGL, AMZN, NEE) têm hash novo — AAPL também ganhou
3 barras (2026-08-03 a 2026-08-05, re-ingestão de teste do RF-CON-01).
Mudança de placar: CAGR segue 1/20 (META), mas **Sharpe caiu de 3/20 para
1/20** — as vitórias de AMZN e GOOGL em Sharpe eram artefato do retorno do
buy-and-hold inflado pelo salto espúrio do ajuste na data do split. No run
corrigido não há trade ≤ 7 dias das datas ex (GOOGL tem 1 trade com entrada
4 dias após o split de 07/2022 — sinal real, série sem salto); NVDA perdeu
1 trade (30→29). Efeitos por ticker (CAGR estratégia, antigo→novo): AAPL
27,08→12,77 (B&H 39,29→22,63); NVDA 96,70→39,28 (B&H 132,40→67,48); GOOGL
14,80→15,59 (B&H 62,73→25,04); AMZN 11,66→11,56 (B&H 64,63→26,50); NEE
18,95→3,75 (B&H 28,59→12,73).

**Nota de ambiente (push).** A migração de splits foi aplicada **no Mongo
local desta máquina**; os dados não vão no git. Qualquer outro ambiente que
precise da base corrigida roda o script determinístico e idempotente
versionado no repo (`scripts/migrate_raw_split_backout.py`, backup em
`/tmp`) e valida com `make verify-raw` antes de rodar E2E com dados reais.

## O que Bloco F entregou

**F1 — CLI `backtest`** (`cli.py::backtest`, `cli.py::run_backtest_flow`).
`--strategy/--ticker/--from/--to/--fast/--slow`, janela default D5
(2015-01-01 até a última barra). Ticker sem dado ingerido propaga
`DataError` de `build_price_series`; CLI captura, imprime mensagem acionável,
sai com código 1 (CA-02.2). Persiste em `backtest_runs` via
`MongoRepository.save_backtest_run`, que carimba `created_at` — `datetime`
continua restrito a `repository.py`/`ingestion/normalizer.py` (design §3.6),
então o CLI nunca toca a classe. Índice definido no mesmo commit (design
v0.7), adiado desde a v0.3.

**F2 — gráfico** (`analytics/plot.py::plot_backtest`). Equity de estratégia
e benchmark no painel superior com marcações ▲/▼ de entrada e saída, drawdown
no inferior. Backend `Agg` (sem display). Salvo em arquivo.

**F3 — RNF-04 + cobertura.** Ver "Números finais" acima.

**F4 — resultado honesto.** Ver [`results/`](../results/) e a seção
"Resultados" do [README](../README.md). SMA cross 20/50 fixo, sem otimização,
em todos os 20 tickers: **a estratégia perde para o buy-and-hold em CAGR em
19 dos 20** — resultado esperado da literatura para seguimento de tendência
em mega caps americanas num mercado de alta prolongada (2015-2026), não
falha do engine. META é a única exceção, por evitar parte de uma queda de
77% em 2021-2022, não por "acertar melhor" o mercado.

## Verificação por mutação desta sessão

| Alvo | Mutação | Testes que caem |
|---|---|---|
| D1 `SmaCross.on_bar` | sinalizar por nível (`fast>slow`) em vez de na transição | 2 |
| D1 `SmaCross.on_bar` | inverter ENTER/EXIT | 3 |
| D1 `SmaCross.on_bar` | comparar SMAs em `i` e `i` em vez de `i` e `i-1` | 3 |
| D1 `SmaCross.warmup` | `warmup = fast` em vez de `slow` | 1 (só o teste de propriedade — ver nota) |

A mutação de `warmup` expôs um teste com dente fraco: os testes de
cruzamento não notavam a diferença porque a fixture (`_CLOSES` plano nas três
primeiras barras) faz uma chamada prematura de `on_bar` produzir
`prev_diff == curr_diff == 0`, que não passa nas comparações estritas —
um empate mascarava o warmup errado atrás de "nenhum sinal", que também é o
resultado correto na maioria das barras. Adicionado
`test_engine_never_calls_on_bar_before_slow_bars_of_true_history`, que trava
o contrato pelo lado que a coincidência aritmética não protege (quais
índices `run_backtest` efetivamente consultou). Com o teste novo, a mesma
mutação derruba 2 testes. Ver [HANDOFF.md](../HANDOFF.md) para a tabela de
E1/E2 (sessão anterior) e a tabela completa desta.

## Consolidação pré-Fase 2 (2026-08-06)

Escopo: §7 de `specs/fase-2a-requirements.md` (v0.1, gate 1 em revisão —
requisitos herdados da Fase 1, não corpo novo da Fase 2a). Design v0.9 de
`specs/00-plataforma/fase-1-design.md` precede o código, conforme CLAUDE.md
§1.

- **RF-CON-01** — barra cuja `date` é ≥ à data UTC de execução (sessão em
  formação) passa de **quarentenada** para **descartada com aviso**,
  avaliada antes de ING-05.1. `MongoRepository.current_execution_date()` é o
  único ponto novo de leitura do relógio (fronteira de instante do design
  §3.6 preservada); `validate_bars` recebe `as_of` como parâmetro
  obrigatório e continua função pura. `ingestion_runs` ganhou
  `discarded_in_progress_count`, separado de `quarantined_count`. Verificado
  contra ingestão real (`AAPL`, 2026-08-01 a 2026-08-06): campo presente no
  documento, `0` no run porque o pregão do dia ainda não tinha barra
  disponível no momento do teste — o mecanismo dispara quando há o quê
  descartar, não sempre.
- **RF-CON-02** — `BacktestReport` ganhou a seção `"run"`: nome/parâmetros
  da estratégia, capital inicial, contagem de barras consumidas, datas
  efetivas de início/fim. Antes, essa informação só existia no nome do
  arquivo. Teste dedicado (`test_full_run_configuration_is_reconstructible_
  from_the_json_alone`) prova CA-02.2 comparando o JSON isolado contra os
  parâmetros originais, não contra `to_dict()` de novo.
- **RF-CON-03** — README ganhou a explicação de por que a estratégia perde
  em CAGR em 19/20 tickers mas só em 17/20 em Sharpe: sair do mercado corta
  drawdown/volatilidade junto com retorno — é a assinatura de
  trend-following (AMZN e GOOGL vencem em Sharpe apesar de perderem em
  CAGR), não um segundo achado independente. **Atualizado em 2026-08-14:**
  após a regeneração pós-back-out de splits, as vitórias de AMZN/GOOGL em
  Sharpe se revelaram artefato do split duplicado e o placar passou a 19/20
  em ambas as métricas (ver a subseção do bug dos splits abaixo).
- **Regeneração dos 20 relatórios.** Mesma ingestão, mesmo universo (20
  tickers de `config/universe.yml`), mesmos parâmetros (SMA 20/50, D5).
  **Os 20 `series_hash` batem, byte a byte, com os relatórios anteriores** —
  confirma que só o formato do JSON mudou, não o pipeline de dados. PNGs não
  regerados (nada nos gráficos depende do formato do relatório). *(A base
  mudou em 2026-08-14 — back-out de splits; a regeneração correspondente
  está na subseção do bug dos splits abaixo.)*

Sequência completa (`make check` + `make test-integration`) verde após cada
parte; commits pequenos por RF, um por vez.

## Pendências

Nenhuma ambiguidade de spec aberta. As quatro do Bloco C (HANDOFF §6) foram
todas fechadas: uma por errata do ADR-0004 (sessão anterior), três por v0.6
do design (esta sessão — todas descritivas, nenhuma exigiu escolher entre
comportamentos, código já implementava a única opção documentada).

**Resolvida (2026-08-14):** os 20 relatórios por ticker da Fase 1 (F4)
foram **regenerados** sobre a base corrigida (back-out de splits) — 15
tickers byte-idênticos, 5 com números novos; placar de Sharpe 17/20 → 19/20
(vitórias de AMZN/GOOGL eram artefato do split duplicado). Detalhe na
subseção do bug dos splits.

**Para a Fase 2b, quando começar:** nenhuma spec escrita ainda. Ideias que já
apareceram ao longo da Fase 1 e vale revisitar então — não implementar agora:
cache de ajuste em Redis (ADR-0003 já deixa isso escopado, condicionado a
RNF-04 virar problema real — não virou), otimização de leitura de histórico
completo com injeção de mapa `data → close` se a leitura de `bars` virar
gargalo medido (ADR-0004 "Revisitar quando"), fallback de provedor de dados
pago caso a qualidade do yfinance grátis continue sendo um risco (o bug de
`NaN` desta sessão é evidência concreta desse risco, não hipotética).
