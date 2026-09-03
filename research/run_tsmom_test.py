"""FASE 1: kan vores apparat genfinde en effekt der beviseligt findes?

Vi har brugt uger på at måle to strategier vi selv fandt på. Begge viste sig tomme.
Men vi ved stadig ikke om apparatet KAN finde en effekt der beviseligt findes — og
indtil det er afklaret, ved vi ikke om "ikke påvist" betød tomme strategier eller
en måling der ikke duer.

Time-series momentum er dokumenteret over mere end et århundrede og på snesevis af
markeder. Kan apparatet ikke genfinde den, er det apparatet der er i stykker.

```bash
.venv/bin/python research/run_tsmom_test.py
```

**Ingen ændring af live handelsadfærd.** Modulet registreres ikke som strategi, og
``config.yaml`` er urørt.
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

from backtest.metrics import curve_metrics  # noqa: E402
from research import tsmom  # noqa: E402
from research.daily_series import (  # noqa: E402
    INSTRUMENTS, load, quality_summary, research_cost_config, usable_span,
    yearly_quality,
)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# --- LÅST FØR KØRSEL ------------------------------------------------------
# Kriteriet bedømmes på REGLEN: 12 måneders lookback, rebalancering den 1.
# Lookback 3/6/9 og rebalancering den 15. er robusthedstjek — der vælges ingen
# vinder, og de indgår ikke i bedømmelsen.
RULE_LOOKBACK = 12
RULE_REBALANCE_DAY = 1

MIN_INSTRUMENTS = 4          # af 8, for krav 1 og 2
N_SUBPERIODS = 4
MIN_SUBPERIODS = 3           # af 4, for krav 3

# "Materielt lavere drawdown" skal have et tal, ellers kan kriteriet bøjes bagefter.
# Låst: strategiens maxDD skal være mindst 20% RELATIVT lavere end buy-and-holds.
# -33,7% mod -55,2% er 39% relativt lavere og tæller; -50% mod -55% gør ikke.
MATERIAL_DD_REDUCTION = 0.20

# Krav 3 læses som "mindst 3 af 4 delperioder med POSITIVT afkast". Den rene
# ordlyd ("samme fortegn") ville også være opfyldt af fire negative delperioder,
# hvilket ikke kan være meningen med et succeskriterium. Begge tællinger
# rapporteres; bedømmelsen bruger den strenge.


def subperiod_returns(equity: pd.Series, n: int = N_SUBPERIODS) -> list[float]:
    """Afkast i n lige lange KALENDER-delperioder. Lige lang tid, ikke lige mange barer."""
    if len(equity) < n * 2:
        return []
    edges = pd.date_range(equity.index[0], equity.index[-1], periods=n + 1)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        seg = equity[(equity.index >= a) & (equity.index <= b)]
        out.append(float(seg.iloc[-1] / seg.iloc[0] - 1) * 100 if len(seg) >= 2 else 0.0)
    return out


def run_one(key: str, config: dict, lookback: int, rebalance_day: int) -> dict:
    inst = INSTRUMENTS[key]
    df = load(inst)
    res = tsmom.run_tsmom(df, inst, config, lookback, rebalance_day)
    m = curve_metrics(res.equity, res.exposure, res.positions)
    b = curve_metrics(res.benchmark)
    subs = subperiod_returns(res.equity)
    return {
        "instrument": key, "lookback": lookback, "rebalance_day": rebalance_day,
        "fra": str(res.equity.index[0].date()), "til": str(res.equity.index[-1].date()),
        "år": m["years"],
        # De to "n" — antal handler og andel af tiden. De besvarer hvert sit
        # spørgsmål og forveksles hvis kun det ene står der.
        "positioner": res.positions,
        "tid_i_marked_%": m["time_in_market_pct"],
        "hold_mdr": res.hold_months,
        "skift_pr_år": res.switches_per_year,
        "omk_%_af_brutto": res.cost_share_of_gross,
        "cagr": m["cagr"], "maxdd": m["max_drawdown_pct"],
        "sharpe": m["sharpe"], "flat_dage": m["longest_flat_days"],
        "total_afkast_%": m["total_return_pct"],
        "bh_cagr": b["cagr"], "bh_maxdd": b["max_drawdown_pct"],
        "bh_sharpe": b["sharpe"], "bh_flat_dage": b["longest_flat_days"],
        "bh_total_%": b["total_return_pct"],
        "dd_reduktion": round(1 - (m["max_drawdown_pct"] / b["max_drawdown_pct"]), 3)
                        if b["max_drawdown_pct"] < 0 else 0.0,
        "delperioder": [round(s, 2) for s in subs],
        "delperioder_positive": sum(1 for s in subs if s > 0),
        "delperioder_samme_fortegn": max(sum(1 for s in subs if s > 0),
                                         sum(1 for s in subs if s < 0)) if subs else 0,
        "slip_median": float(res.slip_days.median()) if len(res.slip_days) else 0.0,
        "slip_maks": int(res.slip_days.max()) if len(res.slip_days) else 0,
        "slip_efter_1": int((res.slip_days > 0).sum()) if len(res.slip_days) else 0,
        "slip_n": int(len(res.slip_days)),
    }


def session_table(rows: list[dict], period: str) -> str:
    """DEL 5 — maks ~15 linjer. Buy-and-hold på SAMME linje, ikke i et separat afsnit."""
    lines = [
        f"FASE 1  time-series momentum ({RULE_LOOKBACK}m, reb. d. {RULE_REBALANCE_DAY})  {period}",
        f"{'instrument':<11}{'n':>4}{'CAGR':>8}{'maxDD':>8}{'Sharpe':>8}{'flat_dg':>9}"
        f" | {'B&H CAGR':>9}{'B&H maxDD':>11}",
    ]
    for r in rows:
        lines.append(
            f"{r['instrument']:<11}{r['positioner']:>4}{r['cagr']:>7.2f}%{r['maxdd']:>7.1f}%"
            f"{r['sharpe']:>8.2f}{r['flat_dage']:>9}"
            f" | {r['bh_cagr']:>8.2f}%{r['bh_maxdd']:>10.1f}%"
        )
    return "\n".join(lines)


def main() -> int:
    config = research_cost_config(yaml.safe_load(open("config.yaml")))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- DEL 1: datakvalitet ------------------------------------------------
    print("DEL 1 — daglige serier, kvalitet (reparerer ingenting)\n")
    quality_rows, yearly = [], {}
    for key, inst in INSTRUMENTS.items():
        df = load(inst)
        q = yearly_quality(df, inst)
        yearly[key] = q
        quality_rows.append(quality_summary(inst, df, q))
    qdf = pd.DataFrame(quality_rows)
    print(qdf[["instrument", "barer", "fra", "til", "år", "flade_barer",
               "nul_volumen", "brugbart_span", "kasserede_år"]].to_string(index=False))

    # --- DEL 3+4: reglen, plus robusthed ------------------------------------
    print("\n\nDEL 3 — kører reglen og robusthedstjekkene ...")
    all_rows = []
    for day in tsmom.REBALANCE_DAYS:
        for lb in tsmom.LOOKBACKS:
            for key in INSTRUMENTS:
                all_rows.append(run_one(key, config, lb, day))
            print(f"  lookback {lb}m, rebalancering d. {day}: færdig")
    rdf = pd.DataFrame(all_rows)
    rdf.to_csv(OUTPUT_DIR / "apparatus_validation.csv", index=False)

    rule = [r for r in all_rows
            if r["lookback"] == RULE_LOOKBACK and r["rebalance_day"] == RULE_REBALANCE_DAY]

    # --- Kriteriet ----------------------------------------------------------
    c1 = [r for r in rule if r["total_afkast_%"] > 0]
    c2 = [r for r in rule if r["dd_reduktion"] >= MATERIAL_DD_REDUCTION]
    c3 = [r for r in rule if r["delperioder_positive"] >= MIN_SUBPERIODS]
    verdict = {
        "krav1_positivt_afkast": (len(c1), [r["instrument"] for r in c1]),
        "krav2_lavere_drawdown": (len(c2), [r["instrument"] for r in c2]),
        "krav3_stabil_fortegn": (len(c3), [r["instrument"] for r in c3]),
    }
    passed = (len(c1) >= MIN_INSTRUMENTS and len(c2) >= MIN_INSTRUMENTS
              and len(c3) >= MIN_INSTRUMENTS)

    span = f"{min(r['fra'] for r in rule)} → {max(r['til'] for r in rule)}"
    print("\n" + session_table(rule, span))
    print()
    for name, (n, who) in verdict.items():
        mark = "OK " if n >= MIN_INSTRUMENTS else "NEJ"
        print(f"  [{mark}] {name}: {n}/8 — {', '.join(who) or 'ingen'}")
    print(f"\n  APPARATET {'VIRKER' if passed else 'BESTOD IKKE'} "
          f"(kriteriet krævede {MIN_INSTRUMENTS}/8 på alle tre)")

    write_report(qdf, yearly, rdf, rule, verdict, passed, span)
    print(f"\nRapport -> {OUTPUT_DIR / 'apparatus_validation.md'}")
    return 0


def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    rows = ["| " + " | ".join(str(v) for v in row) + " |"
            for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


def write_report(qdf, yearly, rdf, rule, verdict, passed, span) -> None:
    from research.report_tsmom import build

    (OUTPUT_DIR / "apparatus_validation.md").write_text(
        build(qdf, yearly, rdf, rule, verdict, passed, span, _md_table,
              session_table(rule, span)),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
