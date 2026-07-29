"""Curated, statisk vidensbase over strategiernes kendte benchmarks og parameter-ranges.

Kræver ingen web-søgning — altid tilgængelig offline. Web-søgning (``web_searcher``)
supplerer denne viden men erstatter den ikke. Tallene er community/akademiske
tommelfingerregler til at sanity-tjekke egne parametre og performance, IKKE hårde
grænser (de hårde grænser bor i ``confidence_gate``).

Enheder: win_rate (wr) og alle ranges er fraktioner (0.0-1.0); profit_factor (pf) er
et forhold. Samme enheder som ``BacktestResult`` gemmer, så sammenligning er direkte.
"""

from __future__ import annotations

from typing import Any, Optional

STRATEGY_KNOWLEDGE: dict[str, dict] = {
    "trend_momentum": {
        "description": "MACD + EMA crossover med volume-confirmation",
        "known_benchmarks": {
            "crypto_4h": {"wr_range": [0.45, 0.60], "pf_range": [1.2, 2.5], "source": "Investopedia/Babypips backtests"},
            "forex_4h": {"wr_range": [0.40, 0.55], "pf_range": [1.1, 1.8], "source": "FXStreet research"},
            "gold_4h": {"wr_range": [0.50, 0.65], "pf_range": [1.5, 3.0], "source": "CME gold studies"},
        },
        "parameter_ranges": {
            "min_confidence": {"recommended": [0.60, 0.75], "note": "Under 0.60 → for mange falske signaler"},
            "cross_strength_scale": {"recommended": [0.05, 0.12], "note": "ATR-normaliseret — 0.08 er community-standard"},
            "trend_strength_scale.crypto": {"recommended": [0.03, 0.08]},
            "trend_strength_scale.forex": {"recommended": [0.008, 0.015]},
            "trend_strength_scale.gold": {"recommended": [0.02, 0.05]},
        },
        "known_failure_modes": [
            "Underpræsterer i news-drevne sideways markets (lav ATR, høj volume)",
            "Falske kryds ved lav likviditet (weekend crypto)",
        ],
    },
    "reversal_context": {
        "description": "RSI-divergence med volume-ratio filter",
        "known_benchmarks": {
            "crypto_4h": {"wr_range": [0.40, 0.55], "pf_range": [1.1, 1.9]},
            "forex_4h": {"wr_range": [0.45, 0.60], "pf_range": [1.2, 2.1]},
        },
        "parameter_ranges": {
            "min_rsi_delta": {"recommended": [3.0, 8.0], "note": "Under 3 → for støjfyldt"},
            "min_volume_ratio": {"recommended": [1.1, 1.5]},
            "min_confidence": {"recommended": [0.60, 0.75]},
        },
        "known_failure_modes": [
            "Underpræsterer i stærke trends (RSI kan forblive overkøbt/oversolgt længe)",
            "Kræver tilstrækkelig volumendata — spot forex mangler dette (brug CME futures)",
        ],
    },
    "volatility_breakout": {
        "description": "Bollinger Band squeeze + ATR-breakout med volume-confirm",
        "known_benchmarks": {
            "crypto_4h": {"wr_range": [0.42, 0.58], "pf_range": [1.3, 2.8]},
            "gold_4h": {"wr_range": [0.48, 0.62], "pf_range": [1.4, 2.5]},
        },
        "parameter_ranges": {
            "squeeze_percentile": {"recommended": [5, 15], "note": "10 er standard — lavere → sjældnere men renere setups"},
            "min_volume_ratio": {"recommended": [1.3, 2.0]},
            "min_confidence": {"recommended": [0.60, 0.72]},
        },
        "known_failure_modes": [
            "Falske breakouts i lav-likviditetsmiljøer",
            "Squeeze kan vare uger — kræver tålmodighed",
        ],
    },
}


def _get_nested(params: dict, dotted_key: str) -> Any:
    """Slå en (evt. punkt-adresseret) nøgle op i params, fx 'trend_strength_scale.crypto'."""
    if dotted_key in params:
        return params[dotted_key]
    node: Any = params
    for part in dotted_key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _param_lines(param_ranges: dict, current_params: dict) -> list[str]:
    lines: list[str] = []
    for name, spec in param_ranges.items():
        lo, hi = spec["recommended"]
        note = spec.get("note", "")
        value = _get_nested(current_params, name)
        if value is None:
            lines.append(f"- {name}: (ikke sat i config) — anbefalet {lo}–{hi}. {note}".rstrip())
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            lines.append(f"- {name}={value}: kunne ikke sammenlignes med range {lo}–{hi}.")
            continue
        if v < lo:
            lines.append(f"- ⚠️ {name}={value} er UNDER anbefalet range [{lo}, {hi}]. {note}".rstrip())
        elif v > hi:
            lines.append(f"- ⚠️ {name}={value} er OVER anbefalet range [{lo}, {hi}]. {note}".rstrip())
        else:
            lines.append(f"- ✅ {name}={value} er inden for anbefalet range [{lo}, {hi}].")
    return lines


def _benchmark_lines(benchmarks: dict, performance: dict, asset_class: Optional[str]) -> list[str]:
    """Sammenlign live wr/pf med benchmark for asset_class (4h). Tom hvis intet at sammenligne."""
    if not performance:
        return []
    key = f"{asset_class}_4h" if asset_class else None
    bench = benchmarks.get(key) if key else None
    if bench is None:
        # Fald tilbage til det bredeste benchmark (union af ranges) hvis asset_class ukendt.
        return []
    lines = [f"Benchmark ({key}, kilde: {bench.get('source', 'community')}):"]
    wr = performance.get("wr")
    pf = performance.get("pf")
    if wr is not None and "wr_range" in bench:
        lo, hi = bench["wr_range"]
        verdict = "under" if wr < lo else ("over" if wr > hi else "inden for")
        lines.append(f"- Live win-rate {wr:.0%} er {verdict} benchmark {lo:.0%}–{hi:.0%}.")
    if pf is not None and "pf_range" in bench:
        lo, hi = bench["pf_range"]
        verdict = "under" if pf < lo else ("over" if pf > hi else "inden for")
        lines.append(f"- Live profit-factor {pf:.2f} er {verdict} benchmark {lo}–{hi}.")
    return lines


def get_strategy_context(
    strategy_id: str,
    current_params: dict,
    performance: dict,
    *,
    asset_class: Optional[str] = None,
) -> str:
    """Byg en kontekst-streng der holder nuværende parametre + performance op mod curated viden.

    Fremhæver parametre uden for anbefalede ranges (⚠️) og performance ift. kendte benchmarks.
    Returnerer en kort note hvis strategien ikke er i vidensbasen (aldrig en exception).
    """
    knowledge = STRATEGY_KNOWLEDGE.get(strategy_id)
    if knowledge is None:
        return f"(ingen curated viden for {strategy_id})"

    current_params = current_params or {}
    performance = performance or {}

    lines = [f"Strategi-viden: {knowledge['description']}"]

    param_lines = _param_lines(knowledge.get("parameter_ranges", {}), current_params)
    if param_lines:
        lines.append("Parametre vs. anbefalede ranges:")
        lines.extend(param_lines)

    bench_lines = _benchmark_lines(knowledge.get("known_benchmarks", {}), performance, asset_class)
    if bench_lines:
        lines.extend(bench_lines)

    failures = knowledge.get("known_failure_modes", [])
    if failures:
        lines.append("Kendte failure modes:")
        lines.extend(f"- {f}" for f in failures)

    return "\n".join(lines)


def get_ab_experiment_ideas(strategy_id: str) -> list[str]:
    """Foreslå A/B-eksperimenter udledt af parameter-ranges (til Loop B-rapporten).

    Rene forslag baseret på curated viden — aldrig auto-apply. Tester hver parameters
    range-endepunkter mod hinanden (fx cross_strength_scale 0.05 vs 0.12).
    """
    knowledge = STRATEGY_KNOWLEDGE.get(strategy_id)
    if knowledge is None:
        return []
    ideas: list[str] = []
    for name, spec in knowledge.get("parameter_ranges", {}).items():
        lo, hi = spec["recommended"]
        note = spec.get("note", "")
        ideas.append(f"{name}: test {lo} vs {hi}" + (f" ({note})" if note else ""))
    return ideas
