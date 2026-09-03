"""DEL 3: time-series momentum med ÉN parameter.

```
Ved hvert månedsskifte:
    hvis afkastet over de seneste 12 måneder er positivt  -> vær long i næste måned
    ellers                                                -> vær ude af markedet
```

Det er det hele. Ingen indikatorer, ingen filtre, ingen confidence-score, ingen
gates, intet stop loss, intet take profit. Positionen holdes til næste månedsskifte
og handles til åbningskursen på første bar efter skiftet.

**Tilføj ingenting.** Fristelsen til at "bare lige" lægge et stop på eller et filter
til, er præcis den fejl der gav os femten parametre på 430 handler.

Modulet ligger bevidst i ``research/`` og ikke i ``strategies/``: registry'et
auto-discoverer ``BaseStrategy``-subklasser, og intet her må kunne samles op og ende
i live.

## Lookahead — grænsen er et objekt, ikke en kommentar

Den nemme fejl er at regne 12-måneders-afkastet frem til EKSEKVERINGSBARENS close i
stedet for forrige måneds close. Det er én bars lookahead, det er usynligt i
resultatet, og det ville gøre hele fase 1 værdiløs.

Derfor beregnes intet signal "undervejs". ``build_schedule`` bygger først en liste af
``Rebalance``-objekter, hvor hver enkelt bærer sine tre indeks eksplicit:

    ref_idx  <  signal_idx  <  exec_idx

``signal_idx`` er sidste bar FØR eksekveringsbaren; ``ref_idx`` er sidste bar før
lookback-vinduets start. Signalet er en ren funktion af ``close`` på de to, og
``exec_idx`` bruges udelukkende til ``open``. Uligheden håndhæves i
``tests/test_tsmom.py`` med en test der kan køre rødt.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest import costs as cost_model
from research.daily_series import Instrument

# Lookbacks der køres hver gang. 12 er reglen; 3/6/9 er robusthedstjek — er 12 den
# eneste der virker, er 12 en tilfældighed. Vælg ikke en vinder.
LOOKBACKS = (3, 6, 9, 12)

# Rebalanceringsdage. Den 1. er reglen. Den 15. er ikke en alternativ strategi, men
# en kontrol: virker TSMOM kun når der rebalanceres den 1., har vi fundet en
# turn-of-month-effekt — et velkendt og separat fænomen — og ikke momentum.
REBALANCE_DAYS = (1, 15)


@dataclass(frozen=True)
class Rebalance:
    """Ét månedsskifte. Bærer sine indeks eksplicit, så grænsen kan testes.

    ``ref_idx`` og ``signal_idx`` er de ENESTE barer signalet må se.
    ``exec_idx`` er den bar handlen udføres på, og kun dens ``open`` bruges.
    """

    period: pd.Period
    exec_idx: int
    signal_idx: int
    ref_idx: int
    slip_days: int      # hvor mange dage efter den tilsigtede dato baren ligger


def build_schedule(df: pd.DataFrame, lookback_months: int,
                   rebalance_day: int = 1) -> list[Rebalance]:
    """Rebalanceringsplanen for hele serien.

    Månedsskiftet er defineret i KALENDERTID: første tilgængelige bar med dato
    >= ``rebalance_day`` i måneden. På krypto er det den dato selv; på futures og
    aktier den første handelsdag derefter. Lookbacket måles tilsvarende i
    kalendertid (12 måneder), ikke i antal barer — 365 vs ~252 barer om året ville
    ellers gøre "12 måneder" til to forskellige ting.

    Tidsstemplerne er allerede reduceret til ren dato i UTC af
    ``daily_series.load``.
    """
    times = df["time"].to_numpy()
    dates = pd.DatetimeIndex(df["time"])
    schedule: list[Rebalance] = []

    months = pd.period_range(dates[0].to_period("M"), dates[-1].to_period("M"), freq="M")
    for period in months:
        target = period.to_timestamp() + pd.Timedelta(days=rebalance_day - 1)
        # Første bar PÅ eller EFTER måltidspunktet.
        exec_idx = int(np.searchsorted(times, np.datetime64(target), side="left"))
        if exec_idx >= len(times) or exec_idx == 0:
            continue
        # Eksekveringsbaren skal ligge i samme måned — ellers er måneden ikke dækket.
        if dates[exec_idx].to_period("M") != period:
            continue

        signal_idx = exec_idx - 1                      # sidste bar FØR eksekvering
        signal_date = dates[signal_idx]
        ref_target = signal_date - pd.DateOffset(months=lookback_months)
        # Sidste bar PÅ eller FØR lookback-vinduets start.
        ref_idx = int(np.searchsorted(times, np.datetime64(ref_target), side="right")) - 1
        if ref_idx < 0:
            continue
        # Vinduet skal reelt dække lookbacket; ellers måler vi noget kortere.
        if (signal_date - dates[ref_idx]).days < lookback_months * 30 - 10:
            continue

        schedule.append(Rebalance(
            period=period, exec_idx=exec_idx, signal_idx=signal_idx, ref_idx=ref_idx,
            slip_days=int((dates[exec_idx] - target).days),
        ))
    return schedule


def signal_for(df: pd.DataFrame, reb: Rebalance) -> bool:
    """Long hvis afkastet over lookback-vinduet er positivt. Ellers ude.

    Ren funktion af ``close`` på ``ref_idx`` og ``signal_idx`` — begge strengt før
    ``exec_idx``. Rør ikke denne funktion uden at køre lookahead-testen.
    """
    closes = df["close"].to_numpy()
    return bool(closes[reb.signal_idx] > closes[reb.ref_idx])


def _position_series(df: pd.DataFrame, schedule: list[Rebalance]) -> np.ndarray:
    """0/1 pr. bar: holdes aktivet fra denne bars open til dens close?

    En rebalancering på bar i sætter tilstanden fra og med bar i. Mellem to
    rebalanceringer er tilstanden uændret — det er dét der gør at et uændret
    signal IKKE udløser en handel.
    """
    pos = np.zeros(len(df), dtype=np.int8)
    if not schedule:
        return pos
    for k, reb in enumerate(schedule):
        state = 1 if signal_for(df, reb) else 0
        end = schedule[k + 1].exec_idx if k + 1 < len(schedule) else len(df)
        pos[reb.exec_idx:end] = state
    return pos


@dataclass
class TsmomResult:
    """Udfaldet af én kørsel: kurve, eksponering og bogholderi."""

    equity: pd.Series           # dagligt mark-to-market, starter i 1.0
    exposure: pd.Series         # 0/1 pr. dag
    benchmark: pd.Series        # buy-and-hold, samme periode, én rundtur
    positions: int              # antal sammenhængende holdeperioder
    hold_months: float          # gennemsnitlig holdeperiode
    switches_per_year: float
    gross_equity_end: float     # slutkapital UDEN omkostninger
    cost_share_of_gross: float  # omkostninger som andel af bruttoafkastet
    slip_days: pd.Series        # hvor mange dage rebalanceringen gled


def run_tsmom(df: pd.DataFrame, inst: Instrument, config: dict,
              lookback_months: int = 12, rebalance_day: int = 1) -> TsmomResult:
    """Kør reglen på én daglig serie. Ingen stop, intet TP, hele kapitalen.

    Egenkapitalkurven er DAGLIG mark-to-market — ikke handel-for-handel. Uden det
    ville strategiens dyk inde i en position være usynlige, mens buy-and-hold blev
    målt hver dag, og kriteriet om lavere drawdown ville være rigget til at bestå.

    ## Omkostninger

    Én rundtur pr. sammenhængende holdeperiode, ikke pr. måned: er signalet stadig
    long ved månedsskiftet, sendes der ingen ordre, og så må der heller ikke
    opkræves noget. Spread og slippage lægges på fill-prisen (åbningskursen),
    kurtagen halvt ved hver fill.

    **Finansiering modelleres ikke.** For ``ownership == "derivat"`` (GC, 6E, 6B,
    XAU-spot) ville roll eller swap løbe på over en holdeperiode på måneder. Det
    er en kendt mangel, ikke en antagelse om at den er nul — se rapporten.
    """
    schedule = build_schedule(df, lookback_months, rebalance_day)
    pos = _position_series(df, schedule)
    dates = pd.DatetimeIndex(df["time"])
    open_, close = df["open"].to_numpy(float), df["close"].to_numpy(float)

    params = cost_model._asset_costs(config, inst.cost_symbol)
    rng = cost_model._rng(config, f"tsmom{lookback_months}", inst.cost_symbol)

    equity = np.ones(len(df))
    gross = np.ones(len(df))
    cost_paid = 0.0
    start = schedule[0].exec_idx if schedule else len(df)

    for i in range(max(start, 1), len(df)):
        held, prev = pos[i], pos[i - 1]
        r = r_gross = 0.0
        if held and prev:                       # holdt igennem
            r = r_gross = close[i] / close[i - 1] - 1
        elif held and not prev:                 # ind på denne bars open
            fill, fee = _fill(open_[i], params, rng, side="buy")
            r = close[i] / fill - 1 - fee
            r_gross = close[i] / open_[i] - 1
        elif prev and not held:                 # ud på denne bars open
            fill, fee = _fill(open_[i], params, rng, side="sell")
            r = fill / close[i - 1] - 1 - fee
            r_gross = open_[i] / close[i - 1] - 1
        equity[i] = equity[i - 1] * (1 + r)
        gross[i] = gross[i - 1] * (1 + r_gross)
        cost_paid += r_gross - r

    eq = pd.Series(equity[start:], index=dates[start:])
    ex = pd.Series(pos[start:].astype(float), index=dates[start:])
    gr = pd.Series(gross[start:], index=dates[start:])

    # Buy-and-hold på PRÆCIS samme periode, med samme omkostningskonvention:
    # én rundtur over hele perioden. Ikke nul.
    bh_cost = _round_turn_pct(params, float(close[start])) if params else 0.0
    bh = metrics_buy_and_hold(df["close"].iloc[start:], dates[start:], bh_cost)

    switches = int(np.sum(np.abs(np.diff(pos[start:]))) ) if len(pos[start:]) > 1 else 0
    entries = int(np.sum((pos[start:] == 1) & (np.r_[0, pos[start:-1]] == 0)))
    years = max((dates[-1] - dates[start]).days / 365.25, 1e-9)
    days_in = float(np.sum(pos[start:]))
    gross_ret = float(gr.iloc[-1] - 1)

    return TsmomResult(
        equity=eq, exposure=ex, benchmark=bh,
        positions=entries,
        hold_months=round(days_in / max(entries, 1) / 30.44, 2),
        switches_per_year=round(switches / years, 2),
        gross_equity_end=round(float(gr.iloc[-1]), 4),
        # Omkostninger som andel af BRUTTOAFKASTET: er de 3%, er mine skøn
        # ligegyldige; er de 40%, står og falder alt med dem.
        cost_share_of_gross=round(100 * cost_paid / abs(gross_ret), 1) if abs(gross_ret) > 1e-9 else 0.0,
        slip_days=pd.Series([r.slip_days for r in schedule]),
    )


def _round_turn_pct(params: dict, price: float) -> float:
    """Samlet rundtur i procent ved en given pris — spread + 2× slippage + kurtage."""
    spread, slip_mean, _, commission = cost_model.cost_fractions(params, price)
    return (spread + 2 * slip_mean + commission) * 100


def _fill(price: float, params: dict | None, rng, side: str) -> tuple[float, float]:
    """Fill-pris og kurtage-brøkdel for én ordre. Begge går imod handlen."""
    if params is None:
        return price, 0.0
    spread, slip_mean, slip_std, commission = cost_model.cost_fractions(params, price)
    slip = max(0.0, float(rng.normal(slip_mean, slip_std)))
    adverse = spread / 2 + slip
    fill = price * (1 + adverse) if side == "buy" else price * (1 - adverse)
    return fill, commission / 2      # halv kurtage pr. fill = én rundtur pr. position


def metrics_buy_and_hold(close: pd.Series, index, cost_pct: float) -> pd.Series:
    """Buy-and-hold-kurve på samme indeks, med én rundtur over hele perioden."""
    from backtest.metrics import buy_and_hold_curve

    series = pd.Series(close.to_numpy(float), index=index)
    return buy_and_hold_curve(series, cost_pct)
