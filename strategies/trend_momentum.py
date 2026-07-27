from __future__ import annotations

import numpy as np
import pandas as pd

from data.indicators import (
    calculate_atr,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    clamp,
)
from strategies.base import BaseStrategy, Signal


class TrendMomentum(BaseStrategy):
    """
    Composite 1 (absorberer macd_volume + ema_crossover).

    Trend-regime via EMA50/EMA200 + frisk MACD-kryds i trendens retning +
    RSI der ikke er udstrakt. Alle tre betingelser skal være opfyldt på
    samme (seneste) bar.
    """

    name = "trend_momentum"
    timeframe = "4h"
    min_confidence = 0.65

    MIN_BARS = 200

    # Fuld-styrke-skala for |ema50-ema200|/ema200 pr. asset-class. En fælles
    # 5%-skala er meningsløs for valuta: empirisk (~2 års 4h-data) trender
    # EUR/USD & GBP/USD i ~0.5% (median), guld i ~2%, crypto i flere %. Uden
    # asset-class-skalering bliver forex' trend_strength≈0 → confidence<0.65 →
    # 0 trades. Skalaerne sætter medianen af hver klasses spread til ~0.5-0.7.
    TREND_STRENGTH_SCALE = {
        "crypto": 0.05,
        "forex": 0.01,
        "gold": 0.03,
    }

    # Fuld-styrke-skala for cross-decisiveness = |Δmacd_hist|/atr, dvs. hvor
    # hurtigt MACD skærer gennem signalet på selve krydsbaren. Erstatter den
    # gamle macd_strength=|macd_hist|/atr, som ~0 ved ET FRISK kryds (macd≈signal
    # → hist≈0) og dermed nulstillede sit 0.25-vægtede led præcis når det blev
    # målt. ATR-normaliseringen gør målet asset-class-agnostisk (empirisk median
    # ~0.06, p75 ~0.08 for både crypto/forex/gold), så én fælles skala rækker.
    CROSS_STRENGTH_SCALE = 0.08

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal | None:
        if len(df) < self.MIN_BARS:
            return None

        ema50 = calculate_ema(df, 50)
        ema200 = calculate_ema(df, 200)
        macd = calculate_macd(df)
        rsi = calculate_rsi(df, 14)
        atr = calculate_atr(df, 14)

        ema_50 = float(ema50.iloc[-1])
        ema_200 = float(ema200.iloc[-1])
        macd_now = float(macd["macd"].iloc[-1])
        macd_prev = float(macd["macd"].iloc[-2])
        sig_now = float(macd["macd_signal"].iloc[-1])
        sig_prev = float(macd["macd_signal"].iloc[-2])
        macd_hist = float(macd["macd_hist"].iloc[-1])
        macd_hist_prev = float(macd["macd_hist"].iloc[-2])
        rsi_now = float(rsi.iloc[-1])
        atr_now = float(atr.iloc[-1])

        if any(
            np.isnan(v)
            for v in (ema_50, ema_200, macd_now, macd_prev, sig_now, sig_prev,
                      macd_hist, macd_hist_prev, rsi_now, atr_now)
        ):
            return None
        if ema_200 == 0 or atr_now <= 0:
            return None

        fresh_cross_up = macd_prev < sig_prev and macd_now > sig_now
        fresh_cross_down = macd_prev > sig_prev and macd_now < sig_now

        if ema_50 > ema_200 and fresh_cross_up and rsi_now < 60:
            side = "long"
            rsi_room = clamp((60 - rsi_now) / 60, 0, 1)
        elif ema_50 < ema_200 and fresh_cross_down and rsi_now > 40:
            side = "short"
            rsi_room = clamp((rsi_now - 40) / 60, 0, 1)
        else:
            return None

        scale = self.TREND_STRENGTH_SCALE.get(
            BaseStrategy.get_asset_class(symbol), 0.05
        )
        trend_strength = clamp(abs(ema_50 - ema_200) / ema_200, 0, scale) / scale
        cross_strength = clamp(
            abs(macd_hist - macd_hist_prev) / atr_now / self.CROSS_STRENGTH_SCALE,
            0, 1,
        )
        confidence = clamp(
            0.35 + 0.25 * trend_strength + 0.25 * cross_strength + 0.15 * rsi_room,
            0.0,
            1.0,
        )

        if confidence < self.min_confidence:
            return None

        return Signal(
            strategy_id=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            timeframe=self.timeframe,
            metadata={
                "ema_50": ema_50,
                "ema_200": ema_200,
                "macd": macd_now,
                "macd_signal": sig_now,
                "macd_hist": macd_hist,
                "macd_hist_prev": macd_hist_prev,
                "rsi": rsi_now,
                "atr": atr_now,
                "trend_strength": trend_strength,
                "cross_strength": cross_strength,
                "rsi_room": rsi_room,
            },
        )
