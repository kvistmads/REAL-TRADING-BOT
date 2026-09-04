# Fase 2 — porteføljekørsel: virker diversificering på vores egne tal?

**Kørsel:** de otte TSMOM-kurver kombineret til én portefølje, invers volatilitet,
månedlig rebalancering.
**Periode:** 1993-04-01 → 2026-09-02
**Status:** research. Ingen ændring af live handelsadfærd, `config.yaml` urørt.

---

## Svaret

**Diversificering virker — men mindre end forventet, og af en grund der er værd at
kende: strategikorrelationerne er næsten lige så høje som aktivkorrelationerne.**

```
FASE 2  portefølje: invers vol (12m bagudskuende), månedlig rebalancering
univers / periode         n    CAGR   maxDD  Sharpe  flat_dg  i mkt |  B&H CAGR B&H maxDD  B&H Sh B&H flat
alle_otte  1993-2026      8   7.83%  -19.0%    0.82     1148    68% |     7.95%    -44.0%    0.63     2086
  fra 2003 (≥5 instr.)        6.03%  -11.7%    0.88     1022        |    10.64%    -44.0%    0.73     1364
  fra 2018 (alle 8)           7.48%  -11.7%    1.03      778        |    15.78%    -44.0%    0.78      846
uden_fx  1993-2026        6  12.18%  -21.1%    0.99     1259    77% |     8.81%    -45.0%    0.65     2203
  fra 2003 (≥5 instr.)       12.28%  -21.1%    1.08      820        |    11.83%    -45.0%    0.77     1286
  fra 2018 (alle 8)          15.86%  -21.1%    1.22      820        |    16.59%    -45.0%    0.78      846
```

| Forhåndsregistreret | Forventet | Faktisk | |
|---|---|---|---|
| Samlet Sharpe | 1,0–1,2 | **0.82** | under båndet, men klart over fejlgrænsen på 0,7 |
| maxDD | 20–25% | **-19.0%** | bedre end forventet |
| longest_flat_days | markant under SPY's 1685 / QQQ's 3958 | **1148** | holder |

Ingen af de to fælder blev udløst: Sharpe er hverken ≥1,5 (som ville have peget på
lookahead i vægtningen) eller ≤0,7 (som ville have betydet at diversificeringen ikke
virker).

**Det tal du sagde betød mest — longest_flat_days — er det der falder klarest ud.**
Porteføljen går 1148 dage som værst uden ny egenkapitaltop, mod
1.685 for `SPY` alene, 3.958 for `QQQ` og 2086 for ligevægtet
køb-og-behold af de samme otte. Det er stadig godt tre år, men det er den halve
ventetid.

---

## DEL 2.1 — den vigtigste måling: strategi- mod aktivkorrelation

Du havde ret i at det var det forkerte tal jeg målte i fase 1. Her er begge.

Gennemsnitlig parvis korrelation over de otte:

| | Gennemsnit | Effektive væddemål (ρ) | Effektive væddemål (egenværdier) |
|---|---|---|---|
| **Strategiernes** månedlige afkast | **+0.257** | **2.86** | 4.19 |
| Aktivernes månedlige afkast | +0.300 | 2.58 | 3.93 |

**Forventningen var at strategikorrelationerne ville være markant lavere. Det er de
ikke.** 0.257 mod 0.300 er en reduktion på
15% — reel, men ikke i nærheden af nok til at gøre otte
instrumenter til otte væddemål.

Par for par (sorteret efter aktivkorrelation):

```
    par  strategi  aktiv  forskel
 GC–XAU      0.98   0.98    -0.01
SPY–QQQ      0.81   0.84    -0.03
BTC–ETH      0.63   0.72    -0.09
  6E–6B      0.67   0.65     0.02
  GC–6E      0.34   0.40    -0.06
SPY–ETH      0.42   0.40     0.02
 XAU–6E      0.31   0.40    -0.08
QQQ–ETH      0.35   0.38    -0.03
 SPY–6B      0.27   0.38    -0.11
SPY–BTC      0.35   0.37    -0.02
QQQ–BTC      0.37   0.34     0.03
 SPY–6E      0.21   0.32    -0.11
 XAU–6B      0.24   0.28    -0.05
  GC–6B      0.24   0.27    -0.03
 QQQ–6B      0.21   0.25    -0.04
 QQQ–6E      0.15   0.20    -0.05
 6B–ETH      0.15   0.17    -0.01
XAU–ETH     -0.10   0.13    -0.22
 6B–BTC      0.13   0.13    -0.00
XAU–BTC      0.06   0.13    -0.06
 6E–ETH      0.11   0.13    -0.02
 6E–BTC      0.01   0.12    -0.11
 GC–BTC      0.01   0.11    -0.10
SPY–XAU      0.09   0.10    -0.01
 SPY–GC      0.08   0.07     0.01
QQQ–XAU      0.11   0.07     0.04
 GC–ETH     -0.10   0.07    -0.17
 QQQ–GC      0.09   0.02     0.07
```

Tre ting at læse ud af den tabel:

1. **`GC`–`XAU` er 0,98 i BEGGE matricer.** Det er ikke to instrumenter, det er ét
   metal hentet fra to kilder. Diversificering kan ikke reparere det, for der er
   ingen uafhængighed at hente.
2. **`SPY`–`QQQ` falder kun fra 0,84 til 0,81.** De to strategier er ude af markedet
   på næsten samme tidspunkter, fordi de reagerer på det samme signal i det samme
   marked. Long-only TSMOM fjerner nedture, men det fjerner dem samtidigt.
3. **Krypto er det eneste sted mekanismen virker som håbet:** `BTC`–`ETH` falder fra
   0,72 til 0,63, fordi de to faktisk går ud af markedet på forskellige tidspunkter.

Det er svaret på hvorfor Sharpe landede på 0.82 og ikke 1,1: der er
**2.9 effektive væddemål, ikke 4.**

Forudsigelsen holder til gengæld præcist. Gennemsnitlig individuel Sharpe er
0.53; 0.53 × √2.86 =
**0.90** forudsagt mod **0.82** faktisk.
Formlen `s × √N` virker — det var antagelsen om N der var for optimistisk.

De to N-mål er ikke enige (2.86 mod 4.19), og
uenigheden er informativ: porteføljen er **klynget**, ikke jævnt korreleret. To par
sidder på 0,98 og 0,81 mens de fleste krydspar ligger under 0,15. ρ-udgaven antager
at alle par er ens og straffer derfor hårdt; egenværdierne ser klyngerne. Sandheden
ligger imellem, og den faktiske Sharpe (0.82) ligger da også mellem de
to forudsigelser.

### Individuelle Sharpe-tal, til reference

| instrument | Sharpe |
|---|---|
| SPY | 0.76 |
| QQQ | 0.56 |
| GC | 0.71 |
| XAU | 0.7 |
| 6E | 0.05 |
| 6B | 0.01 |
| BTC | 0.83 |
| ETH | 0.64 |

Gennemsnit: **0.53** over alle otte, **0.70** uden FX.

---

## DEL 1 — hvordan porteføljen er bygget

- **Vægt:** invers volatilitet, `w_i = (1/σ_i) / Σ(1/σ_j)`, altså lige risikobidrag.
- **σ måles bagudskuende** på 12 måneders daglige afkast frem til dagen FØR
  rebalanceringen, og annualiseres med instrumentets eget antal barer pr. år
  (krypto 365, futures ~252). Uden den korrektion ville krypto se ~20% mere volatil
  ud end den er, alene på grund af kalenderen.
- **Rebalancering:** månedligt, samtidig med TSMOM-signalet.
- **Pladsen holder TSMOM-positionen**, ikke aktivet. Er signalet ude, står pladsens
  kapital i kontanter, og kontanter forrentes ikke.
- **Ingen gearing.** En plads kan aldrig købe for mere end sin egen værdi plus
  kontantbeholdningen — og loftet levner plads til kurtagen. Uden det sidste endte
  kontantbeholdningen på minus gebyret: et lån på 1-2 basispunkter, som ville have
  set ud som afkast. Det blev fanget af `test_portfolio_never_uses_leverage`.

### Omkostninger: to kilder til omsætning

Samlet **2.94%** af startkapitalen over
33 år, hvoraf **28%** er ren
vægtrebalancering — altså omsætning ud over signalskiftene. Den del ville være
usynlig hvis man kun havde modelleret ind- og udgange.

### Instrumenterne findes ikke lige længe

Porteføljen starter i 1993 med `SPY` alene. `QQQ` kommer i 1999, futures i 2001-02,
krypto i 2018. Kapitalen fordeles kun på de instrumenter der findes, og resten står
i kontanter. Det betyder at **det første tiår ikke er en diversificeret portefølje** —
det er `SPY` med et TSMOM-filter.

Derfor står æra-linjerne i tabellen. De er beskrivende, ikke et valg af periode:
fra 2018, hvor alle otte findes, er Sharpe
1.03 —
inde i det forhåndsregistrerede bånd. **Hovedtallet er stadig hele perioden**, som
aftalt; æra-tallene siger hvor meget af afstanden til båndet der skyldes at
porteføljen ikke var en portefølje endnu.

**Det tydeligste enkelttal her:** porteføljens værste drawdown på
-19.0% indtraf **1998-08-31** — altså i
den periode hvor porteføljen bestod af `SPY` alene. Fra 2003 og frem, hvor mindst
fem instrumenter er med, er det værste fald -11.7%.
Det maksimale tab i hovedtallet måler altså ikke en diversificeret portefølje; det
måler ét instrument. Baselinens -44.0% indtraf til
sammenligning 2022-11-09, hvor alle otte var med.

---

## DEL 3 — FX-varianten

| univers | n | CAGR | maxDD | Sharpe | flat_dage | ρ_strategi | N_eff |
|---|---|---|---|---|---|---|---|
| alle_otte | 8 | 7.83 | -19.03 | 0.822 | 1148 | 0.257 | 2.86 |
| uden_fx | 6 | 12.18 | -21.09 | 0.992 | 1259 | 0.277 | 2.51 |

Uden `6E`/`6B` stiger CAGR fra 7.83% til 12.18% og
Sharpe fra 0.82 til 0.99.

**Men det er ikke en begrundelse for at fjerne dem.** Argumentet — at valutaer ikke
har nogen langsigtet drift, så long-only momentum ikke har noget at fange — er
strukturelt korrekt, men det blev formuleret EFTER vi så tallene. Det er derfor en
**hypotese til næste kørsel**, ikke en konklusion fra denne. Hovedtallet er alle otte.

Bemærk desuden at FX' bidrag ikke kun er lavt afkast: `ρ_strategi` er stort set
uændret (0.257 mod 0.277) når de fjernes. De to
FX-kryds tilfører altså hverken afkast eller uafhængighed.

---

## DEL 4 — baseline

Ligevægtet køb-og-behold af de samme instrumenter, samme periode, samme
omkostningskonvention (én rundtur pr. instrument over hele perioden). Instrumenter
der starter senere købes når de findes; kapitalen står i kontanter indtil da —
ellers skulle baselinen enten forudse hvornår Binance åbnede, eller måles på en
kortere periode end strategien.

Porteføljen giver **7.83%** mod baselinens **7.95%** — altså
stort set samme afkast — med **-19.0%** mod
**-44.0%** i maksimalt fald og
**1148** mod **2086** dage uden ny top.

Det er samme mønster som i fase 1, nu på porteføljeniveau: TSMOM slår ikke
køb-og-behold på afkast. Den leverer omtrent samme afkast med under det halve
drawdown.

---

## Lookahead — hvad der er testet

Invers volatilitet beregnet på HELE perioden er den klassiske skjulte fejl her: den
undervægter systematisk de instrumenter der senere viste sig turbulente, den pynter
Sharpe, og den efterlader ingen spor i resultatet.

`tests/test_portfolio.py` har tre spærringer, og alle tre er efterprøvet ved at
indsætte fejlen og se dem køre rødt:

- `test_weights_ignore_all_future_data` — ødelægger alle barer fra
  rebalanceringsdagen og frem og kræver vægtene uændrede, over 32 månedsskifter.
- `test_trailing_vol_excludes_the_rebalance_bar_itself` — grænsen er strengt `<`,
  ikke `<=`. Rebalanceringsdagens egen bar er allerede fremtid.
- `test_equity_before_a_date_is_unaffected_by_later_data` — hele porteføljen kørt på
  afkortede serier, kurven skal være identisk på det fælles stykke.

Begge de to realistiske fejl (`<= asof`, og fuldperiode-volatilitet) får testene til
at fejle.

---

## Hvad kørslen ikke viser

- **Otte instrumenter er ~2.9 væddemål.** Vil man have flere
  uafhængige kilder, skal de komme fra markeder eller strategityper vi ikke har,
  ikke fra flere varianter af det samme.
- **`GC` og `XAU` dobbelttæller guld** (ρ 0,98). Det præregistrerede univers har dem
  begge, så hovedtallet har dem begge — men et gennemsnit over otte instrumenter
  hvor to er identiske, vægter guld dobbelt.
- **Kontanter forrentes stadig ikke.** Porteføljen står uden for markedet
  32% af tiden. Ved 2-5% p.a. er det
  0.6-1.6
  pct-point om året som strategien ikke får krediteret. Testen er konservativ.
- **Ingen valutaeffekt.** Alt er regnet i USD som om kapitalen var i USD.
- **Vægtningen er ikke optimeret, og skal ikke være det.** Invers volatilitet er
  valgt fordi den er parameterfri, ikke fordi den er bedst.

---

## Filer

- `research/portfolio.py` — kombinationsmotoren, vægtning og bogholderi
- `research/run_portfolio_test.py` — kørslen og de forhåndsregistrerede grænser
- `tests/test_portfolio.py` — lookahead-spærringerne og gearingsloftet, 8 tests
- `research/output/portfolio_combination.csv` — begge universer, alle nøgletal
