# PRD: Regime Gate — Strategi-aware sideways + retning i notifikationer

## Baggrund og problem

Regime-gaten klassificerer alt der ikke er TRENDING/VOLATILE som SIDEWAYS og blokerer
100%. Det er korrekt for `trend_momentum`, men direkte forkert for:

- `reversal_context` — designet til ranging/sideways markeder (RSI-divergence opstår
  netop i konsolidering)
- `volatility_breakout` — breakouts opstår fra sideways-komprimering (Bollinger Squeeze
  er per definition et sideways-fænomen)

Resultat: botten afviser de signals der er mest relevante for to ud af tre strategier.
Eksempel fra live-kørsel: SOL/USDT afvist med ADX=15-22 i 9+ på hinanden følgende bars,
mens markedet lå i præcis den konsolidering `reversal_context` er bygget til.

Derudover mangler REJECTED-notifikationer signal-retning (LONG/SHORT), hvilket gør det
umuligt at evaluere hvorvidt de afviste signals var gode muligheder.

## Ændring 1 — Strategi-aware regime gate (`gates/regime.py`)

### Nuværende logik (linje 86-89)
```python
# SIDEWAYS
reason = f"Sideways market (ADX={adx_str})"
logger.info(f"RegimeGate AFVIST ({signal.symbol}): {reason}")
return GateResult(gate_name=self.name, passed=False, score=0.0, reason=reason)
```

### Ny logik
I SIDEWAYS-grenen: tjek `signal.strategy_id`. Strategier der er designet til sideways
markeder passerer med score=0.7 og en informativ reason. Kun trend-strategier blokeres.

```python
# SIDEWAYS
SIDEWAYS_OK_STRATEGIES = {"reversal_context", "volatility_breakout"}

if signal.strategy_id in SIDEWAYS_OK_STRATEGIES:
    reason = f"Sideways market (ADX={adx_str}) — {signal.strategy_id} tilladt i ranging"
    logger.info(f"RegimeGate OK ({signal.symbol}): {reason}")
    return GateResult(
        gate_name=self.name, passed=True, score=0.7,
        reason=reason,
    )

reason = f"Sideways market (ADX={adx_str})"
logger.info(f"RegimeGate AFVIST ({signal.symbol}): {reason}")
return GateResult(gate_name=self.name, passed=False, score=0.0, reason=reason)
```

`SIDEWAYS_OK_STRATEGIES` defineres som en modul-level konstant (eller optionelt som
config-liste `gates.regime.sideways_ok_strategies` med default til de to navne).

**Vigtigt:** TRENDING og VOLATILE logikken røres IKKE.

## Ændring 2 — Retning i REJECTED notifikationer (`core/notifications.py`)

### Nuværende (linje 78-83)
```python
async def send_gate_rejected(self, signal: Signal, result: GateResult) -> None:
    text = (
        f"⚠️ REJECTED {signal.symbol} [{signal.strategy_id}]\n"
        f"Gate: {result.gate_name} | Reason: {result.reason}"
    )
    await self._send(text)
```

### Ny
Tilføj `signal.side` (LONG/SHORT) til beskeden:

```python
async def send_gate_rejected(self, signal: Signal, result: GateResult) -> None:
    text = (
        f"⚠️ REJECTED {signal.symbol} [{signal.strategy_id}] {signal.side}\n"
        f"Gate: {result.gate_name} | Reason: {result.reason}"
    )
    await self._send(text)
```

Eksempel på output:
```
⚠️ REJECTED SOL/USDT [reversal_context] LONG
Gate: regime | Reason: Sideways market (ADX=18)
```

`signal.side` er allerede en streng ("LONG"/"SHORT") fra `strategies/base.py` — ingen
typeændring nødvendig.

## Ændring 3 (config — ALLEREDE GJORT)

`min_trending_adx` er sænket fra 25 til 20 i `config.yaml`. Ingen kodeændring nødvendig.

## Test-krav

1. `test_regime_gate.py` — tilføj cases:
   - `reversal_context` signal med ADX=18 → passed=True, score=0.7
   - `volatility_breakout` signal med ADX=15 → passed=True, score=0.7
   - `trend_momentum` signal med ADX=18 → passed=False, score=0.0
   - Eksisterende TRENDING/VOLATILE tests røres ikke

2. `test_notifications.py` (eller eksisterende) — verificer at `send_gate_rejected`
   output indeholder signal.side strengen.

## Scope

- Filer der ændres: `gates/regime.py`, `core/notifications.py`
- Config allerede opdateret: `config.yaml` (min_trending_adx: 20)
- Ingen DB-ændringer, ingen Alembic migration, ingen ny config-nøgle (brug hardcoded set)
- Kør ALTID via `.venv/bin/python -m pytest tests/ -v` efter ændringer
