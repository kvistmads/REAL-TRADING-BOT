"""Evaluerer shadow signals mod faktisk prisbevægelse og sender promotion-alerts.

Ingen kapital involveret — dette måler blot om news-signalerne rammer rigtigt, så vi
(i Phase 5) kan beslutte om et confirmation-hook er værd at aktivere.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select

from core.database import PromotionAlert, ShadowSignal
from core.time_utils import utc_now

logger = logging.getLogger(__name__)

_CRYPTO = {"BTC/USDT", "ETH/USDT", "SOL/USDT"}
# yfinance-tickere for forex/gold (samme mapping som backtest/runner bruger konceptuelt).
_YF_MAP = {"EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "XAU/USD": "GC=F"}


def default_price_fn(symbol: str) -> float | None:
    """Hent seneste pris. Crypto via ccxt (sync), forex/gold via yfinance. None ved fejl."""
    try:
        if symbol in _CRYPTO:
            import ccxt

            ticker = ccxt.binance().fetch_ticker(symbol)
            return float(ticker["last"])
        yf_symbol = _YF_MAP.get(symbol)
        if yf_symbol:
            import yfinance as yf

            hist = yf.Ticker(yf_symbol).history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning("Kunne ikke hente pris for %s: %s", symbol, e)
    return None


def _direction(entry: float, current: float) -> str:
    if current > entry:
        return "up"
    if current < entry:
        return "down"
    return "neutral"


def evaluate_pending(session, price_fn=None, now: datetime | None = None) -> int:
    """Evaluér shadow signals hvor eval_at er passeret og correct endnu er None.

    Sammenligner predicted_direction med den faktiske retning (aktuel pris vs.
    price_at_signal). Signaler uden referencepris eller uden hentbar aktuel pris
    springes over (forbliver pending). Returnér antal evaluerede.
    """
    now = now or utc_now()
    price_fn = price_fn or default_price_fn
    pending = (
        session.execute(
            select(ShadowSignal).where(
                ShadowSignal.correct.is_(None),
                ShadowSignal.eval_at <= now,
            )
        )
        .scalars()
        .all()
    )

    evaluated = 0
    for sig in pending:
        if sig.price_at_signal is None:
            continue
        current = price_fn(sig.symbol)
        if current is None:
            continue
        actual = _direction(sig.price_at_signal, current)
        sig.actual_direction = actual
        sig.correct = actual == sig.predicted_direction
        evaluated += 1
    if evaluated:
        session.flush()
    logger.info("Evaluerede %d shadow signals.", evaluated)
    return evaluated


def get_accuracy_report(session, symbol: str | None = None, min_signals: int = 10) -> dict:
    """Aggreger accuracy over evaluerede shadow signals (correct != None)."""
    query = select(ShadowSignal).where(ShadowSignal.correct.isnot(None))
    if symbol:
        query = query.where(ShadowSignal.symbol == symbol)
    signals = session.execute(query).scalars().all()

    total = len(signals)
    correct = sum(1 for s in signals if s.correct)
    accuracy = round(correct / total, 3) if total else 0.0

    by_symbol: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
    by_source: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})
    for s in signals:
        by_symbol[s.symbol]["total"] += 1
        by_symbol[s.symbol]["correct"] += int(bool(s.correct))
        by_source[s.source]["total"] += 1
        by_source[s.source]["correct"] += int(bool(s.correct))

    def _finalise(d: dict) -> dict:
        return {
            k: {**v, "accuracy": round(v["correct"] / v["total"], 3) if v["total"] else 0.0}
            for k, v in d.items()
        }

    return {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "by_symbol": _finalise(by_symbol),
        "by_source": _finalise(by_source),
        "promotion_eligible": accuracy >= 0.60 and total >= 30 and total >= min_signals,
    }


def get_symbol_accuracy(session, symbol: str, min_signals: int = 10) -> float | None:
    """Accuracy for ét symbol over evaluerede shadow signals, ellers None.

    Returnerer None hvis der er færre end ``min_signals`` evaluerede signaler — så
    confirmation-hooket (Phase 5) ikke justerer på et for tyndt grundlag.
    """
    signals = (
        session.execute(
            select(ShadowSignal).where(
                ShadowSignal.symbol == symbol,
                ShadowSignal.correct.isnot(None),
            )
        )
        .scalars()
        .all()
    )
    total = len(signals)
    if total < min_signals:
        return None
    correct = sum(1 for s in signals if s.correct)
    return round(correct / total, 3)


def get_latest_shadow_signal(session, symbol: str) -> ShadowSignal | None:
    """Seneste shadow signal for symbol (uanset om det er evalueret), ellers None."""
    return (
        session.execute(
            select(ShadowSignal)
            .where(ShadowSignal.symbol == symbol)
            .order_by(ShadowSignal.created_at.desc())
        )
        .scalars()
        .first()
    )


def _format_alert(symbol: str, source: str, accuracy: float, n: int) -> str:
    return (
        f"📡 News Intelligence Alert — {symbol}\n\n"
        f"{source} news-signaler har ramt rigtigt {accuracy:.0%} af {n} forudsigelser.\n\n"
        "Overvej om news-confirmation bør aktiveres for dette symbol.\n"
        f"Aktiver med: /enable_news_confirm {symbol}"
    )


def check_promotion_alert(
    session,
    telegram_reporter,
    promotion_accuracy: float = 0.60,
    promotion_min_signals: int = 30,
) -> int:
    """Send Telegram-alert for hver symbol×kilde med tilstrækkelig accuracy — én gang.

    Sendte alerts logges i PromotionAlert-tabellen for at undgå spam. Returnér antal
    nye alerts sendt.
    """
    signals = (
        session.execute(select(ShadowSignal).where(ShadowSignal.correct.isnot(None)))
        .scalars()
        .all()
    )
    combos: dict[tuple[str, str], dict] = defaultdict(lambda: {"total": 0, "correct": 0})
    for s in signals:
        combos[(s.symbol, s.source)]["total"] += 1
        combos[(s.symbol, s.source)]["correct"] += int(bool(s.correct))

    sent = 0
    for (symbol, source), stats in combos.items():
        n = stats["total"]
        if n < promotion_min_signals:
            continue
        accuracy = stats["correct"] / n
        if accuracy < promotion_accuracy:
            continue
        already = session.execute(
            select(PromotionAlert).where(
                PromotionAlert.symbol == symbol,
                PromotionAlert.source == source,
            )
        ).scalars().first()
        if already is not None:
            continue

        telegram_reporter.send(_format_alert(symbol, source, accuracy, n))
        session.add(PromotionAlert(symbol=symbol, source=source, accuracy=accuracy, n_signals=n))
        sent += 1
    if sent:
        session.flush()
    return sent
