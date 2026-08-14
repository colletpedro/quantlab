# Fase 2a — Execução realista e alocação — Requisitos

**Status:** em revisão — gate check 1 (parecer P2 validado; pendências P1–P6 aprovadas pelo autor)
**Versão:** 0.2
**Data:** 2026-08-14
**Próximo gate:** design da Fase 2a (`specs/fase-2a-design.md`, não iniciado)
**Antecede:** Fase 2b (venda a descoberto com margem, walk-forward, buy-stop e entradas condicionais de compra)

> **Nota de escopo.** A Fase 2 foi dividida em 2a e 2b. O critério da divisão é a
> contabilidade: 2a **estende** as regras da Fase 1 (N posições em vez de 1, mesmos
> invariantes de sinal); 2b **substitui** o invariante ENG-04.4 por um de margem, o que
> é mudança de natureza diferente e merece gate próprio. Walk-forward fica em 2b porque
> consome o engine — rodar centenas de backtests sobre um engine que ainda vai mudar é
> retrabalho garantido. Buy-stop e entradas condicionais de compra ficam em 2b por
> decisão do autor (P2): na 2a, stop significa **sell-stop protetor de posição longa
> aberta**, apenas.

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
- Ordens limitada e sell-stop protetor, além de mercado
- Bracket (par limite + stop na mesma intenção) via estratégias condicionais (RF-SIG-01)
- Modelo de custos expandido (fixo, percentual, mínimo por ordem)
- Position sizing explícito, com política plugável
- Portfólio multi-ativo com caixa compartilhado
- Alinhamento de calendário entre séries de históricos distintos
- Métricas de portfólio: exposição, turnover, contribuição por ativo
- Contadores de mecanismo no relatório: stops disparados, ambiguidade intrabarra e
  ordens não atendidas por caixa (RF-MET-05)

**Fora:**
- Venda a descoberto, margem, aluguel — Fase 2b
- Walk-forward e otimização de parâmetros — Fase 2b
- **Buy-stop e entradas condicionais de compra — Fase 2b (decisão P2).** Na 2a, stop é
  apenas sell-stop protetor de posição longa aberta
- Persistência de ordem limitada por `n` barras — fora da 2a (decisão Q2); na 2a, limite
  não executado cancela ao fim da barra
- Redis — adiado até existir problema de performance medido (ADR-0003); a Fase 4 é
  o momento provável, com a API
- Fracionário, alavancagem, opções, dados intraday

## 3. Glossário

| Termo | Definição operacional |
|---|---|
| **Slippage** | Diferença entre o preço observado na decisão e o preço efetivamente executado. Aplica-se apenas a ordens a mercado (RF-SLP-04). |
| **ADV** | Average Daily Volume — volume médio negociado por pregão, janela de 20 pregões do **próprio ativo** terminando na barra de execução (configurável). |
| **Participação** | Razão entre o tamanho da ordem e o ADV. Ordem grande relativa ao ADV move o preço contra quem executa; acima do limite, a **quantidade** é cortada (não o preço). |
| **Ordem limitada** | Executa apenas a um preço igual ou melhor que o limite. Pode não executar; na 2a, não executada cancela ao fim da barra. |
| **Sell-stop** | Ordem stop de venda que protege uma posição longa aberta: vira ordem a mercado quando o preço cai ao gatilho. Único tipo de stop da 2a. |
| **Bracket** | Par de ordens (limite de entrada + sell-stop de proteção) derivados da **mesma intenção** da estratégia (RF-SIG-01). |
| **Intenção** | A decisão da estratégia (sinal + metadados condicionais, se houver). A estratégia emite intenção; o engine decide execução e tamanho (ENG-05.2). |
| **Exposição** | Fração do patrimônio alocada em posições, o complemento do caixa ocioso. Exposição média = média diária de `(Σ qtyᵢ × closeᵢ) / equity` (RF-MET-04). |
| **Turnover** | Volume financeiro negociado no período dividido pelo patrimônio médio, anualizado conforme RF-MET-04. Mede giro. |
| **Patrimônio médio** | Média aritmética diária da equity sobre as `n_barras` do backtest. Mesma definição para estratégia e benchmark (RF-MET-04). |
| **Rebalanceamento** | Ajuste de posições existentes para restaurar pesos-alvo; na 2a, disparado apenas por mudança no número de posições abertas (RF-SIZ-03). |
| **Contadores de mecanismo** | Bloco do relatório que agrega eventos de mecanismo do engine: stops disparados, ambiguidades intrabarra e ordens não atendidas por caixa (RF-MET-05). |

---

## 4. Requisitos funcionais

### 4.1 Slippage (RF-SLP)

**RF-SLP-01 — Modelo plugável**
Deve existir um contrato único de slippage que o broker consome, com implementações
intercambiáveis sem alteração no broker.

- **CA-01.1** — *Dado* um modelo de slippage, *quando* uma ordem é executada, *então* o
  preço de execução é o preço de referência ajustado pelo modelo, sempre na direção
  desfavorável ao executor, sujeito às restrições do RF-SLP-04 (slippage de preço só em
  ordens a mercado; limite nunca violado).
- **CA-01.2** — *Dado* um modelo novo implementando o contrato, *quando* o backtest roda,
  *então* nenhuma alteração no broker é necessária.
- **CA-01.3** — *Dado* slippage configurado como zero, *quando* o relatório é emitido,
  *então* ele declara explicitamente que o resultado é irrealista, na mesma política de
  ENG-03.2 para custos.

**RF-SLP-02 — Modelo fixo em bps**
- **CA-02.1** — *Dado* `k` bps configurado, *quando* uma compra executa ao preço `p`,
  *então* o preço efetivo é `p × (1 + k/10000)`; venda é `p × (1 − k/10000)`.

**RF-SLP-03 — Modelo por participação no volume**
- **CA-03.1** — *Dado* uma ordem de `q` ações, *quando* o ADV é computado, *então* ele usa
  a janela de 20 pregões do próprio ativo terminando na barra de execução (configurável),
  e o slippage cresce monotonicamente com a razão `q/ADV`.
- **CA-03.2** — *Dado* que o ADV não está disponível (histórico insuficiente na janela de
  cálculo), *quando* o modelo é aplicado, *então* ele recai para o modelo fixo e emite
  aviso, sem falhar.
- **CA-03.3** — *Dado* que a participação excede um limite configurável (default 10% do
  ADV), *quando* uma **entrada** é gerada — de qualquer tipo de ordem —, *então* a
  quantidade é reduzida ao limite e o corte é registrado no trade com o motivo.
- **CA-03.4** — *Dado* uma saída, *quando* ela executa, *então* ela é integral (decisão
  D3 da Fase 1): o cap de participação **não** se aplica a saídas.
- **CA-03.5** — *Dado* que o corte reduziria a quantidade a menos de 1 ação, *quando* a
  ordem é processada, *então* nenhuma ordem é gerada e o evento é logado.

**RF-SLP-04 — Separação entre corte e slippage de preço** *(novo, S2)*
O corte por participação (RF-SLP-03) reduz **quantidade**; o slippage de preço
(RF-SLP-01/02/03) altera **preço**. São mecanismos distintos, aplicados em etapas
distintas, e custos nunca entram no preço de execução.

- **CA-04.1** — *Dado* uma ordem a mercado, *quando* ela executa, *então* o slippage de
  preço do modelo é aplicado ao preço de referência — e o corte por participação, se
  houver, foi aplicado antes, sobre a quantidade.
- **CA-04.2** — *Dado* uma ordem limitada, *quando* ela executa, *então* o preço de
  execução nunca é pior que o limite (o limite nunca é violado) — slippage de preço
  **não** se aplica a ordens limitadas.
- **CA-04.3** — *Dado* qualquer execução, *quando* o trade é registrado, *então* os
  custos são debitados do caixa e **não** entram no preço de execução; o preço de
  execução é o preço de referência ajustado apenas por slippage.
- **CA-04.4** — *Dado* um sell-stop cujo gatilho é atingido, *quando* a ordem vira a
  mercado (RF-ORD-02), *então* o slippage de preço se aplica à ordem resultante.

### 4.2 Tipos de ordem e ciclo de vida (RF-ORD)

**RF-ORD-01 — Ordem limitada**
- **CA-01.1** — *Dado* uma compra limitada a `L`, *quando* a barra de execução tem
  `low ≤ L`, *então* ela executa ao menor entre `L` e `open`; caso contrário não executa.
- **CA-01.2** — *Dado* uma venda limitada a `L`, *quando* a barra tem `high ≥ L`, *então*
  ela executa ao maior entre `L` e `open`; caso contrário não executa.
- **CA-01.3** — *Dado* uma ordem limitada não executada, *quando* a barra termina, *então*
  ela é **cancelada** (decisão Q2). Persistência por `n` barras fica fora do escopo da 2a.

**RF-ORD-02 — Sell-stop protetor (long-only)**
- **CA-02.1** — *Dado* uma posição longa aberta e um sell-stop em `S`, *quando* a barra
  tem `low ≤ S`, *então* a ordem vira a mercado e executa ao menor entre `S` e `open`,
  com slippage de preço aplicado.
- **CA-02.2** — *Dado* um sell-stop cuja entrada associada nunca executou, *quando* o
  stop é avaliado, *então* ele não ativa: o sell-stop protege apenas posição longa aberta
  (decisão P2).

**RF-ORD-03 — Ambiguidade intrabarra** ⭐
Com barras diárias não se conhece o caminho do preço dentro do pregão. Quando limite e
stop do mesmo ativo seriam ambos tocados na mesma barra, a ordem de execução é
indeterminada. O bracket (RF-SIG-01) torna o caso concreto: a mesma intenção carrega um
limite e um stop que podem ser ambos tocados na mesma barra.

- **CA-03.1** — *Dado* que limite e stop seriam ambos tocados na mesma barra, *quando* a
  execução é resolvida, *então* o sistema assume o **pior caso para o executor** (o stop
  primeiro) e registra a ambiguidade no trade.
- **CA-03.2** — *Dado* qualquer backtest que tenha encontrado ambiguidade intrabarra,
  *quando* o relatório é emitido, *então* a contagem de ocorrências aparece no bloco
  "contadores de mecanismo" (RF-MET-05).
- **CA-03.3** — *Dado* um bracket (par limite + stop da mesma intenção), *quando* limite
  e stop seriam ambos tocados na mesma barra, *então* a resolução segue CA-03.1 e a
  ambiguidade é registrada no trade — não há caminho em que "ambos executam".

**RF-ORD-04 — Ciclo de vida de ordens** *(novo, S3)*
- **CA-04.1** — *Dado* uma intenção `EXIT` para o ativo X, *quando* ela é processada,
  *então* **todas** as ordens pendentes de X são canceladas — incluindo sell-stops — e
  nenhuma delas executa depois.
- **CA-04.2** — *Dado* que a estratégia emite uma intenção nova para X com ordens ainda
  pendentes da intenção anterior, *quando* ela é processada, *então* a última intenção
  vence: as pendentes anteriores são canceladas e substituídas.
- **CA-04.3** — *Dado* qualquer compra, *quando* ela executa, *então* ela usa o caixa
  disponível — não há reserva de caixa para ordens futuras.
- **CA-04.4** — *Dado* qualquer execução originada por limite ou stop, *quando* o `Trade`
  é criado, *então* ele registra o `decision_date` da intenção que originou a ordem — a
  ordem é preexistente à barra de execução e isso é auditável pelo `decision_date` gravado
  no Trade (decisões P1/P6).

### 4.3 Estratégias condicionais (RF-SIG)

**RF-SIG-01 — Contrato ConditionalStrategy** *(novo, S1)*
A estratégia continua emitindo apenas intenção (ENG-05.2 da Fase 1). Estratégias que
precisam de ordens condicionais implementam um Protocol opcional, `ConditionalStrategy`,
que anexa à intenção metadados com o par **limite + stop na mesma intenção** (bracket). O
contrato é retrocompatível: `Signal`/`Strategy` da Fase 1 ficam intocados.

- **CA-01.1** — *Dado* uma estratégia que implementa apenas `Strategy` da Fase 1, *quando*
  o backtest multi-ativo roda, *então* ela funciona sem qualquer alteração — o protocolo
  condicional é opcional.
- **CA-01.2** — *Dado* uma estratégia que implementa `ConditionalStrategy`, *quando* ela
  emite uma intenção com bracket, *então* os metadados da intenção carregam o par
  limite + stop **juntos**, derivados da mesma intenção.
- **CA-01.3** — *Dado* uma intenção com bracket, *quando* o engine a processa, *então* as
  ordens de limite e de stop derivadas dela compartilham o mesmo `decision_date` da
  intenção.
- **CA-01.4** — *Dado* uma nova estratégia condicional, *quando* o backtest roda, *então*
  nenhuma alteração no engine é necessária.

### 4.4 Custos (RF-CST)

**RF-CST-01 — Modelo expandido**
A sequência de redução de quantidade é fixa e determinística:
**SIZING → CAP DE PARTICIPAÇÃO (Q4) → CONVERSÃO EM INTEIRAS (RF-SIZ-01) → AJUSTE POR
CAIXA/CUSTOS**. O trade registra qual etapa causou o corte (reserva R1).

- **CA-01.1** — *Dado* custo fixo `f`, percentual `p` e mínimo `m` configurados, *quando*
  uma ordem de notional `N` executa, *então* o custo é `max(f + p×N, m)`.
- **CA-01.2** — *Dado* o custo, *quando* ele torna a ordem inviável (caixa insuficiente
  após custo), *então* a quantidade é reduzida até caber, ou a ordem é cancelada se nem
  uma ação couber.
- **CA-01.3** — *Dado* um sinal cuja quantidade final é menor que a intenção original,
  *quando* o trade é registrado, *então* ele identifica qual etapa da sequência causou o
  corte — e a sequência é sempre aplicada na ordem fixa acima.

### 4.5 Position sizing (RF-SIZ)

**RF-SIZ-01 — Política plugável**
A estratégia continua emitindo apenas intenção (ENG-05.2 da Fase 1). O tamanho é decidido
por uma política de sizing, plugável, que o engine consulta.

- **CA-01.1** — *Dado* uma política nova implementando o contrato, *quando* o backtest
  roda, *então* nenhuma alteração no engine ou nas estratégias é necessária.
- **CA-01.2** — *Dado* qualquer política, *quando* ela devolve um alvo, *então* o alvo é
  convertido em quantidade inteira pelo broker (3ª etapa da sequência de RF-CST-01), antes
  do ajuste por caixa e custos (4ª etapa).

**RF-SIZ-02 — Peso fixo `1/N`** *(default)*
`N` = número de ativos do **run**, fixado no início (o conjunto passado ao backtest),
independente da disponibilidade de dados — determinístico. Estratégia e benchmark usam o
**mesmo** `N` (decisões P3/Q1).

- **CA-02.1** — *Dado* um universo de `N` ativos declarado no run, *quando* uma entrada
  ocorre, *então* o alvo é `patrimônio_atual / N`, independentemente de quantas posições
  estão abertas, com `N` fixado no início do run.
- **CA-02.2** — *Dado* que poucos sinais estão ativos, *quando* o estado é inspecionado,
  *então* o caixa ocioso é reportado, não realocado.
- **CA-02.3** — *Dado* `N = 1`, *quando* uma entrada ocorre, *então* a regra `1/N`
  degenera em all-in — equivalente à decisão D1 da Fase 1.
- **CA-02.4** — *Dado* um ativo do run que nunca teve barra na janela, *quando* o sizing é
  computado, *então* ele conta no `N` mas nunca recebe alvo: contribui **zero**, é
  reportado como **não-negociado**, e a conciliação de CA-04.2 (RF-POR-04) não abre buraco
  (reserva R2).

**RF-SIZ-03 — Peso igual entre posições abertas** *(opcional, configurável)*
Rebalanceamento é disparado **apenas por mudança de `k`** (número de posições abertas) —
não por deriva de preço — e executa no próximo open (ADR-0002). O limiar gateia o ajuste
(decisão S4).

- **CA-03.1** — *Dado* `k` posições abertas, *quando* uma entrada ou saída altera `k`,
  *então* um evento de rebalanceamento é gerado para o próximo open (ADR-0002).
- **CA-03.2** — *Dado* que esta política gera trades não solicitados pela estratégia,
  *quando* o relatório é emitido, *então* os trades de rebalanceamento são contados
  separadamente dos trades de sinal.
- **CA-03.3** — *Dado* um limiar de tolerância configurável (default 1 pp absoluto do
  patrimônio), *quando* para todo ativo `|wᵢ − 1/k|` está abaixo do limiar, *então*
  nenhum trade de rebalanceamento é gerado — ruído de preço não gera giro infinito.
- **CA-03.4** — *Dado* que `k` não mudou, *quando* os preços se moveram, *então* nenhum
  rebalanceamento é disparado.

**RF-SIZ-04 — Contrato do sizer** *(novo, S5)*
O sizer recebe patrimônio, caixa, posições, último close por ativo e `N`; devolve uma
**fração**; a conversão em quantidade é do broker (RF-SIZ-01). Invariante: `k ≤ N`.

- **CA-04.1** — *Dado* uma política nova implementando o contrato, *quando* o backtest
  roda, *então* nenhuma alteração no engine ou nas estratégias é necessária.
- **CA-04.2** — *Dado* o contrato (patrimônio, caixa, posições, último close por ativo,
  `N`), *quando* o sizer é invocado, *então* ele devolve uma fração e o engine a converte
  em quantidade conforme a sequência de RF-CST-01.
- **CA-04.3** — *Dado* qualquer política, *quando* o estado é inspecionado, *então* o
  número de posições abertas distintas `k` nunca excede `N`.

### 4.6 Portfólio multi-ativo (RF-POR)

**RF-POR-01 — Caixa compartilhado**
- **CA-01.1** — *Dado* `N` ativos operando, *quando* qualquer ordem executa, *então* ela
  debita ou credita o mesmo caixa; não há caixa por ativo.
- **CA-01.2** — *Dado* dois sinais de entrada na mesma barra com caixa insuficiente para
  ambos, *quando* a execução ocorre, *então* a ordem de atendimento é determinística e
  declarada (por ticker, em ordem alfabética); a ordem não atendida é logada **e contada**
  no bloco "contadores de mecanismo" do relatório (decisão Q5).

**RF-POR-02 — Alinhamento de calendário** ⭐
Séries de ativos distintos têm primeiras barras distintas (IPO), e podem ter buracos
(halt, deslistagem). O calendário-união decide apenas em quais datas o engine **acorda**;
ele não fabrica barras (decisão S10).

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
  (§4.6 do design) vale somando sobre todos os ativos. **Teste de conciliação obrigatório
  no run de 20 ativos.**
- **CA-04.3** — *Dado* qualquer instante, *então* `caixa ≥ 0` e `quantidade_i ≥ 0` para
  todo `i`. *(Este invariante é substituído na Fase 2b.)*

**RF-POR-05 — Índice por ativo e fronteira de mutação** *(novo, S10)*
- **CA-05.1** — *Dado* a `MarketView` do ativo X, *quando* a estratégia acessa o índice
  `i`, *então* `i` indexa o array do **próprio ativo** X — não um calendário mesclado
  global.
- **CA-05.2** — *Dado* uma data do calendário-união em que X não tem barra, *quando* o
  engine acorda, *então* não há decisão nem execução para X e nenhuma barra artificial é
  fabricada; ordens pendentes de X aguardam a próxima barra real de X.
- **CA-05.3** — *Dado* uma ordem pendente de X, *quando* a próxima barra de X chega,
  *então* ela executa no open dessa barra (ADR-0002 por ativo), qualquer que seja a
  distância em datas do calendário-união.
- **CA-05.4** — *Dado* o teste de mutação anti-lookahead (ENG-01.2) no run multi-ativo,
  *quando* barras futuras de um ativo são alteradas, *então* as intenções e execuções de
  todos os ativos permanecem idênticas — a fronteira da mutação é **por ativo**.

### 4.7 Métricas e relatório (RF-MET)

**RF-MET-01 — Métricas de portfólio**
Além das métricas da Fase 1 sobre a equity agregada: exposição média, turnover anualizado,
número de trades por ativo, e contribuição de PnL por ativo. As fórmulas estão em
RF-MET-04.

- **CA-01.1** — *Dado* o fim do backtest, *quando* as contribuições por ativo são somadas,
  *então* elas conciliam com o PnL total.
- **CA-01.2** — *Dado* o fim do backtest, *quando* exposição média e turnover anualizado
  são computados, *então* os valores seguem as fórmulas de RF-MET-04.

**RF-MET-02 — Benchmark de portfólio**
O benchmark compra **cada ativo** na primeira barra negociável do próprio ativo, herda
**todas** as regras de entrada (custos, slippage, cap de participação), usa o **mesmo** `N`
do run (P3), mantém caixa ocioso, não rebalanceia e reporta deslistagem travada
(decisão S6).

- **CA-02.1** — *Dado* um backtest multi-ativo, *quando* o relatório é emitido, *então* o
  benchmark é a carteira `1/N` comprada-e-segurada sobre os mesmos ativos, com as mesmas
  regras de entrada (custos, slippage, cap) e o mesmo `N`.
- **CA-02.2** — *Dado* um ativo cuja série começa depois do início do backtest, *quando* o
  benchmark é construído, *então* ele compra o ativo na primeira barra negociável do
  próprio ativo.
- **CA-02.3** — *Dado* um ativo deslistado no meio da janela, *quando* o backtest termina,
  *então* a posição do benchmark é reportada travada — igual à regra da estratégia
  (RF-POR-02 CA-02.3) — e a ocorrência aparece no relatório.
- **CA-02.4** — *Dado* o benchmark, *quando* ele é construído, *então* ele não rebalanceia
  e mantém o caixa ocioso (sem realocação de caixa).

**RF-MET-03 — Vieses atualizados**
- **CA-03.1** — *Quando* o relatório é emitido, *então* a seção fixa de vieses contém:
  ambiguidade intrabarra resolvida por pior caso; slippage modelado mas não calibrado
  contra execuções reais; ausência de impacto permanente de mercado; **fill integral ao
  preço limite é otimista** — a ordem pode não preencher ou preencher parcialmente (S2); e
  **ordem de atendimento alfabética com caixa insuficiente é determinística e neutra, mas
  qualquer regra de atendimento é seleção com viés** (Q5).

**RF-MET-04 — Fórmulas** *(novo, S9/P4)*
Definições únicas, **as mesmas** para estratégia e benchmark:

- `turnover_anualizado = (Σ|notional_compra| + Σ|notional_venda|) / (2 × patrimônio_médio) × (252 / n_barras)`
- `patrimônio_médio` = média aritmética diária da equity sobre as `n_barras`
- `exposição_média` = média diária de `(Σ qtyᵢ × closeᵢ) / equity`

- **CA-04.1** — *Dado* uma fixture sintética com trades e equity calculáveis no papel,
  *quando* o turnover anualizado é computado, *então* o valor bate com a fórmula fechada.
- **CA-04.2** — *Dado* estratégia e benchmark no mesmo run, *quando* as métricas são
  computadas, *então* ambos usam exatamente as mesmas definições (patrimônio médio e
  turnover).
- **CA-04.3** — *Dado* `n_barras`, *quando* o turnover é anualizado, *então* o fator
  `252 / n_barras` é aplicado conforme a fórmula.
- **CA-04.4** — *Dado* uma fixture sintética, *quando* a exposição média é computada,
  *então* o valor bate com a média diária de `(Σ qtyᵢ × closeᵢ) / equity`.

**RF-MET-05 — Contadores de mecanismo** *(novo, P6)*
O relatório tem um bloco **"contadores de mecanismo"** agregando eventos do engine: stops
disparados (categoria própria), ambiguidades intrabarra (RF-ORD-03 CA-03.2) e ordens não
atendidas por caixa (Q5). A auditoria do stop se apoia no `decision_date` gravado no Trade
(RF-ORD-04 CA-04.4).

- **CA-05.1** — *Dado* um backtest com stops disparados, *quando* o relatório é emitido,
  *então* os stops aparecem no bloco como categoria própria.
- **CA-05.2** — *Dado* um backtest com ambiguidade intrabarra, *quando* o relatório é
  emitido, *então* a contagem de ocorrências aparece no bloco.
- **CA-05.3** — *Dado* um backtest com ordens não atendidas por caixa, *quando* o
  relatório é emitido, *então* a contagem aparece no bloco.

### 4.8 Herança de requisitos não funcionais (RF-RNF)

**RF-RNF-01 — Cláusula de herança** *(novo, S7)*
- **CA-01.1** — *Dado* os RNF-01, RNF-03, RNF-05, RNF-06, RNF-07 e RNF-08 da Fase 1,
  *quando* a 2a é implementada, *então* eles valem sem alteração — os testes que os provam
  na Fase 1 continuam passando no run multi-ativo.
- **CA-01.2** — *Dado* o piso de cobertura, *quando* o CI roda, *então* ele é de **85%**
  sobre `engine/`, `analytics/` e módulos novos (broker/slippage/sizing, se virarem
  pacotes próprios) — supersede o piso de 80% da Fase 1 (RNF-02).
- **CA-01.3** — *Dado* o RNF-04 (30 s), *quando* ele é medido, *então* a medição cobre
  **apenas o cômputo** — serialização do relatório e renderização do gráfico ficam fora, e
  isso é declarado na spec e no relatório (decisão P5).

---

## 5. Requisitos não funcionais

- **RNF-01 — Determinismo.** Mesmo estado de banco + mesmos parâmetros ⇒ resultado
  idêntico. Sem aleatoriedade não semeada. *(herdado da Fase 1)*
- **RNF-02 — Cobertura.** Mínimo **85%** em `engine/`, `analytics/` e módulos novos
  (broker/slippage/sizing, se virarem pacotes próprios). Supersede o piso de 80% da Fase 1
  (S7).
- **RNF-03 — Fixtures sintéticas.** Testes de engine e analytics rodam sobre séries
  construídas à mão, com resultado calculável no papel — não sobre dados reais de mercado.
  *(herdado da Fase 1)*
- **RNF-04 — Performance.** Backtest de 20 ativos × 10 anos abaixo de **30 s**, medindo
  **só o cômputo** (execução do engine sobre as séries já lidas) — serialização do
  relatório e renderização do gráfico ficam fora da medição, que é declarada na spec
  (P5). Supersede o RNF-04 da Fase 1 (5 s, ativo único).
- **RNF-05 — Tipagem.** `mypy --strict` mantido no CI. *(herdado da Fase 1)*
- **RNF-06 — Ambiente.** Suíte unitária roda offline, sem rede. *(herdado da Fase 1)*
- **RNF-07 — Datas.** Toda data no sistema é data-calendário naive; nenhuma comparação
  envolve timezone. *(herdado da Fase 1)*
- **RNF-08 — Dinheiro.** Valores monetários usam ponto flutuante, com comparações por
  tolerância explícita. *(herdado da Fase 1)*
- **RNF-09 — Invariantes.** Nenhum invariante da Fase 1 pode ser relaxado sem ADR próprio.

## 6. Premissas

1. Long-only (revisto na 2b).
2. **Stop = sell-stop protetor de posição longa aberta, apenas** (decisão P2). Buy-stop e
   entradas condicionais de compra ficam na 2b, declarados no escopo.
3. Sem alavancagem.
4. Sem fracionário.
5. Capital inicial default 100.000 USD.
6. Moeda única. Sem conversão cambial.
7. Sem imposto.
8. `rf = 0` e dividendos via ajuste de preço (não crédito em caixa) — herdados da Fase 1.
9. Ordens não movem o preço de forma permanente — o slippage modela impacto temporário
   apenas.
10. Ordem limitada não executada cancela ao fim da barra; persistência fica fora da 2a
    (decisão Q2).

## 7. Consolidação herdada da Fase 1 — baseline verificado

O bloco de consolidação (§7 da v0.1: RF-CON-01, RF-CON-02, RF-CON-03) foi
**implementado e verificado** em 2026-08-06 (design v0.9 de
`specs/00-plataforma/fase-1-design.md`, `docs/STATE.md`) — é **baseline verificado, não
escopo novo** (decisão S8). Nada da 2a reabre estes RFs; eles valem como estão:

- **RF-CON-01** — barra do pregão corrente é descartada com aviso, não quarentenada
  (CA-01.1/01.2).
- **RF-CON-02** — relatório auto-suficiente, com parâmetros da estratégia, contagem de
  barras consumidas e datas efetivas de início e fim (CA-02.1/02.2).
- **RF-CON-03** — nota de leitura no README explicando a diferença entre 19/20 em CAGR e
  17/20 em Sharpe (CA-03.1).

## 8. Decisões fechadas — Q1–Q5 e resolução de S1–S10

### Q1–Q5 → D1–D5

| # | Questão | Decisão | Razão |
|---|---|---|---|
| D1 | Default de sizing | `1/N` fixo, com `N` = ativos do run fixado no início (P3). `N = 1` ⇒ all-in (D1 da Fase 1). Peso igual entre abertas fica configurável (RF-SIZ-03) | A alternativa fica disponível para o backtest **medir** a diferença de churn em vez de você adivinhar |
| D2 | Ordem limitada não executada | Cancela ao fim da barra. Persistência por `n` barras fica fora da 2a | Determinismo e simplicidade; persistência reintroduz fila de pendentes entre barras sem necessidade medida |
| D3 | Janela de cálculo do ADV | 20 pregões do próprio ativo, terminando na barra de execução, configurável | Janela curta e local ao ativo; terminar na barra de execução evita lookahead |
| D4 | Limite de participação no volume | 10% do ADV, configurável, aplicado a **entradas** de qualquer tipo de ordem; saída é integral; corte < 1 ação ⇒ sem ordem, logado | O cap protege o pressuposto de ausência de impacto; saída integral preserva D3 da Fase 1 |
| D5 | Ordem de atendimento com caixa insuficiente | Alfabética por ticker, determinística; não-atendidas contadas no relatório; viés declarado (RF-MET-03) | Determinística e neutra; qualquer regra "melhor" seria seleção com viés |

### S1–S10 → requisitos

| S | Resolução | Onde na v0.2 |
|---|---|---|
| S1 | Contrato `ConditionalStrategy` (Protocol opcional, retrocompatível); bracket = par limite + stop na mesma intenção; `Signal`/`Strategy` intocados | RF-SIG-01 |
| S2 | Slippage de preço só em ordem a mercado; limite nunca violado; custos debitam do caixa e não entram no preço de execução; viés "fill integral ao limite é otimista" | RF-SLP-04, RF-MET-03 |
| S3 | Sem reserva de caixa; `EXIT` cancela todas as pendentes do ativo (incluindo stops); última intenção vence | RF-ORD-04 |
| S4 | Rebalance só por mudança de `k`; limiar `|wᵢ − 1/k|` em pp absolutos do patrimônio (default 1 pp) gateia o ajuste; executa no próximo open (ADR-0002) | RF-SIZ-03 |
| S5 | Sizer recebe patrimônio/caixa/posições/último close por ativo/`N`; devolve fração; invariante `k ≤ N` | RF-SIZ-04 |
| S6 | Benchmark compra cada ativo na primeira barra negociável do próprio ativo; herda todas as regras de entrada (custos, slippage, cap); caixa ocioso; sem rebalance; deslistagem travada e reportada | RF-MET-02 |
| S7 | Cláusula de herança de RNFs: RNF-01/03/05/06/07/08 herdados; RNF-02 supersedido (80 → 85%) | RF-RNF-01, §5 |
| S8 | §7 (RF-CON-01/02/03) = baseline verificado (design v0.9, STATE.md 2026-08-06), não escopo novo | §7 |
| S9 | Fórmulas (P4) | RF-MET-04 |
| S10 | `MarketView.i` é índice do array do próprio ativo; calendário-união só decide em quais datas o engine acorda; ordem pendente executa na próxima barra do próprio ativo (ADR-0002 por ativo); fronteira da mutação por ativo | RF-POR-05 |

## 9. Questões em aberto

Nenhuma. Q1–Q5 foram fechadas como D1–D5 e S1–S10 foram incorporados como requisitos
(§8). Nada fica "para depois": o que não é da 2a está declarado no escopo (buy-stop,
persistência de limite, walk-forward, margem).

## 10. Definition of Done

- [ ] Backtest multi-ativo do universo completo (N=20, `config/universe.yml`) roda ponta
      a ponta, estratégia e benchmark
- [ ] Conciliação de CA-04.2 (RF-POR-04) passa no run de 20 ativos
- [ ] Teste de mutação anti-lookahead (ENG-01.2) reformulado para ordens condicionais e
      passado: mutação de barras futuras não altera a intenção emitida pela estratégia
      (sinais e preços de limite/stop); e toda execução originada por limite/stop
      vincula-se a uma ordem preexistente, confirmada via `decision_date` gravado no Trade
      anterior à barra de execução
- [ ] RNF-04 (30 s) medido no run de 20 ativos × 10 anos, apenas o cômputo — serialização
      do relatório e renderização do gráfico fora da medição, como declarado na spec (P5)
- [ ] Um ativo com série truncada no meio da janela testado explicitamente: deslistagem
      travada e reportada, na estratégia e no benchmark
- [ ] Um ativo do run sem nenhuma barra na janela testado explicitamente: conta no `N`,
      contribui zero, reportado como não-negociado, e CA-04.2 concilia sem buraco (R2)
- [ ] Contadores de mecanismo presentes no relatório: stops disparados, ambiguidades
      intrabarra e ordens não atendidas por caixa (RF-MET-05)
- [ ] Cobertura ≥ 85% em `engine/`, `analytics/` e módulos novos; CI verde
- [ ] ADRs escritos para: modelo de slippage escolhido, resolução da ambiguidade
      intrabarra, e política de sizing default
- [ ] Resultado reportado honestamente, comparado contra o `1/N` buy-and-hold

## 11. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.2 | 2026-08-14 | Gate check 1: parecer P2 validado e pendências P1–P6 aprovadas pelo autor. Q1–Q5 fechadas como D1–D5; S1–S10 incorporados como RFs novos (RF-SIG-01, RF-ORD-04, RF-SLP-04, RF-SIZ-04, RF-POR-05, RF-MET-04, RF-MET-05, RF-RNF-01). Emendas em RF-SIZ-02 (N do run, N=1 ⇒ all-in, ativo sem barra), RF-SIZ-03 (S4), RF-ORD-01/02/03 (Q2, P2, bracket), RF-SLP-03 (Q3/Q4), RF-POR-01 (Q5), RF-CST-01 (R1), RF-MET-01/02/03 (P4, S6, vieses). §7 vira baseline verificado (S8). DoD reformulado (P1, P5, R2, RF-MET-05). RNF-02 supersedido para 85% e RNF-04 redefinido (P5/S7). Premissas atualizadas (P2, rf/dividendos). Status draft → em revisão. |
| 0.1 | 2026-08-04 | Rascunho inicial, com Q1–Q5 em aberto |
