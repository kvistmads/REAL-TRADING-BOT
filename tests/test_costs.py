"""Tests for backtest/costs.py — omkostningsmodellen.

Modellen afgør om et resultat er reelt eller kun brutto, så fejl her viser sig som
en forkert konklusion frem for en exception. Tre ting låses fast:

1. **Omkostninger går ALTID imod handlen** — også på shorts, hvor fortegnene vender.
2. **Reproducerbarhed** — samme seed og samme (strategi, symbol) giver samme slippage,
   uanset om symbolet køres alene eller midt i en suite.
3. **Brutto røres aldrig** — netto lægges ved siden af, så begge kan vises.
"""
from __future__ import annotations

import pytest
import yaml

from backtest import costs, metrics

CONFIG = yaml.safe_load(open("config.yaml"))


def _trade(symbol="BTC/USDT", side="long", entry=100.0, exit_=110.0,
           strategy_id="trend_momentum", reason="take_profit") -> dict:
    if side == "long":
        pnl_pct = (exit_ - entry) / entry * 100
    else:
        pnl_pct = (entry - exit_) / entry * 100
    return {
        "symbol": symbol, "side": side, "strategy_id": strategy_id,
        "entry_price": entry, "exit_price": exit_, "reason": reason,
        "pnl_pct": round(pnl_pct, 4), "pnl": round(pnl_pct / 100 * 5.0, 4),
    }


class TestCostFractions:
    def test_proportional_bruger_pct_direkte(self):
        params = {"mode": "proportional", "spread_pct": 0.001,
                  "slippage_mean_pct": 0.0002, "slippage_std_pct": 0.0001,
                  "commission_pct": 0.002}
        spread, mean, std, comm = costs.cost_fractions(params, price=50_000)
        assert (spread, mean, std, comm) == (0.001, 0.0002, 0.0001, 0.002)

    def test_proportional_er_uafhængig_af_pris(self):
        params = {"mode": "proportional", "spread_pct": 0.001}
        assert (costs.cost_fractions(params, 100)[0]
                == costs.cost_fractions(params, 100_000)[0])

    def test_contract_skalerer_med_pris(self):
        """Et tick er det samme i kroner — men en mindre BRØKDEL når prisen stiger."""
        params = {"mode": "contract", "tick_size": 0.10, "spread_ticks": 1.0,
                  "contract_multiplier": 100}
        billig = costs.cost_fractions(params, price=2000)[0]
        dyr = costs.cost_fractions(params, price=4000)[0]
        assert billig == pytest.approx(0.10 / 2000)
        assert dyr == pytest.approx(0.10 / 4000)
        assert dyr < billig  # samme tick, halvt så stor relativ omkostning

    def test_kurtage_deles_med_notional(self):
        params = {"mode": "contract", "tick_size": 0.10, "contract_multiplier": 100,
                  "commission_usd_round_turn": 4.0}
        comm = costs.cost_fractions(params, price=4500)[3]
        assert comm == pytest.approx(4.0 / (100 * 4500))

    def test_nulpris_giver_nul(self):
        assert costs.cost_fractions({"mode": "contract"}, price=0) == (0.0, 0.0, 0.0, 0.0)


class TestOmkostningerGårImodHandlen:
    def test_long_netto_under_brutto(self):
        t = _trade(side="long")
        net = costs.apply_costs(t, CONFIG)
        assert net["pnl_pct_net"] < t["pnl_pct"]

    def test_short_netto_under_brutto(self):
        """Fortegnene vender for en short — omkostningen må ikke vende med."""
        t = _trade(side="short", entry=110.0, exit_=100.0)
        net = costs.apply_costs(t, CONFIG)
        assert t["pnl_pct"] > 0                      # brutto-gevinst
        assert net["pnl_pct_net"] < t["pnl_pct"]     # netto er lavere

    def test_taber_bliver_større_taber(self):
        t = _trade(side="long", entry=100.0, exit_=95.0)
        net = costs.apply_costs(t, CONFIG)
        assert net["pnl_pct_net"] < t["pnl_pct"] < 0

    def test_omkostning_er_positiv_for_alle_symboler(self):
        for symbol in CONFIG["symbols"]:
            net = costs.apply_costs(_trade(symbol=symbol), CONFIG)
            assert net["cost_pct"] > 0, symbol

    def test_slippage_er_aldrig_favorabel(self):
        """En markedsordre der krydser spreadet får ikke en bedre pris end den stillede."""
        for _ in range(50):
            rng = costs._rng(CONFIG, "s", "BTC/USDT")
            net = costs.apply_costs(_trade(), CONFIG, rng)
            assert net["cost_slippage_pct"] >= 0

    def test_fills_ligger_på_den_dyre_side(self):
        long = costs.apply_costs(_trade(side="long", entry=100.0, exit_=110.0), CONFIG)
        assert long["entry_fill"] > 100.0   # køber i asken
        assert long["exit_fill"] < 110.0    # sælger i budet
        short = costs.apply_costs(_trade(side="short", entry=110.0, exit_=100.0), CONFIG)
        assert short["entry_fill"] < 110.0
        assert short["exit_fill"] > 100.0


class TestReproducerbarhed:
    def test_samme_nøgle_giver_samme_slippage(self):
        a = costs.apply_costs(_trade(), CONFIG, costs._rng(CONFIG, "tm", "BTC/USDT"))
        b = costs.apply_costs(_trade(), CONFIG, costs._rng(CONFIG, "tm", "BTC/USDT"))
        assert a == b

    def test_forskellige_symboler_giver_forskellige_træk(self):
        a = costs._rng(CONFIG, "tm", "BTC/USDT").normal(0, 1)
        b = costs._rng(CONFIG, "tm", "ETH/USDT").normal(0, 1)
        assert a != b

    def test_symbol_alene_matcher_symbol_i_suite(self):
        """Kernen i reproducerbarheden: rækkefølgen af symboler må ikke ændre tallene."""
        alene = costs.apply_costs_to_trades(
            [_trade(symbol="ETH/USDT")], CONFIG, "trend_momentum", "ETH/USDT")
        # Samme symbol, men kørt efter et andet symbol i "suiten".
        costs.apply_costs_to_trades(
            [_trade(symbol="BTC/USDT")], CONFIG, "trend_momentum", "BTC/USDT")
        i_suite = costs.apply_costs_to_trades(
            [_trade(symbol="ETH/USDT")], CONFIG, "trend_momentum", "ETH/USDT")
        assert alene[0]["pnl_pct_net"] == i_suite[0]["pnl_pct_net"]

    def test_seed_er_stabil_på_tværs_af_processer(self):
        """zlib.crc32, ikke hash() — Pythons streng-hash er randomiseret pr. proces."""
        import subprocess
        import sys
        code = (
            "import yaml;from backtest import costs;"
            "c=yaml.safe_load(open('config.yaml'));"
            "print(costs._rng(c,'tm','BTC/USDT').normal(0,1))"
        )
        runs = {
            subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True).stdout.strip()
            for _ in range(2)
        }
        assert len(runs) == 1 and runs != {""}


class TestSymbolOverrides:
    def test_eur_usd_bruger_6e_kontrakten(self):
        """6E har halvt tick og dobbelt notional ift. 6B — ét fælles tal ville
        overvurdere EUR/USD's omkostning betydeligt."""
        eur = costs.cost_summary(CONFIG, "EUR/USD", price=1.10)
        gbp = costs.cost_summary(CONFIG, "GBP/USD", price=1.10)
        assert eur["spread_bp"] < gbp["spread_bp"]
        assert eur["commission_bp"] < gbp["commission_bp"]

    def test_override_arver_resten_fra_asset_class(self):
        params = costs._asset_costs(CONFIG, "EUR/USD")
        assert params["tick_size"] == 0.00005        # override
        assert params["spread_ticks"] == 1.0         # arvet fra forex


class TestUdenKonfiguration:
    def test_netto_er_brutto_når_costs_mangler(self):
        t = _trade()
        net = costs.apply_costs(t, {"trading": {"stake_amount": 5.0}})
        assert net["pnl_pct_net"] == t["pnl_pct"]
        assert net["cost_pct"] == 0.0

    def test_ukendt_asset_class_falder_tilbage(self):
        cfg = {"backtest": {"costs": {"crypto": {"mode": "proportional"}}},
               "trading": {"stake_amount": 5.0}}
        net = costs.apply_costs(_trade(symbol="EUR/USD"), cfg)
        assert net["cost_pct"] == 0.0


class TestMetricsBruttoNetto:
    def _trades(self):
        return [
            {"pnl": 1.0, "pnl_pct": 2.0, "pnl_net": 0.8, "pnl_pct_net": 1.6,
             "cost_pct": 0.4, "reason": "take_profit"},
            # Marginal gevinst brutto → tab netto. Præcis det tilfælde der får
            # win_rate til at flytte sig mellem de to opgørelser.
            {"pnl": 0.01, "pnl_pct": 0.02, "pnl_net": -0.1, "pnl_pct_net": -0.2,
             "cost_pct": 0.22, "reason": "stop_loss"},
        ]

    def test_win_rate_kan_flytte_sig(self):
        both = metrics.compute_both(self._trades())
        assert both["gross"]["win_rate"] == 100.0
        assert both["net"]["win_rate"] == 50.0

    def test_begge_opgørelser_er_mærkede(self):
        both = metrics.compute_both(self._trades())
        assert both["gross"]["net"] is False and both["net"]["net"] is True

    def test_samlet_omkostning_summeres(self):
        assert metrics.compute(self._trades(), net=True)["total_cost_pct"] == 0.62

    def test_netto_falder_tilbage_på_brutto_uden_felter(self):
        gamle = [{"pnl": 1.0, "pnl_pct": 2.0, "reason": "take_profit"}]
        assert (metrics.compute(gamle, net=True)["total_pnl_pct"]
                == metrics.compute(gamle)["total_pnl_pct"])

    def test_end_of_data_udelades_også_netto(self):
        t = self._trades() + [{"pnl": 99.0, "pnl_pct": 99.0, "pnl_net": 99.0,
                               "pnl_pct_net": 99.0, "reason": "end_of_data"}]
        assert metrics.compute(t, net=True)["closed_trades"] == 2


class TestBruttoRøresIkke:
    def test_apply_costs_to_trades_beholder_brutto(self):
        trades = [_trade()]
        brutto = trades[0]["pnl_pct"]
        costs.apply_costs_to_trades(trades, CONFIG, "trend_momentum", "BTC/USDT")
        assert trades[0]["pnl_pct"] == brutto
        assert "pnl_pct_net" in trades[0]


class TestKonfigurationRørerIkkeLive:
    def test_costs_ligger_i_egen_sektion(self):
        assert "costs" in CONFIG["backtest"]
        # Ingen af de beskyttede live-nøgler må optræde under backtest.
        forbudt = {"dry_run", "stake_amount", "leverage", "max_open_trades",
                   "total_capital", "min_confidence"}
        assert not (forbudt & set(CONFIG["backtest"].get("costs", {})))

    def test_alle_asset_classes_er_dækket(self):
        c = CONFIG["backtest"]["costs"]
        assert {"crypto", "forex", "gold", "index"} <= set(c)
        for name in ("crypto", "forex", "gold", "index"):
            assert c[name]["mode"] in ("proportional", "contract")


# ---------------------------------------------------------------------------
# Sessionstabel + out-of-sample-split (PRD del 2 og 3)
# ---------------------------------------------------------------------------

class TestSessionstabel:
    def _rows(self):
        return [
            {"symbol": "BTC/USDT", "n": 72, "win_rate": 34.7, "win_rate_net": 33.3,
             "profit_factor": 1.04, "profit_factor_net": 0.91,
             "total_pnl_pct": 3.2, "total_pnl_pct_net": -1.1},
            {"symbol": "TOTAL", "n": 430, "win_rate": 33.0, "win_rate_net": 32.1,
             "profit_factor": 0.98, "profit_factor_net": 0.85,
             "total_pnl_pct": -1.5, "total_pnl_pct_net": -8.2},
        ]

    def test_holder_sig_under_femten_linjer(self):
        """Formatet skal kunne læses i en samtale — også fra mobil."""
        from backtest import report
        rows = [dict(self._rows()[0], symbol=f"SYM{i}") for i in range(6)]
        out = report.format_session_table(rows + [self._rows()[1]], "s", "p", "c")
        assert len(out.splitlines()) <= 15

    def test_viser_både_brutto_og_netto(self):
        from backtest import report
        out = report.format_session_table(self._rows(), "trend_momentum", "2024→2026", "A1")
        assert "WR-brut" in out and "WR-net" in out
        assert "PF-brut" in out and "PF-net" in out
        assert "PnL-brut" in out and "PnL-net" in out
        assert "34.7%" in out and "33.3%" in out   # begge win rates, ikke kun den ene

    def test_header_navngiver_konfigurationen(self):
        from backtest import report
        out = report.format_session_table(self._rows(), "trend_momentum", "2024→2026",
                                          "A2 flip-exit")
        assert out.splitlines()[0] == "BACKTEST  trend_momentum  2024→2026  A2 flip-exit"

    def test_inf_profit_factor_vises_læsbart(self):
        from backtest import report
        rows = [dict(self._rows()[0], profit_factor=float("inf"),
                     profit_factor_net=float("inf"))]
        assert "inf" in report.format_session_table(rows, "s", "p", "c")

    def test_manglende_pf_bliver_tankestreg(self):
        from backtest import report
        rows = [dict(self._rows()[0], profit_factor=None, profit_factor_net=None)]
        assert "—" in report.format_session_table(rows, "s", "p", "c")

    def test_session_row_bygger_fra_compute_both(self):
        from backtest import report
        both = metrics.compute_both([
            {"pnl": 1.0, "pnl_pct": 2.0, "pnl_net": 0.8, "pnl_pct_net": 1.6,
             "cost_pct": 0.4, "reason": "take_profit"},
        ])
        row = report.session_row("BTC/USDT", both)
        assert row["symbol"] == "BTC/USDT" and row["n"] == 1
        assert row["total_pnl_pct"] == 2.0 and row["total_pnl_pct_net"] == 1.6


class TestOutOfSampleSplit:
    def _df(self, n=1000):
        import pandas as pd
        return pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=n, freq="4h"),
            "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
        })

    def test_halvdelene_evaluerer_disjunkte_perioder(self):
        """Anden halvdel får 200 barers warmup MED, men må ikke evaluere dem igen."""
        from research.run_flip_oos_test import WARMUP, split_halves
        first, second = split_halves(self._df())
        assert second["time"].iloc[WARMUP] > first["time"].iloc[-1]

    def test_anden_halvdel_har_varme_indikatorer_ved_skillelinjen(self):
        from research.run_flip_oos_test import WARMUP, split_halves
        first, second = split_halves(self._df())
        assert len(second) == len(self._df()) - len(first) + WARMUP

    def test_kriteriet_afviser_effekt_i_kun_én_halvdel(self):
        """Kernen i testen: virker reglen kun i den ene halvdel, er den støj."""
        from research.run_flip_oos_test import evaluate

        def m(pnl):
            """Minimal metrics-dict i samme form som metrics.compute_both()."""
            g = {"total_pnl_pct": pnl, "closed_trades": 50, "wins": 20,
                 "gross_profit_pct": 10.0, "gross_loss_pct": 10.0 - pnl}
            return {"gross": g, "net": {**g, "total_pnl_pct": pnl - 1,
                                        "total_cost_pct": 1.0}}

        halves = {
            "1. halvdel": {"A1": {s: m(0) for s in "ABCDEF"},
                           "A2": {s: m(5) for s in "ABCDEF"}},   # A2 vinder
            "2. halvdel": {"A1": {s: m(0) for s in "ABCDEF"},
                           "A2": {s: m(-5) for s in "ABCDEF"}},  # A2 taber
        }
        v = evaluate(halves)
        assert v["beats_net"]["1. halvdel"] is True
        assert v["beats_net"]["2. halvdel"] is False
        assert v["all_halves_net"] is False

    def test_kriteriet_bekræfter_når_begge_halvdele_vinder(self):
        from research.run_flip_oos_test import evaluate

        def m(pnl):
            """Minimal metrics-dict i samme form som metrics.compute_both()."""
            g = {"total_pnl_pct": pnl, "closed_trades": 50, "wins": 20,
                 "gross_profit_pct": 10.0, "gross_loss_pct": 10.0 - pnl}
            return {"gross": g, "net": {**g, "total_pnl_pct": pnl - 1,
                                        "total_cost_pct": 1.0}}

        halves = {
            h: {"A1": {s: m(0) for s in "ABCDEF"}, "A2": {s: m(5) for s in "ABCDEF"}}
            for h in ("1. halvdel", "2. halvdel")
        }
        v = evaluate(halves)
        assert v["all_halves_gross"] and v["all_halves_net"] and v["symbols_ok"]
