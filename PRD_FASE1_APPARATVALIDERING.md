# PRD Fase 1: Kan vores apparat finde en edge der beviseligt findes?

**Status:** Backtest og infrastruktur. **Ingen ændring af live handelsadfærd.**
**Skrevet:** 2026-09-03
**Branch:** opret `research/apparatus-validation` fra `main`
**Estimat:** to arbejdsgange, ikke én. DEL 1 og DEL 2 er infrastruktur.

---

## Hvorfor denne opgave findes

Vi har brugt uger på at måle to strategier vi selv fandt på. Begge viste sig tomme.
Apparatet fungerede — det dræbte fire hypoteser og fangede tre fejl.

Men vi ved stadig ikke om **apparatet kan finde en effekt der beviseligt findes.**
Indtil det er afklaret, ved vi ikke om de sidste ugers "ikke påvist" betød at
strategierne var tomme, eller at målingen ikke duer.

Det er hele formålet. Dette er ikke en strategiopgave — det er en test af os selv.

**Og et hul vi aldrig har lukket:** vi har aldrig sammenlignet noget med at holde
aktivet. `trend_momentum` havde PF 0,98 — men PF 0,98 mod *hvad*? Ingen af vores
tal har haft en baseline.

---

## TRIN 0

1. `git checkout main && git pull && git checkout -b research/apparatus-validation`
2. Kør testsuiten, rapportér antal grønne
3. Commit undervejs. Push når du kan; ellers sig til, så gør Mads det.

---

## DEL 1 — Daglige barer, lang historik

### Rettelse til en tidligere konklusion

Ved instrumentklasse-testen konkluderede du at dataudvidelse var umulig fordi Yahoo
capper ved 730 dage. **Det gælder kun intraday.** Daglige barer rækker årtier tilbage.
Den begrænsning var reel for 1h — den gælder ikke her.

### Krav

Hent og valider **daglige** barer, så langt tilbage som muligt:

| Instrument | Kilde | Forventet |
|---|---|---|
| XAU/USD | `data/historical_xau/XAU_1d_data.csv` | 2004–2024 (valideret) |
| GC=F | yfinance | årtier |
| EUR/USD, GBP/USD | yfinance | årtier |
| BTC, ETH | ccxt (Binance) | 2017+ |
| SPY, QQQ | yfinance | årtier |

`SPY` og `QQQ` er med som **ankre**, ikke som handelskandidater. Time-series momentum
er bedst dokumenteret på aktieindeks og futures. Kan effekten ikke findes dér, er det
apparatet der er i stykker — ikke markedet.

Kør samme kvalitetstjek som på guldserien: flade barer, huller, dækningsgrad pr. år.
Rapportér hvad der blev kasseret og hvorfor. **Reparér ingenting.**

---

## DEL 2 — Metrikker for lange horisonter, og en baseline

Apparatet rapporterer i dag win rate, profit factor og R pr. handel. Det er
metrikker for mange korte handler. En strategi der holder en position i en måned
skal måles på sin egenkapitalkurve.

### 2a. Ret en fejl i det eksisterende

`backtest/metrics.py` beregner `total_pnl_pct` som `sum(pcts)` — en naiv sum af
procenter pr. handel. Det er ikke afkast. −102% betyder ikke at kontoen var væk.

Tilføj **rigtig sammensat afkastberegning** ved siden af. Fjern ikke det gamle felt
(andre kaldere bruger det), men marker det tydeligt som en naiv sum i både kode og
rapporter.

### 2b. Nye metrikker

- `cagr` — årligt sammensat afkast
- `max_drawdown_pct` — største fald fra hidtidigt højdepunkt, på egenkapitalkurven
- `sharpe` — årliggjort, med den risikofri rente sat til nul og det dokumenteret
- `time_in_market_pct` — hvor stor en andel af tiden der var en åben position
- `longest_flat_days` — længste periode uden ny egenkapitaltop

Den sidste er den vigtigste og den mest oversete: den fortæller hvor længe Mads skal
kunne holde ud uden fremgang.

### 2c. Buy-and-hold baseline — obligatorisk fremover

**Hver eneste backtest skal fra nu af rapportere en buy-and-hold-baseline for samme
instrument og periode**, med samme metrikker.

En strategi der giver 8% om året på et aktiv der steg 40%, er ikke en god strategi.
Det har vi aldrig kunnet se, fordi vi aldrig har regnet det ud.

---

## DEL 3 — Time-series momentum, én parameter

### Reglen

```
Ved hvert månedsskifte:
    hvis afkastet over de seneste 12 måneder er positivt  -> vær long i næste måned
    ellers                                                -> vær ude af markedet
```

Det er det hele. **Én parameter: 12 måneder.**

- Ingen indikatorer, ingen filtre, ingen confidence-score, ingen gates
- Ingen stop loss og ingen take profit — positionen holdes til næste månedsskifte
- Positionsstørrelse: hele den allokerede kapital pr. instrument, ingen gearing
- Handel udføres på første bar efter månedsskiftet, til åbningskursen

**Tilføj ingenting.** Fristelsen til at "bare lige" lægge et stop på eller et filter
til, er præcis den fejl der gav os femten parametre på 430 handler. Falder resultatet
skuffende ud, er det et resultat — ikke en invitation til at justere.

Læg den som et separat researchmodul, ikke som en strategi i `strategies/`. Den skal
ikke kunne samles op af registry'et og ende i live.

### Robusthedstjek — ikke optimering

Kør også lookback på 3, 6 og 9 måneder. **Formålet er ikke at finde den bedste.** Det
er at se om resultatet er stabilt over nabolande i parameterrummet. Virker kun 12 og
ikke 9 og ikke 6, er 12 en tilfældighed.

Rapportér alle fire. Vælg ikke en vinder.

---

## DEL 4 — Testen, præregistreret

### Spørgsmålet

Kan vores apparat genfinde time-series momentum — en effekt der er dokumenteret over
mere end et århundrede og på snesevis af markeder?

### Kriteriet — låst før kørsel

**Apparatet virker** hvis alle tre holder på tværs af instrumenterne:

1. Positivt netto-afkast på mindst 4 af de 8 instrumenter
2. `max_drawdown_pct` **materielt lavere** end buy-and-hold på mindst 4 af 8
3. Samme fortegn på afkastet i mindst 3 af 4 lige lange delperioder, dér hvor
   historikken rækker

Krav 2 er det vigtigste. Litteraturens hovedfund om TSMOM er **ikke** at den slår
buy-and-hold på afkast — det er at den fanger det meste af afkastet med markant
mindre drawdown. Måler vi på afkast alene, tester vi det forkerte.

### STOP-betingelse

Fejler kriteriet — særligt på `SPY` og `GC=F`, hvor effekten er bedst dokumenteret —
så **stop og rapportér det som et fund om apparatet, ikke om strategien.**

Konklusionen ville da være: vores backtest eller vores data kan ikke genfinde en kendt
effekt, og **alle tal fra de sidste ugers arbejde er dermed uden værdi.** Det er en
ubehagelig konklusion og langt vigtigere end endnu et strategiresultat.

Led i så fald efter årsagen i denne rækkefølge, og stop ved den første du finder:
lookahead i dataindlæsningen, forkert bar-alignment, omkostningsmodellen anvendt
forkert på lange holdeperioder, eller fejl i den nye afkastberegning.

**Justér ikke strategien for at få den til at bestå.** Det ville være at reparere
termometeret ved at ændre patienten.

---

## DEL 5 — Sessionstabel

```
FASE 1  time-series momentum (12m)  <periode>
instrument   n   CAGR   maxDD   Sharpe   flat_dage | B&H CAGR   B&H maxDD
```

Maks ~15 linjer. Buy-and-hold skal stå på samme linje, ikke i et separat afsnit.

---

## Afgrænsning

**Må ikke ændres:** `dry_run`, `sandbox`, `leverage`, `stake_amount`, `max_open_trades`,
`total_capital`, `min_confidence`, gates, entry- eller exit-logik i live, nogen
eksisterende strategis signal-betingelser, `atr_sl_multiplier`, `tp_rr_ratio`,
omkostningstallene i `backtest.costs`.

TSMOM-modulet må ikke registreres som en live-strategi. Ingen nye symboler i
`config.yaml`. Botten kører videre uændret imens.

## Stop bagefter

Når tabellen og rapporten ligger: stop. Foreslå ingen strategiændringer, heller ikke
gode — og især ikke hvis resultatet ser lovende ud. Vi læser det sammen først.

Er en definition uklar — hvordan et månedsskifte defineres på krypto der handler
24/7, hvordan omkostninger skal anvendes på en position der holdes en måned — så spørg
i sessionen frem for at vælge.
