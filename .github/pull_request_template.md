# O que muda

<!-- Uma frase. O quê, não como. -->

## Spec correspondente

<!-- Link para a spec e a seção. Ex.: specs/00-plataforma/fase-1-requirements.md §4.3 -->

- **Spec:**
- **RFs cobertos:**
- **Critérios de aceitação verificados:**

---

## Checklist de gate

Este repositório é spec-driven. Um item não marcado é um gate reprovado, não uma
pendência a resolver depois do merge.

### Spec

- [ ] A spec correspondente existe, está **aprovada** e o PR não a extrapola
- [ ] Se o PR mudou o entendimento do problema, a spec foi atualizada **antes** do código
- [ ] `specs/README.md` reflete o estado real dos gates deste módulo

### ADRs

- [ ] Li os ADRs em `specs/adr/` e o PR não viola nenhum
- [ ] **ADR-0002** — nenhum caminho novo permite decidir com informação posterior ao
      fechamento de D; execução continua no `open` do pregão seguinte
- [ ] **ADR-0003** — preço bruto continua sendo o que é persistido; o ajuste por
      proventos acontece na leitura
- [ ] Se uma decisão arquitetural mudou, há um **novo ADR** declarando supersedência
      (o anterior não foi editado nem removido)

### Testes

- [ ] Cada critério de aceitação citado acima tem um teste que falharia sem esta mudança
- [ ] Testes de `engine/` e `analytics/` usam **fixtures sintéticas** com resultado
      calculável no papel (RNF-03), não dados reais de mercado
- [ ] Cobertura ≥ 80% em `engine/` e `analytics/` (RNF-02)
- [ ] Comparações de valores monetários usam tolerância explícita, nunca igualdade
      exata (RNF-08)
- [ ] A suíte default continua rodando offline (RNF-06)

### Qualidade

- [ ] `make check` passa localmente
- [ ] Type hints em tudo; `mypy --strict` limpo (RNF-05)
- [ ] Nenhum `print()` — saída observável passa por `structlog`
- [ ] Datas são data-calendário naive, sem timezone (RNF-07)
- [ ] Mesma entrada produz mesma saída; nenhuma aleatoriedade não semeada (RNF-01)

### Documentação

- [ ] `specs/CHANGELOG.md` atualizado se alguma spec ou ADR mudou de versão/status
- [ ] `README.md` atualizado se mudou o modo de rodar, a estrutura ou as limitações
- [ ] Novas premissas ou vieses introduzidos estão declarados (RF-ANA-03)

---

## Como verificar

<!-- Comandos exatos para reproduzir o resultado. Se o PR muda número de backtest,
     cole o antes e o depois. -->

## Fora de escopo

<!-- O que foi deliberadamente deixado de fora, e para qual fase. -->
