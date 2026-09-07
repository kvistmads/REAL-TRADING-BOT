"""Rigtige omkostningstal, og hvad de kræver af en 15m-strategi.

Vores omkostningsmodel bygger på skøn. `cost_model.md` markerer det selv: 1 tick
spread og N(0,5; 0,5) ticks slippage er **modelantagelser uden datagrundlag.**

På 4h var det acceptabelt. På 15m er omkostningen pr. handel nogenlunde konstant
mens bevægelsen skrumper, så skønnet bliver den dominerende usikkerhed i alt vi
regner. **Vi bygger ingen 15m-strategi før vi ved hvad en handel koster.**

```bash
.venv/bin/python research/run_cost_analysis.py
```

**Ingen ny strategi. Ingen backtest af handelsregler. Måling og aritmetik.**
`backtest.costs` opdateres IKKE — forskellen mellem model og måling rapporteres,
og beslutningen om at rette modellen tages separat. Ændres den, bliver alle
tidligere resultater usammenlignelige.
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

from backtest import costs as cost_model  # noqa: E402
from research import spread_estimators as se  # noqa: E402
from research.cost_data import TIMEFRAMES, atr_pct, fetch  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
LOOKUP_DATE = "2026-09-07"

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XAU/USD", "EUR/USD", "GBP/USD"]

# --- DEL 1: gebyrer, slået op ---------------------------------------------
# Hvert tal har kilde og dato. Gebyrer ændrer sig, og et tal uden dato er ubrugeligt
# om seks måneder. "primær" = udbyderens egen side; "sekundær" = andenhåndskilde,
# markeret som sådan fordi den ikke kunne bekræftes på udbyderens egen side.
FEES = {
    "binance_spot": {
        "navn": "Binance spot, VIP 0",
        "maker_pct": 0.10, "taker_pct": 0.10,
        "bnb_rabat_pct": 25, "taker_med_bnb_pct": 0.075,
        "rundtur_taker_bp": 20.0, "rundtur_taker_bnb_bp": 15.0,
        "naeste_niveau": "VIP 1: ≥1.000.000 USD 30-dages volumen OG ≥5 BNB",
        "kilde": "binance.com/en/fee/schedule (primær)", "dato": LOOKUP_DATE,
    },
    "binance_futures": {
        "navn": "Binance USDⓈ-M futures, VIP 0",
        "maker_pct": 0.02, "taker_pct": 0.05,
        "bnb_rabat_pct": 10, "taker_med_bnb_pct": 0.045,
        "rundtur_taker_bp": 10.0, "rundtur_taker_bnb_bp": 9.0,
        "naeste_niveau": "samme VIP-stige som spot",
        "kilde": "flere sekundære kilder, enige (SEKUNDÆR — binance.com/en/fee/futureFee "
                 "kræver login og kunne ikke bekræftes)", "dato": LOOKUP_DATE,
    },
}

# Tradovate-planer: kurtage pr. side pr. kontrakt. Exchange/clearing og NFA er OVENI.
TRADOVATE = {
    "Free (0 kr/md)": {"micro": 0.39, "standard": 1.29, "maaned": 0},
    "Monthly (99 USD/md)": {"micro": 0.29, "standard": 0.99, "maaned": 99},
    "Lifetime (1.499 USD)": {"micro": 0.09, "standard": 0.59, "maaned": 0},
}
TRADOVATE_KILDE = "tradovate.com/pricing (primær)"

# Exchange + clearing pr. side for ikke-medlemmer, plus NFA 0,01 USD/kontrakt.
# Kilde: tradestation.com/pricing/exchange-execution-and-clearing-fees (primær,
# broker der offentliggør sine passthrough-satser).
CME_FEES = {
    #  kontrakt      exch+clear   multiplier  tick    typisk pris   klasse
    "MES": {"exch": 0.35, "mult": 5,      "tick": 0.25,    "px": 6000.0, "type": "micro"},
    "ES":  {"exch": 1.38, "mult": 50,     "tick": 0.25,    "px": 6000.0, "type": "standard"},
    "MNQ": {"exch": 0.35, "mult": 2,      "tick": 0.25,    "px": 22000.0, "type": "micro"},
    "NQ":  {"exch": 1.38, "mult": 20,     "tick": 0.25,    "px": 22000.0, "type": "standard"},
    "MGC": {"exch": 1.10, "mult": 10,     "tick": 0.10,    "px": 4000.0, "type": "micro"},
    "GC":  {"exch": 1.55, "mult": 100,    "tick": 0.10,    "px": 4000.0, "type": "standard"},
    "M6E": {"exch": 0.24, "mult": 12500,  "tick": 0.0001,  "px": 1.08,   "type": "micro"},
    "6E":  {"exch": 1.53, "mult": 125000, "tick": 0.00005, "px": 1.08,   "type": "standard"},
}
NFA_PER_SIDE = 0.01


def futures_round_turn(code: str, plan: str = "Free (0 kr/md)") -> dict:
    """Total rundtur pr. kontrakt — kurtage OG exchange, clearing og NFA.

    Det er totalen der rammer P&L, ikke den annoncerede kurtage. For mikrokontrakter
    er forskellen afgørende: gebyrerne er pr. KONTRAKT, mens notional er en tiendedel,
    så mikroer koster mange gange mere i basispunkter end de fuldstore.
    """
    spec = CME_FEES[code]
    comm = TRADOVATE[plan]["micro" if spec["type"] == "micro" else "standard"]
    per_side = comm + spec["exch"] + NFA_PER_SIDE
    notional = spec["mult"] * spec["px"]
    tick_bp = spec["tick"] / spec["px"] * 10_000
    return {
        "kontrakt": code, "type": spec["type"],
        "kurtage_pr_side": round(comm, 2),
        "exch_clear_pr_side": spec["exch"],
        "i_alt_pr_side": round(per_side, 2),
        "rundtur_usd": round(per_side * 2, 2),
        "notional_usd": round(notional),
        "gebyr_bp": round(per_side * 2 / notional * 10_000, 2),
        "et_tick_bp": round(tick_bp, 2),
        # Spread antages til ét tick (modellens antagelse) — markeret som skøn.
        "rundtur_i_alt_bp": round(per_side * 2 / notional * 10_000 + tick_bp, 2),
    }


def spread_analysis(config: dict) -> pd.DataFrame:
    """DEL 2a — Corwin-Schultz og Roll pr. symbol pr. timeframe, med støjgulv."""
    rows = []
    for symbol in SYMBOLS:
        params = cost_model._asset_costs(config, symbol)
        for tf in TIMEFRAMES:
            df = fetch(symbol, tf)
            if df.empty or len(df) < 100:
                continue
            adj = se.corwin_schultz(df, adjust_overnight=True)
            raw = se.corwin_schultz(df, adjust_overnight=False)
            floor = se.noise_floor(df, n_sims=8)
            r = se.roll_rolling(df, window=min(200, len(df) // 5))
            vol = se.volatility_split(df)
            px = float(df["close"].median())
            model_bp = _model_spread_bp(params, px)
            tick_bp = (float(params.get("tick_size", 0)) / px * 10_000
                       if params and params.get("mode") == "contract" else float("nan"))
            rows.append({
                "symbol": symbol, "timeframe": tf, "barer": len(df),
                "fra": str(df["time"].iloc[0].date()), "til": str(df["time"].iloc[-1].date()),
                "cs_justeret_bp": round(adj["spread_pct"] * 100, 2),
                "cs_raa_bp": round(raw["spread_pct"] * 100, 2),
                "stoejgulv_bp": round(floor["floor_pct"] * 100, 2),
                "over_gulv": adj["spread_pct"] > floor["floor_pct"] + 2 * floor["floor_sd_pct"],
                "negative_vinduer_%": adj["negative_share_pct"],
                "roll_bp": round(r["spread_pct"] * 100, 2) if np.isfinite(r["spread_pct"]) else None,
                "roll_udefineret_%": r["undefined_share_pct"],
                "rolig_bp": round(vol["calm_pct"] * 100, 2) if np.isfinite(vol["calm_pct"]) else None,
                "volatil_bp": round(vol["volatile_pct"] * 100, 2) if np.isfinite(vol["volatile_pct"]) else None,
                "volatil_forhold": vol["ratio"],
                "model_bp": round(model_bp, 2),
                "cs_i_ticks": round(adj["spread_pct"] * 100 / tick_bp, 2) if np.isfinite(tick_bp) and tick_bp else None,
                "atr_pct": round(atr_pct(df), 4),
            })
    return pd.DataFrame(rows)


def _model_spread_bp(params: dict | None, price: float) -> float:
    if not params:
        return float("nan")
    spread, _, _, _ = cost_model.cost_fractions(params, price)
    return spread * 10_000


def timeframe_scaling(spreads: pd.DataFrame) -> pd.DataFrame:
    """Den afgørende diagnose: **skalerer estimatet med bar-længden?**

    En rigtig bid-ask spread er en egenskab ved ORDREBOGEN. Den er den samme uanset
    om man ser på 5-minutters- eller 4-timers-barer. Skalerer estimatet med
    bar-længden, måler det volatilitet — ikke spread.

    Forholdet mellem 4h- og 5m-estimatet burde altså være ~1,0. Er det i nærheden af
    √48 ≈ 6,9, er estimatoren en volatilitetsmåler med et spread-navn.
    """
    rows = []
    for symbol, g in spreads.groupby("symbol"):
        by_tf = g.set_index("timeframe")["cs_justeret_bp"]
        floor = g.set_index("timeframe")["stoejgulv_bp"]
        if "5m" not in by_tf or "4h" not in by_tf:
            continue
        rows.append({
            "symbol": symbol,
            "cs_5m_bp": by_tf["5m"], "cs_15m_bp": by_tf.get("15m"),
            "cs_1h_bp": by_tf.get("1h"), "cs_4h_bp": by_tf["4h"],
            "forhold_4h_over_5m": round(by_tf["4h"] / by_tf["5m"], 1),
            "forventet_hvis_spread": 1.0,
            "forventet_hvis_volatilitet": round(np.sqrt(48), 1),
            # Ligger estimatet bare et fast stykke over sit eget støjgulv, er der
            # ingen selvstændig spread-information i det.
            "estimat_over_gulv_x": round(float((by_tf / floor).mean()), 2),
        })
    return pd.DataFrame(rows)


def stop_for_cost_limit(spreads: pd.DataFrame, config: dict,
                        limit: float = 0.20, tf: str = "15m") -> pd.DataFrame:
    """Ved hvilken stop-afstand koster en rundtur præcis ``limit`` R?

    Løst analytisk frem for ved gittersøgning: ``omk_R = rundtur% / (m × ATR%)``
    giver ``m = rundtur% / (limit × ATR%)``. Et gitter over 0,5-2,0 × ATR kan kun
    svare "over 2,0", og det er ikke et svar.
    """
    rows = []
    for symbol in SYMBOLS:
        sub = spreads[(spreads.symbol == symbol) & (spreads.timeframe == tf)]
        if sub.empty:
            continue
        atr = float(sub["atr_pct"].iloc[0])
        rt_pct = _round_turn_bp(config, symbol) / 100
        if not np.isfinite(atr) or atr <= 0:
            continue
        m = rt_pct / (limit * atr)
        rows.append({
            "symbol": symbol, "atr_15m_%": round(atr, 4),
            "rundtur_bp": round(rt_pct * 100, 2),
            "stop_xATR_for_0.20R": round(m, 2),
            "stop_i_%": round(m * atr, 3),
            "omk_R_ved_1xATR": round(rt_pct / atr, 3),
            "realistisk": m <= 2.0,
        })
    return pd.DataFrame(rows).sort_values("stop_xATR_for_0.20R")


def measured_spread() -> pd.DataFrame:
    """Målt spread fra orderbook-optageren — hvis der er optaget noget endnu."""
    from research.orderbook_recorder import load

    df = load()
    if df.empty:
        return pd.DataFrame()
    g = df.groupby("symbol")["spread_pct"].agg(["count", "median", "mean", "max"])
    g = (g * pd.Series({"count": 1, "median": 100, "mean": 100, "max": 100})).round(4)
    g.columns = ["n_snapshots", "median_bp", "middel_bp", "maks_bp"]
    g["n_snapshots"] = g["n_snapshots"].astype(int)
    return g.reset_index()


def breakeven_table(spreads: pd.DataFrame, config: dict) -> pd.DataFrame:
    """DEL 4 — hvad en strategi skal levere for at gå i nul.

        WR* = (L̄ + omkostning_i_R) / (W̄ + L̄)

    Med stoppet som 1R og målet som RR × 1R reducerer det til
    ``WR* = (1 + omk_R) / (RR + 1)``.

    **Det tal der betyder mest er omkostning som andel af 1R.** Bliver stoppet
    strammere på 15m — hvilket det bør, ellers giver timeframen ingen mening —
    stiger det tal, og win rate-kravet med det.
    """
    rows = []
    for symbol in SYMBOLS:
        params = cost_model._asset_costs(config, symbol)
        for tf in TIMEFRAMES:
            sub = spreads[(spreads.symbol == symbol) & (spreads.timeframe == tf)]
            if sub.empty:
                continue
            atr = float(sub["atr_pct"].iloc[0])
            if not np.isfinite(atr) or atr <= 0:
                continue
            px = 1.0
            summary = cost_model.cost_summary(config, symbol, float(sub["model_bp"].iloc[0]) or 1.0)
            del px, summary
            rt_bp = _round_turn_bp(config, symbol)
            for stop_mult in (0.5, 1.0, 1.5, 2.0):
                one_r = stop_mult * atr           # 1R i procent
                cost_r = (rt_bp / 100) / one_r    # rundtur i R
                for rr in (1.0, 1.5, 2.0, 3.0):
                    rows.append({
                        "symbol": symbol, "timeframe": tf, "stop_xATR": stop_mult,
                        "rr": rr, "1R_%": round(one_r, 4),
                        "rundtur_bp": round(rt_bp, 2),
                        "omk_R": round(cost_r, 4),
                        "be_wr_uden_omk_%": round(100 / (rr + 1), 1),
                        "be_wr_%": round(100 * (1 + cost_r) / (rr + 1), 1),
                        "wr_tillaeg_pp": round(100 * cost_r / (rr + 1), 1),
                    })
    return pd.DataFrame(rows)


def _round_turn_bp(config: dict, symbol: str) -> float:
    """Modellens samlede rundtur i basispunkter ved medianprisen."""
    params = cost_model._asset_costs(config, symbol)
    if not params:
        return 0.0
    px = {"BTC/USDT": 79000.0, "ETH/USDT": 2500.0, "SOL/USDT": 105.0,
          "XAU/USD": 4000.0, "EUR/USD": 1.08, "GBP/USD": 1.27}.get(symbol, 100.0)
    spread, slip, _, comm = cost_model.cost_fractions(params, px)
    return (spread + 2 * slip + comm) * 10_000


def session_table(be: pd.DataFrame, spreads: pd.DataFrame) -> str:
    """DEL 5 — sorteret efter omkostning i R, dyreste øverst. Maks ~15 linjer."""
    rule = be[(be.stop_xATR == 1.0) & (be.rr == 2.0)]
    agg = (rule.groupby("timeframe")
           .agg(**{"1R_%": ("1R_%", "median"), "omk_R": ("omk_R", "median"),
                   "rundtur_bp": ("rundtur_bp", "median"),
                   "be_wr_%": ("be_wr_%", "median")})
           .reindex([t for t in TIMEFRAMES if t in rule.timeframe.values]))
    lines = [
        "FASE 3  omkostninger pr. timeframe  (stop = 1,0 x ATR14, RR 2:1, medianer over 6 symboler)",
        f"{'timeframe':<11}{'1R_%':>8}{'rundtur_bp':>12}{'omk_R':>8}"
        f"{'be_WR_%':>9}{'uden_omk_%':>12}{'tillæg_pp':>11}",
    ]
    for tf, r in agg.iterrows():
        lines.append(
            f"{tf:<11}{r['1R_%']:>8.3f}{r['rundtur_bp']:>12.2f}{r['omk_R']:>8.3f}"
            f"{r['be_wr_%']:>9.1f}{33.3:>12.1f}{r['be_wr_%'] - 33.3:>11.1f}"
        )
    lines.append("-" * 71)
    crypto = rule[rule.symbol.str.contains("USDT")]
    other = rule[~rule.symbol.str.contains("USDT")]
    for name, grp in (("krypto", crypto), ("ikke-krypto", other)):
        g = grp[grp.timeframe == "15m"]
        if not g.empty:
            lines.append(f"{'  15m ' + name:<11}{g['1R_%'].median():>8.3f}"
                         f"{g['rundtur_bp'].median():>12.2f}{g['omk_R'].median():>8.3f}"
                         f"{g['be_wr_%'].median():>9.1f}{33.3:>12.1f}"
                         f"{g['be_wr_%'].median() - 33.3:>11.1f}")
    return "\n".join(lines)


def threshold_stop(be: pd.DataFrame, limit: float = 0.20) -> pd.DataFrame:
    """Ved hvilken stop-afstand på 15m koster en rundtur mere end 0,20 R?

    Ved det niveau skal strategien have en win rate 6-7 procentpoint over den
    omkostningsfri tærskel, bare for at gå i nul. Det er en grænse der er værd at
    kende før noget bygges.
    """
    rows = []
    for symbol, g in be[(be.timeframe == "15m") & (be.rr == 2.0)].groupby("symbol"):
        g = g.sort_values("stop_xATR")
        under = g[g.omk_R <= limit]
        rows.append({
            "symbol": symbol,
            "atr15m_%": round(float(g["1R_%"].iloc[0] / g["stop_xATR"].iloc[0]), 4),
            "rundtur_bp": float(g["rundtur_bp"].iloc[0]),
            "mindste_stop_under_0.20R": (float(under["stop_xATR"].min())
                                         if not under.empty else float("nan")),
            "omk_R_ved_1.0xATR": float(g[g.stop_xATR == 1.0]["omk_R"].iloc[0]),
            "omk_R_ved_0.5xATR": float(g[g.stop_xATR == 0.5]["omk_R"].iloc[0]),
        })
    return pd.DataFrame(rows)


def main() -> int:
    config = yaml.safe_load(open("config.yaml"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("DEL 1 — gebyrer, slået op\n")
    fut = pd.DataFrame([futures_round_turn(c) for c in CME_FEES])
    print(fut.to_string(index=False))

    print("\n\nDEL 2a — spread estimeret fra high/low ...")
    spreads = spread_analysis(config)
    spreads.to_csv(OUTPUT_DIR / "spread_estimates.csv", index=False)
    print(spreads[["symbol", "timeframe", "barer", "cs_justeret_bp", "stoejgulv_bp",
                   "over_gulv", "negative_vinduer_%", "roll_bp", "model_bp"]].to_string(index=False))

    print("\n\nDEL 2a — skalerer estimatet med bar-længden? (afgørende diagnose)")
    scaling = timeframe_scaling(spreads)
    print(scaling.to_string(index=False))

    print("\n\nDEL 2b — målt spread fra optageren")
    meas = measured_spread()
    print(meas.to_string(index=False) if not meas.empty else "  (ingen optagelser endnu)")

    print("\n\nDEL 4 — break-even")
    be = breakeven_table(spreads, config)
    be.to_csv(OUTPUT_DIR / "breakeven_table.csv", index=False)
    thr = stop_for_cost_limit(spreads, config)
    print(thr.to_string(index=False))

    print("\n\n" + session_table(be, spreads))

    _write_report(fut, spreads, be, thr, config, scaling, meas)
    print(f"\nRapport -> {OUTPUT_DIR / 'real_costs.md'}")
    return 0


def _write_report(fut, spreads, be, thr, config, scaling, meas) -> None:
    from research.report_costs import build

    (OUTPUT_DIR / "real_costs.md").write_text(
        build(fut, spreads, be, thr, scaling, meas, FEES, TRADOVATE, TRADOVATE_KILDE,
              CME_FEES, NFA_PER_SIDE, LOOKUP_DATE, session_table(be, spreads)),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
