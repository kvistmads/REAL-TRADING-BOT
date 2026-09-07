from __future__ import annotations

import math
from datetime import datetime


def _year_span(trades: list[dict]) -> float:
    times = [t.get("exit_time") or t.get("entry_time") for t in trades]
    times = [t for t in times if isinstance(t, datetime)]
    if len(times) < 2:
        return 0.0
    delta = max(times) - min(times)
    return delta.total_seconds() / (365.25 * 24 * 3600)


# Exits der ikke er et rigtigt trade-udfald: prisen er bare der hvor data slap op.
# De forvrider win-rate, Sharpe og drawdown og holdes derfor ude af alle metrics.
UNFINISHED_REASONS = ("end_of_data",)


def _empty() -> dict:
    return {
        "net": False, "total_cost_pct": 0.0,
        "gross_profit_pct": 0.0, "gross_loss_pct": 0.0,
        "total_trades": 0, "closed_trades": 0, "open_at_end_count": 0,
        "wins": 0, "losses": 0, "win_rate": 0.0,
        "avg_win_pct": 0.0, "avg_loss_pct": 0.0, "profit_factor": 0.0,
        "total_pnl": 0.0, "total_pnl_pct": 0.0, "compound_pnl_pct": 0.0,
        "avg_pnl_pct": 0.0,
        "max_drawdown_pct": 0.0, "sharpe": 0.0,
    }


def compute(trades: list[dict], net: bool = False) -> dict:
    """
    Beregner performance-metrics fra en liste af simulerede trades.
    Hver trade er en dict med mindst 'pnl' (USDT) og 'pnl_pct' (%).

    Trades med reason='end_of_data' var stadig åbne da data slap op — deres
    "exit"-pris er tilfældig, så de tælles med i ``total_trades`` og
    ``open_at_end_count``, men indgår IKKE i win-rate, Sharpe, drawdown eller
    PnL-summerne. ``closed_trades`` er antallet metrics faktisk bygger på.

    net=True regner på ``pnl_net``/``pnl_pct_net`` (efter spread, slippage og
    kurtage) i stedet for brutto. Bemærk at win_rate KAN ændre sig mellem de to:
    en handel der lige akkurat var i plus brutto, kan være i minus netto. Det er
    et rigtigt resultat og skal rapporteres som det falder ud.

    **``total_pnl_pct`` er en NAIV SUM af procenter — ikke et afkast.** −102%
    betyder ikke at kontoen var væk; procenter af skiftende grundlag kan ikke
    lægges sammen. Feltet er bevaret fordi andre kaldere bruger det, men
    ``compound_pnl_pct`` ved siden af er det rigtige tal. Se
    ``compound_return_pct``.
    """
    pnl_key, pct_key = ("pnl_net", "pnl_pct_net") if net else ("pnl", "pnl_pct")
    closed = [t for t in trades if t.get("reason") not in UNFINISHED_REASONS]
    open_at_end = len(trades) - len(closed)

    n = len(closed)
    if n == 0:
        result = _empty()
        result["total_trades"] = len(trades)
        result["open_at_end_count"] = open_at_end
        return result

    # Uden omkostningsfelter (ældre trades, eller ingen konfigureret model) falder
    # netto tilbage på brutto frem for at regne på nuller.
    pnls = [t.get(pnl_key, t.get("pnl", 0.0)) for t in closed]
    pcts = [t.get(pct_key, t.get("pnl_pct", 0.0)) for t in closed]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_pcts = [c for p, c in zip(pnls, pcts) if p > 0]
    loss_pcts = [c for p, c in zip(pnls, pcts) if p <= 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0
    )

    return {
        "net": net,
        "total_cost_pct": round(sum(t.get("cost_pct", 0.0) for t in closed), 3),
        "total_trades": len(trades),      # alle, inkl. dem der stadig var åbne
        "closed_trades": n,               # kun rigtige exits — metrics bygger på disse
        "open_at_end_count": open_at_end,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 2),
        "avg_win_pct": round(sum(win_pcts) / len(win_pcts), 3) if win_pcts else 0.0,
        "avg_loss_pct": round(sum(loss_pcts) / len(loss_pcts), 3) if loss_pcts else 0.0,
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else float("inf"),
        # Summerne bag profit factor. Eksponeret fordi PF IKKE kan aggregeres ved at
        # midle PF'er på tværs af symboler — den skal genberegnes fra summerne.
        "gross_profit_pct": round(sum(c for c in win_pcts), 4),
        "gross_loss_pct": round(abs(sum(c for c in loss_pcts)), 4),
        "total_pnl": round(sum(pnls), 4),
        # NAIV SUM — ikke et afkast. Bevaret for eksisterende kaldere.
        "total_pnl_pct": round(sum(pcts), 3),
        # Det rigtige tal: sammensat, sekventielt. Se compound_return_pct.
        "compound_pnl_pct": round(compound_return_pct(pcts), 3),
        "avg_pnl_pct": round(sum(pcts) / n, 3),
        "max_drawdown_pct": round(max_drawdown(pcts), 3),
        "sharpe": round(sharpe(pcts, closed), 3),
    }


def compute_both(trades: list[dict]) -> dict:
    """{"gross": {...}, "net": {...}} — begge opgørelser af det samme handelssæt.

    Metrikkerne skal vises SIDE OM SIDE, ikke erstattes: pointen er at kunne se
    præcis hvad omkostningerne æder, og et enkelt netto-tal skjuler det.
    """
    return {"gross": compute(trades), "net": compute(trades, net=True)}


def max_drawdown(pcts: list[float]) -> float:
    """Max peak-to-trough drawdown på kumulativ pct-kurve (negativt tal)."""
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pcts:
        cumulative += p
        peak = max(peak, cumulative)
        max_dd = min(max_dd, cumulative - peak)
    return max_dd


def sharpe(pcts: list[float], trades: list[dict], risk_free: float = 0.0) -> float:
    """Annualiseret Sharpe ratio (risk-free = 0) baseret på per-trade returns."""
    n = len(pcts)
    if n < 2:
        return 0.0
    returns = [p / 100 - risk_free for p in pcts]
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance)
    # Identiske returns giver ikke std == 0 eksakt: 9 × -3.0% efterlader
    # afrundingsrester (std ~1e-18), og mean/std eksploderer så til ~1e16.
    # Reel varians i pnl_pct ligger mange størrelsesordner over 1e-10.
    if std < 1e-10:
        return 0.0

    years = _year_span(trades)
    trades_per_year = n / years if years > 0 else float(n)
    return (mean / std) * math.sqrt(trades_per_year)


# ---------------------------------------------------------------------------
# Lange horisonter: egenkapitalkurve, baseline og de metrikker der hører til
# (PRD_FASE1_APPARATVALIDERING del 2)
#
# Apparatet ovenfor rapporterer win rate, profit factor og R pr. handel. Det er
# metrikker for MANGE KORTE handler. En strategi der holder en position i en
# måned skal måles på sin egenkapitalkurve, og den skal måles mod noget: en
# strategi der giver 8% om året på et aktiv der steg 40%, er ikke god.
#
# **Drawdown måles på DAGLIG mark-to-market, ikke ved exit.** Det er ikke en
# detalje. Måler man strategiens drawdown kun på lukkede handler, mens
# buy-and-hold måles dagligt, er strategiens dyk inde i en position usynlige —
# og kriteriet "materielt lavere drawdown end buy-and-hold" ville være rigget til
# at bestå. Begge sider skal ligge på samme tidsgitter.
# ---------------------------------------------------------------------------

def compound_return_pct(pcts: list[float]) -> float:
    """Sammensat afkast (%) af en SEKVENS af handels-procenter.

    ``sum(pcts)`` er ikke et afkast: +50% efterfulgt af −50% er ikke 0, det er
    −25%. Denne funktion kæder dem: ∏(1 + p/100) − 1.

    **Forudsætningen er sekventielle handler med hele kapitalen.** Det passer på
    en strategi som TSMOM, der holder ét instrument ad gangen. Det passer IKKE på
    botten i live, hvor ``stake_amount`` er 5 af 100 og fire positioner kan være
    åbne samtidig — dér er tallet "hvad hvis man havde sat alt på hver handel
    efter tur", ikke kontoens afkast. Kontoens afkast kræver en egenkapitalkurve;
    se ``curve_metrics``.
    """
    equity = 1.0
    for p in pcts:
        equity *= (1 + p / 100)
        if equity <= 0:          # ruin: kontoen kan ikke komme tilbage
            return -100.0
    return (equity - 1) * 100


def _years(index) -> float:
    """Kalenderår mellem første og sidste punkt på en tidsindekseret kurve."""
    if len(index) < 2:
        return 0.0
    return (index[-1] - index[0]).total_seconds() / (365.25 * 24 * 3600)


def max_drawdown_curve(equity) -> float:
    """Største fald fra hidtidigt højdepunkt på en egenkapitalkurve, i procent.

    Negativt tal. Modsat ``max_drawdown`` ovenfor, der arbejder på en kumulativ
    SUM af procenter, regner denne på selve kurven — det er den eneste udgave der
    kan sammenlignes med buy-and-hold.
    """
    import numpy as np

    values = np.asarray(equity, dtype=float)
    if values.size == 0:
        return 0.0
    peak = np.maximum.accumulate(values)
    return float((np.min(values / peak) - 1) * 100)


def longest_flat_days(equity) -> int:
    """Længste periode uden ny egenkapitaltop, i kalenderdage.

    Den vigtigste og mest oversete metrik: den fortæller hvor længe man skal kunne
    holde ud uden fremgang. En strategi med god CAGR og fire år uden nye toppe er
    ikke en strategi nogen faktisk kan følge.

    Perioden måles fra den seneste top til det punkt hvor toppen overgås. Er
    kurven stadig under sin top ved seriens slutning, tæller den igangværende
    periode med — den er lige så virkelig som de afsluttede.
    """
    import numpy as np

    values = np.asarray(equity, dtype=float)
    if values.size == 0:
        return 0
    index = equity.index
    peak = values[0]
    peak_at = index[0]
    worst = 0
    for i in range(1, len(values)):
        if values[i] >= peak:
            peak, peak_at = values[i], index[i]
        else:
            worst = max(worst, (index[i] - peak_at).days)
    return int(worst)


def curve_metrics(equity, exposure=None, positions: int | None = None) -> dict:
    """Metrikker for en egenkapitalkurve — det lange horisonts modstykke til ``compute``.

    ``equity``   pd.Series indekseret på dato, startende i 1.0.
    ``exposure`` pd.Series 0/1 på samme indeks: var der en åben position den dag?
    ``positions`` antal sammenhængende holdeperioder (se nedenfor).

    **De to "n" må ikke forveksles.** ``positions`` er antal gange der blev
    handlet; ``time_in_market_pct`` er hvor stor en andel af tiden der var
    eksponering. En strategi med 12 positioner à 5 måneder og en med 60 positioner
    à én måned kan have samme tid i markedet og vidt forskellige omkostninger.
    Begge tal rapporteres derfor altid.

    Sharpe er **annualiseret med den risikofri rente sat til nul.** Det er en
    bevidst konservativ antagelse, ikke en forglemmelse: kontanter forrentes ikke
    i denne opgørelse, hvilket underdriver afkastet for enhver strategi der står
    uden for markedet en del af tiden.
    """
    import numpy as np

    result = {
        "total_return_pct": 0.0, "cagr": 0.0, "max_drawdown_pct": 0.0,
        "sharpe": 0.0, "time_in_market_pct": 0.0, "longest_flat_days": 0,
        "positions": positions or 0, "years": 0.0,
    }
    if equity is None or len(equity) < 2:
        return result

    years = _years(equity.index)
    values = np.asarray(equity, dtype=float)
    total = float(values[-1] / values[0] - 1)

    rets = np.diff(values) / values[:-1]
    if rets.size >= 2 and float(np.std(rets, ddof=1)) > 1e-12:
        per_year = len(rets) / years if years > 0 else float(len(rets))
        sharpe_v = float(np.mean(rets) / np.std(rets, ddof=1) * math.sqrt(per_year))
    else:
        sharpe_v = 0.0

    result.update({
        "total_return_pct": round(total * 100, 2),
        # CAGR er udefineret hvis kapitalen er udslettet — rapportér -100%.
        "cagr": round(((1 + total) ** (1 / years) - 1) * 100, 2)
                if years > 0 and (1 + total) > 0 else (-100.0 if (1 + total) <= 0 else 0.0),
        "max_drawdown_pct": round(max_drawdown_curve(equity), 2),
        "sharpe": round(sharpe_v, 3),
        "longest_flat_days": longest_flat_days(equity),
        "years": round(years, 1),
    })
    if exposure is not None and len(exposure):
        result["time_in_market_pct"] = round(float(np.mean(np.asarray(exposure, float))) * 100, 1)
    return result


def buy_and_hold_curve(close, cost_pct: float = 0.0):
    """Buy-and-hold-egenkapitalkurve for samme instrument og periode.

    **Obligatorisk baseline.** ``trend_momentum`` havde PF 0,98 — men PF 0,98 mod
    *hvad*? Uden denne linje er intet af projektets tal fortolkeligt.

    ``cost_pct`` er ÉN rundtur over hele perioden: køb i starten, sælg i
    slutningen. Ikke nul. En baseline uden omkostninger ville stille strategien
    gunstigere end virkeligheden og gøre sammenligningen utilsigtet rigget.
    """
    curve = close / float(close.iloc[0])
    if cost_pct:
        # Halvdelen ved køb (dyrere indgang), halvdelen ved salg (billigere udgang).
        half = cost_pct / 100 / 2
        curve = curve * (1 - half) / (1 + half)
        curve.iloc[0] = 1.0
    return curve


def buy_and_hold_metrics(close, times, cost_pct: float = 0.0) -> dict:
    """Buy-and-hold-metrikker for et instrument over en periode.

    ``close`` og ``times`` er de barer strategien faktisk kunne handle i — altså
    EFTER warmup. Baselinen skal dække samme vindue som strategien, ellers
    sammenligner man to perioder.

    Returnerer ``curve_metrics``-dict'en, så baseline og strategi har præcis samme
    felter og ikke kan komme til at blive målt på hver sin måde.
    """
    import pandas as pd

    if close is None or len(close) < 2:
        return curve_metrics(None)
    series = pd.Series(list(map(float, close)), index=pd.DatetimeIndex(times))
    return curve_metrics(buy_and_hold_curve(series, cost_pct))
