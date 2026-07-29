# PRD — End-to-End Integration Test

**Branch:** `main` (kør `git pull` først)  
**Mål:** Verificér at alle komponenter taler korrekt sammen end-to-end — ingen nye features, kun smoke-tests og bug-fixes.  
**Approach:** Kør systemet trin-for-trin, observer hvad der fejler, ret det.

---

## Ikke-forhandlingsbare constraints

- `dry_run: true` og `sandbox: true` MÅ aldrig begge fjernes
- Brug ALTID `.venv/bin/python` — aldrig system-python
- Ingen ændringer til live-logic, capital-parametre eller protected_parameters
- Ingen ændringer til reflection auto-apply logik

---

## Trin 1 — Miljø og imports

```bash
git pull origin main
.venv/bin/python -c "import core.engine; import core.database; import strategies.registry; import reflection.nightly; import reflection.weekly; import reflection.loop_c; import reflection.research.researcher; import reflection.news.confirmation; import status_writer; print('OK')"
```

**Forventet:** `OK` uden ImportError.  
**Fix hvis fejler:** Ret den specifikke import-fejl. Typiske årsager: manglende `__init__.py`, cirkulær import, forkert modul-sti.

---

## Trin 2 — Database initialisering

```bash
.venv/bin/python -c "
import asyncio
from core.database import init_db, init_sync_db, engine
from sqlalchemy import inspect, text

async def check():
    await init_db()
    init_sync_db()
    async with engine.begin() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        print('Tabeller:', sorted(tables))
        # Verificér kritiske kolonner
        result = await conn.execute(text('PRAGMA table_info(trades)'))
        cols = [r[1] for r in result.fetchall()]
        print('Trades-kolonner:', cols)
        assert 'strategy_id' in cols, 'MANGLER strategy_id!'
        assert 'ab_arm' in cols, 'MANGLER ab_arm!'
    print('DB OK')

asyncio.run(check())
"
```

**Forventet:** Alle tabeller til stede inkl. `trades`, `shadow_signals`, `observations`, `ab_experiments`, `backtest_results`, `promotion_alerts`. Kolonnerne `strategy_id` og `ab_arm` på `trades`.

**Fix hvis fejler:**
- Manglende tabel → kør `alembic upgrade head`
- Manglende kolonne → tjek `_apply_additive_migrations` er fjernet korrekt og Alembic-migrationen dækker kolonnen

---

## Trin 3 — Alembic-tilstand

```bash
.venv/bin/python -m alembic current
.venv/bin/python -m alembic check
```

**Forventet:** `head` på nuværende revision, ingen pending migrations.  
**Fix hvis fejler:** `alembic stamp head` på eksisterende DB, eller generer ny migration med `alembic revision --autogenerate -m "fix"`.

---

## Trin 4 — Strategy registry og signal-generering

```bash
.venv/bin/python -c "
import asyncio, ccxt.async_support as ccxt
from strategies.registry import get_registry
import pandas as pd

async def check():
    reg = get_registry()
    print('Registrerede strategier:', list(reg.keys()))
    assert len(reg) == 3, f'Forventet 3, fik {len(reg)}'
    
    # Hent rigtige data
    ex = ccxt.binance({'enableRateLimit': True})
    ohlcv = await ex.fetch_ohlcv('BTC/USDT', '1h', limit=200)
    await ex.close()
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    
    for name, cls in reg.items():
        strat = cls()
        sig = strat.generate_signal(df, 'BTC/USDT')
        print(f'{name}: signal={sig}')
    print('Strategies OK')

asyncio.run(check())
"
```

**Forventet:** Alle 3 strategier returnerer enten `None` eller et `Signal`-objekt (ikke crash). Signal kan sagtens være `None` — det er normalt.

**Fix hvis fejler:** Tjek indikator-beregninger i `data/indicators.py`. Typisk: for få datapunkter, forkerte kolonnenavne, pandas/numpy-API-ændring.

---

## Trin 5 — Engine startup (begrænset kørsel)

Kør engine i 90 sekunder og observér output:

```bash
timeout 90 .venv/bin/python main.py 2>&1 | head -100
```

**Observer:**
- Starter uden crash
- Logger `dry_run=True` og `sandbox=True` ved opstart
- Fetcher OHLCV-data for alle 6 symboler
- Kører tick-loop mindst én gang
- Skriver `bot_status.json` (tjek at filen eksisterer efter kørsel)
- Logger gate-beslutninger (confidence/regime/risk)

```bash
# Efter de 90 sek:
ls -la bot_status.json
.venv/bin/python -c "import json; d=json.load(open('bot_status.json')); print(list(d.keys()))"
```

**Forventet:** `bot_status.json` eksisterer og indeholder nøglerne `mode`, `portfolio`, `gates`, `regime`, `positions`, `recent_trades`, `strategies`, `reflection`.

**Fix hvis fejler:**
- Engine crasher ved opstart → typisk DB-fejl eller import-fejl (se Trin 1-2)
- `bot_status.json` skrives ikke → tjek at `write_status()` kaldes i engine `__init__` og `_tick`
- Ingen data for forex/gold → yfinance-symbol forkert (tjek `6E=F`, `6B=F`, `GC=F`)

---

## Trin 6 — Reflection loops (dry-run)

```bash
# Loop A — nightly (ingen DB-trades endnu, skal håndteres gracefully)
.venv/bin/python reflection/nightly.py --dry-run 2>&1 | tail -30

# Loop B — weekly
.venv/bin/python reflection/weekly.py --dry-run 2>&1 | tail -30

# Loop C — news intelligence
.venv/bin/python reflection/loop_c.py --dry-run 2>&1 | tail -30
```

**Forventet:**
- Alle 3 kører til ende uden exception
- Loop A: `"0 trades to analyse"` eller tilsvarende (ingen trades i DB endnu = normalt)
- Loop B: Rapport genereres (tom men valid)
- Loop C: Shadow signals forsøges (kan få 0 ved ingen news-API-key = OK)

**Fix hvis fejler:**
- `ANTHROPIC_API_KEY` ikke sat → offline mode (0 observationer, ingen fejl = korrekt behavior)
- Loop A crasher på 0 trades → tjek `_analyse_trades` håndterer tomt DataFrame
- Loop C crasher på news-fetch → tjek fetcher returnerer `[]` ved fejl (ikke exception)
- Research-lag fejler → tjek `strategy_db.py` loader korrekt, `backtest_reader.py` håndterer tom `BacktestResult`-tabel

---

## Trin 7 — Research layer (isoleret)

```bash
.venv/bin/python -c "
from reflection.research.researcher import Researcher
from reflection.research import strategy_db, backtest_reader

# Curated viden (altid offline)
rec = strategy_db.get_benchmarks('trend_momentum')
print('Benchmarks:', rec)
assert rec is not None

# Researcher without web (default)
r = Researcher(enable_web=False)
ctx = r.build_context('trend_momentum', 'BTC/USDT')
print('Context (første 200 chars):', ctx[:200])
print('Research OK')
"
```

**Forventet:** Returnerer en ikke-tom kontekst-streng med curated benchmarks. `backtest_reader` returnerer gracefully tom tabel.

---

## Trin 8 — News confirmation hook (isoleret, default OFF)

```bash
.venv/bin/python -c "
from reflection.news.confirmation import apply_confirmation
from strategies.base import Signal
import datetime

# Verificér hook er isoleret og ikke fejler
sig = Signal(side='long', confidence=0.75, symbol='BTC/USDT', strategy_id='trend_momentum', timestamp=datetime.datetime.utcnow())
result = apply_confirmation(sig, symbol_accuracy=0.65, latest_shadow=None)
print('Hook result:', result)
print('Confidence after (ingen shadow):', result.confidence)
print('Confirmation hook OK')
"
```

**Forventet:** Returnerer `Signal`-objekt. Confidence uændret (ingen shadow signal = ingen justering).

---

## Trin 9 — Backtest (ét symbol)

```bash
.venv/bin/python backtest/runner.py --strategy trend_momentum --symbol BTC/USDT 2>&1 | tail -20
```

**Forventet:** Kører til ende, printer performance-metrics, ingen crash. Gemmer IKKE til DB (kun `--all` gør det).

---

## Trin 10 — Fuld test-suite

```bash
.venv/bin/python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```

**Forventet:** 136 passed, 0 failed. Undersøg og fix alle fejl.

---

## Trin 11 — APScheduler job-registrering

```bash
.venv/bin/python -c "
# Verificér at parse_cron og schedule-setup virker
from main import parse_cron
import yaml

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

refl = cfg.get('reflection', {})
loops = {
    'nightly': refl.get('schedule', {}).get('nightly', '0 2 * * *'),
    'weekly':  refl.get('schedule', {}).get('weekly',  '0 3 * * 0'),
    'loop_c':  refl.get('schedule', {}).get('loop_c',  '0 */2 * * *'),
}
for name, cron in loops.items():
    fields = parse_cron(cron)
    print(f'{name}: {cron} → {fields}')
print('APScheduler cron OK')
"
```

**Forventet:** Alle 3 cron-udtryk parses korrekt til APScheduler-felt-dict.

---

## Trin 12 — Dashboard smoke-test

1. Start engine i baggrunden: `.venv/bin/python main.py &`
2. Vent 10 sekunder
3. Start HTTP-server: `.venv/bin/python -m http.server 8000 &`
4. Åbn `http://localhost:8000/dashboard.html` i browser
5. Verificér: badge viser "DRY_RUN" (ikke "DEMO DATA"), portfolio og gates vises

Cleanup: `kill %1 %2`

---

## Acceptkriterier

Alle trin 1–11 kører uden fejl. Trin 12 viser "DRY_RUN" i dashboardet.

Når alt er grønt: `git add -A && git commit -m "fix(integration): pre-papertrading smoke-test fixes"` og PR.

---

## Ikke i scope

- Live trading (Phase 6)
- MEXC API-keys
- Telegram-godkendelse (kræver bot-token og chat-ID)
- Backtest `--all` (lang kørsel, netværksafhængig)
- Web-søgning i research (kræver `reflection.research.web_search: true` i config)
