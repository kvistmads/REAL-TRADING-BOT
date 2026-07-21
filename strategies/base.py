from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class Signal:
    strategy_id: str
    symbol: str
    side: str  # "long" | "short"
    confidence: float  # 0.0–1.0
    timeframe: str
    metadata: dict
    sl_price: float | None = None
    tp_price: float | None = None


class BaseStrategy(ABC):
    name: str
    timeframe: str
    min_confidence: float = 0.60

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal | None:
        """
        df: OHLCV DataFrame med indikatorer beregnet
        symbol: e.g. "BTC/USDT"
        Returnerer Signal eller None. Må IKKE kalde exchange eller DB.
        """

    @staticmethod
    def get_asset_class(symbol: str) -> str:
        if symbol in ("EUR/USD", "GBP/USD"):
            return "forex"
        if symbol == "XAU/USD":
            return "gold"
        return "crypto"
