"""
Daily Bias-klassifikator — TradingLab "How To Find a Daily Bias (On ANY Chart)".

Ren, afhængighedsfri implementering af de aftalte regler. Bruges til validering
FØR strategien bygges ind i botten. Ingen entry-, exit- eller RR-logik her —
dette afgør udelukkende dagens bias.

Regler (aftalt 2026-08-21):
  Referencerange = FORRIGE daglige candle, high/low MED wicks.
  Signalcandle   = seneste LUKKEDE daglige candle.
  Biasen gælder ÉN dag frem. Ny dag = ny range.

Rækkefølgen er kritisk: luk-position tjekkes FØR "begge sider fejet",
ellers filtreres S2 og S5 væk af S3 (de er geometriske delmængder af den).
"""
from dataclasses import dataclass

# --- Konfiguration -----------------------------------------------------------
# Minimum wick-gennembrud i ATR(14)-enheder. 0.0 = "over rangen er over rangen".
MIN_BREAK_ATR = 0.0

# 4c: de tre kombinationer videoen ikke navngiver. Slået FRA — sæt True for
# at aktivere. Ingen af dem kræver ny kode, kun at flaget vendes.
ENABLE_BREAKOUT_UP = False    # sweep high, ingen sweep low, luk OVER prior high
ENABLE_BREAKOUT_DOWN = False  # sweep low, ingen sweep high, luk UNDER prior low
ENABLE_S1_MIRROR = True       # spejl af S1: sweep low, luk tilbage inde i rangen

BULLISH, BEARISH, NO_TRADE = "bullish", "bearish", "no_trade"


@dataclass
class Bias:
    scenario: str      # "S1", "S1M", "S2", "S3", "S4", "S5", "BO_UP", "BO_DOWN"
    direction: str     # BULLISH | BEARISH | NO_TRADE
    note: str
    prior_high: float
    prior_low: float


def classify_daily_bias(prior_high, prior_low, high, low, close, atr=None):
    """Klassificér seneste lukkede dagscandle mod forrige dags range."""
    t = 0.0
    if MIN_BREAK_ATR and atr and atr == atr:
        t = MIN_BREAK_ATR * atr

    swept_high = high > prior_high + t
    swept_low = low < prior_low - t
    B = lambda s, d, n: Bias(s, d, n, prior_high, prior_low)

    # 1) Luk UDEN FOR rangen — stærkeste signaler, skal tjekkes først.
    if swept_high and close < prior_low:
        return B("S5", BEARISH, "fejede over high, lukkede under low")
    if swept_low and close > prior_high:
        return B("S2", BULLISH, "fejede under low, lukkede over high")

    # 2) Begge sider fejet, luk inde i rangen -> ingen retning.
    if swept_high and swept_low:
        return B("S3", NO_TRADE, "likviditet fejet paa begge sider")

    # 3) Én side fejet, luk tilbage inde i rangen.
    if swept_high and close <= prior_high:
        return B("S1", BEARISH, "fejede over high, lukkede tilbage inde")
    if swept_low and close >= prior_low:
        if ENABLE_S1_MIRROR:
            return B("S1M", BULLISH, "fejede under low, lukkede tilbage inde")
        return B("S1M", NO_TRADE, "spejl af S1 — deaktiveret")

    # 4) Ingen af siderne brudt -> konsolidering.
    if not swept_high and not swept_low:
        return B("S4", NO_TRADE, "inside bar, konsolidering")

    # 5) Udefinerede i videoen: brud MED luk uden for, uden modsat sweep.
    if swept_high:
        return B("BO_UP", BULLISH if ENABLE_BREAKOUT_UP else NO_TRADE,
                 "luk over high uden sweep af low")
    return B("BO_DOWN", BEARISH if ENABLE_BREAKOUT_DOWN else NO_TRADE,
             "luk under low uden sweep af high")
