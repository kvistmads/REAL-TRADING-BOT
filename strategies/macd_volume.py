from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal


class MACDVolume(BaseStrategy):
    name = "macd_volume"
    timeframe = "4h"
    min_confidence = 0.60

    VOLUME_MULTIPLIER = 1.5

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal | None:
        required = ["MACD_12_26_9", "MACDs_12_26_9", "MACDh_12_26_9", "volume_sma_20"]
        if any(c not in df.columns for c in required):
            return None
        if len(df) < 3:
            return None

        macd = df["MACD_12_26_9"].values
        signal_line = df["MACDs_12_26_9"].values
        histogram = df["MACDh_12_26_9"].values
        volume = df["volume"].values
        vol_sma = df["volume_sma_20"].values

        if any(np.isnan(v) for v in [macd[-1], macd[-2], signal_line[-1], signal_line[-2], vol_sma[-1]]):
            return None

        volume_confirmed = volume[-1] > self.VOLUME_MULTIPLIER * vol_sma[-1]
        if not volume_confirmed:
            return None

        # Crossover: MACD krydser over signal-linje
        if macd[-2] <= signal_line[-2] and macd[-1] > signal_line[-1]:
            hist_abs = abs(histogram[-1])
            confidence = min(0.60 + hist_abs / (abs(macd[-1]) + 1e-8) * 0.3, 1.0)
            if confidence >= self.min_confidence:
                return Signal(
                    strategy_id=self.name,
                    symbol=symbol,
                    side="long",
                    confidence=confidence,
                    timeframe=self.timeframe,
                    metadata={
                        "macd": float(macd[-1]),
                        "signal": float(signal_line[-1]),
                        "histogram": float(histogram[-1]),
                        "volume_ratio": float(volume[-1] / vol_sma[-1]),
                    },
                )

        # Crossunder: MACD krydser under signal-linje
        if macd[-2] >= signal_line[-2] and macd[-1] < signal_line[-1]:
            hist_abs = abs(histogram[-1])
            confidence = min(0.60 + hist_abs / (abs(macd[-1]) + 1e-8) * 0.3, 1.0)
            if confidence >= self.min_confidence:
                return Signal(
                    strategy_id=self.name,
                    symbol=symbol,
                    side="short",
                    confidence=confidence,
                    timeframe=self.timeframe,
                    metadata={
                        "macd": float(macd[-1]),
                        "signal": float(signal_line[-1]),
                        "histogram": float(histogram[-1]),
                        "volume_ratio": float(volume[-1] / vol_sma[-1]),
                    },
                )

        return None
