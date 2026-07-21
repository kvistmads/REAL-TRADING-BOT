from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal


class BollingerSqueeze(BaseStrategy):
    name = "bollinger_squeeze"
    timeframe = "4h"
    min_confidence = 0.63

    SQUEEZE_THRESHOLD = 0.8  # BandWidth < SMA(BandWidth) * threshold

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal | None:
        upper_col = "BBU_20_2.0"
        lower_col = "BBL_20_2.0"
        mid_col = "BBM_20_2.0"

        if any(c not in df.columns for c in [upper_col, lower_col, mid_col]):
            return None
        if len(df) < 25:
            return None

        upper = df[upper_col].values
        lower = df[lower_col].values
        mid = df[mid_col].values
        close = df["close"].values

        bandwidth = (upper - lower) / np.where(mid != 0, mid, 1)

        bw_series = pd.Series(bandwidth)
        bw_sma = bw_series.rolling(20).mean().values

        if np.isnan(bw_sma[-1]) or np.isnan(bandwidth[-1]):
            return None

        squeeze_active = bandwidth[-1] < bw_sma[-1] * self.SQUEEZE_THRESHOLD

        if not squeeze_active:
            return None

        # Long: close bryder over upper band
        if close[-1] > upper[-1]:
            distance = (close[-1] - upper[-1]) / upper[-1]
            confidence = min(0.63 + distance * 10, 1.0)
            if confidence >= self.min_confidence:
                return Signal(
                    strategy_id=self.name,
                    symbol=symbol,
                    side="long",
                    confidence=confidence,
                    timeframe=self.timeframe,
                    metadata={
                        "bandwidth": float(bandwidth[-1]),
                        "bw_sma": float(bw_sma[-1]),
                        "breakout_distance": float(distance),
                    },
                )

        # Short: close bryder under lower band
        if close[-1] < lower[-1]:
            distance = (lower[-1] - close[-1]) / lower[-1]
            confidence = min(0.63 + distance * 10, 1.0)
            if confidence >= self.min_confidence:
                return Signal(
                    strategy_id=self.name,
                    symbol=symbol,
                    side="short",
                    confidence=confidence,
                    timeframe=self.timeframe,
                    metadata={
                        "bandwidth": float(bandwidth[-1]),
                        "bw_sma": float(bw_sma[-1]),
                        "breakout_distance": float(distance),
                    },
                )

        return None
