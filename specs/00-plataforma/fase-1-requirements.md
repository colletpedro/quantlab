# Fase 1 (MVP) — Requisitos

**Status:** aprovada — gate check 1 concluído
**Versão:** 1.0
**Data:** 2026-08-03
**Próximo gate:** `specs/00-plataforma/fase-1-design.md` (não iniciado)

> **Nota de organização:** a Fase 1 é uma fatia vertical que atravessa cinco módulos. Escrever cinco `requirements.md` isolados agora fragmentaria um critério de aceitação que é, na prática, único ("o backtest roda ponta a ponta e não mente"). Este documento é a fonte da verdade da fase. A partir da Fase 2, cada módulo ganha spec própria e as seções RF-ING / RF-PER / RF-ENG / RF-ANA / RF-CLI migram para os `requirements.md` correspondentes.

---

## 1. Objetivo

Entregar um backtester single-asset funcional ponta a ponta, correto por construção quanto a lookahead bias, sobre dados de ações americanas persistidos localmente.

O objetivo **não** é encontrar uma estratégia lucrativa. É construir um instrumento de medição confiável. Uma estratégia que perde dinheiro num engine correto é um resultado válido e será reportada como tal.

## 2. Escopo

**Dentro:**
- Ingestão de OHLCV diário de 20 tickers americanos via `yfinance`
- Persistência em MongoDB (séries + metadados + eventos corporativos)
- Engine de backtest single-asset, long-only
- Uma estratégia: cruzamento de médias móveis (SMA cross)
- Custos de transação (fixo + percentual sobre o notional)
- Métricas: retorno acumulado, CAGR, Sharpe anualizado, max drawdown, número de trades, taxa de acerto
- Saída: relatório em CLI + gráfico Matplotlib (equity curve + drawdown)

**Fora (fases posteriores):**
Redis, API HTTP, portfólio multi-ativo em execução, position sizing, tipos de ordem além de mercado, slippage variável, short selling, opções e greeks, VaR, walk-forward, otimização de parâmetros, cloud, Terraform, RAG.

## 3. Glossário mínimo

| Termo | Definição operacional |
|---|---|
| **OHLCV** | Open, High, Low, Close, Volume — as cinco séries de uma barra diária. |
| **Barra** | Um período de negociação agregado. Aqui, um dia. |
| **Pregão** | Dia em que o mercado esteve aberto. Fins de semana e feriados não geram barra. |
| **Notional** | Valor financeiro da ordem: quantidade × preço. |
| **bps (basis point)** | Um centésimo de ponto percentual. 1 bps = 0,01%. |
| **Provento / corporate action** | Evento que altera o valor do papel sem que o mercado tenha se movido: dividendo, split, agrupamento. |
| **Preço ajustado** | Série histórica reescrita retroativamente para descontar proventos, de modo que a variação percentual reflita retorno total. |
| **Lookahead bias** | Usar, na decisão de D, qualquer informação que só existiria após D. |
| **Survivorship bias** | Selecionar o universo de ativos com base em quem sobreviveu até hoje, excluindo falências e deslistagens. Infla retorno. |
| **Equity curve** | Série do valor total da carteira ao longo do tempo. |
| **Drawdown** | Queda percentual do valor da carteira desde o pico anterior. |
| **Max drawdown** | Maior drawdown observado no período. |
| **Sharpe ratio** | Retorno excedente médio dividido pelo desvio-padrão dos retornos, anualizado. Mede retorno por unidade de risco. |
| **Slippage** | Diferença entre o preço observado na decisão e o preço efetivamente executado. |
| **Período de aquecimento (warm-up)** | Barras iniciais consumidas para popular indicadores, durante as quais nenhum sinal é gerado. |

---

## 4. Requisitos funcionais

### 4.1 Ingestão (RF-ING)

**RF-ING-01 — Coleta de OHLCV bruto**
O sistema deve coletar OHLCV diário via `yfinance` para uma lista configurável de tickers, em janela de datas configurável.

- **CA-01.1** — *Dado* um ticker válido e uma janela `[início, fim]`, *quando* a ingestão executa, *então* uma barra é obtida para cada pregão da janela.
- **CA-01.2** — *Dado* que o provedor é consultado, *quando* a coleta ocorre, *então* os preços são requisitados **sem ajuste automático** (`auto_adjust=False`). Ver ADR-0003.
- **CA-01.3** — *Dado* que o provedor devolve datas com timezone, *quando* a barra é normalizada, *então* ela é gravada como data-calendário naive em UTC, sem componente de hora.

**RF-ING-02 — Coleta de eventos corporativos**
O sistema deve coletar dividendos e splits como séries próprias, separadas do OHLCV.

- **CA-02.1** — *Dado* um ticker com histórico de dividendos, *quando* a ingestão executa, *então* cada evento é armazenado com data e valor por ação.
- **CA-02.2** — *Dado* um ticker com histórico de splits, *quando* a ingestão executa, *então* cada evento é armazenado com data e razão.
- **CA-02.3** — *Dado* que eventos corporativos são revisados retroativamente pelo provedor, *quando* a ingestão executa, *então* a coleta de eventos é feita sobre o histórico completo do ticker, não apenas sobre a janela solicitada.

**RF-ING-03 — Idempotência**
Reexecutar a ingestão sobre uma janela já ingerida não deve duplicar nem corromper dados.

- **CA-03.1** — *Dado* que a janela `[A, B]` já foi ingerida, *quando* a ingestão de `[A, B]` executa novamente, *então* a contagem de barras permanece idêntica.
- **CA-03.2** — *Dado* que uma barra já existe e o provedor devolve valor diferente para a mesma data, *quando* a ingestão executa, *então* o registro é atualizado e a alteração é logada com valor anterior e novo.

**RF-ING-04 — Resiliência a falha do provedor**
Falha de rede ou erro do provedor não pode deixar o banco em estado parcial silencioso.

- **CA-04.1** — *Dado* que o provedor falha para o ticker X, *quando* a ingestão de uma lista executa, *então* os demais tickers são processados e X é reportado como falho ao final, com código de saída diferente de zero.
- **CA-04.2** — *Dado* que o provedor devolve resposta vazia para um ticker, *quando* a ingestão executa, *então* isso é tratado como falha explícita, não como sucesso com zero barras.

**RF-ING-05 — Validação de qualidade**
O sistema deve detectar e reportar anomalias antes de gravar.

- **CA-05.1** — *Dado* uma barra onde `high < low`, ou `open`/`close` fora do intervalo `[low, high]`, ou preço ≤ 0, ou volume < 0, *quando* a validação executa, *então* a barra é rejeitada e registrada em log de quarentena.
- **CA-05.2** — *Dado* um gap de pregões maior que 5 dias úteis dentro da janela, *quando* a validação executa, *então* um aviso é emitido (não bloqueante).
- **CA-05.3** — *Dado* uma variação de fechamento a fechamento superior a 50% em valor absoluto sem split registrado na data, *quando* a validação executa, *então* um aviso é emitido (não bloqueante), por indicar provável evento corporativo não capturado.

---

### 4.2 Persistência (RF-PER)

**RF-PER-01 — Armazenamento de séries**
Barras devem ser persistidas em MongoDB, unicamente identificadas por `(ticker, date)`.

- **CA-01.1** — *Dado* o par `(ticker, date)`, *quando* uma segunda barra com a mesma chave é gravada, *então* a operação é um upsert, não uma inserção.
- **CA-01.2** — *Dado* o volume de dados da fase, *quando* uma consulta por ticker e intervalo de datas executa, *então* ela usa índice composto `(ticker, date)` e não varre a coleção. Verificável por `explain()`.

**RF-PER-02 — Ajuste na leitura**
O ajuste por proventos deve ser aplicado em tempo de leitura, a partir do bruto + eventos, nunca gravado como substituição do bruto. Ver ADR-0003.

- **CA-02.1** — *Dado* um ticker com split 2:1 na data D, *quando* a série ajustada é lida, *então* as barras anteriores a D têm preços divididos por 2 e volume multiplicado por 2.
- **CA-02.2** — *Dado* um ticker com dividendo na data D, *quando* a série ajustada é lida, *então* as barras anteriores a D são multiplicadas pelo fator de ajuste correspondente.
- **CA-02.3** — *Dado* o mesmo estado do banco, *quando* a leitura ajustada executa duas vezes, *então* os resultados são idênticos.
- **CA-02.4** — *Dado* um ticker sem nenhum evento corporativo, *quando* a série ajustada é lida, *então* ela é numericamente igual à série bruta.

**RF-PER-03 — Reprodutibilidade**
Deve ser possível reproduzir um backtest passado sobre o estado de dados que existia à época.

- **CA-03.1** — *Dado* um backtest executado, *quando* o relatório é gerado, *então* ele registra a data/hora da ingestão mais recente usada e um hash determinístico da série consumida.

---

### 4.3 Engine (RF-ENG)

**RF-ENG-01 — Invariante anti-lookahead** ⭐
Um sinal computado com informação até o fechamento de D só pode ser executado a partir da abertura do próximo pregão disponível.

- **CA-01.1** — *Dado* que a estratégia gera sinal no fechamento de D, *quando* a ordem é executada, *então* o preço de execução é o `open` do próximo pregão disponível.
- **CA-01.2** — *Dado* um backtest concluído, *quando* qualquer barra posterior à última decisão é alterada arbitrariamente e o backtest é reexecutado, *então* o conjunto de trades executados permanece idêntico. **Este é o teste que prova a invariante e é requisito de aceitação da fase.**
- **CA-01.3** — *Dado* que a estratégia solicita dados, *quando* a barra de índice `i` está sendo processada, *então* a API do engine expõe apenas barras de índice ≤ `i`. Tentativa de acesso a índice > `i` levanta exceção.
- **CA-01.4** — *Dado* que um sinal é gerado na última barra da série, *quando* o backtest termina, *então* a ordem não é executada e é reportada como pendente, sem afetar a contabilidade.
- **CA-01.5** — *Dado* um gap de pregões entre D e a próxima barra disponível, *quando* a ordem é executada, *então* ela usa o `open` da próxima barra existente, qualquer que seja a distância em dias, e o gap é registrado no trade.

**RF-ENG-02 — Execução de ordens a mercado**
- **CA-02.1** — *Dado* sinal de entrada, *quando* executado, *então* a posição vai de 0 para o máximo de ações inteiras compráveis com o caixa disponível, após custos.
- **CA-02.2** — *Dado* sinal de saída, *quando* executado, *então* a posição inteira é liquidada.
- **CA-02.3** — *Dado* que o caixa é insuficiente para 1 ação, *quando* o sinal de entrada ocorre, *então* nenhuma ordem é gerada e o evento é logado.
- **CA-02.4** — *Dado* uma posição aberta ao fim da série, *quando* o backtest termina, *então* ela é marcada a mercado pelo último fechamento e reportada separadamente do PnL realizado, sem liquidação forçada.

**RF-ENG-03 — Custos de transação**
- **CA-03.1** — *Dado* um custo configurado (valor fixo por trade e percentual sobre o notional), *quando* uma ordem executa, *então* o custo é debitado do caixa e registrado no trade.
- **CA-03.2** — *Dado* custo configurado como zero, *quando* o backtest executa, *então* nenhum custo é aplicado — e o relatório sinaliza explicitamente que os resultados são irrealistas.

**RF-ENG-04 — Contabilidade**
- **CA-04.1** — *Dado* qualquer instante do backtest, *quando* o estado é inspecionado, *então* `equity = caixa + (posição × preço de fechamento do dia)`.
- **CA-04.2** — *Dado* o fim do backtest, *quando* a soma de PnL realizado de todos os trades, o PnL não realizado e os custos totais é computada, *então* ela concilia com `equity_final − equity_inicial` a menos de erro de ponto flutuante. **Teste de conciliação obrigatório.**
- **CA-04.3** — *Dado* que o ativo paga dividendo durante uma posição aberta, *quando* o backtest usa série ajustada, *então* o provento está refletido no retorno e o relatório declara que o tratamento é via ajuste de preço, não via crédito em caixa.
- **CA-04.4** — *Dado* qualquer instante do backtest, *quando* o estado é inspecionado, *então* caixa ≥ 0 e posição ≥ 0. Violação é erro de programação, não condição de mercado.

**RF-ENG-05 — Interface de estratégia**
Deve existir um contrato único que qualquer estratégia implementa, sem acesso a estado global.

- **CA-05.1** — *Dado* uma nova estratégia, *quando* ela implementa a interface, *então* o engine a executa sem qualquer alteração no engine.
- **CA-05.2** — *Dado* uma estratégia, *quando* ela é executada, *então* ela não tem acesso ao caixa, à posição nem ao histórico de trades. Ela emite intenção; o engine decide execução e tamanho.

**RF-ENG-06 — Estratégia SMA cross**
- **CA-06.1** — *Dado* períodos rápido `f` e lento `s` (`f < s`), *quando* a SMA de `f` cruza a de `s` para cima no fechamento de D, *então* um sinal de entrada é gerado para o próximo pregão.
- **CA-06.2** — *Quando* o cruzamento é para baixo, *então* um sinal de saída é gerado para o próximo pregão.
- **CA-06.3** — *Dado* que ainda não há `s` barras disponíveis, *quando* o engine processa as primeiras barras, *então* nenhum sinal é gerado (período de aquecimento).
- **CA-06.4** — *Dado* `f ≥ s` na configuração, *quando* a estratégia é instanciada, *então* ela falha imediatamente com erro de validação.

---

### 4.4 Analytics (RF-ANA)

**RF-ANA-01 — Métricas de performance**
O sistema deve computar, a partir da equity curve: retorno acumulado, CAGR, Sharpe anualizado, max drawdown, duração do max drawdown, número de trades e taxa de acerto.

- **CA-01.1** — *Dado* uma série de retornos diários, *quando* o Sharpe é computado, *então* ele usa `média(retorno − rf) / desvio-padrão(retorno) × √252`, com `rf` configurável e default 0.
- **CA-01.2** — *Dado* `rf = 0` por default, *quando* o relatório é emitido, *então* essa premissa é declarada no output.
- **CA-01.3** — *Dado* uma equity curve, *quando* o max drawdown é computado, *então* o resultado é a maior queda percentual pico-a-vale, com data de início, de fundo e de recuperação (ou indicação de não recuperado).
- **CA-01.4** — *Dado* desvio-padrão dos retornos igual a zero, *quando* o Sharpe é computado, *então* o resultado é indefinido e reportado como tal, sem divisão por zero.
- **CA-01.5** — *Dado* menos de 30 barras de equity, *quando* as métricas são computadas, *então* o relatório emite aviso de amostra insuficiente para inferência.

**RF-ANA-02 — Benchmark buy-and-hold**
Todo backtest deve reportar, lado a lado, o resultado de comprar e segurar o mesmo ativo no mesmo período, com os mesmos custos de entrada.

- **CA-02.1** — *Dado* um backtest concluído, *quando* o relatório é emitido, *então* as mesmas métricas do benchmark aparecem em paralelo.
- **CA-02.2** — *Dado* que a estratégia tem período de aquecimento, *quando* o benchmark é computado, *então* ele inicia na mesma barra em que a estratégia se tornou apta a operar, e não na primeira barra da série. Comparar períodos diferentes invalidaria a comparação.

**RF-ANA-03 — Declaração de vieses**
- **CA-03.1** — *Dado* qualquer relatório de backtest, *quando* ele é emitido, *então* contém uma seção fixa declarando: universo sujeito a survivorship bias, slippage não modelado, custos simplificados, ausência de impacto de mercado, e ausência de correção para múltiplas hipóteses testadas.

---

### 4.5 CLI e visualização (RF-CLI)

**RF-CLI-01 — Comando de ingestão**

```
python -m quantlab ingest --tickers AAPL,MSFT --from 2015-01-01 --to 2024-12-31
```

- **CA-01.1** — *Quando* o comando executa sem `--tickers`, *então* usa o universo default do arquivo de configuração.

**RF-CLI-02 — Comando de backtest**

```
python -m quantlab backtest --strategy sma_cross --ticker AAPL --from 2015-01-01 --fast 20 --slow 50
```

- **CA-02.1** — *Quando* o comando executa com sucesso, *então* o relatório de métricas é impresso e o gráfico é salvo em arquivo.
- **CA-02.2** — *Dado* que o ticker não tem dados ingeridos, *quando* o comando executa, *então* falha com mensagem acionável e código de saída ≠ 0.

**RF-CLI-03 — Gráfico**
- **CA-03.1** — *Quando* o gráfico é gerado, *então* contém equity curve da estratégia e do benchmark no painel superior, e drawdown no painel inferior, com marcações de entrada e saída.

---

## 5. Requisitos não funcionais

- **RNF-01 — Determinismo.** Mesmo estado de banco + mesmos parâmetros ⇒ resultado idêntico. Sem aleatoriedade não semeada.
- **RNF-02 — Cobertura de testes.** Mínimo 80% em `engine/` e `analytics/`. Os módulos de dinheiro e de medição são os que não podem errar.
- **RNF-03 — Fixtures sintéticas.** Testes de engine e analytics rodam sobre séries construídas à mão, com resultado calculável no papel — não sobre dados reais de mercado.
- **RNF-04 — Performance.** Backtest de 10 anos de barras diárias em um ativo executa em menos de 5 segundos.
- **RNF-05 — Tipagem.** Código com type hints, verificado por `mypy --strict` no CI.
- **RNF-06 — Ambiente.** Python 3.12+; Mongo via `docker-compose`; `make test` roda tudo offline, sem rede.
- **RNF-07 — Datas.** Toda data no sistema é data-calendário naive. Nenhuma comparação de datas envolve timezone.
- **RNF-08 — Dinheiro.** Valores monetários usam ponto flutuante, com comparações em testes por tolerância explícita, nunca por igualdade exata. `Decimal` fica documentado como alternativa descartada por custo de performance.

## 6. Premissas

1. Universo: 20 ações americanas líquidas, lista fixa e versionada em arquivo de configuração.
2. Long-only. Sem venda a descoberto.
3. Sem alavancagem. Sem fracionário.
4. Capital inicial default: 100.000 USD.
5. Todas as ordens são a mercado, executadas integralmente ao preço de abertura, sem impacto de mercado e sem limite de participação no volume.
6. Dividendos entram via ajuste de preço, não como crédito em caixa.
7. Taxa livre de risco = 0.
8. Moeda única (USD). Sem conversão cambial.
9. Sem imposto.

## 7. Decisões fechadas

| # | Questão | Decisão | Razão |
|---|---|---|---|
| D1 | Tamanho da ordem de entrada | *All-in*: todo o caixa disponível | Position sizing é escopo da Fase 2. All-in mantém a Fase 1 focada na correção do engine, não na alocação. |
| D2 | Custo de transação default | 1 bps sobre o notional + USD 1 fixo por trade | Corretoras de varejo nos EUA hoje cobram zero comissão, mas custo zero mascara estratégias de giro alto. O default conservador força a estratégia a pagar pelo giro. Configurável. |
| D3 | Comportamento na saída | Volta a 100% caixa. Sem short. | Simplifica contabilidade e torna a comparação com buy-and-hold interpretável. |
| D4 | Estrutura de dados multi-ativo | `Portfolio` modela N posições desde já; Fase 1 exercita N=1 | Evita reescrita na Fase 2. Custo marginal de modelagem é baixo; custo de retrofit seria alto. |
| D5 | Janela default de backtest | 2015-01-01 até a última barra disponível | ~10 anos cobrem regimes distintos, incluindo o choque de 2020. |

## 8. Definition of Done da fase

- [ ] Os comandos de RF-CLI-01 e RF-CLI-02 executam ponta a ponta em ambiente limpo, após `make up`
- [ ] O teste de CA-01.2 do engine (mutação de dados futuros) passa
- [ ] O teste de conciliação de CA-04.2 passa
- [ ] Cobertura ≥ 80% em `engine/` e `analytics/`
- [ ] CI verde: testes, `mypy --strict`, lint
- [ ] ADRs 0001, 0002 e 0003 escritos
- [ ] README com arquitetura, instruções de execução e seção de limitações conhecidas
- [ ] Um resultado de backtest reportado honestamente, inclusive se a estratégia perder para o buy-and-hold

## 9. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.1 | 2026-08-02 | Rascunho inicial com Q1–Q5 em aberto |
| 1.0 | 2026-08-03 | Q1–Q5 fechadas como D1–D5. Adicionados CA-01.3 (timezone), CA-02.3 (eventos retroativos), CA-04.2 (resposta vazia), CA-05.3 (variação sem split), CA-02.4 (série sem eventos), CA-01.4/01.5 (sinal na última barra, gap de pregões), CA-02.4 (posição aberta no fim), CA-04.4 (invariantes de sinal), CA-05.2 (isolamento da estratégia), CA-06.4 (validação f<s), CA-01.4/01.5 analytics (Sharpe indefinido, amostra pequena), CA-02.2 (alinhamento do benchmark), RNF-07 e RNF-08. |
