# PRD: Validering af Daily Bias — før strategien bygges

**Status:** Forskningsopgave. Ingen ændringer til botten.
**Skrevet:** 2026-08-21
**Forudgående arbejde:** `research/daily_bias.py`, `data/historical_xau/`, `project_daily_bias_test.md`

---

## 1. Hvad denne opgave ER og IKKE er

Vi har en kandidat-strategi der bestemmer en **daglig retningsbias**. Før vi bygger
entry-logik, exits eller en strategifil, vil vi vide om biasen overhovedet indeholder
retningsinformation.

**Denne session skal:** hente daglige data for 8 markeder, køre bias-klassifikatoren,
og måle om biasen slår markedets egen basisrate. Output er en rapport.

**Denne session skal IKKE:**
- Oprette filer i `strategies/`
- Røre `config.yaml`, `engine.py`, `gates/`, `data/fetcher.py` eller `data/indicators.py`
- Bygge entry-, exit- eller RR-logik
- Ændre `dry_run`, `sandbox`, `leverage`, `stake_amount` eller `max_open_trades`

Hvis validering fejler, bygger vi ikke strategien. Det er hele pointen.

---

## 2. Strategien der valideres

Kilde: TradingLab, "How To Find a Daily Bias (On ANY Chart)". Klassifikatoren er
allerede skrevet og enhedstestet i **`research/daily_bias.py`** — genimplementér den ikke,
importér den.

**Referenceramme:** Range = FORRIGE daglige candles high og low, **wicks inkluderet**.
Signalcandle = seneste **lukkede** daglige candle. Bias gælder én dag frem.

| Scenarie | Betingelse | Retning |
|---|---|---|
| S5 | fejer over prior high, lukker under prior low | SHORT |
| S2 | fejer under prior low, lukker over prior high | LONG |
| S3 | begge sider fejet, luk inde i rangen | ingen handel |
| S1 | kun high fejet, luk tilbage inde i rangen | SHORT |
| S1M | kun low fejet, luk tilbage inde i rangen | LONG *(vores tilføjelse — ikke i videoen)* |
| S4 | ingen af siderne brudt | ingen handel |
| BO_UP / BO_DOWN | luk uden for rangen uden modsat sweep | deaktiveret via flag |

**KRITISK — rækkefølge:** luk-position skal tjekkes FØR "begge sider fejet". S2 og S5 er
geometriske delmængder af S3; tjekker man S3 først, filtreres begge stærkeste signaler væk.
Klassifikatoren gør det allerede rigtigt. Lav ikke om på rækkefølgen.

---

## 3. Data

Hent **daglige** barer, så lang historik som kilden giver. Gem som CSV i
`data/historical/<symbol>_1d.csv` med kolonnerne `Date;Open;High;Low;Close;Volume`
(semikolon, dato som `YYYY.MM.DD HH:MM`) så formatet matcher de eksisterende XAU-filer.

| # | Marked | Kilde | Symbol |
|---|---|---|---|
| 1 | Bitcoin | `ccxt` Binance | `BTC/USDT` |
| 2 | Ethereum | `ccxt` Binance | `ETH/USDT` |
| 3 | Solana | `ccxt` Binance | `SOL/USDT` |
| 4 | Euro | `yfinance` | `6E=F` |
| 5 | Pund | `yfinance` | `6B=F` |
| 6 | Guld | `yfinance` | `GC=F` |
| 7 | S&P 500 | `yfinance` | `ES=F` *(futures — besluttet, ikke `^GSPC`)* |
| 8 | Nasdaq 100 | `yfinance` | `NQ=F` *(futures — besluttet, ikke `^NDX`)* |

Begge biblioteker er allerede afhængigheder i repoet.

**Dagsgrænse:** markeder med åbningstider følger deres session — yfinance' daglige barer
gør det allerede korrekt. Crypto (24/7) nulstiller ved **midnat UTC**, hvilket er ccxt's
standard for `1d`. Konstruér ikke egne daglige barer fra intraday-data.

**Datavalidering (påkrævet, gør det først):** `data/historical_xau/XAU_4h_data.csv` og de
øvrige XAU-filer stammer fra et fremmed GitHub-repo og er **aldrig valideret**. Sammenlign
den daglige XAU-serie mod `GC=F` fra yfinance på de overlappende år. Rapportér median
absolut afvigelse i close, og hvor mange dage der mangler i den ene men ikke den anden.
Hvis afvigelsen er væsentlig, brug `GC=F` som primær og noter det.

---

## 4. Testmetode

For hvert marked, hver dag med et handlebart signal (S1, S1M, S2, S5):

**Ankre** — mål begge, rapportér begge:
- **Primær: dag D+1's åbning.** Den tidligste pris man realistisk kan handle på.
- **Sekundær: dag D's luk.** Forskellen mellem de to *er* natte-gappet — rapportér det som
  sin egen kolonne.

**Horisonter:** 1, 2, 3, 4 og 5 **handelsdage** (barer, ikke kalenderdage — crypto handler
i weekenden, de andre gør ikke).

**Exit:** ved horisontens slut. Ingen stop loss, intet take profit, ingen RR.
**Hit** = lukkede i biasens retning ved horisontens slut. Intet tælles som tab fordi det
løb videre — vi validerer udelukkende retning.

**Modstridende bias undervejs:** ignorér. Hold til horisonten. Ellers tester vi en exit-regel.

**Basisrate:** beregnes **pr. marked og pr. horisont**, vægtet efter den faktiske
long/short-fordeling i signalerne. Uden dette måler man markedets drift, ikke strategien.
Et marked i optrend giver "gratis" høj hitrate på long-signaler.

**Overlappende vinduer:** ved N>1 overlapper signaler fra nabodage, så observationerne ikke
er uafhængige — det oppuster signifikansen. Rapportér **både** alle signaler **og** en
ikke-overlappende delmængde (tag næste signal mindst N barer efter det forrige).

**Tærskel for wick-gennembrud:** `MIN_BREAK_ATR = 0.0` er primær ("over rangen er over
rangen"). Kør også 0.05 og 0.10 som robusthedstjek — **ikke** for at vælge den bedste, men
for at se om konklusionen er stabil. Vælg aldrig tærskel efter resultat.

**Ingen entry-regel.** I det øjeblik der tilføjes "gå ind når 15m-lyset gør X", tester vi
biasen plus entry-reglen og kan ikke skelne deres bidrag. Entry-logik kommer først når
biasen er bekræftet.

---

## 5. Regressionstjek — kør dette først

Cowork-sessionen har allerede kørt testen på `data/historical_xau/XAU_1d_data.csv`
(5.383 barer, 2004-06-11 → 2025-09-30, `MIN_BREAK_ATR = 0.0`, anker D-luk, N=1).
**Din pipeline skal reproducere disse tal.** Gør den ikke det, er der en fejl i din kode —
find den før du kører de øvrige markeder.

| Scenarie | n | Hitrate | Basisrate |
|---|---|---|---|
| S1 bearish | 869 | 44,9% | 47,2% |
| S1M bullish | 827 | 54,2% | 52,8% |
| S2 bullish | 153 | 41,2% | 52,8% |
| S5 very bearish | 158 | 45,6% | 47,2% |
| S3 (ingen handel) | 229 | — | — |
| S4 (ingen handel) | 898 | — | — |
| Udefineret | 2.247 | — | — |

Samlet: 2.007 handlebare signaler, 48,5% hitrate, MFE/MAE = 1,00.

---

## 6. Output

**`research/output/bias_validation.md`** — læsbar rapport:
- Én tabel pr. marked: scenarie × horisont, med hitrate, basisrate, forskel i procentpoint,
  n, og z-score mod basisraten
- Tværgående oversigt: hvor mange markeder består kriteriet, pr. scenarie
- Datavalideringsafsnittet fra §3
- Robusthedsafsnit: ændrer ATR-tærsklen eller ankeret konklusionen?

**`research/output/bias_validation.csv`** — rå resultater, én række pr.
(marked, scenarie, horisont, anker, tærskel, overlap-tilstand) med alle metrikker.
Så kan vi analysere videre uden at køre igen.

Rapportér også **frekvens** for S3, S4 og de tre deaktiverede kombinationer — hvor ofte de
optræder er nyttigt selvom de ikke handler.

---

## 7. Succeskriterium — fastlagt FØR kørslen

Biasen består hvis:

- Hitraten slår markedets egen basisrate med **mindst 3 procentpoint**
- på **mindst 4 af de 8 markeder**
- med **mindst 200 signaler** pr. marked
- med **konsistent fortegn** — ikke ét marked der bærer det hele

Basisraten er ~50%, så tærsklen er reelt omkring **53%** direktionel træfsikkerhed.
Det lyder beskedent. Til kalibrering: Renaissance Technologies' Medallion-fond opererer
efter eget udsagn på 50,75%.

**Dette kriterium må ikke justeres efter at have set tallene.** Finder vi en delmængde der
ser stærkere ud — kun crypto, kun én horisont, kun ét scenarie — er det en **hypotese til
næste test**, ikke et resultat. Skriv den ned, konkludér ikke på den.

Rapportér ærligt uanset udfald. Et negativt resultat der sparer os for at bygge strategien
er lige så værdifuldt som et positivt.

---

## 8. Faldgruber

1. **Lookahead.** Biasen for dag D+1 må kun bruge data til og med dag D's luk. Vi fandt
   præcis denne fejl i et andet repo forleden: signalet krævede næste bars luk, men
   handlede på næste bars åbning. Verificér eksplicit at ingen beregning ser fremad.
2. **Basisrate pr. marked.** Guld tidoblede sig i perioden. Uden basisrate-korrektion ser
   ethvert long-signal godt ud og ethvert short-signal dårligt ud.
3. **S2/S5 filtreret væk af S3.** Se §2. Klassifikatoren gør det rigtigt — lav ikke om.
4. **Kontrakt-rulning.** `ES=F`, `NQ=F`, `GC=F`, `6E=F` og `6B=F` er kontinuerte
   futures-serier. Rul-datoer giver kunstige gaps. Noter hvordan yfinance håndterer det og
   om det påvirker range-beregningen.
5. **Et for godt resultat er et alarmsignal.** Ser noget ud til at ramme 70%+, så led efter
   en fejl før du fejrer det.

---

## 9. Kør ikke videre bagefter

Når rapporten ligger, stop. Byg ikke strategien, uanset hvad resultatet viser —
vi tager beslutningen sammen ud fra tallene.
