"""
Tests for flip level + confidence-instrumentering (PRD_FLIP_LEVEL_OG_CONFIDENCE).

Tre ting låses fast her, fordi de er nemme at bryde ved et uheld senere:

1. **Body close bryder, wick gør ikke.** Et wick igennem er et sweep, ikke en
   invalidering — samme skelnen som fejlen der blev rettet i ``find_sr_levels``.
2. **flip_level og confidence er immutable.** De beskriver præmissen for handlen
   på det tidspunkt den blev taget; kan de omskrives bagefter, måler vi ingenting.
3. **Observe-only.** Et brud lukker ingen handel — hverken live eller i A1-backtesten.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from backtest.runner import _flip_breach_offset, run_backtest, simulate_trade
from core.database import Trade
from core.time_utils import utc_now
from execution.position_tracker import is_flip_breached
from strategies.base import Signal
from tests.fixtures.db import temp_db

CONFIG = {
    "trading": {
        "dry_run": True, "total_capital": 100.0, "stake_amount": 5.0,
        "max_open_trades": 4, "leverage": 1, "breakeven_trigger_pct": 0.5,
        "max_bars_held": 24,
    },
    "risk_defaults": {
        "crypto": {"sl_pct": 10.0, "tp_pct": 20.0,
                   "atr_sl_multiplier": 2.0, "tp_rr_ratio": 2.0},
    },
    "strategies": {"min_confidence": 0.45},
}


def _signal(side: str = "long", flip_level: float | None = 95.0,
            confidence: float = 0.7) -> Signal:
    return Signal("trend_momentum", "BTC/USDT", side, confidence, "4h",
                  {"rsi": 55, "flip_level": flip_level})


async def _tracker(monkeypatch, tmp_path):
    session_maker = await temp_db(monkeypatch, tmp_path, "execution.position_tracker")
    from execution.position_tracker import PositionTracker

    return PositionTracker(CONFIG), session_maker


async def _open(tracker, signal: Signal, price: float = 100.0) -> Trade:
    return await tracker.open_position(
        signal, sl_price=90.0, tp_price=120.0, order_result={"id": "o1"},
        current_price=price, gate_scores={},
    )


# ---------------------------------------------------------------------------
# 1. Body close vs. wick
# ---------------------------------------------------------------------------

class TestBodyCloseIkkeWick:
    def test_long_brydes_af_close_under_niveauet(self):
        assert is_flip_breached("long", 95.0, close=94.9) is True

    def test_long_brydes_ikke_af_close_over_niveauet(self):
        assert is_flip_breached("long", 95.0, close=95.1) is False

    def test_short_brydes_af_close_over_niveauet(self):
        assert is_flip_breached("short", 105.0, close=105.1) is True

    def test_short_brydes_ikke_af_close_under_niveauet(self):
        assert is_flip_breached("short", 105.0, close=104.9) is False

    @pytest.mark.asyncio
    async def test_wick_igennem_registreres_ikke(self, monkeypatch, tmp_path):
        """Baren dykker til 90 men LUKKER på 96 → sweep, ikke invalidering."""
        tracker, _ = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0))
        after = trade.entry_time + timedelta(hours=4)

        # Kun (tid, close) sendes videre — netop derfor kan low=90 ikke bryde noget.
        breached = await tracker.check_flip_levels({"BTC/USDT": [(after, 96.0)]})

        assert breached == []
        assert trade.flip_breached_at is None
        assert trade.flip_breached_before_exit is None

    @pytest.mark.asyncio
    async def test_body_close_igennem_registreres(self, monkeypatch, tmp_path):
        tracker, session_maker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0))
        after = trade.entry_time + timedelta(hours=4)

        breached = await tracker.check_flip_levels({"BTC/USDT": [(after, 94.0)]})

        assert [t.id for t in breached] == [trade.id]
        assert trade.flip_breached_at == after
        assert trade.flip_breached_before_exit is True
        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
        assert stored.flip_breached_at == after

    @pytest.mark.asyncio
    async def test_første_brud_vinder_og_gentages_ikke(self, monkeypatch, tmp_path):
        tracker, _ = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0))
        first = trade.entry_time + timedelta(hours=4)
        second = trade.entry_time + timedelta(hours=8)

        await tracker.check_flip_levels({"BTC/USDT": [(first, 94.0), (second, 93.0)]})
        again = await tracker.check_flip_levels({"BTC/USDT": [(second, 93.0)]})

        assert trade.flip_breached_at == first  # første brud, ikke det seneste
        assert again == []

    @pytest.mark.asyncio
    async def test_barer_før_entry_tæller_ikke(self, monkeypatch, tmp_path):
        tracker, _ = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0))
        before = trade.entry_time - timedelta(hours=4)

        await tracker.check_flip_levels({"BTC/USDT": [(before, 80.0)]})

        assert trade.flip_breached_at is None


# ---------------------------------------------------------------------------
# 2. Immutabilitet
# ---------------------------------------------------------------------------

class TestImmutabilitet:
    @pytest.mark.asyncio
    async def test_flip_level_kan_ikke_opdateres(self, monkeypatch, tmp_path):
        tracker, session_maker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0))

        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
            stored.flip_level = 80.0
            with pytest.raises(ValueError, match="flip_level er immutable"):
                await session.commit()

        async with session_maker() as session:
            unchanged = await session.get(Trade, trade.id)
        assert unchanged.flip_level == 95.0

    @pytest.mark.asyncio
    async def test_confidence_kan_ikke_opdateres(self, monkeypatch, tmp_path):
        tracker, session_maker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", confidence=0.71))

        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
            stored.confidence = 0.99
            with pytest.raises(ValueError, match="confidence er immutable"):
                await session.commit()

    @pytest.mark.asyncio
    async def test_brud_felterne_må_gerne_opdateres(self, monkeypatch, tmp_path):
        """Selve observationen er ikke præmissen — den skal kunne skrives."""
        tracker, session_maker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0))
        when = utc_now()

        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
            stored.flip_breached_at = when
            stored.flip_breached_before_exit = True
            await session.commit()  # må ikke rejse

        async with session_maker() as session:
            reloaded = await session.get(Trade, trade.id)
        assert reloaded.flip_breached_before_exit is True

    @pytest.mark.asyncio
    async def test_samme_værdi_tildelt_igen_er_ikke_en_ændring(self, monkeypatch, tmp_path):
        """SQLAlchemy ser en tildeling som en ændring, også når værdien er identisk."""
        tracker, session_maker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0, confidence=0.7))

        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
            stored.flip_level = 95.0
            stored.confidence = 0.7
            stored.pnl = 1.0  # en rigtig ændring, så der faktisk sker et UPDATE
            await session.commit()  # må ikke rejse

        async with session_maker() as session:
            reloaded = await session.get(Trade, trade.id)
        assert reloaded.flip_level == 95.0
        assert reloaded.pnl == 1.0


# ---------------------------------------------------------------------------
# 3. Entry-skrivning og afslutning
# ---------------------------------------------------------------------------

class TestEntryOgExit:
    @pytest.mark.asyncio
    async def test_confidence_og_flip_level_kopieres_ved_entry(self, monkeypatch, tmp_path):
        tracker, session_maker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0, confidence=0.63))

        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
        assert stored.confidence == pytest.approx(0.63)
        assert stored.flip_level == pytest.approx(95.0)

    @pytest.mark.asyncio
    async def test_strategi_uden_flip_level_giver_none(self, monkeypatch, tmp_path):
        tracker, _ = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=None))
        assert trade.flip_level is None

        await tracker.check_flip_levels(
            {"BTC/USDT": [(trade.entry_time + timedelta(hours=4), 1.0)]}
        )
        assert trade.flip_breached_at is None

    @pytest.mark.asyncio
    async def test_intakt_flip_level_bliver_false_ved_exit(self, monkeypatch, tmp_path):
        """None = 'endnu ikke brudt'; ved exit er svaret et endeligt Nej."""
        tracker, session_maker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0))

        closed = await tracker.close_position(trade.id, 110.0, "take_profit")

        assert closed.flip_breached_before_exit is False
        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
        assert stored.flip_breached_before_exit is False

    @pytest.mark.asyncio
    async def test_uden_flip_level_forbliver_none_ved_exit(self, monkeypatch, tmp_path):
        tracker, _ = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=None))
        closed = await tracker.close_position(trade.id, 110.0, "take_profit")
        assert closed.flip_breached_before_exit is None

    @pytest.mark.asyncio
    async def test_brud_bevares_gennem_exit(self, monkeypatch, tmp_path):
        tracker, session_maker = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0))
        await tracker.check_flip_levels(
            {"BTC/USDT": [(trade.entry_time + timedelta(hours=4), 94.0)]}
        )

        await tracker.close_position(trade.id, 91.0, "stop_loss")

        async with session_maker() as session:
            stored = await session.get(Trade, trade.id)
        assert stored.flip_breached_before_exit is True
        assert stored.flip_breached_at is not None

    @pytest.mark.asyncio
    async def test_flip_tjek_lukker_ingen_position(self, monkeypatch, tmp_path):
        """OBSERVE-ONLY: bruddet registreres, handlen kører videre."""
        tracker, _ = await _tracker(monkeypatch, tmp_path)
        trade = await _open(tracker, _signal("long", flip_level=95.0))

        await tracker.check_flip_levels(
            {"BTC/USDT": [(trade.entry_time + timedelta(hours=4), 50.0)]}
        )

        assert tracker.get_open_count() == 1
        assert trade.status == "open"


# ---------------------------------------------------------------------------
# 4. Engine: kun FÆRDIGE barer må tælle
# ---------------------------------------------------------------------------

class TestEngineClosedBars:
    def _engine(self):
        from core.engine import TradingEngine

        return TradingEngine({
            "timeframes": {"primary": "4h", "entry": "1h"},
            "symbols": ["BTC/USDT"],
            "trading": CONFIG["trading"],
            "strategies": {"enabled": [], "min_confidence": 0.45},
            "gates": {"confluence": {"enabled": False}, "risk": {"enabled": False},
                      "regime": {"enabled": False}},
            "notifications": {"telegram": {"enabled": False}},
        })

    def _df(self, times, closes):
        return pd.DataFrame({"time": times, "close": closes})

    def test_uafsluttet_bar_udelades(self):
        """Ved en genstart midt i en bar er 'close' bare den aktuelle pris."""
        now = utc_now()
        # Baren startede for 2 timer siden → lukker først om 2 timer.
        forming = now - timedelta(hours=2)
        finished = now - timedelta(hours=6)
        bars = self._engine()._closed_bars(self._df([finished, forming], [100.0, 90.0]))
        assert [b[1] for b in bars] == [100.0]

    def test_bar_i_close_bufferen_tæller_med(self):
        """Ticket vækkes 2 min FØR close netop for at ramme den bar."""
        now = utc_now()
        closing = now - timedelta(hours=4) + timedelta(minutes=2)
        bars = self._engine()._closed_bars(self._df([closing], [90.0]))
        assert [b[1] for b in bars] == [90.0]

    def test_tom_df(self):
        assert self._engine()._closed_bars(pd.DataFrame()) == []


# ---------------------------------------------------------------------------
# 5. Backtest: A1 observerer, A2 lukker
# ---------------------------------------------------------------------------

def _bars(closes, highs=None, lows=None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=n, freq="4h"),
        "open": closes,
        "high": highs if highs is not None else [c * 1.001 for c in closes],
        "low": lows if lows is not None else [c * 0.999 for c in closes],
        "close": closes,
        "volume": [1000.0] * n,
    })


class TestBacktestFlip:
    def test_offset_finder_første_body_close(self):
        df = _bars([100.0, 99.0, 96.0, 94.0, 93.0])
        assert _flip_breach_offset(_signal("long", 95.0), df, horizon=24) == 3

    def test_offset_ignorerer_wick(self):
        """Bar 1 dykker til 90 (low) men lukker på 96 → ikke et brud."""
        df = _bars([100.0, 96.0, 97.0], lows=[99.9, 90.0, 96.9])
        assert _flip_breach_offset(_signal("long", 95.0), df, horizon=24) is None

    def test_offset_short_spejlvendt(self):
        df = _bars([100.0, 101.0, 106.0])
        assert _flip_breach_offset(_signal("short", 105.0), df, horizon=24) == 2

    def test_uden_flip_level_ingen_offset(self):
        df = _bars([100.0, 50.0, 20.0])
        assert _flip_breach_offset(_signal("long", None), df, horizon=24) is None

    def test_a1_registrerer_uden_at_lukke(self):
        """Baseline: flip level brydes, men exit-årsagen er stadig den gamle."""
        df = _bars([100.0] + [94.0] * 5 + [125.0])
        trade = simulate_trade(_signal("long", 95.0), df, CONFIG, flip_exit=False)
        assert trade["flip_breached_bar"] == 1
        assert trade["flip_breached_before_exit"] is True
        assert trade["reason"] != "flip_level"

    def test_a2_lukker_på_flip_level(self):
        df = _bars([100.0] + [94.0] * 5 + [125.0])
        trade = simulate_trade(_signal("long", 95.0), df, CONFIG, flip_exit=True)
        assert trade["reason"] == "flip_level"
        assert trade["bars_held"] == 1
        assert trade["exit_price"] == pytest.approx(94.0)

    def test_a1_og_a2_er_identiske_når_niveauet_holder(self):
        df = _bars([100.0] + list(range(101, 130)))
        a1 = simulate_trade(_signal("long", 95.0), df, CONFIG, flip_exit=False)
        a2 = simulate_trade(_signal("long", 95.0), df, CONFIG, flip_exit=True)
        assert a1["reason"] == a2["reason"]
        assert a1["pnl_pct"] == a2["pnl_pct"]
        assert a1["flip_timing"] == "never"

    def test_timing_after_exit(self):
        """TP rammes først, flip level brydes bagefter → tesen holdt så længe vi sad i den."""
        df = _bars([100.0, 125.0] + [90.0] * 5)
        trade = simulate_trade(_signal("long", 95.0), df, CONFIG, flip_exit=False)
        assert trade["reason"] == "take_profit"
        assert trade["flip_timing"] == "after_exit"
        assert trade["flip_breached_before_exit"] is False

    def test_timing_uden_niveau(self):
        df = _bars([100.0] + [94.0] * 5)
        trade = simulate_trade(_signal("long", None), df, CONFIG, flip_exit=True)
        assert trade["flip_timing"] == "no_flip_level"
        assert trade["reason"] != "flip_level"


# ---------------------------------------------------------------------------
# 6. Backtesten anvender ALDRIG confidence-gaten (del B)
# ---------------------------------------------------------------------------

class _StubStrategy:
    """Genererer ét signal med fast confidence pr. bar."""

    name = "stub"
    timeframe = "4h"
    min_confidence = 0.65

    def __init__(self, confidence: float):
        self.confidence = confidence
        self.seen_min_conf: list[float] = []

    def generate_signal(self, df, symbol, params=None):
        self.seen_min_conf.append((params or {}).get("min_confidence"))
        return Signal(self.name, symbol, "long", self.confidence, "4h",
                      {"flip_level": None})


class TestIngenConfidenceGateIBacktest:
    def test_lavt_signal_bliver_stadig_simuleret(self):
        strategy = _StubStrategy(confidence=0.10)  # langt under live-tærsklen 0.45
        trades = run_backtest(_bars([100.0] * 210), strategy, "BTC/USDT",
                              CONFIG, warmup=200)
        assert trades, "et signal under min_confidence skal stadig give et udfald"
        assert all(t["confidence"] == pytest.approx(0.10) for t in trades)

    def test_strategien_kaldes_med_nul(self):
        strategy = _StubStrategy(confidence=0.10)
        run_backtest(_bars([100.0] * 210), strategy, "BTC/USDT", CONFIG, warmup=200)
        assert set(strategy.seen_min_conf) == {0.0}

    def test_would_pass_production_markerer_live_udsnittet(self):
        under = run_backtest(_bars([100.0] * 210), _StubStrategy(0.30), "BTC/USDT",
                             CONFIG, warmup=200)
        over = run_backtest(_bars([100.0] * 210), _StubStrategy(0.80), "BTC/USDT",
                            CONFIG, warmup=200)
        assert all(t["would_pass_production"] is False for t in under)
        assert all(t["would_pass_production"] is True for t in over)
        assert all(t["production_min_confidence"] == 0.45 for t in under)


# ---------------------------------------------------------------------------
# 7. Strategierne angiver niveauet
# ---------------------------------------------------------------------------

class TestStrategiMetadata:
    def test_trend_momentum_bruger_ema50(self):
        from strategies.trend_momentum import TrendMomentum
        from tests.fixtures.ohlcv import tm_long_signal

        signal = TrendMomentum().generate_signal(tm_long_signal(), "BTC/USDT",
                                                 {"min_confidence": 0.0})
        assert signal is not None
        assert signal.metadata["flip_level"] == pytest.approx(signal.metadata["ema_50"])

    def test_trend_momentum_short_bruger_samme_niveau(self):
        from strategies.trend_momentum import TrendMomentum
        from tests.fixtures.ohlcv import tm_short_signal

        signal = TrendMomentum().generate_signal(tm_short_signal(), "BTC/USDT",
                                                 {"min_confidence": 0.0})
        assert signal is not None
        assert signal.side == "short"
        assert signal.metadata["flip_level"] == pytest.approx(signal.metadata["ema_50"])

    def test_volatility_breakout_bruger_det_brudte_niveau(self):
        """Long bryder OVER resistance → en close tilbage under det modsiger tesen."""
        from strategies.volatility_breakout import VolatilityBreakout
        from tests.fixtures.ohlcv import vb_long_breakout

        signal = VolatilityBreakout().generate_signal(
            vb_long_breakout(), "BTC/USDT",
            {"min_confidence": 0.0, "min_volume_ratio": 1.2},
        )
        assert signal is not None
        assert signal.side == "long"
        assert signal.metadata["flip_level"] == signal.metadata["breakout_level"]
        assert signal.metadata["flip_level"] == signal.metadata["resistance_level"]

    def test_volatility_breakout_har_altid_et_niveau(self):
        """breakout_level sættes altid når side sættes — modsat den modsatte side af rangen."""
        from strategies.volatility_breakout import VolatilityBreakout
        from tests.fixtures.ohlcv import vb_long_breakout

        signal = VolatilityBreakout().generate_signal(
            vb_long_breakout(), "BTC/USDT",
            {"min_confidence": 0.0, "min_volume_ratio": 1.2},
        )
        assert signal.metadata["flip_level"] is not None

    def test_reversal_context_kan_ikke_angive_et_niveau(self):
        """En strategi der ikke kan formulere sin egen invalidering siger det eksplicit."""
        from strategies.reversal_context import ReversalContext
        from tests.fixtures.ohlcv import rev_bullish_long

        signal = ReversalContext().generate_signal(rev_bullish_long(), "BTC/USDT",
                                                   {"min_confidence": 0.0})
        assert signal is not None
        assert "flip_level" in signal.metadata
        assert signal.metadata["flip_level"] is None


# ---------------------------------------------------------------------------
# 8. Engine-integration: tjekket kaldes fra _tick med kun færdige barer
# ---------------------------------------------------------------------------

class _FlipStrategy:
    """Genererer aldrig et signal — vi tester kun flip-tjekket i _tick."""

    name = "flip_stub"
    timeframe = "4h"
    min_confidence = 0.65

    def generate_signal(self, df, symbol, params=None):
        return None


class TestEngineTickKalderFlipTjek:
    @pytest.mark.asyncio
    async def test_tick_sender_kun_lukkede_barer_videre(self, monkeypatch):
        from tests.fixtures.engine import fake_engine

        now = utc_now()
        # To færdige barer + én der stadig former sig.
        times = [now - timedelta(hours=12), now - timedelta(hours=8),
                 now - timedelta(hours=1)]
        df = pd.DataFrame({
            "time": times,
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1000.0] * 3,
        })
        # add_all kræver flere barer end fixturen har; engine springer df < 30 over,
        # så vi kalder flip-tjekket direkte med den samme df.
        engine = fake_engine(monkeypatch, [_FlipStrategy()], {"BTC/USDT": df})

        await engine._check_flip_levels("BTC/USDT", df)

        assert len(engine.position_tracker.flip_calls) == 1
        bars = engine.position_tracker.flip_calls[0]["BTC/USDT"]
        assert [c for _, c in bars] == [100.0, 101.0]  # den uafsluttede bar er udeladt

    @pytest.mark.asyncio
    async def test_fejl_i_flip_tjek_stopper_ikke_ticket(self, monkeypatch):
        """Instrumentering er underordnet handelsflowet."""
        from tests.fixtures.engine import fake_engine

        df = pd.DataFrame({"time": [utc_now() - timedelta(hours=8)], "close": [100.0]})
        engine = fake_engine(monkeypatch, [_FlipStrategy()], {"BTC/USDT": df})

        async def _boom(closed_bars):
            raise RuntimeError("DB nede")

        monkeypatch.setattr(engine.position_tracker, "check_flip_levels", _boom)
        await engine._check_flip_levels("BTC/USDT", df)  # må ikke rejse
