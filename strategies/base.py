from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class Signal:
    strategy_id: str
    symbol: str
    side: str  # "long" | "short"
    confidence: float  # 0.0–1.0
    timeframe: str
    metadata: dict
    sl_price: float | None = None
    tp_price: float | None = None


class BaseStrategy(ABC):
    name: str
    timeframe: str
    # NB: denne værdi er i praksis DØD i normal drift. Rækkefølgen er:
    #   1. params["min_confidence"] (engine sender config'ens værdi ned som base-param;
    #      backtesten sender 0.0, fordi den aldrig anvender gaten)
    #   2. strategies.params.<id>.min_confidence  (per-strategi-override i config)
    #   3. strategies.min_confidence              (global, i dag 0.45)
    #   4. denne klasseattribut                   (kun hvis intet af ovenstående findes)
    # Efter commit 19dc8d0 blev den globale værdi virksom, så tallet her (og de 0.65
    # subklasserne sætter) vinder aldrig så længe config.yaml har nøglen. Det bliver
    # stående som sidste fallback — ikke som den gældende tærskel.
    min_confidence: float = 0.60

    @abstractmethod
    def generate_signal(
        self, df: pd.DataFrame, symbol: str, params: dict | None = None
    ) -> Signal | None:
        """
        df: OHLCV DataFrame med indikatorer beregnet
        symbol: e.g. "BTC/USDT"
        params: valgfrit dict med parameter-overrides til A/B-eksperimenter.
            Strategier bruger params.get("param_name", self.DEFAULT_VALUE) og
            falder tilbage til klassens konstant når nøglen mangler. None/tom dict
            → uændret default-adfærd. Ingen kode udenfor strategien må ændre
            self.*-felter direkte.
        Returnerer Signal eller None. Må IKKE kalde exchange eller DB.
        """

    @staticmethod
    def get_asset_class(symbol: str) -> str:
        if symbol in ("EUR/USD", "GBP/USD"):
            return "forex"
        if symbol == "XAU/USD":
            return "gold"
        return "crypto"
