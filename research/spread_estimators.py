"""Estimering af effektiv bid-ask spread fra OHLCV — Corwin-Schultz og Roll.

Vores omkostningsmodel antager **1 tick spread og N(0,5; 0,5) ticks slippage**.
`research/output/cost_model.md` markerer det selv som modelantagelser uden
datagrundlag. På 4h var det acceptabelt; på 15m er omkostningen pr. handel
nogenlunde konstant mens bevægelsen skrumper, så skønnet bliver den dominerende
usikkerhed i alt vi regner.

Spread findes ikke i OHLCV. Den skal enten optages fremadrettet
(`research/orderbook_recorder.py`) eller estimeres bagudrettet — det er hvad dette
modul gør.

## Corwin & Schultz (2012), Journal of Finance 67(2), 719-760

Bygger på to observationer: dagens **high er typisk køber-initieret og low
sælger-initieret**, så high/low-forholdet indeholder både volatilitet og spread; og
**volatilitet skalerer med tiden mens spread ikke gør.** To ligninger, to ubekendte.

    β = [ln(H₁/L₁)]² + [ln(H₂/L₂)]²
    γ = [ln(max(H₁,H₂)/min(L₁,L₂))]²
    α = (√(2β) − √β)/(3 − 2√2) − √(γ/(3 − 2√2))
    S = 2(e^α − 1)/(1 + e^α)

Formlerne er verificeret mod forfatterens egen referenceimplementering
(Ødegaards R-kode, `high_low_spread_estimator*.R`), ikke gengivet fra hukommelsen.

### Overnight-justeringen

Estimatoren antager **sammenhængende handel**. Lukker markedet om natten eller i
weekenden — hvilket GC=F, 6E og 6B gør — indeholder to-bars-rangen et spring der
ikke er handel.

**Retningen er kontraintuitiv, og den er efterprøvet frem for gættet.** Springet
puster γ op; γ indgår som −√(γ/K) i α, så et større γ giver et MINDRE α og dermed
et MINDRE spread. Et natligt gap får altså estimatoren til at **undervurdere**
spreadet, ofte så meget at vinduet bliver negativt. Målt på en syntetisk serie med
2% natlige spring: middel-α svarer til −0,032 ujusteret mod −0,001 justeret.

Det er den farlige retning for vores formål: uden justeringen ville futures se
billigere ud end de er, præcis dér hvor prop-sporet skal handle.

Justeringen flytter bar 2's range så den lige akkurat rører forrige bars close:

    hvis H₂ < close₁:  læg (close₁ − H₂) til både H₂ og L₂
    hvis L₂ > close₁:  træk (L₂ − close₁) fra både H₂ og L₂

Krypto handler 24/7 og har ikke problemet; forskellen mellem justeret og ujusteret
er derfor et direkte mål for hvor meget natten fylder på futures.

## Støjgulvet — den vigtigste begrænsning

Estimatoren har et **positivt gulv** der ikke er spread. Gulvlægningen af negative
vinduer (nedenfor) betyder at ren støj midles til et positivt tal: på en simuleret
serie med spread præcis 0 rapporterer den ~0,08%. Vores model antager 1 bp på
krypto — altså en størrelsesorden UNDER gulvet.

``noise_floor()`` kalibrerer gulvet pr. serie ved at køre estimatoren på en
syntetisk nul-spread-serie med samme volatilitet og samme antal barer. Et estimat
der ikke ligger klart over sit eget gulv, er ikke en måling af spread — det er en
måling af volatilitet. **Uden den kalibrering ville hvert eneste tal i DEL 2a se ud
som en spread der var 10-100× for stor.**

### Negative estimater

Enkelte to-bars-vinduer giver **negativ** S. Det er en kendt egenskab ved
estimatoren, ikke en implementeringsfejl. Vi **sætter dem til nul før midling**
(som forfatterens egen kode gør) og rapporterer altid hvor stor en andel de
udgør — er 30% af vinduerne negative, kæmper estimatoren med vores data, og det er
i sig selv et resultat.

## Roll (1984), Journal of Finance 39(4), 1127-1139

Handelsomkostninger får observerede priser til at hoppe mellem bud og udbud, hvilket
skaber **negativ autokovarians** i prisændringer:

    S = 2√(−Cov(Δp_t, Δp_{t−1}))

Anvendes her på **log-afkast**, så resultatet er en brøkdel af prisen og kan
sammenlignes direkte med Corwin-Schultz.

**Estimatoren er udefineret når kovariansen er positiv** — og det er den ofte på
trendende data, hvor momentum overdøver bid-ask-hoppet. Andelen af udefinerede
vinduer rapporteres derfor sammen med tallet; er den høj, er Roll det forkerte
værktøj til den serie, ikke markedet der er mærkeligt.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# (3 − 2√2) går igen i både α-leddene; beregnes én gang.
K = 3 - 2 * np.sqrt(2)


def corwin_schultz_windows(df: pd.DataFrame, adjust_overnight: bool = True) -> np.ndarray:
    """S pr. to-bars-vindue. Returnerer RÅ værdier — også de negative.

    Afkortning hører til i aggregeringen, ikke her: hvor ofte estimatet bliver
    negativt er et resultat vi vil kunne se, og det forsvinder hvis det gulvlægges
    ved kilden.
    """
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    if len(h) < 2:
        return np.array([])

    h1, l1 = h[:-1], l[:-1]
    h2, l2 = h[1:].copy(), l[1:].copy()

    if adjust_overnight:
        prev_close = c[:-1]
        # Bar 2 ligger helt UNDER forrige close → skub den op til den rører.
        gap_down = h2 < prev_close
        diff = prev_close[gap_down] - h2[gap_down]
        h2[gap_down] += diff
        l2[gap_down] += diff
        # Bar 2 ligger helt OVER forrige close → skub den ned.
        gap_up = l2 > prev_close
        diff = l2[gap_up] - prev_close[gap_up]
        h2[gap_up] -= diff
        l2[gap_up] -= diff

    with np.errstate(divide="ignore", invalid="ignore"):
        beta = np.log(h1 / l1) ** 2 + np.log(h2 / l2) ** 2
        gamma = np.log(np.maximum(h1, h2) / np.minimum(l1, l2)) ** 2
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / K - np.sqrt(gamma / K)
        s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    return s[np.isfinite(s)]


def corwin_schultz(df: pd.DataFrame, adjust_overnight: bool = True) -> dict:
    """Aggregeret spread-estimat med det bogholderi der gør det fortolkeligt."""
    s = corwin_schultz_windows(df, adjust_overnight)
    if s.size == 0:
        return {"spread_pct": float("nan"), "n_windows": 0, "negative_share_pct": float("nan"),
                "raw_mean_pct": float("nan"), "median_pct": float("nan")}
    floored = np.maximum(s, 0.0)
    return {
        # Hovedtal: negative vinduer sat til nul før midling, som forfatterens kode.
        "spread_pct": round(float(floored.mean()) * 100, 5),
        # Uafkortet middel — forskellen viser hvor meget gulvet flytter.
        "raw_mean_pct": round(float(s.mean()) * 100, 5),
        "median_pct": round(float(np.median(floored)) * 100, 5),
        "negative_share_pct": round(float((s < 0).mean()) * 100, 1),
        "n_windows": int(s.size),
    }


def roll(df: pd.DataFrame) -> dict:
    """Roll (1984) på log-afkast for hele serien. Udefineret ved positiv kovarians."""
    p = np.log(df["close"].to_numpy(float))
    d = np.diff(p)
    d = d[np.isfinite(d)]
    if d.size < 3:
        return {"spread_pct": float("nan"), "cov": float("nan"), "defined": False, "n": int(d.size)}
    cov = float(np.cov(d[1:], d[:-1], ddof=1)[0, 1])
    return {
        "spread_pct": round(2 * np.sqrt(-cov) * 100, 5) if cov < 0 else float("nan"),
        "cov": cov,
        "defined": cov < 0,
        "n": int(d.size),
    }


def roll_rolling(df: pd.DataFrame, window: int = 200) -> dict:
    """Roll på rullende vinduer — giver en fordeling og andelen af udefinerede.

    Ét tal for hele serien skjuler at kovariansen skifter fortegn undervejs.
    Andelen af vinduer hvor estimatoren ikke kan bruges er lige så informativ som
    gennemsnittet af dem hvor den kan.
    """
    p = np.log(df["close"].to_numpy(float))
    d = np.diff(p)
    d = d[np.isfinite(d)]
    if d.size < window + 2:
        return {"spread_pct": float("nan"), "undefined_share_pct": float("nan"), "n_windows": 0}

    out = []
    undefined = 0
    for i in range(0, d.size - window, max(window // 4, 1)):
        seg = d[i:i + window]
        cov = float(np.cov(seg[1:], seg[:-1], ddof=1)[0, 1])
        if cov < 0:
            out.append(2 * np.sqrt(-cov))
        else:
            undefined += 1
    total = len(out) + undefined
    return {
        "spread_pct": round(float(np.mean(out)) * 100, 5) if out else float("nan"),
        "undefined_share_pct": round(100 * undefined / total, 1) if total else float("nan"),
        "n_windows": total,
    }


def volatility_split(df: pd.DataFrame, adjust_overnight: bool = True) -> dict:
    """Ændrer spreadet sig mellem rolige og volatile perioder?

    Det er den betragtning der afgør om en KONSTANT spread i modellen undervurderer
    omkostningen præcis når strategien handler mest. Vinduerne deles på medianen af
    bar-range (high−low)/close, og spreadet estimeres i hver halvdel for sig.
    """
    rng = ((df["high"] - df["low"]) / df["close"]).to_numpy(float)
    pair_rng = np.maximum(rng[:-1], rng[1:])          # samme vinduer som estimatoren
    s = corwin_schultz_windows(df, adjust_overnight)
    if s.size == 0 or pair_rng.size != s.size:
        n = min(s.size, pair_rng.size)
        s, pair_rng = s[:n], pair_rng[:n]
    if s.size < 20:
        return {"calm_pct": float("nan"), "volatile_pct": float("nan"), "ratio": float("nan")}

    cut = float(np.median(pair_rng))
    calm = np.maximum(s[pair_rng <= cut], 0.0)
    vol = np.maximum(s[pair_rng > cut], 0.0)
    calm_m = float(calm.mean()) * 100 if calm.size else float("nan")
    vol_m = float(vol.mean()) * 100 if vol.size else float("nan")
    return {
        "calm_pct": round(calm_m, 5),
        "volatile_pct": round(vol_m, 5),
        "ratio": round(vol_m / calm_m, 2) if calm_m and np.isfinite(calm_m) and calm_m > 0 else float("nan"),
    }


def noise_floor(df: pd.DataFrame, n_sims: int = 12, seed: int = 4,
                adjust_overnight: bool = True) -> dict:
    """Hvad rapporterer estimatoren på en serie med spread PRÆCIS nul?

    Kalibrerer det positive gulv der stammer fra gulvlægningen af negative vinduer,
    ikke fra spread. Simulerer en geometrisk random walk med samme antal barer,
    samme bar-volatilitet og samme intrabar-range som den rigtige serie — men uden
    bid-ask-hop — og kører estimatoren på den.

    Et estimat der ikke ligger klart OVER sit eget gulv, måler volatilitet, ikke
    spread. Tallet hører derfor med hver eneste gang estimatet rapporteres.
    """
    close = df["close"].to_numpy(float)
    if len(close) < 50:
        return {"floor_pct": float("nan"), "floor_sd_pct": float("nan")}

    ret = np.diff(np.log(close))
    sigma = float(np.nanstd(ret[np.isfinite(ret)], ddof=1))
    # Intrabar-range i forhold til bar-volatiliteten: den bestemmer hvor meget
    # high/low spreder sig ud over close-til-close-bevægelsen.
    rng_ratio = float(np.nanmedian((df["high"] - df["low"]).to_numpy(float) / close))
    n = len(close)

    rng = np.random.default_rng(seed)
    floors = []
    for _ in range(n_sims):
        c = 100 * np.exp(np.cumsum(rng.normal(0, sigma, n)))
        half = rng.uniform(0.3, 0.7, n) * rng_ratio      # asymmetrisk range om close
        sim = pd.DataFrame({
            "close": c, "open": c,
            "high": c * (1 + half), "low": c * (1 - (rng_ratio - half)),
            "volume": 1.0,
        })
        floors.append(corwin_schultz(sim, adjust_overnight)["spread_pct"])
    return {
        "floor_pct": round(float(np.mean(floors)), 5),
        "floor_sd_pct": round(float(np.std(floors, ddof=1)), 5),
    }
