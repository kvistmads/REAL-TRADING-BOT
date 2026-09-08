"""Tests for research/venues.py — venue-, ordretype- og kontraktaritmetikken.

To fund fra fase 3b er nemme at tabe igen, og begge er låst her:

1. **MEXC's API-sats er ikke web-satsen.** Opgaven byggede på 0%/0,02%, som gælder
   web og app. API-ordrer — det eneste botten laver — koster 0,06%/0,08%. Skulle
   nogen komme til at "rette" satsen tilbage til den markedsførte, fejler en test.
2. **Spread skalerer med kontrakten, gebyret gør ikke.** Det er hele forklaringen på
   at mikrokontrakter er dyrere i basispunkter, og det er let at miste hvis man kun
   ser på totalen.
"""
from __future__ import annotations

import pytest

from research import venues as v


# ---------------------------------------------------------------------------
# Venue og ordretype
# ---------------------------------------------------------------------------

def test_mexc_api_is_more_expensive_than_the_advertised_web_rate():
    """Den markedsførte sats gælder ikke vores adgangsvej. Låst mod at blive 'rettet'."""
    web = v.VENUES["mexc_futures_web"]
    api = v.VENUES["mexc_futures_api"]
    assert api.taker_pct > web.taker_pct
    assert api.maker_pct > web.maker_pct
    assert api.round_turn_bp() > web.round_turn_bp()


def test_mexc_api_is_more_expensive_than_binance_futures():
    """Kernen i fase 3b: for en API-bot vender MEXC-fordelen om."""
    assert (v.VENUES["mexc_futures_api"].round_turn_bp()
            > v.VENUES["binance_futures"].round_turn_bp())


def test_round_turn_counts_two_legs():
    binance = v.VENUES["binance_spot"]          # 0,10% begge veje
    assert binance.round_turn_bp() == pytest.approx(20.0)


def test_stop_adjusted_maker_share_follows_the_win_rate():
    """maker-andel = (1 + WR) / 2, fordi kun stoppet tvinger en markedsordre."""
    assert v.stop_adjusted_maker_share(0.33) == pytest.approx(0.665)
    # Vinder man alt, rammes stoppet aldrig: entry + TP = begge ben maker.
    assert v.stop_adjusted_maker_share(1.0) == pytest.approx(1.0)
    # Taber man alt, er halvdelen af benene stop og dermed taker.
    assert v.stop_adjusted_maker_share(0.0) == pytest.approx(0.5)


def test_stop_adjusted_cost_lies_between_pure_taker_and_pure_maker():
    api = v.VENUES["mexc_futures_api"]
    mix = api.round_turn_bp(v.stop_adjusted_maker_share(0.33))
    assert api.round_turn_bp(1.0) < mix < api.round_turn_bp(0.0)


def test_a_venue_without_a_maker_discount_saves_nothing():
    """Binance spot har maker == taker. Maker-kolonnen må ikke opfinde en besparelse."""
    spot = v.VENUES["binance_spot"]
    assert spot.round_turn_bp(1.0) == pytest.approx(spot.round_turn_bp(0.0))


# ---------------------------------------------------------------------------
# Kontrakter — DEL 3's mekanisme
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("micro,full", [("MES", "ES"), ("MNQ", "NQ"), ("MGC", "GC")])
def test_spread_in_bp_is_identical_for_micro_and_full_size(micro, full):
    """Spread skalerer med kontrakten. Det er DEL 3's strukturelle pointe."""
    price = 4000.0
    m = v.contract_costs(v.CONTRACTS[micro], price)
    f = v.contract_costs(v.CONTRACTS[full], price)
    assert m["spread_bp"] == pytest.approx(f["spread_bp"], rel=1e-9)


@pytest.mark.parametrize("micro,full", [("MES", "ES"), ("MNQ", "NQ"), ("MGC", "GC")])
def test_fee_in_bp_is_higher_for_micro_because_fees_do_not_scale(micro, full):
    price = 4000.0
    m = v.contract_costs(v.CONTRACTS[micro], price)
    f = v.contract_costs(v.CONTRACTS[full], price)
    assert m["gebyr_bp"] > f["gebyr_bp"]
    # Totalen fortynder forholdet, fordi spread-delen er ens. Derfor skal begge
    # komponenter rapporteres — totalen alene skjuler mekanismen.
    assert m["i_alt_bp"] / f["i_alt_bp"] < m["gebyr_bp"] / f["gebyr_bp"]


def test_ticks_are_price_independent_but_bp_is_not():
    """Derfor rapporteres begge: ticks er geometri, bp er geometri × prisniveau."""
    gc = v.CONTRACTS["GC"]
    lav = v.contract_costs(gc, 3000.0)
    hoej = v.contract_costs(gc, 5000.0)
    assert lav["i_alt_ticks"] == pytest.approx(hoej["i_alt_ticks"])
    assert lav["i_alt_bp"] > hoej["i_alt_bp"]      # lavere pris -> dyrere i bp


def test_exchange_clearing_is_reported_separately_from_broker_commission():
    """De 4 USD i modellen er brokerens del alene — adskillelsen skal være synlig."""
    c = v.contract_costs(v.CONTRACTS["GC"], 4000.0)
    assert c["broker_pr_side"] > 0 and c["exch_clear_pr_side"] > 0
    assert c["gebyr_rundtur_usd"] == pytest.approx(
        2 * (c["broker_pr_side"] + c["exch_clear_pr_side"] + c["nfa_pr_side"]))


def test_micro_gold_exchange_fee_barely_scales_down():
    """Den egentlige driver: COMEX tager 71% af GC-gebyret for 10% af kontrakten."""
    ratio = v.CONTRACTS["MGC"].exch_clear_pr_side / v.CONTRACTS["GC"].exch_clear_pr_side
    assert ratio > 0.5          # langt fra de 0,1 en proportional skalering ville give
