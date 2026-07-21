import numpy as np
import pandas as pd


def _base_df(n: int = 200) -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=n, freq="4h")
    return pd.DataFrame({"time": times, "volume": np.random.uniform(1000, 5000, n)})


def make_bullish_df(n: int = 200) -> pd.DataFrame:
    """Faldende pris med RSI-divergens setup — pris laver lower low, RSI laver higher low."""
    df = _base_df(n)
    prices = np.linspace(50000, 45000, n) + np.random.normal(0, 200, n)
    # Sidste bar: endnu lavere pris end n-10 bar, men RSI skal være højere
    prices[-1] = prices[-10] * 0.995  # lower low
    df["open"] = prices * 0.999
    df["high"] = prices * 1.002
    df["low"] = prices * 0.997
    df["close"] = prices
    return df


def make_bearish_df(n: int = 200) -> pd.DataFrame:
    """Stigende pris med bearish RSI-divergens setup."""
    df = _base_df(n)
    prices = np.linspace(45000, 55000, n) + np.random.normal(0, 200, n)
    prices[-1] = prices[-10] * 1.005  # higher high
    df["open"] = prices * 0.999
    df["high"] = prices * 1.002
    df["low"] = prices * 0.997
    df["close"] = prices
    return df


def make_squeeze_df(n: int = 200, breakout_direction: str = "long") -> pd.DataFrame:
    """Bollinger squeeze setup med breakout."""
    df = _base_df(n)
    # Flad pris → tætte bands (squeeze)
    prices = np.ones(n) * 50000 + np.random.normal(0, 50, n)
    if breakout_direction == "long":
        prices[-1] = 50000 * 1.025  # breakout over upper band
    else:
        prices[-1] = 50000 * 0.975  # breakout under lower band
    df["open"] = prices * 0.999
    df["high"] = prices * (1.001 if breakout_direction == "long" else 1.0005)
    df["low"] = prices * (0.999 if breakout_direction == "short" else 0.9995)
    df["close"] = prices
    return df


def make_flat_df(n: int = 200) -> pd.DataFrame:
    """Sideways marked — ingen klare signaler."""
    df = _base_df(n)
    prices = np.ones(n) * 50000 + np.random.normal(0, 30, n)
    df["open"] = prices * 0.9995
    df["high"] = prices * 1.001
    df["low"] = prices * 0.999
    df["close"] = prices
    return df


def make_macd_crossover_df(n: int = 200, direction: str = "long") -> pd.DataFrame:
    """MACD crossover med volume spike."""
    df = _base_df(n)
    if direction == "long":
        prices = np.concatenate([
            np.linspace(50000, 48000, n - 10),
            np.linspace(48000, 49500, 10),
        ])
    else:
        prices = np.concatenate([
            np.linspace(48000, 50000, n - 10),
            np.linspace(50000, 48500, 10),
        ])
    df["open"] = prices * 0.999
    df["high"] = prices * 1.002
    df["low"] = prices * 0.997
    df["close"] = prices
    # Volume spike på de sidste bars
    df["volume"] = np.random.uniform(1000, 2000, n)
    df.loc[df.index[-3:], "volume"] = 8000  # 4x normalt
    return df
