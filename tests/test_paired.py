"""Tests for backtest/paired.py — parret evaluering af en exit-regel.

Apparatet findes fordi A1/A2 ikke kunne isolere en exit-regels virkning: markøren
springer frem med handlens længde, så en kortere exit flytter alle efterfølgende
entries. Det der låses fast her er netop parringen — bliver den brudt, måler testen
igen to forskellige vandringer gennem data og kalder forskellen for exit-reglen.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml

from backtest import paired
from strategies.base import Signal

CONFIG = yaml.safe_load(open("config.yaml"))


def _pair(i: int, changed: bool):
    base = {"symbol": "BTC/USDT", "side": "long", "entry_time": i,
            "reason": "take_profit", "r_multiple_net": 1.0, "bars_held": 5}
    var = dict(base)
    if changed:
        var.update(reason="flip_level", r_multiple_net=0.5, bars_held=2)
    return base, var


class TestParringHoldes:
    def test_forskellige_længder_afvises(self):
        b = [_pair(i, False)[0] for i in range(5)]
        with pytest.raises(ValueError, match="parringen er brudt"):
            paired.paired_differences(b, b[:3])

    def test_uændrede_handler_giver_delta_nul(self):
        b, v = zip(*[_pair(i, False) for i in range(6)])
        diffs = paired.paired_differences(list(b), list(v))
        assert all(d["delta_r"] == 0.0 for d in diffs)
        assert all(not d["changed"] for d in diffs)

    def test_ændrede_handler_markeres(self):
        b, v = zip(*[_pair(i, i < 3) for i in range(10)])
        s = paired.paired_summary(paired.paired_differences(list(b), list(v)))
        assert s["n"] == 10 and s["n_changed"] == 3
        assert s["changed_pct"] == 30.0

    def test_handler_uden_R_springes_over(self):
        b, v = zip(*[_pair(i, False) for i in range(4)])
        b, v = list(b), list(v)
        b[0] = {**b[0], "r_multiple_net": None}
        assert len(paired.paired_differences(b, v)) == 3


class TestParretInterval:
    def test_fortynding_af_uændrede_handler_er_synlig(self):
        """En regel der rammer sjældent men hårdt må ikke se svag ud i totalen."""
        b, v = zip(*[_pair(i, i < 2) for i in range(20)])
        s = paired.paired_summary(paired.paired_differences(list(b), list(v)))
        assert s["mean_delta_r"] == pytest.approx(-0.05)          # fortyndet
        assert s["mean_delta_r_changed"] == pytest.approx(-0.5)   # ufortyndet

    def test_krydser_nul_når_effekten_er_støj(self):
        rng = np.random.default_rng(0)
        diffs = [{"delta_r": float(rng.normal(0, 1)), "changed": True} for _ in range(200)]
        s = paired.paired_summary(diffs)
        assert s["crosses_zero"] is True

    def test_krydser_ikke_nul_ved_konsistent_effekt(self):
        diffs = [{"delta_r": 0.5, "changed": True} for _ in range(50)]
        s = paired.paired_summary(diffs)
        assert s["crosses_zero"] is False and s["mean_delta_r"] == 0.5

    def test_optælling_af_bedre_værre_uændret(self):
        diffs = ([{"delta_r": 1.0, "changed": True}] * 3
                 + [{"delta_r": -1.0, "changed": True}] * 2
                 + [{"delta_r": 0.0, "changed": False}] * 5)
        s = paired.paired_summary(diffs)
        assert (s["n_better"], s["n_worse"], s["n_same"]) == (3, 2, 5)

    def test_tomt_input(self):
        assert paired.paired_summary([])["n"] == 0


class _AlwaysSignal:
    """Genererer et signal på hver bar, så parringen kan testes end-to-end."""

    name = "stub"
    timeframe = "4h"
    min_confidence = 0.65

    def generate_signal(self, df, symbol, params=None):
        return Signal(self.name, symbol, "long", 0.9, "4h",
                      {"flip_level": float(df["close"].iloc[-1]) * 0.98})


class TestEndToEnd:
    def _df(self, n=260):
        close = np.linspace(100, 130, n)
        return pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=n, freq="4h"),
            "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": np.full(n, 1000.0),
        })

    def test_identiske_entries_i_begge_lister(self):
        base, var = paired.paired_backtest(self._df(), _AlwaysSignal(), "BTC/USDT",
                                           CONFIG, warmup=200)
        assert len(base) == len(var)
        assert [t["entry_time"] for t in base] == [t["entry_time"] for t in var]
        assert [t["entry_price"] for t in base] == [t["entry_price"] for t in var]

    def test_markøren_følger_baseline(self):
        """Varianten må aldrig kunne forskyde efterfølgende entries."""
        base, var = paired.paired_backtest(self._df(), _AlwaysSignal(), "BTC/USDT",
                                           CONFIG, warmup=200)
        # Entries er strengt stigende og bestemt af baseline's holdetid.
        times = [t["entry_time"] for t in base]
        assert times == sorted(times)
        assert len(set(times)) == len(times)

    def test_begge_lister_får_omkostninger_og_R(self):
        base, var = paired.paired_backtest(self._df(), _AlwaysSignal(), "BTC/USDT",
                                           CONFIG, warmup=200)
        for trades in (base, var):
            assert all("pnl_pct_net" in t for t in trades)
            assert all("r_multiple_net" in t for t in trades)

    def test_fælles_tilfældige_tal_giver_samme_entry_slippage(self):
        """Parret sammenligning: entry-slippage skal være identisk for de to udgaver."""
        base, var = paired.paired_backtest(self._df(), _AlwaysSignal(), "BTC/USDT",
                                           CONFIG, warmup=200)
        assert [t["entry_fill"] for t in base] == [t["entry_fill"] for t in var]
