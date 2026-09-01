# Daily Bias — valideringsrapport

**Kørt:** 2026-08-27 · **Opgave:** `PRD_DAILY_BIAS_VALIDATION.md`  
**Klassifikator:** `research/daily_bias.py` — importeret, ikke genimplementeret  
**Status:** forskning. Ingen ændringer i `strategies/`, `config.yaml`, `engine.py`, `gates/`, `data/fetcher.py` eller `data/indicators.py`.

## Konklusion

**Biasen består ikke. Strategien bør ikke bygges.**

Kriteriet i §7 krævede ≥3 procentpoint over basisraten på mindst 4 af 8 markeder med mindst 200 signaler. Resultatet er **0 af 8 markeder** — ved alle fem horisonter, begge ankre, alle tre ATR-tærskler, med og uden H/L-reparation, og med begge guldkilder.

Poolet over de 8 markeder ved N=1, anker D+1-åbning: **15.183 signaler, 49,40 % hitrate mod 49,94 % basisrate** = −0,55 procentpoint (z = −1,34). Biasen ligger på eller en anelse under markedets egen basisrate.

Tallene hviler på fire rettelser efter review (§3). Én af dem var en egentlig fejl: flade reference-barer **opdigtede** S2/S5-signaler frem for blot at forvrænge en metrik — på `GC=F` var 31,4 % af alle S2/S5 fabrikerede. De øvrige tre var en undermålt defekttælling, en ubegrundet påstand om at H/L-reparationen var konservativ, og et forkert valg af guldkilde. Ingen af dem ændrede konklusionen — men de flyttede guld fra et falsk positivt på +2,9 pp til et nul.

## 1. Regressionstjek (§5) og lookahead

Kørt først, på den fulde utrunkerede `XAU_1d_data.csv` (5.383 barer, `MIN_BREAK_ATR = 0.0`, anker D-luk, N=1) — samme konfiguration som cowork-sessionen.

| Scenarie | n forventet | n målt | Hitrate forventet | Hitrate målt | Status |
|---|---|---|---|---|---|
| S1 | 869 | 869 | 44,9 % | 45,0 % | ✅ |
| S1M | 827 | 827 | 54,2 % | 54,2 % | ✅ |
| S2 | 153 | 153 | 41,2 % | 41,2 % | ✅ |
| S5 | 158 | 158 | 45,6 % | 45,6 % | ✅ |

Samlet 2.007 signaler (forventet 2.007), 48,6 % hitrate (forventet 48,5 %), MFE/MAE = 1,00. **Alle fire signalantal rammer eksakt.** S1's hitrate afviger 0,15 pp, hvilket præcis svarer til de 3 dage der lukkede uændret; de udelades nu i både hitrate og basisrate, mens cowork-sessionen regnede basisraten som `1 − P(op)` og dermed talte uændrede dage som nedadgående.

| Lookahead-test (§8.1) | Resultat |
|---|---|
| Trunkering: klassificér bar *i* på en serie klippet af ved *i* | 400 stikprøver, **0 afvigelser** |
| Indeksering: entry `Open[i+1]`, exit `Close[i+N]` | 0 uden for serien |
| ATR-kausalitet: tærskel fra bar *i−1* | max afvigelse 0,00e+00 |

## 2. Defekttabel — alle ni serier, rå data (§ punkt 2)

Ingen resultater kan tolkes før denne tabel findes. Alt måles på **rå** data: H/L-reparationen er en analyseparameter (§3.3), ikke en egenskab ved filerne — og den udvisker netop de flade barer vi skal kunne tælle.

| Serie | Barer | Periode | High == Low | Andel | Open == Close | Andel | Median dagsrange |
|---|---|---|---|---|---|---|---|
| BTC/USDT | 3.297 | 2017-08 → 2026-08 | 0 | **0,00 %** | 0 | 0,00 % | 3,941 % |
| ETH/USDT | 3.297 | 2017-08 → 2026-08 | 0 | **0,00 %** | 2 | 0,06 % | 5,204 % |
| SOL/USDT | 2.207 | 2020-08 → 2026-08 | 0 | **0,00 %** | 4 | 0,18 % | 7,143 % |
| EUR (6E=F) | 6.551 | 2000-09 → 2026-08 | 36 | **0,55 %** | 47 | 0,72 % | 0,725 % |
| GBP (6B=F) | 6.465 | 2000-10 → 2026-08 | 38 | **0,59 %** | 61 | 0,94 % | 0,708 % |
| Guld (XAU spot) | 5.337 | 2004-06 → 2025-03 | 0 | **0,00 %** | 11 | 0,21 % | 1,276 % |
| S&P 500 (ES=F) | 6.549 | 2000-09 → 2026-08 | 0 | **0,00 %** | 71 | 1,08 % | 1,234 % |
| Nasdaq 100 (NQ=F) | 6.549 | 2000-09 → 2026-08 | 1 | **0,02 %** | 27 | 0,41 % | 1,663 % |
| Guld (GC=F) ⚠️ | 6.520 | 2000-08 → 2026-08 | 1.042 | **15,98 %** | 1.029 | 15,78 % | 0,806 % |

**Kun `GC=F` er alvorligt defekt: 1.042 barer (15,98 %) hvor High == Low** — en hel handelsdag på én eneste pris. `6E=F` og `6B=F` har reelle men små defekter (0,55 % / 0,59 %), koncentreret i 2000–2001. ES, NQ og alle tre crypto-serier er rene. **XAU-broker-filen har nul flade barer.**

Mine første tal (814 flade GC=F-barer, 12,5 %) var målt *efter* H/L-reparationen, som selv fjerner flade barer hvor Open ≠ Close. Det rå tal er 1.042 / 15,98 %.

### 2.1 Flade barer pr. år (High == Low, %)

| År | BTC | ETH | SOL | 6E | 6B | XAU | ES | NQ | GC |
|---|---|---|---|---|---|---|---|---|---|
| 2000 | — | — | — | **15,1 %** | 0,0 % | — | 0,0 % | 1,4 % | **52,4 %** |
| 2001 | — | — | — | **10,0 %** | **15,1 %** | — | 0,0 % | 0,0 % | **47,8 %** |
| 2002 | — | — | — | 0,0 % | 0,0 % | — | 0,0 % | 0,0 % | **38,0 %** |
| 2003 | — | — | — | 0,0 % | 0,0 % | — | 0,0 % | 0,0 % | **43,6 %** |
| 2004 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | **45,4 %** |
| 2005 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | **48,8 %** |
| 2006 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | **47,6 %** |
| 2007 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | **35,7 %** |
| 2008 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | **5,9 %** |
| 2009 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 2,4 % |
| 2010 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | **15,1 %** |
| 2011 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 2,8 % |
| 2012 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,4 % |
| 2013 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 1,6 % |
| 2014 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | **6,3 %** |
| 2015 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,4 % |
| 2016 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 2,4 % |
| 2017 | 0,0 % | 0,0 % | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 4,4 % |
| 2018 | 0,0 % | 0,0 % | — | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | **14,0 %** |
| 2019 | 0,0 % | 0,0 % | — | 0,0 % | 0,4 % | 0,0 % | 0,0 % | 0,0 % | **11,1 %** |
| 2020 | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,4 % | 0,0 % | 0,0 % | 0,0 % | 1,6 % |
| 2021 | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 4,4 % |
| 2022 | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,8 % | 0,0 % | 0,0 % | 0,0 % | **5,2 %** |
| 2023 | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,4 % | 0,0 % | 0,0 % | 0,0 % | **5,6 %** |
| 2024 | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | **5,2 %** |
| 2025 | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 2,4 % |
| 2026 | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,0 % | — | 0,0 % | 0,0 % | 2,5 % |

`GC=F` er ikke et gammelt-data-problem: 2000–2007 ligger på 36–52 %, 2010 på 15,1 %, 2018 på 14,0 %, og 2021–2026 stadig på 2,4–5,6 %. Der findes ingen ren delperiode at skære serien ned til. `6E=F`/`6B=F` er derimod rene fra 2002 og frem.

### 2.2 Open == Close pr. år (%)

| År | BTC | ETH | SOL | 6E | 6B | XAU | ES | NQ | GC |
|---|---|---|---|---|---|---|---|---|---|
| 2000 | — | — | — | **13,7 %** | 0,0 % | — | 0,0 % | 0,0 % | **58,3 %** |
| 2001 | — | — | — | 4,8 % | **7,8 %** | — | 1,2 % | 0,4 % | **51,4 %** |
| 2002 | — | — | — | 0,0 % | 1,9 % | — | 0,8 % | 0,4 % | **42,0 %** |
| 2003 | — | — | — | 0,8 % | 1,2 % | — | 2,7 % | 1,2 % | **29,2 %** |
| 2004 | — | — | — | 0,8 % | 0,4 % | 1,4 % | 2,3 % | 2,3 % | **22,9 %** |
| 2005 | — | — | — | 0,4 % | 0,4 % | 1,6 % | 1,6 % | 1,6 % | **33,1 %** |
| 2006 | — | — | — | 0,8 % | 0,4 % | 0,4 % | 1,2 % | 0,4 % | **30,0 %** |
| 2007 | — | — | — | 0,0 % | 1,2 % | 0,8 % | 1,6 % | 0,4 % | **27,0 %** |
| 2008 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,4 % | 0,8 % | 3,6 % |
| 2009 | — | — | — | 0,4 % | 0,0 % | 0,4 % | 0,4 % | 1,2 % | **12,0 %** |
| 2010 | — | — | — | 0,0 % | 0,0 % | 0,0 % | 0,8 % | 0,8 % | **56,0 %** |
| 2011 | — | — | — | 0,8 % | 0,8 % | 0,0 % | 0,8 % | 0,4 % | 1,6 % |
| 2012 | — | — | — | 0,4 % | 0,0 % | 0,0 % | 2,0 % | 0,4 % | 0,8 % |
| 2013 | — | — | — | 0,4 % | 1,2 % | 0,0 % | 1,6 % | 0,0 % | 2,4 % |
| 2014 | — | — | — | 0,8 % | 0,4 % | 0,4 % | 2,0 % | 0,0 % | **7,1 %** |
| 2015 | — | — | — | 0,4 % | 0,8 % | 0,0 % | 2,0 % | 0,0 % | 0,8 % |
| 2016 | — | — | — | 0,4 % | 0,4 % | 0,0 % | 1,2 % | 0,0 % | 2,4 % |
| 2017 | 0,0 % | 0,0 % | — | 0,0 % | 0,4 % | 0,0 % | 2,0 % | 0,0 % | **6,4 %** |
| 2018 | 0,0 % | 0,0 % | — | 0,0 % | 0,8 % | 0,0 % | 0,8 % | 0,4 % | **16,4 %** |
| 2019 | 0,0 % | 0,5 % | — | 0,4 % | 1,2 % | 0,0 % | 0,4 % | 0,0 % | **13,1 %** |
| 2020 | 0,0 % | 0,0 % | 0,0 % | 0,8 % | 1,6 % | 0,0 % | 0,4 % | 0,0 % | 2,4 % |
| 2021 | 0,0 % | 0,0 % | 0,0 % | 0,8 % | 0,0 % | 0,0 % | 0,4 % | 0,0 % | **5,6 %** |
| 2022 | 0,0 % | 0,0 % | 0,3 % | 0,4 % | 1,2 % | 0,0 % | 0,4 % | 0,0 % | **5,2 %** |
| 2023 | 0,0 % | 0,0 % | 0,3 % | 0,0 % | 1,6 % | 0,0 % | 0,0 % | 0,0 % | **8,0 %** |
| 2024 | 0,0 % | 0,0 % | 0,0 % | 0,0 % | 0,4 % | 0,0 % | 0,8 % | 0,0 % | **7,5 %** |
| 2025 | 0,0 % | 0,0 % | 0,3 % | 0,8 % | 1,2 % | 0,0 % | 0,0 % | 0,0 % | 2,4 % |
| 2026 | 0,0 % | 0,0 % | 0,4 % | 0,6 % | 0,0 % | — | 0,6 % | 0,0 % | 4,3 % |

`Open == Close` er en anden defekt end flade barer: den ødelægger ikke klassifikationen, men gør dagens afkast eksakt 0 ved anker D+1-åbning. Uafgjorte udfald bærer ingen retningsinformation og udelades derfor i **både** hitrate og basisrate — ellers fortyndes kun den ene side. `GC=F` topper igen (15,78 %, med 56,0 % i 2010).

## 3. Fire rettelser efter review

### 3.1 Flade barer opdigter signaler — det er et klassifikationsproblem

Har reference-baren `High == Low`, så er `prior_high == prior_low == P`. Enhver efterfølgende bar der **straddler P** har både `swept_high` og `swept_low` sande. Luk-tjekket kører først (og skal gøre det, jf. PRD §2), så:

```
prior_high == prior_low == P
luk > P  →  S2  (LONG)
luk < P  →  S5  (SHORT)
```

Signalet reduceres til "lukkede i dag over eller under gårsdagens ene pris" — pr. konstruktion, uanset hvad markedet gjorde. At udelade uafgjorte udfald i metrikken fjerner ikke de opdigtede signaler, kun deres bidrag til tællingen. Det var min fejl i første kørsel: jeg behandlede et klassifikationsproblem som et metrikproblem.

Kontamineringen har præcis den asymmetriske signatur mekanismen forudsiger — S2/S5 rammes hårdt, S1/S1M næsten ikke:

| Scenarie | Signaler i alt (`GC=F`) | Heraf fra flad reference | Andel |
|---|---|---|---|
| S1 | 594 | 3 | 0,5 % |
| S1M | 552 | 0 | 0,0 % |
| S2 | 295 | 96 | **32,5 %** |
| S5 | 285 | 86 | **30,2 %** |
| S3 | 148 | 1 | 0,7 % |
| S4 | 999 | 35 | 3,5 % |
| BO_UP | 2.004 | 440 | **22,0 %** |
| BO_DOWN | 1.642 | 381 | **23,2 %** |
| **S2 + S5 samlet** | 580 | 182 | **31,4 %** |

**31,4 % af alle S2/S5-signaler på `GC=F` er fabrikerede.** BO_UP/BO_DOWN er 22–23 % kontamineret (en bar der ligger helt over eller under P falder igennem til breakout-kategorien), mens S1 er 0,5 % og S1M 0,0 %.

**Rettelse:** ethvert signal hvis *reference*-bar er degenereret udelades nu — og de samme dage udelades af basisraten, så de to sider måles på identisk univers (`bias_engine.degenerate_reference`). Primær definition er eksakt nulbredde; robusthedstabellen i §6 kører desuden et gulv på 10 % af seriens median-range.

| Serie | Degenererede reference-barer | Andel af barer | Signaler fjernet |
|---|---|---|---|
| BTC/USDT | 0 | 0,00 % | 0 |
| ETH/USDT | 0 | 0,00 % | 0 |
| SOL/USDT | 0 | 0,00 % | 0 |
| EUR (6E=F) | 36 | 0,55 % | 7 |
| GBP (6B=F) | 38 | 0,59 % | 6 |
| Guld (XAU spot) | 0 | 0,00 % | 0 |
| S&P 500 (ES=F) | 0 | 0,00 % | 0 |
| Nasdaq 100 (NQ=F) | 1 | 0,02 % | 0 |
| Guld (GC=F) | 1.042 | 15,98 % | 185 |

Filteret rører kun de defekte serier: 185 signaler på `GC=F`, 7 på `6E=F`, 6 på `6B=F`, 0 på resten. Regressionstjekket i §1 er derfor uændret.

### 3.2 Alle otte markeder er tjekket, ikke kun guld

Defekttabellen i §2 dækker alle ni serier pr. marked og pr. år. Mistanken mod `6E=F` og `6B=F` var berettiget — begge har flade barer — men omfanget er lille (0,55 % / 0,59 %) og isoleret til 2000–2001. Efter 2002 er de rene.

### 3.3 H/L-reparationen er ikke entydigt konservativ — den er målt

Hver bar er **både** reference for næste dag **og** signalbar mod forrige dag. At udvide High/Low til at omslutte Open/Close gør det sværere at feje baren *som reference*, men lettere for baren *selv* at registrere et sweep. Jeg kaldte den konservativ uden at måle det. Her er begge stillinger, N=1, anker D+1-åbning, poolet over de 8 markeder:

| Scenarie | n rå | n repareret | Δn | Hitrate rå | Hitrate repareret | Δ |
|---|---|---|---|---|---|---|
| S1 | 6.495 | 6.501 | +6 | 48,05 % | 48,01 % | −0,04 pp |
| S1M | 6.228 | 6.234 | +6 | 51,40 % | 51,38 % | −0,02 pp |
| S2 | 1.204 | 1.203 | −1 | 50,00 % | 50,04 % | +0,04 pp |
| S5 | 1.256 | 1.255 | −1 | 45,86 % | 45,98 % | +0,12 pp |
| **Alle** | 15.183 | 15.193 | +10 | 49,40 % | 49,38 % | −0,01 pp |

**Reparationen er et nul.** Den flytter signalantallet 0,1 % og hitraten højst 0,12 pp på noget scenarie. Den trækker altså hverken den ene eller den anden vej i praksis — men det vides nu, i stedet for at være antaget. Rådata er primær; filerne på disk er rå.

### 3.4 Guldkilden afgøres af flad-bar-tællingen, ikke af PRD §3

PRD §3 sagde "brug `GC=F` hvis afvigelsen er væsentlig", men det var skrevet med **pris**-nøjagtighed i tankerne. Afvigelsen viste sig at være i **range**, og range-geometri er det eneste denne strategi bruger. Så kriteriet skal være hvilken kilde der har den brugbare range-geometri:

| | XAU spot (broker-fil) | `GC=F` (yfinance) |
|---|---|---|
| Flade barer (High == Low) | **0** | **1.042** |
| Andel | **0,00 %** | **15,98 %** |
| Signaler der må kasseres | 0 | 185 |
| Fabrikerede S2/S5 | 0,0 % | 31,4 % |
| Barer | 5.337 | 6.520 |
| Median dagsrange (alle) | 16,84 USD | 11,30 USD |
| Median dagsrange (kun ikke-flade) | 17,76 USD | 12,70 USD |
| Handlbar andel af dage | 37,4 % | 28,1 % |

Priserne er enige — median absolut close-afvigelse 1,74 USD (0,145 %), korrelation 0,999958, ingen datoforskydning (median-afvigelse 1,74 USD ved 0 dage mod 6,97 og 6,41 ved ±1 dag). Men `GC=F`'s dagsrange er systematisk smallere, også når man udelader de flade barer, og **det er `GC=F` der har 1.042 flade barer, ikke broker-filen.**

**Beslutning: XAU spot er primær guldkilde.** Den smallere, defekte kilde er den dårligere til dette formål. `GC=F` føres med i CSV'en som kontrol, og de to er enige om svaret (N=1: −0,57 pp mod −0,68 pp), så valget ændrer ikke konklusionen — kun kvaliteten af det grundlag den hviler på.

Broker-filen trunkeres ved **2025-03-31**: derefter har den huller på 11, 27, 18, 81 dage. Den trunkerede serie har 5.337 barer, største hul 5 dage og nul flade barer.

### 3.5 Kontraktrulning (§8.4)

| Marked | Signaler | Berørt af rul-gap | Hitrate alle | Hitrate uden rul |
|---|---|---|---|---|
| EUR (6E=F) | 2.460 | 268 (10,9 %) | 49,1 % | 49,3 % |
| GBP (6B=F) | 2.323 | 224 (9,6 %) | 49,3 % | 49,6 % |
| Guld (GC=F) | 1.447 | 92 (6,4 %) | 49,3 % | 49,6 % |
| Nasdaq 100 (NQ=F) | 2.560 | 485 (18,9 %) | 49,8 % | 49,6 % |
| S&P 500 (ES=F) | 2.558 | 422 (16,5 %) | 49,2 % | 49,4 % |

Yahoos `=F`-serier er kontinuerte front-month-serier uden bagudjustering, så hver rulning efterlader et kunstigt gap. De flytter hitraten højst 0,5 pp.

## 4. Resultater pr. marked

Primær konfiguration: anker **dag D+1's åbning**, `MIN_BREAK_ATR = 0.0`, rå data uden H/L-reparation, degenererede reference-barer udeladt, alle signaler. Celle = hitrate / forskel til basisrate i pp / z-score.

### BTC/USDT

| Scenarie | Retning | n (N=1) | N=1 | N=2 | N=3 | N=4 | N=5 |
|---|---|---|---|---|---|---|---|
| S1 | SHORT | 511 | 51,9 % / +3,0 / +1,37 | 50,4 % / +3,3 / +1,50 | 49,0 % / +2,3 / +1,02 | 47,6 % / +0,5 / +0,24 | 45,7 % / −1,1 / −0,49 |
| S1M | LONG | 514 | 50,6 % / −0,6 / −0,27 | 52,7 % / −0,2 / −0,09 | 50,6 % / −2,7 / −1,20 | 48,7 % / −4,2 / −1,88 | 51,1 % / −2,2 / −0,98 |
| S2 | LONG | 101 | 44,6 % / −6,6 / −1,33 | 49,5 % / −3,4 / −0,69 | 45,5 % / −7,7 / −1,55 | 48,5 % / −4,4 / −0,88 | 43,6 % / −9,7 / −1,95 |
| S5 | SHORT | 89 | 42,7 % / −6,1 / −1,16 | 39,3 % / −7,8 / −1,47 | 38,2 % / −8,6 / −1,62 | 43,8 % / −3,3 / −0,62 | 44,9 % / −1,8 / −0,34 |
| **Alle** | — | 1.215 | 50,0 % / +0,0 / +0,02 | 50,5 % / +0,5 / +0,32 | 48,6 % / −1,4 / −1,01 | 47,9 % / −2,1 / −1,49 | 47,7 % / −2,3 / −1,61 |

Basisrate N=1: long 51,2 % / short 48,8 %. Signaler: 615 long, 600 short.

### ETH/USDT

| Scenarie | Retning | n (N=1) | N=1 | N=2 | N=3 | N=4 | N=5 |
|---|---|---|---|---|---|---|---|
| S1 | SHORT | 549 | 47,4 % / −1,6 / −0,75 | 47,9 % / −0,4 / −0,18 | 46,5 % / −1,1 / −0,51 | 45,4 % / −1,8 / −0,84 | 45,1 % / −2,7 / −1,28 |
| S1M | LONG | 534 | 48,7 % / −2,4 / −1,09 | 51,4 % / −0,3 / −0,14 | 54,2 % / +1,9 / +0,86 | 54,5 % / +1,7 / +0,81 | 52,4 % / +0,2 / +0,08 |
| S2 | LONG | 81 | 48,1 % / −2,9 / −0,52 | 53,8 % / +2,0 / +0,37 | 48,1 % / −4,2 / −0,76 | 38,3 % / −14,5 / −2,61 | 38,3 % / −13,9 / −2,51 |
| S5 | SHORT | 77 | 41,6 % / −7,4 / −1,30 | 42,1 % / −6,2 / −1,08 | 40,3 % / −7,4 / −1,30 | 35,1 % / −12,2 / −2,14 | 39,0 % / −8,9 / −1,55 |
| **Alle** | — | 1.241 | 47,6 % / −2,4 / −1,67 | 49,4 % / −0,5 / −0,39 | 49,6 % / −0,4 / −0,30 | 48,2 % / −1,8 / −1,23 | 47,4 % / −2,6 / −1,83 |

Basisrate N=1: long 51,0 % / short 49,0 %. Signaler: 615 long, 626 short.

### SOL/USDT

| Scenarie | Retning | n (N=1) | N=1 | N=2 | N=3 | N=4 | N=5 |
|---|---|---|---|---|---|---|---|
| S1 | SHORT | 375 | 53,3 % / +3,1 / +1,19 | 53,8 % / +3,8 / +1,49 | 49,6 % / +0,0 / +0,00 | 50,0 % / +0,2 / +0,06 | 50,3 % / +0,5 / +0,18 |
| S1M | LONG | 340 | 48,2 % / −1,5 / −0,56 | 50,4 % / +0,4 / +0,16 | 46,8 % / −3,6 / −1,34 | 49,4 % / −0,7 / −0,28 | 50,3 % / +0,1 / +0,03 |
| S2 | LONG | 62 | 56,5 % / +6,7 / +1,06 | 62,9 % / +12,9 / +2,03 | 48,4 % / −2,0 / −0,32 | 46,8 % / −3,4 / −0,53 | 46,8 % / −3,4 / −0,54 |
| S5 | SHORT | 58 | 55,2 % / +4,9 / +0,75 | 43,1 % / −6,9 / −1,05 | 46,6 % / −3,0 / −0,46 | 48,3 % / −1,6 / −0,24 | 53,4 % / +3,7 / +0,56 |
| **Alle** | — | 835 | 51,6 % / +1,6 / +0,93 | 52,4 % / +2,4 / +1,38 | 48,1 % / −1,8 / −1,06 | 49,4 % / −0,6 / −0,34 | 50,2 % / +0,2 / +0,14 |

Basisrate N=1: long 49,8 % / short 50,2 %. Signaler: 402 long, 433 short.

### EUR (6E=F)

| Scenarie | Retning | n (N=1) | N=1 | N=2 | N=3 | N=4 | N=5 |
|---|---|---|---|---|---|---|---|
| S1 | SHORT | 1.059 | 48,7 % / −0,9 / −0,59 | 47,1 % / −2,5 / −1,66 | 46,8 % / −2,1 / −1,38 | 47,4 % / −1,4 / −0,92 | 47,7 % / −1,3 / −0,81 |
| S1M | LONG | 1.021 | 50,4 % / +0,1 / +0,04 | 51,3 % / +0,9 / +0,60 | 53,1 % / +2,0 / +1,27 | 52,6 % / +1,4 / +0,88 | 52,1 % / +1,0 / +0,66 |
| S2 | LONG | 191 | 47,1 % / −3,3 / −0,90 | 50,0 % / −0,4 / −0,10 | 54,5 % / +3,4 / +0,93 | 55,2 % / +4,0 / +1,12 | 55,7 % / +4,7 / +1,31 |
| S5 | SHORT | 189 | 46,0 % / −3,6 / −0,99 | 47,4 % / −2,3 / −0,62 | 48,1 % / −0,8 / −0,21 | 50,0 % / +1,2 / +0,32 | 46,3 % / −2,7 / −0,74 |
| **Alle** | — | 2.460 | 49,1 % / −0,9 / −0,88 | 49,1 % / −0,9 / −0,90 | 50,1 % / +0,1 / +0,12 | 50,3 % / +0,4 / +0,36 | 50,0 % / +0,1 / +0,05 |

Basisrate N=1: long 50,4 % / short 49,6 %. Signaler: 1.212 long, 1.248 short.

### GBP (6B=F)

| Scenarie | Retning | n (N=1) | N=1 | N=2 | N=3 | N=4 | N=5 |
|---|---|---|---|---|---|---|---|
| S1 | SHORT | 969 | 50,2 % / −0,0 / −0,00 | 50,2 % / +1,5 / +0,92 | 49,9 % / +0,9 / +0,54 | 49,8 % / +1,1 / +0,69 | 50,4 % / +1,3 / +0,78 |
| S1M | LONG | 955 | 49,3 % / −0,5 / −0,32 | 48,3 % / −3,0 / −1,88 | 50,2 % / −0,7 / −0,44 | 48,6 % / −2,6 / −1,62 | 49,4 % / −1,5 / −0,94 |
| S2 | LONG | 187 | 47,1 % / −2,8 / −0,76 | 52,9 % / +1,6 / +0,44 | 52,4 % / +1,5 / +0,40 | 48,7 % / −2,6 / −0,71 | 51,3 % / +0,4 / +0,12 |
| S5 | SHORT | 212 | 47,6 % / −2,5 / −0,73 | 43,9 % / −4,8 / −1,39 | 47,7 % / −1,4 / −0,41 | 48,8 % / +0,1 / +0,03 | 52,1 % / +3,0 / +0,88 |
| **Alle** | — | 2.323 | 49,3 % / −0,7 / −0,65 | 49,0 % / −0,9 / −0,91 | 50,0 % / +0,1 / +0,06 | 49,2 % / −0,8 / −0,79 | 50,2 % / +0,2 / +0,20 |

Basisrate N=1: long 49,8 % / short 50,2 %. Signaler: 1.142 long, 1.181 short.

### Guld (XAU spot)

| Scenarie | Retning | n (N=1) | N=1 | N=2 | N=3 | N=4 | N=5 |
|---|---|---|---|---|---|---|---|
| S1 | SHORT | 861 | 45,9 % / −1,7 / −1,02 | 47,5 % / +1,2 / +0,70 | 45,4 % / −1,0 / −0,57 | 45,1 % / −0,0 / −0,02 | 44,0 % / −0,6 / −0,34 |
| S1M | LONG | 821 | 54,8 % / +2,4 / +1,39 | 54,1 % / +0,5 / +0,27 | 54,1 % / +0,5 / +0,30 | 57,0 % / +2,1 / +1,22 | 54,9 % / −0,5 / −0,27 |
| S2 | LONG | 152 | 42,1 % / −10,3 / −2,54 | 51,3 % / −2,4 / −0,58 | 54,6 % / +1,0 / +0,24 | 57,2 % / +2,4 / +0,59 | 57,9 % / +2,5 / +0,62 |
| S5 | SHORT | 157 | 47,1 % / −0,5 / −0,12 | 49,0 % / +2,7 / +0,69 | 49,0 % / +2,7 / +0,67 | 49,7 % / +4,5 / +1,14 | 48,4 % / +3,8 / +0,96 |
| **Alle** | — | 1.991 | 49,4 % / −0,6 / −0,51 | 50,7 % / +0,7 / +0,66 | 50,0 % / +0,1 / +0,07 | 51,3 % / +1,4 / +1,24 | 49,9 % / +0,0 / +0,04 |

Basisrate N=1: long 52,4 % / short 47,6 %. Signaler: 973 long, 1.018 short.

### S&P 500 (ES=F)

| Scenarie | Retning | n (N=1) | N=1 | N=2 | N=3 | N=4 | N=5 |
|---|---|---|---|---|---|---|---|
| S1 | SHORT | 1.081 | 46,3 % / +1,1 / +0,71 | 44,1 % / +0,1 / +0,07 | 43,1 % / +0,2 / +0,10 | 42,7 % / +0,5 / +0,34 | 42,8 % / +0,6 / +0,42 |
| S1M | LONG | 1.038 | 52,7 % / −2,0 / −1,31 | 57,7 % / +1,8 / +1,15 | 58,0 % / +0,9 / +0,57 | 57,0 % / −0,8 / −0,54 | 58,4 % / +0,6 / +0,41 |
| S2 | LONG | 211 | 55,0 % / +0,3 / +0,07 | 59,4 % / +3,5 / +1,02 | 62,0 % / +4,9 / +1,44 | 59,4 % / +1,6 / +0,47 | 55,2 % / −2,6 / −0,77 |
| S5 | SHORT | 228 | 41,2 % / −4,0 / −1,23 | 43,5 % / −0,5 / −0,17 | 41,7 % / −1,2 / −0,36 | 43,0 % / +0,9 / +0,27 | 42,8 % / +0,6 / +0,18 |
| **Alle** | — | 2.558 | 49,2 % / −0,7 / −0,72 | 50,9 % / +1,0 / +1,01 | 50,6 % / +0,7 / +0,73 | 49,9 % / +0,1 / +0,09 | 50,2 % / +0,4 / +0,36 |

Basisrate N=1: long 54,7 % / short 45,3 %. Signaler: 1.249 long, 1.309 short.

### Nasdaq 100 (NQ=F)

| Scenarie | Retning | n (N=1) | N=1 | N=2 | N=3 | N=4 | N=5 |
|---|---|---|---|---|---|---|---|
| S1 | SHORT | 1.090 | 45,7 % / +0,1 / +0,03 | 42,7 % / −1,3 / −0,83 | 42,0 % / −1,6 / −1,09 | 43,0 % / −0,3 / −0,20 | 42,6 % / +0,1 / +0,04 |
| S1M | LONG | 1.005 | 53,1 % / −1,2 / −0,78 | 54,8 % / −1,2 / −0,77 | 55,5 % / −0,8 / −0,54 | 54,8 % / −1,9 / −1,22 | 55,8 % / −1,7 / −1,06 |
| S2 | LONG | 219 | 57,1 % / +2,7 / +0,81 | 64,5 % / +8,5 / +2,55 | 65,0 % / +8,7 / +2,59 | 62,3 % / +5,6 / +1,68 | 57,1 % / −0,4 / −0,12 |
| S5 | SHORT | 246 | 48,0 % / +2,3 / +0,73 | 43,1 % / −0,9 / −0,29 | 42,1 % / −1,6 / −0,49 | 42,3 % / −1,1 / −0,33 | 39,3 % / −3,2 / −1,03 |
| **Alle** | — | 2.560 | 49,8 % / −0,0 / −0,00 | 49,4 % / −0,4 / −0,36 | 49,3 % / −0,4 / −0,44 | 49,2 % / −0,5 / −0,50 | 48,7 % / −1,0 / −0,98 |

Basisrate N=1: long 54,4 % / short 45,6 %. Signaler: 1.224 long, 1.336 short.

## 5. Tværgående

### 5.1 Hvor mange markeder består kriteriet?

| Scenarie | N=1 | N=2 | N=3 | N=4 | N=5 | Positivt fortegn (N=1) |
|---|---|---|---|---|---|---|
| S1 | **2** / 8 | **2** / 8 | **0** / 8 | **0** / 8 | **0** / 8 | 4 / 8 |
| S1M | **0** / 8 | **0** / 8 | **0** / 8 | **0** / 8 | **0** / 8 | 2 / 8 |
| S2 | **0** / 8 | **2** / 8 | **2** / 8 | **1** / 8 | **0** / 8 | 3 / 8 |
| S5 | **0** / 8 | **0** / 8 | **0** / 8 | **0** / 8 | **0** / 8 | 2 / 8 |
| **Alle handlbare** | **0** / 8 | **0** / 8 | **0** / 8 | **0** / 8 | **0** / 8 | 2 / 8 |

Ingen kombination når 4 af 8. De enkelte 1'ere og 2'ere er forskellige markeder fra horisont til horisont — kriteriets fjerde led om konsistent fortegn er ikke opfyldt.

### 5.2 Poolet på tværs af alle 8 markeder (N=1, D+1 åbning)

| Scenarie | Retning | n | Hitrate | Basisrate | Forskel | z | p |
|---|---|---|---|---|---|---|---|
| S1 | SHORT | 6.495 | 48,05 % | 47,96 % | +0,09 pp | +0,15 | 0,884 |
| S1M | LONG | 6.228 | 51,40 % | 52,02 % | −0,62 pp | −0,98 | 0,328 |
| S2 | LONG | 1.204 | 50,00 % | 52,11 % | −2,11 pp | −1,47 | 0,142 |
| S5 | SHORT | 1.256 | 45,86 % | 47,82 % | −1,96 pp | −1,39 | 0,163 |
| **Alle handlbare** | — | 15.183 | 49,40 % | 49,94 % | −0,55 pp | −1,34 | 0,179 |

Intet scenarie er signifikant i biasens favør.

### 5.3 Er de positive celler flere end tilfældet ville give?

| Mål | Målt | Ved ren støj |
|---|---|---|
| Celler testet (n ≥ 200) | 210 | — |
| ≥ +3 pp | 18 | ~symmetrisk |
| ≤ −3 pp | 11 | — |
| \|z\| > 1,96 | 5 (2,4 %) | ~10 (5,0 %) |
| heraf positive / negative | 4 / 1 | ~lige mange |
| Middel z | −0,061 | 0,000 |

Andelen af "signifikante" celler er 2,4 % — på eller under de 5 % ren tilfældighed ville give, med næsten symmetriske haler. Der er intet signal at grave frem, heller ikke i delmængderne.

## 6. Robusthed

Hver akse køres for sig; ingen af dem ændrer konklusionen.

| Akse | Variant | Signaler (N=1) | Poolet hitrate | Forskel | z | Består |
|---|---|---|---|---|---|---|
| ATR-tærskel | 0,00 *(primær)* | 15.183 | 49,40 % | −0,55 pp | −1,34 | **0 / 8** |
|  | 0,05 | 13.810 | 49,20 % | −0,78 pp | −1,83 | **0 / 8** |
|  | 0,10 | 11.909 | 49,22 % | −0,82 pp | −1,79 | **0 / 8** |
| H/L-reparation | fra *(primær)* | 15.183 | 49,40 % | −0,55 pp | −1,34 | **0 / 8** |
|  | til | 15.193 | 49,38 % | −0,56 pp | −1,38 | **0 / 8** |
| Reference-gulv | eksakt flad *(primær)* | 15.183 | 49,40 % | −0,55 pp | −1,34 | **0 / 8** |
|  | 10 % af median-range | 15.177 | 49,40 % | −0,54 pp | −1,33 | **0 / 8** |
| Anker | D+1 åbning *(primær)* | 15.183 | 49,40 % | −0,55 pp | −1,34 | **0 / 8** |
|  | D luk | 15.157 | 49,57 % | −0,37 pp | −0,90 | **0 / 8** |

### 6.1 Overlappende vs. ikke-overlappende vinduer

Ved N>1 overlapper nabodages signaler. Den ikke-overlappende delmængde vælges grådigt over **alle** handlbare signaler i datorækkefølge (næste signal mindst N barer efter det forrige), så uafhængigheden gælder både inden for og på tværs af scenarier.

| Horisont | Alle: n | Forskel | z | Ikke-overlappende: n | Forskel | z |
|---|---|---|---|---|---|---|
| N=1 | 15.183 | −0,55 pp | −1,34 | 15.183 | −0,55 pp | −1,34 |
| N=2 | 15.208 | +0,04 pp | +0,09 | 10.938 | +0,17 pp | +0,36 |
| N=3 | 15.215 | −0,16 pp | −0,40 | 8.623 | −0,50 pp | −0,93 |
| N=4 | 15.212 | −0,30 pp | −0,73 | 7.087 | −0,72 pp | −1,21 |
| N=5 | 15.212 | −0,44 pp | −1,08 | 6.041 | −0,06 pp | −0,10 |

### 6.2 Natte-gap (forskellen mellem de to ankre)

| Marked | Middel | Middel \|gap\| | Std | p95 \|gap\| |
|---|---|---|---|---|
| BTC/USDT | −0,001 % | 0,011 % | 0,056 % | 0,038 % |
| ETH/USDT | +0,001 % | 0,015 % | 0,073 % | 0,050 % |
| SOL/USDT | +0,000 % | 0,021 % | 0,055 % | 0,088 % |
| EUR (6E=F) | +0,000 % | 0,110 % | 0,231 % | 0,364 % |
| GBP (6B=F) | +0,003 % | 0,103 % | 0,193 % | 0,337 % |
| Guld (XAU spot) | +0,020 % | 0,099 % | 0,195 % | 0,357 % |
| S&P 500 (ES=F) | −0,009 % | 0,105 % | 0,271 % | 0,391 % |
| Nasdaq 100 (NQ=F) | +0,004 % | 0,147 % | 0,332 % | 0,564 % |

**For crypto findes natte-gappet reelt ikke** (0,01–0,02 % i middel absolut): Binances dagsbar åbner hvor den forrige lukkede, så de to ankre er samme pris.

## 7. Scenariefrekvenser (§6)

Andel af klassificerede dage efter reference-filteret, primær konfiguration.

| Marked | S1 | S1M | S2 | S5 | S3 | S4 | BO_UP | BO_DOWN | Handlbar |
|---|---|---|---|---|---|---|---|---|---|
| BTC/USDT | 15,5 % | 15,6 % | 3,1 % | 2,7 % | 4,6 % | 20,8 % | 21,1 % | 16,5 % | **36,9 %** |
| ETH/USDT | 16,7 % | 16,2 % | 2,5 % | 2,3 % | 3,9 % | 20,4 % | 20,7 % | 17,3 % | **37,7 %** |
| SOL/USDT | 17,1 % | 15,5 % | 2,8 % | 2,6 % | 3,8 % | 17,9 % | 20,4 % | 19,9 % | **38,0 %** |
| EUR (6E=F) | 16,3 % | 15,7 % | 2,9 % | 2,9 % | 4,9 % | 13,9 % | 21,9 % | 21,5 % | **37,9 %** |
| GBP (6B=F) | 15,2 % | 15,0 % | 2,9 % | 3,4 % | 4,7 % | 14,0 % | 23,2 % | 21,6 % | **36,5 %** |
| Guld (XAU spot) | 16,2 % | 15,4 % | 2,8 % | 2,9 % | 4,2 % | 16,7 % | 23,6 % | 18,1 % | **37,4 %** |
| S&P 500 (ES=F) | 16,6 % | 16,1 % | 3,3 % | 3,5 % | 5,3 % | 12,6 % | 25,7 % | 16,9 % | **39,4 %** |
| Nasdaq 100 (NQ=F) | 16,7 % | 15,4 % | 3,4 % | 3,8 % | 5,4 % | 11,8 % | 26,1 % | 17,5 % | **39,3 %** |
| **Gennemsnit** | **16,3 %** | **15,6 %** | **3,0 %** | **3,0 %** | **4,6 %** | **16,0 %** | **22,8 %** | **18,7 %** | **37,9 %** |

- **S3** og **S4** er per definition ingen-handel og udgør tilsammen ~20 % af dagene.
- **BO_UP / BO_DOWN** er deaktiveret via flag, men er tilsammen **~43 % af alle dage** — langt den største kategori.
- **S1M** (tilføjelsen der ikke er i videoen) bidrager med ~15 % af dagene, altså knap 40 % af alle handlbare signaler.

### 7.1 Hvad ville de deaktiverede breakouts have gjort?

Beskrivende, da §6 beder om frekvensen — **ikke en del af kriteriet**. Kørt på det filtrerede univers; ufiltreret ville tallet delvist måle `GC=F`-defekten.

| Marked | BO_UP n | Hitrate | Forskel | BO_DOWN n | Hitrate | Forskel |
|---|---|---|---|---|---|---|
| BTC/USDT | 695 | 47,2 % | −4,0 pp | 545 | 43,9 % | −5,0 pp |
| ETH/USDT | 683 | 45,2 % | −5,8 pp | 570 | 44,0 % | −4,9 pp |
| SOL/USDT | 450 | 50,2 % | +0,5 pp | 439 | 48,5 % | −1,7 pp |
| EUR (6E=F) | 1.412 | 46,6 % | −3,8 pp | 1.384 | 48,4 % | −1,2 pp |
| GBP (6B=F) | 1.484 | 49,3 % | −0,6 pp | 1.375 | 51,3 % | +1,2 pp |
| Guld (XAU spot) | 1.259 | 49,4 % | −3,0 pp | 964 | 45,5 % | −2,1 pp |
| S&P 500 (ES=F) | 1.659 | 55,7 % | +1,0 pp | 1.094 | 42,3 % | −3,0 pp |
| Nasdaq 100 (NQ=F) | 1.698 | 55,4 % | +1,1 pp | 1.141 | 44,8 % | −0,9 pp |
| **Poolet BO_UP** | 9.340 | 50,74 % | **−1,40 pp (z = −2,70)** | | | |
| **Poolet BO_DOWN** | 7.512 | 46,49 % | **−1,67 pp (z = −2,89)** | | | |

Studiets statistisk stærkeste fund — **og det peger den forkerte vej**. At følge et dagligt breakout er signifikant dårligere end basisraten. Fundet overlever reference-filteret (det var 22–23 % kontamineret på `GC=F` før). Se §9.

## 8. Succeskriteriet, punkt for punkt

| Krav (§7, fastlagt før kørslen) | Resultat | Opfyldt |
|---|---|---|
| Hitrate slår basisraten med ≥3 pp | Bedste marked: SOL/USDT **+2,39 pp** (N=2). Poolet: **−0,55 pp** | ❌ |
| på mindst 4 af 8 markeder | **0 af 8** ved alle horisonter, ankre, tærskler, reparationsstillinger og guldkilder | ❌ |
| mindst 200 signaler pr. marked | Opfyldt — 835–2.560 pr. marked | ✅ |
| konsistent fortegn | 2 af 8 positive ved N=1; fortegnet vender mellem nabohorisonter | ❌ |

**Kriteriet er ikke justeret efter at have set tallene.** Højeste enkeltmåling på markedsniveau er 52,4 % (SOL/USDT, N=2) mod en basisrate på 50,0 %.

## 9. Hypoteser til en eventuel næste test — ikke konklusioner

1. **Breakouts fader.** BO_UP (−1,40 pp, z = −2,70) og BO_DOWN (−1,67 pp, z = −2,89) rammer begge signifikant *under* basisraten over 16.852 observationer, og fundet overlever reference-filteret. Den omvendte regel — fade et dagligt breakout — er det eneste i datasættet med statistisk substans. Bemærk at ~43 % af alle dage falder i kategorien: det er en helt anden strategi end den validerede, og den kræver sin egen forhåndsregistrerede test.

2. **S2 på Nasdaq ved N=2–3.** Den stærkest udseende enkeltcelle, og den overlever uafhængighedskorrektionen. Men den forsvinder ved N=1 og N=5, findes ikke på S&P 500 og vender fortegn på BTC. Sammenholdt med §5.3 er den efter al sandsynlighed støj.

3. **Guldets datakilde bør afklares før guld undersøges videre.** Ingen af de to nuværende kilder er gode: `GC=F` har 16 % flade barer, og broker-filen har ukendt herkomst og en ødelagt hale. De er enige om svaret her, men et fremtidigt studie bør starte med at skaffe en verificeret guldserie.

## 10. Reproduktion

```bash
.venv/bin/python research/fetch_daily.py                        # raa data -> data/historical/
PYTHONPATH=. .venv/bin/python research/run_bias_validation.py   # -> bias_validation.csv
PYTHONPATH=. .venv/bin/python research/diagnostics.py           # -> _diagnostics.json
PYTHONPATH=. .venv/bin/python research/build_report.py          # -> denne rapport
```

| Fil | Indhold |
|---|---|
| `bias_validation.md` | denne rapport |
| `bias_validation.csv` | rå resultater — én række pr. (marked, scenarie, horisont, anker, tærskel, reparation, reference-gulv, overlap) |
| `bias_scenario_frequency.csv` | scenariefrekvenser pr. marked og konfiguration |
| `_diagnostics.json` | defekttabel, kontaminering, guldkilder, reparationseffekt, rulning |
| `_meta.json`, `data_provenance.json` | datagrundlag og hentemetadata |


CSV-akser: `config` ∈ {primary, atr_005, atr_010, repaired, ref_floor_010} × `anchor` ∈ {d1_open, d_close} × `horizon` 1–5 × `overlap` ∈ {all, non_overlapping} × `scenario` ∈ {S1, S1M, S2, S5, ALL}. Guld findes som både `Guld (XAU spot)` (primær) og `Guld (GC=F)` (kontrol); `dataset=regression` er §1's utrunkerede XAU-serie.


---

*Rapporten stopper her. Strategien er ikke bygget, jf. PRD §9.*
