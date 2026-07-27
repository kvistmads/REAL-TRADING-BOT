"""Nyhedskilde-fetcher for Loop C.

Tre gratis kilder, ingen API-key nødvendig undtagen Alpaca:
- CryptoPanic   (crypto-headlines, public feed)
- Fear & Greed  (alternative.me sentiment-indeks)
- Alpaca News   (forex/gold/crypto, kræver ALPACA_API_KEY/SECRET — springes over hvis mangler)

Alle HTTP-kald går via stdlib ``urllib`` (ingen ekstra dep). Fetcheren fejler ALDRIG
loud: en kilde der timeout'er eller returnerer skrald giver en tom liste + en warning,
så Loop C kører videre. Nyheder ældre end 4 timer filtreres fra (allerede prissat ind).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_MAX_AGE_HOURS = 4
_TIMEOUT = 15

# Symbol → hvilke kilder der er relevante. Crypto får CryptoPanic + Fear&Greed;
# forex/gold får kun Alpaca (som er valgfri).
_CRYPTO = {"BTC/USDT", "ETH/USDT", "SOL/USDT"}

SOURCES = {
    "cryptopanic": {
        "url": "https://cryptopanic.com/api/v1/posts/?auth_token=&public=true&kind=news",
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    },
    "fear_greed": {
        "url": "https://api.alternative.me/fng/?limit=1",
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    },
    "alpaca": {
        "url": "https://data.alpaca.markets/v1beta1/news",
        "symbols": ["EUR/USD", "GBP/USD", "XAU/USD", "BTC/USDT"],
        "optional": True,
    },
}


def _http_get(url: str, headers: dict | None = None, opener=None) -> dict | list | None:
    """GET + JSON-parse. Returnér None ved enhver fejl (netværk, non-200, dårlig JSON)."""
    if opener is not None:
        # Test-injektion: opener(url, headers) → rå streng/bytes.
        try:
            raw = opener(url, headers or {})
        except Exception as e:
            logger.warning("News-fetch fejlede (%s): %s", url, e)
            return None
    else:
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                raw = resp.read()
        except Exception as e:
            logger.warning("News-fetch fejlede (%s): %s", url, e)
            return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("News-JSON kunne ikke parses (%s): %s", url, e)
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fresh(published: datetime | None, now: datetime) -> bool:
    """True hvis nyheden er nyere end _MAX_AGE_HOURS (ukendt tid regnes som frisk)."""
    if published is None:
        return True
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return (now - published) <= timedelta(hours=_MAX_AGE_HOURS)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_cryptopanic(now: datetime, opener=None) -> list[dict]:
    data = _http_get(SOURCES["cryptopanic"]["url"], opener=opener)
    if not isinstance(data, dict):
        return []
    out = []
    for post in data.get("results", []) or []:
        published = _parse_iso(post.get("published_at"))
        if not _fresh(published, now):
            continue
        out.append({
            "title": post.get("title", ""),
            "published": published,
            "source": "cryptopanic",
            "sentiment": None,
        })
    return out


def fetch_fear_greed(now: datetime, opener=None) -> list[dict]:
    data = _http_get(SOURCES["fear_greed"]["url"], opener=opener)
    if not isinstance(data, dict):
        return []
    items = data.get("data") or []
    if not items:
        return []
    item = items[0]
    value = item.get("value")
    classification = item.get("value_classification", "")
    # Fear & Greed er et sentiment-indeks, ikke en overskrift — pak det som en "headline".
    sentiment = None
    try:
        v = int(value)
        sentiment = "positive" if v >= 55 else "negative" if v <= 45 else "neutral"
    except (TypeError, ValueError):
        pass
    return [{
        "title": f"Fear & Greed Index: {value} ({classification})",
        "published": now,
        "source": "fear_greed",
        "sentiment": sentiment,
    }]


def fetch_alpaca(symbol: str, now: datetime, opener=None) -> list[dict]:
    key = os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_API_SECRET")
    if not key or not secret:
        logger.warning("Alpaca-nøgler mangler — springer Alpaca-nyheder over for %s.", symbol)
        return []
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    data = _http_get(SOURCES["alpaca"]["url"], headers=headers, opener=opener)
    if not isinstance(data, dict):
        return []
    out = []
    for art in data.get("news", []) or []:
        published = _parse_iso(art.get("created_at") or art.get("updated_at"))
        if not _fresh(published, now):
            continue
        out.append({
            "title": art.get("headline", ""),
            "published": published,
            "source": "alpaca",
            "sentiment": None,
        })
    return out


def fetch_headlines(symbol: str, sources_cfg: dict | None = None,
                    now: datetime | None = None, opener=None) -> list[dict]:
    """Hent friske headlines for ``symbol`` fra de tilgængelige/enablede kilder.

    Returnér liste af {"title", "published", "source", "sentiment"}. Fejler aldrig:
    en kilde der kaster giver [] for den kilde. ``sources_cfg`` styrer hvilke kilder
    der er slået til (default: alle). ``opener`` injiceres i tests.
    """
    now = now or _now()
    sources_cfg = sources_cfg or {}
    headlines: list[dict] = []

    if symbol in _CRYPTO:
        if sources_cfg.get("cryptopanic", True):
            headlines += fetch_cryptopanic(now, opener=opener)
        if sources_cfg.get("fear_greed", True):
            headlines += fetch_fear_greed(now, opener=opener)

    # Alpaca dækker forex/gold (og crypto). Default false — kræver nøgler.
    if sources_cfg.get("alpaca", False) and symbol in SOURCES["alpaca"]["symbols"]:
        headlines += fetch_alpaca(symbol, now, opener=opener)

    return [h for h in headlines if h.get("title")]
