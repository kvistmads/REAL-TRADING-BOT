"""Tests for A/B arm-assignment fix (execution/ab_router.py + params-injection).

Dækker PRD Opgave 6: router-tildeling, trade-tagging/tællere og at strategierne
respekterer params-overrides uden at ændre default-adfærd.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import ABExperiment, Base, Observation, Trade
from execution import ab_router
from execution.ab_router import ArmAssignment, get_assignment, record_trade_arm
from strategies.reversal_context import ReversalContext
from strategies.trend_momentum import TrendMomentum
from strategies.volatility_breakout import VolatilityBreakout
from tests.fixtures.ohlcv import rev_bullish_long, tm_long_signal, vb_long_breakout


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_experiment(factory, *, strategy_id="reversal_context",
                     parameter="min_rsi_delta", value_a=5, value_b=15,
                     status="running") -> int:
    """Opret en observation + et A/B-eksperiment. Returnér experiment-id."""
    with factory() as s:
        obs = Observation(
            loop="nightly", observation_type="parameter_suggestion",
            strategy_id=strategy_id, parameter=parameter,
            current_value=value_a, suggested_value=value_b,
        )
        s.add(obs)
        s.flush()
        exp = ABExperiment(
            observation_id=obs.id, strategy_id=strategy_id, parameter=parameter,
            value_a=value_a, value_b=value_b, status=status,
        )
        s.add(exp)
        s.commit()
        return exp.id


def _seed_trade(factory, **kw) -> str:
    base = dict(
        strategy_id="reversal_context", symbol="BTC/USDT", side="long",
        entry_price=100.0, sl_price=90.0, tp_price=120.0, quantity=1.0,
        stake_amount=5.0, entry_time=datetime.utcnow(), status="open",
    )
    base.update(kw)
    with factory() as s:
        trade = Trade(**base)
        s.add(trade)
        s.commit()
        return trade.id


# ---------------------------------------------------------------------------
# get_assignment
# ---------------------------------------------------------------------------

def test_no_assignment_when_no_active_experiment(db):
    # Tom DB → ingen tildeling.
    assert get_assignment("reversal_context", session_factory=db) is None


def test_only_running_experiments_are_assigned(db):
    _seed_experiment(db, status="b_wins")
    assert get_assignment("reversal_context", session_factory=db) is None


def test_assignment_returns_a_or_b(db):
    exp_id = _seed_experiment(db)
    for _ in range(25):
        a = get_assignment("reversal_context", session_factory=db)
        assert a is not None
        assert a.arm in ("A", "B")
        assert a.experiment_id == exp_id


def test_arm_b_carries_params(db, monkeypatch):
    _seed_experiment(db, parameter="min_rsi_delta", value_b=15)
    monkeypatch.setattr(ab_router.random, "random", lambda: 0.0)  # < 0.5 → arm B
    a = get_assignment("reversal_context", session_factory=db)
    assert a.arm == "B"
    assert a.params == {"min_rsi_delta": 15}


def test_arm_a_uses_strategy_defaults(db, monkeypatch):
    _seed_experiment(db)
    monkeypatch.setattr(ab_router.random, "random", lambda: 0.99)  # >= 0.5 → arm A
    a = get_assignment("reversal_context", session_factory=db)
    assert a.arm == "A"
    assert a.params == {}


# ---------------------------------------------------------------------------
# record_trade_arm
# ---------------------------------------------------------------------------

def test_record_trade_arm_increments_counter(db):
    exp_id = _seed_experiment(db)
    trade_id = _seed_trade(db)
    assignment = ArmAssignment(arm="B", params={"min_rsi_delta": 15}, experiment_id=exp_id)

    with db() as s:
        record_trade_arm(trade_id, assignment, s)
        s.commit()

    with db() as s:
        assert s.get(Trade, trade_id).ab_arm == "B"
        exp = s.get(ABExperiment, exp_id)
        assert exp.trades_b == 1
        assert exp.trades_a == 0


def test_record_trade_arm_counts_arm_a(db):
    exp_id = _seed_experiment(db)
    trade_id = _seed_trade(db)
    assignment = ArmAssignment(arm="A", params={}, experiment_id=exp_id)

    with db() as s:
        record_trade_arm(trade_id, assignment, s)
        s.commit()

    with db() as s:
        assert s.get(Trade, trade_id).ab_arm == "A"
        exp = s.get(ABExperiment, exp_id)
        assert exp.trades_a == 1
        assert exp.trades_b == 0


# ---------------------------------------------------------------------------
# Strategi params-injection
# ---------------------------------------------------------------------------

def test_reversal_uses_min_rsi_delta_override():
    # rev_bullish_long har rsi_delta ~21: default-gulvet (5.0) passeres → signal.
    df = rev_bullish_long()
    strat = ReversalContext()
    assert strat.generate_signal(df, "BTC/USDT") is not None
    # Et override-gulv over det faktiske delta filtrerer signalet væk.
    assert strat.generate_signal(df, "BTC/USDT", params={"min_rsi_delta": 25}) is None


def test_reversal_falls_back_to_default_when_no_params():
    df = rev_bullish_long()
    strat = ReversalContext()
    a = strat.generate_signal(df, "BTC/USDT")
    b = strat.generate_signal(df, "BTC/USDT", params=None)
    c = strat.generate_signal(df, "BTC/USDT", params={})
    assert a is not None and b is not None and c is not None
    # params=None / {} ændrer intet ift. default-adfærd.
    assert a.side == b.side == c.side == "long"
    assert a.confidence == b.confidence == c.confidence


@pytest.mark.parametrize(
    "strat, fixture",
    [
        (TrendMomentum(), tm_long_signal),
        (ReversalContext(), rev_bullish_long),
        (VolatilityBreakout(), vb_long_breakout),
    ],
)
def test_min_confidence_override_blocks_all_strategies(strat, fixture):
    df = fixture()
    # Default (0.65) → fixturen producerer et signal.
    assert strat.generate_signal(df, "BTC/USDT") is not None
    # Et loft > 1.0 kan aldrig opfyldes (confidence er clampet til <= 1.0) → None.
    # Beviser at params-override'et rent faktisk bruges som gate.
    assert strat.generate_signal(df, "BTC/USDT", params={"min_confidence": 1.01}) is None


def test_trend_momentum_scale_override_changes_confidence():
    # trend_strength_scale påvirker confidence: en meget lille skala mætter
    # trend_strength → højere confidence end en stor skala. Beviser at BEGGE
    # trend-specifikke overrides trådes igennem.
    df = tm_long_signal()
    strat = TrendMomentum()
    # min_confidence=0.0 fjerner gaten, så vi isolerer skala-effekten på confidence.
    tight = strat.generate_signal(
        df, "BTC/USDT", params={"trend_strength_scale": 0.001, "min_confidence": 0.0}
    )
    wide = strat.generate_signal(
        df, "BTC/USDT", params={"trend_strength_scale": 0.5, "min_confidence": 0.0}
    )
    assert tight is not None and wide is not None
    assert tight.confidence > wide.confidence
