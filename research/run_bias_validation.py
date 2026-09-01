"""
Fuld koersel af daily-bias-valideringen — PRD_DAILY_BIAS_VALIDATION.md.

Sweeper fire akser, saa hver metodevalg kan maales i stedet for antages:
  min_break_atr    wick-gennembrudstaerskel (0.0 primaer, 0.05/0.10 robusthed)
  repair           udvid High/Low til Open/Close (IKKE entydigt konservativ)
  ref_floor        udelad signaler med degenereret REFERENCE-bar
  anchor/horizon/overlap som foer

Producerer research/output/bias_validation.csv. Bygger INTET i strategies/.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.bias_engine import (ANCHORS, HORIZONS, TRADEABLE, BULLISH,
                                  evaluate, load_daily, non_overlapping_mask,
                                  two_sided_p, z_score)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research" / "output"

# Guld foeres med BEGGE kilder som ligevaerdige markeder — valget afgoeres af
# flad-bar-taellingen i rapporten, ikke af PRD §3's pris-argument.
# XAU trunkeres 2025-03-31: derefter har filen huller paa 11/27/18/81 dage.
MARKETS = {
    "BTC/USDT":           ("data/historical/BTCUSDT_1d.csv", "crypto", None),
    "ETH/USDT":           ("data/historical/ETHUSDT_1d.csv", "crypto", None),
    "SOL/USDT":           ("data/historical/SOLUSDT_1d.csv", "crypto", None),
    "EUR (6E=F)":         ("data/historical/6E_1d.csv", "futures", None),
    "GBP (6B=F)":         ("data/historical/6B_1d.csv", "futures", None),
    "Guld (XAU spot)":    ("data/historical_xau/XAU_1d_data.csv", "spot", "2025-03-31"),
    "Guld (GC=F)":        ("data/historical/GC_1d.csv", "futures", None),
    "S&P 500 (ES=F)":     ("data/historical/ES_1d.csv", "futures", None),
    "Nasdaq 100 (NQ=F)":  ("data/historical/NQ_1d.csv", "futures", None),
}
GOLD = ("Guld (XAU spot)", "Guld (GC=F)")
# Fuld, utrunkeret XAU — kun til §5-regressionstjekket mod cowork-sessionen.
REGRESSION = {"XAU fuld (regression)": ("data/historical_xau/XAU_1d_data.csv", "spot", None)}

# (min_break_atr, repair, ref_floor, label)
CONFIGS = [
    (0.00, False, 0.00, "primary"),
    (0.05, False, 0.00, "atr_005"),
    (0.10, False, 0.00, "atr_010"),
    (0.00, True,  0.00, "repaired"),
    (0.00, False, 0.10, "ref_floor_010"),
]


def _metrics(g: pd.DataFrame, base_bull: float, base_bear: float) -> dict:
    ties = int(g["tie"].sum())
    g = g[~g["tie"]]           # uafgjorte baerer ingen retning — ud i begge ender
    n = len(g)
    if not n:
        return {}
    hits = int(g["hit"].sum())
    bull = (g["direction"] == BULLISH).to_numpy()
    nb = int(bull.sum())
    p0 = (nb * base_bull + (n - nb) * base_bear) / n
    hr = hits / n
    z = z_score(hits, n, p0)
    return {
        "n": n, "n_long": nb, "n_short": n - nb, "hits": hits, "ties_excluded": ties,
        "hit_rate": hr, "base_rate": p0, "diff_pp": (hr - p0) * 100,
        "z": z, "p_value": two_sided_p(z),
        "mean_ret_pct": float(g["ret"].mean() * 100),
        "median_ret_pct": float(g["ret"].median() * 100),
        "mean_gap_pct": float(g["gap"].mean() * 100),
        "mfe_mae": float(g["mfe"].mean() / g["mae"].mean()) if g["mae"].mean() else float("nan"),
    }


def run(markets: dict, configs=CONFIGS) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rows, freq, meta = [], [], {}
    for market, (rel, kind, cut) in markets.items():
        for thr, repair, floor, label in configs:
            df = load_daily(ROOT / rel, repair=repair)
            if cut:
                df = df[df.index <= cut]
            ev = evaluate(df, market, thr, floor)
            cfg = {"min_break_atr": thr, "repair": repair, "ref_floor": floor, "config": label}
            meta.setdefault(market, {}).update({
                "bars": ev.n_bars, "first": str(ev.first.date()), "last": str(ev.last.date()),
                "kind": kind, "file": rel, "truncated_at": cut})
            if label == "primary":
                meta[market].update(degenerate_refs=ev.n_degenerate_refs,
                                    signals_excluded=ev.n_signals_excluded)
            cnt = ev.scenario_counts_clean
            for sc, c in cnt.items():
                freq.append({"market": market, **cfg, "scenario": sc, "count": int(c),
                             "pct": float(c / cnt.sum() * 100), "tradeable": sc in TRADEABLE})
            if ev.signals.empty:
                continue
            base = ev.base.set_index(["horizon", "anchor"])
            for N, anchor in itertools.product(HORIZONS, ANCHORS):
                if (N, anchor) not in base.index:
                    continue
                bb, bs = base.loc[(N, anchor), ["base_bullish", "base_bearish"]]
                sub = ev.signals[(ev.signals.horizon == N) & (ev.signals.anchor == anchor)]
                if sub.empty:
                    continue
                sub = sub.sort_values("i")
                keep = non_overlapping_mask(sub["i"].to_numpy(), N)
                for overlap, s in (("all", sub), ("non_overlapping", sub[keep])):
                    for sc, g in [(x, s[s.scenario == x]) for x in TRADEABLE] + [("ALL", s)]:
                        m = _metrics(g, bb, bs) if not g.empty else {}
                        if m:
                            rows.append({"market": market, "asset_class": kind, "scenario": sc,
                                         "horizon": N, "anchor": anchor, **cfg,
                                         "overlap": overlap, **m,
                                         "base_bullish": bb, "base_bearish": bs,
                                         "degenerate_refs": ev.n_degenerate_refs,
                                         "signals_excluded_degen": ev.n_signals_excluded})
    return pd.DataFrame(rows), pd.DataFrame(freq), meta


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    res, freq, meta = run(MARKETS)
    res["dataset"] = "primary"
    reg, rfreq, rmeta = run(REGRESSION, configs=[(0.00, False, 0.00, "primary")])
    reg["dataset"] = "regression"
    full = pd.concat([res, reg], ignore_index=True)
    full.to_csv(OUT / "bias_validation.csv", index=False, float_format="%.6g")
    pd.concat([freq, rfreq], ignore_index=True).to_csv(
        OUT / "bias_scenario_frequency.csv", index=False, float_format="%.6g")
    (OUT / "_meta.json").write_text(json.dumps({**meta, **rmeta}, indent=2, sort_keys=True))
    print(f"skrev {len(full)} raekker -> bias_validation.csv")


if __name__ == "__main__":
    main()
