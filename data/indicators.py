import numpy as np
import pandas as pd


def add_rsi(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=length - 1, min_periods=length).mean()
    avg_loss = loss.ewm(com=length - 1, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df[f"rsi_{length}"] = 100 - (100 / (1 + rs))
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    # Samme kolonnenavne som pandas-ta
    df[f"MACD_{fast}_{slow}_{signal}"] = macd_line
    df[f"MACDs_{fast}_{slow}_{signal}"] = signal_line
    df[f"MACDh_{fast}_{slow}_{signal}"] = histogram
    return df


def add_bollinger(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> pd.DataFrame:
    mid = df["close"].rolling(length).mean()
    sigma = df["close"].rolling(length).std(ddof=0)
    # Samme kolonnenavne som pandas-ta
    df[f"BBM_{length}_{std}"] = mid
    df[f"BBU_{length}_{std}"] = mid + std * sigma
    df[f"BBL_{length}_{std}"] = mid - std * sigma
    return df


def add_ema(df: pd.DataFrame, lengths: list = None) -> pd.DataFrame:
    if lengths is None:
        lengths = [20, 50, 200]
    for length in lengths:
        df[f"ema_{length}"] = df["close"].ewm(span=length, adjust=False).mean()
    return df


def add_volume_sma(df: pd.DataFrame, length: int = 20) -> pd.DataFrame:
    df[f"volume_sma_{length}"] = df["volume"].rolling(length).mean()
    return df


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    df = add_rsi(df)
    df = add_macd(df)
    df = add_bollinger(df)
    df = add_ema(df)
    df = add_volume_sma(df)
    return df
