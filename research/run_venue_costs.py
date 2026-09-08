"""FASE 3b: venue og ordretype som akse, futures med, og mikro-påstanden efterprøvet.

```bash
.venv/bin/python research/run_venue_costs.py
```

**Ingen ny strategi, ingen backtest, ingen anbefaling af venue.** `backtest.costs` er
urørt. Live-adfærd urørt.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from research.cost_data import TIMEFRAMES, atr_pct, fetch  # noqa: E402
from research.venues import (  # noqa: E402
    CONTRACTS, LOOKUP_DATE, VENUES, contract_costs, live_prices,
    stop_adjusted_maker_share,
)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

CRYPTO = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
RR = 2.0
ASSUMED_WR = 0.33          # til den stop-justerede blanding; se rapporten
PRICE_SHOCK = 0.30         # ±30% følsomhed på futures


def crypto_atr() -> pd.DataFrame:
    rows = []
    for sym in CRYPTO:
        for tf in TIMEFRAMES:
            df = fetch(sym, tf)
            if df.empty:
                continue
            rows.append({"symbol": sym, "timeframe": tf, "atr_pct": atr_pct(df)})
    return pd.DataFrame(rows)


def venue_table(atr: pd.DataFrame) -> pd.DataFrame:
    """DEL 1 — hver (venue × ordretype) mod hver timeframe.

    Tre ordretype-scenarier, og kolonnenavnene bærer antagelsen:

    - ``taker``          begge ben som markedsordre. Det botten gør i dag.
    - ``maker_100pct``   begge ben fylder som maker. **Øvre grænse for fordelen**,
      ikke en beskrivelse af en strategi der kan bygges — et stop loss er pr.
      definition en markedsordre.
    - ``stop_just``      entry og TP som maker, SL som taker. Blandingen er udledt
      af win rate: maker-andel af ben = (1 + WR) / 2.
    """
    maker_share = stop_adjusted_maker_share(ASSUMED_WR)
    rows = []
    for vkey, v in VENUES.items():
        rt = {
            "taker": v.round_turn_bp(0.0),
            "maker_100pct_fill": v.round_turn_bp(1.0),
            "stop_just": v.round_turn_bp(maker_share),
        }
        for tf in TIMEFRAMES:
            a = atr[atr.timeframe == tf]["atr_pct"].median()
            if not np.isfinite(a) or a <= 0:
                continue
            row = {"venue": v.navn, "venue_key": vkey, "timeframe": tf,
                   "atr_pct": round(float(a), 4), "kampagne": v.kampagne,
                   "primaer_kilde": v.primaer}
            for label, bp in rt.items():
                row[f"rundtur_bp_{label}"] = round(bp, 2)
                row[f"omk_R_{label}"] = round((bp / 100) / a, 3)
                row[f"be_wr_{label}_%"] = round(100 * (1 + (bp / 100) / a) / (RR + 1), 1)
            rows.append(row)
    return pd.DataFrame(rows)


def futures_table(prices: dict) -> pd.DataFrame:
    """DEL 2 — kontrakterne, med børs/clearing adskilt fra brokerkurtage."""
    return pd.DataFrame([contract_costs(c, prices[c.yf_ticker]) for c in CONTRACTS.values()])


def micro_check(prices: dict) -> pd.DataFrame:
    """DEL 3 — mikro mod fuldstor, opdelt i de to komponenter.

    Spread-delen skalerer med kontrakten og er derfor **identisk i bp**. Kun gebyret
    skalerer ikke. At se totalen alene skjuler netop den mekanisme.
    """
    rows = []
    for micro, full in (("MES", "ES"), ("MNQ", "NQ"), ("MGC", "GC")):
        m = contract_costs(CONTRACTS[micro], prices[CONTRACTS[micro].yf_ticker])
        f = contract_costs(CONTRACTS[full], prices[CONTRACTS[full].yf_ticker])
        rows.append({
            "par": f"{micro}/{full}",
            "gebyr_bp_micro": m["gebyr_bp"], "gebyr_bp_fuld": f["gebyr_bp"],
            "gebyr_forhold": round(m["gebyr_bp"] / f["gebyr_bp"], 2),
            "spread_bp_micro": m["spread_bp"], "spread_bp_fuld": f["spread_bp"],
            "spread_forhold": round(m["spread_bp"] / f["spread_bp"], 2),
            "i_alt_bp_micro": m["i_alt_bp"], "i_alt_bp_fuld": f["i_alt_bp"],
            "i_alt_forhold": round(m["i_alt_bp"] / f["i_alt_bp"], 2),
            "exch_clear_forhold": round(
                CONTRACTS[micro].exch_clear_pr_side / CONTRACTS[full].exch_clear_pr_side, 2),
        })
    return pd.DataFrame(rows)


def futures_in_R(prices: dict) -> pd.DataFrame:
    """Omkostning i R for futures på 15m, med ±30% prisfølsomhed.

    Retningen er asymmetrisk: **falder prisen, stiger omkostningen i R.** Go/no-go
    skal derfor vurderes på den lave ende, ikke på dagens pris.
    """
    rows = []
    for code, c in CONTRACTS.items():
        sym = {"ES=F": "ES=F", "NQ=F": "NQ=F", "GC=F": "GC=F"}[c.yf_ticker]
        df = fetch({"GC=F": "XAU/USD"}.get(sym, sym), "15m") if sym == "GC=F" else pd.DataFrame()
        # ATR% for underliggende: guld via XAU/USD-ruten, indeks via yfinance direkte.
        if df.empty:
            from research.cost_data import _fetch_yf
            import research.cost_data as cd
            raw = cd.pd.DataFrame()
            try:
                import yfinance as yf
                raw = yf.download(sym, period="60d", interval="15m",
                                  progress=False, auto_adjust=True, threads=False)
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                raw.columns = [x.lower() for x in raw.columns]
                raw = raw.reset_index().rename(columns={raw.reset_index().columns[0]: "time"})
            except Exception:  # noqa: BLE001
                raw = pd.DataFrame()
            df = raw
        a = atr_pct(df) if not df.empty else float("nan")
        if not np.isfinite(a):
            continue
        base = prices[c.yf_ticker]
        entry = {"kontrakt": code, "klasse": c.klasse, "atr15m_%": round(a, 4)}
        for label, px in (("lav_-30%", base * (1 - PRICE_SHOCK)),
                          ("dagens", base),
                          ("høj_+30%", base * (1 + PRICE_SHOCK))):
            cc = contract_costs(c, px)
            entry[f"bp_{label}"] = cc["i_alt_bp"]
            entry[f"omk_R_{label}"] = round((cc["i_alt_bp"] / 100) / a, 3)
        entry["be_wr_dagens_%"] = round(100 * (1 + entry["omk_R_dagens"]) / (RR + 1), 1)
        entry["be_wr_lav_%"] = round(100 * (1 + entry["omk_R_lav_-30%"]) / (RR + 1), 1)
        rows.append(entry)
    return pd.DataFrame(rows)


def session_table(venues: pd.DataFrame, fut_r: pd.DataFrame) -> str:
    """DEL 6 — sorteret efter omkostning i R på 15m, BILLIGST ØVERST."""
    v = venues[venues.timeframe == "15m"].copy()
    rows = []
    for _, r in v.iterrows():
        rows.append({"instrument": r["venue"][:34], "type": "taker",
                     "bp": r["rundtur_bp_taker"], "omk_R": r["omk_R_taker"],
                     "be_wr": r["be_wr_taker_%"]})
        rows.append({"instrument": r["venue"][:34], "type": "stop-just",
                     "bp": r["rundtur_bp_stop_just"], "omk_R": r["omk_R_stop_just"],
                     "be_wr": r["be_wr_stop_just_%"]})
    for _, r in fut_r.iterrows():
        rows.append({"instrument": f"{r['kontrakt']} futures (Tradovate Free)",
                     "type": "taker", "bp": r["bp_dagens"],
                     "omk_R": r["omk_R_dagens"], "be_wr": r["be_wr_dagens_%"]})
    df = pd.DataFrame(rows).sort_values("omk_R")

    lines = [
        f"FASE 3b  omkostning pr. rundtur, 15m  (RR 2:1, WR-antagelse {ASSUMED_WR:.0%}, "
        f"priser pr. {LOOKUP_DATE})",
        f"{'instrument':<36}{'ordretype':<11}{'rundtur_bp':>11}{'omk_R':>8}{'be_WR_%':>9}",
    ]
    for _, r in df.head(11).iterrows():
        lines.append(f"{r['instrument']:<36}{r['type']:<11}{r['bp']:>11.2f}"
                     f"{r['omk_R']:>8.3f}{r['be_wr']:>9.1f}")
    lines.append("-" * 75)
    lines.append("  maker-tal er ØVRE GRÆNSE for fordelen — adverse selection er ikke målt")
    return "\n".join(lines)


def adverse_selection_threshold(venues: pd.DataFrame) -> pd.DataFrame:
    """Hvor stor skal adverse selection være for at vende svaret?

    besparelse = omk_R(taker) − omk_R(maker). Adverse selection skal koste MERE end
    det pr. handel, før maker bliver det dårligste valg. Så er den umålte størrelse
    i det mindste afgrænset.
    """
    v = venues[venues.timeframe == "15m"]
    return pd.DataFrame([{
        "venue": r["venue"],
        "omk_R_taker": r["omk_R_taker"],
        "omk_R_stop_just": r["omk_R_stop_just"],
        "besparelse_R": round(r["omk_R_taker"] - r["omk_R_stop_just"], 3),
        "adverse_selection_må_koste_under_R": round(r["omk_R_taker"] - r["omk_R_stop_just"], 3),
    } for _, r in v.iterrows()])


def main() -> int:
    yaml.safe_load(open("config.yaml"))       # rører den ikke; læses kun for at fejle tidligt
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)

    print("Henter ATR pr. timeframe ...")
    atr = crypto_atr()
    prices = live_prices([c.yf_ticker for c in CONTRACTS.values()])
    print(f"Live futures-priser ({LOOKUP_DATE}): "
          + ", ".join(f"{k} {v:,.2f}" for k, v in prices.items()))

    print("\n\nDEL 1 — venue × ordretype (15m)")
    v = venue_table(atr)
    v.to_csv(OUTPUT_DIR / "venue_costs.csv", index=False)
    print(v[v.timeframe == "15m"][
        ["venue", "rundtur_bp_taker", "omk_R_taker", "be_wr_taker_%",
         "rundtur_bp_stop_just", "omk_R_stop_just", "be_wr_stop_just_%",
         "rundtur_bp_maker_100pct_fill", "omk_R_maker_100pct_fill"]].to_string(index=False))

    print("\n\nDEL 2 — futures-kontrakter")
    fut = futures_table(prices)
    fut.to_csv(OUTPUT_DIR / "futures_contracts.csv", index=False)
    print(fut[["kontrakt", "klasse", "notional_usd", "broker_pr_side", "exch_clear_pr_side",
               "gebyr_rundtur_usd", "spread_rundtur_usd", "gebyr_i_ticks", "i_alt_ticks",
               "gebyr_bp", "spread_bp", "i_alt_bp"]].to_string(index=False))

    print("\n\nDEL 3 — mikro mod fuldstor")
    mc = micro_check(prices)
    print(mc.to_string(index=False))

    print("\n\nFutures i R på 15m, med ±30% prisfølsomhed")
    fr = futures_in_R(prices)
    print(fr.to_string(index=False))

    print("\n\nAdverse selection-tærskel")
    adv = adverse_selection_threshold(v)
    print(adv.to_string(index=False))

    print("\n\n" + session_table(v, fr))

    from research.report_venues import build
    (OUTPUT_DIR / "venue_costs.md").write_text(
        build(v, fut, mc, fr, adv, prices, session_table(v, fr)), encoding="utf-8")
    print(f"\nRapport -> {OUTPUT_DIR / 'venue_costs.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
