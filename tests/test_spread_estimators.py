"""Tests for research/spread_estimators.py.

Estimatorerne skal bruges til at afgøre om en 15m-strategi overhovedet kan bære
sine omkostninger. Er de forkerte, er den beslutning forkert — og fejlen ville
være usynlig, fordi vi ikke har målt spread at holde dem op imod endnu.

Derfor to slags tests:

1. **Formeltro** — mod forfatterens egen referenceimplementering (Ødegaards
   R-kode). Et enkelt vindue regnet i hånden, så en fortegnsfejl i α ikke kan
   snige sig igennem.
2. **Genfinding** — en syntetisk serie med en KENDT spread. Kan estimatoren ikke
   finde en spread vi selv har lagt ind, kan den heller ikke finde markedets.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research import spread_estimators as se


def _bars_from_prices(prices: np.ndarray, per_bar: int) -> pd.DataFrame:
    """Byg OHLC-barer af en tick-serie."""
    n = len(prices) // per_bar
    p = prices[:n * per_bar].reshape(n, per_bar)
    return pd.DataFrame({
        "open": p[:, 0], "high": p.max(axis=1),
        "low": p.min(axis=1), "close": p[:, -1],
        "volume": 1.0,
    })


def _simulated_market(spread: float, n_ticks: int = 400_000, per_bar: int = 40,
                      vol: float = 0.0004, seed: int = 11) -> pd.DataFrame:
    """Effektiv pris = sand pris × (1 ± spread/2), tilfældigt fortegn.

    Det er præcis den datagenererende proces begge estimatorer antager: en
    efficient pris man ikke ser, og et observeret bid-ask-hop omkring den.
    """
    rng = np.random.default_rng(seed)
    true = 100 * np.exp(np.cumsum(rng.normal(0, vol, n_ticks)))
    side = rng.choice([-1.0, 1.0], n_ticks)
    return _bars_from_prices(true * (1 + side * spread / 2), per_bar)


# ---------------------------------------------------------------------------
# Formeltro
# ---------------------------------------------------------------------------

def test_corwin_schultz_matches_reference_formula_by_hand():
    """Ét vindue, regnet igennem uafhængigt af implementeringen."""
    df = pd.DataFrame({"high": [101.0, 102.0], "low": [99.0, 100.0],
                       "close": [100.0, 101.0], "open": [100.0, 100.5],
                       "volume": [1.0, 1.0]})
    beta = np.log(101 / 99) ** 2 + np.log(102 / 100) ** 2
    gamma = np.log(102 / 99) ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    expected = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))

    got = se.corwin_schultz_windows(df, adjust_overnight=False)
    assert got[0] == pytest.approx(expected, rel=1e-12)


def test_overnight_adjustment_shifts_the_second_bar_onto_the_previous_close():
    """Gap op: bar 2 skubbes NED så dens low rører forrige close.

    Reglen er hentet fra referenceimplementeringen, ikke fra hukommelsen. Uden den
    tæller det natlige spring som handelsrange, og spreadet overvurderes.
    """
    df = pd.DataFrame({"high": [101.0, 112.0], "low": [99.0, 110.0],
                       "close": [100.0, 111.0], "open": [100.0, 110.5],
                       "volume": [1.0, 1.0]})
    # Bar 2 skubbes ned med (110 - 100) = 10 → high 102, low 100.
    manual = pd.DataFrame({"high": [101.0, 102.0], "low": [99.0, 100.0],
                           "close": [100.0, 101.0], "open": [100.0, 100.5],
                           "volume": [1.0, 1.0]})
    adjusted = se.corwin_schultz_windows(df, adjust_overnight=True)
    reference = se.corwin_schultz_windows(manual, adjust_overnight=False)
    assert adjusted[0] == pytest.approx(reference[0], rel=1e-12)


def test_overnight_gaps_bias_the_estimate_DOWN_and_the_adjustment_lifts_it():
    """Retningen er kontraintuitiv, så den er låst fast her.

    Et natligt spring puster γ op. γ indgår som −√(γ/K) i α, så et STØRRE γ giver
    et MINDRE spread-estimat. Gappet får altså estimatoren til at undervurdere —
    ikke overvurdere — og justeringen løfter tallet igen.

    Det er den farlige retning: uden justeringen ville futures se billigere ud end
    de er. Målt på uafkortede vinduer, fordi gulvlægningen ved nul skjuler
    forskellen når begge middelværdier er negative.
    """
    rng = np.random.default_rng(3)
    n = 2000
    close = (100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
             * np.exp(np.cumsum(rng.normal(0, 0.02, n))))   # 2% natlige spring
    df = pd.DataFrame({"close": close, "open": close,
                       "high": close * 1.004, "low": close * 0.996, "volume": 1.0})
    raw = se.corwin_schultz_windows(df, adjust_overnight=False).mean()
    adj = se.corwin_schultz_windows(df, adjust_overnight=True).mean()
    assert raw < adj                       # justeringen LØFTER estimatet
    assert raw < 0                         # gappet driver det negativt


# ---------------------------------------------------------------------------
# Genfinding af en kendt spread
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spread", [0.0005, 0.002])
def test_corwin_schultz_recovers_a_known_spread(spread):
    df = _simulated_market(spread)
    got = se.corwin_schultz(df, adjust_overnight=False)["spread_pct"] / 100
    # Estimatoren er kendt biased i endelige stikprøver; en faktor 2 er den
    # tolerance litteraturen selv arbejder med.
    assert got == pytest.approx(spread, rel=1.0)
    assert got > 0


@pytest.mark.parametrize("spread", [0.002, 0.005])
def test_roll_recovers_a_known_spread(spread):
    df = _simulated_market(spread)
    r = se.roll(df)
    assert r["defined"]
    assert r["spread_pct"] / 100 == pytest.approx(spread, rel=1.0)


def test_roll_goes_undefined_when_the_spread_is_small_relative_to_volatility():
    """Ved 5 bp drukner bid-ask-hoppet i volatiliteten, og kovariansen bliver positiv.

    Det er ikke en fejl — det er estimatorens gyldighedsområde. Den skal sige
    "ved ikke", ikke gætte. Vores model antager 1 bp på krypto, altså langt under
    dette punkt.
    """
    assert not se.roll(_simulated_market(0.0005))["defined"]


def test_corwin_schultz_has_a_positive_noise_floor_that_is_not_spread():
    """På en serie med spread PRÆCIS nul rapporterer estimatoren stadig et positivt tal.

    Gulvlægningen af negative vinduer midler ren støj op til noget positivt. Det er
    den vigtigste begrænsning ved metoden på vores data: modellen antager 1 bp på
    krypto, og gulvet ligger en størrelsesorden derover. Uden denne kalibrering
    ville hvert estimat i DEL 2a se ud som en spread der var 10-100× for stor.
    """
    df = _simulated_market(0.0)
    floored = se.corwin_schultz(df, adjust_overnight=False)
    assert floored["spread_pct"] > 0.05          # gulvet er reelt, ikke nul
    # Det UAFKORTEDE middel er derimod centreret omkring nul, som det skal være.
    assert abs(floored["raw_mean_pct"]) < 0.05

    floor = se.noise_floor(df, n_sims=5)
    assert floor["floor_pct"] > 0
    # Kalibreringen skal ramme det observerede gulv, ikke bare være positiv.
    assert floor["floor_pct"] == pytest.approx(floored["spread_pct"], rel=0.8)


# ---------------------------------------------------------------------------
# Bogholderiet omkring tallene
# ---------------------------------------------------------------------------

def test_negative_windows_are_reported_not_hidden():
    """Andelen af negative vinduer er et resultat, ikke støj der skal fejes væk."""
    df = _simulated_market(0.0)
    out = se.corwin_schultz(df, adjust_overnight=False)
    assert out["negative_share_pct"] > 0          # nul-spread giver mange negative
    assert out["raw_mean_pct"] < out["spread_pct"]  # gulvet flytter middelværdien op


def test_roll_reports_undefined_windows_instead_of_returning_a_number():
    """Positiv autokovarians → udefineret. Estimatoren må ikke lade som om den ved noget.

    Momentum i afkastene (her en AR(1) med positiv koefficient) er præcis det der
    overdøver bid-ask-hoppet. Roll kan ikke skelne, og skal sige det.
    """
    rng = np.random.default_rng(9)
    n = 4000
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = 0.6 * r[i - 1] + rng.normal(0, 0.002)      # positivt autokorreleret
    close = 100 * np.exp(np.cumsum(r))
    trend = pd.DataFrame({"close": close, "open": close,
                          "high": close * 1.001, "low": close * 0.999, "volume": 1.0})
    out = se.roll_rolling(trend, window=200)
    assert out["undefined_share_pct"] > 90
    assert np.isnan(out["spread_pct"]) or out["n_windows"] > 0


def test_volatility_split_separates_calm_from_turbulent_windows():
    df = _simulated_market(0.001)
    out = se.volatility_split(df, adjust_overnight=False)
    assert np.isfinite(out["calm_pct"]) and np.isfinite(out["volatile_pct"])
    assert out["calm_pct"] > 0
