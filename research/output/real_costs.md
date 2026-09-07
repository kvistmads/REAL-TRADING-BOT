# Fase 3 — rigtige omkostningstal, og hvad de kræver af en 15m-strategi

**Kørsel:** måling og aritmetik. **Ingen ny strategi, ingen backtest af handelsregler.**
**Opslagsdato for alle gebyrer:** 2026-09-07
**Status:** `backtest.costs` er **ikke** opdateret. Forskellen mellem model og måling
rapporteres; beslutningen om at rette modellen tages separat, fordi en ændring gør alle
tidligere resultater usammenlignelige.

---

## Kort svar

1. **Gebyrer kunne slås præcist op, og modellen rammer plet på krypto.** 0,10% taker ×
   2 sider = 20 bp rundtur, bekræftet på Binances egen side. Modellens 25 bp er 20 bp
   gebyr + 5 bp antaget spread og slippage.
2. **Corwin-Schultz virker IKKE på vores data.** Estimatet skalerer med bar-længden —
   det måler volatilitet, ikke spread. Detaljerne nedenfor; det er kørslens vigtigste
   fund, og det er negativt.
3. **Den målte spread er 1-3 størrelsesordener under både modellen og estimatet.**
   Første rigtige snapshot: BTC 0,0013 bp mod modellens 1,0 bp.
4. **En 15m-strategi på krypto er aritmetisk død ved Binances spot-takergebyr.** For at
   få omkostningen ned på 0,20 R skal stoppet være 5,5 × ATR på BTC — altså 1,25%,
   hvilket er bredere end et typisk 4h-stop. Så forsvinder grunden til at gå ned i
   timeframe.
5. **Gulds futures er den eneste af de seks der er komfortabel på 15m:** 0,60 bp rundtur
   mod en 15m-ATR på 0,19%, altså 0,031 R ved et 1 × ATR-stop.

```
FASE 3  omkostninger pr. timeframe  (stop = 1,0 x ATR14, RR 2:1, medianer over 6 symboler)
timeframe      1R_%  rundtur_bp   omk_R  be_WR_%  uden_omk_%  tillæg_pp
5m            0.111       13.54   1.055     68.5        33.3       35.2
15m           0.212       13.54   0.595     53.1        33.3       19.9
1h            0.486       13.54   0.231     41.0        33.3        7.7
4h            1.012       13.54   0.100     36.7        33.3        3.4
-----------------------------------------------------------------------
  15m krypto   0.316       25.00   0.792     59.7        33.3       26.4
  15m ikke-krypto   0.041        1.22   0.329     44.3        33.3       11.0
```

---

## DEL 1 — gebyrer, slået op

### Binance

| | Maker | Taker | Rundtur (taker) | Med BNB | Kilde |
|---|---|---|---|---|---|
| Spot, VIP 0 | 0.1% | 0.1% | **20.0 bp** | 0.075% → 15.0 bp | binance.com/en/fee/schedule (primær) |
| USDⓈ-M futures, VIP 0 | 0.02% | 0.05% | **10.0 bp** | 0.045% → 9.0 bp | flere sekundære kilder, enige (SEKUNDÆR — binance.com/en/fee/futureFee kræver login og kunne ikke bekræftes) |

**Modellens 20 bp kurtage på krypto er bekræftet.** BNB-rabatten på 25% ville tage den
til 15 bp; den er ikke brugt i modellen, fordi den forudsætter en BNB-beholdning botten
ikke har.

**Næste VIP-niveau:** VIP 1: ≥1.000.000 USD 30-dages volumen OG ≥5 BNB. Med `total_capital: 100` er det ikke
inden for rækkevidde, og gebyret skal derfor regnes som fast.

**Perpetual futures koster det halve af spot** (10.0 bp mod
20.0 bp). Det er ikke et forslag — det er et tal der hører med,
fordi det halverer den dominerende omkostning på krypto.

⚠️ Futures-satsen er **sekundær kilde**. `binance.com/en/fee/futureFee` kræver login og
kunne ikke bekræftes direkte; flere uafhængige sekundærkilder er enige om 0,02%/0,05%.
Spot-satsen er derimod læst på Binances egen offentlige side.

### Prop-platform: Tradovate

| plan | micro_pr_side_USD | standard_pr_side_USD | abonnement_USD |
|---|---|---|---|
| Free (0 kr/md) | 0.39 | 1.29 | 0 |
| Monthly (99 USD/md) | 0.29 | 0.99 | 99 |
| Lifetime (1.499 USD) | 0.09 | 0.59 | 0 |

Kilde: tradovate.com/pricing (primær), 2026-09-07. **Exchange, clearing og NFA er OVENI** og er
det der gør totalen — den annoncerede kurtage er under halvdelen af regningen på
mikrokontrakter.

### Total rundtur pr. kontrakt (Free-planen, ikke-medlem)

| kontrakt | type | kurtage_pr_side | exch_clear_pr_side | i_alt_pr_side | rundtur_usd | notional_usd | gebyr_bp | et_tick_bp | rundtur_i_alt_bp |
|---|---|---|---|---|---|---|---|---|---|
| MES | micro | 0.39 | 0.35 | 0.75 | 1.5 | 30000 | 0.5 | 0.42 | 0.92 |
| ES | standard | 1.29 | 1.38 | 2.68 | 5.36 | 300000 | 0.18 | 0.42 | 0.6 |
| MNQ | micro | 0.39 | 0.35 | 0.75 | 1.5 | 44000 | 0.34 | 0.11 | 0.45 |
| NQ | standard | 1.29 | 1.38 | 2.68 | 5.36 | 440000 | 0.12 | 0.11 | 0.24 |
| MGC | micro | 0.39 | 1.1 | 1.5 | 3.0 | 40000 | 0.75 | 0.25 | 1.0 |
| GC | standard | 1.29 | 1.55 | 2.85 | 5.7 | 400000 | 0.14 | 0.25 | 0.39 |
| M6E | micro | 0.39 | 0.24 | 0.64 | 1.28 | 13500 | 0.95 | 0.93 | 1.87 |
| 6E | standard | 1.29 | 1.53 | 2.83 | 5.66 | 135000 | 0.42 | 0.46 | 0.88 |

Exchange + clearing pr. side: tradestation.com/pricing/exchange-execution-and-clearing-fees
(primær, broker der offentliggør sine passthrough-satser), 2026-09-07.
NFA: 0.01 USD pr. kontrakt pr. side.

`et_tick_bp` er ét tick som andel af notional — vores model antager netop ét tick spread,
så `rundtur_i_alt_bp` er gebyr + antaget spread.

**Mikrokontrakter koster 1,5-2× de fuldstore målt i basispunkter**, ikke 10× som man
kunne frygte: Tradovates mikro-kurtage (0,39 USD) er selv skaleret ned. Undtagelsen er
`M6E` på 1,87 bp, hvor både gebyr og tick fylder meget på en lille notional.

### Danske udbydere

Ikke medtaget. Sporet her er krypto (Binance) og prop-futures (Tradovate/CME); en dansk
aktieudbyder ville først være relevant hvis aktier eller ETF'er kom i spil, og det er de
ikke i denne opgave.

---

## DEL 2a — spread estimeret fra high/low: **metoden virker ikke på vores data**

Begge estimatorer er slået op og verificeret mod forfatternes egne formler før
implementering — ikke gengivet fra hukommelsen:

- **Corwin & Schultz (2012)**, JF 67(2). Verificeret mod referenceimplementeringen
  (`high_low_spread_estimator*.R`). Én rettelse undervejs: jeg antog først at et
  natligt gap får estimatoren til at OVERvurdere spreadet. **Det er omvendt.** Gappet
  puster γ op, γ indgår som −√(γ/K) i α, så et større γ giver et MINDRE estimat. Et
  ujusteret estimat på et natlukket marked er altså for LAVT — den farlige retning.
- **Roll (1984)**, JF 39(4). `S = 2√(−Cov(Δp, Δp₋₁))`, anvendt på log-afkast.
  Udefineret ved positiv kovarians.

### Den afgørende diagnose

En rigtig bid-ask spread er en egenskab ved **ordrebogen**. Den er den samme uanset om
man ser på 5-minutters- eller 4-timers-barer. Skalerer estimatet med bar-længden, måler
det volatilitet.

| symbol | cs_5m_bp | cs_15m_bp | cs_1h_bp | cs_4h_bp | forhold_4h_over_5m | estimat_over_gulv_x |
|---|---|---|---|---|---|---|
| BTC/USDT | 2.98 | 5.74 | 15.24 | 32.57 | 10.9 | 1.66 |
| ETH/USDT | 4.22 | 7.88 | 20.27 | 48.12 | 11.4 | 1.66 |
| EUR/USD | 0.55 | 1.03 | 3.54 | 5.82 | 10.6 | 1.71 |
| GBP/USD | 0.56 | 1.09 | 3.04 | 5.55 | 9.9 | 1.72 |
| SOL/USDT | 5.98 | 10.19 | 23.79 | 58.33 | 9.8 | 1.62 |
| XAU/USD | 2.98 | 5.53 | 15.32 | 24.94 | 8.4 | 1.84 |

**Forholdet mellem 4h og 5m burde være 1,0. Det er 8,4-11,4.** Ren volatilitetsskalering
ville give √48 ≈ 6,9. Estimatet ligger altså på den forkerte side af selv den forklaring.

Og `estimat_over_gulv_x`: estimatet ligger konstant **1,6-1,8× sit eget støjgulv** på
hver eneste timeframe. Gulvet er hvad estimatoren rapporterer på en simuleret serie med
spread præcis nul, med samme volatilitet og samme bar-struktur. Et estimat der bare
følger sit eget gulv med en fast faktor indeholder ingen selvstændig
spread-information.

### Sanity-ankeret: hvor mange ticks?

Modellen antager ét tick. Estimatet omregnet til ticks:

| symbol | timeframe | cs_justeret_bp | cs_i_ticks |
|---|---|---|---|
| XAU/USD | 5m | 2.98 | 12.4 |
| XAU/USD | 15m | 5.53 | 22.99 |
| XAU/USD | 1h | 15.32 | 51.44 |
| XAU/USD | 4h | 24.94 | 83.65 |
| EUR/USD | 5m | 0.55 | 1.27 |
| EUR/USD | 15m | 1.03 | 2.37 |
| EUR/USD | 1h | 3.54 | 8.09 |
| EUR/USD | 4h | 5.82 | 13.31 |
| GBP/USD | 5m | 0.56 | 0.76 |
| GBP/USD | 15m | 1.09 | 1.47 |
| GBP/USD | 1h | 3.04 | 4.05 |
| GBP/USD | 4h | 5.55 | 7.38 |

**23-84 ticks på guld.** Der er ikke noget marked hvor COMEX-guld har et spread på 84
ticks. Ankeret fyrer præcis som det skulle: fejlen er i anvendelsen, ikke i markedet.
`EUR/USD` og `GBP/USD` på 5m og 15m er de eneste tal i nærheden af plausible (0,8-2,4
ticks) — og netop dér er bar-volatiliteten mindst i forhold til spreadet.

### Sammenligning med den målte spread

| symbol | n_snapshots | median_bp | middel_bp | maks_bp |
|---|---|---|---|---|
| BTC/USDT | 1 | 0.0013 | 0.0013 | 0.0013 |
| ETH/USDT | 1 | 0.0401 | 0.0401 | 0.0401 |
| SOL/USDT | 1 | 0.9604 | 0.9604 | 0.9604 |

Første rigtige orderbook-snapshot mod estimat og model, i basispunkter:

| Symbol | Målt (n=1) | Corwin-Schultz 15m | Model |
|---|---|---|---|
| BTC/USDT | **0,0013** | 5,75 | 1,00 |
| ETH/USDT | **0,0401** | 7,88 | 1,00 |
| SOL/USDT | **0,9604** | 10,19 | 1,00 |

Estimatet er 10-4.400× for højt. **Modellen er tættere på virkeligheden end estimatet
er** — hvilket ikke var det forventede resultat.

⚠️ `n=1`. Ét snapshot pr. symbol, taget mens dette blev skrevet. Det er en indikation,
ikke en måling. Optageren (DEL 2b) er bygget netop for at gøre det til en måling.

### Negative vinduer og udefineret Roll

Andel negative Corwin-Schultz-vinduer, gennemsnit over timeframes:

| symbol | negative_vinduer_% |
|---|---|
| BTC/USDT | 38.8 |
| ETH/USDT | 37.4 |
| EUR/USD | 37.0 |
| GBP/USD | 36.8 |
| SOL/USDT | 37.2 |
| XAU/USD | 35.7 |

**33-44% af vinduerne giver et negativt spread-estimat.** Behandlingen er valgt og fast:
negative vinduer **sættes til nul før midling**, som forfatterens egen kode gør. Det er
også kilden til støjgulvet — ren støj midles op til noget positivt.

Roll er udefineret i 32-47% af de rullende
vinduer (positiv autokovarians, altså momentum der overdøver bid-ask-hoppet).

### Rolige mod volatile perioder — spørgsmålet kan ikke besvares med denne metode

Estimatet er 1,5-3,4× højere i volatile vinduer end i rolige. **Det tal må ikke bruges.**
Vinduerne er delt på bar-range, og estimatoren måler netop bar-range. Resultatet er
cirkulært: vi har delt data op efter volatilitet og fundet at volatilitetsmålet er
højere i den volatile halvdel.

Spørgsmålet — **bliver spreadet bredere når markedet er uroligt?** — er rigtigt og
vigtigt, for en konstant spread i modellen ville undervurdere omkostningen præcis når
strategien handler mest. Det kan besvares når optageren har kørt, ikke før.

---

## DEL 2b — optageren: bygget, testet, ikke installeret

`research/orderbook_recorder.py`. Selvstændig proces, importerer intet fra `core/`.

- **20 niveauer pr. side**, snapshot hvert minut, 3 kryptosymboler.
- **Parquet**, partitioneret `dt=YYYY-MM-DD/symbol=X/HHMM.parquet`. Formatet er valgt
  før første snapshot; skifter vi det senere, er arkivet delt i to inkompatible halvdele.
- **Seneste 50 handler gemmes ved siden af** (`last_trade_px`, `buy_share`) — den
  stillede spread er ikke den effektive, og handlerne kan ikke hentes bagudrettet.
- **Diskforbrug, målt frem for gættet: 1,7 MB/døgn · 52 MB/måned · 0,62 GB/år.**

### Den må ikke dø i stilhed

En optager der stoppede for tre uger siden er værre end ingen optager, fordi vi ville
stole på dataen. Fire spærringer: auto-genstart med backoff (plus launchd `KeepAlive`),
eksplicit hul-logning når uret er drevet, `_heartbeat.json` med seneste vellykkede
snapshot, og `--coverage` der rapporterer dækningsgrad **pr. time i døgnet**.

### MacBooken sover, og det er systematisk skævhed

launchd genstarter ved boot og login, men en lukket MacBook kører ikke. Hullerne kommer
til at matche søvnrytmen — og **spread er bredest om natten og i weekenden, hvor
likviditeten er tyndest.** Måles der kun i dagtimerne, bliver "typisk spread" systematisk
for optimistisk, hvilket er den værste retning at tage fejl i.

Derfor er dækningsgraden opdelt pr. time. Viser den sig skæv, er mulighederne
`caffeinate -s`, ændrede energiindstillinger, eller at optageren flytter til noget der
altid er tændt. Beslutningen tages når tallene foreligger.

### Planlagt validering — skriv den ned nu, så den ikke glemmes

Krypto handler 24/7, så Corwin-Schultz' antagelser holder dér uden overnight-justering.
Når optageren har kørt et par uger: **sammenlign estimatet mod den målte spread på de
samme symboler over samme periode.**

Rammer estimatoren rigtigt dér hvor vi kan tjekke, kan vi tro på den på futures, hvor vi
ikke kan. Baseret på det første snapshot ser det allerede ud til at den ikke gør —
men n=1 afgør ingenting, og sammenligningen skal køres ordentligt.

**Indtil da er alle estimater i dette dokument uvaliderede.**

---

## DEL 3 — slippage: hvad vi ikke kan måle

Slippage er forskellen mellem den pris man forventede og den man fik. **Den kan ikke
måles uden rigtige fills.** Botten kører `dry_run`, så vi har ingen. Modellens
N(0,5; 0,5) ticks afkortet ved nul er et ærligt skøn uden datagrundlag, og det er
stadig tilfældet efter denne kørsel.

Hvad der kan siges nu:

- **Vores ordrer er for små til at flytte markedet.** Med `stake_amount: 5` er en ordre
  5 USD mod en top-of-book-dybde på typisk mange tusinde USD på BTC/USDT. Impact er
  dermed nul, og slippage reduceres i praksis til at krydse spreadet — altså det halve
  spread pr. side. Det bør bekræftes med dybdedataen når optageren har kørt; det er
  præcis hvad de 20 niveauer er til for.
- **Angivet som øvre grænse, ikke som måling.** Modellens 2 × 0,5 tick er en øvre grænse
  for en ordre af vores størrelse, ikke et estimat af den.

**Hvad der skulle til for at måle det rigtigt:** køre live med små beløb og logge
forventet pris mod faktisk fill for hver ordre. Det er en beslutning for senere og ikke
en del af denne opgave.

---

## DEL 4 — hvad en 15m-strategi skal levere

    WR* = (L̄ + omkostning_i_R) / (W̄ + L̄)

Med stoppet som 1R og målet som RR × 1R: **WR\* = (1 + omk_R) / (RR + 1)**.

### Omkostning i R på 15m, pr. stop-afstand

| symbol | 0.5 | 1.0 | 1.5 | 2.0 |
|---|---|---|---|---|
| BTC/USDT | 2.186 | 1.093 | 0.729 | 0.547 |
| ETH/USDT | 1.584 | 0.792 | 0.528 | 0.396 |
| EUR/USD | 0.657 | 0.329 | 0.219 | 0.164 |
| GBP/USD | 1.024 | 0.512 | 0.341 | 0.256 |
| SOL/USDT | 1.356 | 0.678 | 0.452 | 0.339 |
| XAU/USD | 0.062 | 0.031 | 0.021 | 0.015 |

Kolonnerne er stop-afstanden i × ATR(14) på 15m. **Tallet er omkostningen som andel af
1R** — det tal der betyder mest, fordi et strammere stop gør en fast omkostning
relativt større.

### Break-even win rate på 15m ved 1,0 × ATR-stop

| symbol | 1.0 | 1.5 | 2.0 | 3.0 |
|---|---|---|---|---|
| BTC/USDT | 104.7 | 83.7 | 69.8 | 52.3 |
| ETH/USDT | 89.6 | 71.7 | 59.7 | 44.8 |
| EUR/USD | 66.4 | 53.1 | 44.3 | 33.2 |
| GBP/USD | 75.6 | 60.5 | 50.4 | 37.8 |
| SOL/USDT | 83.9 | 67.1 | 55.9 | 42.0 |
| XAU/USD | 51.5 | 41.2 | 34.4 | 25.8 |

Kolonnerne er RR-forholdet. Ved RR 2:1 er den omkostningsfrie tærskel 33,3%.

### Ved hvilken stop-afstand koster en rundtur mere end 0,20 R?

Løst analytisk frem for ved gittersøgning — et gitter over 0,5-2,0 × ATR kan kun svare
"over 2,0", og det er ikke et svar.

| symbol | atr_15m_% | rundtur_bp | stop_xATR_for_0.20R | stop_i_% | omk_R_ved_1xATR | realistisk |
|---|---|---|---|---|---|---|
| XAU/USD | 0.1944 | 0.6 | 0.15 | 0.03 | 0.031 | True |
| EUR/USD | 0.0372 | 1.22 | 1.64 | 0.061 | 0.329 | True |
| GBP/USD | 0.0406 | 2.08 | 2.56 | 0.104 | 0.512 | False |
| SOL/USDT | 0.3686 | 25.0 | 3.39 | 1.25 | 0.678 | False |
| ETH/USDT | 0.3156 | 25.0 | 3.96 | 1.25 | 0.792 | False |
| BTC/USDT | 0.2287 | 25.0 | 5.47 | 1.25 | 1.093 | False |

**Dette er kørslens vigtigste tabel.**

- **`XAU/USD`: 0,15 × ATR.** Guldfutures er så billige (0,60 bp) at selv et meget
  stramt 15m-stop bærer omkostningen. Det eneste komfortable instrument i feltet.
- **`EUR/USD`: 1,64 × ATR** — lige akkurat inden for det realistiske.
- **`GBP/USD`: 2,56 × ATR** — uden for. 6B koster 3,4× mere end 6E i basispunkter.
- **Krypto: 3,4-5,5 × ATR.** På BTC svarer det til et stop på **1,25%** — bredere end et
  typisk 4h-stop. Skal man have et 4h-stop for at kunne betale for at handle på 15m, er
  der ingen grund til at handle på 15m.

Ved et almindeligt 1 × ATR-stop på 15m er omkostningen **0,68-1,09 R på krypto.** En
strategi skal altså vinde mere end en hel risikoenhed i gennemsnit, før den har betalt
for at komme ind og ud.

### Sammenligning på tværs af timeframes

```
FASE 3  omkostninger pr. timeframe  (stop = 1,0 x ATR14, RR 2:1, medianer over 6 symboler)
timeframe      1R_%  rundtur_bp   omk_R  be_WR_%  uden_omk_%  tillæg_pp
5m            0.111       13.54   1.055     68.5        33.3       35.2
15m           0.212       13.54   0.595     53.1        33.3       19.9
1h            0.486       13.54   0.231     41.0        33.3        7.7
4h            1.012       13.54   0.100     36.7        33.3        3.4
-----------------------------------------------------------------------
  15m krypto   0.316       25.00   0.792     59.7        33.3       26.4
  15m ikke-krypto   0.041        1.22   0.329     44.3        33.3       11.0
```

Skaleringen er det der afgør sporet. `1R` vokser omtrent med √tid (0,111% → 0,212% →
0,486% → 1,013%, altså ~×2 pr. skridt), mens omkostningen er konstant. Break-even win
rate ved RR 2:1 går derfor fra 36,6% på 4h til 68,5% på 5m.

**På 5m skal over to ud af tre handler vinde, bare for at gå i nul.**

---

## Forbehold

- **Estimaterne i DEL 2a er ubrugelige til at sætte tal på spread.** De er medtaget
  fordi opgaven bad om dem, og fordi den negative konklusion er værd at have på skrift:
  vi kan ikke estimere vores spread fra OHLCV. Vi bliver nødt til at måle den.
- **Den målte spread er n=1.** En indikation, ikke et tal at regne på.
- **Slippage er uændret et skøn.**
- **Gebyrer har opslagsdato 2026-09-07** og ændrer sig. Binance futures-satsen er
  sekundær kilde.
- **`atr_pct` på 15m for futures bygger på 60 dages historik** — Yahoos intraday-cap.
  Krypto har 8.000 barer. De to tal er ikke lige robuste.
- **`backtest.costs` er urørt.** Modellens 25 bp på krypto er 20 bp verificeret gebyr +
  5 bp antagelse; den antagelse ser nu ud til at være for høj på spread og ukendt på
  slippage. Rettelsen er ikke foretaget.

---

## Filer

- `research/spread_estimators.py` — Corwin-Schultz (med overnight-justering), Roll, støjgulv
- `research/orderbook_recorder.py` — optageren; `--estimate-disk`, `--once`, `--coverage`
- `research/cost_data.py` — flertimeframe-hentning
- `research/run_cost_analysis.py` — DEL 1, 2a, 4 og sessionstabellen
- `tests/test_spread_estimators.py` — formeltro mod referencen + genfinding af kendt spread
- `data/orderbook/README.md` — datasættets egne begrænsninger
- `com.madskvist.orderbook.plist` — launchd, **ikke installeret**
- `research/output/spread_estimates.csv`, `breakeven_table.csv`
