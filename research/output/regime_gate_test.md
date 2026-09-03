# Tjener regime-gaten sit ophold?

**Kørt:** 2026-09-03 07:05 UTC  
**Strategi:** trend_momentum · **Handler:** 432  
**Gatens tærskler (fra config, urørt):** min_trending_adx=20, max_volatile_atr_pct=4.0, volatile_min_confidence=0.75


> Gaten bruges her som **mærkat** på handler. Backtesten kører fortsat uden gates, og intet i live er ændret.


## Svar

**Ikke påvist.** Mindst ét af de tre præregistrerede krav fejler.


## Diagnostik før alt andet

**ADX-gyldighed:** 0 af 432 handler havde ugyldig ADX ved entry. Spørgsmålet om hvordan de skal tælles bortfalder dermed, som ATR-spørgsmålet gjorde i R-censussen.

| halvdel | barer | adx_nan | adx_nan_pct |
|---|---|---|---|
| 1. halvdel | 10072 | 0 | 0.0 |
| 2. halvdel | 11275 | 0 | 0.0 |


**Regimeskift undervejs:** regimet skiftede mindst én gang i **226 af 432 handler (52.3%)**, median 2 skift for dem der skiftede.


> Regimet skifter i de fleste handler. Entry-regimet er dermed en **svag etiket**, og 2b måler noget mere udvandet end det ser ud til — også hvis resultatet falder ud til gatens fordel.


## 2a. Hvor meget filtrerer gaten?

| gruppe | n | tilladt | blokeret | blokeret_% |
|---|---|---|---|---|
| krypto | 266 | 67 | 199 | 74.81 |
| ikke-krypto | 166 | 52 | 114 | 68.67 |
| SAMLET | 432 | 119 | 313 | 72.45 |


### Regime-fordeling ved entry (handler)

| regime | handler | andel_% |
|---|---|---|
| trending | 117 | 27.08 |
| volatile | 3 | 0.69 |
| sideways | 312 | 72.22 |


## 2b. Gaten som filter

En gate skal måles på hvad den FJERNER, ikke kun på hvad den beholder. `samlet_R` står ved siden af `R/handel`: en gate kan hæve gennemsnittet og samtidig fjerne så mange vindere at totalen falder.


| gruppe | n | andel_% | WR_% | R/handel_net | 95%-CI | samlet_R |
|---|---|---|---|---|---|---|
| tilladt | 119 | 27.55 | 34.45 | 0.0651 | [-0.1419, 0.2720] | 7.743 |
| blokeret | 313 | 72.45 | 33.23 | -0.0534 | [-0.1832, 0.0763] | -16.728 |
| alle (baseline) | 432 | 100.0 | 33.56 | -0.0208 | [-0.1307, 0.0891] | -8.985 |


**1. halvdel**

| gruppe | n | andel_% | WR_% | R/handel_net | 95%-CI | samlet_R |
|---|---|---|---|---|---|---|
| tilladt | 57 | 27.8 | 43.86 | 0.3046 | [-0.0139, 0.6232] | 17.364 |
| blokeret | 148 | 72.2 | 36.49 | 0.0426 | [-0.1580, 0.2432] | 6.299 |
| alle (baseline) | 205 | 100.0 | 38.54 | 0.1154 | [-0.0547, 0.2856] | 23.664 |


**2. halvdel**

| gruppe | n | andel_% | WR_% | R/handel_net | 95%-CI | samlet_R |
|---|---|---|---|---|---|---|
| tilladt | 62 | 27.31 | 25.81 | -0.1552 | [-0.4140, 0.1036] | -9.622 |
| blokeret | 165 | 72.69 | 30.3 | -0.1396 | [-0.3071, 0.0280] | -23.027 |
| alle (baseline) | 227 | 100.0 | 29.07 | -0.1438 | [-0.2843, -0.0033] | -32.649 |


### Præregistreret kriterium

| krav | opfyldt |
|---|---|
| 1. Tilladte > blokerede i begge halvdele | NEJ |
| 2. Forskellen (+0.1185 R) overstiger mindst detekterbare (0.4235 R) | NEJ |
| 3. Gaten blokerer mindst 10% (72.5%) | ja |


## 2c. Forklarer regime forværringen mellem halvdelene?

Målt på **barer**, ikke på handler: barer er markedet, handler er en filtreret stikprøve af det.


| halvdel | gruppe | barer | trending_% | volatile_% | sideways_% |
|---|---|---|---|---|---|
| 1. halvdel | ikke-krypto | 4072 | 54.74 | 0.0 | 45.26 |
| 1. halvdel | krypto | 6000 | 52.33 | 1.43 | 46.23 |
| 2. halvdel | ikke-krypto | 4675 | 52.6 | 0.0 | 47.4 |
| 2. halvdel | krypto | 6600 | 53.36 | 0.17 | 46.47 |


### Ændring fra 1. til 2. halvdel

| gruppe | trending_ændring_pp | volatile_ændring_pp | sideways_ændring_pp |
|---|---|---|---|
| krypto | 1.03 | -1.26 | 0.24 |
| ikke-krypto | -2.14 | 0.0 | 2.14 |


> **Regime forklarer det ikke.** Største ændring i regime-fordelingen er 2.1 procentpoint — markedets sammensætning er stort set uændret mellem halvdelene, mens `R/handel` angiveligt faldt ~0,26 R i BEGGE grupper. Kryptos trending-andel steg endda en anelse samtidig med at performance faldt, hvilket er det modsatte af hvad regime-hypotesen forudsiger. Hypotesen var tiltalende og stammede fra en gate der var valgt før nogen af disse analyser — den holder alligevel ikke.


## Modcase 1 — er gaten inert?

Nej, ikke som helhed: den blokerer 72.5% af handlerne. **Men én gren af den er det.** `volatile`-regimet — hvor `volatile_min_confidence = 0.75` skulle slippe høj-confidence-signaler igennem — ramte kun 3 af 432 handler. Den tærskel er i praksis aldrig i brug.


## Modcase 2 — kan to år overhovedet afgøre noget?

Vi har nu skåret de samme ~432 handler i fem separate analyser: confidence-validering, flip-exit out-of-sample, parret flip-exit, instrumentklasse og regime. Groft optalt er der foretaget **omkring 25 sammenligninger** på det samme datasæt.


Ved alpha 5% er sandsynligheden for MINDST ét falsk positivt fund blandt 25 uafhængige sammenligninger ca. **72%** (1 − 0,95²⁵). Med andre ord: havde vi fundet ét enkelt "signifikant" resultat undervejs, ville det mest sandsynlige være at det var tilfældet.


**Samtlige intervaller i denne analyse krydser nul.**


> **Stikprøven er for lille til at afgøre noget om denne strategi, og yderligere opdelinger af de samme to år vil ikke ændre det. Næste skridt skal være mere data, ikke flere spørgsmål.**

Det er ikke "endnu et ikke påvist". Det er en konklusion om metoden: hver ny opdeling gør stikprøven pr. gruppe mindre og multipliciteten værre, og begge dele trækker i den forkerte retning.

Bemærk samtidig hvad de ~25 chancer IKKE producerede: næsten ingen falske positive. Det er svag evidens for at der ikke er nogen stor effekt at finde — ikke bare fravær af bevis.
