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
| `00-plataforma/fase-1` | 1.0 | ✅ aprovada | ✅ aprovada (v0.2) | ✅ aprovada (v0.1) | 🟡 Bloco A |
| `fase-2a` | 0.2 | 🟢 gate 1 aprovado (em revisão) | ✅ aprovada (v0.1) | 🟢 aprovada (v0.1) | ✅ T01–T18 |
| `fase-2b` | 0.2 | 🟢 gate 1 aprovado | — | — | — |
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
| [0004](adr/0004-ajuste-sobre-historico-completo.md) | Ajuste materializado sobre o histórico completo | aceito |
| [0005](adr/0005-execucao-condicional-e-fronteira-de-mutacao.md) | Execução condicional e fronteira de mutação (ENG-01.2 em duas partes) | aceito |
| [0006](adr/0006-modelo-de-slippage.md) | Modelo de slippage (fixo bps + participação com cap, forma funcional cravada) | aceito |
| [0007](adr/0007-ambiguidade-intrabarra.md) | Resolução da ambiguidade intrabarra (pior caso para o executor) | aceito |
| [0008](adr/0008-politica-de-sizing.md) | Política de sizing default (1/N, N do run, N=1 ⇒ all-in) | aceito |

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
