"""Phase 5 — Research Layer.

Giver Loop A/B ekstern viden ud over den interne trade-historik:

- ``strategy_db``     — curated, statisk vidensbase (benchmarks + parameter-ranges), altid offline.
- ``backtest_reader`` — læser backtestede baselines fra BacktestResult-tabellen.
- ``web_searcher``    — best-effort urllib web-søgning (returnerer "" ved enhver fejl).
- ``researcher``      — orchestrerer de tre kilder til én kontekst-streng.

Designprincip: den curated viden er ALTID tilgængelig; web-søgning supplerer den men er
slået fra som standard (``reflection.research.web_search``), så nightly forbliver hurtig og
netværks-uafhængig. Intet i dette lag auto-applier noget — det beriger kun analyse-prompten.
"""
