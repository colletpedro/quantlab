# Specs — quantlab

Este diretório é a fonte da verdade do projeto. Nenhuma linha de implementação é escrita antes da spec correspondente estar escrita, revisada e aprovada.

## Fluxo por módulo

1. **Requisitos** — o que o módulo faz, em linguagem de negócio, com critérios de aceitação testáveis (Given/When/Then).
2. **Design técnico** — arquitetura, interfaces públicas, schemas, decisões com alternativas descartadas.
3. **Plano de tarefas** — tarefas pequenas, ordenadas por dependência, escopo fechado e verificável.
4. **Implementação** — só depois dos três gates acima.

Cada transição entre etapas é um **gate check** explícito. Um gate reprovado volta para a etapa anterior; não se avança com pendência.

## Estado

| Spec | Versão | Requisitos | Design | Tarefas | Implementada |
|---|---|---|---|---|---|
| `00-plataforma/fase-1` | 1.0 | ✅ aprovada | ⬜ não iniciado | ⬜ | ⬜ |
| `01-ingestao` | — | — | — | — | ⬜ |
| `02-persistencia` | — | — | — | — | ⬜ |
| `03-engine` | — | — | — | — | ⬜ |
| `04-analytics` | — | — | — | — | ⬜ |
| `05-api` | — | — | — | — | ⬜ |
| `06-rag` | — | — | — | — | ⬜ |
| `07-infra` | — | — | — | — | ⬜ |

Até a Fase 2, `00-plataforma/fase-1-requirements.md` cobre os módulos 01–04. Cada um ganha spec própria quando a Fase 2 começar.

## ADRs

Decisões arquiteturais são **numeradas e imutáveis**. Quando uma decisão muda, cria-se um novo ADR que declara supersedência do anterior — o antigo não é editado nem removido. O histórico de decisões revertidas faz parte do que o repositório demonstra.

| # | Título | Status |
|---|---|---|
| [0001](adr/0001-mongodb-vs-relacional.md) | MongoDB como banco primário | aceito |
| [0002](adr/0002-execucao-no-open-seguinte.md) | Execução no `open` do pregão seguinte | aceito |
| [0003](adr/0003-ajuste-em-tempo-de-leitura.md) | Preço bruto persistido, ajuste na leitura | aceito |

## Roadmap

| Fase | Escopo | Estado |
|---|---|---|
| 0 | Fundação: repo, docker-compose, CI mínimo | em andamento |
| 1 | MVP: ingestão → Mongo → backtest SMA → métricas → gráfico | requisitos aprovados |
| 2 | Engine sério: custos, slippage, sizing, portfólio, walk-forward, Redis | — |
| 3 | Analytics e risco: Sortino, VaR, correlação, Black-Scholes, Monte Carlo | — |
| 4 | API FastAPI | — |
| 5 | Infra: Terraform, deploy, CI/CD completo | — |
| 6 | RAG sobre specs, código e resultados | — |
