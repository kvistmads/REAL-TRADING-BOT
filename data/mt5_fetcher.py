from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# MetaTrader5-pakken er Windows-only. På macOS/Linux findes ingen wheel, så
# importen fejler — den håndteres gracefully og botten skipper forex/gold.
try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - platform-afhængigt
    mt5 = None


class MT5Fetcher:
    # ccxt-format → MT5-format
    FOREX_SYMBOLS = {
        "EUR/USD": "EURUSD",
        "GBP/USD": "GBPUSD",
        "XAU/USD": "XAUUSD",
    }

    # ccxt-timeframe → navn på MT5-konstant (slås op via getattr så modulet
    # kan importeres selv når MetaTrader5 ikke er installeret).
    _TF_NAMES = {
        "1h": "TIMEFRAME_H1",
        "4h": "TIMEFRAME_H4",
        "1d": "TIMEFRAME_D1",
    }

    def __init__(self):
        self._initialized = False

    @classmethod
    def is_forex(cls, symbol: str) -> bool:
        return symbol in cls.FOREX_SYMBOLS

    def initialize(self) -> bool:
        """Starter MT5-forbindelsen. Returnerer False hvis pakken mangler eller terminal ikke kører."""
        if mt5 is None:
            logger.warning(
                "MetaTrader5-pakken er ikke tilgængelig (Windows-only) — forex/gold skippes"
            )
            return False
        if not mt5.initialize():
            logger.warning(f"MT5 initialize() fejlede: {mt5.last_error()} — forex/gold skippes")
            return False
        self._initialized = True
        logger.info("MT5-forbindelse etableret")
        return True

    def _resolve_tf(self, timeframe: str):
        name = self._TF_NAMES.get(timeframe)
        if name is None or mt5 is None:
            return None
        return getattr(mt5, name, None)

    def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame | None:
        """
        Henter OHLCV fra MT5. Returnerer DataFrame med kolonner:
        time, open, high, low, close, volume — identisk format som DataFetcher/ccxt.
        Returnerer None ved fejl (aldrig exception).
        """
        if not self._initialized or mt5 is None:
            logger.warning(f"MT5 ikke initialiseret — skipper {symbol}")
            return None

        mt5_symbol = self.FOREX_SYMBOLS.get(symbol, symbol)
        tf = self._resolve_tf(timeframe)
        if tf is None:
            logger.warning(f"Ukendt MT5-timeframe: {timeframe}")
            return None

        try:
            rates = mt5.copy_rates_from_pos(mt5_symbol, tf, 0, limit)
        except Exception as e:  # pragma: no cover - MT5 runtime-fejl
            logger.warning(f"MT5 copy_rates fejlede for {symbol}: {e}")
            return None

        if rates is None or len(rates) == 0:
            logger.warning(f"MT5 returnerede ingen data for {symbol} ({mt5_symbol})")
            return None

        df = pd.DataFrame(rates)
        # MT5 leverer 'tick_volume'; map til 'volume' for at matche ccxt-formatet.
        if "volume" not in df.columns:
            if "real_volume" in df.columns and df["real_volume"].sum() > 0:
                df["volume"] = df["real_volume"]
            elif "tick_volume" in df.columns:
                df["volume"] = df["tick_volume"]
            else:
                df["volume"] = 0.0
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

    def get_tick_price(self, symbol: str) -> float | None:
        """Aktuel pris (bid) fra MT5 — bruges af engine til SL/TP-tjek for forex/gold."""
        if not self._initialized or mt5 is None:
            return None
        try:
            tick = mt5.symbol_info_tick(self.FOREX_SYMBOLS.get(symbol, symbol))
        except Exception:  # pragma: no cover
            return None
        if tick is None:
            return None
        return float(tick.bid)

    def shutdown(self) -> None:
        """mt5.shutdown() — kald ved bot-stop."""
        if mt5 is not None and self._initialized:
            mt5.shutdown()
            self._initialized = False
