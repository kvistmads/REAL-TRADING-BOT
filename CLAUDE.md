# CLAUDE.md — REAL TRADING BOT

Dry-run/paper trading-bot. Kør ALTID via `.venv`:

```bash
.venv/bin/python main.py
.venv/bin/python -m pytest tests/ -v
.venv/bin/pip install --only-binary=:all: -r requirements.txt
```

## Indikator-motor
`data/indicators.py` er ren pandas/numpy (IKKE pandas-ta — se `requirements.txt`
for hvorfor den ikke kan køre på numpy 2.x/pandas 3.x). To API'er:
- `add_*(df)` muterer df med pandas-ta-kompatible kolonnenavne (bruges af engine/regime-gate).
- `calculate_*(df)` returnerer Series/DataFrame (bruges af composite-strategierne).

## Strategier (Phase 3 — composites)
- [x] strategies/trend_momentum.py      — composite 1 (PRD 1; absorberer macd_volume + ema_crossover)
- [x] strategies/reversal_context.py    — composite 2 (PRD 2; absorberer rsi_divergence)
- [x] strategies/volatility_breakout.py — composite 3 (PRD 3; absorberer bollinger_squeeze + sr_breakout)

Registry (`strategies/registry.py`) auto-discoverer alle `BaseStrategy`-subklasser i
`strategies/`; kun de 3 ovenstående filer findes, så kun de 3 registreres.
Aktivering + `min_confidence` styres i `config.yaml` (`strategies.min_confidence`, nu 0.45).
Engine sender den ned som base-param via `_config_params()`, så den vinder over
klasseattributten `min_confidence = 0.65`; `strategies.params.<id>.min_confidence`
vinder til gengæld over den globale.

## Datakilder (live + backtest)
Både `data/fetcher.py` (live) og `backtest/runner.py` bruger Binance (ccxt) til crypto og
yfinance til forex/gold. Symbol-mappingen `YFINANCE_SYMBOL_MAP` (`EUR/USD`→`6E=F`,
`GBP/USD`→`6B=F`, `XAU/USD`→`GC=F`) er defineret ÉT sted — `data/fetcher.py` — og importeres
af runneren, så de to aldrig kan divergere. CME-futures frem for spot fordi yfinance-spot har
100% nul-volume og nulstiller volume-gates. yfinance har ingen 4h-barer: begge sider henter 1h
og resampler. MT5 (Windows-only) bruges nu KUN til live tick-priser; uden den falder
`DataFetcher.get_latest_price()` tilbage på seneste 1h-close.

## Backtest

```bash
# Ét symbol
.venv/bin/python backtest/runner.py --strategy trend_momentum --symbol BTC/USDT
# Fuld suite (alle enabled strategier × alle symboler) + suite_DATO.csv
.venv/bin/python backtest/runner.py --all
# Kørsel A2: som ovenfor, men flip level lukker også handlen (måling, ikke live-adfærd)
.venv/bin/python backtest/runner.py --all --flip-exit
```

**Backtesten anvender ALDRIG confidence-gaten.** `run_backtest` kalder strategien med
`min_confidence: 0.0` og simulerer HVERT genereret signal; hver række markeres i stedet
med `would_pass_production` (`confidence >= strategies.min_confidence`). Det er en
permanent adskillelse af to formål — *backtesten viser alt, gaten hører til i live* —
ikke et forskningsflag: filtrerer man først og måler bagefter, kan man kun teste scoren
inden for det bånd hvor filteret allerede har virket. Kapitalen beskyttes i live, hvor
`strategies.min_confidence: 0.45` står uændret. Overlappende positioner undgås stadig
(spring frem til handlen er lukket) — det er porteføljekontrakten, ikke et confidence-filter.

## Learning loop (Phase 4 — reflection/)
To feedback-loops der forbedrer botten uden at røre kapital-parametre eller live-logik.
Kør ALTID via `.venv`. Uden `ANTHROPIC_API_KEY` kører analysten offline (0 observationer,
ingen fejl) — så `--dry-run` virker uden nøgle.

```bash
.venv/bin/python reflection/nightly.py --dry-run   # Loop A: trade-analyse (apply intet)
.venv/bin/python reflection/weekly.py  --dry-run   # Loop B: arkitektur-analyse (rapport only)
```

- **Loop A (`nightly.py`)**: analyserer lukkede trades i tre lag, kører hver observation
  gennem `confidence_gate` (guardrails) → `auto_apply` / `telegram_approval` / `report_only`.
  Vinduet er `reflection.nightly.lookback_hours` (24) — ikke dage. Extractor/signal-analyse
  tager nu TIMER (`lookback_hours`). Med 30 dage rapporterede den de samme gamle rækker nat
  efter nat; den lange historik hører til i weekly.
- **Loop B (`weekly.py`)**: arkitektur/performance-analyse af kodebasen — auto-applier ALDRIG.
- Reflection er **synkron** (egen `sync_engine`/`sync_session_maker` i `core/database.py`)
  mod samme SQLite-fil; de to nye tabeller (`observations`, `ab_experiments`) oprettes via
  `init_sync_db()` (`create_all`, additivt — ingen Alembic i projektet).
- Config i `config.yaml` under `reflection:`. Beskyttede parametre + 200-trades-gulv +
  `max_change_pct` er hard-coded i `confidence_gate` og kan ikke overrides.
- Auto-apply skriver til `strategies.params.<strategy_id>.<param>` (eller `strategies.<param>`
  hvis global), tager altid backup `config.yaml.bak.<ts>` + audit til `reflection/audit.log`.
- Scheduling: APScheduler-cron i `main.py` (kører loops i tråd via `asyncio.to_thread`).
  NB: cron dag-0 = søndag oversættes til APScheduler-navn i `parse_cron`.
- Bevidste afvigelser fra PRD: profilering kører IKKE `main.py` (uendeligt live-loop) men en
  syntetisk indikator/strategi-hot-path; A/B-armtildeling i execution er ikke wired (hård
  grænse mod live-logik); Telegram-godkendelse via long-polling `getUpdates`, ikke webhook.

## Phase 5 — Research + Dashboard + Migrationer
- **Research-lag (`reflection/research/`)**: beriger Loop A Lag 1-prompt (og Loop B-rapporten)
  med ekstern viden. `strategy_db.py` (curated benchmarks/parameter-ranges, altid offline),
  `backtest_reader.py` (læser `BacktestResult`-tabellen), `web_searcher.py` (best-effort urllib,
  returnerer ALTID `""` ved fejl), `researcher.py` (orchestrerer). Styres af `reflection.research`
  i config: `web_search: false` som default → nightly er hurtig/netværks-uafhængig; den curated
  viden dækker offline-behovet. Enheder: wr/max_dd som fraktioner (0-1), matcher `BacktestResult`.
- **Backtest → DB**: `backtest/runner.py --all` importerer nu suite-resultater til
  `BacktestResult` via `save_results_to_db` (win_rate/max_drawdown normaliseret til fraktioner,
  profit_factor=inf → None). CSV skrives stadig som før.
- **Dashboard (`dashboard.html` + `status_writer.py`)**: engine kalder `write_status` →
  `bot_status.json` (atomisk skriv) ved opstart + hvert 60. sek. fra position monitor-loopet
  (se Phase 6). Dashboardet er statisk HTML der poller JSON'en (server med
  `python -m http.server`; viser DEMO DATA hvis filen mangler). Loop C-sektion viser
  shadow-signal-accuracy pr. symbol.
- **News confirmation-hook (Del C)**: `core/engine._apply_news_confirmation` → ren logik i
  `reflection/news/confirmation.py`. Justerer signal-confidence (+boost ved match / -damp ved
  konflikt) ud fra `get_symbol_accuracy` + seneste shadow signal. **Default OFF** via
  `reflection.news_intelligence.confirmation_hook.enabled=false` — aktiveres manuelt.
- **Alembic**: erstatter `_apply_additive_migrations` (fjernet). `alembic/env.py` bruger
  `core.database.Base` + `SYNC_DATABASE_URL` (override med `-x dburl=...`), `render_as_batch=True`
  for SQLite. `create_all` er stadig bootstrap (tests + nye tabeller); NYE KOLONNER på
  eksisterende tabeller kræver `alembic upgrade head`. Eksisterende DB'er stamps: `alembic stamp head`.

## Phase 6 — To engine-loops (Del A+B, `PRD_PHASE6_FIXES.md`)
Engine'en kører nu to parallelle loops via `asyncio.gather` i `start()`:
- `_tick_loop()` — signal-generering, justeret efter bar-close: `_get_sleep_seconds()`
  sover frem til næste `timeframes.primary`-close på UTC-gitteret (4h → 00:00, 04:00, …)
  minus `TICK_CLOSE_BUFFER` (2 min). Strategierne læser `df.iloc[-1]`, så vi vil ramme den
  bar der er ved at LUKKE — et fast sleep på 14400 s fase-låste ticket dér hvor botten blev
  startet og evaluerede hver bar ~31 min inde i forløbet (~13 % volumen), hvilket gjorde
  volatility_breakout's volume-gate uopnåelig. Barens LÆNGDE hedder nu `_get_bar_seconds()`
  og er det, time-stoppet bruger. Loopet: OHLCV, indikatorer, strategier, gates,
  trade-åbning. Skriver IKKE dashboard-status.
- `_position_monitor_loop()` — sover 60 sek. pr. runde: skriver `bot_status.json` hver runde
  (`STATUS_WRITE_INTERVAL`) og kalder `_check_positions_fast()` hver time
  (`POSITION_CHECK_INTERVAL`), som henter pris for de unikke symboler med åbne positioner og
  evaluerer SL/TP. `_apply_sl_tp()` deles af begge loops. `stop()` AFLYSER tasks — ellers
  hænger nedlukningen i op til 4 timers sleep.

Priser hentes ét sted: `DataFetcher.get_latest_price()` (crypto → ccxt-ticker, forex → MT5-tick
eller seneste yfinance-1h-close). `self._last_prices` fodrer urealiseret PnL i dashboardet.

## Arkitektur-fixes (`PRD_ARCHITECTURE_FIXES.md`)
- **Exits**: SL/TP er nu volatilitetstilpasset — `SL = atr_sl_multiplier × ATR(14)`,
  `TP = tp_rr_ratio × SL-afstand` (config: `risk_defaults.<asset_class>`). `sl_pct`/`tp_pct`
  bruges KUN som fallback når ATR mangler. Chart-niveauer fra et signal vinder altid.
  Formlen findes to steder med identisk resultat (test låser det): `backtest/runner._resolve_sl_tp`
  og `engine._resolve_sl_tp(signal, price, df=...)`.
- **Breakeven**: SL flyttes til entry når prisen er `trading.breakeven_trigger_pct` (0.5) af vejen
  mod TP. Backtest: i bar-løkken → `reason="breakeven"`. Live: `Trade.breakeven_trigger` beregnes
  ved åbning, `PositionTracker.check_breakeven()` kaldes FØR `check_sl_tp()` i `_apply_sl_tp`.
- **Time-stop**: `trading.max_bars_held` (24 = 4 døgn på 4h). Backtest tjekker EFTER SL/TP i
  bar-løkken; live måler vægur-tid siden entry (`check_time_stop`). 0 slår det fra.
- **Metrics**: `end_of_data`-trades indgår IKKE i win-rate/Sharpe/drawdown/PnL. `total_trades` =
  alle, `closed_trades` = grundlaget for metrics, `open_at_end_count` = udeladte. Paper-tærsklen
  "> 20 trades" og BacktestResult-baselinen bruger `closed_trades`.
- **Fetcher**: alle yfinance/ccxt-kald går gennem retry med exponential backoff (3 forsøg, 2s/4s);
  `_validate_ohlcv` afviser tomme svar, manglende kolonner, NaN og ikke-monotone timestamps →
  `None` (caches ikke), og `get_multi` udelader symbolet.
- **Indikator-cache**: `add_all()` er memoiseret (FIFO, 50 entries) på datasættets INDHOLD — ikke
  kun indekset, som ville kollidere mellem symboler med samme længde. `add_all()` muterer ikke
  længere kalderens df. Ryd med `clear_indicator_cache()`. Strategier må ALDRIG kalde `add_all`
  selv (statisk test); engine beregner bundlen én gang pr. symbol og deler den.
- **Loop A signal-analyse**: `reflection/signal_analyzer.analyze_signals()` kører uanset antal
  lukkede trades og ender altid i rapport + Telegram. Kræver `SignalLog.gate_scores` (migration
  `7450c4f8f05d`) for at kunne navngive den afvisende gate; ældre rækker tælles som "ukendt".
- **Migrationer**: `f85e785151ca` (trades.breakeven_trigger), `7450c4f8f05d` (signals.gate_scores),
  `a3c1d9e4b217` (trades.confidence + flip level-felterne).
  Kør `.venv/bin/alembic upgrade head` på eksisterende DB'er. NB: koden skriver de nye
  kolonner fra det øjeblik den er indlæst — kører botten under launchd (KeepAlive), skal
  migrationen være kørt FØR den genstarter, ellers fejler INSERT på manglende kolonner.
- Testfixtures: `tests/fixtures/db.temp_db` (isoleret async SQLite pr. test) og
  `tests/fixtures/engine.fake_engine` (TradingEngine uden I/O).

## Omkostningsmodel + rapportering (`PRD_OMKOSTNINGER_OG_RAPPORTERING.md`)
Backtesten havde indtil 2026-09-02 **ingen** omkostningsmodel — hvert historisk tal i
projektet er brutto. `backtest/costs.py` + config-sektionen `backtest.costs` lukker hullet.

- **Egen config-sektion.** `backtest.costs` læses KUN af `backtest/costs.py`; ingen
  live-parameter kan påvirkes. Pr. asset-class (crypto/forex/gold/index) + symbol-overrides.
- **Enheder er native, ikke basispunkter.** `mode: proportional` (krypto: gebyret ER en
  brøkdel af notional) vs. `mode: contract` (futures: ticks + USD/rundtur, omregnet til en
  brøkdel ved HVER handel). Et fast bp-tal ville fryse et prisniveau ind i modellen — guld
  i 4.500 giver halvt så mange bp som guld i 2.250 for præcis samme tick.
- **6E ≠ 6B.** EUR/USD har symbol-override (tick 0,00005, notional 125.000); asset-class-
  defaulten er 6B. Ét fælles forex-tal ville overvurdere EUR/USD med ~70%.
- **Slippage er seedet** på `(slippage_seed, strategi, symbol)` via `zlib.crc32` — ét symbol
  kørt alene giver samme træk som i den fulde suite. `hash()` duer ikke (randomiseret pr.
  proces). Trækket afkortes ved 0: en markedsordre får ikke bedre pris end den stillede.
- **Kilder og antagelser: `research/output/cost_model.md`.** Kontraktspecs og gebyrsatser er
  slået op; spread på ét tick og slippage på et halvt tick er SKØN og er markeret som sådan.
- Størrelsesorden: krypto ~25 bp rundtur (domineret af Binances 0,20%), CME-kontrakterne
  0,5-2 bp. Krypto koster 12-47× mere — brutto og netto afviger derfor meget forskelligt
  pr. symbol.
- **`metrics.compute(trades, net=True)`** / `compute_both()` → `{"gross", "net"}`. Win rate
  KAN flytte sig mellem de to (marginal gevinst brutto → tab netto); det rapporteres som det
  falder ud. Paper-tærsklerne (`pass`) bedømmes nu på NETTO; brutto bevares som `pass_gross`.
  `BacktestResult`-tabellen gemmer fortsat brutto, så baselinen matcher live-paper.

**Enhver backtest afsluttes med en kompakt tabel i sessionen** (maks ~15 linjer) via
`report.format_session_table()` + `report.session_row()`. Brutto og netto står side om side,
aldrig kun det ene. De detaljerede rapporter i `research/output/` erstattes ikke — tabellen
gør resultatet læsbart uden at åbne en fil. Gælder alle fremtidige backtests.

```bash
.venv/bin/python research/run_flip_oos_test.py   # out-of-sample-test af flip-exit
```

## Flip level + confidence-instrumentering (`PRD_FLIP_LEVEL_OG_CONFIDENCE.md`)
Et **stop loss** begrænser tabet; et **flip level** er prisen hvor strategiens *begrundelse*
holder op med at gælde. De falder ikke sammen — stoppet kan rammes mens tesen er intakt,
og tesen kan falde mens handlen er i profit. Uden det split kan Loop A ikke skelne
"stoppet var for stramt" (justér stop/entry) fra "tesen var forkert" (justér signalet).

- **Strategierne** angiver `Signal.metadata["flip_level"]`: `trend_momentum` → EMA50 ved
  entry; `volatility_breakout` → `breakout_level`, altså det niveau der blev brudt
  (resistance for long, support for short) — findes altid, modsat den oprindeligt
  foreslåede modsatte side af rangen, som kunne være `None`; `reversal_context` →
  eksplicit `None` (en divergens har intet prisniveau der modbeviser den).
- **Trade** har nu `confidence`, `flip_level`, `flip_breached_at`,
  `flip_breached_before_exit` (migration `a3c1d9e4b217`, alle nullable). `confidence` og
  `flip_level` skrives ved entry og er **immutable** — håndhævet af en `before_update`-event
  i `core/database.py`, ikke af kaldernes disciplin. Ikke det samme som
  `reflection.protected_parameters`: dét beskytter en global config-værdi, det her beskytter
  én handels præmis mod at blive omskrevet efter udfaldet er kendt.
- **Brud måles på BODY CLOSE, ikke wick** (`position_tracker.is_flip_breached`) — et wick
  igennem er et sweep. Tjekket ligger i `_tick_loop` (som har OHLCV), ikke i position
  monitor-loopet (som kun har tick-priser og derfor ikke kan se forskel).
  `engine._closed_bars()` filtrerer barer der endnu ikke er lukket fra.
- **OBSERVE-ONLY i live**: bruddet registreres, handlen lukkes ikke. Backtesten kan
  besvare "ville et flip-exit have hjulpet?" gratis via `--flip-exit` (A2 mod A1-baseline);
  A2 importeres ikke til `BacktestResult`, da baseline'en skal afspejle live-adfærden.
- **Loop A** får dimensionen via `extractor.aggregate_by_confidence_quartile` /
  `aggregate_by_flip_breach` (lagt ved siden af `aggregate_by_symbol_session_regime`).
  Observationer herfra tvinges til `report_only` i `nightly.py` (`OBSERVE_ONLY_SOURCE`) —
  ingen auto-apply på uafprøvet instrumentering.
- **Forskningskørsel**: `research/run_flip_confidence_study.py` → `research/output/`
  (`confidence_validation.md`/`.csv`, `flip_level_note.md`). Statistikken ligger i
  `research/stats.py` (håndskrevet: ingen scipy på numpy 2.5).
- Config-nøglen `reflection.confidence_gate` hedder nu `reflection.proposal_gate` (modulet
  hedder stadig `confidence_gate.py`). Tre modeller har et felt der hedder `confidence` og
  betyder tre forskellige ting — hver har nu en docstring der siger hvilken den ikke er.

## Kendte forhold ved den kørende bot
Fund fra research-kørslerne der handler om **produktionen**, ikke om statistik. De er
skrevet ned her fordi de overlever de rapporter de kom fra. **Ingen af dem er rettet, og
ingen ændring er foreslået** — de står som observationer til en senere beslutning.

- **`reflection.news_intelligence`-agtig død konfiguration, nr. 1:**
  `gates.regime.volatile_min_confidence: 0.75` ramte **3 af 432 handler** i to års
  backtest. Volatile-regimet kræver ATR/close > 4%, hvilket næsten aldrig indtræffer på
  4h-barer. Tærsklen ligner en beslutning uden at være det.
- **Død konfiguration, nr. 2:** `strategies.min_confidence: 0.45` afviste **3 af 686**
  genererede signaler (`research/output/confidence_validation.md`). For
  `volatility_breakout` er den aritmetisk inaktiv — strategiens laveste observerede
  confidence er 0,548, altså over tærsklen.
  Samme mønster to gange: en indstilling der ser ud til at styre noget, men ikke gør det.
- **Regime-gaten blokerer 72,5% af `trend_momentum`s handler** i produktion, og dens
  gavn kan **ikke påvises**: tilladte handler gav +0,0651 R mod blokeredes −0,0534 R,
  men gaten vender fortegn mellem de to halvdele af perioden, og forskellen (0,12 R)
  er langt under den mindst detekterbare (0,42 R). Se `research/output/regime_gate_test.md`.
- **Gaten skelner ikke mellem "markedet er sideways" og "jeg kan ikke vurdere det".**
  `classify()` returnerer `SIDEWAYS` både ved reelt sideways-marked og ved manglende/NaN
  ADX eller for kort historik. For `trend_momentum` betyder begge dele blokering.
  (Empirisk er det ikke aktuelt: 0 af 432 handler havde ugyldig ADX.)

## Ikke bygget endnu (Phase 7+)
Live trading + MEXC API-keys (Phase 7), confluence-gate (forbliver OFF),
FastAPI-dashboard (HTML-dashboardet dækker behovet), Twitter/X, multi-exchange.
EMA Crossover / SR Breakout som standalone (absorberet i composites);
webhook-server til Telegram-godkendelse (long-polling `getUpdates` bruges).

**Phase 5-afvigelser fra PRD**: `_apply_news_confirmation` køres EFTER `generate_signal`
(hooket justerer et eksisterende signals confidence — kan ikke køre før signalet findes);
research-web-søgning er config-gated OFF som default (reliability); `status_writer.py`/
`dashboard.html` blev bygget fra bunden (PRD antog de fandtes).
