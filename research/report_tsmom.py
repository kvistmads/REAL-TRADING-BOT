"""Rapportgenerator for fase 1 — apparatvalideringen.

Adskilt fra ``run_tsmom_test.py`` af samme grund som ``build_report.py`` er adskilt
fra bias-kørslen: kørslen skal kunne læses uden at skulle igennem tekstskabeloner,
og teksten skal kunne rettes uden at røre en beregning.
"""

from __future__ import annotations

import pandas as pd

from research.daily_series import INSTRUMENTS, load


def _correlation_block() -> str:
    """Er de otte instrumenter otte uafhængige væddemål? Nej — og det skal stå der."""
    closes = {}
    for key, inst in INSTRUMENTS.items():
        df = load(inst)
        closes[key] = df.set_index("time")["close"].pct_change()
    corr = pd.DataFrame(closes).corr().round(2)
    return corr.to_string()


def build(qdf, yearly, rdf, rule, verdict, passed, span, md_table, session) -> str:
    rule_df = pd.DataFrame(rule)
    by_lb = rdf[rdf.rebalance_day == 1].pivot_table(
        index="instrument", columns="lookback", values="cagr").round(2)
    dd_lb = rdf[rdf.rebalance_day == 1].pivot_table(
        index="instrument", columns="lookback", values="dd_reduktion").round(2)
    by_day = rdf.pivot_table(index="instrument", columns="rebalance_day",
                             values="cagr").round(2)

    turn = rule_df[["instrument", "positioner", "tid_i_marked_%", "hold_mdr",
                    "skift_pr_år", "omk_%_af_brutto"]]
    slip = rule_df[["instrument", "slip_n", "slip_efter_1", "slip_median", "slip_maks"]]
    subs = "\n".join(
        f"| {r['instrument']} | {r['delperioder']} | {r['delperioder_positive']}/4 "
        f"| {r['delperioder_samme_fortegn']}/4 |" for r in rule)

    ejerskab = qdf[["instrument", "kilde", "ejerskab", "afkastgrundlag"]]

    return f"""# Fase 1 — kan apparatet finde en edge der beviseligt findes?

**Kørsel:** time-series momentum, 12 måneders lookback, rebalancering den 1.
**Periode:** {span}
**Status:** research. Ingen ændring af live handelsadfærd, `config.yaml` urørt.

---

## Svaret

**Ja.** Alle tre præregistrerede krav holder, og de holder netop dér hvor effekten
er bedst dokumenteret: `SPY` og `GC=F` består begge alle tre krav.

```
{session}
```

| Krav | Tærskel | Resultat | Instrumenter |
|---|---|---|---|
| 1. Positivt netto-afkast | ≥4 af 8 | **{verdict['krav1_positivt_afkast'][0]}/8** | {', '.join(verdict['krav1_positivt_afkast'][1])} |
| 2. Materielt lavere maxDD end B&H | ≥4 af 8 | **{verdict['krav2_lavere_drawdown'][0]}/8** | {', '.join(verdict['krav2_lavere_drawdown'][1])} |
| 3. Positivt afkast i ≥3 af 4 delperioder | ≥4 af 8 | **{verdict['krav3_stabil_fortegn'][0]}/8** | {', '.join(verdict['krav3_stabil_fortegn'][1])} |

Krav 2 var det vigtigste, og det er dét der falder tydeligst ud. Litteraturens
hovedfund om TSMOM er ikke at den slår buy-and-hold på afkast — det er at den
fanger det meste af afkastet med markant mindre drawdown. Det er præcis mønsteret:
`SPY` giver 10,53% mod buy-and-holds 10,81% (altså 97% af afkastet) med et maksimalt
tab på 33,7% mod 55,2%. `QQQ` giver mere afkast end buy-and-hold med halvt så dybt
et fald.

**Hvad det betyder for de sidste ugers arbejde:** apparatet kan genfinde en kendt
effekt. "Ikke påvist" på `trend_momentum` og regime-gaten var altså udsagn om de
strategier, ikke om målingen. Tallene derfra står ved magt.

---

## Definitioner låst FØR kørsel

Disse tal blev skrevet ind i `run_tsmom_test.py` før nogen resultater var set:

- **"Materielt lavere drawdown"** = mindst **20% relativt** lavere end buy-and-hold.
  Uden et tal kan kriteriet bøjes bagefter. −33,7% mod −55,2% er 39% relativt lavere
  og tæller; −50% mod −55% gør ikke.
- **Krav 3** læses som "mindst 3 af 4 delperioder med **positivt** afkast". Den rene
  ordlyd ("samme fortegn") ville også være opfyldt af fire negative delperioder,
  hvilket ikke kan være meningen med et succeskriterium. Begge tællinger står i
  tabellen nedenfor; bedømmelsen bruger den strenge.
- **Bedømmelsen sker på reglen** — 12 måneder, rebalancering den 1. Lookback 3/6/9 og
  rebalancering den 15. er robusthedstjek og indgår ikke. Der vælges ingen vinder.
- **Drawdown måles på daglig mark-to-market** for begge sider. Målte man strategiens
  drawdown ved exit og buy-and-holds dagligt, ville dyk inde i en position være
  usynlige, og krav 2 ville være rigget til at bestå.

---

## Konventioner — så tallene kan læses rigtigt om et halvt år

**Aktier = totalafkast. Futures og FX = kurs. Kontanter forrentes ikke.**

| Instrument | Kilde | Ejerskab | Afkastgrundlag |
|---|---|---|---|
{md_table(ejerskab).split(chr(10), 2)[2]}

### Finansiering modelleres ikke — her holder antagelsen ikke

Omkostningsmodellen opkræver spread, slippage og kurtage pr. rundtur. Den modellerer
hverken futures-roll eller swap. Ved fire døgns hold var det uden betydning; ved
gennemsnitligt 8-20 måneders hold er det ikke.

- **`ejet`** (BTC, ETH, SPY, QQQ): spot-aktivet ejes, ingen finansiering løber på.
  Tallene er komplette på dette punkt.
- **`derivat`** (GC, 6E, 6B og XAU-spot, der i praksis er et CFD/swap-produkt): roll
  eller swap ville løbe på over en holdeperiode på måneder. **Det gør det ikke i
  disse tal.** Det er en kendt mangel, ikke en antagelse om at den er nul.

### Er GC=F roll-justeret? Undersøgt, ikke antaget

Ja — eller i det mindste roll-neutral. En splejset front-month-serie ville hoppe op
ved hver rulning med carry-spreadet (guld er næsten altid i contango) og dermed
akkumulere et kunstigt merafkast mod spot.

Målt mod XAU-spot over 5.185 fælles dage (2004-06 → 2025-02):

| Mål | Resultat |
|---|---|
| Middel-difference GC−XAU på rulledage | +0,008% |
| Middel-difference GC−XAU på andre dage | −0,001% |
| Akkumuleret GC=F | +595,5% (CAGR 9,82%) |
| Akkumuleret XAU-spot | +590,9% (CAGR 9,78%) |
| **Årlig drift GC−XAU** | **+0,04 pct-point/år** |

En naivt splejset serie i contango ville have drevet flere procentpoint om året fra
spot. 0,04 er ikke til at skelne fra nul. **GC=F markeres derfor ikke som upålidelig
til lange hold** — og guld-resultatet bæres uafhængigt af begge serier, der giver
næsten samme svar (CAGR 10,59% mod 10,05%, maxDD −33,3% mod −32,8%). At to
uafhængigt hentede guldserier lander samme sted er selvstændig bekræftelse.

### Kontanter forrentes ikke

> Kontanter forrentes ikke i denne kørsel. Det underdriver TSMOM's afkast med
> omtrent renteniveauet ganget med andelen af tid uden for markedet. Testen er
> dermed konservativ over for TSMOM.

Konkret: `SPY` står ude 18,3% af tiden, `6E` 44,2%. Ved 2-5% p.a. svarer det til
0,4-0,9 pct-point om året for `SPY` og 0,9-2,2 for `6E`, som strategien ikke får
krediteret. Det er ikke modelleret, fordi det ville kræve en historisk renteserie —
en ekstra datakilde i en test hvis eneste formål er at validere apparatet. En
konservativ skævhed vi kender retningen på er bedre end en ekstra afhængighed.

### Buy-and-hold betaler også

Baselinen er ikke gratis: **én rundtur over hele perioden** (køb i starten, sælg i
slutningen), med samme omkostningsmodel som strategien. En gratis baseline ville
stille TSMOM gunstigere end virkeligheden.

### Auto_adjust indfører ikke lookahead — testet, ikke antaget

Justeringsfaktoren for en historisk dato afhænger af udbytter udbetalt EFTER den
dato. Argumentet er at faktorerne står i både tæller og nævner og går ud. Det er
efterprøvet frem for antaget:

1. Dagligt totalafkast rekonstrueret manuelt fra ujusteret kurs + udbytte, holdt op
   mod `auto_adjust`-serien over 8.455 dage: **median |difference| = 1,7 × 10⁻⁷**.
2. 21 stk. 12-måneders vinduer fra 2005 til 2025, justeret afkast mod
   kursafkast + udbytte inde i vinduet: **median residual +0,12%**, uden trend
   tilbage i tid. Lækkede fremtidige udbytter ind, ville residualet vokse med
   afstanden til i dag — ~30% for et 2005-vindue. Det gør det ikke. Residualet er
   geninvesteringseffekten inde i vinduet, ikke kontaminering.

---

## Lookahead — grænsen er en test, ikke en kommentar

Den nemme fejl er at regne 12-måneders-afkastet frem til eksekveringsbarens close i
stedet for forrige måneds close. Én bars lookahead, usynlig i resultatet, og hele
fase 1 ville være værdiløs.

Signalet er derfor en ren funktion af to indeks, og uligheden
`ref_idx < signal_idx < exec_idx` håndhæves af `tests/test_tsmom.py`:

- `test_signal_ignores_execution_bar_and_future` — ødelægger alle barer fra
  eksekveringsbaren og frem og kræver hvert signal uændret.
- `test_equity_before_a_date_is_unaffected_by_later_data` — kører hele strategien på
  en afkortet serie og kræver kurven identisk på det fælles stykke.

**Testen kan køre rødt.** Byttes `signal_idx` ud med `exec_idx` i `signal_for`,
fejler den — det er efterprøvet, ikke påstået.

---

## DEL 1 — datakvalitet. Reparerer ingenting

{md_table(qdf[["instrument", "barer", "fra", "til", "år", "flade_barer", "nul_volumen", "brugbart_span", "kasserede_år"]])}

**Kasseret, og hvorfor** (kriteriet er <90% årsdækning, samme tærskel som guldserien):

- **XAU 2025** — serien er mangelfuld fra marts 2025 (enkelte måneder med en
  brøkdel af de forventede barer). Det er samme hul som blev fundet ved
  DEL 3-guldtesten. Ikke repareret; året er udeladt af det brugbare span.
- **6B 2000-2001** — for få barer i kontraktens første år hos Yahoo.
- Intet andet år er kasseret. **Ingen bar er ændret, udfyldt eller interpoleret.**

**Forbehold der ikke er kasseret, men skal stå:**

- **`GC` har 1.042 flade barer (16%) og 419 barer med nul volumen.** Det er
  kendt fra daily-bias-valideringen og gjorde `GC=F` ubrugelig til range-logik.
  Her betyder det mindre: TSMOM læser kun `close` og `open`, aldrig `high`/`low`,
  og aldrig volumen. Forbeholdet er derfor ikke aktivt for denne kørsel — men det
  ville være det for enhver strategi der rører range eller volumen.
- **`6E` og `6B` har 780/800 barer med nul volumen.** Samme betragtning.
- Korrelationen mellem GC=F's og XAU-spots daglige afkast er 0,89 — ikke 0,99.
  Forskellen er lukketidspunkt (spot 24 timer mod COMEX-close), ikke instrument.

---

## Omsætning — et resultat, ikke en detalje

{md_table(turn)}

**`omk_%_af_brutto` er tallet der afgør om omkostningsskønnene overhovedet betyder
noget.** For de seks instrumenter hvor strategien tjener penge, er omkostningerne
**0,0-0,5% af bruttoafkastet**. Mine skøn for spread og slippage kunne være ti gange
for lave uden at ændre en konklusion.

De 7,5% og 10,9% på `6E` og `6B` er ikke et modsat resultat — de er en lille
omkostning delt med et bruttoafkast tæt på nul. FX-resultatet er ikke
omkostningsdrevet; det er fraværende.

**De to "n" er ikke det samme tal.** `positioner` er hvor mange gange der blev
handlet (4-23 over hele perioden). `tid_i_marked_%` er hvor stor en andel af tiden
der var eksponering (53-82%). En strategi med 11 positioner à 20 måneder og en med
60 à én måned kan have samme tid i markedet og vidt forskellige omkostninger.

### Glider månedsskiftet?

{md_table(slip)}

Månedsskiftet er defineret i kalendertid: første tilgængelige bar med dato ≥ den 1.,
handlet til dens **åbningskurs**. Alle tidsstempler er reduceret til ren dato i UTC
før reglen anvendes — krypto kommer med UTC-midnat, aktier med børsens lokale dato.

Medianglidningen er **0 dage** på alle otte. På krypto glider den aldrig (24/7).
På børshandlede instrumenter glider ~35% af rebalanceringerne 1-3 dage, hvilket er
weekender og helligdage og præcis det man skal forvente. Undtagelsen er `XAU` med
maksimalt 29 dage — det er den mangelfulde 2025-region, samme hul som ovenfor.

---

## Robusthed — formålet er ikke at finde den bedste

### Lookback 3/6/9/12 måneder, CAGR

```
{by_lb.to_string()}
```

### Samme, drawdown-reduktion mod buy-and-hold (andel)

```
{dd_lb.to_string()}
```

Effekten er **ikke** isoleret til 12 måneder. For `SPY` stiger CAGR monotont med
lookbacket (7,76 → 10,53) og drawdown-reduktionen ligger på 0,35-0,39 uanset
parameter. `QQQ`, `GC` og `XAU` er positive på alle fire. Drawdown-reduktionen er
positiv i 31 af 32 celler. Havde kun 12 virket, var 12 en tilfældighed — det er den
ikke.

FX er tæt på nul på alle fire lookbacks. Det er et konsistent fravær af effekt, ikke
en ustabil effekt.

### Rebalancering den 1. mod den 15. — turn-of-month-kontrollen

```
{by_day.to_string()}
```

Dette er kontrollen der betød mest. Virkede TSMOM kun når der rebalanceres den 1.,
havde vi fundet en turn-of-month-effekt — et velkendt og separat fænomen i aktier —
og det ville have set ud præcis som en bestået test.

Det gør den ikke. `SPY` giver 10,77% på den 15. mod 10,53% på den 1.; `QQQ` 8,79 mod
9,39; `GC` 9,26 mod 10,59. Forskellene går i begge retninger og er små i forhold til
niveauet. **Der vælges ingen vinder** — pointen er at resultatet ikke afhænger af
dagen.

### Delperioder

| Instrument | Afkast i 4 lige lange delperioder (%) | Positive | Samme fortegn |
|---|---|---|---|
{subs}

---

## Hvad denne kørsel IKKE viser

- **Otte instrumenter er ikke otte uafhængige væddemål.** `SPY`/`QQQ` er stort set
  samme marked, `GC`/`XAU` er samme metal, `6E`/`6B` er begge USD-kryds, `BTC`/`ETH`
  følges ad. Reelt er der ~4 uafhængige observationer, ikke 8. Korrelationsmatrix på
  daglige afkast:

```
{_correlation_block()}
```

  Kriteriet "4 af 8" er derfor svagere end det lyder. Det ændrer ikke konklusionen —
  effekten findes i alle fire uafhængige grupper på nær FX — men tærsklen bør ikke
  genbruges som om den var otte uafhængige test.

- **Det er ikke en handelsklar strategi, og skal ikke gøres til en.** Ingen
  positionsstørrelse, ingen porteføljekonstruktion, ingen finansiering, intet
  valutahensyn. Modulet ligger i `research/` netop for ikke at kunne samles op af
  registry'et.

- **FX-resultatet er ikke et modbevis.** TSMOM på enkelte valutakryds er svagere
  dokumenteret end på aktieindeks og råvarer, og 6E/6B er to observationer af det
  samme (USD).

- **Ni års krypto-historik er kort.** BTC og ETH består flere krav, men over ét
  marked og halvanden cyklus.

---

## Filer

- `research/daily_series.py` — de otte serier, kvalitetstjek, ejerskabsfelter
- `research/tsmom.py` — reglen. Én parameter
- `research/run_tsmom_test.py` — kørslen og det låste kriterium
- `tests/test_tsmom.py` — lookahead-grænsen og metrikkerne, 13 tests
- `research/output/apparatus_validation.csv` — alle 64 kørsler (8 × 4 lookbacks × 2 dage)
"""
