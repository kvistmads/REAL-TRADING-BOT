"""Tests for research/portfolio.py — porteføljekombinationen.

Den vigtigste test er ``test_weights_ignore_all_future_data``. Invers-volatilitet
beregnet på HELE perioden er klassisk skjult lookahead: den undervægter systematisk
netop de instrumenter der senere viste sig turbulente, den pynter Sharpe, og den gør
det uden at efterlade spor i resultatet. Vægten på dag t må kun afhænge af data før
dag t, og det er en test, ikke en hensigt.

Nummer to er ``test_portfolio_never_uses_leverage``. Bogholderiet er nemt at få til
at låne implicit — en plads der køber for mere end den har, ser ud som en god
strategi indtil man opdager at kontantbeholdningen var negativ.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml

from research import portfolio
from research.daily_series import INSTRUMENTS, research_cost_config

CONFIG = research_cost_config(yaml.safe_load(open("config.yaml")))


def _leg(key: str, days: int = 1400, drift: float = 0.0005, vol: float = 0.01,
         seed: int = 1, start: str = "2016-01-01") -> portfolio.Leg:
    """Syntetisk leg med kendt volatilitet — bygget uden om build_leg's I/O."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=days)
    close = 100 * np.cumprod(1 + rng.normal(drift, vol, days))
    open_ = close * (1 + rng.normal(0, 0.001, days))
    df = pd.DataFrame({"time": dates, "open": open_, "close": close,
                       "high": close, "low": close, "volume": 1.0})
    from research import tsmom
    schedule = tsmom.build_schedule(df, 12, 1)
    return portfolio.Leg(
        key=key, inst=INSTRUMENTS[key], dates=pd.DatetimeIndex(dates),
        open_=open_, close=close, pos=tsmom._position_series(df, schedule),
        exec_by_period={r.period: r.exec_idx for r in schedule},
        one_way_cost=0.0005,
    )


# ---------------------------------------------------------------------------
# Lookahead i vægtningen
# ---------------------------------------------------------------------------

def test_weights_ignore_all_future_data():
    """Ødelæg alle barer fra ``asof`` og frem — vægtene skal være uændrede.

    Kører denne rødt, er der lookahead i vægtningen, og hele porteføljeresultatet
    er værdiløst. Testen kan fejle: ændres ``< asof`` til ``<= asof`` i
    ``trailing_vol``, fejler den her.
    """
    legs = {"SPY": _leg("SPY", seed=1, vol=0.008),
            "BTC": _leg("BTC", seed=2, vol=0.030),
            "GC": _leg("GC", seed=3, vol=0.012)}
    asofs = pd.date_range("2018-06-01", "2021-01-01", freq="MS")
    assert len(asofs) > 20

    for asof in asofs:
        clean = portfolio.inverse_vol_weights(legs, asof)
        poisoned = {}
        for key, leg in legs.items():
            future = leg.dates >= asof
            close = leg.close.copy()
            # Ekstreme, instrument-specifikke tal: ville enhver vol-beregning
            # der rører fremtiden flytte sig forskelligt pr. leg.
            close[future] *= np.linspace(1, 50, int(future.sum())) ** (1 + hash(key) % 3)
            poisoned[key] = portfolio.Leg(
                key=key, inst=leg.inst, dates=leg.dates, open_=leg.open_,
                close=close, pos=leg.pos, exec_by_period=leg.exec_by_period,
                one_way_cost=leg.one_way_cost)
        assert portfolio.inverse_vol_weights(poisoned, asof) == pytest.approx(clean), (
            f"vægtene for {asof.date()} ændrede sig da fremtiden blev ødelagt"
        )


def test_trailing_vol_excludes_the_rebalance_bar_itself():
    """Grænsen er STRENGT før asof. Rebalanceringsdagens egen bar er allerede fremtid."""
    leg = _leg("SPY", seed=5)
    asof = leg.dates[600]
    before = portfolio.trailing_vol(leg, asof)

    spiked = leg.close.copy()
    spiked[600] *= 3.0                      # kun asof-baren selv
    leg2 = portfolio.Leg(key="SPY", inst=leg.inst, dates=leg.dates, open_=leg.open_,
                         close=spiked, pos=leg.pos,
                         exec_by_period=leg.exec_by_period, one_way_cost=0.0)
    assert portfolio.trailing_vol(leg2, asof) == pytest.approx(before)


def test_weights_are_inverse_to_volatility():
    """Det roligste instrument skal have den største vægt, og forholdet skal passe."""
    legs = {"SPY": _leg("SPY", seed=11, vol=0.005),
            "BTC": _leg("BTC", seed=12, vol=0.020)}
    w = portfolio.inverse_vol_weights(legs, pd.Timestamp("2019-01-01"))
    assert w["SPY"] > w["BTC"]
    assert sum(w.values()) == pytest.approx(1.0)
    # ~4x volatilitet -> ~1/4 vægt. Bred tolerance: stikprøvestøj på 12 mdr.
    assert w["SPY"] / w["BTC"] == pytest.approx(4.0, rel=0.45)


def test_weights_skip_instruments_without_enough_history():
    """En manglende volatilitet er ikke en lav volatilitet — vægten skal være 0."""
    legs = {"SPY": _leg("SPY", seed=21),
            "ETH": _leg("ETH", seed=22, start="2019-06-01")}
    w = portfolio.inverse_vol_weights(legs, pd.Timestamp("2019-07-01"))
    assert w["ETH"] == 0.0
    assert w["SPY"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Bogholderi
# ---------------------------------------------------------------------------

def test_portfolio_never_uses_leverage():
    legs = {k: _leg(k, seed=i) for i, k in enumerate(("SPY", "GC", "BTC"), start=30)}
    res = portfolio.run_portfolio(legs)
    assert (res.exposure <= 1.0 + 1e-9).all()
    assert (res.exposure >= -1e-9).all()


def test_weight_rebalancing_costs_are_charged_on_top_of_signal_changes():
    """Vægtdriften mellem månedsskiftene er omsætning der skal betales for."""
    legs = {k: _leg(k, seed=i, vol=v) for i, (k, v) in
            enumerate((("SPY", 0.008), ("BTC", 0.030)), start=40)}
    res = portfolio.run_portfolio(legs)
    assert res.turnover_cost_pct > 0
    # En del af omkostningen må IKKE kunne forklares af signalskift alene.
    assert res.rebalance_cost_share > 0


def test_equity_before_a_date_is_unaffected_by_later_data():
    """End-to-end lookahead: afkort serierne og kræv kurven identisk på det fælles stykke."""
    keys = ("SPY", "GC", "BTC")
    full = {k: _leg(k, days=1400, seed=i) for i, k in enumerate(keys, start=50)}
    cut = pd.Timestamp("2020-01-01")
    part = {}
    for k, leg in full.items():
        m = leg.dates < cut
        part[k] = portfolio.Leg(
            key=k, inst=leg.inst, dates=leg.dates[m], open_=leg.open_[m],
            close=leg.close[m], pos=leg.pos[m],
            exec_by_period={p: i for p, i in leg.exec_by_period.items()
                            if i < int(m.sum())},
            one_way_cost=leg.one_way_cost)

    a = portfolio.run_portfolio(full).equity
    b = portfolio.run_portfolio(part).equity
    common = a.index.intersection(b.index)
    assert len(common) > 200
    np.testing.assert_allclose(a.loc[common], b.loc[common], rtol=1e-9)


def test_baseline_is_equal_weight_and_pays_costs():
    legs = {k: _leg(k, seed=i) for i, k in enumerate(("SPY", "GC"), start=60)}
    res = portfolio.run_portfolio(legs)
    assert res.benchmark.iloc[0] == pytest.approx(1.0, abs=1e-6)
    free = {}
    for k, leg in legs.items():
        free[k] = portfolio.Leg(key=k, inst=leg.inst, dates=leg.dates, open_=leg.open_,
                                close=leg.close, pos=leg.pos,
                                exec_by_period=leg.exec_by_period, one_way_cost=0.0)
    gratis = portfolio.equal_weight_buy_and_hold(free, res.benchmark.index)
    assert res.benchmark.iloc[-1] < gratis.iloc[-1]   # baselinen er ikke gratis


# ---------------------------------------------------------------------------
# Bidragskolonner (fase 2b)
# ---------------------------------------------------------------------------

def test_contribution_shares_sum_to_one_hundred():
    """Bidragene skal dække porteføljen helt — ellers mangler der en post."""
    legs = {k: _leg(k, seed=i) for i, k in enumerate(("SPY", "GC", "BTC"), start=70)}
    res = portfolio.run_portfolio(legs)
    assert sum(res.return_contribution.values()) == pytest.approx(100.0, abs=0.5)
    assert sum(res.risk_contribution.values()) == pytest.approx(100.0, abs=0.5)


def test_return_contribution_excludes_rebalancing_cash_flows():
    """Et instrument der ALDRIG er long, må bidrage med præcis 0 til afkastet.

    Rebalanceringens pengestrømme flytter kapital ind og ud af pladsen. Talte de
    med som afkast, ville en plads der kun har stået i kontanter få et bidrag.
    """
    dates = pd.bdate_range("2016-01-01", periods=900)
    falling = 100 * np.cumprod(np.full(900, 0.999))     # aldrig positivt 12m-afkast
    rising = 100 * np.cumprod(np.full(900, 1.0008))

    from research import tsmom
    legs = {}
    for key, close in (("SPY", rising), ("GC", falling)):
        df = pd.DataFrame({"time": dates, "open": close, "close": close,
                           "high": close, "low": close, "volume": 1.0})
        sched = tsmom.build_schedule(df, 12, 1)
        legs[key] = portfolio.Leg(
            key=key, inst=INSTRUMENTS[key], dates=pd.DatetimeIndex(dates),
            open_=close, close=close, pos=tsmom._position_series(df, sched),
            exec_by_period={r.period: r.exec_idx for r in sched}, one_way_cost=0.0005)

    res = portfolio.run_portfolio(legs)
    assert res.return_contribution["GC"] == pytest.approx(0.0, abs=1e-9)
    assert res.risk_contribution["GC"] == pytest.approx(0.0, abs=1e-9)


def test_duplicate_underlying_is_excluded_from_every_universe():
    """XAU må ikke kunne snige sig ind i et univers igen ved et uheld."""
    for keys in portfolio.UNIVERSES.values():
        assert not set(keys) & set(portfolio.DUPLICATE_UNDERLYING)
    assert len(portfolio.UNIVERSES["alle_syv"]) == 7
