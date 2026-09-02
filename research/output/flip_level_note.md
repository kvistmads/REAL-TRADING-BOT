# Flip level — dækning, timing og hvad et flip-exit ville have kostet

**Kørt:** 2026-09-01 20:01 UTC  
**Data:** 4h, 6 symboler, 2024-08-29 → 2026-09-01

> I live er flip level **observe-only** — det lukker ingen handel. A2 nedenfor er en måling af det spørgsmål, ikke en beslutning.


## Hvor mange handler får et flip level?

En strategi der ikke kan formulere hvad der ville modbevise den, er en holdning frem for en strategi — derfor tælles `no_flip_level` med.


| strategy_id | n_trades | with_flip_level | with_flip_level_pct | n_closed | before_exit | after_exit | never | no_flip_level |
|---|---|---|---|---|---|---|---|---|
| trend_momentum | 434 | 434 | 100.0 | 434 | 314 | 27 | 93 | 0 |
| volatility_breakout | 252 | 252 | 100.0 | 252 | 128 | 42 | 82 | 0 |


**Niveauerne:** `trend_momentum` bruger EMA50 ved entry. `volatility_breakout` bruger `breakout_level` — det niveau der faktisk blev brudt (resistance for long, support for short) — frem for den modsatte side af rangen, som kunne være `None` og først ville bryde efter en fuld rundtur. Begge findes derfor altid.


## Hvornår brydes det?

- `before_exit` — tesen var modbevist mens vi stadig sad i handlen

- `after_exit` — den holdt så længe vi var med; brud kom bagefter (inden for handlens maksimale levetid)

- `never` — holdt hele vejen


| strategy_id | flip_timing | n | win_rate_pct | wr_ci_pct | avg_pnl_pct |
|---|---|---|---|---|---|
| trend_momentum | after_exit | 27 | 18.52 | [8.2, 36.7] | 0.2414 |
| trend_momentum | before_exit | 314 | 21.66 | [17.5, 26.5] | -0.8651 |
| trend_momentum | never | 93 | 78.49 | [69.1, 85.6] | 2.8347 |
| volatility_breakout | after_exit | 42 | 14.29 | [6.7, 27.8] | -0.0412 |
| volatility_breakout | before_exit | 128 | 13.28 | [8.5, 20.2] | -1.3426 |
| volatility_breakout | never | 82 | 69.51 | [58.9, 78.4] | 2.4394 |


Det er dette split der skiller to modsatrettede rettelser: tabt med flip level intakt peger på et for stramt stop, tabt efter et brud peger på selve signalet.


### Læs IKKE forskellen mellem `never` og `before_exit` som en forudsigelse

Gabet mellem de to grupper er stort, men det er i høj grad **mekanisk, ikke prædiktivt**. Flip level ligger pr. konstruktion på handlens tabende side (EMA50 under en long-entry, det brudte niveau under et long-breakout). En handel der vinder, bevæger sig væk fra niveauet og kan derfor næsten ikke bryde det; en der taber, bevæger sig imod det. "Aldrig brudt" er langt hen ad vejen en omskrivning af "gik den rigtige vej" — ikke en uafhængig indikator man kan filtrere på.


De tal der faktisk siger noget nyt er **`before_exit` mod `after_exit`** (begge er handler hvor niveauet blev brudt — forskellen er om det skete mens vi sad i den) og **A2-sammenligningen** nedenfor, som er en ægte fremadrettet test: dér træffes en anden beslutning, og resultatet kan gå begge veje.


## A1 (baseline) mod A2 (flip-exit)

| strategy_id | symbol | a1_trades | a2_trades | a1_wr_pct | a2_wr_pct | wr_delta_pp | a1_pf | a2_pf | a1_avg_pnl_pct | a2_avg_pnl_pct | a1_total_pnl_pct | a2_total_pnl_pct | a2_flip_exits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| trend_momentum | BTC/USDT | 88 | 91 | 31.82 | 32.97 | 1.15 | 0.857 | 0.724 | -0.1898 | -0.2581 | -16.71 | -23.49 | 48 |
| trend_momentum | ETH/USDT | 87 | 96 | 34.48 | 31.25 | -3.23 | 1.155 | 0.989 | 0.2495 | -0.0119 | 21.71 | -1.15 | 57 |
| trend_momentum | EUR/USD | 60 | 67 | 33.33 | 34.33 | 1.0 | 1.197 | 1.099 | 0.0464 | 0.0159 | 2.79 | 1.07 | 44 |
| trend_momentum | GBP/USD | 54 | 62 | 35.19 | 35.48 | 0.29 | 1.543 | 1.757 | 0.1209 | 0.0978 | 6.53 | 6.06 | 40 |
| trend_momentum | SOL/USDT | 91 | 100 | 31.87 | 34.0 | 2.13 | 0.867 | 1.115 | -0.2833 | 0.1278 | -25.78 | 12.78 | 66 |
| trend_momentum | XAU/USD | 54 | 60 | 37.04 | 40.0 | 2.96 | 1.253 | 1.638 | 0.1849 | 0.2499 | 9.98 | 14.99 | 35 |
| volatility_breakout | BTC/USDT | 50 | 55 | 24.0 | 18.18 | -5.82 | 0.803 | 0.707 | -0.2172 | -0.2666 | -10.86 | -14.66 | 21 |
| volatility_breakout | ETH/USDT | 58 | 61 | 22.41 | 16.39 | -6.02 | 1.089 | 0.977 | 0.1376 | -0.0307 | 7.98 | -1.87 | 23 |
| volatility_breakout | EUR/USD | 31 | 34 | 45.16 | 38.24 | -6.92 | 2.093 | 2.327 | 0.2174 | 0.203 | 6.74 | 6.9 | 12 |
| volatility_breakout | GBP/USD | 30 | 30 | 33.33 | 30.0 | -3.33 | 0.883 | 0.889 | -0.0229 | -0.0187 | -0.69 | -0.56 | 10 |
| volatility_breakout | SOL/USDT | 50 | 53 | 34.0 | 22.64 | -11.36 | 1.185 | 1.013 | 0.3872 | 0.0223 | 19.36 | 1.18 | 23 |
| volatility_breakout | XAU/USD | 33 | 33 | 42.42 | 33.33 | -9.09 | 1.167 | 1.335 | 0.1188 | 0.1833 | 3.92 | 6.05 | 15 |


**Samlet:** 394 handler blev lukket af flip-exit i A2. Gennemsnitlig win_rate-ændring: -3.19 pp. Total PnL: 24.97% (A1) → 7.30% (A2).


## Hvad der IKKE er gjort

- Live-adfærden er uændret: flip level registreres, det lukker ingen handel.

- Ingen exit-regler, stops eller gates er ændret ud fra tallene.
