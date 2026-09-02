# Out-of-sample-test: flip-exit på trend_momentum

**Kørt:** 2026-09-02 15:59 UTC  
**Halvdel 1:** 2024-08→2025-08  
**Halvdel 2:** 2025-09→2026-09

> Flip level forbliver observe-only i live uanset hvad der står herunder.


## Svar

**Ikke bekræftet — effekten viser sig kun i 2. halvdel.** En exit-regel der kun virker i den ene halvdel af stikprøven er støj, ikke en edge. Det oprindelige +10,26% var én in-sample kørsel på en strategi med brutto-PF 0,98; dette er hvad der sker når den måles ud af stikprøven.


### Præregistreret kriterium (låst før kørsel)

| krav | opfyldt | detalje |
|---|---|---|
| A2 > A1 i begge halvdele (brutto) | NEJ | 1. halvdel: nej, 2. halvdel: ja |
| A2 > A1 i begge halvdele (netto — overlever omkostninger) | NEJ | 1. halvdel: nej, 2. halvdel: ja |
| samme fortegn på ≥4 af 6 symboler, begge halvdele | NEJ | 1. halvdel: 2/6, 2. halvdel: 3/6 |


## Totaler pr. halvdel

| halvdel | kørsel | n | WR_brut_% | WR_net_% | PF_brut | PF_net | PnL_brut_% | PnL_net_% | omkostning_pp |
|---|---|---|---|---|---|---|---|---|---|
| 1. halvdel | A1 | 205 | 39.02 | 38.54 | 1.27 | 1.12 | 65.68 | 33.05 | 32.63 |
| 1. halvdel | A2 | 225 | 39.11 | 35.11 | 1.39 | 1.14 | 61.53 | 25.07 | 36.46 |
| 2. halvdel | A1 | 229 | 29.26 | 29.26 | 0.76 | 0.65 | -65.28 | -102.04 | 36.76 |
| 2. halvdel | A2 | 252 | 29.76 | 26.19 | 0.73 | 0.58 | -50.43 | -89.19 | 38.76 |


### PnL og profit factor peger hver sin vej

- **1. halvdel:** A2 er dårligere på samlet PnL (+33.05% → +25.07%) men bedre på profit factor (1.12 → 1.14), og tager samtidig flere handler (205 → 225).
- **2. halvdel:** A2 er bedre på samlet PnL (-102.04% → -89.19%) men dårligere på profit factor (0.65 → 0.58), og tager samtidig flere handler (229 → 252).


En exit-regel med en reel edge forbedrer begge dele. Her afhænger svaret af hvilken metrik man vælger, og valget falder ikke ud samme vej i de to halvdele. Flip-exit lukker handler tidligere, så summen af tab bliver mindre — men kvaliteten pr. risikoenhed bliver ikke bedre. Det er hvad man ser når en regel skærer i støj frem for at fange noget reelt.


## A2 minus A1 pr. symbol

| halvdel | symbol | n_A1 | n_A2 | PnL_A1_brut | PnL_A2_brut | delta_brut | PnL_A1_net | PnL_A2_net | delta_net | fortegn_net |
|---|---|---|---|---|---|---|---|---|---|---|
| 1. halvdel | BTC/USDT | 41 | 43 | 6.503 | 0.885 | -5.62 | -3.918 | -10.049 | -6.13 | − |
| 1. halvdel | ETH/USDT | 41 | 48 | 41.433 | 21.754 | -19.68 | 31.093 | 9.728 | -21.37 | − |
| 1. halvdel | SOL/USDT | 43 | 49 | -1.394 | 20.637 | 22.03 | -12.151 | 8.327 | 20.48 | + |
| 1. halvdel | EUR/USD | 28 | 30 | 5.199 | 4.101 | -1.1 | 4.844 | 3.723 | -1.12 | − |
| 1. halvdel | GBP/USD | 25 | 27 | 6.829 | 4.503 | -2.33 | 6.299 | 3.929 | -2.37 | − |
| 1. halvdel | XAU/USD | 27 | 28 | 7.112 | 9.647 | 2.54 | 6.888 | 9.413 | 2.53 | + |
| 2. halvdel | BTC/USDT | 47 | 48 | -23.209 | -24.372 | -1.16 | -35.209 | -36.666 | -1.46 | − |
| 2. halvdel | ETH/USDT | 46 | 49 | -18.877 | -21.938 | -3.06 | -30.42 | -34.214 | -3.79 | − |
| 2. halvdel | SOL/USDT | 48 | 51 | -24.39 | -7.853 | 16.54 | -36.453 | -20.68 | 15.77 | + |
| 2. halvdel | EUR/USD | 31 | 36 | -2.414 | -3.072 | -0.66 | -2.781 | -3.502 | -0.72 | − |
| 2. halvdel | GBP/USD | 30 | 36 | 0.741 | 1.458 | 0.72 | 0.105 | 0.71 | 0.6 | + |
| 2. halvdel | XAU/USD | 27 | 32 | 2.871 | 5.344 | 2.47 | 2.718 | 5.163 | 2.45 | + |


## Hvad der IKKE er gjort

- Live-adfærd er uændret. Flip level lukker ingen handel i live.

- Ingen konfiguration, vægte eller exit-regler er ændret ud fra tallene.

- `volatility_breakout` er ikke testet: konklusionen dér (+26,45% → −2,96%) står, og VB kører uden flip-exit.
