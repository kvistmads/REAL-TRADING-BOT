"""Små statistik-primitiver — punkt-biseriel/Spearman-korrelation og andels-CI'er.

Skrevet i hånden frem for at trække scipy ind: projektet kører på numpy 2.5/pandas 3.0
(se requirements.txt for hvorfor det er lukket land for pandas-ta), og de fire funktioner
her er alt hvad confidence-valideringen har brug for. Alle er rene funktioner uden
tilstand, og de er dækket af tests/test_research_stats.py mod kendte referenceværdier.

Konfidensintervaller er ikke pynt i denne opgave: stikprøven rækker ikke til at se små
forskelle (~150 handler pr. bånd kan realistisk kun afsløre et gab omkring 20 pp), og
uden intervallet ville et snævert resultat blive læst som "virker ikke" i stedet for
"kan ikke afgøres".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# t-fordelingens hale (via den regulariserede ufuldstændige beta-funktion)
# ---------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Kædebrøk til I_x(a,b) — Lentz' algoritme (Numerical Recipes §6.4)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-16:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """I_x(a, b) for 0 <= x <= 1."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_test_p_value(t: float, df: float) -> float:
    """Tosidet p-værdi for en t-statistik. df <= 0 → 1.0 (intet at teste på)."""
    if df <= 0 or not math.isfinite(t):
        return 1.0
    return regularized_incomplete_beta(df / 2.0, 0.5, df / (df + t * t))


# ---------------------------------------------------------------------------
# Korrelationer
# ---------------------------------------------------------------------------


@dataclass
class Correlation:
    r: float
    p_value: float
    n: int

    def __str__(self) -> str:
        return f"r={self.r:+.3f} (p={self.p_value:.4f}, n={self.n})"


def _pearson(x: np.ndarray, y: np.ndarray) -> Correlation:
    n = len(x)
    if n < 3:
        return Correlation(float("nan"), 1.0, n)
    sx, sy = x.std(), y.std()
    if sx == 0 or sy == 0:  # konstant serie → korrelationen er udefineret
        return Correlation(float("nan"), 1.0, n)
    r = float(((x - x.mean()) * (y - y.mean())).mean() / (sx * sy))
    r = max(-1.0, min(1.0, r))
    if abs(r) >= 1.0:
        return Correlation(r, 0.0, n)
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return Correlation(r, t_test_p_value(t, n - 2), n)


def point_biserial(continuous, binary) -> Correlation:
    """Korrelation mellem en kontinuert variabel og et binært udfald.

    Matematisk identisk med Pearson på 0/1-kodningen — det er netop pointen: den
    besvarer "hænger confidence sammen med OM handlen vandt?", ikke hvor meget.
    """
    x = np.asarray(continuous, dtype=float)
    y = np.asarray(binary, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    return _pearson(x[mask], y[mask])


def spearman(x_values, y_values) -> Correlation:
    """Rang-korrelation (Pearson på rangene), robust over for pnl-fordelingens haler.

    Bindinger får gennemsnitsrang, så et bånd med mange ens confidence-værdier ikke
    får en kunstig rækkefølge.
    """
    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    return _pearson(_average_ranks(x[mask]), _average_ranks(y[mask]))


def _average_ranks(values: np.ndarray) -> np.ndarray:
    """Range 1..n med gennemsnitsrang ved bindinger."""
    n = len(values)
    if n == 0:
        return values
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    sorted_vals = values[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


# ---------------------------------------------------------------------------
# Andele
# ---------------------------------------------------------------------------

Z_95 = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score-interval for en andel — pålideligt også ved små n og p nær 0/1,
    hvor det normale Wald-interval kan række uden for [0, 1]."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def proportion_diff_interval(
    s1: int, n1: int, s2: int, n2: int, z: float = Z_95
) -> tuple[float, float]:
    """Newcombes hybrid score-interval for p1 - p2 (øverste minus nederste bånd).

    Bygget på de to Wilson-intervaller frem for en normalapproksimation af
    forskellen, så det opfører sig ordentligt når et bånd har få handler.
    """
    if n1 == 0 or n2 == 0:
        return (-1.0, 1.0)
    p1, p2 = s1 / n1, s2 / n2
    l1, u1 = wilson_interval(s1, n1, z)
    l2, u2 = wilson_interval(s2, n2, z)
    lower = (p1 - p2) - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = (p1 - p2) + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (max(-1.0, lower), min(1.0, upper))


# z for 80% styrke (ensidet beta=0.20). Sammen med Z_95 giver de standardparret
# til to-andels-styrkeberegningen nedenfor.
Z_POWER_80 = 0.8416212335729143


def min_detectable_diff(n_per_group: int, p_baseline: float = 0.4) -> float:
    """Mindste forskel i andele som n handler pr. gruppe kan afsløre (alpha 5%, styrke 80%).

    Normalapproksimation: (z_alpha/2 + z_beta) · sqrt(2·p·(1-p)/n). Bruges til at
    sætte et ærligt loft over hvad stikprøven kan sige — et snævert resultat under
    denne grænse betyder "kan ikke afgøres", ikke "der er ingen effekt".
    """
    if n_per_group < 2:
        return 1.0
    var = 2 * p_baseline * (1 - p_baseline)
    return min(1.0, (Z_95 + Z_POWER_80) * math.sqrt(var / n_per_group))


def spearman_ci(r: float, n: int, z: float = Z_95) -> tuple[float, float]:
    """95%-CI for en Spearman-korrelation via Fisher z-transformation.

    SE = 1/sqrt(n-3) er approksimationen for Pearson; for Spearman er den let
    optimistisk (Bonett-Wright bruger ~1.03/sqrt(n-3)). Med meget små n er
    intervallet uanset så bredt at forskellen er akademisk — pointen med at
    rapportere det er at VISE hvor lidt seks punkter kan afgøre.

    n <= 3 → (-1, 1): der er intet interval at beregne.
    """
    if n <= 3 or not math.isfinite(r):
        return (-1.0, 1.0)
    r = max(-0.999999, min(0.999999, r))
    zr = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3)
    return (math.tanh(zr - z * se), math.tanh(zr + z * se))


def mean_ci(values, z: float = Z_95) -> tuple[float, float]:
    """95%-CI for et gennemsnit (normalapproksimation på standardfejlen)."""
    arr = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    n = len(arr)
    if n < 2:
        return (float("nan"), float("nan"))
    se = arr.std(ddof=1) / math.sqrt(n)
    mean = float(arr.mean())
    return (mean - z * se, mean + z * se)


def breakeven_win_rate(avg_win_r: float, avg_loss_r: float, cost_r: float = 0.0) -> float:
    """Den win rate der lige akkurat går i nul, givet de FAKTISKE haler.

        WR = (L_gns + omkostning) / (W_gns + L_gns)

    Udledt af EV = WR·W − (1−WR)·L − c = 0. Bemærk at antagelsen +2R/−1R giver
    33,3%, men breakeven-stop og time-stop forvrider begge haler: nogle tabere
    lukker nær 0R, nogle vindere lukker under 2R. Det er de observerede haler der
    afgør om en strategi overhovedet kan tjene penge på et givet instrument.

    avg_win_r og avg_loss_r er begge POSITIVE størrelser (tabets absolutværdi).
    """
    denom = avg_win_r + avg_loss_r
    if denom <= 0 or not math.isfinite(denom):
        return float("nan")
    return (avg_loss_r + cost_r) / denom
