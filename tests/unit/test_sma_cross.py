"""D1 — SMA cross (ENG-06.1 a ENG-06.4).

Fixture de papel única, `fast=2, slow=3`, com os dois cruzamentos calculados
à mão. Closes escolhidos por conveniência de aritmética, não de realismo.

    i   close   SMA(2)          SMA(3)          sinal
    0   10                                      (aquecimento)
    1   10                                      (aquecimento)
    2   10                                      (aquecimento)
    3   20      mean(10,20)=15  mean(10,10,20)=13.333  cruzamento p/ cima → ENTER
                prev: SMA2(10,10)=10, SMA3(10,10,10)=10  → prev_diff=0 (<=0)
                curr_diff=15-13.333=1.667>0
    4   30      mean(20,30)=25  mean(10,20,30)=20      sem cruzamento → None
                prev: SMA2(10,20)=15, SMA3(10,10,20)=13.333  → prev_diff=1.667>0
                curr_diff=25-20=5>0
    5    5      mean(30,5)=17.5 mean(20,30,5)=18.333   cruzamento p/ baixo → EXIT
                prev: SMA2(20,30)=25, SMA3(10,20,30)=20  → prev_diff=5>=0
                curr_diff=17.5-18.333=-0.833<0
    6    5      mean(5,5)=5     mean(30,5,5)=13.333    sem cruzamento → None
                prev: SMA2(30,5)=17.5, SMA3(20,30,5)=18.333  → prev_diff=-0.833<=0
                curr_diff=5-13.333=-8.333, não é >0

`warmup = slow = 3`: a primeira chamada possível é `i = 3`, e é exatamente
onde o cruzamento de entrada acontece — a fixture usa a borda do aquecimento
de propósito, não por acaso.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pytest
from numpy.typing import NDArray

from quantlab.engine.backtest import run_backtest
from quantlab.engine.broker import CostModel
from quantlab.engine.market_view import MarketView
from quantlab.engine.strategy import Signal
from quantlab.exceptions import EngineError
from quantlab.storage.series import PriceSeries
from quantlab.strategies.sma_cross import SmaCross

_CLOSES = [10.0, 10.0, 10.0, 20.0, 30.0, 5.0, 5.0]
_FREE = CostModel(fixed=0.0, rate=0.0)


def _series(closes: list[float], *, opens: list[float] | None = None) -> PriceSeries:
    bar_dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(len(closes))]
    dates: NDArray[np.object_] = np.empty(len(bar_dates), dtype=object)
    dates[:] = bar_dates
    open_prices = opens if opens is not None else closes
    return PriceSeries(
        ticker="TEST",
        dates=dates,
        open=np.array(open_prices, dtype=np.float64),
        high=np.array(closes, dtype=np.float64),
        low=np.array(open_prices, dtype=np.float64),
        close=np.array(closes, dtype=np.float64),
        volume=np.array([1_000.0] * len(closes)),
        adjusted=True,
        hash="0" * 64,
    )


# ─── ENG-06.4: fast >= slow falha na instanciação ────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(("fast", "slow"), [(3, 3), (5, 3), (10, 2)])
def test_fast_not_smaller_than_slow_fails_at_instantiation(fast: int, slow: int) -> None:
    with pytest.raises(EngineError, match="fast < slow"):
        SmaCross(fast=fast, slow=slow)


@pytest.mark.unit
def test_valid_fast_slow_instantiates_without_error() -> None:
    strategy = SmaCross(fast=2, slow=3)
    assert strategy.fast == 2
    assert strategy.slow == 3


# ─── ENG-06.3: warmup = slow, sem sinal antes disso ──────────────────────────


@pytest.mark.unit
def test_warmup_equals_slow() -> None:
    assert SmaCross(fast=2, slow=3).warmup == 3
    assert SmaCross(fast=5, slow=20).warmup == 20


@dataclass
class _CallRecordingSmaCross:
    """Encapsula `SmaCross`, registrando todo índice em que `on_bar` é chamado.

    A mutação `warmup = fast` (em vez de `slow`) só derruba
    `test_warmup_equals_slow` — nenhum dos testes de cruzamento abaixo nota a
    diferença, porque nesta fixture (`_CLOSES` plano nas três primeiras
    barras) chamar `on_bar` prematuramente em `i=fast` produz `prev_diff ==
    curr_diff == 0`, que não passa nas comparações estritas (`> 0`/`< 0`) e
    portanto não gera sinal — um empate mascara o warmup errado, não prova
    que ele está certo. Este teste trava o contrato pelo lado que a
    coincidência aritmética não protege: quais índices o engine efetivamente
    consultou, via `run_backtest` de ponta a ponta, não via chamada direta a
    `on_bar`.
    """

    fast: int
    slow: int
    seen_indices: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._inner = SmaCross(fast=self.fast, slow=self.slow)

    @property
    def warmup(self) -> int:
        return self._inner.warmup

    def on_bar(self, view: MarketView) -> Signal | None:
        self.seen_indices.append(view.i)
        return self._inner.on_bar(view)


@pytest.mark.unit
def test_engine_never_calls_on_bar_before_slow_bars_of_true_history() -> None:
    """ENG-06.3, pelo lado do engine: o primeiro índice consultado é `i = slow`.

    Não basta `warmup == slow` como valor isolado (já coberto acima); é o
    `run_backtest` respeitando esse valor que garante que `on_bar` nunca vê
    menos de `slow` barras de fechamento verdadeiro — é essa garantia que faz
    as médias de `on_bar` serem calculadas sobre janelas completas.
    """
    series = _series(_CLOSES)
    spy = _CallRecordingSmaCross(fast=2, slow=3)

    run_backtest(series, spy, costs=_FREE)

    assert spy.seen_indices, "on_bar nunca foi chamado — série curta demais para a fixture"
    assert min(spy.seen_indices) == 3


# ─── ENG-06.1 / ENG-06.2: cruzamento para cima e para baixo, calculados à mão ─


@pytest.mark.unit
def test_crossing_up_enters_at_the_warmup_boundary() -> None:
    """i=3 é a primeira barra elegível (warmup=3) e já é o cruzamento p/ cima."""
    series = _series(_CLOSES)
    strategy = SmaCross(fast=2, slow=3)

    assert strategy.on_bar(MarketView(series, 3)) is Signal.ENTER


@pytest.mark.unit
def test_no_crossing_emits_no_signal() -> None:
    series = _series(_CLOSES)
    strategy = SmaCross(fast=2, slow=3)

    assert strategy.on_bar(MarketView(series, 4)) is None


@pytest.mark.unit
def test_crossing_down_exits() -> None:
    series = _series(_CLOSES)
    strategy = SmaCross(fast=2, slow=3)

    assert strategy.on_bar(MarketView(series, 5)) is Signal.EXIT


@pytest.mark.unit
def test_no_crossing_after_the_exit_emits_no_signal() -> None:
    series = _series(_CLOSES)
    strategy = SmaCross(fast=2, slow=3)

    assert strategy.on_bar(MarketView(series, 6)) is None


# ─── Ponta a ponta: o engine não precisa mudar para receber D1 (ENG-05.1) ────


@pytest.mark.unit
def test_full_backtest_enters_and_exits_at_the_next_bars_open() -> None:
    """ENTER decidido em i=3 executa no open de i=4; EXIT decidido em i=5 no open de i=6."""
    opens = [9.0, 9.0, 9.0, 19.0, 29.0, 4.0, 4.0]
    series = _series(_CLOSES, opens=opens)
    strategy = SmaCross(fast=2, slow=3)

    result = run_backtest(series, strategy, initial_cash=10_000.0, costs=_FREE)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_date == series.dates[4]
    assert trade.entry_price == pytest.approx(opens[4])
    assert trade.exit_date == series.dates[6]
    assert trade.exit_price == pytest.approx(opens[6])
    assert result.reconciles()
