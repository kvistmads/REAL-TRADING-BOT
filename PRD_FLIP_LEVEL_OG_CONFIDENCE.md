# PRD: Flip level (instrumentering) + validering af confidence-scoren

**Status:** Instrumentering og forskning. **Ingen ændring af handelsadfærd.**
**Skrevet:** 2026-08-28
**Baggrund:** `project_premarket_bias_pdf.md`, `project_daily_bias_test.md`

**Tre dele.** A og B er ren backtest og rører hverken `core/engine.py` eller databasen.
C er live-instrumentering: den *skriver* data, læser dem ikke til beslutninger.

| Del | Hvad | Rører |
|---|---|---|
| A | flip level i backtest | `backtest/runner.py` + de 2 strategier |
| B | confidence-validering i backtest | `backtest/runner.py` |
| C | live-registrering så reflection kan analysere det | migration, `core/engine.py`, `reflection/extractor.py` |

Rækkefølge: **C først** (den er tidskritisk, se nedenfor), derefter A og B som kan køres parallelt.

## LÅST — må ikke ændres i denne opgave

`strategies.min_confidence: 0.45` i `config.yaml` **bliver stående.** Mads har bevidst
valgt kvantitet frem for kvalitet i den nuværende fase for at få flere handler i DB'en.
Testen skal måle om valget koster noget — den skal ikke omgøre det.

Bemærk at dette gælder **live**. Backtesten anvender fremover slet ingen confidence-gate
(se princippet i Del B) — det er ikke en ændring af Mads' valg, men en adskillelse af to
forskellige formål.

Foreslå ikke en ændring, og ret den ikke "mens du er der". Rapportér hvad tallene viser;
beslutningen tages bagefter.

---

## Fælles rammer

**Må IKKE ændres:** `dry_run`, `sandbox`, `leverage`, `stake_amount`, `max_open_trades`,
`total_capital`, gates, exit-logik, entry-logik, eller nogen strategis signal-betingelser.

**Ingen strategi må ændre adfærd som følge af denne opgave.** Del A logger kun.

---

# DEL A — Flip level som observation

## Hvad et flip level er (og ikke er)

Et **stop loss** begrænser tabet. Et **flip level** er den pris hvor strategiens
*begrundelse* holder op med at gælde. De falder ikke sammen:

- Stoppet kan rammes mens tesen er intakt (støj)
- Flip level kan brydes mens handlen er i profit

Botten har i dag fire exit-årsager — SL, TP, breakeven, time-stop — og ingen af dem
registrerer at præmissen for handlen bortfaldt. Det er hullet denne opgave lukker.

## Hvorfor det er værd at måle

Loop A ser i dag "trend_momentum har 33% win rate". Med et flip level kan den skelne:

| Tabt fordi | Diagnose | Rettelse |
|---|---|---|
| Stop ramt, flip level intakt | tesen holdt, stoppet var for stramt | juster stop/entry |
| Flip level brudt før stoppet | tesen var forkert | juster signalet, eller drop strategien |

To modsatrettede rettelser. Uden flip level kan loopet ikke se forskel.

## Implementering

**1. Strategierne angiver flip level i `Signal.metadata["flip_level"]`** (float, pris).

Pr. strategi:

| Strategi | Forslag til flip level | Begrundelse |
|---|---|---|
| `trend_momentum` (long) | **EMA50 ved entry** — GODKENDT | tesen er "trend op"; luk under EMA50 modsiger den |
| `trend_momentum` (short) | **EMA50 ved entry** — GODKENDT | spejlvendt |
| `volatility_breakout` (long) | `support_level` (modsat side af squeeze-rangen) — FORELØBIG | tesen er "breakout ud af range"; retur ind i rangen modsiger den |
| `volatility_breakout` (short) | `resistance_level` — FORELØBIG | spejlvendt |

`trend_momentum` er godkendt af Mads. `volatility_breakout` er mit forslag og ikke
bekræftet — implementér det, men markér det i leverancen så det kan justeres billigt.

Kan en strategi ikke angive et flip level, returnér `None` og log det. **En strategi der
ikke kan formulere hvad der ville modbevise den, er en holdning, ikke en strategi** — det
er i sig selv et resultat værd at kende.

**2. Databasen:** tilføj til `trades` (Alembic-migration):

```
flip_level                REAL     NULL   -- pris, skrevet ved entry
flip_breached_at          DATETIME NULL   -- første body close igennem
flip_breached_before_exit BOOLEAN  NULL   -- blev den brudt før handlen lukkede?
```

**`flip_level` er immutabel.** Skrevet ved entry, må aldrig opdateres — heller ikke af
reflection-loopet. Det er den kodede udgave af "flip level never moved". Bemærk at dette
er noget andet end `protected_parameters` i config: dét beskytter en global indstilling,
det her beskytter en enkelt handels præmis mod at blive omskrevet bagefter.

**3. Engine tjekker hver bar — BODY CLOSE, ikke wick:**

```python
# long:  breached = bar.close < flip_level
# short: breached = bar.close > flip_level
```

Brug `close`. Ikke `low`/`high`. Et wick igennem er et sweep, ikke en invalidering.
(Samme skelnen som fejlen i `find_sr_levels` — den er rettet, hold den rettet.)

**4. OBSERVE-ONLY.** Registrér bruddet, luk IKKE handlen. Eksisterende exits er uændrede.
Formålet er at indsamle data om hvorvidt et flip-exit *ville* have hjulpet, uden at ændre
adfærd mens vi finder ud af det.

**5. Loop A får en ny dimension.** Udvid `aggregate_by_symbol_session_regime` eller tilføj
en parallel opgørelse: win_rate og avg_pnl_pct splittet på `flip_breached_before_exit`.

## To backtest-kørsler: med og uden flip-exit

I live er flip level **observe-only** — det lukker ingen handel. Men i backtest kan vi gratis
besvare spørgsmålet det udskyder: *ville det have hjulpet at lukke på flip level?*

Kør derfor begge:

| Kørsel | Exits | Formål |
|---|---|---|
| **A1 baseline** | kun de eksisterende (ATR-stop, TP, breakeven, time-stop) | referencepunkt |
| **A2 flip-exit** | de eksisterende **+ flip level lukker handlen** ved body close igennem | hvad koster/giver det? |

Sammenlign pr. strategi og pr. symbol: win_rate, profit_factor, avg_pnl_pct, antal handler,
og hvor mange handler der overhovedet blev ramt af flip-exit i A2.

Rapportér også fordelingen af **hvornår** flip level brydes: før stoppet, efter stoppet,
eller slet ikke. Det er dét tal der fortæller om tesen eller timingen fejler.

**Ændr ikke live-adfærd ud fra resultatet.** A2 er en måling, ikke en beslutning.

## Leverance del A

- Alembic-migration
- Ændringer i `core/engine.py` (tjek + logning) og de to aktive strategier (metadata)
- Tests der dækker: body close bryder, wick gør ikke, `flip_level` kan ikke opdateres
- Kort notat i `research/output/` om hvor mange handler der får et flip level

---

# DEL B — Virker confidence-scoren? (kun backtest)

## Problemet

`trend_momentum` beregner:
```
confidence = 0.35 + 0.25×trend_strength + 0.25×cross_strength + 0.15×rsi_room
```
`volatility_breakout`:
```
confidence = 0.40 + 0.20×squeeze_intensity + 0.25×volume_strength + 0.15×macd_strength
```

Vægtene er **valgt, ikke fittet**. Tallet bruges som filter i produktion. **Det er aldrig
efterprøvet.** Reflection-loopet grupperer på symbol × session × regime — ikke på confidence.
`signal_analyzer` beregner kun `avg_confidence`/`max_confidence` deskriptivt.

Ekstra hastende nu: den effektive tærskel er sænket fra 0.65 til 0.45 (commit `19dc8d0`
gjorde den globale værdi virksom). For `volatility_breakout` er gulvet i formlen 0,40 —
altså er gaten nu **næsten inaktiv**. Det er enten gratis eller dyrt, afhængigt af om
scoren diskriminerer, og det ved vi ikke.

## PRINCIP: backtesten anvender ALDRIG confidence-gaten

Dette er ikke et flag til én forskningskørsel — det er en **permanent adskillelse**:

> **Backtesten viser alt. Gaten hører til i live.**

Backtestens formål er at forstå hvordan strategien opfører sig, også når den opfører sig
dårligt. Et filter i backtesten skjuler netop de handler der lærer os mest. Live-paper er
hvor kapitalen beskyttes, og dér er `min_confidence: 0.45` Mads' bevidste kvantitetsvalg.

**Ændr `backtest/runner.py` permanent.** I dag står der omkring linje 231:

```python
min_conf = config.get("strategies", {}).get("min_confidence", strategy.min_confidence)
signal = strategy.generate_signal(window, symbol, {"min_confidence": min_conf})
if signal is not None and signal.confidence >= min_conf:
```

Backtesten skal i stedet kalde strategien med `{"min_confidence": 0.0}` og **beholde hvert
eneste genererede signal**. Simulér udfaldet for dem alle med de eksisterende exit-regler.
Markér hver række med `would_pass_production = confidence >= config.strategies.min_confidence`,
så vi kan se både hele billedet og det udsnit der faktisk handles live.

`config.yaml` røres ikke. Live-adfærd ændres ikke.

**Hvorfor det betyder noget statistisk:** filtrerer man først og måler bagefter, tester man
kun om confidence diskriminerer *inden for det bånd hvor filteret allerede har virket* — netop
hvor det betyder mindst. Simulation på en kendt effekt: sandheden var et gab på 23 pp mellem
høj og lav kvartil; målt kun over 0,45 så man 20 pp, målt kun over 0,65 så man 15 pp.
Op mod en tredjedel af effekten forsvinder, og den lave kvartil ser kunstigt god ud fordi de
dårligste signaler aldrig kom med.

## Opgaven

Kør backtest for `trend_momentum` og `volatility_breakout` over alle symboler, og gem
**confidence for hvert signal sammen med udfaldet**. Analysér derefter:

1. **Bånd-sammenligning.** Split på confidence-kvartiler (ikke faste tærskler — fordelingen
   er ukendt). Rapportér win_rate, avg_pnl_pct og profit_factor pr. kvartil, pr. strategi.
2. **Monotoni.** Stiger win_rate med confidence? Et enkelt bånd der stikker ud er støj;
   en stigende trend er signal.
3. **Korrelation.** Punkt-biseriel korrelation mellem confidence og `won`, plus Spearman
   mellem confidence og `pnl_pct`. Rapportér n og p-værdi.
4. **Delkomponenterne.** Hver af de tre-fire led (`trend_strength`, `cross_strength`,
   `rsi_room` / `squeeze_intensity`, `volume_strength`, `macd_strength`) ligger allerede i
   `Signal.metadata`. Test hver enkelt mod udfaldet. **Det er muligt at ét led bærer al
   information og resten er støj** — eller at et led har negativt fortegn.
5. **Effekten af 0.65 → 0.45.** Hvor mange ekstra handler slap igennem, og hvad var deres
   win_rate sammenlignet med dem over 0,65?

## Præregistreret kriterium — låst før kørsel

Confidence-scoren **virker** hvis:

- Øverste kvartil slår nederste kvartil med **≥5 procentpoint win_rate**
- på **begge** strategier
- med **≥150 handler pr. kvartil pr. strategi**
- og forskellen har samme fortegn på mindst 4 af de 6 symboler

**Statistisk styrke:** for at kunne se et gab på 5 pp med 80% styrke kræves ~1.566 handler
pr. bånd. Det har vi ikke. Med ~150 pr. kvartil kan vi realistisk kun se et gab på
**omkring 20 pp**. Rapportér derfor altid konfidensintervallet, og konkludér ikke
"virker ikke" på et snævert resultat — konkludér "kan ikke afgøres med denne stikprøve".
Det er en reel begrænsning, ikke en formalitet.

## Hvis scoren ikke diskriminerer

Så er `min_confidence` et filter uden indhold, og sænkningen til 0.45 kostede ingenting.
**Det er et fund, ikke en handling.** Ændr ikke config, og foreslå ikke at gaten fjernes —
rapportér det og lad Mads beslutte.

**Foreslå heller ikke nye vægte baseret på resultatet.** At tune formlen indtil båndene adskiller
sig er fitting, ikke måling. Et forslag til nye vægte skal testes ud af stikprøven i en
separat opgave.

## Leverance del B

- `research/output/confidence_validation.md` + `.csv`
- Rå data: ét signal pr. række med confidence, alle metadata-delkomponenter, og udfald

---

## Oprydning (lille, men gør det)

`strategies/base.py` har `min_confidence: float = 0.60`; de tre strategier sætter `0.65`.
Efter `19dc8d0` overskrives de af den globale `0.45` og er reelt død kode der vildleder.
Ret dem så de afspejler virkeligheden, eller tilføj en kommentar der forklarer at den
globale værdi vinder.

---

# DEL C — Live-registrering (TIDSKRITISK)

## Hvorfor det ikke kan vente på A og B

`Trade`-modellen i `core/database.py` har **ingen confidence-kolonne**. Loop A's
`extract_closed_trades` selecter fra `Trade` og kan derfor bogstaveligt talt ikke se
hvilken confidence der frembragte handlen. Det er ikke en manglende gruppering — dataene
findes ikke.

Botten kører live-paper nu og samler op mod `min_trades_for_analysis: 200`. **Hver handel
der lukkes uden at confidence og flip level er gemt, er en observation der aldrig kan
genskabes.** Rammer vi 200 uden kolonnerne, kan Loop A stadig ikke analysere det.

Derfor: kolonnerne ind nu, analysen bagefter. Instrumentering der kun skriver er billig og
ændrer ingen adfærd.

## Ændringer

**Migration** (Alembic) — tilføj til `trades`:

```
confidence                REAL     NULL   -- signalets confidence ved entry
flip_level                REAL     NULL   -- pris, skrevet ved entry
flip_breached_at          DATETIME NULL   -- første body close igennem
flip_breached_before_exit BOOLEAN  NULL
```

Alle nullable — eksisterende rækker forbliver gyldige med NULL.

**`core/engine.py`:** ved oprettelse af et Trade, kopiér `signal.confidence` og
`signal.metadata["flip_level"]` med over. Denormaliseret ved entry, præcis som
`strategy_id` allerede er. **Begge er immutable** — skrives én gang, opdateres aldrig,
heller ikke af reflection.

**Flip-tjek i engine:** hver bar, body close mod `flip_level`. Sæt `flip_breached_at`
første gang. **OBSERVE-ONLY — luk ikke handlen.** Eksisterende exits er uændrede.

**`reflection/extractor.py`:** tilføj `confidence` og `flip_breached_before_exit` til de
kolonner der hentes, og tilføj en opgørelse der splitter win_rate og avg_pnl_pct på
confidence-kvartil og på flip-brud. Rør ikke den eksisterende
`aggregate_by_symbol_session_regime` — læg det ved siden af.

## Afgrænsning for del C

- Ingen ændring af handelsadfærd. Ingen exit lukkes på flip level.
- Reflection må **ikke** auto-applye noget baseret på de nye felter endnu. Observation only,
  indtil vi har set backtest-resultatet fra del B.
- `confidence` og `flip_level` på et Trade må aldrig opdateres efter entry.

---

## De tre confidence-felter — ryd op mens du er der

`core/database.py` har tre kolonner der alle hedder `confidence` og betyder forskellige ting:

| Model | Betydning |
|---|---|
| `SignalLog.confidence` | handelssignalets styrke, fra strategiens formel |
| `Observation.confidence` | modellens tillid til sit eget parameterforslag |
| (linje ~165) | Loop C's news-shadow-signal |

**Gør:** omdøb config-nøglen `reflection.confidence_gate` → `reflection.proposal_gate`
(ingen migration), og skriv en docstring på hver af de tre modeller der siger hvilken
confidence det er **og hvilken den ikke er**.

**Gør ikke:** omdøb DB-kolonnerne. Det rører for mange filer for gevinsten.

---

## Stop bagefter

Når leverancerne ligger: stop. Ændr ikke vægte, tærskler eller exits ud fra
resultaterne — vi tager beslutningen sammen.
