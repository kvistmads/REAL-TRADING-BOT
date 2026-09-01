# XAU/USD historisk data — 2004-2025

## Herkomst og forbehold

Hentet fra GitHub-repoet [vaughanf1/GoldQuant](https://github.com/vaughanf1/GoldQuant)
(klonet 2026-08-20, commit `2b93cf8`, repoets eneste commit).

**Dataene er IKKE valideret.** Følgende skal tjekkes før de bruges til backtest:

1. **Kilden er ukendt.** Formatet er MT4/MT5-eksport (`2004.06.11 04:00`, semikolon-separeret).
   Hvilken broker/feed vides ikke. Guld-priser afviger mellem brokere.
2. **Volumen er formentlig tick-volumen**, ikke rigtig omsat volumen. Strategier der bruger
   `volume_ma` eller volumen-ratio skal behandle det derefter.
3. **Ingen krydsvalidering.** Sammenlign mindst 4h-serien mod en uafhængig kilde
   (yfinance `GC=F`, Dukascopy, eller broker-feed) på et par perioder før den erstatter
   den nuværende guld-kilde.
4. **Huller er ikke undersøgt.** Weekender og helligdage forventes; egentlige mangler ikke tjekket.

## Filer

| Fil | Barer | Periode |
|---|---|---|
| `XAU_5m_data.csv.gz` | 1.402.972 | 2004.06.11 → 2025.09.30 |
| `XAU_15m_data.csv.gz` | 480.718 | 2004.06.11 → 2025.09.30 |
| `XAU_30m_data.csv.gz` | 242.153 | 2004.06.11 → 2025.09.30 |
| `XAU_1h_data.csv` | 121.824 | 2004.06.11 → 2025.09.30 |
| `XAU_4h_data.csv` | 32.075 | 2004.06.11 → 2025.09.30 |
| `XAU_1d_data.csv` | 5.384 | 2004.06.11 → 2025.09.30 |
| `XAU_1w_data.csv` | 1.097 | 2004.06.06 → 2025.09.28 |
| `XAU_1Month_data.csv` | 256 | 2004.06.01 → 2025.09.01 |

Format: `Date;Open;High;Low;Close;Volume` — semikolon-separeret, dato som `YYYY.MM.DD HH:MM`.

Udpak: `gunzip XAU_5m_data.csv.gz`

## Hvorfor det er interessant

Den nuværende guld-kilde (yfinance `GC=F`) giver ~2 års historik ≈ 4.400 4h-barer.
Denne serie giver **32.075 4h-barer** — 7× mere, og 1h/30m/15m til at teste
intraday-effekter der ikke kan måles på 4h.
