# Fase 2b — Venda a descoberto, margem e walk-forward — Requisitos

**Status:** em revisão — v0.1 revisada pelo tech lead do web; resoluções R1–R7 aplicadas
**Versão:** 0.2
**Data:** 2026-08-14
**Próximo gate:** aprovação do gate 1 (checklist: CAs falseáveis nomeados, questões abertas vazias, premissas e vieses declarados)
**Antecede:** Fase 3 (analytics e risco: Sortino, VaR, correlação, Black-Scholes, Monte Carlo)

> **Nota de escopo.** A Fase 2 foi dividida em 2a e 2b. O critério da divisão é a
> contabilidade: 2a **estendeu** as regras da Fase 1 (N posições em vez de 1, mesmos
> invariantes de sinal); 2b **substitui** o invariante de posição longa (ENG-04.4 da
> Fase 1 / RF-POR-04 CA-04.3 da 2a) por um invariante de **margem** — mudança de natureza
> diferente, que merece gate e ADR próprios (RNF-09 da 2a). Walk-forward vive na 2b porque
> consome o engine estável: rodar centenas de backtests sobre um engine que ainda mudaria
> seria retrabalho garantido. Buy-stop e entradas condicionais de compra foram adiados
> para a 2b por decisão do autor (P2 da 2a).

---

## 1. Objetivo

Estender o simulador multi-ativo da 2a para operar **long + short com margem**, com
execução realista de venda a descoberto (aluguel), liquidação forçada determinística
quando a margem é violada, buy-stop (adiado da 2a), e **walk-forward** — otimização de
parâmetros in-sample com avaliação honesta out-of-sample.

O objetivo permanece o mesmo das Fases 1 e 2a — **medir sem mentir**. Cada elemento novo
desta fase existe para tornar o resultado *mais verdadeiro*, não melhor: os shorts
adicionam um lado novo de execução (aluguel, margem, liquidação), e o walk-forward
substitui a falsa confiança de um único backtest por uma estimativa honesta do que
sobrevive fora da amostra, com o viés de múltiplos testes declarado.

## 2. Escopo

**Dentro:**
- Venda a descoberto (short) e cobertura (buy-to-cover), com custo de aluguel (borrow
  fee) determinístico e anualizado (RF-SHT)
- Margem: caixa e quantidade podem ficar negativos; o invariante vira `equity ≥ margem
  exigida` (RF-MRG-01, substitui RF-POR-04 CA-04.3 da 2a)
- Liquidação forçada determinística (margin call) detectada no close e corrigida no open
  seguinte, inclusive o estado **fundo quebrado** (RF-MRG-02/03)
- **Buy-stop** (RF-ORD-05) e as novas ambiguidades intrabarra com brackets de compra
  (RF-ORD-06)
- Walk-forward: otimização in-sample por grade determinística + avaliação out-of-sample,
  com isolamento estrito IS/OOS (RF-WFK)
- Fórmulas de exposição gross/net, turnover com shorts e utilização de margem (RF-MRG-04,
  RF-MET)
- Viés de múltiplos testes (MHT) obrigatório no relatório (RF-MET-06)

**Fora:**
- Opções, futuros e derivativos
- Fracionário — a 2b continua operando quantidades inteiras (RF-SIZ-01 da 2a)
- Múltiplas moedas — moeda única (premissa 4)
- Impostos
- High-frequency / dados intraday — barras diárias, como nas fases anteriores
- Redis — adiado até existir problema de performance medido (ADR-0003)
- Rebalanceamento por alvo de risco (risk parity) — política de sizing futura, sem prazo
  (ADR-0008)
- Empréstimo com colateral e gestão de garantias real (o modelo de margem da 2b é um
  modelo determinístico de backtest, não um sistema de clearing)
- **Hard-to-borrow** — a disponibilidade de aluguel é ilimitada por default (premissa
  declarada e viés em RF-MET-06; restrição configurável, RF-SHT-03 CA-03.4)

## 3. Glossário

| Termo | Definição operacional |
|---|---|
| **Short (venda a descoberto)** | Venda de um ativo que não se possui, abrindo quantidade negativa; o lucro vem da queda de preço. Cobertura = compra que zera a posição. |
| **Borrow fee (custo de aluguel)** | Custo diário de manter uma posição short, proporcional ao notional short, anualizado e debitado do caixa em etapa própria (RF-SHT-03). |
| **Disponibilidade de aluguel** | Premissa de que todo short encontra papel para alugar — **ilimitada por default** (otimista, sem hard-to-borrow); restrição configurável (RF-SHT-03 CA-03.4). |
| **Margem** | Garantia exigida para manter posições alavancadas. Exigência = `Σᵢ |qtyᵢ| × closeᵢ × fator`; o invariante da 2b é `equity ≥ margem exigida` (RF-MRG-01). |
| **Liquidação forçada (margin call)** | Fechamento determinístico de posições para restaurar a margem, detectado no close e executado a mercado no open seguinte (RF-MRG-02). |
| **Fundo quebrado** | Estado em que, mesmo após liquidar todas as posições, a equity fica negativa (gap severo). O run congela, reporta o valor real e marca as métricas de retorno como `None` (RF-MRG-03). |
| **Buy-stop** | Ordem stop de compra: dispara quando `high ≥ gatilho` e executa a `max(gatilho, open)` com slippage; não disparada, permanece pendente (RF-ORD-05). |
| **Bracket short** | Par de ordens sobre posição short: take-profit (buy-limit) + stop-loss (buy-stop), ambos derivados da mesma intenção (RF-ORD-06). |
| **Walk-forward** | Divisão do histórico em folds (janela in-sample + janela out-of-sample); parâmetros otimizados no IS e avaliados no OOS do mesmo fold; o resultado honesto é a concatenação dos segmentos OOS (RF-WFK). |
| **Fold** | Par (janela IS, janela OOS) de um walk-forward. |
| **IS / OOS** | In-sample (dados usados para selecionar parâmetros) e out-of-sample (dados usados para avaliar). O IS nunca indexa séries OOS (RF-WFK-01). |
| **Warmup do OOS** | Barras de aquecimento da estratégia no segmento OOS, tomadas da **cauda do IS** (dados ≤ fronteira, sem lookahead) — RF-WFK-01 CA-01.3. |
| **Exposição gross** | Média diária de `(Σᵢ |qtyᵢ| × closeᵢ) / equity`. Pode exceder 100% (alavancada). |
| **Exposição net** | Média diária de `(Σᵢ qtyᵢ × closeᵢ) / equity` — longs e shorts se cancelam; pode ser negativa. |
| **Utilização de margem** | `margem_exigida / equity` — fração da garantia em uso (RF-MRG-04). |
| **MHT (múltiplos testes)** | Viés de seleção: quanto mais parâmetros testados no IS, maior a chance de o melhor deles vencer por sorte no OOS. O relatório declara a métrica de seleção, o tamanho da grade e o número de folds (RF-MET-06). |

---

## 4. Requisitos funcionais

### 4.1 Venda a descoberto e aluguel (RF-SHT)

**RF-SHT-01 — Contrato de sinal com direção** *(decisão D3)*
O `Signal` da Fase 1 ganha as ações `ENTER_SHORT` e `EXIT_SHORT`, **opcionais e
retrocompatíveis**: estratégias long-only (Fase 1 e 2a) emitem apenas `ENTER`/`EXIT` e
rodam sem mudança de comportamento. A **direção é decisão da estratégia, no sinal** — o
sizer nunca decide direção (mantém RF-SIZ-04 da 2a: devolve fração de magnitude, não
sentido).

- **CA-01.1** — *Dado* o contrato `Signal` da Fase 1, *quando* uma estratégia long-only
  roda na 2b, *então* ela emite apenas `ENTER`/`EXIT` e o resultado é idêntico ao run
  equivalente da 2a (regressão zero).
- **CA-01.2** — *Dado* um sinal `ENTER_SHORT`, *quando* o engine converte a intenção,
  *então* o alvo é uma venda (quantidade alvo negativa) e o sizer aplica a fração sobre o
  patrimônio como magnitude.
- **CA-01.3** — *Dado* um sinal semanticamente inválido (ex.: `EXIT_SHORT` sem posição
  short aberta), *quando* o engine processa, *então* é erro de domínio (`EngineError`),
  nunca silêncio.

**RF-SHT-02 — Execução de short e cobertura**
Venda a descoberto = venda a mercado (slippage de venda) que abre `qty < 0`; cobertura =
compra a mercado (slippage de compra) que reduz `|qty|`. Custos e cap de participação da
2a (RF-SLP-03) aplicam-se a entradas short como a qualquer entrada; saída short (cobertura
de uma posição) é integral, como a saída long da 2a (D4 da 2a). Limites de compra usados
para cobrir short seguem as regras da 2a (nunca violados, RF-SLP-04).

- **CA-02.1** — *Dado* um `ENTER_SHORT`, *quando* executa a mercado no open, *então* o
  trade registra `qty < 0` e preço `open × (1 − bps)` (direção desfavorável ao vendedor).
- **CA-02.2** — *Dado* um `EXIT_SHORT` a mercado, *quando* executa no open, *então* o
  trade registra `qty > 0` reduzindo a posição e preço `open × (1 + bps)`.
- **CA-02.3** — *Dado* um short cujo tamanho pedido excede o cap de participação, *quando*
  a entrada é convertida, *então* a quantidade é cortada na entrada (mesma regra e motivo
  da 2a, RF-SLP-03).
- **CA-02.4** — *Dado* um short coberto por buy-limit, *quando* o limite é alcançado,
  *então* o preço de preenchimento nunca viola o limite (herda RF-SLP-04 da 2a).

**RF-SHT-03 — Borrow fee determinístico** *(decisão D3)*
Custo de aluguel: **modelo determinístico, anualizado, debitado diariamente** sobre o
notional short: `diário = |qtyᵢ| × closeᵢ × fee_anual / 252`, com `fee_anual` default
**0,50% a.a.**, configurável. Debitado do caixa em etapa própria (nunca entra no preço de
execução — herda RF-SLP-04 CA-04.3 da 2a). Aparece no relatório em **categoria própria**
e entra na conciliação no termo de custos (RF-POR-04 da 2a estendido).

**Disponibilidade de aluguel** — default **ilimitada** (premissa declarada; viés em
RF-MET-06). Com `aluguel_ilimitado = false`, um `ENTER_SHORT` de ativo indisponível na
data não executa e o evento é logado e contado.

- **CA-03.1** — *Dado* um short de 1.000 ações a $100 mantido por 10 pregões com
  `fee_anual = 0,50%`, *quando* o run termina, *então* o custo total de aluguel bate com a
  forma fechada `Σ_d |qty| × close_d × 0,005/252` (fixture de papel, RNF-03).
- **CA-03.2** — *Dado* um short, *quando* o fee é debitado, *então* incide apenas sobre os
  pregões com posição short aberta (não sobre o dia em que a posição já foi coberta).
- **CA-03.3** — *Dado* o relatório, *quando* há custos de aluguel, *então* eles aparecem
  em categoria própria, separados de corretagem/slippage.
- **CA-03.4** — *Dado* `aluguel_ilimitado = true` (default), *quando* qualquer short é
  emitido, *então* a disponibilidade nunca bloqueia a entrada. *Dado*
  `aluguel_ilimitado = false` e ativo indisponível na data, *quando* o `ENTER_SHORT` é
  convertido, *então* a ordem não executa e o evento é logado e contado (R1).

**RF-SHT-04 — PnL algébrico com `qty < 0` (estende RF-POR-04 CA-04.2 da 2a)**
A identidade de conciliação da 2a vale **sem nova fórmula** com quantidade negativa:
`pnl_realizado = (saída − entrada) × qty` funciona algebricamente, e o não-realizado usa
`qtyᵢ × último_closeᵢ` com `qty` negativo. A conciliação multi-ativo é estendida apenas
nos testes — nenhum termo novo além de custos (incluindo aluguel) no termo próprio.

- **CA-04.1** — *Dado* um round-trip short (venda a $100, cobertura a $90, 100 ações),
  *quando* o pnl realizado é computado, *então* é `+$1.000 − custos` em forma fechada.
- **CA-04.2** — *Dado* um run long+short, *quando* a conciliação roda, *então*
  `Σ realizado + Σ não-realizado − Σ custos ≡ Δequity` fecha com `math.isclose(rel_tol=1e-9)`,
  com `qty` negativo no termo não-realizado.
- **CA-04.3** — *Dado* um short aberto antes e coberto depois de uma data ex-dividendo,
  *quando* o PnL é computado, *então* ele é idêntico ao retorno do preço **ajustado** no
  período (forma fechada) — declara a consistência do modelo de ajuste (dividendos via
  preço, premissa 7) para posições negativas (R2).

**RF-SHT-05 — Deslistagem em posição short**
Posição short cuja série termina antes do fim do run: **travada** no último close
conhecido (mesma semântica de RF-POR-02 CA-02.3 da 2a), **reportada**, e o passivo
(notional short marcado) permanece no patrimônio. Nunca liquidada a preço inventado.

- **CA-05.1** — *Dado* um short de ativo cuja série termina antes do fim do run, *quando*
  o run termina, *então* a posição é reportada travada no último close e o passivo
  permanece marcado na equity.
- **CA-05.2** — *Dado* o relatório, *quando* há short travado, *então* a ocorrência
  aparece com categoria própria (como a deslistagem long da 2a).

### 4.2 Margem e liquidação forçada (RF-MRG)

**RF-MRG-01 — Novo invariante de margem (substitui RF-POR-04 CA-04.3 da 2a)** *(D1)*
Os invariantes `caixa ≥ 0` e `qty ≥ 0` são **relaxados** — o que exige ADR próprio
(RNF-09 da 2a; ADR-0009 a escrever no gate 2). O invariante passa a ser:

- `equity ≥ margem_exigida`, com `margem_exigida = Σᵢ |qtyᵢ| × closeᵢ × margin_factor`
- `margin_factor` default **1.0**, explícito e configurável (R3).

**Nota (R3).** Um fator **único** para os dois lados (long e short) é uma **simplificação
declarada**; a alternativa de dois níveis (fator long × fator short) foi documentada como
alternativa descartada (§8.1).

Com apenas longs e `factor = 1.0`, `margem_exigida = notional longo` e o invariante reduz
a `caixa ≥ 0` — recupera exatamente o caso long-only. Violação fora da janela
close→open (RF-MRG-02) é erro de programação.

- **CA-01.1** — *Dado* um portfolio com shorts, *quando* o invariante é checado, *então*
  ele usa `Σ|qtyᵢ| × closeᵢ × factor` (valores absolutos), nunca a soma algébrica.
- **CA-01.2** — *Dado* um portfolio long-only com `factor = 1.0`, *quando* o invariante é
  checado, *então* ele é equivalente a `caixa ≥ 0` — o teste de invariante da 2a continua
  passando sem mudança (regressão zero).
- **CA-01.3** — *Dado* um gap que viola a margem no close, *quando* a barra é processada,
  *então* não é erro: dispara a liquidação forçada no open seguinte; se a violação
  persistir após o open seguinte, é erro de programação.
- **CA-01.4** — *Dado* o relatório, *quando* há shorts ou alavancagem, *então* a
  utilização de margem (`margem_exigida / equity`) é reportada.
- **CA-01.5** — *Dado* `margin_factor` configurado (default 1.0), *quando* a margem é
  computada, *então* o valor segue exatamente `Σ|qtyᵢ| × closeᵢ × factor` (R3).

**RF-MRG-02 — Liquidação forçada determinística (margin call)** *(D2)*
Detectada na marcação a mercado do **close** (`equity < margem_exigida`). Ordem corretiva
**MARKET no open da próxima barra** (ADR-0002). Seleção: **liquidação integral por ativo**,
em **ordem alfabética de ticker**, repetida até restaurar a margem (parcial no agregado,
nunca parcial dentro de um ativo). Liquidação de long = venda a mercado; de short =
compra a mercado (cobertura). **Cancela todas as pendentes do ativo liquidado** (herda
RF-ORD-04 CA-04.1 da 2a). Cada liquidação é um Trade com `origin = MARGIN_CALL`
(auditável como a auditoria do stop da 2a).

- **CA-02.1** — *Dado* um portfolio em violação de margem no close, *quando* o open
  seguinte é processado, *então* o ativo alfabeticamente primeiro é liquidado
  integralmente a mercado, e o processo se repete até `equity ≥ margem_exigida`.
- **CA-02.2** — *Dado* um ativo liquidado por margem, *quando* o open é processado,
  *então* todas as suas ordens pendentes (limite, sell-stop, buy-stop) são canceladas.
- **CA-02.3** — *Dado* o relatório, *quando* houve liquidações forçadas, *então* cada uma
  aparece com `origin = MARGIN_CALL` e a contagem agregada entra no bloco de contadores de
  mecanismo (estende RF-MET-05 da 2a).
- **CA-02.4** — *Dado* dois runs idênticos com violação de margem, *quando* ambos são
  processados, *então* liquidam exatamente os mesmos ativos nas mesmas barras (a seleção
  nunca usa preço como critério — RNF-01).

**RF-MRG-03 — Estado fundo quebrado** *(Q4 — decisão explícita)*
Se, após liquidar **todas** as posições, a equity ainda for `< 0` (gap severo), o run
**congela**: nenhum trade adicional é gerado; a equity é reportada no valor negativo real;
o relatório marca `fundo_quebrado = true`; métricas que assumem equity positiva (CAGR,
Sharpe, turnover, exposição) são reportadas como **`None` explícito** (nunca `NaN` — lição
do ING-05.1); e a conciliação **continua fechando** — o número negativo é honesto.

- **CA-03.1** — *Dado* um gap que leva `equity < 0` mesmo após a liquidação total, *quando*
  o run prossegue, *então* nenhum novo trade é gerado e o relatório marca
  `fundo_quebrado = true`.
- **CA-03.2** — *Dado* fundo quebrado, *quando* o relatório é emitido, *então* CAGR e
  Sharpe aparecem como **`None` explícito** (nunca `NaN`, nunca zero fabricado) e a
  conciliação fecha com a equity negativa real (isclose 1e-9) (R6).
- **CA-03.3** — *Dado* fundo quebrado, *quando* o run termina, *então* o resultado carrega
  flag que o exclui de comparações automáticas com benchmark (a comparação exige decisão
  explícita de quem lê).

**RF-MRG-04 — Alavancagem e exposição gross/net (estende RF-MET-04 da 2a)** *(D4)*
A exposição **pode exceder 100%** (alavancada via shorts). Definições únicas, as mesmas
para estratégia e benchmark onde aplicável:

- `exposição_gross_média` = média diária de `(Σᵢ |qtyᵢ| × closeᵢ) / equity`
- `exposição_net_média` = média diária de `(Σᵢ qtyᵢ × closeᵢ) / equity` (pode ser negativa)
- `turnover_anualizado` = fórmula da 2a, com `|notional|` por lado — já funciona com
  `qty < 0` (notional absoluto)

- **CA-04.1** — *Dado* um portfolio long+short, *quando* as exposições são computadas,
  *então* gross e net seguem as fórmulas e são reportadas lado a lado.
- **CA-04.2** — *Dado* um portfolio alavancado (gross > 100%), *quando* o relatório é
  emitido, *então* a alavancagem aparece explicitamente junto com a utilização de margem.

### 4.3 Tipos de ordem — extensões (RF-ORD)

**RF-ORD-05 — Buy-stop (estende RF-ORD-02 da 2a)** *(D5)*
Buy-stop: ordem stop de **compra**; dispara quando `high[i] ≥ S`; executa a
`max(S, open[i])` **com slippage de compra** (estende RF-SLP-04 CA-04.4 da 2a ao lado
compra do stop). Não disparada ⇒ **permanece pendente** entre barras do próprio ativo
(como o sell-stop da 2a). Serve como entrada condicional de compra e como stop-loss de
posição short (bracket short, RF-ORD-06). Nunca reserva caixa (herda RF-ORD-04 CA-04.3).

- **CA-05.1** — *Dado* um buy-stop com `high[i] ≥ S`, *quando* a barra é processada,
  *então* a compra executa a `max(S, open[i])` com slippage de compra.
- **CA-05.2** — *Dado* um buy-stop não disparado, *quando* a barra termina, *então* ele
  permanece pendente para a próxima barra do próprio ativo (ADR-0002 por ativo).
- **CA-05.3** — *Dado* um buy-stop que nunca dispara, *quando* o run termina, *então* ele
  não executa e o caixa nunca é debitado (sem reserva de caixa).

**RF-ORD-06 — Ambiguidade intrabarra com buy-stop e bracket short (estende RF-ORD-03 da
2a)** *(D5)*
O pior caso (ADR-0007) é estendido a todos os brackets novos:

- **Bracket long de entrada** (buy-stop de entrada `S_e` + sell-stop de saída `S_s`, com
  `S_s < S_e`) ambos tocados na mesma barra: a posição **abre no buy-stop `S_e`** e
  **fecha no sell-stop `S_s` na mesma barra** — perda realizada, flat, `ambiguous=True`
  (espelha o pior caso de entrada da 2a com os tipos invertidos).
- **Bracket short** (take-profit buy-limit `TP` + stop-loss buy-stop `SL`, com `SL > TP`)
  ambos tocados na mesma barra: o pior caso é o **buy-stop `SL`** — o short é coberto no
  stop, nunca no limite, `ambiguous=True`.
- **Nunca "ambos executam"** (CA-03.3 da 2a mantido): a ambiguidade resolve no pior caso,
  sem dupla contagem.

- **CA-06.1** — *Dado* um bracket long (buy-stop `S_e` + sell-stop `S_s`) com ambos os
  gatilhos tocados na mesma barra, *quando* a barra é processada, *então* o resultado é
  abrir em `S_e` e fechar em `S_s` na mesma barra, flat, `ambiguous=True`, perda
  `(S_e − S_s + custos)` em forma fechada.
- **CA-06.2** — *Dado* um bracket short com `TP` e `SL` ambos tocados na mesma barra,
  *quando* a barra é processada, *então* o short é coberto no `SL` (pior caso), nunca no
  `TP`, `ambiguous=True`.
- **CA-06.3** — *Dado* o relatório, *quando* há ambiguidades com buy-stop, *então* a
  contagem entra no mesmo bloco de contadores de mecanismo da 2a (RF-MET-05).

### 4.4 Walk-forward (RF-WFK)

**RF-WFK-01 — Folds com isolamento estrito IS/OOS** *(D6; ancoragem = D7)*
O histórico é dividido em folds (janela IS + janela OOS). **Isolamento estrito**: o
engine do IS nunca indexa séries OOS — cada fold constrói seus próprios
`UnionCalendar`/`PriceSeries` truncados no fim do IS, e a série OOS não é passada a
nenhum run IS. Ancoragem: **rolling** (janela IS de tamanho fixo, deslizante) como
**default**; **anchored** (janela IS crescente) configurável para medir a diferença
(decisão D7, Q6).

**Warmup do OOS (R4)** — a estratégia no segmento OOS é aquecida com a **cauda do IS**
(últimas `warmup` barras ≤ fronteira, sem lookahead). A alternativa de descartar as
primeiras barras do OOS foi descartada (§8.1).

- **CA-01.1** — *Dado* um fold, *quando* o run IS roda, *então* qualquer acesso a barra
  além do fim do IS é erro (`EngineError`) — guard de fronteira testável (não basta
  "não passar a série"; o acesso é bloqueado por construção).
- **CA-01.2** — *Dado* o esquema de folds, *quando* os folds são construídos, *então* IS
  e OOS de cada fold são disjuntos e a união dos segmentos OOS cobre a janela avaliada
  sem sobreposição.
- **CA-01.3** — *Dado* um fold, *quando* o segmento OOS é avaliado, *então* o warmup da
  estratégia vem da cauda do IS (últimas `warmup` barras ≤ fronteira) — nunca de barras
  OOS anteriores ao segmento; mutar o OOS não altera o warmup (R4).

**RF-WFK-02 — Otimização determinística in-sample**
Otimizador default: **busca em grade explícita** de parâmetros declarados (ex.: janelas
do SmaCross ∈ {10, 20, …, 60}), **determinística** (RNF-01; otimizador estocástico só
com seed travado e declarado). **Métrica de seleção IS: Sharpe anualizado com `rf = 0`**
sobre a equity IS, declarada (R5) e incluída no viés MHT (RF-MET-06). Os parâmetros
selecionados no IS de um fold são exatamente os usados no OOS **do mesmo fold**.

- **CA-02.1** — *Dado* o grid declarado, *quando* o walk-forward roda duas vezes sobre o
  mesmo estado, *então* os parâmetros selecionados por fold são idênticos (RNF-01).
- **CA-02.2** — *Dado* um fold, *quando* o OOS é avaliado, *então* os parâmetros usados
  são exatamente os selecionados no IS do mesmo fold (nunca os de outro fold).
- **CA-02.3** — *Dado* um fold, *quando* a seleção IS roda, *então* a métrica de seleção é
  o Sharpe anualizado com `rf = 0` sobre a equity IS — e a mesma métrica aparece declarada
  no relatório (R5).

**RF-WFK-03 — Resultado = concatenação dos segmentos OOS**
O resultado honesto é a equity **concatenada dos segmentos OOS** (um por fold), com as
métricas computadas sobre ela; o relatório mostra a tabela **por fold** (IS e OOS lado a
lado) com os parâmetros selecionados por fold, e os parâmetros médios.

- **CA-03.1** — *Dado* o walk-forward, *quando* o resultado é reportado, *então* a equity
  é a concatenação exata dos segmentos OOS (testável por comparação direta com o run OOS
  isolado de cada fold).
- **CA-03.2** — *Dado* o relatório, *quando* há walk-forward, *então* a tabela fold a
  fold (IS/OOS, parâmetros selecionados) está presente.

**RF-WFK-04 — Mutação ENG-01.2 estendida ao OOS (ADR-0011)** *(D6)*
O teste de mutação da 2a (ENG-01.2 em duas partes, ADR-0005) é estendido:

- **Parte 1 (IS)**: mutar barras futuras do IS não altera intenções/execuções anteriores
  — agora incluindo `ENTER_SHORT`/`EXIT_SHORT` e buy-stop.
- **Parte 2 (OOS)**: mutar barras OOS **não altera os parâmetros selecionados no IS** — o
  IS não enxerga o OOS por construção.

- **CA-04.1** — *Dado* o run IS de um fold, *quando* barras OOS são mutadas, *então* os
  parâmetros selecionados são idênticos.
- **CA-04.2** — *Dado* um fold, *quando* barras futuras do IS são mutadas, *então*
  intenções e execuções anteriores são idênticas (estende o teste da 2a, incluindo
  shorts e buy-stop).

**RF-WFK-05 — Orçamento de performance declarado (RNF-04 do WF)** *(Q5)*
O RNF-04 da 2a (30 s por run único) **não se aplica** a centenas de runs. Orçamento
declarado em duas escalas: **por fold** (default 30 s para IS+OOS de 20 ativos × janela)
e **total** (default `n_folds × 30 s` + margem declarada). O harness mede ambas e reporta
a meta; sem base ingerida, usa séries sintéticas determinísticas e declara a origem
(padrão da T17).

- **CA-05.1** — *Dado* o harness do WF, *quando* ele roda, *então* reporta tempo por fold
  e tempo total, e ambos respeitam os orçamentos declarados (ou o desvio é reportado).

### 4.5 Métricas e relatório (RF-MET)

**RF-MET-05 — Benchmark e comparação da 2b**
O benchmark da 2b é o **mesmo 1/N long-only da 2a** (mesmas regras de entrada, sem
shorts, sem margem) — a comparação contra uma estratégia com shorts exige um benchmark
long-only explícito. Adicionalmente, o relatório compara o run long+short contra o run
**long-only da própria estratégia** (2a) — a diferença é o que os shorts acrescentam.

- **CA-05.1** — *Dado* o relatório da 2b, *quando* ele é emitido, *então* o benchmark é o
  1/N long-only da 2a e a comparação long+short × long-only da própria estratégia está
  presente.
- **CA-05.2** — *Dado* o benchmark, *quando* a estratégia opera shorts, *então* o
  benchmark permanece long-only (nunca short).

**RF-MET-06 — Vieses da 2b (estende RF-MET-03 da 2a)** *(R1, R5)*
Itens novos na seção fixa de vieses (constante literal no código, padrão Fase 1 §5.2):

- custo de aluguel **não calibrado** — o default de 0,50% a.a. é premissa, não medida;
- **disponibilidade de aluguel ilimitada** — sem hard-to-borrow; otimista para
  estratégias que dependem de short (R1);
- liquidação forçada alfabética é determinística, mas **qualquer regra de seleção é
  seleção com viés** (mesmo argumento do atendimento alfabético da 2a);
- **MHT**: a seleção de parâmetros in-sample é otimista — o relatório declara a **métrica
  de seleção (Sharpe anualizado, `rf = 0`)**, o **tamanho da grade** e o **número de
  folds** (o leitor julga o esforço de busca) (R5);
- "pior caso intrabarra" ampliado aos brackets com buy-stop (RF-ORD-06);
- itens da 2a preservados (fill integral ao limite é otimista; slippage não calibrado;
  sem impacto permanente de mercado).

- **CA-06.1** — *Dado* o relatório, *quando* os vieses são emitidos, *então* a seção
  contém os itens novos (aluguel não calibrado, aluguel ilimitado sem hard-to-borrow, MHT
  com métrica/grid/folds, liquidação alfabética com viés) além dos da 2a.
- **CA-06.2** — *Dado* o relatório, *quando* há walk-forward, *então* a métrica de
  seleção, o tamanho da grade e o número de folds aparecem na seção de run
  (reconstruível do JSON isolado — estende RF-CON-02 da 2a).

### 4.6 Herança de requisitos não funcionais (RF-RNF)

**RF-RNF-02 — Cláusula de herança e cobertura estendida** *(estende RF-RNF-01 da 2a)*
- **CA-02.1** — *Dado* RNF-01, RNF-03, RNF-05, RNF-06, RNF-07 e RNF-08 da Fase 1 e
  RNF-09 da 2a, *quando* a 2b é implementada, *então* valem sem alteração — os testes que
  os provam continuam passando no run long+short.
- **CA-02.2** — *Dado* o piso de cobertura, *quando* o CI roda, *então* é **≥ 85%** sobre
  `engine/`, `analytics/` e módulos novos (margin, walk-forward) — estende o RNF-02 da 2a.
- **CA-02.3** — *Dado* o relaxamento dos invariantes da 2a (RF-POR-04 CA-04.3), *quando*
  a 2b é implementada, *então* existe ADR próprio (ADR-0009) referenciado na spec — o
  RNF-09 da 2a exige, e o teste de arquitetura de specs falha se o ADR não existir.

---

## 5. Requisitos não funcionais

- **RNF-01 — Determinismo.** Mesmo estado de banco + mesmos parâmetros ⇒ resultado
  idêntico. O otimizador do walk-forward é determinístico (grade); otimizador estocástico
  exige seed travado e declarado. *(herdado da Fase 1)*
- **RNF-02 — Cobertura.** Mínimo **85%** em `engine/`, `analytics/` e módulos novos
  (margin, walk-forward). *(estende o RNF-02 da 2a)*
- **RNF-03 — Fixtures sintéticas.** Testes de engine e analytics rodam sobre séries
  construídas à mão, com resultado calculável no papel. *(herdado da Fase 1)*
- **RNF-04 — Performance do run único.** Run de 20 ativos × 10 anos abaixo de **30 s**,
  medindo só o cômputo (declarado na 2a, P5). **Mantido** para o run único; o
  walk-forward tem orçamento próprio (RNF-10).
- **RNF-05 — Tipagem.** `mypy --strict` mantido no CI. *(herdado da Fase 1)*
- **RNF-06 — Ambiente.** Suíte unitária roda offline, sem rede. *(herdado da Fase 1)*
- **RNF-07 — Datas.** Toda data é data-calendário naive; nenhuma comparação envolve
  timezone. *(herdado da Fase 1)*
- **RNF-08 — Dinheiro.** Valores monetários em ponto flutuante com comparações por
  tolerância explícita. *(herdado da Fase 1)*
- **RNF-09 — Invariantes.** Nenhum invariante da Fase 1 ou da 2a pode ser relaxado sem
  ADR próprio. *(herdado da 2a; gatilho do ADR-0009)*
- **RNF-10 — Orçamento do walk-forward.** Performance do WF declarada em duas escalas:
  por fold e total (RF-WFK-05). O "30 s" do RNF-04 não se aplica a centenas de runs.

## 6. Premissas

1. **Long-only REVOGADO** — a 2b opera long + short com margem.
2. Alavancagem limitada pela margem (`margin_factor` default 1.0, explícito e
   configurável — R3).
3. Sem fracionário — quantidades inteiras (RF-SIZ-01 da 2a mantido).
4. Moeda única. Sem conversão cambial.
5. Sem imposto.
6. **Custo de aluguel entra como custo**; o default de 0,50% a.a. é premissa não calibrada
   — viés declarado no relatório (RF-MET-06).
7. **Disponibilidade de aluguel ilimitada** (default) — sem hard-to-borrow; restrição
   configurável (RF-SHT-03 CA-03.4) — viés declarado (R1).
8. `rf = 0` e dividendos via ajuste de preço — herdados da Fase 1; consistência para
   shorts testada (RF-SHT-04 CA-04.3).
9. Buy-stop executa com slippage; limite nunca violado — herdados da 2a (RF-SLP-04).
10. Deslistagem em posição short: travada e reportada, passivo marcado (RF-SHT-05).
11. Benchmark da 2b permanece **long-only 1/N** — isolar o efeito dos shorts exige
    benchmark long-only (RF-MET-05).

## 7. Legado verificado — baseline, não escopo novo

As Fases 1 e 2a estão **implementadas e verificadas** (design Fase 1 v0.10 / 2a v0.1
emendado, `docs/STATE.md` 2026-08-14, 471 testes, cobertura 97,84%). A 2b **estende**,
não reabre:

- **RF-CON-01/02/03 da 2a** (barra corrente descartada; relatório auto-suficiente;
  nota de leitura do placar 19/20 em CAGR e 19/20 em Sharpe pós-regeneração) — valem como
  estão, com o relatório da 2b estendendo a seção "run" (RF-MET-06 CA-06.2).
- **Contratos da 2a** — `ConditionalStrategy`/`Bracket` (RF-SIG-01), `PendingOrder` com
  `kind/limit/stop/intent_seq/decision_date` (RF-ORD-04), sizer com fração (RF-SIZ-04),
  `UnionCalendar` imutável (RF-POR-05), conciliação (RF-POR-04 CA-04.2) — são a base
  sobre a qual a 2b adiciona direção e margem, sem reescrever.

## 8. Decisões da v0.2 (D1–D7)

| # | Decisão | Escolha da v0.2 | Razão | ADR |
|---|---|---|---|---|
| D1 | Invariante de margem | `equity ≥ margem_exigida = Σ\|qtyᵢ\| × closeᵢ × factor` (factor default 1.0, explícito e configurável — R3); caixa/qty podem ser negativos | Fórmula única, recupera long-only com factor 1.0; relaxamento exige ADR (RNF-09) | ADR-0009 (gate 2) |
| D2 | Liquidação forçada | Detectada no close; MARKET no open seguinte (ADR-0002); **integral por ativo, alfabética, repetida** até restaurar margem; cancela pendentes; `origin = MARGIN_CALL` | Integral por ativo preserva a semântica de PnL; alfabética é neutra e determinística | ADR-0010 (gate 2) |
| D3 | Direção no contrato de sinal | `ENTER_SHORT`/`EXIT_SHORT` no `Signal`, opcionais e retrocompatíveis; sizer nunca decide direção | Direção é decisão da estratégia; sizer devolve magnitude (RF-SIZ-04 da 2a) — separação limpa de responsabilidades | — (contrato; RF-SHT-01) |
| D4 | Fórmulas gross/net | Exposição gross e net reportadas lado a lado; turnover com `\|notional\|` (funciona com qty<0); alavancagem >100% explícita | O leitor vê o risco real (gross) e o direcional (net) sem adivinhar | — (RF-MRG-04) |
| D5 | Buy-stop + ambiguidades | Buy-stop executa a `max(S, open)` com slippage; pior caso em brackets com buy-stop (RF-ORD-06) | Espelha o sell-stop e o ADR-0007 da 2a — consistência de semântica | — (RF-ORD-05/06; estende ADR-0007) |
| D6 | Walk-forward | Grade determinística IS; isolamento estrito (OOS nunca indexado pelo IS); resultado = concatenação OOS; MHT declarado; métrica de seleção = Sharpe anualizado `rf=0` (R5) | O número honesto é o OOS concatenado; o IS é seleção, não resultado | ADR-0011 (gate 2, mutação OOS) |
| D7 | Ancoragem dos folds (Q6) | **Rolling** (janela IS fixa deslizante) como **default**; **anchored** (janela IS crescente) configurável para medir a diferença | Rolling é o padrão da literatura e o mais comparável entre folds; anchored fica disponível para **medir**, não adivinhar (decisão do autor, 2026-08-14 — R7) | — (RF-WFK-01) |

### 8.1 Notas e alternativas descartadas (v0.2)

- **Fator de margem em dois níveis (long × short)** *(R3)* — descartado como default:
  o fator único já limita a alavancagem e mantém a fórmula legível; a equivalência com
  dois níveis é trivial (dois fatores configuráveis) e fica documentada para o ADR-0009.
- **Warmup do OOS descartando as primeiras barras do OOS** *(R4)* — descartado: desperdiça
  dados avaliáveis e abre buraco na concatenação dos segmentos; a cauda do IS
  (≤ fronteira) é sem lookahead por construção.
- **Anchored como default** *(R7)* — descartado como default: janelas IS de tamanho
  variável entre folds prejudicam a comparabilidade; mantido configurável.
- **Disponibilidade de aluguel com hard-to-borrow real** *(R1)* — descartado como default:
  exigiria dados de disponibilidade/empréstimo não ingeridos; a premissa ilimitada é
  declarada como viés e a restrição fica configurável.

## 9. Questões em aberto

Nenhuma. Q1–Q5 foram fechadas na v0.1 como D1–D6; **Q6 foi fechada na v0.2 como D7**
(ancoragem rolling como default, anchored configurável — decisão do autor, R7). Nada fica
"para depois": o que não é da 2b está declarado no escopo (opções, fracionário, moedas,
imposto, high-frequency, hard-to-borrow real).

## 10. Definition of Done

- [ ] Run multi-ativo **long+short** ponta a ponta com margem (estratégia com shorts +
      benchmark 1/N long-only), universo de 20 ativos
- [ ] Conciliação CA-04.2 **estendida** (RF-SHT-04) fechando com `isclose(1e-9)` no run
      real, com `qty` negativa e custos de aluguel no termo próprio
- [ ] PnL de posição short atravessando data ex-dividendo ≡ retorno do preço ajustado,
      em forma fechada (RF-SHT-04 CA-04.3)
- [ ] Mutação ENG-01.2 estendida ao OOS (RF-WFK-04, ADR-0011) passando: mutar barras OOS
      não altera parâmetros selecionados no IS; mutar futuro do IS não altera intenções/
      execuções anteriores (incluindo shorts e buy-stop)
- [ ] Liquidação forçada determinística testada (RF-MRG-02): seleção alfabética,
      `origin = MARGIN_CALL`, cancelamento de pendentes — incluindo o estado fundo
      quebrado com métricas `None` explícito (RF-MRG-03, R6)
- [ ] Buy-stop e ambiguidades intrabarra novas testadas (RF-ORD-05/06): pior caso nos
      brackets long e short, sem "ambos executam", contagem nos contadores de mecanismo
- [ ] Walk-forward com resultado honesto (concatenação OOS) comparado contra o 1/N
      long-only e contra o run long-only da 2a (RF-MET-05); warmup do OOS pela cauda do IS
      (RF-WFK-01 CA-01.3)
- [ ] ADRs 0009–0011 escritos (margem; liquidação forçada e fundo quebrado; fronteira de
      mutação IS/OOS)
- [ ] Cobertura ≥ 85% com módulos novos (margin, walk-forward); CI verde; push a cada etapa
- [ ] Resultado reportado honestamente, com os vieses da 2b (aluguel não calibrado,
      aluguel ilimitado sem hard-to-borrow, MHT com métrica/grid/folds, liquidação
      alfabética) na seção fixa do relatório

## 11. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.2 | 2026-08-14 | Revisão do gate 1 (tech lead do web): resoluções **R1–R7** aplicadas. R1: viés "disponibilidade de aluguel ilimitada" em RF-MET-06 + restrição configurável em RF-SHT-03 CA-03.4. R2: RF-SHT-04 CA-04.3 (PnL short através de data ex ≡ retorno do preço ajustado). R3: fator único de margem declarado como simplificação, alternativa de dois níveis descartada (§8.1), default 1.0 explícito (RF-MRG-01 CA-01.5). R4: warmup do OOS pela cauda do IS (RF-WFK-01 CA-01.3), alternativa descartada. R5: métrica de seleção IS = Sharpe anualizado rf=0 (RF-WFK-02 CA-02.3) e incluída no viés MHT (RF-MET-06). R6: fundo quebrado com métricas `None` explícito, nunca NaN (RF-MRG-03 CA-03.2). R7: Q6 fechada como D7 (rolling default, anchored configurável; decisão do autor). §9 vazia. Status draft → em revisão. |
| 0.1 | 2026-08-14 | Rascunho inicial, com decisões D1–D6 propostas e Q1–Q6 em aberto para o gate 1 |
