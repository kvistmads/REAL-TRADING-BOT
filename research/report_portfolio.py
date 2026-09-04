"""Rapportgenerator for fase 2 — porteføljekombinationen."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _side_by_side(strat: pd.DataFrame, asset: pd.DataFrame, keys: list[str]) -> str:
    """Parvis: strategikorrelation, aktivkorrelation og forskellen mellem dem.

    Forskellen ER pointen. Er strategierne markant mindre korrelerede end
    aktiverne, køber TSMOM diversificering oven i den aktiverne allerede giver.
    Er de det ikke, er antallet af uafhængige væddemål det samme som før.
    """
    cs, ca = strat[keys].corr(), asset[keys].corr()
    rows = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            s, v = float(cs.loc[a, b]), float(ca.loc[a, b])
            rows.append({"par": f"{a}–{b}", "strategi": round(s, 2),
                         "aktiv": round(v, 2), "forskel": round(s - v, 2)})
    df = pd.DataFrame(rows).sort_values("aktiv", ascending=False)
    return df.to_string(index=False)


def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    rows = ["| " + " | ".join(str(v) for v in row) + " |"
            for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


def _drawdown_date(curve: pd.Series) -> str:
    dd = curve / curve.cummax() - 1
    return str(dd.idxmin().date())


def build(results, strat_m, asset_m, sharpes, session,
          n_eff_rho, n_eff_eig, offdiag) -> str:
    head = results["alle_otte"]
    nofx = results["uden_fx"]
    keys = head["keys"]
    rho_s, rho_a = offdiag(strat_m[keys].corr()), offdiag(asset_m[keys].corr())
    m, b = head["metrics"], head["baseline"]

    sharpe_tbl = pd.DataFrame(
        [{"instrument": k, "Sharpe": round(v, 2)} for k, v in sharpes.items()])

    weights = head["res"].weights.tail(1).round(3).T
    weights.columns = ["vægt"]
    weights = weights.reset_index().rename(columns={"index": "instrument"})

    return f"""# Fase 2 — porteføljekørsel: virker diversificering på vores egne tal?

**Kørsel:** de otte TSMOM-kurver kombineret til én portefølje, invers volatilitet,
månedlig rebalancering.
**Periode:** {head['res'].equity.index[0].date()} → {head['res'].equity.index[-1].date()}
**Status:** research. Ingen ændring af live handelsadfærd, `config.yaml` urørt.

---

## Svaret

**Diversificering virker — men mindre end forventet, og af en grund der er værd at
kende: strategikorrelationerne er næsten lige så høje som aktivkorrelationerne.**

```
{session}
```

| Forhåndsregistreret | Forventet | Faktisk | |
|---|---|---|---|
| Samlet Sharpe | 1,0–1,2 | **{m['sharpe']:.2f}** | under båndet, men klart over fejlgrænsen på 0,7 |
| maxDD | 20–25% | **{m['max_drawdown_pct']:.1f}%** | bedre end forventet |
| longest_flat_days | markant under SPY's 1685 / QQQ's 3958 | **{m['longest_flat_days']}** | holder |

Ingen af de to fælder blev udløst: Sharpe er hverken ≥1,5 (som ville have peget på
lookahead i vægtningen) eller ≤0,7 (som ville have betydet at diversificeringen ikke
virker).

**Det tal du sagde betød mest — longest_flat_days — er det der falder klarest ud.**
Porteføljen går {m['longest_flat_days']} dage som værst uden ny egenkapitaltop, mod
1.685 for `SPY` alene, 3.958 for `QQQ` og {b['longest_flat_days']} for ligevægtet
køb-og-behold af de samme otte. Det er stadig godt tre år, men det er den halve
ventetid.

---

## DEL 2.1 — den vigtigste måling: strategi- mod aktivkorrelation

Du havde ret i at det var det forkerte tal jeg målte i fase 1. Her er begge.

Gennemsnitlig parvis korrelation over de otte:

| | Gennemsnit | Effektive væddemål (ρ) | Effektive væddemål (egenværdier) |
|---|---|---|---|
| **Strategiernes** månedlige afkast | **{rho_s:+.3f}** | **{n_eff_rho(strat_m[keys].corr()):.2f}** | {n_eff_eig(strat_m[keys].corr()):.2f} |
| Aktivernes månedlige afkast | {rho_a:+.3f} | {n_eff_rho(asset_m[keys].corr()):.2f} | {n_eff_eig(asset_m[keys].corr()):.2f} |

**Forventningen var at strategikorrelationerne ville være markant lavere. Det er de
ikke.** {rho_s:.3f} mod {rho_a:.3f} er en reduktion på
{100 * (1 - rho_s / rho_a):.0f}% — reel, men ikke i nærheden af nok til at gøre otte
instrumenter til otte væddemål.

Par for par (sorteret efter aktivkorrelation):

```
{_side_by_side(strat_m, asset_m, keys)}
```

Tre ting at læse ud af den tabel:

1. **`GC`–`XAU` er 0,98 i BEGGE matricer.** Det er ikke to instrumenter, det er ét
   metal hentet fra to kilder. Diversificering kan ikke reparere det, for der er
   ingen uafhængighed at hente.
2. **`SPY`–`QQQ` falder kun fra 0,84 til 0,81.** De to strategier er ude af markedet
   på næsten samme tidspunkter, fordi de reagerer på det samme signal i det samme
   marked. Long-only TSMOM fjerner nedture, men det fjerner dem samtidigt.
3. **Krypto er det eneste sted mekanismen virker som håbet:** `BTC`–`ETH` falder fra
   0,72 til 0,63, fordi de to faktisk går ud af markedet på forskellige tidspunkter.

Det er svaret på hvorfor Sharpe landede på {m['sharpe']:.2f} og ikke 1,1: der er
**{head['n_eff_rho']:.1f} effektive væddemål, ikke 4.**

Forudsigelsen holder til gengæld præcist. Gennemsnitlig individuel Sharpe er
{head['s_bar']:.2f}; {head['s_bar']:.2f} × √{head['n_eff_rho']:.2f} =
**{head['predicted_sharpe']:.2f}** forudsagt mod **{m['sharpe']:.2f}** faktisk.
Formlen `s × √N` virker — det var antagelsen om N der var for optimistisk.

De to N-mål er ikke enige ({head['n_eff_rho']:.2f} mod {head['n_eff_eig']:.2f}), og
uenigheden er informativ: porteføljen er **klynget**, ikke jævnt korreleret. To par
sidder på 0,98 og 0,81 mens de fleste krydspar ligger under 0,15. ρ-udgaven antager
at alle par er ens og straffer derfor hårdt; egenværdierne ser klyngerne. Sandheden
ligger imellem, og den faktiske Sharpe ({m['sharpe']:.2f}) ligger da også mellem de
to forudsigelser.

### Individuelle Sharpe-tal, til reference

{_md_table(sharpe_tbl)}

Gennemsnit: **{head['s_bar']:.2f}** over alle otte, **{nofx['s_bar']:.2f}** uden FX.

---

## DEL 1 — hvordan porteføljen er bygget

- **Vægt:** invers volatilitet, `w_i = (1/σ_i) / Σ(1/σ_j)`, altså lige risikobidrag.
- **σ måles bagudskuende** på 12 måneders daglige afkast frem til dagen FØR
  rebalanceringen, og annualiseres med instrumentets eget antal barer pr. år
  (krypto 365, futures ~252). Uden den korrektion ville krypto se ~20% mere volatil
  ud end den er, alene på grund af kalenderen.
- **Rebalancering:** månedligt, samtidig med TSMOM-signalet.
- **Pladsen holder TSMOM-positionen**, ikke aktivet. Er signalet ude, står pladsens
  kapital i kontanter, og kontanter forrentes ikke.
- **Ingen gearing.** En plads kan aldrig købe for mere end sin egen værdi plus
  kontantbeholdningen — og loftet levner plads til kurtagen. Uden det sidste endte
  kontantbeholdningen på minus gebyret: et lån på 1-2 basispunkter, som ville have
  set ud som afkast. Det blev fanget af `test_portfolio_never_uses_leverage`.

### Omkostninger: to kilder til omsætning

Samlet **{head['res'].turnover_cost_pct:.2f}%** af startkapitalen over
{m['years']:.0f} år, hvoraf **{head['res'].rebalance_cost_share:.0f}%** er ren
vægtrebalancering — altså omsætning ud over signalskiftene. Den del ville være
usynlig hvis man kun havde modelleret ind- og udgange.

### Instrumenterne findes ikke lige længe

Porteføljen starter i 1993 med `SPY` alene. `QQQ` kommer i 1999, futures i 2001-02,
krypto i 2018. Kapitalen fordeles kun på de instrumenter der findes, og resten står
i kontanter. Det betyder at **det første tiår ikke er en diversificeret portefølje** —
det er `SPY` med et TSMOM-filter.

Derfor står æra-linjerne i tabellen. De er beskrivende, ikke et valg af periode:
fra 2018, hvor alle otte findes, er Sharpe
{head['eras'].get('fra 2018 (alle 8)', ({},))[0].get('sharpe', float('nan')):.2f} —
inde i det forhåndsregistrerede bånd. **Hovedtallet er stadig hele perioden**, som
aftalt; æra-tallene siger hvor meget af afstanden til båndet der skyldes at
porteføljen ikke var en portefølje endnu.

**Det tydeligste enkelttal her:** porteføljens værste drawdown på
{m['max_drawdown_pct']:.1f}% indtraf **{_drawdown_date(head['res'].equity)}** — altså i
den periode hvor porteføljen bestod af `SPY` alene. Fra 2003 og frem, hvor mindst
fem instrumenter er med, er det værste fald {head['eras']['fra 2003 (≥5 instr.)'][0]['max_drawdown_pct']:.1f}%.
Det maksimale tab i hovedtallet måler altså ikke en diversificeret portefølje; det
måler ét instrument. Baselinens {b['max_drawdown_pct']:.1f}% indtraf til
sammenligning {_drawdown_date(head['res'].benchmark)}, hvor alle otte var med.

---

## DEL 3 — FX-varianten

{_md_table(pd.DataFrame([
    {"univers": n, "n": len(r["keys"]), "CAGR": r["metrics"]["cagr"],
     "maxDD": r["metrics"]["max_drawdown_pct"], "Sharpe": r["metrics"]["sharpe"],
     "flat_dage": r["metrics"]["longest_flat_days"],
     "ρ_strategi": round(r["rho_bar"], 3), "N_eff": round(r["n_eff_rho"], 2)}
    for n, r in results.items()]))}

Uden `6E`/`6B` stiger CAGR fra {m['cagr']:.2f}% til {nofx['metrics']['cagr']:.2f}% og
Sharpe fra {m['sharpe']:.2f} til {nofx['metrics']['sharpe']:.2f}.

**Men det er ikke en begrundelse for at fjerne dem.** Argumentet — at valutaer ikke
har nogen langsigtet drift, så long-only momentum ikke har noget at fange — er
strukturelt korrekt, men det blev formuleret EFTER vi så tallene. Det er derfor en
**hypotese til næste kørsel**, ikke en konklusion fra denne. Hovedtallet er alle otte.

Bemærk desuden at FX' bidrag ikke kun er lavt afkast: `ρ_strategi` er stort set
uændret ({head['rho_bar']:.3f} mod {nofx['rho_bar']:.3f}) når de fjernes. De to
FX-kryds tilfører altså hverken afkast eller uafhængighed.

---

## DEL 4 — baseline

Ligevægtet køb-og-behold af de samme instrumenter, samme periode, samme
omkostningskonvention (én rundtur pr. instrument over hele perioden). Instrumenter
der starter senere købes når de findes; kapitalen står i kontanter indtil da —
ellers skulle baselinen enten forudse hvornår Binance åbnede, eller måles på en
kortere periode end strategien.

Porteføljen giver **{m['cagr']:.2f}%** mod baselinens **{b['cagr']:.2f}%** — altså
stort set samme afkast — med **{m['max_drawdown_pct']:.1f}%** mod
**{b['max_drawdown_pct']:.1f}%** i maksimalt fald og
**{m['longest_flat_days']}** mod **{b['longest_flat_days']}** dage uden ny top.

Det er samme mønster som i fase 1, nu på porteføljeniveau: TSMOM slår ikke
køb-og-behold på afkast. Den leverer omtrent samme afkast med under det halve
drawdown.

---

## Lookahead — hvad der er testet

Invers volatilitet beregnet på HELE perioden er den klassiske skjulte fejl her: den
undervægter systematisk de instrumenter der senere viste sig turbulente, den pynter
Sharpe, og den efterlader ingen spor i resultatet.

`tests/test_portfolio.py` har tre spærringer, og alle tre er efterprøvet ved at
indsætte fejlen og se dem køre rødt:

- `test_weights_ignore_all_future_data` — ødelægger alle barer fra
  rebalanceringsdagen og frem og kræver vægtene uændrede, over 32 månedsskifter.
- `test_trailing_vol_excludes_the_rebalance_bar_itself` — grænsen er strengt `<`,
  ikke `<=`. Rebalanceringsdagens egen bar er allerede fremtid.
- `test_equity_before_a_date_is_unaffected_by_later_data` — hele porteføljen kørt på
  afkortede serier, kurven skal være identisk på det fælles stykke.

Begge de to realistiske fejl (`<= asof`, og fuldperiode-volatilitet) får testene til
at fejle.

---

## Hvad kørslen ikke viser

- **Otte instrumenter er ~{head['n_eff_rho']:.1f} væddemål.** Vil man have flere
  uafhængige kilder, skal de komme fra markeder eller strategityper vi ikke har,
  ikke fra flere varianter af det samme.
- **`GC` og `XAU` dobbelttæller guld** (ρ 0,98). Det præregistrerede univers har dem
  begge, så hovedtallet har dem begge — men et gennemsnit over otte instrumenter
  hvor to er identiske, vægter guld dobbelt.
- **Kontanter forrentes stadig ikke.** Porteføljen står uden for markedet
  {100 - m['time_in_market_pct']:.0f}% af tiden. Ved 2-5% p.a. er det
  {(100 - m['time_in_market_pct']) / 100 * 2:.1f}-{(100 - m['time_in_market_pct']) / 100 * 5:.1f}
  pct-point om året som strategien ikke får krediteret. Testen er konservativ.
- **Ingen valutaeffekt.** Alt er regnet i USD som om kapitalen var i USD.
- **Vægtningen er ikke optimeret, og skal ikke være det.** Invers volatilitet er
  valgt fordi den er parameterfri, ikke fordi den er bedst.

---

## Filer

- `research/portfolio.py` — kombinationsmotoren, vægtning og bogholderi
- `research/run_portfolio_test.py` — kørslen og de forhåndsregistrerede grænser
- `tests/test_portfolio.py` — lookahead-spærringerne og gearingsloftet, 8 tests
- `research/output/portfolio_combination.csv` — begge universer, alle nøgletal
"""
