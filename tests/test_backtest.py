import pandas as pd

from backtest import metrics
from backtest.runner import simulate_trade
from strategies.base import Signal

CONFIG = {
    "trading": {"stake_amount": 5.0},
    "risk_defaults": {
        "crypto": {"sl_pct": 10.0, "tp_pct": 20.0},
        "forex": {"sl_pct": 1.5, "tp_pct": 3.0},
        "gold": {"sl_pct": 3.0, "tp_pct": 6.0},
    },
}


def _future(bars: list[tuple]) -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=len(bars), freq="4h")
    return pd.DataFrame(
        [(t, o, h, l, c) for t, (o, h, l, c) in zip(times, bars)],
        columns=["time", "open", "high", "low", "close"],
    )


class TestSimulateTrade:
    def test_long_take_profit(self):
        signal = Signal("s", "BTC/USDT", "long", 0.7, "4h", {}, sl_price=95.0, tp_price=110.0)
        future = _future([(100, 101, 99, 100), (105, 111, 104, 108)])
        trade = simulate_trade(signal, future, CONFIG)
        assert trade["reason"] == "take_profit"
        assert trade["exit_price"] == 110.0
        assert trade["pnl_pct"] == 10.0
        assert trade["pnl"] == 0.5  # 10% af 5 USDT

    def test_long_stop_loss(self):
        signal = Signal("s", "BTC/USDT", "long", 0.7, "4h", {}, sl_price=95.0, tp_price=110.0)
        future = _future([(100, 101, 99, 100), (98, 99, 94, 96)])
        trade = simulate_trade(signal, future, CONFIG)
        assert trade["reason"] == "stop_loss"
        assert trade["pnl_pct"] == -5.0

    def test_short_take_profit(self):
        signal = Signal("s", "BTC/USDT", "short", 0.7, "4h", {}, sl_price=105.0, tp_price=90.0)
        future = _future([(100, 101, 99, 100), (95, 96, 89, 91)])
        trade = simulate_trade(signal, future, CONFIG)
        assert trade["reason"] == "take_profit"
        assert trade["pnl_pct"] == 10.0

    def test_end_of_data_close(self):
        signal = Signal("s", "BTC/USDT", "long", 0.7, "4h", {}, sl_price=90.0, tp_price=120.0)
        future = _future([(100, 101, 99, 100), (102, 103, 101, 102)])
        trade = simulate_trade(signal, future, CONFIG)
        assert trade["reason"] == "end_of_data"
        assert trade["exit_price"] == 102.0

    def test_uses_config_defaults_when_no_chart_levels(self):
        signal = Signal("s", "EUR/USD", "long", 0.7, "4h", {})
        # entry 100, forex tp_pct=3% → tp=103
        future = _future([(100, 100, 100, 100), (102, 104, 101, 103)])
        trade = simulate_trade(signal, future, CONFIG)
        assert trade["reason"] == "take_profit"
        assert round(trade["exit_price"], 2) == 103.0


class TestMetrics:
    def test_empty(self):
        m = metrics.compute([])
        assert m["total_trades"] == 0
        assert m["win_rate"] == 0.0

    def test_basic_metrics(self):
        trades = [
            {"pnl": 2.0, "pnl_pct": 2.0},
            {"pnl": -1.0, "pnl_pct": -1.0},
            {"pnl": 3.0, "pnl_pct": 3.0},
            {"pnl": -1.0, "pnl_pct": -1.0},
        ]
        m = metrics.compute(trades)
        assert m["total_trades"] == 4
        assert m["wins"] == 2
        assert m["losses"] == 2
        assert m["win_rate"] == 50.0
        assert m["total_pnl"] == 3.0
        assert m["profit_factor"] == 2.5  # 5 profit / 2 loss

    def test_max_drawdown(self):
        # kumulativ: 2, -1, -3 → peak 2, trough -3 → dd = -5
        assert metrics.max_drawdown([2, -3, -2]) == -5

    def test_sharpe_is_float(self):
        trades = [
            {"pnl": 1.0, "pnl_pct": 1.0, "exit_time": pd.Timestamp("2024-01-01")},
            {"pnl": 2.0, "pnl_pct": 2.0, "exit_time": pd.Timestamp("2024-06-01")},
            {"pnl": -1.0, "pnl_pct": -1.0, "exit_time": pd.Timestamp("2024-12-01")},
        ]
        m = metrics.compute(trades)
        assert isinstance(m["sharpe"], float)
