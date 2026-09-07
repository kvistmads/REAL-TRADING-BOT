"""FASE 2: kombinér de otte TSMOM-kurver til én portefølje.

Hypotesen der testes: **mange halvgode ukorrelerede kilder slår én god.** Matematikken
siger at N ukorrelerede kilder med Sharpe s giver samlet Sharpe s × √N. Spørgsmålet er
hvor mange uafhængige kilder vi reelt har — og det afhænger af korrelationen mellem
STRATEGIERNES afkast, ikke mellem aktivernes.

## Vægtning: invers volatilitet, bagudskuende

Krypto har 5-9× aktiernes volatilitet. Lige kapitalvægt ville lade BTC og ETH bestemme
hele porteføljens forløb, og resultatet ville være en krypto-kørsel med aktier som pynt.
Vægten er derfor ``w_i = (1/σ_i) / Σ(1/σ_j)`` — lige risikobidrag.

**σ måles på et BAGUDSKUENDE vindue** (12 måneders daglige afkast frem til dagen før
rebalanceringen), aldrig på hele perioden. Fuldperiode-volatilitet til vægtning er
klassisk skjult lookahead: den ville systematisk undervægte netop de instrumenter der
senere viste sig turbulente, pynte resultatet, og gøre det uden at nogen opdagede det.
``tests/test_portfolio.py`` har en test der fejler hvis vægten på dag t afhænger af
data efter dag t.

σ annualiseres med instrumentets EGET antal barer pr. år — krypto har 365, futures
~252. Uden det ville krypto se ~20% mere volatil ud end den er, alene på grund af
kalenderen.

## Hvad der ligger i porteføljen

Instrumentet ligger der med sin **TSMOM-position** (long eller kontant), ikke med
aktivet selv. Er signalet ude, står pladsens kapital i kontanter — og kontanter
forrentes ikke, samme konservative konvention som i fase 1.

## Omkostninger: to kilder til omsætning

1. **Signalskift** — TSMOM går ind eller ud. Modelleret i fase 1.
2. **Vægtrebalancering** — vægtene driver mellem månedsskiftene og skal handles
   tilbage på plads. Det er omsætning UD OVER signalskiftene, og den skal betales.

Begge håndteres af én mekanisme: hver gang en plads' positionsstørrelse ændrer sig,
handles differencen og der betales envejs-omkostning på det handlede beløb. Ingen
gearing — en plads kan aldrig købe for mere end den har plus kontantbeholdningen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest import costs as cost_model
from research import tsmom
from research.daily_series import INSTRUMENTS, Instrument, load

# Vinduet vægtene beregnes på. 12 måneder er valgt for at matche TSMOM's eget
# lookback — ikke optimeret.
VOL_MONTHS = 12

# **Ét instrument pr. underliggende aktiv.** XAU er ude: den korrelerede 0,98 med
# GC i BEGGE matricer — det er samme metal fra to datakilder, ikke to væddemål. Med
# invers volatilitetsvægtning fik guld dermed dobbelt risikobudget. Det er en
# konstruktionsfejl, ikke et resultat.
#
# GC=F beholdes frem for XAU af DATAKVALITET, ikke afkast: GC kommer fra yfinance
# som resten (kendt, reproducerbar kilde), roll-effekten er målt til 0,04
# pct-point/år, og serien dækker 2000-2026. XAU er et ukendt MT4-feed med
# tick-volumen, validerer kun 2004-2024, og afveg 20% i ATR mod den anden kilde.
DUPLICATE_UNDERLYING = ("XAU",)

UNIVERSES = {
    "alle_syv": [k for k in INSTRUMENTS if k not in DUPLICATE_UNDERLYING],
    "uden_fx": [k for k in INSTRUMENTS
                if k not in DUPLICATE_UNDERLYING and k not in ("6E", "6B")],
}


@dataclass
class Leg:
    """Ét instruments TSMOM-position, klar til at indgå i en portefølje."""

    key: str
    inst: Instrument
    dates: pd.DatetimeIndex
    open_: np.ndarray
    close: np.ndarray
    pos: np.ndarray                      # 0/1 pr. egen bar
    exec_by_period: dict = field(default_factory=dict)   # Period -> eget bar-indeks
    one_way_cost: float = 0.0            # brøkdel pr. handlet beløb


def build_leg(key: str, config: dict, lookback_months: int = 12,
              rebalance_day: int = 1) -> Leg:
    """Byg én leg fra fase 1's maskineri. Signalgrænsen er den samme.

    Positionerne kommer fra ``tsmom``-modulet, så porteføljen ikke kan komme til at
    bruge en anden signaldefinition end den enkeltinstrument-kørslen validerede.
    """
    inst = INSTRUMENTS[key]
    df = load(inst)
    schedule = tsmom.build_schedule(df, lookback_months, rebalance_day)
    pos = tsmom._position_series(df, schedule)

    params = cost_model._asset_costs(config, inst.cost_symbol)
    if params:
        mid = float(df["close"].iloc[len(df) // 2])
        spread, slip, _, comm = cost_model.cost_fractions(params, mid)
        one_way = spread / 2 + slip + comm / 2
    else:
        one_way = 0.0

    return Leg(
        key=key, inst=inst, dates=pd.DatetimeIndex(df["time"]),
        open_=df["open"].to_numpy(float), close=df["close"].to_numpy(float),
        pos=pos, exec_by_period={r.period: r.exec_idx for r in schedule},
        one_way_cost=one_way,
    )


def daily_returns(leg: Leg) -> pd.Series:
    """Instrumentets EGNE daglige afkast (aktivet, ikke strategien)."""
    return pd.Series(leg.close, index=leg.dates).pct_change().dropna()


def trailing_vol(leg: Leg, asof: pd.Timestamp, months: int = VOL_MONTHS) -> float:
    """Annualiseret volatilitet på et bagudskuende vindue, STRENGT før ``asof``.

    Uligheden ``< asof`` er hele pointen. ``<=`` ville lade rebalanceringsdagens
    egen bar indgå, og dét er allerede lookahead — samme fejl som at regne
    TSMOM-signalet frem til eksekveringsbarens close.
    """
    start = asof - pd.DateOffset(months=months)
    mask = (leg.dates >= start) & (leg.dates < asof)
    if mask.sum() < 20:
        return float("nan")
    window = pd.Series(leg.close[mask]).pct_change().dropna()
    if len(window) < 20 or window.std(ddof=1) <= 0:
        return float("nan")
    return float(window.std(ddof=1) * np.sqrt(leg.inst.bars_per_year))


def weights_and_vols(legs: dict[str, Leg], asof: pd.Timestamp,
                     months: int = VOL_MONTHS) -> tuple[dict, dict]:
    """(vægte, volatiliteter) på ``asof``. Volatiliteterne genbruges til risikobidrag.

    Ren funktion af data STRENGT før ``asof``. Legs uden brugbart vindue får vægt 0
    frem for at blive gættet på — en manglende volatilitet er ikke en lav volatilitet.
    """
    vols, inv = {}, {}
    for key, leg in legs.items():
        vol = trailing_vol(leg, asof, months)
        if np.isfinite(vol) and vol > 0:
            vols[key] = vol
            inv[key] = 1.0 / vol
    total = sum(inv.values())
    if total <= 0:
        return {k: 0.0 for k in legs}, vols
    return {k: inv.get(k, 0.0) / total for k in legs}, vols


def inverse_vol_weights(legs: dict[str, Leg], asof: pd.Timestamp,
                        months: int = VOL_MONTHS) -> dict[str, float]:
    """Lige risikobidrag over de legs der har historik nok på ``asof``."""
    return weights_and_vols(legs, asof, months)[0]


@dataclass
class PortfolioResult:
    equity: pd.Series
    exposure: pd.Series             # andel af kapitalen i markedet
    weights: pd.DataFrame           # måltvægt pr. måned pr. leg
    n_live: pd.Series               # hvor mange instrumenter var med
    benchmark: pd.Series            # ligevægtet buy-and-hold
    turnover_cost_pct: float        # samlede omkostninger i pct af startkapital
    rebalance_cost_share: float     # heraf vægtrebalancering (ikke signalskift)
    # Bidrag pr. instrument. De to svarer på hvert sit spørgsmål, og et instrument
    # der leverer 5% af afkastet for 20% af risikoen skal kunne ses med det samme.
    return_contribution: dict = field(default_factory=dict)   # andel af samlet PnL
    risk_contribution: dict = field(default_factory=dict)     # andel af vægt × vol


def run_portfolio(legs: dict[str, Leg], vol_months: int = VOL_MONTHS) -> PortfolioResult:
    """Daglig simulering af den samlede portefølje.

    Bogholderiet er eksplicit: ``cash`` plus én ``slot``-værdi pr. instrument.
    E = cash + Σ slots. En plads kan aldrig købe for mere end sin egen værdi plus
    kontantbeholdningen — ingen gearing, ingen implicit lån.
    """
    master = _master_index(legs)
    if len(master) < 2:
        raise ValueError("for lidt overlappende historik")

    periods = pd.PeriodIndex(master, freq="M")
    # Vægtene beregnes ÉN gang pr. måned, på den første master-dato i måneden,
    # og udelukkende af data før den dato.
    month_first = {}
    for i, p in enumerate(periods):
        month_first.setdefault(p, i)
    computed = {p: weights_and_vols(legs, master[i], vol_months)
                for p, i in month_first.items()}
    weight_by_period = {p: w for p, (w, _) in computed.items()}
    vol_by_period = {p: v for p, (_, v) in computed.items()}

    keys = list(legs)
    slot = dict.fromkeys(keys, 0.0)
    cash = 1.0
    equity = np.zeros(len(master))
    invested = np.zeros(len(master))
    live = np.zeros(len(master), dtype=int)
    cost_total = 0.0
    cost_rebalance = 0.0
    # Bidragsbogholderi. pnl tæller KUN kursbevægelser — rebalanceringens
    # pengestrømme er flytninger, ikke afkast, og må ikke smitte af.
    pnl = dict.fromkeys(keys, 0.0)
    fees = dict.fromkeys(keys, 0.0)
    risk_sum = dict.fromkeys(keys, 0.0)

    aligned = {k: _align(leg, master) for k, leg in legs.items()}

    for t in range(len(master)):
        period = periods[t]
        weights = weight_by_period[period]

        for key in keys:
            a = aligned[key]
            if not a["has"][t]:
                continue
            leg = legs[key]

            # 1) Marker til markedet frem til dagens open (kun hvis pladsen er investeret).
            if slot[key] > 0 and np.isfinite(a["prev_c"][t]) and a["prev_c"][t] > 0:
                before = slot[key]
                slot[key] *= a["o"][t] / a["prev_c"][t]
                pnl[key] += slot[key] - before

            # 2) Er dette instrumentets eksekveringsbar for måneden, rebalancér.
            if a["is_exec"][t]:
                e_now = cash + sum(slot.values())
                target = weights.get(key, 0.0) * e_now if a["want"][t] else 0.0
                # Ingen gearing — og loftet skal levne plads til KURTAGEN.
                # Et loft på slot + cash lader kontantbeholdningen ende på minus
                # gebyret: et lån på 1-2 basispunkter, som ser ud som afkast.
                # Købet må højst være cash/(1+c), så cash forbliver >= 0.
                headroom = slot[key] + max(cash, 0.0) / (1 + leg.one_way_cost)
                target = min(target, headroom)
                traded = abs(target - slot[key])
                if traded > 0:
                    fee = traded * leg.one_way_cost
                    cost_total += fee
                    fees[key] += fee
                    # Skiftede signalet ikke, er hele handlen ren vægtrebalancering.
                    if (slot[key] > 0) == bool(a["want"][t]):
                        cost_rebalance += fee
                    cash += slot[key] - target - fee
                    slot[key] = target

            # 3) Resten af dagen: open -> close.
            if slot[key] > 0 and a["o"][t] > 0:
                before = slot[key]
                slot[key] *= a["c"][t] / a["o"][t]
                pnl[key] += slot[key] - before

        invested_now = sum(slot.values())
        equity[t] = cash + invested_now
        invested[t] = invested_now / equity[t] if equity[t] > 0 else 0.0
        live[t] = sum(1 for k in keys if weights.get(k, 0.0) > 0)

        # Risikobidrag = FAKTISK vægt × volatilitet, akkumuleret dag for dag.
        # Den faktiske vægt (og ikke måltvægten) fordi en plads i kontanter bærer
        # ingen risiko, uanset hvad den var tildelt ved månedsskiftet.
        if equity[t] > 0:
            vols = vol_by_period[period]
            for key in keys:
                if slot[key] > 0 and key in vols:
                    risk_sum[key] += slot[key] / equity[t] * vols[key]

    eq = pd.Series(equity, index=master)
    # Kurven starter først når mindst ét instrument har kunnet handle.
    first = int(np.argmax(live > 0)) if (live > 0).any() else 0
    eq = eq.iloc[first:] / eq.iloc[first]

    net_pnl = {k: pnl[k] - fees[k] for k in keys}
    pnl_total = sum(net_pnl.values())
    risk_total = sum(risk_sum.values())

    return PortfolioResult(
        # Andele kan overstige 100% eller være negative når nogle bidrag er
        # negative. Det er et rigtigt udsagn om porteføljen og normaliseres ikke væk.
        return_contribution={k: round(100 * net_pnl[k] / pnl_total, 1)
                             for k in keys} if abs(pnl_total) > 1e-12 else {},
        risk_contribution={k: round(100 * risk_sum[k] / risk_total, 1)
                           for k in keys} if risk_total > 0 else {},
        equity=eq,
        exposure=pd.Series(invested[first:], index=master[first:]),
        weights=pd.DataFrame(weight_by_period).T.sort_index(),
        n_live=pd.Series(live[first:], index=master[first:]),
        benchmark=equal_weight_buy_and_hold(legs, master[first:]),
        turnover_cost_pct=round(cost_total * 100, 3),
        rebalance_cost_share=round(100 * cost_rebalance / cost_total, 1) if cost_total > 0 else 0.0,
    )


def equal_weight_buy_and_hold(legs: dict[str, Leg], index: pd.DatetimeIndex) -> pd.Series:
    """DEL 4 — ligevægtet køb-og-behold af de SAMME instrumenter, samme periode.

    Samme omkostningskonvention som strategien: én rundtur pr. instrument over hele
    perioden. Instrumenter der starter senere (BTC, ETH) købes når de findes, og
    kapitalen står i kontanter indtil da — ellers ville baselinen enten skulle
    forudse hvornår Binance åbnede, eller bruge en kortere periode end strategien.
    """
    curves = []
    for leg in legs.values():
        mask = (leg.dates >= index[0]) & (leg.dates <= index[-1])
        if mask.sum() < 2:
            continue
        series = pd.Series(leg.close[mask], index=leg.dates[mask])
        # Én rundtur: dyrere indgang, billigere udgang.
        c = leg.one_way_cost
        curve = (series / series.iloc[0]) * (1 - c) / (1 + c)
        curve.iloc[0] = 1.0
        curves.append(curve.reindex(index).ffill().fillna(1.0))
    if not curves:
        return pd.Series(1.0, index=index)
    return pd.concat(curves, axis=1).mean(axis=1)


def _master_index(legs: dict[str, Leg]) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex([])
    for leg in legs.values():
        idx = idx.union(leg.dates)
    return idx.sort_values()


def _align(leg: Leg, master: pd.DatetimeIndex) -> dict:
    """Projicér én legs barer op på master-indekset.

    ``prev_c`` er legens SENESTE egne close før denne dato — ikke gårsdagens
    master-dato. Handler SPY ikke i weekenden, skal mandagens afkast måles fra
    fredagens close, ikke fra en dag der ikke findes for SPY.
    """
    n = len(master)
    pos_in_master = master.get_indexer(leg.dates)
    has = np.zeros(n, dtype=bool)
    o = np.full(n, np.nan)
    c = np.full(n, np.nan)
    prev_c = np.full(n, np.nan)
    is_exec = np.zeros(n, dtype=bool)
    want = np.zeros(n, dtype=np.int8)

    has[pos_in_master] = True
    o[pos_in_master] = leg.open_
    c[pos_in_master] = leg.close
    prev_c[pos_in_master[1:]] = leg.close[:-1]
    for period, own_idx in leg.exec_by_period.items():
        m = pos_in_master[own_idx]
        is_exec[m] = True
        want[m] = leg.pos[own_idx]
    return {"has": has, "o": o, "c": c, "prev_c": prev_c,
            "is_exec": is_exec, "want": want}
