"""StrategyMemory — Loop A husker hvad den allerede har lært (Phase 4.1 Del A).

Ved starten af hvert Loop A-kald bygger denne klasse en kortfattet
"hvad-ved-vi-allerede"-opsummering pr. strategi og injicerer den i Lag 1-prompten,
så LLM'en bygger videre på akkumuleret viden i stedet for at re-opdage det samme
hver nat (og ikke genforeslår ting brugeren allerede har afvist).

Datakilder:
- Observation-tabellen (auto-applied / afviste / høj-confidence-uden-handling)
- ABExperiment (outcome for auto-applied ændringer: win-rate før/efter)
- ChromaDB (valgfrit): semantisk relaterede historiske observationer

Best-effort: fejl i én kilde må aldrig vælte nightly — de logges og springes over.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from core.database import ABExperiment, Observation
from core.time_utils import utc_now

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 90


class StrategyMemory:
    def __init__(self, store=None, lookback_days: int = _LOOKBACK_DAYS):
        """store: valgfri ObservationStore til semantisk ChromaDB-opslag."""
        self.store = store
        self.lookback_days = lookback_days

    def build_context(self, strategy_id: str, session) -> str:
        """Opsummér hvad vi ved om ``strategy_id`` som en prompt-venlig streng.

        Tom streng hvis der intet er at fortælle (så prompten ikke får en tom
        overskrift). Sorteret nyeste-først, max ``lookback_days`` tilbage.
        """
        cutoff = utc_now() - timedelta(days=self.lookback_days)

        applied = (
            session.query(Observation)
            .filter(
                Observation.strategy_id == strategy_id,
                Observation.auto_applied.is_(True),
                Observation.created_at >= cutoff,
            )
            .order_by(Observation.created_at.desc())
            .limit(10)
            .all()
        )
        rejected = (
            session.query(Observation)
            .filter(
                Observation.strategy_id == strategy_id,
                Observation.approved_by_user.is_(False),
                Observation.created_at >= cutoff,
            )
            .order_by(Observation.created_at.desc())
            .limit(5)
            .all()
        )
        pending = (
            session.query(Observation)
            .filter(
                Observation.strategy_id == strategy_id,
                Observation.auto_applied.is_(False),
                Observation.approved_by_user.is_(None),
                Observation.confidence >= 0.70,
                Observation.created_at >= cutoff,
            )
            .order_by(Observation.created_at.desc())
            .limit(5)
            .all()
        )

        semantic = self._semantic(strategy_id)
        return self._format(applied, rejected, pending, semantic, session)

    def _ab_outcome(self, obs: Observation, session) -> str:
        """Slå A/B-eksperimentets resultat op for en auto-applied observation."""
        exp = (
            session.query(ABExperiment)
            .filter(ABExperiment.observation_id == obs.id)
            .order_by(ABExperiment.created_at.desc())
            .first()
        )
        if exp is None:
            return "outcome: ikke målt"
        wa = "-" if exp.win_rate_a is None else f"{exp.win_rate_a:.0%}"
        wb = "-" if exp.win_rate_b is None else f"{exp.win_rate_b:.0%}"
        return f"outcome[{exp.status}]: win-rate A={wa} → B={wb}"

    def _semantic(self, strategy_id: str) -> list[dict]:
        if self.store is None:
            return []
        try:
            return self.store.query_similar(f"strategi {strategy_id} historiske observationer", n=5)
        except Exception as e:  # ChromaDB er best-effort
            logger.warning("StrategyMemory: ChromaDB-opslag fejlede: %s", e)
            return []

    def _format(self, applied, rejected, pending, semantic, session) -> str:
        lines = ["## Hvad vi ved om denne strategi (historisk):"]
        if applied:
            lines.append("### Auto-applied ændringer:")
            for o in applied:
                outcome = self._ab_outcome(o, session)
                lines.append(
                    f"- [{o.created_at.date()}] {o.parameter}: "
                    f"{o.current_value} → {o.suggested_value} | {outcome}"
                )
        if rejected:
            lines.append("### Afviste forslag (undersøg ikke igen):")
            for o in rejected:
                lines.append(
                    f"- [{o.created_at.date()}] {o.parameter}: "
                    f"{o.suggested_value} afvist — {o.notes or ''}"
                )
        if pending:
            lines.append("### Høj-confidence observationer uden handling:")
            for o in pending:
                lines.append(f"- [{o.created_at.date()}] conf={o.confidence:.2f}: {o.notes or ''}")
        if semantic:
            lines.append("### Semantisk relaterede tidligere observationer:")
            for s in semantic:
                lines.append(f"- {s.get('text', '')}")
        return "\n".join(lines) if len(lines) > 1 else ""
