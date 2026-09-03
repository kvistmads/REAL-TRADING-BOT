"""Indlæsning og validering af den lange XAU/USD-serie (2004-2025).

``data/historical_xau/XAU_4h_data.csv`` dækker 21 år mod de 2 vi ellers arbejder med.
Den er hentet fra et GitHub-repo med én commit, i MT4/MT5-eksportformat, og
``README.md`` dér opstiller fire forbehold: ukendt kilde, formentlig tick-volumen,
ingen krydsvalidering, huller ikke undersøgt.

**Serien erstatter ikke den nuværende guld-kilde.** Den bruges udelukkende til
research, og kun hvis den består valideringen.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

LONG_SERIES = (Path(__file__).resolve().parent.parent
               / "data" / "historical_xau" / "XAU_4h_data.csv")

# Et normalt år har ~1540 4h-barer i denne serie (guld handler ~23t/døgn, 5 dage/uge).
EXPECTED_BARS_PER_YEAR = 1540
# Under denne årsdækning regnes året som utilstrækkeligt.
MIN_YEAR_COVERAGE = 0.90


def load_long_series(path: Path | None = None) -> pd.DataFrame:
    """Indlæs MT4/MT5-eksporten til projektets standardformat (time/OHLCV).

    Formatet er semikolon-separeret med ``2004.06.11 04:00``-tidsstempler. Serien
    sorteres og dubletter fjernes, så den opfylder samme kontrakt som
    ``backtest.runner.fetch_data``.
    """
    df = pd.read_csv(path or LONG_SERIES, sep=";")
    df.columns = [c.lower() for c in df.columns]
    df["time"] = pd.to_datetime(df["date"], format="%Y.%m.%d %H:%M")
    df = df[["time", "open", "high", "low", "close", "volume"]]
    return (df.drop_duplicates(subset="time")
              .sort_values("time")
              .reset_index(drop=True))


def yearly_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Datakvalitet pr. år — det der afgør hvilke perioder der kan bruges."""
    rows = []
    for year, g in df.groupby(df["time"].dt.year):
        # Første og sidste år er delvise; dækning måles mod den faktisk dækkede
        # del af året frem for mod et helt år.
        span_days = (g["time"].iloc[-1] - g["time"].iloc[0]).days + 1
        expected = EXPECTED_BARS_PER_YEAR * span_days / 365.25
        gaps = g["time"].diff().dt.total_seconds() / 3600
        rows.append({
            "år": int(year),
            "barer": len(g),
            "forventet": int(expected),
            "dækning_%": round(100 * len(g) / expected, 1) if expected else 0.0,
            "flade_barer": int((g["high"] == g["low"]).sum()),
            "nul_volumen": int((g["volume"] == 0).sum()),
            "huller>72t": int((gaps > 72).sum()),
            "største_hul_dage": round(float(gaps.max() / 24), 1) if len(g) > 1 else 0.0,
        })
    out = pd.DataFrame(rows)
    out["brugbar"] = out["dækning_%"] >= 100 * MIN_YEAR_COVERAGE
    return out


def usable_span(quality: pd.DataFrame) -> tuple[int, int] | None:
    """Længste ubrudte række af brugbare år.

    Restriktion til de validerede år er ikke en REPARATION af dataen — intet
    ændres, udfyldes eller interpoleres. Det er en afgrænsning af hvad serien kan
    bære, og den skal stå eksplicit i rapporten.
    """
    usable = quality[quality["brugbar"]]["år"].tolist()
    if not usable:
        return None
    best = cur = [usable[0]]
    for y in usable[1:]:
        if y == cur[-1] + 1:
            cur.append(y)
        else:
            cur = [y]
        if len(cur) > len(best):
            best = list(cur)
    return (best[0], best[-1])


def cross_validate_daily(long_df: pd.DataFrame, reference: pd.DataFrame,
                         periods: list[tuple[str, str]]) -> pd.DataFrame:
    """Sammenlign daglige lukkekurser mod en uafhængig kilde på flere perioder.

    Guld-spot (denne serie) og COMEX-futures (``GC=F``) er ikke samme instrument —
    futures bærer carry, så et niveauafvig er forventeligt. Det der skal holde er
    at de BEVÆGER sig ens: korrelationen på daglige afkast er derfor det afgørende
    tal, ikke prisforskellen.
    """
    long_daily = (long_df.set_index("time")["close"].resample("1D").last().dropna())
    ref_daily = reference["close"].resample("1D").last().dropna()

    rows = []
    for start, end in periods:
        a = long_daily[(long_daily.index >= start) & (long_daily.index <= end)]
        b = ref_daily[(ref_daily.index >= start) & (ref_daily.index <= end)]
        common = a.index.intersection(b.index)
        if len(common) < 20:
            rows.append({"periode": f"{start}→{end}", "fælles_dage": len(common),
                         "status": "for få fælles dage"})
            continue
        a2, b2 = a.loc[common], b.loc[common]
        diff_pct = ((a2 - b2) / b2 * 100)
        ret_a, ret_b = a2.pct_change().dropna(), b2.pct_change().dropna()
        rows.append({
            "periode": f"{start}→{end}",
            "fælles_dage": len(common),
            "lang_serie_barer": len(a),
            "GC=F_barer": len(b),
            "median_prisafvig_%": round(float(diff_pct.median()), 3),
            "maks_prisafvig_%": round(float(diff_pct.abs().max()), 3),
            "korr_daglige_afkast": round(float(ret_a.corr(ret_b)), 4),
            "status": "ok",
        })
    return pd.DataFrame(rows)


def volume_profile(df: pd.DataFrame) -> dict:
    """Opfører volumen sig meningsfuldt, eller er det tick-volumen?

    Tick-volumen tæller prisændringer, ikke omsat mængde. Det er ikke ubrugeligt —
    det korrelerer med aktivitet — men niveauet er broker-afhængigt og kan ikke
    sammenlignes med rigtig volumen. Strategier der bruger volumen-ratio skal
    markeres som upålidelige på serien.
    """
    from data.indicators import calculate_volume_ma

    vol = df["volume"].astype(float)
    ma = calculate_volume_ma(df, 20)
    ratio = (vol / ma).replace([np.inf, -np.inf], np.nan).dropna()
    rng = (df["high"] - df["low"]).abs()
    return {
        "median_volumen": round(float(vol.median()), 1),
        "volumen_min": round(float(vol.min()), 1),
        "volumen_maks": round(float(vol.max()), 1),
        "andel_nul": round(100 * float((vol == 0).mean()), 3),
        "median_ratio": round(float(ratio.median()), 4),
        "ratio_p90": round(float(ratio.quantile(0.90)), 4),
        # Tick-volumen følger prisbevægelse tæt, fordi hvert tick ER en bevægelse.
        # Høj korrelation med bar-range er derfor en indikation på tick-volumen.
        "korr_volumen_range": round(float(vol.corr(rng)), 4),
    }
