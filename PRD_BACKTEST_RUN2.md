# PRD — Backtest Run 2 (min_confidence 0.45)

**Branch:** `main`
**Formål:** Kør den fulde backtest suite med den nye `min_confidence: 0.45`
og præsentér HTML-rapporten. Al infrastruktur er på plads — dette er en ren kørsels-PRD.

---

## Baggrund

Første backtest-run genererede for få trades (0/18 bestod tærsklerne).
`min_confidence` er sænket fra 0.65 → 0.45 i config.yaml (merged til main via PR #14).
Formålet er at få flere trades ind i reflection-loopet og se om strategierne
performer bedre med lavere entry-bar.

---

## Ikke-forhandlingsbare constraints

- `dry_run: true` og `sandbox: true` MÅ aldrig røres
- Brug ALTID `.venv/bin/python`
- Ingen ændringer til kode — dette er en kørselsprocedure

---

## Trin 1 — Forberedelse

```bash
cd ~/Documents/GitHub/REAL\ TRADING\ BOT
git checkout main
git pull origin main

# Bekræft confidence-niveau
grep "min_confidence" config.yaml
# Skal vise: min_confidence: 0.45
```

---

## Trin 2 — Kør fuld backtest suite

```bash
cd ~/Documents/GitHub/REAL\ TRADING\ BOT
.venv/bin/python backtest/runner.py --all
```

Afventer ~5-10 min (18 kombinationer × 2 år OHLCV-data).

---

## Trin 3 — Verificér output

```bash
ls -lh backtest_results/
# Forventet:
#   suite_YYYY-MM-DD.csv      (18 rækker)
#   trades_YYYY-MM-DD.csv     (alle individuelle trades)
#   report_YYYY-MM-DD.html    (HTML-rapport)

wc -l backtest_results/report_*.html
# Skal være > 500 linjer

wc -l backtest_results/trades_*.csv
# Skal have markant flere trades end Run 1
```

---

## Trin 4 — Åbn og præsentér rapporten

```bash
open backtest_results/report_$(date +%Y-%m-%d).html
```

**Præsentér herefter følgende i dit svar:**

1. **Overordnet resultat**: X/18 kombinationer bestod alle tærskelværdier
2. **Antal trades totalt** vs. Run 1 (Run 1 baseline: ~5-22 trades pr. kombination)
3. **Top 3 kombinationer** (strategi + symbol): WR%, PF, Sharpe, trades, total PnL%
4. **Bundniveau 3 kombinationer**: hvad gik galt
5. **Per-strategi-opsummering**: hvilken strategi performer bedst overordnet
6. **Anbefaling**: Er vi klar til at fortsætte paper trading? Hvilke strategier/symboler
   ser mest lovende ud for reflection-loopet?

---

## Trin 5 — Test-suite check

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -10
```

Alle tests skal stadig være grønne.

---

## Acceptkriterie

- `--all` kører uden Python-fejl
- HTML-rapport genereres og åbner i browser
- Alle 8 sektioner i rapporten er udfyldt med data
- Analysen fra Trin 4 præsenteres struktureret i svaret

