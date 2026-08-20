# PRD: Nye profitable strategier med beviselig edge

## Kontekst — hvad botten er

Paper-trading bot (dry_run: true, sandbox: true — røres ALDRIG). Kodebase: Python 3.12,
SQLite via SQLAlchemy/Alembic, APScheduler. Altid kørt via `.venv/bin/python`.

**Symboler:** BTC/USDT, ETH/USDT, SOL/USDT, EUR/USD, GBP/USD, XAU/USD
**Timeframe:** 4h primær (1h til entry-finesse)
**Exchange:** Binance ccxt (crypto) + yfinance CME-futures (forex/gold)
**Kapital:** 100 DKK papir, stake_amount: 5, max_open_trades: 4, leverage: 1

**Dataflow:** `data/fetcher.py` → `data/indicators.py` (ren pandas/numpy, INGEN pandas-ta)
→ strategi → gates → trade

**Indikatorer tilgængelige (add_all):** EMA 20/50/200, RSI, MACD, Bollinger Bands,
ATR(14), ADX, volume MA. Engine beregner bundlen én gang pr. symbol og deler den med
alle strategier. Strategier må ALDRIG kalde `add_all()` selv.

**Gates (i rækkefølge):**
1. Regime gate — klassificerer marked som TRENDING/SIDEWAYS/VOLATILE ud fra ADX + EMA
2. Risk gate — max position size, max dagligt tab
3. Confluence gate — slået FRA

**Exits:** ATR-baserede stops (SL = 2.0 × ATR(14), TP = 2.0 × SL).
Breakeven: SL flyttes til entry når 50% af TP-distance er nået.
Time-stop: 24 barer (= 4 døgn på 4h).

**Reflection loop:** Nightly (Loop A) analyserer lukkede trades, Weekly (Loop B)
analyserer kodebasen. Auto-apply virker ved confidence ≥ 0.85 og n ≥ 30 trades.
Beskyttede parametre (aldrig auto-apply): stake_amount, leverage, max_open_trades,
sl_pct, tp_pct, total_capital.

---

## Aktuelle strategier (Phase 3 composites)

| Strategi | Status | Seneste backtest (2 år, 6 syms) |
|---|---|---|
| `trend_momentum` | ✅ aktiv | 430 trades, WR 33%, PF 0.98 |
| `volatility_breakout` | ✅ aktiv (VB-C params) | 419 trades, WR 30%, PF 1.16 |
| `reversal_context` | ❌ deaktiveret | PF 0.45-0.59 i alle varianter |

`volatility_breakout` med `squeeze_percentile: 25, min_volume_ratio: 1.2` er den eneste
strategi med PF > 1.0. `trend_momentum` er tæt på break-even (PF 0.98). Begge mangler
edge nok til at tjene penge konsistent.

**Backtest-infrastruktur:**
```bash
.venv/bin/python backtest/runner.py --strategy trend_momentum --symbol BTC/USDT
.venv/bin/python backtest/runner.py --all   # alle enabled strategier × alle symboler
```
Metrics: win_rate, profit_factor, Sharpe, avg_pnl_pct, max_drawdown.
`end_of_data`-trades indgår IKKE i metrics (kun rigtige SL/TP/time_stop/breakeven exits).

---

## Strategi-API (BaseStrategy)

```python
class MyStrategy(BaseStrategy):
    STRATEGY_ID = "my_strategy"

    def generate_signal(self, df: pd.DataFrame, symbol: str,
                        params: dict | None = None) -> Signal | None:
        p = params or {}
        # df har kolonner fra add_all(): ema_20, ema_50, ema_200, rsi, macd,
        # macd_signal, macd_hist, bb_upper, bb_lower, bb_width, atr, adx, volume_ma
        # KALD ALDRIG add_all() herfra
        ...
        return Signal(
            symbol=symbol,
            side="long",        # eller "short"
            strategy_id=self.STRATEGY_ID,
            confidence=0.72,    # 0.0-1.0
            metadata={"reason": "..."}
        )
```

Registry auto-discoverer alle `BaseStrategy`-subklasser i `strategies/`. Aktiver i
`config.yaml` under `strategies.enabled`. Params fra config overrides via
`strategies.params.<strategy_id>`.

---

## Mål for denne session

**Overordnet:** Find og implementér 1-2 nye strategier med beviselig positive edge
(PF > 1.1, WR > 38%) over 2 år historisk data på mindst 4 af de 6 symboler.

**Succeskriterier:**
- Backtest: PF > 1.1, WR > 38%, ≥ 30 lukkede trades pr. strategi totalt (over alle symboler)
- Sharpe > 0.3 (helst > 0.5)
- Strategien virker på mindst crypto OG ét af forex/gold (ikke kun ét marked)
- Ingen data-snooping: parametrene fastlægges ud fra logik, ikke grid-search

**Hvad der IKKE skal laves:**
- Ændringer til dry_run/sandbox/leverage/stake_amount/max_open_trades
- Ændringer til gates, engine, fetcher eller indicators (medmindre en ny indikator
  kræves — tilføj da i `data/indicators.py` med `add_*` + `calculate_*` API)
- Strategier der kalder `add_all()` selv
- Code der ændrer engine.py attributter direkte

**Idéer at udforske (vælg 1-2):**
1. **Mean-reversion på RSI extremes** — RSI < 25 (oversold) med price bounce og ATR
   expansion; egnet til forex/gold, kan kombineres med BB-lower touch
2. **Volume-weighted trend** — EMA-kryds KRÆVER volume > 1.5× MA (de store bevægelser
   der er volumenbekræftede); snævrere signal end trend_momentum men bedre edge
3. **ATR expansion breakout** — signal når ATR(14) er > 1.5× sit eget 20-bars MA
   (volatilitet stiger) og prisen bryder en lokal 10-bars high/low; virker godt på crypto
4. **Multi-timeframe momentum** — 4h og 1h RSI peger i samme retning + MACD-histogram
   stigende; dobbelt-bekræftelse reducerer falske signaler

**Vigtig note om markeder og symboler:**
Strategier behøver ikke dække alle 6 symboler. En strategi må gerne være specialiseret:
- Kun crypto (BTC/USDT, ETH/USDT, SOL/USDT)
- Kun forex/gold (EUR/USD, GBP/USD, XAU/USD)
- Kun ét specifikt symbol (fx XAU/USD mean-reversion)
- Eller tværgående hvis logikken understøtter det

Det vigtige er at den har beviselig edge på de symboler den er tiltænkt — bredt men svagt
er dårligere end smalt men profitabelt.

**Fremgangsmåde for denne session:**
Denne session bruges udelukkende til at designe og beskrive nye strategier — IKKE til at
implementere dem i kodebasen. Output er en beskrivelse af:
1. Strategi-idé og logik (pseudokode eller prosaforklaring)
2. Hvilke symboler/markeder den er tiltænkt
3. Hvilke indikatorer der bruges (fra listen ovenfor)
4. Foreslåede startparametre og hvorfor
5. Forventet edge-rationale (hvorfor skulle denne strategi tjene penge?)

Implementering og backtest sker i en separat Code-session bagefter.
