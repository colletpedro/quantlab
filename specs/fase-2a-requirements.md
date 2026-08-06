# Fase 2a — Execução realista e alocação — Requisitos

**Status:** draft — aguardando gate check 1
**Versão:** 0.1
**Data:** 2026-08-04
**Antecede:** Fase 2b (venda a descoberto com margem, walk-forward)

> **Nota de escopo.** A Fase 2 foi dividida em 2a e 2b. O critério da divisão é a
> contabilidade: 2a **estende** as regras da Fase 1 (N posições em vez de 1, mesmos
> invariantes de sinal); 2b **substitui** o invariante ENG-04.4 por um de margem, o que
> é mudança de natureza diferente e merece gate próprio. Walk-forward fica em 2b porque
> consome o engine — rodar centenas de backtests sobre um engine que ainda vai mudar é
> retrabalho garantido.

---

## 1. Objetivo

Transformar o backtester single-asset da Fase 1 num simulador de portfólio com execução
realista: custos e slippage parametrizáveis, tipos de ordem além de mercado, alocação
explícita de capital, e N ativos operando simultaneamente sobre um caixa compartilhado.

O objetivo permanece o da Fase 1 — **medir sem mentir**. Cada elemento novo desta fase
existe para tornar o resultado *pior e mais verdadeiro*, não melhor.

## 2. Escopo

**Dentro:**
- Modelos de slippage plugáveis (fixo em bps, e proporcional à participação no volume)
- Ordens limitada e stop, além de mercado
- Modelo de custos expandido (fixo, percentual, mínimo por ordem)
- Position sizing explícito, com política plugável
- Portfólio multi-ativo com caixa compartilhado
- Alinhamento de calendário entre séries de históricos distintos
- Métricas de portfólio: exposição, turnover, contribuição por ativo
- Consolidação das pendências herdadas da Fase 1 (§7)

**Fora:**
- Venda a descoberto, margem, aluguel — Fase 2b
- Walk-forward e otimização de parâmetros — Fase 2b
- Redis — adiado até existir problema de performance medido (ADR-0003); a Fase 4 é
  o momento provável, com a API
- Fracionário, alavancagem, opções, dados intraday

## 3. Glossário

| Termo | Definição operacional |
|---|---|
| **Slippage** | Diferença entre o preço observado na decisão e o preço efetivamente executado. |
| **ADV** | Average Daily Volume — volume médio negociado por pregão, janela configurável. |
| **Participação** | Razão entre o tamanho da ordem e o ADV. Ordem grande relativa ao ADV move o preço contra quem executa. |
| **Ordem limitada** | Executa apenas a um preço igual ou melhor que o limite. Pode não executar. |
| **Ordem stop** | Vira ordem a mercado quando o preço atravessa o gatilho. Usada para conter perda. |
| **Exposição** | Fração do patrimônio alocada em posições, o complemento do caixa ocioso. |
| **Turnover** | Volume financeiro negociado no período dividido pelo patrimônio médio. Mede giro. |
| **Rebalanceamento** | Ajuste de posições existentes para restaurar pesos-alvo. |

---

## 4. Requisitos funcionais

### 4.1 Slippage (RF-SLP)

**RF-SLP-01 — Modelo plugável**
Deve existir um contrato único de slippage que o broker consome, com implementações
intercambiáveis sem alteração no broker.

- **CA-01.1** — *Dado* um modelo de slippage, *quando* uma ordem é executada, *então* o
  preço de execução é o preço de referência ajustado pelo modelo, sempre na direção
  desfavorável ao executor.
- **CA-01.2** — *Dado* um modelo novo implementando o contrato, *quando* o backtest roda,
  *então* nenhuma alteração no broker é necessária.
- **CA-01.3** — *Dado* slippage configurado como zero, *quando* o relatório é emitido,
  *então* ele declara explicitamente que o resultado é irrealista, na mesma política de
  ENG-03.2 para custos.

**RF-SLP-02 — Modelo fixo em bps**
- **CA-02.1** — *Dado* `k` bps configurado, *quando* uma compra executa ao preço `p`,
  *então* o preço efetivo é `p × (1 + k/10000)`; venda é `p × (1 − k/10000)`.

**RF-SLP-03 — Modelo por participação no volume**
- **CA-03.1** — *Dado* uma ordem de `q` ações e o ADV do ativo na data, *quando* o
  slippage é computado, *então* ele cresce monotonicamente com a razão `q/ADV`.
- **CA-03.2** — *Dado* que o ADV não está disponível (histórico insuficiente na janela de
  cálculo), *quando* o modelo é aplicado, *então* ele recai para o modelo fixo e emite
  aviso, sem falhar.
- **CA-03.3** — *Dado* que a participação excede um limite configurável, *quando* a ordem
  é gerada, *então* ela é reduzida ao limite e o corte é registrado no trade.

### 4.2 Tipos de ordem (RF-ORD)

**RF-ORD-01 — Ordem limitada**
- **CA-01.1** — *Dado* uma compra limitada a `L`, *quando* a barra de execução tem
  `low ≤ L`, *então* ela executa ao menor entre `L` e `open`; caso contrário não executa.
- **CA-01.2** — *Dado* uma venda limitada a `L`, *quando* a barra tem `high ≥ L`, *então*
  ela executa ao maior entre `L` e `open`; caso contrário não executa.
- **CA-01.3** — *Dado* uma ordem limitada não executada, *quando* a barra termina, *então*
  o comportamento é o configurado: cancelar ou permanecer viva por `n` barras.

**RF-ORD-02 — Ordem stop**
- **CA-02.1** — *Dado* um stop de venda em `S`, *quando* a barra tem `low ≤ S`, *então*
  ela vira ordem a mercado e executa ao menor entre `S` e `open`, com slippage aplicado.

**RF-ORD-03 — Ambiguidade intrabarra** ⭐
Com barras diárias não se conhece o caminho do preço dentro do pregão. Quando limite e
stop do mesmo ativo seriam ambos tocados na mesma barra, a ordem de execução é
indeterminada.

- **CA-03.1** — *Dado* que limite e stop seriam ambos tocados na mesma barra, *quando* a
  execução é resolvida, *então* o sistema assume o **pior caso para o executor** (o stop
  primeiro) e registra a ambiguidade no trade.
- **CA-03.2** — *Dado* qualquer backtest que tenha encontrado ambiguidade intrabarra,
  *quando* o relatório é emitido, *então* a contagem de ocorrências aparece nele.

### 4.3 Custos (RF-CST)

**RF-CST-01 — Modelo expandido**
- **CA-01.1** — *Dado* custo fixo `f`, percentual `p` e mínimo `m` configurados, *quando*
  uma ordem de notional `N` executa, *então* o custo é `max(f + p×N, m)`.
- **CA-01.2** — *Dado* o custo, *quando* ele torna a ordem inviável (caixa insuficiente
  após custo), *então* a quantidade é reduzida até caber, ou a ordem é cancelada se nem
  uma ação couber.

### 4.4 Position sizing (RF-SIZ)

**RF-SIZ-01 — Política plugável**
A estratégia continua emitindo apenas intenção (ENG-05.2 da Fase 1). O tamanho é decidido
por uma política de sizing, plugável, que o engine consulta.

- **CA-01.1** — *Dado* uma política nova implementando o contrato, *quando* o backtest
  roda, *então* nenhuma alteração no engine ou nas estratégias é necessária.
- **CA-01.2** — *Dado* qualquer política, *quando* ela devolve um alvo, *então* o alvo é
  convertido em quantidade inteira pelo broker, respeitando caixa e custos.

**RF-SIZ-02 — Peso fixo `1/N`** *(default)*
- **CA-02.1** — *Dado* um universo de `N` ativos declarado, *quando* uma entrada ocorre,
  *então* o alvo é `patrimônio_atual / N`, independentemente de quantas posições estão
  abertas.
- **CA-02.2** — *Dado* que poucos sinais estão ativos, *quando* o estado é inspecionado,
  *então* o caixa ocioso é reportado, não realocado.

**RF-SIZ-03 — Peso igual entre posições abertas** *(opcional, configurável)*
- **CA-03.1** — *Dado* `k` posições abertas, *quando* uma entrada ou saída altera `k`,
  *então* todas as posições são ajustadas para `patrimônio/k`.
- **CA-03.2** — *Dado* que esta política gera trades não solicitados pela estratégia,
  *quando* o relatório é emitido, *então* os trades de rebalanceamento são contados
  separadamente dos trades de sinal.
- **CA-03.3** — *Dado* um limiar de tolerância configurável, *quando* o desvio do peso-alvo
  é menor que o limiar, *então* nenhum rebalanceamento é disparado. Sem isso, ruído de
  preço gera giro infinito.

### 4.5 Portfólio multi-ativo (RF-POR)

**RF-POR-01 — Caixa compartilhado**
- **CA-01.1** — *Dado* `N` ativos operando, *quando* qualquer ordem executa, *então* ela
  debita ou credita o mesmo caixa; não há caixa por ativo.
- **CA-01.2** — *Dado* dois sinais de entrada na mesma barra com caixa insuficiente para
  ambos, *quando* a execução ocorre, *então* a ordem de atendimento é determinística e
  declarada (por ticker, em ordem alfabética), e a ordem não atendida é logada.

**RF-POR-02 — Alinhamento de calendário** ⭐
S�ries de ativos distintos têm primeiras barras distintas (IPO), e podem ter buracos
(halt, deslistagem).

- **CA-02.1** — *Dado* `N` séries, *quando* o backtest inicia, *então* o calendário do
  backtest é a **união** das datas de todas as séries.
- **CA-02.2** — *Dado* uma data em que um ativo não tem barra, *quando* o engine processa
  essa data, *então* nenhuma decisão nem execução ocorre para aquele ativo, e a posição
  existente é marcada a mercado pelo **último fechamento conhecido**.
- **CA-02.3** — *Dado* um ativo cuja série termina antes do fim do backtest (deslistagem),
  *quando* o backtest termina, *então* a posição é reportada como travada, não liquidada
  a preço inventado, e a ocorrência aparece no relatório.
- **CA-02.4** — *Dado* que a estratégia de um ativo recebe sua `MarketView`, *quando* a
  barra é processada, *então* a view contém **apenas** as barras daquele ativo, sem
  preenchimento artificial de datas ausentes.

**RF-POR-03 — Uma instância de estratégia por ativo**
- **CA-03.1** — *Dado* `N` ativos, *quando* o backtest inicia, *então* `N` instâncias
  independentes da estratégia são criadas, cada uma vendo apenas o seu ativo.
- **CA-03.2** — *Dado* o contrato `Strategy` da Fase 1, *quando* o multi-ativo é
  introduzido, *então* o contrato **não muda**. Estratégias da Fase 1 rodam sem alteração.

**RF-POR-04 — Invariantes estendidos**
- **CA-04.1** — *Dado* qualquer instante, *então* `equity = caixa + Σ(quantidade_i ×
  último_fechamento_conhecido_i)`.
- **CA-04.2** — *Dado* o fim do backtest, *então* a identidade de conciliação da Fase 1
  (§4.6 do design) vale somando sobre todos os ativos.
- **CA-04.3** — *Dado* qualquer instante, *então* `caixa ≥ 0` e `quantidade_i ≥ 0` para
  todo `i`. *(Este invariante é substituído na Fase 2b.)*

### 4.6 Métricas e relatório (RF-MET)

**RF-MET-01 — Métricas de portfólio**
Além das métricas da Fase 1 sobre a equity agregada: exposição média, turnover anualizado,
número de trades por ativo, e contribuição de PnL por ativo.

- **CA-01.1** — *Dado* o fim do backtest, *quando* as contribuições por ativo são somadas,
  *então* elas conciliam com o PnL total.

**RF-MET-02 — Benchmark de portfólio**
- **CA-02.1** — *Dado* um backtest multi-ativo, *quando* o relatório é emitido, *então* o
  benchmark é a carteira `1/N` comprada-e-segurada sobre os mesmos ativos, com os mesmos
  custos e slippage de entrada, alinhada à primeira barra negociável.

**RF-MET-03 — Vieses atualizados**
- **CA-03.1** — *Quando* o relatório é emitido, *então* a seção fixa de vieses incorpora
  os itens novos: ambiguidade intrabarra resolvida por pior caso, slippage modelado mas
  não calibrado contra execuções reais, e ausência de impacto permanente de mercado.

---

## 5. Requisitos não funcionais

- **RNF-01** — Determinismo preservado. Mesma base + mesmos parâmetros ⇒ resultado idêntico.
- **RNF-02** — Cobertura ≥ 85% em `engine/` e `analytics/`. O piso sobe: o código agora
  movimenta dinheiro em N ativos.
- **RNF-03** — Fixtures sintéticas com derivação auditável no próprio teste.
- **RNF-04** — Backtest de 20 ativos × 10 anos abaixo de 30 s.
- **RNF-05** — `mypy --strict` mantido.
- **RNF-06** — Suíte unitária offline.
- **RNF-07** — Nenhum invariante da Fase 1 pode ser relaxado sem ADR próprio.

## 6. Premissas

1. Long-only (revisto na 2b). 2. Sem alavancagem. 3. Sem fracionário. 4. Capital inicial
default 100.000 USD. 5. Moeda única. 6. Sem imposto. 7. Ordens não movem o preço de forma
permanente — o slippage modela impacto temporário apenas.

## 7. Consolidação herdada da Fase 1

Entra como primeiro bloco de tarefas, antes de qualquer funcionalidade nova.

**RF-CON-01 — Barra do pregão corrente**
A ingestão que vai até "hoje" traz a sessão em formação, cujos preços são parciais e cujo
`close` pode vir `NaN`. Hoje ela é quarentenada, o que faz toda ingestão reportar `N`
quarentenas — ruído permanente que treina o operador a ignorar a quarentena.

- **CA-01.1** — *Dado* uma barra cuja data é igual ou posterior à data UTC da execução,
  *quando* a ingestão processa, *então* ela é **descartada com aviso**, não quarentenada.
  Barra incompleta não é barra inválida.
- **CA-01.2** — *Quando* o descarte ocorre, *então* o `ingestion_run` registra a contagem
  em campo próprio, separado das quarentenas.

**RF-CON-02 — Relatório auto-suficiente**
Hoje os parâmetros da estratégia existem apenas no nome do arquivo, e a contagem de barras
não existe fora do Mongo. O artefato público não permite auditar o que o produziu.

- **CA-02.1** — *Quando* o relatório é serializado, *então* ele contém os parâmetros da
  estratégia, a contagem de barras consumidas, e as datas efetivas de início e fim.
- **CA-02.2** — *Dado* um relatório JSON isolado do repositório, *quando* alguém o lê,
  *então* é possível reconstruir integralmente a configuração do run.

**RF-CON-03 — Nota de leitura no README**
- **CA-03.1** — *Quando* o README reporta o resultado, *então* ele explica a diferença
  entre 19/20 em CAGR e 17/20 em Sharpe: sair do mercado corta drawdown junto com retorno,
  e isso é a assinatura da classe de estratégia, não um achado.

## 8. Definition of Done

- [ ] Bloco de consolidação (§7) concluído
- [ ] Backtest multi-ativo do universo completo roda ponta a ponta
- [ ] Conciliação de CA-04.2 passa com N ativos
- [ ] Teste de ENG-01.2 (mutação de barras futuras) continua passando, agora multi-ativo
- [ ] Um ativo com série truncada no meio da janela testado explicitamente
- [ ] Cobertura ≥ 85%, CI verde
- [ ] ADRs escritos para: modelo de slippage escolhido, resolução da ambiguidade
      intrabarra, e política de sizing default
- [ ] Resultado reportado honestamente, comparado contra o `1/N` buy-and-hold

## 9. Questões abertas

| # | Questão | Proposta |
|---|---|---|
| Q1 | Default de sizing: `1/N` fixo ou peso igual entre abertas? | `1/N` fixo. A outra fica configurável, para que o backtest **meça** a diferença de churn em vez de você adivinhar |
| Q2 | Ordem limitada não executada: cancela ao fim da barra ou persiste? | Cancela por default; persistência por `n` barras é opção |
| Q3 | Janela de cálculo do ADV | 20 pregões, configurável |
| Q4 | Limite de participação no volume | 10% do ADV, configurável |
| Q5 | Ordem de atendimento com caixa insuficiente | Alfabética por ticker. Determinística e neutra; qualquer regra "melhor" seria seleção com viés |
