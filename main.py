import asyncio
import logging

import yaml
from dotenv import load_dotenv

from core.engine import TradingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

# Cron day-of-week: 0/7 = søndag. APScheduler bruger 0 = mandag → oversæt til navne.
_CRON_DOW = {"0": "sun", "7": "sun", "1": "mon", "2": "tue", "3": "wed",
             "4": "thu", "5": "fri", "6": "sat"}


def parse_cron(expr: str) -> dict:
    """'m h dom mon dow' (standard cron) → kwargs til APScheduler CronTrigger."""
    minute, hour, dom, month, dow = expr.split()
    return {
        "minute": minute,
        "hour": hour,
        "day": dom,
        "month": month,
        "day_of_week": _CRON_DOW.get(dow, dow),
    }


async def _run_reflection(entry, config: dict, label: str) -> None:
    """Kør en (synkron) reflection-loop i en tråd, så event-loopet ikke blokeres."""
    try:
        await asyncio.to_thread(entry, config)
    except Exception as e:
        logger.error("%s-loop fejlede: %s", label, e, exc_info=True)


def _setup_scheduler(config: dict):
    reflection = config.get("reflection", {})
    if not reflection.get("enabled", False):
        logger.info("reflection deaktiveret — ingen scheduler startet.")
        return None

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from reflection.nightly import run_nightly
    from reflection.weekly import run_weekly

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_reflection, "cron", args=[run_nightly, config, "nightly"],
        id="nightly", **parse_cron(reflection["nightly"]["schedule"]),
    )
    scheduler.add_job(
        _run_reflection, "cron", args=[run_weekly, config, "weekly"],
        id="weekly", **parse_cron(reflection["weekly"]["schedule"]),
    )

    news = reflection.get("news_intelligence", {})
    if news.get("enabled", False):
        from reflection.loop_c import run_loop_c

        scheduler.add_job(
            _run_reflection, "cron", args=[run_loop_c, config, "news"],
            id="news", **parse_cron(news["schedule"]),
        )

    scheduler.start()
    logger.info(
        "Reflection-scheduler startet: nightly='%s', weekly='%s', news='%s' (UTC).",
        reflection["nightly"]["schedule"], reflection["weekly"]["schedule"],
        news.get("schedule", "off") if news.get("enabled") else "off",
    )
    return scheduler


async def main() -> None:
    load_dotenv()
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    scheduler = _setup_scheduler(config)

    engine = TradingEngine(config)
    try:
        await engine.start()
    finally:
        # Ctrl-C aflyser main-tasken; uden stop() lukkes ccxt-sessionen aldrig.
        await engine.stop()
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        logger.info("Nedlukning færdig.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
