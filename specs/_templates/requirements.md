# <Módulo / Fase> — Requisitos

**Status:** draft | em revisão | aprovada
**Versão:** 0.1
**Data:** AAAA-MM-DD
**Próximo gate:** `specs/<caminho>/design.md`

> Copie este arquivo para `specs/<NN>-<modulo>/requirements.md`. Enquanto o status
> não for **aprovada**, nenhuma linha de implementação do módulo é escrita.
> Requisitos descrevem **o quê**, em linguagem de negócio. Como se implementa é
> assunto do `design.md`.

---

## 1. Objetivo

<!-- Um parágrafo. O que este módulo entrega e por quê.
     Diga também o que o objetivo NÃO é — é onde o escopo costuma vazar. -->

## 2. Escopo

**Dentro:**

- <!-- item -->

**Fora (e para qual fase vai):**

- <!-- item — fase N -->

## 3. Glossário

Todo termo de domínio usado nos requisitos, com **definição operacional** — a que
permite escrever um teste, não a que soa bem.

| Termo | Definição operacional |
|---|---|
| | |

---

## 4. Requisitos funcionais

Prefixo `RF-<SIGLA>-NN`. Cada RF tem ao menos um critério de aceitação `CA-NN.M`
escrito em **Given/When/Then**, e cada CA precisa ser falseável: se não dá para
imaginar o teste que o quebra, o critério ainda está vago.

### 4.1 <Área>

**RF-XXX-01 — <título curto>**
<!-- Uma ou duas frases. -->

- **CA-01.1** — *Dado* <estado inicial>, *quando* <evento>, *então* <resultado observável>.
- **CA-01.2** — *Dado* ..., *quando* ..., *então* ....

<!-- Marque com ⭐ os requisitos que são invariantes do sistema, não features.
     Um invariante quebrado é bug de correção, não regressão de funcionalidade. -->

---

## 5. Requisitos não funcionais

Só o que for específico deste módulo. Os RNFs globais (RNF-01 a RNF-08) valem
sempre e não precisam ser repetidos — cite-os quando o módulo os tensionar.

- **RNF-XX — <nome>.** <critério mensurável, com número>

## 6. Premissas

Simplificações aceitas conscientemente. Cada uma é uma dívida declarada: se
aparecer num relatório, precisa estar escrita lá também.

1. <!-- premissa -->

## 7. Decisões fechadas

Questões que estavam abertas no draft e foram resolvidas neste gate. Decisão
arquitetural de peso não mora aqui — vira ADR.

| # | Questão | Decisão | Razão |
|---|---|---|---|
| D1 | | | |

## 8. Questões em aberto

Precisa estar **vazia** para o status virar "aprovada".

| # | Questão | Bloqueia o quê | Responsável |
|---|---|---|---|
| Q1 | | | |

## 9. Definition of Done

Lista verificável. Cada item é observável por alguém que não escreveu o código.

- [ ] <!-- item -->

## 10. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.1 | AAAA-MM-DD | Rascunho inicial |
