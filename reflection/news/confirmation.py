"""A/B Confirmation Hook (Phase 5 Del C) — justér signal-confidence ud fra news intelligence.

Ren, testbar logik adskilt fra engine'en: engine-metoden ``_apply_news_confirmation``
er en tynd wrapper der henter DB-data og config, og delegerer hertil. Hooket rører kun
``signal.confidence`` (aldrig kapital) og er som standard slået fra i config.

Retnings-mapping: teknisk ``side`` "long"→"up", "short"→"down". Matcher det seneste
shadow signal vores retning → +boost; er de uenige → -damp; er shadow "neutral" (eller
mangler) → ingen ændring. Aktiveres kun når accuracy for symbolet er kendt (nok signals).
"""

from __future__ import annotations

import logging

from reflection.news.accuracy_tracker import get_latest_shadow_signal, get_symbol_accuracy

logger = logging.getLogger(__name__)

_SIDE_TO_DIR = {"long": "up", "short": "down", "buy": "up", "sell": "down"}


def apply_news_confirmation(
    session,
    signal,
    symbol: str,
    *,
    enabled: bool,
    boost: float = 0.05,
    damp: float = 0.08,
    min_signals: int = 10,
):
    """Justér ``signal.confidence`` baseret på news intelligence. Returnér signalet.

    No-op (returnerer uændret) hvis: hooket er slået fra, signal er None, accuracy er
    ukendt (for få evaluerede signals), eller der ikke findes et retningsgivende
    seneste shadow signal for symbolet.
    """
    if not enabled or signal is None:
        return signal

    accuracy = get_symbol_accuracy(session, symbol, min_signals=min_signals)
    if accuracy is None:
        return signal  # for få signals — ingen justering

    latest = get_latest_shadow_signal(session, symbol)
    if latest is None:
        return signal

    want = _SIDE_TO_DIR.get(str(signal.side).lower())
    if want is None:
        return signal

    if latest.predicted_direction == want:
        signal.confidence = min(1.0, signal.confidence + boost)
        logger.info("News confirmation: %s confidence +%.0f%% (acc %.0f%%)", symbol, boost * 100, accuracy * 100)
    elif latest.predicted_direction in ("up", "down"):
        signal.confidence = max(0.0, signal.confidence - damp)
        logger.info("News conflict: %s confidence -%.0f%% (acc %.0f%%)", symbol, damp * 100, accuracy * 100)

    return signal
