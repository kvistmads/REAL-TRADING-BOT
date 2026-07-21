from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from gates.base import BaseGate, GateResult
from strategies.base import Signal

logger = logging.getLogger(__name__)

TRENDING = "trending"
VOLATILE = "volatile"
SIDEWAYS = "sideways"


class RegimeGate(BaseGate):
    name = "regime"
    blocking = True

    def __init__(self, config: dict):
        cfg = config["gates"].get("regime", {})
        self.min_trending_adx: float = cfg.get("min_trending_adx", 25)
        self.max_volatile_atr_pct: float = cfg.get("max_volatile_atr_pct", 4.0)
        # Kun høj-confidence signaler slipper igennem i volatile regime.
        self.volatile_min_confidence: float = cfg.get("volatile_min_confidence", 0.75)

    def classify(self, df: pd.DataFrame) -> str:
        """
        TRENDING: ADX(14) > min_trending_adx OG EMA(20) hælder konsistent 5 bars
        VOLATILE: ATR(14)/close > max_volatile_atr_pct%
        SIDEWAYS: alt andet
        """
        if df is None or len(df) < 6:
            return SIDEWAYS

        adx = self._last(df, "adx_14")
        atr = self._last(df, "atr_14")
        close = self._last(df, "close")
        if close is None or close == 0:
            return SIDEWAYS

        ema = df["ema_20"].iloc[-5:] if "ema_20" in df.columns else None
        slope_consistent = False
        if ema is not None and not ema.isna().any():
            slope_consistent = ema.is_monotonic_increasing or ema.is_monotonic_decreasing

        if adx is not None and not np.isnan(adx) and adx > self.min_trending_adx and slope_consistent:
            return TRENDING

        if atr is not None and not np.isnan(atr):
            atr_pct = atr / close * 100
            if atr_pct > self.max_volatile_atr_pct:
                return VOLATILE

        return SIDEWAYS

    def evaluate(self, signal: Signal, context: dict) -> GateResult:
        df = context.get("df")
        regime = self.classify(df)
        # Gem regime så engine kan skrive det til trades.market_regime
        context["regime"] = regime

        adx = self._last(df, "adx_14") if df is not None else None
        adx_str = f"{adx:.0f}" if adx is not None and not np.isnan(adx) else "n/a"

        if regime == TRENDING:
            return GateResult(
                gate_name=self.name, passed=True, score=1.0,
                reason=f"Trending market (ADX={adx_str})",
            )

        if regime == VOLATILE:
            passed = signal.confidence >= self.volatile_min_confidence
            reason = (
                f"Volatile market — {'høj' if passed else 'lav'} confidence "
                f"({signal.confidence:.2f} vs {self.volatile_min_confidence:.2f})"
            )
            logger.info(f"RegimeGate {'OK' if passed else 'AFVIST'} ({signal.symbol}): {reason}")
            return GateResult(
                gate_name=self.name, passed=passed,
                score=round(signal.confidence, 2), reason=reason,
            )

        # SIDEWAYS
        reason = f"Sideways market (ADX={adx_str})"
        logger.info(f"RegimeGate AFVIST ({signal.symbol}): {reason}")
        return GateResult(gate_name=self.name, passed=False, score=0.0, reason=reason)

    @staticmethod
    def _last(df: pd.DataFrame, col: str) -> float | None:
        if df is None or col not in df.columns or len(df) == 0:
            return None
        val = df[col].iloc[-1]
        return float(val) if val is not None else None
