"""Parret evaluering af en exit-regel — samme entries, kun exit varierer.

## Problemet dette løser

``run_backtest`` springer frem med ``i += max(trade["bars_held"], 1)`` for at undgå
overlappende positioner. En exit-regel der forkorter handler flytter derfor markøren
anderledes, og efter det FØRSTE forkortede exit ligger alle efterfølgende entries på
andre barer. A1 og A2 er to forskellige vandringer gennem data — ikke de samme handler
med forskellig exit.

Det er ikke en fejl i koden; det er porteføljekontrakten der virker efter hensigten. Men
det betyder at vi ikke har haft et apparat der kan isolere en exit-regels virkning.

## Hvad der gøres her

Markøren følger **baseline**. For hver baseline-handel simuleres den samme entry én gang
til med exit-reglen slået til. De to lister har derfor samme længde, samme entries og
samme rækkefølge — forskellen er udelukkende exit.

De to opgørelser svarer på hvert sit spørgsmål, og begge skal kunne køres fremover:

- **parret** (her): gør reglen den enkelte handel bedre?
- **portefølje** (``runner.run_backtest`` med ``flip_exit``): gør reglen den samlede
  kørsel bedre, inklusive at frigjorte pladser giver flere handler?

## Hvad et positivt parret resultat IKKE betyder

Det genåbner ikke flip-exit som live-ændring. Falder den parrede test positivt ud, er
konklusionen **ikke** "flip-exit virker alligevel" — den er "reglen forbedrer
enkelthandler, men porteføljeeffekten er upåvist". Det er en svagere påstand end den
der blev afvist i out-of-sample-testen.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from backtest import costs as costs_mod
from backtest import rnorm
from data.indicators import add_all


def paired_backtest(df: pd.DataFrame, strategy, symbol: str, config: dict,
                    warmup: int = 200, exit_kwargs: dict | None = None
                    ) -> tuple[list[dict], list[dict]]:
    """(baseline, variant) — to lister med IDENTISKE entries.

    Markøren følger baseline, så variantens kortere handler ikke kan forskyde
    efterfølgende entries. Det er hele pointen: uden det måler man to forskellige
    vandringer gennem data og kalder forskellen for exit-reglens virkning.

    exit_kwargs videresendes til ``simulate_trade`` for varianten (i dag
    ``{"flip_exit": True}``), så apparatet virker for enhver fremtidig exit-regel.
    """
    from backtest.runner import simulate_trade

    kwargs = exit_kwargs or {"flip_exit": True}
    df = add_all(df)
    baseline: list[dict] = []
    variant: list[dict] = []
    i = warmup
    while i < len(df):
        window = df.iloc[:i].copy()
        signal = strategy.generate_signal(window, symbol, {"min_confidence": 0.0})
        if signal is not None:
            future = df.iloc[i:].reset_index(drop=True)
            if len(future) < 2:
                break
            base = simulate_trade(signal, future, config)
            var = simulate_trade(signal, future, config, **kwargs)
            baseline.append(base)
            variant.append(var)
            # Markøren følger BASELINE — ikke varianten.
            i += max(base["bars_held"], 1)
        else:
            i += 1

    # Samme seed til begge lister: parret sammenligning med fælles tilfældige tal.
    # Entry-slippage bliver dermed identisk for de to udgaver af samme handel, så
    # forskellen kommer fra exit-reglen og ikke fra to uafhængige støjtræk.
    for trades in (baseline, variant):
        costs_mod.apply_costs_to_trades(trades, config, strategy.name, symbol)
        rnorm.add_r_multiples(trades)
    return baseline, variant


def paired_differences(baseline: list[dict], variant: list[dict]) -> list[dict]:
    """Én række pr. handelspar med forskellen i R.

    ``changed`` skiller de handler reglen faktisk rørte fra dem hvor den aldrig
    udløste. Uden det split fortyndes gennemsnittet af nuller, og en regel der
    rammer sjældent men hårdt ser svagere ud end den er.
    """
    if len(baseline) != len(variant):
        raise ValueError(
            f"parringen er brudt: {len(baseline)} baseline mod {len(variant)} variant"
        )
    rows = []
    for b, v in zip(baseline, variant):
        if b.get("r_multiple_net") is None or v.get("r_multiple_net") is None:
            continue
        rows.append({
            "symbol": b["symbol"],
            "side": b["side"],
            "entry_time": b.get("entry_time"),
            "baseline_reason": b["reason"],
            "variant_reason": v["reason"],
            "baseline_r": b["r_multiple_net"],
            "variant_r": v["r_multiple_net"],
            "delta_r": round(v["r_multiple_net"] - b["r_multiple_net"], 4),
            "baseline_bars": b["bars_held"],
            "variant_bars": v["bars_held"],
            "changed": v["reason"] != b["reason"] or v["bars_held"] != b["bars_held"],
        })
    return rows


def paired_summary(diffs: list[dict], z: float = 1.959963984540054) -> dict:
    """Gennemsnitlig forskel i R med PARRET konfidensinterval.

    Parret interval frem for to uafhængige: variansen på forskellen er langt mindre
    end variansen på hver serie, fordi handlernes fælles udsving går ud. Det er
    netop derfor apparatet er mere følsomt end A1/A2-sammenligningen.
    """
    if not diffs:
        return {"n": 0, "n_changed": 0}
    deltas = np.array([d["delta_r"] for d in diffs], dtype=float)
    changed = [d for d in diffs if d["changed"]]
    changed_deltas = np.array([d["delta_r"] for d in changed], dtype=float)

    def _ci(arr):
        if len(arr) < 2:
            return (float("nan"), float("nan"))
        se = arr.std(ddof=1) / math.sqrt(len(arr))
        return (float(arr.mean()) - z * se, float(arr.mean()) + z * se)

    lo, hi = _ci(deltas)
    clo, chi = _ci(changed_deltas)
    return {
        "n": len(diffs),
        "n_changed": len(changed),
        "changed_pct": round(100 * len(changed) / len(diffs), 2),
        "mean_delta_r": round(float(deltas.mean()), 4),
        "median_delta_r": round(float(np.median(deltas)), 4),
        "ci_low": round(lo, 4) if lo == lo else None,
        "ci_high": round(hi, 4) if hi == hi else None,
        "crosses_zero": bool(lo <= 0 <= hi) if lo == lo else None,
        "mean_delta_r_changed": round(float(changed_deltas.mean()), 4) if len(changed) else None,
        "ci_low_changed": round(clo, 4) if clo == clo else None,
        "ci_high_changed": round(chi, 4) if chi == chi else None,
        "n_better": int((deltas > 0).sum()),
        "n_worse": int((deltas < 0).sum()),
        "n_same": int((deltas == 0).sum()),
    }
