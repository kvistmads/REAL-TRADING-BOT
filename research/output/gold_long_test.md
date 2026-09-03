# Lang guld-serie: validering og regimetest (2004-2025)

**Kørt:** 2026-09-03 11:24 UTC


## Svar

**Gaten peger den forkerte vej på 21 år guld.** De handler den ville blokere gav **+0.0144 R** mod de tilladtes **-0.1177 R** — en forskel på -0.1321 R i BLOKEREDES favør. Fortegnet er det samme i 4 af 4 perioder.

**Men det er ikke påvist.** Intervallet (-0.3261, 0.0619) krydser nul, og forskellen (0.1321 R) ligger under den mindst detekterbare (0.3299 R). Retningen er konsistent; styrken rækker ikke til en konklusion.

> **Og den modsiger to-års-resultatet.** Dér så gaten gunstig ud (+0,0651 mod −0,0534 R på seks symboler). Her ser den skadelig ud. To stikprøver, modsatte fortegn, ingen af dem signifikante — det er præcis det billede Modcase 2 beskriver.


## Hvad denne kørsel kan og ikke kan købe

21 år guld giver ~750 handler. Mindst detekterbare forskel skalerer med 1/√n, så tærsklen flytter sig fra ~0,42 R til ~0,32 R. **Det er stadig langt over enhver realistisk edge for en trendstrategi.**


Denne kørsel er derfor **ikke** svaret på Modcase 2. Den er (1) en validering af en datakilde vi har liggende, (2) en test af om apparatet holder på en lang serie, og (3) en mulighed for at se regimeskift over mange cyklusser frem for to. Et positivt resultat må ikke overlæses.


> **Hvad der faktisk skulle til:** ~7.600 handler for at kunne se 0,10 R — svarende til ~35 år på seks symboler, eller ~40 symboler over fem år. **Bredde, ikke historik.** Én lang serie på ét instrument løser det ikke.


## 3a. Validering


### Datakvalitet pr. år

| år | barer | forventet | dækning_% | flade_barer | nul_volumen | huller>72t | største_hul_dage | brugbar |
|---|---|---|---|---|---|---|---|---|
| 2004 | 816 | 855 | 95.3 | 5 | 0 | 4 | 3.7 | True |
| 2005 | 1476 | 1526 | 96.7 | 6 | 0 | 6 | 4.7 | True |
| 2006 | 1469 | 1526 | 96.2 | 3 | 0 | 7 | 4.3 | True |
| 2007 | 1535 | 1534 | 100.0 | 0 | 0 | 1 | 3.2 | True |
| 2008 | 1540 | 1538 | 100.1 | 0 | 0 | 2 | 3.2 | True |
| 2009 | 1538 | 1534 | 100.2 | 0 | 0 | 1 | 3.3 | True |
| 2010 | 1525 | 1526 | 99.9 | 2 | 0 | 2 | 3.7 | True |
| 2011 | 1525 | 1526 | 99.9 | 1 | 0 | 3 | 3.5 | True |
| 2012 | 1537 | 1534 | 100.1 | 0 | 0 | 1 | 3.2 | True |
| 2013 | 1544 | 1534 | 100.6 | 0 | 0 | 1 | 3.2 | True |
| 2014 | 1539 | 1534 | 100.3 | 0 | 0 | 1 | 3.2 | True |
| 2015 | 1532 | 1534 | 99.8 | 0 | 0 | 1 | 3.3 | True |
| 2016 | 1542 | 1526 | 101.0 | 0 | 0 | 2 | 3.2 | True |
| 2017 | 1534 | 1522 | 100.8 | 0 | 0 | 2 | 3.5 | True |
| 2018 | 1539 | 1534 | 100.3 | 0 | 0 | 1 | 3.2 | True |
| 2019 | 1540 | 1534 | 100.3 | 0 | 0 | 1 | 3.2 | True |
| 2020 | 1547 | 1538 | 100.5 | 0 | 0 | 2 | 3.2 | True |
| 2021 | 1542 | 1526 | 101.0 | 0 | 0 | 2 | 3.2 | True |
| 2022 | 1548 | 1526 | 101.4 | 0 | 0 | 2 | 3.2 | True |
| 2023 | 1542 | 1522 | 101.3 | 0 | 0 | 2 | 3.2 | True |
| 2024 | 1554 | 1538 | 101.0 | 0 | 0 | 1 | 3.2 | True |
| 2025 | 610 | 1146 | 53.2 | 0 | 0 | 4 | 80.9 | False |


**Brugbart spænd: 2004-2024.** 2025 fejler med 53,2% dækning og et hul på 81 dage (2025-07-11 → 2025-09-30). Restriktionen til de validerede år er ikke en reparation — intet er udfyldt, interpoleret eller ændret.


### Krydsvalidering mod GC=F (daglige lukkekurser)

Guld-spot og COMEX-futures er ikke samme instrument — futures bærer carry, så et niveauafvig er forventeligt. Det afgørende er at de BEVÆGER sig ens.


| periode | fælles_dage | lang_serie_barer | GC=F_barer | median_prisafvig_% | maks_prisafvig_% | korr_daglige_afkast | status |
|---|---|---|---|---|---|---|---|
| 2008-01-01→2008-12-31 | 251 | 258 | 253 | 0.034 | 4.593 | 0.8428 | ok |
| 2015-01-01→2015-12-31 | 251 | 258 | 252 | 0.046 | 1.812 | 0.9067 | ok |
| 2020-01-01→2020-12-31 | 253 | 259 | 253 | 0.03 | 3.032 | 0.9161 | ok |
| 2024-01-01→2024-12-31 | 252 | 259 | 252 | 0.08 | 1.942 | 0.9105 | ok |


**Bestået.** Krav: afkastkorrelation ≥ 0.8 og median prisafvigelse ≤ 1.0% på alle perioder.


### Volumen — er det tick-volumen?

| median_volumen | volumen_min | volumen_maks | andel_nul | median_ratio | ratio_p90 | korr_volumen_range |
|---|---|---|---|---|---|---|
| 9752.0 | 1.0 | 249196.0 | 0.0 | 0.8925 | 1.7524 | 0.4625 |


Volumen varierer meningsfuldt (median-ratio 0,89, p90 1,75) og korrelerer moderat med bar-range (0.4625). Det er konsistent med **tick-volumen**: hvert tick ER en prisbevægelse. Niveauet er broker-afhængigt og kan ikke sammenlignes med rigtig omsat volumen. **Enhver strategi der bruger volumen-ratio er upålidelig på denne serie** — det gælder `volatility_breakout` og `reversal_context`, ikke `trend_momentum`, som ikke rører volumen.


### Overlapstest — den stærkeste identitetstest

Samme strategi, samme periode, to datakilder. Måler præcis det vi bruger dataen til.


Vindue: 2024-10-17 → 2025-02-28. Afkortet ved 2025-02-28, fordi den lange serie er mangelfuld fra marts 2025 (marts 90 barer, april 24, juli 51 mod ~128 i en normal måned).


| kilde | barer_i_vindue | handler | WR_% | R/handel_brut | R/handel_net | median_ATR_% |
|---|---|---|---|---|---|---|
| GC=F (nuværende kilde) | 559 | 9 | 22.22 | 0.076 | 0.0673 | 0.6034 |
| lang serie | 562 | 7 | 14.29 | -0.1429 | -0.1532 | 0.4837 |


**Bestået.** Median ATR% er det stærkeste identitetstal her — handelstallene hviler på 7-9 handler i et vindue på fire en halv måned og skal ikke overfortolkes.


> **Forbehold:** afvigelsen er 19.8%, altså bestået men ikke ren. Barantallet matcher tæt (559 mod 562), men den lange serie er mærkbart mindre volatil i samme vindue. Det er foreneligt med spot mod futures — futures bærer rollover og har bredere natlige spring — men konsekvensen skal stå tydeligt: **1R er ~20% mindre på den lange serie, så R-multipler fra 3b kan ikke sammenlignes direkte med R-multipler fra to-års-kørslerne.** Sammenligninger INDEN FOR den lange serie er upåvirkede.


## 3b. Regimetest på 2004-2024, fire perioder

Ét instrument. Resultatet kan bekræfte eller modsige de to år, men det kan **ikke alene afgøre noget for porteføljen**.


| periode | handler | tilladt | blokeret | blokeret_% | R_tilladt | R_blokeret | forskel |
|---|---|---|---|---|---|---|---|
| P1 2004-06→2009-09 | 133 | 57 | 76 | 57.1 | -0.0775 | 0.0405 | -0.118 |
| P2 2009-09→2014-10 | 148 | 57 | 91 | 61.5 | -0.1237 | 0.0867 | -0.2104 |
| P3 2014-10→2019-11 | 147 | 36 | 111 | 75.5 | -0.1471 | -0.1468 | -0.0003 |
| P4 2019-11→2024-12 | 154 | 44 | 110 | 71.4 | -0.1379 | 0.0993 | -0.2372 |


### Præregistreret kriterium (låst før kørsel)

Kriteriet er **konsistens, ikke signifikans i én periode**: slår gaten igennem i én periode og ikke de andre, er det støj — samme logik som flip-exit.


| krav | resultat | opfyldt |
|---|---|---|
| Tilladte slår blokerede i mindst 3 af 4 perioder | 0/4 | NEJ |
| Samlet interval krydser ikke nul | -0.1321 R, CI (-0.3261, 0.0619) | NEJ |


Mindst detekterbare forskel med n=194 pr. gruppe: **0.3299 R** (mod 0,42 R på to år).


### Regime-fordeling pr. periode (barer)

| periode | barer | trending_% | volatile_% | sideways_% |
|---|---|---|---|---|
| P1 2004-06→2009-09 | 7866 | 62.03 | 0.0 | 37.97 |
| P2 2009-09→2014-10 | 7866 | 58.52 | 0.0 | 41.48 |
| P3 2014-10→2019-11 | 7866 | 56.09 | 0.0 | 43.91 |
| P4 2019-11→2024-12 | 7866 | 53.94 | 0.0 | 46.06 |


**`volatile` udløses 0,00% af tiden i alle fire perioder.** Over 21 år guld rammer regimet aldrig — ATR/close > 4% forekommer ikke på 4h-barer i dette instrument. Det bekræfter fundet fra to-års-kørslen (`volatile_min_confidence: 0.75` ramte 3 af 432 handler) og gør det stærkere: tærsklen er ikke sjældent brugt, den er ubrugt.


Trending-andelen falder jævnt gennem de fire perioder (62,0% → 58,5% → 56,1% → 53,9%). Det er en langsom drift over 21 år, ikke et regimeskift der kan forklare et fald fra én toårsperiode til den næste.


## Antal sammenligninger

Denne kørsel: **5**. Samlet for hele forløbet: ~25 fra de foregående fem analyser plus 5 her = **~30**. Ved alpha 5% er sandsynligheden for mindst ét falsk positivt fund 79%.


## Hvad der IKKE er gjort

- Dataen er ikke repareret. Ingen huller er udfyldt eller interpoleret.

- Den nuværende guld-kilde er ikke erstattet. `config.yaml` er urørt.

- Ingen konfigurationsændring foreslået.
