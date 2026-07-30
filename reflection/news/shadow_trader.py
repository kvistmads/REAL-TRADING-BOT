"""Genererer shadow signals: LLM-forudsigelse af prisretning ud fra headlines.

En shadow signal er en tracked forudsigelse, ikke et trade. Vi gemmer den og
evaluerer den senere (accuracy_tracker) mod faktisk prisbevægelse.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from core.database import ShadowSignal
from core.time_utils import utc_now
from reflection.news import fetcher

logger = logging.getLogger(__name__)

NEWS_ANALYSIS_PROMPT = """
Du er en kvantitativ makro-analytiker. Nedenfor er de seneste nyhedsoverskrifter for {symbol}.

Vurdér den sandsynlige prisretning for {symbol} over de næste {horizon} timer baseret KUN på disse nyheder.
Ignorer alt hvad du ved om den nuværende tekniske situation.

Svar KUN med JSON:
{{
  "symbol": "{symbol}",
  "predicted_direction": "up" | "down" | "neutral",
  "confidence": float (0.0-1.0),
  "horizon_hours": {horizon},
  "reasoning": "...",
  "sentiment_scores": {{"positive": float, "negative": float, "neutral": float}},
  "key_headlines": ["...", "..."]
}}

Brug "neutral" hvis nyheder er modstridende eller ikke retningsgivende.
Confidence under {min_conf} → brug altid "neutral" (ingen halvhjertet forudsigelse).

HEADLINES ({symbol}, seneste 4 timer):
{headlines}
"""


def _build_prompt(symbol: str, headlines: list[dict], horizon_hours: int, min_confidence: float) -> str:
    lines = "\n".join(f"- [{h['source']}] {h['title']}" for h in headlines) or "(ingen headlines)"
    return NEWS_ANALYSIS_PROMPT.format(
        symbol=symbol, horizon=horizon_hours, min_conf=min_confidence, headlines=lines
    )


def generate_shadow_signal(
    symbol: str,
    analyst,
    session,
    *,
    min_confidence: float = 0.55,
    horizon_hours: int = 24,
    sources_cfg: dict | None = None,
    fetch_fn=None,
    price_fn=None,
    now: datetime | None = None,
) -> ShadowSignal | None:
    """Hent headlines, kald LLM, gem ShadowSignal.

    Returnér None hvis confidence < ``min_confidence`` eller retning == "neutral"
    (eller hvis analysten kører offline og intet svarer). Alle eksterne kald er
    injicerbare (fetch_fn/price_fn/analyst) så testen kan køre uden netværk.
    """
    now = now or utc_now()
    fetch_fn = fetch_fn or fetcher.fetch_headlines
    headlines = fetch_fn(symbol, sources_cfg=sources_cfg)
    if not headlines:
        logger.info("Ingen headlines for %s — intet shadow signal.", symbol)
        return None

    prompt = _build_prompt(symbol, headlines, horizon_hours, min_confidence)
    results = analyst.analyse(prompt, context_text="")
    if not results:
        return None
    pred = results[0]

    direction = str(pred.get("predicted_direction", "neutral")).lower()
    confidence = float(pred.get("confidence", 0) or 0)
    if direction == "neutral" or confidence < min_confidence:
        logger.info("Shadow signal droppet for %s (dir=%s conf=%.2f).", symbol, direction, confidence)
        return None

    price = None
    if price_fn is not None:
        try:
            price = price_fn(symbol)
        except Exception as e:  # pris er best-effort ved oprettelse
            logger.warning("Kunne ikke hente pris for %s: %s", symbol, e)

    horizon = int(pred.get("horizon_hours", horizon_hours) or horizon_hours)
    key_heads = pred.get("key_headlines") or [h["title"] for h in headlines[:3]]
    sources = sorted({h["source"] for h in headlines})
    signal = ShadowSignal(
        created_at=now,
        symbol=symbol,
        predicted_direction=direction,
        confidence=confidence,
        horizon_hours=horizon,
        eval_at=now + timedelta(hours=horizon),
        price_at_signal=price,
        news_summary=" | ".join(str(k) for k in key_heads)[:1000],
        sentiment_scores=pred.get("sentiment_scores", {}) or {},
        source="combined" if len(sources) > 1 else (sources[0] if sources else "combined"),
    )
    session.add(signal)
    session.flush()
    logger.info("Shadow signal: %s %s conf=%.2f (eval %s).", symbol, direction, confidence, signal.eval_at)
    return signal
