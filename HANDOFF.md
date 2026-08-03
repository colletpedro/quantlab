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

- ~~Trocar o ecossistema do dependabot de `pip` para `uv`~~ — feito no fechamento, §6.
- Remover a tolerância a exit 5 em `make test-integration` quando o primeiro teste de
  integração entrar (ver 3.3). Ainda pendente.
- ~~Decidir se `Settings.mongo_uri` deve ter credencial no default~~ — resolvido no
  fechamento, §6: o campo deixou de ter default.
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

---

## Fase 0 — fechamento

**Data:** 2026-08-03 (mesmo dia, sessão de fechamento)

A seção 2 acima validou o ambiente por comando isolado, no host. Esta seção valida o
que só se prova rodando de verdade: CI em runner real, Mongo subindo e persistindo, e
três achados de correção que a inspeção não pegou.

### CI — resultado real, não inspeção

Não havia remote. Criado `github.com/colletpedro/quantlab`, **privado**, com
`gh repo create --source=. --remote=origin`, e dado push de `main`.

| Run | Trigger | Resultado | Duração (job `Lint, tipos e testes`) |
|---|---|---|---|
| [30829987942](https://github.com/colletpedro/quantlab/actions/runs/30829987942) | push inicial | ✅ verde | 20s |
| [30830495163](https://github.com/colletpedro/quantlab/actions/runs/30830495163) | push (mongo_uri + testes) | ✅ verde | 25s |
| [30830713040](https://github.com/colletpedro/quantlab/actions/runs/30830713040) | push (dependabot uv) | ✅ verde | 21s |

**Cache de dependências:** no primeiro push, os dois jobs deram `No GitHub Actions
cache found` — esperado, era o primeiro run de todos. No segundo push, ainda miss:
o commit tinha adicionado `pytest-randomly` e mudado `uv.lock`, e a chave do cache é
um hash do lock (`cache-dependency-glob: uv.lock`), então o hash mudou. Miss legítimo,
não bug. No terceiro push — `uv.lock` inalterado desde o segundo — os logs mostraram
`Cache restored successfully` nos dois jobs, confirmando que o cache funciona quando
deveria. Também confirmado: jobs paralelos no mesmo run não veem o cache um do outro
(o save só acontece no post-step, depois que o job termina) — por isso o primeiro run
deu miss nos dois jobs mesmo processando em paralelo.

**Nenhuma falha específica de Linux apareceu** — nem versão de action, nem path
case-sensitive, nem permissão de token. A única observação foi um aviso (não erro) do
próprio GitHub: `Node.js 20 is deprecated... astral-sh/setup-uv@v6` sendo forçado a
rodar em Node 24. Não bloqueia nada hoje; describe [a
descontinuação](https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/)
de runners Node 20, e algumas actions do workflow (`checkout`, `upload-artifact`,
`setup-uv`) já têm versões novas esperando revisão — ver a seção de PRs abertas abaixo.

**Efeito colateral não pedido:** assim que o repositório foi criado com
`.github/dependabot.yml` versionado, o Dependabot abriu PRs sozinho. Cinco estão
abertas hoje, todas com CI verde:

| PR | O quê |
|---|---|
| [#1](https://github.com/colletpedro/quantlab/pull/1) | `astral-sh/setup-uv` 6 → 7 |
| [#2](https://github.com/colletpedro/quantlab/pull/2) | `actions/checkout` 5 → 7 |
| [#3](https://github.com/colletpedro/quantlab/pull/3) | `actions/upload-artifact` 4 → 7 |
| [#4](https://github.com/colletpedro/quantlab/pull/4) | grupo dev-dependencies, 9 pacotes (sob o ecossistema `pip` antigo) |
| [#5](https://github.com/colletpedro/quantlab/pull/5) | grupo runtime-dependencies, 10 pacotes (sob o ecossistema `pip` antigo) |

Não fechei nem dei merge em nenhuma — mexer em PR é ação visível para terceiros e não
foi pedida. #4 e #5 foram abertas sob o ecossistema `pip`, que a seção 6 abaixo trocou
por `uv`; elas provavelmente ficam órfãs quando o Dependabot reavaliar sob a config
nova. Sua decisão: fechar manualmente, ou deixar o Dependabot substituir sozinho.

### Mongo — o que foi exercitado

Sequência completa, contra o container real:

1. `cp .env.example .env`
2. `make up` — subiu, esperou o healthcheck, reportou `healthy` em poucos segundos
   (`docker compose ps` confirmou: `Up ... (healthy)`)
3. Escrita e leitura usando **exatamente** a `QUANTLAB_MONGO_URI` do `.env`
   (`mongodb://quantlab:quantlab@localhost:27017/?authSource=admin`), via `mongosh`
   dentro do container, numa coleção descartável (`quantlab_smoke_test.scratch`) —
   provou que a credencial configurada no compose é a mesma que autentica
   de fato, não só que o compose sobe.
4. `make down` — removeu o container, preservou o volume nomeado (`docker volume ls`
   confirmou `quantlab_mongo_data` ainda existindo depois do down).
5. `make up` de novo — o compose reutilizou o volume (não recriou), voltou a ficar
   healthy.
6. Reli o mesmo documento pela mesma URI — **presente, idêntico**. Prova o volume
   nomeado, não só o container.
7. `db.dropDatabase()` na coleção de teste, `make down`. Ambiente limpo.

Nada falhou nesta etapa. A única coisa que a exercitação expôs — não uma falha do
Mongo, mas do código que fala com ele — foi o item 3 abaixo.

### `Settings.mongo_uri` — por que virou obrigatório

O HANDOFF original (§3.2) já tinha sinalizado o risco sem resolvê-lo: o default
`mongodb://localhost:27017` não carrega credencial. Qualquer outro MongoDB sem
autenticação rodando na 27017 da mesma máquina — de outro projeto, por exemplo —
seria aceito da mesma forma. O app conectaria, leria ou gravaria no banco errado, e
nada indicaria isso: nem erro, nem log, nem exceção.

Resolvido: `mongo_uri` não tem mais default. `Settings.__init__` intercepta o
`pydantic.ValidationError` de campo ausente e relança como `ConfigError`, com
`cp .env.example .env` na própria mensagem — a correção acionável que a regra de
exceções do CLAUDE.md pede.

Ao mexer nisso, apareceu um segundo problema, fora da lista original: `clean_env`
(fixture de `tests/conftest.py`) limpava as variáveis `QUANTLAB_*` do processo, mas
não o `lru_cache` de `get_settings()`. O primeiro teste da suíte que chamasse
`get_settings()` congelaria os valores para todos os testes seguintes, e o resultado
passaria a depender de qual teste rodou primeiro — exatamente o tipo de
não-determinismo que RNF-01 proíbe. Corrigido: `clean_env` agora chama
`get_settings.cache_clear()` antes e depois de cada teste. Um par de testes
(`test_get_settings_sees_this_tests_own_mongo_uri_a`/`_b` em
`tests/unit/test_config.py`) prova o isolamento, definindo valores diferentes da
mesma variável e conferindo que cada um só enxerga o seu.

Adicionado `pytest-randomly` como dependência de dev para confirmar isso de verdade:
suíte rodada em ordem fixa (`-p no:randomly`) e em ordem aleatória com várias seeds
(`1`, `42`, `999`, mais uma automática) — mesmo resultado em todas, 5 testes passando.

O `test_smoke.py` também precisou de ajuste: o callback do CLI chama
`get_settings()`, que agora exige `mongo_uri`. O teste passou a setar
`QUANTLAB_MONGO_URI` via `monkeypatch.setenv`, em vez de depender de um `.env` no
diretório — o `.env` local existe na minha máquina (criado no passo do Mongo acima),
mas não existiria no CI, e o teste não pode passar só localmente por acidente de
ambiente.

`README.md` e `CONTRIBUTING.md` não precisaram de mudança: os dois já listavam
`cp .env.example .env` como primeiro passo obrigatório, não como sugestão — a mudança
de comportamento já estava coberta pela instrução existente.

### Dependabot — conclusão

Verificado antes de mexer, como pedido. Fontes:

- [GitHub Changelog — "Dependabot version updates now support uv in general
  availability"](https://github.blog/changelog/2025-03-13-dependabot-version-updates-now-support-uv-in-general-availability/)
  (2025-03-13): GA, não beta.
- [Documentação oficial do
  `astral-sh/uv`](https://docs.astral.sh/uv/guides/integration/dependabot/) sobre
  integração com Dependabot, com o formato de configuração.
- Página de referência do GitHub sobre ecossistemas suportados: `uv` está listado
  como valor de `package-ecosystem` de primeira classe, com suporte a
  `dependency-type` (usado nos grupos `dev-dependencies`/`runtime-dependencies` já
  configurados) equivalente ao de `pip`.

Conclusão: suporte estável e confirmado. Troquei `package-ecosystem: "pip"` por
`package-ecosystem: "uv"` em `.github/dependabot.yml`. Validado de duas formas depois
do push: a run de "Dependabot Updates" sob o ecossistema `uv` apareceu automaticamente
e completou com sucesso (nenhuma PR nova foi aberta — as dependências já estavam nas
versões que ele sugeriria); e o YAML foi validado localmente com `yaml.safe_load`
antes do commit.

### Algo que apareceu e não estava na lista

Nada além do que já foi descrito acima (o cache de `get_settings()`, e o efeito
colateral das PRs automáticas do Dependabot). Os oito comandos da verificação final
original (a–h) mais os quatro extras pedidos nesta rodada (`test-unit`,
`test-integration`, `audit`, `docker compose config`) foram todos reexecutados depois
de cada mudança e terminaram verdes — sequência completa registrada por último logo
antes do push final.

---

## Bloco A — storage

**Data:** 2026-08-03
**Origem:** `fase-1-tasks.md` v0.1, Bloco A, tarefas A1 a A10
**Escopo:** apenas `storage/`. `ingestion/`, `engine/`, `strategies/` e `analytics/`
continuam vazios — são dos Blocos B a E.

### 1. O que foi implementado, por tarefa

Um commit por tarefa, na ordem A1 → A10.

| Tarefa | Entrega | Arquivos |
|---|---|---|
| **A1** | Cliente Mongo com pool, timeouts explícitos e fechamento determinístico. `DataError` acionável citando `make up` e `QUANTLAB_MONGO_URI` | `storage/client.py` |
| **A2** | As cinco coleções de §3.1–3.5 com índices idempotentes | `storage/schema.py` |
| **A3** | `to_bson_date`/`from_bson_date`, só no repositório | `storage/repository.py`, `storage/models.py` |
| **A4** | Upsert de barras por `(ticker, date)` com log de revisão | `storage/repository.py` |
| **A5** | Upsert de eventos por `(ticker, date, kind)` com log de revisão | `storage/repository.py` |
| **A6** | Quarentena em coleção própria, payload bruto, todas as razões | `storage/repository.py` |
| **A7** ⭐ | Fator de ajuste cumulativo por `cumprod` reverso, O(n) | `storage/adjustment.py` |
| **A8** | `PriceSeries` congelada + arrays read-only; `get_series` | `storage/series.py`, `storage/repository.py` |
| **A9** | SHA-256 canônico, 6 casas fixas | `storage/hashing.py` |
| **A10** | Job de integração no CI; remoção da dívida do exit 5 | `.github/workflows/ci.yml`, `Makefile` |

Pontos onde o design é específico e o mecanismo foi implementado como escrito:

- **A2** — `bars` tem `{ticker: 1, date: 1}` **único** e nenhum índice isolado em
  `date`. Há um teste que falha se alguém adicionar um. `IXSCAN` provado com
  `explain()`, percorrendo o plano aninhado em vez de olhar só o topo (é aí que essa
  verificação costuma passar por acidente).
- **A3** — a conversão existe só em `repository.py`. Um teste de arquitetura varre os
  imports de `storage/` e falha se outro módulo tocar em instante.
- **A6** — coleção própria, não flag; payload bruto preservado inclusive nos campos
  que o quantlab não conhece; todas as razões.
- **A7** — `C` é o fechamento **bruto** do pregão anterior; `cumprod` reverso;
  bordas de §3.7.
- **A8** — `frozen=True` **e** `flags.writeable = False`, as duas; eventos sobre o
  histórico completo.
- **A9** — 6 casas decimais fixas, ordem por data, separador fixo, sem localização.

### 2. Resultado da verificação e do CI

**Local — tudo verde:**

| Comando | Resultado |
|---|---|
| `make install` | exit 0 |
| `make lint` | exit 0 |
| `make typecheck` | exit 0 — 34 arquivos, `mypy --strict` |
| `make test` | exit 0 — 108 unitários, cobertura ≥ 80% |
| `make test-unit` | exit 0 — 108 |
| `make test-integration` | exit 0 — 43 contra Mongo real |
| `make check` | exit 0 |
| `make audit` | exit 0 — nenhuma vulnerabilidade |
| `pre-commit run --all-files` | exit 0 — 8 hooks |
| `python -m quantlab version` | exit 0 |
| `docker compose config` | exit 0 |

**CI — [run 30836546555](https://github.com/colletpedro/quantlab/actions/runs/30836546555), os três jobs verdes:**

| Job | Duração | Resultado |
|---|---|---|
| Lint, tipos e testes | 22 s | ✅ (offline, RNF-06) |
| **Testes de integração** | 40 s | ✅ **43 passed, 108 deselected** contra `mongo:7` |
| Auditoria de dependências | 18 s | ✅ |

O log do job de integração confirma `collected 151 items / 108 deselected / 43
selected` seguido de `43 passed` — os testes rodaram de verdade contra o serviço, não
foram silenciosamente coletados como zero.

**Verificação de A10, feita localmente e não commitada:** com os testes presentes
`make test-integration` sai 0; movendo todos os `test_*.py` de `tests/integration/`
para fora, o alvo falha (`108 deselected`, pytest exit 5); restaurados, volta a 0.

**A7 conferido por mutação.** Como é a tarefa de maior risco e os testes passaram de
primeira, verifiquei que eles têm dente, quebrando a implementação de propósito:

| Mutação | Testes que caem |
|---|---|
| `bisect_left` → `bisect_right` (a barra da data ex passa a ser ajustada) | 15 |
| split multiplica o preço em vez de dividir | 13 |
| erro de 1e-7 no fator de volume | 1 |

Arquivo restaurado byte a byte depois (conferido com `diff`), 27 testes verdes.

### 3. Decisões que tomei por conta própria — revise

**3.1 Dividendo ≥ fechamento anterior levanta `DataError`.** O design não diz o que
fazer. O fator `(C − d)/C` viraria zero ou negativo, e preço nulo ou negativo
atravessaria o resto do sistema parecendo um número. Optei por falhar alto. A
alternativa — avisar e ignorar o evento — é defensável e produziria uma série
*parcialmente* ajustada, que é o tipo de resultado que este projeto trata como pior
que nenhum. Se preferir a outra, é uma linha.

**3.2 Zero negativo normalizado no hash.** `f"{-0.0:.6f}"` devolve `"-0.000000"`, que
difere de `"0.000000"` e daria hashes distintos para valores numericamente iguais.
Não deveria aparecer em preço, mas é exatamente a "diferença de última casa" que §3.8
manda neutralizar. Normalizei. Não está escrito no design.

**3.3 O que entra no hash.** §3.8 diz "cada campo" sem enumerar. Incluí data (ISO-8601)
mais os cinco campos OHLCV. **Ticker e flag `adjusted` ficaram de fora** — os dois já
são registrados à parte no relatório. Consequência: duas séries de tickers diferentes
com preços idênticos colidiriam no hash. Aceitável hoje; se você quiser o ticker
dentro, é decisão sua e muda todo hash já gravado.

**3.4 `MongoRepository` é classe, não funções soltas.** §3.7 mostra
`def get_series(ticker, start, end, adjusted)` sem `self` nem parâmetro de banco. Como
alguém precisa segurar a conexão, virou método — a assinatura pública vista pelo
chamador é a mesma.

**3.5 `volume` é `float64` na `PriceSeries`.** Split de razão não inteira deixa o
volume fracionário; manter `int` obrigaria a truncar em silêncio. O volume não é usado
pelo engine na Fase 1 (premissa 5: sem limite de participação).

**3.6 `dates` é array de objetos `date`.** Não `datetime64`, que reintroduziria
instante e fuso contra RNF-07. Custa performance de acesso, mas datas não estão no
laço quente — o engine compara índices.

**3.7 `ruff format` deixou de tocar `specs/`.** Esta versão do ruff reformata blocos
```python dentro de Markdown, e ao versionar o design v0.2 o `make lint` passou a
querer reescrevê-lo. Documento normativo não é reformatado por ferramenta, e os ADRs
são declarados imutáveis em CLAUDE.md §2. Commit próprio.

**3.8 Status dos gates nas specs.** Os headers diziam "aguardando gate check 2" e
"draft — aguardando gate check 3", contradizendo a instrução de implementar. Marquei
os três como aprovados em commit separado, antes de qualquer código, conforme
CLAUDE.md §1. **A aprovação é sua declaração, não inferência minha** — se algum gate
não estiver mesmo fechado, é aqui que se reverte.

**3.9 `explicit_package_bases` no mypy.** Com dois `conftest.py` os nomes de módulo
colidiam e a checagem parava antes de começar.

### 4. Onde o design v0.2 se mostrou ambíguo ou incompleto — para a v0.3

Em ordem de impacto.

**4.1 §3.6 é impossível de cumprir ao literal.** "`datetime` só aparece em
`ingestion/normalizer.py` e `storage/repository.py`" — mas o tipo do domínio é
`datetime.date`, do mesmo módulo da biblioteca padrão, e a tabela da própria §3.6 diz
"domínio: `datetime.date` sempre". Proibir o módulo proibiria o tipo que o design
manda usar em toda parte. Implementei a regra pretendida: o que não pode vazar é a
classe `datetime` e o aparato de fuso (`UTC`, `timezone`, `tzinfo`); `date` e
`timedelta` são livres. **A v0.3 deveria escrever a regra assim**, porque B5 vai
implementar a mesma varredura para o projeto inteiro e precisa da formulação certa.

**4.2 `ingestion_run_id` na `PriceSeries` não tem de onde sair.** §3.7 lista o campo
entre os metadados, mas o documento de `bars` em §3.1 **não tem esse campo** — só
`quarantined_bars` tem. Nada em storage sabe preenchê-lo. Deixei `None` e atendi
PER-03.1 pelo outro caminho que a §3.1 permite: `last_ingested_at`, derivado de
`max(ingested_at)` sobre a janela. A v0.3 precisa escolher: (a) adicionar
`ingestion_run_id` ao documento de `bars`, (b) resolver por consulta a
`ingestion_runs`, ou (c) tirar o campo da `PriceSeries`.

**4.3 §3.4 e §3.5 não declaram índice nenhum.** `ingestion_runs` e `backtest_runs`
ficaram sem, porque inventar índice é decidir por um padrão de acesso que ninguém
escreveu. Quando B4 e F1 forem escrever nessas coleções, o padrão vai aparecer e o
índice deve ser especificado então.

**4.4 §3.8 não enumera os campos do hash nem diz como formatar a data.** Ver 3.3
acima. "Cada campo com 6 casas decimais" não se aplica a uma data.

**4.5 As duas bordas de §3.7 se sobrepõem.** "Evento anterior à primeira barra é
ignorado" e "dividendo sem barra anterior vira aviso e é ignorado" descrevem a mesma
condição quando o evento é um dividendo. Implementei como: descarte silencioso para
split, descarte com aviso para dividendo (a regra mais específica vence). Vale
escrever assim.

**4.6 §3.7 não diz o que fazer com dividendo ≥ `C`.** Ver 3.1.

**4.7 §3.7 não especifica a representação de `dates` na `PriceSeries`.** §4.1 sugere
`NDArray` ao listar `dates` junto dos preços, mas não diz o dtype. Ver 3.6.

**4.8 A semântica de escrita de `bars` não está escrita.** §3.2 declara "upsert pela
chave única" para `corporate_actions`, e diz que a política de log de ING-03.2 vale
"para barras" — mas não há uma §3.1 equivalente dizendo o mesmo de `bars`. Deduzi da
simetria. Vale explicitar.

### 5. Próximo passo

**Bloco B — ingestão**, que consome o Bloco A e é o próximo na ordem de dependência
de `tasks.md`. B1 (cliente yfinance) → B2 (normalizador) → B3 (validador) → B4
(orquestrador) → B5 (teste de arquitetura) → B6 (CLI `ingest`).

Dois avisos para quem pegar:

- **B5 deve reaproveitar a formulação de 4.1**, não a literal de §3.6. O recorte de
  storage já está em `tests/unit/test_storage_date_isolation.py` e serve de base — B5
  é a mesma varredura ampliada para o projeto inteiro.
- **B3 (validador) é quem decide o que é inválido.** O Bloco A só entrega o destino
  (`quarantine_bars`). As regras de ING-05.1 não estão implementadas em lugar nenhum
  ainda, e os avisos não-bloqueantes de ING-05.2/05.3 dependem de `ingestion_runs`,
  que B4 escreve.

Antes de B1, vale decidir 4.1 e 4.2 na v0.3 do design: as duas afetam código que o
Bloco B vai escrever, e corrigir a spec depois do código é o que CLAUDE.md §1 proíbe.
