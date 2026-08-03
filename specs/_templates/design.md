# <Módulo / Fase> — Design técnico

**Status:** draft | em revisão | aprovada
**Versão:** 0.1
**Data:** AAAA-MM-DD
**Requisitos de origem:** `specs/<caminho>/requirements.md` v<X.Y>
**Próximo gate:** `specs/<caminho>/tasks.md`

> Este documento só começa depois que os requisitos estão **aprovados**. Todo
> requisito citado aqui precisa existir lá; toda decisão de peso vira um ADR em
> `specs/adr/`, não um parágrafo perdido nesta seção.

---

## 1. Visão geral

<!-- Um parágrafo e um diagrama. Quem chama quem, e em que direção os dados fluem. -->

```
<diagrama em texto — caixas e setas bastam>
```

## 2. Componentes

| Componente | Responsabilidade | Não faz |
|---|---|---|
| | | |

A coluna "não faz" é a que evita o módulo crescer sem ninguém notar.

## 3. Interfaces públicas

Assinaturas com type hints completos. O que não estiver aqui é detalhe interno e
pode mudar sem aviso.

```python
# src/quantlab/<pacote>/<modulo>.py

def exemplo(...) -> ...:
    """..."""
```

**Contratos:**

- Pré-condições: <!-- o que o chamador garante -->
- Pós-condições: <!-- o que a função garante -->
- Exceções: <!-- quais, e em que situação — usar a hierarquia de quantlab.exceptions -->

## 4. Modelo de dados

### 4.1 Schemas

<!-- Documentos Mongo, dataclasses ou modelos pydantic. Tipo e unidade de cada
     campo. Datas são data-calendário naive (RNF-07). -->

```json
{
  "campo": "tipo — unidade — obrigatório?"
}
```

### 4.2 Índices e padrões de acesso

| Consulta | Índice usado | Justificativa |
|---|---|---|
| | | |

## 5. Fluxos

Passo a passo dos caminhos principais, incluindo onde cada validação acontece.

1. <!-- passo -->

### 5.1 Casos de borda

| Situação | Comportamento esperado | CA que cobre |
|---|---|---|
| | | |

## 6. Decisões

Decisão local do módulo. Se a decisão amarra o sistema inteiro ou é cara de
reverter, ela é um **ADR** — registre em `specs/adr/` e apenas referencie aqui.

### <D1 — título>

**Escolha:** <!-- o que foi decidido -->

**Por quê:** <!-- a razão, não a racionalização -->

**Alternativas descartadas:**

- **<alternativa>** — <por que é razoável> ... <o que a derrubou>.
  <!-- Se você não consegue escrever a força da alternativa, não a avaliou. -->

**Custo aceito:** <!-- o que fica pior por causa desta escolha -->

## 7. Invariantes

O que precisa ser verdade sempre, e como o código garante — por construção,
por asserção ou por teste.

| Invariante | Como é garantido | Teste que prova |
|---|---|---|
| | | |

## 8. Riscos

| Risco | Impacto | Probabilidade | Mitigação |
|---|---|---|---|
| | | | |

## 9. Estratégia de testes

- **Fixtures:** sintéticas, com resultado calculado no papel (RNF-03)
- **Unitários:** <!-- o que cobrem -->
- **Integração:** <!-- o que exige serviço externo -->
- **Cobertura alvo:** <!-- ≥ 80% em engine/ e analytics/ (RNF-02) -->

## 10. Histórico

| Versão | Data | Mudança |
|---|---|---|
| 0.1 | AAAA-MM-DD | Rascunho inicial |
