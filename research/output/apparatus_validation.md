# Fase 1 — kan apparatet finde en edge der beviseligt findes?

**Kørsel:** time-series momentum, 12 måneders lookback, rebalancering den 1.
**Periode:** 1994-02-01 → 2026-09-02
**Status:** research. Ingen ændring af live handelsadfærd, `config.yaml` urørt.

---

## Svaret

**Ja.** Alle tre præregistrerede krav holder, og de holder netop dér hvor effekten
er bedst dokumenteret: `SPY` og `GC=F` består begge alle tre krav.

```
FASE 1  time-series momentum (12m, reb. d. 1)  1994-02-01 → 2026-09-02
instrument   n_pos  CAGR_%  maxDD_%  Sharpe  flat_år  i_mkt_% |   B&H_CAGR_%  B&H_maxDD_%
SPY             11   10.53    -33.7    0.76      4.6     81.7 |        10.81        -55.2
QQQ             11    9.39    -41.0    0.56     10.8     79.2 |         8.28        -81.2
GC              15   10.59    -33.3    0.71      8.9     76.3 |        11.99        -44.4
XAU             15   10.05    -32.8    0.70      8.9     70.6 |        11.46        -44.6
6E              23    0.10    -42.1    0.05     18.3     55.8 |         0.98        -39.8
6B              20   -0.13    -33.7    0.01     18.8     53.7 |        -0.29        -49.2
BTC              4   34.37    -63.3    0.83      2.3     65.8 |        34.95        -76.6
ETH              7   21.96    -62.2    0.64      2.5     53.2 |        30.66        -79.3
```

| Krav | Tærskel | Resultat | Instrumenter |
|---|---|---|---|
| 1. Positivt netto-afkast | ≥4 af 8 | **7/8** | SPY, QQQ, GC, XAU, 6E, BTC, ETH |
| 2. Materielt lavere maxDD end B&H | ≥4 af 8 | **6/8** | SPY, QQQ, GC, XAU, 6B, ETH |
| 3. Positivt afkast i ≥3 af 4 delperioder | ≥4 af 8 | **5/8** | SPY, QQQ, GC, XAU, BTC |

Krav 2 var det vigtigste, og det er dét der falder tydeligst ud. Litteraturens
hovedfund om TSMOM er ikke at den slår buy-and-hold på afkast — det er at den
fanger det meste af afkastet med markant mindre drawdown. Det er præcis mønsteret:
`SPY` giver 10,53% mod buy-and-holds 10,81% (altså 97% af afkastet) med et maksimalt
tab på 33,7% mod 55,2%. `QQQ` giver mere afkast end buy-and-hold med halvt så dybt
et fald.

**Hvad det betyder for de sidste ugers arbejde:** apparatet kan genfinde en kendt
effekt. "Ikke påvist" på `trend_momentum` og regime-gaten var altså udsagn om de
strategier, ikke om målingen. Tallene derfra står ved magt.

---

## Definitioner låst FØR kørsel

Disse tal blev skrevet ind i `run_tsmom_test.py` før nogen resultater var set:

- **"Materielt lavere drawdown"** = mindst **20% relativt** lavere end buy-and-hold.
  Uden et tal kan kriteriet bøjes bagefter. −33,7% mod −55,2% er 39% relativt lavere
  og tæller; −50% mod −55% gør ikke.
- **Krav 3** læses som "mindst 3 af 4 delperioder med **positivt** afkast". Den rene
  ordlyd ("samme fortegn") ville også være opfyldt af fire negative delperioder,
  hvilket ikke kan være meningen med et succeskriterium. Begge tællinger står i
  tabellen nedenfor; bedømmelsen bruger den strenge.
- **Bedømmelsen sker på reglen** — 12 måneder, rebalancering den 1. Lookback 3/6/9 og
  rebalancering den 15. er robusthedstjek og indgår ikke. Der vælges ingen vinder.
- **Drawdown måles på daglig mark-to-market** for begge sider. Målte man strategiens
  drawdown ved exit og buy-and-holds dagligt, ville dyk inde i en position være
  usynlige, og krav 2 ville være rigget til at bestå.

---

## Konventioner — så tallene kan læses rigtigt om et halvt år

**Aktier = totalafkast. Futures og FX = kurs. Kontanter forrentes ikke.**

| Instrument | Kilde | Ejerskab | Afkastgrundlag |
|---|---|---|---|
| SPY | S&P 500 ETF | ejet | totalafkast |
| QQQ | Nasdaq 100 ETF | ejet | totalafkast |
| GC | COMEX guld-futures (GC=F) | derivat | kurs |
| XAU | Guld spot (XAU/USD, lang serie) | derivat | kurs |
| 6E | EUR/USD-futures (6E=F) | derivat | kurs |
| 6B | GBP/USD-futures (6B=F) | derivat | kurs |
| BTC | Bitcoin (Binance spot) | ejet | kurs |
| ETH | Ether (Binance spot) | ejet | kurs |

### Finansiering modelleres ikke — her holder antagelsen ikke

Omkostningsmodellen opkræver spread, slippage og kurtage pr. rundtur. Den modellerer
hverken futures-roll eller swap. Ved fire døgns hold var det uden betydning; ved
gennemsnitligt 8-20 måneders hold er det ikke.

- **`ejet`** (BTC, ETH, SPY, QQQ): spot-aktivet ejes, ingen finansiering løber på.
  Tallene er komplette på dette punkt.
- **`derivat`** (GC, 6E, 6B og XAU-spot, der i praksis er et CFD/swap-produkt): roll
  eller swap ville løbe på over en holdeperiode på måneder. **Det gør det ikke i
  disse tal.** Det er en kendt mangel, ikke en antagelse om at den er nul.

### Er GC=F roll-justeret? Undersøgt, ikke antaget

Ja — eller i det mindste roll-neutral. En splejset front-month-serie ville hoppe op
ved hver rulning med carry-spreadet (guld er næsten altid i contango) og dermed
akkumulere et kunstigt merafkast mod spot.

Målt mod XAU-spot over 5.185 fælles dage (2004-06 → 2025-02):

| Mål | Resultat |
|---|---|
| Middel-difference GC−XAU på rulledage | +0,008% |
| Middel-difference GC−XAU på andre dage | −0,001% |
| Akkumuleret GC=F | +595,5% (CAGR 9,82%) |
| Akkumuleret XAU-spot | +590,9% (CAGR 9,78%) |
| **Årlig drift GC−XAU** | **+0,04 pct-point/år** |

En naivt splejset serie i contango ville have drevet flere procentpoint om året fra
spot. 0,04 er ikke til at skelne fra nul. **GC=F markeres derfor ikke som upålidelig
til lange hold** — og guld-resultatet bæres uafhængigt af begge serier, der giver
næsten samme svar (CAGR 10,59% mod 10,05%, maxDD −33,3% mod −32,8%). At to
uafhængigt hentede guldserier lander samme sted er selvstændig bekræftelse.

### Kontanter forrentes ikke

> Kontanter forrentes ikke i denne kørsel. Det underdriver TSMOM's afkast med
> omtrent renteniveauet ganget med andelen af tid uden for markedet. Testen er
> dermed konservativ over for TSMOM.

Konkret: `SPY` står ude 18,3% af tiden, `6E` 44,2%. Ved 2-5% p.a. svarer det til
0,4-0,9 pct-point om året for `SPY` og 0,9-2,2 for `6E`, som strategien ikke får
krediteret. Det er ikke modelleret, fordi det ville kræve en historisk renteserie —
en ekstra datakilde i en test hvis eneste formål er at validere apparatet. En
konservativ skævhed vi kender retningen på er bedre end en ekstra afhængighed.

### Buy-and-hold betaler også

Baselinen er ikke gratis: **én rundtur over hele perioden** (køb i starten, sælg i
slutningen), med samme omkostningsmodel som strategien. En gratis baseline ville
stille TSMOM gunstigere end virkeligheden.

### Auto_adjust indfører ikke lookahead — testet, ikke antaget

Justeringsfaktoren for en historisk dato afhænger af udbytter udbetalt EFTER den
dato. Argumentet er at faktorerne står i både tæller og nævner og går ud. Det er
efterprøvet frem for antaget:

1. Dagligt totalafkast rekonstrueret manuelt fra ujusteret kurs + udbytte, holdt op
   mod `auto_adjust`-serien over 8.455 dage: **median |difference| = 1,7 × 10⁻⁷**.
2. 21 stk. 12-måneders vinduer fra 2005 til 2025, justeret afkast mod
   kursafkast + udbytte inde i vinduet: **median residual +0,12%**, uden trend
   tilbage i tid. Lækkede fremtidige udbytter ind, ville residualet vokse med
   afstanden til i dag — ~30% for et 2005-vindue. Det gør det ikke. Residualet er
   geninvesteringseffekten inde i vinduet, ikke kontaminering.

---

## Lookahead — grænsen er en test, ikke en kommentar

Den nemme fejl er at regne 12-måneders-afkastet frem til eksekveringsbarens close i
stedet for forrige måneds close. Én bars lookahead, usynlig i resultatet, og hele
fase 1 ville være værdiløs.

Signalet er derfor en ren funktion af to indeks, og uligheden
`ref_idx < signal_idx < exec_idx` håndhæves af `tests/test_tsmom.py`:

- `test_signal_ignores_execution_bar_and_future` — ødelægger alle barer fra
  eksekveringsbaren og frem og kræver hvert signal uændret.
- `test_equity_before_a_date_is_unaffected_by_later_data` — kører hele strategien på
  en afkortet serie og kræver kurven identisk på det fælles stykke.

**Testen kan køre rødt.** Byttes `signal_idx` ud med `exec_idx` i `signal_for`,
fejler den — det er efterprøvet, ikke påstået.

---

## DEL 1 — datakvalitet. Reparerer ingenting

| instrument | barer | fra | til | år | flade_barer | nul_volumen | brugbart_span | kasserede_år |
|---|---|---|---|---|---|---|---|---|
| SPY | 8456 | 1993-01-29 | 2026-09-02 | 33.6 | 0 | 0 | 1993–2026 | — |
| QQQ | 6914 | 1999-03-10 | 2026-09-02 | 27.5 | 0 | 0 | 1999–2026 | — |
| GC | 6520 | 2000-08-30 | 2026-08-26 | 26.0 | 1042 | 419 | 2000–2026 | — |
| XAU | 5383 | 2004-06-11 | 2025-09-30 | 21.3 | 0 | 0 | 2004–2024 | 2025 |
| 6E | 6551 | 2000-09-12 | 2026-08-26 | 26.0 | 36 | 780 | 2000–2026 | — |
| 6B | 6465 | 2000-10-05 | 2026-08-26 | 25.9 | 38 | 800 | 2002–2026 | 2000, 2001 |
| BTC | 3297 | 2017-08-17 | 2026-08-26 | 9.0 | 0 | 0 | 2017–2026 | — |
| ETH | 3297 | 2017-08-17 | 2026-08-26 | 9.0 | 0 | 0 | 2017–2026 | — |

**Kasseret, og hvorfor** (kriteriet er <90% årsdækning, samme tærskel som guldserien):

- **XAU 2025** — serien er mangelfuld fra marts 2025 (enkelte måneder med en
  brøkdel af de forventede barer). Det er samme hul som blev fundet ved
  DEL 3-guldtesten. Ikke repareret; året er udeladt af det brugbare span.
- **6B 2000-2001** — for få barer i kontraktens første år hos Yahoo.
- Intet andet år er kasseret. **Ingen bar er ændret, udfyldt eller interpoleret.**

**Forbehold der ikke er kasseret, men skal stå:**

- **`GC` har 1.042 flade barer (16%) og 419 barer med nul volumen.** Det er
  kendt fra daily-bias-valideringen og gjorde `GC=F` ubrugelig til range-logik.
  Her betyder det mindre: TSMOM læser kun `close` og `open`, aldrig `high`/`low`,
  og aldrig volumen. Forbeholdet er derfor ikke aktivt for denne kørsel — men det
  ville være det for enhver strategi der rører range eller volumen.
- **`6E` og `6B` har 780/800 barer med nul volumen.** Samme betragtning.
- Korrelationen mellem GC=F's og XAU-spots daglige afkast er 0,89 — ikke 0,99.
  Forskellen er lukketidspunkt (spot 24 timer mod COMEX-close), ikke instrument.

---

## Omsætning — et resultat, ikke en detalje

| instrument | positioner | tid_i_marked_% | hold_mdr | skift_pr_år | omk_%_af_brutto |
|---|---|---|---|---|---|
| SPY | 11 | 81.7 | 20.0 | 0.61 | 0.0 |
| QQQ | 11 | 79.2 | 15.72 | 0.76 | 0.0 |
| GC | 15 | 76.3 | 10.47 | 1.16 | 0.0 |
| XAU | 15 | 70.6 | 7.92 | 1.38 | 0.0 |
| 6E | 23 | 55.8 | 5.01 | 1.77 | 7.5 |
| 6B | 20 | 53.7 | 5.53 | 1.57 | 10.9 |
| BTC | 4 | 65.8 | 15.75 | 0.88 | 0.1 |
| ETH | 7 | 53.2 | 7.28 | 1.75 | 0.5 |

**`omk_%_af_brutto` er tallet der afgør om omkostningsskønnene overhovedet betyder
noget.** For de seks instrumenter hvor strategien tjener penge, er omkostningerne
**0,0-0,5% af bruttoafkastet**. Mine skøn for spread og slippage kunne være ti gange
for lave uden at ændre en konklusion.

De 7,5% og 10,9% på `6E` og `6B` er ikke et modsat resultat — de er en lille
omkostning delt med et bruttoafkast tæt på nul. FX-resultatet er ikke
omkostningsdrevet; det er fraværende.

**De to "n" er ikke det samme tal.** `positioner` er hvor mange gange der blev
handlet (4-23 over hele perioden). `tid_i_marked_%` er hvor stor en andel af tiden
der var eksponering (53-82%). En strategi med 11 positioner à 20 måneder og en med
60 à én måned kan have samme tid i markedet og vidt forskellige omkostninger.

### Glider månedsskiftet?

| instrument | slip_n | slip_efter_1 | slip_median | slip_maks |
|---|---|---|---|---|
| SPY | 392 | 141 | 0.0 | 3 |
| QQQ | 318 | 115 | 0.0 | 3 |
| GC | 300 | 109 | 0.0 | 4 |
| XAU | 242 | 85 | 0.0 | 29 |
| 6E | 299 | 107 | 0.0 | 3 |
| 6B | 298 | 107 | 0.0 | 3 |
| BTC | 96 | 0 | 0.0 | 0 |
| ETH | 96 | 0 | 0.0 | 0 |

Månedsskiftet er defineret i kalendertid: første tilgængelige bar med dato ≥ den 1.,
handlet til dens **åbningskurs**. Alle tidsstempler er reduceret til ren dato i UTC
før reglen anvendes — krypto kommer med UTC-midnat, aktier med børsens lokale dato.

Medianglidningen er **0 dage** på alle otte. På krypto glider den aldrig (24/7).
På børshandlede instrumenter glider ~35% af rebalanceringerne 1-3 dage, hvilket er
weekender og helligdage og præcis det man skal forvente. Undtagelsen er `XAU` med
maksimalt 29 dage — det er den mangelfulde 2025-region, samme hul som ovenfor.

---

## Robusthed — formålet er ikke at finde den bedste

### Lookback 3/6/9/12 måneder, CAGR

```
lookback       3      6      9      12
instrument                            
6B           0.66   0.43   0.43  -0.13
6E           2.02   1.30   1.28   0.10
BTC         23.25  16.44  34.10  34.37
ETH         24.16   5.46   2.93  21.96
GC           6.77   9.70   8.71  10.59
QQQ         11.07  10.32  10.48   9.39
SPY          7.76   8.67   9.55  10.53
XAU          6.94  10.32   7.24  10.05
```

### Samme, drawdown-reduktion mod buy-and-hold (andel)

```
lookback      3     6     9     12
instrument                        
6B          0.60  0.50  0.41  0.32
6E          0.60  0.64  0.30 -0.06
BTC         0.19  0.10  0.31  0.17
ETH         0.12  0.06  0.06  0.22
GC          0.04  0.43  0.07  0.25
QQQ         0.40  0.56  0.56  0.50
SPY         0.39  0.37  0.35  0.39
XAU         0.13  0.43  0.07  0.27
```

Effekten er **ikke** isoleret til 12 måneder. For `SPY` stiger CAGR monotont med
lookbacket (7,76 → 10,53) og drawdown-reduktionen ligger på 0,35-0,39 uanset
parameter. `QQQ`, `GC` og `XAU` er positive på alle fire. Drawdown-reduktionen er
positiv i 31 af 32 celler. Havde kun 12 virket, var 12 en tilfældighed — det er den
ikke.

FX er tæt på nul på alle fire lookbacks. Det er et konsistent fravær af effekt, ikke
en ustabil effekt.

### Rebalancering den 1. mod den 15. — turn-of-month-kontrollen

```
rebalance_day     1      15
instrument                 
6B              0.35  -0.14
6E              1.18   0.76
BTC            27.04  22.75
ETH            13.63  16.88
GC              8.94   8.75
QQQ            10.32  10.08
SPY             9.13   8.98
XAU             8.64   8.28
```

Dette er kontrollen der betød mest. Virkede TSMOM kun når der rebalanceres den 1.,
havde vi fundet en turn-of-month-effekt — et velkendt og separat fænomen i aktier —
og det ville have set ud præcis som en bestået test.

Det gør den ikke. `SPY` giver 10,77% på den 15. mod 10,53% på den 1.; `QQQ` 8,79 mod
9,39; `GC` 9,26 mod 10,59. Forskellene går i begge retninger og er små i forhold til
niveauet. **Der vælges ingen vinder** — pointen er at resultatet ikke afhænger af
dagen.

### Delperioder

| Instrument | Afkast i 4 lige lange delperioder (%) | Positive | Samme fortegn |
|---|---|---|---|
| SPY | [201.9, 58.44, 140.2, 130.47] | 4/4 | 4/4 |
| QQQ | [-26.12, 82.92, 168.52, 201.49] | 3/4 | 3/4 |
| GC | [167.97, 81.97, 10.7, 123.93] | 4/4 | 4/4 |
| XAU | [150.54, 20.5, 37.35, 68.57] | 4/4 | 4/4 |
| 6E | [47.48, -22.57, -8.07, -2.94] | 1/4 | 3/4 |
| 6B | [27.8, -19.57, -6.25, 0.2] | 2/4 | 2/4 |
| BTC | [-2.88, 268.15, 94.78, 51.88] | 3/4 | 3/4 |
| ETH | [-13.2, 534.89, 26.91, -30.26] | 2/4 | 2/4 |

---

## Hvad denne kørsel IKKE viser

- **Otte instrumenter er ikke otte uafhængige væddemål.** `SPY`/`QQQ` er stort set
  samme marked, `GC`/`XAU` er samme metal, `6E`/`6B` er begge USD-kryds, `BTC`/`ETH`
  følges ad. Reelt er der ~4 uafhængige observationer, ikke 8. Korrelationsmatrix på
  daglige afkast:

```
      SPY   QQQ    GC   XAU    6E    6B   BTC   ETH
SPY  1.00  0.85  0.01  0.05  0.12  0.19  0.29  0.32
QQQ  0.85  1.00 -0.01  0.04  0.05  0.14  0.30  0.33
GC   0.01 -0.01  1.00  0.87  0.36  0.29  0.10  0.09
XAU  0.05  0.04  0.87  1.00  0.37  0.30  0.10  0.09
6E   0.12  0.05  0.36  0.37  1.00  0.64  0.09  0.10
6B   0.19  0.14  0.29  0.30  0.64  1.00  0.13  0.14
BTC  0.29  0.30  0.10  0.10  0.09  0.13  1.00  0.78
ETH  0.32  0.33  0.09  0.09  0.10  0.14  0.78  1.00
```

  Kriteriet "4 af 8" er derfor svagere end det lyder. Det ændrer ikke konklusionen —
  effekten findes i alle fire uafhængige grupper på nær FX — men tærsklen bør ikke
  genbruges som om den var otte uafhængige test.

- **Det er ikke en handelsklar strategi, og skal ikke gøres til en.** Ingen
  positionsstørrelse, ingen porteføljekonstruktion, ingen finansiering, intet
  valutahensyn. Modulet ligger i `research/` netop for ikke at kunne samles op af
  registry'et.

- **FX-resultatet er ikke et modbevis.** TSMOM på enkelte valutakryds er svagere
  dokumenteret end på aktieindeks og råvarer, og 6E/6B er to observationer af det
  samme (USD).

- **Ni års krypto-historik er kort.** BTC og ETH består flere krav, men over ét
  marked og halvanden cyklus.

---

## Filer

- `research/daily_series.py` — de otte serier, kvalitetstjek, ejerskabsfelter
- `research/tsmom.py` — reglen. Én parameter
- `research/run_tsmom_test.py` — kørslen og det låste kriterium
- `tests/test_tsmom.py` — lookahead-grænsen og metrikkerne, 13 tests
- `research/output/apparatus_validation.csv` — alle 64 kørsler (8 × 4 lookbacks × 2 dage)
