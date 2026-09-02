"""Omkostningsmodel for backtesten — spread, slippage og kurtage.

Indtil nu har hvert tal i projektets historie været BRUTTO: `trend_momentum` PF 0,98,
`volatility_breakout` PF 1,16 og hele flip-exit-sammenligningen er beregnet uden at
betale for at komme ind og ud af markedet. Dette modul lukker det hul.

**Rører ikke live.** Konfigurationen ligger i sin egen ``backtest.costs``-sektion og
læses kun herfra; ingen live-parameter kan påvirkes af den.

## Enheder — hvorfor futures ikke er i basispunkter

Krypto-gebyrer er proportionale (0,10% af notional), mens futures-omkostninger er
defineret i kontraktens egne enheder: et tick på COMEX GC er 0,10 USD uanset om guld
står i 2.250 eller 4.500. Regner man den om til basispunkter og fryser tallet i en
config, indbygger man et prisniveau i modellen — og på 2 års data er den fejl på
størrelse med selve omkostningen. Derfor:

- ``mode: proportional`` → omkostningen ER en brøkdel af prisen (krypto)
- ``mode: contract``     → omkostningen er i ticks/USD og omregnes til en brøkdel
  ved HVER handel ud fra dens faktiske entry-pris

Begge ender samme sted: en brøkdel af prisen, som kan trækkes fra ``pnl_pct``.

## Hvad der er slået op, og hvad der er skøn

Slået op i børsernes dokumentation (se ``research/output/cost_model.md`` for kilder):
kontraktstørrelser, tick-værdier og Binances gebyrsatser. **Skøn:** spread på ét tick
og slippage på et halvt tick. Der findes ingen offentliggjort slippage-statistik at
slå op, og et tal der ser præcist ud ville være værre end et ærligt skøn.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np

from strategies.base import BaseStrategy


@dataclass(frozen=True)
class CostResult:
    """Omkostningen ved én handel, opgjort i brøkdele af entry-prisen."""

    spread: float       # halvdelen betalt ved entry, halvdelen ved exit
    slippage: float     # summen af entry- og exit-slippage
    commission: float   # pr. rundtur
    entry_fill: float   # faktisk fyldpris efter spread + slippage
    exit_fill: float

    @property
    def total(self) -> float:
        return self.spread + self.slippage + self.commission


def _asset_costs(config: dict, symbol: str) -> dict | None:
    """Omkostningsparametre for et symbol: asset-class-default + symbol-override.

    Returnerer None hvis ``backtest.costs`` ikke er konfigureret — så kører
    backtesten som før (rent brutto), i stedet for at fejle på en ældre config.
    """
    costs = (config.get("backtest") or {}).get("costs")
    if not costs:
        return None
    asset_class = BaseStrategy.get_asset_class(symbol)
    base = costs.get(asset_class)
    if not base:
        return None
    override = (costs.get("symbols") or {}).get(symbol) or {}
    return {**base, **override}


def _rng(config: dict, strategy_id: str, symbol: str) -> np.random.Generator:
    """Deterministisk generator pr. (seed, strategi, symbol).

    Nøglen indgår i seedet, så ét symbol kørt alene giver PRÆCIS samme slippage som
    det samme symbol kørt i den fulde suite. Et enkelt globalt ``default_rng(seed)``
    ville lade rækkefølgen af symboler bestemme tallene, og så kan to kørsler af
    "samme" backtest ikke sammenlignes. zlib.crc32 frem for ``hash()``: Pythons
    streng-hash er randomiseret pr. proces og ville bryde reproducerbarheden.
    """
    seed = (config.get("backtest") or {}).get("costs", {}).get("slippage_seed", 0)
    key = f"{seed}|{strategy_id}|{symbol}".encode()
    return np.random.default_rng(zlib.crc32(key))


def cost_fractions(params: dict, price: float) -> tuple[float, float, float, float]:
    """(spread, slippage_mean, slippage_std, commission) som brøkdele af `price`.

    For ``mode: contract`` omregnes ticks og USD-kurtage til brøkdele ud fra den
    faktiske pris og kontraktens multiplier — derfor skaleres omkostningen korrekt
    når instrumentet flytter sig over årene.
    """
    if price <= 0:
        return (0.0, 0.0, 0.0, 0.0)

    if params.get("mode") == "proportional":
        return (
            float(params.get("spread_pct", 0.0)),
            float(params.get("slippage_mean_pct", 0.0)),
            float(params.get("slippage_std_pct", 0.0)),
            float(params.get("commission_pct", 0.0)),
        )

    tick = float(params.get("tick_size", 0.0))
    multiplier = float(params.get("contract_multiplier", 1.0))
    notional = multiplier * price
    return (
        float(params.get("spread_ticks", 0.0)) * tick / price,
        float(params.get("slippage_mean_ticks", 0.0)) * tick / price,
        float(params.get("slippage_std_ticks", 0.0)) * tick / price,
        (float(params.get("commission_usd_round_turn", 0.0)) / notional
         if notional > 0 else 0.0),
    )


def apply_costs(trade: dict, config: dict, rng: np.random.Generator | None = None) -> dict:
    """Beregn netto-udfald for én simuleret handel.

    Returnerer et dict med ``pnl_pct_net``, ``pnl_net`` og omkostningsopdelingen.
    Brutto-felterne på ``trade`` røres ALDRIG — begge tal skal kunne vises side om
    side, så man kan se præcis hvad omkostningerne æder.

    Spread betales halvt ved entry og halvt ved exit. Slippage trækkes pr. fill fra
    N(mean, std) og afkortes ved 0: en markedsordre der krydser spreadet kan ikke
    få en bedre pris end den stillede — den favorable hale er en fiktion.
    """
    params = _asset_costs(config, trade["symbol"])
    if params is None:
        # Ingen omkostningsmodel konfigureret → netto == brutto, eksplicit markeret.
        return {
            "pnl_pct_net": trade["pnl_pct"], "pnl_net": trade["pnl"],
            "cost_pct": 0.0, "cost_spread_pct": 0.0,
            "cost_slippage_pct": 0.0, "cost_commission_pct": 0.0,
            "entry_fill": trade["entry_price"], "exit_fill": trade["exit_price"],
        }

    rng = rng or _rng(config, trade.get("strategy_id", ""), trade["symbol"])
    entry, exit_ = float(trade["entry_price"]), float(trade["exit_price"])
    spread, slip_mean, slip_std, commission = cost_fractions(params, entry)

    half_spread = spread / 2.0
    slip_entry = max(0.0, float(rng.normal(slip_mean, slip_std)))
    slip_exit = max(0.0, float(rng.normal(slip_mean, slip_std)))

    # Begge fills går ALTID imod handlen: man køber i asken og sælger i budet.
    if trade["side"] == "long":
        entry_fill = entry * (1 + half_spread + slip_entry)
        exit_fill = exit_ * (1 - half_spread - slip_exit)
        gross_net_pct = (exit_fill - entry_fill) / entry_fill * 100
    else:
        entry_fill = entry * (1 - half_spread - slip_entry)
        exit_fill = exit_ * (1 + half_spread + slip_exit)
        gross_net_pct = (entry_fill - exit_fill) / entry_fill * 100

    pnl_pct_net = gross_net_pct - commission * 100
    stake = config.get("trading", {}).get("stake_amount", 0.0)

    return {
        "pnl_pct_net": round(pnl_pct_net, 4),
        "pnl_net": round(pnl_pct_net / 100 * stake, 4),
        "cost_pct": round(trade["pnl_pct"] - pnl_pct_net, 4),
        "cost_spread_pct": round(spread * 100, 6),
        "cost_slippage_pct": round((slip_entry + slip_exit) * 100, 6),
        "cost_commission_pct": round(commission * 100, 6),
        "entry_fill": round(entry_fill, 8),
        "exit_fill": round(exit_fill, 8),
    }


def apply_costs_to_trades(trades: list[dict], config: dict, strategy_id: str,
                          symbol: str) -> list[dict]:
    """Berig en liste handler med netto-felter. Muterer og returnerer listen.

    Én generator for hele listen, seedet på (strategi, symbol): trækkene er dermed
    de samme uanset hvornår i en suite symbolet køres.
    """
    rng = _rng(config, strategy_id, symbol)
    for trade in trades:
        trade.update(apply_costs(trade, config, rng))
    return trades


def cost_summary(config: dict, symbol: str, price: float) -> dict:
    """Omkostningsopdeling i basispunkter ved en given pris — til rapportering."""
    params = _asset_costs(config, symbol)
    if params is None:
        return {}
    spread, slip_mean, _, commission = cost_fractions(params, price)
    return {
        "symbol": symbol,
        "asset_class": BaseStrategy.get_asset_class(symbol),
        "price": price,
        "spread_bp": round(spread * 10_000, 3),
        "slippage_bp": round(2 * slip_mean * 10_000, 3),  # entry + exit
        "commission_bp": round(commission * 10_000, 3),
        "total_bp": round((spread + 2 * slip_mean + commission) * 10_000, 3),
    }
