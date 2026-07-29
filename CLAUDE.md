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

## Backtest
`backtest/runner.py` henter data fra to kilder: Binance (ccxt) til crypto,
yfinance til forex/gold (`EUR/USD`, `GBP/USD`, `XAU/USD`).

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
  `bot_status.json` (atomisk skriv) ved opstart + throttlet til hvert 60. sek. (`_STATUS_INTERVAL`).
  Dashboardet er statisk HTML der poller JSON'en (server med `python -m http.server`; viser
  DEMO DATA hvis filen mangler). Loop C-sektion viser shadow-signal-accuracy pr. symbol.
- **News confirmation-hook (Del C)**: `core/engine._apply_news_confirmation` → ren logik i
  `reflection/news/confirmation.py`. Justerer signal-confidence (+boost ved match / -damp ved
  konflikt) ud fra `get_symbol_accuracy` + seneste shadow signal. **Default OFF** via
  `reflection.news_intelligence.confirmation_hook.enabled=false` — aktiveres manuelt.
- **Alembic**: erstatter `_apply_additive_migrations` (fjernet). `alembic/env.py` bruger
  `core.database.Base` + `SYNC_DATABASE_URL` (override med `-x dburl=...`), `render_as_batch=True`
  for SQLite. `create_all` er stadig bootstrap (tests + nye tabeller); NYE KOLONNER på
  eksisterende tabeller kræver `alembic upgrade head`. Eksisterende DB'er stamps: `alembic stamp head`.

## Ikke bygget endnu (Phase 6+)
Live trading + MEXC API-keys (Phase 6), confluence-gate (forbliver OFF),
FastAPI-dashboard (HTML-dashboardet dækker behovet), Twitter/X, multi-exchange.
EMA Crossover / SR Breakout som standalone (absorberet i composites);
webhook-server til Telegram-godkendelse (long-polling `getUpdates` bruges).

**Phase 5-afvigelser fra PRD**: `_apply_news_confirmation` køres EFTER `generate_signal`
(hooket justerer et eksisterende signals confidence — kan ikke køre før signalet findes);
research-web-søgning er config-gated OFF som default (reliability); `status_writer.py`/
`dashboard.html` blev bygget fra bunden (PRD antog de fandtes).
