"""
Tests for time-stop (Ændring 4) — både backtest og live.

Positioner blev observeret holdt i op til 849 barer (~5 måneder) for
trend_momentum. Time-stop lukker en position til markedsprisen efter
trading.max_bars_held barer, men først når SL/TP ikke rammes på samme bar.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from backtest.runner import simulate_trade
from core.time_utils import utc_now
from strategies.base import Signal

CONFIG = {
    "trading": {"stake_amount": 5.0, "breakeven_trigger_pct": 0.5, "max_bars_held": 24},
    "risk_defaults": {
        "crypto": {"sl_pct": 10.0, "tp_pct": 20.0,
                   "atr_sl_multiplier": 2.0, "tp_rr_ratio": 2.0},
        "forex": {"sl_pct": 1.5, "tp_pct": 3.0,
                  "atr_sl_multiplier": 2.0, "tp_rr_ratio": 2.0},
        "gold": {"sl_pct": 3.0, "tp_pct": 6.0,
                 "atr_sl_multiplier": 2.0, "tp_rr_ratio": 2.0},
    },
}

ENGINE_CONFIG = {
    "trading": {"dry_run": True, "total_capital": 100.0, "stake_amount": 5.0,
                "max_open_trades": 4, "breakeven_trigger_pct": 0.5, "max_bars_held": 24},
}

FOUR_HOURS = 14400


def _signal(side: str = "long", sl=None, tp=None) -> Signal:
    return Signal("s", "BTC/USDT", side, 0.7, "4h", {}, sl_price=sl, tp_price=tp)


def _flat_future(n: int, close: float = 100.0) -> pd.DataFrame:
    """n barer der hverken rammer SL eller TP (prisen står stille)."""
    times = pd.date_range("2024-01-01", periods=n, freq="4h")
    return pd.DataFrame({
        "time": times, "open": [close] * n, "high": [close + 0.5] * n,
        "low": [close - 0.5] * n, "close": [close] * n,
    })


class TestBacktestTimeStop:
    def test_lukkes_efter_praecis_max_bars(self):
        future = _flat_future(60)
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), future, CONFIG)
        assert trade["reason"] == "time_stop"
        assert trade["bars_held"] == 24
        assert trade["exit_price"] == pytest.approx(100.0)

    def test_exit_price_er_baren_close(self):
        future = _flat_future(60)
        future.loc[24, "close"] = 104.0
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), future, CONFIG)
        assert trade["exit_price"] == pytest.approx(104.0)
        assert trade["pnl_pct"] == pytest.approx(4.0)

    def test_exit_time_er_baren_time(self):
        future = _flat_future(60)
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), future, CONFIG)
        assert trade["exit_time"] == future.iloc[24]["time"]

    def test_sl_paa_bar_5_vinder_over_time_stop(self):
        future = _flat_future(60)
        future.loc[5, "low"] = 88.0
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), future, CONFIG)
        assert trade["reason"] == "stop_loss"
        assert trade["bars_held"] == 5

    def test_tp_paa_samme_bar_som_time_stop_vinder(self):
        future = _flat_future(60)
        future.loc[24, ["high", "low"]] = [125.0, 100.5]  # låget rammes uden retrace
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), future, CONFIG)
        assert trade["reason"] == "take_profit"
        assert trade["exit_price"] == pytest.approx(120.0)

    def test_bar_der_baade_trigger_breakeven_og_retracerer_lukker_i_nul(self):
        """Konservativ intra-bar-antagelse: vi kender ikke rækkefølgen inde i en
        bar, så en bar der både passerer breakeven-triggeren og dykker under entry
        lukkes i nul — også selvom samme bars high nåede TP."""
        future = _flat_future(60)
        future.loc[24, "high"] = 125.0  # low = 99.5 < entry
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), future, CONFIG)
        assert trade["reason"] == "breakeven"
        assert trade["exit_price"] == pytest.approx(100.0)

    def test_kortere_data_end_max_bars_giver_end_of_data(self):
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), _flat_future(10), CONFIG)
        assert trade["reason"] == "end_of_data"

    def test_graensen_kan_konfigureres(self):
        config = {**CONFIG, "trading": {**CONFIG["trading"], "max_bars_held": 6}}
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), _flat_future(60), config)
        assert trade["reason"] == "time_stop"
        assert trade["bars_held"] == 6

    def test_nul_slaar_time_stop_fra(self):
        config = {**CONFIG, "trading": {**CONFIG["trading"], "max_bars_held": 0}}
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), _flat_future(60), config)
        assert trade["reason"] == "end_of_data"

    def test_short_lukkes_ogsaa(self):
        trade = simulate_trade(_signal("short", sl=110.0, tp=80.0), _flat_future(60), CONFIG)
        assert trade["reason"] == "time_stop"
        assert trade["bars_held"] == 24

    def test_time_stop_er_et_rigtigt_udfald_i_metrics(self):
        from backtest import metrics

        trade = simulate_trade(_signal(sl=90.0, tp=120.0), _flat_future(60), CONFIG)
        m = metrics.compute([trade])
        assert m["closed_trades"] == 1
        assert m["open_at_end_count"] == 0


class TestLiveTimeStop:
    async def _tracker(self, monkeypatch, tmp_path):
        from tests.fixtures.db import temp_db

        await temp_db(monkeypatch, tmp_path, "execution.position_tracker")
        from execution.position_tracker import PositionTracker

        return PositionTracker(ENGINE_CONFIG)

    async def _open(self, tracker, age_hours: float):
        trade = await tracker.open_position(
            _signal(), sl_price=90.0, tp_price=120.0, order_result={},
            current_price=100.0, gate_scores={},
        )
        trade.entry_time = utc_now() - timedelta(hours=age_hours)
        return trade

    @pytest.mark.asyncio
    async def test_gammel_position_lukkes_til_markedspris(self, monkeypatch, tmp_path):
        tracker = await self._tracker(monkeypatch, tmp_path)
        trade = await self._open(tracker, age_hours=96)  # 24 barer × 4h

        closed = await tracker.check_time_stop({"BTC/USDT": 103.0}, 24, FOUR_HOURS)

        assert [t.id for t in closed] == [trade.id]
        assert closed[0].exit_price == pytest.approx(103.0)
        assert closed[0].pnl_pct == pytest.approx(3.0)  # 0.05 stk × 3 USDT / 5 stake
        assert tracker.get_open_count() == 0

    @pytest.mark.asyncio
    async def test_ung_position_lukkes_ikke(self, monkeypatch, tmp_path):
        tracker = await self._tracker(monkeypatch, tmp_path)
        await self._open(tracker, age_hours=95)

        assert await tracker.check_time_stop({"BTC/USDT": 103.0}, 24, FOUR_HOURS) == []
        assert tracker.get_open_count() == 1

    @pytest.mark.asyncio
    async def test_symbol_uden_pris_springes_over(self, monkeypatch, tmp_path):
        tracker = await self._tracker(monkeypatch, tmp_path)
        await self._open(tracker, age_hours=200)

        assert await tracker.check_time_stop({}, 24, FOUR_HOURS) == []
        assert tracker.get_open_count() == 1

    @pytest.mark.asyncio
    async def test_nul_graense_slaar_time_stop_fra(self, monkeypatch, tmp_path):
        tracker = await self._tracker(monkeypatch, tmp_path)
        await self._open(tracker, age_hours=1000)

        assert await tracker.check_time_stop({"BTC/USDT": 103.0}, 0, FOUR_HOURS) == []
        assert tracker.get_open_count() == 1

    @pytest.mark.asyncio
    async def test_lukket_position_persisteres(self, monkeypatch, tmp_path):
        from tests.fixtures.db import temp_db

        session_maker = await temp_db(monkeypatch, tmp_path, "execution.position_tracker")
        from core.database import Trade
        from execution.position_tracker import PositionTracker

        tracker = PositionTracker(ENGINE_CONFIG)
        trade = await self._open(tracker, age_hours=96)
        await tracker.check_time_stop({"BTC/USDT": 103.0}, 24, FOUR_HOURS)

        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
            assert stored.status == "closed"
            assert stored.exit_price == pytest.approx(103.0)
