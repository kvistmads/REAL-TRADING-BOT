from strategies.reversal_context import ReversalContext
from tests.fixtures.ohlcv import (
    rev_bullish_long,
    rev_low_volume,
    rev_no_divergence,
    rev_too_short,
    rev_wrong_trend_context,
)

META_KEYS = {
    "rsi_first_swing", "rsi_second_swing", "rsi_delta",
    "price_first_swing", "price_second_swing", "ema_50", "ema_200",
    "trend_context", "volume", "volume_ma_20", "volume_ratio",
    "divergence_strength", "volume_strength",
}


class TestReversalContext:
    def setup_method(self):
        self.strategy = ReversalContext()

    def test_bullish_divergence_in_downtrend_with_volume_gives_long(self):
        sig = self.strategy.generate_signal(rev_bullish_long(), "BTC/USDT")
        assert sig is not None
        assert sig.side == "long"
        assert sig.strategy_id == "reversal_context"
        assert 0.65 <= sig.confidence <= 1.0
        # divergens: lower low i pris, higher low i RSI
        assert sig.metadata["price_second_swing"] < sig.metadata["price_first_swing"]
        assert sig.metadata["rsi_second_swing"] > sig.metadata["rsi_first_swing"]
        assert sig.metadata["volume_ratio"] > 1.2
        assert META_KEYS.issubset(sig.metadata.keys())

    def test_wrong_trend_context_blocks_signal(self):
        # Gyldig divergens men EMA50>EMA200 → kontekst-gate afviser.
        assert self.strategy.generate_signal(rev_wrong_trend_context(), "BTC/USDT") is None

    def test_insufficient_volume_blocks_signal(self):
        assert self.strategy.generate_signal(rev_low_volume(), "BTC/USDT") is None

    def test_no_divergence_returns_none(self):
        assert self.strategy.generate_signal(rev_no_divergence(), "BTC/USDT") is None

    def test_too_short_returns_none(self):
        assert self.strategy.generate_signal(rev_too_short(), "BTC/USDT") is None
