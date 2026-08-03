# Contribuindo

quantlab é **spec-driven**: `specs/` é a fonte da verdade, e código sem spec aprovada
não entra. Este documento descreve o fluxo e os gates. As convenções de código estão
em [CLAUDE.md](CLAUDE.md).

## O fluxo

Cada módulo passa por quatro etapas, nesta ordem:

| # | Etapa | Artefato | Template |
|---|---|---|---|
| 1 | **Requisitos** | O que o módulo faz, em linguagem de negócio, com critérios de aceitação testáveis em Given/When/Then | [`specs/_templates/requirements.md`](specs/_templates/requirements.md) |
| 2 | **Design** | Arquitetura, interfaces públicas, schemas, decisões com alternativas descartadas | [`specs/_templates/design.md`](specs/_templates/design.md) |
| 3 | **Tarefas** | Tarefas pequenas, ordenadas por dependência, com critério de verificação | [`specs/_templates/tasks.md`](specs/_templates/tasks.md) |
| 4 | **Implementação** | Código e testes | — |

## Os gates

Cada transição é um **gate check** explícito. Um gate reprovado volta para a etapa
anterior — não se avança com pendência aberta.

**Gate 1 — requisitos → design.** Todo critério de aceitação é falseável (dá para
imaginar o teste que o quebra). A seção de questões em aberto está vazia. Premissas e
vieses estão declarados.

**Gate 2 — design → tarefas.** Toda interface pública tem assinatura tipada e contrato.
Cada invariante tem um teste nomeado que o prova. Decisões caras de reverter viraram
ADR, não parágrafo.

**Gate 3 — tarefas → implementação.** Cada tarefa cabe em um commit, tem critério de
verificação objetivo e não depende de nada inexistente. Todo RF da spec é coberto por
ao menos uma tarefa.

**Gate 4 — implementação → merge.** O checklist do
[template de PR](.github/pull_request_template.md), integralmente.

Descobrir no meio da implementação que a spec está errada é normal e esperado. O
caminho é **voltar, corrigir a spec, e só então mexer no código** — nunca ajustar o
código e deixar a spec desatualizada.

## ADRs

Decisão arquitetural cara de reverter vira um ADR em [`specs/adr/`](specs/adr/), a
partir de [`specs/_templates/adr.md`](specs/_templates/adr.md).

ADRs são **numerados e imutáveis**. Quando uma decisão muda, cria-se um ADR novo
declarando supersedência do anterior; o antigo não é editado nem removido. O histórico
de decisões revertidas faz parte do que este repositório demonstra.

Alternativa descartada precisa aparecer com a **sua força**, não como espantalho. Se
você não consegue escrever o que a alternativa tem de bom, você não a avaliou.

## Rodando localmente

```bash
cp .env.example .env
```

```bash
make install
```

```bash
uv run pre-commit install
```

Depois disso, `make check` antes de cada commit. É o mesmo que o CI roda.

Testes de integração exigem o banco no ar:

```bash
make up
```

```bash
make test-integration
```

## Commits e PRs

- Commits pequenos, um assunto cada, mensagem no imperativo dizendo **por quê**.
- **Nunca `git add .`** — adicione arquivo por arquivo, pelo caminho.
- Prefixos: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`.
- O PR aponta a spec e os critérios de aceitação que cobre. Sem isso, não há como
  revisar contra o quê.
- Atualize `specs/CHANGELOG.md` quando uma spec ou ADR mudar de versão ou status, e
  `specs/README.md` quando um gate mudar de estado.

## Uma regra sobre resultados

Este projeto mede estratégias. Um resultado ruim é um resultado: se a estratégia perde
para o buy-and-hold, reporte assim. Nunca ajuste uma premissa, uma janela ou um
parâmetro de custo para melhorar um número. Todo relatório declara seus vieses
(RF-ANA-03) — é isso que separa um instrumento de medição de uma peça de marketing.
