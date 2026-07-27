from __future__ import annotations

import numpy as np
import pandas as pd

from data.indicators import (
    calculate_atr,
    calculate_bollinger,
    calculate_macd,
    calculate_volume_ma,
    clamp,
    find_sr_levels,
)
from strategies.base import BaseStrategy, Signal


class VolatilityBreakout(BaseStrategy):
    """
    Composite 3 (absorberer bollinger_squeeze + sr_breakout).

    Bollinger-squeeze (bb_width i nederste 10-percentil over 120 barer, aktiv
    inden for de seneste 5 barer) efterfulgt af et S/R-breakout, bekræftet af
    volume og MACD-histogram. Volume og MACD er hårde gates. Leverer et
    measured-move take-profit + ATR-baseret stop i metadata.
    """

    name = "volatility_breakout"
    timeframe = "4h"
    min_confidence = 0.65

    MIN_BARS = 120
    PCTL_WINDOW = 120
    SQUEEZE_LOOKBACK = 5
    SR_LOOKBACK = 50
    SWING_WINDOW = 5
    SR_MAX_ATR = 1.5
    # Overrideable via params (A/B): gate-tærskel på volume-spike, hvilken
    # percentil der definerer et squeeze, og confidence-gulv. Defaults = uændret
    # Phase 3-adfærd.
    MIN_VOLUME_RATIO = 1.5
    SQUEEZE_PERCENTILE = 10

    def generate_signal(
        self, df: pd.DataFrame, symbol: str, params: dict | None = None
    ) -> Signal | None:
        p = params or {}
        min_volume_ratio = p.get("min_volume_ratio", self.MIN_VOLUME_RATIO)
        squeeze_pct = p.get("squeeze_percentile", self.SQUEEZE_PERCENTILE)
        min_conf = p.get("min_confidence", self.min_confidence)

        if len(df) < self.MIN_BARS:
            return None

        boll = calculate_bollinger(df, 20, 2.0)
        macd = calculate_macd(df)
        atr = calculate_atr(df, 14)
        vol_ma = calculate_volume_ma(df, 20)

        bb_width = boll["bb_width"]
        window120 = bb_width.dropna().iloc[-self.PCTL_WINDOW:]
        if len(window120) < 20:
            return None

        p10 = float(np.percentile(window120, squeeze_pct))
        p90 = float(np.percentile(window120, 90))

        # Squeeze skal have været aktiv (bb_width <= p10) inden for seneste 5 barer.
        last5 = bb_width.iloc[-self.SQUEEZE_LOOKBACK:]
        squeeze_bars = last5[last5 <= p10]
        if squeeze_bars.empty:
            return None
        # Tightest squeeze i vinduet = referencebar.
        squeeze_idx = squeeze_bars.idxmin()
        bb_width_squeeze = float(bb_width.loc[squeeze_idx])
        price_at_squeeze = float(df["close"].loc[squeeze_idx])

        atr_now = float(atr.iloc[-1])
        macd_hist = float(macd["macd_hist"].iloc[-1])
        volume = float(df["volume"].iloc[-1])
        volume_ma_20 = float(vol_ma.iloc[-1])
        close = float(df["close"].iloc[-1])

        if any(np.isnan(v) for v in (atr_now, macd_hist, volume, volume_ma_20, close)):
            return None
        if atr_now <= 0 or volume_ma_20 <= 0 or p90 <= 0:
            return None

        levels = find_sr_levels(df, self.SR_LOOKBACK, self.SWING_WINDOW)
        resistance = levels["resistance"]
        support = levels["support"]

        # --- Retning: close bryder over resistance (long) / under support (short) ---
        side = None
        if resistance is not None and close > resistance and \
                abs(resistance - price_at_squeeze) <= self.SR_MAX_ATR * atr_now:
            side = "long"
            breakout_level = resistance
        elif support is not None and close < support and \
                abs(support - price_at_squeeze) <= self.SR_MAX_ATR * atr_now:
            side = "short"
            breakout_level = support
        else:
            return None

        # Hårde gates: volume + MACD-retning.
        if volume <= min_volume_ratio * volume_ma_20:
            return None
        if side == "long" and not (macd_hist > 0):
            return None
        if side == "short" and not (macd_hist < 0):
            return None

        volume_ratio = volume / volume_ma_20
        squeeze_intensity = clamp(1 - (bb_width_squeeze / p90), 0, 1)
        volume_strength = clamp((volume_ratio - 1.5) / 1.0, 0, 1)
        macd_strength = clamp(abs(macd_hist) / atr_now, 0, 1)
        confidence = clamp(
            0.40 + 0.20 * squeeze_intensity + 0.25 * volume_strength
            + 0.15 * macd_strength,
            0.0,
            1.0,
        )
        if confidence < min_conf:
            return None

        # Measured-move target ud fra prior range.
        if resistance is not None and support is not None:
            prior_range = resistance - support
        else:
            prior_range = 2 * self.SR_MAX_ATR * atr_now
        if side == "long":
            suggested_take_profit = breakout_level + prior_range
            suggested_stop_loss = breakout_level - 0.5 * atr_now
        else:
            suggested_take_profit = breakout_level - prior_range
            suggested_stop_loss = breakout_level + 0.5 * atr_now

        return Signal(
            strategy_id=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            timeframe=self.timeframe,
            metadata={
                "bb_width": bb_width_squeeze,
                "bb_width_percentile": p10,
                "squeeze_active": True,
                "resistance_level": resistance,
                "support_level": support,
                "breakout_level": float(breakout_level),
                "volume": volume,
                "volume_ma_20": volume_ma_20,
                "volume_ratio": float(volume_ratio),
                "macd_hist": macd_hist,
                "atr": atr_now,
                "squeeze_intensity": float(squeeze_intensity),
                "volume_strength": float(volume_strength),
                "macd_strength": float(macd_strength),
                "suggested_take_profit": float(suggested_take_profit),
                "suggested_stop_loss": float(suggested_stop_loss),
            },
        )
