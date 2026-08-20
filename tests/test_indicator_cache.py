"""
Tests for indikator-cachen og den delte indikator-bundle (Ændring 7).

add_all() er den tungeste del af hvert tick (weekly-profileringen har peget på den
tre uger i træk). Den beregnes nu én gang pr. symbol i engine og deles med alle
strategier; cachen fanger resten. Testene her låser to ting fast: at cachen
faktisk rammer, og at den ALDRIG serverer ét symbols indikatorer til et andet.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data import indicators
from data.indicators import add_all, clear_indicator_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_indicator_cache()
    yield
    clear_indicator_cache()


def _df(n: int = 60, base: float = 100.0, seed: float = 1.0) -> pd.DataFrame:
    closes = [base + seed * (i % 7) for i in range(n)]
    return pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=n, freq="4h"),
        "open": closes,
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
        "close": closes,
        "volume": [1000.0 + i for i in range(n)],
    })


class TestCacheHit:
    def test_identisk_df_beregnes_kun_en_gang(self, monkeypatch):
        calls: list[int] = []
        original = indicators._compute_all
        monkeypatch.setattr(indicators, "_compute_all",
                            lambda df: (calls.append(1), original(df))[1])

        first = add_all(_df())
        second = add_all(_df())

        assert len(calls) == 1
        assert second is first

    def test_cached_resultat_har_alle_indikatorer(self):
        add_all(_df())
        result = add_all(_df())
        for col in ("rsi_14", "atr_14", "adx_14", "ema_20", "volume_sma_20"):
            assert col in result.columns

    def test_ny_bar_giver_ny_beregning(self, monkeypatch):
        calls: list[int] = []
        original = indicators._compute_all
        monkeypatch.setattr(indicators, "_compute_all",
                            lambda df: (calls.append(1), original(df))[1])

        add_all(_df(60))
        add_all(_df(61))  # en bar mere → andet datasæt

        assert len(calls) == 2

    def test_input_df_muteres_ikke(self):
        df = _df()
        add_all(df)
        assert "rsi_14" not in df.columns

    def test_tom_df_returneres_uroert(self):
        empty = pd.DataFrame()
        assert add_all(empty) is empty
        assert indicators._indicator_cache == {}


class TestCacheIsolation:
    def test_forskellige_symboler_deler_ikke_cache(self):
        """Regression: en nøgle på kun indekset ville kollidere — to symboler
        hentet med samme limit har identisk RangeIndex."""
        btc = _df(60, base=50000.0).drop(columns=["time"])
        eth = _df(60, base=3000.0).drop(columns=["time"])

        btc_result = add_all(btc)
        eth_result = add_all(eth)

        assert btc_result is not eth_result
        assert btc_result["ema_20"].iloc[-1] != eth_result["ema_20"].iloc[-1]

    def test_samme_laengde_men_forskellige_priser_er_forskellige_noegler(self):
        assert indicators._cache_key(_df(60, base=100.0)) != indicators._cache_key(
            _df(60, base=200.0)
        )

    def test_samme_data_giver_samme_noegle(self):
        assert indicators._cache_key(_df()) == indicators._cache_key(_df())


class TestCacheEviction:
    def test_cachen_vokser_ikke_ubegraenset(self):
        for i in range(indicators._CACHE_MAX_ENTRIES + 20):
            add_all(_df(60, base=100.0 + i))
        assert len(indicators._indicator_cache) <= indicators._CACHE_MAX_ENTRIES

    def test_aeldste_entry_ryger_foerst(self):
        first = _df(60, base=1000.0)
        first_key = indicators._cache_key(first)
        add_all(first)

        for i in range(indicators._CACHE_MAX_ENTRIES):
            add_all(_df(60, base=100.0 + i))

        assert first_key not in indicators._indicator_cache

    def test_clear_toemmer_cachen(self):
        add_all(_df())
        assert indicators._indicator_cache
        clear_indicator_cache()
        assert indicators._indicator_cache == {}


class TestDeltBundle:
    # Samme skip-liste som registry.load_strategies() — det er dens definition af
    # hvad der tæller som et strategi-modul.
    IKKE_STRATEGIER = {"__init__", "base", "registry"}

    def test_strategierne_kalder_ikke_add_all_selv(self):
        """Del B: den tunge beregning sker ét sted — i engine/runner, ikke pr. strategi.

        Glob frem for en håndholdt liste, så en ny strategi er dækket fra den dag
        filen lander, og en fjernet strategi ikke efterlader et dødt navn her.
        """
        moduler = [p for p in sorted(Path("strategies").glob("*.py"))
                   if p.stem not in self.IKKE_STRATEGIER]
        # Uden denne ville et glob der ikke matcher noget give en grønt lysende
        # test der ikke tjekker en eneste fil.
        assert moduler, "ingen strategi-moduler fundet i strategies/"
        for path in moduler:
            assert "add_all" not in path.read_text(), \
                f"{path.stem} kalder add_all internt"

    @pytest.mark.asyncio
    async def test_engine_deler_samme_enriched_df_med_alle_strategier(self, monkeypatch):
        """Alle strategier skal se præcis det samme objekt — én beregning pr. symbol."""
        from tests.fixtures.engine import fake_engine

        seen: dict[str, list[int]] = {}

        class RecordingStrategy:
            def __init__(self, name: str):
                self.name = name
                self.min_confidence = 0.65

            def generate_signal(self, df, symbol, params=None):
                seen.setdefault(symbol, []).append(id(df))
                assert "atr_14" in df.columns  # bundlen er allerede beriget
                return None

        calls: list[int] = []
        original = indicators._compute_all
        monkeypatch.setattr(indicators, "_compute_all",
                            lambda df: (calls.append(1), original(df))[1])

        engine = fake_engine(
            monkeypatch,
            strategies=[RecordingStrategy(n) for n in ("a", "b", "c")],
            bars={"BTC/USDT": _df(120), "ETH/USDT": _df(120, base=3000.0)},
        )
        await engine._tick()

        assert len(seen["BTC/USDT"]) == 3
        assert len(set(seen["BTC/USDT"])) == 1      # ét delt objekt
        assert len(set(seen["ETH/USDT"])) == 1
        assert seen["BTC/USDT"][0] != seen["ETH/USDT"][0]  # men ikke på tværs af symboler
        assert len(calls) == 2                       # én beregning pr. symbol
