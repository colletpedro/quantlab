# Fase 1 (MVP) — Plano de tarefas

**Status:** aprovada — gate check 3 concluído
**Versão:** 0.1
**Data:** 2026-08-03
**Origem:** `fase-1-requirements.md` v1.0, `fase-1-design.md` v0.2

---

## Princípio de ordenação

Blocos ordenados por dependência de dados, não por camada arquitetural. A regra: nenhuma tarefa começa antes que aquilo que ela consome exista e esteja testado.

`storage/` vem primeiro porque `PriceSeries` é o contrato que ingestão produz e engine consome. `engine/` vem antes de `analytics/` porque `BacktestResult` é a entrada das métricas. `strategies/` é pequeno e depende só do protocolo.

Cada tarefa tem **escopo fechado** (dá para dizer se terminou) e **critério de verificação** (um comando ou teste que prova).

---

## Bloco A — Storage (fundação)

Consome: nada além de Mongo. Produz: `PriceSeries`, o contrato central.

### A1 — Conexão e ciclo de vida do cliente
**Escopo:** módulo de conexão com Mongo lendo `Settings.mongo_uri`, com pool, timeout explícito e fechamento determinístico. Nenhuma lógica de domínio.
**Verificação:** teste de integração conecta, faz ping, fecha. Falha de conexão levanta `DataError` com mensagem acionável.
**Cobre:** RNF-06.

### A2 — Criação de coleções e índices (idempotente)
**Escopo:** rotina que cria `bars`, `corporate_actions`, `quarantined_bars`, `ingestion_runs`, `backtest_runs` com os índices de design §3.1–3.5. Reexecutável sem erro.
**Verificação:** teste de integração roda duas vezes e confirma índices via `list_indexes()`; consulta por `(ticker, intervalo)` verificada com `explain()` usando `IXSCAN`, não `COLLSCAN`.
**Cobre:** PER-01.2.

### A3 — Fronteira de data (`date` ⇄ `datetime`)
**Escopo:** funções de conversão no repositório, isoladas. Nenhum outro módulo de storage converte.
**Verificação:** testes unitários de ida e volta, incluindo datas de virada de ano e de horário de verão. Nenhum `datetime` vaza no retorno público.
**Cobre:** RNF-07, design §3.6.

### A4 — Escrita de barras com upsert
**Escopo:** upsert por `(ticker, date)`, com log de alteração quando o valor muda.
**Verificação:** escrever a mesma barra duas vezes mantém a contagem; escrever valor diferente atualiza e registra anterior e novo.
**Cobre:** ING-03.1, ING-03.2, PER-01.1.

### A5 — Escrita de eventos corporativos com upsert
**Escopo:** upsert por `(ticker, date, kind)`, com log de revisão.
**Verificação:** dividendo e split na mesma data coexistem; revisão de valor atualiza sem duplicar.
**Cobre:** ING-02.1, ING-02.2, design §3.2.

### A6 — Coleção de quarentena
**Escopo:** gravação de barra rejeitada com payload bruto, todas as razões de rejeição, e `ingestion_run_id`.
**Verificação:** barra inválida vai para `quarantined_bars` e **não** aparece em `bars`; múltiplas violações registram todas as razões.
**Cobre:** ING-05.1, design §3.3.

### A7 — Fator de ajuste ⭐
**Escopo:** cálculo do fator cumulativo a partir de eventos, `cumprod` reverso, aplicado a preços e volume. Casos de borda de design §3.7.
**Verificação:** fixtures de papel com resultado calculado à mão — split isolado, dividendo isolado, ambos combinados, evento anterior à primeira barra, série sem eventos (PER-02.4). Determinismo em duas leituras (PER-02.3).
**Cobre:** PER-02.1 a PER-02.4. **Tarefa de maior risco do bloco.**

### A8 — `PriceSeries` e leitura ajustada
**Escopo:** value object congelado, arrays marcados `writeable=False`, `get_series()` com `adjusted=True|False`. Eventos carregados sobre histórico completo, não sobre a janela.
**Verificação:** tentativa de escrita em qualquer array levanta `ValueError`; série com evento fora da janela é ajustada corretamente (ING-02.3).
**Cobre:** design §3.7.

### A9 — Hash determinístico
**Escopo:** SHA-256 sobre representação canônica, 6 casas decimais fixas.
**Verificação:** mesma série ⇒ mesmo hash em execuções distintas; alteração de um centésimo de centavo em uma barra muda o hash.
**Cobre:** PER-03.1.

### A10 — Integração no CI e remoção da dívida
**Escopo:** job de integração no CI com serviço MongoDB; remoção da tolerância a exit 5 em `make test-integration`.
**Verificação:** CI verde com os dois jobs; apagar todos os testes de integração faz o job falhar (verificar localmente, não commitar).
**Cobre:** dívida registrada no HANDOFF §3.3.

---

## Bloco B — Ingestão

Consome: Bloco A. Produz: dados reais no banco.

### B1 — Cliente yfinance
**Escopo:** wrapper com `auto_adjust=False`, retry com backoff, timeout. Sem normalização.
**Verificação:** testes com resposta mockada — sucesso, erro de rede, resposta vazia tratada como falha (ING-04.2).
**Cobre:** ING-01.1, ING-01.2, ING-04.1, ING-04.2.

### B2 — Normalizador (fronteira de entrada)
**Escopo:** `pd.Timestamp` tz-aware ou naive ⇒ `datetime.date`. Único ponto de conversão na ingestão.
**Verificação:** fixtures com ambos os formatos produzem a mesma data.
**Cobre:** ING-01.3, RNF-07.

### B3 — Validador
**Escopo:** regras de quarentena (ING-05.1) e avisos não-bloqueantes (ING-05.2, ING-05.3).
**Verificação:** cada regra com fixture própria; aviso não impede gravação.
**Cobre:** ING-05.1 a ING-05.3.

### B4 — Orquestrador e `ingestion_runs`
**Escopo:** laço sobre tickers, tolerância a falha individual, registro do run, exit code ≠ 0 se houver falha.
**Verificação:** falha em um ticker não impede os outros; código de saída correto.
**Cobre:** ING-04.1, PER-03.1.

### B5 — Teste de arquitetura da fronteira de data
**Escopo:** varredura de imports; `datetime` só em `ingestion/normalizer.py` e `storage/repository.py`. Bloqueante.
**Verificação:** introduzir `datetime` em outro módulo faz o teste falhar.
**Cobre:** design §3.6, decisão Q3.

### B6 — CLI `ingest`
**Verificação:** comando roda ponta a ponta contra Mongo real; sem `--tickers` usa o universo default.
**Cobre:** RF-CLI-01.

---

## Bloco C — Engine

Consome: `PriceSeries` (Bloco A). Testável sem banco, com séries de papel.

### C1 — `MarketView` ⭐
**Escopo:** fatias `[:i+1]`, `writeable=False`, `InsufficientHistoryError`, superfície mínima.
**Verificação:** acesso além de `i` impossível pela API; teste exercita `.base` — mutação falha, leitura documentada como fora do contrato.
**Cobre:** ENG-01.3, design §4.1.

### C2 — Protocolo `Strategy` e `Signal`
**Verificação:** estratégia dummy implementa e roda sem alteração no engine.
**Cobre:** ENG-05.1, ENG-05.2.

### C3 — `Trade`, `Position`, `Portfolio`
**Escopo:** N posições modeladas, N=1 exercitado. Campos de auditoria de gap.
**Verificação:** invariantes `cash ≥ 0`, `quantity ≥ 0`.
**Cobre:** ENG-04.4, D4.

### C4 — `Broker` e custos
**Escopo:** quantidade inteira máxima resolvendo `q·p + custo ≤ caixa`. Custo debitado e registrado.
**Verificação:** fixture onde ignorar o custo produziria caixa negativo; quantidade zero não gera ordem.
**Cobre:** ENG-02.1 a ENG-02.3, ENG-03.1, ENG-03.2.

### C5 — Laço de barras ⭐
**Escopo:** ordem executar → marcar → consultar. Ordem pendente, sinal na última barra, gap.
**Verificação:** **teste de mutação de barras futuras (ENG-01.2)** — o critério de aceitação da fase.
**Cobre:** ENG-01.1, ENG-01.2, ENG-01.4, ENG-01.5, design §4.3.

### C6 — Conciliação
**Verificação:** identidade de design §4.6 com `math.isclose(rel_tol=1e-9)`, em cenários com posição aberta ao fim e com dividendo durante posição.
**Cobre:** ENG-04.1 a ENG-04.3.

---

## Bloco D — Estratégia

### D1 — SMA cross
**Escopo:** `warmup = slow`, validação `fast < slow`, cruzamento para cima e para baixo.
**Verificação:** série de papel com cruzamentos em datas conhecidas; `fast >= slow` falha na instanciação.
**Cobre:** ENG-06.1 a ENG-06.4.

---

## Bloco E — Analytics

### E1 — Métricas
**Verificação:** séries de papel com resultado calculado à mão; Sharpe com volatilidade zero devolve `None`; drawdown não recuperado.
**Cobre:** ANA-01.1 a ANA-01.5.

### E2 — Benchmark alinhado
**Escopo:** compra ao `open[warmup + 1]`, mesmos custos.
**Verificação:** janelas de equity idênticas entre estratégia e benchmark.
**Cobre:** ANA-02.1, ANA-02.2.

### E3 — Relatório e seção de vieses
**Escopo:** dataclass, render texto e JSON, constante literal com os seis itens de design §5.2.
**Verificação:** teste assegura que a seção existe em todo relatório e que os seis itens estão presentes.
**Cobre:** ANA-03.1.

---

## Bloco F — Fechamento

### F1 — CLI `backtest` e persistência do run
**Cobre:** RF-CLI-02, design §3.5.

### F2 — Gráfico
**Escopo:** equity da estratégia e do benchmark no painel superior, drawdown no inferior, marcações de entrada e saída.
**Cobre:** RF-CLI-03.

### F3 — Cobertura e benchmark de performance
**Verificação:** ≥ 80% em `engine/` e `analytics/` com código real; 10 anos em < 5 s (RNF-04).

### F4 — README e resultado honesto
**Escopo:** documentação final e um resultado de backtest reportado como saiu, incluindo derrota para o buy-and-hold.
**Cobre:** Definition of Done.

---

## Ordem de execução

```
A1 → A2 → A3 → A4 → A5 → A6 → A7 → A8 → A9 → A10
                                            ↓
B1 → B2 → B3 → B4 → B5 → B6 ────────────────┤
                                            ↓
C1 → C2 → C3 → C4 → C5 → C6 → D1 ───────────┤
                                            ↓
E1 → E2 → E3 → F1 → F2 → F3 → F4
```

Blocos A e C são os de maior risco: A7 (fator de ajuste) e C5 (laço de barras) concentram a chance de bug silencioso.
