"""Loop A — Nightly Trade-Analysis (PRD Opgave 2).

Kører 02:00 UTC (via scheduler) eller manuelt. Analyserer lukkede trades i tre lag,
kører hver observation gennem confidence-gaten og dispatcher:
- auto_apply         → ParameterApplier skriver til config.yaml
- telegram_approval  → A/B-eksperiment startes + observation sendes til godkendelse
- report_only        → kun med i markdown-rapporten

    .venv/bin/python reflection/nightly.py --dry-run   # analysér, apply intet
    .venv/bin/python reflection/nightly.py             # fuld kørsel
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import yaml
from dotenv import load_dotenv

# Gør projekt-roden importerbar når scriptet køres direkte (python reflection/nightly.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import Observation, init_sync_db, sync_session_maker
from core.time_utils import utc_now
from reflection import confidence_gate, extractor
from reflection.ab_tracker import ABTracker
from reflection.analyst import ReflectionAnalyst
from reflection.applier import ParameterApplier
from reflection.chromadb_store import ObservationStore
from reflection.research.researcher import Researcher
from reflection.strategy_memory import StrategyMemory
from reflection.reporter import (
    TelegramReporter,
    format_nightly_telegram,
    write_nightly_report,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt-byggere (tre-lags cascading analyse)
# ---------------------------------------------------------------------------

def _prompt_layer1(
    strategy_id: str, sub, meta_cols: list[str], memory_ctx: str = "", research_ctx: str = ""
) -> str:
    keys = ", ".join(c.replace("meta_", "") for c in meta_cols) or "(ingen metadata)"
    cols = ["symbol", "side", "pnl_pct", "won", "session", "market_regime", "adx_at_entry", *meta_cols]
    cols = [c for c in cols if c in sub.columns]
    csv = sub[cols].to_csv(index=False)
    memory_block = ""
    if memory_ctx:
        memory_block = (
            f"\n{memory_ctx}\n\n"
            "## Vigtigt: Foreslå IKKE ændringer der allerede er afvist (se afviste forslag ovenfor).\n"
            "Byg videre på auto-applied ændringer fremfor at revertere dem uden stærkt "
            "statistisk grundlag.\n"
        )
    research_block = ""
    if research_ctx:
        research_block = (
            f"\n{research_ctx}\n\n"
            "## Instruktioner til analysen:\n"
            "- Hvis makro-konteksten forklarer underperformance → flag perioden som atypisk, "
            "foreslå IKKE parameterændringer\n"
            "- Sammenlign nuværende parametre med anbefalede ranges — prioritér korrektioner "
            "der er UDENFOR range\n"
            "- Sammenlign live performance med backtest baseline — store afvigelser kræver forklaring\n"
            "- Byg videre på hvad der allerede virker (se memory-kontekst) fremfor at "
            "eksperimentere bredt\n"
        )
    return (
        f"Du er en kvantitativ trading-analytiker. Nedenfor er {len(sub)} lukkede trades "
        f"for strategi '{strategy_id}'. Hver trade har metadata (indikatorer ved entry) og "
        f"outcome (pnl_pct, won).\n\n"
        f"Find de indikator-tærskler der bedst skelner vindende fra tabende trades.\n"
        f"Se særligt på: {keys}.\n"
        f"{memory_block}"
        f"{research_block}\n"
        "Svar KUN med et JSON-array af observationer i formatet:\n"
        '[{"strategy_id":"...","type":"parameter_suggestion","parameter":"...",'
        '"current_value":...,"suggested_value":...,'
        '"evidence":{"win_above":0.0,"win_below":0.0,"n":0,"threshold":0.0},'
        '"confidence":0.0,"reasoning":"..."}]\n\n'
        f"TRADES:\n{csv}"
    )


def _live_metrics(sub) -> dict:
    """Kompakte live-metrics for et (strategi × symbol)-subset til research-sammenligning."""
    n = len(sub)
    if n == 0:
        return {"trades": 0, "wr": 0.0, "pf": None, "avg_pnl_pct": 0.0}
    gains = float(sub.loc[sub["pnl_pct"] > 0, "pnl_pct"].sum())
    losses = float(-sub.loc[sub["pnl_pct"] < 0, "pnl_pct"].sum())
    pf = None if losses == 0 else round(gains / losses, 3)
    return {
        "trades": n,
        "wr": round(float((sub["pnl_pct"] > 0).mean()), 3),
        "pf": pf,
        "avg_pnl_pct": round(float(sub["pnl_pct"].mean()), 3),
    }


def _build_research_ctx(researcher, strategy_id: str, sub, config: dict, period_str: str, session) -> str:
    """Byg research-kontekst pr. symbol for en strategi (best-effort → "" ved fejl)."""
    if researcher is None:
        return ""
    try:
        strat_cfg = config.get("strategies", {})
        sparams = strat_cfg.get("params", {}).get(strategy_id, {})
        current_params = {**sparams, "min_confidence": strat_cfg.get("min_confidence")}
        blocks = []
        for symbol in sub["symbol"].dropna().unique():
            sym_sub = sub[sub["symbol"] == symbol]
            blocks.append(
                researcher.build_context(
                    strategy_id, symbol, period_str, current_params, _live_metrics(sym_sub), session
                )
            )
        return "\n\n".join(blocks)
    except Exception as e:  # research må aldrig vælte nightly
        logger.warning("Kunne ikke bygge research-kontekst for %s: %s", strategy_id, e)
        return ""


def _prompt_layer2(strategy_id: str, agg_csv: str) -> str:
    return (
        f"Analyser præstationsmønstrene for strategi '{strategy_id}' på tværs af symboler, "
        "sessioner og regime-kontekster.\n"
        "Find: (1) hvilke symboler/sessioner/regimer der over/underperformer, (2) temporal "
        "drift, (3) regime-korrelationer der forudsiger tab bedre end regime-gaten i dag.\n\n"
        'Svar i samme JSON-format. Tilladt type: "regime_correlation" | "temporal_drift" | '
        '"symbol_filter".\n\n'
        f"AGGREGEREDE DATA (symbol × session × regime):\n{agg_csv}"
    )


def _prompt_layer3(weekly_csv: str, corr_csv: str, shadow_csv: str = "", lookback_days: int = 30) -> str:
    shadow_block = ""
    if shadow_csv:
        shadow_block = (
            f"\n\n## News Intelligence performance (seneste {lookback_days} dage):\n"
            f"{shadow_csv}\n\n"
            "Find: Er der perioder hvor news-intelligence havde høj accuracy men vores tekniske "
            "strategier underpræsterede? Det indikerer at news-signalet kunne have haft merværdi."
        )
    return (
        "Nedenfor er de tre strategiers ugentlige pnl og deres korrelationsmatrix.\n"
        "Find: (1) perioder hvor alle taber samtidig (systemisk fejl), (2) om strategierne "
        "reelt er ukorrelerede, (3) om porteføljen giver reel diversifikation.\n\n"
        'Svar med type: "portfolio_pattern" | "correlation_warning" | "diversification_gap".\n\n'
        f"UGENTLIG PNL PR. STRATEGI:\n{weekly_csv}\n\nKORRELATIONSMATRIX:\n{corr_csv}"
        f"{shadow_block}"
    )


# ---------------------------------------------------------------------------
# Kørsel
# ---------------------------------------------------------------------------

def _gate_cfg(reflection_cfg: dict) -> dict:
    """Fladt config-dict til confidence_gate.evaluate."""
    return {
        **reflection_cfg["confidence_gate"],
        "protected_parameters": reflection_cfg["protected_parameters"],
        "min_trades_for_analysis": reflection_cfg["min_trades_for_analysis"],
    }


def run_nightly(
    config: dict,
    dry_run: bool = False,
    *,
    session_factory=None,
    analyst=None,
    store=None,
    applier=None,
    reporter=None,
    memory=None,
    researcher=None,
    cfg_path: str = "config.yaml",
) -> dict:
    """Kør Loop A. Returnér et summary-dict (til logging/test).

    Alle afhængigheder kan injiceres (til tests). Uden injektion bruges
    produktions-objekterne: den rigtige DB, ChromaDB-store, Anthropic-analyst osv.
    """
    rcfg = config["reflection"]
    if not rcfg.get("enabled", False):
        logger.info("reflection.enabled=false — springer nightly over.")
        return {"skipped": True}

    date_str = utc_now().strftime("%Y-%m-%d")
    if session_factory is None:
        init_sync_db()
        session_factory = sync_session_maker
    if store is None:
        store = ObservationStore()
    if analyst is None:
        analyst = ReflectionAnalyst(rcfg["anthropic_model"], store=store)
    if applier is None:
        applier = ParameterApplier()
    if reporter is None:
        reporter = TelegramReporter(config)
    if memory is None:
        memory = StrategyMemory(store=store)
    if researcher is None:
        research_cfg = rcfg.get("research", {})
        if research_cfg.get("enabled", True):
            researcher = Researcher(enable_web=research_cfg.get("web_search", False), store=store)
    period_str = utc_now().strftime("%B %Y")
    gate_cfg = _gate_cfg(rcfg)
    ab = ABTracker(
        significance_threshold=rcfg["ab_experiments"]["significance_threshold"],
        min_trades_per_arm=rcfg["ab_experiments"]["min_trades_per_arm"],
    )

    auto_applied: list[dict] = []
    pending: list[dict] = []
    report_only: list[dict] = []
    all_obs_for_report: list[dict] = []

    with session_factory() as session:
        total_trades = extractor.count_closed_trades(session)
        df = extractor.extract_closed_trades(session, rcfg["nightly"]["lookback_days"])
        logger.info("Nightly: %d lukkede trades i lookback, %d totalt.", len(df), total_trades)

        raw_observations: list[dict] = []
        if not df.empty:
            min_per_strat = rcfg["nightly"]["min_trades_per_strategy"]
            # Lag 1 + 2 pr. strategi
            for strategy_id, sub in df.groupby("strategy_id"):
                if len(sub) < min_per_strat:
                    logger.info("Springer %s over (%d < %d trades).", strategy_id, len(sub), min_per_strat)
                    continue
                meta_cols = extractor.meta_columns(sub)
                ctx = f"strategi {strategy_id} nightly analyse"
                memory_ctx = memory.build_context(strategy_id, session)
                research_ctx = _build_research_ctx(
                    researcher, strategy_id, sub, config, period_str, session
                )
                raw_observations += analyst.analyse(
                    _prompt_layer1(strategy_id, sub, meta_cols, memory_ctx, research_ctx), ctx
                )
                agg = extractor.aggregate_by_symbol_session_regime(sub)
                if not agg.empty:
                    raw_observations += analyst.analyse(_prompt_layer2(strategy_id, agg.to_csv(index=False)), ctx)
            # Lag 3 — portefølje (beriget med news-intelligence-performance)
            weekly = extractor.weekly_pnl_by_strategy(df)
            corr = extractor.strategy_correlation(weekly)
            lookback = rcfg["nightly"]["lookback_days"]
            shadow_df = extractor.extract_shadow_signal_performance(session, lookback)
            shadow_csv = shadow_df.to_csv(index=False) if not shadow_df.empty else ""
            if not weekly.empty:
                raw_observations += analyst.analyse(
                    _prompt_layer3(weekly.to_csv(), corr.to_csv(), shadow_csv, lookback),
                    "portefølje meta-analyse",
                )

        # Dispatch hver observation gennem gaten
        for obs in raw_observations:
            decision = confidence_gate.evaluate(obs, gate_cfg, total_trades)
            if dry_run:
                decision.action = "report_only"
                decision.reason = f"[dry-run] {decision.reason}"

            row = Observation(
                loop="nightly",
                observation_type=obs.get("type", "parameter_suggestion"),
                strategy_id=obs.get("strategy_id"),
                parameter=obs.get("parameter"),
                current_value=obs.get("current_value"),
                suggested_value=obs.get("suggested_value"),
                evidence=obs.get("evidence", {}),
                confidence=float(obs.get("confidence", 0) or 0),
                notes=obs.get("reasoning"),
            )
            session.add(row)
            session.flush()  # tildel row.id

            text = _obs_text(obs)
            try:
                row.chromadb_id = store.add(row.id, text, {"type": row.observation_type,
                                                            "strategy": row.strategy_id or "portfolio"})
            except Exception as e:
                logger.warning("Kunne ikke gemme observation i ChromaDB: %s", e)

            obs["_gate_action"] = decision.action
            obs["_gate_reason"] = decision.reason
            all_obs_for_report.append(obs)

            if decision.action == "auto_apply":
                record = applier.apply(row, cfg_path=cfg_path, notify=reporter.send)
                auto_applied.append(record)
            elif decision.action == "telegram_approval":
                if row.strategy_id and row.parameter:
                    ab.start_experiment(row, session)
                pending.append(obs)
            else:
                report_only.append(obs)

        session.commit()

    report_path = write_nightly_report(date_str, all_obs_for_report)
    message = format_nightly_telegram(
        date_str, len(df) if not df.empty else 0,
        auto_applied, pending, report_only, report_path,
    )
    reporter.send(message)

    summary = {
        "date": date_str,
        "trades_analysed": int(len(df)),
        "total_trades": total_trades,
        "auto_applied": len(auto_applied),
        "pending": len(pending),
        "report_only": len(report_only),
        "report_path": report_path,
        "dry_run": dry_run,
    }
    logger.info("Nightly færdig: %s", summary)
    return summary


def _obs_text(obs: dict) -> str:
    return (
        f"{obs.get('type','')} {obs.get('strategy_id','')} {obs.get('parameter','')}: "
        f"{obs.get('current_value')} -> {obs.get('suggested_value')}. {obs.get('reasoning','')}"
    ).strip()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Loop A — Nightly trade-analyse")
    parser.add_argument("--dry-run", action="store_true", help="Analysér, men apply intet")
    args = parser.parse_args()

    load_dotenv()
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    run_nightly(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
