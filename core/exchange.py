from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime

import ccxt.async_support as ccxt
import pandas as pd

from strategies.base import Signal

logger = logging.getLogger(__name__)


class ExchangeClient:
    def __init__(self, config: dict):
        self.dry_run: bool = config["trading"]["dry_run"]
        self.exchange = ccxt.binance({
            "apiKey": config["exchange"].get("api_key", os.getenv("EXCHANGE_API_KEY", "")),
            "secret": config["exchange"].get("api_secret", os.getenv("EXCHANGE_API_SECRET", "")),
            "options": {"defaultType": "future"},
        })
        if config["exchange"].get("sandbox", True):
            self.exchange.set_sandbox_mode(True)

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        data = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        return df

    async def fetch_ticker(self, symbol: str) -> dict:
        return await self.exchange.fetch_ticker(symbol)

    async def place_order(
        self, signal: Signal, size: float, sl_price: float, tp_price: float
    ) -> dict:
        if self.dry_run:
            logger.warning(
                f"DRY-RUN: ville have åbnet {signal.side} {signal.symbol} "
                f"size={size:.6f} confidence={signal.confidence:.2f} "
                f"sl={sl_price:.4f} tp={tp_price:.4f}"
            )
            return self._simulate_order(signal, size, sl_price, tp_price)

        side = "buy" if signal.side == "long" else "sell"
        return await self.exchange.create_order(
            symbol=signal.symbol,
            type="market",
            side=side,
            amount=size,
            params={"stopLoss": sl_price, "takeProfit": tp_price},
        )

    async def fetch_balance(self) -> dict:
        if self.dry_run:
            return {"USDT": {"free": 100.0, "total": 100.0}}
        return await self.exchange.fetch_balance()

    async def fetch_positions(self) -> list:
        if self.dry_run:
            return []
        return await self.exchange.fetch_positions()

    async def cancel_order(self, order_id: str, symbol: str) -> dict:
        if self.dry_run:
            return {"id": order_id, "status": "cancelled"}
        return await self.exchange.cancel_order(order_id, symbol)

    async def close(self) -> None:
        await self.exchange.close()

    def _simulate_order(self, signal: Signal, size: float, sl_price: float, tp_price: float) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "symbol": signal.symbol,
            "side": "buy" if signal.side == "long" else "sell",
            "type": "market",
            "amount": size,
            "price": None,
            "average": None,
            "status": "closed",
            "timestamp": datetime.utcnow().isoformat(),
            "dry_run": True,
            "sl_price": sl_price,
            "tp_price": tp_price,
        }
