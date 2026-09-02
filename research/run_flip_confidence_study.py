"""Forskningskørsel: virker confidence-scoren, og ville et flip-exit have hjulpet?

Én kørsel, to leverancer (PRD_FLIP_LEVEL_OG_CONFIDENCE):

* **Del B** — ``research/output/confidence_validation.md`` + ``.csv``:
  confidence-bånd, monotoni, korrelationer, delkomponenter og effekten af 0.65 → 0.45.
* **Del A** — ``research/output/flip_level_note.md``: hvor mange handler der overhovedet
  får et flip level, hvornår det brydes, og A1 (baseline) vs. A2 (flip-exit).

Data hentes ÉN gang og genbruges til begge kørsler — 6 symboler × 2 års 4h-data er
det dyre led, ikke simuleringen.

```bash
.venv/bin/python research/run_flip_confidence_study.py            # begge dele
.venv/bin/python research/run_flip_confidence_study.py --part b   # kun confidence
```

**Kørslen ændrer intet.** Den rører hverken ``config.yaml``, databasen eller
live-adfærden — den skriver to filer i ``research/output/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.runner import fetch_data, run_backtest  # noqa: E402
from research import stats  # noqa: E402
from strategies.registry import load_strategies  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# Præregistreret kriterium — LÅST FØR KØRSEL (PRD del B). Ændres ikke efter at have
# set tallene; det er hele pointen med at skrive det ned først.
CRITERION_MIN_GAP_PP = 5.0        # øverste kvartil skal slå nederste med >= 5 pp
CRITERION_MIN_N_PER_BAND = 150    # pr. kvartil pr. strategi
CRITERION_MIN_SYMBOLS_AGREE = 4   # af 6 symboler skal have samme fortegn

# Delkomponenterne i de to confidence-formler. Ligger allerede i Signal.metadata;
# testes hver for sig, fordi ét led kan bære al information — eller pege modsat.
COMPONENTS = {
    "trend_momentum": ["trend_strength", "cross_strength", "rsi_room"],
    "volatility_breakout": ["squeeze_intensity", "volume_strength", "macd_strength"],
}


# ---------------------------------------------------------------------------
# Kørsel
# ---------------------------------------------------------------------------

def collect_trades(config: dict, timeframe: str, flip_exit: bool,
                   data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Kør alle enabled strategier × alle symboler og saml én række pr. signal."""
    registry = load_strategies()
    strategies = registry.get_enabled(config["strategies"]["enabled"])
    rows: list[dict] = []
    for strategy in strategies:
        for symbol, df in data.items():
            if df is None or df.empty or len(df) < 200:
                continue
            label = "A2" if flip_exit else "A1"
            print(f"  [{label}] {strategy.name:22s} × {symbol:10s} ...",
                  end="", flush=True)
            trades = run_backtest(df.copy(), strategy, symbol, config,
                                  flip_exit=flip_exit)
            for t in trades:
                row = {k: v for k, v in t.items() if k != "signal_metadata"}
                row["strategy_id"] = strategy.name
                row["run"] = label
                # Udfaldet. end_of_data-trades er ikke rigtige udfald (handlen nåede
                # aldrig at lukke) og udelades af al statistik nedenfor.
                row["closed"] = t["reason"] != "end_of_data"
                row["won"] = t["pnl_pct"] > 0
                for key, value in (t.get("signal_metadata") or {}).items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        row[f"meta_{key}"] = value
                rows.append(row)
            print(f" {len(trades)} signaler")
    return pd.DataFrame(rows)


def _closed(df: pd.DataFrame) -> pd.DataFrame:
    """Kun handler med et rigtigt udfald — samme regel som backtest/metrics.py."""
    return df[df["closed"]] if "closed" in df.columns else df


# ---------------------------------------------------------------------------
# Del B — analyse
# ---------------------------------------------------------------------------

def confidence_bands(df: pd.DataFrame, q: int = 4) -> pd.DataFrame:
    """Confidence-kvartiler med win_rate, avg_pnl_pct, profit_factor og Wilson-CI.

    Kvartiler frem for faste tærskler: fordelingen er ukendt og har forskellige gulve
    pr. strategi (0.35 mod 0.40), så faste bånd ville ikke være sammenlignelige.
    """
    if df.empty:
        return pd.DataFrame()
    d = df.copy()
    try:
        d["band"] = pd.qcut(d["confidence"], q=q, duplicates="drop")
    except ValueError:
        return pd.DataFrame()

    out = []
    for band, g in d.groupby("band", observed=True):
        wins = int(g["won"].sum())
        n = len(g)
        low, high = stats.wilson_interval(wins, n)
        gains = g.loc[g["pnl_pct"] > 0, "pnl_pct"].sum()
        losses = -g.loc[g["pnl_pct"] < 0, "pnl_pct"].sum()
        out.append({
            "band": str(band),
            "conf_min": round(float(g["confidence"].min()), 4),
            "conf_max": round(float(g["confidence"].max()), 4),
            "n": n,
            "wins": wins,
            "win_rate_pct": round(100 * wins / n, 2),
            "wr_ci_low_pct": round(100 * low, 2),
            "wr_ci_high_pct": round(100 * high, 2),
            "avg_pnl_pct": round(float(g["pnl_pct"].mean()), 4),
            "profit_factor": round(float(gains / losses), 3) if losses > 0 else float("inf"),
        })
    return pd.DataFrame(out)


def monotonicity(bands: pd.DataFrame) -> dict:
    """Stiger win_rate med båndet? Ét bånd der stikker ud er støj; en trend er signal."""
    if len(bands) < 2:
        return {"steps_up": 0, "steps_total": 0, "strictly_increasing": False,
                "rank_corr": float("nan")}
    wr = bands["win_rate_pct"].to_numpy()
    steps_up = int((np.diff(wr) > 0).sum())
    return {
        "steps_up": steps_up,
        "steps_total": len(wr) - 1,
        "strictly_increasing": bool(steps_up == len(wr) - 1),
        # Rang-korrelation mellem båndets nummer og dets win_rate.
        "rank_corr": round(float(stats.spearman(np.arange(len(wr)), wr).r), 3),
    }


def component_tests(df: pd.DataFrame, components: list[str]) -> pd.DataFrame:
    """Hvert led i formlen testet mod udfaldet — bærer ét led al information?"""
    rows = []
    for comp in components:
        col = f"meta_{comp}"
        if col not in df.columns:
            continue
        sub = df[df[col].notna()]
        if len(sub) < 3:
            continue
        pb = stats.point_biserial(sub[col], sub["won"])
        sp = stats.spearman(sub[col], sub["pnl_pct"])
        rows.append({
            "component": comp,
            "n": pb.n,
            "corr_won": round(pb.r, 4),
            "p_won": round(pb.p_value, 5),
            "spearman_pnl": round(sp.r, 4),
            "p_pnl": round(sp.p_value, 5),
        })
    return pd.DataFrame(rows)


def threshold_effect(df: pd.DataFrame, old: float = 0.65, new: float = 0.45) -> dict:
    """Hvad slap igennem da tærsklen faldt fra 0.65 til 0.45 — og hvordan klarede de sig?"""
    above_old = df[df["confidence"] >= old]
    between = df[(df["confidence"] >= new) & (df["confidence"] < old)]
    below_new = df[df["confidence"] < new]

    def _wr(sub):
        if sub.empty:
            return None
        wins = int(sub["won"].sum())
        low, high = stats.wilson_interval(wins, len(sub))
        return {
            "n": len(sub),
            "win_rate_pct": round(100 * wins / len(sub), 2),
            "ci_pct": [round(100 * low, 2), round(100 * high, 2)],
            "avg_pnl_pct": round(float(sub["pnl_pct"].mean()), 4),
        }

    result = {
        "above_0.65": _wr(above_old),
        "extra_0.45_to_0.65": _wr(between),
        "below_0.45_never_traded_live": _wr(below_new),
    }
    if not above_old.empty and not between.empty:
        diff = stats.proportion_diff_interval(
            int(between["won"].sum()), len(between),
            int(above_old["won"].sum()), len(above_old),
        )
        result["extra_minus_above_pp"] = round(
            100 * (between["won"].mean() - above_old["won"].mean()), 2
        )
        result["extra_minus_above_ci_pp"] = [round(100 * diff[0], 2), round(100 * diff[1], 2)]
    return result


def top_vs_bottom(df: pd.DataFrame, bands: pd.DataFrame) -> dict:
    """Øverste mod nederste kvartil — det præregistrerede kriteriums kerne."""
    if len(bands) < 2:
        return {}
    lo, hi = bands.iloc[0], bands.iloc[-1]
    gap = hi["win_rate_pct"] - lo["win_rate_pct"]
    ci = stats.proportion_diff_interval(
        int(hi["wins"]), int(hi["n"]), int(lo["wins"]), int(lo["n"])
    )
    n_min = int(min(hi["n"], lo["n"]))
    return {
        "gap_pp": round(float(gap), 2),
        "ci_pp": [round(100 * ci[0], 2), round(100 * ci[1], 2)],
        "n_top": int(hi["n"]),
        "n_bottom": int(lo["n"]),
        "meets_gap": bool(gap >= CRITERION_MIN_GAP_PP),
        "meets_n": bool(n_min >= CRITERION_MIN_N_PER_BAND),
        "min_detectable_pp": round(100 * stats.min_detectable_diff(n_min), 2),
    }


def per_symbol_signs(df: pd.DataFrame) -> pd.DataFrame:
    """Har øverste halvdel højere win_rate end nederste — pr. symbol?

    Halvdele frem for kvartiler pr. symbol: med ~50-100 handler pr. symbol ville
    kvartiler give bånd på et dusin handler, hvor fortegnet er ren møntkast.
    """
    rows = []
    for symbol, g in df.groupby("symbol"):
        if len(g) < 8:
            rows.append({"symbol": symbol, "n": len(g), "gap_pp": None, "sign": "n/a"})
            continue
        median = g["confidence"].median()
        high = g[g["confidence"] >= median]
        low = g[g["confidence"] < median]
        if high.empty or low.empty:
            rows.append({"symbol": symbol, "n": len(g), "gap_pp": None, "sign": "n/a"})
            continue
        gap = 100 * (high["won"].mean() - low["won"].mean())
        rows.append({
            "symbol": symbol, "n": len(g),
            "n_high": len(high), "n_low": len(low),
            "wr_high_pct": round(100 * high["won"].mean(), 2),
            "wr_low_pct": round(100 * low["won"].mean(), 2),
            "gap_pp": round(float(gap), 2),
            "sign": "+" if gap > 0 else ("-" if gap < 0 else "0"),
        })
    return pd.DataFrame(rows)


def analyse_strategy(df: pd.DataFrame, strategy_id: str) -> dict:
    sub = _closed(df[df["strategy_id"] == strategy_id])
    bands = confidence_bands(sub)
    return {
        "strategy_id": strategy_id,
        "n_signals": int(len(df[df["strategy_id"] == strategy_id])),
        "n_closed": int(len(sub)),
        "n_would_pass_production": int(sub["would_pass_production"].sum()) if not sub.empty else 0,
        "win_rate_pct": round(100 * float(sub["won"].mean()), 2) if not sub.empty else None,
        "min_confidence_seen": round(float(sub["confidence"].min()), 4) if not sub.empty else None,
        "bands": bands,
        "monotonicity": monotonicity(bands),
        "top_vs_bottom": top_vs_bottom(sub, bands),
        "corr_confidence_won": stats.point_biserial(sub["confidence"], sub["won"]),
        "corr_confidence_pnl": stats.spearman(sub["confidence"], sub["pnl_pct"]),
        "components": component_tests(sub, COMPONENTS.get(strategy_id, [])),
        "threshold_effect": threshold_effect(sub),
        "per_symbol": per_symbol_signs(sub),
    }


# ---------------------------------------------------------------------------
# Del A — flip level
# ---------------------------------------------------------------------------

def flip_coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Hvor mange handler får overhovedet et flip level — og hvornår brydes det?

    Dækningen tælles over ALLE signaler (spørgsmålet er om strategien overhovedet kan
    formulere sin egen invalidering). Timing-fordelingen tælles kun over handler der
    faktisk lukkede: for en ``end_of_data``-handel er "før/efter exit" meningsløst,
    fordi der ikke var nogen exit.
    """
    rows = []
    for strategy_id, g in df.groupby("strategy_id"):
        n = len(g)
        with_level = int(g["flip_level"].notna().sum())
        closed = _closed(g)
        timing = closed["flip_timing"].value_counts()
        rows.append({
            "strategy_id": strategy_id,
            "n_trades": n,
            "with_flip_level": with_level,
            "with_flip_level_pct": round(100 * with_level / n, 1) if n else 0.0,
            "n_closed": len(closed),
            "before_exit": int(timing.get("before_exit", 0)),
            "after_exit": int(timing.get("after_exit", 0)),
            "never": int(timing.get("never", 0)),
            "no_flip_level": int(timing.get("no_flip_level", 0)),
        })
    return pd.DataFrame(rows)


def flip_outcome_split(df: pd.DataFrame) -> pd.DataFrame:
    """Win_rate og avg_pnl for handler hvor flip level blev brudt vs. ikke brudt.

    Det er splittet der adskiller "tesen var forkert" fra "stoppet var for stramt".
    """
    d = _closed(df)
    rows = []
    for (strategy_id, timing), g in d.groupby(["strategy_id", "flip_timing"]):
        wins = int(g["won"].sum())
        low, high = stats.wilson_interval(wins, len(g))
        rows.append({
            "strategy_id": strategy_id,
            "flip_timing": timing,
            "n": len(g),
            "win_rate_pct": round(100 * wins / len(g), 2),
            "wr_ci_pct": f"[{100 * low:.1f}, {100 * high:.1f}]",
            "avg_pnl_pct": round(float(g["pnl_pct"].mean()), 4),
        })
    return pd.DataFrame(rows)


def compare_runs(a1: pd.DataFrame, a2: pd.DataFrame) -> pd.DataFrame:
    """A1 (baseline) mod A2 (flip-exit) pr. strategi × symbol."""
    def _metrics(df):
        d = _closed(df)
        if d.empty:
            return {"trades": 0, "win_rate_pct": 0.0, "profit_factor": 0.0,
                    "avg_pnl_pct": 0.0, "total_pnl_pct": 0.0, "flip_exits": 0}
        gains = d.loc[d["pnl_pct"] > 0, "pnl_pct"].sum()
        losses = -d.loc[d["pnl_pct"] < 0, "pnl_pct"].sum()
        return {
            "trades": len(d),
            "win_rate_pct": round(100 * float(d["won"].mean()), 2),
            "profit_factor": round(float(gains / losses), 3) if losses > 0 else float("inf"),
            "avg_pnl_pct": round(float(d["pnl_pct"].mean()), 4),
            "total_pnl_pct": round(float(d["pnl_pct"].sum()), 2),
            "flip_exits": int((d["reason"] == "flip_level").sum()),
        }

    rows = []
    for (strategy_id, symbol), g1 in a1.groupby(["strategy_id", "symbol"]):
        g2 = a2[(a2["strategy_id"] == strategy_id) & (a2["symbol"] == symbol)]
        m1, m2 = _metrics(g1), _metrics(g2)
        rows.append({
            "strategy_id": strategy_id, "symbol": symbol,
            "a1_trades": m1["trades"], "a2_trades": m2["trades"],
            "a1_wr_pct": m1["win_rate_pct"], "a2_wr_pct": m2["win_rate_pct"],
            "wr_delta_pp": round(m2["win_rate_pct"] - m1["win_rate_pct"], 2),
            "a1_pf": m1["profit_factor"], "a2_pf": m2["profit_factor"],
            "a1_avg_pnl_pct": m1["avg_pnl_pct"], "a2_avg_pnl_pct": m2["avg_pnl_pct"],
            "a1_total_pnl_pct": m1["total_pnl_pct"], "a2_total_pnl_pct": m2["total_pnl_pct"],
            "a2_flip_exits": m2["flip_exits"],
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Rapporter
# ---------------------------------------------------------------------------

def _md_table(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_(ingen data)_\n"
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    lines = [header, sep]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(
            "" if pd.isna(v) else ("inf" if v == float("inf") else str(v))
            for v in row
        ) + " |")
    return "\n".join(lines) + "\n"


def write_confidence_report(results: list[dict], meta: dict, path: Path) -> Path:
    n_bands_ok = [r for r in results if r["top_vs_bottom"].get("meets_n")]
    gap_ok = [r for r in results if r["top_vs_bottom"].get("meets_gap")]
    symbols_ok = []
    for r in results:
        signs = r["per_symbol"]
        if not signs.empty and "sign" in signs:
            symbols_ok.append(int((signs["sign"] == "+").sum()))
        else:
            symbols_ok.append(0)

    criterion_met = (
        len(gap_ok) == len(results)
        and len(n_bands_ok) == len(results)
        and all(s >= CRITERION_MIN_SYMBOLS_AGREE for s in symbols_ok)
    )
    underpowered = len(n_bands_ok) < len(results)

    L: list[str] = []
    L.append("# Virker confidence-scoren?\n")
    L.append(f"**Kørt:** {meta['run_at']}  ")
    L.append(f"**Data:** {meta['timeframe']}, {meta['n_symbols']} symboler, "
             f"{meta['period']}  ")
    L.append(f"**Backtest:** ingen confidence-gate (strategien kaldes med "
             f"`min_confidence: 0.0`); live-tærsklen er uændret "
             f"{meta['production_min_confidence']}\n")
    L.append("> Forskningskørsel. `config.yaml`, databasen og live-adfærden er urørt.\n")

    L.append("## Svar\n")
    if criterion_met:
        L.append("**Kriteriet er opfyldt** — scoren diskriminerer på begge strategier.\n")
    elif underpowered:
        L.append("**Kan ikke afgøres med denne stikprøve.** Kriteriet krævede "
                 f"≥{CRITERION_MIN_N_PER_BAND} handler pr. kvartil pr. strategi, og det "
                 "har vi ikke. Et resultat under den mindst detekterbare forskel "
                 "(kolonnen `min_detectable_pp` nedenfor) er ikke bevis for at scoren "
                 "ikke virker — det er fravær af bevis.\n")
    else:
        L.append("**Kriteriet er ikke opfyldt** på det tilgængelige datagrundlag.\n")

    L.append("### Hvor meget filtrerer gaten overhovedet?\n")
    gate_rows = []
    for r in results:
        n, passed = r["n_closed"], r["n_would_pass_production"]
        gate_rows.append({
            "strategi": r["strategy_id"],
            "signaler": n,
            "over 0,45": passed,
            "afvist af gaten": n - passed,
            "afvist %": round(100 * (n - passed) / n, 1) if n else 0.0,
            "laveste confidence set": r["min_confidence_seen"],
        })
    L.append(_md_table(pd.DataFrame(gate_rows)))
    total_rejected = sum(r["n_closed"] - r["n_would_pass_production"] for r in results)
    total_n = sum(r["n_closed"] for r in results)
    L.append(f"\n`min_confidence: 0.45` afviser **{total_rejected} af {total_n}** genererede "
             "signaler. Det er et selvstændigt fund uafhængigt af om scoren diskriminerer: "
             "en gate der ikke afviser noget kan hverken koste eller gavne. For en strategi "
             "hvis laveste observerede confidence ligger OVER tærsklen, er gaten aritmetisk "
             "inaktiv.\n")

    L.append("### Præregistreret kriterium (låst før kørsel)\n")
    L.append(f"Scoren virker hvis øverste kvartil slår nederste med "
             f"**≥{CRITERION_MIN_GAP_PP} pp win_rate**, på **begge** strategier, med "
             f"**≥{CRITERION_MIN_N_PER_BAND} handler pr. kvartil pr. strategi**, og med "
             f"samme fortegn på mindst **{CRITERION_MIN_SYMBOLS_AGREE} af 6 symboler**.\n")
    crit_rows = []
    for r, n_plus in zip(results, symbols_ok):
        tvb = r["top_vs_bottom"]
        crit_rows.append({
            "strategi": r["strategy_id"],
            "gap_pp": tvb.get("gap_pp"),
            "95%-CI (pp)": str(tvb.get("ci_pp")),
            "n_top/n_bund": f"{tvb.get('n_top')}/{tvb.get('n_bottom')}",
            f"gap≥{CRITERION_MIN_GAP_PP}": "ja" if tvb.get("meets_gap") else "nej",
            f"n≥{CRITERION_MIN_N_PER_BAND}": "ja" if tvb.get("meets_n") else "NEJ",
            "symboler med +": f"{n_plus}/6",
            "min. synlig forskel (pp)": tvb.get("min_detectable_pp"),
        })
    L.append(_md_table(pd.DataFrame(crit_rows)))

    L.append("\n### Statistisk styrke — en reel begrænsning, ikke en formalitet\n")
    L.append("For at se et gab på 5 pp med 80% styrke kræves ~1.566 handler pr. bånd. "
             "Kolonnen `min_detectable_pp` ovenfor er hvad stikprøven her realistisk "
             "kan afsløre. Ligger det målte gab under den, er konklusionen "
             "**\"kan ikke afgøres\"** — ikke \"virker ikke\".\n")

    for r in results:
        L.append(f"\n## {r['strategy_id']}\n")
        unfinished = r["n_signals"] - r["n_closed"]
        L.append(f"{r['n_signals']} signaler, {r['n_closed']} med et rigtigt udfald"
                 + (f" ({unfinished} var stadig åbne da data slap op)" if unfinished else "")
                 + f". {r['n_would_pass_production']} ville have passeret live-gaten. "
                 f"Samlet win rate: {r['win_rate_pct']}%.\n")

        L.append("\n### Confidence-kvartiler\n")
        L.append(_md_table(r["bands"]))

        mono = r["monotonicity"]
        L.append(f"\n**Monotoni:** {mono['steps_up']} af {mono['steps_total']} trin "
                 f"stiger (rang-korrelation bånd↔win_rate: {mono['rank_corr']}). "
                 + ("Strengt stigende.\n" if mono["strictly_increasing"]
                    else "Ikke strengt stigende — et enkelt bånd der stikker ud er støj.\n"))

        L.append("\n### Korrelation\n")
        L.append(f"- confidence ↔ `won` (punkt-biseriel): {r['corr_confidence_won']}\n")
        L.append(f"- confidence ↔ `pnl_pct` (Spearman): {r['corr_confidence_pnl']}\n")

        L.append("\n### Delkomponenter\n")
        L.append("Ét led kan bære al information mens resten er støj — eller pege "
                 "den forkerte vej. Negativ `corr_won` betyder at leddet trækker "
                 "confidence op netop når handlen taber.\n\n")
        L.append(_md_table(r["components"]))
        n_tests = 2 * len(r["components"]) if len(r["components"]) else 0
        if n_tests:
            L.append(f"\n**Multiple sammenligninger:** der er kørt {n_tests} tests i denne "
                     "tabel (hver komponent mod både `won` og `pnl_pct`), og over begge "
                     "strategier "
                     f"{2 * sum(len(x['components']) for x in results)} i alt. Ved alpha 5% "
                     "forventes cirka én p-værdi under 0,05 ved rent tilfælde. En enkelt "
                     "grænsesignifikant komponent er derfor ikke et fund — den skal "
                     "gentages ud af stikprøven før den betyder noget.\n")

        L.append("\n### Effekten af 0.65 → 0.45\n")
        te = r["threshold_effect"]
        te_rows = []
        for key, label in [("above_0.65", "over 0,65 (gammel tærskel)"),
                           ("extra_0.45_to_0.65", "ekstra: 0,45–0,65"),
                           ("below_0.45_never_traded_live", "under 0,45 (handles aldrig live)")]:
            v = te.get(key)
            if v:
                te_rows.append({
                    "bånd": label, "n": v["n"], "win_rate_pct": v["win_rate_pct"],
                    "95%-CI (pp)": str(v["ci_pct"]), "avg_pnl_pct": v["avg_pnl_pct"],
                })
        L.append(_md_table(pd.DataFrame(te_rows)))
        if "extra_minus_above_pp" in te:
            L.append(f"\nDe ekstra handler ligger **{te['extra_minus_above_pp']} pp** "
                     f"fra dem over 0,65 (95%-CI {te['extra_minus_above_ci_pp']} pp).\n")

        L.append("\n### Pr. symbol (øverste mod nederste halvdel)\n")
        L.append(_md_table(r["per_symbol"]))

    L.append("\n## Hvad der IKKE er gjort\n")
    L.append("- `config.yaml` er urørt. `strategies.min_confidence: 0.45` står som den var.\n")
    L.append("- Ingen nye vægte foreslås. At tune formlen indtil båndene adskiller sig "
             "er fitting, ikke måling; et forslag skal testes ud af stikprøven.\n")
    L.append("- Ingen ændring af exits, gates eller entry-logik.\n")

    L.append("\n## Forbehold ved stikprøven\n")
    L.append("- Backtesten springer frem til en åben handel er lukket, så signaler der "
             "opstår mens en position er åben kommer ikke med. Springet afhænger af den "
             "FORRIGE handels varighed, ikke af det aktuelle signals confidence, så "
             "udvalget er kun svagt afhængigt af det vi måler — men det er ikke nul.\n")
    L.append("- `end_of_data`-handler indgår ikke: de har ingen exit og dermed intet udfald.\n")
    L.append("- Kvartilgrænserne er stikprøveafhængige og flytter sig med nye data.\n")

    path.write_text("\n".join(L), encoding="utf-8")
    return path


def write_flip_note(coverage: pd.DataFrame, outcome: pd.DataFrame,
                    comparison: pd.DataFrame, meta: dict, path: Path) -> Path:
    L: list[str] = []
    L.append("# Flip level — dækning, timing og hvad et flip-exit ville have kostet\n")
    L.append(f"**Kørt:** {meta['run_at']}  ")
    L.append(f"**Data:** {meta['timeframe']}, {meta['n_symbols']} symboler, {meta['period']}\n")
    L.append("> I live er flip level **observe-only** — det lukker ingen handel. "
             "A2 nedenfor er en måling af det spørgsmål, ikke en beslutning.\n")

    L.append("\n## Hvor mange handler får et flip level?\n")
    L.append("En strategi der ikke kan formulere hvad der ville modbevise den, er en "
             "holdning frem for en strategi — derfor tælles `no_flip_level` med.\n\n")
    L.append(_md_table(coverage))
    L.append("\n**Niveauerne:** `trend_momentum` bruger EMA50 ved entry. "
             "`volatility_breakout` bruger `breakout_level` — det niveau der faktisk blev "
             "brudt (resistance for long, support for short) — frem for den modsatte side "
             "af rangen, som kunne være `None` og først ville bryde efter en fuld rundtur. "
             "Begge findes derfor altid.\n")

    L.append("\n## Hvornår brydes det?\n")
    L.append("- `before_exit` — tesen var modbevist mens vi stadig sad i handlen\n")
    L.append("- `after_exit` — den holdt så længe vi var med; brud kom bagefter "
             "(inden for handlens maksimale levetid)\n")
    L.append("- `never` — holdt hele vejen\n\n")
    L.append(_md_table(outcome))
    L.append("\nDet er dette split der skiller to modsatrettede rettelser: tabt med "
             "flip level intakt peger på et for stramt stop, tabt efter et brud peger "
             "på selve signalet.\n")

    L.append("\n### Læs IKKE forskellen mellem `never` og `before_exit` som en forudsigelse\n")
    L.append("Gabet mellem de to grupper er stort, men det er i høj grad **mekanisk, ikke "
             "prædiktivt**. Flip level ligger pr. konstruktion på handlens tabende side "
             "(EMA50 under en long-entry, det brudte niveau under et long-breakout). En "
             "handel der vinder, bevæger sig væk fra niveauet og kan derfor næsten ikke "
             "bryde det; en der taber, bevæger sig imod det. \"Aldrig brudt\" er langt hen "
             "ad vejen en omskrivning af \"gik den rigtige vej\" — ikke en uafhængig "
             "indikator man kan filtrere på.\n")
    L.append("\nDe tal der faktisk siger noget nyt er **`before_exit` mod `after_exit`** "
             "(begge er handler hvor niveauet blev brudt — forskellen er om det skete mens "
             "vi sad i den) og **A2-sammenligningen** nedenfor, som er en ægte fremadrettet "
             "test: dér træffes en anden beslutning, og resultatet kan gå begge veje.\n")

    L.append("\n## A1 (baseline) mod A2 (flip-exit)\n")
    L.append(_md_table(comparison))

    if not comparison.empty:
        wr_delta = comparison["wr_delta_pp"].mean()
        pnl_a1 = comparison["a1_total_pnl_pct"].sum()
        pnl_a2 = comparison["a2_total_pnl_pct"].sum()
        flips = comparison["a2_flip_exits"].sum()
        L.append(f"\n**Samlet:** {int(flips)} handler blev lukket af flip-exit i A2. "
                 f"Gennemsnitlig win_rate-ændring: {wr_delta:+.2f} pp. "
                 f"Total PnL: {pnl_a1:.2f}% (A1) → {pnl_a2:.2f}% (A2).\n")

    L.append("\n## Hvad der IKKE er gjort\n")
    L.append("- Live-adfærden er uændret: flip level registreres, det lukker ingen handel.\n")
    L.append("- Ingen exit-regler, stops eller gates er ændret ud fra tallene.\n")

    path.write_text("\n".join(L), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--part", choices=["a", "b", "all"], default="all",
                        help="a = flip level, b = confidence, all = begge (default)")
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = yaml.safe_load(open(args.config))
    symbols = config["symbols"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Henter data for {len(symbols)} symboler ({args.timeframe})...")
    data: dict[str, pd.DataFrame] = {}
    period_start, period_end = None, None
    for symbol in symbols:
        print(f"  {symbol:10s} ...", end="", flush=True)
        try:
            df = fetch_data(symbol, args.timeframe)
            data[symbol] = df
            if not df.empty:
                lo, hi = df["time"].iloc[0], df["time"].iloc[-1]
                period_start = lo if period_start is None else min(period_start, lo)
                period_end = hi if period_end is None else max(period_end, hi)
            print(f" {len(df)} barer")
        except Exception as e:
            data[symbol] = None
            print(f" FEJL: {type(e).__name__}: {str(e)[:80]}")

    meta = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "timeframe": args.timeframe,
        "n_symbols": sum(1 for d in data.values() if d is not None and not d.empty),
        "period": (f"{period_start.date()} → {period_end.date()}"
                   if period_start is not None else "ukendt"),
        "production_min_confidence": config["strategies"]["min_confidence"],
    }

    print("\nA1 — baseline (eksisterende exits):")
    a1 = collect_trades(config, args.timeframe, flip_exit=False, data=data)
    if a1.empty:
        print("Ingen trades genereret — afbryder.")
        return 1

    csv_path = OUTPUT_DIR / "confidence_validation.csv"
    a1.to_csv(csv_path, index=False)
    print(f"\n  Rådata ({len(a1)} signaler) gemt til {csv_path}")

    if args.part in ("b", "all"):
        results = [analyse_strategy(a1, sid) for sid in config["strategies"]["enabled"]]
        md = write_confidence_report(results, meta, OUTPUT_DIR / "confidence_validation.md")
        print(f"  Del B-rapport: {md}")

    if args.part in ("a", "all"):
        print("\nA2 — flip-exit:")
        a2 = collect_trades(config, args.timeframe, flip_exit=True, data=data)
        a2.to_csv(OUTPUT_DIR / "flip_exit_trades.csv", index=False)
        note = write_flip_note(
            flip_coverage(a1), flip_outcome_split(a1), compare_runs(a1, a2),
            meta, OUTPUT_DIR / "flip_level_note.md",
        )
        print(f"  Del A-notat: {note}")

    (OUTPUT_DIR / "flip_confidence_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    print("\nFærdig. config.yaml, databasen og live-adfærden er urørt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
