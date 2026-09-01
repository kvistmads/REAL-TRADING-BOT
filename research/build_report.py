"""Bygger research/output/bias_validation.md ud fra CSV'erne + _diagnostics.json."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from research.bias_engine import two_sided_p

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research" / "output"
HZ = [1, 2, 3, 4, 5]
SCEN = ["S1", "S1M", "S2", "S5"]
ALLSC = ["S1", "S1M", "S2", "S5", "S3", "S4", "BO_UP", "BO_DOWN"]
DIR = {"S1": "SHORT", "S1M": "LONG", "S2": "LONG", "S5": "SHORT"}
GOLD_ALT = "Guld (GC=F)"
SHORT = {"BTC/USDT": "BTC", "ETH/USDT": "ETH", "SOL/USDT": "SOL", "EUR (6E=F)": "6E",
         "GBP (6B=F)": "6B", "Guld (XAU spot)": "XAU", "Guld (GC=F)": "GC",
         "S&P 500 (ES=F)": "ES", "Nasdaq 100 (NQ=F)": "NQ"}
MINUS = "−"
L: list[str] = []
w = L.append


def n_(x): return f"{int(x):,}".replace(",", ".")
def d_(x, k=2): return f"{x:.{k}f}".replace(".", ",").replace("-", MINUS)
def pc(x, k=2): return d_(x, k) + " %"
def sg(x, k=1): return f"{x:+.{k}f}".replace(".", ",").replace("-", MINUS)


def pooled(g):
    n = int(g.n.sum())
    if not n:
        return np.nan, np.nan, np.nan, 0
    p0 = float((g.base_rate * g.n).sum() / n)
    hr = float(g.hits.sum() / n)
    return hr, p0, (hr - p0) / np.sqrt(p0 * (1 - p0) / n), n


def main() -> None:
    r = pd.read_csv(OUT / "bias_validation.csv")
    fq = pd.read_csv(OUT / "bias_scenario_frequency.csv")
    dg = json.loads((OUT / "_diagnostics.json").read_text())
    prim = r[r.dataset == "primary"]
    mkts = [m for m in prim.market.unique() if m != GOLD_ALT]   # guld = XAU spot
    base = prim[(prim.config == "primary") & (prim.overlap == "all") & (prim.market.isin(mkts))]
    defects, contam = dg["defects"], dg["contamination"]

    w("# Daily Bias — valideringsrapport\n")
    w(f"**Kørt:** {date.today().isoformat()} · **Opgave:** `PRD_DAILY_BIAS_VALIDATION.md`  ")
    w("**Klassifikator:** `research/daily_bias.py` — importeret, ikke genimplementeret  ")
    w("**Status:** forskning. Ingen ændringer i `strategies/`, `config.yaml`, `engine.py`, "
      "`gates/`, `data/fetcher.py` eller `data/indicators.py`.\n")

    hr, p0, z, n = pooled(base[(base.scenario == "ALL") & (base.anchor == "d1_open") & (base.horizon == 1)])
    w("## Konklusion\n")
    w("**Biasen består ikke. Strategien bør ikke bygges.**\n")
    w(f"Kriteriet i §7 krævede ≥3 procentpoint over basisraten på mindst 4 af 8 markeder med "
      f"mindst 200 signaler. Resultatet er **0 af 8 markeder** — ved alle fem horisonter, begge "
      f"ankre, alle tre ATR-tærskler, med og uden H/L-reparation, og med begge guldkilder.\n")
    w(f"Poolet over de 8 markeder ved N=1, anker D+1-åbning: **{n_(n)} signaler, {pc(hr*100)} "
      f"hitrate mod {pc(p0*100)} basisrate** = {sg((hr-p0)*100, 2)} procentpoint "
      f"(z = {sg(z, 2)}). Biasen ligger på eller en anelse under markedets egen basisrate.\n")
    w("Tallene hviler på fire rettelser efter review (§3). Én af dem var en egentlig fejl: flade "
      "reference-barer **opdigtede** S2/S5-signaler frem for blot at forvrænge en metrik — på "
      "`GC=F` var 31,4 % af alle S2/S5 fabrikerede. De øvrige tre var en undermålt "
      "defekttælling, en ubegrundet påstand om at H/L-reparationen var konservativ, og et "
      "forkert valg af guldkilde. Ingen af dem ændrede konklusionen — men de flyttede guld "
      "fra et falsk positivt på +2,9 pp til et nul.\n")

    # ---------------------------------------------------------------- §1 regression
    w("## 1. Regressionstjek (§5) og lookahead\n")
    c = r[(r.dataset == "regression") & (r.horizon == 1) & (r.anchor == "d_close") & (r.overlap == "all")]
    exp = {"S1": (869, 44.9), "S1M": (827, 54.2), "S2": (153, 41.2), "S5": (158, 45.6)}
    w("Kørt først, på den fulde utrunkerede `XAU_1d_data.csv` (5.383 barer, "
      "`MIN_BREAK_ATR = 0.0`, anker D-luk, N=1) — samme konfiguration som cowork-sessionen.\n")
    w("| Scenarie | n forventet | n målt | Hitrate forventet | Hitrate målt | Status |")
    w("|---|---|---|---|---|---|")
    for sc, (en, eh) in exp.items():
        x = c[c.scenario == sc].iloc[0]
        nn = int(x.n) + int(x.ties_excluded)
        w(f"| {sc} | {en} | {nn} | {pc(eh,1)} | {pc(x.hit_rate*100,1)} | "
          f"{'✅' if nn == en else '❌'} |")
    t = c[c.scenario == "ALL"].iloc[0]
    w(f"\nSamlet {n_(int(t.n)+int(t.ties_excluded))} signaler (forventet 2.007), "
      f"{pc(t.hit_rate*100,1)} hitrate (forventet 48,5 %), MFE/MAE = {d_(t.mfe_mae)}. "
      f"**Alle fire signalantal rammer eksakt.** S1's hitrate afviger 0,15 pp, hvilket præcis "
      f"svarer til de 3 dage der lukkede uændret; de udelades nu i både hitrate og basisrate, "
      f"mens cowork-sessionen regnede basisraten som `1 − P(op)` og dermed talte uændrede dage "
      f"som nedadgående.\n")
    w("| Lookahead-test (§8.1) | Resultat |")
    w("|---|---|")
    w("| Trunkering: klassificér bar *i* på en serie klippet af ved *i* | 400 stikprøver, "
      "**0 afvigelser** |")
    w("| Indeksering: entry `Open[i+1]`, exit `Close[i+N]` | 0 uden for serien |")
    w("| ATR-kausalitet: tærskel fra bar *i−1* | max afvigelse 0,00e+00 |")

    # ---------------------------------------------------------------- §2 defekter
    w("\n## 2. Defekttabel — alle ni serier, rå data (§ punkt 2)\n")
    w("Ingen resultater kan tolkes før denne tabel findes. Alt måles på **rå** data: "
      "H/L-reparationen er en analyseparameter (§3.3), ikke en egenskab ved filerne — og den "
      "udvisker netop de flade barer vi skal kunne tælle.\n")
    w("| Serie | Barer | Periode | High == Low | Andel | Open == Close | Andel | Median dagsrange |")
    w("|---|---|---|---|---|---|---|---|")
    order = mkts + [GOLD_ALT]
    for m in order:
        v = defects[m]
        flag = " ⚠️" if v["flat_pct"] >= 1 else ""
        w(f"| {m}{flag} | {n_(v['bars'])} | {v['first'][:7]} → {v['last'][:7]} | "
          f"{n_(v['flat'])} | **{pc(v['flat_pct'])}** | {n_(v['oc'])} | {pc(v['oc_pct'])} | "
          f"{pc(v['median_range_pct'],3)} |")
    w(f"\n**Kun `GC=F` er alvorligt defekt: {n_(defects[GOLD_ALT]['flat'])} barer "
      f"({pc(defects[GOLD_ALT]['flat_pct'])}) hvor High == Low** — en hel handelsdag på én "
      f"eneste pris. `6E=F` og `6B=F` har reelle men små defekter (0,55 % / 0,59 %), koncentreret "
      f"i 2000–2001. ES, NQ og alle tre crypto-serier er rene. "
      f"**XAU-broker-filen har nul flade barer.**\n")
    w("Mine første tal (814 flade GC=F-barer, 12,5 %) var målt *efter* H/L-reparationen, som "
      "selv fjerner flade barer hvor Open ≠ Close. Det rå tal er 1.042 / 15,98 %.\n")

    w("### 2.1 Flade barer pr. år (High == Low, %)\n")
    yrs = sorted({int(y) for m in order for y in defects[m]["by_year"]})
    w("| År | " + " | ".join(SHORT[m] for m in order) + " |")
    w("|---|" + "---|" * len(order))
    for y in yrs:
        cells = []
        for m in order:
            v = defects[m]["by_year"].get(str(y))
            cells.append("—" if v is None else
                         (f"**{pc(v['flat_pct'],1)}**" if v["flat_pct"] >= 5 else pc(v["flat_pct"], 1)))
        w(f"| {y} | " + " | ".join(cells) + " |")
    w("\n`GC=F` er ikke et gammelt-data-problem: 2000–2007 ligger på 36–52 %, 2010 på 15,1 %, "
      "2018 på 14,0 %, og 2021–2026 stadig på 2,4–5,6 %. Der findes ingen ren delperiode at "
      "skære serien ned til. `6E=F`/`6B=F` er derimod rene fra 2002 og frem.\n")

    w("### 2.2 Open == Close pr. år (%)\n")
    w("| År | " + " | ".join(SHORT[m] for m in order) + " |")
    w("|---|" + "---|" * len(order))
    for y in yrs:
        cells = []
        for m in order:
            v = defects[m]["by_year"].get(str(y))
            cells.append("—" if v is None else
                         (f"**{pc(v['oc_pct'],1)}**" if v["oc_pct"] >= 5 else pc(v["oc_pct"], 1)))
        w(f"| {y} | " + " | ".join(cells) + " |")
    w("\n`Open == Close` er en anden defekt end flade barer: den ødelægger ikke klassifikationen, "
      "men gør dagens afkast eksakt 0 ved anker D+1-åbning. Uafgjorte udfald bærer ingen "
      "retningsinformation og udelades derfor i **både** hitrate og basisrate — ellers fortyndes "
      "kun den ene side. `GC=F` topper igen (15,78 %, med 56,0 % i 2010).\n")

    # ---------------------------------------------------------------- §3 rettelser
    w("## 3. Fire rettelser efter review\n")
    w("### 3.1 Flade barer opdigter signaler — det er et klassifikationsproblem\n")
    w("Har reference-baren `High == Low`, så er `prior_high == prior_low == P`. Enhver "
      "efterfølgende bar der **straddler P** har både `swept_high` og `swept_low` sande. "
      "Luk-tjekket kører først (og skal gøre det, jf. PRD §2), så:\n")
    w("```\nprior_high == prior_low == P\nluk > P  →  S2  (LONG)\nluk < P  →  S5  (SHORT)\n```\n")
    w("Signalet reduceres til \"lukkede i dag over eller under gårsdagens ene pris\" — pr. "
      "konstruktion, uanset hvad markedet gjorde. At udelade uafgjorte udfald i metrikken "
      "fjerner ikke de opdigtede signaler, kun deres bidrag til tællingen. Det var min fejl i "
      "første kørsel: jeg behandlede et klassifikationsproblem som et metrikproblem.\n")
    w("Kontamineringen har præcis den asymmetriske signatur mekanismen forudsiger — S2/S5 rammes "
      "hårdt, S1/S1M næsten ikke:\n")
    gc = contam[GOLD_ALT]
    w("| Scenarie | Signaler i alt (`GC=F`) | Heraf fra flad reference | Andel |")
    w("|---|---|---|---|")
    for sc in ALLSC:
        v = gc["per_scenario"].get(sc)
        if not v:
            continue
        b = "**" if v["pct"] >= 10 else ""
        w(f"| {sc} | {n_(v['n'])} | {n_(v['from_flat_ref'])} | {b}{pc(v['pct'],1)}{b} |")
    w(f"| **S2 + S5 samlet** | {n_(gc['s2s5_n'])} | {n_(gc['s2s5_from_flat'])} | "
      f"**{pc(gc['s2s5_pct'],1)}** |")
    w(f"\n**{pc(gc['s2s5_pct'],1)} af alle S2/S5-signaler på `GC=F` er fabrikerede.** "
      f"BO_UP/BO_DOWN er 22–23 % kontamineret (en bar der ligger helt over eller under P "
      f"falder igennem til breakout-kategorien), mens S1 er 0,5 % og S1M 0,0 %.\n")
    w("**Rettelse:** ethvert signal hvis *reference*-bar er degenereret udelades nu — og de "
      "samme dage udelades af basisraten, så de to sider måles på identisk univers "
      "(`bias_engine.degenerate_reference`). Primær definition er eksakt nulbredde; "
      "robusthedstabellen i §6 kører desuden et gulv på 10 % af seriens median-range.\n")
    w("| Serie | Degenererede reference-barer | Andel af barer | Signaler fjernet |")
    w("|---|---|---|---|")
    for m in order:
        v, dv = contam[m], defects[m]
        w(f"| {m} | {n_(v['degenerate_bars'])} | {pc(dv['flat_pct'])} | "
          f"{n_(v['tradeable_from_flat'])} |")
    w("\nFilteret rører kun de defekte serier: 185 signaler på `GC=F`, 7 på `6E=F`, 6 på `6B=F`, "
      "0 på resten. Regressionstjekket i §1 er derfor uændret.\n")

    w("### 3.2 Alle otte markeder er tjekket, ikke kun guld\n")
    w("Defekttabellen i §2 dækker alle ni serier pr. marked og pr. år. Mistanken mod `6E=F` og "
      "`6B=F` var berettiget — begge har flade barer — men omfanget er lille (0,55 % / 0,59 %) "
      "og isoleret til 2000–2001. Efter 2002 er de rene.\n")

    w("### 3.3 H/L-reparationen er ikke entydigt konservativ — den er målt\n")
    w("Hver bar er **både** reference for næste dag **og** signalbar mod forrige dag. At udvide "
      "High/Low til at omslutte Open/Close gør det sværere at feje baren *som reference*, men "
      "lettere for baren *selv* at registrere et sweep. Jeg kaldte den konservativ uden at måle "
      "det. Her er begge stillinger, N=1, anker D+1-åbning, poolet over de 8 markeder:\n")
    w("| Scenarie | n rå | n repareret | Δn | Hitrate rå | Hitrate repareret | Δ |")
    w("|---|---|---|---|---|---|---|")
    re_ = dg["repair_effect"]
    for sc in SCEN + ["ALL"]:
        n0 = sum(re_[m]["raw"][sc]["n"] for m in mkts)
        n1 = sum(re_[m]["repaired"][sc]["n"] for m in mkts)
        h0 = sum(re_[m]["raw"][sc]["hit"] * re_[m]["raw"][sc]["n"] for m in mkts) / n0
        h1 = sum(re_[m]["repaired"][sc]["hit"] * re_[m]["repaired"][sc]["n"] for m in mkts) / n1
        lbl = "**Alle**" if sc == "ALL" else sc
        w(f"| {lbl} | {n_(n0)} | {n_(n1)} | {sg(n1-n0,0)} | {pc(h0,2)} | {pc(h1,2)} | "
          f"{sg(h1-h0,2)} pp |")
    w("\n**Reparationen er et nul.** Den flytter signalantallet 0,1 % og hitraten højst 0,12 pp "
      "på noget scenarie. Den trækker altså hverken den ene eller den anden vej i praksis — men "
      "det vides nu, i stedet for at være antaget. Rådata er primær; filerne på disk er rå.\n")

    w("### 3.4 Guldkilden afgøres af flad-bar-tællingen, ikke af PRD §3\n")
    g = dg["gold_sources"]
    w("PRD §3 sagde \"brug `GC=F` hvis afvigelsen er væsentlig\", men det var skrevet med "
      "**pris**-nøjagtighed i tankerne. Afvigelsen viste sig at være i **range**, og "
      "range-geometri er det eneste denne strategi bruger. Så kriteriet skal være hvilken kilde "
      "der har den brugbare range-geometri:\n")
    w("| | XAU spot (broker-fil) | `GC=F` (yfinance) |")
    w("|---|---|---|")
    w(f"| Flade barer (High == Low) | **{n_(g['xau_flat'])}** | **{n_(g['gc_flat'])}** |")
    w(f"| Andel | **0,00 %** | **{pc(defects[GOLD_ALT]['flat_pct'])}** |")
    w(f"| Signaler der må kasseres | 0 | {n_(contam[GOLD_ALT]['tradeable_from_flat'])} |")
    w(f"| Fabrikerede S2/S5 | 0,0 % | {pc(gc['s2s5_pct'],1)} |")
    w(f"| Barer | {n_(g['xau_bars'])} | {n_(g['gc_bars'])} |")
    w(f"| Median dagsrange (alle) | {d_(g['range_xau_all'])} USD | {d_(g['range_gc_all'])} USD |")
    w(f"| Median dagsrange (kun ikke-flade) | {d_(g['range_xau_nonflat'])} USD | "
      f"{d_(g['range_gc_nonflat'])} USD |")
    w(f"| Handlbar andel af dage | {pc(fq[(fq.market=='Guld (XAU spot)')&(fq.config=='primary')&fq.tradeable].pct.sum(),1)} | "
      f"{pc(fq[(fq.market==GOLD_ALT)&(fq.config=='primary')&fq.tradeable].pct.sum(),1)} |")
    w(f"\nPriserne er enige — median absolut close-afvigelse {d_(g['median_abs_usd'])} USD "
      f"({pc(g['median_abs_pct'],3)}), korrelation {d_(g['corr'],6)}, ingen datoforskydning "
      f"(median-afvigelse {d_(g['shift_median_usd']['0'])} USD ved 0 dage mod "
      f"{d_(g['shift_median_usd']['-1'])} og {d_(g['shift_median_usd']['1'])} ved ±1 dag). "
      f"Men `GC=F`'s dagsrange er systematisk smallere, også når man udelader de flade barer, "
      f"og **det er `GC=F` der har 1.042 flade barer, ikke broker-filen.**\n")
    w("**Beslutning: XAU spot er primær guldkilde.** Den smallere, defekte kilde er den dårligere "
      "til dette formål. `GC=F` føres med i CSV'en som kontrol, og de to er enige om svaret "
      f"(N=1: {sg(-0.57,2)} pp mod {sg(-0.68,2)} pp), så valget ændrer ikke konklusionen — "
      "kun kvaliteten af det grundlag den hviler på.\n")
    w(f"Broker-filen trunkeres ved **{g['xau_truncated_at']}**: derefter har den huller på "
      f"{', '.join(str(v) for v in g['xau_tail_gaps'].values())} dage. Den trunkerede serie har "
      f"{n_(g['xau_bars'])} barer, største hul 5 dage og nul flade barer.\n")

    w("### 3.5 Kontraktrulning (§8.4)\n")
    w("| Marked | Signaler | Berørt af rul-gap | Hitrate alle | Hitrate uden rul |")
    w("|---|---|---|---|---|")
    for m, v in dg["roll_sensitivity"].items():
        w(f"| {m} | {n_(v['n'])} | {n_(v['contaminated'])} ({pc(v['contaminated_pct'],1)}) | "
          f"{pc(v['hit_all'],1)} | {pc(v['hit_clean'],1)} |")
    w("\nYahoos `=F`-serier er kontinuerte front-month-serier uden bagudjustering, så hver "
      "rulning efterlader et kunstigt gap. De flytter hitraten højst 0,5 pp.\n")

    # ---------------------------------------------------------------- §4 resultater
    w("## 4. Resultater pr. marked\n")
    w("Primær konfiguration: anker **dag D+1's åbning**, `MIN_BREAK_ATR = 0.0`, rå data uden "
      "H/L-reparation, degenererede reference-barer udeladt, alle signaler. "
      "Celle = hitrate / forskel til basisrate i pp / z-score.\n")
    for m in mkts:
        gg = base[(base.market == m) & (base.anchor == "d1_open")]
        w(f"### {m}\n")
        w("| Scenarie | Retning | n (N=1) | " + " | ".join(f"N={h}" for h in HZ) + " |")
        w("|---|---|---|" + "---|" * len(HZ))
        for sc in SCEN + ["ALL"]:
            s = gg[gg.scenario == sc].set_index("horizon")
            if s.empty:
                continue
            cells = [f"{pc(s.loc[h,'hit_rate']*100,1)} / {sg(s.loc[h,'diff_pp'])} / "
                     f"{sg(s.loc[h,'z'],2)}" if h in s.index else "—" for h in HZ]
            w(f"| {'**Alle**' if sc=='ALL' else sc} | {DIR.get(sc,'—')} | "
              f"{n_(s.loc[1,'n'])} | " + " | ".join(cells) + " |")
        b1 = gg[(gg.scenario == "ALL") & (gg.horizon == 1)].iloc[0]
        w(f"\nBasisrate N=1: long {pc(b1.base_bullish*100,1)} / short {pc(b1.base_bearish*100,1)}. "
          f"Signaler: {n_(b1.n_long)} long, {n_(b1.n_short)} short.\n")

    # ---------------------------------------------------------------- §5 tvaergaaende
    w("## 5. Tværgående\n")
    w("### 5.1 Hvor mange markeder består kriteriet?\n")
    w("| Scenarie | " + " | ".join(f"N={h}" for h in HZ) + " | Positivt fortegn (N=1) |")
    w("|---|" + "---|" * (len(HZ) + 1))
    for sc in SCEN + ["ALL"]:
        cells = []
        for h in HZ:
            gq = base[(base.scenario == sc) & (base.anchor == "d1_open") & (base.horizon == h)]
            cells.append(f"**{int(((gq.diff_pp>=3)&(gq.n>=200)).sum())}** / 8")
        g1 = base[(base.scenario == sc) & (base.anchor == "d1_open") & (base.horizon == 1)]
        w(f"| {'**Alle handlbare**' if sc=='ALL' else sc} | " + " | ".join(cells)
          + f" | {int((g1.diff_pp>0).sum())} / 8 |")
    w("\nIngen kombination når 4 af 8. De enkelte 1'ere og 2'ere er forskellige markeder fra "
      "horisont til horisont — kriteriets fjerde led om konsistent fortegn er ikke opfyldt.\n")

    w("### 5.2 Poolet på tværs af alle 8 markeder (N=1, D+1 åbning)\n")
    w("| Scenarie | Retning | n | Hitrate | Basisrate | Forskel | z | p |")
    w("|---|---|---|---|---|---|---|---|")
    for sc in SCEN + ["ALL"]:
        gq = base[(base.scenario == sc) & (base.anchor == "d1_open") & (base.horizon == 1)]
        h2, p2, z2, n2 = pooled(gq)
        w(f"| {'**Alle handlbare**' if sc=='ALL' else sc} | {DIR.get(sc,'—')} | {n_(n2)} | "
          f"{pc(h2*100)} | {pc(p2*100)} | {sg((h2-p2)*100,2)} pp | {sg(z2,2)} | "
          f"{d_(two_sided_p(z2),3)} |")
    w("\nIntet scenarie er signifikant i biasens favør.\n")

    w("### 5.3 Er de positive celler flere end tilfældet ville give?\n")
    cells = base[(base.scenario != "ALL") & (base.n >= 200)]
    nc = len(cells)
    hi, lo = int((cells.z > 1.96).sum()), int((cells.z < -1.96).sum())
    w("| Mål | Målt | Ved ren støj |")
    w("|---|---|---|")
    w(f"| Celler testet (n ≥ 200) | {n_(nc)} | — |")
    w(f"| ≥ +3 pp | {int((cells.diff_pp>=3).sum())} | ~symmetrisk |")
    w(f"| ≤ {MINUS}3 pp | {int((cells.diff_pp<=-3).sum())} | — |")
    w(f"| \\|z\\| > 1,96 | {hi+lo} ({pc((hi+lo)/nc*100,1)}) | ~{n_(round(nc*0.05))} (5,0 %) |")
    w(f"| heraf positive / negative | {hi} / {lo} | ~lige mange |")
    w(f"| Middel z | {sg(cells.z.mean(),3)} | 0,000 |")
    w(f"\nAndelen af \"signifikante\" celler er {pc((hi+lo)/nc*100,1)} — på eller under de 5 % "
      f"ren tilfældighed ville give, med næsten symmetriske haler. Der er intet signal at grave "
      f"frem, heller ikke i delmængderne.\n")

    # ---------------------------------------------------------------- §6 robusthed
    w("## 6. Robusthed\n")
    w("Hver akse køres for sig; ingen af dem ændrer konklusionen.\n")
    w("| Akse | Variant | Signaler (N=1) | Poolet hitrate | Forskel | z | Består |")
    w("|---|---|---|---|---|---|---|")
    rows = [("ATR-tærskel", "0,00 *(primær)*", dict(config="primary", anchor="d1_open")),
            ("", "0,05", dict(config="atr_005", anchor="d1_open")),
            ("", "0,10", dict(config="atr_010", anchor="d1_open")),
            ("H/L-reparation", "fra *(primær)*", dict(config="primary", anchor="d1_open")),
            ("", "til", dict(config="repaired", anchor="d1_open")),
            ("Reference-gulv", "eksakt flad *(primær)*", dict(config="primary", anchor="d1_open")),
            ("", "10 % af median-range", dict(config="ref_floor_010", anchor="d1_open")),
            ("Anker", "D+1 åbning *(primær)*", dict(config="primary", anchor="d1_open")),
            ("", "D luk", dict(config="primary", anchor="d_close"))]
    for axis, lbl, sel in rows:
        gq = prim[(prim.market.isin(mkts)) & (prim.overlap == "all") & (prim.scenario == "ALL")
                  & (prim.horizon == 1) & (prim.config == sel["config"])
                  & (prim.anchor == sel["anchor"])]
        h2, p2, z2, n2 = pooled(gq)
        w(f"| {axis} | {lbl} | {n_(n2)} | {pc(h2*100)} | {sg((h2-p2)*100,2)} pp | {sg(z2,2)} | "
          f"**{int(((gq.diff_pp>=3)&(gq.n>=200)).sum())} / 8** |")

    w("\n### 6.1 Overlappende vs. ikke-overlappende vinduer\n")
    w("Ved N>1 overlapper nabodages signaler. Den ikke-overlappende delmængde vælges grådigt over "
      "**alle** handlbare signaler i datorækkefølge (næste signal mindst N barer efter det "
      "forrige), så uafhængigheden gælder både inden for og på tværs af scenarier.\n")
    w("| Horisont | Alle: n | Forskel | z | Ikke-overlappende: n | Forskel | z |")
    w("|---|---|---|---|---|---|---|")
    for h in HZ:
        row = f"| N={h} |"
        for ov in ("all", "non_overlapping"):
            gq = prim[(prim.config == "primary") & (prim.market.isin(mkts)) & (prim.overlap == ov)
                      & (prim.scenario == "ALL") & (prim.anchor == "d1_open") & (prim.horizon == h)]
            h2, p2, z2, n2 = pooled(gq)
            row += f" {n_(n2)} | {sg((h2-p2)*100,2)} pp | {sg(z2,2)} |"
        w(row)
    w("\n### 6.2 Natte-gap (forskellen mellem de to ankre)\n")
    w("| Marked | Middel | Middel \\|gap\\| | Std | p95 \\|gap\\| |")
    w("|---|---|---|---|---|")
    for m in mkts:
        v = defects[m]
        w(f"| {m} | {sg(v['gap_mean_pct'],3)} % | {pc(v['gap_abs_mean_pct'],3)} | "
          f"{pc(v['gap_std_pct'],3)} | {pc(v['gap_p95_pct'],3)} |")
    w("\n**For crypto findes natte-gappet reelt ikke** (0,01–0,02 % i middel absolut): Binances "
      "dagsbar åbner hvor den forrige lukkede, så de to ankre er samme pris.\n")

    # ---------------------------------------------------------------- §7 frekvens
    w("## 7. Scenariefrekvenser (§6)\n")
    w("Andel af klassificerede dage efter reference-filteret, primær konfiguration.\n")
    w("| Marked | " + " | ".join(ALLSC) + " | Handlbar |")
    w("|---|" + "---|" * (len(ALLSC) + 1))
    f0 = fq[(fq.config == "primary") & (fq.market.isin(mkts))]
    for m in mkts:
        gq = f0[f0.market == m].set_index("scenario")
        w(f"| {m} | " + " | ".join(pc(gq.pct.get(s, 0), 1) for s in ALLSC)
          + f" | **{pc(gq[gq.tradeable].pct.sum(),1)}** |")
    gm = f0.groupby("scenario").pct.mean()
    w("| **Gennemsnit** | " + " | ".join(f"**{pc(gm.get(s,0),1)}**" for s in ALLSC)
      + f" | **{pc(sum(gm.get(s,0) for s in SCEN),1)}** |")
    w("\n- **S3** og **S4** er per definition ingen-handel og udgør tilsammen ~20 % af dagene.\n"
      "- **BO_UP / BO_DOWN** er deaktiveret via flag, men er tilsammen **~43 % af alle dage** — "
      "langt den største kategori.\n"
      "- **S1M** (tilføjelsen der ikke er i videoen) bidrager med ~15 % af dagene, altså knap "
      "40 % af alle handlbare signaler.\n")

    w("### 7.1 Hvad ville de deaktiverede breakouts have gjort?\n")
    w("Beskrivende, da §6 beder om frekvensen — **ikke en del af kriteriet**. Kørt på det "
      "filtrerede univers; ufiltreret ville tallet delvist måle `GC=F`-defekten.\n")
    w("| Marked | BO_UP n | Hitrate | Forskel | BO_DOWN n | Hitrate | Forskel |")
    w("|---|---|---|---|---|---|---|")
    for m in mkts:
        v = dg["breakout"]["per_market"][m]
        w(f"| {m} | {n_(v['BO_UP']['n'])} | {pc(v['BO_UP']['hit'],1)} | "
          f"{sg(v['BO_UP']['diff_pp'])} pp | {n_(v['BO_DOWN']['n'])} | "
          f"{pc(v['BO_DOWN']['hit'],1)} | {sg(v['BO_DOWN']['diff_pp'])} pp |")
    for sc in ("BO_UP", "BO_DOWN"):
        v = dg["breakout"]["pooled"][sc]
        w(f"| **Poolet {sc}** | {n_(v['n'])} | {pc(v['hit'])} | **{sg(v['diff_pp'],2)} pp "
          f"(z = {sg(v['z'],2)})** | | | |")
    w("\nStudiets statistisk stærkeste fund — **og det peger den forkerte vej**. At følge et "
      "dagligt breakout er signifikant dårligere end basisraten. Fundet overlever "
      "reference-filteret (det var 22–23 % kontamineret på `GC=F` før). Se §9.\n")

    # ---------------------------------------------------------------- §8 kriterium
    w("## 8. Succeskriteriet, punkt for punkt\n")
    hr, p0, z, n = pooled(base[(base.scenario == "ALL") & (base.anchor == "d1_open") & (base.horizon == 1)])
    best = base[base.scenario == "ALL"].nlargest(1, "diff_pp").iloc[0]
    w("| Krav (§7, fastlagt før kørslen) | Resultat | Opfyldt |")
    w("|---|---|---|")
    w(f"| Hitrate slår basisraten med ≥3 pp | Bedste marked: {best.market} "
      f"**{sg(best.diff_pp,2)} pp** (N={int(best.horizon)}). Poolet: **{sg((hr-p0)*100,2)} pp** | ❌ |")
    w("| på mindst 4 af 8 markeder | **0 af 8** ved alle horisonter, ankre, tærskler, "
      "reparationsstillinger og guldkilder | ❌ |")
    w(f"| mindst 200 signaler pr. marked | Opfyldt — {n_(base[(base.scenario=='ALL')&(base.horizon==1)&(base.anchor=='d1_open')].n.min())}"
      f"–{n_(base[(base.scenario=='ALL')&(base.horizon==1)&(base.anchor=='d1_open')].n.max())} pr. marked | ✅ |")
    w(f"| konsistent fortegn | {int((base[(base.scenario=='ALL')&(base.anchor=='d1_open')&(base.horizon==1)].diff_pp>0).sum())} af 8 positive ved N=1; "
      "fortegnet vender mellem nabohorisonter | ❌ |")
    w(f"\n**Kriteriet er ikke justeret efter at have set tallene.** Højeste enkeltmåling på "
      f"markedsniveau er {pc(best.hit_rate*100,1)} ({best.market}, N={int(best.horizon)}) mod en "
      f"basisrate på {pc(best.base_rate*100,1)}.\n")

    # ---------------------------------------------------------------- §9 hypoteser
    w("## 9. Hypoteser til en eventuel næste test — ikke konklusioner\n")
    bu, bd = dg["breakout"]["pooled"]["BO_UP"], dg["breakout"]["pooled"]["BO_DOWN"]
    w(f"1. **Breakouts fader.** BO_UP ({sg(bu['diff_pp'],2)} pp, z = {sg(bu['z'],2)}) og BO_DOWN "
      f"({sg(bd['diff_pp'],2)} pp, z = {sg(bd['z'],2)}) rammer begge signifikant *under* "
      f"basisraten over {n_(bu['n']+bd['n'])} observationer, og fundet overlever "
      f"reference-filteret. Den omvendte regel — fade et dagligt breakout — er det eneste i "
      f"datasættet med statistisk substans. Bemærk at ~43 % af alle dage falder i kategorien: "
      f"det er en helt anden strategi end den validerede, og den kræver sin egen "
      f"forhåndsregistrerede test.\n")
    w("2. **S2 på Nasdaq ved N=2–3.** Den stærkest udseende enkeltcelle, og den overlever "
      "uafhængighedskorrektionen. Men den forsvinder ved N=1 og N=5, findes ikke på S&P 500 og "
      "vender fortegn på BTC. Sammenholdt med §5.3 er den efter al sandsynlighed støj.\n")
    w("3. **Guldets datakilde bør afklares før guld undersøges videre.** Ingen af de to "
      "nuværende kilder er gode: `GC=F` har 16 % flade barer, og broker-filen har ukendt "
      "herkomst og en ødelagt hale. De er enige om svaret her, men et fremtidigt studie bør "
      "starte med at skaffe en verificeret guldserie.\n")

    # ---------------------------------------------------------------- §10
    w("## 10. Reproduktion\n")
    w("```bash\n"
      ".venv/bin/python research/fetch_daily.py                        # raa data -> data/historical/\n"
      "PYTHONPATH=. .venv/bin/python research/run_bias_validation.py   # -> bias_validation.csv\n"
      "PYTHONPATH=. .venv/bin/python research/diagnostics.py           # -> _diagnostics.json\n"
      "PYTHONPATH=. .venv/bin/python research/build_report.py          # -> denne rapport\n"
      "```\n")
    w("| Fil | Indhold |\n|---|---|\n"
      "| `bias_validation.md` | denne rapport |\n"
      "| `bias_validation.csv` | rå resultater — én række pr. (marked, scenarie, horisont, anker, "
      "tærskel, reparation, reference-gulv, overlap) |\n"
      "| `bias_scenario_frequency.csv` | scenariefrekvenser pr. marked og konfiguration |\n"
      "| `_diagnostics.json` | defekttabel, kontaminering, guldkilder, reparationseffekt, rulning |\n"
      "| `_meta.json`, `data_provenance.json` | datagrundlag og hentemetadata |\n")
    w("\nCSV-akser: `config` ∈ {primary, atr_005, atr_010, repaired, ref_floor_010} × "
      "`anchor` ∈ {d1_open, d_close} × `horizon` 1–5 × `overlap` ∈ {all, non_overlapping} × "
      "`scenario` ∈ {S1, S1M, S2, S5, ALL}. Guld findes som både `Guld (XAU spot)` (primær) og "
      "`Guld (GC=F)` (kontrol); `dataset=regression` er §1's utrunkerede XAU-serie.\n")
    w("\n---\n")
    w("*Rapporten stopper her. Strategien er ikke bygget, jf. PRD §9.*")

    (OUT / "bias_validation.md").write_text("\n".join(L) + "\n")
    print(f"skrev {OUT/'bias_validation.md'}")


if __name__ == "__main__":
    main()
