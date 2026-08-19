from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from math import ceil

import pandas as pd

from core.exchange import ExchangeClient
from core.time_utils import utc_now
from data.mt5_fetcher import MT5Fetcher

logger = logging.getLogger(__name__)

_TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}

# ccxt-symbol → yfinance-ticker for forex/gold. backtest/runner.py importerer
# denne konstant, så live og backtest ALDRIG kan divergere.
#
# CME-valutafutures (6E=F/6B=F) og ikke spot (EURUSD=X): yfinance-spot returnerer
# 100% nul-volume, hvilket strukturelt nulstiller volume-gates i reversal_context
# + volatility_breakout. Futures leverer ~96% non-zero volume og en prisskala der
# matcher spot — præcis som guld allerede bruger GC=F.
YFINANCE_SYMBOL_MAP: dict[str, str] = {
    "EUR/USD": "6E=F",
    "GBP/USD": "6B=F",
    "XAU/USD": "GC=F",
}

# ccxt-timeframe → yfinance-interval. yfinance har ingen 4h-barer, så 1h hentes
# og resamples til 4h — identisk med backtest/runner.fetch_forex_ohlcv().
_YF_INTERVAL = {
    "1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "1h", "1d": "1d",
}

# yfinance' maksimale period pr. interval (1m: 7 dage, øvrige intraday: 60/730).
_YF_MAX_DAYS = {"1m": 7, "5m": 60, "15m": 60}
_YF_BAR_HOURS = {"1m": 1 / 60, "5m": 5 / 60, "15m": 0.25, "1h": 1.0, "1d": 24.0}


# Retry-politik for netværkskald: 3 forsøg med 2s/4s backoff. Et enkelt 5xx eller
# en tabt forbindelse må ikke koste et helt tick (næste er 4 timer væk).
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0

REQUIRED_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


def _fetch_with_retry(fetch_fn, max_retries: int = MAX_RETRIES,
                      base_delay: float | None = None, label: str = ""):
    """Kald fetch_fn med exponential backoff. Rejser sidste exception hvis alle fejler.

    Blokerende (time.sleep) — kaldes kun fra tråde via asyncio.to_thread eller fra
    synkron kode, aldrig direkte i event-loopet. base_delay=None læser modulets
    RETRY_BASE_DELAY ved kaldet, så tests kan skrue ventetiden ned.
    """
    base_delay = RETRY_BASE_DELAY if base_delay is None else base_delay
    for attempt in range(max_retries):
        try:
            return fetch_fn()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Fetch fejlede%s (forsøg %d/%d): %s — prøver igen om %.0fs",
                f" for {label}" if label else "", attempt + 1, max_retries, e, delay,
            )
            time.sleep(delay)
    return None


async def _fetch_with_retry_async(fetch_fn, max_retries: int = MAX_RETRIES,
                                  base_delay: float | None = None, label: str = ""):
    """Som _fetch_with_retry, men til awaitables (ccxt async) — sover uden at blokere."""
    base_delay = RETRY_BASE_DELAY if base_delay is None else base_delay
    for attempt in range(max_retries):
        try:
            return await fetch_fn()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Fetch fejlede%s (forsøg %d/%d): %s — prøver igen om %.0fs",
                f" for {label}" if label else "", attempt + 1, max_retries, e, delay,
            )
            await asyncio.sleep(delay)
    return None


def _validate_ohlcv(df: pd.DataFrame | None, symbol: str) -> bool:
    """Sanity-check på en OHLCV-ramme. False → data må ikke bruges til signaler.

    Fanger de fejl der ellers propagerer stille ind i indikatorerne: tomme svar,
    manglende kolonner, NaN-huller og barer der ikke kommer i tidsrækkefølge.
    """
    if df is None or df.empty:
        logger.warning(f"[{symbol}] Tom OHLCV-respons")
        return False

    for col in REQUIRED_OHLCV_COLUMNS:
        if col not in df.columns:
            logger.warning(f"[{symbol}] Mangler kolonne '{col}'")
            return False
        if df[col].isna().any():
            logger.warning(f"[{symbol}] NaN i kolonne '{col}'")
            return False

    # Tidsstempler ligger i 'time'-kolonnen (ccxt/yfinance/MT5 normaliseres alle
    # dertil); falder tilbage på indekset hvis kolonnen mangler.
    stamps = df["time"] if "time" in df.columns else df.index.to_series()
    if not stamps.is_monotonic_increasing:
        logger.warning(f"[{symbol}] Timestamps ikke monotont stigende")
        return False
    return True


def _yf_period(interval: str, bars: int) -> str:
    """Kalendervindue der dækker `bars` barer i `interval`.

    Forex-futures handler ~5 af 7 dage, så vinduet skaleres 1.7x + 3 dages margin
    for weekender/helligdage. Kappes til yfinance' grænse for intervallet.
    """
    days = ceil(bars * _YF_BAR_HOURS[interval] / 24 * 1.7) + 3
    return f"{min(days, _YF_MAX_DAYS.get(interval, 730))}d"


def _fetch_yfinance(symbol: str, timeframe: str, limit: int) -> pd.DataFrame | None:
    """OHLCV for forex/gold via yfinance. Returnerer None ved fejl (aldrig exception).

    Blokerende (urllib) — kaldes via ``asyncio.to_thread`` fra DataFetcher.
    Returnerer kolonnerne time/open/high/low/close/volume, samme format som
    ccxt- og MT5-pathen.
    """
    # Lazy import: yfinance er tung og kun forex/gold-pathen bruger den.
    import yfinance as yf

    ticker = YFINANCE_SYMBOL_MAP.get(symbol)
    if ticker is None:
        return None
    interval = _YF_INTERVAL.get(timeframe)
    if interval is None:
        logger.warning(f"yfinance understøtter ikke timeframe {timeframe} ({symbol})")
        return None

    # Barer der skal hentes FØR resample (4h = 4 × 1h).
    mult = _TIMEFRAME_SECONDS[timeframe] // _TIMEFRAME_SECONDS[interval]
    try:
        raw = _fetch_with_retry(
            lambda: yf.download(ticker, period=_yf_period(interval, limit * mult),
                                interval=interval, auto_adjust=True, progress=False),
            label=f"{symbol} ({ticker})",
        )
    except Exception as e:
        logger.warning(f"yfinance fetch fejlede for {symbol} ({ticker}): {e}")
        return None

    if raw is None or raw.empty:
        logger.warning(f"yfinance returnerede ingen data for {symbol} ({ticker})")
        return None

    try:
        # yfinance >= 0.2 leverer MultiIndex-kolonner (felt × ticker) — flad ud.
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw[["Open", "High", "Low", "Close", "Volume"]]
        if mult > 1:
            df = df.resample(timeframe).agg({
                "Open": "first", "High": "max", "Low": "min",
                "Close": "last", "Volume": "sum",
            }).dropna()
        df = df.tail(limit).copy()
        df.columns = [c.lower() for c in df.columns]
        idx = pd.to_datetime(df.index)
        df.insert(0, "time", idx.tz_convert(None) if idx.tz is not None else idx)
        return df.reset_index(drop=True)
    except Exception as e:
        logger.warning(f"Kunne ikke normalisere yfinance-data for {symbol}: {e}")
        return None


class DataFetcher:
    def __init__(self, exchange: ExchangeClient, config: dict):
        self.exchange = exchange
        self.config = config
        self._cache: dict[str, tuple[pd.DataFrame, datetime]] = {}
        self.mt5 = MT5Fetcher()
        # Forsøg at åbne MT5-forbindelsen ved start; fejler gracefully på Mac/Linux.
        self.mt5_available = self.mt5.initialize()

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame | None:
        key = f"{symbol}:{timeframe}"
        cached_df, cached_at = self._cache.get(key, (None, None))

        if cached_df is not None and cached_at is not None:
            tf_secs = _TIMEFRAME_SECONDS.get(timeframe, 3600)
            age = (utc_now() - cached_at).total_seconds()
            if age < tf_secs:
                return cached_df

        # Forex/gold hentes fra yfinance (samme kilde og mapping som backtesten,
        # og virker på alle platforme); crypto fra ccxt-børsen som før. MT5 bruges
        # kun til live tick-priser når terminalen faktisk kører (Windows).
        if MT5Fetcher.is_forex(symbol):
            df = await asyncio.to_thread(_fetch_yfinance, symbol, timeframe, limit)
        else:
            try:
                df = await _fetch_with_retry_async(
                    lambda: self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit),
                    label=f"{symbol} {timeframe}",
                )
            except Exception as e:
                logger.warning(f"OHLCV-fetch fejlede for {symbol} {timeframe}: {e}")
                return None

        # Fail-safe: ugyldige data caches ikke og bruges ikke — kalderen springer
        # symbolet over denne runde frem for at handle på et hul i serien.
        if not _validate_ohlcv(df, symbol):
            return None

        self._cache[key] = (df, utc_now())
        logger.debug(f"Hentet {len(df)} bars for {symbol} {timeframe}")
        return df

    async def get_latest_price(self, symbol: str) -> float | None:
        """Seneste pris til SL/TP-tjek. Returnerer None ved fejl (aldrig exception).

        Crypto: ccxt-ticker. Forex/gold: MT5-tick hvis terminalen kører, ellers
        seneste yfinance-1h-close (uafhængig af OHLCV-cachen, som har
        timeframe-lang TTL og derfor er for gammel til exit-tjek).
        """
        try:
            if MT5Fetcher.is_forex(symbol):
                if self.mt5_available:
                    price = self.mt5.get_tick_price(symbol)
                    if price is not None:
                        return price
                df = await asyncio.to_thread(_fetch_yfinance, symbol, "1h", 2)
                if df is None or df.empty:
                    return None
                return float(df["close"].iloc[-1])

            ticker = await _fetch_with_retry_async(
                lambda: self.exchange.fetch_ticker(symbol), label=symbol
            )
            last = ticker.get("last") if ticker else None
            return float(last) if last is not None else None
        except Exception as e:
            logger.warning(f"Kunne ikke hente pris for {symbol}: {e}")
            return None

    def shutdown(self) -> None:
        self.mt5.shutdown()

    async def get_multi(self, symbols: list[str], timeframe: str) -> dict[str, pd.DataFrame]:
        tasks = {s: self.get_ohlcv(s, timeframe) for s in symbols}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        out: dict[str, pd.DataFrame] = {}
        for symbol, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"Fejl ved hentning af {symbol}: {result}")
            elif result is None:
                logger.warning(f"Springer {symbol} over — ingen valid data")
            else:
                out[symbol] = result
        return out
