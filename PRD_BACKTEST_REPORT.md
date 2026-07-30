# PRD — Fuld Backtest Suite + Rich HTML-rapport

**Branch:** `backtest/full-suite` (opret fra main)
**Formål:** Kør alle 3 strategier × 6 symboler (18 kombinationer) og præsentér resultaterne
i en selvstændig HTML-rapport med tabeller, charts og per-trade detaljer.
**Grundlag:** `backtest/runner.py --all` fungerer allerede — denne PRD udvider outputtet,
rører ikke simulation-logikken.

---

## Ikke-forhandlingsbare constraints

- `dry_run: true` og `sandbox: true` MÅ aldrig røres
- Brug ALTID `.venv/bin/python`
- Ingen ændringer til simulation-logik (`run_backtest`, `simulate_trade`, `metrics.py`)
- Rapporten er read-only output — ingen DB-writes udover hvad `--all` allerede gør

---

## Universum

**3 strategier:** trend_momentum, reversal_context, volatility_breakout

**6 symboler** (fra config.yaml):

| Symbol    | Asset-klasse | Datakilde                           | SL / TP   |
|-----------|--------------|-------------------------------------|-----------|
| BTC/USDT  | crypto       | Binance (~4400 4h barer ≈ 2 år)    | 10% / 20% |
| ETH/USDT  | crypto       | Binance (~4400 4h barer ≈ 2 år)    | 10% / 20% |
| SOL/USDT  | crypto       | Binance (~4400 4h barer ≈ 2 år)    | 10% / 20% |
| EUR/USD   | forex        | yfinance CME 6E=F (1h→4h resample) | 1.5% / 3% |
| GBP/USD   | forex        | yfinance CME 6B=F (1h→4h resample) | 1.5% / 3% |
| XAU/USD   | gold         | yfinance CME GC=F (1h→4h resample) | 3% / 6%   |

**Tærskelværdier** (eksisterende THRESHOLDS i runner.py):
- Win rate > 50%, Profit factor > 1.3, Max drawdown > -20%, Sharpe > 0.8, Trades > 20

---

## Del A — Udvidet per-trade CSV

### Problem
`_run_all()` samler `all_trades` men gemmer dem aldrig til disk.

### Løsning
Gem `all_trades` til `backtest_results/trades_YYYY-MM-DD.csv` efter suiten kører.

Kolonner: `strategy_id, symbol, side, entry_time, exit_time, entry_price, exit_price, pnl, pnl_pct, reason, bars_held`

`reason` er én af: `stop_loss`, `take_profit`, `end_of_data`.

Tilføj `_save_trades_csv(all_trades)` i `backtest/runner.py` — kaldes fra `_run_all()`.

---

## Del B — Udvidede metrics i suite-tabel og CSV

Tilføj følgende kolonner til rows-dict, suite-tabel og suite-CSV:

| Ny kolonne      | Kilde                | Beskrivelse                   |
|-----------------|----------------------|-------------------------------|
| `wins`          | m["wins"]            | Antal vindende trades         |
| `losses`        | m["losses"]          | Antal tabende trades          |
| `avg_win_pct`   | m["avg_win_pct"]     | Snit-gevinst per vinder (%)   |
| `avg_loss_pct`  | m["avg_loss_pct"]    | Snit-tab per taber (%)        |
| `avg_bars_held` | mean(bars_held)      | Gns. 4h-barer i position      |

`avg_bars_held` beregnes i `_run_all()` fra trades-listen.
Opdatér `_print_suite_table()` og `_save_suite_csv()` med nye kolonner.

---

## Del C — HTML-rapport (backtest_results/report_YYYY-MM-DD.html)

Selvstændig HTML-fil. Brug kun dette CDN:
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
```

Genereres af `generate_html_report(rows, all_trades, periods)` i `backtest/report.py`.
Kaldes fra `_run_all()` efter CSV-skrivning.

Stil — mørkt tema, samme farvepalette som dashboard.html:
```
--bg: #0b0e14; --panel: #141922; --border: #262d3d; --text: #e6e9ef;
--green: #29d391; --red: #ff5c6c; --amber: #ffb454; --blue: #4aa3ff;
```

### Sektion 1 — Header
Titel, køredato, tidsperiode pr. asset-klasse, samlet godkendt X/18.

### Sektion 2 — Heatmap (Win Rate + Profit Factor)
3×6 grid: strategier som rækker, symboler som kolonner.
Win Rate: grøn (>60%), gul (50–60%), rød (<50%).
Profit Factor: samme grid ved siden af.

### Sektion 3 — Samlet suite-tabel
Alle 18 rækker, alle Del B-kolonner. Sorterbar (klik kolonnehoved).
✅/❌ i OK-kolonne. Grøn rækkefarve ved ✅.

### Sektion 4 — Per-strategi total PnL% (3 bar charts)
Ét Chart.js bar chart pr. strategi. X: symbol, Y: total_pnl_pct.
Grøn hvis positiv, rød hvis negativ.

### Sektion 5 — Exit-årsager (3 donut charts)
Fra all_trades, gruppér pr. strategi efter reason: stop_loss, take_profit, end_of_data.
Én donut pr. strategi.

### Sektion 6 — Kumulativ PnL-kurve pr. symbol (6 line charts)
For hvert symbol: én linje pr. strategi. X: entry_time, Y: kumulativ sum(pnl_pct).

### Sektion 7 — Bars held histogram (3 charts)
Histogram pr. strategi over fordeling af bars_held.

### Sektion 8 — Månedlig performance heatmap
Aggregér all_trades pr. (strategy_id, YYYY-MM): sum(pnl_pct).
HTML-tabel: måneder som kolonner, strategier som rækker.
Grøn/rød/grå cellefarve.

---

## Del D — Kørsel og verifikation

```bash
# Kør fuld suite
.venv/bin/python backtest/runner.py --all

# Test-suite stadig grøn
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5

# Verificér output-filer
ls -lh backtest_results/

# HTML ikke-tom
wc -l backtest_results/report_*.html

# Åbn i browser
open backtest_results/report_$(date +%Y-%m-%d).html
```

**Acceptkriterie:** HTML åbner i browser, alle 8 sektioner vises med data,
alle 18 kombinationer repræsenteret, ingen tomme charts.

---

## Ikke i scope

- Ændringer i simulation-logik
- Nye strategier eller symboler
- Parameter-optimering
- Live trading
