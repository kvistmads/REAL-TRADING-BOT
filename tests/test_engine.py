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


class TestConfigParams:
    """`strategies.params.<id>` skal nå frem til generate_signal.

    Nøglen er hvor reflection-loopets auto-apply skriver (reflection/applier.py).
    Indtil Ændring 11 læste engine kun A/B-arm-params, så alt der stod under
    strategies.params var et stille no-op — botten kørte videre på klasse-defaults.
    """

    def _engine(self, params: dict | None) -> TradingEngine:
        strategies = dict(BASE_CONFIG["strategies"])
        if params is not None:
            strategies["params"] = params
        return TradingEngine({**BASE_CONFIG, "strategies": strategies})

    def test_manglende_params_sektion_giver_tom_dict(self):
        assert self._engine(None)._config_params("volatility_breakout") == {}

    def test_ukendt_strategi_giver_tom_dict(self):
        engine = self._engine({"volatility_breakout": {"squeeze_percentile": 25}})
        assert engine._config_params("trend_momentum") == {}

    def test_params_hentes_pr_strategi(self):
        engine = self._engine({
            "volatility_breakout": {"squeeze_percentile": 25, "min_volume_ratio": 1.2},
            "trend_momentum": {"cross_strength_scale": 0.12},
        })
        assert engine._config_params("volatility_breakout") == {
            "squeeze_percentile": 25, "min_volume_ratio": 1.2}
        assert engine._config_params("trend_momentum") == {"cross_strength_scale": 0.12}

    def test_kalderen_kan_ikke_mutere_config(self):
        engine = self._engine({"volatility_breakout": {"squeeze_percentile": 25}})
        engine._config_params("volatility_breakout")["squeeze_percentile"] = 99
        assert engine._config_params("volatility_breakout") == {"squeeze_percentile": 25}

    @pytest.mark.asyncio
    async def test_params_naar_frem_til_generate_signal(self, monkeypatch):
        import pandas as pd

        from tests.fixtures.engine import CONFIG, fake_engine

        seen: list[dict] = []

        class RecordingStrategy:
            name = "volatility_breakout"
            min_confidence = 0.65

            def generate_signal(self, df, symbol, params=None):
                seen.append(dict(params or {}))
                return None

        bars = {"BTC/USDT": pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=120, freq="4h"),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
            "volume": 1000.0,
        })}
        config = {**CONFIG, "symbols": list(bars), "strategies": {
            "enabled": ["volatility_breakout"], "min_confidence": 0.45,
            "params": {"volatility_breakout": {
                "squeeze_percentile": 25, "min_volume_ratio": 1.2}},
        }}
        engine = fake_engine(monkeypatch, strategies=[RecordingStrategy()],
                             bars=bars, config=config)
        await engine._tick()

        assert seen == [{"squeeze_percentile": 25, "min_volume_ratio": 1.2}]

    @pytest.mark.asyncio
    async def test_ab_arm_vinder_over_config(self, monkeypatch):
        """Arm B's ene parameter lægges oven på config — resten af config består."""
        import pandas as pd

        from core import engine as engine_mod
        from execution.ab_router import ArmAssignment
        from tests.fixtures.engine import CONFIG, fake_engine

        seen: list[dict] = []

        class RecordingStrategy:
            name = "volatility_breakout"
            min_confidence = 0.65

            def generate_signal(self, df, symbol, params=None):
                seen.append(dict(params or {}))
                return None

        monkeypatch.setattr(
            engine_mod, "get_assignment",
            lambda sid: ArmAssignment(arm="B", params={"squeeze_percentile": 5},
                                      experiment_id=1),
        )
        bars = {"BTC/USDT": pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=120, freq="4h"),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
            "volume": 1000.0,
        })}
        config = {**CONFIG, "symbols": list(bars), "strategies": {
            "enabled": ["volatility_breakout"], "min_confidence": 0.45,
            "params": {"volatility_breakout": {
                "squeeze_percentile": 25, "min_volume_ratio": 1.2}},
        }}
        engine = fake_engine(monkeypatch, strategies=[RecordingStrategy()],
                             bars=bars, config=config)
        await engine._tick()

        assert seen == [{"squeeze_percentile": 5, "min_volume_ratio": 1.2}]
