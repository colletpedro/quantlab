# ADR-0003 — Guardar preço bruto e ajustar por proventos em tempo de leitura

**Status:** aceito
**Data:** 2026-08-03
**Contexto de decisão:** Fase 1 — persistência

## Contexto

Preços de ações precisam ser corrigidos por eventos corporativos antes de virarem retorno. Sem isso, um split 2:1 aparece como queda de 50% e um dividendo aparece como perda no dia ex.

O ponto não óbvio: **o ajuste não é uma propriedade do passado, é uma função do presente.** Toda vez que um novo dividendo é pago, a série ajustada inteira muda retroativamente. Um valor "ajustado" gravado hoje estará errado no mês que vem.

Há três desenhos possíveis: gravar apenas ajustado, gravar bruto e ajustado lado a lado, ou gravar bruto e ajustar na leitura.

## Decisão

Persistir OHLCV **bruto** e eventos corporativos em coleções separadas. Aplicar o ajuste em tempo de leitura, na camada de repositório. A coleta usa `auto_adjust=False`.

## Justificativa

- **O bruto é imutável, o ajustado não é.** Guardar o imutável e derivar o mutável é a direção correta da dependência.
- **Reprodutibilidade.** Com bruto + eventos, é possível reconstruir a série tal como era em qualquer data passada. Com ajustado gravado, essa informação se perde.
- **Auditabilidade.** Quando um número parecer errado, dá para separar erro de dado de erro de ajuste. Com ajustado gravado, os dois são indistinguíveis.
- **Valor didático.** Implementar o fator de ajuste força o entendimento de por que a série muda sozinha — um dos assuntos que separa quem já lidou com dados de mercado de quem não lidou.

## Alternativas descartadas

**Usar `auto_adjust=True` e gravar o ajustado.** Mais simples e menos sujeito a bug de implementação. Descartada porque congela um ajuste que envelhece, impede reprodutibilidade histórica, e transfere para o provedor uma decisão que o sistema deveria conseguir explicar. Reconhecidamente, é a opção de menor risco de bug.

**Gravar bruto e ajustado lado a lado.** Descartada por criar duas fontes de verdade que divergem silenciosamente assim que um novo provento é pago. Denormalização sem invalidação é armadilha.

**Materializar o ajustado em cache, invalidado por novo evento.** Boa ideia — mas é otimização. Descartada na Fase 1 por não haver problema de performance a resolver. Reavaliar na Fase 2, quando Redis entrar.

## Consequências

- Custo de CPU em toda leitura de série. Irrelevante no volume da fase (RNF-04 dá folga).
- Risco real de bug no fator de ajuste. Mitigado por CA-02.1 a CA-02.4, com fixtures sintéticas de split e dividendo com resultado calculado no papel, e por CA-02.4 garantindo que série sem eventos passa intacta.
- Eventos corporativos precisam ser coletados sobre o histórico completo, não só sobre a janela pedida (CA-02.3): um split fora da janela ainda afeta os preços dentro dela.
- Sanidade cruzada recomendada durante o desenvolvimento: comparar a série ajustada própria contra o `Adj Close` do provedor. Divergência sistemática indica bug; divergência pequena é esperada por diferença de convenção de arredondamento.

## Nota técnica — fator de ajuste

Para split de razão `r` na data D, toda barra anterior a D tem preços divididos por `r` e volume multiplicado por `r`.

Para dividendo `d` pago na data ex D, com `close` de D−1 igual a `C`, o fator é `(C − d) / C`, aplicado multiplicativamente a todas as barras anteriores a D. Volume não muda.

Quando há múltiplos eventos, os fatores são cumulativos: a barra em `t` recebe o produto de todos os fatores de eventos posteriores a `t`.
