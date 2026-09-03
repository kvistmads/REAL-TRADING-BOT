"""Parret test af flip-exit: gør reglen den ENKELTE handel bedre?

Out-of-sample-testen sammenlignede A1 og A2 som to hele kørsler — men fordi markøren
springer frem med handlens længde, flytter en kortere exit alle efterfølgende entries.
A1 og A2 var derfor to forskellige vandringer gennem data, ikke samme handler med
forskellig exit. Denne test isolerer exit-reglens virkning ved at holde entries faste.

**Et positivt resultat genåbner ikke flip-exit som live-ændring.** Konklusionen ville
være "reglen forbedrer enkelthandler, men porteføljeeffekten er upåvist" — svagere end
den påstand out-of-sample-testen afviste. Flip level forbliver observe-only.

```bash
.venv/bin/python research/run_paired_exit_test.py
```
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import paired  # noqa: E402
from backtest.runner import fetch_data  # noqa: E402
from strategies.registry import load_strategies  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
STRATEGY = "trend_momentum"
WARMUP = 200


def _md(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_(ingen data)_\n"
    head = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    lines = [head, sep]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join("—" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = yaml.safe_load(open(args.config))
    strategy = load_strategies().get(STRATEGY)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_diffs: list[dict] = []
    per_symbol_rows: list[dict] = []
    period = "—"

    print(f"Parret exit-test ({STRATEGY}, {args.timeframe})...")
    for symbol in config["symbols"]:
        print(f"  {symbol:10s} ...", end="", flush=True)
        try:
            df = fetch_data(symbol, args.timeframe)
        except Exception as e:
            print(f" FEJL: {type(e).__name__}: {str(e)[:60]}")
            continue
        if df is None or df.empty or len(df) < WARMUP + 10:
            print(" for lidt data")
            continue
        period = f"{df['time'].iloc[0]:%Y-%m}→{df['time'].iloc[-1]:%Y-%m}"

        base, var = paired.paired_backtest(df, strategy, symbol, config, warmup=WARMUP)
        # Kun handler med et rigtigt udfald i BEGGE udgaver — en handel der løb tør
        # for data i den ene og ikke i den anden er ikke et gyldigt par.
        pairs = [(b, v) for b, v in zip(base, var)
                 if b["reason"] != "end_of_data" and v["reason"] != "end_of_data"]
        if not pairs:
            print(" ingen par")
            continue
        b_list, v_list = [p[0] for p in pairs], [p[1] for p in pairs]
        diffs = paired.paired_differences(b_list, v_list)
        all_diffs += diffs

        s = paired.paired_summary(diffs)
        per_symbol_rows.append({
            "symbol": symbol, "n_par": s["n"], "n_ændret": s["n_changed"],
            "ændret_%": s["changed_pct"],
            "delta_R_gns": s["mean_delta_r"], "delta_R_median": s["median_delta_r"],
            "95%-CI": f"[{s['ci_low']}, {s['ci_high']}]",
            "krydser_nul": "ja" if s["crosses_zero"] else "nej",
            "bedre": s["n_better"], "værre": s["n_worse"], "uændret": s["n_same"],
        })
        print(f" {s['n']} par, {s['n_changed']} ændret, delta {s['mean_delta_r']:+.4f} R")

    total = paired.paired_summary(all_diffs)
    if not total.get("n"):
        print("Ingen par at rapportere.")
        return 1

    L = [
        "# Parret test af flip-exit — samme entries, kun exit varierer\n",
        f"**Kørt:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}  ",
        f"**Strategi:** {STRATEGY} · **Periode:** {period}\n",
        "\n> **Et positivt resultat genåbner ikke flip-exit som live-ændring.** "
        "Konklusionen ville være \"reglen forbedrer enkelthandler, men "
        "porteføljeeffekten er upåvist\" — svagere end den påstand out-of-sample-"
        "testen afviste. Flip level forbliver observe-only.\n",
        "\n## Hvad denne test måler, som A1/A2 ikke kunne\n",
        "`run_backtest` springer markøren frem med handlens længde for at undgå "
        "overlappende positioner. En kortere exit flytter derfor alle efterfølgende "
        "entries, og A1/A2 var to forskellige vandringer gennem data. Her følger "
        "markøren **baseline**, så de to lister har identiske entries og forskellen "
        "udelukkende kommer fra exit-reglen.\n",
        "\n## Samlet\n",
        _md(pd.DataFrame([{
            "n_par": total["n"], "n_ændret": total["n_changed"],
            "ændret_%": total["changed_pct"],
            "delta_R_gns": total["mean_delta_r"],
            "delta_R_median": total["median_delta_r"],
            "95%-CI (parret)": f"[{total['ci_low']}, {total['ci_high']}]",
            "krydser_nul": "ja" if total["crosses_zero"] else "nej",
            "bedre/værre/uændret":
                f"{total['n_better']}/{total['n_worse']}/{total['n_same']}",
        }])),
        "\n### Kun de handler reglen faktisk rørte\n",
        "Handler hvor flip level aldrig udløste har delta præcis 0 og fortynder "
        "gennemsnittet. En regel der rammer sjældent men hårdt ser svagere ud end "
        "den er, hvis man kun ser totalen.\n\n",
        _md(pd.DataFrame([{
            "n_ændret": total["n_changed"],
            "delta_R_gns": total["mean_delta_r_changed"],
            "95%-CI (parret)": f"[{total['ci_low_changed']}, {total['ci_high_changed']}]",
        }])),
        "\n## Pr. symbol\n",
        _md(pd.DataFrame(per_symbol_rows)),
        "\n## Fortolkning\n",
    ]

    if total["crosses_zero"]:
        L.append("Det parrede interval **krydser nul**. Selv med entries holdt faste — "
                 "den mest følsomme sammenligning vi kan lave — kan flip-exits virkning "
                 "på den enkelte handel ikke skelnes fra nul. Det er en stærkere "
                 "afvisning end out-of-sample-testens, fordi den parrede variant har "
                 "lavere varians: handlernes fælles udsving går ud.\n")
    elif total["mean_delta_r"] > 0:
        L.append("Det parrede interval ligger **over nul**: reglen forbedrer den enkelte "
                 "handel. Bemærk at dette IKKE er det samme som at den forbedrer "
                 "porteføljen — out-of-sample-testen afviste netop porteføljeeffekten, "
                 "og de to spørgsmål har hvert sit svar.\n")
    else:
        L.append("Det parrede interval ligger **under nul**: reglen forringer den "
                 "enkelte handel.\n")

    L += [
        "\n## Hvad der IKKE er gjort\n",
        "- Live-adfærd er uændret. Flip level lukker ingen handel.\n",
        "- Ingen exit-regel, tærskel eller konfiguration er ændret.\n",
        "- Apparatet er bygget generelt (`exit_kwargs`), så det virker for enhver "
        "fremtidig exit-regel — ikke kun flip level.\n",
    ]

    path = OUTPUT_DIR / "paired_exit_test.md"
    path.write_text("\n".join(L), encoding="utf-8")
    pd.DataFrame(all_diffs).to_csv(OUTPUT_DIR / "paired_exit_diffs.csv", index=False)

    print()
    print(f"BACKTEST  {STRATEGY}  {period}  parret flip-exit")
    print(f"{'symbol':<12} {'par':>5} {'ændret':>7} {'delta_R':>9} {'95%-CI':>22} "
          f"{'nul?':>5}")
    for r in per_symbol_rows:
        print(f"{r['symbol']:<12} {r['n_par']:>5} {r['n_ændret']:>7} "
              f"{r['delta_R_gns']:>+9.4f} {r['95%-CI']:>22} {r['krydser_nul']:>5}")
    total_ci = f"[{total['ci_low']}, {total['ci_high']}]"
    nul = "ja" if total["crosses_zero"] else "nej"
    print(f"{'TOTAL':<12} {total['n']:>5} {total['n_changed']:>7} "
          f"{total['mean_delta_r']:>+9.4f} {total_ci:>22} {nul:>5}")
    print(f"\nRapport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
