"""Optælling før beslutning: hvor mange handler hviler på et ikke-ATR-stop, og hvorfor?

Svaret afgør om R-tabellerne kan medregne dem. Fallback-stoppet er config'ens faste
``sl_pct`` — krypto 10%, forex 1,5%, guld 3%, altså et forhold på 6,7× sat af en
konfigurationsfil frem for af markedet. R-normaliseringen findes netop for at fjerne
indbygget skalering fra sammenligningen mellem instrumentklasser, så et 1R der stammer
fra ``sl_pct`` betyder noget kategorisk andet end et der stammer fra ATR.

Producerer også DEL 1's hovedtabel — ``ATR%_median`` og ``1R_i_%`` pr. symbol — som er
det der afgør om procent-sammenligninger overhovedet er meningsfulde på tværs af
instrumenter.

```bash
.venv/bin/python research/run_r_census.py
```

**Ændrer intet.** Skriver til ``research/output/``.
"""

from __future__ import annotations

import argparse
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
from strategies.base import BaseStrategy  # noqa: E402
from strategies.registry import load_strategies  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
WARMUP = 200


def split_halves(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Samme split som out-of-sample-testen: anden halvdel får warmup med bagud."""
    mid = len(df) // 2
    return df.iloc[:mid].copy(), df.iloc[max(0, mid - WARMUP):].copy()


def bar_quality(df: pd.DataFrame, symbol: str) -> dict:
    """Datakvalitet pr. symbol — særligt FLADE barer (High == Low).

    Flade barer kontaminerede ``GC=F`` i daily bias-testen: de opdigter en
    volatilitet på nul, hvilket giver ATR(14) == 0 og dermed et ugyldigt R.
    Er de årsagen til nul-ATR, er det et datakvalitetsproblem, ikke et
    R-regnskabsspørgsmål.
    """
    n = len(df)
    flat = int((df["high"] == df["low"]).sum())
    zero_vol = int((df["volume"] == 0).sum())
    return {
        "symbol": symbol,
        "barer": n,
        "fra": f"{df['time'].iloc[0]:%Y-%m-%d}" if n else "—",
        "til": f"{df['time'].iloc[-1]:%Y-%m-%d}" if n else "—",
        "flade_barer": flat,
        "flade_pct": round(100 * flat / n, 3) if n else 0.0,
        "nul_volumen": zero_vol,
        "nul_volumen_pct": round(100 * zero_vol / n, 2) if n else 0.0,
    }


def atr_profile(df: pd.DataFrame, symbol: str) -> dict:
    """ATR(14) som procent af prisen — medianen der afgør om procent er sammenligneligt."""
    enriched = add_all(df.copy())
    atr = enriched["atr_14"].dropna()
    close = enriched.loc[atr.index, "close"]
    atr_pct = (atr / close * 100).replace([np.inf, -np.inf], np.nan).dropna()
    if atr_pct.empty:
        return {"symbol": symbol, "ATR_pct_median": None, "ATR_pct_q1": None,
                "ATR_pct_q3": None, "atr_nul_barer": 0}
    return {
        "symbol": symbol,
        "asset_class": BaseStrategy.get_asset_class(symbol),
        "ATR_pct_median": round(float(atr_pct.median()), 4),
        "ATR_pct_q1": round(float(atr_pct.quantile(0.25)), 4),
        "ATR_pct_q3": round(float(atr_pct.quantile(0.75)), 4),
        "atr_nul_barer": int((atr <= 0).sum()),
    }


def _closed(trades: list[dict]) -> list[dict]:
    return [t for t in trades if t.get("reason") != "end_of_data"]


def census_rows(trades: list[dict], half: str) -> list[dict]:
    """Fallback-optælling pr. symbol for én halvdel."""
    out = []
    for _, row in rnorm.fallback_census(trades).iterrows():
        r = row.to_dict()
        r["halvdel"] = half
        out.append(r)
    return out


def per_symbol_table(trades: list[dict], config: dict) -> pd.DataFrame:
    """DEL 1's hovedtabel: kan procent-tal overhovedet sammenlignes på tværs?"""
    from backtest import costs as costs_mod

    rows = []
    df = pd.DataFrame(_closed(trades))
    if df.empty:
        return pd.DataFrame()
    for symbol, g in df.groupby("symbol"):
        with_r = g[g["r_multiple_net"].notna()]
        price = float(g["entry_price"].median())
        summary = costs_mod.cost_summary(config, symbol, price)
        rows.append({
            "symbol": symbol,
            "gruppe": "krypto" if BaseStrategy.get_asset_class(symbol) == "crypto"
                      else "ikke-krypto",
            "n": len(g),
            "1R_i_%_median": round(float(with_r["risk_pct"].median()), 3)
                             if not with_r.empty else None,
            "1R_i_%_iqr": round(float(with_r["risk_pct"].quantile(0.75)
                                      - with_r["risk_pct"].quantile(0.25)), 3)
                          if not with_r.empty else None,
            "PnL/handel_%": round(float(g["pnl_pct_net"].mean()), 4),
            "PnL/handel_R": round(float(with_r["r_multiple_net"].mean()), 4)
                            if not with_r.empty else None,
            "omkost_bp": summary.get("total_bp"),
            "omkost_R": round(float(with_r["cost_in_r"].mean()), 4)
                        if not with_r.empty else None,
        })
    return pd.DataFrame(rows)


def _md(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_(ingen data)_\n"
    head = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    lines = [head, sep]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(
            "—" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--strategy", default="trend_momentum")
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = yaml.safe_load(open(args.config))
    strategy = load_strategies().get(args.strategy)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Henter data ({args.timeframe})...")
    data: dict[str, pd.DataFrame] = {}
    quality, atr_rows = [], []
    for symbol in config["symbols"]:
        print(f"  {symbol:10s} ...", end="", flush=True)
        try:
            df = fetch_data(symbol, args.timeframe)
            data[symbol] = df
            quality.append(bar_quality(df, symbol))
            atr_rows.append(atr_profile(df, symbol))
            print(f" {len(df)} barer")
        except Exception as e:
            data[symbol] = None
            print(f" FEJL: {type(e).__name__}: {str(e)[:70]}")

    all_trades: list[dict] = []
    census: list[dict] = []
    for symbol, df in data.items():
        if df is None or df.empty or len(df) < WARMUP + 10:
            continue
        first, second = split_halves(df)
        for half, part in (("1. halvdel", first), ("2. halvdel", second)):
            print(f"  [{half}] {symbol:10s} ...", end="", flush=True)
            trades = _closed(run_backtest(part, strategy, symbol, config, warmup=WARMUP))
            for t in trades:
                t["halvdel"] = half
            all_trades += trades
            census += census_rows(trades, half)
            print(f" {len(trades)} handler")

    census_df = pd.DataFrame(census)
    quality_df = pd.DataFrame(quality)
    atr_df = pd.DataFrame(atr_rows)
    symbol_df = per_symbol_table(all_trades, config)
    dist_df = rnorm.r_distribution(all_trades)
    top_df = rnorm.largest_r_multiples(all_trades, n=5)

    n_total = len(all_trades)
    n_fallback = sum(1 for t in all_trades if t.get("stop_source") == "fallback_pct")
    n_no_r = sum(1 for t in all_trades if not t.get("r_valid"))
    share = n_fallback / n_total if n_total else 0.0

    L = [
        "# R-census: fallback-stops, datakvalitet og R-skala\n",
        f"**Kørt:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}  ",
        f"**Strategi:** {args.strategy}  ",
        f"**Handler i alt (lukkede):** {n_total}\n",
        "\n## 1. Hvor mange handler hviler på et ikke-ATR-stop?\n",
        f"**{n_fallback} af {n_total} ({100 * share:.2f}%)** brugte config'ens faste "
        f"`sl_pct` i stedet for ATR. **{n_no_r}** handler har intet gyldigt R "
        "(stop lig entry, eller ikke-endelig risiko).\n\n",
        f"Grænsen for at blande dem ind i R-tabellerne er "
        f"{100 * rnorm.FALLBACK_TOLERANCE:.0f}%: "
        + ("**under grænsen** — de medregnes, og antallet står her.\n"
           if share <= rnorm.FALLBACK_TOLERANCE else
           "**over grænsen** — R-tabellerne bygger kun på ATR-baserede stops, og "
           "fallback-handlerne får deres egen række.\n"),
        "\n### Pr. symbol og halvdel\n",
        _md(census_df),
        "\n## 2. Datakvalitet — flade barer\n",
        "Flade barer (`High == Low`) opdigter en volatilitet på nul og giver "
        "ATR(14) == 0. De kontaminerede `GC=F` i daily bias-testen.\n\n",
        _md(quality_df),
        "\n## 3. ATR i procent — kan procent-tal sammenlignes på tværs?\n",
        _md(atr_df),
        "\n## 4. R-skala pr. symbol\n",
        _md(symbol_df),
        "\n### Fordelingen af 1R (median + interkvartilafstand)\n",
        _md(dist_df),
        "\n### De fem største r_multiples i absolut værdi\n",
        "Et meget stramt stop giver et lille R, og så bliver et normalt kursudsving "
        "til et enormt R-multiple. Sådanne outliers kan trække et gennemsnit alene.\n\n",
        _md(top_df),
    ]
    path = OUTPUT_DIR / "r_census.md"
    path.write_text("\n".join(L), encoding="utf-8")

    pd.DataFrame(all_trades).to_csv(OUTPUT_DIR / "r_census_trades.csv", index=False)

    print("\n" + "=" * 78)
    print(f"FALLBACK: {n_fallback}/{n_total} ({100 * share:.2f}%)  |  UDEN R: {n_no_r}")
    print("=" * 78)
    print(census_df.to_string(index=False) if not census_df.empty else "(ingen)")
    print("\nDATAKVALITET")
    print(quality_df.to_string(index=False))
    print("\nATR I PROCENT")
    print(atr_df.to_string(index=False))
    print("\nR-SKALA PR. SYMBOL")
    print(symbol_df.to_string(index=False))
    print(f"\nRapport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
