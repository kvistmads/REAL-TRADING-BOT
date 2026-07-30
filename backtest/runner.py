from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import ccxt
import pandas as pd
import yaml
import yfinance as yf

# Tillad kørsel som `python backtest/runner.py` (tilføj projektrod til sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import metrics as metrics_mod  # noqa: E402
from backtest import report  # noqa: E402
from data.fetcher import YFINANCE_SYMBOL_MAP as YFINANCE_MAP  # noqa: E402
from data.indicators import add_all  # noqa: E402
from strategies.base import BaseStrategy  # noqa: E402
from strategies.registry import load_strategies  # noqa: E402

logger = logging.getLogger(__name__)

# Symbol-mappingen (forex/gold → CME-futures) deles med live-fetcheren, så de to
# datakilder ikke kan divergere — se data/fetcher.YFINANCE_SYMBOL_MAP for hvorfor
# det er futures og ikke spot. Symboler der IKKE står der hentes fra Binance.


# ---------------------------------------------------------------------------
# Datakilder
# ---------------------------------------------------------------------------

_TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def fetch_crypto_ohlcv(symbol: str, timeframe: str, limit: int = 4400) -> pd.DataFrame:
    """
    Crypto-OHLCV fra Binance via ccxt. Binance klines returnerer max 1000 barer
    pr. kald, så vi paginerer bagud (~2 år ved 4h = 4400 barer) for at matche
    yfinance-vinduet. Returnerer df med 'time'-kolonne.
    """
    exchange = ccxt.binance({"enableRateLimit": True})
    tf_ms = _TF_MS.get(timeframe, 14_400_000)
    since = exchange.milliseconds() - limit * tf_ms
    all_bars: list[list] = []
    while len(all_bars) < limit:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        all_bars.extend(batch)
        since = batch[-1][0] + tf_ms
        if len(batch) < 1000:
            break
    df = pd.DataFrame(all_bars, columns=["time", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="time")
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.reset_index(drop=True)


def fetch_forex_ohlcv(symbol: str) -> pd.DataFrame:
    """
    Forex/gold-OHLCV via yfinance. Henter 1h og resampler til 4h.
    yfinance leverer MultiIndex-kolonner (OHLCV × ticker) — de flades ud først.
    Returnerer df med 'time'-kolonne, samme format som crypto-pathen.
    """
    ticker = YFINANCE_MAP[symbol]
    raw = yf.download(ticker, period="2y", interval="1h",
                      auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    # Flad MultiIndex-kolonner (yfinance >= 0.2) til enkelt niveau.
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw.resample("4h").agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum",
    }).dropna()
    df.columns = [c.lower() for c in df.columns]
    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: "time"})
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    return df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def fetch_data(symbol: str, timeframe: str = "4h") -> pd.DataFrame:
    """Router: forex/gold → yfinance, ellers crypto → Binance."""
    if symbol in YFINANCE_MAP:
        return fetch_forex_ohlcv(symbol)
    return fetch_crypto_ohlcv(symbol, timeframe)


# ---------------------------------------------------------------------------
# Trade-simulering (uændret kontrakt: df med 'time'-kolonne)
# ---------------------------------------------------------------------------

def _resolve_sl_tp(signal, entry_price: float, config: dict) -> tuple[float, float]:
    if signal.sl_price is not None and signal.tp_price is not None:
        return signal.sl_price, signal.tp_price
    asset_class = BaseStrategy.get_asset_class(signal.symbol)
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_one(strategy, symbol: str, config: dict, df: pd.DataFrame) -> tuple[dict, list[dict]]:
    """Kør backtest på allerede-hentet data, returnér (metrics, trades)."""
    if df is None or df.empty or len(df) < 200:
        return metrics_mod.compute([]), []
    trades = run_backtest(df.copy(), strategy, symbol, config)
    return metrics_mod.compute(trades), trades


def _to_db_record(strategy_id: str, symbol: str, m: dict, period: tuple, source_file: str) -> dict:
    """Byg et BacktestResult-kwargs-dict fra en metrics-dict.

    Normaliserer til research-lagets forventede enheder: win_rate/max_drawdown som
    fraktioner (0.0-1.0), total_return_pct i procent. profit_factor=inf → None.
    """
    pf = m.get("profit_factor", 0.0)
    start, end = period if period else (None, None)
    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "period_start": start,
        "period_end": end,
        "total_trades": int(m.get("total_trades", 0)),
        "win_rate": round(m.get("win_rate", 0.0) / 100, 4),
        "profit_factor": None if pf == float("inf") else round(float(pf), 4),
        "sharpe": round(float(m.get("sharpe", 0.0)), 4),
        "max_drawdown": round(abs(m.get("max_drawdown_pct", 0.0)) / 100, 4),
        "total_return_pct": round(float(m.get("total_pnl_pct", 0.0)), 4),
        "source_file": source_file,
    }


def save_results_to_db(records: list[dict], session_factory=None) -> int:
    """Gem backtest-records til BacktestResult-tabellen. Returnér antal gemte rækker.

    Best-effort: DB-fejl må aldrig vælte en suite-kørsel (logges og springes over).
    Importeres lazily så backtest-runneren ikke trækker DB-laget ind ved simple kørsler.
    session_factory kan injiceres (tests); ellers bruges den synkrone produktions-session.
    """
    if not records:
        return 0
    try:
        from core.database import BacktestResult

        if session_factory is None:
            from core.database import init_sync_db, sync_session_maker

            init_sync_db()
            session_factory = sync_session_maker
        with session_factory() as session:
            for r in records:
                session.add(BacktestResult(**r))
            session.commit()
        return len(records)
    except Exception as e:  # pragma: no cover - DB-miljøafhængigt
        logger.warning("Kunne ikke gemme backtest-resultater til DB: %s", e)
        return 0


def _run_single(args, config) -> int:
    registry = load_strategies()
    try:
        strategy = registry.get(args.strategy)
    except KeyError:
        print(f"Ukendt strategi: {args.strategy}. Tilgængelige: "
              f"{[s.name for s in registry.all()]}")
        return 1

    print(f"Henter data for {args.symbol} ({args.timeframe})...")
    df = fetch_data(args.symbol, args.timeframe)
    if df is None or df.empty:
        print(f"Ingen data hentet for {args.symbol} {args.timeframe}")
        return 1

    trades = run_backtest(df, strategy, args.symbol, config)
    result = metrics_mod.compute(trades)
    meta = {
        "strategy": args.strategy, "symbol": args.symbol, "timeframe": args.timeframe,
        "from": str(df["time"].iloc[0].date()),
        "to": str(df["time"].iloc[-1].date()),
    }
    report.print_metrics(result, meta)
    if trades:
        report.save_csv(trades, meta)
    return 0


THRESHOLDS = {
    "win_rate": 50.0, "profit_factor": 1.3,
    "max_drawdown_pct": -20.0, "sharpe": 0.8, "total_trades": 20,
}


def _passes(m: dict) -> bool:
    return (
        m["total_trades"] > THRESHOLDS["total_trades"]
        and m["win_rate"] > THRESHOLDS["win_rate"]
        and (m["profit_factor"] == float("inf") or m["profit_factor"] > THRESHOLDS["profit_factor"])
        and m["max_drawdown_pct"] > THRESHOLDS["max_drawdown_pct"]
        and m["sharpe"] > THRESHOLDS["sharpe"]
    )


def _run_all(config, timeframe: str) -> int:
    registry = load_strategies()
    strategies = registry.get_enabled(config["strategies"]["enabled"])
    symbols = config["symbols"]

    # Hent hvert symbol én gang og genbrug på tværs af strategier.
    data: dict[str, pd.DataFrame] = {}
    periods: dict[str, tuple] = {}
    for symbol in symbols:
        print(f"  Henter {symbol:10s} ...", end="", flush=True)
        try:
            df = fetch_data(symbol, timeframe)
            data[symbol] = df
            if not df.empty:
                periods[symbol] = (
                    df["time"].iloc[0].to_pydatetime(),
                    df["time"].iloc[-1].to_pydatetime(),
                )
            print(f" {len(df)} barer"
                  + (f"  ({df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()})"
                     if not df.empty else ""))
        except Exception as e:
            data[symbol] = None
            print(f" FEJL: {type(e).__name__}: {str(e)[:80]}")

    source_file = f"suite_{date.today().isoformat()}.csv"
    rows: list[dict] = []
    db_records: list[dict] = []
    all_trades: list[dict] = []
    for strategy in strategies:
        for symbol in symbols:
            print(f"  {strategy.name:22s} × {symbol:10s} ...", end="", flush=True)
            try:
                m, trades = _run_one(strategy, symbol, config, data.get(symbol))
            except Exception as e:  # data-fejl pr. symbol må ikke stoppe suiten
                print(f" FEJL: {type(e).__name__}: {str(e)[:80]}")
                rows.append({"strategy": strategy.name, "symbol": symbol,
                             "trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                             "max_dd": 0.0, "sharpe": 0.0, "total_pnl_pct": 0.0,
                             "wins": 0, "losses": 0, "avg_win_pct": 0.0,
                             "avg_loss_pct": 0.0, "avg_bars_held": 0.0,
                             "pass": False})
                continue
            pf = m["profit_factor"]
            print(f" {m['total_trades']:>4d} trades | WR {m['win_rate']:>5.1f}% | "
                  f"PF {'inf' if pf == float('inf') else f'{pf:.2f}'}")
            avg_bars = (
                sum(t["bars_held"] for t in trades) / len(trades) if trades else 0.0
            )
            rows.append({
                "strategy": strategy.name, "symbol": symbol,
                "trades": m["total_trades"], "win_rate": m["win_rate"],
                "profit_factor": pf, "max_dd": m["max_drawdown_pct"],
                "sharpe": m["sharpe"], "total_pnl_pct": m["total_pnl_pct"],
                "wins": m["wins"], "losses": m["losses"],
                "avg_win_pct": m["avg_win_pct"], "avg_loss_pct": m["avg_loss_pct"],
                "avg_bars_held": round(avg_bars, 1),
                "pass": _passes(m),
            })
            # Kun symboler med faktiske data (og dermed en kendt periode) importeres til DB.
            if m["total_trades"] > 0 and symbol in periods:
                db_records.append(
                    _to_db_record(strategy.name, symbol, m, periods[symbol], source_file)
                )
            for t in trades:
                t["strategy_id"] = strategy.name
                all_trades.append(t)

    _print_suite_table(rows)
    _save_suite_csv(rows)
    _save_trades_csv(all_trades)
    # Rapporten er pynt oven på resultaterne — en fejl her må ikke koste hele
    # suitens DB-import (samme best-effort-kontrakt som save_results_to_db).
    try:
        report.generate_html_report(rows, all_trades, periods)
    except Exception as e:
        logger.warning("Kunne ikke generere HTML-rapport: %s", e)
        print(f"  ADVARSEL: HTML-rapport fejlede: {type(e).__name__}: {str(e)[:80]}")
    saved = save_results_to_db(db_records)
    if saved:
        print(f"  {saved} backtest-resultater importeret til DB (backtest_results-tabellen)")
    return 0


def _print_suite_table(rows: list[dict]) -> None:
    print()
    print("=" * 132)
    print(f"  {'Strategi':22s} {'Symbol':10s} {'Trades':>7s} {'Win%':>7s} "
          f"{'PF':>7s} {'MaxDD%':>8s} {'Sharpe':>7s} {'PnL%':>9s} "
          f"{'W':>5s} {'L':>5s} {'AvgW%':>7s} {'AvgL%':>7s} {'Bars':>6s}  {'OK':>3s}")
    print("-" * 132)
    for r in rows:
        pf = r["profit_factor"]
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        print(f"  {r['strategy']:22s} {r['symbol']:10s} {r['trades']:>7d} "
              f"{r['win_rate']:>7.1f} {pf_s:>7s} {r['max_dd']:>8.2f} "
              f"{r['sharpe']:>7.2f} {r['total_pnl_pct']:>9.2f} "
              f"{r['wins']:>5d} {r['losses']:>5d} {r['avg_win_pct']:>7.2f} "
              f"{r['avg_loss_pct']:>7.2f} {r['avg_bars_held']:>6.1f}  "
              f"{'✅' if r['pass'] else '❌':>3s}")
    print("=" * 132)
    n_pass = sum(1 for r in rows if r["pass"])
    print(f"  Godkendt til paper mode (alle tærskler): {n_pass}/{len(rows)}")
    print("=" * 132)


def _save_suite_csv(rows: list[dict]) -> Path:
    report.RESULTS_DIR.mkdir(exist_ok=True)
    path = report.RESULTS_DIR / f"suite_{date.today().isoformat()}.csv"
    fields = ["strategy", "symbol", "trades", "win_rate", "profit_factor",
              "max_dd", "sharpe", "total_pnl_pct", "wins", "losses",
              "avg_win_pct", "avg_loss_pct", "avg_bars_held", "pass"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            row = dict(r)
            if row["profit_factor"] == float("inf"):
                row["profit_factor"] = "inf"
            writer.writerow(row)
    print(f"  Suite-resultater gemt til {path}")
    return path


def _save_trades_csv(all_trades: list[dict]) -> Path | None:
    """Gem alle suitens trades samlet til én CSV (én række pr. trade).

    Modsat report.save_csv (én fil pr. strategi×symbol) er det her hele suiten i
    én fil, så per-trade data kan analyseres på tværs uden at samle filer først.
    """
    if not all_trades:
        return None
    report.RESULTS_DIR.mkdir(exist_ok=True)
    path = report.RESULTS_DIR / f"trades_{date.today().isoformat()}.csv"
    fields = ["strategy_id", "symbol", "side", "entry_time", "exit_time",
              "entry_price", "exit_price", "pnl", "pnl_pct", "reason", "bars_held"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_trades)
    print(f"  {len(all_trades)} trades gemt til {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backtest composite-strategier mod Binance (crypto) / yfinance (forex/gold)")
    parser.add_argument("--strategy", help="Strateginavn, fx trend_momentum")
    parser.add_argument("--symbol", help="ccxt-symbol, fx BTC/USDT eller EUR/USD")
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--all", action="store_true",
                        help="Kør alle enabled strategier × alle symboler")
    args = parser.parse_args()

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    if args.all:
        return _run_all(config, args.timeframe)

    if not args.strategy or not args.symbol:
        parser.error("Angiv enten --all eller både --strategy og --symbol")
    return _run_single(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
