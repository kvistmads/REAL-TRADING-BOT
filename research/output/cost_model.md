# Omkostningsmodel — kilder og antagelser

**Skrevet:** 2026-09-02. Konfiguration: `config.yaml` → `backtest.costs`.
Implementering: `backtest/costs.py`. Tests: `tests/test_costs.py`.

Indtil nu har hvert tal i projektets historie været **brutto**. `trend_momentum` PF 0,98,
`volatility_breakout` PF 1,16 og hele flip-exit-sammenligningen er beregnet uden at betale
for at komme ind og ud af markedet. Dette dokument redegør for hvor hvert tal i modellen
kommer fra — og lige så vigtigt, hvilke der **ikke** er slået op.

---

## Hvorfor futures ikke er i basispunkter

Krypto-gebyrer er proportionale: 0,10% af notional, uanset prisniveau. Futures-omkostninger
er det ikke — et tick på COMEX GC er 0,10 USD, hvad enten guld står i 2.250 eller 4.500.

Omregner man et tick til basispunkter og fryser tallet i en config, indbygger man et
prisniveau i modellen. Over de 2 år testen dækker er den fejl på størrelse med selve
omkostningen. Derfor gemmes futures-omkostninger i kontraktens egne enheder og omregnes til
en brøkdel af prisen ved **hver** handel:

| mode | betydning | bruges af |
|---|---|---|
| `proportional` | omkostningen ER en brøkdel af prisen | crypto |
| `contract` | omkostningen er i ticks/USD, omregnes pr. handel | forex, gold, index |

---

## Slået op — børsdokumentation og offentliggjorte gebyrsatser

### Krypto (Binance spot)

| Tal | Værdi | Kilde |
|---|---|---|
| Taker-gebyr, VIP 0 | **0,10% pr. side** | Binances gebyrskema, VIP 0-niveauet |
| Rundtur | 0,20% | 2 × 0,10% |

Modellen bruger **taker**, ikke maker. Strategierne handler på bar-close-signaler, altså
markedsordrer der krydser spreadet — maker-raten ville forudsætte limitordrer der ligger og
venter, hvilket ikke er det botten gør. BNB-rabatten på 25% (→ 0,075%) er **ikke** brugt:
den forudsætter en BNB-beholdning botten ikke har.

### CME-kontrakter

Forex og guld hentes som CME-futures (`6E=F`, `6B=F`, `GC=F`) — se `data/fetcher.py` for
hvorfor det er futures og ikke spot. Omkostningerne er derfor futures-omkostninger.

| Kontrakt | Contract unit | Tick | Tick-værdi | Bruges til |
|---|---|---|---|---|
| COMEX GC (guld) | 100 troy oz | 0,10 USD | 10,00 USD | `XAU/USD` |
| CME 6E (Euro FX) | 125.000 EUR | 0,00005 | 6,25 USD | `EUR/USD` |
| CME 6B (British Pound) | 62.500 GBP | 0,0001 | 6,25 USD | `GBP/USD` |
| CME ES (E-mini S&P) | multiplier 50 | 0,25 | 12,50 USD | (index — ikke handlet) |

**6E og 6B er ikke ens.** 6E har halvt tick og dobbelt notional. Ét fælles forex-tal ville
overvurdere EUR/USD's omkostning med ~70%, så `EUR/USD` har en symbol-override i configen;
asset-class-defaulten er 6B (den dyrere af de to i brøkdele af prisen).

### Kurtage

| Tal | Værdi | Kilde |
|---|---|---|
| CME exchange fee, ES, ikke-medlem | ~1,18 USD pr. rundtur | CME's gebyrskema |
| NFA-afgift (pr. 1. juli 2026) | 0,01 USD pr. side = 0,02 pr. rundtur | NFA assessment fee |
| Spændet mellem billigste og dyreste retail-broker | ~4,00 USD pr. rundtur | brokersammenligninger |

Modellen bruger **4,00 USD pr. rundtur pr. kontrakt** — den dyre ende af retail-spektret,
inklusive broker-kommission, exchange-, clearing- og NFA-gebyrer. Et lavere tal ville
smigre resultaterne.

---

## IKKE slået op — skøn, markeret som skøn

Disse to tal er **modelantagelser**. Der findes ingen offentliggjort statistik at slå op,
og et tal der ser præcist ud ville være værre end et ærligt skøn.

| Antagelse | Værdi | Begrundelse |
|---|---|---|
| Bid-ask spread | **1 tick** | Front-month CME-kontrakter handler typisk i ét tick; det udvides ved nyheder (NFP, rentemøder). ES er dokumenteret som "ofte ét tick" — for 6E/6B/GC er ét tick en rimelig, men ikke citerbar, front-month-antagelse. |
| Slippage | **0,5 tick i snit, std 0,5 tick** | Intet offentligt datasæt. Et halvt tick ud over spreadet er et konservativt skøn for markedsordrer i likvide kontrakter. |
| Krypto-spread | **1 bp** | Majors på Binance spot handler tættere end dette i rolige perioder og bredere i stress. Krypto domineres alligevel af kurtagen (20 bp), så spread-antagelsen flytter lidt. |

**Slippage kan aldrig være favorabel** i modellen: trækket fra N(0,5; 0,5) ticks afkortes
ved 0. En markedsordre der krydser spreadet får ikke en bedre pris end den stillede — den
favorable hale ville være en fiktion der pyntede på resultatet.

**Slippage er seedet.** Generatoren nøgles på `(slippage_seed, strategi, symbol)`, så det
samme symbol giver de samme træk uanset om det køres alene eller midt i en suite. Uden det
ville rækkefølgen af symboler ændre resultatet, og to kørsler af "samme" backtest kunne
ikke sammenlignes. Seedet bruger `zlib.crc32` og ikke `hash()`, fordi Pythons streng-hash
er randomiseret pr. proces.

---

## Hvad det koster i praksis

Rundtur pr. handel, ved realistiske prisniveauer:

| Symbol | Pris | Spread | Slippage | Kurtage | **I alt** |
|---|---|---|---|---|---|
| BTC/USDT | 110.000 | 1,0 bp | 4,0 bp | 20,0 bp | **25,0 bp** |
| ETH/USDT | 4.000 | 1,0 bp | 4,0 bp | 20,0 bp | **25,0 bp** |
| SOL/USDT | 200 | 1,0 bp | 4,0 bp | 20,0 bp | **25,0 bp** |
| EUR/USD | 1,10 | 0,46 bp | 0,46 bp | 0,29 bp | **1,20 bp** |
| GBP/USD | 1,30 | 0,77 bp | 0,77 bp | 0,49 bp | **2,03 bp** |
| XAU/USD | 4.505 | 0,22 bp | 0,22 bp | 0,09 bp | **0,53 bp** |

**Krypto koster 12-47× mere end CME-kontrakterne** i brøkdele af prisen, og forskellen er
næsten udelukkende Binances 20 bp rundtur mod futures-kurtage spredt over en notional på
flere hundrede tusind dollars. Med en gennemsnitlig handel omkring ±0,2% æder 25 bp godt en
ottendedel af bevægelsen på krypto, mens 0,5 bp på guld er støj.

Det betyder at brutto-tal og netto-tal afviger **meget** forskelligt pr. symbol — og at en
strategi der ser ens ud på tværs af symboler brutto, ikke gør det netto.

---

## Afgrænsning

- Modellen læses **kun** af backtesten. Live-handelsadfærd er upåvirket.
- `BacktestResult`-tabellen (research-lagets baseline) gemmer fortsat **brutto**, så den
  matcher live-paper, der heller ikke betaler omkostninger. Skal den skifte til netto,
  kræver det en bevidst beslutning og en migration.
- Paper-tærsklerne i `backtest/runner.THRESHOLDS` bedømmes nu på **netto** (`pass`), med
  brutto-vurderingen bevaret som `pass_gross`. En strategi der kun består brutto består
  ikke i virkeligheden.
- Finansieringsomkostninger (funding rates på perpetuals, roll-omkostninger på futures) er
  **ikke** modelleret. Botten handler ikke perpetuals, og roll-effekten på et 4h-signal med
  maks 4 døgns holdetid er lille — men den er ikke nul, og den er ikke med.

---

## Kilder

- [Binance Maker Taker Fee 2026: Spot 0.1%](https://binancemakertakerfee.org/)
- [Binance Fees Breakdown (BitDegree)](https://www.bitdegree.org/crypto/tutorials/binance-fees)
- [Gold Futures Contract Specs — CME Group](https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html)
- [Euro FX Futures EUR/USD Contract Specs — CME Group](https://www.cmegroup.com/markets/fx/g10/euro-fx.contractSpecs.html)
- [British Pound Futures GBP/USD Contract Specs — CME Group](https://www.cmegroup.com/markets/fx/g10/british-pound.contractSpecs.html)
- [E-mini S&P 500 Futures (ES) Contract Specs — NinjaTrader](https://ninjatrader.com/futures/futures-contracts/equity-index/e-mini-s-p-500/)
- [Futures Round Turn Cost — Ironbeam](https://www.ironbeam.com/futures-round-turn-cost/)
- [NFA Assessment Fees FAQ](https://www.nfa.futures.org/faqs/members/nfa-assessment-fees.html)
- [Futures Trading Fees Compared Across Brokers 2026 — Metrotrade](https://www.metrotrade.com/futures-trading-fees/)
- [Understanding Bid-Ask Spreads — Optimus Futures](https://learn.optimusfutures.com/bid-ask-spreads)
