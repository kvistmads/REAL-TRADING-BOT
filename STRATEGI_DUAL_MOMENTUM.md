# Dual momentum — alert-sporet på aktiesparekonto

**Status:** påbegyndt 2026-10-03. Ingen kode skrevet. Ingen konto åbnet.
Overlevering til ny session og nyt repo.

Forgænger: `STRATEGI_TSMOM.md` — den indeholder backtesten, tallene og de
oprindelige forbehold. **Læs den først.** Dette dokument beskriver hvordan
strategien ændrer sig når den skal leve på en dansk aktiesparekonto.

---

## 1. Hvad sporet er

Et **alert-værktøj**, ikke en handelsbot. Den scanner, rangordner og sender besked
én gang om måneden. Mads placerer handlerne selv hos Nordnet.

Begrundelsen er ikke forsigtighed — det er frekvens. TSMOM havde 11 positioner på
32 år. Automatisk eksekvering løser et problem der ikke findes.

### Afgrænsning

- **Nyt repo**, adskilt fra både daytrading-botten og propfirm-sporet.
- Apparatet (`backtest/rnorm.py`, `backtest/paired.py`, `research/stats.py`,
  `backtest/costs.py`) **kopieres, deles ikke**.
- Dette spor rører ikke de andre projekter og omvendt.

---

## 2. Beslutninger truffet (2026-10-03)

| Spørgsmål | Valg |
|---|---|
| Konto | Aktiesparekonto hos Nordnet. 17% af afkastet, loft 174.200 kr. (2026) |
| Strategi | **Dual momentum** — absolut filter + relativ rangordning |
| Eksekvering | Manuel. Botten sender alert, Mads handler |
| Univers | 30-50 instrumenter, udvalgt blandt det ASK tillader |
| Antal positioner | 1-3 nu, vokser til 5-10 når kontoen når 50-100.000 kr. |
| Indbetaling | ~1.000 kr./måned, samlet i ét instrument pr. måned |
| Guld | Åbent — kan ikke ligge på ASK (se §5) |

---

## 3. Strategien

**Dual momentum.** Gary Antonacci, *Risk Premia Harvesting Through Dual Momentum*
(SSRN 2042750, 2012). Kombinationen af relativ styrke og absolut trend er
dokumenteret som sin egen strategi — det er ikke en hjemmelavet hybrid.

```
HVER MÅNED, for hver position der EJES:
  står den stadig over sin egen kurs for 12 måneder siden?
  nej  -> SÆLG. Pengene står kontant.

HVER MÅNED, for kontanter (inkl. månedens indbetaling):
  1. filtrér universet: behold kun dem der står over deres egen 12-mdr kurs
  2. rangordn de overlevende efter relativ styrke
  3. køb de bedste, op til N positioner
  passerer færre end N  -> køb færre. Resten bliver stående kontant.
```

### Hvorfor to lag

- **Lag 1 (absolut)** er krakbeskyttelsen. Det var hele den målte gevinst ved TSMOM:
  QQQ −41,0% maxDD mod buy-and-holds −81,2%. SPY −33,7% mod −55,2%. Afkastet var
  omtrent det samme; **drawdown blev halveret**, fordi strategien gik i kontanter.
- **Lag 2 (relativ)** er det der gør et stort univers nyttigt. Ren TSMOM på 50
  instrumenter giver 50 ja/nej-kontakter der tænder og slukker næsten samtidig —
  bredden køber meget lidt. Rangordning bruger bredden til at vælge.

### Hvad beskyttelsen IKKE dækker — vigtigt

Et månedligt tjek med 12-måneders lookback fanger **langvarige bjørnemarkeder**, ikke
**hurtige krak**.

Tallene ovenfor kom fra 2000-2002 og 2008-2009, hvor nedturen varede kvartaler og
signalet nåede at udløse. I februar-marts 2020 faldt markedet 34% på fem uger —
der nåede et månedligt filter ingenting.

Beskyttelsen er desuden **aktiv, ikke passiv**: kontantandelen opstår fordi
salgssignalet affyres på det man ejer, ikke fordi nogen beslutter at stå udenfor.
Lag 1 gælder hver måned på hele beholdningen, ikke kun ved køb.

---

## 4. De tre designvalg — uddybet

### 4.1 Lookback: 12-1 til rangordning, 12-0 til filteret

**Forslaget:** brug forskellige vinduer til de to lag.

- **Lag 1, absolut filter: hele 12 måneder (12-0).** Spørgsmålet er "trender dette
  aktiv overhovedet". Det er den regel der er testet i `STRATEGI_TSMOM.md`, og den
  skal ikke ændres uden grund.
- **Lag 2, relativ rangordning: 12 måneder minus den seneste (12-1).** Altså
  afkastet fra for 12 måneder siden til for 1 måned siden.

**Hvorfor springe den seneste måned over ved rangordning:** der er en veldokumenteret
kortsigtet reversal-effekt på én måneds horisont — aktiver der lige er steget kraftigt
har tendens til at falde tilbage den følgende måned. Ved *rangordning* betyder det at
den seneste måneds støj kan skubbe et aktiv til tops lige inden det vender. Ved et
*ja/nej-filter* betyder det mindre, fordi man kun spørger om fortegnet.

**Forbehold:** 12-1 er standard i den akademiske cross-sectional-litteratur
(Jegadeesh & Titman og efterfølgere). Vi har ikke testet den forskel selv. Det skal
præregistreres som et spørgsmål og måles, ikke antages.

**Hvad der skal testes:** 12-0 mod 12-1 til rangordning, med konfidensinterval og
mindste detekterbare forskel beregnet på forhånd. Krydser intervallet nul, vælges
den enkleste — altså 12-0 til begge lag.

---

### 4.2 N følger kontoen, ikke universet

**Forslaget:** antallet af positioner bestemmes af kurtagen, ikke af
diversifikationsteori.

Nordnets minimumskurtage er **25 kr. pr. handel**. Det giver en hård nedre grænse for
hvad en position må koste:

| positionsstørrelse | kurtage pr. side | brugbar? |
|---|---|---|
| 1.000 kr. | 2,50% | nej |
| 5.000 kr. | 0,50% | grænsen |
| 10.000 kr. | 0,25% | ja |
| 17.420 kr. | 0,14% | ved fuldt loft, 10 positioner |

Hertil kommer **valutatillæg på 0,25%** ved hver vekselning. En rotation (sælg + køb)
på 1.000 kr. koster derfor cirka **5,5% i alt** — mere end et helt års forventet
overafkast for én ombytning.

**Reglerne der følger:**

1. **Månedens indbetaling går samlet i ÉT instrument** — det højest rangerede der
   passerer lag 1. Ikke splittet ud på flere. Én handel, 25 kr.
2. **Antal positioner vokser med kontoen:** 1-3 ved start, 5-10 når kontoen når
   50-100.000 kr.
3. **Salgssignaler ignoreres under en minimumsstørrelse.** En position på 1.000 kr.
   er ikke værd at rotere; en på 10.000 kr. er. Tærsklen sættes ved cirka 5.000 kr.
4. **Universet må gerne være stort selvom N er lille.** At scanne er gratis.
   Scan bredt, hold få.

**Åbent:** punkt 3 skaber en asymmetri — et lille, faldende aktiv beholdes selvom
signalet siger sælg. Det skal måles hvad den asymmetri koster, ikke blot accepteres.

---

### 4.3 Rang-buffer mod churn

**Forslaget:** brug et bånd i stedet for en skarp grænse.

Ejer man top 3 og sælger i det øjeblik noget falder til plads 4, roteres der konstant
på støj — rangeringer skifter plads hver måned uden at noget reelt har ændret sig.

```
KØB    ind i top N
SÆLG   først når et aktiv falder ud af top 2N
```

Ejer du top 3, sælger du altså først når noget falder under plads 6.

**Hvorfor det virker:** turnover falder markant, mens porteføljen stadig følger de
store skift. Prisen er at man holder et middelmådigt aktiv lidt længere. Ved 25 kr.
minimumskurtage og positioner på 5-10.000 kr. er den pris lille i forhold til hvad
churn koster.

**Bemærk at lag 1 stadig gælder ubetinget.** Falder et aktiv under sin egen
12-måneders kurs, sælges det uanset rang. Bufferen gælder kun den relative
rangordning, aldrig det absolutte filter. Ellers ville krakbeskyttelsen blive udvandet.

**Hvad der skal testes:** buffer 2N mod ingen buffer, målt på både afkast og antal
handler. Omkostningen skal med i begge tal — det er hele pointen.

---

## 5. Egnethed — hvad der må ligge på kontoen

Dette er den del der skal automatiseres fuldstændigt, fordi fejlen er dyr.

### Reglen

Skattestyrelsen: man må have aktier noteret på et **reguleret marked eller MTF**, og
**investeringsselskaber hvor mindst 50% af aktiverne er aktier**, registreret hos
Skattestyrelsen.

Køber man noget uegnet, *anses det for aldrig at have været på kontoen*. Det fjernes
med tilbagevirkende kraft fra købsdatoen, og gevinst og tab skal selvangives udenfor.
Det er en aktiv fejl, ikke bare et manglende valg.

### 50%-spørgsmålet skal vi ikke selv besvare

Det er præcis det kriterium Skattestyrelsen bruger når de beslutter hvem der kommer
på listen. **Står ISIN'et på listen, har SKAT allerede afgjort at det er
aktiebaseret.** Vi efterregner ikke fondens beholdning.

### Datakilden

Skattestyrelsen udgiver en Excel-fil over aktiebaserede investeringsselskaber (ABIS).
Pr. 28. september 2026: `september-2026-abis-liste-2021-2026.xlsx`, **5.441 fonde**,
med mindst ISIN og navn pr. række.

> `https://skat.dk/erhverv/ekapital/vaerdipapirer/beviser-og-aktier-i-investeringsforeninger-og-selskaber-ifpa`

**Filen er ikke verificeret af os.** Den kunne ikke hentes fra Cowork-sessionen
(proxyen blokerer skat.dk). Første opgave i det nye repo er at hente den, bekræfte
kolonnerne og antallet, og skrive en parser.

### Tjekket

```
1. Er papiret en ENKELTAKTIE eller et INVESTERINGSSELSKAB?

2a. Enkeltaktie      -> noteret på reguleret marked/MTF?        -> OK
2b. Fond eller ETF   -> ISIN på ABIS-listen for INDEVÆRENDE år?
                     -> OG handlet på reguleret marked/MTF?     -> OK

3. Alt andet -> UDELUKKET
```

**Hvid liste, ikke sort liste.** Alt der ikke kan valideres positivt ryger ud.
Konservativt med vilje — alternativet er en skatteregning med tilbagevirkende kraft.

### Listen er årsopdelt — og det har en konsekvens

Filnavnet er `abis-liste-2021-2026`: den har kolonner pr. skatteår og opdateres hvert
efterår. **En fond kan falde af listen uden at man har gjort noget.** Et papir man
ejer lovligt i år kan være uegnet næste år.

Tjekket skal derfor køre mod indeværende års kolonne, og køres igen når den nye fil
udkommer i september.

**ÅBENT SPØRGSMÅL:** hvad sker der skattemæssigt med en beholdning der falder af
listen mens man ejer den? Det skal afklares hos Skattestyrelsen, ikke gættes.

### Det du ikke kan købe

- **Amerikanske ETF'er (SPY, QQQ, GLD) kan slet ikke handles.** Ikke en ASK-regel —
  PRIIPs. Siden 1. januar 2018 kræver EU et KID på lokalsproget, og amerikanske
  udstedere laver ikke KID'er. Brug UCITS-versioner: CSPX (S&P 500), EQQQ/CNDX
  (Nasdaq-100).
- **Guld kan ikke ligge på ASK.** En guld-ETC ejer metal, ikke aktier — 0%
  aktieandel. (Dette er vores ræsonnement ud fra 50%-kravet, ikke et citat.)
- **Krypto kan ikke ligge på ASK.**

Guld var den mest effektive komponent i backtesten: **23,9% af afkastet for 15,0% af
risikoen**, fordi den korrelerede kun 0,08 med aktier. At miste den er et reelt tab af
diversifikation. Tre muligheder, ingen valgt: drop guld, hold det i et separat depot
(kapitalindkomst, andet skatteregime), eller brug guldmine-ETF'er (de **er** aktier og
kan ligge på ASK hvis de står på listen — men de korrelerer med aktiemarkedet og giver
derfor ikke guldets 0,08).

### Vælg akkumulerende frem for udbyttebetalende

Nordnet trækker 15% i udbytteskat på udenlandske udbytter fra lande med
dobbeltbeskatningsaftale, og skriver selv at de *"ikke kan hjælpe med rettelser eller
tilbagebetaling, hvis du har betalt for meget i udbytteskat."*

Akkumulerende ETF'er udlodder ikke, så der er intet udbytte at trække skat af hos dig.
Lagerprincippet beskatter alligevel kursstigningen, så du taber intet ved valget.

---

## 6. Skatten

| | |
|---|---|
| Sats | 17% af afkastet |
| Loft | 174.200 kr. (2026) |
| Princip | **Lagerprincippet** — skat af urealiserede gevinster hvert år |
| Tab | Kan kun modregnes i fremtidige gevinster på kontoen |

Lagerprincippet har en praktisk konsekvens: en position holdt i to år udløser skat af
papirgevinst undervejs. Der skal være kontanter til regningen uden at sælge.

---

## 7. Metoderegler — arvet

1. **Præregistrér falsifikationskriteriet før hver kørsel.**
2. **Konfidensinterval på alt.** Krydser det nul, er resultatet uafgjort — ikke
   svagt positivt.
3. **Beregn mindste detekterbare forskel FØR testen.**
4. **Alle tal både brutto og netto** for omkostninger. Her betyder det: kurtage på
   25 kr. minimum, valutatillæg 0,25%, og 17% lagerbeskatning.
5. **Enheden står i kolonnenavnet**, ikke i en fodnote.
6. **Gates hører til i live, aldrig i backtesten.**
7. **En sats tæller først når den er verificeret for den kanal man faktisk bruger.**
8. **Stop efter hver kørsel.** Ingen ændringer, ingen forslag — resultaterne læses
   sammen først.
9. **Mads' egne idéer skal ikke valideres videnskabeligt** — vurder i stedet om de
   kan automatiseres, om de passer ind, og hvor omfattende ændringen er.
10. **Alt andet sammenholdes med nyeste litteratur.**

---

## 8. Åbne spørgsmål, i rækkefølge

**Før kode:**

1. **Hent og verificér ABIS-filen.** Kolonner, antal rækker, årsopdeling. Skriv en
   parser. Alt andet hviler på den.
2. **Hvad sker der med en beholdning der falder af listen?** Spørg Skattestyrelsen.
3. **Afgør guld.** Drop, separat depot, eller miner.
4. **Vælg universet.** 30-50 instrumenter blandt det egnede. Regioner og sektorer
   frem for flere brede verdensindeks — de er den samme eksponering igen.
5. **Historik til backtest.** `londonstrategicedge.com` har 14 opløsninger og bulk
   Parquet, gratis nøgle, licens der tillader egen research og trading. Dybden for
   europæiske UCITS-ETF'er er ikke oplyst og skal testes. Alternativt kan backtesten
   køres på indeksene frem for ETF'erne, med omkostningerne lagt på.

**Før alert sættes i drift:**

6. Test 12-0 mod 12-1 til rangordning (§4.1).
7. Test rang-buffer 2N mod ingen buffer (§4.3).
8. Mål hvad minimumsstørrelse-asymmetrien koster (§4.2, punkt 3).
9. Hvordan leveres alerten, og hvad gør den når der ikke er noget at melde?
   Den skal være **stille** når intet skal skifte.

---

## 9. Hvad der IKKE er en del af sporet

- **Automatisk eksekvering.** Handler placeres manuelt.
- **Daytrading og propfirm.** Egne repos, egne dokumenter.
- **Krypto, FX og futures.** Kan ikke ligge på kontoen. FX var i øvrigt allerede
  værdiløst på egne meritter: 6E og 6B gav tilsammen **−2,1% af afkastet for 20,1%
  af risikoen**.

---

## 10. Arvede forbehold fra TSMOM-backtesten

Disse gælder stadig og skal ikke glemmes fordi strategien har fået et nyt lag:

- **n er lille.** SPY: 11 positioner på 32 år. Hele resultatet hviler på elleve
  beslutninger. Vi tror på det fordi det matcher en effekt dokumenteret på 58
  instrumenter over et århundrede — ikke fordi vores elleve beviser noget.
- **Ventetiden er lang.** SPY: 4,6 år uden ny egenkapitaltop. QQQ: 10,8 år.
  Porteføljen: 3,1 år. Det er det man skal kunne holde ud uden at slukke.
- **Porteføljens maxDD på −19,0% indtraf i 1998**, da porteføljen bestod af SPY
  alene. Fra 2003 er værste fald −11,7%.
- **Krypto-tallene var aldrig et strategiresultat** — BTC n=4, ETH n=7.
- **Dual momentum er ikke testet i vores apparat.** Hverken lagene hver for sig i
  denne form eller kombinationen. Den er dokumenteret i litteraturen; den er ikke
  efterprøvet af os.

---

## Kilder

- Antonacci, *Risk Premia Harvesting Through Dual Momentum*, SSRN 2042750 (2012)
- Moskowitz, Ooi & Pedersen (2012) — grundlaget under `STRATEGI_TSMOM.md`
- skat.dk: aktiesparekonto, og listen over aktiebaserede investeringsselskaber
- nordnet.dk: prisliste, aktiesparekonto, FAQ om udbytteskat
- Alle hentet 2026-10-03
