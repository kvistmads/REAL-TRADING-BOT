"""Rapportgenerator for fase 3b."""

from __future__ import annotations

import pandas as pd

from research.venues import CONTRACTS, LOOKUP_DATE, VENUES


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    return "\n".join([
        "| " + " | ".join(str(c) for c in cols) + " |",
        "|" + "|".join("---" for _ in cols) + "|",
        *["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)],
    ])


def build(venues, fut, micro, fut_r, adv, prices, session) -> str:
    v15 = venues[venues.timeframe == "15m"]
    gc = fut_r[fut_r.kontrakt == "GC"].iloc[0] if not fut_r[fut_r.kontrakt == "GC"].empty else None
    mgc = fut_r[fut_r.kontrakt == "MGC"].iloc[0] if not fut_r[fut_r.kontrakt == "MGC"].empty else None
    m_gold = micro[micro.par == "MGC/GC"].iloc[0]

    venue_view = v15[["venue", "rundtur_bp_taker", "omk_R_taker", "be_wr_taker_%",
                      "rundtur_bp_stop_just", "omk_R_stop_just", "be_wr_stop_just_%",
                      "rundtur_bp_maker_100pct_fill", "omk_R_maker_100pct_fill"]]
    tf_view = venues[venues.venue_key.isin(["binance_spot", "binance_futures",
                                            "mexc_futures_api"])][
        ["venue", "timeframe", "atr_pct", "omk_R_taker", "be_wr_taker_%"]]

    return f"""# Fase 3b — venue, ordretype, futures, og mikro-påstanden efterprøvet

**Opslagsdato for alle satser og priser:** {LOOKUP_DATE}
**Status:** måling og aritmetik. `backtest.costs` er **urørt**. Ingen strategi, ingen
backtest, ingen anbefaling af venue.

---

## Det vigtigste fund vender opgavens præmis

Opgaven bygger på at MEXC tilbyder 0% maker / 0,02% taker på futures, og at det ville
tage BTC 15m fra 1,09 R til 0,22 R.

**De satser gælder web og app. De gælder ikke ordrer lagt gennem API'et — og vores bot
handler udelukkende gennem API'et.**

MEXC's egen annoncering siger det ordret: *"API trades follow a separate fee structure,
which takes precedence over web and app rates"*, med eksemplet at BTC-futures koster
maker 0% / taker 0,01% på web, men maker 0,01% / taker 0,05% via API.

Satsen er desuden hævet **to gange på tre måneder**:

| Fra | Maker | Taker | Kilde |
|---|---|---|---|
| 2026-03-31 | 0,01% | 0,05% | mexc.com/announcements — "Introducing API Futures Trading" |
| 2026-05-01 | 0,04% | 0,06% | mexc.com/announcements — "Updates to API Futures Trading Fees (May 1, 2026)" |
| **2026-06-01** | **0,06%** | **0,08%** | mexc.com/announcements — "Updates to API Futures Trading Fees (Jun 1, 2026)" |

**For en API-bot er MEXC futures dermed dyrere end Binance futures**, ikke billigere:
16 bp rundtur mod 10 bp. Konklusionen fra fase 3 var venue-specifik og skulle korrigeres
— men korrektionen peger den modsatte vej af den forventede.

Alle tre MEXC-annonceringer er **primærkilder** (MEXC's eget annonceringsarkiv).

---

## DEL 1 — venue × ordretype på 15m

{_md(venue_view.round(3))}

**Kolonnenavnene bærer antagelsen.** `maker_100pct_fill` er ikke et maker-tal, det er
en **øvre grænse** for hvad maker kunne spare hvis begge ben fyldte.

### De tre ordretype-scenarier

- **`taker`** — begge ben som markedsordre. Det botten gør i dag.
- **`maker_100pct_fill`** — begge ben fylder som maker. **Uopnåeligt for en
  stop-baseret strategi** (se DEL 5). Medtaget som øvre grænse, ikke som mulighed.
- **`stop_just`** — entry og take-profit som limit, stop loss som market. Blandingen er
  **udledt af strategiens geometri**, ikke gættet:

      maker-andel af ben = (1 + WR) / 2
      taker-andel af ben = (1 − WR) / 2

  Ved 33% win rate: 67% af benene maker. Det er den eneste af de tre der beskriver en
  strategi vi faktisk kunne bygge.

### På tværs af timeframes

{_md(tf_view.round(3))}

### Kampagnesatser

`mexc_spot` (0% maker) og `mexc_futures_web` (0% maker / 0,02% taker) er markeret som
**kampagnesatser** — de har kørt længe, men er ikke garanterede. For spot er der ingen
dokumenteret separat API-sats; **men futures-præcedensen betyder at det skal verificeres
i kontoen før man regner med den**, ikke antages.

`binance_futures` er **sekundær kilde**: Binances egen futures-gebyrside kræver login.

---

## DEL 2 — futures-kontrakterne

Børs- og clearinggebyrer står **adskilt fra brokerkurtage**, som opgaven kræver.

{_md(fut[["kontrakt", "klasse", "notional_usd", "broker_pr_side", "exch_clear_pr_side",
          "nfa_pr_side", "gebyr_rundtur_usd", "spread_rundtur_usd", "gebyr_i_ticks",
          "i_alt_ticks", "gebyr_bp", "spread_bp", "i_alt_bp"]])}

Priser pr. {LOOKUP_DATE}: {", ".join(f"{k} {v:,.2f}" for k, v in prices.items())}.

**Din formodning holder.** De 4 USD i vores model er brokerens del alene; børs og
clearing lægger 0,35-1,55 USD **pr. side** oveni. Din angivelse på 1,50-2,50 USD/side
passer på de fuldstore kontrakter (ES/NQ 1,38, GC 1,55), mens mikroerne ligger lavere
(0,35 for MES/MNQ) — undtagen MGC på 1,10, hvilket er hele pointen i DEL 3.

⚠️ **Kildeforbehold.** CME's egen fee-finder er et interaktivt værktøj og svarede
403/timeout. Tallene for børs+clearing kommer derfor fra en **brokers offentliggjorte
passthrough-satser** (TradeStation), ikke fra CME's eget skema. En anden broker
(NinjaTrader) antyder ~0,55 USD for MNQ mod TradeStations 0,35 — en usikkerhed på ~60%
på netop mikro-indeks. Den står her frem for at blive midlet væk.

### Ticks ved siden af bp

`i_alt_ticks` er **helt prisuafhængigt** — det er kontraktens egen geometri. `i_alt_bp`
er den samme omkostning omregnet ved dagens pris. Med begge kolonner kan de to drivere
ses hver for sig i stedet for at være blandet sammen i ét bp-tal der bevæger sig af
uklare grunde.

**Kun futures-rækkerne er prisfølsomme.** Krypto-gebyrer er proportionale — 0,10% er
0,10% uanset prisniveau — så DEL 1-tabellen er prisuafhængig i sin helhed.

---

## DEL 3 — mikro mod fuldstor: du har ret i mekanismen, men ikke i tallet

{_md(micro)}

**Din strukturelle indsigt er præcis rigtig, og tabellen bekræfter den:**
`spread_forhold` er **1,00** for alle tre par. Spread-delen skalerer med kontrakten og
er derfor identisk i basispunkter. Kun gebyret skalerer ikke.

Regnestykket med dine egne tal (guld 3.200, kurtage 4 USD / 1 USD rundtur):

```
GC   notional $320.000   spread $15,00 = 0,469 bp   kurtage $4,00 = 0,125 bp   i alt 0,594 bp
MGC  notional $ 32.000   spread $ 1,50 = 0,469 bp   kurtage $1,00 = 0,312 bp   i alt 0,781 bp
                                                                     forhold:  1,32×
```

**Fejlen er en faktor 10 i kurtage-leddet.** 1 USD / 32.000 USD = 3,125 × 10⁻⁵, og
1 bp = 10⁻⁴, så det er **0,31 bp — ikke 3,1 bp.** Med 3,1 bp bliver totalen 3,6 bp og
forholdet 6×; med 0,31 bp bliver den 0,78 bp og forholdet 1,3×.

Med **fulde gebyrer** (broker + børs + clearing + NFA) ved dagens guldpris
({prices.get("GC=F", float("nan")):,.2f}):

- gebyrdelen alene: **{m_gold['gebyr_forhold']}×** — altså inden for dit interval på 3-6×
- spread-delen: **{m_gold['spread_forhold']}×** — identisk, som du sagde
- **totalen: {m_gold['i_alt_forhold']}×** ({m_gold['i_alt_bp_micro']} bp mod {m_gold['i_alt_bp_fuld']} bp)

**Så vi havde begge ret om noget og fejl om noget.** Du havde ret om gebyrleddet
({m_gold['gebyr_forhold']}× ligger i dit 3-6-interval) og om at spread ikke skalerer.
Mit "1,5-2×" var understated — fase 3's egne tal viste op til 2,6×, og jeg refererede
mit eget interval forkert.

Den egentlige driver: **MGC's børs- og clearinggebyr er {m_gold['exch_clear_forhold']}×
GC's** (1,10 mod 1,55 USD/side) på en tiendedel af notional. Børsen skalerer altså slet
ikke sit gebyr ned proportionalt — det gør Tradovates kurtage derimod (0,39 mod 1,29).

---

## Futures i R på 15m, med prisfølsomhed

{_md(fut_r)}

**Go/no-go vurderes på den lave ende**, fordi retningen er asymmetrisk: falder prisen,
stiger omkostningen i R.

{f'''- **`GC` koster {gc["omk_R_dagens"]} R ved dagens pris, {gc["omk_R_lav_-30%"]} R hvis guld falder 30%.**
  Ved begge er den fortsat klart handlebar på 15m.
- **`MGC` koster {mgc["omk_R_dagens"]} R ved dagens pris, {mgc["omk_R_lav_-30%"]} R ved guld 30% lavere.**
  {"Ved den lave ende er den fortsat under 0,20 R og dermed stadig handlebar."
   if mgc["omk_R_lav_-30%"] < 0.20 else
   "Ved den lave ende passerer den 0,20 R og er dermed ikke længere komfortabel."}''' if gc is not None and mgc is not None else ""}

---

## DEL 4a — optageren dækker nu begge børser

`research/orderbook_recorder.py` optager nu **Binance og MEXC** med samme symboler,
samme kadence og samme format. Børsen er en **partitionsnøgle** (`dt=/venue=/symbol=`),
ikke bare en kolonne, så en analyse kan læse den ene uden at røre den anden.

Skemaet er udvidet **før optageren blev sat i drift**. Havde den kørt i uger først,
ville arkivet være delt i to halvdele med forskellig sti-struktur — præcis den fælde vi
undgik ved at vælge parquet fra starten.

Diskforbrug fordobles: **3,4 MB/døgn · 103 MB/måned · 1,24 GB/år.**

### Første måling — begge børser, samme øjeblik

| Symbol | Binance | MEXC | Forhold |
|---|---|---|---|
| BTC/USDT | 0,0013 bp | **0,8064 bp** | 620× |
| ETH/USDT | 0,0408 bp | 0,0408 bp | 1,0× |
| SOL/USDT | 0,9799 bp | 0,9796 bp | 1,0× |

⚠️ **n = 1 pr. børs.** Ét snapshot taget samtidig. Det er en indikation, ikke en måling.

Men den peger på præcis det spørgsmål optageren blev udvidet for at besvare: **æder
MEXC's tyndere bog gebyrfordelen?** På BTC er forskellen i dette øjeblik 0,80 bp, hvilket
er samme størrelsesorden som hele gebyrforskellen mellem de to børser. På ETH og SOL er
bøgerne identiske. Det kan først afgøres med uger af data.

---

## DEL 4b — kan guld, FX og indeks optages? Undersøgt, ikke implementeret

Optageren dækker kun krypto, fordi ccxt kun taler med kryptobørser. Guld er det
instrument fase 3 pegede på som mest lovende, og vi kan ikke måle dets spread.

| Mulighed | Pris | Hvad den giver | Forbehold |
|---|---|---|---|
| **Alpaca Basic (gratis)** | 0 kr | Realtids **IEX-only** bid/ask via WebSocket for `GLD`, `SPY`, `QQQ` | IEX er få procent af den amerikanske aktieomsætning, så IEX-spreadet er **bredere end det konsoliderede NBBO** — tallet ville systematisk OVERvurdere. Og ETF'er er proxyer: `GLD`s spread er ikke `GC`s |
| **Alpaca Algo Trader Plus** | 99 USD/md | Fuld SIP-konsolideret NBBO for samme ETF'er | Rigtigt spread, men stadig ETF-proxy frem for futures |
| **CME-realtid via broker** | ~10-15 USD/md **pr. børs** (CME + COMEX = to) for top-of-book; dybde koster mere | Ægte `ES`/`NQ`/`GC`-kvoter | Kræver brokerkonto. Non-professional-status skal godkendes |
| **IBKR paper** | Data-abonnement som ovenfor; frafalder ved tilstrækkelig kurtage | Ægte kvoter | Kræver TWS/Gateway kørende lokalt — en tung afhængighed for en optager der skal køre uafbrudt |
| **Tradovate demo** | Følger deres datapakke | Ægte kvoter | Kræver konto |

**Billigst der faktisk virker: Alpaca Basic med ETF-proxyer. Den er ikke implementeret,
og det er et bevidst valg.**

To grunde. For det første kræver den en Alpaca-konto og `ALPACA_API_KEY`/`ALPACA_API_SECRET`
i `.env` — de findes ikke i dag (`config.yaml` har `alpaca: false`, og nøglerne er ikke
sat), så jeg kan hverken teste eller verificere den. At levere uafprøvet kode til en
optager hvis hele formål er dataintegritet ville være forkert.

For det andet ville tallet være **dobbelt biased**: IEX-only overvurderer spreadet, og
`GLD` er ikke `GC`. Vi ville måle noget, men ikke det vi spørger om.

**Rapporteret og stoppet**, som afgrænsningen foreskriver.

---

## DEL 5 — maker-fælden

**0% er ikke gratis.** To ting skal stå ved hvert eneste maker-tal:

**1. Maker på begge ben er uopnåeligt for en stop-baseret strategi.** Et stop loss er pr.
definition en markedsordre der krydser spreadet når den udløses. Man kan ikke være maker
på et stop. Derfor er `maker_100pct_fill` en øvre grænse og ikke en mulighed, og derfor
findes `stop_just`-kolonnen.

**2. Adverse selection er ikke målt.** Maker-ordrer fylder ikke altid, og de handler man
går glip af er **systematisk dem hvor prisen løb den rigtige vej** — limitordren på købssiden
fylder når markedet falder mod den, og fylder ikke når markedet løber væk opad. Gebyr-
besparelsen er reel; den udeblevne gevinst er ikke målt.

### Hvor stor skal adverse selection være for at vende svaret?

{_md(adv)}

Besparelsen ved at gå fra ren taker til den stop-justerede blanding er den kolonne.
**Adverse selection skal koste MERE end det pr. handel, før maker bliver det dårligste
valg.** Så er den umålte størrelse i det mindste afgrænset — på samme måde som vi
afgrænser en effekt med mindste detekterbare forskel frem for at kalde den ukendt.

Ingen løsning foreslået.

---

## DEL 6 — sessionstabel

```
{session}
```

---

## Forbehold

- **`backtest.costs` er urørt.** Modellens 25 bp på krypto svarer til Binance spot taker
  (20 bp gebyr + 5 bp antagelse). Den er hverken bekræftet eller korrigeret her.
- **Spread på futures er sat til 1,5 tick — et SKØN**, overtaget fra opgavens eget
  regnestykke. Det er ikke målt, og DEL 4b forklarer hvorfor det endnu ikke kan måles.
- **Børs- og clearinggebyrer kommer fra en brokers passthrough**, ikke fra CME's eget
  skema; op til ~60% usikkerhed på mikro-indeks.
- **ATR på 15m for futures bygger på 60 dages historik** (Yahoos intraday-cap) mod
  krypto's mange tusinde barer. De to tal er ikke lige robuste.
- **Målt spread er n=1 pr. børs.**
- **MEXC's API-sats er hævet to gange på tre måneder.** Den bør slås op igen før den
  bruges til noget, ikke behandles som en konstant.

---

## Filer

- `research/venues.py` — venues, API- mod web-satser, kontraktspecs, stop-justeret blanding
- `research/run_venue_costs.py` — DEL 1, 2, 3 og 6
- `research/orderbook_recorder.py` — nu Binance + MEXC, partitioneret pr. børs
- `research/output/venue_costs.csv`, `futures_contracts.csv`
"""
