"""Loop C — News Intelligence (Phase 4.1 Del B).

Køres hver 2. time ("0 */2 * * *"). Opgaver pr. kørsel:
1. Evaluer afventende shadow signals (faktisk outcome).
2. Hent nye headlines for alle 6 symboler.
3. Generer shadow signals hvor confidence >= min_confidence.
4. Tjek promotion-alerts (Telegram).
5. Match/konflikt-check mod aktive tekniske signaler (fra DB).
6. Send kort Telegram-status (kun hvis noget nyt).

Rører ALDRIG kapital eller live-logik — confirmation-hooket er Phase 5 (config-flag false).

    .venv/bin/python reflection/loop_c.py --dry-run   # generér intet, evaluer kun
    .venv/bin/python reflection/loop_c.py             # fuld kørsel
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta

import yaml
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from core.database import ShadowSignal, SignalLog, init_sync_db, sync_session_maker
from core.time_utils import utc_now
from reflection.analyst import ReflectionAnalyst
from reflection.chromadb_store import ObservationStore
from reflection.news import accuracy_tracker, shadow_trader
from reflection.reporter import TelegramReporter

logger = logging.getLogger(__name__)

# De 6 symboler Loop C dækker (crypto via CryptoPanic/Fear&Greed, forex/gold via Alpaca).
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "EUR/USD", "GBP/USD", "XAU/USD"]

_SIDE_TO_DIR = {"long": "up", "short": "down", "buy": "up", "sell": "down"}


def _match_technical_signals(session, sig: ShadowSignal, now: datetime) -> None:
    """Sæt matching_/conflicting_strategies ud fra nylige tekniske signaler.

    Infrastruktur til Phase 5-confirmation-hooket — selve hooket aktiveres ikke her.
    """
    cutoff = now - timedelta(hours=sig.horizon_hours)
    rows = (
        session.execute(
            select(SignalLog).where(
                SignalLog.symbol == sig.symbol,
                SignalLog.timestamp >= cutoff,
                SignalLog.gate_passed.is_(True),
            )
        )
        .scalars()
        .all()
    )
    matching, conflicting = [], []
    for r in rows:
        tech_dir = _SIDE_TO_DIR.get(str(r.side).lower())
        if tech_dir is None:
            continue
        if tech_dir == sig.predicted_direction:
            matching.append(r.strategy_id)
        else:
            conflicting.append(r.strategy_id)
    sig.matching_strategies = sorted(set(matching)) or None
    sig.conflicting_strategies = sorted(set(conflicting)) or None


def run_loop_c(
    config: dict,
    dry_run: bool = False,
    *,
    session_factory=None,
    analyst=None,
    reporter=None,
    price_fn=None,
    fetch_fn=None,
    now: datetime | None = None,
) -> dict:
    """Kør Loop C. Returnér summary-dict. Alle afhængigheder er injicerbare (tests)."""
    rcfg = config["reflection"]
    ni = rcfg.get("news_intelligence", {})
    if not ni.get("enabled", False):
        logger.info("news_intelligence.enabled=false — springer Loop C over.")
        return {"skipped": True}

    now = now or utc_now()
    if session_factory is None:
        init_sync_db()
        session_factory = sync_session_maker
    if analyst is None:
        analyst = ReflectionAnalyst(rcfg["anthropic_model"], store=ObservationStore())
    if reporter is None:
        reporter = TelegramReporter(config)

    min_conf = ni.get("min_confidence", 0.55)
    horizon = ni.get("horizon_hours", 24)
    sources_cfg = ni.get("sources", {})
    prom_acc = ni.get("promotion_accuracy", 0.60)
    prom_min = ni.get("promotion_min_signals", 30)

    generated: list[ShadowSignal] = []
    with session_factory() as session:
        # 1. Evaluer afventende signaler.
        evaluated = accuracy_tracker.evaluate_pending(session, price_fn=price_fn, now=now)

        # 2-3-5. Generer nye signaler (skippes i dry-run) + match mod tekniske signaler.
        if not dry_run:
            for symbol in SYMBOLS:
                sig = shadow_trader.generate_shadow_signal(
                    symbol, analyst, session,
                    min_confidence=min_conf, horizon_hours=horizon,
                    sources_cfg=sources_cfg, fetch_fn=fetch_fn, price_fn=price_fn, now=now,
                )
                if sig is not None:
                    _match_technical_signals(session, sig, now)
                    generated.append(sig)

        # 4. Promotion-alerts.
        alerts = accuracy_tracker.check_promotion_alert(session, reporter, prom_acc, prom_min)
        report = accuracy_tracker.get_accuracy_report(session)
        session.commit()

        # 6. Kort status kun hvis noget nyt skete.
        if generated or evaluated or alerts:
            reporter.send(_status_message(now, generated, evaluated, alerts, report))

    summary = {
        "evaluated": evaluated,
        "generated": len(generated),
        "alerts": alerts,
        "accuracy": report["accuracy"],
        "total_signals": report["total"],
        "dry_run": dry_run,
    }
    logger.info("Loop C færdig: %s", summary)
    return summary


def _status_message(now, generated, evaluated, alerts, report) -> str:
    lines = [f"📡 News Intelligence {now.strftime('%Y-%m-%d %H:%M')} UTC", ""]
    lines.append(f"Nye shadow signals: {len(generated)}")
    for s in generated:
        lines.append(f"• {s.symbol}: {s.predicted_direction} (conf {s.confidence:.2f})")
    lines.append(f"Evalueret: {evaluated}")
    if report["total"]:
        lines.append(f"Samlet accuracy: {report['accuracy']:.0%} af {report['total']} signaler")
    if alerts:
        lines.append(f"🚨 {alerts} nye promotion-alert(s)")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Loop C — News Intelligence")
    parser.add_argument("--dry-run", action="store_true", help="Evaluer kun, generér ingen nye signaler")
    args = parser.parse_args()

    load_dotenv()
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    run_loop_c(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
