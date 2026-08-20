"""Signal-analyse til Loop A (Ændring 10).

Loop A analyserede kun LUKKEDE trades. Med 0 trades — som nu, hvor gates afviser
alt — kørte reflektionen reelt aldrig, selvom SignalLog var fuld af data om hvad
botten *ville* have handlet. Denne analyse kører uanset antal trades og svarer på:
hvor mange signaler blev genereret, hvilke gates afviste dem, og hvor stærke var de?

Rene funktioner mod en synkron session — ingen Anthropic, intet netværk.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from core.database import SignalLog
from core.time_utils import utc_now

logger = logging.getLogger(__name__)


def _as_dict(value: Any) -> dict:
    """gate_scores kommer som dict via JSON-kolonnen, men tål også en JSON-streng."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _first_failing_gate(gate_scores: Any) -> str | None:
    """Navnet på den gate der afviste signalet. Engine bryder ved første blocking
    afvisning, så den første ikke-beståede gate er årsagen."""
    for name, data in _as_dict(gate_scores).items():
        if isinstance(data, dict) and not data.get("passed", True):
            return name
    return None


def analyze_signals(session, lookback_days: int) -> dict:
    """Analysér SignalLog for perioden. Kører uanset antal lukkede trades."""
    cutoff = utc_now() - timedelta(days=lookback_days)
    signals = (
        session.execute(select(SignalLog).where(SignalLog.timestamp >= cutoff))
        .scalars()
        .all()
    )
    if not signals:
        return {"total": 0}

    total = len(signals)
    passed = [s for s in signals if s.gate_passed]
    rejected = [s for s in signals if not s.gate_passed]

    rejection_reasons: Counter = Counter()
    unknown = 0
    for s in rejected:
        gate = _first_failing_gate(s.gate_scores)
        if gate:
            rejection_reasons[gate] += 1
        else:
            unknown += 1
    if unknown:
        # Signaler logget før gate_scores-kolonnen fandtes (eller afvist uden scores).
        rejection_reasons["ukendt"] = unknown

    confidences = [s.confidence for s in signals]
    return {
        "total": total,
        "passed": len(passed),
        "rejected": len(rejected),
        "pass_rate_pct": round(len(passed) / total * 100, 1),
        "by_strategy": dict(Counter(s.strategy_id for s in signals).most_common()),
        "by_symbol": dict(Counter(s.symbol for s in signals).most_common()),
        "avg_confidence": round(sum(confidences) / total, 3),
        "max_confidence": round(max(confidences), 3),
        "rejection_reasons": dict(rejection_reasons.most_common()),
    }


def format_signal_section(stats: dict, lookback_days: int) -> str:
    """Markdown-afsnit til nightly-rapporten. Tom analyse → stadig et afsnit."""
    lines = [f"## Signal-analyse (seneste {lookback_days} dage)"]
    if not stats or not stats.get("total"):
        lines.append("- Ingen signaler genereret i perioden.")
        return "\n".join(lines)

    lines += [
        f"- Total genererede signals: {stats['total']}",
        f"- Passerede gates: {stats['passed']} ({stats['pass_rate_pct']}%)",
        f"- Afviste: {stats['rejected']}",
        f"- Afvisningsårsager: {_kv(stats.get('rejection_reasons'))}",
        f"- Pr. strategi: {_kv(stats.get('by_strategy'))}",
        f"- Pr. symbol: {_kv(stats.get('by_symbol'))}",
        f"- Gennemsnitlig confidence: {stats['avg_confidence']} "
        f"(højeste: {stats['max_confidence']})",
    ]
    return "\n".join(lines)


def format_signal_telegram(stats: dict) -> str:
    """Én-til-to linjer til nightly-Telegrambeskeden."""
    if not stats or not stats.get("total"):
        return "📊 Signals: ingen genereret i perioden"
    line = (
        f"📊 Signals: {stats['total']} genereret, {stats['passed']} passerede "
        f"({stats['pass_rate_pct']}% pass-rate)"
    )
    if stats.get("rejection_reasons"):
        line += f"\nGate-afvisninger: {_kv(stats['rejection_reasons'])}"
    return line


def _kv(mapping: dict | None) -> str:
    if not mapping:
        return "ingen"
    return ", ".join(f"{k}={v}" for k, v in mapping.items())
