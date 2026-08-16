# ADR-0009 — Invariante de margem e liquidação forçada determinística (substitui ENG-04.4/POR-04.3)

**Status:** aceito
**Data:** 2026-08-14
**Contexto de decisão:** Fase 2b — engine (margem e liquidação)

## Contexto

A Fase 2a fechou o invariante `cash ≥ 0`, `qty ≥ 0`, `k ≤ N` (RF-POR-04 CA-04.3), checado a cada barra como erro de programação. A Fase 2b opera **long + short**: uma posição short (quantidade negativa) usa o produto da venda como caixa, e a marcação a mercado pode deixar o caixa negativo sem que o portfólio esteja em ruína — o invariante da 2a, literalmente aplicado, torna shorts impossíveis.

O RNF-09 da 2a exige: **nenhum invariante das fases anteriores pode ser relaxado sem ADR próprio**. Este ADR é o registro desse relaxamento — e da decisão acoplada de **como** o novo invariante é mantido quando violado (liquidação forçada determinística) e do que acontece quando nem a liquidação salva o fundo (estado fundo quebrado, RF-MRG-03).

## Decisão

**Novo invariante (substitui `cash ≥ 0`/`qty ≥ 0`):**

```
equity ≥ margem_exigida,  margem_exigida = Σᵢ |qtyᵢ| × closeᵢ × margin_factor
```

- `margin_factor` default **1.0**, explícito e configurável (R3/RF-MRG-01 CA-01.5).
- **Fator único** para long e short — simplificação declarada (R3); a alternativa de dois níveis (fator long × fator short) fica documentada como descartada abaixo.
- Com apenas longs e `factor = 1.0`, `margem_exigida = notional longo` ⇒ `equity ≥ notional ⇔ cash ≥ 0` — recupera exatamente o caso long-only (CA-01.2, regressão zero do teste da 2a).
- O invariante vale **após a fase de execução do open** (pós-liquidação); violação detectada no **close** é evento normal — agenda liquidação (CA-01.3); violação persistindo após o open seguinte é erro de programação (CA-01.3). A janela close→open é a única em que o invariante pode ficar pendente.

**Liquidação forçada determinística (RF-MRG-02):**

- **Detecção:** no close (marcação a mercado + débito de borrow fee), `equity < margem_exigida`.
- **Execução:** ordem **MARKET no open da próxima barra** (ADR-0002), do PRÓPRIO ativo.
- **Seleção:** **integral por ativo** (nunca parcial dentro de um ativo; parcial no agregado por parar quando a margem restaura), em **ordem alfabética de ticker** — nunca preço como critério (CA-02.4/RNF-01). Long → venda; short → compra (cobertura).
- **Pendentes:** cancela **todas** as pendentes do ativo liquidado (herda ORD-04.1 da 2a — CA-02.2).
- **Auditoria:** cada liquidação é um Trade com `origin = MARGIN_CALL` (CA-02.3), no mesmo padrão da auditoria do stop da 2a.

**Estado fundo quebrado (RF-MRG-03):** se, após liquidar **todas** as posições, `equity < 0` (gap severo), o run **congela**: nenhum trade adicional; a equity é reportada no valor negativo real; `fundo_quebrado = true`; métricas que assumem equity positiva (CAGR, Sharpe, turnover, exposição) são **`None` explícito** — nunca `NaN` (R6, lição do ING-05.1); a conciliação **continua fechando** com a equity negativa (CA-03.2); o resultado fica excluído de comparações automáticas com benchmark (CA-03.3).

## Justificativa

- **Um único invariante substitui dois.** `cash ≥ 0` e `qty ≥ 0` eram duas faces da mesma restrição (long-only). Com shorts, nenhum dos dois é um invariante de sanidade isolado: o que mede a saúde do portfólio é a capacidade de cobrir o passivo, que é exatamente o que `equity ≥ margem` expressa.
- **Regressão long-only é por construção, não por teste ad hoc.** Com `factor = 1.0` e apenas longs, a fórmula colapsa em `cash ≥ 0` — o teste de invariante da 2a passa sem mudança (CA-01.2). É a mesma técnica do ADR-0008 (N=1 ⇒ all-in).
- **Alfabético é o critério mais fraco que continua sendo determinístico.** Qualquer critério baseado em preço/valor introduziria dependência de dados e seleção com viés; alfabético é neutro, determinístico (RNF-01) e declarado como viés no relatório (RF-MET-06) — mesmo argumento do atendimento alfabético da 2a.
- **Integral por ativo preserva a semântica de PnL.** Liquidação parcial dentro de um ativo misturaria o PnL realizado do trade original com o da liquidação; integral fecha o trade de forma auditável (`origin = MARGIN_CALL`).
- **Fundo quebrado é estado, não exceção.** Um gap severo é dado, não bug; reportar a equity negativa real e `None` explícito nas métricas é mais honesto do que uma exceção que aborta o run ou um `NaN` que corrompe a leitura.

## Alternativas descartadas

**Manter `cash ≥ 0`/`qty ≥ 0` e modelar short como "conta espelho" (posição separada long-only + passivo).** Evitaria relaxar o invariante e manteria a 2a intocada. Descartada porque cria um segundo conjunto de regras de PnL (o espelho teria que espelhar exatamente o short real, sob risco de drift), e porque o problema não é o sinal da quantidade — é a capacidade de cobrir o passivo, que o espelho não mede melhor.

**Fator de margem em dois níveis (long × short).** Mais realista (margens de short costumam ser maiores). Descartado como default porque a 2b não tem dado de garantia real para calibrar a diferença — o fator único já limita a alavancagem e mantém a fórmula legível; a equivalência é trivial (dois fatores configuráveis) e fica documentada na spec §8.1. Volta à mesa quando existir modelo de garantia real (escopo fora da 2b).

**Liquidação parcial por ativo (reduz proporcionalmente todos).** Distribui o corte e minimiza a liquidação de qualquer ativo individual. Descartada porque fragmenta o PnL de cada trade (parte realizado, parte não) e porque a seleção proporcional é um critério baseado em valor — a mesma objeção de viés da seleção por preço.

**Seleção por maior peso / maior perda.** "Liquida o que mais pesa" parece mais eficiente. Descartada porque usa preço/valor como critério — introduz seleção com viés e quebra o determinismo neutro que alfabético dá.

**Fundo quebrado como exceção ou `NaN`.** Abortar esconderia o dado; `NaN` corromperia métricas e relatório. Descartado: estado declarado + `None` explícito (R6).

## Consequências

- `Position.quantity < 0` passa a ser válido; `cash` pode ficar negativo; os testes de invariante da 2a que checam `cash ≥ 0`/`qty ≥ 0` são **substituídos** pelos testes de margem (CA-01.2 mantém a regressão long-only).
- O laço (backtest.py) é o dono da detecção e do congelamento; o broker (`execute_margin_calls`) é o dono da execução; `margin_requirement`/`margin_utilization` são puras (§3.3 do design).
- Cada liquidação gera um Trade auditável (`origin = MARGIN_CALL`, `decision_date` = close que detectou) — o relatório conta `margin_calls` como categoria própria (RF-MET-05 estendido).
- A janela close→open é a única em que o invariante pode ficar pendente — documentada no fluxo (§4) e testada (CA-01.3).
- Violação persistente após o open seguinte é erro de programação (CA-01.3) — inclui a borda rara de posição travada sem barra de execução (nunca preço inventado).

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| `margem_exigida = Σ\|qtyᵢ\| × closeᵢ × factor` — valores absolutos (CA-01.1) | `test_margin_requirement_uses_absolute_qty` |
| Long-only + factor 1.0 ⇒ invariante ≡ `cash ≥ 0` (CA-01.2, regressão) | `test_margin_invariant_reduces_to_cash_ge_zero_long_only` |
| Violação no close agenda liquidação; persistir após o open = erro (CA-01.3) | `test_margin_breach_close_to_open_window_allowed_then_error` |
| Liquidação alfabética, integral por ativo, até restaurar (CA-02.1) | `test_forced_liquidation_alphabetical_until_margin_restored` |
| Liquidação cancela pendentes do ativo (CA-02.2) | `test_forced_liquidation_cancels_pending_orders` |
| Trades com `origin = MARGIN_CALL` contados (CA-02.3) | `test_report_counts_margin_call_origin_trades` |
| Seleção determinística, sem preço como critério (CA-02.4/RNF-01) | `test_forced_liquidation_deterministic_across_runs` |
| Fundo quebrado congela e reporta equity negativa real (CA-03.1) | `test_broken_fund_freezes_no_new_trades_and_flag` |
| Métricas `None` explícito, nunca NaN (CA-03.2/R6) | `test_broken_fund_metrics_are_explicit_none_never_nan` |
| Exclusão de comparação automática (CA-03.3) | `test_broken_fund_result_excluded_from_auto_comparison` |

## Revisitar quando

Existir modelo de garantia real (fatores por classe, haircuts, colateral) — a 2b declara o modelo de margem como determinístico de backtest, não clearing (escopo fora). Também revisitar se um fator único se mostrar insuficiente para calibrar alavancagem em estratégias short-heavy: o sinal típico é relatório de utilização de margem sistematicamente próximo de 1.0.
