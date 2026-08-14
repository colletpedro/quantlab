# ADR-0008 — Política de sizing default (1/N, N do run, N=1 ⇒ all-in)

**Status:** aceito
**Data:** 2026-08-14
**Contexto de decisão:** Fase 2a — engine (sizing)

## Contexto

A estratégia emite apenas intenção; o engine decide tamanho (ENG-05.2). A Fase 2a introduz a política de sizing plugável (RF-SIZ-01) e precisa de um default para relatórios comparáveis — e o benchmark precisa da mesma regra para a comparação ser justa (RF-MET-02).

O requisito fechou três pontos no gate 1: `1/N` fixo como default (Q1/D1); `N` = ativos do **run**, fixado no início, independente da disponibilidade de dados, determinístico (P3); e `N = 1` degenera em all-in, a decisão D1 da Fase 1 (Q1). Ativo do run sem nenhuma barra na janela conta no `N`, nunca recebe alvo, contribui zero e é reportado não-negociado (R2/SIZ-02.4).

## Decisão

- **Default: `FixedOneOverN`** — alvo de entrada = `patrimônio_atual / N`, com `N` fixado no início do run (o conjunto passado ao backtest), o mesmo `N` usado pelo benchmark (P3).
- **`N = 1` ⇒ all-in** (fração 1.0), reproduzindo a decisão D1 da Fase 1 (SIZ-02.3).
- **Peso igual entre posições abertas (`EqualWeightOpen`, 1/k) permanece disponível como política configurável** (RF-SIZ-03), com rebalance disparado apenas por mudança de `k` e limiar `|w − 1/k|` em pp absolutos do patrimônio (default 1 pp) gateando o ajuste (S4).
- Invariante: `k ≤ N` — nunca mais posições abertas que ativos no run (SIZ-04.3).

## Justificativa

- **É o benchmark neutro da literatura.** A carteira 1/N é a referência padrão contra a qual se mede qualquer alocação; usar a mesma regra na estratégia e no benchmark mantém a comparação interpretável (RF-MET-02).
- **Determinístico por definição (P3).** N fixado no início, independente de dados disponíveis: dois runs sobre o mesmo universo produzem a mesma alocação-alvo, e o ativo sem barra não introduz buraco de conciliação (R2).
- **Herança limpa da Fase 1.** N=1 ⇒ all-in significa que a Fase 2a roda a Fase 1 sem mudança de comportamento — o contrato de estratégia intocado (SIG-01.1) e a semântica de alocação idêntica.
- **A alternativa (1/k) fica disponível para medir:** o ponto do gate 1 era o backtest **medir** a diferença de churn entre as políticas, não adivinhar — mantê-la configurável preserva isso.

## Alternativas descartadas

**Peso igual entre posições abertas (1/k) com rebalance por mudança de k.** Adapta o capital à concentração real e mede o giro de rebalance — a força honesta é essa. Descartada como default porque gera trades **não solicitados pela estratégia** (o rebalance ajusta posições que a estratégia não pediu), contaminando a leitura do alpha: o relatório não distinguiria retorno de sinal de retorno de realocação. Continua disponível configurável, e o relatório conta trades de rebalance separados dos de sinal (SIZ-03.2).

**`1/N` com N = número de ativos com dado disponível.** Parece a mesma regra e evita "desperdiçar" o N. Descartada porque quebra P3/R2: o N variaria com a disponibilidade de dados (não-determinístico entre runs) e o ativo sem barra sumiria da conciliação em vez de contribuir zero — exatamente o buraco que R2 fecha.

**Inverso da volatilidade (risk parity).** Melhor direcionamento de risco, e o default preferido em gestão de fundos. Descartada como default porque exige janela de estimação (nova fonte de lookahead e de não-determinismo), e o objetivo da fase é medir o engine, não demonstrar uma política de risco específica. Fica como política configurável futura, sem prazo.

## Consequências

- `FixedOneOverN` não consulta o mercado: é função pura de `n` — trivial de testar e impossível de quebrar por estado.
- Benchmark e estratégia compartilham o mesmo N e a mesma regra (MET-04.2/P3) — a comparação mede a mesma pergunta.
- Ativo sem barra: alvo nunca atribuído, contribuição zero, reportado não-negociado (SIZ-02.4) — a conciliação de POR-04.2 não abre buraco.
- Custo aceito: com poucos sinais ativos, 1/N deixa caixa ocioso — que é reportado (SIZ-02.2), não realocado (regra da fase; realocação é política do usuário).

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| Alvo = `patrimônio / N` com N fixado no início do run (SIZ-02.1/P3) | `test_target_is_equity_over_n_fixed_and_n1_is_allin` |
| N=1 ⇒ fração 1.0 (all-in, D1 da Fase 1) (SIZ-02.3) | idem |
| Ativo sem barra conta no N, nunca recebe alvo, contribui zero, concilia (SIZ-02.4/R2) | `test_never_traded_asset_contributes_zero_and_reconciles` |
| Caixa ocioso reportado, não realocado (SIZ-02.2) | `test_idle_cash_reported_not_reallocated` |
| k ≤ N (SIZ-04.3) | `test_open_positions_never_exceed_n` |

## Revisitar quando

O autor adotar uma política de alocação específica para os relatórios da casa (ex.: risk parity com janela definida). Até lá, o default 1/N é a referência neutra; a troca seria um ADR novo supersedendo este.
