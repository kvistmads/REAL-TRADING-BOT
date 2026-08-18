import numpy as np
import pandas as pd

from data.indicators import add_all
from gates.base import GateResult
from gates.regime import (
    RegimeGate,
    SIDEWAYS_OK_STRATEGIES,
    TRENDING,
    VOLATILE,
    SIDEWAYS,
)
from strategies.base import Signal
from strategies.registry import load_strategies

CONFIG = {
    "gates": {
        "regime": {
            "enabled": True,
            "blocking": True,
            "min_trending_adx": 25,
            "max_volatile_atr_pct": 4.0,
            "volatile_min_confidence": 0.75,
        }
    }
}


def _df(prices: np.ndarray, high_mult=1.005, low_mult=0.995) -> pd.DataFrame:
    n = len(prices)
    times = pd.date_range("2024-01-01", periods=n, freq="4h")
    df = pd.DataFrame({
        "time": times,
        "open": prices,
        "high": prices * high_mult,
        "low": prices * low_mult,
        "close": prices,
        "volume": np.full(n, 1000.0),
    })
    return add_all(df)


def trending_df(n: int = 300) -> pd.DataFrame:
    return _df(np.linspace(100, 200, n))


def sideways_df(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    return _df(100 + rng.normal(0, 0.05, n))


def choppy_df(seed: int, drift: float, noise: float, n: int = 300) -> pd.DataFrame:
    """Konsolidering med lav — men ikke nul — ADX, som live-kørslens SOL/USDT (ADX 15-22)."""
    rng = np.random.default_rng(seed)
    return _df(100 + np.cumsum(rng.normal(drift, noise, n)))


def adx18_df() -> pd.DataFrame:
    return choppy_df(seed=1, drift=0.02, noise=0.8)  # ADX ≈ 18


def adx15_df() -> pd.DataFrame:
    return choppy_df(seed=5, drift=0.05, noise=0.5)  # ADX ≈ 15


def volatile_df(n: int = 300) -> pd.DataFrame:
    # Store, retningsløse udsving → høj ATR, lav ADX, ingen konsistent EMA-hældning.
    prices = np.array([100.0 if i % 2 == 0 else 135.0 for i in range(n)])
    return _df(prices, high_mult=1.02, low_mult=0.98)


def _signal(confidence: float, strategy_id: str = "rsi_divergence") -> Signal:
    return Signal(
        strategy_id=strategy_id, symbol="BTC/USDT", side="long",
        confidence=confidence, timeframe="4h", metadata={},
    )


class TestRegimeClassification:
    def setup_method(self):
        self.gate = RegimeGate(CONFIG)

    def test_trending(self):
        assert self.gate.classify(trending_df()) == TRENDING

    def test_sideways(self):
        assert self.gate.classify(sideways_df()) == SIDEWAYS

    def test_volatile(self):
        assert self.gate.classify(volatile_df()) == VOLATILE


class TestRegimeGate:
    def setup_method(self):
        self.gate = RegimeGate(CONFIG)

    def test_trending_passes(self):
        ctx = {"df": trending_df()}
        result = self.gate.evaluate(_signal(0.65), ctx)
        assert isinstance(result, GateResult)
        assert result.passed is True
        assert ctx["regime"] == TRENDING

    def test_sideways_blocked(self):
        ctx = {"df": sideways_df()}
        result = self.gate.evaluate(_signal(0.90), ctx)
        assert result.passed is False
        assert ctx["regime"] == SIDEWAYS

    def test_volatile_low_confidence_blocked(self):
        ctx = {"df": volatile_df()}
        result = self.gate.evaluate(_signal(0.60), ctx)
        assert result.passed is False
        assert ctx["regime"] == VOLATILE

    def test_volatile_high_confidence_passes(self):
        ctx = {"df": volatile_df()}
        result = self.gate.evaluate(_signal(0.80), ctx)
        assert result.passed is True
        assert ctx["regime"] == VOLATILE

    def test_missing_df_is_sideways(self):
        ctx = {"df": None}
        result = self.gate.evaluate(_signal(0.90), ctx)
        assert result.passed is False
        assert ctx["regime"] == SIDEWAYS


class TestSidewaysIsStrategyAware:
    """Sideways blokerer kun trend-strategier — ranging-strategierne slipper igennem."""

    def setup_method(self):
        self.gate = RegimeGate(CONFIG)

    def test_reversal_context_passes_at_adx_18(self):
        ctx = {"df": adx18_df()}
        result = self.gate.evaluate(_signal(0.65, "reversal_context"), ctx)
        assert ctx["regime"] == SIDEWAYS
        assert result.passed is True
        assert result.score == 0.7
        assert "ADX=18" in result.reason
        assert "reversal_context" in result.reason

    def test_volatility_breakout_passes_at_adx_15(self):
        ctx = {"df": adx15_df()}
        result = self.gate.evaluate(_signal(0.65, "volatility_breakout"), ctx)
        assert ctx["regime"] == SIDEWAYS
        assert result.passed is True
        assert result.score == 0.7
        assert "ADX=15" in result.reason
        assert "volatility_breakout" in result.reason

    def test_trend_momentum_blocked_at_adx_18(self):
        ctx = {"df": adx18_df()}
        result = self.gate.evaluate(_signal(0.65, "trend_momentum"), ctx)
        assert ctx["regime"] == SIDEWAYS
        assert result.passed is False
        assert result.score == 0.0
        assert "trend_momentum" not in result.reason

    def test_sideways_ok_strategies_are_real_strategies(self):
        # Fanger tastefejl i konstanten — et navn der ikke findes i registeret ville
        # lydløst slå fixet fra.
        registered = {s.name for s in load_strategies().all()}
        assert SIDEWAYS_OK_STRATEGIES <= registered
