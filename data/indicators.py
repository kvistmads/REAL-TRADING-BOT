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


def _true_range(df: pd.DataFrame) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    return pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def add_atr(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    """Average True Range (Wilder-udjævnet via RMA/ewm alpha=1/length)."""
    tr = _true_range(df)
    df[f"atr_{length}"] = tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    return df


def add_adx(df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
    """Average Directional Index (Wilder). Tilføjer adx_{length}, plus_di_{length}, minus_di_{length}."""
    alpha = 1 / length
    tr = _true_range(df)
    atr = tr.ewm(alpha=alpha, min_periods=length, adjust=False).mean()

    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index
    )

    plus_di = 100 * plus_dm.ewm(alpha=alpha, min_periods=length, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=alpha, min_periods=length, adjust=False).mean() / atr
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum

    df[f"adx_{length}"] = dx.ewm(alpha=alpha, min_periods=length, adjust=False).mean()
    df[f"plus_di_{length}"] = plus_di
    df[f"minus_di_{length}"] = minus_di
    return df


def _compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Beregn alle add_*-indikatorer på en kopi (kalderens df muteres ikke)."""
    df = df.copy()
    df = add_rsi(df)
    df = add_macd(df)
    df = add_bollinger(df)
    df = add_ema(df)
    df = add_volume_sma(df)
    df = add_atr(df)
    df = add_adx(df)
    return df


# add_all er den tunge del af hvert tick (weekly-profileringen har peget på den
# tre uger i træk). Engine kalder den én gang pr. symbol og deler resultatet med
# alle strategier; cachen fanger de resterende gentagelser — fx backtestens
# suite, hvor de samme barer køres igennem for hver strategi.
_indicator_cache: dict[tuple, pd.DataFrame] = {}
_CACHE_MAX_ENTRIES = 50


def _cache_key(df: pd.DataFrame) -> tuple:
    """Nøgle der identificerer præcis dette datasæt.

    De 5 seneste barers tidsstempel + OHLCV plus rækkeantallet. Kun indekset er
    IKKE nok: to symboler hentet med samme limit har identisk RangeIndex, og
    BTC ville så få ETH's indikatorer serveret fra cachen.
    """
    tail = df.tail(5)
    stamps = tail["time"] if "time" in df.columns else tail.index.to_series()
    values = tuple(
        tuple(float(v) for v in tail[col])
        for col in ("open", "high", "low", "close", "volume")
        if col in df.columns
    )
    return (len(df), tuple(str(t) for t in stamps), values)


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Alle indikatorer på df — memoiseret på datasættets indhold.

    Returnerer den cachede ramme direkte; kalderne behandler den som read-only
    (strategierne bruger calculate_*-API'et og muterer ikke deres input).
    """
    if df is None or df.empty:
        return df

    try:
        key = _cache_key(df)
    except (TypeError, ValueError):  # uventet dtype → spring cachen over
        return _compute_all(df)

    cached = _indicator_cache.get(key)
    if cached is not None:
        return cached

    result = _compute_all(df)
    _indicator_cache[key] = result
    if len(_indicator_cache) > _CACHE_MAX_ENTRIES:
        del _indicator_cache[next(iter(_indicator_cache))]  # FIFO: ældste ryger
    return result


def clear_indicator_cache() -> None:
    """Tøm indikator-cachen (tests og langtidskørsler der skifter datasæt)."""
    _indicator_cache.clear()


# ---------------------------------------------------------------------------
# calculate_* — funktionel API brugt af de 3 composite-strategier (Phase 3).
# Returnerer Series/DataFrame i stedet for at mutere df. Ren pandas/numpy;
# matematisk identisk med add_*-helperne ovenfor (samme EWM/rolling-metoder).
# ---------------------------------------------------------------------------

def clamp(value: float, lo: float, hi: float) -> float:
    """Begræns value til [lo, hi]. Håndterer NaN → returnerer lo."""
    if value != value:  # NaN
        return lo
    return max(lo, min(hi, value))


def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
    return df["close"].ewm(span=period, adjust=False).mean()


def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26,
                   signal: int = 9) -> pd.DataFrame:
    """Kolonner: macd, macd_signal, macd_hist."""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame(
        {
            "macd": macd_line,
            "macd_signal": signal_line,
            "macd_hist": macd_line - signal_line,
        },
        index=df.index,
    )


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = _true_range(df)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def calculate_bollinger(df: pd.DataFrame, period: int = 20,
                        std: float = 2.0) -> pd.DataFrame:
    """Kolonner: bb_upper, bb_middle, bb_lower, bb_width."""
    mid = df["close"].rolling(period).mean()
    sigma = df["close"].rolling(period).std(ddof=0)
    upper = mid + std * sigma
    lower = mid - std * sigma
    width = (upper - lower) / mid.replace(0, np.nan)
    return pd.DataFrame(
        {
            "bb_upper": upper,
            "bb_middle": mid,
            "bb_lower": lower,
            "bb_width": width,
        },
        index=df.index,
    )


def calculate_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["volume"].rolling(period).mean()


def find_swing_points(series: pd.Series, window: int = 5) -> tuple[list[int], list[int]]:
    """
    Fraktal-pivots: index i er et swing high hvis series[i] er strengt større end
    de `window` barer på hver side; swing low symmetrisk med strengt mindre.
    Returnerer (swing_high_indices, swing_low_indices) i stigende rækkefølge —
    positioner er 0-baserede ift. den givne series.
    """
    values = np.asarray(series, dtype=float)
    n = len(values)
    highs: list[int] = []
    lows: list[int] = []
    for i in range(window, n - window):
        center = values[i]
        if np.isnan(center):
            continue
        left = values[i - window:i]
        right = values[i + 1:i + window + 1]
        neighbors = np.concatenate([left, right])
        if np.isnan(neighbors).any():
            continue
        if center > neighbors.max():
            highs.append(i)
        elif center < neighbors.min():
            lows.append(i)
    return highs, lows


def find_sr_levels(
    df: pd.DataFrame, lookback: int = 50, window: int = 5, ref: float | None = None
) -> dict:
    """
    Nærmeste resistance/support ift. `ref` (default: seneste close), fundet blandt
    fraktal-pivots inden for de seneste `lookback` barer. Resistance kommer fra
    swing highs i high-serien, support fra swing lows i low-serien.

    Kun pivots på den rigtige side af `ref` tæller: resistance ligger OVER ref,
    support UNDER. Uden det filter valgtes bare det nærmeste pivot uanset side, så
    et pivot på den forkerte side kunne maskere det reelle niveau. Breakout-kaldere
    skal sende prisen FØR udbruddet som `ref` — bruger man seneste close, ligger et
    netop brudt niveau pr. definition på den forkerte side og filtreres væk.

    Returnerer {'resistance': float | None, 'support': float | None}.
    """
    recent = df.iloc[-lookback:]
    if ref is None:
        ref = float(recent["close"].iloc[-1])

    swing_highs, _ = find_swing_points(recent["high"], window)
    _, swing_lows = find_swing_points(recent["low"], window)

    high_vals = recent["high"].to_numpy(dtype=float)
    low_vals = recent["low"].to_numpy(dtype=float)
    above = [high_vals[i] for i in swing_highs if high_vals[i] > ref]
    below = [low_vals[i] for i in swing_lows if low_vals[i] < ref]

    # Nærmeste på hver side: laveste pivot over ref, højeste pivot under ref.
    resistance = float(min(above)) if above else None
    support = float(max(below)) if below else None

    return {"resistance": resistance, "support": support}
