from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

# Tillad kørsel som `python backtest/runner.py` (tilføj projektrod til sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import metrics as metrics_mod  # noqa: E402
from backtest import report  # noqa: E402
from data.indicators import add_all  # noqa: E402
from data.mt5_fetcher import MT5Fetcher  # noqa: E402
from strategies.base import BaseStrategy  # noqa: E402
from strategies.registry import load_strategies  # noqa: E402

# MT5 bruger ccxt-formatet til asset-class-opslag; runner accepterer begge stavemåder.
_MT5_TO_CCXT = {v: k for k, v in MT5Fetcher.FOREX_SYMBOLS.items()}


def _resolve_sl_tp(signal, entry_price: float, config: dict) -> tuple[float, float]:
    if signal.sl_price is not None and signal.tp_price is not None:
        return signal.sl_price, signal.tp_price
    asset_class = BaseStrategy.get_asset_class(_MT5_TO_CCXT.get(signal.symbol, signal.symbol))
    defaults = config["risk_defaults"][asset_class]
    sl_pct = defaults["sl_pct"] / 100
    tp_pct = defaults["tp_pct"] / 100
    if signal.side == "long":
        return entry_price * (1 - sl_pct), entry_price * (1 + tp_pct)
    return entry_price * (1 + sl_pct), entry_price * (1 - tp_pct)


def simulate_trade(signal, future_df: pd.DataFrame, config: dict) -> dict:
    """
    Simulér én trade fremad i tiden fra signalet.
    future_df: barer FRA og med udførelsesbaren (fill sker på første bars open).
    Lukker ved SL, TP eller sidste bar. SL tjekkes før TP samme bar (konservativt).
    """
    entry_price = float(future_df.iloc[0]["open"])
    sl, tp = _resolve_sl_tp(signal, entry_price, config)
    stake = config["trading"]["stake_amount"]

    exit_price = float(future_df.iloc[-1]["close"])
    reason = "end_of_data"
    bars_held = len(future_df) - 1
    exit_time = future_df.iloc[-1].get("time")

    for offset in range(1, len(future_df)):
        bar = future_df.iloc[offset]
        high, low = float(bar["high"]), float(bar["low"])
        if signal.side == "long":
            if low <= sl:
                exit_price, reason = sl, "stop_loss"
            elif high >= tp:
                exit_price, reason = tp, "take_profit"
        else:
            if high >= sl:
                exit_price, reason = sl, "stop_loss"
            elif low <= tp:
                exit_price, reason = tp, "take_profit"
        if reason != "end_of_data":
            bars_held = offset
            exit_time = bar.get("time")
            break

    if signal.side == "long":
        pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:
        pnl_pct = (entry_price - exit_price) / entry_price * 100
    pnl = pnl_pct / 100 * stake

    return {
        "symbol": signal.symbol,
        "side": signal.side,
        "strategy_id": signal.strategy_id,
        "entry_time": future_df.iloc[0].get("time"),
        "exit_time": exit_time,
        "entry_price": round(entry_price, 6),
        "exit_price": round(exit_price, 6),
        "pnl": round(pnl, 4),
        "pnl_pct": round(pnl_pct, 4),
        "reason": reason,
        "bars_held": bars_held,
    }


def run_backtest(df: pd.DataFrame, strategy, symbol: str, config: dict,
                 warmup: int = 200) -> list[dict]:
    """Rullende vindue over df; kør strategien og simulér hver trade fremad."""
    df = add_all(df)
    trades: list[dict] = []
    i = warmup
    while i < len(df):
        window = df.iloc[:i].copy()
        signal = strategy.generate_signal(window, symbol)
        if signal is not None and signal.confidence >= strategy.min_confidence:
            future = df.iloc[i:].reset_index(drop=True)
            if len(future) < 2:
                break
            trade = simulate_trade(signal, future, config)
            trades.append(trade)
            # Spring frem til trade er lukket for at undgå overlappende positioner.
            i += max(trade["bars_held"], 1)
        else:
            i += 1
    return trades


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest en strategi mod historisk MT5-data")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--symbol", required=True, help="MT5-symbol, fx EURUSD")
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--from", dest="date_from", default=None)
    parser.add_argument("--to", dest="date_to", default=None)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    registry = load_strategies()
    try:
        strategy = registry.get(args.strategy)
    except KeyError:
        print(f"Ukendt strategi: {args.strategy}. Tilgængelige: "
              f"{[s.name for s in registry.all()]}")
        return 1

    fetcher = MT5Fetcher()
    if not fetcher.initialize():
        print("MT5-terminal er ikke tilgængelig — backtest kræver at MT5 kører lokalt "
              "(Windows). Kan ikke hente historik.")
        return 1

    df = fetcher.get_ohlcv(args.symbol, args.timeframe, limit=args.limit)
    fetcher.shutdown()
    if df is None or df.empty:
        print(f"Ingen data hentet for {args.symbol} {args.timeframe}")
        return 1

    if args.date_from:
        df = df[df["time"] >= pd.to_datetime(args.date_from)]
    if args.date_to:
        df = df[df["time"] <= pd.to_datetime(args.date_to)]
    df = df.reset_index(drop=True)

    trades = run_backtest(df, strategy, args.symbol, config)
    result = metrics_mod.compute(trades)
    meta = {
        "strategy": args.strategy, "symbol": args.symbol, "timeframe": args.timeframe,
        "from": args.date_from or str(df["time"].iloc[0].date()),
        "to": args.date_to or str(df["time"].iloc[-1].date()),
    }
    report.print_metrics(result, meta)
    if trades:
        report.save_csv(trades, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
