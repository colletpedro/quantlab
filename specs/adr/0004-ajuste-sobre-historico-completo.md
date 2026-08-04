# ADR-0004 — Materializar o ajuste sobre o histórico completo, depois fatiar

**Status:** aceito
**Data:** 2026-08-04
**Contexto de decisão:** Fase 1 — persistência
**Relação com ADR-0003:** refina, não reverte. ADR-0003 continua valendo integralmente — preço bruto persistido, ajuste em tempo de leitura, `auto_adjust=False`. Este ADR decide **sobre quais barras** o ajuste é computado.

## Contexto

ADR-0003 decidiu que o ajuste é aplicado na leitura, e o design §3.7 detalhou o algoritmo: para um dividendo `d` com data ex `D`, o fator é `(C − d)/C`, onde `C` é o fechamento **bruto** do pregão anterior a `D`.

A implementação do Bloco A (A7) levou esse algoritmo ao pé da letra, mas com uma assimetria que passou despercebida no gate de design e nas fixtures de papel:

- os **eventos** são carregados sobre o histórico completo do ticker (ING-02.3 exige isso explicitamente, e o código faz);
- as **barras** chegam filtradas pela janela pedida em `get_series(ticker, start, end)`.

`adjustment_factors()` recebe só as barras da janela e calcula `C` como "o fechamento da última barra **dessa janela** estritamente anterior a `D`". Quando `D` é posterior ao fim da janela — o caso de todo evento após o último pregão pedido —, `C` vira silenciosamente o último fechamento da janela, que pode estar meses ou anos antes do `D` verdadeiro.

**O bug foi encontrado pela sanidade cruzada que o próprio ADR-0003 recomenda** ("comparar a série ajustada própria contra o `Adj Close` do provedor. Divergência sistemática indica bug"). A divergência era de 0,2447% em AAPL, constante em todas as barras da janela — o formato constante foi o que apontou para o conjunto ou os valores dos fatores, e não para a lógica por barra.

Números do diagnóstico, ticker AAPL, janela 2024-01-02 a 2024-01-10 (7 barras), 10 dividendos posteriores:

| | fator acumulado | preço ajustado de 2024-01-02 |
|---|---|---|
| implementação com `C` da janela (`C = 186.19` nos 10 eventos) | 0.9863884035 | 183.1131 |
| mesma fórmula, `C` correto de cada `D−1` | 0.9888072905 | 183.5622 |
| `Adj Close` do yfinance | 0.9888072623 | 183.5622 |

Razão entre o cálculo com `C` correto e a referência: **1.0000000285** — ruído de ponto flutuante. O conjunto de eventos estava certo, a fórmula estava certa, o `cumprod` reverso estava certo. Só o `C` estava errado, e só porque a barra `D−1` não estava na janela.

A consequência é observável sem nenhuma referência externa, e é o que torna isto um bug de correção e não uma imprecisão tolerável: **o valor ajustado de uma barra passa a depender da janela consultada**. Duas leituras do mesmo banco, sobre janelas que compartilham barras, devolvem valores diferentes para essas barras — e hashes diferentes, o que ataca PER-03.1 no ponto exato em que ele existe para dar garantia.

Medido, mesmo banco, ticker AAPL com 42 barras: leitura ampla (42 barras) contra leitura estreita (7 barras), nas 7 barras compartilhadas — 0,0437% de diferença em todas as sete, e hashes distintos.

## Decisão

O ajuste é computado sobre o **histórico completo de barras do ticker**, e só então a série resultante é fatiada para a janela pedida.

`get_series(ticker, start, end)` passa a ler todas as barras do ticker, materializar a série ajustada inteira, e devolver o recorte `[start, end]` dela. Barras e eventos passam a ter o mesmo escopo — o histórico completo —, que é a simetria que faltava.

## Justificativa

- **Restaura a simetria que o design já pretendia.** §3.7 mandava carregar os eventos sobre o histórico completo justamente porque um evento fora da janela afeta preços dentro dela. O mesmo raciocínio se aplica às barras: o `C` de um evento fora da janela é uma barra fora da janela. Tratar os dois escopos de forma diferente foi o bug.
- **Dá independência de janela por construção, não por disciplina.** Depois desta decisão não existe caminho pelo qual a janela pedida influencie o valor ajustado — não porque alguém lembrou de passar as barras certas, mas porque a função de ajuste nunca vê uma janela. É a distinção que o design §1 chama de "por construção" contra "por convenção".
- **Torna "pregão anterior à data ex" inambíguo, sem calendário de pregão.** Com o histórico completo, a barra imediatamente anterior a `D` *é* o pregão anterior — não há como confundir "o mercado estava fechado" com "não ingerimos esse dia". Sem isto, distinguir os dois casos exigiria um calendário de pregão que o projeto não tem e que a Fase 1 não quer introduzir.
- **O custo é irrelevante neste volume.** ADR-0001 dimensiona o projeto inteiro em ~50 mil documentos; o histórico completo de um ticker por 10 anos é ~2500 barras. Uma leitura a mais por `get_series`, uma vez por backtest — não uma por barra. RNF-04 dá 5 segundos para um backtest de 10 anos e o ajuste já era uma travessia única.
- **Reconhecidamente subótimo em um eixo:** um backtest sobre uma janela de um mês passa a ler dez anos de barras. É desperdício mensurável e assumido. A alternativa — otimizar a leitura mantendo a correção — é possível (ver "Revisitar quando"), mas otimizar antes de existir problema de performance é o que ADR-0003 já recusou uma vez, ao descartar cache de ajuste na Fase 1.

## Alternativas descartadas

**(A) Buscar o `C` no banco, por evento, fora da janela.** `get_series` consultaria `bars` para o fechamento anterior a cada data ex, sem carregar o histórico inteiro — corrige o valor do `C` lendo bem menos que a alternativa escolhida, e é a opção mais econômica em I/O das três. Descartada por duas razões: tira a pureza de `adjustment_factors()`, que hoje é função sem I/O testável com fixtures de papel (RNF-03) e passaria a depender do repositório ou a receber um callback de busca; e **mantém a assimetria que causou o bug** — barras e eventos continuariam com escopos diferentes, e a próxima pessoa a mexer no módulo teria de reconstruir sozinha o raciocínio de por que um é janela e o outro não. Voltaria à mesa se a leitura do histórico completo virasse gargalo real e a pureza pudesse ser preservada por injeção explícita de um mapa `data → close`.

**(B) Ignorar evento cujo pregão `D−1` não está na janela, com aviso.** Não adiciona I/O nenhum, é a mudança de menor superfície, e estende de forma natural a borda que §3.7 já tem para "dividendo sem barra anterior". Descartada porque **não resolve o problema, só troca o modo de errar**: a série continuaria dependente da janela, agora por omitir ajustes que uma janela mais ampla aplicaria. Uma série a que faltam ajustes legítimos é pior que uma com `C` impreciso — o erro deixa de ser um desvio de fração de por cento e vira o dividendo inteiro não descontado. E o aviso não salva: um aviso que aparece em toda leitura de janela estreita vira ruído e para de ser lido, exatamente o argumento pelo qual a decisão Q3 do design tornou o teste de arquitetura bloqueante.

## Consequências

- `get_series` lê o histórico completo de barras do ticker, não a janela. ~2500 documentos para 10 anos de um ticker; irrelevante no volume de ADR-0001, e assumido como desperdício em janelas curtas.
- **`adjustment_factors()` continua função pura**, sem I/O e sem conhecer o repositório. O que muda é quem a chama e com o quê: `get_series` passa a alimentá-la com o histórico completo. As fixtures de papel de A7 continuam válidas sem alteração.
- **"Pregão anterior à data ex" passa a ser inambíguo** e dispensa calendário de pregão. Um gap grande entre a barra anterior e a data ex deixa de ser ambiguidade e vira sinal de dado faltando — tratado como aviso não-bloqueante no limiar já usado por ING-05.2 (5 dias úteis).
- O hash de PER-03.1 de uma barra passa a depender só do estado do banco, nunca da janela consultada. Dois backtests sobre janelas diferentes que compartilham barras produzem valores idênticos para elas.
- Evento com data ex posterior à **última barra do histórico completo** passa a ser descartado com aviso — não há `C` honesto para ele, e o fator de um evento posterior a todas as barras seria reescalonamento uniforme da série inteira, neutro em retorno. Detalhado em design §3.7.
- Os valores ajustados mudam em relação ao que o Bloco A produzia sempre que havia evento após o fim da janela. Isso é a correção, não uma regressão — mas invalida qualquer hash gravado antes desta data.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| **Independência de janela.** Duas leituras de janelas distintas, sobre o mesmo estado do banco, concordam valor a valor nas barras que compartilham. | `tests/unit/test_adjustment.py::test_factors_do_not_depend_on_the_requested_window` (papel) e `tests/integration/test_repository_series.py::test_adjusted_values_do_not_depend_on_the_requested_window` (Mongo real) |
| `C` é o fechamento bruto da barra imediatamente anterior à data ex **no histórico completo**, e não da última barra de uma janela. | `tests/unit/test_adjustment.py::test_dividend_after_the_window_uses_the_true_previous_close` |
| Evento com data ex posterior à última barra do histórico é descartado com aviso. | `tests/unit/test_adjustment.py::test_event_after_the_last_bar_is_discarded_with_a_warning` |

## Revisitar quando

Quando a leitura do histórico completo virar gargalo medido — não suposto. O gatilho concreto: um backtest que viole RNF-04 (10 anos de barras diárias em menos de 5 segundos) com o tempo dominado pela leitura de `bars`, ou a Fase 2 introduzir multi-ativo em execução, onde o custo se multiplica pelo número de papéis do portfólio. Nesse ponto a alternativa (A) volta à mesa com a pureza preservada por injeção de um mapa `data → close`, e o cache em Redis que ADR-0003 já deixou anotado para a Fase 2 passa a ter um problema real para resolver.
