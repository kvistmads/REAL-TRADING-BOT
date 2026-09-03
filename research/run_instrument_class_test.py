"""Har `trend_momentum` en edge, og afhænger den af instrumentklasse?

Efter flip-exit-testen så det ud som om strategiens fortegnsskifte mellem halvdelene
skyldtes krypto. Den opgørelse var i procent af entrypris — og ATR i procent er 5-9×
større på krypto end på EUR/USD, så krypto vil dominere både gevinster og tab uanset
om strategien er bedre eller dårligere dér. Denne test måler i **R**.

Tre spørgsmål, rapporteret med samme vægt:

1. **Hovedspørgsmålet:** er krypto skadelig for strategien? (præregistreret kriterium)
2. **Modcasen:** har strategien nogen edge overhovedet — også på ikke-krypto?
3. **Break-even:** hvilken win rate KRÆVER de observerede haler, pr. instrument?

Punkt 3 afgør reelt de to andre. Alt andet er en omvej til det spørgsmål.

```bash
.venv/bin/python research/run_instrument_class_test.py
```

**Ændrer intet.** Live-adfærd, config og database er urørt.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import math

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import report, rnorm  # noqa: E402
from backtest.runner import fetch_data, run_backtest  # noqa: E402
from research import stats  # noqa: E402
from strategies.base import BaseStrategy  # noqa: E402
from strategies.registry import load_strategies  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
STRATEGY = "trend_momentum"
WARMUP = 200

# --- LÅST FØR KØRSEL ------------------------------------------------------
# Grupperne følger aktivklasse, ikke resultat, og justeres ikke efter kørslen.
GROUPS = {
    "krypto": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    "ikke-krypto": ["EUR/USD", "GBP/USD", "XAU/USD"],
}

# Forudsigelse låst før kørsel (fra censussens haler W=1.472R, L=0.694R):
# break-even WR 32,0% brutto, 33,2% ved ikke-kryptos omkostning, 35,7% ved kryptos.
# Observeret WR var 33,80% brutto. Forventning: krypto klart negativ i R,
# ikke-krypto omkring nul. Falder kørslen markant anderledes ud, RAPPORTÉR
# uoverensstemmelsen frem for at forklare den.
PREDICTION = {
    "breakeven_gross_pct": 32.0,
    "breakeven_noncrypto_pct": 33.2,
    "breakeven_crypto_pct": 35.7,
    "observed_wr_pct": 33.80,
    "expect_crypto": "klart negativ i R",
    "expect_noncrypto": "omkring nul",
    # Hvor stor en afvigelse der tæller som "markant anderledes" og udløser et STOP.
    "tolerance_pp": 3.0,
}


def group_of(symbol: str) -> str:
    return "krypto" if symbol in GROUPS["krypto"] else "ikke-krypto"


def split_halves(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    mid = len(df) // 2
    return df.iloc[:mid].copy(), df.iloc[max(0, mid - WARMUP):].copy()


def _closed(trades: list[dict]) -> list[dict]:
    return [t for t in trades if t.get("reason") != "end_of_data"]


# ---------------------------------------------------------------------------
# R-dekomponering — vinder- og taberhalen hver for sig
# ---------------------------------------------------------------------------

def r_decomposition(trades: list[dict]) -> dict:
    """Vinder- og taberhalen hver for sig, plus den break-even WR de faktisk kræver.

    Vinder/taber afgøres på BRUTTO, og W/L er brutto-R: omkostningen indgår separat
    i break-even-formlen, ellers ville den tælle to gange. Den observerede WR der
    skal sammenlignes med tærsklen er derfor også brutto-WR.
    """
    with_r = [t for t in trades if t.get("r_multiple_gross") is not None]
    n = len(with_r)
    if n == 0:
        return {"n": 0}

    win_r = [t["r_multiple_gross"] for t in with_r if t["pnl_pct"] > 0]
    loss_r = [abs(t["r_multiple_gross"]) for t in with_r if t["pnl_pct"] <= 0]
    net_r = [t["r_multiple_net"] for t in with_r]
    cost_r = [t.get("cost_in_r") or 0.0 for t in with_r]

    w_mean = float(np.mean(win_r)) if win_r else 0.0
    l_mean = float(np.mean(loss_r)) if loss_r else 0.0
    # Profit factor på NETTO-R: summen af positive mod summen af negative. Må ikke
    # udledes af brutto-halerne — så ville kolonnen hedde "netto" og vise brutto.
    pos = sum(r for r in net_r if r > 0)
    neg = -sum(r for r in net_r if r < 0)
    pf_net = (pos / neg) if neg > 0 else (float("inf") if pos > 0 else 0.0)
    c_mean = float(np.mean(cost_r))
    wr_gross = len(win_r) / n
    wr_net = sum(1 for t in with_r if t["pnl_pct_net"] > 0) / n
    be = stats.breakeven_win_rate(w_mean, l_mean, c_mean)
    lo, hi = stats.mean_ci(net_r)

    return {
        "n": n,
        "wr_gross_pct": round(100 * wr_gross, 2),
        "wr_net_pct": round(100 * wr_net, 2),
        "W_gns_R": round(w_mean, 4),
        "L_gns_R": round(l_mean, 4),
        "W_median_R": round(float(np.median(win_r)), 4) if win_r else None,
        "L_median_R": round(float(np.median(loss_r)), 4) if loss_r else None,
        "W_iqr_R": round(float(np.subtract(*np.percentile(win_r, [75, 25]))), 4)
                   if len(win_r) > 1 else None,
        "L_iqr_R": round(float(np.subtract(*np.percentile(loss_r, [75, 25]))), 4)
                   if len(loss_r) > 1 else None,
        "cost_R": round(c_mean, 4),
        "pf_net": round(pf_net, 3) if pf_net != float("inf") else float("inf"),
        "WR_breakeven_pct": round(100 * be, 2) if be == be else None,
        # Positiv margin = den observerede WR ligger OVER det krævede.
        "WR_margin_pp": round(100 * (wr_gross - be), 2) if be == be else None,
        "R_per_trade_gross": round(float(np.mean([t["r_multiple_gross"] for t in with_r])), 4),
        "R_per_trade_net": round(float(np.mean(net_r)), 4),
        "R_net_ci_low": round(lo, 4) if lo == lo else None,
        "R_net_ci_high": round(hi, 4) if hi == hi else None,
        "R_net_sd": round(float(np.std(net_r, ddof=1)), 4) if n > 1 else None,
        "pnl_pct_per_trade_net": round(float(np.mean([t["pnl_pct_net"] for t in with_r])), 4),
    }


def decomposition_table(buckets: dict[str, list[dict]], label: str) -> pd.DataFrame:
    rows = []
    for name, trades in buckets.items():
        d = r_decomposition(trades)
        if not d.get("n"):
            continue
        rows.append({
            label: name, "n": d["n"],
            "WR_brut_%": d["wr_gross_pct"], "WR_net_%": d["wr_net_pct"],
            "WR_breakeven_%": d["WR_breakeven_pct"],
            "margin_pp": d["WR_margin_pp"],
            "W_gns_R": d["W_gns_R"], "L_gns_R": d["L_gns_R"],
            "W_median_R": d["W_median_R"], "L_median_R": d["L_median_R"],
            "omkost_R": d["cost_R"], "PF_net": d["pf_net"],
            "R/handel_brut": d["R_per_trade_gross"],
            "R/handel_net": d["R_per_trade_net"],
            "95%-CI": f"[{d['R_net_ci_low']}, {d['R_net_ci_high']}]",
            "PnL/handel_%": d["pnl_pct_per_trade_net"],
        })
    return pd.DataFrame(rows)


def breakeven_decomposition(per_symbol: dict[str, list[dict]]) -> pd.DataFrame:
    """Opdel break-even-tærsklen i sit omkostnings- og sit haleformsbidrag.

    Break-even-tabellen er IKKE en strukturel egenskab ved instrumentet. Formlen
    omskrives til en forventningsværdi:

        E = (W̄ + L̄) · [WR − WR*]        hvor WR* = (L̄ + c)/(W̄ + L̄)

    Margin er altså forventningsværdien divideret med (W̄+L̄) — samme tal, anden
    enhed. Og WR* falder fra hinanden i to led:

        WR* = L̄/(W̄+L̄)   +   c/(W̄+L̄)
              ^ haleform      ^ omkostning

    Kun omkostningsleddet er kendt på forhånd og en egenskab ved instrumentet.
    Haleformsleddet er REALISERET i denne stikprøve og dermed støjfyldt: et symbol
    med heldige haler får mekanisk en lavere tærskel.
    """
    rows = []
    for symbol, trades in per_symbol.items():
        d = r_decomposition(trades)
        if not d.get("n"):
            continue
        denom = d["W_gns_R"] + d["L_gns_R"]
        if denom <= 0:
            continue
        tail = d["L_gns_R"] / denom
        cost = d["cost_R"] / denom
        rows.append({
            "symbol": symbol, "gruppe": group_of(symbol),
            "W_gns_R": d["W_gns_R"], "L_gns_R": d["L_gns_R"],
            "WR_breakeven_%": d["WR_breakeven_pct"],
            "haleform_bidrag_%": round(100 * tail, 2),
            "omkostning_bidrag_%": round(100 * cost, 2),
        })
    return pd.DataFrame(rows)


def half_difference(by_half: dict, bucket: str) -> dict:
    """Halvdel 1 minus halvdel 2 i R/handel, med konfidensinterval.

    To uafhængige stikprøver (forskellige perioder), så variansen lægges sammen:
    SE = sqrt(SE1² + SE2²). Krydser intervallet nul, er "tidseffekten" ikke påvist
    — og så er den ikke et bedre fund end instrumenteffekten var.
    """
    halves = list(by_half.keys())
    if len(halves) != 2:
        return {}
    a = [t["r_multiple_net"] for t in by_half[halves[0]].get(bucket, [])
         if t.get("r_multiple_net") is not None]
    b = [t["r_multiple_net"] for t in by_half[halves[1]].get(bucket, [])
         if t.get("r_multiple_net") is not None]
    if len(a) < 2 or len(b) < 2:
        return {}
    arr_a, arr_b = np.asarray(a), np.asarray(b)
    diff = float(arr_a.mean() - arr_b.mean())
    se = math.sqrt(arr_a.var(ddof=1) / len(a) + arr_b.var(ddof=1) / len(b))
    z = 1.959963984540054
    lo, hi = diff - z * se, diff + z * se
    return {
        "gruppe": bucket, "n_1": len(a), "n_2": len(b),
        "R_halvdel_1": round(float(arr_a.mean()), 4),
        "R_halvdel_2": round(float(arr_b.mean()), 4),
        "forskel": round(diff, 4),
        "95%-CI": f"[{lo:.4f}, {hi:.4f}]",
        "krydser_nul": "ja" if lo <= 0 <= hi else "nej",
    }


# ---------------------------------------------------------------------------
# Præregistreret kriterium
# ---------------------------------------------------------------------------

def evaluate_criterion(by_half: dict) -> dict:
    """Krypto er skadelig hvis alle tre holder — fejler ét, er svaret 'ikke påvist'."""
    crypto_neg, noncrypto_higher, gross_too = {}, {}, {}
    for half, groups in by_half.items():
        c = r_decomposition(groups.get("krypto", []))
        nc = r_decomposition(groups.get("ikke-krypto", []))
        if not c.get("n") or not nc.get("n"):
            continue
        crypto_neg[half] = c["R_per_trade_net"] < 0
        noncrypto_higher[half] = nc["R_per_trade_net"] > c["R_per_trade_net"]
        gross_too[half] = nc["R_per_trade_gross"] > c["R_per_trade_gross"]

    halves = len(crypto_neg)
    return {
        "crypto_negative": crypto_neg,
        "noncrypto_higher": noncrypto_higher,
        "gross_too": gross_too,
        "c1": halves == 2 and all(crypto_neg.values()),
        "c2": halves == 2 and all(noncrypto_higher.values()),
        "c3": halves == 2 and all(gross_too.values()),
    }


# ---------------------------------------------------------------------------
# Kontinuert test — omkostning_i_R mod afkast
# ---------------------------------------------------------------------------

def continuous_test(per_symbol: dict[str, list[dict]]) -> dict:
    """Falder R/handel netto monotont med instrumentets omkostning i R?

    Legitim at tilføje efter censussen, fordi omkostning_i_R er en EGENSKAB ved
    instrumentet, målt før nogen afkasttal blev set. Havde inddelingen fulgt afkast,
    ville det være datamining. Med n=6 er styrken uanset ringe.
    """
    rows = []
    for symbol, trades in per_symbol.items():
        d = r_decomposition(trades)
        if d.get("n"):
            rows.append({
                "symbol": symbol,
                "gruppe": group_of(symbol),
                "omkost_R": d["cost_R"],
                "R/handel_net": d["R_per_trade_net"],
                "n": d["n"],
            })
    df = pd.DataFrame(rows).sort_values("omkost_R").reset_index(drop=True)
    if len(df) < 3:
        return {"table": df, "rho": None, "p": None, "ci": None, "n": len(df)}

    corr = stats.spearman(df["omkost_R"], df["R/handel_net"])
    lo, hi = stats.spearman_ci(corr.r, len(df))
    return {
        "table": df, "rho": round(corr.r, 4), "p": round(corr.p_value, 4),
        "ci": (round(lo, 3), round(hi, 3)), "n": len(df),
    }


def daily_return_correlation(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Parvis korrelation mellem symbolernes DAGLIGE afkast.

    Tre symboler pr. gruppe er ikke tre uafhængige observationer når de er stærkt
    korrelerede — nærmere én til to. Det skal stå i rapporten, ikke kun i PRD'en.
    """
    series = {}
    for symbol, df in data.items():
        if df is None or df.empty:
            continue
        s = df.set_index("time")["close"].resample("1D").last().dropna()
        series[symbol] = s.pct_change().dropna()
    if len(series) < 2:
        return pd.DataFrame()
    return pd.DataFrame(series).corr(method="pearson").round(3)


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

def _md(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_(ingen data)_\n"
    head = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    lines = [head, sep]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join("—" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines) + "\n"


def check_prediction(overall: dict[str, list[dict]]) -> dict:
    """Sammenlign med den låste forudsigelse. Afvigelse rapporteres, ikke bortforklares."""
    c = r_decomposition(overall.get("krypto", []))
    nc = r_decomposition(overall.get("ikke-krypto", []))
    notes, mismatch = [], False

    for name, d, expected_be in (
        ("krypto", c, PREDICTION["breakeven_crypto_pct"]),
        ("ikke-krypto", nc, PREDICTION["breakeven_noncrypto_pct"]),
    ):
        if not d.get("n"):
            continue
        diff = d["WR_breakeven_pct"] - expected_be
        if abs(diff) > PREDICTION["tolerance_pp"]:
            mismatch = True
            notes.append(
                f"- **{name}:** break-even WR målt til {d['WR_breakeven_pct']}%, "
                f"forudsagt {expected_be}% — afvigelse {diff:+.2f} pp, over "
                f"tolerancen på {PREDICTION['tolerance_pp']} pp."
            )
        else:
            notes.append(
                f"- {name}: break-even WR {d['WR_breakeven_pct']}% mod forudsagt "
                f"{expected_be}% ({diff:+.2f} pp) — inden for tolerancen."
            )

    if c.get("n"):
        sign_ok = c["R_per_trade_net"] < 0
        notes.append(f"- krypto R/handel netto = {c['R_per_trade_net']:+.4f} "
                     f"({'negativ som forudsagt' if sign_ok else 'IKKE negativ — modsat forudsigelsen'})")
        mismatch = mismatch or not sign_ok
    if nc.get("n"):
        near_zero = nc["R_net_ci_low"] is not None and nc["R_net_ci_low"] <= 0 <= nc["R_net_ci_high"]
        notes.append(f"- ikke-krypto R/handel netto = {nc['R_per_trade_net']:+.4f}, "
                     f"95%-CI [{nc['R_net_ci_low']}, {nc['R_net_ci_high']}] "
                     f"({'overlapper nul som forudsagt' if near_zero else 'OVERLAPPER IKKE nul'})")
    return {"mismatch": mismatch, "notes": notes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = yaml.safe_load(open(args.config))
    strategy = load_strategies().get(STRATEGY)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Henter data ({args.timeframe})...")
    data, quality = {}, []
    for symbol in config["symbols"]:
        print(f"  {symbol:10s} ...", end="", flush=True)
        try:
            df = fetch_data(symbol, args.timeframe)
            data[symbol] = df
            flat = int((df["high"] == df["low"]).sum())
            quality.append({
                "symbol": symbol, "gruppe": group_of(symbol), "barer": len(df),
                "fra": f"{df['time'].iloc[0]:%Y-%m-%d}", "til": f"{df['time'].iloc[-1]:%Y-%m-%d}",
                "flade_barer": flat,
                "flade_pct": round(100 * flat / len(df), 3) if len(df) else 0.0,
                "kasserede": 0,
            })
            print(f" {len(df)} barer ({df['time'].iloc[0]:%Y-%m} → {df['time'].iloc[-1]:%Y-%m})")
        except Exception as e:
            data[symbol] = None
            print(f" FEJL: {type(e).__name__}: {str(e)[:70]}")

    per_symbol: dict[str, list[dict]] = {}
    by_half: dict[str, dict[str, list[dict]]] = {
        "1. halvdel": {"krypto": [], "ikke-krypto": []},
        "2. halvdel": {"krypto": [], "ikke-krypto": []},
    }
    per_symbol_half: dict[str, dict[str, list[dict]]] = {
        "1. halvdel": {}, "2. halvdel": {}}
    periods: dict[str, str] = {}

    for symbol, df in data.items():
        if df is None or df.empty or len(df) < WARMUP + 10:
            continue
        first, second = split_halves(df)
        periods.setdefault("1. halvdel", f"{first['time'].iloc[0]:%Y-%m}→{first['time'].iloc[-1]:%Y-%m}")
        periods.setdefault("2. halvdel", f"{second['time'].iloc[WARMUP]:%Y-%m}→{second['time'].iloc[-1]:%Y-%m}")
        per_symbol[symbol] = []
        for half, part in (("1. halvdel", first), ("2. halvdel", second)):
            print(f"  [{half}] {symbol:10s} ...", end="", flush=True)
            trades = _closed(run_backtest(part, strategy, symbol, config, warmup=WARMUP))
            per_symbol[symbol] += trades
            per_symbol_half[half][symbol] = trades
            by_half[half][group_of(symbol)] += trades
            print(f" {len(trades)} handler")

    overall = {g: [t for s in syms for t in per_symbol.get(s, [])]
               for g, syms in GROUPS.items()}
    all_trades = [t for ts in per_symbol.values() for t in ts]

    verdict = evaluate_criterion(by_half)
    cont = continuous_test(per_symbol)
    corr_df = daily_return_correlation(data)
    pred = check_prediction(overall)

    nc = r_decomposition(overall["ikke-krypto"])
    c = r_decomposition(overall["krypto"])
    sd = r_decomposition(all_trades).get("R_net_sd") or 0.0
    mdd = rnorm.min_detectable_r(min(c.get("n", 0), nc.get("n", 0)), sd)

    # Hovedkonklusionen afhænger af modcasen, ikke af gruppekriteriet: overlapper
    # ikke-krypto nul i BEGGE halvdele, er svaret ikke "drop krypto" men "ingen
    # påvist edge nogen steder". Det afgøres her frem for i læserens hoved.
    nc_halves = [r_decomposition(by_half[h].get("ikke-krypto", [])) for h in by_half]
    nc_overlaps_both = all(
        d.get("n") and d["R_net_ci_low"] is not None
        and d["R_net_ci_low"] <= 0 <= d["R_net_ci_high"]
        for d in nc_halves
    )
    criterion_met = verdict["c1"] and verdict["c2"] and verdict["c3"]
    if nc_overlaps_both:
        headline = (
            "**Strategien har ingen påvist edge på noget instrument.** Ikke-kryptos "
            "R/handel netto overlapper nul i BEGGE halvdele, så konklusionen er ikke "
            "\"drop krypto\" — det er at der ikke er demonstreret en edge nogen steder. "
            "Krypto er dér hvor tabene er størst, men det følger af at volatiliteten "
            "er størst dér, ikke af at strategien er påviseligt dårligere."
        )
    elif criterion_met:
        headline = ("**Krypto er klassificeret som skadelig** — alle tre præregistrerede "
                    "krav er opfyldt.")
    else:
        headline = ("**Ikke påvist.** Mindst ét af de tre præregistrerede krav fejler, "
                    "og så leder vi ikke efter en delmængde hvor det ser bedre ud.")

    # ---------------- rapport ----------------
    L = [
        "# Instrumentklasse-test: har trend_momentum en edge, og hvor?\n",
        f"**Kørt:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}  ",
        f"**Strategi:** {STRATEGY}, uden gates, uden flip-exit  ",
        f"**Halvdel 1:** {periods.get('1. halvdel','—')} · **Halvdel 2:** {periods.get('2. halvdel','—')}\n",
        "\n> **Stikprøven er ikke udvidet.** yfinance leverer kun 1-times-data 730 dage "
        "tilbage (Yahoo: *\"The requested range must be within the last 730 days\"*), så "
        "forex og guld kan ikke gå længere tilbage uden en ny datakilde. Krypto kunne, "
        "men så ville grupperne dække forskellige perioder og sammenligningen være "
        "konfunderet. Resultatet er derfor **underpowered** — se styrkeafsnittet.\n",
        "\n## Svar\n",
        headline + "\n",
        f"\nPræregistreret kriterium: krav 1 {'opfyldt' if verdict['c1'] else 'FEJLER'}, "
        f"krav 2 {'opfyldt' if verdict['c2'] else 'FEJLER'}, "
        f"krav 3 {'opfyldt' if verdict['c3'] else 'FEJLER'} "
        f"→ **{'krypto klassificeret som skadelig' if criterion_met else 'ikke påvist'}**.\n",
        "\n## 1. Break-even — det tal der afgør alt andet\n",
        "Antagelsen +2R/−1R giver en break-even WR på 33,3%. De FAKTISKE haler er "
        "komprimerede af breakeven-stop og time-stop, så tærsklen ligger et andet sted. "
        "`margin_pp` er observeret WR minus den krævede: positiv = strategien tjener.\n\n",
        _md(decomposition_table({s: t for s, t in per_symbol.items()}, "symbol")),
        "\n### Pr. gruppe\n",
        _md(decomposition_table(overall, "gruppe")),
        "\n### Hvad \"kræver\"-kolonnen faktisk er\n",
        "Break-even-tærsklen er **ikke** en strukturel egenskab ved instrumentet. "
        "Formlen er en omskrivning af forventningsværdien:\n\n"
        "```\nE = (W̄ + L̄) · [WR − WR*]     hvor WR* = (L̄ + c)/(W̄ + L̄)\n```\n\n"
        "`margin_pp` er altså forventningsværdien divideret med (W̄+L̄) — samme tal i "
        "en anden enhed. Og tærsklen falder fra hinanden i to led:\n\n"
        "```\nWR* = L̄/(W̄+L̄)  +  c/(W̄+L̄)\n      ^ haleform     ^ omkostning\n```\n\n",
        _md(breakeven_decomposition(per_symbol)),
        "\n**Kun omkostningsbidraget er en instrumentegenskab.** Det er kendt på "
        "forhånd og ligger mellem 0,2 og 4,9 procentpoint. Haleformsbidraget er "
        "REALISERET i denne stikprøve: et symbol med heldige haler får mekanisk en "
        "lavere tærskel, og spredningen i \"kræver\"-kolonnen er derfor overvejende "
        "udfald — ikke struktur. Læs den ikke som at guld er et lettere instrument "
        "end BTC; læs den som at guld havde bedre haler i netop disse to år.\n",
        "\n## 2. Præregistreret kriterium (låst før kørsel)\n",
        "Krypto klassificeres som skadelig hvis **alle tre** holder. Fejler ét, er "
        "svaret \"ikke påvist\" — og så leder vi ikke efter en delmængde hvor det ser "
        "bedre ud.\n\n",
        _md(pd.DataFrame([
            {"krav": "1. Krypto negativ R/handel netto i begge halvdele",
             "opfyldt": "ja" if verdict["c1"] else "NEJ",
             "detalje": ", ".join(f"{h}: {'ja' if v else 'nej'}"
                                  for h, v in verdict["crypto_negative"].items())},
            {"krav": "2. Ikke-krypto højere end krypto i begge halvdele",
             "opfyldt": "ja" if verdict["c2"] else "NEJ",
             "detalje": ", ".join(f"{h}: {'ja' if v else 'nej'}"
                                  for h, v in verdict["noncrypto_higher"].items())},
            {"krav": "3. Forskellen findes også brutto",
             "opfyldt": "ja" if verdict["c3"] else "NEJ",
             "detalje": ", ".join(f"{h}: {'ja' if v else 'nej'}"
                                  for h, v in verdict["gross_too"].items())},
        ])),
        "\n### Pr. halvdel\n",
    ]
    for half, groups in by_half.items():
        L.append(f"\n**{half}**\n")
        L.append(_md(decomposition_table(groups, "gruppe")))

    L += [
        "\n### Er forskellen mellem halvdelene overhovedet påvist?\n",
        "Rapporten fremhævede tidligere at begge grupper forværres ~0,26 R mellem "
        "halvdelene, uden usikkerhed på det tal. Her er den:\n\n",
        _md(pd.DataFrame([r for r in (
            half_difference(by_half, "krypto"),
            half_difference(by_half, "ikke-krypto"),
        ) if r])),
        "\n## 3. Modcasen — har strategien en edge NOGEN steder?\n",
        "Den mest sandsynlige forklaring er ikke at krypto er specielt dårligt, men at "
        "strategien ikke har nogen edge nogen steder og at tabene samler sig hvor "
        "volatiliteten er størst.\n\n",
        _md(pd.DataFrame([
            {"gruppe": g, "n": d["n"], "R/handel_net": d["R_per_trade_net"],
             "95%-CI": f"[{d['R_net_ci_low']}, {d['R_net_ci_high']}]",
             "overlapper_nul": "ja" if (d["R_net_ci_low"] is not None
                                        and d["R_net_ci_low"] <= 0 <= d["R_net_ci_high"])
                               else "nej"}
            for g, d in (("krypto", c), ("ikke-krypto", nc)) if d.get("n")
        ])),
        f"\n**Mindste forskel stikprøven kan afsløre:** {mdd:.4f} R "
        f"(80% styrke, alpha 5%, spredning {sd:.3f} R, n≈{min(c.get('n',0), nc.get('n',0))} "
        "pr. gruppe). En målt forskel mindre end det er \"kan ikke afgøres\", ikke "
        "\"ingen forskel\".\n",
        "\n## 4. Kontinuert test — falder afkast med omkostning i R?\n",
        "Rapporteret **ved siden af** gruppekriteriet; det er gruppekriteriet der "
        "afgør dommen. Legitim fordi `omkost_R` er en egenskab ved instrumentet, målt "
        "før afkasttallene blev set.\n\n",
        _md(cont["table"]),
    ]
    if cont["rho"] is not None:
        L.append(f"\nSpearman(omkost_R, R/handel_net) = **{cont['rho']}** "
                 f"(p={cont['p']}, n={cont['n']}, 95%-CI {cont['ci']}).\n")
        L.append("\nMed seks punkter er intervallet så bredt at det er foreneligt med "
                 "næsten enhver sammenhæng. Korrelationen er en indikation, ikke et bevis.\n")

    L += [
        "\n## 5. Uafhængighed — symbolerne er ikke seks observationer\n",
        "Parvis korrelation mellem daglige afkast i perioden:\n\n",
        _md(corr_df.reset_index().rename(columns={"index": ""})),
        "\nEr korrelationen inden for en gruppe høj, er tre symboler nærmere én til to "
        "uafhængige observationer. Det halverer reelt den styrke gruppetesten har, "
        "oven i den lille stikprøve.\n",
        "\n## 6. Forudsigelsen, låst før kørsel\n",
        f"Forventet: krypto {PREDICTION['expect_crypto']}, ikke-krypto "
        f"{PREDICTION['expect_noncrypto']}. Break-even forudsagt til "
        f"{PREDICTION['breakeven_gross_pct']}% brutto, "
        f"{PREDICTION['breakeven_noncrypto_pct']}% / "
        f"{PREDICTION['breakeven_crypto_pct']}% ved de to gruppers omkostning.\n\n",
        "\n".join(pred["notes"]) + "\n",
    ]
    if pred["mismatch"]:
        L.append("\n> **STOP — kørslen afviger markant fra forudsigelsen.** Enten er "
                 "break-even-regnestykket forkert, eller også er der noget i kørslen vi "
                 "ikke forstår. Afvigelsen rapporteres her frem for at blive forklaret.\n")

    L += [
        "\n## Datagrundlag\n", _md(pd.DataFrame(quality)),
        "\n## Hvad der IKKE er gjort\n",
        "- Ingen konfigurationsændringer foreslået. Live-adfærd er urørt.\n",
        "- Ingen symboler tilføjet eller fjernet.\n",
        "- Grupperne er ikke justeret efter at have set resultatet.\n",
        "- Flip level forbliver observe-only.\n",
    ]

    path = OUTPUT_DIR / "instrument_class_test.md"
    path.write_text("\n".join(L), encoding="utf-8")
    pd.DataFrame(all_trades).to_csv(OUTPUT_DIR / "instrument_class_trades.csv", index=False)

    # ---------------- sessionstabel (DEL 4) ----------------
    print()
    print(f"BACKTEST  {STRATEGY}  "
          f"{periods.get('1. halvdel','—')} + {periods.get('2. halvdel','—')}  "
          f"A1 uden gates, i R")
    print(f"{'gruppe/symbol':<14} {'n':>4} {'WR':>7} {'WR_be':>7} {'PF-net':>7} "
          f"{'R/handel':>9} {'omkost_R':>9}")
    for symbol in config["symbols"]:
        d = r_decomposition(per_symbol.get(symbol, []))
        if not d.get("n"):
            continue
        print(f"{symbol:<14} {d['n']:>4} {d['wr_gross_pct']:>6.1f}% "
              f"{d['WR_breakeven_pct']:>6.1f}% {d['pf_net']:>7.2f} "
              f"{d['R_per_trade_net']:>+9.4f} {d['cost_R']:>9.4f}")
    for g, d in (("KRYPTO", c), ("IKKE-KRYPTO", nc)):
        if not d.get("n"):
            continue
        print(f"{g:<14} {d['n']:>4} {d['wr_gross_pct']:>6.1f}% "
              f"{d['WR_breakeven_pct']:>6.1f}% {d['pf_net']:>7.2f} "
              f"{d['R_per_trade_net']:>+9.4f} {d['cost_R']:>9.4f}")

    print(f"\nKriterium: 1={verdict['c1']}  2={verdict['c2']}  3={verdict['c3']}")
    print(f"Rapport: {path}")
    if pred["mismatch"]:
        print("\n*** AFVIGELSE FRA FORUDSIGELSEN — se rapportens afsnit 6 ***")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
