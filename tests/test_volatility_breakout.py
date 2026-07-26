from strategies.volatility_breakout import VolatilityBreakout
from tests.fixtures.ohlcv import (
    vb_long_breakout,
    vb_low_volume,
    vb_macd_disagree,
    vb_no_squeeze,
    vb_too_short,
)

META_KEYS = {
    "bb_width", "bb_width_percentile", "squeeze_active", "resistance_level",
    "support_level", "breakout_level", "volume", "volume_ma_20", "volume_ratio",
    "macd_hist", "atr", "squeeze_intensity", "volume_strength", "macd_strength",
    "suggested_take_profit", "suggested_stop_loss",
}


class TestVolatilityBreakout:
    def setup_method(self):
        self.strategy = VolatilityBreakout()

    def test_squeeze_breakout_with_volume_and_macd_gives_long(self):
        sig = self.strategy.generate_signal(vb_long_breakout(), "BTC/USDT")
        assert sig is not None
        assert sig.side == "long"
        assert sig.strategy_id == "volatility_breakout"
        assert 0.65 <= sig.confidence <= 1.0
        assert sig.metadata["volume_ratio"] > 1.5
        assert sig.metadata["macd_hist"] > 0
        assert META_KEYS.issubset(sig.metadata.keys())
        # measured-move: TP over breakout, SL under breakout for long
        assert sig.metadata["suggested_take_profit"] > sig.metadata["breakout_level"]
        assert sig.metadata["suggested_stop_loss"] < sig.metadata["breakout_level"]

    def test_insufficient_volume_blocks_signal(self):
        assert self.strategy.generate_signal(vb_low_volume(), "BTC/USDT") is None

    def test_no_prior_squeeze_returns_none(self):
        assert self.strategy.generate_signal(vb_no_squeeze(), "BTC/USDT") is None

    def test_macd_disagreeing_with_direction_blocks_signal(self):
        assert self.strategy.generate_signal(vb_macd_disagree(), "BTC/USDT") is None

    def test_too_short_returns_none(self):
        assert self.strategy.generate_signal(vb_too_short(), "BTC/USDT") is None
