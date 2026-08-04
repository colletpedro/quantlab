"""SMA cross — D1, design §4.2, RF-ENG-06.

A estratégia mais simples possível, e por isso a que exercita o contrato de
C2 sem folga: recebe só a `MarketView`, declara `warmup`, devolve `Signal`.
Se D1 exigisse qualquer mudança no engine, o protocolo estaria incompleto —
não exigiu (ENG-05.1).
"""

from dataclasses import dataclass

from quantlab.engine.market_view import MarketView
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError

__all__ = ["SmaCross"]


@dataclass(frozen=True, slots=True)
class SmaCross:
    """Cruzamento de médias móveis simples — ENG-06.1 a ENG-06.4.

    `warmup = slow` (ENG-06.3 sai de graça: o engine não chama `on_bar` antes
    disso). Cruzamento para cima gera `ENTER`, para baixo gera `EXIT`, ambos
    executados no próximo pregão via ADR-0002 — a estratégia só emite a
    intenção, quem decide execução é o laço do engine.
    """

    fast: int
    slow: int

    def __post_init__(self) -> None:
        if self.fast >= self.slow:
            raise EngineError(
                f"SMA cross exige fast < slow; recebeu fast={self.fast}, slow={self.slow}."
            )

    @property
    def warmup(self) -> int:
        return self.slow

    def on_bar(self, view: MarketView) -> Signal | None:
        """Compara a SMA atual contra a da barra anterior para achar o cruzamento.

        `warmup = slow` garante, na primeira chamada (`i = slow`), `slow + 1`
        barras em `view.close` — o suficiente para calcular as duas médias na
        barra corrente e também na anterior, sem tocar `last()` (que não tem
        como expressar uma janela deslocada).
        """
        close = view.close

        current_fast = float(close[-self.fast :].mean())
        current_slow = float(close[-self.slow :].mean())
        previous_fast = float(close[-self.fast - 1 : -1].mean())
        previous_slow = float(close[-self.slow - 1 : -1].mean())

        previous_diff = previous_fast - previous_slow
        current_diff = current_fast - current_slow

        if previous_diff <= 0 and current_diff > 0:
            return Signal.ENTER
        if previous_diff >= 0 and current_diff < 0:
            return Signal.EXIT
        return None
