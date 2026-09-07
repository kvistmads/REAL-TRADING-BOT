# Fase 2b — porteføljen med ét instrument pr. aktiv

**Kørsel:** syv TSMOM-kurver kombineret til én portefølje, invers volatilitet,
månedlig rebalancering. `XAU` fjernet som duplikat af `GC`.
**Periode:** 1993-04-01 → 2026-09-02
**Status:** research. Ingen ændring af live handelsadfærd, `config.yaml` urørt.

---

## Svaret: rettelsen gjorde tallene en anelse dårligere, og det er pointen

```
FASE 2b  portefølje alle_syv  1993-2026  invers vol (12m bagud), månedlig rebalancering
instrument    CAGR_%  maxDD_%  Sharpe  flat_år  i_mkt_%  n_pos  B&H_CAGR_%  B&H_maxDD_%  afk_bidrag_%  risk_bidrag_%
SPY            10.53    -33.7    0.76      4.6     81.7     11       10.81        -55.2          42.2           39.6
GC             10.59    -33.3    0.71      8.9     76.3     15       11.99        -44.4          23.9           15.0
QQQ             9.39    -41.0    0.56     10.8     79.2     11        8.28        -81.2          19.7           17.0
BTC            34.37    -63.3    0.83      2.3     65.8      4       34.95        -76.6           9.8            4.6
ETH            21.96    -62.2    0.64      2.5     53.2      7       30.66        -79.3           6.5            3.8
6E              0.10    -42.1    0.05     18.3     55.8     23        0.98        -39.8          -1.0           10.3
6B             -0.13    -33.7    0.01     18.8     53.7     20       -0.29        -49.2          -1.1            9.8
------------------------------------------------------------------------------------------------------------------------------
PORTEFØLJE      7.40    -19.0    0.79      3.1     67.7      —        8.05        -46.7         100.0          100.0
  instrument-rækkerne er STANDALONE TSMOM; bidragskolonnerne er instrumentets andel i porteføljen

FASE 2b  portefølje uden_fx  1993-2026  invers vol (12m bagud), månedlig rebalancering
instrument    CAGR_%  maxDD_%  Sharpe  flat_år  i_mkt_%  n_pos  B&H_CAGR_%  B&H_maxDD_%  afk_bidrag_%  risk_bidrag_%
SPY            10.53    -33.7    0.76      4.6     81.7     11       10.81        -55.2          27.4           39.0
GC             10.59    -33.3    0.71      8.9     76.3     15       11.99        -44.4          26.2           23.6
QQQ             9.39    -41.0    0.56     10.8     79.2     11        8.28        -81.2          24.3           24.1
BTC            34.37    -63.3    0.83      2.3     65.8      4       34.95        -76.6          13.5            7.3
ETH            21.96    -62.2    0.64      2.5     53.2      7       30.66        -79.3           8.5            5.9
------------------------------------------------------------------------------------------------------------------------------
PORTEFØLJE     12.75    -25.2    0.98      3.4     78.2      —        9.06        -47.8         100.0          100.0
  instrument-rækkerne er STANDALONE TSMOM; bidragskolonnerne er instrumentets andel i porteføljen
```

| mål | fase 2 (8 instr.) | fase 2b (7 instr.) | ændring |
|---|---|---|---|
| Sharpe | 0.82 | 0.786 | -0.03 |
| CAGR_% | 7.83 | 7.4 | -0.43 |
| maxDD_% | -19.0 | -19.03 | -0.03 |
| flat_år | 3.1 | 3.1 | 0.0 |
| N_eff (ρ) | 2.86 | 2.72 | -0.14 |
| ρ_strategi | 0.257 | 0.262 | 0.005 |

**Sharpe faldt fra 0,82 til 0.79.** Det er ikke et tegn på at rettelsen
var forkert — det er et tegn på at duplikatet pyntede resultatet.

Mekanismen: med `XAU` og `GC` som to pladser fik guld **dobbelt risikobudget** under
invers volatilitetsvægtning. Guld var samtidig et af de bedste enkeltinstrumenter
(standalone Sharpe 0,71) og korrelerede kun 0,08 med aktier. At overvægte det ved et
uheld hjalp derfor porteføljen. Da duplikatet forsvandt, halveredes guldets vægt, og
porteføljen mistede eksponering mod netop den bedste diversificerende kilde.

Det ændrer ikke at rettelsen er rigtig. **Ét væddemål talt to gange er stadig ét
væddemål**, og en portefølje der ser god ud fordi den dobbelttæller en position, er
ikke god — den er forkert opgjort. En konstruktionskorrektion måles på om den er
sand, ikke på om den hjælper.

`N_eff` faldt tilsvarende fra 2,86 til 2.72. To ting trak samme
vej: N gik fra 8 til 7, og ρ̄ steg marginalt (fra 0,257 til 0.262), fordi `XAU`
korrelerede lidt lavere end gennemsnittet med alt andet end `GC`.

### Uden FX

| mål | fase 2 (6 instr.) | fase 2b (5 instr.) | ændring |
|---|---|---|---|
| Sharpe | 0.99 | 0.983 | -0.01 |
| CAGR_% | 12.18 | 12.75 | 0.57 |
| maxDD_% | -21.1 | -25.2 | -4.1 |
| N_eff (ρ) | 2.51 | 2.27 | -0.24 |

---

## DEL 1 — hvorfor `GC=F` og ikke `XAU`

Valget er truffet på **datakvalitet, ikke afkast**:

| | `GC=F` | `XAU/USD` |
|---|---|---|
| Kilde | yfinance, som resten af porteføljen | ukendt MT4-feed, ét commit på GitHub |
| Volumen | rigtig (419 nul-barer) | tick-volumen, broker-afhængig |
| Validerede år | 2000–2026 | 2004–2024 (2025 kasseret) |
| Roll-drift mod spot | målt til +0,04 pct-point/år | — |
| ATR i overlapstest | reference | afveg ~20% |

Havde valget stået på afkast, ville de to være næsten uskelnelige: standalone CAGR
10,59% mod 10,05% og maxDD −33,3% mod −32,8%. Det er netop derfor beslutningen kan
træffes rent på kilde og reproducerbarhed.

Reglen er skrevet ind i `CLAUDE.md`: **ét instrument pr. underliggende aktiv i en
portefølje. To tickere for samme ting er ikke diversificering.** Listen ligger i
`research/portfolio.DUPLICATE_UNDERLYING`.

---

## DEL 2 — hvad bidragskolonnerne viser

| instrument | afkast_bidrag_% | risiko_bidrag_% | afkast_pr_risiko |
|---|---|---|---|
| SPY | 42.2 | 39.6 | 1.07 |
| GC | 23.9 | 15.0 | 1.59 |
| QQQ | 19.7 | 17.0 | 1.16 |
| BTC | 9.8 | 4.6 | 2.13 |
| ETH | 6.5 | 3.8 | 1.71 |
| 6E | -1.0 | 10.3 | -0.1 |
| 6B | -1.1 | 9.8 | -0.11 |

`afkast_pr_risiko` er forholdet mellem de to andele. Over 1,0 betyder at
instrumentet leverer mere afkast end det bruger risiko.

**Det tal du bad om at kunne se med det samme, er FX-linjen.** `6E` og `6B` leverer
tilsammen **−2,1% af afkastet** og bruger **20.1%
af risikoen.** De er ikke bare uden bidrag; de er negative, og de fylder en femtedel
af risikobudgettet mens de gør det.

De øvrige linjer:

- **`SPY` bærer porteføljen** (42% af afkastet
  for 40% af risikoen). Det er også det
  instrument der har været med længst, så tallet er delvis en historik-effekt.
- **`GC` er den mest effektive** (24% af
  afkastet for kun 15% af risikoen) — netop
  fordi den korrelerer lavt med aktierne.
- **Krypto leverer over sin risikoandel** trods kun 9 års historik, fordi invers
  volatilitet giver den en lille vægt og afkastet er stort.

**Risikobidraget er defineret som faktisk vægt × volatilitet**, akkumuleret dag for
dag — ikke måltvægt. En plads i kontanter bærer ingen risiko, uanset hvad den blev
tildelt ved månedsskiftet.

---

## Korrelation: strategi mod aktiv

| | Gennemsnit | N_eff (ρ) | N_eff (egenværdier) |
|---|---|---|---|
| **Strategiernes** månedlige afkast | **+0.262** | **2.72** | 4.09 |
| Aktivernes månedlige afkast | +0.301 | 2.49 | 3.84 |

Konklusionen fra fase 2 står uændret efter rettelsen: **strategikorrelationerne er
ikke markant lavere end aktivkorrelationerne.** 0.262 mod 0.301.

```
    par  strategi  aktiv  forskel
SPY–QQQ      0.81   0.84    -0.03
BTC–ETH      0.63   0.72    -0.09
  6E–6B      0.67   0.65     0.02
  GC–6E      0.34   0.40    -0.06
SPY–ETH      0.42   0.40     0.02
QQQ–ETH      0.35   0.38    -0.03
 SPY–6B      0.27   0.38    -0.11
SPY–BTC      0.35   0.37    -0.02
QQQ–BTC      0.37   0.34     0.03
 SPY–6E      0.21   0.32    -0.11
  GC–6B      0.24   0.27    -0.03
 QQQ–6B      0.21   0.25    -0.04
 QQQ–6E      0.15   0.20    -0.05
 6B–ETH      0.15   0.17    -0.01
 6E–ETH      0.11   0.13    -0.02
 6B–BTC      0.13   0.13    -0.00
 6E–BTC      0.01   0.12    -0.11
 GC–BTC      0.01   0.11    -0.10
 SPY–GC      0.08   0.07     0.01
 GC–ETH     -0.10   0.07    -0.17
 QQQ–GC      0.09   0.02     0.07
```

Med `XAU` ude er det tydeligere hvor det eneste reelle fald ligger: `BTC`–`ETH`
(0,72 → 0,63). `SPY`–`QQQ` falder kun fra 0,84 til 0,81 — de to strategier går ud af
markedet næsten samtidig, fordi de reagerer på det samme signal i det samme marked.

Forudsigelsen holder fortsat: gennemsnitlig individuel Sharpe 0.51 ×
√2.72 = **0.84** forudsagt mod
**0.79** faktisk.

### Individuelle Sharpe-tal

| instrument | Sharpe |
|---|---|
| SPY | 0.76 |
| QQQ | 0.56 |
| GC | 0.71 |
| 6E | 0.05 |
| 6B | 0.01 |
| BTC | 0.83 |
| ETH | 0.64 |

Gennemsnit **0.51** over de syv, **0.70** uden FX.

---

## Konstruktion og omkostninger

- **Vægt:** invers volatilitet på 12 måneders bagudskuende daglige afkast, målt
  strengt FØR rebalanceringsdagen, annualiseret med instrumentets eget antal barer
  pr. år (krypto 365, futures ~252).
- **Pladsen holder TSMOM-positionen**, ikke aktivet. Er signalet ude, står kapitalen
  i kontanter, og kontanter forrentes ikke.
- **Ingen gearing**, og loftet levner plads til kurtagen.
- **Omkostninger:** 2.76% af startkapitalen over
  33 år, hvoraf **29%** er ren
  vægtrebalancering — omsætning ud over signalskiftene, som ville være usynlig hvis
  man kun modellerede ind- og udgange.

Uden FX stiger omkostningerne til 11.56%, hvoraf
40% er rebalancering. Årsagen er ikke flere
handler, men dyrere: krypto koster ~25 bp rundtur mod futures' 0,5–2 bp, og med
færre instrumenter får krypto en større vægt.

### Instrumenterne findes ikke lige længe

Porteføljen starter i 1993 med `SPY` alene; `QQQ` kommer i 1999, futures i 2001-02,
krypto i 2018. **Det første tiår er derfor ikke en diversificeret portefølje** — det
er `SPY` med et TSMOM-filter.

Det ses tydeligst på drawdown: porteføljens værste fald på -19.0%
indtraf **1998-08-31**, mens porteføljen bestod af `SPY` alene. Fra
2003 og frem er det værste fald
-11.9%. Hovedtallets maxDD
måler altså ikke en diversificeret portefølje.

---

## Baseline

Ligevægtet køb-og-behold af de samme syv, samme periode, én rundtur pr. instrument.
Porteføljen giver **7.40%** mod baselinens **8.05%** med
**-19.0%** mod **-46.7%** i maksimalt
fald og **3.1** mod
**6.0** år uden ny top.

Samme mønster som i fase 1, nu på porteføljeniveau: TSMOM slår ikke køb-og-behold på
afkast. Den leverer lidt mindre afkast med under det halve drawdown og den halve
ventetid.

---

## Hvad kørslen ikke viser

- **Syv instrumenter er 2.7 væddemål.** Flere uafhængige kilder
  skal komme fra markeder eller strategityper vi ikke har.
- **Kontanter forrentes ikke.** Porteføljen står ude 32%
  af tiden; ved 2-5% p.a. er det
  0.6-1.6
  pct-point om året strategien ikke får krediteret.
- **`SPY`s bidrag er delvis en historik-effekt** — den har været med i 33 år, krypto
  i 9. Bidragskolonnerne er ikke normaliseret for tid i porteføljen.
- **Vægtningen er ikke optimeret og skal ikke være det.** Invers volatilitet er valgt
  fordi den er parameterfri.

---

## Filer

- `research/portfolio.py` — motoren, `DUPLICATE_UNDERLYING`, bidragsbogholderi
- `research/run_portfolio_test.py` — kørslen og tabelformatet
- `tests/test_portfolio.py` — lookahead, gearingsloft, bidragsandele
- `research/output/portfolio_contributions.csv` — bidrag pr. instrument pr. univers
