"""DEL 1: de otte daglige serier bag apparatvalideringen — indlæsning og kvalitet.

Ved instrumentklasse-testen konkluderede vi at dataudvidelse var umulig fordi Yahoo
capper ved 730 dage. **Det gælder kun intraday.** Daglige barer rækker årtier tilbage,
og denne modul samler dem ét sted.

``SPY`` og ``QQQ`` er **ankre, ikke handelskandidater**. Time-series momentum er bedst
dokumenteret på aktieindeks og futures. Kan effekten ikke findes dér, er det apparatet
der er i stykker — ikke markedet.

## Ejerskab og finansiering — hvor antagelsen ikke holder

Omkostningsmodellen (``backtest/costs.py``) opkræver spread, slippage og kurtage pr.
rundtur. Den modellerer **ikke** finansiering: hverken futures-roll eller swap på en
CFD. Ved fire døgns hold var det uden betydning; ved fem måneders hold er det ikke.

Derfor bærer hvert instrument et eksplicit ``ownership``-felt:

- ``ejet``    — spot-aktivet ejes. Ingen finansiering løber på. (BTC, ETH, SPY, QQQ)
- ``derivat`` — positionen er syntetisk. Roll eller swap ville løbe på, og gør det
  ikke i disse tal. (GC, 6E, 6B, og XAU-spot, der i praksis er et CFD/swap-produkt)

Finansiering modelleres IKKE her. Feltet findes for at rapporten kan sige præcis hvor
antagelsen ikke holder, frem for at lade det være underforstået.

## Afkastgrundlag

- Aktier (SPY, QQQ): **totalafkast** — auto_adjust, udbytte geninvesteret.
- Futures og FX (GC, 6E, 6B) samt XAU-spot: **kurs**. De betaler intet udbytte.
- Kontanter forrentes ikke. Se ``research/run_tsmom_test.py`` for hvad det koster.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HISTORICAL = ROOT / "data" / "historical"
XAU_DAILY = ROOT / "data" / "historical_xau" / "XAU_1d_data.csv"

# Under denne årsdækning regnes året som utilstrækkeligt. Samme tærskel som
# gold_long_series.MIN_YEAR_COVERAGE — kriteriet skal ikke skifte mellem kørsler.
MIN_YEAR_COVERAGE = 0.90


@dataclass(frozen=True)
class Instrument:
    """Ét instrument i apparatvalideringen.

    ``cost_symbol`` er det symbol ``backtest/costs.py`` kender. SPY og QQQ findes
    ikke i ``config.yaml`` og får derfor research-lokale parametre — se
    ``research_cost_config()``, som bygger dem i hukommelsen og aldrig skriver til
    config'en.
    """

    key: str            # navn i tabeller og rapporter
    path: Path
    label: str
    calendar: str       # "24/7" eller "børs"
    bars_per_year: int  # forventet antal barer i et helt år
    ownership: str      # "ejet" eller "derivat"
    return_basis: str   # "totalafkast" eller "kurs"
    cost_symbol: str
    anchor: bool = False   # anker, ikke handelskandidat


# De otte instrumenter fra PRD'ens DEL 1-tabel, i rapporteringsrækkefølge.
INSTRUMENTS: dict[str, Instrument] = {
    "SPY": Instrument("SPY", HISTORICAL / "SPY_1d.csv", "S&P 500 ETF",
                      "børs", 252, "ejet", "totalafkast", "SPY", anchor=True),
    "QQQ": Instrument("QQQ", HISTORICAL / "QQQ_1d.csv", "Nasdaq 100 ETF",
                      "børs", 252, "ejet", "totalafkast", "QQQ", anchor=True),
    "GC": Instrument("GC", HISTORICAL / "GC_1d.csv", "COMEX guld-futures (GC=F)",
                     "børs", 252, "derivat", "kurs", "XAU/USD"),
    "XAU": Instrument("XAU", XAU_DAILY, "Guld spot (XAU/USD, lang serie)",
                      "børs", 260, "derivat", "kurs", "XAU/USD"),
    "6E": Instrument("6E", HISTORICAL / "6E_1d.csv", "EUR/USD-futures (6E=F)",
                     "børs", 252, "derivat", "kurs", "EUR/USD"),
    "6B": Instrument("6B", HISTORICAL / "6B_1d.csv", "GBP/USD-futures (6B=F)",
                     "børs", 252, "derivat", "kurs", "GBP/USD"),
    "BTC": Instrument("BTC", HISTORICAL / "BTCUSDT_1d.csv", "Bitcoin (Binance spot)",
                      "24/7", 365, "ejet", "kurs", "BTC/USDT"),
    "ETH": Instrument("ETH", HISTORICAL / "ETHUSDT_1d.csv", "Ether (Binance spot)",
                      "24/7", 365, "ejet", "kurs", "ETH/USDT"),
}


# Research-lokale omkostningsparametre for de to aktie-ETF'er.
#
# SPY og QQQ findes ikke i ``config.yaml``, og ``BaseStrategy.get_asset_class``
# ville klassificere dem som "crypto" og pålægge dem Binances 0,20% rundtur. Det
# ville være forkert med en faktor ~100. Parametrene her er SKØN for en likvid
# aktie-ETF hos en moderne broker: ét basispunkt spread (SPY handler typisk 1 cent
# på ~600 USD), et halvt basispunkt slippage pr. fill, ingen kurtage.
#
# De skrives ALDRIG til config.yaml — ``backtest.costs`` er urørt, som PRD'ens
# afgrænsning kræver. De lægges kun oven på en kopi af config'en i hukommelsen.
ETF_COST_PARAMS = {
    "mode": "proportional",
    "spread_pct": 0.0001,
    "slippage_mean_pct": 0.00005,
    "slippage_std_pct": 0.00005,
    "commission_pct": 0.0,
}


def research_cost_config(config: dict) -> dict:
    """Kopi af config'en med research-lokale omkostninger for SPY og QQQ.

    Muterer ikke den config der blev givet ind, og rører ikke ``config.yaml``.
    """
    import copy

    cfg = copy.deepcopy(config)
    costs = cfg.setdefault("backtest", {}).setdefault("costs", {})
    symbols = costs.setdefault("symbols", {})
    for etf in ("SPY", "QQQ"):
        symbols[etf] = dict(ETF_COST_PARAMS)
    return cfg


def load(instrument: Instrument | str) -> pd.DataFrame:
    """Indlæs en daglig serie til projektets standardformat (time/OHLCV).

    Alle filer er semikolon-CSV i XAU-formatet — også dem ``fetch_daily.py`` har
    skrevet, netop for at der kun findes ét format at læse.

    Tidsstemplerne reduceres til **ren dato i UTC**. Krypto kommer med UTC-midnat
    og aktier med børsens lokale dato; uden normaliseringen ville "første bar med
    dato >= den 1." betyde to forskellige ting på tværs af instrumenterne.
    """
    inst = INSTRUMENTS[instrument] if isinstance(instrument, str) else instrument
    df = pd.read_csv(inst.path, sep=";")
    df.columns = [c.lower() for c in df.columns]
    df["time"] = pd.to_datetime(df["date"], format="%Y.%m.%d %H:%M").dt.normalize()
    df = df[["time", "open", "high", "low", "close", "volume"]]
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return (df.drop_duplicates(subset="time", keep="last")
              .sort_values("time")
              .reset_index(drop=True))


def yearly_quality(df: pd.DataFrame, inst: Instrument) -> pd.DataFrame:
    """Datakvalitet pr. år — samme tjek som på guldserien. **Reparerer ingenting.**

    Dækning måles mod den faktisk dækkede del af året, ikke mod et helt år: første
    og sidste år er delvise, og ellers ville de altid se ødelagte ud.
    """
    rows = []
    for year, g in df.groupby(df["time"].dt.year):
        span_days = (g["time"].iloc[-1] - g["time"].iloc[0]).days + 1
        expected = inst.bars_per_year * span_days / 365.25
        gaps = g["time"].diff().dt.total_seconds() / 86400
        rows.append({
            "år": int(year),
            "barer": len(g),
            "forventet": int(round(expected)),
            "dækning_%": round(100 * len(g) / expected, 1) if expected else 0.0,
            "flade_barer": int((g["high"] == g["low"]).sum()),
            "nul_volumen": int((g["volume"] == 0).sum()),
            "huller>7d": int((gaps > 7).sum()),
            "største_hul_dage": round(float(gaps.max()), 1) if len(g) > 1 else 0.0,
        })
    out = pd.DataFrame(rows)
    out["brugbar"] = out["dækning_%"] >= 100 * MIN_YEAR_COVERAGE
    return out


def usable_span(quality: pd.DataFrame) -> tuple[int, int] | None:
    """Længste ubrudte række af brugbare år.

    Afgrænsningen er ikke en REPARATION — intet ændres, udfyldes eller
    interpoleres. Det er en afgrænsning af hvad serien kan bære, og den skal stå
    eksplicit i rapporten.
    """
    usable = quality[quality["brugbar"]]["år"].tolist()
    if not usable:
        return None
    best = cur = [usable[0]]
    for y in usable[1:]:
        cur = cur + [y] if y == cur[-1] + 1 else [y]
        if len(cur) > len(best):
            best = list(cur)
    return (best[0], best[-1])


def quality_summary(inst: Instrument, df: pd.DataFrame, quality: pd.DataFrame) -> dict:
    """Én linje pr. instrument til DEL 1-tabellen."""
    span = usable_span(quality)
    discarded = quality[~quality["brugbar"]]["år"].tolist()
    return {
        "instrument": inst.key,
        "kilde": inst.label,
        "barer": len(df),
        "fra": str(df["time"].iloc[0].date()),
        "til": str(df["time"].iloc[-1].date()),
        "år": round((df["time"].iloc[-1] - df["time"].iloc[0]).days / 365.25, 1),
        "flade_barer": int((df["high"] == df["low"]).sum()),
        "nul_volumen": int((df["volume"] == 0).sum()),
        "brugbart_span": f"{span[0]}–{span[1]}" if span else "—",
        "kasserede_år": ", ".join(str(y) for y in discarded) or "—",
        "ejerskab": inst.ownership,
        "afkastgrundlag": inst.return_basis,
    }
