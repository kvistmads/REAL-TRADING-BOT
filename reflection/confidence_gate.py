"""Confidence gate — afgør per observation: auto_apply / telegram_approval / report_only.

Dette er guardrail-laget (PRD Opgave 5). Reglerne her er hard-coded og kan IKKE
overrides af LLM-output eller config-værdier:

1. protected_parameters → altid report_only.
2. Under min_trades_for_analysis (200) globalt → auto-apply deaktiveret (report_only).
3. Auto-apply kræver: confidence >= auto_apply_threshold OG n >= min_sample_for_auto
   OG relativ ændring <= max_change_pct.
4. Ellers: confidence >= telegram_threshold → telegram_approval; under det → report_only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GateDecision:
    action: str  # "auto_apply" | "telegram_approval" | "report_only"
    reason: str


def _change_pct(obs: dict) -> float:
    """Relativ ændring |suggested - current| / |current|.

    Returnerer 1.0 (100% — blokerer auto) hvis værdierne ikke er numeriske eller
    current er 0, så vi aldrig auto-applier en ændring vi ikke kan kvantificere.
    """
    cur = obs.get("current_value")
    sug = obs.get("suggested_value")
    try:
        cur = float(cur)
        sug = float(sug)
    except (TypeError, ValueError):
        return 1.0
    if cur == 0:
        return 1.0
    return abs(sug - cur) / abs(cur)


def evaluate(obs: dict, cfg: dict, total_trades: int) -> GateDecision:
    """
    obs: observation-dict fra LLM med bl.a. confidence, evidence.n, parameter,
         current_value, suggested_value.
    cfg: fladt gate-config med nøglerne protected_parameters, min_trades_for_analysis,
         auto_apply_threshold, telegram_threshold, min_sample_for_auto, max_change_pct.
    total_trades: antal lukkede trades i DB globalt.
    """
    conf = obs.get("confidence", 0) or 0
    n = (obs.get("evidence") or {}).get("n", 0) or 0
    param = obs.get("parameter") or ""
    change_pct = _change_pct(obs)

    # Regel 1 — hård beskyttelse.
    if param in cfg["protected_parameters"]:
        return GateDecision("report_only", f"{param} er beskyttet parameter")

    # Regel 2 — for få lukkede trades globalt: auto-apply globalt deaktiveret.
    if total_trades < cfg["min_trades_for_analysis"]:
        return GateDecision(
            "report_only",
            f"Kun {total_trades} trades — min {cfg['min_trades_for_analysis']} krævet",
        )

    # Regel 3 — auto-apply (alle betingelser skal være opfyldt).
    if (
        conf >= cfg["auto_apply_threshold"]
        and n >= cfg["min_sample_for_auto"]
        and change_pct <= cfg["max_change_pct"]
    ):
        return GateDecision(
            "auto_apply", f"conf={conf:.2f}, n={n}, ændring={change_pct:.1%}"
        )

    # Regel 4 — telegram-godkendelse.
    if conf >= cfg["telegram_threshold"]:
        return GateDecision("telegram_approval", f"conf={conf:.2f}, n={n}")

    return GateDecision("report_only", f"conf={conf:.2f} under telegram-tærsklen")
