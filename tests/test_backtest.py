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


class TestPnlFortegn:
    """Eksplicit dokumentation af PnL-formlen — særligt for shorts, hvor et
    prisfald er en gevinst. Beskytter mod fortegnsregressioner i simulate_trade."""

    def test_short_pnl_take_profit(self):
        # entry=100, tp=80 → prisen faldt 20% → +20%
        signal = Signal("s", "BTC/USDT", "short", 0.7, "4h", {}, sl_price=110.0, tp_price=80.0)
        future = _future([(100, 100, 100, 100), (95, 96, 79, 80)])
        trade = simulate_trade(signal, future, CONFIG)
        assert trade["reason"] == "take_profit"
        assert trade["exit_price"] == 80.0
        assert trade["pnl_pct"] == 20.0
        assert trade["pnl"] == 1.0  # 20% af 5 USDT

    def test_short_pnl_stop_loss(self):
        # entry=100, sl=110 → prisen steg 10% → -10%
        signal = Signal("s", "BTC/USDT", "short", 0.7, "4h", {}, sl_price=110.0, tp_price=80.0)
        future = _future([(100, 100, 100, 100), (105, 111, 104, 110)])
        trade = simulate_trade(signal, future, CONFIG)
        assert trade["reason"] == "stop_loss"
        assert trade["exit_price"] == 110.0
        assert trade["pnl_pct"] == -10.0
        assert trade["pnl"] == -0.5

    def test_short_pnl_end_of_data(self):
        # entry=100, sidste close=95 → prisen faldt 5% → +5%
        signal = Signal("s", "BTC/USDT", "short", 0.7, "4h", {}, sl_price=110.0, tp_price=80.0)
        future = _future([(100, 100, 100, 100), (98, 99, 94, 95)])
        trade = simulate_trade(signal, future, CONFIG)
        assert trade["reason"] == "end_of_data"
        assert trade["pnl_pct"] == 5.0

    def test_long_pnl_take_profit(self):
        # entry=100, tp=120 → +20%
        signal = Signal("s", "BTC/USDT", "long", 0.7, "4h", {}, sl_price=90.0, tp_price=120.0)
        future = _future([(100, 100, 100, 100), (110, 121, 109, 120)])
        trade = simulate_trade(signal, future, CONFIG)
        assert trade["reason"] == "take_profit"
        assert trade["pnl_pct"] == 20.0
        assert trade["pnl"] == 1.0

    def test_long_pnl_stop_loss(self):
        signal = Signal("s", "BTC/USDT", "long", 0.7, "4h", {}, sl_price=90.0, tp_price=120.0)
        future = _future([(100, 100, 100, 100), (95, 96, 89, 90)])
        trade = simulate_trade(signal, future, CONFIG)
        assert trade["reason"] == "stop_loss"
        assert trade["pnl_pct"] == -10.0

    def test_long_og_short_er_spejlvendte(self):
        """Samme prisbevægelse skal give modsat fortegn for long og short."""
        bars = [(100, 100, 100, 100), (98, 99, 94, 95)]
        long_trade = simulate_trade(
            Signal("s", "BTC/USDT", "long", 0.7, "4h", {}, sl_price=80.0, tp_price=120.0),
            _future(bars), CONFIG)
        short_trade = simulate_trade(
            Signal("s", "BTC/USDT", "short", 0.7, "4h", {}, sl_price=120.0, tp_price=80.0),
            _future(bars), CONFIG)
        assert long_trade["pnl_pct"] == -short_trade["pnl_pct"]


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

    def test_end_of_data_udelades_fra_win_rate(self):
        # 2 rigtige wins + 1 uafsluttet tab → 100%, ikke 66%
        trades = [
            {"pnl": 2.0, "pnl_pct": 2.0, "reason": "take_profit"},
            {"pnl": 3.0, "pnl_pct": 3.0, "reason": "take_profit"},
            {"pnl": -5.0, "pnl_pct": -5.0, "reason": "end_of_data"},
        ]
        m = metrics.compute(trades)
        assert m["win_rate"] == 100.0
        assert m["wins"] == 2
        assert m["losses"] == 0

    def test_end_of_data_tælles_men_indgår_ikke_i_metrics(self):
        trades = [
            {"pnl": 2.0, "pnl_pct": 2.0, "reason": "take_profit"},
            {"pnl": 3.0, "pnl_pct": 3.0, "reason": "take_profit"},
            {"pnl": -5.0, "pnl_pct": -5.0, "reason": "end_of_data"},
        ]
        m = metrics.compute(trades)
        assert m["total_trades"] == 3          # det fulde billede
        assert m["closed_trades"] == 2         # grundlaget for metrics
        assert m["open_at_end_count"] == 1
        assert m["total_pnl"] == 5.0           # -5 fra den uafsluttede er ude
        assert m["avg_pnl_pct"] == 2.5

    def test_drawdown_ignorerer_uafsluttet_trade(self):
        # Den uafsluttede -10% ville ellers dominere drawdown'en.
        trades = [
            {"pnl": 2.0, "pnl_pct": 2.0, "reason": "take_profit"},
            {"pnl": -1.0, "pnl_pct": -1.0, "reason": "stop_loss"},
            {"pnl": -10.0, "pnl_pct": -10.0, "reason": "end_of_data"},
        ]
        m = metrics.compute(trades)
        assert m["max_drawdown_pct"] == -1.0

    def test_sharpe_ignorerer_uafsluttet_trade(self):
        real = [
            {"pnl": 1.0, "pnl_pct": 1.0, "reason": "take_profit",
             "exit_time": pd.Timestamp("2024-01-01")},
            {"pnl": 2.0, "pnl_pct": 2.0, "reason": "take_profit",
             "exit_time": pd.Timestamp("2024-06-01")},
            {"pnl": -1.0, "pnl_pct": -1.0, "reason": "stop_loss",
             "exit_time": pd.Timestamp("2024-12-01")},
        ]
        unfinished = {"pnl": -30.0, "pnl_pct": -30.0, "reason": "end_of_data",
                      "exit_time": pd.Timestamp("2025-06-01")}
        assert metrics.compute(real)["sharpe"] == metrics.compute(real + [unfinished])["sharpe"]

    def test_kun_uafsluttede_trades_giver_nul_metrics(self):
        m = metrics.compute([{"pnl": 4.0, "pnl_pct": 4.0, "reason": "end_of_data"}])
        assert m["total_trades"] == 1
        assert m["closed_trades"] == 0
        assert m["open_at_end_count"] == 1
        assert m["win_rate"] == 0.0
        assert m["total_pnl"] == 0.0

    def test_tom_liste_har_de_nye_felter(self):
        m = metrics.compute([])
        assert m["closed_trades"] == 0
        assert m["open_at_end_count"] == 0

    def test_time_stop_tæller_som_afsluttet(self):
        m = metrics.compute([{"pnl": -1.0, "pnl_pct": -1.0, "reason": "time_stop"}])
        assert m["closed_trades"] == 1
        assert m["open_at_end_count"] == 0

    def test_breakeven_tæller_som_afsluttet(self):
        m = metrics.compute([{"pnl": 0.0, "pnl_pct": 0.0, "reason": "breakeven"}])
        assert m["closed_trades"] == 1

    def test_sharpe_zero_variance(self):
        # reversal_context × XAU/USD gav 9 identiske -3.0%-tab; std blev
        # 3.7e-18 i stedet for 0, og sharpe eksploderede til -2.2e16.
        trades = [
            {"pnl": -3.0, "pnl_pct": -3.0,
             "exit_time": pd.Timestamp("2024-01-01") + pd.Timedelta(days=30 * i)}
            for i in range(9)
        ]
        m = metrics.compute(trades)
        assert m["sharpe"] == 0.0
