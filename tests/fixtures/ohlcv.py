"""
Deterministiske OHLCV-fixtures til Phase 3 composite-strategierne.

Ingen tilfældighed — hver fixture er konstrueret så den (be)kræfter præcis én
sti gennem strategien (signal eller en bestemt gate der fejler). Verificeret i
tests/test_trend_momentum.py, test_reversal_context.py, test_volatility_breakout.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _mk(closes, highs=None, lows=None, vols=None,
        hi_mult=1.003, lo_mult=0.997, base_vol=2000.0) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    times = pd.date_range("2024-01-01", periods=n, freq="4h")
    highs = closes * hi_mult if highs is None else np.asarray(highs, dtype=float)
    lows = closes * lo_mult if lows is None else np.asarray(lows, dtype=float)
    if vols is None:
        vols = np.full(n, base_vol)
    else:
        vols = np.asarray(vols, dtype=float)
    return pd.DataFrame({
        "time": times, "open": closes, "high": highs,
        "low": lows, "close": closes, "volume": vols,
    })


# ---------------------------------------------------------------------------
# trend_momentum
# ---------------------------------------------------------------------------

def tm_long_signal() -> pd.DataFrame:
    """Golden cross + frisk MACD-kryds op + RSI ~53 → long."""
    base = list(np.linspace(100, 240, 171))
    pull = list(np.linspace(240, 210, 25))
    rec = list(np.linspace(pull[-1] + 3.0, pull[-1] + 12.0, 4))
    return _mk(base + pull + rec)


def tm_long_rsi_too_high() -> pd.DataFrame:
    """Samme uptrend-setup men skarp recovery → RSI > 60 → None."""
    base = list(np.linspace(100, 240, 176))
    pull = list(np.linspace(240, 210, 18))
    rec = list(np.linspace(pull[-1] + 4.0, pull[-1] + 24.0, 6))
    return _mk(base + pull + rec)


def tm_short_signal() -> pd.DataFrame:
    """Præcis spejling af tm_long_signal → death cross + frisk MACD-kryds ned → short."""
    df = tm_long_signal()
    c = df["close"].to_numpy()
    reflected = (c.max() + c.min()) - c
    return _mk(reflected)


def tm_no_fresh_cross() -> pd.DataFrame:
    """Ren, stabil uptrend — MACD har været over signal længe, intet frisk kryds → None."""
    return _mk(list(np.linspace(100, 300, 220)))


def tm_too_short() -> pd.DataFrame:
    """< 200 bars → None."""
    return _mk(list(np.linspace(100, 150, 150)))


# ---------------------------------------------------------------------------
# reversal_context
# ---------------------------------------------------------------------------

def _bullish_divergence_zone() -> list[float]:
    """Steep dyk til trough1, gentle dyk til en marginalt lavere trough2 (higher RSI low)."""
    drop1 = list(np.linspace(165, 150, 6))[1:]
    rally1 = list(np.linspace(150, 158, 7))[1:]
    drop2 = list(np.linspace(158, 149, 9))[1:]
    rally2 = list(np.linspace(149, 155, 7))[1:]
    return drop1 + rally1 + drop2 + rally2


def _spike_at_last_trough(prices: list[float], spike: float,
                          base_vol: float = 2000.0) -> np.ndarray:
    vols = np.full(len(prices), base_vol)
    arr = np.asarray(prices)
    t2 = int(np.argmin(arr[-15:]) + len(arr) - 15)
    vols[t2] = spike
    return vols


def rev_bullish_long() -> pd.DataFrame:
    """Lower low + higher RSI low, downtrend-kontekst (EMA50<EMA200), volume-spike → long."""
    prices = list(np.linspace(200, 166, 60)) + _bullish_divergence_zone()
    vols = _spike_at_last_trough(prices, spike=3500.0)
    return _mk(prices, hi_mult=1.002, lo_mult=0.998, vols=vols)


def rev_wrong_trend_context() -> pd.DataFrame:
    """Gyldig bullish divergens MEN uptrend-kontekst (EMA50>EMA200) → kontekst-gate → None."""
    seg_a = list(np.linspace(100, 165, 60))
    drop1 = list(np.linspace(165, 140, 5))[1:]
    rally1 = list(np.linspace(140, 150, 6))[1:]
    drop2 = list(np.linspace(150, 139, 10))[1:]
    rally2 = list(np.linspace(139, 147, 6))[1:]
    prices = seg_a + drop1 + rally1 + drop2 + rally2
    vols = _spike_at_last_trough(prices, spike=3500.0)
    return _mk(prices, hi_mult=1.002, lo_mult=0.998, vols=vols)


def rev_low_volume() -> pd.DataFrame:
    """Gyldig divergens + rigtig kontekst men flad volume (~1.0×MA) → volume-gate → None."""
    prices = list(np.linspace(200, 166, 60)) + _bullish_divergence_zone()
    return _mk(prices, hi_mult=1.002, lo_mult=0.998)  # konstant volume


def rev_no_divergence() -> pd.DataFrame:
    """Monoton nedtrend — ingen swing lows → ingen divergens → None."""
    return _mk(list(np.linspace(200, 150, 90)), hi_mult=1.002, lo_mult=0.998)


def rev_too_short() -> pd.DataFrame:
    """< 30 bars → None."""
    return _mk(list(np.linspace(200, 180, 25)), hi_mult=1.002, lo_mult=0.998)


# ---------------------------------------------------------------------------
# volatility_breakout
# ---------------------------------------------------------------------------

def _vb_frame(closes, last_vol, bv=2000.0, brk_high=None, brk_low=99.9) -> pd.DataFrame:
    closes = list(closes)
    n = len(closes)
    highs = [c * 1.002 for c in closes]
    lows = [c * 0.998 for c in closes]
    highs[-1] = brk_high if brk_high is not None else closes[-1] * 1.01
    lows[-1] = brk_low
    vols = [bv] * n
    vols[-1] = last_vol
    return _mk(closes, highs=highs, lows=lows, vols=vols)


def _vb_vol_phase() -> list[float]:
    return [100 + 4 * np.sin(2 * np.pi * k / 15) for k in range(60)]


def vb_long_breakout() -> pd.DataFrame:
    """Squeeze + breakout over resistance + volume ~2.3× + MACD hist > 0 → long."""
    closes = _vb_vol_phase() + [100.0] * 64
    closes[60 + 30] = 100.55            # resistance-bump inde i konsolideringen
    closes = closes + [103.0]           # breakout-bar
    return _vb_frame(closes, last_vol=5000.0, brk_high=103.0 * 1.01)


def vb_low_volume() -> pd.DataFrame:
    """Samme squeeze/breakout men volume ~1.1×MA → volume-gate → None."""
    closes = _vb_vol_phase() + [100.0] * 64
    closes[60 + 30] = 100.55
    closes = closes + [103.0]
    return _vb_frame(closes, last_vol=2210.0, brk_high=103.0 * 1.01)


def vb_no_squeeze() -> pd.DataFrame:
    """Breakout uden forudgående squeeze (vedvarende volatilitet) → squeeze-gate → None."""
    volatile_cons = [100 + 3.5 * np.sin(2 * np.pi * k / 9) for k in range(64)]
    closes = _vb_vol_phase() + volatile_cons + [103.0]
    return _vb_frame(closes, last_vol=5000.0, brk_high=103.0 * 1.01)


def vb_macd_disagree() -> pd.DataFrame:
    """
    Optrend → flad squeeze (MACD vender ned under signal) → lille up-breakout der
    rydder resistance, men macd_hist < 0 (uenig med long-retningen) → MACD-gate → None.
    """
    up = [90 + (100 - 90) * k / 59 + 2.5 * np.sin(2 * np.pi * k / 12) for k in range(60)]
    closes = up + [100.0] * 18
    closes[60 + 5] = 100.35
    closes = closes + [100.9]
    return _vb_frame(closes, last_vol=5000.0, brk_high=100.9 * 1.004, brk_low=99.95)


def vb_too_short() -> pd.DataFrame:
    """< 120 bars → None."""
    return _vb_frame(_vb_vol_phase() + [100.0] * 39 + [103.0], last_vol=5000.0)
