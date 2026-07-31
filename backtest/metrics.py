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


def compute(trades: list[dict]) -> dict:
    """
    Beregner performance-metrics fra en liste af simulerede trades.
    Hver trade er en dict med mindst 'pnl' (USDT) og 'pnl_pct' (%).
    """
    n = len(trades)
    if n == 0:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "avg_win_pct": 0.0, "avg_loss_pct": 0.0, "profit_factor": 0.0,
            "total_pnl": 0.0, "total_pnl_pct": 0.0, "avg_pnl_pct": 0.0,
            "max_drawdown_pct": 0.0, "sharpe": 0.0,
        }

    pnls = [t.get("pnl", 0.0) for t in trades]
    pcts = [t.get("pnl_pct", 0.0) for t in trades]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_pcts = [t["pnl_pct"] for t in trades if t.get("pnl", 0.0) > 0]
    loss_pcts = [t["pnl_pct"] for t in trades if t.get("pnl", 0.0) <= 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0
    )

    return {
        "total_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 2),
        "avg_win_pct": round(sum(win_pcts) / len(win_pcts), 3) if win_pcts else 0.0,
        "avg_loss_pct": round(sum(loss_pcts) / len(loss_pcts), 3) if loss_pcts else 0.0,
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else float("inf"),
        "total_pnl": round(sum(pnls), 4),
        "total_pnl_pct": round(sum(pcts), 3),
        "avg_pnl_pct": round(sum(pcts) / n, 3),
        "max_drawdown_pct": round(max_drawdown(pcts), 3),
        "sharpe": round(sharpe(pcts, trades), 3),
    }


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
