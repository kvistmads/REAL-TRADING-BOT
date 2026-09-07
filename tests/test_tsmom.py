"""Tests for research/tsmom.py og de lange-horisont-metrikker.

Den vigtigste test i filen er ``test_signal_ignores_execution_bar_and_future``.
TSMOM's hele formål er at afgøre om apparatet kan genfinde en effekt der beviseligt
findes. Regner signalet ét eneste bar for langt frem — til eksekveringsbarens close
i stedet for forrige måneds close — så BESTÅR testen, og den består af den forkerte
grund. Fejlen er usynlig i resultatet: kurven ser bare lidt for god ud.

Derfor er lookahead-grænsen ikke en kommentar i koden. Den er en test der kan køre
rødt: vi ødelægger alle barer fra eksekveringsbaren og frem, og kræver at hvert
eneste signal er uændret.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml

from backtest import metrics
from research import tsmom
from research.daily_series import INSTRUMENTS, research_cost_config

CONFIG = research_cost_config(yaml.safe_load(open("config.yaml")))


def _series(days: int = 1500, start: str = "2015-01-01", seed: int = 7) -> pd.DataFrame:
    """Syntetisk daglig serie — børskalender (man-fre), stigende med støj."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=days)
    close = 100 * np.cumprod(1 + rng.normal(0.0004, 0.011, days))
    open_ = close * (1 + rng.normal(0, 0.002, days))
    return pd.DataFrame({
        "time": dates, "open": open_, "close": close,
        "high": np.maximum(open_, close) * 1.001,
        "low": np.minimum(open_, close) * 0.999,
        "volume": 1000.0,
    })


# ---------------------------------------------------------------------------
# Lookahead
# ---------------------------------------------------------------------------

def test_schedule_indices_are_strictly_ordered():
    """ref < signal < exec for HVER rebalancering. Grænsen er en ulighed, ikke en hensigt."""
    df = _series()
    schedule = tsmom.build_schedule(df, lookback_months=12, rebalance_day=1)
    assert schedule
    for reb in schedule:
        assert reb.ref_idx < reb.signal_idx < reb.exec_idx


def test_signal_ignores_execution_bar_and_future():
    """Ødelæg alt fra eksekveringsbaren og frem — signalet skal være uændret.

    Kører denne rødt, er der lookahead i ``signal_for``, og ALLE tal fra fase 1
    er værdiløse. Testen skal kunne fejle: bytter man ``signal_idx`` ud med
    ``exec_idx`` i ``signal_for``, fejler den her.
    """
    df = _series()
    schedule = tsmom.build_schedule(df, lookback_months=12, rebalance_day=1)
    assert len(schedule) > 20

    for reb in schedule:
        poisoned = df.copy()
        # Fra eksekveringsbaren og frem: tal der ikke ligner noget marked.
        poisoned.loc[reb.exec_idx:, ["open", "high", "low", "close"]] = -1e9
        assert tsmom.signal_for(poisoned, reb) == tsmom.signal_for(df, reb), (
            f"signalet for {reb.period} ændrede sig da fremtiden blev ødelagt"
        )


def test_equity_before_a_date_is_unaffected_by_later_data():
    """End-to-end: kurven frem til et tidspunkt må ikke afhænge af data efter det.

    Stærkere end signaltesten — den fanger også lookahead der måtte snige sig ind i
    positions-serien eller i omkostningerne.
    """
    df = _series(days=1200)
    inst = INSTRUMENTS["SPY"]
    cut = 900
    truncated = df.iloc[:cut].reset_index(drop=True)

    full = tsmom.run_tsmom(df, inst, CONFIG, 12, 1)
    part = tsmom.run_tsmom(truncated, inst, CONFIG, 12, 1)

    common = full.equity.index.intersection(part.equity.index)
    assert len(common) > 100
    np.testing.assert_allclose(full.equity.loc[common], part.equity.loc[common], rtol=1e-9)


# ---------------------------------------------------------------------------
# Månedsskiftet
# ---------------------------------------------------------------------------

def test_execution_bar_is_first_bar_on_or_after_the_target_day():
    df = _series()
    dates = pd.DatetimeIndex(df["time"])
    for reb in tsmom.build_schedule(df, 12, rebalance_day=1):
        exec_date = dates[reb.exec_idx]
        assert exec_date.month == reb.period.month
        assert exec_date.day <= 4          # første handelsdag, aldrig midt i måneden
        assert dates[reb.exec_idx - 1] < reb.period.to_timestamp()


def test_rebalance_day_15_shifts_the_schedule():
    """Timing-kontrollen skal faktisk flytte handlen — ellers tester den ingenting."""
    df = _series()
    first = tsmom.build_schedule(df, 12, rebalance_day=1)
    mid = tsmom.build_schedule(df, 12, rebalance_day=15)
    dates = pd.DatetimeIndex(df["time"])
    assert {dates[r.exec_idx].day for r in mid}.isdisjoint({1, 2, 3, 4})
    assert len(mid) == pytest.approx(len(first), abs=2)


def test_lookback_window_length_matches_the_parameter():
    df = _series()
    dates = pd.DatetimeIndex(df["time"])
    for months in (3, 6, 12):
        for reb in tsmom.build_schedule(df, months, 1):
            span = (dates[reb.signal_idx] - dates[reb.ref_idx]).days
            assert months * 30 - 10 <= span <= months * 31 + 10


# ---------------------------------------------------------------------------
# Omkostninger: én rundtur pr. holdeperiode, ikke pr. måned
# ---------------------------------------------------------------------------

def test_costs_are_charged_per_position_not_per_month():
    """Et signal der bliver liggende long må ikke koste noget ved månedsskiftet."""
    days = 900
    dates = pd.bdate_range("2016-01-01", periods=days)
    close = 100 * np.cumprod(np.full(days, 1.0008))     # monoton stigning -> altid long
    df = pd.DataFrame({"time": dates, "open": close, "close": close,
                       "high": close, "low": close, "volume": 1000.0})
    res = tsmom.run_tsmom(df, INSTRUMENTS["BTC"], CONFIG, 12, 1)
    assert res.positions == 1                 # én sammenhængende holdeperiode
    assert res.exposure.mean() == 1.0         # aldrig ude
    assert res.hold_months > 12


def test_flat_when_lookback_return_is_negative():
    days = 900
    dates = pd.bdate_range("2016-01-01", periods=days)
    close = 100 * np.cumprod(np.full(days, 0.9992))     # monotont fald -> aldrig long
    df = pd.DataFrame({"time": dates, "open": close, "close": close,
                       "high": close, "low": close, "volume": 1000.0})
    res = tsmom.run_tsmom(df, INSTRUMENTS["BTC"], CONFIG, 12, 1)
    assert res.positions == 0
    assert res.exposure.sum() == 0
    assert res.equity.iloc[-1] == pytest.approx(1.0)    # kontanter forrentes ikke


# ---------------------------------------------------------------------------
# DEL 2: metrikkerne
# ---------------------------------------------------------------------------

def test_compound_return_is_not_the_naive_sum():
    assert metrics.compound_return_pct([50, -50]) == pytest.approx(-25.0)
    assert metrics.compound_return_pct([-12] * 10) == pytest.approx(-71.757, abs=0.5)
    # Den naive sum ville sige -120% — altså mere end kontoen.
    assert sum([-12] * 10) == -120


def test_compute_exposes_both_the_naive_sum_and_the_compounded_return():
    trades = [{"pnl": 1, "pnl_pct": 50.0, "reason": "take_profit"},
              {"pnl": -1, "pnl_pct": -50.0, "reason": "stop_loss"}]
    m = metrics.compute(trades)
    assert m["total_pnl_pct"] == pytest.approx(0.0)        # naiv sum, bevaret
    assert m["compound_pnl_pct"] == pytest.approx(-25.0)   # det rigtige tal


def test_max_drawdown_is_measured_on_the_curve():
    eq = pd.Series([1.0, 1.5, 0.75, 1.2], index=pd.date_range("2020-01-01", periods=4))
    assert metrics.max_drawdown_curve(eq) == pytest.approx(-50.0)


def test_longest_flat_days_counts_an_unrecovered_period():
    idx = pd.date_range("2020-01-01", periods=4, freq="365D")
    eq = pd.Series([1.0, 2.0, 1.0, 1.5], index=idx)   # top i år 2, aldrig overgået
    assert metrics.longest_flat_days(eq) >= 730


def test_buy_and_hold_pays_one_round_turn():
    close = pd.Series([100.0, 110.0], index=pd.date_range("2020-01-01", periods=2))
    free = metrics.buy_and_hold_curve(close, 0.0)
    charged = metrics.buy_and_hold_curve(close, 0.5)
    assert free.iloc[-1] == pytest.approx(1.10)
    assert charged.iloc[-1] < free.iloc[-1]      # baselinen er ikke gratis
    assert charged.iloc[-1] == pytest.approx(1.10 * (1 - 0.0025) / (1 + 0.0025), rel=1e-6)
