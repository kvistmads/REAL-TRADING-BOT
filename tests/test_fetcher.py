"""
Tests for data/fetcher.py — Phase 6 Del A: forex/gold via yfinance.

Ingen netværk: yf.download mockes overalt. De tre forex/gold-symboler skal
hente fra yfinance med SAMME CME-futures-mapping og samme 1h→4h-resample som
backtest/runner.py, så live-signaler beregnes på de samme barer som backtesten.
"""
from __future__ import annotations

import inspect

import pandas as pd
import pytest

from data.fetcher import (
    YFINANCE_SYMBOL_MAP,
    DataFetcher,
    _fetch_yfinance,
    _yf_period,
)
from data.mt5_fetcher import MT5Fetcher


def _raw(n: int = 8, tz: str | None = "UTC", multiindex: bool = True,
         ticker: str = "6E=F") -> pd.DataFrame:
    """Efterligner yfinance-output: tz-aware DatetimeIndex + MultiIndex-kolonner."""
    idx = pd.date_range("2026-07-01 00:00", periods=n, freq="1h", tz=tz)
    closes = [float(i + 1) for i in range(n)]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 0.5 for c in closes],
            "Low": [c - 0.5 for c in closes],
            "Close": closes,
            "Volume": [100.0] * n,
        },
        index=idx,
    )
    if multiindex:
        df.columns = pd.MultiIndex.from_product([df.columns, [ticker]])
    return df


def _patch_download(monkeypatch, result=None, exc: Exception | None = None) -> dict:
    """Mock yf.download og returnér en dict med de fangede args/kwargs."""
    captured: dict = {}

    def fake_download(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        if exc is not None:
            raise exc
        return _raw() if result is None else result

    monkeypatch.setattr("yfinance.download", fake_download)
    return captured


class TestSymbolMapping:
    @pytest.mark.parametrize(
        "symbol,ticker",
        [("EUR/USD", "6E=F"), ("GBP/USD", "6B=F"), ("XAU/USD", "GC=F")],
    )
    def test_forex_og_gold_mapper_til_cme_futures(self, monkeypatch, symbol, ticker):
        captured = _patch_download(monkeypatch)
        df = _fetch_yfinance(symbol, "4h", 50)
        assert df is not None
        assert captured["args"][0] == ticker

    def test_mapping_er_identisk_med_backtest_runner(self):
        """Non-negotiable constraint: samme datakilde og mapping i live og backtest."""
        from backtest.runner import YFINANCE_MAP

        assert YFINANCE_MAP is YFINANCE_SYMBOL_MAP

    def test_crypto_ruter_ikke_til_yfinance(self, monkeypatch):
        captured = _patch_download(monkeypatch)
        assert _fetch_yfinance("BTC/USDT", "4h", 50) is None
        assert captured == {}


class TestDownloadKwargs:
    def test_4h_hentes_som_1h_interval(self, monkeypatch):
        captured = _patch_download(monkeypatch)
        _fetch_yfinance("EUR/USD", "4h", 50)
        assert captured["kwargs"]["interval"] == "1h"
        assert captured["kwargs"]["auto_adjust"] is True
        assert captured["kwargs"]["progress"] is False

    def test_kwargs_er_gyldige_i_yfinance_api(self, monkeypatch):
        """Regression: et ukendt kwarg (fx multi_level_col) ville ryge i except-blokken
        og få _fetch_yfinance til ALTID at returnere None — uden at nogen test faldt."""
        import yfinance as yf

        captured = _patch_download(monkeypatch)
        _fetch_yfinance("EUR/USD", "4h", 50)
        # bind() rejser TypeError hvis vi sender et kwarg yfinance ikke kender.
        inspect.signature(yf.download).bind(*captured["args"], **captured["kwargs"])

    def test_period_daekker_det_oenskede_antal_barer(self, monkeypatch):
        captured = _patch_download(monkeypatch)
        _fetch_yfinance("EUR/USD", "4h", 500)
        # 500 4h-barer = 2000 1h-barer ≈ 84 døgn handel → ~142 kalenderdage med buffer.
        assert int(captured["kwargs"]["period"].rstrip("d")) >= 84

    def test_period_kappes_til_yfinance_graense(self):
        assert _yf_period("1m", 100_000) == "7d"      # 1m: max 7 dage
        assert _yf_period("1h", 100_000) == "730d"    # intraday: max 730 dage


class TestNormalisering:
    def test_1h_resamples_til_4h(self, monkeypatch):
        _patch_download(monkeypatch, result=_raw(n=8))
        df = _fetch_yfinance("EUR/USD", "4h", 50)
        assert len(df) == 2
        first = df.iloc[0]
        assert first["open"] == 1.0        # first
        assert first["high"] == 4.5        # max
        assert first["low"] == 0.5         # min
        assert first["close"] == 4.0       # last
        assert first["volume"] == 400.0    # sum
        assert df.iloc[1]["close"] == 8.0

    def test_1h_timeframe_resamples_ikke(self, monkeypatch):
        _patch_download(monkeypatch, result=_raw(n=8))
        df = _fetch_yfinance("EUR/USD", "1h", 50)
        assert len(df) == 8

    def test_kolonneformat_matcher_ccxt_og_mt5(self, monkeypatch):
        _patch_download(monkeypatch)
        df = _fetch_yfinance("EUR/USD", "4h", 50)
        assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]
        assert df.index.tolist() == [0, 1]
        # time er tz-naiv, som i crypto- og MT5-pathen.
        assert df["time"].dt.tz is None

    def test_tz_naivt_index_haandteres(self, monkeypatch):
        _patch_download(monkeypatch, result=_raw(n=8, tz=None))
        df = _fetch_yfinance("EUR/USD", "4h", 50)
        assert df["time"].dt.tz is None
        assert len(df) == 2

    def test_flade_kolonner_haandteres(self, monkeypatch):
        _patch_download(monkeypatch, result=_raw(n=8, multiindex=False))
        df = _fetch_yfinance("EUR/USD", "4h", 50)
        assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]

    def test_limit_klipper_til_seneste_barer(self, monkeypatch):
        _patch_download(monkeypatch, result=_raw(n=8))
        df = _fetch_yfinance("EUR/USD", "4h", 1)
        assert len(df) == 1
        assert df.iloc[0]["close"] == 8.0  # seneste bar, ikke den første


class TestFejlhaandtering:
    def test_tom_dataframe_returnerer_none(self, monkeypatch, caplog):
        _patch_download(monkeypatch, result=pd.DataFrame())
        with caplog.at_level("WARNING"):
            assert _fetch_yfinance("EUR/USD", "4h", 50) is None
        assert "ingen data" in caplog.text

    def test_exception_returnerer_none_og_logger_warning(self, monkeypatch, caplog):
        _patch_download(monkeypatch, exc=RuntimeError("netværk nede"))
        with caplog.at_level("WARNING"):
            assert _fetch_yfinance("EUR/USD", "4h", 50) is None
        assert "netværk nede" in caplog.text

    def test_uventet_kolonneformat_returnerer_none(self, monkeypatch, caplog):
        _patch_download(monkeypatch, result=pd.DataFrame({"foo": [1.0]}))
        with caplog.at_level("WARNING"):
            assert _fetch_yfinance("EUR/USD", "4h", 50) is None

    def test_ukendt_timeframe_returnerer_none(self, monkeypatch, caplog):
        captured = _patch_download(monkeypatch)
        with caplog.at_level("WARNING"):
            assert _fetch_yfinance("EUR/USD", "3m", 50) is None
        assert captured == {}


# ---------------------------------------------------------------------------
# DataFetcher-routing
# ---------------------------------------------------------------------------

class FakeExchange:
    def __init__(self, last: float | None = 27000.0, exc: Exception | None = None):
        self.last = last
        self.exc = exc
        self.ohlcv_calls: list[tuple] = []
        self.ticker_calls: list[str] = []

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500):
        self.ohlcv_calls.append((symbol, timeframe, limit))
        return pd.DataFrame({
            "time": pd.date_range("2026-07-01", periods=3, freq="4h"),
            "open": [1.0, 2.0, 3.0], "high": [1.0, 2.0, 3.0],
            "low": [1.0, 2.0, 3.0], "close": [1.0, 2.0, 3.0],
            "volume": [10.0, 10.0, 10.0],
        })

    async def fetch_ticker(self, symbol: str) -> dict:
        self.ticker_calls.append(symbol)
        if self.exc is not None:
            raise self.exc
        return {"last": self.last}


def _fetcher(monkeypatch, exchange: FakeExchange, mt5_available: bool = False) -> DataFetcher:
    """DataFetcher uden MT5-terminal (som på macOS/Linux) medmindre andet ønskes."""
    monkeypatch.setattr(MT5Fetcher, "initialize", lambda self: mt5_available)
    fetcher = DataFetcher(exchange, {})
    fetcher.mt5_available = mt5_available
    return fetcher


def _patch_yf_helper(monkeypatch, result=None) -> list[tuple]:
    """Mock data.fetcher._fetch_yfinance og returnér listen af kald."""
    calls: list[tuple] = []

    def fake(symbol, timeframe, limit):
        calls.append((symbol, timeframe, limit))
        return result

    monkeypatch.setattr("data.fetcher._fetch_yfinance", fake)
    return calls


def _bars(close: float = 1.0855) -> pd.DataFrame:
    return pd.DataFrame({
        "time": pd.date_range("2026-07-01", periods=2, freq="1h"),
        "open": [close, close], "high": [close, close], "low": [close, close],
        "close": [close, close], "volume": [1.0, 1.0],
    })


class TestGetOhlcvRouting:
    @pytest.mark.asyncio
    async def test_forex_hentes_fra_yfinance_ikke_mt5(self, monkeypatch):
        exchange = FakeExchange()
        fetcher = _fetcher(monkeypatch, exchange)
        calls = _patch_yf_helper(monkeypatch, result=_bars())

        df = await fetcher.get_ohlcv("EUR/USD", "4h", 50)

        assert df is not None and len(df) == 2
        assert calls == [("EUR/USD", "4h", 50)]
        assert exchange.ohlcv_calls == []

    @pytest.mark.asyncio
    async def test_gold_hentes_fra_yfinance(self, monkeypatch):
        fetcher = _fetcher(monkeypatch, FakeExchange())
        calls = _patch_yf_helper(monkeypatch, result=_bars(3400.0))
        assert await fetcher.get_ohlcv("XAU/USD", "4h", 50) is not None
        assert calls == [("XAU/USD", "4h", 50)]

    @pytest.mark.asyncio
    async def test_crypto_ruter_til_exchange(self, monkeypatch):
        exchange = FakeExchange()
        fetcher = _fetcher(monkeypatch, exchange)
        calls = _patch_yf_helper(monkeypatch, result=_bars())

        df = await fetcher.get_ohlcv("BTC/USDT", "4h", 50)

        assert df is not None
        assert exchange.ohlcv_calls == [("BTC/USDT", "4h", 50)]
        assert calls == []

    @pytest.mark.asyncio
    async def test_yfinance_fejl_returnerer_none_og_cacher_ikke(self, monkeypatch):
        fetcher = _fetcher(monkeypatch, FakeExchange())
        calls = _patch_yf_helper(monkeypatch, result=None)

        assert await fetcher.get_ohlcv("EUR/USD", "4h", 50) is None
        assert await fetcher.get_ohlcv("EUR/USD", "4h", 50) is None
        assert len(calls) == 2  # intet cachet → nyt forsøg næste tick

    @pytest.mark.asyncio
    async def test_cache_genbruges_inden_for_timeframe(self, monkeypatch):
        fetcher = _fetcher(monkeypatch, FakeExchange())
        calls = _patch_yf_helper(monkeypatch, result=_bars())

        await fetcher.get_ohlcv("EUR/USD", "4h", 50)
        await fetcher.get_ohlcv("EUR/USD", "4h", 50)

        assert len(calls) == 1


class TestGetLatestPrice:
    @pytest.mark.asyncio
    async def test_crypto_bruger_ticker(self, monkeypatch):
        exchange = FakeExchange(last=27123.5)
        fetcher = _fetcher(monkeypatch, exchange)
        assert await fetcher.get_latest_price("BTC/USDT") == 27123.5
        assert exchange.ticker_calls == ["BTC/USDT"]

    @pytest.mark.asyncio
    async def test_crypto_ticker_fejl_returnerer_none(self, monkeypatch):
        fetcher = _fetcher(monkeypatch, FakeExchange(exc=RuntimeError("børs nede")))
        assert await fetcher.get_latest_price("BTC/USDT") is None

    @pytest.mark.asyncio
    async def test_forex_uden_mt5_bruger_seneste_yfinance_close(self, monkeypatch):
        fetcher = _fetcher(monkeypatch, FakeExchange(), mt5_available=False)
        calls = _patch_yf_helper(monkeypatch, result=_bars(1.0855))

        assert await fetcher.get_latest_price("EUR/USD") == pytest.approx(1.0855)
        # 1h-barer, ikke det 4-timers tick-timeframe → prisen er højst 1 time gammel.
        assert calls == [("EUR/USD", "1h", 2)]

    @pytest.mark.asyncio
    async def test_forex_med_mt5_foretraekker_tick(self, monkeypatch):
        fetcher = _fetcher(monkeypatch, FakeExchange(), mt5_available=True)
        monkeypatch.setattr(fetcher.mt5, "get_tick_price", lambda symbol: 1.0900)
        calls = _patch_yf_helper(monkeypatch, result=_bars(1.0855))

        assert await fetcher.get_latest_price("EUR/USD") == pytest.approx(1.0900)
        assert calls == []

    @pytest.mark.asyncio
    async def test_forex_falder_tilbage_naar_mt5_tick_er_none(self, monkeypatch):
        fetcher = _fetcher(monkeypatch, FakeExchange(), mt5_available=True)
        monkeypatch.setattr(fetcher.mt5, "get_tick_price", lambda symbol: None)
        _patch_yf_helper(monkeypatch, result=_bars(1.0855))

        assert await fetcher.get_latest_price("EUR/USD") == pytest.approx(1.0855)

    @pytest.mark.asyncio
    async def test_forex_uden_data_returnerer_none(self, monkeypatch):
        fetcher = _fetcher(monkeypatch, FakeExchange())
        _patch_yf_helper(monkeypatch, result=None)
        assert await fetcher.get_latest_price("EUR/USD") is None
