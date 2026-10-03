"""Cron-udtryk: oversættelse til APScheduler og nightly-loopets analysevindue.

Vinduet afledes af schedule frem for at stå som et selvstændigt tal i config.
Et fast ``lookback_hours`` skulle holdes i takt med schedule i hånden. Da nightly
gik fra daglig til månedlig (2026-09-16), blev det stående på 24 timer, og
månedsanalysen så derefter kun på månedens sidste døgn.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Cron day-of-week: 0/7 = søndag. APScheduler bruger 0 = mandag → oversæt til navne.
_CRON_DOW = {"0": "sun", "7": "sun", "1": "mon", "2": "tue", "3": "wed",
             "4": "thu", "5": "fri", "6": "sat"}

# APScheduler kan ikke iterere baglæns, så vi går frem fra et punkt der med
# sikkerhed ligger mindst to perioder tilbage. 400 dage rækker til halvårlige skemaer.
_SEARCH_DAYS = 400


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


def period_start(expr: str, now: datetime) -> datetime:
    """Starten af den seneste hele periode: den næstsidste planlagte kørsel <= now.

    Kører det månedlige skema til tiden 1. november 03:00, er starten 1. oktober
    03:00, og vinduet [start, now) er hele oktober. Kommer kørslen for sent (Mac'en
    sov), flytter starten sig ikke: der opstår aldrig et hul mellem to vinduer, kun
    et overlap på forsinkelsen. ``now`` og resultatet er naiv UTC, som databasen.
    """
    from apscheduler.triggers.cron import CronTrigger  # dovent, som i main._setup_scheduler

    trigger = CronTrigger(timezone=timezone.utc, **parse_cron(expr))
    aware_now = now.replace(tzinfo=timezone.utc)
    previous = latest = None
    fire = trigger.get_next_fire_time(None, aware_now - timedelta(days=_SEARCH_DAYS))
    while fire is not None and fire <= aware_now:
        previous, latest = latest, fire
        fire = trigger.get_next_fire_time(fire, fire)
    if previous is None:
        raise ValueError(f"cron '{expr}' har ikke to kørsler inden for {_SEARCH_DAYS} dage før {now}")
    return previous.replace(tzinfo=None)
