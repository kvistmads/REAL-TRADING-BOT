"""Tests for Phase 4 — Learning Loop (reflection/)."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import chromadb
import pytest
import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.database import ABExperiment, Base, Observation, Trade
from reflection import confidence_gate, extractor, nightly
from reflection.ab_tracker import ABTracker
from reflection.applier import ParameterApplier
from reflection.chromadb_store import ObservationStore

GATE_CFG = {
    "auto_apply_threshold": 0.85,
    "telegram_threshold": 0.65,
    "min_sample_for_auto": 30,
    "max_change_pct": 0.20,
    "protected_parameters": [
        "stake_amount", "leverage", "max_open_trades", "sl_pct", "tp_pct", "total_capital",
    ],
    "min_trades_for_analysis": 200,
}


# ---------------------------------------------------------------------------
# confidence_gate
# ---------------------------------------------------------------------------

def test_auto_apply_requires_sufficient_sample():
    # conf=0.90 men n=10 (< 30) → telegram, ikke auto.
    obs = {"parameter": "min_rsi_delta", "confidence": 0.90,
           "current_value": 5, "suggested_value": 6, "evidence": {"n": 10}}
    d = confidence_gate.evaluate(obs, GATE_CFG, total_trades=500)
    assert d.action == "telegram_approval"


def test_protected_parameter_always_report_only():
    obs = {"parameter": "stake_amount", "confidence": 1.0,
           "current_value": 5, "suggested_value": 6, "evidence": {"n": 1000}}
    d = confidence_gate.evaluate(obs, GATE_CFG, total_trades=500)
    assert d.action == "report_only"


def test_under_200_trades_no_auto():
    obs = {"parameter": "min_rsi_delta", "confidence": 0.90,
           "current_value": 5, "suggested_value": 5.5, "evidence": {"n": 50}}
    d = confidence_gate.evaluate(obs, GATE_CFG, total_trades=150)
    assert d.action == "report_only"


def test_change_exceeding_20pct_not_auto():
    # 0.65 → 0.85 = 30.8% ændring → over max_change_pct → falder til telegram.
    obs = {"parameter": "min_confidence", "confidence": 0.90,
           "current_value": 0.65, "suggested_value": 0.85, "evidence": {"n": 50}}
    d = confidence_gate.evaluate(obs, GATE_CFG, total_trades=500)
    assert d.action == "telegram_approval"


def test_auto_apply_when_all_conditions_met():
    obs = {"parameter": "min_rsi_delta", "confidence": 0.90,
           "current_value": 5, "suggested_value": 5.5, "evidence": {"n": 50}}
    d = confidence_gate.evaluate(obs, GATE_CFG, total_trades=500)
    assert d.action == "auto_apply"


# ---------------------------------------------------------------------------
# applier
# ---------------------------------------------------------------------------

def _write_config(path) -> str:
    cfg = {"strategies": {"enabled": ["reversal_context"], "min_confidence": 0.65}}
    p = path / "config.yaml"
    p.write_text(yaml.dump(cfg))
    return str(p)


def _fake_obs(**kw):
    base = dict(id=1, strategy_id="reversal_context", parameter="min_rsi_delta",
                current_value=5, suggested_value=10, evidence={"n": 45}, confidence=0.9,
                auto_applied=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_applier_creates_backup_before_writing(tmp_path):
    cfg_path = _write_config(tmp_path)
    applier = ParameterApplier(audit_path=str(tmp_path / "audit.log"))
    applier.apply(_fake_obs(), cfg_path=cfg_path)
    backups = list(tmp_path.glob("config.yaml.bak.*"))
    assert len(backups) == 1


def test_applier_sets_correct_nested_value(tmp_path):
    cfg_path = _write_config(tmp_path)
    applier = ParameterApplier(audit_path=str(tmp_path / "audit.log"))
    obs = _fake_obs()
    applier.apply(obs, cfg_path=cfg_path)

    cfg = yaml.safe_load(open(cfg_path))
    assert cfg["strategies"]["params"]["reversal_context"]["min_rsi_delta"] == 10
    assert obs.auto_applied is True
    # Uændrede felter bevares.
    assert cfg["strategies"]["min_confidence"] == 0.65


def test_applier_global_parameter_writes_under_strategies(tmp_path):
    cfg_path = _write_config(tmp_path)
    applier = ParameterApplier(audit_path=str(tmp_path / "audit.log"))
    obs = _fake_obs(strategy_id=None, parameter="min_confidence",
                    current_value=0.65, suggested_value=0.70)
    applier.apply(obs, cfg_path=cfg_path)
    cfg = yaml.safe_load(open(cfg_path))
    assert cfg["strategies"]["min_confidence"] == 0.70


# ---------------------------------------------------------------------------
# extractor
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        yield s


def _make_trade(**kw) -> Trade:
    base = dict(
        strategy_id="trend_momentum", symbol="BTC/USDT", side="long",
        entry_price=100.0, exit_price=110.0, sl_price=90.0, tp_price=120.0,
        quantity=1.0, stake_amount=5.0, pnl=5.0, pnl_pct=10.0,
        entry_time=datetime(2026, 7, 20, 9, 30), exit_time=datetime.utcnow(),
        status="closed",
        gate_scores={"regime": {"passed": True, "score": 1.0, "reason": "Trending market (ADX=27)"}},
        market_regime="trending",
        signal_data={"rsi": 61.0, "cross_strength": 0.02},
        dry_run=True,
    )
    base.update(kw)
    return Trade(**base)


def test_extractor_adds_temporal_features(mem_session):
    mem_session.add(_make_trade())
    mem_session.commit()
    df = extractor.extract_closed_trades(mem_session, lookback_days=3650)
    row = df.iloc[0]
    assert row["hour"] == 9
    assert row["weekday"] == 0  # 2026-07-20 er en mandag
    assert row["session"] == "london"


def test_extractor_unpacks_gate_scores(mem_session):
    mem_session.add(_make_trade())
    mem_session.commit()
    df = extractor.extract_closed_trades(mem_session, lookback_days=3650)
    row = df.iloc[0]
    assert row["adx_at_entry"] == 27.0
    assert row["regime_score"] == 1.0
    assert row["meta_rsi"] == 61.0
    assert row["meta_cross_strength"] == 0.02


def test_extractor_counts_only_closed(mem_session):
    mem_session.add(_make_trade())
    mem_session.add(_make_trade(status="open", exit_time=None, pnl_pct=None))
    mem_session.commit()
    assert extractor.count_closed_trades(mem_session) == 1


# ---------------------------------------------------------------------------
# ab_tracker
# ---------------------------------------------------------------------------

def _exp(**kw):
    base = dict(trades_a=40, trades_b=40, profit_factor_a=1.0, profit_factor_b=1.0,
                min_trades_per_arm=30, status="running")
    base.update(kw)
    return SimpleNamespace(**base)


def test_experiment_stays_running_below_min_trades():
    tracker = ABTracker()
    assert tracker.evaluate(_exp(trades_a=10, trades_b=40)) == "running"


def test_experiment_b_wins_above_threshold():
    tracker = ABTracker(significance_threshold=0.10)
    # B's profit factor 1.5 > A's 1.0 * 1.10 → b_wins.
    assert tracker.evaluate(_exp(profit_factor_a=1.0, profit_factor_b=1.5)) == "b_wins"


def test_experiment_inconclusive_below_threshold():
    tracker = ABTracker(significance_threshold=0.10)
    # 1.05 er < 1.0 * 1.10 → hverken A eller B vinder.
    assert tracker.evaluate(_exp(profit_factor_a=1.0, profit_factor_b=1.05)) == "inconclusive"


# ---------------------------------------------------------------------------
# chromadb_store (in-memory)
# ---------------------------------------------------------------------------

def test_store_returns_similar_observations():
    # Unikt collection-navn: EphemeralClient deler ellers state på tværs af tests.
    store = ObservationStore(client=chromadb.EphemeralClient(), collection_name="test_similar")
    store.add(1, "reversal_context underperformer i lav-ADX regimer", {"type": "regime_correlation"})
    store.add(2, "trend_momentum laver ingen forex-trades pga. confidence-gulv", {"type": "parameter_suggestion"})
    results = store.query_similar("forex trend momentum nul trades", n=1)
    assert len(results) == 1
    assert "forex" in results[0]["text"]


def test_store_empty_returns_empty_list():
    store = ObservationStore(client=chromadb.EphemeralClient(), collection_name="test_empty")
    assert store.query_similar("hvad som helst", n=5) == []


# ---------------------------------------------------------------------------
# Loop A — integration (nightly.run_nightly med injicerede afhængigheder)
# ---------------------------------------------------------------------------

class _FakeAnalyst:
    """Returnerer et sæt observationer på første analyse-kald, [] derefter."""

    def __init__(self, batches):
        self._batches = list(batches)

    def analyse(self, prompt, context_text=""):
        return self._batches.pop(0) if self._batches else []


class _DummyReporter:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


def _seed_trades(session_factory, n, *, strategy="trend_momentum", symbol="BTC/USDT",
                 hour=9, regime="trending", weeks_spread=0):
    now = datetime.utcnow()
    with session_factory() as s:
        for i in range(n):
            exit_time = now - timedelta(weeks=(i % (weeks_spread + 1)))
            s.add(Trade(
                strategy_id=strategy, symbol=symbol, side="long",
                entry_price=100.0, exit_price=110.0, sl_price=90.0, tp_price=120.0,
                quantity=1.0, stake_amount=5.0, pnl=1.0 if i % 2 else -1.0,
                pnl_pct=2.0 if i % 2 else -2.0,
                entry_time=datetime(2026, 7, 20, hour, 0), exit_time=exit_time,
                status="closed",
                gate_scores={"regime": {"passed": True, "score": 1.0,
                                        "reason": f"Trending market (ADX=27)"}},
                market_regime=regime,
                signal_data={"cross_strength": 0.02, "rsi": 55.0},
                dry_run=True,
            ))
        s.commit()


@pytest.fixture
def temp_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reflect.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def base_config():
    return yaml.safe_load(open("config.yaml"))


def test_nightly_dispatches_by_gate(tmp_path, temp_db, base_config):
    # 200 lukkede trades → over 200-grænsen, så auto-apply er tilladt.
    _seed_trades(temp_db, 200)
    tmp_cfg = tmp_path / "config.yaml"
    shutil.copy("config.yaml", tmp_cfg)

    observations = [
        {"strategy_id": "reversal_context", "type": "parameter_suggestion",
         "parameter": "min_rsi_delta", "current_value": 5, "suggested_value": 5.5,
         "evidence": {"n": 50}, "confidence": 0.90, "reasoning": "auto"},          # → auto_apply
        {"strategy_id": "trend_momentum", "type": "parameter_suggestion",
         "parameter": "cross_strength_min", "current_value": 0.02, "suggested_value": 0.03,
         "evidence": {"n": 40}, "confidence": 0.70, "reasoning": "tg"},            # → telegram
        {"strategy_id": "volatility_breakout", "type": "parameter_suggestion",
         "parameter": "squeeze_pct", "current_value": 2, "suggested_value": 2.1,
         "evidence": {"n": 15}, "confidence": 0.50, "reasoning": "report"},        # → report_only
    ]
    reporter = _DummyReporter()
    summary = nightly.run_nightly(
        base_config,
        session_factory=temp_db,
        analyst=_FakeAnalyst([observations]),
        store=ObservationStore(client=chromadb.EphemeralClient(), collection_name="test_dispatch"),
        applier=ParameterApplier(audit_path=str(tmp_path / "audit.log")),
        reporter=reporter,
        cfg_path=str(tmp_cfg),
    )

    assert summary["auto_applied"] == 1
    assert summary["pending"] == 1
    assert summary["report_only"] == 1
    assert summary["total_trades"] == 200

    # Auto-apply skrev til (temp-)config'en.
    written = yaml.safe_load(open(tmp_cfg))
    assert written["strategies"]["params"]["reversal_context"]["min_rsi_delta"] == 5.5

    # Alle tre observationer blev persisteret + fik chromadb_id; ét A/B-eksperiment for telegram.
    with temp_db() as s:
        rows = s.execute(select(Observation)).scalars().all()
        assert len(rows) == 3
        assert sum(1 for o in rows if o.auto_applied) == 1
        assert all(o.chromadb_id for o in rows)
        exps = s.execute(select(ABExperiment)).scalars().all()
        assert len(exps) == 1
        assert exps[0].strategy_id == "trend_momentum"


def test_nightly_dry_run_forces_report_only(tmp_path, temp_db, base_config):
    _seed_trades(temp_db, 200)
    tmp_cfg = tmp_path / "config.yaml"
    shutil.copy("config.yaml", tmp_cfg)
    obs = [{"strategy_id": "reversal_context", "type": "parameter_suggestion",
            "parameter": "min_rsi_delta", "current_value": 5, "suggested_value": 5.5,
            "evidence": {"n": 50}, "confidence": 0.99, "reasoning": "would-auto"}]

    summary = nightly.run_nightly(
        base_config, dry_run=True,
        session_factory=temp_db,
        analyst=_FakeAnalyst([obs]),
        store=ObservationStore(client=chromadb.EphemeralClient(), collection_name="test_dryrun"),
        applier=ParameterApplier(audit_path=str(tmp_path / "audit.log")),
        reporter=_DummyReporter(),
        cfg_path=str(tmp_cfg),
    )
    # Trods conf=0.99 → intet auto-applied i dry-run.
    assert summary["auto_applied"] == 0
    assert summary["report_only"] == 1
    # config urørt (min_rsi_delta blev ikke skrevet).
    written = yaml.safe_load(open(tmp_cfg))
    assert "params" not in written.get("strategies", {})


def test_nightly_runs_on_varied_simulated_trades(tmp_path, temp_db, base_config):
    # Flere strategier/symboler/regimer over flere uger → udøver aggregering/korrelation.
    _seed_trades(temp_db, 20, strategy="trend_momentum", symbol="BTC/USDT",
                 hour=9, regime="trending", weeks_spread=3)
    _seed_trades(temp_db, 20, strategy="reversal_context", symbol="ETH/USDT",
                 hour=15, regime="sideways", weeks_spread=3)

    summary = nightly.run_nightly(
        base_config,
        session_factory=temp_db,
        analyst=_FakeAnalyst([]),  # offline-agtig: ingen observationer
        store=ObservationStore(client=chromadb.EphemeralClient(), collection_name="test_varied"),
        applier=ParameterApplier(audit_path=str(tmp_path / "audit.log")),
        reporter=_DummyReporter(),
        cfg_path=str(tmp_path / "unused.yaml"),
    )
    assert summary["trades_analysed"] == 40
    assert Path(summary["report_path"]).exists()


# ---------------------------------------------------------------------------
# Telegram approve/reject-kommandoer
# ---------------------------------------------------------------------------

def _seed_pending_observation(session_factory) -> int:
    with session_factory() as s:
        obs = Observation(
            loop="nightly", observation_type="parameter_suggestion",
            strategy_id="reversal_context", parameter="min_rsi_delta",
            current_value=5, suggested_value=10, evidence={"n": 45}, confidence=0.75,
            auto_applied=False, approved_by_user=None,
        )
        s.add(obs)
        s.commit()
        return obs.id


def test_approve_command_applies_change(tmp_path, temp_db):
    from reflection import telegram_handler

    _seed_pending_observation(temp_db)
    tmp_cfg = tmp_path / "config.yaml"
    shutil.copy("config.yaml", tmp_cfg)

    with temp_db() as s:
        reply = telegram_handler.handle_command(
            "/approve_1", s,
            applier=ParameterApplier(audit_path=str(tmp_path / "audit.log")),
            cfg_path=str(tmp_cfg),
        )
    assert "Godkendt" in reply
    written = yaml.safe_load(open(tmp_cfg))
    assert written["strategies"]["params"]["reversal_context"]["min_rsi_delta"] == 10
    with temp_db() as s:
        obs = s.execute(select(Observation)).scalars().one()
        assert obs.approved_by_user is True
        assert obs.auto_applied is True


def test_reject_command_leaves_config_untouched(tmp_path, temp_db):
    from reflection import telegram_handler

    _seed_pending_observation(temp_db)
    tmp_cfg = tmp_path / "config.yaml"
    shutil.copy("config.yaml", tmp_cfg)

    with temp_db() as s:
        reply = telegram_handler.handle_command("/reject_1", s, cfg_path=str(tmp_cfg))
    assert "Afvist" in reply
    written = yaml.safe_load(open(tmp_cfg))
    assert "params" not in written.get("strategies", {})
    with temp_db() as s:
        obs = s.execute(select(Observation)).scalars().one()
        assert obs.approved_by_user is False


def test_unknown_command_returns_empty(temp_db):
    from reflection import telegram_handler

    with temp_db() as s:
        assert telegram_handler.handle_command("hej bot", s) == ""
