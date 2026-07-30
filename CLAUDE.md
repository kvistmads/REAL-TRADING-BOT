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
Aktivering + `min_confidence: 0.65` styres i `config.yaml`.

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
```

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
- `_tick_loop()` — signal-generering hvert `timeframes.primary` (4h): OHLCV, indikatorer,
  strategier, gates, trade-åbning. Skriver IKKE dashboard-status.
- `_position_monitor_loop()` — sover 60 sek. pr. runde: skriver `bot_status.json` hver runde
  (`STATUS_WRITE_INTERVAL`) og kalder `_check_positions_fast()` hver time
  (`POSITION_CHECK_INTERVAL`), som henter pris for de unikke symboler med åbne positioner og
  evaluerer SL/TP. `_apply_sl_tp()` deles af begge loops. `stop()` AFLYSER tasks — ellers
  hænger nedlukningen i op til 4 timers sleep.

Priser hentes ét sted: `DataFetcher.get_latest_price()` (crypto → ccxt-ticker, forex → MT5-tick
eller seneste yfinance-1h-close). `self._last_prices` fodrer urealiseret PnL i dashboardet.

## Ikke bygget endnu (Phase 7+)
Live trading + MEXC API-keys (Phase 7), confluence-gate (forbliver OFF),
FastAPI-dashboard (HTML-dashboardet dækker behovet), Twitter/X, multi-exchange.
EMA Crossover / SR Breakout som standalone (absorberet i composites);
webhook-server til Telegram-godkendelse (long-polling `getUpdates` bruges).

**Phase 5-afvigelser fra PRD**: `_apply_news_confirmation` køres EFTER `generate_signal`
(hooket justerer et eksisterende signals confidence — kan ikke køre før signalet findes);
research-web-søgning er config-gated OFF som default (reliability); `status_writer.py`/
`dashboard.html` blev bygget fra bunden (PRD antog de fandtes).
