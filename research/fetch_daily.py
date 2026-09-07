"""
Hent DAGLIGE barer for de 8 markeder i PRD_DAILY_BIAS_VALIDATION.md §3.

Skriver data/historical/<navn>_1d.csv i samme format som de eksisterende
XAU-filer: Date;Open;High;Low;Close;Volume, semikolon, dato 'YYYY.MM.DD HH:MM'.

Kun forskning — rører ikke data/fetcher.py, config.yaml eller botten.
Kør:  .venv/bin/python research/fetch_daily.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"

# navn -> (kilde, ticker, adjust).  Navnet er filnavnet; ticker er kilde-symbolet.
#
# ``adjust`` er kun relevant for yfinance og betyder auto_adjust: prisen
# bagudjusteres for splits OG udbytter, så serien bliver totalafkast frem for
# kursafkast. Futures og krypto betaler intet udbytte, så flaget ville være en
# no-op der; det står som False for at holde de eksisterende filer bit-identiske.
#
# SPY og QQQ hentes JUSTERET, og det er ikke en detalje: DEL 2c gør buy-and-hold
# til obligatorisk baseline, og buy-and-hold af SPY UDEN udbytte er ikke
# buy-and-hold af SPY — det er ~1,5%/år for lidt. Fejlen er ikke symmetrisk
# mellem de to sider: baselinen sidder i markedet 100% af tiden, TSMOM ~70%, så
# ujusterede kurser ville trække mest fra netop den side strategien skal slå.
MARKETS: dict[str, tuple[str, str, bool]] = {
    "BTCUSDT": ("ccxt", "BTC/USDT", False),
    "ETHUSDT": ("ccxt", "ETH/USDT", False),
    "SOLUSDT": ("ccxt", "SOL/USDT", False),
    "6E": ("yfinance", "6E=F", False),
    "6B": ("yfinance", "6B=F", False),
    "GC": ("yfinance", "GC=F", False),
    "ES": ("yfinance", "ES=F", False),
    "NQ": ("yfinance", "NQ=F", False),
    "SPY": ("yfinance", "SPY", True),
    "QQQ": ("yfinance", "QQQ", True),
}

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def fetch_ccxt(symbol: str) -> pd.DataFrame:
    """Paginér Binance' 1d-OHLCV helt tilbage til listing."""
    import ccxt

    ex = ccxt.binance({"enableRateLimit": True})
    since = ex.parse8601("2010-01-01T00:00:00Z")
    rows: list[list] = []
    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe="1d", since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1][0] + 86_400_000
        if nxt <= since or len(batch) < 2:
            break
        since = nxt
        time.sleep(ex.rateLimit / 1000)
        if batch[-1][0] > ex.milliseconds():
            break

    df = pd.DataFrame(rows, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
    df = df.drop_duplicates(subset="ts").sort_values("ts")
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_localize(None)
    return df[COLUMNS].astype(float)


def fetch_yfinance(ticker: str, adjust: bool = False) -> pd.DataFrame:
    """Hele den historik Yahoo har for serien. ``adjust`` → totalafkast (se MARKETS)."""
    import yfinance as yf

    raw = yf.download(
        ticker, period="max", interval="1d",
        auto_adjust=adjust, progress=False, threads=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance gav intet for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.index = pd.to_datetime(raw.index)
    if getattr(raw.index, "tz", None) is not None:
        raw.index = raw.index.tz_localize(None)
    df = raw[COLUMNS].astype(float)
    return df[~df.index.duplicated(keep="last")].sort_index()


def clean(df: pd.DataFrame, name: str, report: dict) -> pd.DataFrame:
    """Gem RAA data. Ingen reparation her — den er en analyseparameter.

    Tidligere udvidede dette High/Low til at omslutte Open/Close. Det var forkert
    at bage ind i filerne: hver bar er BAADE reference for naeste dag OG signalbar
    mod forrige dag, saa udvidelsen goer det svaerere at feje baren som reference,
    men LETTERE for baren selv at registrere et sweep. Reparationen hoerer derfor
    hjemme i bias_engine.load_daily(repair=...), hvor den kan slaas fra og maales.
    Den udvisker desuden praecis de flade barer vi er noedt til at kunne taelle.
    """
    before = len(df)
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    report["dropped_nan"] = before - len(df)

    broken = df["High"] < df["Low"]          # aegte oedelagte — kan ikke tolkes
    report["dropped_high_lt_low"] = int(broken.sum())
    df = df[~broken]

    # Rent bogholderi: hvor mange barer VILLE reparationen roere?
    hi = df[["High", "Open", "Close"]].max(axis=1)
    lo = df[["Low", "Open", "Close"]].min(axis=1)
    touched = (hi > df["High"]) | (lo < df["Low"])
    report["repairable_bars"] = int(touched.sum())
    report["flat_bars_raw"] = int((df["High"] == df["Low"]).sum())
    report["open_eq_close_raw"] = int((df["Open"] == df["Close"]).sum())
    if touched.any():
        print(f"  {name}: {int(touched.sum())} barer har Open/Close uden for High/Low "
              f"(gemmes RAAT — reparation sker ved indlaesning)")

    today = pd.Timestamp(datetime.now(timezone.utc).date())
    if len(df) and df.index[-1] >= today:
        print(f"  {name}: droppede uafsluttet bar {df.index[-1].date()}")
        df = df[df.index < today]
        report["dropped_incomplete"] = 1
    return df


def write_csv(df: pd.DataFrame, path: Path) -> None:
    out = df.copy()
    out.insert(0, "Date", out.index.strftime("%Y.%m.%d %H:%M"))
    out.to_csv(path, sep=";", index=False, float_format="%.6g")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failures = []
    provenance: dict = {}
    for name, (source, ticker, adjust) in MARKETS.items():
        path = OUT_DIR / f"{name}_1d.csv"
        if path.exists():
            print(f"{name}: findes allerede ({path.name}) — springer over")
            continue
        print(f"{name} <- {source}:{ticker}{' (justeret)' if adjust else ''}")
        try:
            df = (fetch_ccxt(ticker) if source == "ccxt"
                  else fetch_yfinance(ticker, adjust=adjust))
            rep: dict = {"source": source, "ticker": ticker, "raw_bars": len(df),
                         "auto_adjust": adjust}
            df = clean(df, name, rep)
            if df.empty:
                raise RuntimeError("tom serie efter rensning")
            write_csv(df, path)
            rep.update(bars=len(df), first=str(df.index[0].date()), last=str(df.index[-1].date()))
            provenance[name] = rep
            print(f"  OK {len(df)} barer  {df.index[0].date()} -> {df.index[-1].date()}")
        except Exception as exc:  # noqa: BLE001 — forskningsscript, rapportér og fortsæt
            print(f"  FEJL: {type(exc).__name__}: {exc}")
            failures.append(name)
    if provenance:
        prov_path = Path(__file__).resolve().parent / "output" / "data_provenance.json"
        prov_path.parent.mkdir(parents=True, exist_ok=True)
        merged = json.loads(prov_path.read_text()) if prov_path.exists() else {}
        merged.update(provenance)
        prov_path.write_text(json.dumps(merged, indent=2, sort_keys=True))
        print(f"\nProvenans -> {prov_path}")
    if failures:
        print(f"\nFejlede: {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
