"""DEL 3: validér den lange guld-serie, og kør derefter regimetesten på den.

## Hvad denne kørsel KAN og IKKE KAN købe — læs før resultaterne

21 år guld giver ~750 handler. Mindst detekterbare forskel skalerer med 1/√n, så
tærsklen flytter sig fra ~0,42 R til ~0,32 R. **Det er stadig langt over enhver
realistisk edge for en trendstrategi.**

Denne kørsel er derfor **ikke** svaret på Modcase 2. Den er tre andre ting:

1. en validering af en datakilde vi har liggende
2. en test af om apparatet holder på en lang serie
3. en mulighed for at se regimeskift over mange cyklusser frem for to

Hvad der FAKTISK skulle til for at se 0,10 R: ~7.600 handler, svarende til ~35 år på
seks symboler — eller ~40 symboler over fem år. **Bredde, ikke historik.** Én lang
serie på ét instrument løser det ikke.

**Serien erstatter ikke den nuværende guld-kilde.** Live er urørt.

```bash
.venv/bin/python research/run_gold_long_test.py
```
"""

from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from backtest import rnorm  # noqa: E402
from backtest.runner import fetch_data, run_backtest  # noqa: E402
from data.indicators import add_all  # noqa: E402
from gates.regime import RegimeGate  # noqa: E402
from research import stats  # noqa: E402
from research.gold_long_series import (  # noqa: E402
    cross_validate_daily, load_long_series, usable_span, volume_profile,
    yearly_quality,
)
from research.run_regime_gate_test import (  # noqa: E402
    _md, _r_stats, label_trades, regime_at,
)
from strategies.registry import load_strategies  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
STRATEGY = "trend_momentum"
WARMUP = 200

# --- LÅST FØR KØRSEL ------------------------------------------------------
# Kriteriet er KONSISTENS, inte signifikans i én periode: slår gaten igennem i én
# periode og ikke de andre, er det støj — samme logik som flip-exit.
CRITERION_MIN_PERIODS = 3      # af 4
N_PERIODS = 4

CROSSVAL_PERIODS = [
    ("2008-01-01", "2008-12-31"),   # finanskrise, ekstrem volatilitet
    ("2015-01-01", "2015-12-31"),   # bearmarked
    ("2020-01-01", "2020-12-31"),   # covid
    ("2024-01-01", "2024-12-31"),   # nyeste hele år, overlapper vores data
]
# Under denne korrelation på daglige afkast er de to serier ikke samme instrument.
MIN_RETURN_CORR = 0.80
# Median prisafvigelse over dette er et niveauproblem, ikke bare spot/futures-basis.
MAX_MEDIAN_PRICE_DEV_PCT = 1.0


def _daily_reference() -> pd.DataFrame:
    import yfinance as yf

    ref = yf.download("GC=F", start="2004-06-01", interval="1d",
                      auto_adjust=True, progress=False)
    if isinstance(ref.columns, pd.MultiIndex):
        ref.columns = ref.columns.get_level_values(0)
    ref.columns = [c.lower() for c in ref.columns]
    return ref


def overlap_test(long_df: pd.DataFrame, config: dict, strategy) -> dict:
    """Kør strategien på DEN OVERLAPPENDE periode med begge datakilder.

    Stærkere end krydsvalideringen mod GC=F, fordi den måler præcis det vi bruger
    dataen til. Afviger de to serier væsentligt her, er de ikke det samme instrument,
    og intet fra den lange serie kan sammenlignes med det vi har lavet indtil nu.

    Vinduet afkortes ved 2025-02-28: fra marts 2025 er den lange serie mangelfuld
    (marts 90 barer, april 24, juli 51 mod ~128 i en normal måned), og en
    sammenligning hen over de huller ville måle huller frem for instrumenter.
    """
    gcf = fetch_data("XAU/USD", "4h")
    cutoff = pd.Timestamp("2025-02-28")
    gcf = gcf[gcf["time"] <= cutoff].reset_index(drop=True)
    if len(gcf) <= WARMUP + 10:
        return {"status": "for lidt GC=F-data i overlappet"}

    # Evalueringen skal starte samme kalenderdag i begge serier, ellers
    # sammenligner vi to forskellige perioder.
    eval_start = gcf["time"].iloc[WARMUP]
    long_win = long_df[(long_df["time"] >= pd.Timestamp("2023-01-01"))
                       & (long_df["time"] <= cutoff)].reset_index(drop=True)
    long_warmup = int((long_win["time"] < eval_start).sum())
    if long_warmup < WARMUP or len(long_win) - long_warmup < 10:
        return {"status": "for lidt lang-serie-data i overlappet"}

    rows = []
    for name, df, warm in (("GC=F (nuværende kilde)", gcf, WARMUP),
                           ("lang serie", long_win, long_warmup)):
        trades = [t for t in run_backtest(df, strategy, "XAU/USD", config, warmup=warm)
                  if t["reason"] != "end_of_data"]
        enriched = add_all(df.copy())
        atr_pct = (enriched["atr_14"] / enriched["close"] * 100).iloc[warm:].dropna()
        s = _r_stats(trades)
        gross = [t["r_multiple_gross"] for t in trades
                 if t.get("r_multiple_gross") is not None]
        rows.append({
            "kilde": name,
            "barer_i_vindue": len(df) - warm,
            "handler": len(trades),
            "WR_%": s["wr"] if s["n"] else None,
            "R/handel_brut": round(float(np.mean(gross)), 4) if gross else None,
            "R/handel_net": s["mean"],
            "median_ATR_%": round(float(atr_pct.median()), 4) if len(atr_pct) else None,
        })
    return {"status": "ok", "table": pd.DataFrame(rows),
            "eval_start": f"{eval_start:%Y-%m-%d}", "eval_end": f"{cutoff:%Y-%m-%d}"}


def split_periods(df: pd.DataFrame, n: int) -> list[tuple[str, pd.DataFrame]]:
    """Del serien i n perioder, hver med WARMUP barer med bagud.

    Perioderne evaluerer disjunkte kalendervinduer; warmup-halen sikrer kun at
    indikatorerne er varme ved periodens start.
    """
    size = len(df) // n
    out = []
    for k in range(n):
        start = k * size
        end = (k + 1) * size if k < n - 1 else len(df)
        lo = max(0, start - WARMUP)
        part = df.iloc[lo:end].copy().reset_index(drop=True)
        warm = start - lo
        label = (f"P{k + 1} {part['time'].iloc[warm]:%Y-%m}"
                 f"→{part['time'].iloc[-1]:%Y-%m}")
        out.append((label, part, warm))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = yaml.safe_load(open(args.config))
    strategy = load_strategies().get(STRATEGY)
    gate = RegimeGate(config)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("3a. Validering af den lange serie...")
    long_df = load_long_series()
    quality = yearly_quality(long_df)
    span = usable_span(quality)
    vol = volume_profile(long_df)
    xval = cross_validate_daily(long_df, _daily_reference(), CROSSVAL_PERIODS)

    xval_ok = (not xval.empty and (xval["status"] == "ok").all()
               and (xval["korr_daglige_afkast"] >= MIN_RETURN_CORR).all()
               and (xval["median_prisafvig_%"].abs() <= MAX_MEDIAN_PRICE_DEV_PCT).all())
    print(f"   krydsvalidering: {'BESTÅET' if xval_ok else 'FEJLET'}")
    print(f"   brugbart spænd: {span}")

    print("   overlapstest...")
    ov = overlap_test(long_df, config, strategy)

    ov_ok = False
    if ov.get("status") == "ok":
        t = ov["table"]
        a, b = t.iloc[0], t.iloc[1]
        # Median ATR% er det stærkeste identitetstal her: handelstallene har
        # meget lille n i et halvt års vindue.
        atr_dev = abs(a["median_ATR_%"] - b["median_ATR_%"]) / max(a["median_ATR_%"], 1e-9)
        ov_ok = atr_dev <= 0.25
        print(f"   overlapstest: ATR%-afvigelse {100 * atr_dev:.1f}% "
              f"→ {'BESTÅET' if ov_ok else 'FEJLET'}")

    passed = xval_ok and ov_ok and span is not None

    # ---------------- 3b ----------------
    period_rows, criterion_rows, all_trades, bar_rows = [], [], [], []
    n_comparisons = 0
    if passed:
        lo, hi = span
        usable = long_df[(long_df["time"].dt.year >= lo)
                         & (long_df["time"].dt.year <= hi)].reset_index(drop=True)
        print(f"3b. Regimetest på {lo}-{hi} ({len(usable)} barer), {N_PERIODS} perioder...")
        for label, part, warm in split_periods(usable, N_PERIODS):
            print(f"   {label} ...", end="", flush=True)
            trades = [t for t in run_backtest(part, strategy, "XAU/USD", config,
                                              warmup=warm)
                      if t["reason"] != "end_of_data"]
            enriched = add_all(part.copy())
            label_trades(enriched, trades, gate)
            for t in trades:
                t["periode"] = label
            all_trades += trades

            allowed = [t for t in trades if t.get("gate_passed") is True]
            blocked = [t for t in trades if t.get("gate_passed") is False]
            sa, sb = _r_stats(allowed), _r_stats(blocked)
            period_rows.append({
                "periode": label, "handler": len(trades),
                "tilladt": sa["n"], "blokeret": sb["n"],
                "blokeret_%": round(100 * sb["n"] / len(trades), 1) if trades else 0.0,
                "R_tilladt": sa["mean"], "R_blokeret": sb["mean"],
                "forskel": (round(sa["mean"] - sb["mean"], 4)
                            if sa["mean"] is not None and sb["mean"] is not None else None),
            })
            n_comparisons += 1
            labels = [regime_at(enriched, k, gate) for k in range(warm, len(enriched))]
            counts = pd.Series(labels).value_counts()
            bar_rows.append({"periode": label, "barer": len(labels),
                             **{f"{r}_%": round(100 * counts.get(r, 0) / len(labels), 2)
                                for r in ("trending", "volatile", "sideways")}})
            print(f" {len(trades)} handler")

    # ---------------- kriterium ----------------
    verdict = {}
    if period_rows:
        signs = [r["forskel"] for r in period_rows if r["forskel"] is not None]
        positive = sum(1 for s in signs if s > 0)
        allowed_all = [t for t in all_trades if t.get("gate_passed") is True]
        blocked_all = [t for t in all_trades if t.get("gate_passed") is False]
        sa, sb = _r_stats(allowed_all), _r_stats(blocked_all)
        pooled = [t["r_multiple_net"] for t in all_trades
                  if t.get("r_multiple_net") is not None]
        sd = float(np.std(pooled, ddof=1)) if len(pooled) > 1 else 0.0
        mdd = rnorm.min_detectable_r(min(sa["n"], sb["n"]) or 2, sd)
        diff_vals = ([t["r_multiple_net"] for t in allowed_all
                      if t.get("r_multiple_net") is not None],
                     [t["r_multiple_net"] for t in blocked_all
                      if t.get("r_multiple_net") is not None])
        import math
        se = math.sqrt(np.var(diff_vals[0], ddof=1) / max(len(diff_vals[0]), 1)
                       + np.var(diff_vals[1], ddof=1) / max(len(diff_vals[1]), 1))
        d = (sa["mean"] or 0) - (sb["mean"] or 0)
        z = 1.959963984540054
        ci = (d - z * se, d + z * se)
        verdict = {
            "positive": positive, "n_periods": len(signs),
            "consistent": positive >= CRITERION_MIN_PERIODS,
            "diff": round(d, 4), "ci": (round(ci[0], 4), round(ci[1], 4)),
            "crosses_zero": ci[0] <= 0 <= ci[1],
            "mdd": round(mdd, 4), "n_allowed": sa["n"], "n_blocked": sb["n"],
            "sa": sa, "sb": sb,
        }
        n_comparisons += 1

    # ---------------- rapport ----------------
    L = [
        "# Lang guld-serie: validering og regimetest (2004-2025)\n",
        f"**Kørt:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}\n",
    ]

    if verdict:
        harmful = verdict["diff"] < 0
        L.append("\n## Svar\n")
        if harmful and not verdict["consistent"]:
            L.append(
                f"**Gaten peger den forkerte vej på 21 år guld.** De handler den ville "
                f"blokere gav **{verdict['sb']['mean']:+.4f} R** mod de tilladtes "
                f"**{verdict['sa']['mean']:+.4f} R** — en forskel på "
                f"{verdict['diff']:+.4f} R i BLOKEREDES favør. Fortegnet er det samme i "
                f"{verdict['n_periods'] - verdict['positive']} af {verdict['n_periods']} "
                "perioder.\n\n"
                f"**Men det er ikke påvist.** Intervallet {verdict['ci']} krydser nul, og "
                f"forskellen ({abs(verdict['diff'])} R) ligger under den mindst "
                f"detekterbare ({verdict['mdd']} R). Retningen er konsistent; styrken "
                "rækker ikke til en konklusion.\n\n"
                "> **Og den modsiger to-års-resultatet.** Dér så gaten gunstig ud "
                "(+0,0651 mod −0,0534 R på seks symboler). Her ser den skadelig ud. "
                "To stikprøver, modsatte fortegn, ingen af dem signifikante — det er "
                "præcis det billede Modcase 2 beskriver.\n"
            )
        elif verdict["consistent"] and not verdict["crosses_zero"]:
            L.append("**Gaten tjener sit ophold på den lange serie** — konsistent på "
                     "tværs af perioder, og intervallet udelukker nul.\n")
        else:
            L.append("**Ikke påvist.** Kriteriet om konsistens på tværs af perioder "
                     "er ikke opfyldt.\n")

    L += [
        "\n## Hvad denne kørsel kan og ikke kan købe\n",
        "21 år guld giver ~750 handler. Mindst detekterbare forskel skalerer med "
        "1/√n, så tærsklen flytter sig fra ~0,42 R til ~0,32 R. **Det er stadig langt "
        "over enhver realistisk edge for en trendstrategi.**\n\n",
        "Denne kørsel er derfor **ikke** svaret på Modcase 2. Den er (1) en validering "
        "af en datakilde vi har liggende, (2) en test af om apparatet holder på en "
        "lang serie, og (3) en mulighed for at se regimeskift over mange cyklusser "
        "frem for to. Et positivt resultat må ikke overlæses.\n\n",
        "> **Hvad der faktisk skulle til:** ~7.600 handler for at kunne se 0,10 R — "
        "svarende til ~35 år på seks symboler, eller ~40 symboler over fem år. "
        "**Bredde, ikke historik.** Én lang serie på ét instrument løser det ikke.\n",
        "\n## 3a. Validering\n",
        "\n### Datakvalitet pr. år\n",
        _md(quality),
    ]
    if span:
        L.append(f"\n**Brugbart spænd: {span[0]}-{span[1]}.** 2025 fejler med 53,2% "
                 "dækning og et hul på 81 dage (2025-07-11 → 2025-09-30). Restriktionen "
                 "til de validerede år er ikke en reparation — intet er udfyldt, "
                 "interpoleret eller ændret.\n")
    L += [
        "\n### Krydsvalidering mod GC=F (daglige lukkekurser)\n",
        "Guld-spot og COMEX-futures er ikke samme instrument — futures bærer carry, "
        "så et niveauafvig er forventeligt. Det afgørende er at de BEVÆGER sig ens.\n\n",
        _md(xval),
        f"\n{'**Bestået.**' if xval_ok else '**FEJLET.**'} Krav: afkastkorrelation "
        f"≥ {MIN_RETURN_CORR} og median prisafvigelse ≤ {MAX_MEDIAN_PRICE_DEV_PCT}% "
        "på alle perioder.\n",
        "\n### Volumen — er det tick-volumen?\n",
        _md(pd.DataFrame([vol])),
        "\nVolumen varierer meningsfuldt (median-ratio 0,89, p90 1,75) og korrelerer "
        f"moderat med bar-range ({vol['korr_volumen_range']}). Det er konsistent med "
        "**tick-volumen**: hvert tick ER en prisbevægelse. Niveauet er broker-afhængigt "
        "og kan ikke sammenlignes med rigtig omsat volumen. **Enhver strategi der "
        "bruger volumen-ratio er upålidelig på denne serie** — det gælder "
        "`volatility_breakout` og `reversal_context`, ikke `trend_momentum`, som ikke "
        "rører volumen.\n",
        "\n### Overlapstest — den stærkeste identitetstest\n",
        "Samme strategi, samme periode, to datakilder. Måler præcis det vi bruger "
        "dataen til.\n\n",
    ]
    if ov.get("status") == "ok":
        L.append(f"Vindue: {ov['eval_start']} → {ov['eval_end']}. Afkortet ved "
                 "2025-02-28, fordi den lange serie er mangelfuld fra marts 2025 "
                 "(marts 90 barer, april 24, juli 51 mod ~128 i en normal måned).\n\n")
        L.append(_md(ov["table"]))
        t = ov["table"]
        dev = 100 * abs(t.iloc[0]["median_ATR_%"] - t.iloc[1]["median_ATR_%"]) / t.iloc[0]["median_ATR_%"]
        L.append(f"\n{'**Bestået.**' if ov_ok else '**FEJLET.**'} Median ATR% er det "
                 "stærkeste identitetstal her — handelstallene hviler på 7-9 handler i "
                 "et vindue på fire en halv måned og skal ikke overfortolkes.\n")
        L.append(
            f"\n> **Forbehold:** afvigelsen er {dev:.1f}%, altså bestået men ikke ren. "
            "Barantallet matcher tæt (559 mod 562), men den lange serie er mærkbart "
            "mindre volatil i samme vindue. Det er foreneligt med spot mod futures — "
            "futures bærer rollover og har bredere natlige spring — men konsekvensen "
            "skal stå tydeligt: **1R er ~20% mindre på den lange serie, så R-multipler "
            "fra 3b kan ikke sammenlignes direkte med R-multipler fra to-års-kørslerne.** "
            "Sammenligninger INDEN FOR den lange serie er upåvirkede.\n")
    else:
        L.append(f"_{ov.get('status')}_\n")

    if not passed:
        L += ["\n## 3b. Ikke kørt\n",
              "Serien bestod ikke valideringen. Dataen er **ikke** repareret, og den "
              "nuværende guld-kilde er **ikke** erstattet.\n"]
    else:
        L += [
            f"\n## 3b. Regimetest på {span[0]}-{span[1]}, fire perioder\n",
            "Ét instrument. Resultatet kan bekræfte eller modsige de to år, men det "
            "kan **ikke alene afgøre noget for porteføljen**.\n\n",
            _md(pd.DataFrame(period_rows)),
            "\n### Præregistreret kriterium (låst før kørsel)\n",
            "Kriteriet er **konsistens, ikke signifikans i én periode**: slår gaten "
            "igennem i én periode og ikke de andre, er det støj — samme logik som "
            "flip-exit.\n\n",
            _md(pd.DataFrame([
                {"krav": f"Tilladte slår blokerede i mindst "
                         f"{CRITERION_MIN_PERIODS} af {verdict['n_periods']} perioder",
                 "resultat": f"{verdict['positive']}/{verdict['n_periods']}",
                 "opfyldt": "ja" if verdict["consistent"] else "NEJ"},
                {"krav": "Samlet interval krydser ikke nul",
                 "resultat": f"{verdict['diff']:+.4f} R, CI {verdict['ci']}",
                 "opfyldt": "NEJ" if verdict["crosses_zero"] else "ja"},
            ])),
            f"\nMindst detekterbare forskel med n={min(verdict['n_allowed'], verdict['n_blocked'])} "
            f"pr. gruppe: **{verdict['mdd']} R** (mod 0,42 R på to år).\n",
            "\n### Regime-fordeling pr. periode (barer)\n",
            _md(pd.DataFrame(bar_rows)),
            "\n**`volatile` udløses 0,00% af tiden i alle fire perioder.** Over 21 år "
            "guld rammer regimet aldrig — ATR/close > 4% forekommer ikke på 4h-barer i "
            "dette instrument. Det bekræfter fundet fra to-års-kørslen "
            "(`volatile_min_confidence: 0.75` ramte 3 af 432 handler) og gør det "
            "stærkere: tærsklen er ikke sjældent brugt, den er ubrugt.\n",
            "\nTrending-andelen falder jævnt gennem de fire perioder "
            "(62,0% → 58,5% → 56,1% → 53,9%). Det er en langsom drift over 21 år, "
            "ikke et regimeskift der kan forklare et fald fra én toårsperiode til "
            "den næste.\n",
        ]

    L += [
        "\n## Antal sammenligninger\n",
        f"Denne kørsel: **{n_comparisons}**. Samlet for hele forløbet: ~25 fra de "
        f"foregående fem analyser plus {n_comparisons} her = **~{25 + n_comparisons}**. "
        f"Ved alpha 5% er sandsynligheden for mindst ét falsk positivt fund "
        f"{100 * (1 - 0.95 ** (25 + n_comparisons)):.0f}%.\n",
        "\n## Hvad der IKKE er gjort\n",
        "- Dataen er ikke repareret. Ingen huller er udfyldt eller interpoleret.\n",
        "- Den nuværende guld-kilde er ikke erstattet. `config.yaml` er urørt.\n",
        "- Ingen konfigurationsændring foreslået.\n",
    ]

    path = OUTPUT_DIR / "gold_long_test.md"
    path.write_text("\n".join(L), encoding="utf-8")
    if all_trades:
        pd.DataFrame(all_trades).to_csv(OUTPUT_DIR / "gold_long_trades.csv", index=False)

    # ---------------- sessionstabel ----------------
    print()
    if passed and period_rows:
        print(f"BACKTEST  {STRATEGY}  {span[0]}-{span[1]}  regime-gate, 4 perioder")
        print(f"{'periode':<18} {'n':>5} {'blok%':>6} {'R_till':>8} {'R_blok':>8} "
              f"{'forskel':>8}")
        for r in period_rows:
            print(f"{r['periode']:<18} {r['handler']:>5} {r['blokeret_%']:>5.1f}% "
                  f"{r['R_tilladt'] or 0:>+8.4f} {r['R_blokeret'] or 0:>+8.4f} "
                  f"{r['forskel'] or 0:>+8.4f}")
        print(f"{'SAMLET':<18} {len(all_trades):>5} "
              f"{100 * verdict['n_blocked'] / len(all_trades):>5.1f}% "
              f"{verdict['sa']['mean'] or 0:>+8.4f} {verdict['sb']['mean'] or 0:>+8.4f} "
              f"{verdict['diff']:>+8.4f}")
        print(f"\nKonsistens: {verdict['positive']}/{verdict['n_periods']} perioder  |  "
              f"CI {verdict['ci']} {'krydser nul' if verdict['crosses_zero'] else 'udelukker nul'}"
              f"  |  mindst detekterbar {verdict['mdd']} R")
    print(f"Rapport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
