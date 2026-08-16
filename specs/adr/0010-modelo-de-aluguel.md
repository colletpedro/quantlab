# ADR-0010 — Modelo de aluguel (borrow fee determinístico e disponibilidade)

**Status:** proposto (gate 2 da Fase 2b)
**Data:** 2026-08-14
**Contexto de decisão:** Fase 2b — engine (short/aluguel, RF-SHT-03)

## Contexto

Vender a descoberto exige alugar o papel. A Fase 2b introduz shorts (RF-SHT-01/02) e precisa de um custo de carregamento para a posição short — o **borrow fee**. O projeto não tem dado de empréstimo ingerido (o universo do ADR-0001 é OHLCV + corporate actions), então o modelo tem duas decisões de calibração abertas:

1. **Quanto custa alugar** — o default precisa ser determinístico, testável em forma fechada (RNF-03) e declarado como premissa não calibrada (RF-MET-06).
2. **A disponibilidade do papel** — o mercado real tem hard-to-borrow (papel sem oferta, taxa mais alta, recall). Sem dado de disponibilidade, o default honesto é declarar a premissa (ilimitada) e torná-la configurável (R1), não fingir que se mede o que não se tem.

Restrições herdadas: custos nunca entram no preço de execução (SLP-04.3 da 2a); o fee é custo de **carregamento** (diário), não de transação; a conciliação (RF-POR-04 CA-04.2 da 2a) ganha um termo próprio, debitado **uma única vez**.

## Decisão

- **Modelo determinístico, anualizado, debitado diariamente** sobre o notional short:

```
fee_diário = |qty_short| × close_d × fee_anual / 252
```

- `fee_anual` default **0,50% a.a.**, configurável.
- **Débito:** no **close**, em etapa própria (depois de marcar, antes de checar margem — design §4), direto do caixa. **Nunca** entra no preço de execução (herda SLP-04.3).
- **Incidência:** apenas sobre pregões com posição short **aberta no close** (CA-03.2) — não incide sobre o dia em que a posição já foi coberta no open.
- **Relatório:** categoria **própria** (CA-03.3), separada de corretagem/slippage; termo próprio na conciliação (§6 do design), **uma única vez** (a armadilha da dupla contagem da T13).
- **Disponibilidade (R1):** default **ilimitada** — `unlimited = true`, nenhum short é bloqueado (CA-03.4, lado esquerdo). Com `unlimited = false`, um `ENTER_SHORT` de ativo indisponível na data **não executa**, é **logado e contado** (`MechanismCounters.borrow_rejections`, CA-03.4, lado direito). A indisponibilidade é configurável (conjunto de tickers/datas), não derivada de dado de empréstimo.
- **Viés declarado no relatório (RF-MET-06):** o default de 0,50% a.a. é premissa **não calibrada**; a disponibilidade ilimitada é **otimista** para estratégias que dependem de short (sem hard-to-borrow).

## Justificativa

- **"Medir sem mentir" pede o custo explícito, mesmo sem calibração.** Omitir o fee tornaria o short sistematicamente otimista sem declaração; cobrar uma taxa arbitrária esconderia a arbitrariedade. O default de 0,50% a.a. é um valor de prateleira, **declarado como tal** — o leitor vê o custo e o viés juntos.
- **Determinístico e de forma fechada (RNF-01/RNF-03).** A fórmula é função pura de `(|qty|, close)` — o teste bate o valor de papel (CA-03.1) e a conciliação fecha com o termo exato. Nenhum dado de mercado entra no modelo; dois runs idênticos produzem o mesmo fee.
- **Diário no close, não no open da entrada.** O fee é custo de carregamento — o que importa é a posição existente ao marcar, não a transação; o close é o ponto de marcação da 2a (POR-02.2) e a etapa de débito fica naturalmente ordenada antes da checagem de margem (a margem usa o caixa pós-fee).
- **Disponibilidade configurável, default ilimitada (R1).** Restringir por default exigiria dado de empréstimo que não existe no universo; a premissa ilimitada é declarada como viés e o mecanismo de restrição fica pronto para quando o dado existir — a mesma postura do ADR-0006 (modelo não calibrado, mas com forma cravada).

## Alternativas descartadas

**Fee sobre o notional médio do período (suavizado).** Menos ruído no custo diário. Descartada porque quebra a forma fechada diária (o teste de papel exigiria média), mistura o fee com a dinâmica da posição e dificulta a auditoria por trade — o modelo diário é auditável barra a barra.

**Fee embutido no preço de execução (ajustar o fill da venda).** Um único ajuste, sem etapa própria. Descartada porque viola SLP-04.3 (custos fora do preço) e confunde custo de transação com custo de carregamento — o preço de execução continuaria "limpo" e o fee apareceria como slippage, escondendo a categoria.

**Hard-to-borrow real como default (papel sem oferta ⇒ short bloqueado).** Mais realista onde se tem o dado. Descartado como default porque exigiria ingestão de disponibilidade/empréstimo que o universo não tem; a restrição fica configurável (CA-03.4) e o viés da premissa ilimitada é declarado (RF-MET-06).

**Base 360 dias (convenção de mercado de renda fixa).** Alinharia com a convenção. Descartada porque o projeto usa 252 (pregões) em todas as fórmulas de retorno anualizado (RF-MET-04 da 2a, turnovover); 360 introduziria uma segunda convenção sem ganho.

## Consequências

- `BorrowFeeModel` (frozen) vive em `engine/margin.py` (§3.4 do design); o débito é do laço, o `convert` só consulta `is_available` para `ENTER_SHORT`.
- A conciliação ganha `total_borrow_fees` no `ReconciliationReport` — termo próprio, uma única vez (§6).
- `MechanismCounters` ganha `borrow_rejections` (contado no `convert`, como `unfilled_cash_orders` da 2a).
- O relatório declara o fee em categoria própria e o viés "aluguel não calibrado + disponibilidade ilimitada" na seção fixa (RF-MET-06).
- Custo aceito: estratégias short-heavy ficam com custo de carregamento que pode não refletir o mercado real — o viés é o mecanismo de honestidade, não a taxa em si.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| Forma fechada: `Σ_d |qty| × close_d × 0,005/252` em 10 pregões (CA-03.1) | `test_borrow_fee_closed_form_10_days` |
| Fee incide só em dias com short aberto no close (CA-03.2) | `test_borrow_fee_only_on_days_with_open_short` |
| Categoria própria no relatório (CA-03.3) | `test_report_borrow_fee_own_category` |
| Default ilimitado nunca bloqueia (CA-03.4, esq.) | `test_borrow_availability_unlimited_default_never_blocks` |
| Restrito ⇒ short não executa, logado e contado (CA-03.4, dir.) | `test_borrow_restricted_blocks_short_and_logs` |
| Fee no termo próprio da conciliação, uma única vez (SHT-04.2) | `test_reconciliation_closes_with_negative_qty` |

## Revisitar quando

Existir dado de empréstimo (disponibilidade, taxas por papel, recall) no universo — o sinal típico é a comparação do relatório contra execuções reais de short. Também revisitar a taxa default se a Fase 3 (analytics de risco) calibrar custos de carregamento por classe.
