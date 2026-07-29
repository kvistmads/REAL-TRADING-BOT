"""Best-effort web-søgning via stdlib urllib (ingen ny dependency).

Kontrakt: enhver funktion her returnerer en formateret streng ELLER "" — den kaster
ALDRIG. Netværksfejl, timeouts og parse-fejl logges som warning og giver "". Derfor kan
Loop A køre offline/uden netværk uden at fejle.

Web-søgning er som standard slået fra (``reflection.research.web_search`` i config); den
curated ``strategy_db`` dækker offline-behovet. Strategi-research caches i ChromaDB med
7 dages TTL for at undgå gentagne søgninger inden for samme uge.
"""

from __future__ import annotations

import html
import logging
import re
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

SEARCH_QUERIES = {
    "macro": "{period} fed interest rate crypto market reuters bloomberg",
    "strategy": "{strategy_name} parameters optimization backtest crypto forex 2024 2025",
    "symbol": "{symbol} price action analysis {period}",
}

_DDG_HTML = "https://html.duckduckgo.com/html/?q={query}"
_USER_AGENT = "Mozilla/5.0 (compatible; RealTradingBot/1.0; research)"
_TIMEOUT = 8
_CACHE_TTL = 7 * 86400  # 7 dage

# Titel-links i DuckDuckGo's HTML-endpoint: <a class="result__a" ...>TITLE</a>.
_RESULT_RE = re.compile(r'class="result__a"[^>]*>(.*?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _default_opener(url: str, headers: dict) -> str:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _clean(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub("", fragment)).strip()


def _search(query: str, top_n: int, opener=None) -> list[str]:
    """Kør én søgning, returnér op til top_n rensede resultat-titler. [] ved enhver fejl."""
    opener = opener or _default_opener
    url = _DDG_HTML.format(query=urllib.parse.quote(query))
    try:
        body = opener(url, {"User-Agent": _USER_AGENT})
    except Exception as e:
        logger.warning("Web-søgning fejlede (%s): %s", query[:40], e)
        return []
    titles = [_clean(m) for m in _RESULT_RE.findall(body or "")]
    return [t for t in titles if t][:top_n]


def search_macro_context(period_str: str, *, opener=None) -> str:
    """Søg efter makro-events i analyse-perioden. Top-3 titler eller "" ved fejl."""
    query = SEARCH_QUERIES["macro"].format(period=period_str)
    titles = _search(query, 3, opener=opener)
    if not titles:
        return ""
    lines = [f"Web makro-kontekst ({period_str}):"]
    lines.extend(f"- {t}" for t in titles)
    return "\n".join(lines)


def _cache_get(store, cache_id: str) -> str | None:
    if store is None:
        return None
    try:
        res = store.collection.get(ids=[cache_id])
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        if docs and docs[0]:
            ts = float((metas[0] or {}).get("ts", 0)) if metas else 0.0
            if time.time() - ts < _CACHE_TTL:
                return docs[0]
    except Exception as e:  # cache er best-effort
        logger.debug("Web-cache læsning fejlede: %s", e)
    return None


def _cache_put(store, cache_id: str, text: str) -> None:
    if store is None or not text:
        return
    try:
        store.collection.upsert(
            ids=[cache_id],
            documents=[text],
            metadatas=[{"kind": "web_cache", "ts": time.time()}],
        )
    except Exception as e:  # cache er best-effort
        logger.debug("Web-cache skrivning fejlede: %s", e)


def search_strategy_research(strategy_id: str, *, store=None, opener=None) -> str:
    """Søg efter ekstern viden om strategi-typen. Caches i ChromaDB (7 dages TTL).

    Returnerer "" ved netværksfejl eller hvis intet blev fundet.
    """
    cache_id = f"webcache_strategy_{strategy_id}"
    cached = _cache_get(store, cache_id)
    if cached is not None:
        return cached

    query = SEARCH_QUERIES["strategy"].format(strategy_name=strategy_id.replace("_", " "))
    titles = _search(query, 3, opener=opener)
    if not titles:
        return ""
    text = "\n".join([f"Web strategi-research ({strategy_id}):", *(f"- {t}" for t in titles)])
    _cache_put(store, cache_id, text)
    return text
