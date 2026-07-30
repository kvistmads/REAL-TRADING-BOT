# PRD — Phase 6 Fixes: Forex Fetcher + Position Monitor + Dashboard

**Branch:** `phase-6`
**Prioritet:** Blocker for paper trading — ingen af de seks symboler handler korrekt uden disse rettelser.
**Version:** 1.1 — implementeret 2026-07-30. Kodeeksemplerne herunder er den faktiske
implementation; v1.0's eksempler ramte API'er der ikke fandtes (se *Afvigelser fra v1.0*).

---

## Ikke-forhandlingsbare constraints

- `dry_run: true` og `sandbox: true` MÅ aldrig begge fjernes
- Brug ALTID `.venv/bin/python` — aldrig system-python
- Ingen ændringer til capital-parametre eller protected_parameters
- Backtest og live-fetcher skal bruge præcis samme datakilde og symbol-mapping

---

## Baggrund

Integration-testen (branch `fix/integration-smoke-test`) afslørede tre strukturelle problemer:

1. **Forex/gold fetcher bruger MT5** (kun Windows) — tre af seks symboler handler aldrig på Mac
2. **Tick-loopet kører kun hvert 4. time** — SL/TP på åbne positioner tjekkes for sjældent
3. **`_STATUS_INTERVAL = 60` er død kode** — dashboard opdateres kun hvert 4. time i stedet for løbende

---

## Del A — Forex/Gold Live Fetcher ✅

### Problem
`data/fetcher.py` sendte EUR/USD, GBP/USD og XAU/USD til MT5, som ikke er tilgængeligt på
Mac/Linux. Engine'en loggede `MT5 utilgængelig — skipper [symbol]` og sprang symbolet over
hvert tick. Prisopslaget (`get_tick_price`) var også MT5-only, så selv med OHLCV på plads
ville forex-signaler blive droppet i gate-pipelinen (`current_price is None`) og forex-
positioner aldrig få tjekket SL/TP.

`backtest/runner.py` håndterede det korrekt med yfinance og CME-futures-mapping:
```
EUR/USD  → 6E=F
GBP/USD  → 6B=F
XAU/USD  → GC=F
```

### Løsning
Forex/gold hentes fra yfinance i `data/fetcher.py` — samme kilde, mapping og bar-opbygning
som backtest-runneren. MT5 bruges kun til live tick-priser når terminalen faktisk kører.

### Implementation

**`data/fetcher.py`**

- `YFINANCE_SYMBOL_MAP` er nu **den delte kilde**: `backtest/runner.py` importerer den
  (`from data.fetcher import YFINANCE_SYMBOL_MAP as YFINANCE_MAP`), så live og backtest ikke
  kan divergere. En test asserter at det er det *samme objekt*.
- `_fetch_yfinance(symbol, timeframe, limit)` henter 1h-barer og **resampler til 4h** —
  yfinance har ingen 4h-barer, og backtesten resampler på samme måde. Uden resample ville
  live-strategierne køre på 1h-barer mens backtesten kørte på 4h.
- `_yf_period(interval, bars)` beregner kalendervinduet ud fra det ønskede antal barer
  (1.7x for weekender + margin), kappet til yfinance' grænser (1m: 7d, øvrige intraday: 730d).
- Kald er blokerende urllib → køres via `asyncio.to_thread`, så event-loopet ikke fryser
  mens `get_multi()` henter symboler parallelt.
- Output-format: kolonnerne `time/open/high/low/close/volume`, tz-naiv — identisk med
  ccxt- og MT5-pathen.

I `DataFetcher.get_ohlcv()`: `MT5Fetcher.is_forex(symbol)` → `_fetch_yfinance()`. Ingen
MT5-fallback. Cachen (TTL = timeframe) er uændret.

**Nyt: `DataFetcher.get_latest_price(symbol)`** — én indgang til prisopslag for begge
asset-klasser, erstatter `get_tick_price()` og MT5-grenen i `engine._tick()`:

| Symbol | Kilde |
|---|---|
| Crypto | ccxt-ticker (`fetch_ticker`) |
| Forex/gold + MT5 kører | MT5 tick (bid) |
| Forex/gold uden MT5 | seneste yfinance **1h**-close (ikke 4h-cachen — den er for gammel til exit-tjek) |

Returnerer `None` ved fejl; rejser aldrig.

**Verificering (kørt 2026-07-30):**
```bash
.venv/bin/python -c "
import asyncio
from data.fetcher import DataFetcher

class NoExchange:
    async def fetch_ohlcv(self, *a, **k): raise AssertionError('crypto-path')
    async def fetch_ticker(self, *a, **k): raise AssertionError('crypto-path')

async def check():
    f = DataFetcher(NoExchange(), {})
    for sym in ['EUR/USD', 'GBP/USD', 'XAU/USD']:
        df = await f.get_ohlcv(sym, '4h', 50)
        price = await f.get_latest_price(sym)
        print(sym, len(df), df['time'].iloc[-1], round(df['close'].iloc[-1], 4), price)

asyncio.run(check())
"
```
Resultat: alle tre returnerer 50 4h-barer med **0 nul-volume-barer** (pointen med CME-futures)
og en pris fra yfinance-fallbacket.

---

## Del B — Position Monitor + Tick-interval ✅

### Problem
Engine'en havde ét loop der sov `_get_sleep_seconds()` (= `timeframes.primary` = 4h) mellem
hvert tick: SL/TP blev tjekket hvert 4. time, og `bot_status.json` blev skrevet lige så sjældent.

### Løsning
To parallelle loops i `asyncio.gather`:

**`_tick_loop()` — signal-generator (hvert `timeframes.primary`)**
Fuld OHLCV-fetch, indikatorer, signaler, gates, trade-åbning. Skriver **ikke** status.

**`_position_monitor_loop()` — exit-side + dashboard**
Sover `STATUS_WRITE_INTERVAL` (60 sek) pr. runde:
- hver runde: `_write_dashboard_status()`
- hver `POSITION_CHECK_INTERVAL // STATUS_WRITE_INTERVAL` runde (= hver time):
  `_check_positions_fast()`

De to intervaller er adskilt fordi de koster vidt forskellige ting: status er DB-læsning +
atomisk diskskriv, mens SL/TP-tjek er ét netværksopslag pr. symbol med åbne positioner.
En fejl i SL/TP-tjekket blokerer ikke dashboard-skrivningen.

Når 1h-strategier tilføjes sættes `timeframes.primary: "1h"` i config — så flyder tick- og
positions-intervallet naturligt sammen.

### Implementation

**`core/engine.py`**

```python
POSITION_CHECK_INTERVAL = 3600   # SL/TP-tjek: ét prisopslag pr. symbol
STATUS_WRITE_INTERVAL = 60       # bot_status.json: kun DB + disk
```

- `start()` opretter begge loops som tasks og `gather`'er dem; `stop()` **aflyser** dem
  (ellers ville bot'en hænge op til 4 timer i `asyncio.sleep` ved nedlukning).
- `_check_positions_fast()` henter pris via `fetcher.get_latest_price()` for de **unikke**
  symboler med åbne positioner (to positioner i samme symbol = ét opslag) og kalder
  `_apply_sl_tp()`. Ingen OHLCV-fetch, ingen indikatorer, ingen signal-generering.
- `_apply_sl_tp(prices)` er udtrukket af `_tick()` og deles nu af begge loops:
  `position_tracker.check_sl_tp()` + Telegram-notifikation pr. lukket trade.
- `self._last_prices` holder seneste kendte pris pr. symbol (opdateres af begge loops) og
  bruges til urealiseret PnL i `bot_status.json`. `_write_dashboard_status()` tager derfor
  ingen argumenter længere.
- Fjernet: `_STATUS_INTERVAL`, `self._last_status_write`, `_maybe_write_status()`,
  `DataFetcher.get_tick_price()` og MT5-grenen i `_tick()`.

`position_tracker.check_sl_tp()` er **uændret** — den lukker kun i DB, aldrig via exchange,
og respekterer dermed `dry_run` som før.

**Verificering:**
```bash
.venv/bin/python main.py &
sleep 70                        # initial skriv ved opstart + monitor-skriv ved t=60s
stat -f "%Sm" bot_status.json   # timestamp skal rykke sig mellem t=15s og t=70s
kill %1
```

---

## Del C — Dashboard Status-Interval ✅

Løst af Del B: `_position_monitor_loop()` skriver `bot_status.json` hvert 60. sekund.
Ingen ændringer i `status_writer.py` eller `dashboard.html`.

---

## Test-suite

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

**179 tests grønne** (136 eksisterende + 43 nye):
- `tests/test_fetcher.py` (30) — Del A: symbol-mapping, 1h→4h-resample, kolonneformat,
  tz-håndtering, limit, tomt/fejlende svar, routing crypto vs. forex, cache, `get_latest_price`
  i alle fire grene. Ingen netværk — `yf.download` mockes.
- `tests/test_engine_monitor.py` (13) — Del B: monitor-loopets kadence (60 status-skriv pr.
  SL/TP-tjek), no-op uden åbne positioner, ét prisopslag pr. symbol, forex-positioner,
  SL-exit notificeres uden at røre exchange, `stop()` aflyser begge loops.

En test asserter eksplicit at kwargs til `yf.download` kan bindes mod yfinances signatur —
et ukendt kwarg ville ellers lande i `except`-blokken og få fetcheren til at returnere `None`
i al stilhed (præcis den fælde v1.0's kodeeksempel indeholdt).

---

## Acceptkriterier

- [x] `get_ohlcv("EUR/USD", "4h", 50)` returnerer DataFrame (ikke None) — samme for GBP/USD og XAU/USD
- [x] Forex/gold har også en **pris** (`get_latest_price`), så signaler passerer gates og SL/TP tjekkes
- [x] `bot_status.json` opdateres inden for 65 sekunder efter engine-start
- [x] 179 tests grønne
- [x] `_STATUS_INTERVAL` og `self._last_status_write` er fjernet
- [x] Backtest og live deler `YFINANCE_SYMBOL_MAP` (samme objekt, verificeret i test)

---

## Afvigelser fra v1.0

| v1.0 | Faktisk |
|---|---|
| `fetch_ohlcv()` som modul-funktion i `data/fetcher.py` | Findes ikke — routing lagt i `DataFetcher.get_ohlcv()` (async metode med cache) |
| `yf.download(..., multi_level_col=False)` | Ugyldigt kwarg → `TypeError` → fetcheren ville altid returnere `None`. Bruger i stedet manuel MultiIndex-udfladning som `backtest/runner.py` |
| `4h` → interval `1h`, ingen resample | Resampler 1h→4h, ellers kører live på andre barer end backtesten |
| Ingen omtale af tick-pris | `get_latest_price()` tilføjet — uden den var forex stadig ikke handlebart |
| `run()`, `_evaluate_exit()`, `_build_status_payload()` | Hedder `start()`, `position_tracker.check_sl_tp()` (batchvis), `_write_dashboard_status()` |
| Status skrives hvert 3600. sek | Status hvert 60. sek, SL/TP hvert 3600. sek — ellers var 65-sekunders-acceptkriteriet kun opfyldt af opstartsskrivningen |
| `YFINANCE_SYMBOL_MAP` duplikeret i to filer | Delt konstant, importeret af `backtest/runner.py` |

**Kendt kompromis:** ved hvert 4-timers tick henter forex/gold to gange fra yfinance — én gang
til prisen (1h-barer) og én gang til OHLCV (4h). To små kald pr. symbol pr. 4 timer; prisen
skal være friskere end den 4-timers bar-close for at SL/TP giver mening.

---

## Ikke i scope

- Live trading / MEXC API-keys (Phase 7)
- 1h-strategier (tilføjes separat — sæt blot `timeframes.primary: "1h"` i config)
- Confluence-gate
- Telegram-godkendelse via webhook
