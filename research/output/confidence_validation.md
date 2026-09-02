# Virker confidence-scoren?

**Kørt:** 2026-09-01 20:01 UTC  
**Data:** 4h, 6 symboler, 2024-08-29 → 2026-09-01  
**Backtest:** ingen confidence-gate (strategien kaldes med `min_confidence: 0.0`); live-tærsklen er uændret 0.45

> Forskningskørsel. `config.yaml`, databasen og live-adfærden er urørt.

## Svar

**Kan ikke afgøres med denne stikprøve.** Kriteriet krævede ≥150 handler pr. kvartil pr. strategi, og det har vi ikke. Et resultat under den mindst detekterbare forskel (kolonnen `min_detectable_pp` nedenfor) er ikke bevis for at scoren ikke virker — det er fravær af bevis.

### Hvor meget filtrerer gaten overhovedet?

| strategi | signaler | over 0,45 | afvist af gaten | afvist % | laveste confidence set |
|---|---|---|---|---|---|
| trend_momentum | 434 | 431 | 3 | 0.7 | 0.3978 |
| volatility_breakout | 252 | 252 | 0 | 0.0 | 0.5478 |


`min_confidence: 0.45` afviser **3 af 686** genererede signaler. Det er et selvstændigt fund uafhængigt af om scoren diskriminerer: en gate der ikke afviser noget kan hverken koste eller gavne. For en strategi hvis laveste observerede confidence ligger OVER tærsklen, er gaten aritmetisk inaktiv.

### Præregistreret kriterium (låst før kørsel)

Scoren virker hvis øverste kvartil slår nederste med **≥5.0 pp win_rate**, på **begge** strategier, med **≥150 handler pr. kvartil pr. strategi**, og med samme fortegn på mindst **4 af 6 symboler**.

| strategi | gap_pp | 95%-CI (pp) | n_top/n_bund | gap≥5.0 | n≥150 | symboler med + | min. synlig forskel (pp) |
|---|---|---|---|---|---|---|---|
| trend_momentum | -3.67 | [-16.19, 9.01] | 109/109 | nej | NEJ | 2/6 | 18.59 |
| volatility_breakout | -12.7 | [-27.87, 3.31] | 63/63 | nej | NEJ | 1/6 | 24.45 |


### Statistisk styrke — en reel begrænsning, ikke en formalitet

For at se et gab på 5 pp med 80% styrke kræves ~1.566 handler pr. bånd. Kolonnen `min_detectable_pp` ovenfor er hvad stikprøven her realistisk kan afsløre. Ligger det målte gab under den, er konklusionen **"kan ikke afgøres"** — ikke "virker ikke".


## trend_momentum

434 signaler, 434 med et rigtigt udfald. 431 ville have passeret live-gaten. Samlet win rate: 33.64%.


### Confidence-kvartiler

| band | conf_min | conf_max | n | wins | win_rate_pct | wr_ci_low_pct | wr_ci_high_pct | avg_pnl_pct | profit_factor |
|---|---|---|---|---|---|---|---|---|---|
| (0.397, 0.631] | 0.3978 | 0.6308 | 109 | 42 | 38.53 | 29.93 | 47.91 | 0.0663 | 1.078 |
| (0.631, 0.706] | 0.6309 | 0.7062 | 108 | 35 | 32.41 | 24.32 | 41.71 | -0.1547 | 0.866 |
| (0.706, 0.793] | 0.7064 | 0.7928 | 108 | 31 | 28.7 | 21.02 | 37.85 | -0.0993 | 0.931 |
| (0.793, 0.886] | 0.7929 | 0.8864 | 109 | 38 | 34.86 | 26.57 | 44.19 | 0.1718 | 1.13 |


**Monotoni:** 1 af 3 trin stiger (rang-korrelation bånd↔win_rate: -0.4). Ikke strengt stigende — et enkelt bånd der stikker ud er støj.


### Korrelation

- confidence ↔ `won` (punkt-biseriel): r=-0.006 (p=0.8953, n=434)

- confidence ↔ `pnl_pct` (Spearman): r=-0.037 (p=0.4480, n=434)


### Delkomponenter

Ét led kan bære al information mens resten er støj — eller pege den forkerte vej. Negativ `corr_won` betyder at leddet trækker confidence op netop når handlen taber.


| component | n | corr_won | p_won | spearman_pnl | p_pnl |
|---|---|---|---|---|---|
| trend_strength | 434 | 0.0203 | 0.67318 | -0.041 | 0.39477 |
| cross_strength | 434 | -0.031 | 0.51886 | -0.0053 | 0.91233 |
| rsi_room | 434 | -0.0306 | 0.52493 | 0.0175 | 0.71601 |


**Multiple sammenligninger:** der er kørt 6 tests i denne tabel (hver komponent mod både `won` og `pnl_pct`), og over begge strategier 12 i alt. Ved alpha 5% forventes cirka én p-værdi under 0,05 ved rent tilfælde. En enkelt grænsesignifikant komponent er derfor ikke et fund — den skal gentages ud af stikprøven før den betyder noget.


### Effekten af 0.65 → 0.45

| bånd | n | win_rate_pct | 95%-CI (pp) | avg_pnl_pct |
|---|---|---|---|---|
| over 0,65 (gammel tærskel) | 293 | 32.08 | [27.0, 37.63] | -0.0344 |
| ekstra: 0,45–0,65 | 138 | 36.96 | [29.36, 45.26] | 0.0585 |
| under 0,45 (handles aldrig live) | 3 | 33.33 | [6.15, 79.23] | 0.1747 |


De ekstra handler ligger **4.87 pp** fra dem over 0,65 (95%-CI [-4.53, 14.61] pp).


### Pr. symbol (øverste mod nederste halvdel)

| symbol | n | n_high | n_low | wr_high_pct | wr_low_pct | gap_pp | sign |
|---|---|---|---|---|---|---|---|
| BTC/USDT | 88 | 44 | 44 | 31.82 | 31.82 | 0.0 | 0 |
| ETH/USDT | 87 | 44 | 43 | 34.09 | 34.88 | -0.79 | - |
| EUR/USD | 60 | 30 | 30 | 23.33 | 43.33 | -20.0 | - |
| GBP/USD | 54 | 27 | 27 | 22.22 | 48.15 | -25.93 | - |
| SOL/USDT | 91 | 46 | 45 | 36.96 | 26.67 | 10.29 | + |
| XAU/USD | 54 | 27 | 27 | 40.74 | 33.33 | 7.41 | + |


## volatility_breakout

252 signaler, 252 med et rigtigt udfald. 252 ville have passeret live-gaten. Samlet win rate: 31.75%.


### Confidence-kvartiler

| band | conf_min | conf_max | n | wins | win_rate_pct | wr_ci_low_pct | wr_ci_high_pct | avg_pnl_pct | profit_factor |
|---|---|---|---|---|---|---|---|---|---|
| (0.547, 0.644] | 0.5478 | 0.6427 | 63 | 23 | 36.51 | 25.72 | 48.85 | 0.4514 | 1.423 |
| (0.644, 0.773] | 0.6441 | 0.7729 | 63 | 20 | 31.75 | 21.59 | 44.0 | -0.1143 | 0.904 |
| (0.773, 0.826] | 0.7731 | 0.8263 | 63 | 22 | 34.92 | 24.33 | 47.25 | 0.3801 | 1.432 |
| (0.826, 0.913] | 0.8267 | 0.9127 | 63 | 15 | 23.81 | 14.99 | 35.64 | -0.2973 | 0.785 |


**Monotoni:** 1 af 3 trin stiger (rang-korrelation bånd↔win_rate: -0.8). Ikke strengt stigende — et enkelt bånd der stikker ud er støj.


### Korrelation

- confidence ↔ `won` (punkt-biseriel): r=-0.093 (p=0.1416, n=252)

- confidence ↔ `pnl_pct` (Spearman): r=-0.050 (p=0.4254, n=252)


### Delkomponenter

Ét led kan bære al information mens resten er støj — eller pege den forkerte vej. Negativ `corr_won` betyder at leddet trækker confidence op netop når handlen taber.


| component | n | corr_won | p_won | spearman_pnl | p_pnl |
|---|---|---|---|---|---|
| squeeze_intensity | 252 | -0.105 | 0.09641 | -0.069 | 0.27531 |
| volume_strength | 252 | -0.091 | 0.14995 | -0.0758 | 0.23061 |
| macd_strength | 252 | 0.0732 | 0.24713 | 0.1239 | 0.04939 |


**Multiple sammenligninger:** der er kørt 6 tests i denne tabel (hver komponent mod både `won` og `pnl_pct`), og over begge strategier 12 i alt. Ved alpha 5% forventes cirka én p-værdi under 0,05 ved rent tilfælde. En enkelt grænsesignifikant komponent er derfor ikke et fund — den skal gentages ud af stikprøven før den betyder noget.


### Effekten af 0.65 → 0.45

| bånd | n | win_rate_pct | 95%-CI (pp) | avg_pnl_pct |
|---|---|---|---|---|
| over 0,65 (gammel tærskel) | 187 | 29.95 | [23.84, 36.86] | -0.0456 |
| ekstra: 0,45–0,65 | 65 | 36.92 | [26.23, 49.08] | 0.5381 |


De ekstra handler ligger **6.98 pp** fra dem over 0,65 (95%-CI [-5.76, 20.58] pp).


### Pr. symbol (øverste mod nederste halvdel)

| symbol | n | n_high | n_low | wr_high_pct | wr_low_pct | gap_pp | sign |
|---|---|---|---|---|---|---|---|
| BTC/USDT | 50 | 25 | 25 | 24.0 | 24.0 | 0.0 | 0 |
| ETH/USDT | 58 | 29 | 29 | 27.59 | 17.24 | 10.34 | + |
| EUR/USD | 31 | 16 | 15 | 37.5 | 53.33 | -15.83 | - |
| GBP/USD | 30 | 15 | 15 | 26.67 | 40.0 | -13.33 | - |
| SOL/USDT | 50 | 25 | 25 | 20.0 | 48.0 | -28.0 | - |
| XAU/USD | 33 | 17 | 16 | 41.18 | 43.75 | -2.57 | - |


## Hvad der IKKE er gjort

- `config.yaml` er urørt. `strategies.min_confidence: 0.45` står som den var.

- Ingen nye vægte foreslås. At tune formlen indtil båndene adskiller sig er fitting, ikke måling; et forslag skal testes ud af stikprøven.

- Ingen ændring af exits, gates eller entry-logik.


## Forbehold ved stikprøven

- Backtesten springer frem til en åben handel er lukket, så signaler der opstår mens en position er åben kommer ikke med. Springet afhænger af den FORRIGE handels varighed, ikke af det aktuelle signals confidence, så udvalget er kun svagt afhængigt af det vi måler — men det er ikke nul.

- `end_of_data`-handler indgår ikke: de har ingen exit og dermed intet udfald.

- Kvartilgrænserne er stikprøveafhængige og flytter sig med nye data.
