# R-census: fallback-stops, datakvalitet og R-skala

**Kørt:** 2026-09-02 17:58 UTC  
**Strategi:** trend_momentum  
**Handler i alt (lukkede):** 432


## 1. Hvor mange handler hviler på et ikke-ATR-stop?

**0 af 432 (0.00%)** brugte config'ens faste `sl_pct` i stedet for ATR. **0** handler har intet gyldigt R (stop lig entry, eller ikke-endelig risiko).


Grænsen for at blande dem ind i R-tabellerne er 2%: **under grænsen** — de medregnes, og antallet står her.


### Pr. symbol og halvdel

| symbol | n | atr_stop | signal_stop | fallback_stop | fallback_pct | atr_nan | atr_zero | atr_missing | uden_R | halvdel |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC/USDT | 41 | 41 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 1. halvdel |
| BTC/USDT | 47 | 47 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 2. halvdel |
| ETH/USDT | 41 | 41 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 1. halvdel |
| ETH/USDT | 46 | 46 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 2. halvdel |
| SOL/USDT | 43 | 43 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 1. halvdel |
| SOL/USDT | 48 | 48 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 2. halvdel |
| EUR/USD | 28 | 28 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 1. halvdel |
| EUR/USD | 30 | 30 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 2. halvdel |
| GBP/USD | 25 | 25 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 1. halvdel |
| GBP/USD | 29 | 29 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 2. halvdel |
| XAU/USD | 27 | 27 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 1. halvdel |
| XAU/USD | 27 | 27 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | 2. halvdel |


## 2. Datakvalitet — flade barer

Flade barer (`High == Low`) opdigter en volatilitet på nul og giver ATR(14) == 0. De kontaminerede `GC=F` i daily bias-testen.


| symbol | barer | fra | til | flade_barer | flade_pct | nul_volumen | nul_volumen_pct |
|---|---|---|---|---|---|---|---|
| BTC/USDT | 4400 | 2024-08-30 | 2026-09-02 | 0 | 0.0 | 0 | 0.0 |
| ETH/USDT | 4400 | 2024-08-30 | 2026-09-02 | 0 | 0.0 | 0 | 0.0 |
| SOL/USDT | 4400 | 2024-08-30 | 2026-09-02 | 0 | 0.0 | 0 | 0.0 |
| EUR/USD | 3112 | 2024-09-03 | 2026-09-02 | 0 | 0.0 | 3 | 0.1 |
| GBP/USD | 3112 | 2024-09-03 | 2026-09-02 | 0 | 0.0 | 2 | 0.06 |
| XAU/USD | 3114 | 2024-09-03 | 2026-09-02 | 0 | 0.0 | 3 | 0.1 |


## 3. ATR i procent — kan procent-tal sammenlignes på tværs?

| symbol | asset_class | ATR_pct_median | ATR_pct_q1 | ATR_pct_q3 | atr_nul_barer |
|---|---|---|---|---|---|
| BTC/USDT | crypto | 1.2364 | 1.0059 | 1.5737 | 0 |
| ETH/USDT | crypto | 1.9216 | 1.5436 | 2.318 | 0 |
| SOL/USDT | crypto | 2.2586 | 1.8542 | 2.7645 | 0 |
| EUR/USD | forex | 0.2396 | 0.1883 | 0.3037 | 0 |
| GBP/USD | forex | 0.2418 | 0.2123 | 0.2802 | 0 |
| XAU/USD | gold | 0.8253 | 0.5444 | 1.043 | 0 |


## 4. R-skala pr. symbol

| symbol | gruppe | n | 1R_i_%_median | 1R_i_%_iqr | PnL/handel_% | PnL/handel_R | omkost_bp | omkost_R |
|---|---|---|---|---|---|---|---|---|
| BTC/USDT | krypto | 88 | 2.418 | 1.1 | -0.4446 | -0.1609 | 25.0 | 0.1076 |
| ETH/USDT | krypto | 87 | 3.731 | 1.584 | 0.0077 | -0.0039 | 25.0 | 0.0729 |
| EUR/USD | ikke-krypto | 58 | 0.525 | 0.201 | 0.0214 | -0.022 | 1.14 | 0.0259 |
| GBP/USD | ikke-krypto | 54 | 0.5 | 0.115 | 0.127 | 0.1708 | 1.97 | 0.0415 |
| SOL/USDT | krypto | 91 | 4.49 | 1.878 | -0.5341 | -0.1152 | 25.0 | 0.0611 |
| XAU/USD | ikke-krypto | 54 | 1.643 | 0.912 | 0.1779 | 0.1491 | 0.673 | 0.0051 |


### Fordelingen af 1R (median + interkvartilafstand)

| symbol | n | 1R_pct_median | 1R_pct_q1 | 1R_pct_q3 | 1R_pct_iqr |
|---|---|---|---|---|---|
| BTC/USDT | 88 | 2.4183 | 1.9967 | 3.0969 | 1.1002 |
| ETH/USDT | 87 | 3.731 | 2.9569 | 4.5413 | 1.5844 |
| EUR/USD | 58 | 0.525 | 0.3981 | 0.599 | 0.201 |
| GBP/USD | 54 | 0.5004 | 0.4484 | 0.5632 | 0.1148 |
| SOL/USDT | 91 | 4.4901 | 3.5074 | 5.3852 | 1.8778 |
| XAU/USD | 54 | 1.6429 | 1.1151 | 2.0268 | 0.9117 |


### De fem største r_multiples i absolut værdi

Et meget stramt stop giver et lille R, og så bliver et normalt kursudsving til et enormt R-multiple. Sådanne outliers kan trække et gennemsnit alene.


| symbol | side | entry_time | risk_pct | stop_source | pnl_pct | r_multiple_net | reason |
|---|---|---|---|---|---|---|---|
| XAU/USD | long | 2026-02-18 11:00:00 | 2.36944 | atr | 4.7389 | 1.9977 | take_profit |
| XAU/USD | long | 2025-04-09 00:00:00 | 3.363327 | atr | 6.7267 | 1.9975 | take_profit |
| XAU/USD | short | 2026-06-01 12:00:00 | 1.765043 | atr | 3.5301 | 1.9973 | take_profit |
| XAU/USD | short | 2026-04-28 00:00:00 | 1.539387 | atr | 3.0788 | 1.9972 | take_profit |
| XAU/USD | long | 2026-01-09 07:00:00 | 1.411602 | atr | 2.8232 | 1.9968 | take_profit |
