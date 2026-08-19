"""
Tests for execution/position_tracker.py (Ændring 6).

Positionslaget er det eneste sted PnL faktisk bogføres — fejl her forplanter sig
til dashboard, daglig summary og hele reflection-loopet. Hver test kører mod en
frisk temp-SQLite (tests/fixtures/db.temp_db); produktions-DB'en røres aldrig.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from core.database import Trade
from core.time_utils import utc_now
from gates.risk import RiskGate
from strategies.base import Signal
from tests.fixtures.db import temp_db

CONFIG = {
    "trading": {
        "dry_run": True, "total_capital": 100.0, "stake_amount": 5.0,
        "max_open_trades": 4, "leverage": 1, "breakeven_trigger_pct": 0.5,
    },
    "gates": {"risk": {"max_daily_loss_pct": 3.0, "max_position_pct": 5.0}},
}


def _signal(symbol: str = "BTC/USDT", side: str = "long") -> Signal:
    return Signal("trend_momentum", symbol, side, 0.7, "4h", {"rsi": 55})


async def _tracker(monkeypatch, tmp_path):
    await temp_db(monkeypatch, tmp_path, "execution.position_tracker")
    from execution.position_tracker import PositionTracker

    return PositionTracker(CONFIG)


async def _open(tracker, symbol: str = "BTC/USDT", side: str = "long",
                price: float = 100.0, sl: float = 90.0, tp: float = 120.0) -> Trade:
    return await tracker.open_position(
        _signal(symbol, side), sl_price=sl, tp_price=tp, order_result={"id": "o1"},
        current_price=price, gate_scores={"risk": {"passed": True}},
    )


class TestOpenPosition:
    @pytest.mark.asyncio
    async def test_gemmer_trade_i_db(self, monkeypatch, tmp_path):
        session_maker = await temp_db(monkeypatch, tmp_path, "execution.position_tracker")
        from execution.position_tracker import PositionTracker

        tracker = PositionTracker(CONFIG)
        trade = await _open(tracker)

        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
        assert stored is not None
        assert stored.status == "open"
        assert stored.strategy_id == "trend_momentum"
        assert stored.dry_run is True

    @pytest.mark.asyncio
    async def test_quantity_er_stake_divideret_med_pris(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, price=250.0)
        assert trade.quantity == pytest.approx(5.0 / 250.0)
        assert trade.stake_amount == 5.0

    @pytest.mark.asyncio
    async def test_position_tælles_som_åben(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        await _open(tracker)
        assert tracker.get_open_count() == 1
        assert len(tracker.get_open_positions()) == 1


class TestCloseOgPnl:
    @pytest.mark.asyncio
    async def test_open_and_close_position(self, monkeypatch, tmp_path):
        """Åbn → luk ved TP → verificér PnL, status og at positionen er væk."""
        session_maker = await temp_db(monkeypatch, tmp_path, "execution.position_tracker")
        from execution.position_tracker import PositionTracker

        tracker = PositionTracker(CONFIG)
        trade = await _open(tracker)

        closed = await tracker.check_sl_tp({"BTC/USDT": 120.0})

        assert [t.id for t in closed] == [trade.id]
        assert closed[0].pnl == pytest.approx(1.0)      # 20% af 5 USDT
        assert closed[0].pnl_pct == pytest.approx(20.0)
        assert tracker.get_open_count() == 0
        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
        assert stored.status == "closed"
        assert stored.exit_time is not None

    @pytest.mark.asyncio
    async def test_stop_loss_close(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        await _open(tracker)

        closed = await tracker.check_sl_tp({"BTC/USDT": 90.0})

        assert closed[0].pnl == pytest.approx(-0.5)
        assert closed[0].pnl_pct == pytest.approx(-10.0)

    @pytest.mark.asyncio
    async def test_pnl_calculation_long(self, monkeypatch, tmp_path):
        # entry=100, exit=120, stake=5 → 0.05 stk × 20 USDT = 1.0
        tracker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker)
        closed = await tracker.close_position(trade.id, 120.0, "take_profit")
        assert closed.pnl == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_pnl_calculation_short(self, monkeypatch, tmp_path):
        # short entry=100, exit=80 → prisfald er gevinst
        tracker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, side="short", sl=110.0, tp=80.0)
        closed = await tracker.close_position(trade.id, 80.0, "take_profit")
        assert closed.pnl == pytest.approx(1.0)
        assert closed.pnl_pct == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_short_taber_naar_prisen_stiger(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, side="short", sl=110.0, tp=80.0)
        closed = await tracker.close_position(trade.id, 110.0, "stop_loss")
        assert closed.pnl == pytest.approx(-0.5)

    @pytest.mark.asyncio
    async def test_ukendt_trade_giver_keyerror(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        with pytest.raises(KeyError):
            await tracker.close_position("findes-ikke", 100.0, "manual")


class TestCheckSlTp:
    @pytest.mark.asyncio
    async def test_pris_mellem_sl_og_tp_lukker_ikke(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        await _open(tracker)
        assert await tracker.check_sl_tp({"BTC/USDT": 105.0}) == []
        assert tracker.get_open_count() == 1

    @pytest.mark.asyncio
    async def test_symbol_uden_pris_lukkes_ikke(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        await _open(tracker)
        assert await tracker.check_sl_tp({"ETH/USDT": 1.0}) == []

    @pytest.mark.asyncio
    async def test_short_sl_er_over_entry(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        await _open(tracker, side="short", sl=110.0, tp=80.0)
        closed = await tracker.check_sl_tp({"BTC/USDT": 111.0})
        assert closed[0].pnl < 0

    @pytest.mark.asyncio
    async def test_flere_symboler_evalueres_uafhaengigt(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        await _open(tracker, "BTC/USDT")
        await _open(tracker, "ETH/USDT")

        closed = await tracker.check_sl_tp({"BTC/USDT": 120.0, "ETH/USDT": 105.0})

        assert [t.symbol for t in closed] == ["BTC/USDT"]
        assert tracker.get_open_count() == 1


class TestOpenCountOgRiskGraense:
    @pytest.mark.asyncio
    async def test_get_open_count(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        assert tracker.get_open_count() == 0
        for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
            await _open(tracker, symbol)
        assert tracker.get_open_count() == 3

    @pytest.mark.asyncio
    async def test_get_open_by_symbol(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        await _open(tracker, "BTC/USDT")
        await _open(tracker, "ETH/USDT")
        assert [t.symbol for t in tracker.get_open_by_symbol("ETH/USDT")] == ["ETH/USDT"]

    @pytest.mark.asyncio
    async def test_multiple_open_positions_femte_afvises(self, monkeypatch, tmp_path):
        """Grænsen håndhæves af RiskGate (trackeren tæller), så begge sider testes."""
        tracker = await _tracker(monkeypatch, tmp_path)
        gate = RiskGate({**CONFIG, "gates": {"risk": {**CONFIG["gates"]["risk"]}}})

        for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"):
            await _open(tracker, symbol)
        assert tracker.get_open_count() == 4

        result = gate.evaluate(
            _signal("ADA/USDT"),
            {"open_trades_count": tracker.get_open_count(), "daily_pnl": 0.0,
             "account_balance": 100.0},
        )
        assert result.passed is False
        assert "Max åbne trades" in result.reason

    @pytest.mark.asyncio
    async def test_lukket_position_frigiver_plads(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        gate = RiskGate(CONFIG)
        for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"):
            await _open(tracker, symbol)
        await tracker.check_sl_tp({"BTC/USDT": 120.0})

        result = gate.evaluate(
            _signal("ADA/USDT"),
            {"open_trades_count": tracker.get_open_count(), "daily_pnl": 0.0,
             "account_balance": 100.0},
        )
        assert result.passed is True


class TestDailyPnl:
    @pytest.mark.asyncio
    async def test_get_daily_pnl_summerer_dagens_lukkede_trades(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        t1 = await _open(tracker, "BTC/USDT")
        t2 = await _open(tracker, "ETH/USDT")

        await tracker.close_position(t1.id, 120.0, "take_profit")   # +1.0
        await tracker.close_position(t2.id, 90.0, "stop_loss")      # -0.5

        assert tracker.get_daily_pnl() == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_daily_pnl_er_nul_uden_lukkede_trades(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        await _open(tracker)
        assert tracker.get_daily_pnl() == 0.0

    @pytest.mark.asyncio
    async def test_daily_pnl_nulstilles_ved_doegnskift(self, monkeypatch, tmp_path):
        tracker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker)
        await tracker.close_position(trade.id, 90.0, "stop_loss")
        assert tracker.get_daily_pnl() < 0

        # Simulér at trackeren blev sat op i går.
        tracker._daily_reset_date = (utc_now() - timedelta(days=1)).strftime("%Y-%m-%d")

        assert tracker.get_daily_pnl() == 0.0


class TestLoadOpenPositions:
    @pytest.mark.asyncio
    async def test_aabne_positioner_genindlaeses(self, monkeypatch, tmp_path):
        await temp_db(monkeypatch, tmp_path, "execution.position_tracker")
        from execution.position_tracker import PositionTracker

        tracker = PositionTracker(CONFIG)
        trade = await _open(tracker)
        await _open(tracker, "ETH/USDT")
        await tracker.check_sl_tp({"ETH/USDT": 120.0})  # luk den ene

        fresh = PositionTracker(CONFIG)
        await fresh.load_open_positions()

        assert [t.id for t in fresh.get_open_positions()] == [trade.id]

    @pytest.mark.asyncio
    async def test_breakeven_flag_genskabes_efter_genstart(self, monkeypatch, tmp_path):
        """SL == entry i DB betyder at breakeven allerede var aktiveret."""
        await temp_db(monkeypatch, tmp_path, "execution.position_tracker")
        from execution.position_tracker import PositionTracker

        tracker = PositionTracker(CONFIG)
        trade = await _open(tracker)
        await tracker.check_breakeven({"BTC/USDT": 111.0})

        fresh = PositionTracker(CONFIG)
        await fresh.load_open_positions()

        assert fresh.is_breakeven_activated(trade.id) is True
