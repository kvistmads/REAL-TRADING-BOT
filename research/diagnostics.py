"""
Datakvalitets- og robusthedsdiagnostik til daily-bias-rapporten.
Skriver research/output/_diagnostics.json. Koeres foer build_report.py.

Alt maales paa RAA data (repair=False) med mindre andet staar — reparationen er
en analyseparameter, ikke en egenskab ved filerne.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import research.daily_bias as db
from research.bias_engine import (TRADEABLE, classify_series, degenerate_reference,
                                  evaluate, load_daily, z_score)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research" / "output"
SER = {
    "BTC/USDT": ("data/historical/BTCUSDT_1d.csv", None),
    "ETH/USDT": ("data/historical/ETHUSDT_1d.csv", None),
    "SOL/USDT": ("data/historical/SOLUSDT_1d.csv", None),
    "EUR (6E=F)": ("data/historical/6E_1d.csv", None),
    "GBP (6B=F)": ("data/historical/6B_1d.csv", None),
    "Guld (XAU spot)": ("data/historical_xau/XAU_1d_data.csv", "2025-03-31"),
    "Guld (GC=F)": ("data/historical/GC_1d.csv", None),
    "S&P 500 (ES=F)": ("data/historical/ES_1d.csv", None),
    "Nasdaq 100 (NQ=F)": ("data/historical/NQ_1d.csv", None),
}
CRYPTO = {"BTC/USDT", "ETH/USDT", "SOL/USDT"}


def _load(rel: str, cut: str | None, repair: bool = False) -> pd.DataFrame:
    d = load_daily(ROOT / rel, repair=repair)
    return d[d.index <= cut] if cut else d


def defect_table() -> dict:
    """§ punkt 2: flade barer og Open==Close pr. marked OG pr. aar, paa raa data."""
    out = {}
    for name, (rel, cut) in SER.items():
        d = _load(rel, cut)
        flat, oc = (d["High"] == d["Low"]), (d["Open"] == d["Close"])
        by_year = {}
        for y, g in d.groupby(d.index.year):
            by_year[int(y)] = {
                "bars": len(g),
                "flat": int((g["High"] == g["Low"]).sum()),
                "flat_pct": float((g["High"] == g["Low"]).mean() * 100),
                "oc": int((g["Open"] == g["Close"]).sum()),
                "oc_pct": float((g["Open"] == g["Close"]).mean() * 100),
            }
        dg = d.index.to_series().diff().dt.days
        lim = 1 if name in CRYPTO else 4
        gap = ((d["Open"] - d["Close"].shift(1)) / d["Close"].shift(1) * 100)
        out[name] = {
            "bars": len(d), "first": str(d.index[0].date()), "last": str(d.index[-1].date()),
            "flat": int(flat.sum()), "flat_pct": float(flat.mean() * 100),
            "oc": int(oc.sum()), "oc_pct": float(oc.mean() * 100),
            "median_range_pct": float(((d["High"] - d["Low"]) / d["Close"]).median() * 100),
            "holes": int((dg > lim).sum()), "max_hole_days": int(dg.max()),
            "gap_mean_pct": float(gap.mean()), "gap_abs_mean_pct": float(gap.abs().mean()),
            "gap_std_pct": float(gap.std()), "gap_p95_pct": float(gap.abs().quantile(.95)),
            "by_year": by_year,
        }
    return out


def contamination() -> dict:
    """§ punkt 1: hvor mange signaler pr. scenarie stammer fra en flad reference-bar."""
    out = {}
    for name, (rel, cut) in SER.items():
        d = _load(rel, cut)
        deg = degenerate_reference(d, 0.0)
        cls = classify_series(d, 0.0)
        i = cls["i"].to_numpy()
        cls = cls.assign(ref_deg=deg[i - 1])
        per = {}
        for sc, g in cls.groupby("scenario"):
            per[sc] = {"n": len(g), "from_flat_ref": int(g.ref_deg.sum()),
                       "pct": float(g.ref_deg.mean() * 100)}
        tr = cls[cls.scenario.isin(TRADEABLE)]
        s25 = cls[cls.scenario.isin(("S2", "S5"))]
        out[name] = {
            "degenerate_bars": int(deg.sum()), "per_scenario": per,
            "tradeable_n": len(tr), "tradeable_from_flat": int(tr.ref_deg.sum()),
            "tradeable_pct": float(tr.ref_deg.mean() * 100) if len(tr) else 0.0,
            "s2s5_n": len(s25), "s2s5_from_flat": int(s25.ref_deg.sum()),
            "s2s5_pct": float(s25.ref_deg.mean() * 100) if len(s25) else 0.0,
        }
    return out


def gold_sources() -> dict:
    """§ punkt 4: de to guldkilder maalt mod hinanden paa det der betyder noget."""
    x = _load(*SER["Guld (XAU spot)"])
    g = _load(*SER["Guld (GC=F)"])
    xf = load_daily(ROOT / "data/historical_xau/XAU_1d_data.csv")   # utrunkeret
    xd, gd = xf.copy(), g.copy()
    xd.index, gd.index = xd.index.normalize(), gd.index.normalize()
    ov = xd.index.intersection(gd.index)
    diff = (xd.loc[ov, "Close"] - gd.loc[ov, "Close"])
    # Range-sammenligning maa udelade GC=F's flade barer, ellers maaler vi defekten.
    gnf = gd[gd["High"] > gd["Low"]]
    ov2 = xd.index.intersection(gnf.index)
    gaps = xf.index.to_series().diff().dt.days
    return {
        "overlap_days": len(ov), "overlap_first": str(ov.min().date()),
        "overlap_last": str(ov.max().date()),
        "median_abs_usd": float(diff.abs().median()),
        "median_abs_pct": float((diff.abs() / gd.loc[ov, "Close"] * 100).median()),
        "corr": float(xd.loc[ov, "Close"].corr(gd.loc[ov, "Close"])),
        "shift_median_usd": {s: float((xd["Close"].shift(s).reindex(ov)
                                       - gd.loc[ov, "Close"]).abs().median()) for s in (-1, 0, 1)},
        "range_xau_all": float((xd.loc[ov, "High"] - xd.loc[ov, "Low"]).median()),
        "range_gc_all": float((gd.loc[ov, "High"] - gd.loc[ov, "Low"]).median()),
        "range_xau_nonflat": float((xd.loc[ov2, "High"] - xd.loc[ov2, "Low"]).median()),
        "range_gc_nonflat": float((gnf.loc[ov2, "High"] - gnf.loc[ov2, "Low"]).median()),
        "xau_flat": int((x["High"] == x["Low"]).sum()), "xau_bars": len(x),
        "gc_flat": int((g["High"] == g["Low"]).sum()), "gc_bars": len(g),
        "xau_tail_gaps": {str(k.date()): int(v) for k, v in gaps[gaps > 5].items()},
        "xau_truncated_at": "2025-03-31",
    }


def repair_effect() -> dict:
    """§ punkt 3: hvad reparationen goer ved signalantal og hitrate pr. scenarie."""
    out = {}
    for name, (rel, cut) in SER.items():
        row = {}
        for lbl, rep in (("raw", False), ("repaired", True)):
            ev = evaluate(_load(rel, cut, repair=rep), name, 0.0, 0.0)
            s = ev.signals[(ev.signals.horizon == 1) & (ev.signals.anchor == "d1_open")
                           & (~ev.signals.tie)]
            row[lbl] = {sc: {"n": int((s.scenario == sc).sum()),
                             "hit": float(s[s.scenario == sc].hit.mean() * 100)
                             if (s.scenario == sc).any() else float("nan")}
                        for sc in TRADEABLE}
            row[lbl]["ALL"] = {"n": len(s), "hit": float(s.hit.mean() * 100)}
        out[name] = row
    return out


def roll_sensitivity() -> dict:
    out = {}
    for name in ["EUR (6E=F)", "GBP (6B=F)", "Guld (GC=F)", "S&P 500 (ES=F)", "Nasdaq 100 (NQ=F)"]:
        d = _load(*SER[name])
        gap = ((d["Open"] - d["Close"].shift(1)) / d["Close"].shift(1)).abs()
        big = (gap > 5 * gap.median()).to_numpy()
        o, c = d["Open"].to_numpy(), d["Close"].to_numpy()
        ev = evaluate(d, name, 0.0, 0.0)
        s = ev.signals[(ev.signals.horizon == 1) & (ev.signals.anchor == "d1_open") & (~ev.signals.tie)]
        i = s["i"].to_numpy()
        contam = big[i] | big[i + 1]
        out[name] = {"n": len(s), "contaminated": int(contam.sum()),
                     "contaminated_pct": float(contam.mean() * 100),
                     "hit_all": float(s.hit.mean() * 100),
                     "hit_clean": float(s.hit[~contam].mean() * 100)}
    return out


def breakout_diagnostic() -> dict:
    """§6: BO_UP/BO_DOWN er deaktiveret — men hvad ville de have gjort?

    Koeres PAA DET FILTREREDE UNIVERS: paa GC=F stammer 22-23 % af alle BO-signaler
    fra en flad reference-bar, saa et ufiltreret tal ville maale defekten.
    Beskrivende — en hypotese, ikke et resultat.
    """
    db.ENABLE_BREAKOUT_UP = db.ENABLE_BREAKOUT_DOWN = True
    try:
        per, agg = {}, {"BO_UP": [0, 0, 0.0], "BO_DOWN": [0, 0, 0.0]}
        for name, (rel, cut) in SER.items():
            if name == "Guld (GC=F)":       # guld repraesenteres af XAU-kilden
                continue
            ev = evaluate(_load(rel, cut), name, 0.0, 0.0)
            b = ev.base.set_index(["horizon", "anchor"]).loc[(1, "d1_open")]
            s = ev.signals[(ev.signals.horizon == 1) & (ev.signals.anchor == "d1_open")
                           & (~ev.signals.tie)]
            per[name] = {}
            for sc, bp in (("BO_UP", b.base_bullish), ("BO_DOWN", b.base_bearish)):
                g = s[s.scenario == sc]
                per[name][sc] = {"n": len(g), "hit": float(g.hit.mean() * 100),
                                 "base": float(bp * 100),
                                 "diff_pp": float((g.hit.mean() - bp) * 100)}
                agg[sc][0] += len(g); agg[sc][1] += int(g.hit.sum()); agg[sc][2] += bp * len(g)
        pooled = {sc: {"n": n, "hit": h / n * 100, "base": wb / n * 100,
                       "diff_pp": (h / n - wb / n) * 100, "z": z_score(h, n, wb / n)}
                  for sc, (n, h, wb) in agg.items()}
        return {"per_market": per, "pooled": pooled}
    finally:
        db.ENABLE_BREAKOUT_UP = db.ENABLE_BREAKOUT_DOWN = False


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    d = {"defects": defect_table(), "contamination": contamination(),
         "gold_sources": gold_sources(), "repair_effect": repair_effect(),
         "roll_sensitivity": roll_sensitivity(), "breakout": breakout_diagnostic()}
    (OUT / "_diagnostics.json").write_text(json.dumps(d, indent=2, sort_keys=True, default=float))
    print(f"skrev {OUT/'_diagnostics.json'}")


if __name__ == "__main__":
    main()
