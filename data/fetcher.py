from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import pandas as pd

from core.exchange import ExchangeClient

logger = logging.getLogger(__name__)

_TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}


class DataFetcher:
    def __init__(self, exchange: ExchangeClient, config: dict):
        self.exchange = exchange
        self._cache: dict[str, tuple[pd.DataFrame, datetime]] = {}

    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        key = f"{symbol}:{timeframe}"
        cached_df, cached_at = self._cache.get(key, (None, None))

        if cached_df is not None and cached_at is not None:
            tf_secs = _TIMEFRAME_SECONDS.get(timeframe, 3600)
            age = (datetime.utcnow() - cached_at).total_seconds()
            if age < tf_secs:
                return cached_df

        df = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        self._cache[key] = (df, datetime.utcnow())
        logger.debug(f"Hentet {len(df)} bars for {symbol} {timeframe}")
        return df

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
