# ADR-NNNN — <decisão em uma linha, no imperativo>

**Status:** proposto | aceito | substituído por [ADR-MMMM](MMMM-<slug>.md)
**Data:** AAAA-MM-DD
**Contexto de decisão:** Fase <N> — <módulo>

> Copie para `specs/adr/NNNN-<slug-em-kebab-case>.md` e registre a linha no
> índice de `specs/README.md`.
>
> **ADRs são numerados e imutáveis.** Quando a decisão mudar, escreva um ADR novo
> declarando supersedência e marque este como substituído. Não edite o conteúdo
> nem apague o arquivo: o histórico de decisões revertidas faz parte do que o
> repositório demonstra.
>
> ADR é para decisão **cara de reverter** ou que amarra o sistema. Escolha local
> e barata mora na seção "Decisões" do `design.md`.

---

## Contexto

<!-- Qual é a força em jogo. Restrições reais: volume, prazo, competência
     disponível, o que já existe. Escreva o suficiente para que alguém daqui a
     um ano entenda a decisão sem precisar de você. Sem justificar nada ainda. -->

## Decisão

<!-- Uma ou duas frases, afirmativas e específicas. O que passa a valer. -->

## Justificativa

<!-- Por que esta e não outra. Se a escolha é reconhecidamente subótima em algum
     eixo, diga qual e por que o trade-off compensa — um ADR que só elogia a
     própria decisão não foi escrito honestamente. -->

- **<argumento>.** <!-- desenvolvimento -->

## Alternativas descartadas

Cada alternativa precisa aparecer com a **sua força**, não como espantalho. Se a
alternativa não tem nenhuma vantagem escrita, ela não foi avaliada.

**<Alternativa A>.** <o que ela tem de bom, honestamente> Descartada porque <o que
a derruba neste contexto>. <Quando ela voltaria a ser a resposta certa.>

**<Alternativa B>.** ...

## Consequências

O que passa a ser verdade — inclusive o que fica pior.

- <!-- consequência positiva -->
- <!-- consequência negativa, e como é mitigada -->
- <!-- o que isso obriga o código a respeitar daqui pra frente -->

## Invariantes que o código precisa respeitar

Se esta decisão gera regra que o código não pode violar, escreva aqui e aponte o
teste que a prova. É esta seção que transforma o ADR em algo verificável em vez
de um documento decorativo.

| Invariante | Teste que prova |
|---|---|
| | |

## Revisitar quando

<!-- O gatilho concreto que reabre esta decisão: um limiar de volume, uma fase do
     roadmap, uma dependência que mudar. "Se necessário" não é gatilho. -->
