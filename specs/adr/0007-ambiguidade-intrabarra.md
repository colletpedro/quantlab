# ADR-0007 — Resolução da ambiguidade intrabarra (pior caso para o executor)

**Status:** aceito
**Data:** 2026-08-14
**Contexto de decisão:** Fase 2a — engine (broker)

## Contexto

Com barras diárias, o caminho do preço dentro do pregão é desconhecido. Quando limite e stop do mesmo ativo seriam **ambos** tocados na mesma barra, a ordem de execução é indeterminada (RF-ORD-03). O bracket da Fase 2a (RF-SIG-01) torna o caso concreto: a mesma intenção carrega um limite e um stop que podem ser ambos cruzados em uma barra.

Dois cenários existem:

1. **Bracket de entrada** (limite L + sell-stop S): a intenção compra em L e protege com stop em S. Ambos tocados na mesma barra ⇒ a posição teria aberto e o stop teria sido atingido — com caminho desconhecido, não se sabe a ordem.
2. **Bracket de saída** (take-profit limite + stop sobre posição aberta): ambos tocados ⇒ ou o lucro é travado no limite, ou o stop corta a posição. Indeterminado da mesma forma.

Restrição adicional: o sell-stop só ativa com posição aberta (ORD-02.2, P2) — o stop de um bracket de entrada só fica vivo **após** a entrada preencher.

## Decisão

Resolver por **pior caso para o executor**, aplicado a todos os brackets, e registrar:

- **Bracket de entrada (L + S), ambos tocados na mesma barra:** a posição **abre em L** e **fecha no stop S** na mesma barra ⇒ perda realizada `(L − S + custos)`, fica **flat**, `Trade.ambiguous = True`.
- **Bracket de saída (take-profit limite + stop), ambos tocados:** o **stop preenche em S** (pior que o limite), `Trade.ambiguous = True`.

Ambos os casos incrementam `MechanismCounters.intrabar_ambiguities` (RF-MET-05), e a ambiguidade é registrada no trade (ORD-03.1/03.3).

## Justificativa

- **Coerente com "medir sem mentir".** O caminho intrabarra é desconhecido; assumir o melhor caso (limite primeiro) inflaria o resultado com um preenchimento que pode não ter acontecido. O pior caso é conservador na direção que a fase inteira adota (resultado pior e mais verdadeiro).
- **Determinístico (RNF-01).** A regra é fixa e sem aleatoriedade — duas execuções idênticas produzem o mesmo resultado, e o relatório pode explicar cada trade.
- **Registrado, não escondido.** `ambiguous=True` + contador no relatório transformam a ambiguidade em dado auditável, não em decisão silenciosa do engine.
- **Um único regime para todos os brackets.** Aplicar o pior caso apenas à entrada (ou apenas à saída) criaria assimetria sem justificativa de mecanismo — os dois casos têm a mesma raiz (caminho intrabarra desconhecido).

## Alternativas descartadas

**Ambos executam (entrada preenche e o stop dispara — e no bracket de saída, limite E stop preenchem).** Reflete o que pode acontecer no mercado real, onde ambos podem ser preenchidos. Descartada porque é otimista em relação ao executor (dupla contagem na mesma barra — no bracket de saída, receberia o limite e ainda fecharia no stop, um resultado impossível de dinheiro que não existe) e distorce a leitura de custos.

**Aleatório (sorteio por barra).** Sem viés sistemático e é o que um simulador de eventos discretos faria. Descartada porque quebra RNF-01 (determinismo) por construção: o backtest não seria reproduzível sem semear o gerador, e a semeadura introduziria um parâmetro novo que não corresponde a nenhuma decisão real.

**Limite primeiro (o caminho "do trader").** É o que quem escreveu a estratégia deseja — e por isso mesmo o mais perigoso: elimina a ambiguidade a favor de quem executa, escondendo o custo do caminho desconhecido. Descartada por ser exatamente o oposto do princípio organizador da fase.

## Consequências

- Todo bracket de entrada com ambos tocados na mesma barra gera um trade de perda `(L − S + custos)` com `ambiguous=True` — o relatório mostra esses trades como categoria própria (contadores de mecanismo).
- O número de ambiguidades é métrica de qualidade de dados: uma estratégia com muitas ambiguidades intrabarra tem resultado menos confiável, e isso fica visível.
- A regra vale também para ordens soltas (stop sobre posição + limite na mesma barra) — o pior caso é o stop preenchendo.
- Custo aceito: o pior caso é pessimista em relação ao limite-primeiro; a diferença é declarada no relatório (viés de RF-MET-03), não oculta.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| Bracket de entrada com L e S tocados ⇒ abre em L e fecha em S, flat, `ambiguous=True` | `test_intrabar_ambiguity_entry_bracket_worst_case` |
| Bracket de saída com ambos tocados ⇒ stop preenche em S, `ambiguous=True` | `test_intrabar_ambiguity_exit_bracket_worst_case` |
| Não existe caminho em que "ambos executam" (ORD-03.3) | idem (asserção de quantidade final e caixa) |
| Ambiguidades contadas no bloco de contadores (MET-05.2) | `test_report_mechanism_counters_block` |
| Stop de bracket de entrada não ativa antes de a entrada preencher (ORD-02.2) | `test_stop_never_activates_without_open_position` |

## Revisitar quando

Existirem dados intraday (a Fase 2a não tem, e ADR-0002 descartou VWAP/intrabarra por isso): com caminho conhecido, a ambiguidade deixa de existir e a regra de pior caso vira resolução direta pelo caminho real. Gatilho: aquisição de base intraday no roadmap.
