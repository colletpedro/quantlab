# quantlab

Plataforma de backtesting de estratégias sistemáticas sobre ações americanas.

O objetivo do projeto **não** é encontrar uma estratégia lucrativa. É construir um
instrumento de medição confiável — um backtester correto por construção quanto a
lookahead bias. Uma estratégia que perde dinheiro num engine correto é um resultado
válido e será reportada como tal.

---

## Estado atual — Fase 0 (fundação)

Este repositório contém **apenas o esqueleto**: pacote, configuração, ambiente, CI e
templates de processo. Os subpacotes de domínio (`ingestion/`, `storage/`, `engine/`,
`strategies/`, `analytics/`) estão **vazios de propósito**.

O projeto é spec-driven: nenhuma linha de implementação é escrita antes da spec
correspondente passar pelo gate de design. Os requisitos da Fase 1 estão aprovados
([`specs/00-plataforma/fase-1-requirements.md`](specs/00-plataforma/fase-1-requirements.md)),
mas o design ainda não. Enquanto isso não acontecer, os módulos permanecem vazios.

| Fase | Escopo | Estado |
|---|---|---|
| 0 | Fundação: repo, docker-compose, CI mínimo | **este commit** |
| 1 | MVP: ingestão → Mongo → backtest SMA → métricas → gráfico | requisitos aprovados, design não iniciado |
| 2+ | Custos, portfólio, walk-forward, analytics de risco, API, infra, RAG | — |

O roadmap completo está em [`specs/README.md`](specs/README.md).

## Stack

| Camada | Escolha | Por quê |
|---|---|---|
| Linguagem | Python 3.12+ | — |
| Pacotes | `uv` | Resolução e sync rápidos, lockfile versionado |
| Dados | `pandas`, `numpy` | Séries e vetorização |
| Banco | MongoDB 7 | [ADR-0001](specs/adr/0001-mongodb-vs-relacional.md) |
| Provedor de dados | `yfinance` | Gratuito, cobre OHLCV diário e eventos corporativos |
| CLI | `typer` | — |
| Configuração | `pydantic-settings` | Validação na fronteira, tudo via env |
| Logging | `structlog` | Saída estruturada; o projeto não usa `print()` |
| Gráficos | `matplotlib` | — |
| Qualidade | `ruff`, `mypy --strict`, `pytest`, `pre-commit` | RNF-05 |

## Como rodar

Pré-requisitos: [uv](https://docs.astral.sh/uv/), Docker e `make`.

```bash
cp .env.example .env
```

```bash
make install
```

```bash
make up
```

```bash
python -m quantlab version
```

`make up` sobe o MongoDB e só retorna quando o healthcheck passa. `make down` derruba
os containers preservando o volume de dados.

Os comandos de ingestão e backtest (`RF-CLI-01`, `RF-CLI-02`) **ainda não existem** —
são escopo da Fase 1.

### Alvos do Makefile

| Alvo | O que faz |
|---|---|
| `make install` | Instala dependências de runtime e de desenvolvimento |
| `make up` / `down` / `logs` | Ciclo de vida do MongoDB local |
| `make test` | Suíte default com cobertura (integração desmarcada) |
| `make test-unit` / `test-integration` | Recortes por marcador |
| `make lint` / `format` | `ruff check` / `ruff format` |
| `make typecheck` | `mypy --strict` |
| `make audit` | `pip-audit` nas dependências instaladas |
| `make check` | **Portão local:** lint + typecheck + test — o mesmo que o CI roda |
| `make clean` | Remove caches e artefatos |

## Estrutura

```
quantlab/
├── config/
│   └── universe.yml           # 20 tickers por setor GICS, lista fixa e versionada
├── specs/                     # fonte da verdade do projeto — leia antes de codar
│   ├── README.md              # fluxo, gates, índice de ADRs, roadmap
│   ├── CHANGELOG.md           # histórico de versões das specs
│   ├── 00-plataforma/         # requisitos da Fase 1
│   ├── adr/                   # decisões arquiteturais, numeradas e imutáveis
│   └── _templates/            # esqueletos de requirements, design, tasks e ADR
├── src/quantlab/
│   ├── cli.py                 # app Typer
│   ├── config.py              # Settings via env (prefixo QUANTLAB_)
│   ├── logging.py             # structlog: JSON fora de dev, legível em dev
│   ├── exceptions.py          # QuantlabError e subclasses
│   ├── ingestion/             # vazio — aguarda gate de design
│   ├── storage/               # vazio — aguarda gate de design
│   ├── engine/                # vazio — aguarda gate de design
│   ├── strategies/            # vazio — aguarda gate de design
│   └── analytics/             # vazio — aguarda gate de design
├── tests/
│   ├── conftest.py            # fixtures de infraestrutura
│   ├── unit/                  # rodam sempre, offline
│   ├── integration/           # exigem `make up`
│   └── fixtures/              # séries sintéticas (RNF-03) — vazio na Fase 0
├── docker-compose.yml         # MongoDB 7 (Redis é Fase 2)
├── Dockerfile                 # multi-stage, runtime não-root
└── CLAUDE.md                  # regras de trabalho no repositório
```

## Specs e decisões

A pasta [`specs/`](specs/) é a fonte da verdade. Três decisões arquiteturais já estão
fechadas e o código precisa respeitá-las:

- **[ADR-0001](specs/adr/0001-mongodb-vs-relacional.md)** — MongoDB como banco primário.
  Reconhecidamente não-ótimo para séries temporais; a justificativa e os trade-offs
  contra TimescaleDB e Parquet estão escritos.
- **[ADR-0002](specs/adr/0002-execucao-no-open-seguinte.md)** — sinal calculado no
  fechamento de D executa no `open` do próximo pregão. Invariante, não convenção.
- **[ADR-0003](specs/adr/0003-ajuste-em-tempo-de-leitura.md)** — persiste-se o preço
  bruto; o ajuste por proventos é aplicado na leitura. O ajustado envelhece, o bruto não.

## Limitações conhecidas

Declaradas aqui porque um backtester que esconde suas premissas é pior que nenhum.

**Da Fase 0 (este commit)**

- Nenhuma funcionalidade de negócio existe. O único comando é `version`.
- A cobertura de 80% está configurada e escopada a `engine/` e `analytics/`, mas é
  trivialmente satisfeita enquanto esses pacotes estiverem vazios.
- O `Dockerfile` ainda não entra no `docker-compose.yml`.
- O MongoDB local sobe com credenciais de exemplo, adequadas apenas à máquina do
  desenvolvedor.

**Do desenho da Fase 1, já assumidas**

- **Survivorship bias.** O universo em `config/universe.yml` é uma lista fixa de
  empresas que existem e são líquidas hoje. Empresas que faliram ou foram deslistadas
  não aparecem. Isso infla o retorno de qualquer estratégia testada — e do benchmark.
- **Slippage não modelado.** A execução assume preenchimento integral no `open`, sem
  impacto de mercado e sem limite de participação no volume.
- **Custos simplificados.** Valor fixo por trade mais percentual sobre o notional.
  Sem taxas de bolsa, sem borrow, sem imposto.
- **Múltiplas hipóteses.** Nenhuma correção para o número de configurações testadas.
  Testar muitos parâmetros e reportar o melhor produz resultado enviesado por
  construção.
- **Dividendos entram via ajuste de preço**, não como crédito em caixa.
- **Long-only, sem alavancagem, sem fracionário, moeda única (USD).**

## Contribuindo

O fluxo e os gates estão em [CONTRIBUTING.md](CONTRIBUTING.md). As convenções de código
e as invariantes que não podem ser violadas estão em [CLAUDE.md](CLAUDE.md).

## Licença

MIT.
