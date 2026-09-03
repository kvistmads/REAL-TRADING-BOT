# Parret test af flip-exit — samme entries, kun exit varierer

**Kørt:** 2026-09-03 06:35 UTC  
**Strategi:** trend_momentum · **Periode:** 2024-09→2026-09


> **Et positivt resultat genåbner ikke flip-exit som live-ændring.** Konklusionen ville være "reglen forbedrer enkelthandler, men porteføljeeffekten er upåvist" — svagere end den påstand out-of-sample-testen afviste. Flip level forbliver observe-only.


## Hvad denne test måler, som A1/A2 ikke kunne

`run_backtest` springer markøren frem med handlens længde for at undgå overlappende positioner. En kortere exit flytter derfor alle efterfølgende entries, og A1/A2 var to forskellige vandringer gennem data. Her følger markøren **baseline**, så de to lister har identiske entries og forskellen udelukkende kommer fra exit-reglen.


## Samlet

| n_par | n_ændret | ændret_% | delta_R_gns | delta_R_median | 95%-CI (parret) | krydser_nul | bedre/værre/uændret |
|---|---|---|---|---|---|---|---|
| 434 | 260 | 59.91 | 0.0152 | 0.0 | [-0.0546, 0.0849] | ja | 169/91/174 |


### Kun de handler reglen faktisk rørte

Handler hvor flip level aldrig udløste har delta præcis 0 og fortynder gennemsnittet. En regel der rammer sjældent men hårdt ser svagere ud end den er, hvis man kun ser totalen.


| n_ændret | delta_R_gns | 95%-CI (parret) |
|---|---|---|
| 260 | 0.0253 | [-0.0912, 0.1418] |


## Pr. symbol

| symbol | n_par | n_ændret | ændret_% | delta_R_gns | delta_R_median | 95%-CI | krydser_nul | bedre | værre | uændret |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC/USDT | 88 | 47 | 53.41 | -0.0099 | 0.0 | [-0.165, 0.1453] | ja | 29 | 18 | 41 |
| ETH/USDT | 87 | 50 | 57.47 | -0.0497 | 0.0 | [-0.2073, 0.1078] | ja | 30 | 20 | 37 |
| SOL/USDT | 91 | 59 | 64.84 | 0.1122 | 0.0 | [-0.024, 0.2485] | ja | 43 | 16 | 32 |
| EUR/USD | 60 | 38 | 63.33 | -0.0664 | 0.0 | [-0.2666, 0.1339] | ja | 24 | 14 | 22 |
| GBP/USD | 54 | 34 | 62.96 | 0.0451 | 0.0 | [-0.1608, 0.2511] | ja | 20 | 14 | 20 |
| XAU/USD | 54 | 32 | 59.26 | 0.0575 | 0.0 | [-0.1492, 0.2643] | ja | 23 | 9 | 22 |


## Fortolkning

Det parrede interval **krydser nul**. Selv med entries holdt faste — den mest følsomme sammenligning vi kan lave — kan flip-exits virkning på den enkelte handel ikke skelnes fra nul. Det er en stærkere afvisning end out-of-sample-testens, fordi den parrede variant har lavere varians: handlernes fælles udsving går ud.


## Hvad der IKKE er gjort

- Live-adfærd er uændret. Flip level lukker ingen handel.

- Ingen exit-regel, tærskel eller konfiguration er ændret.

- Apparatet er bygget generelt (`exit_kwargs`), så det virker for enhver fremtidig exit-regel — ikke kun flip level.
