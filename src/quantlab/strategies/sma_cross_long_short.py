"""SMA cross long+short — T13 (DoD 2b): a `SmaCross` 20/50 estendida para shorts.

Mesma lógica da `SmaCross` da Fase 1/2a (cruzamento das médias 20/50), agora
com o lado curto: tendência de alta ⇒ long, tendência de baixa ⇒ short,
sempre no mercado (flip). A **direção é decisão da estratégia, no sinal**
(D3/RF-SHT-01): `ENTER`/`ENTER_SHORT` abrem, `EXIT` fecha qualquer posição.

Por que **EXIT** fecha o short (e não `EXIT_SHORT`)? A cobertura pelo `EXIT`
do laço é **agnóstica de sinal** (venda que zera a posição, long ou short —
semântica Q2: "EXIT sem posição é consumido"), e isso é o que torna a
estratégia **robusta a liquidação forçada** (RF-MRG-02): se a margem cobrir um
short à revelia da estratégia (seleção alfabética, CA-02.1), o `EXIT` seguinte
é consumido sem erro e o estado interno se re-sincroniza na entrada seguinte.
`EXIT_SHORT` sem posição short aberta é `EngineError` (SHT-01.3) — emitir esse
sinal com estado dessincronizado quebraria o run inteiro no primeiro margin
call. O `EXIT_SHORT` continua sendo o caminho canônico de cobertura (testado
na T02 e na mutação da T12); esta estratégia só não o usa, por decisão
documentada aqui.

O fechamento segue o **gate de warmup do laço** (`warmup = slow`, mesmo da
`SmaCross`): a estratégia nunca trade a cauda, e o `EXIT` na última barra da
série morre pendente (ENG-01.4) — mesma regra da Fase 1.

**Estado por instância:** uma instância por ativo por run (o runner cria
instâncias novas a cada execução — determinismo RNF-01). `_pos` é o estado
pretendido; divergências de realidade causadas por liquidação forçada se
re-sincronizam pelo `EXIT` consumido, acima.
"""

from dataclasses import dataclass, field

from quantlab.engine.market_view import MarketView
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError

__all__ = ["SmaCrossLongShort"]


@dataclass
class SmaCrossLongShort:
    """Cruzamento 20/50 long+short — T13 (DoD 2b).

    Comportamento por cruzamento das médias (espelho da `SmaCross`, com o
    lado curto):

    - cruzamento para cima: short aberto ⇒ `EXIT` (cobre, estado vira flat);
      flat ⇒ `ENTER` (long); long ⇒ nada (já long).
    - cruzamento para baixo: long aberto ⇒ `EXIT` (fecha, estado vira flat);
      flat ⇒ `ENTER_SHORT` (short); short ⇒ nada (já short).
    - sem cruzamento com estado flat: a tendência vigente decide a **reentrada**
      (alta ⇒ `ENTER`, baixa ⇒ `ENTER_SHORT`) — é o que transforma o "fechou e
      ficou flat" do cruzamento na virada long ↔ short.

    A reentrada sem cruzamento é necessária porque o cruzamento é um evento
    único: "fechou o long" e "abriu o short" não cabem num único sinal — a
    virada acontece em dois passos (fecha no cruzamento, abre na barra
    seguinte com a tendência ainda vigente), cada um executando no próximo
    open do PRÓPRIO ativo (ADR-0002).
    """

    fast: int
    slow: int
    #: Estado pretendido da instância (long/short/flat) — não é dado de
    #: mercado, é memória das próprias emissões (D3: o sizer nunca decide
    #: direção; aqui quem decide é a estratégia, no sinal).
    _pos: str = field(default="flat", init=False, repr=False)

    def __post_init__(self) -> None:
        if self.fast >= self.slow:
            raise EngineError(
                f"SMA cross exige fast < slow; recebeu fast={self.fast}, slow={self.slow}."
            )

    @property
    def warmup(self) -> int:
        return self.slow

    def on_bar(self, view: MarketView) -> Signal | None:
        close = view.close
        current_fast = float(close[-self.fast :].mean())
        current_slow = float(close[-self.slow :].mean())
        previous_fast = float(close[-self.fast - 1 : -1].mean())
        previous_slow = float(close[-self.slow - 1 : -1].mean())

        previous_diff = previous_fast - previous_slow
        current_diff = current_fast - current_slow

        if previous_diff <= 0 and current_diff > 0:  # cruzou para cima
            if self._pos == "short":
                self._pos = "flat"
                return Signal.EXIT
            if self._pos == "flat":
                self._pos = "long"
                return Signal.ENTER
            return None
        if previous_diff >= 0 and current_diff < 0:  # cruzou para baixo
            if self._pos == "long":
                self._pos = "flat"
                return Signal.EXIT
            if self._pos == "flat":
                self._pos = "short"
                return Signal.ENTER_SHORT
            return None
        # Sem cruzamento — reentrada da virada (long ↔ short) com estado flat.
        if self._pos == "flat":
            if current_diff > 0:
                self._pos = "long"
                return Signal.ENTER
            if current_diff < 0:
                self._pos = "short"
                return Signal.ENTER_SHORT
        return None
