# Notes — Forex/Gold Live Fetcher Fix

(Gemmet fra PRD_PHASE6_FIXES.md til brug i næste PRD)

> **Status: implementeret 2026-07-30** (Phase 6 Del A) — se `PRD_PHASE6_FIXES.md` for den
> faktiske implementation. Skitsen herunder havde tre fejl: `multi_level_col` er ikke et
> gyldigt yfinance-kwarg (fetcheren ville altid returnere `None`), 4h skal resamples fra
> 1h ellers kører live på andre barer end backtesten, og tick-prisen manglede — uden den
> droppes forex-signaler stadig i gate-pipelinen. Beholdt som historik.

## Problem
`data/fetcher.py` sender EUR/USD, GBP/USD og XAU/USD til MT5 (kun Windows).
Tre af seks symboler handler aldrig på Mac/Linux.

Backtest/runner.py håndterer dette korrekt med yfinance + CME-futures-mapping:
```
EUR/USD  → 6E=F
GBP/USD  → 6B=F
XAU/USD  → GC=F
```

## Løsning
Erstat MT5-kaldet i `data/fetcher.py` med yfinance for ikke-crypto-symboler.
Logikken skal være **identisk** med hvad backtest-runner'en allerede gør.

```python
YFINANCE_SYMBOL_MAP: dict[str, str] = {
    "EUR/USD": "6E=F",
    "GBP/USD": "6B=F",
    "XAU/USD": "GC=F",
}

def _fetch_yfinance(symbol: str, timeframe: str, limit: int) -> pd.DataFrame | None:
    import yfinance as yf
    ticker = YFINANCE_SYMBOL_MAP.get(symbol)
    if ticker is None:
        return None
    tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "4h": "1h", "1d": "1d"}
    interval = tf_map.get(timeframe, "1h")
    period_map = {"1m": "7d", "5m": "7d", "15m": "7d", "60m": "30d", "1h": "30d", "1d": "90d"}
    period = period_map.get(interval, "30d")
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         auto_adjust=True, progress=False, multi_level_col=False)
        if df.empty:
            return None
        df = df[["Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower)
        df.index = pd.to_datetime(df.index, utc=True)
        return df.tail(limit)
    except Exception as exc:
        logger.warning("yfinance fetch fejlede for %s: %s", symbol, exc)
        return None
```

I `fetch_ohlcv()`: tjek `symbol in YFINANCE_SYMBOL_MAP` → kald `_fetch_yfinance()` → ingen MT5-fallback.

## Test-krav
- Mock `yf.download`, verificér symbol-mapping
- Tom DataFrame → returnerer None
- Exception → returnerer None + logger warning
- Crypto-symboler ruter IKKE til yfinance
