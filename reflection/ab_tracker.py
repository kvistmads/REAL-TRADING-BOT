"""A/B-tracker: sammenligner kontrol (arm A) mod kandidat (arm B) på en parameter.

Kontrakt (PRD Opgave 2c): bruges KUN for telegram_approval-observationer. auto_apply
går direkte til applier (nok statistisk grundlag), report_only starter intet.

NB: selve tildelingen af nye live-trades til arm A/B ligger i execution-laget og er
bevidst IKKE wired op her — Phase 4 har en hård grænse mod at ændre live-trading-logik
fra reflection-laget. Denne klasse opretter eksperimentet og evaluerer resultatet når
execution-laget (senere) har udfyldt trades_*/win_rate_*/profit_factor_*.
"""

from __future__ import annotations

import logging

from core.database import ABExperiment, Observation

logger = logging.getLogger(__name__)


class ABTracker:
    def __init__(self, significance_threshold: float = 0.10, min_trades_per_arm: int = 30):
        self.significance_threshold = significance_threshold
        self.min_trades_per_arm = min_trades_per_arm

    def start_experiment(self, obs: Observation, session) -> ABExperiment:
        """Opret et eksperiment for en parameter-ændring og gem det."""
        exp = ABExperiment(
            observation_id=obs.id,
            strategy_id=obs.strategy_id,
            parameter=obs.parameter,
            value_a=obs.current_value,
            value_b=obs.suggested_value,
            min_trades_per_arm=self.min_trades_per_arm,
        )
        session.add(exp)
        session.flush()  # tildel exp.id uden at kræve fuld commit her
        logger.info(
            "A/B-eksperiment startet: %s.%s  A=%s vs B=%s",
            obs.strategy_id, obs.parameter, obs.current_value, obs.suggested_value,
        )
        return exp

    def evaluate(self, exp: ABExperiment) -> str:
        """Evaluér status. Muterer exp.status og returnerer den.

        "running" indtil begge arme har >= min_trades_per_arm. Derefter vinder B
        hvis dens profit factor er mindst (1 + significance_threshold) gange A's
        (og omvendt); ellers "inconclusive".
        """
        if exp.trades_a < exp.min_trades_per_arm or exp.trades_b < exp.min_trades_per_arm:
            exp.status = "running"
            return exp.status

        pf_a = exp.profit_factor_a or 0.0
        pf_b = exp.profit_factor_b or 0.0
        edge = 1 + self.significance_threshold

        if pf_b > pf_a * edge:
            exp.status = "b_wins"
        elif pf_a > pf_b * edge:
            exp.status = "a_wins"
        else:
            exp.status = "inconclusive"
        return exp.status
