"""Researcher — orchestrerer de tre research-kilder til én kontekst-streng for Loop A/B.

Kilder: strategy_db (curated, altid on), backtest_reader (DB-baseline), web_searcher
(best-effort, slået fra som standard). Alt er best-effort: en fejlende kilde giver en
kort note frem for en exception, så nightly aldrig vælter på research-laget.
"""

from __future__ import annotations

import logging
from typing import Optional

from strategies.base import BaseStrategy

from reflection.research import backtest_reader, strategy_db, web_searcher

logger = logging.getLogger(__name__)


class Researcher:
    def __init__(self, *, enable_web: bool = False, store=None):
        """enable_web: slå urllib web-søgning til (default fra → hurtig/offline).
        store: valgfri ObservationStore til web-cache (7 dages TTL).
        """
        self.enable_web = enable_web
        self.store = store

    def build_context(
        self,
        strategy_id: str,
        symbol: str,
        period_str: str,
        current_params: dict,
        live_metrics: dict,
        session,
    ) -> str:
        """Byg samlet research-kontekst for én (strategi × symbol)-kombination."""
        asset_class = BaseStrategy.get_asset_class(symbol)

        macro = self._macro(period_str)
        strat_curated = strategy_db.get_strategy_context(
            strategy_id, current_params, live_metrics, asset_class=asset_class
        )
        strat_web = self._strategy_web(strategy_id)
        baseline = self._baseline(strategy_id, symbol, session)
        compare = backtest_reader.compare_live_vs_backtest(live_metrics, baseline)

        parts = [
            f"## Research kontekst for {strategy_id} × {symbol}",
            "",
            f"### Ekstern makro-kontekst ({period_str}):",
            macro or "(ingen web makro-kontekst — søgning slået fra eller uden resultat)",
            "",
            "### Strategi-research:",
            strat_curated,
        ]
        if strat_web:
            parts.append(strat_web)
        parts += [
            "",
            "### Backtest baseline:",
            compare,
            "",
            "### Implikationer for analysen:",
            "- Hvis live underpræsterer backtest OG makro var atypisk → flag perioden, undgå parameterændringer.",
            "- Hvis live underpræsterer backtest OG makro var normal → parameterændring kan være relevant.",
            "- Hvis parametre er uden for anbefalede ranges (⚠️) → prioritér at korrigere dem.",
        ]
        return "\n".join(parts)

    def build_strategy_deep_dive(self, strategy_id: str, session) -> str:
        """Dybere strategi-research til Loop B (curated viden + evt. web)."""
        curated = strategy_db.get_strategy_context(strategy_id, {}, {})
        web = self._strategy_web(strategy_id)
        ideas = strategy_db.get_ab_experiment_ideas(strategy_id)
        lines = [f"### {strategy_id}", curated]
        if web:
            lines.append(web)
        if ideas:
            lines.append("Mulige A/B-eksperimenter:")
            lines.extend(f"- {idea}" for idea in ideas)
        return "\n".join(lines)

    def build_ab_experiment_suggestions(self, strategy_ids: list[str], session=None) -> str:
        """Byg 'Anbefalede A/B-eksperimenter'-afsnittet til Loop B-rapporten.

        Rene forslag afledt af den curated vidensbase — aldrig auto-apply.
        """
        blocks: list[str] = []
        for sid in strategy_ids:
            ideas = strategy_db.get_ab_experiment_ideas(sid)
            if not ideas:
                continue
            blocks.append(f"**{sid}:**")
            blocks.extend(f"- {idea}" for idea in ideas)
            blocks.append("")
        if not blocks:
            return "Ingen research-baserede eksperiment-forslag."
        return "\n".join(blocks).strip()

    # ------------------------------------------------------------------
    # Interne best-effort-wrappers
    # ------------------------------------------------------------------

    def _macro(self, period_str: str) -> str:
        if not self.enable_web:
            return ""
        try:
            return web_searcher.search_macro_context(period_str)
        except Exception as e:  # pragma: no cover - web_searcher sluger selv fejl
            logger.warning("Makro-søgning fejlede: %s", e)
            return ""

    def _strategy_web(self, strategy_id: str) -> str:
        if not self.enable_web:
            return ""
        try:
            return web_searcher.search_strategy_research(strategy_id, store=self.store)
        except Exception as e:  # pragma: no cover
            logger.warning("Strategi-søgning fejlede: %s", e)
            return ""

    def _baseline(self, strategy_id: str, symbol: str, session) -> Optional[dict]:
        try:
            return backtest_reader.get_backtest_baseline(strategy_id, symbol, session=session)
        except Exception as e:  # pragma: no cover
            logger.warning("Backtest-baseline opslag fejlede: %s", e)
            return None
