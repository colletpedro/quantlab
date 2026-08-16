# ADR-0011 — Protocolo walk-forward e fronteira de mutação IS/OOS

**Status:** proposto (gate 2 da Fase 2b)
**Data:** 2026-08-14
**Contexto de decisão:** Fase 2b — engine (walk-forward, RF-WFK)

## Contexto

Um único backtest sobre o histórico completo é otimista: os parâmetros foram (implicitamente ou explicitamente) escolhidos olhando o período inteiro. A Fase 2b substitui essa falsa confiança por **walk-forward** — otimização in-sample por grade determinística + avaliação out-of-sample honesta (RF-WFK), com o viés de múltiplos testes (MHT) declarado (RF-MET-06).

Três decisões de peso precisam de registro próprio:

1. **Isolamento estrito IS/OOS.** O engine do IS nunca pode indexar séries OOS — e "não passar a série" não basta: o acesso precisa ser bloqueado por construção (RF-WFK-01 CA-01.1), e a fronteira de mutação do ENG-01.2 (ADR-0005) precisa ser estendida ao OOS: mutar dados OOS não pode alterar os parâmetros selecionados no IS (RF-WFK-04 CA-04.1). O ADR-0005 declarou exatamente esse gatilho: "A Fase 2b introduzir entradas condicionais de compra (buy-stop): a fronteira de mutação precisa ser reauditada para o novo tipo de ordem, e a parte 2 ganha um caso novo".
2. **Ancoragem dos folds.** Rolling (janela IS fixa deslizante) vs anchored (janela IS crescente) muda a comparabilidade entre folds (decisão do autor, D7/R7).
3. **Onde o WF encaixa na arquitetura.** Rodar o `run_backtest_multi` da 2a como **caixa preta** por fold (herança por construção, mesma filosofia do benchmark 1/N da T15) em vez de reimplementar o laço.

## Decisão

- **Isolamento estrito por construção (CA-01.1):** cada fold constrói `PriceSeries`/`UnionCalendar` **truncados no fim do IS** para o run IS; o `MarketView` indexa o array truncado e qualquer acesso além do fim é `EngineError` — a fronteira é do array, não da disciplina de quem chama. A série OOS **não é passada** a nenhum run IS.
- **Warmup do OOS = cauda do IS (R4):** a avaliação OOS roda sobre a série composta (últimas `warmup` barras ≤ fronteira, dados IS — sem lookahead) + segmento OOS; decisões durante a cauda são aquecimento (descartadas); equity registrado a partir do primeiro bar OOS. Mutar o OOS não altera o warmup (CA-01.3).
- **Métrica de seleção IS (R5):** **Sharpe anualizado com `rf = 0`** sobre a equity IS — forma fechada única, compartilhada com o relatório (sem drift entre seleção e declaração de MHT).
- **Resultado honesto:** equity = **concatenação exata dos segmentos OOS** (RF-WFK-03 CA-03.1); relatório mostra a tabela fold a fold (IS/OOS, parâmetros selecionados — CA-03.2) e os parâmetros médios.
- **Ancoragem (D7/R7):** **rolling** (janela IS de tamanho fixo, deslizante) como **default**; **anchored** (janela IS crescente) configurável para **medir a diferença**, não adivinhar.
- **Fronteira de mutação estendida (ADR-0005 revisado):** o teste de mutação do ENG-01.2 ganha a parte OOS — **mutar barras OOS não altera os parâmetros selecionados no IS** (CA-04.1) — e a parte IS é reauditada para `ENTER_SHORT`/`EXIT_SHORT` e buy-stop (CA-04.2).
- **Otimização determinística (RNF-01):** grade explícita de parâmetros (default); otimizador estocástico exige seed travado e declarado. `grid_size` e `n_folds` declarados no relatório (MHT — CA-06.2).
- **Orçamento (RNF-10/RF-WFK-05):** o "30 s" do RNF-04 vale para o run único; o WF tem orçamento em duas escalas — **por fold** (default 30 s para IS+OOS de 20 ativos × janela) e **total** (`n_folds × 30 s` + margem declarada) — medidos pelo harness.

## Justificativa

- **Construção > convenção (princípio da casa).** "Não passar a série OOS" é convenção — um refactor poderia reintroduzir o dado; a fronteira no array é construção — o `EngineError` por índice fora do intervalo não depende de ninguém lembrar. É a mesma postura do ADR-0005 (partes 1 e 2 do ENG-01.2).
- **Rolling como default é o padrão da literatura e o mais comparável entre folds** (janelas IS de tamanho igual ⇒ mesma quantidade de dado de seleção por fold). Anchored fica disponível para medir o efeito do tamanho crescente — decisão do autor (R7), registrada, não adivinhada.
- **Warmup pela cauda do IS é sem lookahead por construção** (dados ≤ fronteira são IS) e não desperdiça dados avaliáveis do OOS; a alternativa de descartar as primeiras barras do OOS abriria buraco na concatenação (spec §8.1).
- **Caixa preta por fold** garante que a avaliação OOS herda **todas** as regras de execução da 2b (custos, slippage, cap, margem, borrow fee, buy-stop) por construção — se o WF reimplementasse o laço, o resultado OOS poderia divergir do run único sem que ninguém percebesse.
- **Métricas None em fold quebrado (R6):** fold OOS com fundo quebrado reporta a equity negativa real e métricas `None` explícito — mesma política do ADR-0009/MRG-03.

## Alternativas descartadas

**Walk-forward reimplementando o laço (injeção de parâmetros no meio do engine).** Evitaria N re-runs e a sobrecarga de construção de calendários. Descartada porque duplicaria as regras de execução (a segunda fonte de lookahead que a filosofia "herança por construção" evita) e porque o custo de `grid_size × n_folds + n_folds` runs é exatamente o que o orçamento do RNF-10 declara e mede — o design não esconde o custo, declara-o.

**Anchored como default.** Janela IS crescente usa mais dado de seleção nos folds finais. Descartado como default porque janelas de tamanho variável entre folds prejudicam a comparabilidade (o melhor parâmetro de um fold com 8 anos de IS não é comparável ao de um com 3); mantido configurável para medir (R7).

**Warmup do OOS descartando as primeiras barras do OOS.** Simples e sem cauda. Descartado (R4, spec §8.1): desperdiça dados avaliáveis e abre buraco na concatenação dos segmentos; a cauda do IS é sem lookahead por construção.

**Um único split treino/teste (um fold).** Mais simples e o padrão clássico de ML. Descartado porque produz **um** número OOS (alta variância) e não mede a estabilidade dos parâmetros ao longo do tempo — que é uma das perguntas do walk-forward; folds múltiplos permitem a tabela fold a fold (CA-03.2).

**Métricas de seleção alternativas (retorno total, Calmar, Sortino).** Cada uma tem sua força. Descartadas como default porque o Sharpe anualizado com `rf = 0` é a métrica padrão da casa (Fase 1/2a, relatórios) — a seleção usa a mesma métrica que o relatório declara (R5), evitando a divergência "seleciono por X, reporto por Y". Permanecem disponíveis como política configurável de seleção.

## Consequências

- O ADR-0005 é **estendido, não substituído**: as partes 1 e 2 do ENG-01.2 permanecem; a parte OOS (CA-04.1) é adicionada e a parte IS é reauditada para shorts/buy-stop (CA-04.2).
- `engine/walkforward.py` (novo) roda `run_backtest_multi` como caixa preta; `sharpe_annualized_rf0` vive lá e é importada por `analytics/metrics.py` (uma implementação, dois consumidores).
- O relatório declara métrica de seleção, `grid_size` e `n_folds` na seção "run" (reconstruível do JSON — CA-06.2) e o viés MHT na seção fixa (RF-MET-06).
- O harness do RNF-10 mede por fold e total, com séries sintéticas determinísticas se não houver base ingerida (padrão T17).
- Fold OOS com fundo quebrado: equity negativa real na concatenação, métricas `None` e exclusão de comparação automática (MRG-03/CA-03.3).

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| IS nunca indexa OOS — acesso bloqueado por construção (CA-01.1) | `test_is_run_never_indexes_oos_bars_engine_error` |
| Folds disjuntos; união dos OOS cobre a janela sem sobreposição (CA-01.2) | `test_folds_are_disjoint_and_oos_union_covers_window` |
| Warmup do OOS = cauda do IS, sem lookahead (CA-01.3/R4) | `test_oos_warmup_uses_is_tail_without_lookahead` |
| Grade determinística (CA-02.1/RNF-01) | `test_walkforward_grid_is_deterministic_params_identical` |
| OOS usa params do MESMO fold (CA-02.2) | `test_oos_uses_params_selected_in_same_fold` |
| Seleção = Sharpe anualizado rf=0, declarado (CA-02.3/R5) | `test_is_selection_metric_is_annualized_sharpe_rf0_declared` |
| Equity = concatenação exata dos OOS (CA-03.1) | `test_walkforward_equity_is_exact_oos_concatenation` |
| Mutar OOS não altera params IS (CA-04.1 — ADR-0005 estendido) | `test_mutating_oos_does_not_change_is_selected_params` |
| Mutar futuro do IS não altera intenções/execuções anteriores, incl. shorts e buy-stop (CA-04.2) | `test_mutating_future_is_bars_does_not_change_prior_intentions_long_short_buy_stop` |
| Orçamento por fold e total medidos e reportados (CA-05.1/RNF-10) | `test_walkforward_harness_reports_per_fold_and_total_budgets` |
| MHT declarado: métrica/grid/folds na seção "run" (CA-06.2) | `test_run_section_reports_mht_metric_grid_folds_reconstructible` |

## Revisitar quando

A Fase 3 (analytics de risco) definir um protocolo de seleção alternativo (ex.: otimização contínua em vez de grade) — a troca é um ADR novo supersedendo este. Também revisitar se dados intraday entrarem no roadmap (ADR-0007): o isolamento IS/OOS por construção independe da granularidade, mas o orçamento do RNF-10 precisaria de reescala.
