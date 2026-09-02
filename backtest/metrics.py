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
        "total_pnl": 0.0, "total_pnl_pct": 0.0, "avg_pnl_pct": 0.0,
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
        "total_pnl_pct": round(sum(pcts), 3),
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
