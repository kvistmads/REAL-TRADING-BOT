"""R-normalisering — udfald målt i risikoenheder frem for i procent af entrypris.

## Hvorfor

Botten sætter stop på ``atr_sl_multiplier × ATR(14)`` og TP på ``tp_rr_ratio × R``, så
hver handel har et defineret R. ATR i procent er langt større på krypto end på EUR/USD,
og målt i procent vil krypto derfor dominere både gevinster og tab — uanset om strategien
er bedre eller dårligere dér. En sammenligning på tværs af instrumentklasser i procent
måler til dels bare hvilket instrument der bevæger sig mest.

Det samme gælder omkostningerne: 25 bp på krypto mod 0,5-2 bp på CME-kontrakterne er
rigtigt i bp, men hvis 1R på krypto er mange gange større, er omkostningen **pr.
risikoenhed** langt tættere på hinanden end forholdet antyder.

## Definition

``risk_per_unit`` = |entry − INITIAL stop|, i prisenheder. Kilden er ligegyldig: ATR,
strategiens eget chart-niveau, eller ``sl_pct``-fallbacken — R er hvad handlen faktisk
risikerede ved indgang.

**R er risikoen ved INDGANG.** Flyttes stoppet (breakeven ved 50% af TP), ændrer det ikke
R — ellers ville et flyttet stop kunne få en dårlig handel til at se god ud.

``r_multiple`` = ``pnl_pct / risk_pct``. Brutto og netto deler den samme nævner, netop
fordi nævneren er låst ved entry.

## Handler uden gyldigt R

Er ``risk_per_unit`` nul, negativ eller ikke-endelig — stop lig entry, eller intet stop —
får handlen **intet** R og havner i en separat bucket. Der divideres aldrig igennem uden
at tallet er kontrolleret. ``stop_source`` skiller desuden ATR-baserede stops fra dem der
kom fra config'ens faste ``sl_pct``: de sidste er et forhold på 6,7× (krypto 10% mod forex
1,5%) sat af en konfigurationsfil, ikke af markedet, og et 1R derfra betyder noget
kategorisk andet end et ATR-afledt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Grænsen for hvornår fallback-handler må blandes ind i R-tabellerne. Under den er
# de for få til at flytte noget; over den får de deres egen række.
FALLBACK_TOLERANCE = 0.02


def atr_status(future_df: pd.DataFrame) -> tuple[float | None, str]:
    """(ATR-værdi, status) på udførelsesbaren.

    Status skelner de tre måder ATR kan svigte på, fordi de har hver sin årsag:
    ``missing`` = kolonnen findes ikke (indikatorer ikke beregnet), ``nan`` = for
    kort historik til ATR(14), ``zero`` = barerne er flade (High == Low), hvilket
    er et DATAKVALITETS-problem og ikke et R-regnskabsspørgsmål.
    """
    if "atr_14" not in future_df.columns:
        return None, "missing"
    value = float(future_df["atr_14"].iloc[0])
    if value != value:
        return None, "nan"
    if value <= 0:
        return value, "zero"
    return value, "ok"


def stop_source(signal, atr: float | None) -> str:
    """Hvor kom det initiale stop fra? Spejler ``runner._resolve_sl_tp``s forgrening."""
    if signal.sl_price is not None and signal.tp_price is not None:
        return "signal"          # strategiens eget chart-niveau (fx volatility_breakout)
    if atr is not None and atr == atr and atr > 0:
        return "atr"
    return "fallback_pct"        # config'ens faste sl_pct — ikke markedsafledt


def risk_fields(entry_price: float, initial_sl: float, signal, atr: float | None,
                atr_state: str) -> dict:
    """Risikofelterne for én handel, beregnet ved entry."""
    risk_per_unit = abs(entry_price - initial_sl)
    valid = (
        math.isfinite(risk_per_unit) and risk_per_unit > 0
        and math.isfinite(entry_price) and entry_price > 0
    )
    return {
        "risk_per_unit": round(risk_per_unit, 10) if valid else None,
        "risk_pct": round(risk_per_unit / entry_price * 100, 6) if valid else None,
        "atr_at_entry": atr,
        "atr_status": atr_state,
        "stop_source": stop_source(signal, atr),
        "r_valid": valid,
    }


def add_r_multiples(trades: list[dict]) -> list[dict]:
    """Beregn r_multiple (brutto/netto) og cost_in_r. Muterer og returnerer listen.

    Kaldes EFTER omkostningsmodellen, så netto-felterne findes. Brutto og netto deler
    nævner: R er låst ved entry, og en omkostning må ikke kunne ændre den risiko
    handlen blev taget med.
    """
    for t in trades:
        risk_pct = t.get("risk_pct")
        if not risk_pct or not t.get("r_valid"):
            t["r_multiple_gross"] = None
            t["r_multiple_net"] = None
            t["cost_in_r"] = None
            continue
        t["r_multiple_gross"] = round(t["pnl_pct"] / risk_pct, 4)
        if "pnl_pct_net" in t:
            t["r_multiple_net"] = round(t["pnl_pct_net"] / risk_pct, 4)
            t["cost_in_r"] = round(t.get("cost_pct", 0.0) / risk_pct, 4)
        else:
            t["r_multiple_net"] = t["r_multiple_gross"]
            t["cost_in_r"] = 0.0
    return trades


# ---------------------------------------------------------------------------
# Opgørelser
# ---------------------------------------------------------------------------

@dataclass
class RSummary:
    """R-statistik for et sæt handler. n_no_r tælles med — den må ikke forsvinde."""

    n: int
    n_with_r: int
    n_no_r: int
    mean_r_gross: float | None
    mean_r_net: float | None
    median_r_net: float | None
    cost_in_r: float | None
    ci_low: float | None
    ci_high: float | None


def _mean_ci(values: list[float], z: float = 1.959963984540054) -> tuple[float, float]:
    """95%-CI for gennemsnittet (normalapproksimation på standardfejlen)."""
    n = len(values)
    if n < 2:
        return (float("nan"), float("nan"))
    arr = np.asarray(values, dtype=float)
    se = arr.std(ddof=1) / math.sqrt(n)
    mean = float(arr.mean())
    return (mean - z * se, mean + z * se)


def summarise(trades: list[dict]) -> RSummary:
    """R-statistik med konfidensinterval på gennemsnittet.

    ``end_of_data``-handler er allerede filtreret fra af kalderen; her filtreres kun
    på om handlen HAR et R.
    """
    with_r = [t for t in trades if t.get("r_multiple_net") is not None]
    n_no_r = len(trades) - len(with_r)
    if not with_r:
        return RSummary(len(trades), 0, n_no_r, None, None, None, None, None, None)

    gross = [t["r_multiple_gross"] for t in with_r]
    net = [t["r_multiple_net"] for t in with_r]
    costs = [t.get("cost_in_r") or 0.0 for t in with_r]
    low, high = _mean_ci(net)
    return RSummary(
        n=len(trades),
        n_with_r=len(with_r),
        n_no_r=n_no_r,
        mean_r_gross=round(float(np.mean(gross)), 4),
        mean_r_net=round(float(np.mean(net)), 4),
        median_r_net=round(float(np.median(net)), 4),
        cost_in_r=round(float(np.mean(costs)), 4),
        ci_low=round(low, 4) if low == low else None,
        ci_high=round(high, 4) if high == high else None,
    )


def min_detectable_r(n_per_group: int, spread: float,
                     power_z: float = 0.8416212335729143,
                     alpha_z: float = 1.959963984540054) -> float:
    """Mindste forskel i gennemsnitligt R som n handler pr. gruppe kan afsløre.

    Samme logik som ``research.stats.min_detectable_diff``, men for et kontinuert mål:
    (z_alpha/2 + z_beta) · sqrt(2/n) · spredning. Bruges til at sætte et ærligt loft
    over hvad stikprøven kan sige — et resultat under grænsen er "kan ikke afgøres",
    ikke "der er ingen forskel".
    """
    if n_per_group < 2 or not math.isfinite(spread) or spread <= 0:
        return float("inf")
    return (alpha_z + power_z) * spread * math.sqrt(2.0 / n_per_group)


def fallback_census(trades: list[dict]) -> pd.DataFrame:
    """Hvor mange handler hviler på et ikke-ATR-stop, og hvorfor?

    Svaret afgør om R-tabellerne kan medregne dem: fallback-stoppet er en fast
    config-procent, så et 1R derfra er ikke sammenligneligt med et ATR-afledt.
    """
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "symbol": t.get("symbol"),
        "stop_source": t.get("stop_source"),
        "atr_status": t.get("atr_status"),
        "r_valid": t.get("r_valid"),
    } for t in trades])

    rows = []
    for symbol, g in df.groupby("symbol"):
        n = len(g)
        fallback = int((g["stop_source"] == "fallback_pct").sum())
        rows.append({
            "symbol": symbol,
            "n": n,
            "atr_stop": int((g["stop_source"] == "atr").sum()),
            "signal_stop": int((g["stop_source"] == "signal").sum()),
            "fallback_stop": fallback,
            "fallback_pct": round(100 * fallback / n, 2) if n else 0.0,
            "atr_nan": int((g["atr_status"] == "nan").sum()),
            "atr_zero": int((g["atr_status"] == "zero").sum()),
            "atr_missing": int((g["atr_status"] == "missing").sum()),
            "uden_R": int((~g["r_valid"].astype(bool)).sum()),
        })
    return pd.DataFrame(rows)


def r_distribution(trades: list[dict], group_key: str = "symbol") -> pd.DataFrame:
    """Fordelingen af 1R som procent af prisen — median OG interkvartilafstand.

    Spredningen er ikke pynt: et chart-baseret stop kan ligge meget tæt på entry, så
    en strategis R-fordeling kan være langt bredere end en andens. Uden spredningen
    kan et gennemsnitligt r_multiple ikke sammenlignes på tværs af strategier.
    """
    rows = []
    df = pd.DataFrame([t for t in trades if t.get("risk_pct")])
    if df.empty:
        return pd.DataFrame()
    for key, g in df.groupby(group_key):
        risk = g["risk_pct"].astype(float)
        q1, q3 = float(risk.quantile(0.25)), float(risk.quantile(0.75))
        rows.append({
            group_key: key,
            "n": len(g),
            "1R_pct_median": round(float(risk.median()), 4),
            "1R_pct_q1": round(q1, 4),
            "1R_pct_q3": round(q3, 4),
            "1R_pct_iqr": round(q3 - q1, 4),
        })
    return pd.DataFrame(rows)


def largest_r_multiples(trades: list[dict], n: int = 5) -> pd.DataFrame:
    """De n største r_multiples i absolut værdi.

    Et meget stramt stop giver et lille R, og så bliver et normalt kursudsving til et
    enormt R-multiple. Den slags outliers kan trække et gennemsnit alene, og det skal
    kunne ses frem for at gemme sig i middelværdien.
    """
    with_r = [t for t in trades if t.get("r_multiple_net") is not None]
    if not with_r:
        return pd.DataFrame()
    ranked = sorted(with_r, key=lambda t: abs(t["r_multiple_net"]), reverse=True)[:n]
    return pd.DataFrame([{
        "symbol": t["symbol"],
        "side": t["side"],
        "entry_time": t.get("entry_time"),
        "risk_pct": t.get("risk_pct"),
        "stop_source": t.get("stop_source"),
        "pnl_pct": t["pnl_pct"],
        "r_multiple_net": t["r_multiple_net"],
        "reason": t.get("reason"),
    } for t in ranked])
