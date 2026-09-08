"""Venue og ordretype som AKSE, ikke som konstant — plus futures-kontrakternes specs.

Fase 3 konkluderede at 15m på krypto er dødt ved 25 bp rundtur. **Det tal var korrekt
for Binance spot med markedsordrer, og forkert som udsagn om "krypto".** Omkostningen
er en egenskab ved (børs × produkt × ordretype × adgangsvej), ikke ved aktivklassen.

## Den vigtigste enkeltopdagelse: API-satser er ikke web-satser

MEXC's markedsførte 0% maker / 0,02% taker på futures gælder **web og app**. Ordrer
lagt gennem API'et har en separat sats der **går forud for** web-satsen — MEXC's egen
annoncering siger det ordret. Vores bot handler udelukkende gennem API.

Satsen er desuden hævet to gange på tre måneder:

    2026-03-31   maker 0,01%   taker 0,05%   (API futures lanceres)
    2026-05-01   maker 0,04%   taker 0,06%
    2026-06-01   maker 0,06%   taker 0,08%   <- gældende

**Det vender konklusionen.** For en API-bot er MEXC futures dyrere end Binance futures,
ikke billigere.

## Prisfølsomhed rammer kun futures

Krypto-gebyrer er **proportionale**: 0,10% af handelsværdien er 0,10% uanset prisniveau,
så basispunkterne er prisuafhængige. Problemet findes kun på futures, hvor kurtagen er
et fast dollarbeløb mod en notional der bevæger sig. Derfor rapporteres futures også i
**ticks**, som er helt prisuafhængige — prisen kommer først ind ved omregning til bp.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LOOKUP_DATE = "2026-09-07"


@dataclass(frozen=True)
class Venue:
    """Én kombination af børs, produkt og adgangsvej."""

    key: str
    navn: str
    maker_pct: float          # pr. side
    taker_pct: float          # pr. side
    kilde: str
    dato: str = LOOKUP_DATE
    primaer: bool = True      # udbyderens egen side?
    kampagne: bool = False    # kan ændre sig uden varsel
    note: str = ""

    def round_turn_bp(self, maker_share: float = 0.0) -> float:
        """Rundtur i bp. ``maker_share`` er andelen af BEN der fylder som maker."""
        per_leg = maker_share * self.maker_pct + (1 - maker_share) * self.taker_pct
        return per_leg * 2 * 100


# Adgangsvejen er en del af nøglen, fordi den ændrer prisen.
VENUES: dict[str, Venue] = {
    "binance_spot": Venue(
        "binance_spot", "Binance spot (VIP 0)", 0.10, 0.10,
        "binance.com/en/fee/schedule", primaer=True,
        note="BNB-rabat 25% ville give 0,075%; forudsætter en BNB-beholdning botten ikke har"),
    "binance_futures": Venue(
        "binance_futures", "Binance USDⓈ-M futures (VIP 0)", 0.02, 0.05,
        "flere enige sekundærkilder; binance.com/en/fee/futureFee kræver login",
        primaer=False,
        note="SEKUNDÆR kilde — kunne ikke bekræftes på Binances egen offentlige side"),
    "mexc_spot": Venue(
        "mexc_spot", "MEXC spot (web/app-sats)", 0.0, 0.05,
        "mexc.com fee-side + annonceringer", primaer=True, kampagne=True,
        note="0% maker er en KAMPAGNESATS. Ingen separat API-sats er dokumenteret for "
             "spot — men futures-præcedensen betyder at det skal verificeres i kontoen "
             "før man regner med den"),
    "mexc_futures_web": Venue(
        "mexc_futures_web", "MEXC futures web/app (IKKE vores vej)", 0.0, 0.02,
        "mexc.com annonceringer", primaer=True, kampagne=True,
        note="Markedsført sats. Gælder IKKE ordrer lagt gennem API'et"),
    "mexc_futures_api": Venue(
        "mexc_futures_api", "MEXC futures via API (vores vej)", 0.06, 0.08,
        "mexc.com/announcements 'Updates to API Futures Trading Fees (Jun 1, 2026)'",
        primaer=True, kampagne=False,
        note="Hævet to gange på tre måneder: 0,01/0,05 → 0,04/0,06 → 0,06/0,08"),
}


def stop_adjusted_maker_share(win_rate: float) -> float:
    """Andel af BEN der realistisk kan fylde som maker for en stop-baseret strategi.

    **"Maker på begge ben" er uopnåeligt når man har et stop loss.** Et stop er pr.
    definition en markedsordre der krydser spreadet når den udløses:

        entry        -> limit, kan være maker
        exit på TP   -> limit, kan være maker
        exit på SL   -> market, ALTID taker

    Blandingen er dermed bestemt af strategiens win rate, ikke af en gættet fill-rate:

        maker-andel af ben = (1 + WR) / 2
        taker-andel af ben = (1 - WR) / 2

    Ved 33% win rate: 67% af benene maker. Tallet er UDLEDT af geometrien, ikke opfundet.
    """
    return (1 + win_rate) / 2


# ---------------------------------------------------------------------------
# Futures — DEL 2
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Contract:
    """Én futures-kontrakt. Børs/clearing holdes ADSKILT fra brokerkurtage."""

    kode: str
    navn: str
    multiplier: float
    tick: float
    exch_clear_pr_side: float     # børs + clearing, ikke broker
    klasse: str                   # "micro" eller "standard"
    yf_ticker: str
    spread_ticks: float = 1.5     # SKØN — se forbehold i rapporten
    nfa_pr_side: float = 0.01

    @property
    def tick_value(self) -> float:
        """USD pr. tick. Skalerer med kontraktstørrelsen — derfor er spread i bp ens."""
        return self.tick * self.multiplier


# exch_clear: TradeStation offentliggør sine CME-passthrough-satser pr. side
# (tradestation.com/pricing/exchange-execution-and-clearing-fees). CME's egen
# fee-finder er et interaktivt værktøj og svarede 403/timeout, så tallene her er
# en BROKERS offentliggjorte passthrough, ikke CME's eget skema. En anden broker
# (NinjaTrader) antyder ~0,55 USD for MNQ mod TradeStations 0,35 — usikkerheden
# står i rapporten frem for at blive midlet væk.
CONTRACTS: dict[str, Contract] = {
    "ES":  Contract("ES",  "E-mini S&P 500",      50,     0.25,    1.38, "standard", "ES=F"),
    "MES": Contract("MES", "Micro E-mini S&P",     5,     0.25,    0.35, "micro",    "ES=F"),
    "NQ":  Contract("NQ",  "E-mini Nasdaq-100",   20,     0.25,    1.38, "standard", "NQ=F"),
    "MNQ": Contract("MNQ", "Micro E-mini Nasdaq",  2,     0.25,    0.35, "micro",    "NQ=F"),
    "GC":  Contract("GC",  "COMEX guld",         100,     0.10,    1.55, "standard", "GC=F"),
    "MGC": Contract("MGC", "Micro guld (10 oz)",  10,     0.10,    1.10, "micro",    "GC=F"),
}

# Tradovate-kurtage pr. side (tradovate.com/pricing, primær).
BROKER_PLANS: dict[str, dict] = {
    "Tradovate Free":     {"micro": 0.39, "standard": 1.29, "abonnement_usd": 0},
    "Tradovate Monthly":  {"micro": 0.29, "standard": 0.99, "abonnement_usd": 99},
    "Tradovate Lifetime": {"micro": 0.09, "standard": 0.59, "abonnement_usd": 1499},
}


def contract_costs(c: Contract, price: float, plan: str = "Tradovate Free") -> dict:
    """Omkostningen ved én rundtur — i USD, i ticks og i bp.

    **Ticks er prisuafhængige**; bp er ikke. Begge rapporteres, så de to drivere
    (kontraktens egen geometri og prisniveauet) kan ses hver for sig i stedet for
    at være blandet sammen i ét tal der bevæger sig af uklare grunde.
    """
    broker = BROKER_PLANS[plan]["micro" if c.klasse == "micro" else "standard"]
    fee_pr_side = broker + c.exch_clear_pr_side + c.nfa_pr_side
    fee_rt_usd = fee_pr_side * 2
    spread_usd = c.spread_ticks * c.tick_value
    notional = c.multiplier * price

    return {
        "kontrakt": c.kode, "navn": c.navn, "klasse": c.klasse,
        "multiplier": c.multiplier, "tick": c.tick,
        "tick_value_usd": round(c.tick_value, 4),
        "pris": round(price, 2), "notional_usd": round(notional),
        # Adskilt, som opgaven kræver:
        "broker_pr_side": broker,
        "exch_clear_pr_side": c.exch_clear_pr_side,
        "nfa_pr_side": c.nfa_pr_side,
        "gebyr_rundtur_usd": round(fee_rt_usd, 2),
        "spread_rundtur_usd": round(spread_usd, 2),
        "i_alt_rundtur_usd": round(fee_rt_usd + spread_usd, 2),
        # Prisuafhængigt:
        "gebyr_i_ticks": round(fee_rt_usd / c.tick_value, 3),
        "spread_i_ticks": c.spread_ticks,
        "i_alt_ticks": round(fee_rt_usd / c.tick_value + c.spread_ticks, 3),
        # Prisafhængigt:
        "gebyr_bp": round(fee_rt_usd / notional * 10_000, 3),
        "spread_bp": round(spread_usd / notional * 10_000, 3),
        "i_alt_bp": round((fee_rt_usd + spread_usd) / notional * 10_000, 3),
    }


def live_prices(tickers: list[str]) -> dict[str, float]:
    """Seneste lukkekurs pr. ticker. Stemples med dato i rapporten."""
    import warnings

    warnings.filterwarnings("ignore")
    import pandas as pd
    import yfinance as yf

    out: dict[str, float] = {}
    for t in set(tickers):
        try:
            d = yf.download(t, period="5d", interval="1d",
                            progress=False, auto_adjust=False, threads=False)
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
            out[t] = float(d["Close"].dropna().iloc[-1])
        except Exception:  # noqa: BLE001 — forskningsscript
            out[t] = float("nan")
    return out
