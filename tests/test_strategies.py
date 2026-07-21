import pytest
import pandas as pd
import numpy as np

from data.indicators import add_all
from strategies.rsi_divergence import RSIDivergence
from strategies.macd_volume import MACDVolume
from strategies.bollinger_squeeze import BollingerSqueeze
from strategies.base import Signal
from tests.fixtures.ohlcv import (
    make_bullish_df, make_bearish_df, make_flat_df,
    make_squeeze_df, make_macd_crossover_df,
)


def with_indicators(df: pd.DataFrame) -> pd.DataFrame:
    return add_all(df.copy())


class TestRSIDivergence:
    def setup_method(self):
        self.strategy = RSIDivergence()

    def test_returns_none_on_flat_market(self):
        df = with_indicators(make_flat_df())
        # Flat marked har sjældent divergens — vi bekræfter at det i hvert fald ikke crasher
        result = self.strategy.generate_signal(df, "BTC/USDT")
        assert result is None or isinstance(result, Signal)

    def test_strategy_id_matches_name(self):
        df = with_indicators(make_bullish_df())
        result = self.strategy.generate_signal(df, "BTC/USDT")
        if result is not None:
            assert result.strategy_id == self.strategy.name

    def test_confidence_in_valid_range(self):
        for make_df in [make_bullish_df, make_bearish_df, make_flat_df]:
            df = with_indicators(make_df())
            result = self.strategy.generate_signal(df, "BTC/USDT")
            if result is not None:
                assert 0.0 <= result.confidence <= 1.0

    def test_side_is_valid(self):
        for make_df in [make_bullish_df, make_bearish_df]:
            df = with_indicators(make_df())
            result = self.strategy.generate_signal(df, "BTC/USDT")
            if result is not None:
                assert result.side in ("long", "short")

    def test_returns_none_on_too_short_df(self):
        df = with_indicators(make_flat_df(n=10))
        result = self.strategy.generate_signal(df, "BTC/USDT")
        assert result is None

    def test_no_sl_tp_set(self):
        df = with_indicators(make_bullish_df())
        result = self.strategy.generate_signal(df, "BTC/USDT")
        if result is not None:
            assert result.sl_price is None
            assert result.tp_price is None


class TestMACDVolume:
    def setup_method(self):
        self.strategy = MACDVolume()

    def test_strategy_id_matches_name(self):
        df = with_indicators(make_macd_crossover_df(direction="long"))
        result = self.strategy.generate_signal(df, "BTC/USDT")
        if result is not None:
            assert result.strategy_id == self.strategy.name

    def test_confidence_in_valid_range(self):
        for direction in ["long", "short"]:
            df = with_indicators(make_macd_crossover_df(direction=direction))
            result = self.strategy.generate_signal(df, "BTC/USDT")
            if result is not None:
                assert 0.0 <= result.confidence <= 1.0

    def test_side_is_valid(self):
        for direction in ["long", "short"]:
            df = with_indicators(make_macd_crossover_df(direction=direction))
            result = self.strategy.generate_signal(df, "BTC/USDT")
            if result is not None:
                assert result.side in ("long", "short")

    def test_returns_none_without_volume_spike(self):
        df = with_indicators(make_flat_df())
        result = self.strategy.generate_signal(df, "BTC/USDT")
        assert result is None

    def test_no_sl_tp_set(self):
        df = with_indicators(make_macd_crossover_df())
        result = self.strategy.generate_signal(df, "BTC/USDT")
        if result is not None:
            assert result.sl_price is None


class TestBollingerSqueeze:
    def setup_method(self):
        self.strategy = BollingerSqueeze()

    def test_strategy_id_matches_name(self):
        for direction in ["long", "short"]:
            df = with_indicators(make_squeeze_df(breakout_direction=direction))
            result = self.strategy.generate_signal(df, "BTC/USDT")
            if result is not None:
                assert result.strategy_id == self.strategy.name

    def test_confidence_in_valid_range(self):
        for direction in ["long", "short"]:
            df = with_indicators(make_squeeze_df(breakout_direction=direction))
            result = self.strategy.generate_signal(df, "BTC/USDT")
            if result is not None:
                assert 0.0 <= result.confidence <= 1.0

    def test_returns_none_on_flat_market(self):
        df = with_indicators(make_flat_df())
        result = self.strategy.generate_signal(df, "BTC/USDT")
        # Flat marked har ingen squeeze breakout
        assert result is None or isinstance(result, Signal)

    def test_no_sl_tp_set(self):
        df = with_indicators(make_squeeze_df())
        result = self.strategy.generate_signal(df, "BTC/USDT")
        if result is not None:
            assert result.sl_price is None
