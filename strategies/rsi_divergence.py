from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal


class RSIDivergence(BaseStrategy):
    name = "rsi_divergence"
    timeframe = "4h"
    min_confidence = 0.62

    LOOKBACK_MIN = 5
    LOOKBACK_MAX = 20

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal | None:
        if len(df) < self.LOOKBACK_MAX + 5:
            return None

        rsi_col = "rsi_14"
        if rsi_col not in df.columns:
            return None

        close = df["close"].values
        rsi = df[rsi_col].values

        # Søg bullish divergence: pris lavere low, RSI højere low
        bullish = self._find_bullish_divergence(close, rsi)
        if bullish is not None:
            confidence = bullish
            if confidence >= self.min_confidence:
                return Signal(
                    strategy_id=self.name,
                    symbol=symbol,
                    side="long",
                    confidence=confidence,
                    timeframe=self.timeframe,
                    metadata={"divergence": "bullish", "rsi": float(rsi[-1])},
                )

        # Søg bearish divergence: pris højere high, RSI lavere high
        bearish = self._find_bearish_divergence(close, rsi)
        if bearish is not None:
            confidence = bearish
            if confidence >= self.min_confidence:
                return Signal(
                    strategy_id=self.name,
                    symbol=symbol,
                    side="short",
                    confidence=confidence,
                    timeframe=self.timeframe,
                    metadata={"divergence": "bearish", "rsi": float(rsi[-1])},
                )

        return None

    def _find_bullish_divergence(self, close: np.ndarray, rsi: np.ndarray) -> float | None:
        n = len(close)
        for lookback in range(self.LOOKBACK_MAX, self.LOOKBACK_MIN - 1, -1):
            i = n - 1 - lookback
            if i < 0:
                continue
            if np.isnan(rsi[i]) or np.isnan(rsi[-1]):
                continue
            # Pris: lower low
            price_lower_low = close[-1] < close[i]
            # RSI: higher low
            rsi_higher_low = rsi[-1] > rsi[i]
            if price_lower_low and rsi_higher_low:
                price_diff = abs(close[i] - close[-1]) / close[i]
                rsi_diff = abs(rsi[-1] - rsi[i]) / max(abs(rsi[i]), 1)
                confidence = min(0.62 + (price_diff + rsi_diff) * 2, 1.0)
                return confidence
        return None

    def _find_bearish_divergence(self, close: np.ndarray, rsi: np.ndarray) -> float | None:
        n = len(close)
        for lookback in range(self.LOOKBACK_MAX, self.LOOKBACK_MIN - 1, -1):
            i = n - 1 - lookback
            if i < 0:
                continue
            if np.isnan(rsi[i]) or np.isnan(rsi[-1]):
                continue
            # Pris: higher high
            price_higher_high = close[-1] > close[i]
            # RSI: lower high
            rsi_lower_high = rsi[-1] < rsi[i]
            if price_higher_high and rsi_lower_high:
                price_diff = abs(close[-1] - close[i]) / close[i]
                rsi_diff = abs(rsi[i] - rsi[-1]) / max(abs(rsi[i]), 1)
                confidence = min(0.62 + (price_diff + rsi_diff) * 2, 1.0)
                return confidence
        return None
