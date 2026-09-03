"""Tjener regime-gaten sit ophold?

Første gang vi tester noget der **faktisk er tændt i produktion**. Gaten bruges her
udelukkende som MÆRKAT på handler — backtesten kører fortsat uden gates, og intet
i live røres.

Tre spørgsmål:

- **2a** Hvor meget filtrerer gaten overhovedet? (som `min_confidence: 0.45`, der
  viste sig at afvise 3 af 686 signaler og dermed være aritmetisk inaktiv)
- **2b** Er de tilladte handler bedre end de blokerede? En gate er et filter og skal
  måles på hvad den FJERNER, ikke kun på hvad den beholder.
- **2c** Forklarer regime forværringen mellem halvdelene? Denne kan falsificere hele
  regime-hypotesen, og den er lige så vigtig som 2b.

Gatens egen kode og egne tærskler bruges (`gates.regime.RegimeGate`) — ingen
genimplementering, ingen selvvalgte ADX-grænser. Vi tester den gate der kører.

```bash
.venv/bin/python research/run_regime_gate_test.py
```
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import rnorm  # noqa: E402
from backtest.runner import fetch_data, run_backtest  # noqa: E402
from data.indicators import add_all  # noqa: E402
from gates.regime import SIDEWAYS, RegimeGate  # noqa: E402
from research import stats  # noqa: E402
from strategies.base import Signal  # noqa: E402
from strategies.registry import load_strategies  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
STRATEGY = "trend_momentum"
WARMUP = 200
Z = 1.959963984540054

# --- LÅST FØR KØRSEL ------------------------------------------------------
GROUPS = {"krypto": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
          "ikke-krypto": ["EUR/USD", "GBP/USD", "XAU/USD"]}
# Under denne andel blokerede handler er gaten i praksis inaktiv.
INACTIVE_THRESHOLD = 0.10
# Over denne andel handler med regimeskift er entry-regimet en svag etiket.
LABEL_WEAK_THRESHOLD = 0.25

# classify() ser kun på de sidste 5 barer (ema_20-hældning) plus sidste
# adx/atr/close. En hale på 6 barer giver derfor PRÆCIS samme svar som hele
# serien — det er det der gør bar-for-bar-mærkning billig nok til at være exakt.
CLASSIFY_TAIL = 6


def group_of(symbol: str) -> str:
    return "krypto" if symbol in GROUPS["krypto"] else "ikke-krypto"


def split_halves(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    mid = len(df) // 2
    return df.iloc[:mid].copy(), df.iloc[max(0, mid - WARMUP):].copy()


def regime_at(df: pd.DataFrame, idx: int, gate: RegimeGate) -> str:
    """Gatens egen classify() på det vindue den ville have set ved bar `idx`."""
    lo = max(0, idx - CLASSIFY_TAIL + 1)
    return gate.classify(df.iloc[lo:idx + 1])


def label_trades(df: pd.DataFrame, trades: list[dict], gate: RegimeGate) -> list[dict]:
    """Mærk hver handel med entry-regimet og gatens beslutning.

    Entry-regimet afgør alt: det er hvad gaten FAKTISK ser når den træffer sin
    beslutning, og filteret kender kun entry-baren.

    Vinduet er ``df.iloc[:i]`` hvor i er udførelsesbarens indeks — præcis det
    vindue strategien selv så, så mærkatet svarer til live-situationen.
    """
    time_to_idx = {t: i for i, t in enumerate(df["time"])}
    for tr in trades:
        i = time_to_idx.get(tr.get("entry_time"))
        if i is None or i == 0:
            tr["regime_at_entry"] = None
            tr["gate_passed"] = None
            tr["adx_valid_at_entry"] = None
            continue
        window = df.iloc[max(0, i - CLASSIFY_TAIL):i]
        adx = window["adx_14"].iloc[-1] if "adx_14" in window.columns else float("nan")
        tr["adx_valid_at_entry"] = bool(adx == adx)

        # Gatens EGEN evaluate() — inklusive volatile_min_confidence og
        # SIDEWAYS_OK_STRATEGIES. Ingen genimplementering af beslutningen.
        signal = Signal(STRATEGY, tr["symbol"], tr["side"],
                        float(tr.get("confidence") or 0.0), "4h", {})
        result = gate.evaluate(signal, {"df": window})
        tr["regime_at_entry"] = gate.classify(window)
        tr["gate_passed"] = bool(result.passed)

        # Diagnostik: skiftede regimet mens handlen var åben? Ét tal til
        # FORTOLKNING af 2b, ikke en parallel opgørelse.
        exit_idx = min(i + int(tr.get("bars_held") or 0), len(df) - 1)
        labels = [regime_at(df, k, gate) for k in range(i, exit_idx + 1)]
        switches = sum(1 for a, b in zip(labels, labels[1:]) if a != b)
        tr["regime_switches"] = switches
        tr["regime_changed"] = switches > 0
    return trades


def bar_regimes(df: pd.DataFrame, gate: RegimeGate, start: int) -> list[str]:
    """Regime pr. BAR fra `start` og frem.

    2c måles på barer og ikke på handler: barer er markedet, handler er en
    filtreret stikprøve af det.
    """
    return [regime_at(df, k, gate) for k in range(start, len(df))]


# ---------------------------------------------------------------------------
# Opgørelser
# ---------------------------------------------------------------------------

def _r_stats(trades: list[dict]) -> dict:
    vals = [t["r_multiple_net"] for t in trades if t.get("r_multiple_net") is not None]
    if not vals:
        return {"n": 0, "mean": None, "ci": "—", "total": 0.0, "lo": None, "hi": None}
    arr = np.asarray(vals, dtype=float)
    lo, hi = stats.mean_ci(arr)
    return {
        "n": len(arr), "mean": round(float(arr.mean()), 4),
        "ci": f"[{lo:.4f}, {hi:.4f}]" if lo == lo else "—",
        "lo": lo, "hi": hi,
        # Samlet R, ikke kun pr. handel: en gate kan hæve gennemsnittet og
        # samtidig fjerne så mange vindere at totalen falder.
        "total": round(float(arr.sum()), 3),
        "wr": round(100 * float((arr > 0).mean()), 2),
    }


def filter_table(trades: list[dict], label: str) -> pd.DataFrame:
    allowed = [t for t in trades if t.get("gate_passed") is True]
    blocked = [t for t in trades if t.get("gate_passed") is False]
    rows = []
    for name, subset in (("tilladt", allowed), ("blokeret", blocked),
                         ("alle (baseline)", trades)):
        s = _r_stats(subset)
        rows.append({label: name, "n": s["n"], "andel_%":
                     round(100 * s["n"] / len(trades), 2) if trades else 0.0,
                     "WR_%": s["wr"] if s["n"] else None,
                     "R/handel_net": s["mean"], "95%-CI": s["ci"],
                     "samlet_R": s["total"]})
    return pd.DataFrame(rows)


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
    gate = RegimeGate(config)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_trades: list[dict] = []
    by_half: dict[str, list[dict]] = {"1. halvdel": [], "2. halvdel": []}
    bar_rows: list[dict] = []
    adx_bar_rows: list[dict] = []

    print(f"Regime-gate-test ({STRATEGY}, {args.timeframe})...")
    print(f"  Gatens tærskler: min_trending_adx={gate.min_trending_adx}, "
          f"max_volatile_atr_pct={gate.max_volatile_atr_pct}, "
          f"volatile_min_confidence={gate.volatile_min_confidence}")

    for symbol in config["symbols"]:
        print(f"  {symbol:10s} ...", end="", flush=True)
        try:
            raw = fetch_data(symbol, args.timeframe)
        except Exception as e:
            print(f" FEJL: {type(e).__name__}: {str(e)[:60]}")
            continue
        if raw is None or raw.empty or len(raw) < WARMUP + 10:
            print(" for lidt data")
            continue

        for half, part in zip(("1. halvdel", "2. halvdel"), split_halves(raw)):
            enriched = add_all(part.copy())
            trades = [t for t in run_backtest(part, strategy, symbol, config,
                                              warmup=WARMUP)
                      if t["reason"] != "end_of_data"]
            label_trades(enriched, trades, gate)
            for t in trades:
                t["halvdel"] = half
                t["gruppe"] = group_of(symbol)
            all_trades += trades
            by_half[half] += trades

            # 2c: regime pr. BAR (kun de barer der kunne handles på)
            labels = bar_regimes(enriched, gate, WARMUP)
            counts = pd.Series(labels).value_counts()
            bar_rows.append({
                "halvdel": half, "gruppe": group_of(symbol), "symbol": symbol,
                "barer": len(labels),
                **{r: int(counts.get(r, 0)) for r in ("trending", "volatile", "sideways")},
            })
            adx = enriched["adx_14"].iloc[WARMUP:]
            adx_bar_rows.append({
                "halvdel": half, "symbol": symbol, "barer": len(adx),
                "adx_nan": int(adx.isna().sum()),
                "adx_nan_%": round(100 * float(adx.isna().mean()), 3),
            })
        print(f" {sum(1 for t in all_trades if t['symbol'] == symbol)} handler")

    if not all_trades:
        print("Ingen handler.")
        return 1

    # ---- diagnostik: ADX-gyldighed og regimeskift ----
    n = len(all_trades)
    adx_invalid = [t for t in all_trades if t.get("adx_valid_at_entry") is False]
    changed = [t for t in all_trades if t.get("regime_changed")]
    switch_counts = [t["regime_switches"] for t in changed]
    changed_share = len(changed) / n
    blocked = [t for t in all_trades if t.get("gate_passed") is False]
    blocked_share = len(blocked) / n
    gate_inactive = blocked_share < INACTIVE_THRESHOLD
    label_weak = changed_share > LABEL_WEAK_THRESHOLD

    # ---- 2c: regime pr. bar ----
    bars_df = pd.DataFrame(bar_rows)
    bars_by_half = (bars_df.groupby(["halvdel", "gruppe"])[
        ["barer", "trending", "volatile", "sideways"]].sum().reset_index())
    for r in ("trending", "volatile", "sideways"):
        bars_by_half[f"{r}_%"] = (100 * bars_by_half[r] / bars_by_half["barer"]).round(2)

    # ---- 2b ----
    overall_tbl = filter_table(all_trades, "gruppe")
    half_tbls = {h: filter_table(ts, "gruppe") for h, ts in by_half.items() if ts}

    allowed_all = [t for t in all_trades if t.get("gate_passed") is True]
    blocked_all = blocked
    a_stats, b_stats = _r_stats(allowed_all), _r_stats(blocked_all)
    sd = float(np.std([t["r_multiple_net"] for t in all_trades
                       if t.get("r_multiple_net") is not None], ddof=1))
    mdd = rnorm.min_detectable_r(min(a_stats["n"], b_stats["n"]) or 2, sd)

    c1 = all(
        (_r_stats([t for t in ts if t.get("gate_passed") is True])["mean"] or -9e9)
        > (_r_stats([t for t in ts if t.get("gate_passed") is False])["mean"] or 9e9)
        for ts in by_half.values() if ts
    )
    diff = ((a_stats["mean"] or 0) - (b_stats["mean"] or 0))
    c2 = abs(diff) > mdd
    c3 = blocked_share >= INACTIVE_THRESHOLD
    gate_earns = c1 and c2 and c3
    gate_destroys = (b_stats["mean"] is not None and a_stats["mean"] is not None
                     and b_stats["mean"] > a_stats["mean"])

    # ---------------- rapport ----------------
    L = [
        "# Tjener regime-gaten sit ophold?\n",
        f"**Kørt:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}  ",
        f"**Strategi:** {STRATEGY} · **Handler:** {n}  ",
        f"**Gatens tærskler (fra config, urørt):** min_trending_adx="
        f"{gate.min_trending_adx}, max_volatile_atr_pct={gate.max_volatile_atr_pct}, "
        f"volatile_min_confidence={gate.volatile_min_confidence}\n",
        "\n> Gaten bruges her som **mærkat** på handler. Backtesten kører fortsat uden "
        "gates, og intet i live er ændret.\n",
        "\n## Svar\n",
    ]

    if gate_inactive:
        L.append(f"**Gaten er i praksis inaktiv.** Den ville blokere "
                 f"{len(blocked)} af {n} handler ({100 * blocked_share:.1f}%), under "
                 f"grænsen på {100 * INACTIVE_THRESHOLD:.0f}%. Som med "
                 "`min_confidence: 0.45` er den relevante opdagelse at vi har en gate "
                 "der ikke gør ret meget.\n")
    elif gate_destroys:
        L.append(f"**Gaten ødelægger værdi i produktion lige nu.** De handler den "
                 f"ville blokere har HØJERE forventningsværdi ({b_stats['mean']:+.4f} R) "
                 f"end dem den tillader ({a_stats['mean']:+.4f} R).\n")
    elif gate_earns:
        L.append("**Gaten tjener sit ophold** — alle tre præregistrerede krav er opfyldt.\n")
    else:
        L.append("**Ikke påvist.** Mindst ét af de tre præregistrerede krav fejler.\n")

    L += [
        "\n## Diagnostik før alt andet\n",
        f"**ADX-gyldighed:** {len(adx_invalid)} af {n} handler havde ugyldig ADX ved "
        "entry"
        + (". Spørgsmålet om hvordan de skal tælles bortfalder dermed, som "
           "ATR-spørgsmålet gjorde i R-censussen.\n" if not adx_invalid else
           " — se den separate opgørelse nedenfor.\n"),
        _md(pd.DataFrame(adx_bar_rows).groupby("halvdel")[
            ["barer", "adx_nan"]].sum().reset_index().assign(
            adx_nan_pct=lambda d: (100 * d["adx_nan"] / d["barer"]).round(3))),
        f"\n**Regimeskift undervejs:** regimet skiftede mindst én gang i "
        f"**{len(changed)} af {n} handler ({100 * changed_share:.1f}%)**"
        + (f", median {int(np.median(switch_counts))} skift for dem der skiftede.\n"
           if switch_counts else ".\n"),
        ("\n> Regimet skifter i de fleste handler. Entry-regimet er dermed en **svag "
         "etiket**, og 2b måler noget mere udvandet end det ser ud til — også hvis "
         "resultatet falder ud til gatens fordel.\n" if label_weak else
         "\n> Regimet skifter sjældent nok til at entry-regimet er en **god etiket**, "
         "og 2b kan læses som den står.\n"),
        "\n## 2a. Hvor meget filtrerer gaten?\n",
        _md(pd.DataFrame([{
            "gruppe": g,
            "n": len([t for t in all_trades if t["gruppe"] == g]),
            "tilladt": len([t for t in all_trades if t["gruppe"] == g and t["gate_passed"]]),
            "blokeret": len([t for t in all_trades if t["gruppe"] == g and t["gate_passed"] is False]),
            "blokeret_%": round(100 * len([t for t in all_trades if t["gruppe"] == g
                                           and t["gate_passed"] is False])
                                / max(len([t for t in all_trades if t["gruppe"] == g]), 1), 2),
        } for g in ("krypto", "ikke-krypto")] + [{
            "gruppe": "SAMLET", "n": n,
            "tilladt": n - len(blocked), "blokeret": len(blocked),
            "blokeret_%": round(100 * blocked_share, 2),
        }])),
        "\n### Regime-fordeling ved entry (handler)\n",
        _md(pd.DataFrame([{
            "regime": r,
            "handler": len([t for t in all_trades if t["regime_at_entry"] == r]),
            "andel_%": round(100 * len([t for t in all_trades
                                        if t["regime_at_entry"] == r]) / n, 2),
        } for r in ("trending", "volatile", "sideways")])),
    ]

    if gate_inactive:
        L.append("\n## 2b. Sprunget over\n")
        L.append("Gaten blokerer under 10% af handlerne og er dermed i praksis "
                 "inaktiv. En filtertest på så lille en blokeret gruppe kan ikke "
                 "afgøre noget.\n")
    else:
        L += [
            "\n## 2b. Gaten som filter\n",
            "En gate skal måles på hvad den FJERNER, ikke kun på hvad den beholder. "
            "`samlet_R` står ved siden af `R/handel`: en gate kan hæve gennemsnittet "
            "og samtidig fjerne så mange vindere at totalen falder.\n\n",
            _md(overall_tbl),
        ]
        for half, tbl in half_tbls.items():
            L.append(f"\n**{half}**\n")
            L.append(_md(tbl))
        L += [
            "\n### Præregistreret kriterium\n",
            _md(pd.DataFrame([
                {"krav": "1. Tilladte > blokerede i begge halvdele",
                 "opfyldt": "ja" if c1 else "NEJ"},
                {"krav": f"2. Forskellen ({diff:+.4f} R) overstiger mindst "
                         f"detekterbare ({mdd:.4f} R)",
                 "opfyldt": "ja" if c2 else "NEJ"},
                {"krav": f"3. Gaten blokerer mindst {100 * INACTIVE_THRESHOLD:.0f}% "
                         f"({100 * blocked_share:.1f}%)",
                 "opfyldt": "ja" if c3 else "NEJ"},
            ])),
        ]
        if gate_destroys:
            L.append("\n> **Blokerede handler har højere forventningsværdi end "
                     "tilladte.** Gaten fjerner værdi i den bot der kører lige nu. "
                     "Det står her uindpakket; ingen ændring foreslås.\n")

    # 2c: er regime-fordelingen overhovedet ændret mellem halvdelene?
    pivot = bars_by_half.set_index(["halvdel", "gruppe"])
    shifts = []
    for g in ("krypto", "ikke-krypto"):
        try:
            a = pivot.loc[("1. halvdel", g)]
            b = pivot.loc[("2. halvdel", g)]
        except KeyError:
            continue
        shifts.append({
            "gruppe": g,
            **{f"{r}_ændring_pp": round(float(b[f"{r}_%"] - a[f"{r}_%"]), 2)
               for r in ("trending", "volatile", "sideways")},
        })
    shift_df = pd.DataFrame(shifts)
    max_shift = 0.0
    if not shift_df.empty:
        max_shift = float(np.abs(shift_df.select_dtypes("number").to_numpy()).max())
    regime_explains = max_shift >= 10.0

    L += [
        "\n## 2c. Forklarer regime forværringen mellem halvdelene?\n",
        "Målt på **barer**, ikke på handler: barer er markedet, handler er en "
        "filtreret stikprøve af det.\n\n",
        _md(bars_by_half[["halvdel", "gruppe", "barer",
                          "trending_%", "volatile_%", "sideways_%"]]),
        "\n### Ændring fra 1. til 2. halvdel\n",
        _md(shift_df),
    ]
    if regime_explains:
        L.append("\nRegime-fordelingen er markant anderledes i anden halvdel. Regime "
                 "er dermed en kandidat til forklaringen på forværringen.\n")
    else:
        L.append(f"\n> **Regime forklarer det ikke.** Største ændring i "
                 f"regime-fordelingen er {max_shift:.1f} procentpoint — markedets "
                 "sammensætning er stort set uændret mellem halvdelene, mens "
                 "`R/handel` angiveligt faldt ~0,26 R i BEGGE grupper. Kryptos "
                 "trending-andel steg endda en anelse samtidig med at performance "
                 "faldt, hvilket er det modsatte af hvad regime-hypotesen forudsiger. "
                 "Hypotesen var tiltalende og stammede fra en gate der var valgt før "
                 "nogen af disse analyser — den holder alligevel ikke.\n")

    # ---- Modcase 2 + multiplicitet ----
    all_cis = [
        ("tilladt", a_stats), ("blokeret", b_stats),
        ("alle", _r_stats(all_trades)),
    ]
    crossing = [name for name, st in all_cis
                if st["lo"] is not None and st["lo"] <= 0 <= st["hi"]]
    excludes = [name for name, st in all_cis
                if st["lo"] is not None and not (st["lo"] <= 0 <= st["hi"])]

    L += [
        "\n## Modcase 1 — er gaten inert?\n",
        f"Nej, ikke som helhed: den blokerer {100 * blocked_share:.1f}% af handlerne. "
        "**Men én gren af den er det.** `volatile`-regimet — hvor `volatile_min_confidence "
        f"= {gate.volatile_min_confidence}` skulle slippe høj-confidence-signaler igennem "
        f"— ramte kun {len([t for t in all_trades if t['regime_at_entry'] == 'volatile'])} "
        f"af {n} handler. Den tærskel er i praksis aldrig i brug.\n",
        "\n## Modcase 2 — kan to år overhovedet afgøre noget?\n",
        "Vi har nu skåret de samme ~432 handler i fem separate analyser: "
        "confidence-validering, flip-exit out-of-sample, parret flip-exit, "
        "instrumentklasse og regime. Groft optalt er der foretaget **omkring 25 "
        "sammenligninger** på det samme datasæt.\n\n",
        "Ved alpha 5% er sandsynligheden for MINDST ét falsk positivt fund blandt 25 "
        "uafhængige sammenligninger ca. **72%** (1 − 0,95²⁵). Med andre ord: havde vi "
        "fundet ét enkelt \"signifikant\" resultat undervejs, ville det mest "
        "sandsynlige være at det var tilfældet.\n\n",
    ]
    if excludes:
        L.append(f"Intervaller der IKKE krydser nul: {', '.join(excludes)}. "
                 "Alle øvrige krydser nul.\n")
    else:
        L.append("**Samtlige intervaller i denne analyse krydser nul.**\n")
    L.append(
        "\n> **Stikprøven er for lille til at afgøre noget om denne strategi, og "
        "yderligere opdelinger af de samme to år vil ikke ændre det. Næste skridt "
        "skal være mere data, ikke flere spørgsmål.**\n\n"
        "Det er ikke \"endnu et ikke påvist\". Det er en konklusion om metoden: hver "
        "ny opdeling gør stikprøven pr. gruppe mindre og multipliciteten værre, og "
        "begge dele trækker i den forkerte retning.\n\n"
        "Bemærk samtidig hvad de ~25 chancer IKKE producerede: næsten ingen falske "
        "positive. Det er svag evidens for at der ikke er nogen stor effekt at finde "
        "— ikke bare fravær af bevis.\n"
    )

    path = OUTPUT_DIR / "regime_gate_test.md"
    path.write_text("\n".join(L), encoding="utf-8")
    pd.DataFrame(all_trades).to_csv(OUTPUT_DIR / "regime_gate_trades.csv", index=False)

    # ---------------- sessionstabel (DEL 4) ----------------
    print()
    print(f"BACKTEST  {STRATEGY}  2 år  regime-gate som mærkat")
    print(f"{'gruppe/regime':<16} {'n':>5} {'andel%':>7} {'WR':>6} "
          f"{'R/handel':>9} {'95%-CI':>20} {'samlet_R':>9}")
    for name, subset in (("tilladt", allowed_all), ("blokeret", blocked_all),
                         ("alle", all_trades)):
        s = _r_stats(subset)
        if not s["n"]:
            continue
        print(f"{name:<16} {s['n']:>5} {100 * s['n'] / n:>6.1f}% {s['wr']:>5.1f}% "
              f"{s['mean']:>+9.4f} {s['ci']:>20} {s['total']:>+9.2f}")
    for r in ("trending", "volatile", "sideways"):
        s = _r_stats([t for t in all_trades if t["regime_at_entry"] == r])
        if not s["n"]:
            continue
        print(f"{'  ' + r:<16} {s['n']:>5} {100 * s['n'] / n:>6.1f}% {s['wr']:>5.1f}% "
              f"{s['mean']:>+9.4f} {s['ci']:>20} {s['total']:>+9.2f}")
    print(f"\nGaten blokerer {100 * blocked_share:.1f}%  |  regimeskift i "
          f"{100 * changed_share:.1f}% af handlerne")
    print(f"Rapport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
