# Time-series momentum — komplet dokumentation

**Status:** Færdigtestet, ikke implementeret. Lagt på hylden som kandidat til en
notifikationsbot med manuel eksekvering.
**Skrevet:** 2026-09-04
**Kode:** `research/tsmom.py`, `research/portfolio.py`
**Rapporter:** `research/output/apparatus_validation.md`, `portfolio_combination.md`

---

## 1. Hvad strategien er

Ét spørgsmål, stillet én gang om måneden, pr. instrument:

> **Står prisen højere end for 12 måneder siden?**
> Ja → ejer aktivet den næste måned.
> Nej → stå i kontanter den næste måned.

Det er hele reglen. **Én parameter: 12 måneder.**

- Ingen indikatorer, ingen confidence-score, ingen gates
- **Ingen stop loss og ingen take profit** — positionen holdes til signalet skifter
- Handel udføres på åbningskursen af første handelsdag i den nye måned
- Signalet beregnes udelukkende af data til og med sidste bar i forrige måned

### Hvor længe holdes en position

Langt længere end en måned. `SPY` havde **11 positioner på 32 år** — i snit omkring
to år pr. position. Det månedlige tjek spørger blot "trender den stadig?", og svaret
er som regel ja.

---

## 2. Hvorfor det virker

Time-series momentum er dokumenteret over mere end et århundrede og på snesevis af
markeder. Referencen er Moskowitz, Ooi og Pedersen (2012), som tester 58 instrumenter
over fire aktivklasser.

**Det virker ikke fordi det er smart. Det virker fordi det er ubehageligt.**

Reglen indebærer at tabe småt mange gange i træk, at sidde år uden fremgang, og at
købe ting der lige er steget meget — hvilket føles forkert hver gang. De fleste holder
ikke ud. Præmien er betaling for at holde ud.

Smarte tricks bliver arbitreret væk. Ubehag gør ikke.

### Hovedfundet er ikke højere afkast

Det er **lavere drawdown for omtrent samme afkast**. Måler man på afkast alene, tester
man det forkerte. `SPY` fanger 97% af buy-and-holds afkast med 61% af nedturen.

---

## 3. Resultater — enkeltinstrumenter

Periode 1993-02 → 2026-09. Netto efter omkostninger. Aktier er totalafkast
(udbytte geninvesteret); futures og FX er kurs. Kontanter forrentes ikke, hvilket
underdriver strategiens afkast med omtrent renteniveauet × tid uden for markedet.

```
instrument   CAGR_%  maxDD_%  Sharpe  flat_år  i_mkt_%  n_pos  B&H_CAGR_%  B&H_maxDD_%
SPY           10.53    -33.7    0.76      4.6     81.7     11       10.81        -55.2
GC            10.59    -33.3    0.71      8.9     76.3     15       11.99        -44.4
QQQ            9.39    -41.0    0.56     10.8     79.2     11        8.28        -81.2
BTC           34.37    -63.3    0.83      2.3     65.8      4       34.95        -76.6
ETH           21.96    -62.2    0.64      2.5     53.2      7       30.66        -79.3
6E             0.10    -42.1    0.05     18.3     55.8     23        0.98        -39.8
6B            -0.13    -33.7    0.01     18.8     53.7     20       -0.29        -49.2
```

**Instrumenterne:** `SPY` = ETF på S&P 500 (500 største amerikanske selskaber).
`QQQ` = ETF på Nasdaq-100 (teknologitungt). `GC` = guld-futures på COMEX.
`6E`/`6B` = euro- og pund-futures på CME. `BTC`/`ETH` = spot-krypto på Binance.

### FX er strukturelt tomt

`6E` og `6B` giver nul. Grunden er ikke tilfældig: **valutaer har ingen langsigtet
drift.** EUR/USD er et forhold mellem to valutaer — stiger den ene, falder den anden.
Aktier stiger fordi virksomheder vokser; guld med inflation; BTC med udbredelse. Et
valutakryds har ingenting at stige af.

Long-only momentum kræver drift. Den professionelle FX-udgave er **long/short**: køb
de stærkeste valutaer, sælg de svageste samtidig. Det er en anden strategi, som ikke
er bygget.

**At metoden viser nul præcis dér hvor der skal være nul, er lige så validerende som
at den viser 10% på aktier.**

---

## 4. Resultater — portefølje

Invers volatilitetsvægtning (12 måneders bagudskuende vindue), månedlig
rebalancering. `XAU` er fjernet fordi den korrelerede 0,98 med `GC` — samme metal
fra to datakilder, hvilket gav guld dobbelt risikobudget.

```
univers          CAGR_%  maxDD_%  Sharpe  flat_år
alle_syv           7.40    -19.0    0.79      3.1
uden_fx           12.75    -21.1    0.98      3.4
B&H (ligevægtet)   8.05    -46.7      —        —
```

### Bidrag pr. instrument (alle syv)

```
instrument   afk_bidrag_%  risk_bidrag_%
SPY                  42.2           39.6
GC                   23.9           15.0
QQQ                  19.7           17.0
BTC                   9.8            4.6
ETH                   6.5            3.8
6E                   -1.0           10.3
6B                   -1.1            9.8
```

`GC` er den mest effektive: 23,9% af afkastet for 15,0% af risikoen, fordi den
korrelerer kun 0,08 med aktier. `6E` og `6B` giver tilsammen **−2,1% af afkastet for
20,1% af risikoen.**

Bemærk: kolonnerne er ikke normaliseret for tid i porteføljen. `SPY` har været med i
33 år, krypto i 9.

---

## 5. Diversificering — hvad vi lærte

**Effektive væddemål: 2,72** ud af syv instrumenter.

```
                              gennemsnitlig korrelation
strategiernes månedlige afkast          +0.257
aktivernes månedlige afkast             +0.300
```

Forventningen var at strategikorrelationerne ville være markant lavere end
aktivkorrelationerne — at strategierne ville gå i kontanter på forskellige tidspunkter.
**Det holder ikke.** 15% reduktion, ikke i nærheden af nok.

```
par        strategi  aktiv
SPY–QQQ        0.81   0.84
6E–6B          0.67   0.65
BTC–ETH        0.63   0.72
SPY–GC         0.08   0.07
GC–BTC         0.01   0.11
```

`SPY` og `QQQ` går ud af markedet næsten samtidig — samme signal, samme marked.
Krypto er det eneste sted hvor mekanismen giver reel uafhængighed.

### Formlen der holder

Samlet Sharpe ≈ gennemsnitlig individuel Sharpe × √(effektive væddemål).

0,53 × √2,86 = 0,90 forudsagt mod 0,82 faktisk. **Matematikken er rigtig; det var
antagelsen om antal uafhængige kilder der var for optimistisk.**

**Konsekvens:** bredde kommer fra forskellige *mekanismer*, ikke fra flere tickere.
Fem trendstrategier på samme aktiver er én strategi med fem navne.

---

## 6. Omkostningsmodel

```
krypto (Binance spot)
  spread              1 bp
  slippage            2 bp i snit (std 2 bp, afkortet så den aldrig er favorabel)
  kurtage            20 bp rundtur  (0,10% taker × 2 sider)
  i alt             ~23 bp pr. rundtur

forex (6B-kontrakt, 62.500 GBP ≈ 79.000 USD notional)
  spread + slippage   1,5 tick à 6,25 USD = 9,38 USD
  kurtage             4,00 USD rundtur
  i alt              ~1,7 bp

guld (GC-kontrakt, 100 troy oz)
  spread + slippage   1,5 tick à 10 USD = 15 USD
  kurtage             4,00 USD rundtur
  i alt              ~0,8 bp
```

Omkostning opkræves **kun ved signalskift**, ikke hver måned. En sammenhængende
holdeperiode = én rundtur.

Omkostninger udgør **0,0-0,5% af bruttoafkastet** dér hvor strategien tjener penge.
Skønnene kunne være ti gange for lave uden at ændre en konklusion.

### Hvad der IKKE er modelleret

- **Rulning af futures.** En kontrakt udløber; holder man i to år, skal der rulles
  omkring tolv gange. Målt effekt på guld: 0,04 pct-point/år. På andre futures
  (olie, volatilitet) kan contango koste flere procent årligt.
- **Swap/finansiering** på gearede positioner holdt natten over.
- **Forrentning af kontanter** i de ~30% af tiden strategien står ude. Udeladt bevidst
  — det gør testen konservativ.

---

## 7. Praktisk implementering

### Kontraktstørrelser er det største problem

En GC-guldfuture er 100 troy ounces — flere hundrede tusind dollars i notional. En
ES-kontrakt på S&P 500 tilsvarende. **Med en konto på 5-10.000 kr. kan man ikke købe
én kontrakt**, og slet ikke risikovægte syv af dem.

Mikro-kontrakter findes (MGC = 10 oz guld, MES = 1/10 ES) men kræver stadig margin
i tusindvis og er gearede.

### Den realistiske vej: ETF'er

`GLD` i stedet for guld-futures, `SPY` og `QQQ` direkte. Ingen rulning, intet udløb,
ingen finansiering, ingen gearing — man ejer bare andelen. Billigere spread end
antaget i modellen ovenfor.

Kræver en aktiebroker. Backtesten er kørt på institutionelle instrumenter fordi det
er dér historikken er; implementeringen hører til på ETF'er, som opfører sig næsten
identisk.

### Notifikationsvarianten — den valgte form

Med 11 handler på 32 år er automatisk eksekvering ikke nødvendig. Botten skal:

1. Hente daglige kurser for universet
2. Ved hvert månedsskifte beregne 12-måneders-afkastet pr. instrument
3. Sammenligne mod nuværende beholdning
4. **Sende en notifikation hvis noget skal skifte** — ellers være stille
5. Logge signalet så historikken kan efterprøves

Handler placeres manuelt hos en dansk udbyder, hvilket forenkler skatteafregningen.
Kontrollen tager få minutter én gang om måneden.

---

## 8. Kendte svagheder

**n er lille.** `SPY`: 11 positioner på 32 år. Hele resultatet hviler på elleve
beslutninger. Vi tror på det fordi det matcher en effekt dokumenteret på 58
instrumenter over et århundrede — ikke fordi vores elleve positioner beviser noget.

**Ventetiden er lang.** `SPY`: 4,6 år uden ny egenkapitaltop. `QQQ`: 10,8 år.
Porteføljen: 3,1 år. Det er det man skal kunne holde ud uden at slukke.

**Krypto-tallene er ikke et strategiresultat.** `BTC` n=4, `ETH` n=7. Det er "krypto
steg, og vi var med det meste af tiden".

**Porteføljens maxDD på −19,0% indtraf 1998-08-31**, da porteføljen bestod af `SPY`
alene. Fra 2003 er værste fald −11,7%. Hovedtallet måler ikke en diversificeret
portefølje.

**Bidragskolonnerne er ikke tidsnormaliserede.**

---

## 9. Validering — hvad der er efterprøvet

- **Lookahead:** test der fejler hvis signalet afhænger af eksekveringsbaren eller
  senere. Fejlen blev indsat bevidst og bekræftet at slå testen rød.
- **Vægtningens lookahead:** både `<= asof` og fuldperiode-volatilitet får testene
  til at køre rødt.
- **`auto_adjust`:** median-difference 1,7 × 10⁻⁷ mod manuelt rekonstrueret
  totalafkast. Residualet vokser ikke tilbage i tid, som det ville hvis fremtidige
  udbytter lækkede ind.
- **Turn-of-month:** rebalancering den 15. giver `SPY` 10,77% mod 10,53% på den 1.
  Resultatet afhænger ikke af dagen.
- **Robusthed på lookback:** 3, 6, 9 og 12 måneder kørt. Rapporteret uden at vælge
  vinder.
- **Gearingslæk:** fanget af test — kontantbeholdningen kunne ende på minus kurtagen,
  et lån på 1-2 bp der ville have set ud som afkast. Rettet.

---

## 10. Kalibrering — hvad tallene betyder

```
S&P 500, køb og behold, langt sigt      Sharpe ~0,4-0,5
Trendfølge-branchen (managed futures)          ~0,5
Gode hedgefonde                                ~0,5-1,0
Denne portefølje over 33 år                     0,98
Renaissance Medallion                          ~2+
```

Sharpe 2 er niveauet for verdens bedste hedgefond, lukket for udefrakommende penge.
**En backtest der viser Sharpe 2 på retail-niveau er næsten altid en fejl** —
overfitting, lookahead, eller skjult halerisiko. Behandl 2,0 som et advarselssignal,
ikke som et mål.

For at fordoble Sharpe fra 1,0 til 2,0 kræves fire gange så mange uafhængige
væddemål — fra 2,7 til omkring 11. Det er tolv forskellige mekanismer der ikke
fejler samtidig, ikke flere instrumenter i samme familie.
