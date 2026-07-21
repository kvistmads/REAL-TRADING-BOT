from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import pandas as pd

from core.exchange import ExchangeClient
from data.mt5_fetcher import MT5Fetcher

logger = logging.getLogger(__name__)

_TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}


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

        # Forex/gold hentes fra MT5; crypto fra ccxt-børsen (som før).
        if MT5Fetcher.is_forex(symbol):
            if not self.mt5_available:
                logger.warning(f"MT5 utilgængelig — skipper {symbol} for denne tick")
                return None
            df = self.mt5.get_ohlcv(symbol, timeframe, limit)
            if df is None:
                return None
        else:
            df = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

        self._cache[key] = (df, datetime.utcnow())
        logger.debug(f"Hentet {len(df)} bars for {symbol} {timeframe}")
        return df

    def get_tick_price(self, symbol: str) -> float | None:
        """Aktuel pris for forex/gold via MT5. Returnerer None hvis utilgængelig."""
        if MT5Fetcher.is_forex(symbol) and self.mt5_available:
            return self.mt5.get_tick_price(symbol)
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
