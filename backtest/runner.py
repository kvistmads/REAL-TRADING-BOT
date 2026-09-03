from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd
import yaml
import yfinance as yf

# Tillad kørsel som `python backtest/runner.py` (tilføj projektrod til sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import costs as costs_mod  # noqa: E402
from backtest import metrics as metrics_mod  # noqa: E402
from backtest import report  # noqa: E402
from backtest import rnorm  # noqa: E402
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

def _resolve_sl_tp(signal, entry_price: float, config: dict,
                   atr: float | None = None) -> tuple[float, float]:
    """SL/TP for en trade. Chart-baserede niveauer fra signalet vinder altid.

    Ellers volatilitetstilpasset: SL-afstand = atr_sl_multiplier × ATR(14) og
    TP-afstand = tp_rr_ratio × SL-afstand (default 2.0 → uændret 2:1 R:R).
    Uden brugbar ATR bruges de faste sl_pct/tp_pct fra config som fallback.
    """
    if signal.sl_price is not None and signal.tp_price is not None:
        return signal.sl_price, signal.tp_price

    asset_class = BaseStrategy.get_asset_class(signal.symbol)
    defaults = config["risk_defaults"][asset_class]

    if atr is not None and atr == atr and atr > 0:  # atr == atr filtrerer NaN
        sl_dist = defaults.get("atr_sl_multiplier", 2.0) * atr
        tp_dist = defaults.get("tp_rr_ratio", 2.0) * sl_dist
    else:
        sl_dist = entry_price * defaults["sl_pct"] / 100
        tp_dist = entry_price * defaults["tp_pct"] / 100

    if signal.side == "long":
        return entry_price - sl_dist, entry_price + tp_dist
    return entry_price + sl_dist, entry_price - tp_dist


def _breakeven_trigger(side: str, entry_price: float, tp: float, pct: float) -> float:
    """Prisen hvor SL flyttes til entry: `pct` af vejen fra entry mod TP."""
    if side == "long":
        return entry_price + pct * (tp - entry_price)
    return entry_price - pct * (entry_price - tp)


def _entry_atr(future_df: pd.DataFrame) -> float | None:
    """ATR(14) på udførelsesbaren. None hvis kolonnen mangler eller er NaN."""
    if "atr_14" not in future_df.columns:
        return None
    value = float(future_df["atr_14"].iloc[0])
    return None if value != value else value  # NaN → None


def _flip_breach_offset(signal, future_df: pd.DataFrame, horizon: int) -> int | None:
    """Første bar-offset (>=1) hvor en BODY CLOSE bryder signalets flip level.

    Body close, ikke high/low: et wick igennem er et sweep, ikke en invalidering
    (samme skelnen som i ``find_sr_levels`` og ``position_tracker.is_flip_breached``).

    Scannet går til `horizon` barer uanset hvornår handlen faktisk lukkede, så vi kan
    skelne "brudt før exit" fra "brudt bagefter" — dvs. om tesen var forkert eller
    blot timingen. Horisonten er handlens maksimale levetid (time-stoppet), så et
    "bagefter" altid er inden for det vindue handlen kunne have levet i.

    None = intet flip level, eller aldrig brudt inden for horisonten.
    """
    flip_level = (signal.metadata or {}).get("flip_level")
    if flip_level is None or horizon < 1:
        return None
    closes = future_df["close"].to_numpy(dtype=float)[1:horizon + 1]
    if closes.size == 0:
        return None
    breached = closes < flip_level if signal.side == "long" else closes > flip_level
    if not breached.any():
        return None
    return int(np.argmax(breached)) + 1


def simulate_trade(signal, future_df: pd.DataFrame, config: dict,
                   flip_exit: bool = False) -> dict:
    """
    Simulér én trade fremad i tiden fra signalet.
    future_df: barer FRA og med udførelsesbaren (fill sker på første bars open).
    Lukker ved SL, TP eller sidste bar. SL tjekkes før TP samme bar (konservativt).

    flip_exit=False (default, kørsel A1) = live-adfærden: flip level registreres kun
    som observation. flip_exit=True (kørsel A2) lukker desuden handlen på første body
    close gennem niveauet — en MÅLING af hvad et flip-exit ville have kostet/givet,
    ikke en anbefaling.
    """
    entry_price = float(future_df.iloc[0]["open"])
    atr = _entry_atr(future_df)
    sl, tp = _resolve_sl_tp(signal, entry_price, config, atr=atr)
    stake = config["trading"]["stake_amount"]

    # R låses HER, før breakeven kan flytte stoppet. Flyttede vi R med stoppet,
    # ville en dårlig handel kunne se god ud fordi risikoen blev omskrevet undervejs.
    # atr_status skelner nan/zero/missing, fordi zero typisk betyder flade barer
    # (High == Low) — et datakvalitetsproblem, ikke et R-regnskabsspørgsmål.
    _atr_value, _atr_state = rnorm.atr_status(future_df)
    risk = rnorm.risk_fields(entry_price, sl, signal, _atr_value, _atr_state)

    trigger_pct = config.get("trading", {}).get("breakeven_trigger_pct", 0.5)
    breakeven_trigger = _breakeven_trigger(signal.side, entry_price, tp, trigger_pct)
    breakeven_activated = False
    max_bars = config.get("trading", {}).get("max_bars_held", 24)

    sl_initial = sl
    flip_level = (signal.metadata or {}).get("flip_level")
    flip_horizon = max_bars if max_bars else len(future_df) - 1
    flip_offset = _flip_breach_offset(signal, future_df, flip_horizon)

    exit_price = float(future_df.iloc[-1]["close"])
    reason = "end_of_data"
    bars_held = len(future_df) - 1
    exit_time = future_df.iloc[-1].get("time")

    for offset in range(1, len(future_df)):
        bar = future_df.iloc[offset]
        high, low = float(bar["high"]), float(bar["low"])

        # Breakeven: når prisen har bevæget sig trigger_pct af vejen mod TP
        # flyttes SL til entry. Tjekkes før exit-tjekket på samme bar, så en bar
        # der både trigger og retracerer lukkes i 0 frem for på det gamle SL.
        if not breakeven_activated:
            if (signal.side == "long" and high >= breakeven_trigger) or (
                signal.side == "short" and low <= breakeven_trigger
            ):
                sl = entry_price
                breakeven_activated = True

        if signal.side == "long":
            if low <= sl:
                exit_price = sl
                reason = "breakeven" if breakeven_activated else "stop_loss"
            elif high >= tp:
                exit_price, reason = tp, "take_profit"
        else:
            if high >= sl:
                exit_price = sl
                reason = "breakeven" if breakeven_activated else "stop_loss"
            elif low <= tp:
                exit_price, reason = tp, "take_profit"
        if reason != "end_of_data":
            bars_held = offset
            exit_time = bar.get("time")
            break

        # Flip-exit (kun A2): efter SL/TP fordi de rammes INDE i baren, mens flip
        # level først er brudt når baren lukker. Før time-stoppet, fordi "tesen er
        # modbevist" er en mere specifik grund end "tiden løb ud".
        if flip_exit and flip_offset is not None and offset >= flip_offset:
            exit_price = float(bar["close"])
            reason = "flip_level"
            bars_held = offset
            exit_time = bar.get("time")
            break

        # Time-stop: tjekkes EFTER SL/TP, så et niveau der rammes på samme bar
        # vinder. En momentum-strategi skal ikke holde en position i månedsvis.
        if max_bars and offset >= max_bars:
            exit_price = float(bar["close"])
            reason = "time_stop"
            bars_held = offset
            exit_time = bar.get("time")
            break

    if signal.side == "long":
        pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:
        pnl_pct = (entry_price - exit_price) / entry_price * 100
    pnl = pnl_pct / 100 * stake

    if flip_level is None:
        flip_timing = "no_flip_level"
    elif flip_offset is None:
        flip_timing = "never"
    elif flip_offset <= bars_held:
        flip_timing = "before_exit"
    else:
        flip_timing = "after_exit"

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
        "breakeven_activated": breakeven_activated,
        # Confidence gemmes pr. signal, ikke kun aggregeret: uden den kan spørgsmålet
        # "diskriminerer scoren?" ikke stilles bagefter (PRD del B).
        "confidence": round(float(signal.confidence), 6),
        "flip_level": None if flip_level is None else round(float(flip_level), 6),
        "flip_breached_bar": flip_offset,
        "flip_breached_before_exit": None if flip_level is None else flip_timing == "before_exit",
        "flip_timing": flip_timing,
        "signal_metadata": dict(signal.metadata or {}),
        # R-normalisering: risikoen ved INDGANG. r_multiple beregnes efter
        # omkostningsmodellen (add_r_multiples), så brutto og netto deler nævner.
        **risk,
        "initial_sl": round(float(sl_initial), 8),
    }


def run_backtest(df: pd.DataFrame, strategy, symbol: str, config: dict,
                 warmup: int = 200, flip_exit: bool = False) -> list[dict]:
    """Rullende vindue over df; kør strategien og simulér hver trade fremad.

    **Backtesten anvender ALDRIG confidence-gaten.** Strategien kaldes med
    ``min_confidence: 0.0`` og hvert genereret signal simuleres med de eksisterende
    exit-regler. Det er en permanent adskillelse af to formål, ikke et forsknings-flag:

        Backtesten viser alt. Gaten hører til i live.

    Et filter i backtesten skjuler netop de handler der lærer os mest, og gør det
    umuligt at måle OM filteret virker: måler man kun over tærsklen, tester man
    scoren dér hvor den allerede har filtreret — altså hvor den betyder mindst.
    Kapitalen beskyttes i live, hvor ``strategies.min_confidence`` er uændret; hver
    række markeres med ``would_pass_production`` så det udsnit kan isoleres bagefter.

    Overlappende positioner undgås stadig (spring frem til trade er lukket) — det er
    backtestens porteføljekontrakt og har intet med confidence at gøre.
    """
    df = add_all(df)
    trades: list[dict] = []
    i = warmup
    # Live-tærsklen bruges KUN som mærkat, aldrig som filter her.
    production_min_conf = config.get("strategies", {}).get(
        "min_confidence", strategy.min_confidence
    )
    while i < len(df):
        window = df.iloc[:i].copy()
        signal = strategy.generate_signal(window, symbol, {"min_confidence": 0.0})
        if signal is not None:
            future = df.iloc[i:].reset_index(drop=True)
            if len(future) < 2:
                break
            trade = simulate_trade(signal, future, config, flip_exit=flip_exit)
            trade["would_pass_production"] = signal.confidence >= production_min_conf
            trade["production_min_confidence"] = production_min_conf
            trades.append(trade)
            # Spring frem til trade er lukket for at undgå overlappende positioner.
            i += max(trade["bars_held"], 1)
        else:
            i += 1
    # Netto-felter oven på brutto — brutto røres ikke, begge skal kunne vises.
    costs_mod.apply_costs_to_trades(trades, config, strategy.name, symbol)
    # R-multipler til sidst: de har brug for både brutto og netto.
    return rnorm.add_r_multiples(trades)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_one(strategy, symbol: str, config: dict, df: pd.DataFrame,
             flip_exit: bool = False) -> tuple[dict, list[dict]]:
    """Kør backtest på allerede-hentet data, returnér (metrics, trades).

    ``metrics`` er brutto-opgørelsen (uændret kontrakt for eksisterende kaldere) med
    netto-opgørelsen vedhæftet under nøglen ``"net_metrics"``, så begge kan vises.
    """
    if df is None or df.empty or len(df) < 200:
        return metrics_mod.compute([]), []
    trades = run_backtest(df.copy(), strategy, symbol, config, flip_exit=flip_exit)
    both = metrics_mod.compute_both(trades)
    m = both["gross"]
    m["net_metrics"] = both["net"]
    return m, trades


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
        # Baseline'en skal matche de metrics den ledsager → afsluttede trades.
        "total_trades": int(m.get("closed_trades", m.get("total_trades", 0))),
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

    trades = run_backtest(df, strategy, args.symbol, config, flip_exit=args.flip_exit)
    both = metrics_mod.compute_both(trades)
    result = both["gross"]
    meta = {
        "strategy": args.strategy, "symbol": args.symbol, "timeframe": args.timeframe,
        "from": str(df["time"].iloc[0].date()),
        "to": str(df["time"].iloc[-1].date()),
    }
    if args.flip_exit:
        meta["run"] = "A2-flip-exit"
    print(_flip_summary(trades))
    report.print_metrics(result, meta)
    if trades:
        report.save_csv(trades, meta)

    # Enhver backtest afsluttes med den kompakte tabel (PRD del 3) — også
    # enkeltkørsler, så formatet er det samme uanset hvordan man kom hertil.
    print()
    print(report.format_session_table(
        [report.session_row(args.symbol, both)],
        strategy.name,
        f"{meta['from'][:7]}→{meta['to'][:7]}",
        "A2 flip-exit" if args.flip_exit else "A1 baseline",
    ))
    return 0


THRESHOLDS = {
    "win_rate": 50.0, "profit_factor": 1.3,
    "max_drawdown_pct": -20.0, "sharpe": 0.8, "total_trades": 20,
}


def _passes(m: dict) -> bool:
    # Sample-kravet gælder rigtige exits: 30 trades hvoraf 25 stadig var åbne da
    # data slap op er ikke 30 udfald at bedømme en strategi på.
    return (
        m.get("closed_trades", m["total_trades"]) > THRESHOLDS["total_trades"]
        and m["win_rate"] > THRESHOLDS["win_rate"]
        and (m["profit_factor"] == float("inf") or m["profit_factor"] > THRESHOLDS["profit_factor"])
        and m["max_drawdown_pct"] > THRESHOLDS["max_drawdown_pct"]
        and m["sharpe"] > THRESHOLDS["sharpe"]
    )


def _flip_summary(trades: list[dict]) -> str:
    """Fordelingen af HVORNÅR flip level brydes — tallet der skiller tese fra timing.

    'before_exit' = tesen var modbevist mens vi stadig sad i handlen; 'after_exit' =
    den holdt så længe vi var med (timing/stop-problem); 'never' = den holdt hele
    handlens mulige levetid; 'no_flip_level' = strategien kunne ikke angive et niveau.
    """
    if not trades:
        return "  Flip level: ingen trades"
    order = ["before_exit", "after_exit", "never", "no_flip_level"]
    counts = {k: 0 for k in order}
    for t in trades:
        counts[t.get("flip_timing", "no_flip_level")] += 1
    n = len(trades)
    parts = [f"{k}={counts[k]} ({counts[k] / n:.0%})" for k in order]
    return f"  Flip level ({n} trades): " + "  ".join(parts)


def _run_all(config, timeframe: str, flip_exit: bool = False) -> int:
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

    suffix = "_flipexit" if flip_exit else ""
    source_file = f"suite_{date.today().isoformat()}{suffix}.csv"
    rows: list[dict] = []
    session_rows: dict[str, list[dict]] = {}
    db_records: list[dict] = []
    all_trades: list[dict] = []
    for strategy in strategies:
        for symbol in symbols:
            print(f"  {strategy.name:22s} × {symbol:10s} ...", end="", flush=True)
            try:
                m, trades = _run_one(strategy, symbol, config, data.get(symbol),
                                     flip_exit=flip_exit)
            except Exception as e:  # data-fejl pr. symbol må ikke stoppe suiten
                print(f" FEJL: {type(e).__name__}: {str(e)[:80]}")
                rows.append({"strategy": strategy.name, "symbol": symbol,
                             "trades": 0, "open_at_end": 0,
                             "win_rate": 0.0, "profit_factor": 0.0,
                             "max_dd": 0.0, "sharpe": 0.0, "total_pnl_pct": 0.0,
                             "wins": 0, "losses": 0, "avg_win_pct": 0.0,
                             "avg_loss_pct": 0.0, "avg_bars_held": 0.0,
                             "pass": False})
                continue
            pf = m["profit_factor"]
            print(f" {m['closed_trades']:>4d} trades | WR {m['win_rate']:>5.1f}% | "
                  f"PF {'inf' if pf == float('inf') else f'{pf:.2f}'}"
                  + (f" | {m['open_at_end_count']} åbne v. data-slut"
                     if m["open_at_end_count"] else ""))
            avg_bars = (
                sum(t["bars_held"] for t in trades) / len(trades) if trades else 0.0
            )
            net = m.get("net_metrics", m)
            rows.append({
                "strategy": strategy.name, "symbol": symbol,
                "trades": m["closed_trades"], "win_rate": m["win_rate"],
                "open_at_end": m["open_at_end_count"],
                "profit_factor": pf, "max_dd": m["max_drawdown_pct"],
                "sharpe": m["sharpe"], "total_pnl_pct": m["total_pnl_pct"],
                "wins": m["wins"], "losses": m["losses"],
                "avg_win_pct": m["avg_win_pct"], "avg_loss_pct": m["avg_loss_pct"],
                "avg_bars_held": round(avg_bars, 1),
                # Netto side om side med brutto — aldrig i stedet for.
                "win_rate_net": net["win_rate"],
                "profit_factor_net": net["profit_factor"],
                "total_pnl_pct_net": net["total_pnl_pct"],
                "max_dd_net": net["max_drawdown_pct"],
                "sharpe_net": net["sharpe"],
                "total_cost_pct": net["total_cost_pct"],
                "gross_profit_pct": m["gross_profit_pct"],
                "gross_loss_pct": m["gross_loss_pct"],
                "gross_profit_pct_net": net["gross_profit_pct"],
                "gross_loss_pct_net": net["gross_loss_pct"],
                # Paper-tærsklerne bedømmes på NETTO: en strategi der kun består
                # brutto består ikke i virkeligheden.
                "pass": _passes(net),
                "pass_gross": _passes(m),
            })
            session_rows.setdefault(strategy.name, []).append(
                report.session_row(symbol, {"gross": m, "net": net})
            )
            # Kun symboler med faktiske data (og dermed en kendt periode) importeres til DB.
            if m["closed_trades"] > 0 and symbol in periods:
                db_records.append(
                    _to_db_record(strategy.name, symbol, m, periods[symbol], source_file)
                )
            for t in trades:
                t["strategy_id"] = strategy.name
                all_trades.append(t)

    _print_suite_table(rows)
    _print_session_tables(session_rows, rows, periods, flip_exit)
    print(_flip_summary(all_trades))
    _save_suite_csv(rows, suffix)
    _save_trades_csv(all_trades, suffix)
    # Rapporten er pynt oven på resultaterne — en fejl her må ikke koste hele
    # suitens DB-import (samme best-effort-kontrakt som save_results_to_db).
    try:
        report.generate_html_report(rows, all_trades, periods)
    except Exception as e:
        logger.warning("Kunne ikke generere HTML-rapport: %s", e)
        print(f"  ADVARSEL: HTML-rapport fejlede: {type(e).__name__}: {str(e)[:80]}")
    if flip_exit:
        # A2 er en MÅLING af et hypotetisk exit, ikke botten som den kører.
        # Research-lagets baseline skal blive ved med at afspejle live-adfærden.
        print("  (flip-exit-kørsel — resultater importeres IKKE til DB som baseline)")
    else:
        saved = save_results_to_db(db_records)
        if saved:
            print(f"  {saved} backtest-resultater importeret til DB (backtest_results-tabellen)")
    return 0


def _period_label(periods: dict) -> str:
    """Kompakt periodetekst på tværs af symboler, fx "2024-08→2026-09"."""
    if not periods:
        return "ukendt periode"
    starts = [p[0] for p in periods.values()]
    ends = [p[1] for p in periods.values()]
    return f"{min(starts):%Y-%m}→{max(ends):%Y-%m}"


def _total_row(strategy_rows: list[dict], suite_rows: list[dict], strategy: str) -> dict:
    """TOTAL-rækken: vægtede totaler på tværs af symboler for én strategi.

    Win rate vægtes med antal handler (ikke et gennemsnit af procenter — et symbol
    med 30 handler skal ikke tælle lige så meget som ét med 100), og profit factor
    genberegnes fra summen af gevinster og tab frem for at midle PF'er.
    """
    n = sum(r["n"] for r in strategy_rows)
    if n == 0:
        return {"symbol": "TOTAL", "n": 0, "win_rate": 0.0, "win_rate_net": 0.0,
                "profit_factor": 0.0, "profit_factor_net": 0.0,
                "total_pnl_pct": 0.0, "total_pnl_pct_net": 0.0}
    sub = [r for r in suite_rows if r["strategy"] == strategy]
    wins = sum(r["wins"] for r in sub)

    def _pf(profit_key: str, loss_key: str) -> float:
        profit = sum(r.get(profit_key, 0.0) for r in sub)
        loss = sum(r.get(loss_key, 0.0) for r in sub)
        if loss > 0:
            return round(profit / loss, 2)
        return float("inf") if profit > 0 else 0.0

    return {
        "symbol": "TOTAL",
        "n": n,
        "win_rate": round(100 * wins / n, 1),
        "win_rate_net": round(
            sum(r["win_rate_net"] * r["n"] for r in strategy_rows) / n, 1),
        "profit_factor": _pf("gross_profit_pct", "gross_loss_pct"),
        "profit_factor_net": _pf("gross_profit_pct_net", "gross_loss_pct_net"),
        "total_pnl_pct": round(sum(r["total_pnl_pct"] for r in strategy_rows), 2),
        "total_pnl_pct_net": round(sum(r["total_pnl_pct_net"] for r in strategy_rows), 2),
    }


def _print_session_tables(session_rows: dict, suite_rows: list[dict],
                          periods: dict, flip_exit: bool) -> None:
    """Kompakt tabel pr. strategi — det man faktisk kan læse i en samtale."""
    period = _period_label(periods)
    config_label = "A2 flip-exit" if flip_exit else "A1 baseline"
    for strategy, srows in session_rows.items():
        print()
        print(report.format_session_table(
            srows + [_total_row(srows, suite_rows, strategy)],
            strategy, period, config_label,
        ))


def _print_suite_table(rows: list[dict]) -> None:
    print()
    print("=" * 148)
    print(f"  {'Strategi':22s} {'Symbol':10s} {'Trades':>7s} {'Win%':>7s} "
          f"{'PF':>7s} {'PFnet':>7s} {'MaxDD%':>8s} {'Sharpe':>7s} {'PnL%':>9s} "
          f"{'PnLnet%':>9s} {'W':>5s} {'L':>5s} {'AvgW%':>7s} {'AvgL%':>7s} "
          f"{'Bars':>6s}  {'OK':>3s}")
    print("-" * 148)
    for r in rows:
        pf = r["profit_factor"]
        pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
        pfn = r.get("profit_factor_net", pf)
        pfn_s = "inf" if pfn == float("inf") else f"{pfn:.2f}"
        print(f"  {r['strategy']:22s} {r['symbol']:10s} {r['trades']:>7d} "
              f"{r['win_rate']:>7.1f} {pf_s:>7s} {pfn_s:>7s} {r['max_dd']:>8.2f} "
              f"{r['sharpe']:>7.2f} {r['total_pnl_pct']:>9.2f} "
              f"{r.get('total_pnl_pct_net', 0.0):>9.2f} "
              f"{r['wins']:>5d} {r['losses']:>5d} {r['avg_win_pct']:>7.2f} "
              f"{r['avg_loss_pct']:>7.2f} {r['avg_bars_held']:>6.1f}  "
              f"{'✅' if r['pass'] else '❌':>3s}")
    print("=" * 148)
    n_pass = sum(1 for r in rows if r["pass"])
    n_gross = sum(1 for r in rows if r.get("pass_gross", r["pass"]))
    print(f"  Godkendt til paper mode (alle tærskler, NETTO): {n_pass}/{len(rows)}"
          + (f"   [brutto ville give {n_gross}/{len(rows)}]" if n_gross != n_pass else ""))
    print("=" * 148)


def _save_suite_csv(rows: list[dict], suffix: str = "") -> Path:
    report.RESULTS_DIR.mkdir(exist_ok=True)
    path = report.RESULTS_DIR / f"suite_{date.today().isoformat()}{suffix}.csv"
    fields = ["strategy", "symbol", "trades", "open_at_end", "win_rate",
              "profit_factor", "max_dd", "sharpe", "total_pnl_pct", "wins",
              "losses", "avg_win_pct", "avg_loss_pct", "avg_bars_held",
              "win_rate_net", "profit_factor_net", "total_pnl_pct_net",
              "max_dd_net", "sharpe_net", "total_cost_pct",
              "pass", "pass_gross"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            row = dict(r)
            for key in ("profit_factor", "profit_factor_net"):
                if row.get(key) == float("inf"):
                    row[key] = "inf"
            writer.writerow(row)
    print(f"  Suite-resultater gemt til {path}")
    return path


def _save_trades_csv(all_trades: list[dict], suffix: str = "") -> Path | None:
    """Gem alle suitens trades samlet til én CSV (én række pr. trade).

    Modsat report.save_csv (én fil pr. strategi×symbol) er det her hele suiten i
    én fil, så per-trade data kan analyseres på tværs uden at samle filer først.
    """
    if not all_trades:
        return None
    report.RESULTS_DIR.mkdir(exist_ok=True)
    path = report.RESULTS_DIR / f"trades_{date.today().isoformat()}{suffix}.csv"
    fields = ["strategy_id", "symbol", "side", "entry_time", "exit_time",
              "entry_price", "exit_price", "pnl", "pnl_pct", "reason", "bars_held",
              "breakeven_activated", "confidence", "would_pass_production",
              "flip_level", "flip_breached_bar", "flip_breached_before_exit",
              "flip_timing", "pnl_net", "pnl_pct_net", "cost_pct",
              "cost_spread_pct", "cost_slippage_pct", "cost_commission_pct"]
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
    parser.add_argument("--flip-exit", action="store_true",
                        help="Kørsel A2: luk også handlen på body close gennem flip "
                             "level. Måling af et hypotetisk exit — live-adfærden "
                             "(A1, uden flaget) er uændret observe-only.")
    args = parser.parse_args()

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    if args.all:
        return _run_all(config, args.timeframe, flip_exit=args.flip_exit)

    if not args.strategy or not args.symbol:
        parser.error("Angiv enten --all eller både --strategy og --symbol")
    return _run_single(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
