"""
Tests for ATR-baserede stops + breakeven (Ændring 1).

SL/TP sættes efter markedets aktuelle volatilitet frem for faste procenter:
SL-afstand = atr_sl_multiplier × ATR(14), TP-afstand = tp_rr_ratio × SL-afstand.
Faste sl_pct/tp_pct er kun fallback når ATR ikke findes. Breakeven flytter SL til
entry når prisen har bevæget sig halvvejs mod TP — samme formel i backtest og live.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backtest.runner import _resolve_sl_tp, simulate_trade
from core.engine import TradingEngine
from execution.position_tracker import compute_breakeven_trigger
from strategies.base import Signal

CONFIG = {
    "trading": {"stake_amount": 5.0, "breakeven_trigger_pct": 0.5},
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
    **CONFIG,
    "exchange": {"name": "binance", "sandbox": True},
    "trading": {"dry_run": True, "total_capital": 100.0, "stake_amount": 5.0,
                "max_open_trades": 4, "leverage": 1, "breakeven_trigger_pct": 0.5},
    "symbols": ["BTC/USDT"],
    "timeframes": {"primary": "4h", "entry": "1h"},
    "strategies": {"enabled": [], "min_confidence": 0.45},
    "gates": {"confluence": {"enabled": False}, "risk": {"enabled": False},
              "regime": {"enabled": False}},
}


def _signal(symbol: str = "BTC/USDT", side: str = "long", sl=None, tp=None) -> Signal:
    return Signal("s", symbol, side, 0.7, "4h", {}, sl_price=sl, tp_price=tp)


def _future(bars: list[tuple], atr: float | None = None) -> pd.DataFrame:
    """bars: (open, high, low, close). atr=None → ingen atr_14-kolonne (fallback)."""
    times = pd.date_range("2024-01-01", periods=len(bars), freq="4h")
    df = pd.DataFrame(
        [(t, o, h, low, c) for t, (o, h, low, c) in zip(times, bars)],
        columns=["time", "open", "high", "low", "close"],
    )
    if atr is not None:
        df["atr_14"] = atr
    return df


class TestResolveSlTpMedATR:
    def test_long_bruger_atr_afstande(self):
        # entry=100, ATR=2 → SL = 100 - 2×2 = 96, TP = 100 + 2×(2×2) = 108
        sl, tp = _resolve_sl_tp(_signal(), 100.0, CONFIG, atr=2.0)
        assert sl == pytest.approx(96.0)
        assert tp == pytest.approx(108.0)

    def test_short_bruger_atr_afstande(self):
        sl, tp = _resolve_sl_tp(_signal(side="short"), 100.0, CONFIG, atr=2.0)
        assert sl == pytest.approx(104.0)
        assert tp == pytest.approx(92.0)

    def test_rr_ratio_giver_2_til_1(self):
        sl, tp = _resolve_sl_tp(_signal(), 100.0, CONFIG, atr=1.5)
        assert (tp - 100.0) == pytest.approx(2.0 * (100.0 - sl))

    def test_atr_none_falder_tilbage_til_faste_procenter(self):
        sl, tp = _resolve_sl_tp(_signal(), 100.0, CONFIG, atr=None)
        assert sl == pytest.approx(90.0)    # sl_pct 10%
        assert tp == pytest.approx(120.0)   # tp_pct 20%

    def test_atr_nul_falder_tilbage(self):
        sl, tp = _resolve_sl_tp(_signal(), 100.0, CONFIG, atr=0.0)
        assert sl == pytest.approx(90.0)

    def test_atr_nan_falder_tilbage(self):
        sl, tp = _resolve_sl_tp(_signal(), 100.0, CONFIG, atr=float("nan"))
        assert sl == pytest.approx(90.0)

    def test_chart_niveauer_vinder_over_atr(self):
        sl, tp = _resolve_sl_tp(_signal(sl=95.0, tp=110.0), 100.0, CONFIG, atr=2.0)
        assert (sl, tp) == (95.0, 110.0)

    def test_forex_bruger_egen_multiplier(self):
        sl, tp = _resolve_sl_tp(_signal("EUR/USD"), 1.10, CONFIG, atr=0.002)
        assert sl == pytest.approx(1.096)
        assert tp == pytest.approx(1.108)


class TestSimulateTradeMedATR:
    def test_atr_hentes_fra_udfoerelsesbaren(self):
        # entry=100, ATR=2 → TP=108. Bar 2 rammer 108.
        future = _future([(100, 100, 100, 100), (104, 109, 103, 108)], atr=2.0)
        trade = simulate_trade(_signal(), future, CONFIG)
        assert trade["reason"] == "take_profit"
        assert trade["exit_price"] == pytest.approx(108.0)

    def test_uden_atr_kolonne_bruges_faste_procenter(self):
        # Ingen atr_14 → TP=120, som ikke rammes → end_of_data
        future = _future([(100, 100, 100, 100), (104, 109, 103, 108)])
        trade = simulate_trade(_signal(), future, CONFIG)
        assert trade["reason"] == "end_of_data"

    def test_short_stop_loss_paa_atr_afstand(self):
        # short entry=100, ATR=2 → SL=104
        future = _future([(100, 100, 100, 100), (101, 105, 100, 104)], atr=2.0)
        trade = simulate_trade(_signal(side="short"), future, CONFIG)
        assert trade["reason"] == "stop_loss"
        assert trade["exit_price"] == pytest.approx(104.0)
        assert trade["pnl_pct"] == pytest.approx(-4.0)


class TestBreakeven:
    def test_aktiveres_ved_halvvejs_til_tp(self):
        # entry=100, sl=90, tp=120 → trigger=110. Bar 1 rammer 110 og falder
        # senere til 95: uden breakeven ville tradet stadig være åbent.
        future = _future([(100, 100, 100, 100), (105, 111, 104, 110), (108, 109, 94, 95)])
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), future, CONFIG)
        assert trade["breakeven_activated"] is True
        assert trade["reason"] == "breakeven"
        assert trade["exit_price"] == pytest.approx(100.0)
        assert trade["pnl_pct"] == pytest.approx(0.0)

    def test_short_breakeven(self):
        # short entry=100, sl=110, tp=80 → trigger=90.
        future = _future([(100, 100, 100, 100), (95, 96, 89, 90), (92, 106, 91, 105)])
        trade = simulate_trade(_signal(side="short", sl=110.0, tp=80.0), future, CONFIG)
        assert trade["breakeven_activated"] is True
        assert trade["reason"] == "breakeven"
        assert trade["pnl_pct"] == pytest.approx(0.0)

    def test_ikke_aktiveret_under_trigger(self):
        future = _future([(100, 100, 100, 100), (102, 105, 101, 104), (100, 101, 89, 90)])
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), future, CONFIG)
        assert trade["breakeven_activated"] is False
        assert trade["reason"] == "stop_loss"
        assert trade["exit_price"] == pytest.approx(90.0)

    def test_tp_rammes_stadig_efter_breakeven(self):
        future = _future([(100, 100, 100, 100), (105, 121, 104, 120)])
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), future, CONFIG)
        assert trade["reason"] == "take_profit"
        assert trade["breakeven_activated"] is True

    def test_trigger_pct_kan_konfigureres(self):
        config = {**CONFIG, "trading": {**CONFIG["trading"], "breakeven_trigger_pct": 0.9}}
        # trigger = 100 + 0.9×20 = 118 → bar 1 (high 111) aktiverer ikke længere
        future = _future([(100, 100, 100, 100), (105, 111, 104, 110), (108, 109, 94, 95)])
        trade = simulate_trade(_signal(sl=90.0, tp=120.0), future, config)
        assert trade["breakeven_activated"] is False
        assert trade["reason"] == "end_of_data"

    def test_trigger_formel_er_delt_med_live(self):
        """Backtest og live skal flytte stoppet præcis samme sted."""
        from backtest.runner import _breakeven_trigger

        assert _breakeven_trigger("long", 100.0, 120.0, 0.5) == compute_breakeven_trigger(
            "long", 100.0, 120.0, 0.5
        )
        assert _breakeven_trigger("short", 100.0, 80.0, 0.5) == compute_breakeven_trigger(
            "short", 100.0, 80.0, 0.5
        )

    def test_deaktiveret_naar_pct_er_nul(self):
        assert compute_breakeven_trigger("long", 100.0, 120.0, 0.0) is None


class TestEngineResolveSlTp:
    def setup_method(self):
        self.engine = TradingEngine(ENGINE_CONFIG)

    def _df(self, atr: float | None) -> pd.DataFrame:
        df = pd.DataFrame({"close": [100.0, 100.0]})
        if atr is not None:
            df["atr_14"] = [atr, atr]
        return df

    def test_bruger_atr_fra_seneste_bar(self):
        sl, tp = self.engine._resolve_sl_tp(_signal(), 100.0, df=self._df(2.0))
        assert sl == pytest.approx(96.0)
        assert tp == pytest.approx(108.0)

    def test_short_med_atr(self):
        sl, tp = self.engine._resolve_sl_tp(_signal(side="short"), 100.0, df=self._df(2.0))
        assert sl == pytest.approx(104.0)
        assert tp == pytest.approx(92.0)

    def test_uden_df_falder_tilbage_til_procenter(self):
        sl, tp = self.engine._resolve_sl_tp(_signal(), 100.0)
        assert sl == pytest.approx(90.0)
        assert tp == pytest.approx(120.0)

    def test_df_uden_atr_kolonne_falder_tilbage(self):
        sl, tp = self.engine._resolve_sl_tp(_signal(), 100.0, df=self._df(None))
        assert sl == pytest.approx(90.0)

    def test_nan_atr_falder_tilbage(self):
        sl, tp = self.engine._resolve_sl_tp(_signal(), 100.0, df=self._df(float("nan")))
        assert sl == pytest.approx(90.0)

    def test_engine_og_backtest_giver_samme_niveauer(self):
        """Non-negotiable: live må ikke sætte andre stops end backtesten."""
        live = self.engine._resolve_sl_tp(_signal(), 100.0, df=self._df(2.0))
        bt = _resolve_sl_tp(_signal(), 100.0, CONFIG, atr=2.0)
        assert live == pytest.approx(bt)


class TestLiveBreakeven:
    """PositionTracker-siden: trigger beregnes ved åbning, SL flyttes ved hit."""

    async def _tracker(self, monkeypatch, tmp_path):
        from tests.fixtures.db import temp_db

        await temp_db(monkeypatch, tmp_path, "execution.position_tracker")
        from execution.position_tracker import PositionTracker

        return PositionTracker(ENGINE_CONFIG)

    async def _open(self, tracker, side: str = "long", tp: float = 120.0):
        return await tracker.open_position(
            _signal(side=side), sl_price=90.0 if side == "long" else 110.0,
            tp_price=tp, order_result={}, current_price=100.0, gate_scores={},
        )

    @pytest.mark.asyncio
    async def test_trigger_gemmes_ved_aabning(self, monkeypatch, tmp_path):
        tracker = await self._tracker(monkeypatch, tmp_path)
        trade = await self._open(tracker)
        assert trade.breakeven_trigger == pytest.approx(110.0)  # 100 + 0.5×20

    @pytest.mark.asyncio
    async def test_sl_flyttes_til_entry_ved_trigger(self, monkeypatch, tmp_path):
        tracker = await self._tracker(monkeypatch, tmp_path)
        trade = await self._open(tracker)

        activated = await tracker.check_breakeven({"BTC/USDT": 111.0})

        assert [t.id for t in activated] == [trade.id]
        assert trade.sl_price == pytest.approx(100.0)
        assert tracker.is_breakeven_activated(trade.id) is True

    @pytest.mark.asyncio
    async def test_sl_flyttes_ikke_under_trigger(self, monkeypatch, tmp_path):
        tracker = await self._tracker(monkeypatch, tmp_path)
        trade = await self._open(tracker)

        assert await tracker.check_breakeven({"BTC/USDT": 105.0}) == []
        assert trade.sl_price == pytest.approx(90.0)

    @pytest.mark.asyncio
    async def test_short_trigger_er_under_entry(self, monkeypatch, tmp_path):
        tracker = await self._tracker(monkeypatch, tmp_path)
        trade = await self._open(tracker, side="short", tp=80.0)
        assert trade.breakeven_trigger == pytest.approx(90.0)

        await tracker.check_breakeven({"BTC/USDT": 89.0})

        assert trade.sl_price == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_aktiveres_kun_en_gang(self, monkeypatch, tmp_path):
        tracker = await self._tracker(monkeypatch, tmp_path)
        await self._open(tracker)

        assert len(await tracker.check_breakeven({"BTC/USDT": 111.0})) == 1
        assert await tracker.check_breakeven({"BTC/USDT": 112.0}) == []

    @pytest.mark.asyncio
    async def test_ny_sl_persisteres_i_db(self, monkeypatch, tmp_path):
        from tests.fixtures.db import temp_db

        session_maker = await temp_db(monkeypatch, tmp_path, "execution.position_tracker")
        from core.database import Trade
        from execution.position_tracker import PositionTracker

        tracker = PositionTracker(ENGINE_CONFIG)
        trade = await self._open(tracker)
        await tracker.check_breakeven({"BTC/USDT": 111.0})

        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
            assert stored.sl_price == pytest.approx(100.0)
            assert stored.breakeven_trigger == pytest.approx(110.0)

    @pytest.mark.asyncio
    async def test_breakeven_lukker_naer_entry_i_stedet_for_paa_gammelt_sl(
        self, monkeypatch, tmp_path
    ):
        """Efter aktivering lukkes tradet ved entry i stedet for 10% lavere.

        NB: live fylder til den observerede markedspris (monitoren poller hver
        time), ikke til SL-niveauet præcist som backtesten — derfor ~-1% her og
        ikke 0.00. Uden breakeven ville samme prisbevægelse først lukke på 90.
        """
        tracker = await self._tracker(monkeypatch, tmp_path)
        trade = await self._open(tracker)
        await tracker.check_breakeven({"BTC/USDT": 111.0})

        closed = await tracker.check_sl_tp({"BTC/USDT": 99.0})

        assert [t.id for t in closed] == [trade.id]
        assert closed[0].pnl_pct == pytest.approx(-1.0)  # ikke -10% (oprindeligt SL)
