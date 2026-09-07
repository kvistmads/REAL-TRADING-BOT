# Orderbook-optagelser — hvad de er, og hvad de IKKE er

Skrevet af `research/orderbook_recorder.py`. Formål: erstatte omkostningsmodellens
**skøn** for bid-ask spread med en måling. `research/output/cost_model.md` markerer
selv 1 tick spread og N(0,5; 0,5) ticks slippage som antagelser uden datagrundlag.

## Format

Parquet, partitioneret pr. dag og symbol:

```
data/orderbook/dt=YYYY-MM-DD/symbol=BTC-USDT/HHMM.parquet
```

Én række pr. snapshot: `ts`, `bid`, `ask`, `mid`, `spread_pct`, 20 niveauer pr. side
(`bid_px_0..19`, `bid_sz_0..19`, `ask_px_*`, `ask_sz_*`), plus `last_trade_px`,
`n_trades_sampled` og `buy_share` fra de seneste 50 handler.

Læs med `research.orderbook_recorder.load(symbol=..., day=...)`.

**Formatet er valgt før første snapshot og skal ikke ændres.** Skifter vi format
undervejs, er arkivet delt i to inkompatible halvdele.

## Begrænsning 1: dette er en STIKPRØVE, ikke en optagelse

Ét snapshot i minuttet. **Spread kan blæse ud i fem sekunder under en likvidation og
være tilbage igen — det ser vi ikke.**

Det betyder at den målte spread er **den typiske spread, ikke den spread man møder i
de øjeblikke hvor en kortsigtet strategi oftest handler.** En 15m-strategi der
handler på breakouts og volatilitetsudvidelser, handler pr. konstruktion netop når
bogen er tyndest.

Tallet herfra er derfor en **nedre grænse** for den spread en sådan strategi vil
betale. Skriv det med hver gang tallet bruges.

## Begrænsning 2: kun krypto

yfinance leverer ingen orderbook, så `EUR/USD`, `GBP/USD` og `XAU/USD` kan ikke
optages herfra. Futures-spread må estimeres (`research/spread_estimators.py`) eller
måles hos den broker der faktisk handles på.

## Begrænsning 3: maskinen sover

launchd genstarter processen ved boot og login, men en lukket MacBook kører ikke.
Hullerne kommer til at matche søvnrytmen — og det er **systematisk skævhed, ikke
tilfældige huller**: spread er bredest om natten og i weekenden, hvor likviditeten
er tyndest. Måles der kun i dagtimerne, bliver "typisk spread" for optimistisk.

```bash
.venv/bin/python research/orderbook_recorder.py --coverage
```

viser dækningsgrad **pr. time i døgnet**, netop så skævheden kan ses frem for gættes.
Er den skæv, er mulighederne `caffeinate -s`, ændrede energiindstillinger, eller at
optageren flytter til noget der altid er tændt.

## Sundhedstjek

`_heartbeat.json` indeholder seneste vellykkede snapshot, antal fejl og antal
registrerede huller:

```bash
cat data/orderbook/_heartbeat.json
```

Er `last_ok` gammel, kører optageren ikke. Logs ligger i `_logs/` og roterer ved 5 MB.

## Diskforbrug

Målt, ikke gættet: **1,7 MB/døgn · 52 MB/måned · 0,62 GB/år** for 3 symboler à 20
niveauer. Kør `--estimate-disk` for at genberegne hvis symboler eller dybde ændres.

## Planlagt validering

Krypto handler 24/7, så Corwin-Schultz' antagelser holder dér uden overnight-justering.
Når optageren har kørt et par uger: **sammenlign Corwin-Schultz-estimatet mod den målte
spread på de samme symboler over samme periode.**

Rammer estimatoren rigtigt dér hvor vi kan tjekke, kan vi tro på den på futures, hvor
vi ikke kan. Er den 3× ved siden af, er futures-tallene værdiløse. Indtil den
sammenligning er kørt, er alle estimater i `research/output/real_costs.md`
**uvaliderede**.
