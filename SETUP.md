# Setup

**Kræver Python 3.12** (3.13+ er endnu ikke understøttet af cryptography/numba).

Denne maskine bruger en uv-håndteret Python 3.12 i et projekt-venv (`.venv/`).

## Installation

```bash
# 1. Opret virtuelt miljø med Python 3.12
python3.12 -m venv .venv

# 2. Installér dependencies (binære wheels — cryptography bygger ellers fra kilde)
.venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
```

> **Note:** `--only-binary=:all:` er nødvendigt. Uden det forsøger pip at bygge
> `cryptography` fra kilde (kræver Rust) og fejler. Flaget tvinger færdige wheels.

## Kør botten

```bash
.venv/bin/python main.py
```

Stop med `Ctrl+C`. Botten kører i dry-run (`config.yaml` → `trading.dry_run: true`)
og sender aldrig live orders.

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

Forventet: 32/32 grønne.

## Kendte begrænsninger i Phase 1

- **Forex/gold-symboler** (EUR/USD, GBP/USD, XAU/USD) fejler gracefully — Binance
  er en crypto-exchange og har ikke disse par. De aktiveres i Phase 2 via MT5 som
  datakilde. De 3 crypto-symboler (BTC/ETH/SOL) henter data normalt.
