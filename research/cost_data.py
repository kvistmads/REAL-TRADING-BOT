"""Datahentning til omkostningsanalysen — flere timeframes, samme symboler.

Krypto hentes fra Binance via ccxt; futures fra yfinance. Yahoo capper intraday:
**15m rækker kun 60 dage tilbage, 1h rækker 730.** Det er ikke til at komme udenom,
og det står i rapporten frem for at blive skjult i et gennemsnit.
"""

from __future__ import annotations

import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from backtest.runner import fetch_crypto_ohlcv  # noqa: E402
from data.fetcher import YFINANCE_SYMBOL_MAP as YF_MAP  # noqa: E402

TIMEFRAMES = ("5m", "15m", "1h", "4h")

# Antal barer vi henter pr. timeframe for krypto. Nok til et stabilt medianestimat
# uden at paginere i evigheder.
CRYPTO_LIMIT = {"5m": 8000, "15m": 8000, "1h": 6000, "4h": 4400}

# yfinance' egne grænser for intraday-historik.
YF_PERIOD = {"5m": "60d", "15m": "60d", "1h": "730d", "4h": "730d"}


def fetch(symbol: str, timeframe: str, attempts: int = 3) -> pd.DataFrame:
    """OHLCV for ét symbol og én timeframe. Tom df hvis kilden ikke kan levere.

    Retry med backoff, som ``data/fetcher.py`` gør: en enkelt netværkstimeout hos
    Binance skal ikke koste en analysekørsel der tager flere minutter. Efter sidste
    forsøg returneres en tom df, og symbolet udelades af tabellen frem for at
    stoppe hele kørslen.
    """
    import time

    for attempt in range(attempts):
        try:
            if symbol in YF_MAP:
                return _fetch_yf(symbol, timeframe)
            return fetch_crypto_ohlcv(symbol, timeframe,
                                      limit=CRYPTO_LIMIT.get(timeframe, 5000))
        except Exception as exc:  # noqa: BLE001 — forskningsscript: rapportér og fortsæt
            if attempt == attempts - 1:
                print(f"    {symbol} {timeframe}: opgiver efter {attempts} forsøg "
                      f"({type(exc).__name__})")
                return pd.DataFrame(
                    columns=["time", "open", "high", "low", "close", "volume"])
            time.sleep(2 ** attempt * 2)
    return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])


def _fetch_yf(symbol: str, timeframe: str) -> pd.DataFrame:
    import yfinance as yf

    ticker = YF_MAP[symbol]
    # yfinance har ingen 4h-bar: hent 1h og resample, som resten af projektet gør.
    interval = "1h" if timeframe == "4h" else timeframe
    raw = yf.download(ticker, period=YF_PERIOD[timeframe], interval=interval,
                      auto_adjust=True, progress=False, threads=False)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if timeframe == "4h":
        raw = raw.resample("4h").agg({"Open": "first", "High": "max", "Low": "min",
                                      "Close": "last", "Volume": "sum"}).dropna()
    raw.columns = [c.lower() for c in raw.columns]
    df = raw.reset_index()
    df = df.rename(columns={df.columns[0]: "time"})
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    return df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    """Median ATR(14) i procent af close — grundlaget for 1R.

    Median frem for gennemsnit: ATR-fordelingen har en lang hale i stressede
    perioder, og et gennemsnit ville gøre den typiske handel dyrere end den er.
    """
    from data.indicators import calculate_atr

    if df.empty or len(df) < period + 5:
        return float("nan")
    atr = calculate_atr(df, period)
    return float((atr / df["close"] * 100).median())
