import pytest

from gates.base import GateResult
from gates.risk import RiskGate
from strategies.base import Signal


BASE_CONFIG = {
    "trading": {
        "dry_run": True,
        "total_capital": 100.0,
        "stake_amount": 5.0,
        "max_open_trades": 4,
        "leverage": 1,
    },
    "gates": {
        "risk": {
            "enabled": True,
            "max_position_pct": 5.0,
            "max_daily_loss_pct": 3.0,
            "blocking": True,
        }
    },
    "risk_defaults": {
        "crypto": {"sl_pct": 10.0, "tp_pct": 20.0},
        "forex": {"sl_pct": 1.5, "tp_pct": 3.0},
        "gold": {"sl_pct": 3.0, "tp_pct": 6.0},
    },
}

SIGNAL = Signal(
    strategy_id="rsi_divergence",
    symbol="BTC/USDT",
    side="long",
    confidence=0.70,
    timeframe="4h",
    metadata={},
)

BASE_CONTEXT = {
    "current_price": 50000.0,
    "open_trades_count": 0,
    "daily_pnl": 0.0,
    "account_balance": 100.0,
    "asset_class": "crypto",
}


class TestRiskGate:
    def setup_method(self):
        self.gate = RiskGate(BASE_CONFIG)

    def test_passes_under_normal_conditions(self):
        result = self.gate.evaluate(SIGNAL, BASE_CONTEXT)
        assert isinstance(result, GateResult)
        assert result.passed is True
        assert result.gate_name == "risk"
        assert 0.0 <= result.score <= 1.0
        assert isinstance(result.reason, str)

    def test_blocks_when_too_many_open_trades(self):
        ctx = {**BASE_CONTEXT, "open_trades_count": 4}
        result = self.gate.evaluate(SIGNAL, ctx)
        assert result.passed is False
        assert "4" in result.reason

    def test_blocks_when_daily_loss_exceeded(self):
        ctx = {**BASE_CONTEXT, "daily_pnl": -4.0}  # > 3% af 100
        result = self.gate.evaluate(SIGNAL, ctx)
        assert result.passed is False
        assert "tab" in result.reason.lower()

    def test_gate_result_always_populated(self):
        for ctx in [
            BASE_CONTEXT,
            {**BASE_CONTEXT, "open_trades_count": 10},
            {**BASE_CONTEXT, "daily_pnl": -99.0},
        ]:
            result = self.gate.evaluate(SIGNAL, ctx)
            assert result.gate_name == "risk"
            assert isinstance(result.passed, bool)
            assert isinstance(result.score, float)
            assert isinstance(result.reason, str)
            assert len(result.reason) > 0

    def test_score_is_float_between_0_and_1(self):
        result = self.gate.evaluate(SIGNAL, BASE_CONTEXT)
        assert 0.0 <= result.score <= 1.0

    def test_blocks_on_position_size_too_large(self):
        # Stake=5, balance=50 → 10% > max_position_pct 5%
        ctx = {**BASE_CONTEXT, "account_balance": 50.0}
        result = self.gate.evaluate(SIGNAL, ctx)
        assert result.passed is False
