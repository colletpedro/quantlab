# HANDOFF — Fase 0 (fundação)

**Data:** 2026-08-03
**Escopo entregue:** estrutura, ferramental, CI e templates de processo.
**Escopo deliberadamente não entregue:** qualquer lógica de negócio.

Os subpacotes `ingestion/`, `storage/`, `engine/`, `strategies/` e `analytics/` estão
vazios porque o gate de design da Fase 1 não foi feito. O `requirements.md` está
aprovado; o `design.md` não existe.

---

## 1. O que foi criado, por bloco

### Bloco 1 — pacote e dependências

| Arquivo | Conteúdo |
|---|---|
| `pyproject.toml` | Python 3.12+, gerenciado por `uv`, build via hatchling, layout `src/` |
| `uv.lock` | Lock versionado — reprodutibilidade entre máquina e CI (RNF-01) |
| `.python-version` | `3.12` |
| `src/quantlab/__init__.py` | `__version__ = "0.1.0"` |
| `src/quantlab/cli.py` | App Typer com o único comando `version`; callback configura o logging |
| `src/quantlab/__main__.py` | Despacha `python -m quantlab` para o CLI |
| `src/quantlab/config.py` | `Settings` (pydantic-settings, prefixo `QUANTLAB_`) + `get_settings()` cacheado |
| `src/quantlab/logging.py` | structlog: JSON fora de dev, console em dev, decidido por `QUANTLAB_ENV` |
| `src/quantlab/exceptions.py` | `QuantlabError` → `DataError`, `ConfigError`, `EngineError`. Sem lógica |
| `src/quantlab/{ingestion,storage,engine,strategies,analytics}/__init__.py` | Vazios, com docstring dizendo qual gate estão esperando |
| `src/quantlab/py.typed` | Marca o pacote como tipado |
| `config/universe.yml` | 20 tickers americanos, 11 setores GICS, survivorship bias declarado no topo |

Runtime: pandas, numpy, matplotlib, pymongo, yfinance, typer, pydantic,
pydantic-settings, structlog, pyyaml.
Dev: pytest, pytest-cov, pytest-mock, mypy, ruff, pre-commit, pip-audit
(+ `types-pyyaml` e `pandas-stubs`, exigidos por `mypy --strict`).

Defaults de `Settings` conforme as premissas da spec: `initial_capital = 100_000.0`
(premissa 4) e `risk_free_rate = 0.0` (premissa 7).

### Bloco 2 — ambiente e execução

| Arquivo | Conteúdo |
|---|---|
| `docker-compose.yml` | MongoDB 7 apenas. Volume nomeado `quantlab_mongo_data`, porta configurável, healthcheck via `mongosh`, variáveis de `.env`. Redis fora — é Fase 2 |
| `.env.example` | Todas as `QUANTLAB_*` documentadas, mais `QUANTLAB_ENV` e as variáveis do container |
| `Dockerfile` | Multi-stage: builder com `uv`, runtime slim, usuário não-root (uid 1000). Fora do compose por enquanto |
| `.dockerignore` | Mantém o contexto enxuto e impede `.env` na imagem |
| `Makefile` | `up down logs install test test-unit test-integration lint format typecheck audit check clean` |

### Bloco 3 — qualidade e testes

- **ruff** — linha 100, `target-version = py312`, regras `E, F, I, N, UP, B, SIM, RUF`,
  isort integrado com `known-first-party = ["quantlab"]`.
- **mypy** — `strict = true`, plugin do pydantic, `warn_unreachable`. Roda sobre
  `src` e `tests`.
- **pytest** — markers `unit` e `integration` registrados com `--strict-markers`;
  integração desmarcada por default via `addopts = -m "not integration"`, de modo que
  a suíte da Fase 0 roda offline (RNF-06).
- **cobertura** — `fail_under = 80` escopado a `quantlab.engine` e `quantlab.analytics`
  (RNF-02), com `branch = true` e `skip_empty = true`.
- **`tests/`** — `conftest.py` com três fixtures de infraestrutura (`workdir`,
  `clean_env`, `settings`), `unit/test_smoke.py`, e `integration/` e `fixtures/`
  criados vazios com `.gitkeep` explicando para que servem.
- **`.pre-commit-config.yaml`** — `check-added-large-files`, `check-yaml`,
  `check-toml`, `end-of-file-fixer`, `trailing-whitespace`, `ruff-check`,
  `ruff-format` e `mypy`.

### Bloco 4 — CI e governança

- **`.github/workflows/ci.yml`** — push em `main` e todo PR.
  Job `quality`: `setup-uv` com cache por `uv.lock` → `make install` → `make lint` →
  `make typecheck` → `make test` → publica `coverage.xml` como artefato.
  Job `audit`: `make audit`, com `continue-on-error: true`.
  Sem serviços externos.
- **`.github/dependabot.yml`** — `pip` e `github-actions`, mensal, agrupando
  dependências de dev e de runtime em PRs separados.
- **`.github/pull_request_template.md`** — checklist de gate: spec aprovada, ADRs
  respeitados (com ADR-0002 e ADR-0003 como itens verificáveis), testes cobrindo os
  critérios de aceitação citados, e changelog atualizado.

### Bloco 5 — templates de processo

`specs/_templates/`: `requirements.md`, `design.md`, `tasks.md` e `adr.md`.

Os templates carregam as regras do processo, não só as seções: o de requisitos exige
critérios falseáveis e uma seção de questões em aberto que precisa estar vazia para o
status virar "aprovada"; o de ADR exige que cada alternativa descartada apareça com a
própria força e tem uma tabela ligando invariante ao teste que a prova.

### Bloco 6 — documentação

- **`CLAUDE.md`** — proibição de implementar sem spec aprovada, ordem de leitura
  obrigatória, os invariantes de ADR-0002 e ADR-0003 escritos como regra verificável,
  convenções (type hints, mypy strict, structlog em vez de `print`, fixtures
  sintéticas, commits pequenos, nunca `git add .`) e os comandos do Makefile.
- **`README.md`** — o que é o projeto, estado da Fase 0, stack com a razão de cada
  escolha, como rodar, estrutura de pastas, link para `specs/` e limitações conhecidas
  separadas em "da Fase 0" e "do desenho da Fase 1, já assumidas".
- **`CONTRIBUTING.md`** — fluxo spec-driven, os quatro gates e o critério de aprovação
  de cada um.
- **`.gitignore`** — Python, caches, artefatos e `.env`.

---

## 2. Resultado da verificação final

Executado em 2026-08-03, macOS 25.4.0, Python 3.12.3 no venv do projeto.

| # | Passo | Resultado |
|---|---|---|
| a | `make install` | ✅ exit 0 — 87 pacotes resolvidos |
| b | `make lint` | ✅ exit 0 — `All checks passed`, 27 arquivos já formatados |
| c | `make typecheck` | ✅ exit 0 — `Success: no issues found in 13 source files` |
| d | `make test` | ✅ exit 0 — 1 teste passou, cobertura 100% (2 arquivos vazios pulados), piso de 80% atingido |
| e | `make check` | ✅ exit 0 |
| f | `python -m quantlab version` | ✅ exit 0 — `[info] quantlab.version version=0.1.0` |
| g | `docker compose config` | ✅ exit 0 — compose válido, `name: quantlab` |
| h | `pre-commit run --all-files` | ✅ exit 0 — 8 hooks, todos `Passed` |

Extras verificados: `make test-unit` (exit 0), `make test-integration` (exit 0),
`make audit` (exit 0, nenhuma vulnerabilidade conhecida).

Dois problemas foram encontrados durante a verificação e corrigidos no commit
`fix(make)`:

1. `make test-integration` retornava vermelho porque o pytest devolve exit 5 quando não
   coleta nada, e ainda não existe teste de integração.
2. `make audit` listava o próprio `quantlab` como "não auditado" — ruído que esconderia
   um skip real.

O CI **não foi executado** — não há remote configurado. O workflow foi validado apenas
por inspeção e pelo fato de invocar exatamente os mesmos alvos do Makefile que rodaram
verdes localmente.

---

## 3. Decisões que tomei por conta própria — revise

Em ordem decrescente de impacto.

### 3.1 Reorganizei o layout de `specs/`

As specs estavam na raiz de `specs/` com nomes descritivos (`MongoDB vs Relational.md`,
`Trading Execution Guide.md`, …), mas o índice dentro de `specs/README.md` já apontava
para `adr/0001-mongodb-vs-relacional.md` e afins — os links estavam quebrados, e o
enunciado da tarefa também se referia a `specs/00-plataforma/fase-1-requirements.md`.
Movi os arquivos para o layout que o próprio README declara:

| Antes | Depois |
|---|---|
| `Claude Trading Platform README.md` | `specs/README.md` |
| `Trading Platform Requirements.md` | `specs/00-plataforma/fase-1-requirements.md` |
| `MongoDB vs Relational.md` | `specs/adr/0001-mongodb-vs-relacional.md` |
| `Trading Execution Guide.md` | `specs/adr/0002-execucao-no-open-seguinte.md` |
| `Ajuste em Tempo de Leitura.md` | `specs/adr/0003-ajuste-em-tempo-de-leitura.md` |
| `Claude Trading Changelog.md` | `specs/CHANGELOG.md` |

**O conteúdo não foi alterado** — só os caminhos. Confirme que os nomes de destino são
os que você quer, especialmente `specs/CHANGELOG.md`, que era o único sem caminho
declarado no README.

### 3.2 MongoDB sobe com autenticação, e a URI default do código não tem credencial

O compose cria um usuário root (`quantlab`/`quantlab` por default). Mas o default de
`Settings.mongo_uri` é `mongodb://localhost:27017`, sem credencial. Isso significa que
**`cp .env.example .env` é obrigatório** — sem isso o app não conecta no container.

A alternativa seria subir o Mongo sem auth para funcionar com zero configuração.
Preferi o caminho com credencial por ser mais próximo do real, e documentei o
`cp .env.example .env` como primeiro passo no README e no CONTRIBUTING. Se você achar
que a fricção não compensa na Fase 0, é uma linha para mudar.

### 3.3 Escolhas que o enunciado não fixou

- **`hatchling`** como build backend, e **`.python-version = 3.12`** para o venv de
  desenvolvimento. `requires-python` continua `>=3.12`. Pinei o 3.12 para garantir
  wheels de pandas/numpy/matplotlib; a máquina tem Python 3.14 como sistema.
- **`pandas-stubs` e `types-pyyaml`** entraram em dev — `mypy --strict` não passa sem
  eles, e não estavam na lista do enunciado.
- **`get_settings()` com `lru_cache`** em `config.py`. O enunciado pedia só a classe
  `Settings`. Achei que um acessor cacheado é encanamento, não regra de negócio, mas é
  código a mais do que foi pedido.
- **`QUANTLAB_ENV`** controla o formato do log (dev → console, resto → JSON). Não virou
  campo de `Settings` de propósito, para não alterar a lista de campos que você fixou.
- **`py.typed`** e um **`.dockerignore`**, que não estavam no enunciado.
- **mypy no pre-commit roda via `uv run`** (hook `local`), não pelo `mirrors-mypy`. Um
  mypy em ambiente isolado não enxergaria os stubs de pydantic e pandas, e divergiria
  de `make typecheck`.
- **CI invoca `make lint`, `make typecheck` e `make test` como passos separados** em vez
  de um `make check` só. São exatamente os mesmos comandos que `check` encadeia — a
  separação existe só para a falha apontar direto o portão que quebrou.
- **`dependabot` usa o ecossistema `pip`**, como você pediu. Hoje existe um ecossistema
  `uv` nativo, que entenderia `uv.lock` melhor. Vale trocar se você concordar.
- **Universo:** 20 tickers, 11 setores GICS, com `BRK-B` no formato do yfinance.
  Curadoria minha — confira se a composição serve.
- **`make test-integration` tolera exit 5** do pytest enquanto não houver teste de
  integração. Há um comentário no Makefile mandando remover a tolerância quando o
  primeiro entrar. **Não esqueça disso** — enquanto ela existir, apagar todos os testes
  de integração passaria despercebido.

### 3.4 Sobre a cobertura enquanto os pacotes estão vazios

`fail_under = 80` está configurado e escopado corretamente a `engine/` e `analytics/`,
mas hoje ele é **trivialmente satisfeito**: os pacotes têm zero statements, o coverage
reporta 100% e `skip_empty` pula os arquivos vazios. O piso só passa a significar
alguma coisa quando houver código lá. Está declarado no README, em "Limitações
conhecidas".

---

## 4. O que deliberadamente NÃO foi feito

Tudo abaixo depende do gate de design da Fase 1 e **não deve ser começado** antes de
`specs/00-plataforma/fase-1-design.md` estar aprovado.

**Domínio (escopo do gate de design)**

- Ingestão: cliente `yfinance`, normalização de timezone, coleta de eventos
  corporativos, idempotência, validação de qualidade (RF-ING-01 a 05).
- Persistência: schemas de documento, índice composto `(ticker, date)`, repositório,
  ajuste em tempo de leitura, hash determinístico da série (RF-PER-01 a 03).
- Engine: laço de barras, API que expõe só índices ≤ `i`, execução no `open` seguinte,
  contabilidade, custos, interface de estratégia (RF-ENG-01 a 06).
- Estratégias: SMA cross (RF-ENG-06).
- Analytics: CAGR, Sharpe, max drawdown, taxa de acerto, benchmark buy-and-hold,
  seção fixa de vieses (RF-ANA-01 a 03).
- CLI: comandos `ingest` e `backtest`, e o gráfico Matplotlib (RF-CLI-01 a 03).
- Modelo `Portfolio` para N posições (decisão D5 da spec).

**Testes que a spec exige e que ainda não existem**

- O teste de mutação de barras futuras que prova a invariante anti-lookahead
  (CA-01.2 do engine) — requisito de aceitação da fase.
- O teste de conciliação de PnL (CA-04.2 do engine).
- Fixtures sintéticas de split e dividendo com resultado calculado no papel
  (RNF-03, CA-02.1 a CA-02.4 da persistência).

**Infraestrutura adiada de propósito**

- Redis — Fase 2.
- `Dockerfile` no `docker-compose.yml` — na Fase 0 o CLI roda no host.
- Job de integração no CI com serviço MongoDB — a suíte da Fase 0 é offline (RNF-06).
- Schema validation no lado do Mongo, citada em ADR-0001 como mitigação — é decisão de
  design de persistência.
- Benchmark de performance para RNF-04 (10 anos em menos de 5 s) — não há o que medir.

**Pendências menores anotadas durante o trabalho**

- Trocar o ecossistema do dependabot de `pip` para `uv` (ver 3.3).
- Remover a tolerância a exit 5 em `make test-integration` (ver 3.3).
- Decidir se `Settings.mongo_uri` deve ter credencial no default (ver 3.2).
- `make install` não instala os hooks do git. É um comando à parte
  (`uv run pre-commit install`), documentado no CONTRIBUTING. Se você preferir que
  `install` faça as duas coisas, é uma linha.

---

## 5. Próximo passo sugerido

**Escrever `specs/00-plataforma/fase-1-design.md`** a partir de
`specs/_templates/design.md`. É o gate 2, e é o único que destrava a implementação.

Sugestão de ordem, porque algumas decisões de design amarram outras:

1. **Schemas e repositório primeiro.** Documentos de barra e de evento corporativo, o
   índice `(ticker, date)`, e a assinatura da leitura ajustada. É onde ADR-0003 vira
   código, e é o que a ingestão e o engine consomem.
2. **Interface de estratégia e API do engine.** A parte crítica é desenhar a API de
   modo que a estratégia **não consiga** ver o futuro (CA-01.3) nem o estado da carteira
   (CA-05.2). Se isso for garantido por construção, o teste de CA-01.2 passa a ser
   confirmação em vez de rede de segurança.
3. **Contabilidade.** Onde caixa, posição, custos e PnL vivem, e como a identidade de
   CA-04.2 (`realizado + não realizado + custos ≡ equity_final − equity_inicial`) é
   verificável a qualquer instante.
4. **Analytics e relatório.** Métricas, alinhamento do benchmark ao fim do warm-up
   (CA-02.2), e a seção fixa de vieses.

Três pontos que valem atenção no gate, por serem os que costumam ser decididos por
omissão:

- A fronteira exata onde a data vira naive (RNF-07). Se ficar espalhada, vaza timezone.
- Onde a série ajustada é materializada em memória e por quanto tempo — ADR-0003 aceita
  o custo de CPU, mas o desenho precisa deixar claro quem paga.
- Como o gap de pregões (CA-01.5) é representado no trade, já que ele precisa ser
  auditável depois.

Depois do design aprovado vem `tasks.md` (gate 3) e só então a primeira linha de
implementação.
