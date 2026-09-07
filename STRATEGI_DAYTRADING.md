# Daytrading-sporet — hvad vi ved, hvad vi har afvist, og hvad der mangler

**Status:** Aktivt spor. Målet er en bot der handler mens Mads er på arbejde, slår
buy-and-hold over tid, og kan bestå en prop-firma-evaluering.
**Skrevet:** 2026-09-04
**Søsterdokument:** `STRATEGI_TSMOM.md` (udskilt til separat notifikationsprojekt)

---

## 1. Fire ting vi har afvist — og hvad de kostede

Alle fire blev testet med præregistrerede kriterier. Ingen af dem bestod.

### Flip-exit (luk når EMA50 brydes)

Første kørsel så lovende ud: `trend_momentum` gik fra −1,48% til +10,26%. Ud af
stikprøven holdt det ikke.

```
                 1. halvdel      2. halvdel
A1 (uden flip)   +33,05%         −102,04%
A2 (med flip)    +25,07%          −89,19%
```

A2 er bedre på PnL i anden halvdel, dårligere på profit factor. Omvendt i første.
**En regel med reel edge forbedrer begge mål.**

Den parrede test — samme entries, kun exit varierer — gav delta 0,0152 R med
CI [−0,0546, +0,0849]. Krydser nul.

Og hele effekten sad i ét symbol: SOL bidrog +15,77 i anden halvdel mod en samlet
forskel på +12,85. Uden SOL var A2 dårligere.

**Afvist på begge testmetoder. Lukket.**

### Confidence-scoren

`min_confidence: 0.45` afviser **3 af 686 signaler**. En gate der ikke afviser noget
kan hverken koste eller gavne.

Kvartilgab: `trend_momentum` −3,67 pp, `volatility_breakout` −12,7 pp. Men mindste
detekterbare forskel var 18,59 og 24,45 pp. **Kan ikke afgøres**, ikke "virker ikke".

For at se et gab på 5 pp med 80% styrke kræves ~1.566 handler pr. bånd. Vi havde 109.

### Instrumentklasse (krypto mod ikke-krypto)

```
gruppe        R/handel netto   95%-CI
krypto             −0,0939     [−0,2298, +0,042]
ikke-krypto        +0,0964     [−0,0884, +0,2812]
```

Begge krydser nul. Målt gruppeforskel 0,19 R, mindste detekterbare 0,36 R.
**Kan ikke afgøres.**

### Regime-gaten (ADX + EMA)

Den eneste af de fire der ikke er inert: **blokerer 313 af 432 handler = 72,5%.**

```
              1. halvdel   2. halvdel
tilladt        +0,3046      −0,1552
blokeret       +0,0426      −0,1396
```

På 21 års guld peger den den forkerte vej i 4 af 4 perioder: tilladt −0,1177 mod
blokeret +0,0144. CI (−0,3261, +0,0619) krydser nul.

**To stikprøver, modsatte fortegn, ingen af dem signifikante. Den samlede evidens
for gaten er nul** — ikke "uafklaret", men bogstaveligt talt nul netto.

---

## 2. Regnestykket der forklarer det hele

Strategiens geometri afgør hvor god den skal være for bare at gå i nul.

```
E = (W̄ + L̄) · [WR − WR*]        hvor WR* = (L̄ + omkostning) / (W̄ + L̄)
```

Faktiske haler for `trend_momentum`:

```
W̄ (gns. vinder)     1,472 R
L̄ (gns. taber)      0,694 R
break-even WR       32,0%
observeret WR       33,80% brutto / 33,56% netto
```

Med omkostninger flytter tærsklen sig:

```
omkostning              break-even WR
0 R (brutto)                32,0%
0,024 R (ikke-krypto)       33,2%
0,080 R (krypto)            35,7%
```

**Strategien ligger mellem de to tærskler.** Den klarer knap ikke ikke-kryptos krav
og misser kryptos med to procentpoint. Det er hele historien i ét tal.

### Konsekvens for design

Hvis `tp_rr_ratio` sænkes fra 2,0 til 1,5, stiger break-even WR fra 33,3% til 40,0%
(ved idealiserede haler). Strategien skal så levere seks procentpoint mere end den
nogensinde har gjort. **Enhver ændring af RR-forholdet skal regnes igennem her
først.**

---

## 3. Omkostninger — det centrale problem for daytrading

### Målt pr. handel (nuværende model, 4h)

```
                 i basispunkter    i risikoenheder (R)
krypto                25,0 bp            0,0803 R
ikke-krypto            1,26 bp           0,0242 R
forhold                19,8×                3,3×
```

**Bemærk hvordan forholdet kollapser når man normaliserer.** 19,8× i bp lyder
dramatisk, men krypto risikerer også langt mere pr. handel. Målt pr. risikoenhed er
forskellen 3,3×, ikke 20×.

### Hvorfor 1R er så forskelligt

```
symbol     ATR%_median   1R i %
BTC/USDT      1,24        2,42
ETH/USDT      1,92        3,73
SOL/USDT      2,26        4,49
XAU/USD       0,83        1,64
EUR/USD       0,24        0,53
GBP/USD       0,24        0,50
```

Krypto har 5-9× større ATR i procent end forex. **Derfor er procent-sammenligninger
på tværs af instrumentklasser meningsløse.** Alt skal måles i R.

### Hvad omkostninger gjorde ved 4h-botten

```
periode        brutto      netto     omkostning
1. halvdel    +65,68%    +33,05%      32,63 pp
2. halvdel    −65,28%   −102,04%      36,76 pp
```

**Omkostningerne var på størrelse med bruttoresultatet.** Krypto bar 96% af trækket,
fordi krypto udgjorde 61% af handlerne til 25 bp mod 1,5 bp for resten.

### Skaleringen ned i timeframe

Dette er den vigtigste enkeltbetragtning for daytrading-sporet.

Omkostningen pr. handel er nogenlunde konstant. Bevægelsen man fanger skrumper når
timeframen falder. Går man fra 4h til 15m, får man cirka 16× flere handler, og
bevægelsen pr. handel er tilsvarende mindre.

**Omkostningen som andel af bruttoresultatet stiger dermed dramatisk.** Til
sammenligning: TSMOM på månedsbasis havde omkostninger på 0,0-0,5% af bruttoafkastet;
4h-botten lå omkring 50%.

Det udelukker ikke lavere timeframes. Men det betyder at **en 15m-strategi skal have
en markant større edge pr. handel end en 4h-strategi for at ende samme sted** — og
den skal handle et sted hvor omkostningerne er lave.

---

## 4. Måleapparatet — hvad vi har bygget

Al kode ligger i repoet og er testdækket.

| Fil | Hvad den gør |
|---|---|
| `backtest/costs.py` | Spread, slippage, kurtage pr. aktivklasse. Seedet slippage, aldrig favorabel |
| `backtest/rnorm.py` | R-normalisering, R-fordeling, største outliers, mindste detekterbare forskel |
| `backtest/paired.py` | Parret sammenligning — samme entries, kun én regel varierer |
| `research/stats.py` | Wilson-intervaller, Spearman + CI, break-even WR, styrkeberegning |
| `research/diagnostics.py` | Flade barer, huller, dækningsgrad, krydsvalidering |

**Apparatet er valideret:** det genfandt time-series momentum, en effekt dokumenteret
over et århundrede. `SPY` gav 10,53% CAGR med −33,7% drawdown mod buy-and-holds
10,81% / −55,2%. Kriteriet holdt på alle tre krav.

**Det betyder at "ikke påvist" i de fire afvisninger ovenfor var udsagn om
strategierne, ikke om målingen.**

### Metoderegler vi har vedtaget

1. **Præregistrér kriteriet før kørslen.** Uden undtagelse.
2. **Buy-and-hold-baseline på hver eneste kørsel**, på samme linje i tabellen.
3. **Brutto og netto side om side.** Aldrig kun det ene.
4. **Modcasen vægtes lige så tungt** som hovedhypotesen.
5. **Backtesten kører uden gates.** Gates hører til i live.
6. **Ingen strategi bygges oven på en anden før basen har vist edge.** Vi brugte uger
   på at forfine en exit-regel på en strategi med brutto-PF 0,98.
7. **Ét instrument pr. underliggende aktiv** i en portefølje.
8. **R er risikoen ved indgang.** Et flyttet stop ændrer ikke R.
9. **Rapportér mindste detekterbare forskel.** Et resultat under den er "kan ikke
   afgøres", ikke "virker ikke".

### Multiplicitet — den vigtigste advarsel

Vi har foretaget **omkring 30 separate sammenligninger på de samme 432 handler.** Ved
alpha 5% giver det ~79% sandsynlighed for mindst ét falsk positivt fund.

Symbolerne er heller ikke uafhængige: 0,80-0,83 inden for krypto, 0,78 mellem EUR/USD
og GBP/USD. Otte symboler var reelt ~4 uafhængige observationer.

**Kigger man på seks ting, finder man altid en der ser overbevisende ud.** Den eneste
beskyttelse er at beslutte hvad man leder efter, før man kigger.

---

## 5. Kendte forhold ved den kørende bot

Står også i `CLAUDE.md`. Ingen af dem er rettet.

- **`min_confidence: 0.45`** afviser 3 af 686 signaler. Aritmetisk næsten inaktiv.
- **`volatile_min_confidence: 0.75`** er ubrugt. Volatile-regimet ramte 3 af 432
  handler i to-års-kørslen og **0,00% over 21 års guld**. Konfigurationen har tre
  regime-tilstande; i praksis har den to.
- **Regime-gaten blokerer 72,5% af handlerne** uden påviselig gavn.
- **Gaten skelner ikke mellem "sideways" og "kan ikke vurdere".** NaN-ADX falder
  igennem til SIDEWAYS, hvilket for `trend_momentum` betyder blokeret. Manglende data
  tælles som en regimevurdering.
- **Regimet skifter undervejs i 52,3% af handlerne** (median 2 skift). Gaten
  revurderer aldrig — den kører én gang ved entry.

### En mekanisme man skal kende i backtesten

`backtest/runner.py` springer markøren frem med `i += max(trade["bars_held"], 1)` for
at undgå overlappende positioner. **En exit-regel der forkorter handler flytter
derfor alle efterfølgende entries.** To kørsler med forskellige exits er ikke samme
handler med forskellig exit — det er to forskellige vandringer gennem data.

Derfor findes `backtest/paired.py`. Brug den når en enkelt regel skal isoleres.

---

## 6. Hvor jeg ville lede efter en kortsigtet edge

Ikke i indikatormønstre. EMA-krydsninger, MACD, RSI og Bollinger på 4h er de mest
afprøvede ideer der findes; havde der været en simpel edge dér, var den væk.

**Ledetråden er: hvorfor betaler nogen mig for det her?** Kan spørgsmålet ikke
besvares, er der ingen edge — kun en parameterindstilling der passede til fortiden.

Kandidater hvor svaret findes:

**Funding rates på krypto-perpetuals.** Du får en *oplyst* rate for at tage den anden
side af en overbelastet position. Den mest eksplicitte edge der findes, tilgængelig
på Binance med lille konto. Risikoen er basis-risiko, ikke retningsrisiko.

**Likvidationskaskader.** Osler (2003, 2005) dokumenterer at stop-loss-klynger
udløser kaskader der *fortsætter* i omkring to timer, mens take-profit-drevne
vendinger dør ud på 30 minutter. Gemt som idé, aldrig bygget.

**Prisforskelle mellem børser.** Mekanisk, målbar, men kræver hurtig eksekvering.

**Kortsigtet reversal.** Dokumenteret, men omkostninger æder det typisk på
retail-niveau — se skaleringsafsnittet ovenfor.

Fælles for de tre første: **de betaler for at tage en ubehagelig eller ubekvem
position**, ikke for at genkende et mønster. Smarte mønstre bliver arbitreret væk;
ubehag gør ikke.

---

## 7. Åbne spørgsmål før næste fase

Disse skal besvares med rigtige tal, ikke skøn.

**Omkostninger.** Hvad koster en rundtur faktisk hos den broker vi ender med? Ikke
et modelleret bp-tal, men målte fills. Binance taker-fee afhænger af VIP-niveau og
BNB-rabat. Spread på 15m i stressede perioder er ikke det samme som i rolige.

**Slippage.** Vores model bruger N(0,5; 0,5) ticks afkortet ved nul. Det er et ærligt
skøn uden datagrundlag. Rigtige tal kræver enten broker-statistik eller egne fills.

**Datakilde.** Til backtest bruger vi ccxt og yfinance. Til live er tanken at hente
fra den broker der handles på, for at undgå forsinkelse — men så er backtest og live
kørt på forskellige serier, og det skal måles hvor meget de afviger. Vi så præcis det
problem på guld: 20% forskel i ATR mellem to kilder for samme instrument og periode,
formentlig fordi bar-grænserne lå forskelligt (MT4 servertid mod UTC).

**Timeframe.** 15m eller lavere kræver at omkostningen pr. handel er lav nok. Regn
break-even-tærsklen igennem *før* strategien bygges, ikke efter.

**Prop-firma-reglerne.** Sekundære guides modsiger hinanden om hvorvidt fuldt
automatiseret handel er tilladt på funded konti. Læs firmaets egen regelbog og få
skriftligt svar fra deres support på "må en bot åbne og lukke handler uden at jeg
sidder ved skærmen?" **før** der betales et gebyr. Der findes desuden
inaktivitetsregler, konsistensregler og nyhedsvinduer der alle rammer en
lavfrekvent strategi.

---

## 8. To strategier til prop-konti — den plan Mads har skitseret

**Én til at bestå evalueringen.** Opgaven er "nå +10% før du rammer −10% inden for
reglerne". Det er et defineret spil med defineret risiko — en anden opgave end at
tjene penge på lang sigt.

**Én til at holde kontoen bagefter** og sikre payouts.

Målprofil: 1-3 handler om dagen, helst 1-2 profitable, ingen handler når der ikke er
muligheder.

**Den spænding der skal håndteres:** profilen der består evalueringer — høj win rate,
små gevinster, sjældne store tab — er også den profil der sprænger funded konti
bagefter. Trendfølge med få store vindere er det modsatte og falder ofte i konflikt
med firmaernes konsistensregler. De to strategier trækker altså i hver sin retning
med vilje, og det er derfor de skal være to.

**Og drawdown er den bindende begrænsning, ikke afkast.** Hos de fleste firmaer
tæller urealiseret tab med i dagsgrænsen — en åben position under vand tæller, selv
om den ikke er lukket. Det er direkte uforeneligt med at holde positioner over natten
uden stramme stops.
