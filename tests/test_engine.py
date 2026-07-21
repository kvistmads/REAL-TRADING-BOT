import pytest

from core.engine import TradingEngine
from strategies.base import BaseStrategy, Signal

BASE_CONFIG = {
    "exchange": {"name": "binance", "sandbox": True},
    "trading": {
        "dry_run": True,
        "total_capital": 100.0,
        "stake_amount": 5.0,
        "max_open_trades": 4,
        "leverage": 1,
    },
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "timeframes": {"primary": "4h", "entry": "1h"},
    "strategies": {"enabled": ["rsi_divergence"], "min_confidence": 0.60},
    "gates": {
        "confluence": {"enabled": False},
        "risk": {"enabled": True, "max_position_pct": 5.0, "max_daily_loss_pct": 3.0, "blocking": True},
    },
    "risk_defaults": {
        "crypto": {"sl_pct": 10.0, "tp_pct": 20.0},
        "forex": {"sl_pct": 1.5, "tp_pct": 3.0},
        "gold": {"sl_pct": 3.0, "tp_pct": 6.0},
    },
}


class TestResolveSlTp:
    def setup_method(self):
        self.engine = TradingEngine(BASE_CONFIG)

    def _signal(self, symbol: str, side: str, sl=None, tp=None) -> Signal:
        return Signal(
            strategy_id="test",
            symbol=symbol,
            side=side,
            confidence=0.70,
            timeframe="4h",
            metadata={},
            sl_price=sl,
            tp_price=tp,
        )

    def test_crypto_long_uses_config_defaults(self):
        sl, tp = self.engine._resolve_sl_tp(self._signal("BTC/USDT", "long"), 50000.0)
        assert sl == pytest.approx(50000 * 0.90, rel=1e-6)
        assert tp == pytest.approx(50000 * 1.20, rel=1e-6)

    def test_crypto_short_uses_config_defaults(self):
        sl, tp = self.engine._resolve_sl_tp(self._signal("BTC/USDT", "short"), 50000.0)
        assert sl == pytest.approx(50000 * 1.10, rel=1e-6)
        assert tp == pytest.approx(50000 * 0.80, rel=1e-6)

    def test_forex_long_uses_config_defaults(self):
        sl, tp = self.engine._resolve_sl_tp(self._signal("EUR/USD", "long"), 1.10)
        assert sl == pytest.approx(1.10 * (1 - 0.015), rel=1e-6)
        assert tp == pytest.approx(1.10 * (1 + 0.030), rel=1e-6)

    def test_gold_short_uses_config_defaults(self):
        sl, tp = self.engine._resolve_sl_tp(self._signal("XAU/USD", "short"), 2000.0)
        assert sl == pytest.approx(2000.0 * 1.030, rel=1e-6)   # sl_pct=3%
        assert tp == pytest.approx(2000.0 * 0.940, rel=1e-6)   # tp_pct=6%

    def test_chart_based_sl_tp_takes_priority(self):
        signal = self._signal("BTC/USDT", "long", sl=45000.0, tp=60000.0)
        sl, tp = self.engine._resolve_sl_tp(signal, 50000.0)
        assert sl == 45000.0
        assert tp == 60000.0

    def test_chart_based_sl_tp_overrides_for_forex(self):
        signal = self._signal("EUR/USD", "short", sl=1.12, tp=1.07)
        sl, tp = self.engine._resolve_sl_tp(signal, 1.10)
        assert sl == 1.12
        assert tp == 1.07


class TestAssetClass:
    def test_btc_is_crypto(self):
        assert BaseStrategy.get_asset_class("BTC/USDT") == "crypto"

    def test_eth_is_crypto(self):
        assert BaseStrategy.get_asset_class("ETH/USDT") == "crypto"

    def test_eurusd_is_forex(self):
        assert BaseStrategy.get_asset_class("EUR/USD") == "forex"

    def test_gbpusd_is_forex(self):
        assert BaseStrategy.get_asset_class("GBP/USD") == "forex"

    def test_xauusd_is_gold(self):
        assert BaseStrategy.get_asset_class("XAU/USD") == "gold"
