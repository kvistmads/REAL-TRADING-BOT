"""ABRouter — tjekker for aktive A/B-eksperimenter og returnerer arm + params.

Kaldes af engine'en inden signal-evaluering. Er der intet aktivt eksperiment for
strategien, returneres None, og engine'en kører på strategiens default-parametre
(trades tagges så med ab_arm=None). Dette er den bevidst-tynde wrapper mellem
reflection-laget (som opretter eksperimenter) og live-execution.

Skema-note: et ABExperiment tester ÉN parameter ad gangen — value_a/value_b er
skalar-værdier (native JSON), ikke JSON-strenge med parameter-dicts. Derfor bygger
vi override-dict'en som {exp.parameter: exp.value_b}. Arm A er kontrol og kører på
strategiens defaults (tom params-dict).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from core.database import ABExperiment, Trade, sync_session_maker


@dataclass
class ArmAssignment:
    arm: str                       # "A" (kontrol) | "B" (kandidat)
    params: dict = field(default_factory=dict)  # tom dict = brug strategy defaults (arm A)
    experiment_id: int = 0


def get_assignment(strategy_id: str, *, session_factory=None) -> ArmAssignment | None:
    """Returnér arm-tildeling hvis der er et aktivt eksperiment for strategy_id.

    Returnér None hvis intet aktivt eksperiment — engine bruger defaults.
    50/50 random assignment per signal-evaluering. session_factory kan injiceres
    i tests; ellers bruges den synkrone produktions-session.
    """
    factory = session_factory or sync_session_maker
    with factory() as session:
        exp = (
            session.query(ABExperiment)
            .filter(
                ABExperiment.strategy_id == strategy_id,
                ABExperiment.status == "running",
            )
            .first()
        )

        if not exp:
            return None

        arm = "B" if random.random() < 0.5 else "A"
        params = {exp.parameter: exp.value_b} if arm == "B" else {}
        return ArmAssignment(arm=arm, params=params, experiment_id=exp.id)


def record_trade_arm(trade_id: str, assignment: ArmAssignment, session) -> None:
    """Tag trade'en med arm-label og øg eksperimentets trade-tæller.

    Muterer via den givne session — caller er ansvarlig for at committe.
    """
    trade = session.get(Trade, trade_id)
    if trade:
        trade.ab_arm = assignment.arm

    exp = session.get(ABExperiment, assignment.experiment_id)
    if exp:
        if assignment.arm == "A":
            exp.trades_a += 1
        else:
            exp.trades_b += 1
