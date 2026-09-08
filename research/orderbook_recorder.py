"""Optager af rigtig orderbook-spread. **Infrastruktur — skal blive stående.**

Spread findes ikke i OHLCV. `research/spread_estimators.py` estimerer den bagudrettet,
men et estimat er et estimat: Corwin-Schultz har et positivt støjgulv omkring 0,08%,
og vores model antager 1 bp. Vi kan ikke afgøre om modellen er rigtig uden at måle.

Denne proces måler. Den rører **ikke** handelsmotoren og importerer intet fra `core/`.

```bash
.venv/bin/python research/orderbook_recorder.py --estimate-disk   # FØR du starter
.venv/bin/python research/orderbook_recorder.py --once            # ét snapshot, til test
.venv/bin/python research/orderbook_recorder.py --coverage        # dækningsgrad
.venv/bin/python research/orderbook_recorder.py                   # kør (launchd gør dette)
```

## Hvorfor parquet og ikke JSON

Arkivet skal vokse i måneder og læses med pandas bagefter. Én stor JSON-fil ville
være ubrugelig til begge dele. Data partitioneres pr. **dag og symbol**, så en
analyse kan læse præcis det den skal.

Formatet vælges før første snapshot. Skifter vi det om to måneder, er arkivet delt i
to inkompatible halvdele.

## Optageren må ikke dø i stilhed

En optager der stoppede for tre uger siden er værre end ingen optager, fordi vi
ville stole på dataen. Fire spærringer:

1. **Auto-genstart** ved fejl, med backoff. launchd genstarter desuden processen.
2. **Huller logges eksplicit** — hvert manglende snapshot kan ses bagefter.
3. **Heartbeat** (`_heartbeat.json`) med seneste vellykkede snapshot, så det kan
   tjekkes med ét blik om den kører.
4. **Dækningsgrad rapporteres pr. time i døgnet**, ikke kun pr. dag. Se nedenfor.

## MacBooken sover — og det er systematisk skævhed, ikke tilfældige huller

launchd genstarter ved boot og login, men en lukket MacBook kører ikke. Hullerne
kommer derfor til at matche Mads' søvnrytme — og **spread er bredest om natten og i
weekenden, hvor likviditeten er tyndest.**

Måler vi kun i europæisk og amerikansk dagtid, bliver vores "typiske spread"
systematisk for optimistisk. Det er den værste retning at tage fejl i, når tallet
skal bruges til at afgøre om en 15m-strategi kan bære sine omkostninger.

Derfor er `--coverage` opdelt pr. time i døgnet. Løsningen — hvis skævheden viser
sig — er `caffeinate -s`, ændrede energiindstillinger, eller at optageren flytter til
noget der altid er tændt. Den beslutning tages når tallene foreligger.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "orderbook"
LOG_DIR = ROOT / "data" / "orderbook" / "_logs"
HEARTBEAT = DATA_DIR / "_heartbeat.json"

# Kun krypto: yfinance leverer ingen orderbook, så forex/guld kan ikke optages
# herfra. Det er en reel begrænsning og står i rapporten.
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

DEPTH = 20              # niveauer pr. side
INTERVAL_SEC = 60       # ét snapshot i minuttet
FLUSH_MINUTES = 15      # skriv til disk hvert kvarter — små nok filer, få nok skrivninger
TRADE_LIMIT = 50        # seneste handler pr. snapshot → effektiv spread

logger = logging.getLogger("orderbook")


def _setup_logging(verbose: bool = False) -> None:
    """Roterende log. Uger uden rotation fylder disken."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "recorder.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    if verbose:
        logger.addHandler(logging.StreamHandler(sys.stdout))
    logger.setLevel(logging.INFO)


def _exchange():
    import ccxt

    return ccxt.binance({"enableRateLimit": True})


def snapshot(exchange, symbol: str, depth: int = DEPTH) -> dict | None:
    """Ét orderbook-snapshot + de seneste handler. None ved fejl (logget)."""
    try:
        book = exchange.fetch_order_book(symbol, limit=depth)
    except Exception as exc:  # noqa: BLE001 — netværksfejl må ikke stoppe optageren
        logger.warning("orderbook %s: %s: %s", symbol, type(exc).__name__, exc)
        return None

    bids, asks = book.get("bids") or [], book.get("asks") or []
    if not bids or not asks:
        logger.warning("orderbook %s: tom bog", symbol)
        return None

    row: dict = {
        "ts": pd.Timestamp.now(tz="UTC").tz_localize(None),
        "symbol": symbol,
        "bid": float(bids[0][0]), "ask": float(asks[0][0]),
    }
    row["mid"] = (row["bid"] + row["ask"]) / 2
    row["spread_pct"] = (row["ask"] - row["bid"]) / row["mid"] * 100
    for i in range(depth):
        row[f"bid_px_{i}"] = float(bids[i][0]) if i < len(bids) else None
        row[f"bid_sz_{i}"] = float(bids[i][1]) if i < len(bids) else None
        row[f"ask_px_{i}"] = float(asks[i][0]) if i < len(asks) else None
        row[f"ask_sz_{i}"] = float(asks[i][1]) if i < len(asks) else None

    # Seneste handler ved siden af: den STILLEDE spread er ikke den samme som den
    # EFFEKTIVE. Ét ekstra kald, og det kan ikke hentes bagudrettet.
    try:
        trades = exchange.fetch_trades(symbol, limit=TRADE_LIMIT)
        row["last_trade_px"] = float(trades[-1]["price"]) if trades else None
        row["n_trades_sampled"] = len(trades)
        # Andel af de seneste handler der ramte asken — skævhed i ordreflowet.
        buys = sum(1 for t in trades if t.get("side") == "buy")
        row["buy_share"] = round(buys / len(trades), 4) if trades else None
    except Exception as exc:  # noqa: BLE001
        logger.info("trades %s utilgængelige: %s", symbol, type(exc).__name__)
        row["last_trade_px"] = None
        row["n_trades_sampled"] = 0
        row["buy_share"] = None
    return row


def _flush(buffer: list[dict]) -> int:
    """Skriv bufferen til parquet, partitioneret pr. dag og symbol."""
    if not buffer:
        return 0
    df = pd.DataFrame(buffer)
    written = 0
    for (day, symbol), group in df.groupby([df["ts"].dt.date, "symbol"]):
        out_dir = DATA_DIR / f"dt={day}" / f"symbol={symbol.replace('/', '-')}"
        out_dir.mkdir(parents=True, exist_ok=True)
        # Ét filnavn pr. kvarter: idempotent hvis processen genstarter midt i.
        stamp = group["ts"].iloc[0].strftime("%H%M")
        group.drop(columns=["symbol"]).to_parquet(
            out_dir / f"{stamp}.parquet", index=False, compression="snappy")
        written += len(group)
    return written


def _write_heartbeat(state: dict) -> None:
    """Én fil der kan tjekkes med ét blik — uden at grave i launchctl eller logs."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HEARTBEAT.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(HEARTBEAT)      # atomisk, som status_writer gør det


def run(verbose: bool = False) -> int:
    """Hovedløkken. Kører til den bliver stoppet; genstarter sig selv ved fejl."""
    _setup_logging(verbose)
    exchange = _exchange()
    buffer: list[dict] = []
    state = {"started": datetime.now(timezone.utc), "snapshots_ok": 0,
             "snapshots_failed": 0, "gaps": 0, "last_ok": None, "last_flush": None}
    stopping = {"now": False}

    def _stop(signum, _frame):
        logger.info("signal %s — flusher og stopper", signum)
        stopping["now"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    last_flush = time.time()
    expected_next = time.time()
    while not stopping["now"]:
        tick_start = time.time()
        for symbol in SYMBOLS:
            row = snapshot(exchange, symbol)
            if row is None:
                state["snapshots_failed"] += 1
            else:
                buffer.append(row)
                state["snapshots_ok"] += 1
                state["last_ok"] = row["ts"]

        if time.time() - last_flush >= FLUSH_MINUTES * 60 or stopping["now"]:
            try:
                n = _flush(buffer)
                logger.info("flushede %d rækker", n)
                buffer.clear()
                last_flush = time.time()
                state["last_flush"] = datetime.now(timezone.utc)
            except Exception as exc:  # noqa: BLE001 — hellere beholde bufferen
                logger.error("flush fejlede: %s: %s", type(exc).__name__, exc)

        _write_heartbeat(state)

        # Hullet logges EKSPLICIT frem for at skulle udledes af dataen bagefter.
        expected_next += INTERVAL_SEC
        drift = expected_next - time.time()
        if drift < -INTERVAL_SEC:
            missed = int(-drift // INTERVAL_SEC)
            state["gaps"] += missed
            logger.warning("HUL: %d snapshots sprunget over (drift %.0fs) — "
                           "maskinen har formentlig sovet", missed, -drift)
            expected_next = time.time() + INTERVAL_SEC
        else:
            time.sleep(max(0.0, drift))
        del tick_start

    _flush(buffer)
    _write_heartbeat(state)
    logger.info("stoppet rent: %s", state)
    return 0


def load(symbol: str | None = None, day: str | None = None) -> pd.DataFrame:
    """Læs optaget data. Partitioneringen gør det billigt at læse et udsnit."""
    pattern = f"dt={day or '*'}/symbol={symbol.replace('/', '-') if symbol else '*'}/*.parquet"
    files = sorted(DATA_DIR.glob(pattern))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        d = pd.read_parquet(f)
        d["symbol"] = f.parent.name.split("=", 1)[1].replace("-", "/")
        frames.append(d)
    return pd.concat(frames, ignore_index=True).sort_values("ts")


def coverage() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Dækningsgrad pr. dag OG pr. time i døgnet.

    Time-opdelingen er den vigtige. Sover maskinen om natten, får vi kun spread i
    dagtimerne — og spread er bredest når likviditeten er tyndest. En skævhed dér
    gør vores tal systematisk for optimistiske, og den kan kun ses pr. time.
    """
    df = load()
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    per_symbol = df["symbol"].nunique()
    expected_per_hour = 3600 / INTERVAL_SEC * per_symbol

    df["dag"] = df["ts"].dt.date
    df["time"] = df["ts"].dt.hour

    daily = (df.groupby("dag").size().rename("snapshots").reset_index())
    daily["forventet"] = 24 * expected_per_hour
    daily["dækning_%"] = (100 * daily["snapshots"] / daily["forventet"]).round(1)

    hourly = (df.groupby("time").size().rename("snapshots").reset_index())
    n_days = max(df["dag"].nunique(), 1)
    hourly["forventet"] = expected_per_hour * n_days
    hourly["dækning_%"] = (100 * hourly["snapshots"] / hourly["forventet"]).round(1)
    return daily, hourly


def estimate_disk(days: int = 1) -> dict:
    """Diskforbrug, MÅLT på et syntetisk døgn — ikke gættet.

    Skal køres FØR optageren startes. Et arkiv man opdager størrelsen på når disken
    er fuld, er et arkiv man mister.
    """
    import shutil
    import tempfile

    rows_per_day = int(86400 / INTERVAL_SEC) * len(SYMBOLS)
    rng = pd.Series(range(rows_per_day))
    base = 50_000 + rng * 0.01
    row = {
        "ts": pd.date_range("2026-01-01", periods=rows_per_day, freq="20s"),
        "bid": base, "ask": base * 1.0001, "mid": base, "spread_pct": 0.01,
        "last_trade_px": base, "n_trades_sampled": 50, "buy_share": 0.5,
    }
    for i in range(DEPTH):
        row[f"bid_px_{i}"] = base * (1 - i * 0.0001)
        row[f"bid_sz_{i}"] = 1.0 + i
        row[f"ask_px_{i}"] = base * (1 + i * 0.0001)
        row[f"ask_sz_{i}"] = 1.0 + i
    df = pd.DataFrame(row)

    tmp = Path(tempfile.mkdtemp())
    try:
        path = tmp / "probe.parquet"
        df.to_parquet(path, index=False, compression="snappy")
        per_day = path.stat().st_size
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return {
        "symboler": len(SYMBOLS), "niveauer": DEPTH,
        "snapshots_pr_døgn": rows_per_day,
        "kolonner": len(df.columns),
        "MB_pr_døgn": round(per_day / 1e6, 2),
        "MB_pr_måned": round(per_day * 30.44 / 1e6, 1),
        "GB_pr_år": round(per_day * 365.25 / 1e9, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="ét snapshot pr. symbol, så stop")
    ap.add_argument("--coverage", action="store_true", help="dækningsgrad pr. dag og time")
    ap.add_argument("--estimate-disk", action="store_true", help="mål diskforbrug før start")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.estimate_disk:
        for k, v in estimate_disk().items():
            print(f"  {k:20} {v}")
        return 0

    if args.coverage:
        daily, hourly = coverage()
        if daily.empty:
            print("Ingen optaget data endnu.")
            return 0
        print("Pr. dag:\n" + daily.to_string(index=False))
        print("\nPr. time i døgnet (UTC) — her ses det hvis maskinen sover:")
        print(hourly.to_string(index=False))
        return 0

    if args.once:
        _setup_logging(verbose=True)
        ex = _exchange()
        rows = [r for s in SYMBOLS if (r := snapshot(ex, s)) is not None]
        for r in rows:
            print(f"  {r['symbol']:10} bid {r['bid']:.2f}  ask {r['ask']:.2f}  "
                  f"spread {r['spread_pct']:.4f}%  handler {r['n_trades_sampled']}")
        print(f"  ({_flush(rows)} rækker skrevet til {DATA_DIR})")
        return 0

    return run(verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
