"""
Parameter-sweep: hvilke strategi-parametre giver nok signaler til at fodre
reflection-loopet, uden at kvaliteten kollapser?

Engangs-analyse (PRD_BACKTEST_PARAM_SWEEP.md). Scriptet rører IKKE
``strategies/*.py`` — de to løsnede trend-varianter (TM-C/TM-D) er subklasser
defineret her i filen, og alle øvrige varianter er rene ``params``-overrides
gennem det A/B-API strategierne allerede har.

    .venv/bin/python backtest/param_sweep.py
    .venv/bin/python backtest/param_sweep.py --variants TM-C,TM-D --symbols BTC/USDT
    .venv/bin/python backtest/param_sweep.py --self-check   # verificér TM-C≡produktion
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# Tillad kørsel som `python backtest/param_sweep.py` (tilføj projektrod til sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import metrics as metrics_mod  # noqa: E402
from backtest import report  # noqa: E402
from backtest.runner import fetch_data, simulate_trade  # noqa: E402
from data.indicators import (  # noqa: E402
    add_all,
    calculate_atr,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    clamp,
)
from strategies.base import BaseStrategy, Signal  # noqa: E402
from strategies.reversal_context import ReversalContext  # noqa: E402
from strategies.trend_momentum import TrendMomentum  # noqa: E402
from strategies.volatility_breakout import VolatilityBreakout  # noqa: E402

DATA_CACHE = report.RESULTS_DIR / ".data_cache"


# ---------------------------------------------------------------------------
# TM-C / TM-D: løsnede trend-varianter (kun i dette script)
# ---------------------------------------------------------------------------
# Produktionens flaskehals er at MACD skal krydse signalet på PRÆCIS den seneste
# bar. De to varianter løsner kun dén betingelse — EMA-trendfilteret, RSI-loftet
# og confidence-formlen er identiske med TrendMomentum, så tallene kan
# sammenlignes direkte med baseline. Detektoren er det eneste der udskiftes.


def _detect_cross(macd_arr, sig_arr, hist_arr, lookback: int):
    """Seneste MACD/signal-kryds inden for `lookback` barer.

    Returnerer ("up"|"down", |Δhist| på krydsbaren) eller None. Offset 1 =
    krydset mellem næstsidste og sidste bar, dvs. produktionens definition —
    ``lookback=1`` reproducerer TrendMomentum bar for bar (se --self-check).
    """
    for k in range(1, lookback + 1):
        now, prev = -k, -k - 1
        delta = abs(hist_arr[now] - hist_arr[prev])
        if macd_arr[prev] < sig_arr[prev] and macd_arr[now] > sig_arr[now]:
            return "up", delta
        if macd_arr[prev] > sig_arr[prev] and macd_arr[now] < sig_arr[now]:
            return "down", delta
    return None


def _detect_hist_turn(macd_arr, sig_arr, hist_arr, lookback: int = 2):
    """MACD-histogrammet har skiftet retning over de seneste 2 barer.

    Faldende → stigende = long-kandidat (og omvendt). Ingen krav om at MACD
    faktisk krydser signalet, så det her er den bredeste af de fire varianter.
    """
    h3, h2, h1 = hist_arr[-3], hist_arr[-2], hist_arr[-1]
    if h2 < h3 and h1 > h2:
        return "up", abs(h1 - h2)
    if h2 > h3 and h1 < h2:
        return "down", abs(h1 - h2)
    return None


def _trend_signal(strategy, df, symbol, params, detector, lookback):
    """TrendMomentum.generate_signal med udskiftelig kryds-detektor.

    Alt andet end detektoren er en 1:1-kopi af produktionsstrategien: samme
    indikatorer, samme gates, samme confidence-vægte og samme param-nøgler.
    """
    p = params or {}
    if len(df) < strategy.MIN_BARS:
        return None

    ema50 = calculate_ema(df, 50)
    ema200 = calculate_ema(df, 200)
    macd = calculate_macd(df)
    rsi = calculate_rsi(df, 14)
    atr = calculate_atr(df, 14)

    macd_arr = macd["macd"].to_numpy(dtype=float)
    sig_arr = macd["macd_signal"].to_numpy(dtype=float)
    hist_arr = macd["macd_hist"].to_numpy(dtype=float)

    ema_50 = float(ema50.iloc[-1])
    ema_200 = float(ema200.iloc[-1])
    rsi_now = float(rsi.iloc[-1])
    atr_now = float(atr.iloc[-1])

    # Detektoren kigger op til `lookback`+1 barer tilbage — NaN-tjekket skal
    # dække hele det vindue, ellers slipper en NaN igennem til confidence.
    depth = lookback + 1
    if len(macd_arr) < depth + 1:
        return None
    if any(
        np.isnan(v)
        for v in (*macd_arr[-depth - 1:], *sig_arr[-depth - 1:],
                  *hist_arr[-depth - 1:], ema_50, ema_200, rsi_now, atr_now)
    ):
        return None
    if ema_200 == 0 or atr_now <= 0:
        return None

    cross = detector(macd_arr, sig_arr, hist_arr, lookback)
    if cross is None:
        return None
    direction, hist_delta = cross

    if direction == "up" and ema_50 > ema_200 and rsi_now < 60:
        side = "long"
        rsi_room = clamp((60 - rsi_now) / 60, 0, 1)
    elif direction == "down" and ema_50 < ema_200 and rsi_now > 40:
        side = "short"
        rsi_room = clamp((rsi_now - 40) / 60, 0, 1)
    else:
        return None

    scale = p.get(
        "trend_strength_scale",
        strategy.TREND_STRENGTH_SCALE.get(BaseStrategy.get_asset_class(symbol), 0.05),
    )
    cross_scale = p.get("cross_strength_scale", strategy.CROSS_STRENGTH_SCALE)
    min_conf = p.get("min_confidence", strategy.min_confidence)

    trend_strength = clamp(abs(ema_50 - ema_200) / ema_200, 0, scale) / scale
    cross_strength = clamp(hist_delta / atr_now / cross_scale, 0, 1)
    confidence = clamp(
        0.35 + 0.25 * trend_strength + 0.25 * cross_strength + 0.15 * rsi_room,
        0.0,
        1.0,
    )
    if confidence < min_conf:
        return None

    return Signal(
        strategy_id=strategy.name,
        symbol=symbol,
        side=side,
        confidence=confidence,
        timeframe=strategy.timeframe,
        metadata={
            "ema_50": ema_50,
            "ema_200": ema_200,
            "macd": float(macd_arr[-1]),
            "macd_signal": float(sig_arr[-1]),
            "macd_hist": float(hist_arr[-1]),
            "rsi": rsi_now,
            "atr": atr_now,
            "trend_strength": trend_strength,
            "cross_strength": cross_strength,
            "rsi_room": rsi_room,
            "cross_lookback": lookback,
        },
    )


class TrendMomentumRelaxed(TrendMomentum):
    """TM-C: accepterer et MACD-kryds fra de seneste 3 barer, ikke kun bar -1."""

    name = "trend_momentum_relaxed"
    CROSS_LOOKBACK = 3

    def generate_signal(self, df, symbol, params=None):
        return _trend_signal(self, df, symbol, params, _detect_cross,
                             self.CROSS_LOOKBACK)


class TrendMomentumHistDir(TrendMomentum):
    """TM-D: intet kryds-krav — MACD-histogrammets retningsskift er signalet."""

    name = "trend_momentum_histdir"

    def generate_signal(self, df, symbol, params=None):
        return _trend_signal(self, df, symbol, params, _detect_hist_turn, 2)


# ---------------------------------------------------------------------------
# Varianter
# ---------------------------------------------------------------------------

STRATEGY_FACTORIES = {
    "trend_momentum": TrendMomentum,
    "trend_momentum_relaxed": TrendMomentumRelaxed,
    "trend_momentum_histdir": TrendMomentumHistDir,
    "reversal_context": ReversalContext,
    "volatility_breakout": VolatilityBreakout,
}


@dataclass(frozen=True)
class Variant:
    key: str            # "TM-A"
    label: str          # kolonne-tekst i tabellen
    group: str          # hvilken baseline-strategi den sammenlignes med
    strategy_key: str   # nøgle i STRATEGY_FACTORIES
    params: dict = field(default_factory=dict)


# Baseline = præcis hvad `runner.py --all` gør i dag: tomt params-dict, så
# strategien kører på klassens defaults og confidence-gulvet kommer fra
# config.yaml (strategies.min_confidence).
VARIANTS: list[Variant] = [
    Variant("TM-base", "Baseline", "trend_momentum", "trend_momentum"),
    Variant("TM-A", "TM-A (cs=0.05)", "trend_momentum", "trend_momentum",
            {"min_confidence": 0.45, "cross_strength_scale": 0.05}),
    Variant("TM-B", "TM-B (cs=0.12)", "trend_momentum", "trend_momentum",
            {"min_confidence": 0.45, "cross_strength_scale": 0.12}),
    Variant("TM-C", "TM-C (3-bar kryds)", "trend_momentum",
            "trend_momentum_relaxed", {"min_confidence": 0.45}),
    Variant("TM-D", "TM-D (hist-retning)", "trend_momentum",
            "trend_momentum_histdir", {"min_confidence": 0.45}),

    Variant("RC-base", "Baseline", "reversal_context", "reversal_context"),
    Variant("RC-A", "RC-A (vol=1.1, d=3)", "reversal_context", "reversal_context",
            {"min_volume_ratio": 1.1, "min_rsi_delta": 3.0}),
    Variant("RC-B", "RC-B (vol=1.5, d=8)", "reversal_context", "reversal_context",
            {"min_volume_ratio": 1.5, "min_rsi_delta": 8.0}),
    Variant("RC-C", "RC-C (ingen vol-gate)", "reversal_context", "reversal_context",
            {"min_volume_ratio": 1.0, "min_rsi_delta": 3.0}),
    Variant("RC-D", "RC-D (aggressiv)", "reversal_context", "reversal_context",
            {"min_volume_ratio": 1.0, "min_rsi_delta": 2.0, "min_confidence": 0.40}),

    Variant("VB-base", "Baseline", "volatility_breakout", "volatility_breakout"),
    Variant("VB-A", "VB-A (p5, vol=1.3)", "volatility_breakout", "volatility_breakout",
            {"squeeze_percentile": 5, "min_volume_ratio": 1.3}),
    Variant("VB-B", "VB-B (p15, vol=2.0)", "volatility_breakout", "volatility_breakout",
            {"squeeze_percentile": 15, "min_volume_ratio": 2.0}),
    Variant("VB-C", "VB-C (p25, vol=1.2)", "volatility_breakout", "volatility_breakout",
            {"squeeze_percentile": 25, "min_volume_ratio": 1.2}),
    Variant("VB-D", "VB-D (aggressiv)", "volatility_breakout", "volatility_breakout",
            {"squeeze_percentile": 30, "min_volume_ratio": 1.0}),
]

VARIANTS_BY_KEY = {v.key: v for v in VARIANTS}
GROUP_ORDER = ["trend_momentum", "reversal_context", "volatility_breakout"]

# Kvalitetsbaren fra PRD'en: vi accepterer dårligere tal end paper-tærsklerne
# for at få nok udfald til at reflection-loopet overhovedet kan lære noget.
QUALITY_MIN_WIN_RATE = 40.0
QUALITY_MIN_PF = 0.9
GOAL_TRADES_PER_SYMBOL_YEAR = 5.0
MIN_TRADES_FOR_PF_RANKING = 10


# ---------------------------------------------------------------------------
# Backtest-kørsel med eksplicitte params
# ---------------------------------------------------------------------------

def run_variant(strategy, symbol: str, df: pd.DataFrame, config: dict,
                params: dict, warmup: int = 200) -> list[dict]:
    """Som ``runner.run_backtest``, men med et frit params-dict.

    Runneren hard-coder ``params={"min_confidence": <config>}``; her skal
    varianten kunne sætte sit eget gulv. Confidence tjekkes ét sted (strategien
    gør det selv) og igen udenfor, præcis som runneren — så en variant uden
    ``min_confidence`` giver bit-identiske trades med ``runner.py --all``.
    """
    df = add_all(df)
    gate = params.get(
        "min_confidence",
        config.get("strategies", {}).get("min_confidence", strategy.min_confidence),
    )
    call_params = dict(params)
    call_params.setdefault("min_confidence", gate)

    trades: list[dict] = []
    i = warmup
    while i < len(df):
        window = df.iloc[:i].copy()
        signal = strategy.generate_signal(window, symbol, call_params)
        if signal is not None and signal.confidence >= gate:
            future = df.iloc[i:].reset_index(drop=True)
            if len(future) < 2:
                break
            trade = simulate_trade(signal, future, config)
            trade["confidence"] = round(float(signal.confidence), 4)
            trades.append(trade)
            # Spring frem til trade er lukket for at undgå overlappende positioner.
            i += max(trade["bars_held"], 1)
        else:
            i += 1
    return trades


# ---------------------------------------------------------------------------
# Data (hentes én gang, caches på disk pr. dag)
# ---------------------------------------------------------------------------

def _cache_path(symbol: str, timeframe: str) -> Path:
    slug = symbol.replace("/", "-")
    return DATA_CACHE / f"{slug}_{timeframe}_{date.today().isoformat()}.pkl"


def load_data(symbols: list[str], timeframe: str,
              refresh: bool = False) -> dict[str, Path]:
    """Hent OHLCV for hvert symbol og læg det på disk. Returnér symbol → sti.

    Cachen er dagsdateret, så en sweep-kørsel kan gentages uden at hamre
    Binance/yfinance — og alle varianter ser garanteret præcis samme barer.
    """
    DATA_CACHE.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for symbol in symbols:
        path = _cache_path(symbol, timeframe)
        if path.exists() and not refresh:
            df = pickle.loads(path.read_bytes())
            print(f"  {symbol:10s} {len(df):>5d} barer  (cache)")
            paths[symbol] = path
            continue
        print(f"  {symbol:10s} henter ...", end="", flush=True)
        try:
            df = fetch_data(symbol, timeframe)
        except Exception as e:
            print(f" FEJL: {type(e).__name__}: {str(e)[:70]}")
            continue
        if df is None or df.empty or len(df) < 200:
            print(f" for lidt data ({0 if df is None else len(df)} barer) — udelades")
            continue
        path.write_bytes(pickle.dumps(df))
        print(f"\r  {symbol:10s} {len(df):>5d} barer  "
              f"({df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()})")
        paths[symbol] = path
    return paths


def data_spans(paths: dict[str, Path]) -> dict[str, float]:
    """Symbol → antal år data. Bruges til trades-pr-symbol-pr-år."""
    spans: dict[str, float] = {}
    for symbol, path in paths.items():
        df = pickle.loads(Path(path).read_bytes())
        delta = df["time"].iloc[-1] - df["time"].iloc[0]
        spans[symbol] = delta.total_seconds() / (365.25 * 24 * 3600)
    return spans


# ---------------------------------------------------------------------------
# Worker (ProcessPool: sweepen er 15 × 6 uafhængige backtests)
# ---------------------------------------------------------------------------

_WORKER_DATA: dict[str, pd.DataFrame] = {}
_WORKER_CONFIG: dict = {}


def _worker_init(paths: dict[str, str], config: dict) -> None:
    global _WORKER_CONFIG
    _WORKER_CONFIG = config
    for symbol, path in paths.items():
        _WORKER_DATA[symbol] = pickle.loads(Path(path).read_bytes())


def _worker_task(variant_key: str, symbol: str) -> dict:
    variant = VARIANTS_BY_KEY[variant_key]
    strategy = STRATEGY_FACTORIES[variant.strategy_key]()
    started = time.time()
    try:
        trades = run_variant(strategy, symbol, _WORKER_DATA[symbol].copy(),
                             _WORKER_CONFIG, variant.params)
    except Exception as e:
        return {"variant": variant_key, "symbol": symbol, "error":
                f"{type(e).__name__}: {e}", "trades": [], "metrics": metrics_mod.compute([]),
                "seconds": time.time() - started}
    for t in trades:
        t["variant"] = variant_key
        t["strategy_id"] = strategy.name
    return {"variant": variant_key, "symbol": symbol, "error": None,
            "trades": trades, "metrics": metrics_mod.compute(trades),
            "seconds": time.time() - started}


def execute(tasks: list[tuple[str, str]], paths: dict[str, Path], config: dict,
            jobs: int) -> list[dict]:
    """Kør alle (variant, symbol)-par — parallelt hvis jobs > 1."""
    str_paths = {s: str(p) for s, p in paths.items()}
    results: list[dict] = []
    total = len(tasks)
    done = 0
    started = time.time()

    def _log(res: dict) -> None:
        m = res["metrics"]
        pf = m["profit_factor"]
        tail = (f"FEJL: {res['error'][:60]}" if res["error"] else
                f"{m['closed_trades']:>4d} trades | WR {m['win_rate']:>5.1f}% | "
                f"PF {'inf' if pf == float('inf') else f'{pf:.2f}'}")
        print(f"  [{done:>3d}/{total}] {res['variant']:<8s} {res['symbol']:<10s} "
              f"{res['seconds']:>5.1f}s  {tail}", flush=True)

    if jobs <= 1:
        _worker_init(str_paths, config)
        for variant_key, symbol in tasks:
            res = _worker_task(variant_key, symbol)
            done += 1
            results.append(res)
            _log(res)
    else:
        with ProcessPoolExecutor(max_workers=jobs, initializer=_worker_init,
                                 initargs=(str_paths, config)) as pool:
            futures = {pool.submit(_worker_task, v, s): (v, s) for v, s in tasks}
            for future in as_completed(futures):
                res = future.result()
                done += 1
                results.append(res)
                _log(res)

    print(f"\n  {total} backtests på {time.time() - started:.0f}s "
          f"({jobs} parallelle job)")
    return results


# ---------------------------------------------------------------------------
# Aggregering
# ---------------------------------------------------------------------------

def _sort_key(trade: dict):
    t = trade.get("exit_time") or trade.get("entry_time")
    return t if isinstance(t, datetime) else datetime.min


def aggregate(results: list[dict], spans: dict[str, float]) -> list[dict]:
    """Saml resultaterne pr. variant (alle symboler i én pulje).

    Puljen sorteres kronologisk før metrics beregnes — ellers ville max
    drawdown afhænge af hvilken rækkefølge symbolerne tilfældigvis kom i.
    """
    rows: list[dict] = []
    for variant in VARIANTS:
        mine = [r for r in results if r["variant"] == variant.key]
        if not mine:
            continue
        pooled = sorted((t for r in mine for t in r["trades"]), key=_sort_key)
        m = metrics_mod.compute(pooled)
        years = sum(spans.get(r["symbol"], 0.0) for r in mine)
        avg_bars = (sum(t["bars_held"] for t in pooled) / len(pooled)) if pooled else 0.0
        rows.append({
            "variant": variant.key,
            "label": variant.label,
            "group": variant.group,
            "strategy_id": variant.strategy_key,
            "params": json.dumps(variant.params, sort_keys=True),
            "scope": "ALL",
            "symbol": "",
            "symbols": len(mine),
            "trades": m["closed_trades"],
            "open_at_end": m["open_at_end_count"],
            "win_rate": m["win_rate"],
            "profit_factor": m["profit_factor"],
            "avg_pnl_pct": m["avg_pnl_pct"],
            "total_pnl_pct": m["total_pnl_pct"],
            "max_dd": m["max_drawdown_pct"],
            "sharpe": m["sharpe"],
            "wins": m["wins"],
            "losses": m["losses"],
            "avg_win_pct": m["avg_win_pct"],
            "avg_loss_pct": m["avg_loss_pct"],
            "avg_bars_held": round(avg_bars, 1),
            "trades_per_symbol_year": round(m["closed_trades"] / years, 2) if years else 0.0,
            "errors": sum(1 for r in mine if r["error"]),
        })
    return rows


def per_symbol_rows(results: list[dict], spans: dict[str, float]) -> list[dict]:
    rows: list[dict] = []
    for variant in VARIANTS:
        for res in [r for r in results if r["variant"] == variant.key]:
            m = res["metrics"]
            years = spans.get(res["symbol"], 0.0)
            trades = res["trades"]
            avg_bars = (sum(t["bars_held"] for t in trades) / len(trades)) if trades else 0.0
            rows.append({
                "variant": variant.key,
                "label": variant.label,
                "group": variant.group,
                "strategy_id": variant.strategy_key,
                "params": json.dumps(variant.params, sort_keys=True),
                "scope": "symbol",
                "symbol": res["symbol"],
                "symbols": 1,
                "trades": m["closed_trades"],
                "open_at_end": m["open_at_end_count"],
                "win_rate": m["win_rate"],
                "profit_factor": m["profit_factor"],
                "avg_pnl_pct": m["avg_pnl_pct"],
                "total_pnl_pct": m["total_pnl_pct"],
                "max_dd": m["max_drawdown_pct"],
                "sharpe": m["sharpe"],
                "wins": m["wins"],
                "losses": m["losses"],
                "avg_win_pct": m["avg_win_pct"],
                "avg_loss_pct": m["avg_loss_pct"],
                "avg_bars_held": round(avg_bars, 1),
                "trades_per_symbol_year": round(m["closed_trades"] / years, 2) if years else 0.0,
                "errors": 1 if res["error"] else 0,
            })
    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _pf(value) -> str:
    return "inf" if value == float("inf") else f"{value:.2f}"


def print_tables(rows: list[dict]) -> None:
    for group in GROUP_ORDER:
        mine = [r for r in rows if r["group"] == group]
        if not mine:
            continue
        base = next((r for r in mine if r["variant"].endswith("-base")), None)
        print()
        print(f"=== {group} ===")
        print(f"{'Variant':<22s} | {'Trades':>6s} | {'Win%':>6s} | {'PF':>5s} | "
              f"{'Avg PnL%':>8s} | {'Max DD%':>8s} | {'Sharpe':>6s} | {'Tr/sym/år':>9s} | {'vs base':>7s}")
        print("-" * 22 + "-|-" + "-" * 6 + "-|-" + "-" * 6 + "-|-" + "-" * 5 + "-|-"
              + "-" * 8 + "-|-" + "-" * 8 + "-|-" + "-" * 6 + "-|-" + "-" * 9 + "-|-" + "-" * 7)
        for r in mine:
            if base and base["trades"] > 0 and r is not base:
                ratio = f"{r['trades'] / base['trades']:.1f}x"
            else:
                ratio = "—"
            flag = " ✅" if _quality_ok(r) else ""
            print(f"{r['label']:<22s} | {r['trades']:>6d} | {r['win_rate']:>6.1f} | "
                  f"{_pf(r['profit_factor']):>5s} | {r['avg_pnl_pct']:>+8.2f} | "
                  f"{r['max_dd']:>8.1f} | {r['sharpe']:>6.2f} | "
                  f"{r['trades_per_symbol_year']:>9.2f} | {ratio:>7s}{flag}")
        open_at_end = sum(r["open_at_end"] for r in mine)
        if open_at_end:
            print(f"  (+{open_at_end} trades stadig åbne ved data-slut på tværs af "
                  f"varianter — ikke medregnet)")
    print()
    print(f"✅ = win-rate > {QUALITY_MIN_WIN_RATE:.0f}% og PF > {QUALITY_MIN_PF} "
          f"(PRD'ens kvalitetsbar). Tr/sym/år måles mod målet på "
          f"{GOAL_TRADES_PER_SYMBOL_YEAR:.0f}.")


def _quality_ok(row: dict) -> bool:
    pf = row["profit_factor"]
    return (row["trades"] > 0
            and row["win_rate"] > QUALITY_MIN_WIN_RATE
            and (pf == float("inf") or pf > QUALITY_MIN_PF))


def print_recommendation(rows: list[dict]) -> None:
    print()
    print("=" * 100)
    print("ANBEFALING:")
    print("=" * 100)
    for group in GROUP_ORDER:
        mine = [r for r in rows if r["group"] == group]
        if not mine:
            continue
        base = next((r for r in mine if r["variant"].endswith("-base")), None)
        rankable = [r for r in mine if r["trades"] >= MIN_TRADES_FOR_PF_RANKING]
        best_pf = max(rankable, key=lambda r: (r["profit_factor"] == float("inf"),
                                               r["profit_factor"]), default=None)
        qualified = [r for r in mine if _quality_ok(r)]
        most_trades = max(qualified, key=lambda r: r["trades"], default=None)
        goal_hit = [r for r in mine
                    if r["trades_per_symbol_year"] >= GOAL_TRADES_PER_SYMBOL_YEAR]

        print(f"- {group}:")
        if best_pf is not None:
            print(f"    bedst PF (≥{MIN_TRADES_FOR_PF_RANKING} trades): "
                  f"{best_pf['label']} — PF {_pf(best_pf['profit_factor'])}, "
                  f"WR {best_pf['win_rate']:.1f}%, {best_pf['trades']} trades")
        else:
            print(f"    bedst PF: ingen variant nåede {MIN_TRADES_FOR_PF_RANKING} trades")
        if most_trades is not None:
            extra = ""
            if base and base["trades"] > 0:
                extra = f" ({most_trades['trades'] / base['trades']:.1f}× baseline)"
            print(f"    flest trades ved acceptabel kvalitet: {most_trades['label']} — "
                  f"{most_trades['trades']} trades{extra}, WR {most_trades['win_rate']:.1f}%, "
                  f"PF {_pf(most_trades['profit_factor'])}")
        else:
            print(f"    flest trades ved acceptabel kvalitet: INGEN variant klarer "
                  f"WR>{QUALITY_MIN_WIN_RATE:.0f}% + PF>{QUALITY_MIN_PF}")
        if goal_hit:
            names = ", ".join(f"{r['variant']} ({r['trades_per_symbol_year']:.1f})"
                              for r in goal_hit)
            print(f"    ≥{GOAL_TRADES_PER_SYMBOL_YEAR:.0f} trades/symbol/år: {names}")
        else:
            best = max(mine, key=lambda r: r["trades_per_symbol_year"])
            print(f"    ≥{GOAL_TRADES_PER_SYMBOL_YEAR:.0f} trades/symbol/år: ingen — "
                  f"bedst er {best['variant']} med {best['trades_per_symbol_year']:.1f}")
    print("=" * 100)


CSV_FIELDS = ["variant", "label", "group", "strategy_id", "params", "scope", "symbol",
              "symbols", "trades", "open_at_end", "win_rate", "profit_factor",
              "avg_pnl_pct", "total_pnl_pct", "max_dd", "sharpe", "wins", "losses",
              "avg_win_pct", "avg_loss_pct", "avg_bars_held",
              "trades_per_symbol_year", "errors"]


def save_csv(rows: list[dict]) -> Path:
    report.RESULTS_DIR.mkdir(exist_ok=True)
    path = report.RESULTS_DIR / f"param_sweep_{date.today().isoformat()}.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            row = dict(r)
            if row["profit_factor"] == float("inf"):
                row["profit_factor"] = "inf"
            writer.writerow(row)
    print(f"  Sweep-resultater gemt til {path}")
    return path


def save_trades_csv(results: list[dict]) -> Path | None:
    all_trades = [t for r in results for t in r["trades"]]
    if not all_trades:
        return None
    report.RESULTS_DIR.mkdir(exist_ok=True)
    path = report.RESULTS_DIR / f"param_sweep_trades_{date.today().isoformat()}.csv"
    fields = ["variant", "strategy_id", "symbol", "side", "entry_time", "exit_time",
              "entry_price", "exit_price", "confidence", "pnl", "pnl_pct", "reason",
              "bars_held", "breakeven_activated"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_trades)
    print(f"  {len(all_trades)} trades gemt til {path}")
    return path


# ---------------------------------------------------------------------------
# Self-check: TM-C's motor med lookback=1 skal være produktionsstrategien
# ---------------------------------------------------------------------------

def self_check(symbol: str, timeframe: str, config: dict) -> int:
    """Verificér at variant-motoren ikke er drevet fra produktionsstrategien.

    Med ``lookback=1`` er `_trend_signal` per konstruktion TrendMomentum. Hvis
    de to giver forskellige signaler er kopien divergeret, og TM-C/TM-D's tal
    kan ikke sammenlignes med baseline.
    """
    class _Lookback1(TrendMomentum):
        name = "trend_momentum_lookback1"

        def generate_signal(self, df, symbol, params=None):
            return _trend_signal(self, df, symbol, params, _detect_cross, 1)

    paths = load_data([symbol], timeframe)
    if symbol not in paths:
        print(f"Ingen data for {symbol} — self-check kan ikke køre")
        return 1
    df = add_all(pickle.loads(paths[symbol].read_bytes()))

    prod, copy = TrendMomentum(), _Lookback1()
    params = {"min_confidence": config["strategies"]["min_confidence"]}
    checked = mismatches = signals = 0
    for i in range(200, len(df), 3):
        window = df.iloc[:i].copy()
        a = prod.generate_signal(window, symbol, params)
        b = copy.generate_signal(window, symbol, params)
        checked += 1
        if (a is None) != (b is None):
            mismatches += 1
        elif a is not None:
            signals += 1
            if a.side != b.side or abs(a.confidence - b.confidence) > 1e-9:
                mismatches += 1
    print(f"\n  {checked} vinduer sammenlignet ({signals} med signal), "
          f"{mismatches} afvigelser")
    if mismatches:
        print("  ❌ variant-motoren afviger fra strategies/trend_momentum.py")
        return 1
    print("  ✅ _trend_signal(lookback=1) ≡ TrendMomentum.generate_signal")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--symbols", help="Kommasepareret liste; default = config.symbols")
    parser.add_argument("--variants", help="Kommasepareret liste, fx TM-C,VB-D")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                        help="Parallelle processer (1 = sekventielt)")
    parser.add_argument("--refresh-data", action="store_true",
                        help="Ignorér disk-cachen og hent OHLCV forfra")
    parser.add_argument("--self-check", action="store_true",
                        help="Verificér variant-motoren mod produktionsstrategien og stop")
    args = parser.parse_args()

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    symbols = ([s.strip() for s in args.symbols.split(",")] if args.symbols
               else list(config["symbols"]))

    if args.self_check:
        return self_check(symbols[0], args.timeframe, config)

    if args.variants:
        wanted = {v.strip() for v in args.variants.split(",")}
        unknown = wanted - set(VARIANTS_BY_KEY)
        if unknown:
            parser.error(f"Ukendte varianter: {sorted(unknown)}. "
                         f"Vælg blandt: {list(VARIANTS_BY_KEY)}")
        variants = [v for v in VARIANTS if v.key in wanted]
    else:
        variants = VARIANTS

    print("=" * 100)
    print(f"  PARAMETER-SWEEP  |  {len(variants)} varianter × {len(symbols)} symboler "
          f"|  {args.timeframe}  |  min_confidence (config) = "
          f"{config['strategies']['min_confidence']}")
    print("=" * 100)
    print("\nData:")
    paths = load_data(symbols, args.timeframe, refresh=args.refresh_data)
    if not paths:
        print("Ingen brugbare data — afbryder")
        return 1
    spans = data_spans(paths)

    tasks = [(v.key, s) for v in variants for s in paths]
    print(f"\nKører {len(tasks)} backtests:")
    results = execute(tasks, paths, config, max(1, args.jobs))

    rows = aggregate(results, spans)
    print_tables(rows)
    print_recommendation(rows)
    print()
    save_csv(rows + per_symbol_rows(results, spans))
    save_trades_csv(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
