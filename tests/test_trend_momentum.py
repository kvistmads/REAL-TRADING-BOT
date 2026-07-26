from strategies.base import Signal
from strategies.trend_momentum import TrendMomentum
from tests.fixtures.ohlcv import (
    tm_long_rsi_too_high,
    tm_long_signal,
    tm_no_fresh_cross,
    tm_short_signal,
    tm_too_short,
)

META_KEYS = {
    "ema_50", "ema_200", "macd", "macd_signal", "macd_hist",
    "rsi", "atr", "trend_strength", "macd_strength", "rsi_room",
}


class TestTrendMomentum:
    def setup_method(self):
        self.strategy = TrendMomentum()

    def test_golden_cross_fresh_macd_mid_rsi_gives_long(self):
        sig = self.strategy.generate_signal(tm_long_signal(), "BTC/USDT")
        assert sig is not None
        assert sig.side == "long"
        assert sig.strategy_id == "trend_momentum"
        assert 0.65 <= sig.confidence <= 1.0
        assert sig.metadata["rsi"] < 60
        assert META_KEYS.issubset(sig.metadata.keys())

    def test_high_rsi_blocks_long(self):
        assert self.strategy.generate_signal(tm_long_rsi_too_high(), "BTC/USDT") is None

    def test_death_cross_fresh_macd_gives_short(self):
        sig = self.strategy.generate_signal(tm_short_signal(), "BTC/USDT")
        assert sig is not None
        assert sig.side == "short"
        assert 0.65 <= sig.confidence <= 1.0
        assert sig.metadata["rsi"] > 40

    def test_too_short_returns_none_without_exception(self):
        assert self.strategy.generate_signal(tm_too_short(), "BTC/USDT") is None

    def test_no_fresh_cross_returns_none(self):
        assert self.strategy.generate_signal(tm_no_fresh_cross(), "BTC/USDT") is None

    def test_signal_carries_no_sl_tp(self):
        sig = self.strategy.generate_signal(tm_long_signal(), "BTC/USDT")
        assert isinstance(sig, Signal)
        assert sig.sl_price is None and sig.tp_price is None
