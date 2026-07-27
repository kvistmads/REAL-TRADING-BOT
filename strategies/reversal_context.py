from __future__ import annotations

import numpy as np
import pandas as pd

from data.indicators import (
    calculate_ema,
    calculate_rsi,
    calculate_volume_ma,
    clamp,
    find_swing_points,
)
from strategies.base import BaseStrategy, Signal


class ReversalContext(BaseStrategy):
    """
    Composite 2 (absorberer rsi_divergence).

    RSI-divergens over de seneste 30 barer, kun taget hvis den peger MOD den
    herskende EMA50/EMA200-trend (kontrarian kontekst), og bekræftet af volume
    på selve swing-baren. Begge kontekst- og volume-checks er hårde gates.
    """

    name = "reversal_context"
    timeframe = "4h"
    min_confidence = 0.65

    MIN_BARS = 30
    LOOKBACK = 30
    SWING_WINDOW = 5
    # Overrideable via params (A/B): gate-tærskel på volume-spike ift. MA, minimum
    # RSI-divergens-delta og confidence-gulv. Defaults = uændret Phase 3-adfærd.
    MIN_VOLUME_RATIO = 1.2
    MIN_RSI_DELTA = 5.0

    def generate_signal(
        self, df: pd.DataFrame, symbol: str, params: dict | None = None
    ) -> Signal | None:
        p = params or {}
        min_volume_ratio = p.get("min_volume_ratio", self.MIN_VOLUME_RATIO)
        min_rsi_delta = p.get("min_rsi_delta", self.MIN_RSI_DELTA)
        min_conf = p.get("min_confidence", self.min_confidence)

        if len(df) < self.MIN_BARS:
            return None

        rsi = calculate_rsi(df, 14)
        ema50 = calculate_ema(df, 50)
        ema200 = calculate_ema(df, 200)
        vol_ma = calculate_volume_ma(df, 20)

        recent = df.iloc[-self.LOOKBACK:]
        rsi_recent = rsi.iloc[-self.LOOKBACK:].to_numpy(dtype=float)
        vol_recent = recent["volume"].to_numpy(dtype=float)
        vol_ma_recent = vol_ma.iloc[-self.LOOKBACK:].to_numpy(dtype=float)
        low_recent = recent["low"].to_numpy(dtype=float)
        high_recent = recent["high"].to_numpy(dtype=float)

        ema_50 = float(ema50.iloc[-1])
        ema_200 = float(ema200.iloc[-1])
        if np.isnan(ema_50) or np.isnan(ema_200):
            return None

        swing_highs, swing_lows = find_swing_points(
            pd.Series(low_recent), self.SWING_WINDOW
        )
        # Swing highs skal findes på high-serien for bearish-siden.
        high_swings, _ = find_swing_points(pd.Series(high_recent), self.SWING_WINDOW)

        # --- Bullish divergens: lower low i pris, higher low i RSI ---
        if len(swing_lows) >= 2:
            sw1, sw2 = swing_lows[-2], swing_lows[-1]
            price1, price2 = low_recent[sw1], low_recent[sw2]
            rsi1, rsi2 = rsi_recent[sw1], rsi_recent[sw2]
            if not (np.isnan(rsi1) or np.isnan(rsi2)):
                if price2 < price1 and rsi2 > rsi1:
                    signal = self._build(
                        symbol, "long", ema_50, ema_200,
                        price1, price2, rsi1, rsi2, rsi2 - rsi1,
                        vol_recent[sw2], vol_ma_recent[sw2],
                        min_volume_ratio, min_rsi_delta, min_conf,
                    )
                    if signal is not None:
                        return signal

        # --- Bearish divergens: higher high i pris, lower high i RSI ---
        if len(high_swings) >= 2:
            sw1, sw2 = high_swings[-2], high_swings[-1]
            price1, price2 = high_recent[sw1], high_recent[sw2]
            rsi1, rsi2 = rsi_recent[sw1], rsi_recent[sw2]
            if not (np.isnan(rsi1) or np.isnan(rsi2)):
                if price2 > price1 and rsi2 < rsi1:
                    signal = self._build(
                        symbol, "short", ema_50, ema_200,
                        price1, price2, rsi1, rsi2, rsi1 - rsi2,
                        vol_recent[sw2], vol_ma_recent[sw2],
                        min_volume_ratio, min_rsi_delta, min_conf,
                    )
                    if signal is not None:
                        return signal

        return None

    def _build(self, symbol, side, ema_50, ema_200, price1, price2,
               rsi1, rsi2, rsi_delta, volume, volume_ma_20,
               min_volume_ratio, min_rsi_delta, min_conf) -> Signal | None:
        # Kontekst-gate: divergens skal pege mod trenden.
        if side == "long" and not (ema_50 < ema_200):
            return None
        if side == "short" and not (ema_50 > ema_200):
            return None

        # Divergens-gate: RSI-deltaet skal være mindst min_rsi_delta.
        if rsi_delta < min_rsi_delta:
            return None

        # Volume-gate på seneste swing-bar.
        if np.isnan(volume) or np.isnan(volume_ma_20) or volume_ma_20 <= 0:
            return None
        volume_ratio = volume / volume_ma_20
        if volume <= min_volume_ratio * volume_ma_20:
            return None

        divergence_strength = clamp(rsi_delta / 20, 0, 1)
        volume_strength = clamp((volume_ratio - 1.2) / 0.8, 0, 1)
        confidence = clamp(
            0.45 + 0.30 * divergence_strength + 0.25 * volume_strength, 0.0, 1.0
        )
        if confidence < min_conf:
            return None

        return Signal(
            strategy_id=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            timeframe=self.timeframe,
            metadata={
                "rsi_first_swing": float(rsi1),
                "rsi_second_swing": float(rsi2),
                "rsi_delta": float(rsi_delta),
                "price_first_swing": float(price1),
                "price_second_swing": float(price2),
                "ema_50": float(ema_50),
                "ema_200": float(ema_200),
                "trend_context": "downtrend" if side == "long" else "uptrend",
                "volume": float(volume),
                "volume_ma_20": float(volume_ma_20),
                "volume_ratio": float(volume_ratio),
                "divergence_strength": float(divergence_strength),
                "volume_strength": float(volume_strength),
            },
        )
