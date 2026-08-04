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

---

## Bloco B — ingestão

**Data:** 2026-08-03
**Origem:** `fase-1-tasks.md` v0.1, Bloco B, tarefas B1 a B6, mais Parte 0 (design v0.3)
**Escopo:** `ingestion/` e o CLI de B6. `engine/`, `strategies/` e `analytics/`
continuam vazios — são dos Blocos C a E.

### 0. Design v0.3 — as 8 ambiguidades do Bloco A, decididas

Commit próprio (`c76c41d`), antes de qualquer código do Bloco B, como CLAUDE.md §1
exige. As oito decisões do enunciado foram aplicadas literalmente às seções que a
ambiguidade original ocupava (§3.1, §3.4/§3.5, §3.6, §3.7 ×4, §3.8). Uma delas exigiu
mudança de código no mesmo commit: `PriceSeries.ingestion_run_id` existia como campo
morto (nunca preenchido, nunca lido) e foi removido — o código não podia continuar
contradizendo a spec por um campo sem uso.

Durante B4, uma nona decisão apareceu — o índice de `ingestion_runs` (§3.4), que a
v0.3 tinha deixado explicitamente adiado "para quando B4 definir o padrão de acesso".
Virou v0.4 (`375bf5a`), no mesmo commit que passou a escrever na coleção, como a
própria v0.3 instruía.

### 1. O que foi implementado, por tarefa

Um commit por tarefa, na ordem B1 → B6, mais os commits de infraestrutura que cada
tarefa expôs como necessários.

| Tarefa | Entrega | Arquivos |
|---|---|---|
| **B1** | `MarketDataProvider` (Protocol), `ResilientProvider` (retry+backoff+ING-04.2 por composição), `YFinanceProvider` (fino, sem resiliência própria) | `ingestion/provider.py`, `resilient_provider.py`, `yfinance_provider.py` |
| **B2** | `normalize_timestamp`/`normalize_prices`/`normalize_corporate_actions` — fronteira de entrada | `ingestion/normalizer.py` |
| **B3** | `validate_bars` — função pura, ING-05.1 bloqueante (10 razões) + ING-05.2/05.3 aviso | `ingestion/validator.py` |
| **B4** | `run_ingestion` — laço por ticker, `IngestionRepository` (Protocol), `ingestion_runs` | `ingestion/orchestrator.py`, `storage/repository.py` (novos métodos), `storage/schema.py` (índice) |
| **B5** | Teste de arquitetura projeto-inteiro, formulação v0.3 | `tests/unit/test_architecture_date_isolation.py` (substitui o recorte de storage de A3) |
| **B6** | `python -m quantlab ingest`, universo default | `cli.py`, `universe.py` |

Pontos onde o enunciado é específico e o mecanismo foi implementado como pedido:

- **B1** — `auto_adjust=False` (ADR-0003); resposta vazia de preços é `DataError`
  **sem retry** (não é falha transitória); corporate actions vazias **não** são falha
  (ausência de provento é legítima); retry com backoff exponencial (1×, 2×, 4×...).
  Protocolo + `FakeProvider` — nenhum teste, unitário ou de integração, toca rede.
- **B2** — único ponto de conversão `pd.Timestamp → date` da ingestão; ticker
  canonicalizado para maiúsculas na fronteira.
- **B3** — dez razões de CA-05.1, avaliadas de forma independente (não em cadeia de
  `elif`); ING-05.2 com `np.busday_count`; ING-05.3 suspensa só por split, não por
  dividendo.
- **B4** — `ingestion_runs` aberto **antes** de processar qualquer ticker, para que o
  `run_id` exista a tempo de ser gravado em cada `QuarantinedBar` (referência cruzada
  de design §3.3); falha de um ticker não impede os demais.
- **B5** — bloqueante no CI; verificado localmente (não commitado) que
  `datetime.now()` num módulo de domínio derruba o teste.
- **B6** — sem `--tickers`, usa `config/universe.yml` (CA-01.1); exit ≠ 0 quando
  qualquer ticker falha (ING-04.1); `ensure_schema` roda no início, então o comando
  funciona contra um Mongo que nunca viu quantlab.

### 2. Resultado da verificação e do CI

**Local — tudo verde, sequência completa após o último commit:**

| Comando | Resultado |
|---|---|
| `make install` | exit 0 |
| `make lint` | exit 0 |
| `make typecheck` | exit 0 — `mypy --strict` |
| `make test` | exit 0 — 177 unitários |
| `make test-integration` | exit 0 — 54 contra Mongo real |
| `make check` | exit 0 |
| `make audit` | exit 0 — nenhuma vulnerabilidade |
| `pre-commit run --all-files` | exit 0 |
| `python -m quantlab version` | exit 0 |

**Estabilidade de ordem confirmada à força bruta:** `make test-integration` rodado 5
vezes seguidas com `pytest-randomly` (ordem diferente a cada vez) — 54/54 em todas.
Isso não era garantido de graça: a primeira rodada expôs um bug real (seção 3 abaixo).

**CI — [run 30860993103](https://github.com/colletpedro/quantlab/actions/runs/30860993103), os três jobs verdes:**

| Job | Resultado |
|---|---|
| Lint, tipos e testes | ✅ (offline, RNF-06) |
| Testes de integração | ✅ `collected 231 items / 177 deselected / 54 selected` → `54 passed` |
| Auditoria de dependências | ✅ |

**B5 verificado, não commitado:** introduzi `datetime.now()` em
`storage/adjustment.py` (módulo de domínio, fora da fronteira) — o teste de
arquitetura falhou apontando exatamente o arquivo e o nome importado; restaurado
byte a byte depois (`diff` confirmou).

### 3. Um bug real de cross-test, encontrado e corrigido na fonte

**Não foi um problema de fixture — foi um bug de biblioteca acionado pela primeira
vez que o projeto chamou `configure_logging()` mais de uma vez no mesmo processo.**

`tests/integration/test_cli_ingest.py` usa `CliRunner` para invocar o comando `ingest`
de verdade, o que roda o callback `main()` do Typer e chama `configure_logging()`
de novo (a primeira chamada acontece na importação de `quantlab.cli`, a segunda
dentro do teste). `configure_logging()` usava `cache_logger_on_first_use=True`.

Isso não é cache de configuração global — é `BoundLoggerLazyProxy.bind()`
sobrescrevendo `.bind` **na própria instância** do proxy, na primeira chamada de log,
permanentemente. Um logger de módulo como `_log = get_logger(__name__)` em
`storage/repository.py` — criado uma vez na importação, reusado pela vida inteira do
processo — fica preso, depois da primeira chamada seguinte a uma reconfiguração, na
config daquele instante. **Nenhuma chamada futura a `structlog.configure()` ou
`structlog.reset_defaults()` desfaz isso**, porque não é o config global que está
sendo consultado — é um método sobrescrito na instância.

Sintoma: testes de A4/A6 que dependem da fixture `log_events`
(`structlog.testing.capture_logs()`) passavam isolados, mas falhavam de forma
dependente de ordem sempre que rodavam depois de `test_cli_ingest.py` — confirmado
rodando `make test-integration` repetidas vezes com ordem aleatória.

**Corrigido na fonte** (`src/quantlab/logging.py`): `cache_logger_on_first_use=False`.
quantlab é CLI/batch, não serviço de alto throughput — o ganho de performance do
cache não compensava esta classe de bug, que afetaria qualquer código futuro que
chamasse o CLI programaticamente mais de uma vez no mesmo processo, não só os testes.
A fixture de restauração em `test_cli_ingest.py` ficou como defesa em profundidade
(ela sozinha, sem a correção na fonte, **não bastava** — confirmado durante o
diagnóstico).

### 4. Decisões que tomei por conta própria — revise

**4.1 `IngestionRepository` e `MarketDataProvider` como `Protocol`, não classes
concretas.** O orquestrador e a CLI recebem `MongoRepository`/`YFinanceProvider` só em
produção; nos testes, `FakeRepository`/`FakeProvider` implementam a mesma forma sem
herdar de nada. Sem isso, testar "um ticker ruim no meio da lista não impede os
outros" exigiria Mongo mesmo no unitário. Não estava pedido explicitamente, mas é o
que torna B4 e B6 testáveis sem infra pesada.

**4.2 `_build_provider()` isolado em `cli.py`.** Único ponto de acesso a
`YFinanceProvider`/rede no comando `ingest`; testes de integração fazem
`monkeypatch.setattr(cli_module, "_build_provider", ...)` para trocar por
`FakeProvider` e exercitar o comando real (`CliRunner`, Mongo real, código de saída)
sem tocar `yfinance`. Sem esse ponto único, não haveria como testar a CLI ponta a
ponta sem rede.

**4.3 `run_ingest()` separado do comando Typer `ingest()`.** A lógica de RF-CLI-01
(parse de data, resolução de ticker, chamada ao orquestrador) é uma função só, sem
Typer nem Mongo — testável direto com fakes. `ingest()` só faz parsing de CLI e
conecta dependências reais. Mesmo padrão de `IngestionRepository`.

**4.4 `ensure_schema()` dentro do comando `ingest`, não como passo manual separado.**
RF-CLI-01 não menciona setup de schema. Sem chamar aqui, o comando falharia contra
Mongo limpo com erro de coleção inexistente, em vez de simplesmente funcionar — decidi
que "funciona contra Mongo real" implicitamente inclui "mesmo que seja a primeira
vez". Testado explicitamente (`test_ingest_command_creates_schema_on_a_fresh_database`).

**4.5 `--from`/`--to` obrigatórios em `ingest`, sem default.** RF-CLI-01 não declara
default de janela para ingestão (D5 do requirements é o default de janela do
**backtest**, RF-CLI-02, não deste comando). Preferi exigir explicitamente a inventar
um default que a spec não pediu.

**4.6 Dividendo/split de magnitude zero descartados silenciosamente em
`normalize_corporate_actions`.** yfinance ocasionalmente inclui zero residual em datas
sem evento nas séries `.dividends`/`.splits`. Sem o filtro, `CorporateAction`
levantaria `DataError` do construtor (A5) para um "evento" que não é evento nenhum.
Não está no design; acho a decisão óbvia o bastante para não ter sido ambiguidade,
mas registro para revisão.

**4.7 `pythonpath = ["."]` e `__init__.py` em `tests/`.** Necessário para
`FakeRepository`/`FakeProvider` serem compartilháveis entre `tests/unit/` e
`tests/integration/` via `from tests.support import ...`. O `__init__.py` veio depois,
quando dois arquivos de nome igual (`test_orchestrator.py`) em diretórios irmãos
colidiram no import sem pacote — os dois achados estão em commits próprios
(`f45c782`, `035e6f5`).

**4.8 `cache_logger_on_first_use=False`.** Já detalhado na seção 3. É mudança de
comportamento de produção motivada por um bug descoberto em teste, não um ajuste "só
para os testes passarem" — o raciocínio (CLI/batch, não hot path) está no comentário
do código.

### 5. Execução real contra yfinance

Fora da suíte, como pedido. Comando:

```
python -m quantlab ingest --tickers AAPL,MSFT --from 2024-01-02 --to 2024-01-10
```

Contra o Mongo local (`docker compose`), rede de verdade, sem `FakeProvider`.

**Resultado:** exit 0. `succeeded=['AAPL', 'MSFT']`, `failed=[]`, `bars_inserted=14`
(7 pregões × 2 tickers, a janela pedida), `quarantined_count=0`, `warning_count=0`.
`corporate_actions`: 195 eventos coletados sobre o **histórico completo** dos dois
tickers (181 dividendos + 14 splits, remontando a 1987) — confirma ING-02.3 na
prática, não só em teste. `ingestion_runs` gravou um documento com `tickers`,
`window_start`/`window_end`, `started_at`/`finished_at` e as contagens finais.

**Sanidade cruzada (recomendada por ADR-0003):** comparei a série ajustada própria
contra o `Adj Close` do yfinance para a mesma janela de AAPL. Divergência sistemática,
pequena mas consistente — sempre nossa série abaixo da de referência, em ~0,2%–0,25%
em todas as 7 barras:

| Data | quantlab (ajustado) | yfinance `Adj Close` | diferença |
|---|---|---|---|
| 2024-01-02 | 183.1131 | 183.5622 | -0,24% |
| 2024-01-03 | 181.7421 | 182.1877 | -0,24% |
| 2024-01-04 | 179.4339 | 179.8739 | -0,24% |
| 2024-01-05 | 178.7138 | 179.1521 | -0,24% |
| 2024-01-08 | 183.0342 | 183.4831 | -0,24% |
| 2024-01-09 | 182.6199 | 183.0678 | -0,24% |
| 2024-01-10 | 183.6557 | 184.1060 | -0,24% |

ADR-0003 distingue "divergência sistemática indica bug" de "divergência pequena é
esperada por diferença de convenção de arredondamento". Uma diferença **constante em
todas as barras** parece mais estruturada que ruído de arredondamento — o formato
(mesma % em toda a série) é consistente com um fator de ajuste a mais ou a menos
compondo o produto todo, não com erro por barra. Hipótese mais provável: o `Adj
Close` que o yfinance devolve na mesma chamada de `history()` é calculado a partir de
um snapshot de dividendos que pode não coincidir exatamente com o que
`.dividends` devolve momentos depois (cache interno do yfinance, ou o próprio
provedor upstream revisando dado entre as duas chamadas) — não necessariamente um bug
do quantlab. **Não investiguei a fundo dentro do escopo desta tarefa** — é uma
verificação de sanidade de desenvolvimento, não um critério de aceitação (nenhuma CA
exige bater com o `Adj Close` do provedor; os CAs de PER-02 são cobertos pelas
fixtures de papel de A7, calculadas à mão). Fica registrado para quem revisar decidir
se vale investigar antes do Bloco C consumir `get_series`.

> ### ⚠️ CORREÇÃO (2026-08-04) — a hipótese acima estava ERRADA
>
> O parágrafo acima fica como foi escrito, sem edição, porque o valor deste registro
> está em mostrar uma hipótese sendo derrubada por evidência — não em parecer que
> nunca houve hipótese errada.
>
> **O que eu supus:** que a divergência viesse de defasagem entre o `Adj Close` do
> yfinance e o que `.dividends` devolve, "não necessariamente um bug do quantlab".
>
> **O que o diagnóstico encontrou:** era bug nosso, em A7. O raciocínio sobre o
> *formato* estava certo — constância aponta para os fatores, não para a lógica por
> barra —, mas eu parei uma casa antes de chegar na causa e escolhi a explicação que
> não exigia culpa nossa. A causa real: `adjustment_factors()` recebia só as barras da
> **janela pedida**, então o `C` de cada um dos 10 dividendos posteriores virava o
> último fechamento da janela (`C = 186.19`, de 2024-01-10) em vez do fechamento do
> pregão anterior a cada data ex (188.32, 216.24, ..., 293.32).
>
> **O número que fecha o caso:** trocando só o `C` pelo correto, mantendo conjunto de
> eventos e fórmula, o fator vai de 0.9863884035 para 0.9888072905, contra
> 0.9888072623 do yfinance — **razão 1.0000000285**, ruído de ponto flutuante. O
> conjunto de eventos estava certo, a fórmula estava certa, o `cumprod` estava certo.
> Só o `C`.
>
> **Consequência mais séria que a divergência em si:** o valor ajustado de uma barra
> dependia da janela consultada. Medido no mesmo banco, sem envolver yfinance: leitura
> de 42 barras contra leitura de 7, 0,0437% de diferença nas 7 compartilhadas, hashes
> distintos — PER-03.1 atacado no ponto exato em que existe para dar garantia.
>
> **Onde foi parar:** [ADR-0004](specs/adr/0004-ajuste-sobre-historico-completo.md)
> (ajuste materializado sobre o histórico completo), design v0.5 §3.7, e a correção de
> A7 na seção "Correção de A7 + Bloco C" abaixo.
>
> **A lição que fica**, e que a v0.5 do design registra em §3.7 para não depender deste
> handoff: o que separa ruído de arredondamento de bug de fator não é a **magnitude**,
> é o **formato** — ruído é errático entre barras, bug de fator é constante. Eu escrevi
> isso corretamente acima e ainda assim não segui até o fim. A segunda lição é sobre a
> minha própria conclusão de que "não era critério de aceitação": era, sim — só não
> pelo caminho que eu olhei. Nenhuma CA exige bater com o `Adj Close`, mas PER-02.3 e
> PER-03.1 exigem determinismo, e a mesma causa quebrava os dois.

**Limpeza:** as 14 barras, os 195 eventos corporativos e o documento de
`ingestion_runs` foram removidos do banco de desenvolvimento (`quantlab`) logo após a
inspeção, confirmado por contagem zero nas três coleções.

### 6. Próximo passo

**Bloco C — engine**, que consome `PriceSeries` (Bloco A) e é testável inteiramente
com séries de papel, sem banco — a ordem de `tasks.md` é C1 (`MarketView`) → C2
(protocolo `Strategy`) → C3 (`Trade`/`Position`/`Portfolio`) → C4 (`Broker`) → C5
(laço de barras) → C6 (conciliação).

Dois avisos para quem pegar:

- **C1 e C5 são as tarefas de maior risco da fase** (junto com A7, já feita) — é onde
  a invariante anti-lookahead (ENG-01.2) vive ou morre. Vale reler design §4.1 e §4.3
  inteiros antes de escrever qualquer linha, não só a assinatura de `MarketView`.
- **A divergência da seção 5 vale uma decisão antes de C1**, não durante: se o Bloco C
  vai comparar resultados contra alguma referência externa em algum momento (não é
  requisito da Fase 1, mas pode aparecer em teste exploratório), a causa dessa
  diferença de ~0,24% precisa estar entendida, não só registrada.

---

## Correção de A7 + Bloco C — engine

**Data:** 2026-08-04
**Origem:** diagnóstico da divergência de 0,24%, ADR-0004, e `fase-1-tasks.md` Bloco C
**Escopo:** correção de `storage/` (ADR-0004) e `engine/` completo.
`strategies/` (Bloco D) e `analytics/` (Bloco E) continuam vazios.

### 1. O diagnóstico: era bug nosso, e o registro anterior foi corrigido

O aviso da seção acima ("vale uma decisão antes de C1") estava certo, e a decisão foi
investigar. Resultado: **categoria (ii), bug em A7** — não defasagem do provedor, como
a hipótese do Bloco B §5 supunha.

**A causa.** `adjustment_factors()` recebia só as barras da **janela pedida**. Para os
10 dividendos de AAPL posteriores à janela de 7 barras, o `C` de cada um virou o último
fechamento da janela (`186.19`, de 2024-01-10) em vez do fechamento do pregão anterior
a cada data ex (188.32, 216.24, ..., 293.32).

| | fator acumulado | ajustado de 2024-01-02 |
|---|---|---|
| implementação da v0.4 (`C` da janela) | 0.9863884035 | 183.1131 |
| mesma fórmula, `C` correto de cada `D−1` | 0.9888072905 | 183.5622 |
| `Adj Close` do yfinance | 0.9888072623 | 183.5622 |

**Razão entre o corrigido e a referência: 1.0000000285** — ruído de ponto flutuante.
Conjunto de eventos, fórmula e `cumprod` estavam corretos; só o `C`.

**A consequência que torna isto bug de correção e não imprecisão**, observável sem
nenhuma referência externa: leitura de 42 barras contra leitura de 7 divergiam em
**0,0437%** nas 7 compartilhadas, com hashes distintos. O valor ajustado de uma barra
dependia da consulta — PER-03.1 atacado no ponto em que existe para dar garantia.

O registro do Bloco B §5 foi corrigido **no lugar**, sem reescrever o histórico: o
parágrafo com a hipótese errada continua lá, com a correção anotada abaixo dele. O
valor está em mostrar a hipótese sendo derrubada por evidência.

### 2. O que foi entregue, por parte

| Parte | Entrega | Commit |
|---|---|---|
| **0** | ADR-0004 + design v0.5 (6 itens, §3.2 e §3.7) | `4f8e08e`, `847ada5` |
| **1** | Correção de A7 — `build_price_series`, borda de ponta direita, aviso de vão | `6a6c88a` |
| **2** | Correção do registro no HANDOFF | `d3f28b0` |
| **C1** | `MarketView` | `7d75d5b` |
| **C2/C3/C4** | `Signal`/`Strategy`, `Trade`/`Position`/`Portfolio`, `Broker`/`CostModel` | `3c2dbcc` |
| **C5/C6** | Laço de barras e conciliação | `4312957` |
| — | Lacuna que a mutação expôs | `a0b17af` |

**A peça de desenho que a correção exigiu:** `build_price_series` é função **pura**
nova em `storage/series.py` — histórico completo + eventos entram, `PriceSeries`
fatiada sai. Não foi refatoração gratuita: enquanto a materialização morava dentro de
`MongoRepository.get_series`, só teste de integração alcançava, e foi por isso que
nenhuma fixture cobria dividendo pós-janela. Agora o invariante de independência de
janela é testável **offline, com fixtures de papel**.

`get_series` ficou com sete linhas de corpo. `adjustment_factors` continua pura, como
ADR-0004 exige — o que mudou é com o que ela é alimentada.

### 3. Verificação por mutação — as duas frentes, separadas

**Frente 1 — a correção de A7.** As fixtures novas foram escritas **antes** da
implementação e falharam contra o código anterior, como a ordem da tarefa manda:

| Mutação | Testes que caem |
|---|---|
| `get_series` volta a passar só as barras da janela (o bug original) | 3 |
| Remover o descarte de evento posterior à última barra | 5 |
| Fatiar antes de ajustar, dentro do builder (a assimetria) | 3 |

**Frente 2 — o Bloco C.** As quatro mutações pedidas, mais uma que precisei
acrescentar:

| Mutação | Testes que caem |
|---|---|
| Executar ao `close[i]` em vez de `open[i]` | 3 |
| Executar no mesmo índice da decisão | 6 |
| Remover `writeable=False` da materialização | 16 |
| Inverter passos 1 e 2 (marcar antes de executar) — *acrescentada* | 3 |
| **Inverter passos 2 e 3 (consultar antes de marcar)** | **0** ⚠️ |

Arquivos restaurados byte a byte em todos os casos, conferido com `diff` e
`git status`.

**A mutação que não derrubou nada, e o que fiz com isso.** Inverter os passos 2 e 3 do
laço não quebra teste nenhum — verificado em isolamento, com confirmação explícita de
que a mutação aplicou (75 testes, todos verdes com os passos trocados).

A causa **não é teste faltando no sentido usual**: consultar a estratégia não tem
efeito colateral sobre a carteira. `on_bar` só devolve um sinal, que vira ordem
pendente para `i+1`. É consequência direta de ENG-05.2 — a estratégia não alcança
caixa, posição nem trades. A ordem entre 2 e 3 é **genuinamente livre**, e a numeração
de design §4.3 sugere uma restrição em três níveis que não existe.

O que faltava era travar a **premissa** que torna a liberdade válida. Adicionei
`test_the_equity_of_a_bar_does_not_depend_on_the_signal_emitted_on_it`, e confirmei que
ele tem dente injetando um `cash -= 0.01` logo após a consulta: **10 testes caem**. Se
alguém der efeito colateral a `on_bar` no futuro, descobre pelo teste e não por um
número errado no relatório.

A docstring do laço passou a declarar quais ordens carregam peso, com o número de
testes de cada uma, em vez de apresentar os três passos como igualmente restritos.

Como a instrução previa, essa foi a mutação mais informativa das cinco — justamente
por não derrubar nada.

### 4. Verificação e CI

**Local — nove passos, todos verdes:** `make install`, `lint`, `typecheck`, `test`,
`test-integration`, `check`, `audit`, `pre-commit run --all-files`,
`python -m quantlab version`.

- 266 testes unitários, 57 de integração.
- **Cobertura de `engine/`: 96%** — o piso de 80% de RNF-02 deixou de ser trivialmente
  satisfeito pela primeira vez. `portfolio.py` estava em 77% e ganhou testes próprios;
  os pontos descobertos eram justamente os *guards* de ENG-04.4, e testar o guard é
  diferente de testar o caminho feliz: o guard só serve se alguém provou que dispara.

| Módulo | Cobertura |
|---|---|
| `engine/backtest.py` | 95% |
| `engine/broker.py` | 90% |
| `engine/market_view.py` | 98% |
| `engine/portfolio.py` | 100% |
| `engine/strategy.py` | 100% |

**CI — [run 30876152658](https://github.com/colletpedro/quantlab/actions/runs/30876152658), os três jobs verdes.**

### 5. Decisões que tomei por conta própria — revise

**5.1 `build_price_series` como função pura, em `storage/series.py`.** ADR-0004 decide
*o quê*; a separação em função pura é *como*, e não estava especificada. Justificativa
no corpo: é o que torna o invariante testável offline. O custo é uma peça a mais no
módulo.

**5.2 O fatiamento usa `.copy()`, não view.** Uma view manteria vivo o array-mãe do
histórico inteiro, alcançável por `.base` — inclusive as barras fora da janela, que é
exatamente o que a janela existe para excluir. Custo: uma cópia por `get_series`,
irrelevante contra a leitura do banco.

**5.3 Aviso de vão grande só para dividendo, não para split.** Design v0.5 §3.7 escreve
a regra dentro do parágrafo que define `C`, e o fator de um split é `1/r` qualquer que
seja a barra âncora — um vão grande não torna o número suspeito. Para dividendo o `C`
entra na conta. Se a intenção era avisar nos dois casos, é uma linha.

**5.4 `_warn_if_gap_is_large` duplica `_business_day_gap` de
`ingestion/validator.py`.** De propósito: `storage/` importar de `ingestion/`
inverteria a direção das dependências (design §2) e criaria ciclo, já que `ingestion`
importa `storage.models`. Duplicar duas linhas puras me pareceu melhor que criar um
módulo `utils` prematuro. Se aparecer um terceiro uso, aí vale extrair.

**5.5 `InsufficientHistoryError` como subclasse de `EngineError`.** Design §4.1 nomeia
a exceção mas não diz onde ela mora na hierarquia. `EngineError` é o encaixe natural
(CLAUDE.md §3 manda usar a hierarquia do projeto).

**5.6 `Trade` congelado é fechado por substituição, não mutação.** `_close_trade` cria
o `Trade` fechado e troca **no mesmo índice** da lista, preservando a ordem
cronológica — que é o que `hit_rate` (E1) e o relatório vão esperar.

**5.7 `close[i]` fica visível à estratégia.** ADR-0002 proíbe *executar* na barra da
decisão, não usar o fechamento dela para decidir. Esconder quebraria a SMA cross sem
necessidade. Está com teste explícito.

**5.8 Dois erros meus, corrigidos, registrados porque são instrutivos.**
(a) No teste de ENG-01.2, mutei a partir do índice 3 — mas a decisão do índice 2
executa legitimamente no `open` de 3. A fronteira livre é *última decisão + 1*, não
*última decisão*; um teste anti-lookahead cedo demais acusa lookahead onde há execução
correta. (b) Em `test_entry_cost_is_debited_and_recorded_on_the_trade` eu esperava
q=98 e a implementação deu 99 — o próprio comentário do meu teste mostrava
`9900+1+0.99 = 9901.99 <= 10000`. Conferi a conta à mão antes de mexer, como CLAUDE.md
manda, e corrigi o **teste**, não a implementação.

### 6. Ambiguidades de spec encontradas — para a v0.6

**6.1 Design §4.3 sugere uma ordem em três níveis; só duas restrições existem.** Ver a
seção 3. As ordens que carregam peso são `1 antes de 2` e `1 antes de 3`; a relação
entre 2 e 3 é livre por ENG-05.2. A v0.6 poderia dizer isso explicitamente — hoje um
leitor razoável conclui que inverter 2 e 3 é violação, e não é.

**6.2 ADR-0004 nomeia testes que não existem com aqueles nomes exatos.** A tabela de
invariantes cita `test_factors_do_not_depend_on_the_requested_window` em
`test_adjustment.py`. O invariante acabou onde ele é de fato observável — no builder
(`tests/unit/test_series_builder.py`) e na integração —, porque no nível da função pura
de fator ele não é enunciável: a função nunca vê uma janela. Os nomes reais estão nos
commits; vale alinhar a tabela do ADR numa errata ou num ADR futuro, já que ADR é
imutável.

**6.3 §4.5 não diz se `Trade` guarda a data de decisão da SAÍDA.** A struct do design
lista `exit_gap_days` mas não `exit_decision_date`. Adicionei o campo por simetria — o
gap de saída precisa da mesma auditabilidade que o de entrada, e derivar a data a
partir do gap seria reconstruir informação que já tínhamos.

**6.4 §4.4 não define o que fazer com `EXIT` sem posição no nível do laço.** A decisão
Q2 cobre o caso na estratégia ("ignorado e logado"), mas não diz se a ordem pendente é
consumida ou fica para a barra seguinte. Implementei **consumida**: deixá-la pendente
faria a ordem ser tentada de novo com um preço que a decisão não conhecia — o que é
lookahead por outro caminho.

### 7. Próximo passo

**Bloco D — SMA cross** (`strategies/`), que é pequeno e depende só do protocolo de C2:
`warmup = slow`, validação `fast < slow`, cruzamento para cima e para baixo, com série
de papel e cruzamentos em datas conhecidas (ENG-06.1 a ENG-06.4).

Depois, **Bloco E** (analytics) e **Bloco F** (fechamento). Dois avisos:

- **O engine está pronto para receber a SMA cross sem alteração.** ENG-05.1 tem teste
  (`test_a_strategy_the_engine_has_never_seen_runs_unchanged`, com uma estratégia
  definida dentro do próprio teste). Se D1 exigir mudança no engine, é sinal de que o
  protocolo de C2 está incompleto — vale parar e olhar em vez de adaptar o engine.
- **F3 vai medir RNF-04 (10 anos em menos de 5 s) pela primeira vez com código real.**
  ADR-0004 acrescentou uma leitura de histórico completo por `get_series`, e o gatilho
  de revisitação que o próprio ADR declara é exatamente esse: gargalo *medido*, não
  suposto. F3 é onde a medição acontece.

## Blocos D e E — estratégia e analytics

**Data:** 2026-08-04
**Origem:** retomada de sessão depois de esgotar contexto. Estado inicial verificado
limpo (`git status`), nove passos locais verdes antes de escrever qualquer código.
**Escopo:** errata do ADR-0004, D1 (SMA cross), E1-E3 (analytics). `analytics/` deixa
de estar vazio; Bloco F (CLI `backtest`, gráfico, cobertura/perf, README) continua.

**Nota sobre `docs/STATE.md`:** o prompt de retomada desta sessão mandava lê-lo antes
de tudo. O arquivo não existia — nunca tinha sido commitado, apesar de HANDOFF.md
anteriores não terem sinalizado isso. Reportado ao usuário como discrepância antes de
prosseguir; criado do zero ao fim desta sessão com o estado atual.

### 1. O que foi entregue, por parte

| Parte | Entrega | Commit |
|---|---|---|
| Errata | ADR-0004 — corrige nomes de teste na tabela de invariantes, sem tocar o corpo | `1109c7a` |
| D1 | SMA cross (`strategies/sma_cross.py`), ENG-06.1 a ENG-06.4 | `d50556a` |
| E1 | Métricas puras (`analytics/metrics.py`), ANA-01.1 a ANA-01.5 | `0310c8e` |
| E2 | Benchmark buy-and-hold (`analytics/benchmark.py`), ANA-02.1/02.2 | `827c478` |
| E3 | `BacktestReport` (`analytics/report.py`), ANA-03.1 | `3c7adef` |

### 2. Errata do ADR-0004

A tabela "Invariantes que o código precisa respeitar" citava
`tests/unit/test_adjustment.py::test_factors_do_not_depend_on_the_requested_window`, que
não existe com esse nome. O invariante de independência de janela não é enunciável no
nível de `adjustment_factors()` — a função é pura e nunca vê uma janela, só recebe as
barras que lhe são passadas. Os testes reais que provam o invariante são
`test_two_windows_agree_value_by_value_on_shared_bars` (`test_series_builder.py`, no
nível do builder, onde a janela existe de fato) e
`test_adjusted_values_do_not_depend_on_the_requested_window` (integração, já correto na
tabela original). Correção via seção "Errata" datada ao **fim** do ADR — corpo intocado,
sem ADR-0005, porque é correção factual de nomenclatura, não mudança de decisão.

### 3. D1 — SMA cross

`warmup = slow` sai de graça do contrato de C2: o engine não chama `on_bar` antes disso
(ENG-06.3). Validação `fast < slow` levanta `EngineError` na instanciação (ENG-06.4).
Cruzamento para cima → `ENTER`, para baixo → `EXIT`, calculados comparando a SMA da barra
corrente contra a da barra anterior — na primeira chamada possível (`i = warmup`), o
`view.close` já tem `slow + 1` observações, suficiente para as duas janelas sem tocar
`last()` (que não expressa deslocamento).

Fixture de papel única (`fast=2, slow=3`, sete barras) com os dois cruzamentos calculados
à mão, incluindo o caso de borda em que o cruzamento de entrada acontece exatamente na
primeira barra elegível — não por acaso, para testar exatamente a fronteira do warmup.
Teste ponta a ponta via `run_backtest` confirma ENG-05.1: **o engine não precisou de
nenhuma alteração** para rodar D1. Se tivesse precisado, seria sinal de que o protocolo
de C2 estava incompleto — a instrução da sessão foi parar e olhar nesse caso, e não foi
necessário.

### 4. E1 — Métricas

Funções puras sobre `pd.Series` (`analytics/metrics.py`), decisão de usar pandas como
tipo de fronteira em `analytics/` conforme Q1 do design ("DataFrame apenas nas
fronteiras — I/O e analytics").

- `sharpe(returns, rf=0.0, periods=252)` — `None`, nunca `nan`, com desvio-padrão zero
  ou menos de duas observações. `nan` se propaga em silêncio por agregação a jusante;
  `None` estoura no primeiro uso aritmético.
- `max_drawdown(equity)` — pico é o **corrente** (`cummax`), não o primeiro valor da
  série nem o último valor local antes da queda. `DrawdownResult` com magnitude, data de
  pico, de fundo e de recuperação (`None` se não recuperado).
- `cagr(equity)` — usa dias corridos entre a primeira e a última data do índice, não
  contagem de barras (pregões têm gaps de fim de semana e feriado). `0.0` sem tempo
  decorrido.
- `hit_rate(trades)` — só trades **fechados**; `None` sem nenhum fechado, não `0.0`.

Fixtures de papel com resultado calculado à mão. Duas das fixturas originais que escrevi
tinham erro de aritmética minha, não bug do código — pego pelo próprio teste, corrigido
antes de prosseguir (ver §7.2 abaixo, honestidade de erro próprio como o Bloco C já
tinha registrado no seu §5.8).

Amostra insuficiente (ANA-01.5) **não** vive em `metrics.py`: essas funções emitiriam um
aviso (log ou similar), o que quebraria a pureza que RNF-03 exige para testar com séries
de papel. Fica em E3, que é quem tem para quem avisar.

### 5. E2 — Benchmark

`buy_and_hold(series, warmup, initial_cash, costs)` reaproveita `BacktestResult` e
`EquityPoint` do engine em vez de um tipo paralelo: é um backtest de uma estratégia só
(compra e segura), e E1, E3 e `reconciles()` do próprio engine já sabem ler essa forma —
decisão própria, registrada aqui porque design não especifica o tipo de retorno.

Compra ao `open[warmup + 1]`, mesmos custos de entrada, `decision_date` = barra de
`warmup` (simetria com ADR-0002: "decidido" em `warmup`, "executado" em `warmup + 1`).

Teste que mais importa: `test_shares_the_exact_equity_window_with_a_strategy_of_the_same_warmup`
prova que a janela de equity do benchmark é, barra a barra, o sufixo
`equity_curve[warmup + 1:]` de uma estratégia com o mesmo `warmup` rodando sobre a mesma
série — não uma janela parecida, a mesma. É a garantia que ANA-02.2 pede.

### 6. E3 — Relatório

`BacktestReport.build(strategy=..., benchmark=..., rf=0.0)` — construído via classmethod,
não `__init__` posicional direto, porque montar os dois `MetricsSummary` errados seria
fácil de fazer sem essa fronteira.

`BIAS_DISCLOSURE` é `tuple[str, ...]` module-level com os seis itens de design §5.2 —
constante literal, nenhum caminho de `build()` a omite. Teste dedicado confirma
`len(BIAS_DISCLOSURE) == 6` e que os seis aparecem em `to_text()` e `to_dict()["biases"]`
em todo relatório construído, inclusive um com avisos condicionais ativos (para provar
que os avisos não deslocam nem truncam a seção fixa).

O relatório também é onde convergem obrigações de outras RFs que só fazem sentido uma
vez que existe relatório: aviso de custo zerado (`CostModel.is_zero`, ENG-03.2),
tratamento de dividendo declarado como "ajuste de preço, sem crédito em caixa"
(ENG-04.3), proveniência de hash + timestamp de ingestão (PER-03.1). Nenhuma dessas é
scope creep — design §5.2 já lista "premissas declaradas (rf, custos, dividendo)" como
conteúdo do relatório; só ainda não existia relatório nenhum para carregá-las.

`to_dict()`/`to_json()`/`to_text()` renderizam o mesmo conteúdo em dois formatos, como o
design pede. `to_json()` é `json.dumps(to_dict())`; nenhum teste de round-trip falhou.

### 7. Verificação por mutação — E1 e E2, obrigatória

| Módulo | Mutação | Testes que caem |
|---|---|---|
| E1 `sharpe` | anualizar por √12 em vez de √252 | 3 |
| E1 `max_drawdown` | medir do início da série em vez do pico corrente (`cummax`) | 3 |
| E1 `max_drawdown` | `>=` → `>` no limiar de recuperação (mutação própria, não pedida) | 1 |
| E2 `buy_and_hold` | comprar na barra 0 em vez de `warmup + 1` | 5 de 7 |

Todas as quatro restauradas byte a byte, confirmado com `diff` depois de cada uma —
nenhuma mutação ficou sem teste que a derrubasse. Diferente do Bloco C (M1, ordem 2-3 do
laço), que achou uma liberdade genuína de desenho, aqui as quatro mutações pedidas e a
acrescentada por conta própria (o limiar de recuperação de drawdown) tinham teste.

#### 7.1 A mutação acrescentada e por quê

A instrução mandava, no mínimo, quatro mutações. Ao escrever `max_drawdown`, notei que a
condição de recuperação (`equity >= pico anterior`) tinha uma fronteira testável que
nenhuma das quatro mutações pedidas cobria: `>=` contra `>`. Escrevi
`test_max_drawdown_recovery_is_exactly_on_the_bar_that_reaches_the_peak` de propósito
para isolar essa fronteira (recuperação por igualdade exata, não por ultrapassagem) e
confirmei que ela — e só ela — cai com a mutação. Um teste com dente, não um teste que
passaria de qualquer forma.

#### 7.2 Dois erros meus, corrigidos, registrados por serem instrutivos

Duas das fixtures de E1 que escrevi primeiro falharam contra a própria implementação —
não porque o código estava errado, mas porque minha aritmética manual estava.

(a) `test_sharpe_with_nonzero_risk_free_rate_shifts_the_mean`: previ que subtrair `rf`
constante de ambos os retornos preservaria a razão média/desvio-padrão (porque o
desvio-padrão realmente não muda ao subtrair uma constante — isso eu acertei). O erro foi
não recalcular a **média** deslocada: ela caiu de 0.02 para 0.01, o desvio ficou igual
(0.02/√2), e o Sharpe caiu pela metade (√126 em vez de √504). Conferi a álgebra de novo
antes de mudar qualquer coisa e corrigi o valor esperado no teste, não a implementação.

(b) `test_max_drawdown_picks_the_deepest_of_two_drops`: assumi que o pico "resetaria"
para o último valor local (100) depois de uma recuperação parcial, dando uma segunda
queda de -40% até 60. Mas o pico usado é o **corrente** (`cummax`), que não desce nunca —
continuava 120 (o máximo já visto), então a queda até 60 é -50%, não -40%. É exatamente o
comportamento que ANA-01.3 pede ("maior queda... pico-a-vale", pico corrente, não pico
local) e que a mutação de `max_drawdown` — medir do início — existe para vigiar pelo lado
oposto. Corrigi o teste, documentei a diferença na docstring da fixture, porque é
precisamente a distinção que a fixture deveria estar testando.

### 8. Verificação e CI

**Local — nove passos, todos verdes**, executados antes de qualquer código (Parte 0) e
de novo ao final: `make up`, `install`, `lint`, `typecheck`, `test`, `test-integration`,
`check`, `audit`, `pre-commit run --all-files`.

- 367 testes coletados: **310 unitários** (era 266 no fim do Bloco C — 44 novos entre
  D1 e E1-E3) + 57 de integração, inalterados.
- Cobertura total (unitários, offline): **97.22%**. `analytics/`: `metrics.py` 100%,
  `benchmark.py` 100%, `report.py` 99% (uma ramificação de `to_text()` não coberta,
  1 linha). É a primeira vez que o piso de 80% de RNF-02 deixa de ser trivialmente
  satisfeito em `analytics/`, e ficou com folga confortável.
- `engine/` sem mudança de código nesta sessão, cobertura idêntica ao Bloco C (95-100%
  por arquivo).

**CI — [run 30876286773](https://github.com/colletpedro/quantlab/actions/runs/30876286773)**,
os três jobs verdes (lint+tipos+testes, integração, auditoria de dependências).

### 9. Decisões que tomei por conta própria — revise

**9.1 `buy_and_hold` devolve `BacktestResult`, não um tipo próprio de benchmark.** Design
não especifica o tipo. Reaproveitar evita duplicar `reconciles()`, `realized_pnl` etc., e
deixa E1/E3 tratarem estratégia e benchmark de forma uniforme. Custo: `BacktestResult` tem
campos que não fazem sentido para um benchmark (`pending_order` sempre `None`).

**9.2 `decision_date` do benchmark é a barra de `warmup`, não `warmup + 1`.** Simetria
com ADR-0002 — "decidido" uma barra antes de "executado" — mas o design não fala nisso
para o benchmark. Efeito prático: `entry_gap_days` do trade do benchmark sai preenchido
de forma consistente com o resto do sistema, em vez de zero.

**9.3 Amostra insuficiente e aviso de custo zero moram no relatório (E3), não nas
métricas (E1).** Design §5 diz que as funções de métrica são puras, sem I/O; um aviso é
uma forma de I/O (ou pelo menos de efeito observável), então a checagem se move para
onde há alguém a quem avisar. Não está errado dividir assim, mas é uma leitura de "onde
mora a responsabilidade" que o design não decide explicitamente.

**9.4 `BacktestReport` usa `classmethod build()` em vez de `__init__` direto.** Os campos
de `MetricsSummary` são derivados, não dados brutos — um `__init__` posicional convidaria
a montar um relatório com metade dos campos calculados errado ou inconsistente entre si.

**9.5 `×` (sinal de multiplicação Unicode) trocado por `x` ASCII nas docstrings de
`metrics.py`.** `ruff` (regra `RUF002`) rejeita caractere ambíguo em docstring. O próprio
CLAUDE.md usa `×` na descrição da fórmula do Sharpe, mas isso é markdown, não código
lintado.

### 10. Ambiguidades de spec — reavaliadas, nenhuma bloqueou D/E

As quatro ambiguidades do Bloco C §6 foram lidas e avaliadas antes de começar D1: nenhuma
bloqueava código a escrever, porque todas eram sobre documentação não refletir decisões
*já tomadas*, não sobre decisões pendentes que afetassem D ou E.

1. **Design §4.3, ordem em três níveis vs. duas restrições reais.** Sem mudança nesta
   sessão — recomendação inalterada: reescrever §4.3 para não sugerir uma restrição entre
   os passos 2 e 3 que não existe.
2. **ADR-0004, nomes de teste errados na tabela.** **Resolvida nesta sessão** — errata
   datada, commit `1109c7a`.
3. **Design §4.5, `exit_decision_date` ausente do struct de `Trade` documentado.** Sem
   mudança — já implementado, só falta o design refletir.
4. **Design §4.4, destino de `EXIT` sem posição no nível do laço.** Sem mudança — já
   implementado como consumida, só falta o design declarar essa escolha.

Nenhuma delas afeta `strategies/` ou `analytics/`: são todas sobre `engine/`, já
implementado e testado no Bloco C. Recomendação geral: as quatro entram juntas numa v0.6
do design quando o Bloco F terminar, em vez de uma revisão por ambiguidade.

### 11. Próximo passo

**Bloco F — fechamento.** F1 (CLI `backtest` + persistência em `backtest_runs`) é onde
`run_backtest`, `buy_and_hold` e `BacktestReport.build()` se conectam pela primeira vez
num caminho de ponta a ponta de verdade — vale rodar contra dado real (AAPL, via
`make up` + ingestão) antes de declarar F1 pronto, não só fixture de papel. F2 (gráfico)
consome a mesma tripla. F3 é a primeira medição real de RNF-04 com o custo de leitura de
histórico completo que ADR-0004 introduziu — o gatilho de revisitação que o próprio ADR
já previu. F4 fecha a Fase 1 com um resultado honesto, incluindo se a SMA cross perder
para o buy-and-hold — CLAUDE.md §"Honestidade de resultado" é explícito que perder é um
resultado válido a reportar, não algo a maquiar.
