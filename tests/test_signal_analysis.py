"""
Tests for signal-analysen i Loop A (Ændring 10).

Med 0 lukkede trades kørte reflektionen reelt aldrig — selvom SignalLog var fuld
af data om hvad botten ville have handlet, og hvilke gates der stoppede den.
Analysen her skal derfor køre uanset antal trades og altid ende i rapporten.
"""
from __future__ import annotations

import shutil
from datetime import timedelta

import chromadb
import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, SignalLog
from core.time_utils import utc_now
from reflection import nightly
from reflection.chromadb_store import ObservationStore
from reflection.reporter import format_nightly_telegram, write_nightly_report
from reflection.signal_analyzer import (
    analyze_signals,
    format_signal_section,
    format_signal_telegram,
)


# Rummeligt vindue til de tests der bare skal have ALT med. Den skarpe
# 24-timers-grænse fra config testes separat i TestLookbackVindue.
WIDE_WINDOW_H = 720  # 30 døgn i timer


@pytest.fixture
def temp_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'signals.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def base_config():
    return yaml.safe_load(open("config.yaml"))


def _seed(session_factory, n: int, *, strategy="trend_momentum", symbol="BTC/USDT",
          passed=False, gate="regime", confidence=0.5, days_ago=1, hours_ago=None,
          gate_scores=None):
    with session_factory() as s:
        for _ in range(n):
            if gate_scores is None:
                scores = {"risk": {"passed": True, "score": 1.0, "reason": "ok"}}
                if not passed:
                    scores[gate] = {"passed": False, "score": 0.0, "reason": "afvist"}
            else:
                scores = gate_scores
            s.add(SignalLog(
                strategy_id=strategy, symbol=symbol, side="long", confidence=confidence,
                timeframe="4h", signal_metadata={},
                timestamp=utc_now() - (timedelta(hours=hours_ago) if hours_ago is not None
                                       else timedelta(days=days_ago)),
                gate_passed=passed, gate_scores=scores,
            ))
        s.commit()


class TestAnalyzeSignals:
    def test_ingen_signaler_giver_total_nul(self, temp_db):
        with temp_db() as s:
            assert analyze_signals(s, WIDE_WINDOW_H) == {"total": 0}

    def test_taeller_passerede_og_afviste(self, temp_db):
        _seed(temp_db, 8, passed=False)
        _seed(temp_db, 2, passed=True)
        with temp_db() as s:
            stats = analyze_signals(s, WIDE_WINDOW_H)
        assert stats["total"] == 10
        assert stats["passed"] == 2
        assert stats["rejected"] == 8
        assert stats["pass_rate_pct"] == 20.0

    def test_afvisningsaarsager_taelles_fra_gate_scores(self, temp_db):
        _seed(temp_db, 42, gate="regime")
        _seed(temp_db, 5, gate="risk")
        with temp_db() as s:
            stats = analyze_signals(s, WIDE_WINDOW_H)
        assert stats["rejection_reasons"] == {"regime": 42, "risk": 5}

    def test_kun_foerste_fejlende_gate_taelles(self, temp_db):
        """Engine bryder ved første blocking afvisning — årsagen er én gate."""
        _seed(temp_db, 3, gate_scores={
            "regime": {"passed": False, "reason": "sideways"},
            "risk": {"passed": False, "reason": "max trades"},
        })
        with temp_db() as s:
            stats = analyze_signals(s, WIDE_WINDOW_H)
        assert stats["rejection_reasons"] == {"regime": 3}

    def test_signaler_uden_gate_scores_bliver_ukendt(self, temp_db):
        _seed(temp_db, 4, gate_scores={})
        with temp_db() as s:
            stats = analyze_signals(s, WIDE_WINDOW_H)
        assert stats["rejection_reasons"] == {"ukendt": 4}

    def test_gate_scores_som_json_streng_haandteres(self, temp_db):
        _seed(temp_db, 2, gate_scores='{"regime": {"passed": false}}')
        with temp_db() as s:
            stats = analyze_signals(s, WIDE_WINDOW_H)
        assert stats["rejection_reasons"] == {"regime": 2}

    def test_fordeling_pr_strategi(self, temp_db):
        _seed(temp_db, 23, strategy="reversal_context")
        _seed(temp_db, 18, strategy="volatility_breakout")
        _seed(temp_db, 6, strategy="trend_momentum")
        with temp_db() as s:
            stats = analyze_signals(s, WIDE_WINDOW_H)
        assert stats["by_strategy"] == {
            "reversal_context": 23, "volatility_breakout": 18, "trend_momentum": 6,
        }
        assert list(stats["by_strategy"])[0] == "reversal_context"  # sorteret, størst først

    def test_fordeling_pr_symbol(self, temp_db):
        _seed(temp_db, 3, symbol="BTC/USDT")
        _seed(temp_db, 1, symbol="EUR/USD")
        with temp_db() as s:
            stats = analyze_signals(s, WIDE_WINDOW_H)
        assert stats["by_symbol"] == {"BTC/USDT": 3, "EUR/USD": 1}

    def test_confidence_statistik(self, temp_db):
        _seed(temp_db, 2, confidence=0.40)
        _seed(temp_db, 2, confidence=0.64)
        with temp_db() as s:
            stats = analyze_signals(s, WIDE_WINDOW_H)
        assert stats["avg_confidence"] == 0.52
        assert stats["max_confidence"] == 0.64

    def test_signaler_udenfor_lookback_udelades(self, temp_db):
        _seed(temp_db, 5, days_ago=1)
        _seed(temp_db, 7, days_ago=45)
        with temp_db() as s:
            assert analyze_signals(s, WIDE_WINDOW_H)["total"] == 5


class TestFormattering:
    def _stats(self, temp_db):
        _seed(temp_db, 42, gate="regime", strategy="reversal_context")
        _seed(temp_db, 5, gate="risk", strategy="trend_momentum")
        with temp_db() as s:
            return analyze_signals(s, WIDE_WINDOW_H)

    def test_markdown_afsnit(self, temp_db):
        section = format_signal_section(self._stats(temp_db), WIDE_WINDOW_H)
        assert "## Signal-analyse (seneste 720 timer)" in section
        assert "Total genererede signals: 47" in section
        assert "Passerede gates: 0 (0.0%)" in section
        assert "regime=42, risk=5" in section
        assert "reversal_context=42" in section

    def test_markdown_afsnit_uden_signaler(self):
        assert "Ingen signaler genereret" in format_signal_section({"total": 0}, WIDE_WINDOW_H)

    def test_telegram_linje(self, temp_db):
        text = format_signal_telegram(self._stats(temp_db))
        assert "47 genereret" in text
        assert "0 passerede" in text
        assert "Gate-afvisninger: regime=42, risk=5" in text

    def test_telegram_uden_signaler(self):
        assert "ingen genereret" in format_signal_telegram({"total": 0})

    def test_rapport_indeholder_signal_afsnit_uden_observationer(self, tmp_path, temp_db):
        path = write_nightly_report("2026-08-19", [], reports_dir=str(tmp_path),
                                    signal_stats=self._stats(temp_db), lookback_hours=WIDE_WINDOW_H)
        content = open(path).read()
        assert "## Signal-analyse" in content
        assert "Total genererede signals: 47" in content
        assert "Ingen observationer genereret." in content

    def test_telegram_besked_har_signal_statistik(self, temp_db):
        message = format_nightly_telegram(
            "2026-08-19", 0, [], [], [], "rapport.md", signal_stats=self._stats(temp_db)
        )
        assert message.startswith("🔄 Nightly analyse 2026-08-19 — 0 trades analyseret")
        assert "📊 Signals: 47 genereret" in message


class _DummyReporter:
    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


class _NoopAnalyst:
    def analyse(self, prompt, context_text=""):
        return []


class TestNightlyIntegration:
    def test_nul_trades_giver_stadig_signal_rapport(self, tmp_path, temp_db, base_config):
        """Kernen i Ændring 10: rapporten genereres selv uden en eneste trade."""
        # hours_ago=2: base_config er den RIGTIGE config.yaml, og nightly kører
        # nu på 24 timer — default days_ago=1 ville lande præcis på grænsen.
        _seed(temp_db, 10, gate="regime", hours_ago=2)
        reporter = _DummyReporter()

        summary = nightly.run_nightly(
            base_config,
            session_factory=temp_db,
            analyst=_NoopAnalyst(),
            store=ObservationStore(client=chromadb.EphemeralClient(),
                                   collection_name="test_signals"),
            reporter=reporter,
            cfg_path=str(shutil.copy("config.yaml", tmp_path / "config.yaml")),
            dry_run=True,
        )

        assert summary["trades_analysed"] == 0
        assert summary["signals_analysed"] == 10
        assert summary["signals_passed"] == 0
        assert "📊 Signals: 10 genereret" in reporter.sent[0]
        assert "Gate-afvisninger: regime=10" in reporter.sent[0]
        assert "Total genererede signals: 10" in open(summary["report_path"]).read()

    def test_uden_signaler_naevnes_det_i_rapporten(self, tmp_path, temp_db, base_config):
        reporter = _DummyReporter()
        summary = nightly.run_nightly(
            base_config,
            session_factory=temp_db,
            analyst=_NoopAnalyst(),
            store=ObservationStore(client=chromadb.EphemeralClient(),
                                   collection_name="test_no_signals"),
            reporter=reporter,
            cfg_path=str(shutil.copy("config.yaml", tmp_path / "config.yaml")),
            dry_run=True,
        )
        assert summary["signals_analysed"] == 0
        assert "ingen genereret" in reporter.sent[0]
        assert "Ingen signaler genereret i perioden." in open(summary["report_path"]).read()


class TestLookbackVindue:
    """Nightly kører nu på et 24-timers vindue (config: reflection.nightly.lookback_hours).

    Før så den 30 dage tilbage og rapporterede de samme gamle rækker hver eneste
    nat — 12 signaler fra 11.-12. august blev talt med i seks nætter i træk.
    """

    def test_24t_vindue_udelader_aeldre_signaler(self, temp_db):
        _seed(temp_db, 3, hours_ago=2)    # inden for vinduet
        _seed(temp_db, 9, hours_ago=48)   # to døgn gammelt — skal IKKE tælles med
        with temp_db() as s:
            assert analyze_signals(s, 24)["total"] == 3

    def test_bredere_vindue_tager_de_gamle_med(self, temp_db):
        _seed(temp_db, 3, hours_ago=2)
        _seed(temp_db, 9, hours_ago=48)
        with temp_db() as s:
            assert analyze_signals(s, 72)["total"] == 12

    def test_afsnit_navngiver_vinduet_i_timer(self, temp_db):
        _seed(temp_db, 1, hours_ago=1)
        with temp_db() as s:
            section = format_signal_section(analyze_signals(s, 24), 24)
        assert "## Signal-analyse (seneste 24 timer)" in section
