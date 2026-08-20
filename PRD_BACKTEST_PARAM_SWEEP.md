# PRD: Parameter-sweep backtest — signal-hyppighed og kvalitet

## Baggrund og problem

Botten har kørt i 3+ uger uden en eneste live-trade. Regime-gate-fix og ADX-threshold er
styr på. Det egentlige problem er at strategiernes interne betingelser er for snævre:

**trend_momentum:** Kræver et MACD-kryds på præcis den seneste bar (linje 83-84). På 4h
timeframe sker dette statistisk set en gang hvert par uger pr. symbol. Det er årsagen til
de 6-14 trades over 2 år i backtest.

**reversal_context:** Kræver RSI-divergens + volume-spike > 1.2× MA inden for de seneste
30 barer. Begge betingelser skal pege i samme retning på en swing-bar.

**volatility_breakout:** Kræver BB-width i den nederste 10-percentil over 120 barer (de
10% mest komprimerede perioder) inden for de seneste 5 barer. Meget restriktivt.

## Formål

Kør systematisk backtest med parameter-variationer for at finde indstillinger der giver:
- **Significt flere trades** (mål: 5+ trades pr. strategi pr. symbol pr. år)
- **Acceptabel kvalitet** (win-rate > 40%, profit factor > 0.9 — vi accepterer dårligere tal
  nu for at få data til reflection-loopet)

## Setup

Branch: `feature/architecture-fixes` (eller main — ingen kodeændringer til produktion).
Kør ALTID via `.venv/bin/python`.

Skriv et selvstændigt script `backtest/param_sweep.py` der:
1. Importerer de 3 strategier + runner
2. Henter data for alle 6 symboler (same som `--all`)
3. Kører backtest med hvert param-sæt beskrevet nedenfor
4. Printer en sammenligningstabel til stdout + gemmer `backtest_results/param_sweep_<dato>.csv`

## Variationer der testes

### Baseline (nuværende defaults)
Kør `--all` med standard params som kontrol.

---

### trend_momentum — 4 varianter

Bottleneck: `fresh_cross_up`/`fresh_cross_down` kræver kryds på seneste bar præcis.

**Variant TM-A (reflection-forslag lav):**
```python
params = {"min_confidence": 0.45, "cross_strength_scale": 0.05}
```

**Variant TM-B (reflection-forslag høj):**
```python
params = {"min_confidence": 0.45, "cross_strength_scale": 0.12}
```

**Variant TM-C (løsere kryds-definition — NYT):**
Modificér midlertidigt i `generate_signal` til at acceptere kryds fra de seneste 3 barer
(ikke kun bar -1 vs -2). Dette kræver en lokal kopi af strategien i sweep-scriptet —
IKKE en ændring til `strategies/trend_momentum.py`.

Implementer som inline-subklasse i sweep-scriptet:
```python
class TrendMomentumRelaxed(TrendMomentum):
    def generate_signal(self, df, symbol, params=None):
        # Tjek kryds på bar[-1] vs [-2], [-2] vs [-3], og [-3] vs [-4]
        # Returner signal hvis nogen af de tre peger i trendens retning
        ...
```

**Variant TM-D (endnu løsere — MACD histogram retning):**
I stedet for kryds: accepter signal hvis MACD-histogram har ændret retning de seneste 2 barer
(fra faldende til stigende for long, omvendt for short). Inline-subklasse i sweep-scriptet.

---

### reversal_context — 4 varianter

**Variant RC-A (reflection lav volume + lav delta):**
```python
params = {"min_volume_ratio": 1.1, "min_rsi_delta": 3.0}
```

**Variant RC-B (reflection høj volume + høj delta):**
```python
params = {"min_volume_ratio": 1.5, "min_rsi_delta": 8.0}
```

**Variant RC-C (ingen volume-gate):**
```python
params = {"min_volume_ratio": 1.0, "min_rsi_delta": 3.0}
```
Volume-ratio = 1.0 svarer til ingen volume-krav (enhver bar passerer).

**Variant RC-D (aggressiv):**
```python
params = {"min_volume_ratio": 1.0, "min_rsi_delta": 2.0, "min_confidence": 0.40}
```

---

### volatility_breakout — 4 varianter

**Variant VB-A (reflection lav percentil + lav volume):**
```python
params = {"squeeze_percentile": 5, "min_volume_ratio": 1.3}
```

**Variant VB-B (reflection høj percentil + høj volume):**
```python
params = {"squeeze_percentile": 15, "min_volume_ratio": 2.0}
```

**Variant VB-C (bred squeeze-definition):**
```python
params = {"squeeze_percentile": 25, "min_volume_ratio": 1.2}
```
25-percentilen betyder at vi accepterer de 25% mest komprimerede perioder.

**Variant VB-D (aggressiv):**
```python
params = {"squeeze_percentile": 30, "min_volume_ratio": 1.0}
```

---

## Output-format

Tabel pr. strategi med alle symboler samlet:

```
=== trend_momentum ===
Variant          | Trades | Win%  | PF    | Avg PnL% | Max DD%
-----------------|--------|-------|-------|----------|--------
Baseline         |     14 | 35.7% |  0.82 |    -0.4% |  -18.2%
TM-A (cs=0.05)  |     18 | 38.9% |  0.91 |    -0.2% |  -15.1%
TM-B (cs=0.12)  |     11 | 45.5% |  1.12 |    +0.8% |  -12.3%
TM-C (3-bar)    |     42 | 38.1% |  0.95 |    +0.1% |  -22.4%
TM-D (hist dir) |     67 | 33.3% |  0.88 |    -0.3% |  -28.1%
```

Skriv også en samlet anbefaling til sidst:
```
ANBEFALING:
- trend_momentum: TM-B giver bedst P/F, TM-C giver flest trades ved acceptabel kvalitet
- reversal_context: RC-A giver 3× flere trades med marginal forringelse af win-rate
- volatility_breakout: VB-C giver 4× flere trades, PF forbliver over 1.0
```

## Vigtige noter

- Alle inline-subklasser i sweep-scriptet ændrer IKKE `strategies/*.py` — production-koden
  er urørt. Sweep-scriptet er engangs-analyse.
- Backtest bruger de nye ATR-stops + breakeven + time-stop fra `PRD_ARCHITECTURE_FIXES.md`
  (allerede implementeret på branchen).
- Kør `.venv/bin/python backtest/param_sweep.py` — IKKE `main.py`.
- `dry_run: true` og `sandbox: true` i config røres aldrig.
- Gem CSV i `backtest_results/` (allerede i .gitignore).
- Print klar stdout-opsummering så resultatet kan kopieres direkte til chat.
