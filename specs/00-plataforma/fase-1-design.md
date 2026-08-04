# Fase 1 (MVP) — Design técnico

**Status:** aprovada — gate check 2 concluído
**Versão:** 0.6
**Data:** 2026-08-04
**Requisitos de origem:** `specs/00-plataforma/fase-1-requirements.md` v1.0
**ADRs vinculantes:** 0001, 0002, 0003, 0004

> **Convenção de referência:** critérios de aceitação são citados com prefixo da família de requisito — `ENG-01.4` significa CA-01.4 de RF-ENG-01; `ANA-01.4` significa CA-01.4 de RF-ANA-01. A v0.1 citava CAs sem prefixo e colidia namespaces. Recomenda-se adotar a mesma convenção no requirements na próxima revisão dele.

---

## 1. Princípio organizador

Um requisito pode ser satisfeito de duas formas: por convenção (o código faz a coisa certa porque quem escreveu lembrou) ou por construção (o código não consegue fazer a coisa errada).

O requisito central da fase — a invariante anti-lookahead — é satisfeito **por construção contra acidente**: a estratégia não recebe os dados futuros e o caminho normal de acesso é fechado. Contra código deliberadamente adversarial a garantia não é absoluta (ver 4.1 — Python não oferece encapsulamento forte), e o design declara isso em vez de fingir o contrário. A consequência prática permanece: o teste de ENG-01.2 confirma um desenho, não vigia um descuido.

Onde a construção não é possível, o design nomeia explicitamente qual teste carrega a garantia.

## 2. Arquitetura

```
                 ┌──────────────┐
 yfinance ──────▶│  ingestion/  │──────┐
                 └──────────────┘      │
                                       ▼
                              ┌──────────────────────┐
                              │       storage/       │
                              │  bars (bruto)        │◀── MongoDB
                              │  corporate_actions   │
                              │  quarantined_bars    │
                              │  ingestion_runs      │
                              │  backtest_runs       │
                              └──────────┬───────────┘
                                         │ PriceSeries (ajustada)
                                         ▼
   strategies/ ──Signal──▶  ┌──────────────────┐
        ▲                   │     engine/      │
        │  MarketView        │  loop de barras  │
        └───────────────────│  Broker          │
                             │  Portfolio       │
                             └────────┬─────────┘
                                      │ BacktestResult
                                      ▼
                             ┌──────────────────┐
                             │    analytics/    │──▶ Report ──▶ CLI + PNG
                             └──────────────────┘
```

Dependências apontam para dentro. `engine/` não conhece MongoDB nem yfinance; recebe uma `PriceSeries` já materializada. `strategies/` não conhece o engine, só o contrato. Isso é o que permite RNF-03: testes de engine rodam sobre séries construídas à mão, sem banco.

---

## 3. Camada de persistência

### 3.1 Coleção `bars`

```javascript
{
  ticker: "AAPL",           // string, uppercase
  date:   ISODate(...),     // 00:00:00 UTC — ver 3.6
  open:   185.42,  high: 187.05,  low: 184.90,  close: 186.31,
  volume: 54321000,         // int
  source: "yfinance",
  ingested_at: ISODate(...)
}
```

Índice: `{ticker: 1, date: 1}`, **único**. Ele serve três padrões de acesso: consulta por ticker + intervalo (o dominante), consulta por ticker inteiro (pelo prefixo) e a garantia de unicidade que torna o upsert de PER-01.1 correto.

Índice isolado em `date` não é criado: seletividade baixa (20 tickers por data) e nenhuma consulta parte da data sem o ticker.

**Semântica de escrita: upsert pela chave única, simétrica a `corporate_actions` (v0.3).** A v0.2 declarava isso para `corporate_actions` (§3.2) e citava a mesma política "para barras", mas nunca escrevia a regra aqui. Fica explícita: se o provedor devolve valor diferente para uma data já gravada, a chave `{ticker, date}` casa e o documento é **atualizado**, com o valor anterior logado (ING-03.2). Reexecutar sobre uma janela já ingerida mantém a contagem (ING-03.1) porque a operação nunca é insert.

**Alternativa descartada — `_id` composto** (`_id: {t: ..., d: ...}`). Daria unicidade sem índice adicional. Descartada porque a ordenação de subdocumento em Mongo é por documento inteiro, o que torna consultas de intervalo em `_id.d` corretas mas frágeis a qualquer mudança na ordem dos campos. O ganho de um índice não compensa a armadilha.

**Alternativa descartada — bucketing por mês** (um documento por ticker-mês, com array de barras). É o padrão recomendado para séries temporais em Mongo e reduz overhead de documento. Descartada por volume: 50 mil documentos não justificam a complexidade de leitura parcial e de upsert dentro de array.

### 3.2 Coleção `corporate_actions`

```javascript
{
  ticker: "AAPL",
  date:   ISODate(...),     // data ex
  kind:   "dividend" | "split",
  value:  0.24,             // dividendo por ação — presente sse kind == "dividend"
  ratio:  4.0,              // razão do split  — presente sse kind == "split"
  ingested_at: ISODate(...)
}
```

Índice `{ticker: 1, date: 1, kind: 1}`, único. `kind` entra na chave porque dividendo e split podem cair na mesma data.

**Semântica de escrita: upsert pela chave única.** Se o provedor revisa retroativamente o valor de um dividendo, a chave `{ticker, date, kind}` casa e o documento é **atualizado**, com o valor anterior logado (mesma política de ING-03.2 para barras). Coleção separada de `bars` exatamente porque o ciclo de vida é outro: eventos são revisados retroativamente (ING-02.3) e cobrem o histórico completo, não a janela ingerida.

**Consequência declarada:** revisão retroativa de um evento muda a série ajustada e, portanto, o hash de PER-03.1. Isso é o comportamento desejado — o hash existe para detectar exatamente essa mudança de estado. Hash divergente entre dois runs após uma reingestão é **sinal esperado de revisão de dados**, não bug; o relatório de backtest referencia o `ingestion_run_id`, permitindo rastrear a divergência à sua causa.

**Eventos de magnitude nula (v0.5).** Dividendo de valor `0.0` e split de razão `1.0` são descartados **silenciosamente na normalização** (`ingestion/normalizer.py`), antes de chegarem a esta coleção. Não são eventos: o provedor os inclui como resíduo em datas sem evento, e o fator de ambos é exatamente `1.0` — aplicá-los não mudaria número nenhum, e gravá-los poluiria a coleção com linhas sem significado. Silenciosamente, e não com aviso, porque a ausência de evento numa data é o caso comum, não uma anomalia que mereça atenção. Um dividendo **negativo** continua sendo erro e levanta `DataError` no construtor de `CorporateAction` — o filtro é de magnitude nula, não de sinal.

### 3.3 Coleção `quarantined_bars`

A v0.1 referenciava quarentena sem desenhá-la. Fica desenhada aqui.

**Regras que disparam quarentena** — as de ING-05.1, avaliadas por `ingestion/validator.py` **antes** de qualquer escrita em `bars`:

- `high < low`
- `open` ou `close` fora de `[low, high]`
- qualquer preço ≤ 0
- `volume < 0`

**Destino:** a barra rejeitada **não entra** em `bars`. O payload bruto vai para a coleção própria:

```javascript
{
  ticker: "XYZ",
  date: ISODate(...),
  raw: { ... },                    // payload como veio do provedor, intacto
  reasons: ["close_above_high"],   // toda regra violada, não só a primeira
  ingestion_run_id: ObjectId(...),
  quarantined_at: ISODate(...)
}
```

**Decisões:** (a) coleção própria, e não flag em `bars` — uma barra inválida dentro de `bars` seria uma bomba esperando um `find` que esqueça o filtro; (b) payload bruto preservado, e não descartado com log — quarentena serve para diagnóstico, e diagnóstico precisa do dado original; (c) sem índice único — o mesmo par `(ticker, date)` pode ser quarentenado em runs diferentes, e o histórico interessa; índice simples `{ticker: 1, date: 1}` para consulta.

Quarentena **não bloqueia** o run (diferente de falha de provedor, ING-04.1): as demais barras do ticker seguem, e o `ingestion_run` registra a contagem. Os avisos não-bloqueantes de ING-05.2 e ING-05.3 (gap de pregões, variação extrema sem split) **não** quarentenam — são registrados como `warnings` no `ingestion_run`, porque a barra em si é plausível; o que é suspeito é o contexto.

### 3.4 Coleção `ingestion_runs`

Um documento por execução: tickers pedidos, janela, contagem de barras inseridas e atualizadas, tickers falhos, contagem de quarentenadas (com referência cruzada via `ingestion_run_id`), `warnings`, timestamps de início e fim. Atende PER-03.1 e serve de trilha de auditoria.

**Índice (v0.4 — definido por B4):** `{tickers: 1, started_at: -1}`. `tickers` é array; o índice sobre campo array vira multikey no Mongo automaticamente, e a combinação com `started_at` descendente serve aos dois padrões de acesso que motivaram a lacuna da v0.3 — "qual foi a última ingestão que tocou este ticker" e "runs mais recentes" — com um índice só, sem precisar de dois separados.

### 3.5 Coleção `backtest_runs`

Documento heterogêneo — a razão declarada de ADR-0001 para escolher Mongo. Guarda: parâmetros da estratégia (formato livre), janela, capital inicial, configuração de custos, métricas, lista de trades, curva de equity, hash da série consumida, `ingestion_run_id` de referência, e versão do código.

**Índice (v0.3):** mesma lacuna e mesma razão que §3.4. Fica para F1 (CLI `backtest`), quando o padrão de leitura de resultados existir.

### 3.6 Fronteira de timezone — RNF-07

BSON não tem tipo data-sem-hora. Toda data em Mongo é um instante. A conversão é inevitável — o que importa é que aconteça em **um lugar só**.

| Camada | Tipo de data | Responsável pela conversão |
|---|---|---|
| yfinance | `pd.Timestamp`, às vezes tz-aware | — |
| `ingestion/normalizer.py` | converte para `datetime.date` | **fronteira de entrada** |
| domínio (`engine`, `analytics`, `strategies`) | `datetime.date` sempre | nunca converte |
| `storage/repository.py` | `date` ⇄ `datetime` 00:00 UTC | **fronteira de saída** |

**Regra verificável (v0.3):** a formulação original — "`datetime` só aparece em `ingestion/normalizer.py` e `storage/repository.py`" — se mostrou impossível de cumprir ao pé da letra durante a implementação do Bloco A. O tipo do domínio é `datetime.date`, do mesmo módulo da biblioteca padrão que a linha acima proíbe, e esta própria tabela manda usá-lo "sempre" no domínio. Proibir o módulo `datetime` proibiria o tipo que o design exige em todo lugar.

A regra passa a ser: **a classe `datetime` e o aparato de fuso (`timezone`, `tzinfo`, `UTC`) só podem aparecer em `ingestion/normalizer.py` e `storage/repository.py`.** Os tipos `date` e `timedelta` são livres em todo o projeto — são vocabulário de data-calendário, e RNF-07 exige exatamente esse vocabulário no domínio. O que não pode vazar da fronteira é o *instante*, não a *data*.

Um teste de arquitetura varre os imports e falha se a regra for violada. **Bloqueante no CI** (decisão Q3 da v0.1, confirmada): aviso não-bloqueante vira ruído e para de ser lido.

### 3.7 Leitura ajustada e materialização — ADR-0003

Assinatura pública do repositório:

```python
def get_series(
    ticker: str,
    start: date | None = None,
    end: date | None = None,
    adjusted: bool = True,
) -> PriceSeries: ...
```

`PriceSeries` é um value object: dataclass congelada contendo arrays de preço/volume, datas, e metadados (`ticker`, `adjusted`, `hash`, `last_ingested_at`).

**Sobre `ingestion_run_id` (v0.3 — removido dos metadados).** A v0.2 listava o campo aqui, mas o documento de `bars` em §3.1 nunca o carregou — só `quarantined_bars` tem `ingestion_run_id`, e uma `PriceSeries` é lida de `bars`, não de `quarantined_bars`. O campo não tinha de onde sair, e o Bloco A confirmou isso na implementação: nada em `storage/` sabia preenchê-lo. Mais fundamental: o campo era mal definido mesmo em tese — uma série materializada por `get_series` cobre uma janela de datas que pode atravessar **N ingestões distintas** (uma barra de 2015 e uma de 2024 quase certamente vieram de runs diferentes), então não existe um `ingestion_run_id` singular para atribuir à série inteira. PER-03.1 continua atendido, pelo caminho que já existia: `last_ingested_at` (derivado de `max(ingested_at)` sobre a janela) mais `hash`. Rastrear uma barra específica até seu run de origem continua possível — é `bars` → `ingested_at` → busca em `ingestion_runs` por intervalo de tempo —, só não é um campo único na série agregada.

**Sobre `dates` (v0.3).** É um array de objetos `datetime.date`, não `numpy.datetime64`. `datetime64` reintroduziria instante e fuso pela porta dos fundos, contra RNF-07 — a mesma razão pela qual §3.6 proíbe a classe `datetime` fora da fronteira. O custo é acesso por objeto Python em vez de vetorizado nessa coluna especificamente; aceitável porque data não entra no laço quente do engine, que opera por índice inteiro.

**Sobre imutabilidade — precisão da claim:** `frozen=True` impede reatribuição de atributos, não mutação do conteúdo dos arrays. A imutabilidade **dos dados** vem de outra medida: **na materialização, todos os arrays internos são marcados `flags.writeable = False`**. As duas juntas dão o que a v0.1 chamava vagamente de "imutável": nem os atributos trocam, nem os dados mudam — por qualquer caminho, incluindo via `.base` de views derivadas (ver 4.1).

**Materialização sobre o histórico completo (v0.5 — ADR-0004).** `get_series` lê **todas** as barras do ticker, materializa a série ajustada inteira, e só então devolve o recorte `[start, end]`. Barras e eventos têm o mesmo escopo — o histórico completo. A v0.4 carregava os eventos sobre o histórico completo mas as barras filtradas pela janela, e essa assimetria foi exatamente o bug que ADR-0004 corrige: o `C` de um evento posterior ao fim da janela virava o último fechamento da janela, silenciosamente.

**Quem paga o custo de CPU, e por quanto tempo:** o ajuste é computado **uma vez por chamada de `get_series`**, sobre o **histórico completo** do ticker — não sobre a janela —, e o `PriceSeries` vive enquanto durar o backtest. O engine recebe o objeto materializado e nunca reconsulta o repositório. Uma travessia de ajuste por backtest, não uma por barra. O desperdício de janelas curtas (ler dez anos para devolver um mês) é assumido: ~2500 barras para 10 anos de um ticker, irrelevante no volume que ADR-0001 dimensiona. Sem cache em Fase 1 — ADR-0003 registra materialização em Redis como escopo da Fase 2, condicionada a problema de performance real; RNF-04 dá folga.

**Invariante: INDEPENDÊNCIA DE JANELA (v0.5).** Duas leituras de janelas distintas, sobre o mesmo estado do banco, concordam **valor a valor** nas barras que compartilham. O valor ajustado de uma barra é propriedade do dado, nunca da consulta. É o que a materialização sobre histórico completo garante por construção — não por disciplina de quem chama —, e o que a v0.4 violava: leituras de 42 e de 7 barras divergiam em 0,0437% nas 7 compartilhadas, com hashes distintos. Como o hash de PER-03.1 é função da série, violar este invariante violava PER-03.1 junto.

**Algoritmo do fator.** Eventos carregados sobre o histórico completo do ticker (ING-02.3): um split fora da janela ainda afeta os preços dentro dela.

```
fator_evento(split, razão r)       = 1/r sobre preços,  r sobre volume
fator_evento(dividendo d, close C) = (C − d)/C sobre preços,  1 sobre volume
```

onde `C` é o fechamento **bruto** do pregão anterior à data ex. O fator aplicado à barra em `t` é o produto de todos os fatores de eventos com data **estritamente posterior** a `t` — `cumprod` reverso sobre a série de fatores diários, O(n).

**Definição precisa de `C` (v0.5 — ADR-0004).** `C` é o fechamento bruto da barra **imediatamente anterior à data ex no histórico completo**, qualquer que seja o gap de calendário entre as duas. Com o histórico completo em mãos, "barra imediatamente anterior" *é* o pregão anterior — não há como confundir "o mercado estava fechado" com "não ingerimos esse dia", e portanto não é preciso calendário de pregão para desambiguar. Um gap maior que **5 dias úteis** entre essa barra e a data ex (o mesmo limiar de ING-05.2) emite **aviso não-bloqueante**: o ajuste é aplicado com o `C` disponível, mas um vão desse tamanho indica dado faltando no histórico, e o número resultante merece desconfiança de quem o ler.

**Casos de borda (v0.3 — precisados).** A v0.2 dava duas regras que se sobrepunham quando o evento sem barra anterior era um dividendo ("evento anterior à primeira barra é ignorado" e "dividendo sem barra anterior vira aviso") sem dizer qual prevalece. Resolvido por especificidade — a regra mais específica ao tipo de evento vence:

- **Split** sem nenhuma barra estritamente anterior a ele (evento anterior à primeira barra da série disponível): descartado em silêncio. Não há preço para dividir nem volume para multiplicar; não é uma anomalia, é a série simplesmente não cobrir aquele passado.
- **Dividendo** sem nenhuma barra estritamente anterior: descartado, mas com **aviso**, porque `C` — o fechamento anterior — seria indefinido e descartar em silêncio esconderia um ajuste que deveria ter acontecido caso a série cobrisse uma barra a mais para trás.

**Evento posterior à última barra do histórico (v0.5 — ADR-0004).** Data ex depois do último pregão que existe no banco: **descartado com aviso**, qualquer que seja o tipo. Duas razões:

1. **Não há `C` honesto.** O fechamento anterior à data ex é uma barra que ainda não foi ingerida. Usar o último fechamento disponível como substituto é exatamente o bug que ADR-0004 corrige — só que na ponta direita do histórico em vez da ponta direita da janela.
2. **O fator seria neutro em retorno.** Um evento posterior a **todas** as barras multiplica a série inteira pelo mesmo fator, uniformemente. Retorno percentual entre quaisquer duas barras não muda; muda só o nível absoluto dos preços. E a distorção de nível absoluto já é declarada como o viés 5 de §5.2 (quantidade inteira sobre preço ajustado não corresponde à restrição histórica real). Descartar é conservador e não altera nenhuma métrica de performance.

O aviso existe porque a situação é informativa: significa que o banco tem eventos mais recentes que as barras, ou seja, a ingestão de preços está atrasada em relação à de proventos.

**Dividendo maior ou igual a `C` (v0.3 — não coberto na v0.2).** Produziria fator `(C − d)/C` nulo ou negativo, e um preço ajustado nulo ou negativo atravessaria o resto do sistema parecendo um número válido — o tipo de corrupção silenciosa que este projeto existe para evitar. Tratado como `DataError`: um dividendo maior ou igual ao fechamento do pregão anterior não corresponde a nenhum evento real e indica dado corrompido do provedor. A mensagem de erro deve sugerir a conferência dos eventos corporativos daquele ticker na data em questão.

**Nota — a sanidade cruzada de ADR-0003 encontrou um bug real (v0.5).** ADR-0003 fecha com uma recomendação: "comparar a série ajustada própria contra o `Adj Close` do provedor. Divergência sistemática indica bug; divergência pequena é esperada por diferença de convenção de arredondamento." A recomendação se pagou — foi ela que expôs o bug que ADR-0004 corrige.

Executada ao fim do Bloco B sobre AAPL, janela 2024-01-02 a 2024-01-10, a comparação deu **0,2447% de divergência, constante nas 7 barras**, sempre com a nossa série abaixo. A constância foi o diagnóstico: barras diferentes com a mesma razão só podem divergir por um fator comum, o que aponta para o conjunto ou os valores dos eventos e **descarta** erro de índice ou de `cumprod`. O diagnóstico confirmou:

| | fator acumulado | ajustado de 2024-01-02 |
|---|---|---|
| implementação da v0.4 (`C` da janela) | 0.9863884035 | 183.1131 |
| mesma fórmula, `C` correto de cada `D−1` | 0.9888072905 | 183.5622 |
| `Adj Close` do yfinance | 0.9888072623 | 183.5622 |

Razão entre o cálculo corrigido e a referência: **1.0000000285**. Conjunto de eventos, fórmula e `cumprod` estavam corretos; só o `C` estava errado.

Duas lições que ficam registradas aqui e não só no HANDOFF: (1) a divergência pequena que ADR-0003 dizia ser "esperada por arredondamento" pode ser bug — o que separa os dois casos não é a magnitude, é o **formato**: ruído de arredondamento é errático entre barras, bug de fator é constante; (2) as fixtures de papel de A7 não pegaram porque nenhuma exercitava dividendo posterior ao fim da janela — a única fixture de evento fora da janela usava split, que não precisa de `C`. Fixture de papel só cobre o caso que alguém pensou em escrever.

### 3.8 Hash determinístico — PER-03.1

SHA-256 sobre a representação canônica da série ajustada: linhas ordenadas por data, cada campo formatado com **6 casas decimais fixas**, separador fixo, sem localização.

O arredondamento explícito não é cosmético: sem ele, diferenças de última casa entre plataformas produziriam hashes distintos para a mesma série, e a reprodutibilidade que o hash deveria provar seria justamente o que ele quebraria.

**Campos que entram no hash (v0.3 — enumerados).** A v0.2 dizia "cada campo" sem listar quais, o que não faz sentido ao pé da letra para uma data (uma data não tem 6 casas decimais). Por linha: `date` em ISO-8601 (`AAAA-MM-DD`), seguida de `open`, `high`, `low`, `close`, `volume`, cada um com 6 casas decimais fixas.

`ticker` e a flag `adjusted` **ficam fora** do hash — ambos já são registrados à parte no relatório (§3.5) como metadados da série, e o hash em si identifica o *conteúdo* da série de preços, não sua identidade. Consequência aceita: duas séries de tickers diferentes com preços numericamente idênticos produziriam o mesmo hash. Se isso vier a importar, ticker entra na representação canônica em versão futura — mudaria todo hash já gravado, por isso não é decisão a tomar sem necessidade concreta.

**Zero negativo (v0.3).** `f"{-0.0:.6f}"` produz `"-0.000000"`, que como string difere de `"0.000000"` — hashes distintos para valores numericamente iguais. Não deveria aparecer em preço, mas é exatamente o tipo de "diferença de última casa" que este parágrafo já manda neutralizar; a implementação normaliza zero negativo para positivo antes de formatar.

---

## 4. Engine — o núcleo

### 4.1 `MarketView` — fechando o caminho normal e declarando o anormal

```python
class MarketView:
    """Janela sobre a série, limitada à barra corrente."""
    @property
    def i(self) -> int: ...              # índice da barra corrente
    @property
    def close(self) -> NDArray: ...      # fatia [0 : i+1], somente leitura
    # idem open, high, low, volume, dates
    def last(self, field: str, n: int) -> NDArray: ...
```

O que a construção garante, e por quais mecanismos:

1. **Fatiamento na origem.** Cada acessor devolve `array[: i+1]`. Fatia de numpy é *view*, não cópia — custo O(1), sem penalidade de performance.
2. **Arrays-mãe read-only.** Toda view de numpy expõe `.base`, que aponta para o array original completo — incluindo o futuro. Não há como remover esse atributo. O que o design faz é neutralizar a parte perigosa: como a `PriceSeries` marca os **arrays-mãe** com `writeable=False` na materialização (3.7), o caminho via `.base` não permite **mutação** por nenhuma rota. A **leitura** do futuro via `.base` permanece tecnicamente possível.
3. **Superfície mínima.** `MarketView` não expõe a `PriceSeries`, o array completo nem o índice máximo por sua API. `last(field, n)` com `n > i+1` levanta `InsufficientHistoryError` — nome correto para o que é: histórico insuficiente, não tentativa de lookahead. Com `warmup` declarado isso não deve ocorrer; se ocorrer, o nome do erro aponta a causa certa a quem debugar.

**Claim honesta:** isto é proteção contra **acidente**, não contra **adversário**. Python não tem encapsulamento forte; uma estratégia que escreva `view.close.base` deliberadamente lê o futuro. A postura do design é a mesma já adotada para `writeable=False` na v0.1: aceitar, declarar, e documentar em código — **o teste de ENG-01.3 tenta explicitamente o caminho via `.base`**, verifica que a mutação falha (`ValueError` do numpy) e que a leitura, embora possível, está fora do contrato. A limitação fica gravada onde não se perde: na suíte.

**Alternativa descartada — copiar a fatia a cada barra.** Eliminaria também a leitura via `.base` (a cópia não referencia o array-mãe). Descartada por O(n²) em memória e tempo, para proteger contra um adversário que é o próprio autor do código. Se a Fase 2 introduzir estratégias de terceiros, a decisão deve ser revisitada — está anotado na tabela de riscos.

**Alternativa descartada — DataFrame completo com convenção de só olhar até `i`.** O desenho da maioria dos backtesters de portfólio no GitHub, e a origem da maioria dos lookaheads. Convenção que depende de lembrar não é garantia.

Isto atende ENG-01.3 no caminho de acesso normal. ENG-01.2 (mutação de barras futuras) continua sendo escrito, como confirmação do desenho.

### 4.2 Contrato de estratégia

```python
class Signal(Enum):
    ENTER = "enter"
    EXIT  = "exit"

class Strategy(Protocol):
    @property
    def warmup(self) -> int: ...
    def on_bar(self, view: MarketView) -> Signal | None: ...
```

A estratégia recebe **apenas** a `MarketView`. Não recebe caixa, posição, histórico de trades nem configuração de custos — ENG-05.2 por construção: não há o que consultar.

A separação é conceitual: a estratégia emite **intenção**; o engine decide **execução e tamanho**. É o que permite trocar o esquema de sizing na Fase 2 sem tocar em nenhuma estratégia.

`warmup` é declarado pela estratégia (para SMA cross, `slow`). O engine não chama `on_bar` antes disso — ENG-06.3 sai de graça, sem cada estratégia reimplementar a checagem.

`ENTER` com posição já aberta é **ignorado e logado** (decisão Q2 da v0.1, confirmada): cruzamento repetido é condição de mercado, não erro de programação. Simetricamente para `EXIT` sem posição.

**`EXIT` sem posição consome a ordem pendente, não a deixa para a barra seguinte (v0.6 — precisão sobre Q2).** "Ignorado e logado" já dizia o que acontece com o sinal; o que a v0.1 não precisava porque não existia laço ainda é o que acontece com a *ordem pendente* que carregava esse sinal. A implementação do Bloco C limpa `state.pending` no mesmo passo em que decide ignorar, em vez de deixá-la para ser tentada de novo em `i+1`. Deixá-la pendente reintroduziria lookahead por um caminho indireto: a ordem seria executada, mais tarde, a um preço que a decisão original não conhecia — o mesmo problema que ADR-0002 existe para prevenir, só que via a fila em vez de via a barra.

### 4.3 Ordem de operações dentro da barra

**A parte mais fácil de errar da fase.** Para cada índice `i`:

1. **Executar ordem pendente**, se houver, ao `open[i]`. É aqui que ADR-0002 vira código.
2. **Marcar a mercado** ao `close[i]` e registrar o ponto da equity curve.
3. **Consultar a estratégia** com `MarketView(i)`, se `i >= warmup`. Um sinal retornado vira ordem pendente para `i+1`.

A sequência não é arbitrária, mas não é uma cadeia total de três elos — é duas restrições independentes (v0.6, precisão sobre a redação original). **1 antes de 2**: executar antes de marcar garante que a equity de `i` reflita a posição real ao fim de `i`; inverter atrasaria a equity em um dia em toda barra com execução, e derruba testes de ENG-01.2. **1 antes de 3**: executar antes de consultar garante que nenhuma decisão de `i` seja executada em `i` — é ADR-0002 em código; executar no mesmo índice da decisão também derruba ENG-01.2. **A ordem entre 2 e 3 é livre**: consultar a estratégia não tem efeito colateral sobre a carteira (ENG-05.2 — ela só devolve um sinal, que vira ordem pendente para `i+1`), então marcar antes ou depois de consultar produz o mesmo resultado. A numeração 1-2-3 acima é a ordem em que o laço lê melhor, não uma cadeia de três restrições — um leitor que a tome ao pé da letra concluiria, errado, que inverter 2 e 3 também é violação. A premissa de que a consulta não tem efeito colateral é ela própria travada por teste (`test_the_equity_of_a_bar_does_not_depend_on_the_signal_emitted_on_it`), não presumida. A docstring do loop declara a sequência como invariante; uma inversão que viole 1-antes-de-2 ou 1-antes-de-3 em refatoração futura quebra ENG-01.2.

O "próximo pregão disponível" de ENG-01.5 é simplesmente `i+1` no array — a série contém apenas pregões, gaps de calendário estão implícitos. O gap em dias corridos é computado e gravado no trade para auditoria (4.5).

Sinal na última barra: não há `i+1`, a ordem morre pendente e é reportada como tal (ENG-01.4).

### 4.4 `Portfolio` e `Broker`

`Portfolio` modela N posições desde já (decisão D4 do requirements), com N=1 exercitado. Estado: `cash`, `positions: dict[str, Position]`, `trades: list[Trade]`.

`Broker` executa: calcula quantidade inteira máxima resolvendo `q·p + custo(q·p) ≤ caixa` — atenção a não ignorar o custo no cálculo do tamanho, erro que produz caixa negativo. Quantidade zero ⇒ nenhuma ordem, evento logado (ENG-02.3).

Invariantes checadas a cada barra, como erro de programação e não condição de mercado (ENG-04.4): `cash ≥ 0`, `quantity ≥ 0`.

### 4.5 `Trade`

```python
@dataclass(frozen=True)
class Trade:
    ticker: str
    entry_date: date;  entry_price: float;  entry_decision_date: date
    exit_date: date | None;  exit_price: float | None;  exit_decision_date: date | None
    quantity: int
    entry_cost: float;  exit_cost: float
    entry_gap_days: int;  exit_gap_days: int | None
```

**`exit_decision_date` (v0.6 — struct completado por simetria).** A v0.5 e anteriores listavam `exit_gap_days` sem a data de decisão que o origina, embora `entry_gap_days` viesse acompanhada de `entry_decision_date`. A saída precisa da mesma auditabilidade que a entrada — derivar a data de decisão a partir só do gap reconstruiria informação que o backtest já tinha calculado, e a implementação do Bloco C já carrega o campo.

`entry_decision_date` e `entry_gap_days` tornam o gap de ENG-01.5 auditável: guardando a data da decisão junto da data de execução, o gap é derivável e verificável a posteriori, e não some numa métrica agregada. Uma execução com gap de 4 dias corridos após um feriado longo fica visível no relatório.

### 4.6 Identidade de conciliação — ENG-04.2

Ambiguidade de dupla contagem, resolvida por definição explícita:

```
pnl_realizado(trade) = (saída − entrada) × quantidade          [BRUTO de custos]
custo_total          = Σ (entry_cost + exit_cost)
pnl_nao_realizado    = (último_close − entrada) × quantidade   [posições abertas]

equity_final − equity_inicial ≡ Σ pnl_realizado + pnl_nao_realizado − custo_total
```

PnL realizado é **bruto**; custos entram uma única vez, no termo próprio. A alternativa (PnL líquido) é igualmente válida, mas convida a subtrair custos duas vezes — e o bug resultante é pequeno o bastante para passar despercebido.

Verificação com `math.isclose(rel_tol=1e-9)`, conforme RNF-08. Nunca igualdade exata.

---

## 5. Analytics

Funções puras sobre a equity curve. Nenhuma toca banco ou I/O; todas testáveis com séries de papel (RNF-03).

```python
def sharpe(returns: Series, rf: float = 0.0, periods: int = 252) -> float | None
def max_drawdown(equity: Series) -> DrawdownResult
def cagr(equity: Series) -> float
def hit_rate(trades: list[Trade]) -> float | None
```

Sharpe devolve `None` quando o desvio-padrão é zero (ANA-01.4) — `None` e não `nan`, porque `nan` se propaga silenciosamente por agregações e `None` estoura na hora.

`DrawdownResult` carrega magnitude, data de pico, data de fundo e data de recuperação (ou `None` para não recuperado), conforme ANA-01.3.

### 5.1 Alinhamento do benchmark — ANA-02.2

`first_tradable_index = warmup`. A estratégia só emite sinal a partir de `warmup`, logo só executa a partir de `warmup + 1`.

O benchmark compra ao `open[warmup + 1]`, com os mesmos custos de entrada, e é marcado a mercado até o fim. Estratégia e benchmark compartilham exatamente a mesma janela de equity — sem isso a comparação mede períodos diferentes e não significa nada.

### 5.2 Relatório e a seção fixa de vieses — ANA-03.1

`BacktestReport` é um dataclass renderizado em dois formatos: texto para o CLI e JSON persistido em `backtest_runs`. Contém métricas lado a lado com o benchmark, premissas declaradas (`rf = 0`, custos configurados, tratamento de dividendo via ajuste de preço), e a seção fixa de vieses.

A seção de vieses é **constante literal no código**, não texto montado condicionalmente. Um relatório sem ela é impossível de produzir. Conteúdo integral da constante:

1. **Survivorship bias** — universo fixo de sobreviventes; retornos inflados por construção.
2. **Sem slippage** — execução integral ao `open`, sem desvio entre preço observado e preço pago.
3. **Custos simplificados** — modelo fixo + bps; sem spread, sem borrow, sem imposto.
4. **Sem impacto de mercado** — ordens não movem preço, qualquer tamanho executa.
5. **Granularidade de posição fictícia** — quantidades inteiras calculadas sobre **preços ajustados**, que não são os preços históricos reais (AAPL pré-split-4:1 aparece a ~1/4 do preço da época). A restrição de ação inteira, portanto, não corresponde à restrição que existia historicamente. Simplificação padrão para total return com dividendo via ajuste; declarada, não escondida.
6. **Sem correção para múltiplas hipóteses** — parâmetros testados repetidamente contra a mesma amostra inflacionam métricas.

O item 5 é consequência direta de ADR-0003 + premissa 3 do requirements (sem fracionário) e não estava declarado na v0.1 — a distorção existia no desenho, só não estava confessada.

---

## 6. Riscos do design

| Risco | Impacto | Mitigação |
|---|---|---|
| Bug no fator de ajuste cumulativo | Alto — corrompe tudo a jusante, de forma plausível | Fixtures de papel para split, dividendo e ambos combinados; PER-02.4 (série sem eventos passa intacta); sanidade cruzada contra `Adj Close` durante o desenvolvimento |
| Leitura do futuro via `view.<campo>.base` | Baixo em Fase 1 (autor == usuário) | Proteção é contra acidente, não adversário — aceito e declarado em 4.1; teste de ENG-01.3 documenta o caminho; mutação via `.base` bloqueada por arrays-mãe read-only. **Revisitar se a Fase 2 aceitar estratégias de terceiros** — aí a cópia da fatia volta à mesa |
| Cálculo de quantidade ignorando custo ⇒ caixa negativo | Médio | ENG-04.4 checada a cada barra |
| `datetime` vazando para o domínio | Médio — reaparece em comparação de datas | Teste de arquitetura sobre imports (3.6), bloqueante no CI |
| Ordem de operações na barra invertida em refatoração | Alto — reintroduz lookahead | ENG-01.2 quebra; docstring do loop declara a sequência como invariante |
| Barra inválida escapando da quarentena para `bars` | Médio | Validação em `ingestion/validator.py` é o único caminho de escrita em `bars`; teste de integração grava payload inválido e verifica destino |

## 7. Decisões fechadas nesta versão

| # | Questão (v0.1) | Decisão |
|---|---|---|
| Q1 | `PriceSeries`: DataFrame ou arrays? | Arrays numpy crus na `PriceSeries` e no engine; DataFrame apenas nas fronteiras (I/O e analytics). O laço quente não paga overhead de pandas |
| Q2 | `ENTER` com posição aberta | Ignorar e logar (4.2). Simétrico para `EXIT` sem posição |
| Q3 | Teste de arquitetura: bloqueante ou aviso? | Bloqueante no CI (3.6) |
| Q4 | `EXIT` sem posição: ordem pendente consumida ou retida para a próxima barra? | Consumida (4.2, 4.3) — retê-la reintroduziria lookahead pela fila em vez de pela barra |

## 8. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.6 | 2026-08-04 | Fecha três das quatro ambiguidades registradas em HANDOFF §"Correção de A7 + Bloco C" (a quarta, nomes de teste do ADR-0004, já fora corrigida por errata no próprio ADR). Todas as três são precisão de documentação sobre decisões já tomadas e testadas no Bloco C — nenhuma muda comportamento. (1) §4.3 reescrita: a sequência de três passos do laço não é uma cadeia total — só 1-antes-de-2 e 1-antes-de-3 são restrições reais; a ordem entre 2 e 3 é livre (ENG-05.2) e travada por teste dedicado, não presumida; (2) §4.5 — `exit_decision_date` adicionado ao struct de `Trade`, por simetria com `entry_decision_date`, já implementado desde o Bloco C; (3) §4.2 — precisão sobre Q2: `EXIT` sem posição não só é "ignorado e logado", a ordem pendente correspondente é **consumida**, não retida para a barra seguinte — reter reintroduziria lookahead pela fila. Q4 adicionada à tabela de decisões (7) para ficar no mesmo formato de Q1-Q3. |
| 0.1 | 2026-08-03 | Rascunho inicial |
| 0.2 | 2026-08-03 | Review incorporado: (1) claim "sem escapatória" do `MarketView` corrigida — `.base` do numpy documentado, arrays-mãe marcados read-only na materialização, teste de ENG-01.3 passa a exercitar o caminho de fuga, risco adicionado à tabela; (2) distorção de quantidade inteira sobre preço ajustado adicionada à seção fixa de vieses (item 5), junto com slippage que também faltava; (3) quarentena desenhada — coleção `quarantined_bars`, regras, destino, módulo responsável (3.3); (4) referências de CA prefixadas por família (ENG-/ANA-/ING-/PER-) eliminando colisões de namespace; (5) semântica de upsert de `corporate_actions` declarada + hash divergente após revisão retroativa explicitado como sinal esperado (3.2); menores: `LookaheadError` → `InsufficientHistoryError` para histórico insuficiente, imutabilidade da `PriceSeries` precisada (frozen + writeable=False). Q1–Q3 fechadas |
| 0.3 | 2026-08-03 | Ambiguidades encontradas na implementação do Bloco A (HANDOFF §"Bloco A — storage", seção 4), resolvidas: (1) regra da fronteira de timezone (3.6) reescrita — proíbe a classe `datetime` e o aparato de fuso fora de `ingestion/normalizer.py`/`storage/repository.py`, não o módulo inteiro, que proibiria o próprio `datetime.date` que o design exige no domínio; (2) `ingestion_run_id` removido dos metadados da `PriceSeries` (3.7) — o documento de `bars` nunca carregou o campo, e uma série materializada pode atravessar N ingestões, então não existe um valor singular correto; PER-03.1 continua atendido por `last_ingested_at` + hash; (3) índices de `ingestion_runs` e `backtest_runs` (3.4, 3.5) explicitamente adiados para quando B4 e F1 definirem o padrão de acesso, em vez de ficarem como lacuna silenciosa; (4) campos do hash enumerados — data ISO-8601 + OHLCV, ticker e `adjusted` de fora (3.8); zero negativo normalizado antes de formatar; (5) as duas bordas de ajuste que se sobrepunham (3.7) resolvidas por especificidade: split sem barra anterior é silencioso, dividendo sem barra anterior é aviso + descarte; (6) dividendo ≥ fechamento bruto anterior definido como `DataError` (3.7) — fator nulo ou negativo seria corrupção silenciosa; (7) `dates` da `PriceSeries` especificado como array de `datetime.date`, nunca `datetime64` (3.7); (8) semântica de escrita de `bars` (3.1) escrita explicitamente — upsert pela chave única com log de revisão, simétrica ao que §3.2 já dizia de `corporate_actions`. A implementação do Bloco A já seguia sete das oito decisões (o gate estava code-first nesses pontos); a exceção foi o campo `ingestion_run_id` da `PriceSeries` (item 2), que existia na classe sem ser usado em lugar nenhum e foi removido no mesmo commit desta revisão, para o código não ficar contradizendo a spec por um campo morto. |
| 0.4 | 2026-08-03 | Índice de `ingestion_runs` (3.4) definido por B4, no mesmo commit que passou a gravar na coleção: `{tickers: 1, started_at: -1}`, multikey sobre o array de tickers combinado com ordenação por início — serve tanto "última ingestão deste ticker" quanto "runs mais recentes" com um índice só. `backtest_runs` continua sem índice, adiado para F1. |
| 0.5 | 2026-08-04 | Incorpora **ADR-0004** (ajuste materializado sobre o histórico completo), escrito depois que a sanidade cruzada recomendada por ADR-0003 expôs um bug de correção em A7: `get_series` carregava os eventos sobre o histórico completo mas as barras filtradas pela janela, e o `C` de um evento posterior ao fim da janela virava silenciosamente o último fechamento dela. Mudanças: (1) §3.7 — materialização sobre o histórico completo, depois fatiamento; parágrafo "quem paga o custo de CPU" atualizado para dizer que a travessia é sobre o histórico, não a janela, com o desperdício de janelas curtas assumido; (2) §3.7 — nova borda: evento com data ex posterior à última barra do histórico é descartado com aviso, porque não há `C` honesto e o fator seria reescalonamento uniforme, neutro em retorno; (3) §3.7 — `C` definido como o fechamento bruto da barra imediatamente anterior à data ex **no histórico completo**, qualquer que seja o gap de calendário, com aviso não-bloqueante acima de 5 dias úteis (limiar de ING-05.2); (4) §3.7 — invariante nomeado: **independência de janela**, duas leituras concordam valor a valor nas barras compartilhadas; (5) §3.2 — eventos de magnitude nula (dividendo 0.0, split 1.0) descartados silenciosamente na normalização, pendência registrada no HANDOFF do Bloco B §4.6; (6) §3.7 — nota registrando que a sanidade cruzada de ADR-0003 encontrou o bug, com os números do diagnóstico e as duas lições (o que separa ruído de arredondamento de bug de fator é o formato, não a magnitude; fixture de papel só cobre o caso que alguém pensou em escrever). |
