from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

RESULTS_DIR = Path("backtest_results")


def print_metrics(metrics: dict, meta: dict) -> None:
    """Print et pænt resumé til terminalen."""
    pf = metrics["profit_factor"]
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    print()
    print("=" * 60)
    print(
        f"  {meta.get('strategy', '?')} | {meta.get('symbol', '?')} | "
        f"{meta.get('timeframe', '?')}  "
        f"({meta.get('from', '?')} → {meta.get('to', '?')})"
    )
    print("=" * 60)
    print(
        f"  Trades: {metrics['total_trades']} | "
        f"Win rate: {metrics['win_rate']}% | "
        f"Avg P&L: {metrics['avg_pnl_pct']:+.2f}% | "
        f"Max drawdown: {metrics['max_drawdown_pct']:.2f}%"
    )
    print(
        f"  Wins: {metrics['wins']} | Losses: {metrics['losses']} | "
        f"Profit factor: {pf_str}"
    )
    print(
        f"  Avg win: {metrics['avg_win_pct']:+.2f}% | "
        f"Avg loss: {metrics['avg_loss_pct']:+.2f}% | "
        f"Total P&L: {metrics['total_pnl_pct']:+.2f}% ({metrics['total_pnl']:+.2f} USDT)"
    )
    print(f"  Sharpe (annualized): {metrics['sharpe']:.2f}")
    print("=" * 60)


def save_csv(trades: list[dict], meta: dict) -> Path:
    """Gem alle trades til CSV under backtest_results/."""
    RESULTS_DIR.mkdir(exist_ok=True)
    # Symboler er på formen BTC/USDT — skråstregen ville ellers blive læst som undermappe.
    symbol = meta["symbol"].replace("/", "-")
    filename = f"{meta['strategy']}_{symbol}_{meta['timeframe']}.csv"
    path = RESULTS_DIR / filename

    fields = [
        "symbol", "side", "strategy_id", "entry_time", "exit_time",
        "entry_price", "exit_price", "pnl", "pnl_pct", "reason", "bars_held",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for t in trades:
            writer.writerow(t)

    print(f"  Resultater gemt til {path}")
    return path
