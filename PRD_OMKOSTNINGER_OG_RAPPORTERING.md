# PRD: Omkostningsmodel, out-of-sample-test og læsbar rapportering

**Status:** Backtest-infrastruktur. **Ingen ændring af live handelsadfærd.**
**Skrevet:** 2026-09-02
**Branch:** `feature/confidence-flip-level` — fortsæt på den, opret ikke en ny
**Baggrund:** `PRD_FLIP_LEVEL_OG_CONFIDENCE.md`, `research/output/flip_level_note.md`,
`research/output/confidence_validation.md`

---

## TRIN 0 — Repoet er allerede ryddet, verificér og push

Cowork-sessionen har været inde på maskinen og ryddet op. Tilstanden pr. 2026-09-02 08:00 UTC:

- Branch: `feature/confidence-flip-level` (samme HEAD som `origin/main` før oprydningen)
- **Alt arbejdet fra forrige opgave lå ucommittet** — ~800 linjer over 18 filer plus 9 nye
  filer. Det er nu committet som `4012b1c`, inkl. alembic-migrationen, flip-level-
  instrumenteringen, `research/run_flip_confidence_study.py`, `research/stats.py`, testene
  og rapporterne.
- `research/output/confidence_validation.csv` og `flip_exit_trades.csv` er `add -f`'et forbi
  `.gitignore`, så tallene kan efterprøves.
- Efterladte git-låsefiler (`HEAD.lock`, `maintenance.lock`, 43 `tmp_obj_*`) er flyttet til
  `_to_delete/git-lock-rester/`. Cowork kan ikke slette filer på maskinen — **slet den mappe**,
  den skal ikke med i noget commit.
- Arbejdstræet er ellers rent.

Gør dette først:

1. `git log --oneline -2` — bekræft at `4012b1c` er HEAD
2. Slet `_to_delete/`
3. Kør testsuiten. Arbejdet blev committet uden at være verificeret — hvis noget fejler, så
   fiks det og commit fixet, før du går videre til DEL 1.
4. `git push -u origin feature/confidence-flip-level` (branchen er 1 commit foran remote)
5. Rapportér i sessionen: HEAD-sha, testresultat, og om træet er rent

---

## LUKKET — genåbn ikke

**Confidence-valideringen er afsluttet.** Resultatet blev "kan ikke afgøres" (n for lille),
og et afgørende svar kræver 3.000+ handler. Kør ingen flere confidence-backtests, foreslå
ingen nye vægte, og rør ikke `min_confidence: 0.45`.

**Instrumenteringen bliver stående** — `Trade.confidence` gemmes fortsat ved hver entry, så
spørgsmålet kan genåbnes når data findes. Vi dropper analysen, ikke opsamlingen.

**Gates hører til i live.** Backtesten kører permanent uden confidence-gate. Det er allerede
implementeret; lav det ikke om.

---

## DEL 1 — Omkostningsmodel i backtesten

Backtesten har i dag **ingen** omkostningsmodel. Hvert tal i projektets historie —
`trend_momentum` PF 0,98, `volatility_breakout` PF 1,16, flip-exit-resultaterne — er brutto.

### Krav

**Ny config-sektion `backtest.costs`.** Læg den for sig selv, ikke under `trading` eller
`strategies`. Den må ikke kunne påvirke live-parametre.

Pr. asset-class (crypto / forex / gold / index):
- `spread` — halvdelen på entry, halvdelen på exit
- `slippage_mean` og `slippage_std` — stokastisk, men **seedet** så kørsler er reproducerbare
- `commission` — pr. rundtur, 0 hvor den ikke findes

**Slå værdierne op, tag ikke mine.** Binance taker-fee og typiske CME-spreads for `GC`, `ES`,
`6E`, `6B` findes i børsernes egen dokumentation. **Dokumentér kilden til hvert tal** i
rapporten. Et gæt der ser præcist ud er værre end et interval der er ærligt.

### Rapportering — det vigtigste krav

**Hver metrik skal vises to gange, side om side: brutto og netto.** Ikke erstattet — begge.
Mads vil kunne se præcis hvad omkostningerne æder.

```
                        BRUTTO      NETTO     forskel
win_rate                 33.0%      33.0%       0.0pp
profit_factor             0.98       0.85      -0.13
total_pnl_pct            -1.48%     -8.20%    -6.72pp
avg_pnl_pct              -0.003%    -0.019%
```

Bemærk at win_rate kan ændre sig hvis en handel går fra marginal gevinst til marginalt tab —
rapportér det som det falder ud, forklar ikke forskellen væk.

---

## DEL 2 — Out-of-sample-test af flip-exit på trend_momentum

`trend_momentum` gik fra −1,48% (A1) til +10,26% (A2) med EMA50-flip-exit. Det er det mest
interessante resultat vi har — og det er **én in-sample kørsel på en strategi med brutto-PF
0,98**, altså dokumenteret nul-edge. Enten har exit-reglen fundet noget reelt, eller den har
passet sig til støjen i netop denne stikprøve.

### Testen

Del de 2 år i to lige halvdele. Kør A1 og A2 på **hver halvdel for sig**, alle 6 symboler.
Rapportér brutto og netto.

### Præregistreret kriterium — låst før kørsel

Flip-exit på `trend_momentum` er **bekræftet** hvis:

- A2 slår A1 i **begge** halvdele
- med **samme fortegn** på mindst 4 af de 6 symboler
- og effekten overlever omkostninger i begge halvdele

Viser effekten sig kun i den ene halvdel, er den støj. Sig det ligeud.

**Ændr ikke live-adfærd uanset udfald.** Flip level forbliver observe-only i live.
Beslutningen tages sammen med Mads bagefter.

`volatility_breakout` skal ikke testes videre på flip-exit — resultatet dér (+26,45% → −2,96%)
bekræftede en forudsigelse fra før kørslen om at breakout-retests udløser falske brud.
Konklusionen står: lad VB være uden flip-exit.

---

## DEL 3 — Læsbar rapportering i sessionen

De sidste rapporter var 8-33 kB markdown. De er gode til arkivet, men ubrugelige til at få
overblik i en samtale — særligt fra mobil.

**Fra nu af skal enhver backtest afsluttes med en kompakt tabel printet direkte i sessionen.**
Maks ~15 linjer. Fast format:

```
BACKTEST  <strategi>  <periode>  <konfiguration>
symbol        n    WR     PF-brutto  PF-netto   PnL-brutto  PnL-netto
BTC/USDT     72   34.7%      1.04      0.91        +3.2%      -1.1%
...
TOTAL       430   33.0%      0.98      0.85        -1.5%      -8.2%
```

Den detaljerede rapport ligger fortsat i `research/output/` — tabellen erstatter den ikke,
den gør den bare tilgængelig uden at åbne en fil.

Gælder alle fremtidige backtests, ikke kun denne opgave.

---

## Afgrænsning

**Må ikke ændres:** `dry_run`, `sandbox`, `leverage`, `stake_amount`, `max_open_trades`,
`total_capital`, `min_confidence`, gates, entry-logik, exit-logik i live, eller nogen
strategis signal-betingelser.

Flip level forbliver observe-only i live. Ingen auto-apply på nye felter.

## Stop bagefter

Når tabellen og rapporterne ligger: stop. Ændr ikke konfiguration ud fra resultaterne —
vi læser dem sammen først.
