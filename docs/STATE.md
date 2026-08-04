# STATE — mapa do projeto

Mantenha-o atualizado a cada sessão — desatualizado vale menos que ausente.

## Onde estamos

**Fase 1 (MVP) concluída.** Todos os blocos A-F implementados, testados, e um
resultado honesto rodado contra dado de mercado real e comprometido em
[`results/`](../results/). Definition of Done da fase (requirements.md §8)
integralmente atendido.

| Bloco | Escopo | Estado |
|---|---|---|
| A | `storage/` — persistência, ajuste em tempo de leitura | ✅ |
| B | `ingestion/` — coleta, validação, orquestração, CLI `ingest` | ✅ |
| C | `engine/` — `MarketView`, `Strategy`, `Portfolio`, `Broker`, laço de barras | ✅ |
| D | `strategies/` — SMA cross (D1) | ✅ |
| E | `analytics/` — métricas (E1), benchmark (E2), relatório (E3) | ✅ |
| F | CLI `backtest` + persistência (F1), gráfico (F2), RNF-04 + cobertura (F3), README + resultado honesto (F4) | ✅ |

CI: 3 jobs verdes em todo push a `main`. Último run verificado:
[30881248393](https://github.com/colletpedro/quantlab/actions/runs/30881248393).

**Próximo:** Fase 2 (não iniciada) — custos realistas, portfólio multi-ativo,
walk-forward, analytics de risco, Redis, API, infra. Nenhuma spec de Fase 2
escrita ainda; `specs/README.md` tem o roadmap de alto nível.

## Números finais da Fase 1

- **367 testes**: 333 unitários (offline), 60 de integração (`make up`).
- Cobertura com `make test` (unitários, offline): **97.09%** total.
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

## Invariantes que não são sugestões (ver CLAUDE.md e ADRs)

- **ADR-0002** — execução no `open` do pregão seguinte.
- **ADR-0003** — preço bruto persistido, ajuste em tempo de leitura.
- **ADR-0004** — ajuste materializado sobre o histórico completo, depois
  fatiado. Errata datada ao fim do ADR corrige nomes de teste (não o corpo).
- **ADR-0001** — MongoDB, índice composto `(ticker, date)`. `backtest_runs`
  ganhou índice `{ticker:1, "strategy.name":1, created_at:-1}` em F1.

## Bug real encontrado e corrigido nesta sessão

**Preço não finito (`NaN`) escapava da validação (ING-05.1).** As regras de
quarentena são comparações de desigualdade (`high < low`, fora de
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

## Pendências

Nenhuma ambiguidade de spec aberta. As quatro do Bloco C (HANDOFF §6) foram
todas fechadas: uma por errata do ADR-0004 (sessão anterior), três por v0.6
do design (esta sessão — todas descritivas, nenhuma exigiu escolher entre
comportamentos, código já implementava a única opção documentada).

**Para a Fase 2, quando começar:** nenhuma spec escrita ainda. Ideias que já
apareceram ao longo da Fase 1 e vale revisitar então — não implementar agora:
cache de ajuste em Redis (ADR-0003 já deixa isso escopado, condicionado a
RNF-04 virar problema real — não virou), otimização de leitura de histórico
completo com injeção de mapa `data → close` se a leitura de `bars` virar
gargalo medido (ADR-0004 "Revisitar quando"), fallback de provedor de dados
pago caso a qualidade do yfinance grátis continue sendo um risco (o bug de
`NaN` desta sessão é evidência concreta desse risco, não hipotética).
