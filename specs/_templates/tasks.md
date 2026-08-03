# <Módulo / Fase> — Plano de tarefas

**Status:** draft | em revisão | aprovada
**Versão:** 0.1
**Data:** AAAA-MM-DD
**Design de origem:** `specs/<caminho>/design.md` v<X.Y>

> Último gate antes da implementação. Uma tarefa boa aqui cabe em um commit,
> tem critério de verificação objetivo e não depende de nada que ainda não
> exista. Se você não consegue escrever como verificar, a tarefa está grande
> demais ou mal entendida — quebre antes de começar.

---

## Ordem de execução

Ordenadas por dependência: uma tarefa só aparece depois de tudo que ela precisa.

```
T01 ──> T02 ──> T04
   └──> T03 ──┘
```

## Resumo

| # | Tarefa | Depende de | RFs cobertos | Estado |
|---|---|---|---|---|
| T01 | | — | | ⬜ |
| T02 | | T01 | | ⬜ |

Estados: ⬜ não iniciada · 🟡 em andamento · ✅ concluída · ⛔ bloqueada

---

## T01 — <título imperativo e curto>

**Depende de:** —
**RFs cobertos:** RF-XXX-01 (CA-01.1, CA-01.2)
**Arquivos:** `src/quantlab/<...>`, `tests/unit/<...>`

**Escopo**

<!-- O que esta tarefa faz. Duas ou três frases. -->

**Fora do escopo**

<!-- O que alguém razoavelmente esperaria daqui e que NÃO é para fazer agora,
     e em qual tarefa isso mora. É esta seção que impede a tarefa de inchar. -->

**Critério de verificação**

<!-- Objetivo e executável por quem não escreveu o código. Comando + resultado
     esperado, ou o teste que precisa passar. "Funciona" não é critério. -->

- [ ] `<comando>` termina com <resultado observável>
- [ ] Teste `<caminho>::<nome>` cobre CA-01.1 e falha sem esta mudança

**Riscos**

<!-- O que pode dar errado nesta tarefa especificamente. Omita se não houver. -->

---

## T02 — <título>

**Depende de:** T01
**RFs cobertos:**
**Arquivos:**

**Escopo**

**Fora do escopo**

**Critério de verificação**

- [ ]

---

## Encerramento da fase

Só marcar quando todas as tarefas estiverem ✅.

- [ ] Todos os RFs da spec têm ao menos uma tarefa que os cobre
- [ ] Todos os critérios de aceitação citados têm teste correspondente
- [ ] `make check` verde
- [ ] Definition of Done do `requirements.md` integralmente satisfeita
- [ ] `specs/README.md` e `specs/CHANGELOG.md` atualizados

## Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.1 | AAAA-MM-DD | Rascunho inicial |
