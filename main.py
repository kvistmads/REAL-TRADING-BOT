import asyncio
import logging
import signal

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


def _request_shutdown(task: "asyncio.Future", sig: int) -> None:
    """Aflys engine-tasken, så main()'s finally-blok kan køre engine.stop()."""
    try:
        name = signal.Signals(sig).name
    except ValueError:  # pragma: no cover - ukendt signalnummer
        name = str(sig)
    logger.info("Modtog %s — lukker ned...", name)
    if not task.done():
        task.cancel()


def _install_signal_handlers(task: "asyncio.Future") -> None:
    """Luk pænt ned på SIGTERM/SIGINT.

    SIGTERM er det signal cron/LaunchAgent (og `kill`) bruger til at stoppe botten.
    Uden en handler dør processen på stedet: ccxt-sessionen lukkes aldrig, og de to
    engine-loops afbrydes midt i en runde.

    Startes processen fra en non-interaktiv shell kan SIGTERM være ARVET som
    SIG_IGN — så ignoreres signalet uanset hvor pænt vi ellers rydder op. At
    installere en handler her overskriver den arv, hvilket er hele pointen med
    at gøre det eksplicit frem for at stole på default-dispositionen.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown, task, sig)
        except (NotImplementedError, RuntimeError, AttributeError):
            # Windows-event-loops har ingen add_signal_handler — fald tilbage på
            # signal.signal og hop tilbage i loop-tråden derfra.
            def _fallback(signum, frame, _task=task, _loop=loop):
                _loop.call_soon_threadsafe(_request_shutdown, _task, signum)

            try:
                signal.signal(sig, _fallback)
            except (OSError, ValueError) as e:  # pragma: no cover - platformafhængigt
                logger.warning("Kunne ikke installere handler for %s: %s", sig, e)


async def main() -> None:
    load_dotenv()
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    scheduler = _setup_scheduler(config)

    engine = TradingEngine(config)
    # Engine'en kører som sin EGEN task, så signal-handleren kan aflyse præcis den.
    # Aflyses main() i stedet, bliver finally-blokken selv afbrudt midt i oprydningen.
    engine_task = asyncio.ensure_future(engine.start())
    _install_signal_handlers(engine_task)
    try:
        await engine_task
    except asyncio.CancelledError:
        logger.info("Engine-loopet aflyst — kører nedlukning.")
    finally:
        # Ctrl-C/SIGTERM aflyser engine-tasken; uden stop() lukkes ccxt-sessionen aldrig.
        await engine.stop()
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        logger.info("Nedlukning færdig.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
