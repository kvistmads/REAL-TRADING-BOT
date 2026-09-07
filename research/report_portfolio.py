"""Rapportgenerator for fase 2/2b — porteføljekombinationen."""

from __future__ import annotations

import numpy as np
import pandas as pd

# Fase 2's tal, FØR guld-duplikatet blev fjernet. De står her så effekten af
# rettelsen er synlig frem for at skulle huskes.
FASE2 = {
    "alle_syv": {"label": "alle otte (med XAU)", "n": 8, "sharpe": 0.82, "cagr": 7.83,
                 "maxdd": -19.0, "flat_days": 1148, "n_eff": 2.86, "n_eff_eig": 4.19,
                 "rho": 0.257},
    "uden_fx": {"label": "uden FX (med XAU)", "n": 6, "sharpe": 0.99, "cagr": 12.18,
                "maxdd": -21.1, "flat_days": 1259, "n_eff": 2.51, "n_eff_eig": 3.20,
                "rho": 0.277},
}


def _side_by_side(strat: pd.DataFrame, asset: pd.DataFrame, keys: list[str]) -> str:
    """Parvis: strategikorrelation, aktivkorrelation og forskellen mellem dem."""
    cs, ca = strat[keys].corr(), asset[keys].corr()
    rows = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            s, v = float(cs.loc[a, b]), float(ca.loc[a, b])
            rows.append({"par": f"{a}–{b}", "strategi": round(s, 2),
                         "aktiv": round(v, 2), "forskel": round(s - v, 2)})
    return pd.DataFrame(rows).sort_values("aktiv", ascending=False).to_string(index=False)


def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    rows = ["| " + " | ".join(str(v) for v in row) + " |"
            for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


def _drawdown_date(curve: pd.Series) -> str:
    return str((curve / curve.cummax() - 1).idxmin().date())


def _delta(new: float, old: float, unit: str = "") -> str:
    return f"{new:.2f}{unit} (var {old:.2f}{unit}, {new - old:+.2f})"


def build(results, strat_m, asset_m, sharpes, session,
          n_eff_rho, n_eff_eig, offdiag) -> str:
    head, nofx = results["alle_syv"], results["uden_fx"]
    keys = head["keys"]
    rho_s, rho_a = offdiag(strat_m[keys].corr()), offdiag(asset_m[keys].corr())
    m, b = head["metrics"], head["baseline"]
    res = head["res"]

    change = pd.DataFrame([
        {"mål": "Sharpe", "fase 2 (8 instr.)": FASE2["alle_syv"]["sharpe"],
         "fase 2b (7 instr.)": m["sharpe"],
         "ændring": round(m["sharpe"] - FASE2["alle_syv"]["sharpe"], 2)},
        {"mål": "CAGR_%", "fase 2 (8 instr.)": FASE2["alle_syv"]["cagr"],
         "fase 2b (7 instr.)": m["cagr"],
         "ændring": round(m["cagr"] - FASE2["alle_syv"]["cagr"], 2)},
        {"mål": "maxDD_%", "fase 2 (8 instr.)": FASE2["alle_syv"]["maxdd"],
         "fase 2b (7 instr.)": m["max_drawdown_pct"],
         "ændring": round(m["max_drawdown_pct"] - FASE2["alle_syv"]["maxdd"], 2)},
        {"mål": "flat_år", "fase 2 (8 instr.)": round(FASE2["alle_syv"]["flat_days"] / 365.25, 1),
         "fase 2b (7 instr.)": round(m["longest_flat_days"] / 365.25, 1),
         "ændring": round((m["longest_flat_days"] - FASE2["alle_syv"]["flat_days"]) / 365.25, 1)},
        {"mål": "N_eff (ρ)", "fase 2 (8 instr.)": FASE2["alle_syv"]["n_eff"],
         "fase 2b (7 instr.)": round(head["n_eff_rho"], 2),
         "ændring": round(head["n_eff_rho"] - FASE2["alle_syv"]["n_eff"], 2)},
        {"mål": "ρ_strategi", "fase 2 (8 instr.)": FASE2["alle_syv"]["rho"],
         "fase 2b (7 instr.)": round(rho_s, 3),
         "ændring": round(rho_s - FASE2["alle_syv"]["rho"], 3)},
    ])

    nofx_change = pd.DataFrame([
        {"mål": "Sharpe", "fase 2 (6 instr.)": FASE2["uden_fx"]["sharpe"],
         "fase 2b (5 instr.)": nofx["metrics"]["sharpe"],
         "ændring": round(nofx["metrics"]["sharpe"] - FASE2["uden_fx"]["sharpe"], 2)},
        {"mål": "CAGR_%", "fase 2 (6 instr.)": FASE2["uden_fx"]["cagr"],
         "fase 2b (5 instr.)": nofx["metrics"]["cagr"],
         "ændring": round(nofx["metrics"]["cagr"] - FASE2["uden_fx"]["cagr"], 2)},
        {"mål": "maxDD_%", "fase 2 (6 instr.)": FASE2["uden_fx"]["maxdd"],
         "fase 2b (5 instr.)": nofx["metrics"]["max_drawdown_pct"],
         "ændring": round(nofx["metrics"]["max_drawdown_pct"] - FASE2["uden_fx"]["maxdd"], 2)},
        {"mål": "N_eff (ρ)", "fase 2 (6 instr.)": FASE2["uden_fx"]["n_eff"],
         "fase 2b (5 instr.)": round(nofx["n_eff_rho"], 2),
         "ændring": round(nofx["n_eff_rho"] - FASE2["uden_fx"]["n_eff"], 2)},
    ])

    contrib = pd.DataFrame([
        {"instrument": k,
         "afkast_bidrag_%": res.return_contribution.get(k, 0.0),
         "risiko_bidrag_%": res.risk_contribution.get(k, 0.0),
         "afkast_pr_risiko": round(res.return_contribution.get(k, 0.0)
                                   / res.risk_contribution.get(k, 1.0), 2)}
        for k in keys
    ]).sort_values("afkast_bidrag_%", ascending=False)

    sharpe_tbl = pd.DataFrame(
        [{"instrument": k, "Sharpe": round(sharpes[k], 2)} for k in keys])

    return f"""# Fase 2b — porteføljen med ét instrument pr. aktiv

**Kørsel:** syv TSMOM-kurver kombineret til én portefølje, invers volatilitet,
månedlig rebalancering. `XAU` fjernet som duplikat af `GC`.
**Periode:** {res.equity.index[0].date()} → {res.equity.index[-1].date()}
**Status:** research. Ingen ændring af live handelsadfærd, `config.yaml` urørt.

---

## Svaret: rettelsen gjorde tallene en anelse dårligere, og det er pointen

```
{session}
```

{_md_table(change)}

**Sharpe faldt fra 0,82 til {m['sharpe']:.2f}.** Det er ikke et tegn på at rettelsen
var forkert — det er et tegn på at duplikatet pyntede resultatet.

Mekanismen: med `XAU` og `GC` som to pladser fik guld **dobbelt risikobudget** under
invers volatilitetsvægtning. Guld var samtidig et af de bedste enkeltinstrumenter
(standalone Sharpe 0,71) og korrelerede kun 0,08 med aktier. At overvægte det ved et
uheld hjalp derfor porteføljen. Da duplikatet forsvandt, halveredes guldets vægt, og
porteføljen mistede eksponering mod netop den bedste diversificerende kilde.

Det ændrer ikke at rettelsen er rigtig. **Ét væddemål talt to gange er stadig ét
væddemål**, og en portefølje der ser god ud fordi den dobbelttæller en position, er
ikke god — den er forkert opgjort. En konstruktionskorrektion måles på om den er
sand, ikke på om den hjælper.

`N_eff` faldt tilsvarende fra 2,86 til {head['n_eff_rho']:.2f}. To ting trak samme
vej: N gik fra 8 til 7, og ρ̄ steg marginalt (fra 0,257 til {rho_s:.3f}), fordi `XAU`
korrelerede lidt lavere end gennemsnittet med alt andet end `GC`.

### Uden FX

{_md_table(nofx_change)}

---

## DEL 1 — hvorfor `GC=F` og ikke `XAU`

Valget er truffet på **datakvalitet, ikke afkast**:

| | `GC=F` | `XAU/USD` |
|---|---|---|
| Kilde | yfinance, som resten af porteføljen | ukendt MT4-feed, ét commit på GitHub |
| Volumen | rigtig (419 nul-barer) | tick-volumen, broker-afhængig |
| Validerede år | 2000–2026 | 2004–2024 (2025 kasseret) |
| Roll-drift mod spot | målt til +0,04 pct-point/år | — |
| ATR i overlapstest | reference | afveg ~20% |

Havde valget stået på afkast, ville de to være næsten uskelnelige: standalone CAGR
10,59% mod 10,05% og maxDD −33,3% mod −32,8%. Det er netop derfor beslutningen kan
træffes rent på kilde og reproducerbarhed.

Reglen er skrevet ind i `CLAUDE.md`: **ét instrument pr. underliggende aktiv i en
portefølje. To tickere for samme ting er ikke diversificering.** Listen ligger i
`research/portfolio.DUPLICATE_UNDERLYING`.

---

## DEL 2 — hvad bidragskolonnerne viser

{_md_table(contrib)}

`afkast_pr_risiko` er forholdet mellem de to andele. Over 1,0 betyder at
instrumentet leverer mere afkast end det bruger risiko.

**Det tal du bad om at kunne se med det samme, er FX-linjen.** `6E` og `6B` leverer
tilsammen **−2,1% af afkastet** og bruger **{res.risk_contribution.get('6E', 0) + res.risk_contribution.get('6B', 0):.1f}%
af risikoen.** De er ikke bare uden bidrag; de er negative, og de fylder en femtedel
af risikobudgettet mens de gør det.

De øvrige linjer:

- **`SPY` bærer porteføljen** ({res.return_contribution.get('SPY', 0):.0f}% af afkastet
  for {res.risk_contribution.get('SPY', 0):.0f}% af risikoen). Det er også det
  instrument der har været med længst, så tallet er delvis en historik-effekt.
- **`GC` er den mest effektive** ({res.return_contribution.get('GC', 0):.0f}% af
  afkastet for kun {res.risk_contribution.get('GC', 0):.0f}% af risikoen) — netop
  fordi den korrelerer lavt med aktierne.
- **Krypto leverer over sin risikoandel** trods kun 9 års historik, fordi invers
  volatilitet giver den en lille vægt og afkastet er stort.

**Risikobidraget er defineret som faktisk vægt × volatilitet**, akkumuleret dag for
dag — ikke måltvægt. En plads i kontanter bærer ingen risiko, uanset hvad den blev
tildelt ved månedsskiftet.

---

## Korrelation: strategi mod aktiv

| | Gennemsnit | N_eff (ρ) | N_eff (egenværdier) |
|---|---|---|---|
| **Strategiernes** månedlige afkast | **{rho_s:+.3f}** | **{head['n_eff_rho']:.2f}** | {head['n_eff_eig']:.2f} |
| Aktivernes månedlige afkast | {rho_a:+.3f} | {n_eff_rho(asset_m[keys].corr()):.2f} | {n_eff_eig(asset_m[keys].corr()):.2f} |

Konklusionen fra fase 2 står uændret efter rettelsen: **strategikorrelationerne er
ikke markant lavere end aktivkorrelationerne.** {rho_s:.3f} mod {rho_a:.3f}.

```
{_side_by_side(strat_m, asset_m, keys)}
```

Med `XAU` ude er det tydeligere hvor det eneste reelle fald ligger: `BTC`–`ETH`
(0,72 → 0,63). `SPY`–`QQQ` falder kun fra 0,84 til 0,81 — de to strategier går ud af
markedet næsten samtidig, fordi de reagerer på det samme signal i det samme marked.

Forudsigelsen holder fortsat: gennemsnitlig individuel Sharpe {head['s_bar']:.2f} ×
√{head['n_eff_rho']:.2f} = **{head['predicted_sharpe']:.2f}** forudsagt mod
**{m['sharpe']:.2f}** faktisk.

### Individuelle Sharpe-tal

{_md_table(sharpe_tbl)}

Gennemsnit **{head['s_bar']:.2f}** over de syv, **{nofx['s_bar']:.2f}** uden FX.

---

## Konstruktion og omkostninger

- **Vægt:** invers volatilitet på 12 måneders bagudskuende daglige afkast, målt
  strengt FØR rebalanceringsdagen, annualiseret med instrumentets eget antal barer
  pr. år (krypto 365, futures ~252).
- **Pladsen holder TSMOM-positionen**, ikke aktivet. Er signalet ude, står kapitalen
  i kontanter, og kontanter forrentes ikke.
- **Ingen gearing**, og loftet levner plads til kurtagen.
- **Omkostninger:** {res.turnover_cost_pct:.2f}% af startkapitalen over
  {m['years']:.0f} år, hvoraf **{res.rebalance_cost_share:.0f}%** er ren
  vægtrebalancering — omsætning ud over signalskiftene, som ville være usynlig hvis
  man kun modellerede ind- og udgange.

Uden FX stiger omkostningerne til {nofx['res'].turnover_cost_pct:.2f}%, hvoraf
{nofx['res'].rebalance_cost_share:.0f}% er rebalancering. Årsagen er ikke flere
handler, men dyrere: krypto koster ~25 bp rundtur mod futures' 0,5–2 bp, og med
færre instrumenter får krypto en større vægt.

### Instrumenterne findes ikke lige længe

Porteføljen starter i 1993 med `SPY` alene; `QQQ` kommer i 1999, futures i 2001-02,
krypto i 2018. **Det første tiår er derfor ikke en diversificeret portefølje** — det
er `SPY` med et TSMOM-filter.

Det ses tydeligst på drawdown: porteføljens værste fald på {m['max_drawdown_pct']:.1f}%
indtraf **{_drawdown_date(res.equity)}**, mens porteføljen bestod af `SPY` alene. Fra
2003 og frem er det værste fald
{head['eras']['fra 2003 (≥5 instr.)'][0]['max_drawdown_pct']:.1f}%. Hovedtallets maxDD
måler altså ikke en diversificeret portefølje.

---

## Baseline

Ligevægtet køb-og-behold af de samme syv, samme periode, én rundtur pr. instrument.
Porteføljen giver **{m['cagr']:.2f}%** mod baselinens **{b['cagr']:.2f}%** med
**{m['max_drawdown_pct']:.1f}%** mod **{b['max_drawdown_pct']:.1f}%** i maksimalt
fald og **{m['longest_flat_days'] / 365.25:.1f}** mod
**{b['longest_flat_days'] / 365.25:.1f}** år uden ny top.

Samme mønster som i fase 1, nu på porteføljeniveau: TSMOM slår ikke køb-og-behold på
afkast. Den leverer lidt mindre afkast med under det halve drawdown og den halve
ventetid.

---

## Hvad kørslen ikke viser

- **Syv instrumenter er {head['n_eff_rho']:.1f} væddemål.** Flere uafhængige kilder
  skal komme fra markeder eller strategityper vi ikke har.
- **Kontanter forrentes ikke.** Porteføljen står ude {100 - m['time_in_market_pct']:.0f}%
  af tiden; ved 2-5% p.a. er det
  {(100 - m['time_in_market_pct']) / 100 * 2:.1f}-{(100 - m['time_in_market_pct']) / 100 * 5:.1f}
  pct-point om året strategien ikke får krediteret.
- **`SPY`s bidrag er delvis en historik-effekt** — den har været med i 33 år, krypto
  i 9. Bidragskolonnerne er ikke normaliseret for tid i porteføljen.
- **Vægtningen er ikke optimeret og skal ikke være det.** Invers volatilitet er valgt
  fordi den er parameterfri.

---

## Filer

- `research/portfolio.py` — motoren, `DUPLICATE_UNDERLYING`, bidragsbogholderi
- `research/run_portfolio_test.py` — kørslen og tabelformatet
- `tests/test_portfolio.py` — lookahead, gearingsloft, bidragsandele
- `research/output/portfolio_contributions.csv` — bidrag pr. instrument pr. univers
"""
