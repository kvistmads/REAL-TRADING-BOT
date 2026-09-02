# Instrumentklasse-test: har trend_momentum en edge, og hvor?

**Kørt:** 2026-09-02 18:55 UTC  
**Strategi:** trend_momentum, uden gates, uden flip-exit  
**Halvdel 1:** 2024-08→2025-09 · **Halvdel 2:** 2025-09→2026-09


> **Stikprøven er ikke udvidet.** yfinance leverer kun 1-times-data 730 dage tilbage (Yahoo: *"The requested range must be within the last 730 days"*), så forex og guld kan ikke gå længere tilbage uden en ny datakilde. Krypto kunne, men så ville grupperne dække forskellige perioder og sammenligningen være konfunderet. Resultatet er derfor **underpowered** — se styrkeafsnittet.


## Svar

**Strategien har ingen påvist edge på noget instrument.** Ikke-kryptos R/handel netto overlapper nul i BEGGE halvdele, så konklusionen er ikke "drop krypto" — det er at der ikke er demonstreret en edge nogen steder. Krypto er dér hvor tabene er størst, men det følger af at volatiliteten er størst dér, ikke af at strategien er påviseligt dårligere.


Præregistreret kriterium: krav 1 FEJLER, krav 2 opfyldt, krav 3 opfyldt → **ikke påvist**.


## 1. Break-even — det tal der afgør alt andet

Antagelsen +2R/−1R giver en break-even WR på 33,3%. De FAKTISKE haler er komprimerede af breakeven-stop og time-stop, så tærsklen ligger et andet sted. `margin_pp` er observeret WR minus den krævede: positiv = strategien tjener.


| symbol | n | WR_brut_% | WR_net_% | WR_breakeven_% | margin_pp | W_gns_R | L_gns_R | W_median_R | L_median_R | omkost_R | PF_net | R/handel_brut | R/handel_net | 95%-CI | PnL/handel_% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC/USDT | 88 | 31.82 | 30.68 | 39.32 | -7.5 | 1.4094 | 0.7359 | 2.0 | 1.0 | 0.1076 | 0.721 | -0.0533 | -0.1609 | [-0.4002, 0.0784] | -0.4446 |
| ETH/USDT | 87 | 34.48 | 34.48 | 34.67 | -0.18 | 1.443 | 0.6541 | 2.0 | 1.0 | 0.0729 | 0.992 | 0.0691 | -0.0039 | [-0.2462, 0.2384] | 0.0077 |
| SOL/USDT | 91 | 31.87 | 31.87 | 37.53 | -5.66 | 1.3332 | 0.7031 | 2.0 | 1.0 | 0.0611 | 0.778 | -0.0542 | -0.1152 | [-0.3415, 0.111] | -0.5341 |
| EUR/USD | 58 | 32.76 | 32.76 | 33.76 | -1.0 | 1.4853 | 0.718 | 1.9999 | 1.0 | 0.0259 | 0.956 | 0.0038 | -0.022 | [-0.3267, 0.2826] | 0.0214 |
| GBP/USD | 54 | 37.04 | 37.04 | 29.92 | 7.12 | 1.7232 | 0.6765 | 2.0 | 1.0 | 0.0415 | 1.378 | 0.2123 | 0.1708 | [-0.168, 0.5097] | 0.127 |
| XAU/USD | 54 | 37.04 | 37.04 | 30.25 | 6.79 | 1.5369 | 0.6591 | 2.0 | 1.0 | 0.0051 | 1.357 | 0.1542 | 0.1491 | [-0.172, 0.4702] | 0.1779 |


### Pr. gruppe

| gruppe | n | WR_brut_% | WR_net_% | WR_breakeven_% | margin_pp | W_gns_R | L_gns_R | W_median_R | L_median_R | omkost_R | PF_net | R/handel_brut | R/handel_net | 95%-CI | PnL/handel_% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| krypto | 266 | 32.71 | 32.33 | 37.19 | -4.48 | 1.3956 | 0.6985 | 2.0 | 1.0 | 0.0803 | 0.821 | -0.0136 | -0.0939 | [-0.2298, 0.042] | -0.3273 |
| ikke-krypto | 166 | 35.54 | 35.54 | 31.3 | 4.25 | 1.5834 | 0.6861 | 2.0 | 1.0 | 0.0242 | 1.21 | 0.1205 | 0.0964 | [-0.0884, 0.2812] | 0.1067 |


## 2. Præregistreret kriterium (låst før kørsel)

Krypto klassificeres som skadelig hvis **alle tre** holder. Fejler ét, er svaret "ikke påvist" — og så leder vi ikke efter en delmængde hvor det ser bedre ud.


| krav | opfyldt | detalje |
|---|---|---|
| 1. Krypto negativ R/handel netto i begge halvdele | NEJ | 1. halvdel: nej, 2. halvdel: ja |
| 2. Ikke-krypto højere end krypto i begge halvdele | ja | 1. halvdel: ja, 2. halvdel: ja |
| 3. Forskellen findes også brutto | ja | 1. halvdel: ja, 2. halvdel: ja |


### Pr. halvdel


**1. halvdel**

| gruppe | n | WR_brut_% | WR_net_% | WR_breakeven_% | margin_pp | W_gns_R | L_gns_R | W_median_R | L_median_R | omkost_R | PF_net | R/handel_brut | R/handel_net | 95%-CI | PnL/handel_% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| krypto | 125 | 37.6 | 36.8 | 35.79 | 1.81 | 1.4698 | 0.7059 | 2.0 | 1.0 | 0.0728 | 1.081 | 0.1122 | 0.0394 | [-0.1718, 0.2506] | 0.1202 |
| ikke-krypto | 80 | 41.25 | 41.25 | 31.46 | 9.79 | 1.662 | 0.7301 | 2.0 | 1.0 | 0.0224 | 1.53 | 0.2566 | 0.2342 | [-0.0503, 0.5188] | 0.2254 |


**2. halvdel**

| gruppe | n | WR_brut_% | WR_net_% | WR_breakeven_% | margin_pp | W_gns_R | L_gns_R | W_median_R | L_median_R | omkost_R | PF_net | R/handel_brut | R/handel_net | 95%-CI | PnL/handel_% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| krypto | 141 | 28.37 | 28.37 | 38.97 | -10.6 | 1.3084 | 0.6927 | 1.5237 | 1.0 | 0.0871 | 0.621 | -0.125 | -0.2121 | [-0.3856, -0.0387] | -0.724 |
| ikke-krypto | 86 | 30.23 | 30.23 | 31.73 | -1.49 | 1.4837 | 0.6516 | 2.0 | 1.0 | 0.0259 | 0.933 | -0.006 | -0.0319 | [-0.2693, 0.2056] | -0.0038 |


## 3. Modcasen — har strategien en edge NOGEN steder?

Den mest sandsynlige forklaring er ikke at krypto er specielt dårligt, men at strategien ikke har nogen edge nogen steder og at tabene samler sig hvor volatiliteten er størst.


| gruppe | n | R/handel_net | 95%-CI | overlapper_nul |
|---|---|---|---|---|
| krypto | 266 | -0.0939 | [-0.2298, 0.042] | ja |
| ikke-krypto | 166 | 0.0964 | [-0.0884, 0.2812] | ja |


**Mindste forskel stikprøven kan afsløre:** 0.3586 R (80% styrke, alpha 5%, spredning 1.166 R, n≈166 pr. gruppe). En målt forskel mindre end det er "kan ikke afgøres", ikke "ingen forskel".


## 4. Kontinuert test — falder afkast med omkostning i R?

Rapporteret **ved siden af** gruppekriteriet; det er gruppekriteriet der afgør dommen. Legitim fordi `omkost_R` er en egenskab ved instrumentet, målt før afkasttallene blev set.


| symbol | gruppe | omkost_R | R/handel_net | n |
|---|---|---|---|---|
| XAU/USD | ikke-krypto | 0.0051 | 0.1491 | 54 |
| EUR/USD | ikke-krypto | 0.0259 | -0.022 | 58 |
| GBP/USD | ikke-krypto | 0.0415 | 0.1708 | 54 |
| SOL/USDT | krypto | 0.0611 | -0.1152 | 91 |
| ETH/USDT | krypto | 0.0729 | -0.0039 | 87 |
| BTC/USDT | krypto | 0.1076 | -0.1609 | 88 |


Spearman(omkost_R, R/handel_net) = **-0.6** (p=0.208, n=6, 95%-CI (-0.949, 0.412)).


Med seks punkter er intervallet så bredt at det er foreneligt med næsten enhver sammenhæng. Korrelationen er en indikation, ikke et bevis.


## 5. Uafhængighed — symbolerne er ikke seks observationer

Parvis korrelation mellem daglige afkast i perioden:


|  | BTC/USDT | ETH/USDT | SOL/USDT | EUR/USD | GBP/USD | XAU/USD |
|---|---|---|---|---|---|---|
| BTC/USDT | 1.0 | 0.828 | 0.797 | 0.092 | 0.175 | 0.162 |
| ETH/USDT | 0.828 | 1.0 | 0.802 | 0.079 | 0.174 | 0.145 |
| SOL/USDT | 0.797 | 0.802 | 1.0 | 0.08 | 0.155 | 0.135 |
| EUR/USD | 0.092 | 0.079 | 0.08 | 1.0 | 0.777 | 0.324 |
| GBP/USD | 0.175 | 0.174 | 0.155 | 0.777 | 1.0 | 0.324 |
| XAU/USD | 0.162 | 0.145 | 0.135 | 0.324 | 0.324 | 1.0 |


Er korrelationen inden for en gruppe høj, er tre symboler nærmere én til to uafhængige observationer. Det halverer reelt den styrke gruppetesten har, oven i den lille stikprøve.


## 6. Forudsigelsen, låst før kørsel

Forventet: krypto klart negativ i R, ikke-krypto omkring nul. Break-even forudsagt til 32.0% brutto, 33.2% / 35.7% ved de to gruppers omkostning.


- krypto: break-even WR 37.19% mod forudsagt 35.7% (+1.49 pp) — inden for tolerancen.
- ikke-krypto: break-even WR 31.3% mod forudsagt 33.2% (-1.90 pp) — inden for tolerancen.
- krypto R/handel netto = -0.0939 (negativ som forudsagt)
- ikke-krypto R/handel netto = +0.0964, 95%-CI [-0.0884, 0.2812] (overlapper nul som forudsagt)


## Datagrundlag

| symbol | gruppe | barer | fra | til | flade_barer | flade_pct | kasserede |
|---|---|---|---|---|---|---|---|
| BTC/USDT | krypto | 4400 | 2024-08-30 | 2026-09-02 | 0 | 0.0 | 0 |
| ETH/USDT | krypto | 4400 | 2024-08-30 | 2026-09-02 | 0 | 0.0 | 0 |
| SOL/USDT | krypto | 4400 | 2024-08-30 | 2026-09-02 | 0 | 0.0 | 0 |
| EUR/USD | ikke-krypto | 3112 | 2024-09-03 | 2026-09-02 | 0 | 0.0 | 0 |
| GBP/USD | ikke-krypto | 3112 | 2024-09-03 | 2026-09-02 | 0 | 0.0 | 0 |
| XAU/USD | ikke-krypto | 3114 | 2024-09-03 | 2026-09-02 | 0 | 0.0 | 0 |


## Hvad der IKKE er gjort

- Ingen konfigurationsændringer foreslået. Live-adfærd er urørt.

- Ingen symboler tilføjet eller fjernet.

- Grupperne er ikke justeret efter at have set resultatet.

- Flip level forbliver observe-only.
