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
    _fetch_with_retry,
    _fetch_with_retry_async,
    _fetch_yfinance,
    _validate_ohlcv,
    _yf_period,
)
from data.mt5_fetcher import MT5Fetcher


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """Retry-backoff'en er 2s/4s i produktion — nulstil den så tests er hurtige."""
    monkeypatch.setattr("data.fetcher.RETRY_BASE_DELAY", 0.0)


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


# ---------------------------------------------------------------------------
# Retry + validering (Ændring 5)
# ---------------------------------------------------------------------------

class TestRetry:
    def test_returnerer_resultat_uden_fejl(self):
        assert _fetch_with_retry(lambda: "ok") == "ok"

    def test_succes_efter_et_fejlet_forsoeg(self):
        calls: list[int] = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("timeout")
            return "ok"

        assert _fetch_with_retry(flaky, base_delay=0.0) == "ok"
        assert len(calls) == 2

    def test_giver_op_efter_max_forsoeg(self):
        calls: list[int] = []

        def always_fails():
            calls.append(1)
            raise RuntimeError("børs nede")

        with pytest.raises(RuntimeError, match="børs nede"):
            _fetch_with_retry(always_fails, base_delay=0.0)
        assert len(calls) == 3

    def test_backoff_er_eksponentiel(self, monkeypatch):
        delays: list[float] = []
        monkeypatch.setattr("data.fetcher.time.sleep", lambda d: delays.append(d))

        with pytest.raises(RuntimeError):
            _fetch_with_retry(_raiser, base_delay=2.0)
        assert delays == [2.0, 4.0]

    @pytest.mark.asyncio
    async def test_async_variant_prøver_igen(self):
        calls: list[int] = []

        async def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("netværk")
            return "ok"

        assert await _fetch_with_retry_async(flaky, base_delay=0.0) == "ok"
        assert len(calls) == 3


def _raiser():
    raise RuntimeError("altid galt")


class TestValidering:
    def _df(self, **overrides) -> pd.DataFrame:
        df = pd.DataFrame({
            "time": pd.date_range("2026-07-01", periods=3, freq="4h"),
            "open": [1.0, 2.0, 3.0], "high": [1.5, 2.5, 3.5],
            "low": [0.5, 1.5, 2.5], "close": [1.0, 2.0, 3.0],
            "volume": [10.0, 11.0, 12.0],
        })
        for col, values in overrides.items():
            df[col] = values
        return df

    def test_gyldig_ramme_godkendes(self):
        assert _validate_ohlcv(self._df(), "BTC/USDT") is True

    def test_none_afvises(self):
        assert _validate_ohlcv(None, "BTC/USDT") is False

    def test_tom_dataframe_afvises(self, caplog):
        with caplog.at_level("WARNING"):
            assert _validate_ohlcv(pd.DataFrame(), "BTC/USDT") is False
        assert "Tom OHLCV-respons" in caplog.text

    def test_nan_i_close_afvises(self, caplog):
        with caplog.at_level("WARNING"):
            assert _validate_ohlcv(self._df(close=[1.0, float("nan"), 3.0]), "BTC/USDT") is False
        assert "NaN i kolonne 'close'" in caplog.text

    def test_manglende_volume_afvises(self, caplog):
        df = self._df().drop(columns=["volume"])
        with caplog.at_level("WARNING"):
            assert _validate_ohlcv(df, "BTC/USDT") is False
        assert "Mangler kolonne 'volume'" in caplog.text

    def test_ikke_monotone_timestamps_afvises(self, caplog):
        df = self._df()
        df.loc[2, "time"] = pd.Timestamp("2026-06-01")
        with caplog.at_level("WARNING"):
            assert _validate_ohlcv(df, "BTC/USDT") is False
        assert "monotont stigende" in caplog.text


class TestGetOhlcvFailSafe:
    @pytest.mark.asyncio
    async def test_nan_i_data_returnerer_none(self, monkeypatch):
        bars = _bars()
        bars.loc[1, "close"] = float("nan")
        fetcher = _fetcher(monkeypatch, FakeExchange())
        _patch_yf_helper(monkeypatch, result=bars)

        assert await fetcher.get_ohlcv("EUR/USD", "4h", 50) is None

    @pytest.mark.asyncio
    async def test_ugyldige_data_caches_ikke(self, monkeypatch):
        bars = _bars()
        bars.loc[1, "close"] = float("nan")
        fetcher = _fetcher(monkeypatch, FakeExchange())
        calls = _patch_yf_helper(monkeypatch, result=bars)

        await fetcher.get_ohlcv("EUR/USD", "4h", 50)
        await fetcher.get_ohlcv("EUR/USD", "4h", 50)

        assert len(calls) == 2  # nyt forsøg næste tick, intet cachet

    @pytest.mark.asyncio
    async def test_ikke_monotone_barer_returnerer_none(self, monkeypatch):
        bars = _bars()
        bars.loc[1, "time"] = pd.Timestamp("2026-06-01")
        fetcher = _fetcher(monkeypatch, FakeExchange())
        _patch_yf_helper(monkeypatch, result=bars)

        assert await fetcher.get_ohlcv("EUR/USD", "4h", 50) is None

    @pytest.mark.asyncio
    async def test_crypto_fetch_prøver_igen_og_lykkes(self, monkeypatch):
        exchange = FakeExchange()
        calls: list[int] = []
        original = exchange.fetch_ohlcv

        async def flaky(symbol, timeframe, limit=500):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("502 Bad Gateway")
            return await original(symbol, timeframe, limit)

        exchange.fetch_ohlcv = flaky
        fetcher = _fetcher(monkeypatch, exchange)

        df = await fetcher.get_ohlcv("BTC/USDT", "4h", 50)

        assert df is not None and len(df) == 3
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_crypto_fetch_giver_op_og_returnerer_none(self, monkeypatch):
        exchange = FakeExchange()

        async def always_fails(symbol, timeframe, limit=500):
            raise RuntimeError("børs nede")

        exchange.fetch_ohlcv = always_fails
        fetcher = _fetcher(monkeypatch, exchange)

        assert await fetcher.get_ohlcv("BTC/USDT", "4h", 50) is None

    @pytest.mark.asyncio
    async def test_get_multi_udelader_symboler_uden_valid_data(self, monkeypatch, caplog):
        fetcher = _fetcher(monkeypatch, FakeExchange())
        _patch_yf_helper(monkeypatch, result=None)

        with caplog.at_level("WARNING"):
            out = await fetcher.get_multi(["BTC/USDT", "EUR/USD"], "4h")

        assert list(out) == ["BTC/USDT"]
        assert "Springer EUR/USD over" in caplog.text

    @pytest.mark.asyncio
    async def test_ticker_prøver_igen_før_den_giver_op(self, monkeypatch):
        exchange = FakeExchange()
        calls: list[int] = []

        async def flaky(symbol):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("timeout")
            return {"last": 27123.5}

        exchange.fetch_ticker = flaky
        fetcher = _fetcher(monkeypatch, exchange)

        assert await fetcher.get_latest_price("BTC/USDT") == 27123.5
        assert len(calls) == 2
