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

## Ikke bygget endnu
Live trading, confluence-gate (forbliver OFF), FastAPI-dashboard.
EMA Crossover / SR Breakout som standalone (absorberet i composites).
