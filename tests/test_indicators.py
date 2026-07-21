import numpy as np
import pandas as pd

from data.indicators import add_adx, add_atr, add_all


def _trend_df(n: int = 300) -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=n, freq="4h")
    prices = np.linspace(100, 200, n)
    return pd.DataFrame({
        "time": times,
        "open": prices,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": np.full(n, 1000.0),
    })


class TestATR:
    def test_column_added(self):
        df = add_atr(_trend_df())
        assert "atr_14" in df.columns

    def test_atr_positive(self):
        df = add_atr(_trend_df())
        assert df["atr_14"].iloc[-1] > 0

    def test_warmup_is_nan(self):
        df = add_atr(_trend_df())
        assert np.isnan(df["atr_14"].iloc[0])


class TestADX:
    def test_columns_added(self):
        df = add_adx(_trend_df())
        for col in ("adx_14", "plus_di_14", "minus_di_14"):
            assert col in df.columns

    def test_adx_high_in_strong_trend(self):
        df = add_adx(_trend_df())
        assert df["adx_14"].iloc[-1] > 25

    def test_adx_in_range(self):
        df = add_adx(_trend_df())
        last = df["adx_14"].iloc[-1]
        assert 0 <= last <= 100


def test_add_all_includes_regime_indicators():
    df = add_all(_trend_df())
    for col in ("atr_14", "adx_14", "ema_20"):
        assert col in df.columns
