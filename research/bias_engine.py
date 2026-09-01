"""
Valideringsmotor for daily bias — PRD_DAILY_BIAS_VALIDATION.md §4.

Ren maaling af RETNING. Ingen entries, exits, stops eller RR.
Klassifikatoren importeres fra research/daily_bias.py — den genimplementeres IKKE.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import research.daily_bias as db

BULLISH, BEARISH = db.BULLISH, db.BEARISH
TRADEABLE = ("S1", "S1M", "S2", "S5")
HORIZONS = (1, 2, 3, 4, 5)
ANCHORS = ("d1_open", "d_close")


def load_daily(path: str | Path, repair: bool = False) -> pd.DataFrame:
    """Laes en semikolon-CSV i XAU-formatet (Date;Open;High;Low;Close;Volume).

    ``repair`` udvider High/Low til at omslutte Open/Close. Det er IKKE entydigt
    konservativt: hver bar er baade reference for naeste dag OG signalbar mod
    forrige dag. En bredere reference goer sweeps svaerere, men en bredere
    signalbar goer det LETTERE for baren selv at registrere et sweep. Derfor er
    det en parameter der maales i begge stillinger, ikke en default.
    """
    df = pd.read_csv(path, sep=";")
    df["Date"] = pd.to_datetime(df["Date"], format="%Y.%m.%d %H:%M")
    df = df.set_index("Date").sort_index()
    for c in ("Open", "High", "Low", "Close"):
        df[c] = df[c].astype(float)
    df = df[~df.index.duplicated(keep="last")]
    if repair:
        hi = df[["High", "Open", "Close"]].max(axis=1)
        lo = df[["Low", "Open", "Close"]].min(axis=1)
        df = df.assign(High=hi, Low=lo)
    return df


def degenerate_reference(df: pd.DataFrame, frac: float = 0.0) -> np.ndarray:
    """Barer der er ubrugelige SOM REFERENCERANGE for den naeste dag.

    Er prior_high == prior_low == P, saa har enhver bar der straddler P baade
    swept_high og swept_low sande. Luk-tjekket koerer foerst, saa luk > P giver
    S2 og luk < P giver S5 — pr. konstruktion, uanset hvad markedet gjorde.
    Paa GC=F stammer 31 % af alle S2/S5 fra saadan en bar. Det er et
    KLASSIFIKATIONS-problem: at udelade uafgjorte udfald i metrikken fjerner
    ikke de opdigtede signaler, kun deres bidrag til taellingen.

    ``frac`` = 0.0 rammer kun eksakt nul-bredde. frac > 0 saetter desuden et
    gulv paa frac x seriens median-range (relativt til close).
    """
    rng = ((df["High"] - df["Low"]) / df["Close"]).to_numpy()
    if frac <= 0:
        return rng <= 0
    return rng <= frac * float(np.nanmedian(rng))


def wilder_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR(14), Wilder-udglattet. Bruges KUN som wick-gennembrudstaerskel."""
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def classify_series(df: pd.DataFrame, min_break_atr: float = 0.0) -> pd.DataFrame:
    """Bias for hver bar i mod bar i-1's range. Biasen gaelder dag i+1.

    Ingen lookahead: bar i's egen luk er det seneste der bruges, og ATR-taersklen
    tages fra bar i-1 (range-candlen) — begge kendt naar dag i lukker.
    """
    prev = db.MIN_BREAK_ATR
    db.MIN_BREAK_ATR = min_break_atr  # klassifikatoren laeser globalen ved kald
    try:
        atr = wilder_atr(df).to_numpy()
        o, h, l, c = (df[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
        rows = []
        for i in range(1, len(df)):
            b = db.classify_daily_bias(h[i - 1], l[i - 1], h[i], l[i], c[i], atr[i - 1])
            rows.append((i, df.index[i], b.scenario, b.direction))
    finally:
        db.MIN_BREAK_ATR = prev
    return pd.DataFrame(rows, columns=["i", "date", "scenario", "direction"])


def _hit(ret: np.ndarray, bullish: np.ndarray) -> np.ndarray:
    """Traf biasen retningen? Uaendret (ret == 0) taeller som miss."""
    return np.where(bullish, ret > 0, ret < 0)


@dataclass
class MarketEval:
    market: str
    signals: pd.DataFrame          # én raekke pr. (signal, horisont)
    base: pd.DataFrame             # basisrater pr. (horisont, anker)
    scenario_counts: pd.Series     # frekvens for ALLE scenarier, ogsaa no-trade
    n_bars: int
    first: pd.Timestamp
    last: pd.Timestamp
    n_degenerate_refs: int = 0
    n_signals_excluded: int = 0
    scenario_counts_clean: pd.Series | None = None


def evaluate(df: pd.DataFrame, market: str, min_break_atr: float = 0.0,
             min_ref_range_frac: float = 0.0) -> MarketEval:
    """Byg raa signal- og basisrate-tabeller for ét marked.

    Signaler hvis REFERENCE-bar er degenereret udelades — og de samme dage
    udelades af basisraten, saa de to sider maales paa praecis samme univers.
    """
    cls = classify_series(df, min_break_atr)
    o, h, l, c = (df[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    n = len(df)
    deg = degenerate_reference(df, min_ref_range_frac)
    ok = ~deg[np.maximum(np.arange(n) - 1, 0)]     # bar i er brugbar hvis i-1 er ok
    ok[0] = False

    base_rows = []
    for N in HORIZONS:
        # Universet: alle barer der KUNNE have baaret et signal med N barers fremtid.
        idx = np.arange(1, n - N)
        idx = idx[ok[idx]]                          # samme univers som signalerne
        if len(idx) == 0:
            continue
        for anchor in ANCHORS:
            entry = o[idx + 1] if anchor == "d1_open" else c[idx]
            ret = (c[idx + N] - entry) / entry
            # Uafgjorte (ret == 0) bærer ingen retningsinformation og udelades i
            # BEGGE ender. GC=F har 12,5 % helt flade barer (High==Low); talte man
            # dem med i basisraten men ikke i signalerne, ville guld faa en
            # kunstig overperformance paa ~3 procentpoint.
            live = ret != 0
            r = ret[live]
            base_rows.append({
                "horizon": N, "anchor": anchor,
                "base_bullish": float((r > 0).mean()) if len(r) else float("nan"),
                "base_bearish": float((r < 0).mean()) if len(r) else float("nan"),
                "base_n": int(live.sum()), "base_ties": int((~live).sum()),
            })
    base = pd.DataFrame(base_rows)

    n_deg_excluded = int((cls["direction"].isin((BULLISH, BEARISH))
                          & ~ok[cls["i"].to_numpy()]).sum())
    sig = cls[cls["direction"].isin((BULLISH, BEARISH)) & ok[cls["i"].to_numpy()]].copy()
    out = []
    for N in HORIZONS:
        s = sig[sig["i"] <= n - 1 - N]
        if s.empty:
            continue
        i = s["i"].to_numpy()
        bull = (s["direction"] == BULLISH).to_numpy()
        exit_px = c[i + N]
        # Excursion-vindue: barerne biasen faktisk daekker (i+1 .. i+N).
        win_hi = np.array([h[a + 1:a + N + 1].max() for a in i])
        win_lo = np.array([l[a + 1:a + N + 1].min() for a in i])
        for anchor in ANCHORS:
            entry = o[i + 1] if anchor == "d1_open" else c[i]
            ret = (exit_px - entry) / entry
            mfe = np.where(bull, win_hi - entry, entry - win_lo)
            mae = np.where(bull, entry - win_lo, win_hi - entry)
            out.append(pd.DataFrame({
                "market": market, "date": s["date"].to_numpy(), "i": i,
                "scenario": s["scenario"].to_numpy(),
                "direction": s["direction"].to_numpy(),
                "horizon": N, "anchor": anchor,
                "ret": ret, "hit": _hit(ret, bull), "tie": ret == 0,
                "gap": (o[i + 1] - c[i]) / c[i],
                "mfe": mfe, "mae": mae,
            }))
    signals = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    ev = MarketEval(market, signals, base, cls["scenario"].value_counts(),
                    n, df.index[0], df.index[-1])
    ev.n_degenerate_refs = int(deg.sum())
    ev.n_signals_excluded = n_deg_excluded
    ev.scenario_counts_clean = cls[ok[cls["i"].to_numpy()]]["scenario"].value_counts()
    return ev


def non_overlapping_mask(dates_i: np.ndarray, N: int) -> np.ndarray:
    """Grådigt udvalg: naeste signal mindst N barer efter det forrige.

    Koeres over ALLE handlebare signaler i datoraekkefoelge (ikke pr. scenarie),
    saa delmaengden er uafhaengig baade inden for og paa tvaers af scenarier.
    """
    keep = np.zeros(len(dates_i), dtype=bool)
    last = -10**9
    for k, idx in enumerate(dates_i):
        if idx - last >= N:
            keep[k] = True
            last = idx
    return keep


def z_score(hits: int, n: int, p0: float) -> float:
    """Én-stikproeve proportionstest mod en kendt basisrate."""
    if n == 0 or p0 <= 0 or p0 >= 1:
        return float("nan")
    return (hits / n - p0) / math.sqrt(p0 * (1 - p0) / n)


def two_sided_p(z: float) -> float:
    """Normalapproksimation — scipy er ikke en afhaengighed i dette repo."""
    if not math.isfinite(z):
        return float("nan")
    return math.erfc(abs(z) / math.sqrt(2))
