# CLAUDE.md — regras de trabalho neste repositório

quantlab é uma plataforma de backtesting de estratégias sistemáticas. O objetivo do
projeto não é achar uma estratégia lucrativa: é construir um **instrumento de medição
confiável**. Um backtest que mente é pior que backtest nenhum, porque parece
informação. Tudo aqui existe para impedir que o instrumento minta.

---

## 1. Nenhuma implementação sem spec aprovada

Este repositório é **spec-driven**. A pasta `specs/` é a fonte da verdade, não
documentação de apoio.

**Antes de escrever qualquer linha de código de um módulo, leia, nesta ordem:**

1. [`specs/README.md`](specs/README.md) — o fluxo, os gates e o estado atual de cada spec
2. O `requirements.md` do módulo em questão
3. **Todos** os ADRs em [`specs/adr/`](specs/adr/) — não só o que parece relevante

O fluxo por módulo é: **requisitos → design → tarefas → implementação**. Cada transição
é um gate explícito. Um gate reprovado volta para a etapa anterior; não se avança com
pendência.

Se a spec do módulo não estiver com status **aprovada**, a resposta correta não é
implementar assim mesmo com uma ressalva. É parar e dizer que o gate não foi feito.

**Estado atual: Fase 0.** Os subpacotes `ingestion/`, `storage/`, `engine/`,
`strategies/` e `analytics/` estão vazios **de propósito**. Os requisitos da Fase 1
estão aprovados, mas o design não. Não preencha esses pacotes — nem "só um esboço",
nem "para facilitar depois". Anote a ideia em `HANDOFF.md` e siga.

Quando a spec estiver errada, o caminho é corrigir a spec primeiro e o código depois.
Nunca o inverso, e nunca os dois no mesmo commit sem dizer.

## 2. Invariantes — não são sugestões

Três decisões estão fechadas em ADR. Elas amarram o código, e duas delas geram
invariantes que um teste precisa provar.

### ADR-0002 — execução no `open` do pregão seguinte

[`specs/adr/0002-execucao-no-open-seguinte.md`](specs/adr/0002-execucao-no-open-seguinte.md)

Um sinal calculado com informação até o fechamento de D **só pode ser executado a
partir da abertura do próximo pregão disponível**. Nunca ao `close` de D.

Consequências práticas para qualquer código de engine:

- A API do engine expõe à estratégia **apenas barras de índice ≤ `i`**. Acesso a
  índice `> i` levanta exceção (CA-01.3). Isso é garantido por construção, não por
  disciplina de quem escreve a estratégia.
- Sinal na última barra da série **não é executado** — é reportado como pendente
  (CA-01.4).
- Em gap de pregões, executa-se no `open` da próxima barra existente, qualquer que
  seja a distância em dias, e o gap fica registrado no trade (CA-01.5).
- **O teste que prova a invariante (CA-01.2):** mutar arbitrariamente as barras
  posteriores à última decisão e reexecutar o backtest tem que produzir exatamente o
  mesmo conjunto de trades. Se qualquer lookahead entrar no código, esse teste quebra.
  Ele é requisito de aceitação da fase, não um teste opcional.

Qualquer conveniência que dê à estratégia acesso ao futuro — mesmo indireto, mesmo via
um `DataFrame` inteiro passado "só para calcular o indicador" — viola este ADR.

### ADR-0003 — preço bruto persistido, ajuste em tempo de leitura

[`specs/adr/0003-ajuste-em-tempo-de-leitura.md`](specs/adr/0003-ajuste-em-tempo-de-leitura.md)

O ajuste por proventos **não é propriedade do passado, é função do presente**: cada
novo dividendo reescreve a série ajustada inteira, retroativamente.

- Persiste-se **OHLCV bruto**; o ajuste é aplicado na leitura, na camada de repositório.
- A coleta usa `auto_adjust=False`. Nunca grave o ajustado por cima do bruto, e nunca
  grave os dois lado a lado.
- Eventos corporativos são coletados sobre o **histórico completo** do ticker, não só
  sobre a janela pedida: um split fora da janela ainda afeta os preços dentro dela.
- Série sem nenhum evento tem que sair da leitura ajustada **numericamente idêntica**
  à bruta (CA-02.4).

### ADR-0001 — MongoDB como banco primário

[`specs/adr/0001-mongodb-vs-relacional.md`](specs/adr/0001-mongodb-vs-relacional.md)

Índice composto `(ticker, date)`. A camada de repositório isola o resto do sistema do
driver — o engine não importa `pymongo`.

### Se uma decisão precisar mudar

Escreva um **ADR novo** declarando supersedência do anterior. ADRs são numerados e
imutáveis: não edite nem apague o antigo. Use
[`specs/_templates/adr.md`](specs/_templates/adr.md).

## 3. Convenções de código

- **Type hints obrigatórios**, em tudo, inclusive nos testes. `mypy --strict` roda no
  CI e precisa passar limpo (RNF-05). Sem `# type: ignore` sem comentário explicando.
- **`structlog`, nunca `print()`.** Toda saída observável passa por
  `quantlab.logging.get_logger`. Não há exceção "só para debugar".
- **Exceções da hierarquia do projeto.** Levante `DataError`, `ConfigError` ou
  `EngineError` de `quantlab.exceptions`, não `Exception` ou `ValueError` cru.
- **Datas são data-calendário naive** (RNF-07). Nenhuma comparação de datas envolve
  timezone. Normalize na fronteira da ingestão, não no meio do engine.
- **Dinheiro é `float`**, com comparações de teste por **tolerância explícita**
  (`pytest.approx`), nunca igualdade exata (RNF-08). `Decimal` está documentado como
  alternativa descartada — não reintroduza sem ADR.
- **Determinismo** (RNF-01). Mesmo estado de banco e mesmos parâmetros produzem
  resultado idêntico. Nenhuma aleatoriedade sem semente, nenhuma dependência de
  `datetime.now()` dentro da lógica.
- **Configuração via `quantlab.config.Settings`**, prefixo `QUANTLAB_`. Nada de
  `os.getenv` espalhado, nada de constante mágica.
- **Linha de 100 colunas**, `ruff` com `E, F, I, N, UP, B, SIM, RUF`.

### Testes

- **Fixtures sintéticas para `engine/` e `analytics/`** (RNF-03). As séries são
  construídas à mão, com o resultado esperado **calculado no papel**. Dados reais de
  mercado não entram em teste desses módulos: um teste que valida contra o número que
  o próprio código produziu não valida nada.
- Cobertura mínima de **80% em `engine/` e `analytics/`** (RNF-02). São os módulos de
  dinheiro e de medição — os que não podem errar. Os outros não entram no cálculo.
- Marque todo teste com `@pytest.mark.unit` ou `@pytest.mark.integration`. A suíte
  default roda **offline** (RNF-06); integração exige `make up`.
- Teste de comportamento observável, não de detalhe interno.

### Commits

- **Pequenos e explícitos.** Um assunto por commit. Mensagem no imperativo, dizendo
  também **por quê**, não só o quê.
- **Nunca `git add .`** — nem `git add -A`, nem `git commit -a`. Adicione cada arquivo
  pelo caminho. Isso evita subir `.env`, artefatos de build, gráficos gerados e
  mudanças não revisadas junto com o que você quis commitar.
- Não commite resultado de backtest, gráfico ou dado de mercado.
- Não reescreva histórico já publicado.

### Honestidade de resultado

Um número ruim é um resultado. Se a estratégia perde para o buy-and-hold, o relatório
diz isso. Se o custo está configurado como zero, o relatório sinaliza que os números
são irrealistas (CA-03.2). Todo relatório declara os vieses conhecidos — survivorship,
slippage não modelado, custos simplificados, ausência de impacto de mercado e ausência
de correção para múltiplas hipóteses (RF-ANA-03).

Nunca ajuste uma premissa para melhorar um resultado.

## 4. Comandos

```bash
make install
```

```bash
make check
```

`make check` é o portão local — encadeia `lint`, `typecheck` e `test`, exatamente o que
o CI roda. Rode antes de qualquer commit.

| Comando | O que faz |
|---|---|
| `make install` | Instala dependências de runtime e de desenvolvimento |
| `make up` / `make down` / `make logs` | Ciclo de vida do MongoDB local |
| `make test` | Suíte default com cobertura (integração desmarcada) |
| `make test-unit` / `make test-integration` | Recortes por marcador |
| `make lint` / `make format` | `ruff check` / `ruff format` |
| `make typecheck` | `mypy --strict` |
| `make audit` | `pip-audit` nas dependências instaladas |
| `make check` | **lint + typecheck + test** |
| `make clean` | Remove caches e artefatos |

Dependências entram por `uv add` (ou `uv add --dev`), nunca editando `pyproject.toml` na
mão sem atualizar `uv.lock`.

## 5. Antes de dizer que terminou

- [ ] `make check` passa — sem passo vermelho, sem teste pulado sem justificativa
- [ ] A spec correspondente está aprovada e o que foi feito não a extrapola
- [ ] Os critérios de aceitação citados têm teste que falharia sem a mudança
- [ ] Nenhum ADR foi violado
- [ ] Nada foi implementado "por adiantamento" fora do escopo da tarefa

Se algo ficou por fazer, diga o que e por quê. Não relate como concluído.
