# Fase 3b — venue, ordretype, futures, og mikro-påstanden efterprøvet

**Opslagsdato for alle satser og priser:** 2026-09-07
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

| venue | rundtur_bp_taker | omk_R_taker | be_wr_taker_% | rundtur_bp_stop_just | omk_R_stop_just | be_wr_stop_just_% | rundtur_bp_maker_100pct_fill | omk_R_maker_100pct_fill |
|---|---|---|---|---|---|---|---|---|
| Binance spot (VIP 0) | 20.0 | 0.64 | 54.7 | 20.0 | 0.64 | 54.7 | 20.0 | 0.64 |
| Binance USDⓈ-M futures (VIP 0) | 10.0 | 0.32 | 44.0 | 6.01 | 0.192 | 39.7 | 4.0 | 0.128 |
| MEXC spot (web/app-sats) | 10.0 | 0.32 | 44.0 | 3.35 | 0.107 | 36.9 | 0.0 | 0.0 |
| MEXC futures (web/app — IKKE vores adgangsvej) | 4.0 | 0.128 | 37.6 | 1.34 | 0.043 | 34.8 | 0.0 | 0.0 |
| MEXC futures via API (vores adgangsvej) | 16.0 | 0.512 | 50.4 | 13.34 | 0.427 | 47.6 | 12.0 | 0.384 |

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

| venue | timeframe | atr_pct | omk_R_taker | be_wr_taker_% |
|---|---|---|---|---|
| Binance spot (VIP 0) | 5m | 0.159 | 1.257 | 75.2 |
| Binance spot (VIP 0) | 15m | 0.312 | 0.64 | 54.7 |
| Binance spot (VIP 0) | 1h | 0.775 | 0.258 | 41.9 |
| Binance spot (VIP 0) | 4h | 1.906 | 0.105 | 36.8 |
| Binance USDⓈ-M futures (VIP 0) | 5m | 0.159 | 0.628 | 54.3 |
| Binance USDⓈ-M futures (VIP 0) | 15m | 0.312 | 0.32 | 44.0 |
| Binance USDⓈ-M futures (VIP 0) | 1h | 0.775 | 0.129 | 37.6 |
| Binance USDⓈ-M futures (VIP 0) | 4h | 1.906 | 0.052 | 35.1 |
| MEXC futures via API (vores adgangsvej) | 5m | 0.159 | 1.006 | 66.9 |
| MEXC futures via API (vores adgangsvej) | 15m | 0.312 | 0.512 | 50.4 |
| MEXC futures via API (vores adgangsvej) | 1h | 0.775 | 0.206 | 40.2 |
| MEXC futures via API (vores adgangsvej) | 4h | 1.906 | 0.084 | 36.1 |

### Kampagnesatser

`mexc_spot` (0% maker) og `mexc_futures_web` (0% maker / 0,02% taker) er markeret som
**kampagnesatser** — de har kørt længe, men er ikke garanterede. For spot er der ingen
dokumenteret separat API-sats; **men futures-præcedensen betyder at det skal verificeres
i kontoen før man regner med den**, ikke antages.

`binance_futures` er **sekundær kilde**: Binances egen futures-gebyrside kræver login.

---

## DEL 2 — futures-kontrakterne

Børs- og clearinggebyrer står **adskilt fra brokerkurtage**, som opgaven kræver.

| kontrakt | klasse | notional_usd | broker_pr_side | exch_clear_pr_side | nfa_pr_side | gebyr_rundtur_usd | spread_rundtur_usd | gebyr_i_ticks | i_alt_ticks | gebyr_bp | spread_bp | i_alt_bp |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ES | standard | 384788 | 1.29 | 1.38 | 0.01 | 5.36 | 18.75 | 0.429 | 1.929 | 0.139 | 0.487 | 0.627 |
| MES | micro | 38479 | 0.39 | 0.35 | 0.01 | 1.5 | 1.88 | 1.2 | 2.7 | 0.39 | 0.487 | 0.877 |
| NQ | standard | 590705 | 1.29 | 1.38 | 0.01 | 5.36 | 7.5 | 1.072 | 2.572 | 0.091 | 0.127 | 0.218 |
| MNQ | micro | 59070 | 0.39 | 0.35 | 0.01 | 1.5 | 0.75 | 3.0 | 4.5 | 0.254 | 0.127 | 0.381 |
| GC | standard | 443970 | 1.29 | 1.55 | 0.01 | 5.7 | 15.0 | 0.57 | 2.07 | 0.128 | 0.338 | 0.466 |
| MGC | micro | 44397 | 0.39 | 1.1 | 0.01 | 3.0 | 1.5 | 3.0 | 4.5 | 0.676 | 0.338 | 1.014 |

Priser pr. 2026-09-07: GC=F 4,439.70, NQ=F 29,535.25, ES=F 7,695.75.

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

| par | gebyr_bp_micro | gebyr_bp_fuld | gebyr_forhold | spread_bp_micro | spread_bp_fuld | spread_forhold | i_alt_bp_micro | i_alt_bp_fuld | i_alt_forhold | exch_clear_forhold |
|---|---|---|---|---|---|---|---|---|---|---|
| MES/ES | 0.39 | 0.139 | 2.81 | 0.487 | 0.487 | 1.0 | 0.877 | 0.627 | 1.4 | 0.25 |
| MNQ/NQ | 0.254 | 0.091 | 2.79 | 0.127 | 0.127 | 1.0 | 0.381 | 0.218 | 1.75 | 0.25 |
| MGC/GC | 0.676 | 0.128 | 5.28 | 0.338 | 0.338 | 1.0 | 1.014 | 0.466 | 2.18 | 0.71 |

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
(4,439.70):

- gebyrdelen alene: **5.28×** — altså inden for dit interval på 3-6×
- spread-delen: **1.0×** — identisk, som du sagde
- **totalen: 2.18×** (1.014 bp mod 0.466 bp)

**Så vi havde begge ret om noget og fejl om noget.** Du havde ret om gebyrleddet
(5.28× ligger i dit 3-6-interval) og om at spread ikke skalerer.
Mit "1,5-2×" var understated — fase 3's egne tal viste op til 2,6×, og jeg refererede
mit eget interval forkert.

Den egentlige driver: **MGC's børs- og clearinggebyr er 0.71×
GC's** (1,10 mod 1,55 USD/side) på en tiendedel af notional. Børsen skalerer altså slet
ikke sit gebyr ned proportionalt — det gør Tradovates kurtage derimod (0,39 mod 1,29).

---

## Futures i R på 15m, med prisfølsomhed

| kontrakt | klasse | atr15m_% | bp_lav_-30% | omk_R_lav_-30% | bp_dagens | omk_R_dagens | bp_høj_+30% | omk_R_høj_+30% | be_wr_dagens_% | be_wr_lav_% |
|---|---|---|---|---|---|---|---|---|---|---|
| ES | standard | 0.0897 | 0.895 | 0.1 | 0.627 | 0.07 | 0.482 | 0.054 | 35.7 | 36.7 |
| MES | micro | 0.0897 | 1.253 | 0.14 | 0.877 | 0.098 | 0.675 | 0.075 | 36.6 | 38.0 |
| NQ | standard | 0.1678 | 0.311 | 0.019 | 0.218 | 0.013 | 0.167 | 0.01 | 33.8 | 34.0 |
| MNQ | micro | 0.1678 | 0.544 | 0.032 | 0.381 | 0.023 | 0.293 | 0.017 | 34.1 | 34.4 |
| GC | standard | 0.1939 | 0.666 | 0.034 | 0.466 | 0.024 | 0.359 | 0.019 | 34.1 | 34.5 |
| MGC | micro | 0.1939 | 1.448 | 0.075 | 1.014 | 0.052 | 0.78 | 0.04 | 35.1 | 35.8 |

**Go/no-go vurderes på den lave ende**, fordi retningen er asymmetrisk: falder prisen,
stiger omkostningen i R.

- **`GC` koster 0.024 R ved dagens pris, 0.034 R hvis guld falder 30%.**
  Ved begge er den fortsat klart handlebar på 15m.
- **`MGC` koster 0.052 R ved dagens pris, 0.075 R ved guld 30% lavere.**
  Ved den lave ende er den fortsat under 0,20 R og dermed stadig handlebar.

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

| venue | omk_R_taker | omk_R_stop_just | besparelse_R | adverse_selection_må_koste_under_R |
|---|---|---|---|---|
| Binance spot (VIP 0) | 0.64 | 0.64 | 0.0 | 0.0 |
| Binance USDⓈ-M futures (VIP 0) | 0.32 | 0.192 | 0.128 | 0.128 |
| MEXC spot (web/app-sats) | 0.32 | 0.107 | 0.213 | 0.213 |
| MEXC futures (web/app — IKKE vores adgangsvej) | 0.128 | 0.043 | 0.085 | 0.085 |
| MEXC futures via API (vores adgangsvej) | 0.512 | 0.427 | 0.085 | 0.085 |

Besparelsen ved at gå fra ren taker til den stop-justerede blanding er den kolonne.
**Adverse selection skal koste MERE end det pr. handel, før maker bliver det dårligste
valg.** Så er den umålte størrelse i det mindste afgrænset — på samme måde som vi
afgrænser en effekt med mindste detekterbare forskel frem for at kalde den ukendt.

Ingen løsning foreslået.

---

## DEL 6 — sessionstabel

```
FASE 3b  omkostning pr. rundtur, 15m  (RR 2:1, WR-antagelse 33%, priser pr. 2026-09-07)
instrument                          ordretype   rundtur_bp   omk_R  be_WR_%
NQ futures (Tradovate Free)         taker             0.22   0.013     33.8
MNQ futures (Tradovate Free)        taker             0.38   0.023     34.1
GC futures (Tradovate Free)         taker             0.47   0.024     34.1
MEXC futures (web/app — IKKE vores  stop-just         1.34   0.043     34.8
MGC futures (Tradovate Free)        taker             1.01   0.052     35.1
ES futures (Tradovate Free)         taker             0.63   0.070     35.7
MES futures (Tradovate Free)        taker             0.88   0.098     36.6
MEXC spot (web/app-sats)            stop-just         3.35   0.107     36.9
MEXC futures (web/app — IKKE vores  taker             4.00   0.128     37.6
Binance USDⓈ-M futures (VIP 0)      stop-just         6.01   0.192     39.7
MEXC spot (web/app-sats)            taker            10.00   0.320     44.0
---------------------------------------------------------------------------
  maker-tal er ØVRE GRÆNSE for fordelen — adverse selection er ikke målt
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
