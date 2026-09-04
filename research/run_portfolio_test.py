"""FASE 2: virker diversificering på vores egne tal?

Hypotesen er Mads': **mange halvgode ukorrelerede kilder slår én god.** N ukorrelerede
kilder med Sharpe s giver samlet Sharpe s × √N. Spørgsmålet er hvor mange uafhængige
kilder vi reelt har — og det afgøres af korrelationen mellem STRATEGIERNES afkast,
ikke mellem aktivernes.

```bash
.venv/bin/python research/run_portfolio_test.py
```

**Ingen ændring af live handelsadfærd.** `config.yaml` er urørt.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from backtest.metrics import curve_metrics  # noqa: E402
from research import tsmom  # noqa: E402
from research.daily_series import INSTRUMENTS, load, research_cost_config  # noqa: E402
from research.portfolio import (  # noqa: E402
    UNIVERSES, VOL_MONTHS, build_leg, run_portfolio,
)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# --- LÅST FØR KØRSEL ------------------------------------------------------
# HOVEDTALLET ER ALLE OTTE. Det er det præregistrerede univers.
HEADLINE_UNIVERSE = "alle_otte"

# Forhåndsregistreret forventning: samlet Sharpe 1,0-1,2.
EXPECTED_SHARPE = (1.0, 1.2)
# Over dette: mistænk lookahead i vægtningen og find fejlen FØR resultatet
# rapporteres som godt.
SHARPE_SUSPECT_LOOKAHEAD = 1.5
# Under dette: diversificeringen virker ikke, og strategikorrelationerne er
# højere end aktivkorrelationerne antyder.
SHARPE_DIVERSIFICATION_FAILS = 0.7

# Delperioder rapporteres, men bedømmelsen sker på HELE perioden. Æraerne er
# beskrivende — de er valgt af hvornår instrumenterne findes, ikke af resultatet.
ERAS = {"fra 2003 (≥5 instr.)": "2003-01-01", "fra 2018 (alle 8)": "2018-01-01"}


def _offdiag_mean(corr: pd.DataFrame) -> float:
    v = corr.to_numpy(float)
    n = len(v)
    return float((v.sum() - n) / (n * n - n)) if n > 1 else 0.0


def n_eff_from_rho(corr: pd.DataFrame) -> float:
    """Effektivt antal uafhængige væddemål ud fra gennemsnitlig parvis korrelation.

    Dette er tallet der hører til ``Sharpe = s × √N``. For N lige vægtede kilder med
    Sharpe s og gennemsnitlig korrelation ρ er porteføljens Sharpe præcis
    ``s × √(N / (1 + (N−1)ρ))``. Nævneren er derfor det effektive antal.
    """
    n = len(corr)
    rho = _offdiag_mean(corr)
    denom = 1 + (n - 1) * rho
    return float(n / denom) if denom > 0 else float(n)


def n_eff_from_eigenvalues(corr: pd.DataFrame) -> float:
    """Samme spørgsmål via korrelationsmatricens egenværdier (participation ratio).

    Krydstjek på ρ-udgaven. De to er ikke det samme mål: ρ-udgaven antager at ALLE
    par korrelerer lige meget, mens egenværdierne ser den faktiske klyngestruktur —
    to par à 0,98 og seks par à 0,05 er ikke det samme som otte par à 0,25.
    Ligger de langt fra hinanden, er porteføljen klynget frem for jævnt korreleret.
    """
    lam = np.linalg.eigvalsh(corr.to_numpy(float))
    lam = lam[lam > 1e-12]
    return float(lam.sum() ** 2 / (lam ** 2).sum())


def monthly_returns(config: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Månedlige afkast pr. instrument: STRATEGIENS og AKTIVETS, samt Sharpe.

    Forskellen mellem de to matricer er selve pointen i DEL 2: strategierne kan
    være mindre korrelerede end aktiverne, fordi de er ude af markedet på
    forskellige tidspunkter.
    """
    strat, asset, sharpes = {}, {}, {}
    for key, inst in INSTRUMENTS.items():
        df = load(inst)
        res = tsmom.run_tsmom(df, inst, config, 12, 1)
        strat[key] = res.equity.resample("ME").last().pct_change().dropna()
        asset[key] = (pd.Series(df["close"].to_numpy(), index=pd.DatetimeIndex(df["time"]))
                      .resample("ME").last().pct_change().dropna())
        sharpes[key] = curve_metrics(res.equity)["sharpe"]
    return pd.DataFrame(strat), pd.DataFrame(asset), sharpes


def evaluate(keys: list[str], config: dict, strat_m: pd.DataFrame,
             sharpes: dict) -> dict:
    legs = {k: build_leg(k, config) for k in keys}
    res = run_portfolio(legs)
    m = curve_metrics(res.equity, res.exposure)
    b = curve_metrics(res.benchmark)
    corr = strat_m[keys].corr()
    s_bar = float(np.mean([sharpes[k] for k in keys]))
    n_eff = n_eff_from_rho(corr)

    eras = {}
    for label, start in ERAS.items():
        eq = res.equity[res.equity.index >= start]
        bh = res.benchmark[res.benchmark.index >= start]
        if len(eq) > 250:
            eras[label] = (curve_metrics(eq / eq.iloc[0]),
                           curve_metrics(bh / bh.iloc[0]))

    return {
        "univers": "+".join(keys) if len(keys) < 4 else f"{len(keys)} instrumenter",
        "keys": keys, "res": res, "metrics": m, "baseline": b,
        "corr": corr, "s_bar": s_bar,
        "n_eff_rho": n_eff, "n_eff_eig": n_eff_from_eigenvalues(corr),
        "rho_bar": _offdiag_mean(corr),
        "predicted_sharpe": s_bar * np.sqrt(n_eff),
        "eras": eras,
    }


def session_table(results: dict) -> str:
    """DEL 4 — baselinen står på SAMME linje, som hidtil."""
    lines = [
        f"FASE 2  portefølje: invers vol ({VOL_MONTHS}m bagudskuende), månedlig rebalancering",
        f"{'univers / periode':<24}{'n':>3}{'CAGR':>8}{'maxDD':>8}{'Sharpe':>8}{'flat_dg':>9}"
        f"{'i mkt':>7} | {'B&H CAGR':>9}{'B&H maxDD':>10}{'B&H Sh':>8}{'B&H flat':>9}",
    ]
    for name, r in results.items():
        m, b = r["metrics"], r["baseline"]
        span = f"{r['res'].equity.index[0]:%Y}-{r['res'].equity.index[-1]:%Y}"
        lines.append(
            f"{name + '  ' + span:<24}{len(r['keys']):>3}{m['cagr']:>7.2f}%"
            f"{m['max_drawdown_pct']:>7.1f}%{m['sharpe']:>8.2f}{m['longest_flat_days']:>9}"
            f"{m['time_in_market_pct']:>6.0f}% | {b['cagr']:>8.2f}%"
            f"{b['max_drawdown_pct']:>9.1f}%{b['sharpe']:>8.2f}{b['longest_flat_days']:>9}"
        )
        for label, (em, eb) in r["eras"].items():
            lines.append(
                f"{'  ' + label:<24}{'':>3}{em['cagr']:>7.2f}%"
                f"{em['max_drawdown_pct']:>7.1f}%{em['sharpe']:>8.2f}{em['longest_flat_days']:>9}"
                f"{'':>7} | {eb['cagr']:>8.2f}%{eb['max_drawdown_pct']:>9.1f}%"
                f"{eb['sharpe']:>8.2f}{eb['longest_flat_days']:>9}"
            )
    return "\n".join(lines)


def main() -> int:
    config = research_cost_config(yaml.safe_load(open("config.yaml")))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Beregner enkeltinstrument-kurver og månedlige afkast ...")
    strat_m, asset_m, sharpes = monthly_returns(config)

    results = {}
    for name, keys in UNIVERSES.items():
        print(f"  kombinerer {name} ({len(keys)} instrumenter) ...")
        results[name] = evaluate(keys, config, strat_m, sharpes)

    print("\n" + session_table(results))

    head = results[HEADLINE_UNIVERSE]
    sharpe = head["metrics"]["sharpe"]
    print(f"\n  HOVEDTAL ({HEADLINE_UNIVERSE}): Sharpe {sharpe:.2f}")
    print(f"  Forventet {EXPECTED_SHARPE[0]}-{EXPECTED_SHARPE[1]} "
          f"(gns. individuel Sharpe {head['s_bar']:.2f} × √{head['n_eff_rho']:.2f} "
          f"= {head['predicted_sharpe']:.2f})")
    if sharpe >= SHARPE_SUSPECT_LOOKAHEAD:
        print("  ADVARSEL: over 1,5 — mistænk lookahead i vægtningen FØR dette "
              "rapporteres som et godt resultat.")
    elif sharpe <= SHARPE_DIVERSIFICATION_FAILS:
        print("  Under 0,7 — diversificeringen virker ikke; strategikorrelationerne "
              "er højere end aktivkorrelationerne antyder.")
    elif EXPECTED_SHARPE[0] <= sharpe <= EXPECTED_SHARPE[1]:
        print("  Inden for det forventede bånd.")
    else:
        print(f"  Under det forventede bånd, men over fejlgrænsen på "
              f"{SHARPE_DIVERSIFICATION_FAILS}.")

    print(f"\n  Strategikorrelation gns. {head['rho_bar']:+.3f} mod "
          f"aktivkorrelation {_offdiag_mean(asset_m[head['keys']].corr()):+.3f}")
    print(f"  Effektive væddemål: {head['n_eff_rho']:.2f} (ρ) / "
          f"{head['n_eff_eig']:.2f} (egenværdier)")

    _save(results, strat_m, asset_m, sharpes)
    print(f"\nRapport -> {OUTPUT_DIR / 'portfolio_combination.md'}")
    return 0


def _save(results, strat_m, asset_m, sharpes) -> None:
    from research.report_portfolio import build

    rows = []
    for name, r in results.items():
        m, b = r["metrics"], r["baseline"]
        rows.append({
            "univers": name, "n_instrumenter": len(r["keys"]),
            "fra": str(r["res"].equity.index[0].date()),
            "til": str(r["res"].equity.index[-1].date()),
            "cagr": m["cagr"], "maxdd": m["max_drawdown_pct"],
            "sharpe": m["sharpe"], "flat_dage": m["longest_flat_days"],
            "tid_i_marked_%": m["time_in_market_pct"],
            "bh_cagr": b["cagr"], "bh_maxdd": b["max_drawdown_pct"],
            "bh_sharpe": b["sharpe"], "bh_flat_dage": b["longest_flat_days"],
            "rho_strategi": round(r["rho_bar"], 3),
            "n_eff_rho": round(r["n_eff_rho"], 2),
            "n_eff_eig": round(r["n_eff_eig"], 2),
            "sharpe_forudsagt": round(r["predicted_sharpe"], 2),
            "omkostninger_pct": r["res"].turnover_cost_pct,
            "heraf_vaegtrebalancering_pct": r["res"].rebalance_cost_share,
        })
    pd.DataFrame(rows).to_csv(OUTPUT_DIR / "portfolio_combination.csv", index=False)
    (OUTPUT_DIR / "portfolio_combination.md").write_text(
        build(results, strat_m, asset_m, sharpes, session_table(results),
              n_eff_from_rho, n_eff_from_eigenvalues, _offdiag_mean),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
