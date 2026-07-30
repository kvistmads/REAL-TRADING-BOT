"""
Tests for position monitor-loopet — Phase 6 Del B.

Engine'en har to loops: det langsomme signal-tick (timeframes.primary = 4h) og
position monitor'en, der tjekker SL/TP hver time og skriver bot_status.json hvert
minut. Testene her rører aldrig DB eller netværk — tracker/fetcher/notifier er fakes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from core import engine as engine_mod
from core.database import Trade
from core.engine import POSITION_CHECK_INTERVAL, STATUS_WRITE_INTERVAL, TradingEngine

CONFIG = {
    "exchange": {"name": "binance", "sandbox": True},
    "trading": {
        "dry_run": True,
        "total_capital": 100.0,
        "stake_amount": 5.0,
        "max_open_trades": 4,
        "leverage": 1,
    },
    "symbols": ["BTC/USDT", "EUR/USD"],
    "timeframes": {"primary": "4h", "entry": "1h"},
    "strategies": {"enabled": ["trend_momentum"], "min_confidence": 0.65},
    "gates": {
        "confluence": {"enabled": False},
        "risk": {"enabled": True, "blocking": True},
        "regime": {"enabled": True, "blocking": True},
    },
    "risk_defaults": {
        "crypto": {"sl_pct": 10.0, "tp_pct": 20.0},
        "forex": {"sl_pct": 1.5, "tp_pct": 3.0},
        "gold": {"sl_pct": 3.0, "tp_pct": 6.0},
    },
}


def _trade(symbol: str = "BTC/USDT", side: str = "long", **overrides) -> Trade:
    defaults = dict(
        id=f"t-{symbol}-{side}", strategy_id="trend_momentum", symbol=symbol, side=side,
        entry_price=50000.0, sl_price=45000.0, tp_price=60000.0, quantity=0.0001,
        stake_amount=5.0, status="open", entry_time=datetime(2026, 7, 30, 10, 0),
    )
    defaults.update(overrides)
    return Trade(**defaults)


class FakeTracker:
    def __init__(self, open_positions: list[Trade] | None = None,
                 closed: list[Trade] | None = None):
        self._open = open_positions or []
        self._closed = closed or []
        self.sl_tp_calls: list[dict] = []

    def get_open_positions(self) -> list[Trade]:
        return list(self._open)

    async def check_sl_tp(self, prices: dict[str, float]) -> list[Trade]:
        self.sl_tp_calls.append(dict(prices))
        return list(self._closed)


class FakeFetcher:
    def __init__(self, prices: dict[str, float] | None = None):
        self.prices = prices or {}
        self.calls: list[str] = []

    async def get_latest_price(self, symbol: str) -> float | None:
        self.calls.append(symbol)
        return self.prices.get(symbol)


class FakeNotifier:
    def __init__(self):
        self.closed: list[tuple[str, str]] = []

    async def send_trade_closed(self, trade: Trade, reason: str) -> None:
        self.closed.append((trade.symbol, reason))


class FakeExchange:
    """Enhver berøring er en fejl: exits må ALDRIG gå via børsen i dry-run."""

    def __init__(self):
        self.calls: list[str] = []

    async def place_order(self, *args, **kwargs):
        self.calls.append("place_order")
        raise AssertionError("exchange.place_order kaldt fra position monitor")

    async def create_order(self, *args, **kwargs):
        self.calls.append("create_order")
        raise AssertionError("exchange.create_order kaldt fra position monitor")


def _engine(tracker: FakeTracker, fetcher: FakeFetcher | None = None) -> TradingEngine:
    engine = TradingEngine(CONFIG)
    engine.position_tracker = tracker
    engine.fetcher = fetcher or FakeFetcher()
    engine.notifier = FakeNotifier()
    engine.exchange = FakeExchange()
    return engine


class TestCheckPositionsFast:
    @pytest.mark.asyncio
    async def test_no_op_uden_aabne_positioner(self):
        engine = _engine(FakeTracker([]))
        await engine._check_positions_fast()
        assert engine.fetcher.calls == []
        assert engine.position_tracker.sl_tp_calls == []

    @pytest.mark.asyncio
    async def test_henter_pris_og_evaluerer_sl_tp(self):
        tracker = FakeTracker([_trade("BTC/USDT")])
        engine = _engine(tracker, FakeFetcher({"BTC/USDT": 44000.0}))

        await engine._check_positions_fast()

        assert engine.fetcher.calls == ["BTC/USDT"]
        assert tracker.sl_tp_calls == [{"BTC/USDT": 44000.0}]

    @pytest.mark.asyncio
    async def test_henter_kun_en_pris_pr_symbol(self):
        """To positioner i samme symbol må ikke give to prisopslag."""
        tracker = FakeTracker([_trade("BTC/USDT", "long"), _trade("BTC/USDT", "short")])
        engine = _engine(tracker, FakeFetcher({"BTC/USDT": 50000.0}))

        await engine._check_positions_fast()

        assert engine.fetcher.calls == ["BTC/USDT"]

    @pytest.mark.asyncio
    async def test_forex_position_tjekkes_ogsaa(self):
        """Del A gør forex-priser tilgængelige på Mac — monitoren skal bruge dem."""
        tracker = FakeTracker([_trade("EUR/USD", entry_price=1.09, sl_price=1.07,
                                      tp_price=1.12)])
        engine = _engine(tracker, FakeFetcher({"EUR/USD": 1.0855}))

        await engine._check_positions_fast()

        assert tracker.sl_tp_calls == [{"EUR/USD": pytest.approx(1.0855)}]

    @pytest.mark.asyncio
    async def test_symbol_uden_pris_udelades(self):
        tracker = FakeTracker([_trade("BTC/USDT"), _trade("EUR/USD")])
        engine = _engine(tracker, FakeFetcher({"BTC/USDT": 50000.0}))

        await engine._check_positions_fast()

        assert tracker.sl_tp_calls == [{"BTC/USDT": 50000.0}]

    @pytest.mark.asyncio
    async def test_ingen_priser_giver_intet_sl_tp_kald(self):
        tracker = FakeTracker([_trade("BTC/USDT")])
        engine = _engine(tracker, FakeFetcher({}))

        await engine._check_positions_fast()

        assert tracker.sl_tp_calls == []

    @pytest.mark.asyncio
    async def test_sl_exit_notificeres_og_gaar_ikke_via_boersen(self):
        closed = _trade("BTC/USDT", exit_price=44000.0, status="closed", pnl=-0.6)
        tracker = FakeTracker([_trade("BTC/USDT")], closed=[closed])
        engine = _engine(tracker, FakeFetcher({"BTC/USDT": 44000.0}))

        await engine._check_positions_fast()

        assert engine.notifier.closed == [("BTC/USDT", "SL hit")]
        assert engine.exchange.calls == []  # dry-run: lukkes kun i DB

    @pytest.mark.asyncio
    async def test_priser_gemmes_til_dashboardet(self):
        tracker = FakeTracker([_trade("BTC/USDT")])
        engine = _engine(tracker, FakeFetcher({"BTC/USDT": 51000.0}))

        await engine._check_positions_fast()

        assert engine._last_prices == {"BTC/USDT": 51000.0}


class TestMonitorLoop:
    @pytest.mark.asyncio
    async def test_status_hvert_minut_og_sl_tp_hver_time(self, monkeypatch):
        """60 runder à 60 sek = 1 time → 60 status-skriv og præcis 1 SL/TP-tjek."""
        engine = _engine(FakeTracker([]))
        engine._running = True
        sleeps: list[float] = []
        checks, writes = [], []

        async def fake_sleep(secs):
            sleeps.append(secs)
            if len(sleeps) >= POSITION_CHECK_INTERVAL // STATUS_WRITE_INTERVAL:
                engine._running = False

        async def fake_check():
            checks.append(1)

        async def fake_write():
            writes.append(1)

        monkeypatch.setattr(engine_mod.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(engine, "_check_positions_fast", fake_check)
        monkeypatch.setattr(engine, "_write_dashboard_status", fake_write)

        await engine._position_monitor_loop()

        assert sleeps == [STATUS_WRITE_INTERVAL] * 60
        assert len(writes) == 60
        assert len(checks) == 1

    @pytest.mark.asyncio
    async def test_fejlet_sl_tp_tjek_blokerer_ikke_dashboardet(self, monkeypatch):
        engine = _engine(FakeTracker([]))
        engine._running = True
        rounds, writes = [], []

        async def fake_sleep(secs):
            rounds.append(secs)
            if len(rounds) >= 2:
                engine._running = False

        async def boom():
            raise RuntimeError("prisfetch nede")

        async def fake_write():
            writes.append(1)

        monkeypatch.setattr(engine_mod.asyncio, "sleep", fake_sleep)
        # Tjek hver runde, så begge runder rammer den fejlende prisfetch.
        monkeypatch.setattr(engine_mod, "POSITION_CHECK_INTERVAL", STATUS_WRITE_INTERVAL)
        monkeypatch.setattr(engine, "_check_positions_fast", boom)
        monkeypatch.setattr(engine, "_write_dashboard_status", fake_write)

        await engine._position_monitor_loop()  # må ikke rejse

        assert len(writes) == 2  # status skrives selvom exit-tjekket fejler

    @pytest.mark.asyncio
    async def test_stop_aflyser_begge_loops(self):
        engine = _engine(FakeTracker([]))
        engine._running = True

        async def forever():
            await asyncio.sleep(3600)

        engine._tasks = [asyncio.create_task(forever()) for _ in range(2)]
        tasks = list(engine._tasks)
        engine.fetcher = None
        engine.exchange = None

        await engine.stop()
        await asyncio.gather(*tasks, return_exceptions=True)

        assert all(t.cancelled() for t in tasks)
        assert engine._running is False


class TestTickLoopSkriverIkkeStatus:
    def test_status_konstanter_er_ryddet_op(self):
        """PRD-acceptkriterie: throttle-koden fra Phase 5 er væk."""
        assert not hasattr(engine_mod, "_STATUS_INTERVAL")
        assert not hasattr(TradingEngine(CONFIG), "_last_status_write")

    def test_intervaller_er_som_specificeret(self):
        assert POSITION_CHECK_INTERVAL == 3600
        assert STATUS_WRITE_INTERVAL == 60
