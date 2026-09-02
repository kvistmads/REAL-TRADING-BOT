"""Out-of-sample-test: er flip-exit på trend_momentum reelt, eller passede det til støjen?

`trend_momentum` gik fra −1,48% (A1) til +10,26% (A2) med EMA50-flip-exit. Det er det
mest interessante resultat projektet har — og det er **én in-sample kørsel på en strategi
med brutto-PF 0,98**, altså dokumenteret nul-edge. En exit-regel der tilføjes bagefter og
måles på de samme data, har haft rig lejlighed til at finde støj der ligner en effekt.

Testen deler de 2 år i to lige halvdele og kører A1 og A2 på hver for sig. Halvdelene
deler ingen evaluerede barer: anden halvdel får de 200 foregående barer som warmup, så
indikatorerne er varme præcis ved skillelinjen, og første evaluerede bar dér er den første
bar efter midten.

```bash
.venv/bin/python research/run_flip_oos_test.py
```

**Ændrer intet.** Flip level forbliver observe-only i live uanset udfald.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import metrics as metrics_mod  # noqa: E402
from backtest import report  # noqa: E402
from backtest.runner import fetch_data, run_backtest  # noqa: E402
from strategies.registry import load_strategies  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
STRATEGY = "trend_momentum"
WARMUP = 200

# Præregistreret kriterium — LÅST FØR KØRSEL (PRD del 2). Ændres ikke bagefter.
CRITERION_MIN_SYMBOLS_AGREE = 4   # af 6
CRITERION_HALVES = 2              # A2 skal slå A1 i BEGGE halvdele


def split_halves(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Del df i to halvdele der evaluerer hver sin disjunkte periode.

    Anden halvdel får WARMUP barer med bagud, så dens indikatorer er varme ved
    skillelinjen — ellers ville de første 200 barer efter midten gå tabt, og
    anden halvdel ville reelt teste en kortere og senere periode end første.
    """
    mid = len(df) // 2
    return df.iloc[:mid].copy(), df.iloc[max(0, mid - WARMUP):].copy()


def _period(df: pd.DataFrame, skip_warmup: bool = False) -> str:
    if df.empty:
        return "—"
    start = df["time"].iloc[WARMUP] if skip_warmup and len(df) > WARMUP else df["time"].iloc[0]
    return f"{start:%Y-%m}→{df['time'].iloc[-1]:%Y-%m}"


def run_half(strategy, symbol: str, df: pd.DataFrame, config: dict,
             flip_exit: bool) -> tuple[dict, list[dict]]:
    """Kør én halvdel for ét symbol; returnér (begge opgørelser, handler)."""
    if df is None or df.empty or len(df) <= WARMUP + 2:
        return metrics_mod.compute_both([]), []
    trades = run_backtest(df, strategy, symbol, config, warmup=WARMUP, flip_exit=flip_exit)
    return metrics_mod.compute_both(trades), trades


def _agg_pf(per_symbol: dict[str, dict], key: str) -> float:
    """Profit factor på tværs af symboler — genberegnet fra summerne.

    PF kan IKKE aggregeres ved at midle symbolernes PF'er: et symbol med PF 10 på
    en lille gevinst og ét med PF 0,1 på et stort tab giver naivt 5,05, mens den
    rigtige samlede PF er 1,0. Summerne skal lægges sammen først.
    """
    profit = sum(m[key].get("gross_profit_pct", 0.0) for m in per_symbol.values())
    loss = sum(m[key].get("gross_loss_pct", 0.0) for m in per_symbol.values())
    if loss > 0:
        return round(profit / loss, 2)
    return float("inf") if profit > 0 else 0.0


def _totals(per_symbol: dict[str, dict]) -> dict:
    """Aggreger på tværs af symboler for én (halvdel × konfiguration)."""
    n = sum(m["gross"]["closed_trades"] for m in per_symbol.values())
    wins_g = sum(m["gross"]["wins"] for m in per_symbol.values())
    wins_n = sum(m["net"]["wins"] for m in per_symbol.values())
    return {
        "n": n,
        "pnl_gross": round(sum(m["gross"]["total_pnl_pct"] for m in per_symbol.values()), 2),
        "pnl_net": round(sum(m["net"]["total_pnl_pct"] for m in per_symbol.values()), 2),
        "wr_gross": round(100 * wins_g / n, 2) if n else 0.0,
        "wr_net": round(100 * wins_n / n, 2) if n else 0.0,
        "pf_gross": _agg_pf(per_symbol, "gross"),
        "pf_net": _agg_pf(per_symbol, "net"),
        "cost": round(sum(m["net"]["total_cost_pct"] for m in per_symbol.values()), 2),
    }


def evaluate(halves: dict) -> dict:
    """Bedøm det præregistrerede kriterium mod resultaterne."""
    beats_gross, beats_net, symbol_agreement = {}, {}, {}
    for half, data in halves.items():
        a1, a2 = _totals(data["A1"]), _totals(data["A2"])
        beats_gross[half] = a2["pnl_gross"] > a1["pnl_gross"]
        beats_net[half] = a2["pnl_net"] > a1["pnl_net"]
        positive = 0
        for symbol in data["A1"]:
            d = (data["A2"][symbol]["net"]["total_pnl_pct"]
                 - data["A1"][symbol]["net"]["total_pnl_pct"])
            if d > 0:
                positive += 1
        symbol_agreement[half] = positive

    n_symbols = len(next(iter(halves.values()))["A1"]) if halves else 0
    return {
        "beats_gross": beats_gross,
        "beats_net": beats_net,
        "symbol_agreement": symbol_agreement,
        "n_symbols": n_symbols,
        "all_halves_gross": all(beats_gross.values()) and len(beats_gross) == CRITERION_HALVES,
        "all_halves_net": all(beats_net.values()) and len(beats_net) == CRITERION_HALVES,
        "symbols_ok": all(v >= CRITERION_MIN_SYMBOLS_AGREE for v in symbol_agreement.values()),
    }


def _delta_table(halves: dict) -> pd.DataFrame:
    """A2 minus A1 pr. symbol pr. halvdel — brutto og netto."""
    rows = []
    for half, data in halves.items():
        for symbol in data["A1"]:
            g1, g2 = data["A1"][symbol]["gross"], data["A2"][symbol]["gross"]
            n1, n2 = data["A1"][symbol]["net"], data["A2"][symbol]["net"]
            rows.append({
                "halvdel": half,
                "symbol": symbol,
                "n_A1": g1["closed_trades"], "n_A2": g2["closed_trades"],
                "PnL_A1_brut": g1["total_pnl_pct"], "PnL_A2_brut": g2["total_pnl_pct"],
                "delta_brut": round(g2["total_pnl_pct"] - g1["total_pnl_pct"], 2),
                "PnL_A1_net": n1["total_pnl_pct"], "PnL_A2_net": n2["total_pnl_pct"],
                "delta_net": round(n2["total_pnl_pct"] - n1["total_pnl_pct"], 2),
                "fortegn_net": "+" if n2["total_pnl_pct"] > n1["total_pnl_pct"] else "−",
            })
    return pd.DataFrame(rows)


def _md_table(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_(ingen data)_\n"
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    lines = [header, sep]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(
            "" if pd.isna(v) else ("inf" if v == float("inf") else str(v)) for v in row
        ) + " |")
    return "\n".join(lines) + "\n"


def write_report(halves: dict, verdict: dict, periods: dict, path: Path) -> Path:
    L: list[str] = []
    L.append("# Out-of-sample-test: flip-exit på trend_momentum\n")
    L.append(f"**Kørt:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}  ")
    L.append(f"**Halvdel 1:** {periods.get('1. halvdel', '—')}  ")
    L.append(f"**Halvdel 2:** {periods.get('2. halvdel', '—')}\n")
    L.append("> Flip level forbliver observe-only i live uanset hvad der står herunder.\n")

    L.append("\n## Svar\n")
    confirmed = (verdict["all_halves_net"] and verdict["symbols_ok"]
                 and verdict["all_halves_gross"])
    if confirmed:
        L.append("**Bekræftet.** A2 slår A1 i begge halvdele, effekten overlever "
                 "omkostninger, og fortegnet holder på tværs af symboler.\n")
    elif any(verdict["beats_net"].values()):
        vundne = [h for h, v in verdict["beats_net"].items() if v]
        L.append(f"**Ikke bekræftet — effekten viser sig kun i {' og '.join(vundne)}.** "
                 "En exit-regel der kun virker i den ene halvdel af stikprøven er støj, "
                 "ikke en edge. Det oprindelige +10,26% var én in-sample kørsel på en "
                 "strategi med brutto-PF 0,98; dette er hvad der sker når den måles "
                 "ud af stikprøven.\n")
    else:
        L.append("**Ikke bekræftet.** A2 slår ikke A1 i nogen af halvdelene.\n")

    L.append("\n### Præregistreret kriterium (låst før kørsel)\n")
    crit = pd.DataFrame([
        {"krav": "A2 > A1 i begge halvdele (brutto)",
         "opfyldt": "ja" if verdict["all_halves_gross"] else "NEJ",
         "detalje": ", ".join(f"{h}: {'ja' if v else 'nej'}"
                              for h, v in verdict["beats_gross"].items())},
        {"krav": "A2 > A1 i begge halvdele (netto — overlever omkostninger)",
         "opfyldt": "ja" if verdict["all_halves_net"] else "NEJ",
         "detalje": ", ".join(f"{h}: {'ja' if v else 'nej'}"
                              for h, v in verdict["beats_net"].items())},
        {"krav": f"samme fortegn på ≥{CRITERION_MIN_SYMBOLS_AGREE} af "
                 f"{verdict['n_symbols']} symboler, begge halvdele",
         "opfyldt": "ja" if verdict["symbols_ok"] else "NEJ",
         "detalje": ", ".join(f"{h}: {v}/{verdict['n_symbols']}"
                              for h, v in verdict["symbol_agreement"].items())},
    ])
    L.append(_md_table(crit))

    L.append("\n## Totaler pr. halvdel\n")
    tot_rows = []
    for half, data in halves.items():
        for cfg in ("A1", "A2"):
            t = _totals(data[cfg])
            tot_rows.append({
                "halvdel": half, "kørsel": cfg, "n": t["n"],
                "WR_brut_%": t["wr_gross"], "WR_net_%": t["wr_net"],
                "PF_brut": t["pf_gross"], "PF_net": t["pf_net"],
                "PnL_brut_%": t["pnl_gross"], "PnL_net_%": t["pnl_net"],
                "omkostning_pp": t["cost"],
            })
    L.append(_md_table(pd.DataFrame(tot_rows)))

    # PF og PnL kan pege hver sin vej. Det er ikke en detalje: det er selve
    # signaturen på støj, og uden den note ville tabellen kunne læses som om A2
    # "vandt" anden halvdel.
    pf_note = []
    for half, data in halves.items():
        a1, a2 = _totals(data["A1"]), _totals(data["A2"])
        pnl_dir = "bedre" if a2["pnl_net"] > a1["pnl_net"] else "dårligere"
        pf_dir = "bedre" if a2["pf_net"] > a1["pf_net"] else "dårligere"
        if pnl_dir != pf_dir:
            pf_note.append(
                f"- **{half}:** A2 er {pnl_dir} på samlet PnL "
                f"({a1['pnl_net']:+.2f}% → {a2['pnl_net']:+.2f}%) men {pf_dir} på "
                f"profit factor ({a1['pf_net']:.2f} → {a2['pf_net']:.2f}), "
                f"og tager samtidig flere handler ({a1['n']} → {a2['n']})."
            )
    if pf_note:
        L.append("\n### PnL og profit factor peger hver sin vej\n")
        L.append("\n".join(pf_note) + "\n")
        L.append("\nEn exit-regel med en reel edge forbedrer begge dele. Her afhænger "
                 "svaret af hvilken metrik man vælger, og valget falder ikke ud samme "
                 "vej i de to halvdele. Flip-exit lukker handler tidligere, så summen "
                 "af tab bliver mindre — men kvaliteten pr. risikoenhed bliver ikke "
                 "bedre. Det er hvad man ser når en regel skærer i støj frem for at "
                 "fange noget reelt.\n")

    L.append("\n## A2 minus A1 pr. symbol\n")
    L.append(_md_table(_delta_table(halves)))

    L.append("\n## Hvad der IKKE er gjort\n")
    L.append("- Live-adfærd er uændret. Flip level lukker ingen handel i live.\n")
    L.append("- Ingen konfiguration, vægte eller exit-regler er ændret ud fra tallene.\n")
    L.append("- `volatility_breakout` er ikke testet: konklusionen dér "
             "(+26,45% → −2,96%) står, og VB kører uden flip-exit.\n")

    path.write_text("\n".join(L), encoding="utf-8")
    return path


def _session_tables(halves: dict, periods: dict) -> str:
    """Kompakte tabeller — én pr. (halvdel × konfiguration)."""
    out = []
    for half, data in halves.items():
        for cfg in ("A1", "A2"):
            rows = [report.session_row(sym, m) for sym, m in data[cfg].items()]
            t = _totals(data[cfg])
            rows.append({
                "symbol": "TOTAL", "n": t["n"],
                "win_rate": t["wr_gross"], "win_rate_net": t["wr_net"],
                "profit_factor": t["pf_gross"], "profit_factor_net": t["pf_net"],
                "total_pnl_pct": t["pnl_gross"], "total_pnl_pct_net": t["pnl_net"],
            })
            out.append(report.format_session_table(
                rows, STRATEGY, periods.get(half, "—"),
                f"{cfg} {'flip-exit' if cfg == 'A2' else 'baseline'} · {half}",
            ))
    return "\n\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = yaml.safe_load(open(args.config))
    strategy = load_strategies().get(STRATEGY)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Henter data for {len(config['symbols'])} symboler ({args.timeframe})...")
    data: dict[str, pd.DataFrame] = {}
    for symbol in config["symbols"]:
        print(f"  {symbol:10s} ...", end="", flush=True)
        try:
            df = fetch_data(symbol, args.timeframe)
            data[symbol] = df
            print(f" {len(df)} barer")
        except Exception as e:
            data[symbol] = None
            print(f" FEJL: {type(e).__name__}: {str(e)[:80]}")

    halves: dict[str, dict] = {"1. halvdel": {"A1": {}, "A2": {}},
                               "2. halvdel": {"A1": {}, "A2": {}}}
    periods: dict[str, str] = {}

    for symbol, df in data.items():
        if df is None or df.empty:
            continue
        first, second = split_halves(df)
        periods.setdefault("1. halvdel", _period(first))
        periods.setdefault("2. halvdel", _period(second, skip_warmup=True))
        for half, part in (("1. halvdel", first), ("2. halvdel", second)):
            for cfg, flip in (("A1", False), ("A2", True)):
                print(f"  [{half} {cfg}] {symbol:10s} ...", end="", flush=True)
                both, trades = run_half(strategy, symbol, part, config, flip)
                halves[half][cfg][symbol] = both
                print(f" {both['gross']['closed_trades']} handler")

    verdict = evaluate(halves)
    path = write_report(halves, verdict, periods, OUTPUT_DIR / "flip_oos_test.md")

    print()
    print(_session_tables(halves, periods))
    print(f"\nRapport: {path}")
    print("Live-adfærd, config og database er urørt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
