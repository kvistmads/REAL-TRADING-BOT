"""Tests for Phase 4.1 — News Intelligence (Loop C) + StrategyMemory."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.database import Base, Observation, PromotionAlert, ShadowSignal
from reflection.news import accuracy_tracker, fetcher, shadow_trader
from reflection.strategy_memory import StrategyMemory


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s


class _FakeAnalyst:
    """Returnerer et fast LLM-resultat (liste af dicts) på hvert analyse-kald."""

    def __init__(self, result):
        self.result = result

    def analyse(self, prompt, context_text=""):
        return list(self.result)


class _DummyReporter:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


def _headlines(*_a, **_kw):
    return [{"title": "BTC pumps on ETF news", "published": None, "source": "cryptopanic", "sentiment": None}]


def _shadow(**kw) -> ShadowSignal:
    base = dict(
        symbol="BTC/USDT", predicted_direction="up", confidence=0.7, horizon_hours=24,
        eval_at=datetime.utcnow() - timedelta(hours=1), price_at_signal=100.0,
        news_summary="x", sentiment_scores={}, source="cryptopanic",
    )
    base.update(kw)
    return ShadowSignal(**base)


# ---------------------------------------------------------------------------
# fetcher
# ---------------------------------------------------------------------------

def test_fetcher_returns_empty_list_on_network_failure():
    def _boom(url, headers):
        raise ConnectionError("network down")

    result = fetcher.fetch_headlines("BTC/USDT", opener=_boom)
    assert result == []


# ---------------------------------------------------------------------------
# shadow_trader
# ---------------------------------------------------------------------------

def test_shadow_signal_not_created_below_confidence_threshold(session):
    analyst = _FakeAnalyst([{"predicted_direction": "up", "confidence": 0.50}])
    sig = shadow_trader.generate_shadow_signal(
        "BTC/USDT", analyst, session,
        min_confidence=0.55, fetch_fn=_headlines, price_fn=lambda s: 100.0,
    )
    assert sig is None
    assert session.execute(select(ShadowSignal)).scalars().all() == []


def test_shadow_signal_created_above_threshold(session):
    analyst = _FakeAnalyst([{"predicted_direction": "up", "confidence": 0.70,
                             "sentiment_scores": {"positive": 0.7}}])
    sig = shadow_trader.generate_shadow_signal(
        "BTC/USDT", analyst, session,
        min_confidence=0.55, fetch_fn=_headlines, price_fn=lambda s: 100.0,
    )
    session.commit()
    assert sig is not None
    rows = session.execute(select(ShadowSignal)).scalars().all()
    assert len(rows) == 1
    assert rows[0].predicted_direction == "up"
    assert rows[0].price_at_signal == 100.0


# ---------------------------------------------------------------------------
# accuracy_tracker — evaluering
# ---------------------------------------------------------------------------

def test_evaluator_sets_correct_true_on_matching_direction(session):
    session.add(_shadow(predicted_direction="up", price_at_signal=100.0))
    session.commit()
    # Pris steg 2% → faktisk "up" → matcher forudsigelse.
    n = accuracy_tracker.evaluate_pending(session, price_fn=lambda s: 102.0)
    assert n == 1
    sig = session.execute(select(ShadowSignal)).scalars().one()
    assert sig.actual_direction == "up"
    assert sig.correct is True


def test_evaluator_sets_correct_false_on_wrong_direction(session):
    session.add(_shadow(predicted_direction="up", price_at_signal=100.0))
    session.commit()
    # Pris faldt 1.5% → faktisk "down" → forkert.
    accuracy_tracker.evaluate_pending(session, price_fn=lambda s: 98.5)
    sig = session.execute(select(ShadowSignal)).scalars().one()
    assert sig.actual_direction == "down"
    assert sig.correct is False


# ---------------------------------------------------------------------------
# accuracy_tracker — rapport + promotion
# ---------------------------------------------------------------------------

def test_accuracy_tracker_calculates_correctly(session):
    for i in range(10):
        session.add(_shadow(correct=(i < 7), actual_direction="up"))  # 7 af 10 rigtige
    session.commit()
    report = accuracy_tracker.get_accuracy_report(session)
    assert report["total"] == 10
    assert report["correct"] == 7
    assert report["accuracy"] == 0.7


def test_no_promotion_alert_below_min_signals(session):
    for i in range(15):  # accuracy 80% men kun 15 signaler < 30
        session.add(_shadow(correct=(i < 12), actual_direction="up"))
    session.commit()
    reporter = _DummyReporter()
    sent = accuracy_tracker.check_promotion_alert(session, reporter,
                                                  promotion_accuracy=0.60, promotion_min_signals=30)
    assert sent == 0
    assert reporter.sent == []


def test_promotion_alert_above_threshold(session):
    for i in range(35):  # accuracy ~66% over 35 signaler → alert
        session.add(_shadow(correct=(i < 23), actual_direction="up"))
    session.commit()
    reporter = _DummyReporter()
    sent = accuracy_tracker.check_promotion_alert(session, reporter,
                                                  promotion_accuracy=0.60, promotion_min_signals=30)
    assert sent == 1
    assert len(reporter.sent) == 1
    assert "BTC/USDT" in reporter.sent[0]
    # Én PromotionAlert logget → ingen gentagelse ved næste kald.
    assert len(session.execute(select(PromotionAlert)).scalars().all()) == 1
    assert accuracy_tracker.check_promotion_alert(session, reporter,
                                                  promotion_accuracy=0.60, promotion_min_signals=30) == 0


# ---------------------------------------------------------------------------
# StrategyMemory
# ---------------------------------------------------------------------------

def _obs(**kw) -> Observation:
    base = dict(
        loop="nightly", observation_type="parameter_suggestion",
        strategy_id="trend_momentum", parameter="cross_strength_min",
        current_value=0.02, suggested_value=0.03, evidence={"n": 50},
        confidence=0.9, auto_applied=False,
    )
    base.update(kw)
    return Observation(**base)


def test_strategy_memory_excludes_rejected_params(session):
    session.add(_obs(parameter="rsi_max", suggested_value=70,
                     approved_by_user=False, notes="ingen edge fundet"))
    session.commit()
    ctx = StrategyMemory().build_context("trend_momentum", session)
    assert "Afviste forslag" in ctx
    assert "rsi_max" in ctx


def test_strategy_memory_builds_context_from_applied_changes(session):
    session.add(_obs(parameter="cross_strength_min", auto_applied=True))
    session.commit()
    ctx = StrategyMemory().build_context("trend_momentum", session)
    assert "Auto-applied ændringer" in ctx
    assert "cross_strength_min" in ctx
