# ADR-0006 — Modelo de slippage (fixo em bps + participação com cap, forma funcional cravada)

**Status:** aceito
**Data:** 2026-08-14
**Contexto de decisão:** Fase 2a — engine (broker/slippage)

## Contexto

A Fase 1 executava ao `open` sem slippage (premissa 5 do requirements da Fase 1). A Fase 2a parametriza slippage (RF-SLP-01/02/03) e precisa de um modelo default para relatórios comparáveis. Duas classes de efeito coexistem e precisam de tratamento explícito:

1. **Slippage de preço** — o preço efetivo diverge do preço de referência na direção desfavorável ao executor.
2. **Participação no volume** — ordem grande relativa ao ADV (janela de 20 pregões do próprio ativo, RF-SLP-03 CA-03.1) degrada o preço; acima de um limite (10% do ADV), a **quantidade** é cortada nas entradas (RF-SLP-03 CA-03.3), nunca o preço (RF-SLP-04).

Restrições herdadas: limite de preço nunca é violado (SLP-04.2); custos nunca entram no preço de execução (SLP-04.3); saída é integral, sem cap (SLP-03.4, D3 da Fase 1); slippage só se aplica a ordens a mercado e a stops convertidos (SLP-04.1/04.4).

## Decisão

- **Modelo default composto:** `FixedBps` (base) + `Participation` com cap.
- **Forma funcional cravada do `Participation` (correção C2 da revisão):**

```
slippage_bps = bps × (1 + k × q/ADV)
execução     = ref × (1 ± slippage_bps/10000)   # + compra, − venda
```

Linear em `q/ADV` até o cap — o cap corta quantidade, não preço.

- **Parâmetros default determinísticos (checklist do gate 2):** `bps = 1.0` e `k = 1.0`, ambos configuráveis. O default fixado em `k = 1.0` garante que dois runs com a mesma configuração produzem o mesmo número (RNF-01) e fecha o gate 3 — sem default cravado, o gate 3 ficaria não-determinístico. `bps = 1.0` alinha com o custo default de 1 bps da Fase 1 (D2), mantendo regime conservador de fábrica.

- **Fallback:** ADV indisponível (histórico insuficiente na janela de 20 pregões) ⇒ recai em `FixedBps` com aviso, sem falhar (SLP-03.2).
- **Cap de participação:** `qty = min(qty, cap × ADV)` nas **entradas** de qualquer tipo de ordem (SLP-03.3); corte < 1 ação ⇒ sem ordem, logado (SLP-03.5). Saídas nunca passam pelo cap (SLP-03.4).
- Slippage zero configurado continua sinalizando resultado irrealista no relatório (SLP-01.3), na política de ENG-03.2.

## Justificativa

- **Sem forma funcional, o gate 3 é não-determinístico (C2):** monotonicidade é critério de aceitação (SLP-03.1), não função. Duas implementações monotônicas diferentes produziriam números diferentes e nenhuma estaria "errada". A fórmula fechada transforma o CA em teste de igualdade contra valor de papel.
- **Linear até o cap é o default mais simples defensável:** um parâmetro (`k`) de sensibilidade, interpretável (slippage dobra quando `q = ADV/k`), sem curva a calibrar — não há dados de execução real para ajustar nada mais sofisticado nesta fase.
- **Cap na quantidade, não no preço (SLP-04):** cortar o preço quebraria a promessa de "limite nunca violado" e misturaria os dois mecanismos; cortar quantidade mantém o pressuposto de ausência de impacto permanente coerente.
- **Cap só em entradas:** saída integral é decisão fechada da Fase 1 (D3) e cap em saída distorceria a gestão de risco da estratégia.

## Alternativas descartadas

**Somente `FixedBps`.** Mais simples e determinístico, sem depender de volume. Descartada porque ignora participação: ordens grandes ficariam sistematicamente otimistas, e o viés de slippage não calibrado (RF-MET-03) dobraria de peso sem necessidade.

**Participação sem cap.** O preço piora monotonicamente com `q/ADV`, penalizando ordens grandes sem precisar de regra de corte. Descartada porque o notional não fica limitado: uma ordem que exceda em muito o ADV viola o pressuposto de ausência de impacto que o modelo pretende proteger — e o relatório declararia realismo que o modelo não sustenta.

**Cap também em saídas.** Simétrico às entradas e mais conservador. Descartada porque quebra D3 da Fase 1 (saída integral) e muda a semântica de risco da estratégia — a saída é o mecanismo de controle de perda e não deve ser truncada por liquidez do modelo.

**Formas não lineares (raiz quadrada, potência ajustável).** Modelos de crowding na literatura usam `slippage ∝ (q/ADV)^α` com α ≈ 0,5–0,8, mais realistas para ordens grandes. Descartadas nesta fase porque não há dado de execução real para calibrar α (o parâmetro seria chute com cara de precisão), e o cap de quantidade já domina o regime onde a não-linearidade importaria. Voltariam à mesa quando existir calibração contra execuções reais.

## Consequências

- `analytics/metrics.py` e o relatório usam o mesmo modelo para estratégia e benchmark (MET-04.2) — o benchmark herda slippage e cap como regras de entrada (S6).
- O relatório declara que o slippage é modelado, não calibrado (RF-MET-03) — a fórmula é default de fábrica, não medição.
- A forma funcional vira teste de fórmula fechada (fecha o gate 3).
- Custo aceito: o componente base `bps` do `Participation` precisa ser configurado junto com `k`; configurar só `k` sem `bps` não é um estado válido (validação no construtor).

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| Execução do `Participation` bate com `ref × (1 ± bps(1 + k·q/ADV)/10000)` | `test_participation_slippage_matches_closed_form` |
| Slippage cresce monotonicamente com `q/ADV` (SLP-03.1) | `test_slippage_monotonic_in_participation` |
| ADV indisponível ⇒ fallback em `FixedBps` com aviso, sem falhar (SLP-03.2) | `test_participation_falls_back_to_fixed_with_warning` |
| Limite nunca violado; slippage só em mercado (SLP-04.1/04.2) | `test_limit_price_never_violated_and_market_slippage_only` |
| Cap só em entradas; corte < 1 ação ⇒ sem ordem (SLP-03.3–03.5) | `test_cap_applies_to_entries_only_and_subshare_cancels` |

## Revisitar quando

Existir dado de execução real para calibrar (alphas não lineares, spread por ativo) — sinal típico: relatório de backtest comparado contra execuções reais da estratégia. Também revisitar se a Fase 2b introduzir aluguel/margem, que muda o custo de carregar posição e a dinâmica de participação.
