from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from math import ceil

import pandas as pd

from core.exchange import ExchangeClient
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
        raw = yf.download(ticker, period=_yf_period(interval, limit * mult),
                          interval=interval, auto_adjust=True, progress=False)
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
            age = (datetime.utcnow() - cached_at).total_seconds()
            if age < tf_secs:
                return cached_df

        # Forex/gold hentes fra yfinance (samme kilde og mapping som backtesten,
        # og virker på alle platforme); crypto fra ccxt-børsen som før. MT5 bruges
        # kun til live tick-priser når terminalen faktisk kører (Windows).
        if MT5Fetcher.is_forex(symbol):
            df = await asyncio.to_thread(_fetch_yfinance, symbol, timeframe, limit)
            if df is None:
                return None
        else:
            df = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

        self._cache[key] = (df, datetime.utcnow())
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

            ticker = await self.exchange.fetch_ticker(symbol)
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
            else:
                out[symbol] = result
        return out
