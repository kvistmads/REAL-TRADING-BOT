"""Phase 4 — Learning Loop.

To uafhængige feedback-loops der forbedrer botten over tid uden at røre kapital-
parametre eller live-beslutninger:

- Loop A (``nightly.py``): analyserer lukkede trades, foreslår parameter-justeringer.
- Loop B (``weekly.py``): analyserer selve kodebasen (arkitektur/performance) — rapport only.

Fælles infrastruktur: ChromaDB (``chromadb_store``), Anthropic-klient (``analyst``),
forslags-gaten (modulet hedder ``confidence_gate``, config-nøglen ``reflection.proposal_gate``
— den vurderer analystens tillid til sit eget PARAMETERFORSLAG, ikke et handelssignals
confidence). Alle guardrails er hard-coded i modulet og kan ikke overrides af config.
"""
