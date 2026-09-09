# Propfirm-sporet

**Status:** påbegyndt 2026-09-09. Ingen kode skrevet. Ingen konto åbnet.
Dette dokument er overlevering til en ny session og et nyt repo — ikke en plan der er
godkendt til at blive bygget.

Søsterdokumenter: `STRATEGI_TSMOM.md`, `STRATEGI_DAYTRADING.md`.

---

## 1. Hvad sporet er

Et separat handelssystem der skal **bestå en propfirm-evaluering og derefter holde den
funded konto i live**. Kapitalen er propfirmaets, ikke Mads'.

To strategier, ikke én:

- **Eval-strategien** skal nå profitmålet inden for reglerne. Den må være aggressiv,
  fordi konsekvensen af at fejle er et nyt evalueringsgebyr — ikke tab af egne penge.
- **Konto-strategien** skal holde kontoen i live bagefter. Den må være defensiv,
  fordi konsekvensen af at fejle er at hele arbejdet er væk.

De to har modsatrettede tabsfunktioner. Det er grunden til at de er to strategier og
ikke én med et parameter skruet på.

### Afgrænsning

- **Nyt repo.** Ikke en ny main i det eksisterende. Begrundelsen er Mads' egen:
  "knald eller fald, en forkert fejl på det forkerte tidspunkt, konto død."
  `core/engine.py` i det nuværende repo har én `ExchangeClient`, én `PositionTracker`
  og intet kontobegreb — den kan ikke bære to konti uden ombygning.
- **Apparatet kopieres, deles ikke.** `backtest/rnorm.py`, `backtest/paired.py`,
  `research/stats.py` og `backtest/costs.py` er valideret arbejde og skal med. De må
  ikke importeres på tværs af repos, så en ændring i det ene kan bryde det andet.
- **De 5-10K er ikke en del af dette spor.** De hører til det eksisterende
  krypto-paperprojekt. Propfirm-strategierne handler propfirm-kapital.

---

## 2. Beslutninger truffet (2026-09-09)

| Spørgsmål | Valg |
|---|---|
| Kapital | Udelukkende propfirm-kapital |
| Firma | Topstep er førstevalg, ikke låst |
| Mål | Bestå eval, behold funded konto |
| Autonomi | Backtest og paper-forward **fuldauto**; funded live **semi** (bot foreslår, Mads bekræfter), udvides til fuldt autonom bagefter. Combine-fasen ikke afgjort |
| Session | US RTH som udgangspunkt; ønske om blanding med døgndrift skal måles først |
| Instrument | MNQ (mikro Nasdaq) som primært |

Semi-først er valgt bevidst. Fuldt autonomt er tilladt hos Topstep (se §3), så det er
ikke en regelbegrænsning — det er en tillidsbegrænsning. Botten skal have vist at den
foreslår noget fornuftigt, før den får lov at trykke selv.

---

## 3. Topstep's regler — primærkilder

Alt herunder er fra Topstep's eget help center, hentet 2026-09-09. **Regler ændrer sig;
slå dem op igen før noget bygges.**

### Automatisering — tilladt

> "Custom automated strategies and bots are allowed via the TopstepX / ProjectX API,
> subject to standard platform rules and our prohibition on high-frequency trading (HFT)."

API-adgang koster **$29/md, $14,50 med koden `topstep`**. REST + WebSocket.
Ingen sandbox — "API orders are final". Topstep yder ingen support på implementeringen
og laver ingen undtagelser for fejlagtige handler eller nedbrud.

### Den bindende begrænsning — hvor koden kører

> "All trading activity must originate from your personal device. The use of VPS, VPNs,
> and remote servers is prohibited by Topstep's Terms of Use."

**Det udelukker en cloud-server.** Botten skal køre på Mads' egen maskine.
Det udelukker derimod ikke at han er på arbejde imens — reglen handler om *hvor koden
kører*, ikke om hvorvidt nogen kigger på.

Konsekvens: Macens oppetid bliver en del af strategien. Samme problem som
orderbook-optageren, hvor processen døde ved genstart fordi launchd ikke var installeret.
Det skal løses ordentligt før første live-handel, ikke bagefter.

### Maximum Loss Limit (MLL)

> "The MLL is a trailing limit. It rises as your end-of-day balance grows, but never
> moves down." — og den låser permanent når den når startsaldoen.

| Kontostørrelse | MLL |
|---|---|
| $50K | $2.000 |
| $100K | $3.000 |
| $150K | $4.500 |

**Både realiseret og urealiseret P&L tæller, i realtid gennem sessionen.** Et åbent tab
kan altså lukke kontoen uden at handlen nogensinde blev lukket.

Den vigtigste mekanik at forstå: MLL trailer **op** på dagsslutsaldoen og aldrig ned.
En god dag hæver permanent dit gulv. Man har derfor aldrig mere end $2.000 luft fra sit
eget high-water mark, før den låser ved startsaldoen. Det er en hård, veldefineret
grænse — og præcis den slags en bot kan overholde bedre end et menneske.

### Øvrige parametre

- **Daily Loss Limit** (funded, $50K): $2.000. Justeres automatisk ned når saldoen
  falder under $10K/$5K over startsaldoen; revideres om fredagen.
- **Max position, $50K:** 5 fuldstore kontrakter eller 50 mikroer.
  Falder saldoen til $10K/$5K: 5 hhv. 3 kontrakter.
- **Konsistens:** bedste enkeltdag skal holdes under 50% af profitmålet.
- **Minimum handelsdage:** to.

**Ikke verificeret endnu:** profitmålets beløb pr. kontostørrelse, abonnementsprisen på
selve Combine, om markedsdata følger med API-adgangen, og om reglerne adskiller sig
mellem Combine og Live Funded ud over de tal der står ovenfor.

---

## 4. Omkostningsgrundlaget

Fra fase 3b (`research/output/venue_costs.md` i det gamle repo). Alle tal ved 15m og
2:1 gevinst/tab.

| kontrakt | omk_R | be_WR | ATR 15m |
|---|---|---|---|
| **MNQ** | **0,023** | **34,1%** | 0,168% |
| MGC | 0,052 | 35,1% | 0,194% |
| MES | 0,098 | 36,6% | 0,090% |
| Binance futures krypto | 0,320 | 44,0% | 0,312% |
| MEXC futures via API | 0,512 | 50,4% | 0,312% |

**MNQ er 14× billigere i R end den billigste kryptovej.** Oversat: skiftet fra krypto til
mikro-Nasdaq forærer os ~10 procentpoint win rate før strategien har gjort noget.

Hvorfor NQ vinder: alle seks kontrakter koster 1,9-4,5 ticks i rundtur. Forskellen er
hvad én tick er værd i bp. Nasdaq har samme ticksize som S&P på et 3,8× større
indekstal (0,085 mod 0,325 bp/tick). Det er kontraktgeometri og flytter sig ikke.

**Omkostningsspørgsmålet er lukket.** Bedste realistiske tilfælde (limit-entry,
1-tick-marked) er 0,018 R mod 0,023 — be_WR falder fra 34,1% til 33,9%. Der er intet at
hente ved at optimere videre. Det der mangler er en edge.

### Hvad tallene IKKE indeholder

- **Slippage på stops.** Et stop er en markedsordre; i en hurtig bevægelse fylder den
  dårligere end én tick. Ikke målt.
- **Spread uden for US RTH.** 1,5 tick er et RTH-skøn. Om natten er NQ tyndere.
  Ønsket om døgndrift rammer præcis her.
- **Faste omkostninger.** API $14,50/md, Combine-abonnement, evt. markedsdata.
  På en evalueringskonto er de reelle og løbende.

---

## 5. Sporets største uløste problem

**Én MNQ med et 1-ATR-stop på 15m risikerer ~$99. Hele MLL på en $50K-konto er $2.000.**

Det er **5% af hele risikobudgettet pr. handel**. Tyve tabende handler i træk fra start,
og kontoen er død. Almindelig risikostyring ville sige 1% af budgettet — $20 — hvilket
svarer til et stop på ~10 NQ-point, altså en femtedel af ATR på 15m.

Der er ikke en åbenlyst rigtig løsning. Mulighederne udelukker delvist hinanden:

1. **Lavere timeframe.** 5m har mindre ATR, altså mindre absolut risiko pr. handel — men
   omkostningen er konstant pr. handel, så omk_R stiger. Skal beregnes, ikke gættes.
2. **Sub-ATR stop.** Tættere stop end volatiliteten tilsiger giver flere stop-outs
   på støj. Det var præcis symptomet i det nuværende paperprojekt.
3. **Acceptér 5%** og byg eval-strategien om at 20 tab er nok. Med 2:1 og en win rate
   over ~34% er forventningen positiv, men *sekvensen* afgør, og MLL'en trailer kun opad.
4. **Større konto.** $150K har $4.500 MLL, altså 2,2% pr. MNQ. Dyrere evaluering.

**Dette skal afgøres før der skrives kode**, og det skal afgøres med tal, ikke med en
mavefornemmelse. Det er sporets ækvivalent til go/no-go-spørgsmålet på guld.

---

## 6. Signal, mobil og infrastruktur

Besluttet 2026-09-09. Semi-autonom drift er ikke kun et tillidsvalg — den er også den
sikre vej i forhold til Topstep's personal-device-regel, fordi **ordren afsendes fra
Macen** uanset hvad. Telefonen sender kun et "ja". Det er ikke anderledes end at ringe
til en mægler, og det fjerner behovet for at få reglen afklaret hos Topstep.

### Arkitektur — pilen vender udad

Macen skal ikke kunne nås udefra. Den laver kun udgående forbindelser:

    Mac finder setup
      -> sender signal ud via Telegram-bot
      -> Mads trykker ja på telefonen
      -> Macen poller efter svaret og lægger ordren

Ingen åbne porte, ingen tunnel, ingen router-opsætning, ingen angrebsflade mod den
maskine der handler. **Telegram er valgt** fordi ét bibliotek klarer begge veje, det
virker på låseskærmen, og latenstiden er sekunder. Kræver en fallback for det tilfælde
at Telegram er nede.

### Bekræftelsesgaten gælder KUN live med rigtige penge

Tilføjet 2026-09-09. **Backtest og paper-forward-test kører fuldautomatisk.** Ingen
bekræftelse, intet ja eller nej — der skal strategien vise hvad den kan, ubeskåret.

Det er ikke en detalje, det er det der redder målingen. En testfase hvor Mads skal
bekræfte, måler hans vagtplan lige så meget som strategien. Fuldautomatisk paper-drift
er derfor **referencen** som alt andet holdes op imod.

Konsekvens, og den er stærkere end shadow-loggen alene: **paper-instansen bliver ved med
at køre fuldautomatisk parallelt med den semi-automatiske live-instans.** Forskellen
mellem de to kurver *er* prisen for bekræftelsesgaten — direkte observeret frem for
estimeret. Det er den samme kode med et flag, så det koster stort set ingenting.

    backtest        fuldauto    strategiens rå egenskaber
    paper-forward   fuldauto    referencen, kører permanent
    Combine         ÅBENT       ingen kapital på spil, kun evalueringsgebyret
    funded live     semi        bekræftelse via Telegram, jf. nedenfor

Combine-fasen er ikke afgjort. Der er ingen kapital på spil ud over gebyret, så
argumentet for fuldautomatik gælder næsten lige så stærkt som i paper — men det er også
sidste chance for at opdage at botten gør noget dumt, før den rører rigtige penge.

### Beslutninger for live-fasen

| | |
|---|---|
| Kanal | Telegram-bot |
| Timeout | **Signalet udløber.** Botten gør intet hvis der ikke svares i tide |
| Svarvindue | 5 minutter (Mads' egen vurdering af hvad han kan holde på vagt) |
| Uden at spørge: lukke position | **Tilladt** |
| Uden at spørge: flytte stop/TP | **Tilladt** |
| Uden at spørge: åbne position | **Ikke tilladt** |

Tilladelserne er asymmetriske med vilje. At lukke en position kan aldrig skabe ny
eksponering, og en bot der skal bede om lov til at redde kontoen mens telefonen ligger i
et skab er farligere end en der bare gør det.

### Den skjulte omkostning ved semi-auto — skal måles, ikke antages

Et 15m-setup er gyldigt i minutter. Missede signaler er derfor uundgåelige, og de gør
**live-resultaterne usammenlignelige med backtesten**: filteret "nåede Mads at svare"
findes ikke i backtesten. En dårlig måned kunne skyldes strategien eller vagtplanen, og
vi ville ikke kunne se forskel.

**Krav:** botten logger både hvad den ville have gjort og hvad der faktisk skete —
samme mønster som `reflection.news.shadow_trader` i det eksisterende repo. Sammen med
den permanent kørende fuldautomatiske paper-instans betyder det at prisen for
bekræftelsesgaten er målt to gange og fra to vinkler. Det bygges ind fra dag ét.

### Infrastruktur

Mønsteret findes færdigt i det eksisterende repo (`com.madskvist.tradingbot.plist`):
`RunAtLoad` + `KeepAlive` + `ThrottleInterval`. Prop-botten får en kopi hvor kun
`Label`, stien og logfilerne ændres. Macen kører konstant og starter automatisk igen
efter nedlukning eller strømafbrydelse.

**Men `KeepAlive` er farligere på en prop-konto end på krypto i dry_run.** Dør botten
med en åben position og bliver genstartet, må den ikke tro at den står flad. MLL'en
tæller urealiseret tab i realtid, så en position botten har glemt kan lukke kontoen.

**Krav: tilstandsgenopretning ved opstart.** Botten spørger Topstep "hvad har jeg
åbent?" før den gør noget som helst andet. Ikke en finesse — en forudsætning.

## 7. Metoderegler — arvet fra det eksisterende projekt

Disse er ikke til forhandling. De er grunden til at fire hypoteser blev afvist i stedet
for at blive rationaliseret.

1. **Præregistrér kriteriet før kørslen.** Hvad ville falsificere hypotesen, og ved
   hvilken tærskel.
2. **Konfidensinterval på alt.** Krydser det nul, er resultatet uafgjort — ikke svagt
   positivt.
3. **Mindste detekterbare forskel beregnes før testen.** Måler man 0,19 R med en
   detektionsgrænse på 0,36 R, har man ikke målt noget.
4. **Gates hører til i live, aldrig i backtesten.** Backtesten skal være maksimalt
   gennemsigtig.
5. **Alle tal både brutto og netto** for omkostninger.
6. **Enheden står i kolonnenavnet.** Ikke i en fodnote. `omk_R_maker_100pct_fill`,
   ikke `omk_R_maker`.
7. **En gebyrsats tæller først når den er verificeret for den kanal botten faktisk
   bruger.** MEXC-lektionen: 0% maker gjaldt web og app, API-ordrer havde en separat
   sats der gik forud — og var hævet to gange på tre måneder. Annoncerede satser er
   ikke data.
8. **Stop efter hver kørsel.** Ingen konfigurationsændringer, ingen strategiforslag,
   heller ikke gode. Resultaterne læses sammen først.
9. **Egne idéer skal ikke valideres videnskabeligt** — de vurderes på: kan den
   automatiseres, passer den til botten, hvor omfattende er ændringen.
10. **Alt andet sammenlignes mod nyeste litteratur.**

---

## 8. Åbne spørgsmål, i den rækkefølge de skal besvares

Rækkefølgen er ikke bureaukrati. MLL-budgettet bestemmer hvor stor risiko én handel må
have, hvilket bestemmer stopbredden, hvilket bestemmer hvilken timeframe der overhovedet
er mulig. Findes der en flot 15m-strategi som bagefter viser sig ikke at kunne sizes
inden for $2.000, er arbejdet spildt. Spørgsmål 1 **indsnævrer søgefeltet** før
strategisøgningen begynder — det er en halv times regnestykke, ikke et projekt.

**Før kode:**

1. Positionsstørrelse mod MLL (§5). Hvilken af de fire veje, og med hvilke tal bag.
2. Topstep's profitmål og Combine-pris pr. kontostørrelse. Ikke verificeret.
3. Følger markedsdata med API-adgangen, eller er det et separat abonnement?
4. ~~Tæller en ordre afsendt fra telefonen som "your personal device"?~~ **Bortfaldet.**
   Semi-designet i §6 sender ordren fra Macen; telefonen sender kun et ja. Spørgsmålet
   vender først tilbage hvis der senere bygges fuld autonomi med afsendelse fra andet
   end Macen.
5. Historik til backtest. `londonstrategicedge.com` har 14 opløsninger inkl. 15m,
   bulk Parquet, gratis nøgle, og en licens der tillader egen research og trading
   kommercielt (ikke videresalg). **Futures-dybden er ikke oplyst** — de nævner aktier
   2003, FX 2009, krypto 2017. Test: hent NQ 15m, se hvor langt tilbage det går, og hold
   en dag op mod Yahoo. 20 minutters arbejde.
6. Reelt spread på MNQ, målt frem for gættet — og målt pr. tidsblok, så ønsket om
   døgndrift kan vurderes i stedet for antages.

**Før live:**

7. **Tilstandsgenopretning ved opstart** (§6). Botten skal spørge Topstep hvad der er
   åbent, før den gør noget andet. Uden den er `KeepAlive` en risiko frem for en
   sikkerhed.
8. Netværkstab midt i en åben position. Hvad gør botten, og hvad gør den når
   forbindelsen kommer tilbage?
9. Fallback når Telegram er nede.
10. Slippage på stops, målt.
11. Hvad gør systemet når MLL'en nærmer sig? Det skal være en eksplicit regel i koden,
    ikke en konsekvens af at strategien tilfældigvis holder op med at handle.

---

## 9. Hvad der IKKE er en del af dette spor

- **TSMOM.** Ude af projektet. Dokumenteret i `STRATEGI_TSMOM.md` som reference.
- **Krypto.** Omkostningen på 15m gør sporet dødt for daytrading; det eksisterende
  paperprojekt kører videre uafhængigt.
- **De 5-10K egen kapital.** Hører til det eksisterende projekt.
- **Aktie-execution.** Udskudt.

---

## 10. Åbne observationer fra det eksisterende projekt

Ikke undersøgt, men noteret så de ikke fordamper:

- **Break-even-stop og trailing stop fungerer muligvis ikke som håbet.** Mads'
  observation fra live paper-handler. Ikke målt. Kandidat til en falsifikationstest
  med samme apparat som de fire foregående.
- **Prisen rammer ofte lige akkurat ikke TP**, hvorefter den går mod SL eller lukkes af
  tidsstop. Det var begrundelsen for at sætte `tp_rr_ratio` til 1,5 i det nuværende
  projekt — et bevidst valg truffet efter at konsekvensen (break-even WR stiger til
  40,0%) var regnet igennem.

Bemærk at propfirm-sporets tabeller regner med **2:1**, ikke 1,5:1. Ved 2:1 er bunden
33,33%; ved 1,5:1 er den 40,0%. De to må ikke krydslæses.

---

## Kilder

- help.topstep.com — TopstepX API Access, Trading Combine Parameters,
  Live Funded Account Parameters, What is the Maximum Loss Limit (alle 2026-09-09)
- `research/output/venue_costs.md` — fase 3b, dette repo
- github.com/londonstrategicedge/lse-data — datakilde, ikke verificeret
