from unittest.mock import MagicMock

import numpy as np
import pytest

import data.mt5_fetcher as mt5_mod
from data.mt5_fetcher import MT5Fetcher


def _fake_rates(n: int = 300):
    dtype = [
        ("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
        ("close", "f8"), ("tick_volume", "i8"), ("spread", "i8"), ("real_volume", "i8"),
    ]
    start = 1_609_459_200  # 2021-01-01
    return np.array(
        [(start + i * 14400, 1.10, 1.12, 1.09, 1.11, 500, 2, 0) for i in range(n)],
        dtype=dtype,
    )


@pytest.fixture
def fake_mt5(monkeypatch):
    mock = MagicMock()
    mock.initialize.return_value = True
    mock.copy_rates_from_pos.return_value = _fake_rates()
    monkeypatch.setattr(mt5_mod, "mt5", mock)
    return mock


class TestMT5Fetcher:
    def test_is_forex(self):
        assert MT5Fetcher.is_forex("EUR/USD")
        assert MT5Fetcher.is_forex("XAU/USD")
        assert not MT5Fetcher.is_forex("BTC/USDT")

    def test_get_ohlcv_returns_correct_columns(self, fake_mt5):
        fetcher = MT5Fetcher()
        assert fetcher.initialize() is True
        df = fetcher.get_ohlcv("EUR/USD", "4h", limit=300)
        assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]
        assert len(df) == 300
        # tick_volume skal være mappet til volume
        assert df["volume"].iloc[0] == 500

    def test_maps_ccxt_symbol_to_mt5(self, fake_mt5):
        fetcher = MT5Fetcher()
        fetcher.initialize()
        fetcher.get_ohlcv("EUR/USD", "4h")
        called_symbol = fake_mt5.copy_rates_from_pos.call_args[0][0]
        assert called_symbol == "EURUSD"

    def test_fallback_when_package_missing(self, monkeypatch):
        monkeypatch.setattr(mt5_mod, "mt5", None)
        fetcher = MT5Fetcher()
        assert fetcher.initialize() is False
        assert fetcher.get_ohlcv("EUR/USD", "4h") is None

    def test_get_ohlcv_none_when_not_initialized(self, fake_mt5):
        fetcher = MT5Fetcher()  # initialize() ikke kaldt
        assert fetcher.get_ohlcv("EUR/USD", "4h") is None

    def test_no_data_returns_none(self, fake_mt5):
        fake_mt5.copy_rates_from_pos.return_value = np.array([], dtype=[("time", "i8")])
        fetcher = MT5Fetcher()
        fetcher.initialize()
        assert fetcher.get_ohlcv("EUR/USD", "4h") is None
