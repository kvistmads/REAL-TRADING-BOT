"""Tests for Phase 5 — Research Layer, Confirmation Hook, Backtest→DB og Dashboard-status."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backtest.runner import _to_db_record, save_results_to_db
from core.database import BacktestResult, Base, ShadowSignal
from reflection.news import accuracy_tracker
from reflection.news.confirmation import apply_news_confirmation
from reflection.research import backtest_reader, strategy_db, web_searcher
from reflection.research.researcher import Researcher
from status_writer import write_status
from strategies.base import Signal


@pytest.fixture
def db_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def session(db_factory):
    with db_factory() as s:
        yield s


def _signal(side: str = "long", confidence: float = 0.70) -> Signal:
    return Signal("trend_momentum", "BTC/USDT", side, confidence, "4h", {})


def _seed_shadow(session, *, symbol="BTC/USDT", n_eval=12, correct=True, predicted="up") -> None:
    now = datetime.utcnow()
    for i in range(n_eval):
        session.add(
            ShadowSignal(
                symbol=symbol, predicted_direction=predicted, confidence=0.7, horizon_hours=24,
                eval_at=now - timedelta(hours=1), price_at_signal=100.0,
                actual_direction=predicted, correct=correct,
                created_at=now - timedelta(hours=n_eval - i),  # sidste er nyest
            )
        )
    session.commit()


# ---------------------------------------------------------------------------
# strategy_db (curated, offline)
# ---------------------------------------------------------------------------

def test_strategy_db_returns_context_for_all_strategies():
    for sid in ["trend_momentum", "reversal_context", "volatility_breakout"]:
        ctx = strategy_db.get_strategy_context(sid, {}, {})
        assert isinstance(ctx, str) and len(ctx) > 20
        assert "Strategi-viden" in ctx


def test_strategy_db_flags_params_outside_range():
    ctx = strategy_db.get_strategy_context("trend_momentum", {"min_confidence": 0.50}, {})
    assert "⚠️ min_confidence" in ctx
    assert "UNDER" in ctx
    # En værdi inden for range flagges ikke som udenfor.
    ok = strategy_db.get_strategy_context("trend_momentum", {"min_confidence": 0.68}, {})
    assert "⚠️ min_confidence" not in ok


def test_strategy_db_flags_nested_param_outside_range():
    # Punkt-adresseret parameter (trend_strength_scale.crypto, anbefalet 0.03-0.08).
    ctx = strategy_db.get_strategy_context(
        "trend_momentum", {"trend_strength_scale": {"crypto": 0.20}}, {}
    )
    assert "trend_strength_scale.crypto" in ctx
    assert "OVER" in ctx


# ---------------------------------------------------------------------------
# backtest_reader
# ---------------------------------------------------------------------------

def test_backtest_reader_returns_none_when_no_data(session):
    assert backtest_reader.get_backtest_baseline("trend_momentum", "BTC/USDT", session=session) is None


def test_backtest_reader_returns_baseline_when_data_exists(session):
    session.add(
        BacktestResult(
            strategy_id="trend_momentum", symbol="BTC/USDT",
            period_start=datetime(2024, 1, 1), period_end=datetime(2026, 7, 1),
            total_trades=22, win_rate=0.545, profit_factor=2.23, sharpe=1.35,
            max_drawdown=0.12, total_return_pct=40.0, source_file="suite_2026-07-26.csv",
        )
    )
    session.commit()
    b = backtest_reader.get_backtest_baseline("trend_momentum", "BTC/USDT", session=session)
    assert b is not None
    assert b["wr"] == 0.545
    assert b["pf"] == 2.23
    assert b["trades"] == 22
    assert b["source"] == "suite_2026-07-26.csv"
    assert "2024-01-01" in b["period"]


def test_compare_live_vs_backtest_identifies_underperformance():
    baseline = {"wr": 0.55, "pf": 2.0, "trades": 30, "period": "x", "source": "suite.csv"}
    live = {"wr": 0.40, "pf": 1.2, "trades": 25}
    out = backtest_reader.compare_live_vs_backtest(live, baseline)
    assert "UNDERPRÆSTERER" in out


def test_compare_live_vs_backtest_no_baseline():
    out = backtest_reader.compare_live_vs_backtest({"wr": 0.5, "trades": 30}, None)
    assert "Ingen backtest-baseline" in out


def test_compare_live_vs_backtest_too_few_trades():
    baseline = {"wr": 0.55, "pf": 2.0, "trades": 30, "period": "x", "source": "suite.csv"}
    out = backtest_reader.compare_live_vs_backtest({"wr": 0.5, "trades": 3}, baseline)
    assert "for få" in out.lower()


# ---------------------------------------------------------------------------
# web_searcher (best-effort, offline)
# ---------------------------------------------------------------------------

def test_web_searcher_returns_empty_on_network_error():
    def boom(url, headers):
        raise ConnectionError("network down")

    assert web_searcher.search_macro_context("July 2026", opener=boom) == ""
    assert web_searcher.search_strategy_research("trend_momentum", opener=boom) == ""


# ---------------------------------------------------------------------------
# Researcher (offline orchestration)
# ---------------------------------------------------------------------------

def test_researcher_builds_context_offline(session):
    r = Researcher(enable_web=False)
    ctx = r.build_context(
        "trend_momentum", "BTC/USDT", "July 2026",
        current_params={"min_confidence": 0.50},
        live_metrics={"wr": 0.30, "pf": 0.7, "trades": 5},
        session=session,
    )
    assert "Research kontekst for trend_momentum × BTC/USDT" in ctx
    assert "søgning slået fra" in ctx           # web deaktiveret
    assert "Ingen backtest-baseline" in ctx     # ingen DB-data → graceful
    assert "min_confidence" in ctx


def test_researcher_ab_suggestions_offline():
    section = Researcher(enable_web=False).build_ab_experiment_suggestions(
        ["trend_momentum", "reversal_context", "volatility_breakout"]
    )
    assert "trend_momentum" in section
    assert "test" in section


# ---------------------------------------------------------------------------
# accuracy_tracker.get_symbol_accuracy + confirmation hook
# ---------------------------------------------------------------------------

def test_get_symbol_accuracy_none_below_min(session):
    _seed_shadow(session, n_eval=5)
    assert accuracy_tracker.get_symbol_accuracy(session, "BTC/USDT", min_signals=10) is None


def test_get_symbol_accuracy_value_above_min(session):
    _seed_shadow(session, n_eval=10, correct=True)
    assert accuracy_tracker.get_symbol_accuracy(session, "BTC/USDT", min_signals=10) == 1.0


def test_news_confirmation_hook_boosts_confidence_on_match(session):
    _seed_shadow(session, predicted="up", correct=True, n_eval=12)
    out = apply_news_confirmation(
        session, _signal("long", 0.70), "BTC/USDT",
        enabled=True, boost=0.05, damp=0.08, min_signals=10,
    )
    assert out.confidence == pytest.approx(0.75)


def test_news_confirmation_hook_damps_confidence_on_conflict(session):
    _seed_shadow(session, predicted="up", correct=True, n_eval=12)
    # Nyere, konfliktende shadow signal (down) bliver "seneste".
    session.add(
        ShadowSignal(
            symbol="BTC/USDT", predicted_direction="down", confidence=0.8, horizon_hours=24,
            eval_at=datetime.utcnow() + timedelta(hours=24), price_at_signal=100.0,
            created_at=datetime.utcnow() + timedelta(minutes=5),
        )
    )
    session.commit()
    out = apply_news_confirmation(
        session, _signal("long", 0.70), "BTC/USDT", enabled=True, boost=0.05, damp=0.08,
    )
    assert out.confidence == pytest.approx(0.62)


def test_news_confirmation_hook_skips_when_disabled(session):
    _seed_shadow(session, predicted="up", n_eval=12)
    out = apply_news_confirmation(
        session, _signal("long", 0.70), "BTC/USDT", enabled=False, boost=0.05, damp=0.08,
    )
    assert out.confidence == 0.70


def test_news_confirmation_hook_noop_with_few_signals(session):
    _seed_shadow(session, predicted="up", n_eval=5)  # < min_signals → accuracy None
    out = apply_news_confirmation(
        session, _signal("long", 0.70), "BTC/USDT", enabled=True, boost=0.05, damp=0.08, min_signals=10,
    )
    assert out.confidence == 0.70


# ---------------------------------------------------------------------------
# Backtest → DB
# ---------------------------------------------------------------------------

def test_to_db_record_normalises_units():
    m = {"total_trades": 5, "win_rate": 60.0, "profit_factor": 3.0, "sharpe": 0.97,
         "max_drawdown_pct": -10.0, "total_pnl_pct": 40.0}
    rec = _to_db_record("trend_momentum", "ETH/USDT", m,
                        (datetime(2024, 1, 1), datetime(2026, 7, 1)), "suite_test.csv")
    assert rec["win_rate"] == 0.6
    assert rec["max_drawdown"] == 0.1
    assert rec["total_return_pct"] == 40.0


def test_to_db_record_handles_inf_profit_factor():
    m = {"total_trades": 1, "win_rate": 100.0, "profit_factor": float("inf"),
         "sharpe": 0.0, "max_drawdown_pct": 0.0, "total_pnl_pct": 1.5}
    rec = _to_db_record("trend_momentum", "BTC/USDT", m, None, "s.csv")
    assert rec["profit_factor"] is None
    assert rec["period_start"] is None


def test_backtest_result_saved_to_db(db_factory):
    m = {"total_trades": 5, "win_rate": 60.0, "profit_factor": 3.0, "sharpe": 0.97,
         "max_drawdown_pct": -10.0, "total_pnl_pct": 40.0}
    rec = _to_db_record("trend_momentum", "ETH/USDT", m,
                        (datetime(2024, 1, 1), datetime(2026, 7, 1)), "suite_test.csv")
    assert save_results_to_db([rec], session_factory=db_factory) == 1
    with db_factory() as s:
        rows = s.execute(select(BacktestResult)).scalars().all()
        assert len(rows) == 1
        assert rows[0].strategy_id == "trend_momentum"
        assert rows[0].symbol == "ETH/USDT"
        assert rows[0].win_rate == 0.6


# ---------------------------------------------------------------------------
# status_writer
# ---------------------------------------------------------------------------

def test_status_writer_writes_valid_json(tmp_path):
    path = tmp_path / "bot_status.json"
    write_status(
        mode="dry_run", status="running",
        portfolio={"total_value": 100.0, "profit_factor": None, "signals_today": 3},
        positions=[], recent_trades=[],
        regime={"BTC/USDT": "trending"},
        gates={"risk": True, "regime": True, "dry_run": True},
        strategies={"trend_momentum": {"trades": 2, "win_rate": 0.5, "total_pnl": 1.0}},
        reflection={"loop_c": {"total_signals": 0, "accuracy_by_symbol": {}, "last_signal": None}},
        path=str(path),
    )
    assert path.exists()
    data = json.loads(path.read_text())  # kaster hvis ugyldig JSON
    for key in ["updated_at", "mode", "status", "portfolio", "positions",
                "recent_trades", "regime", "gates", "strategies", "reflection"]:
        assert key in data
    assert data["mode"] == "dry_run"
    assert data["regime"]["BTC/USDT"] == "trending"
    assert data["reflection"]["loop_c"]["total_signals"] == 0
