"""Tests for core/schedule.py — cron-oversættelse og nightly-loopets analysevindue."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
import yaml

from core.schedule import parse_cron, period_start

MONTHLY = "0 3 1 * *"


@pytest.mark.parametrize(
    "now, expected",
    [
        # Kørslen til tiden: vinduet er hele den foregående måned.
        (datetime(2026, 11, 1, 3, 0, 0, 500), datetime(2026, 10, 1, 3, 0)),
        # Forsinket (Mac'en sov): starten flytter sig IKKE → intet hul i dækningen.
        (datetime(2026, 11, 1, 9, 0), datetime(2026, 10, 1, 3, 0)),
        (datetime(2026, 11, 3, 8, 0), datetime(2026, 10, 1, 3, 0)),
        # Februar er 28 dage — et fast 744-timers vindue ville tage 3 januar-dage med.
        (datetime(2026, 3, 1, 3, 0, 1), datetime(2026, 2, 1, 3, 0)),
        # Manuel kørsel midt i måneden: seneste hele periode + den løbende.
        (datetime(2026, 10, 15, 12, 0), datetime(2026, 9, 1, 3, 0)),
    ],
    ids=["til_tiden", "6t_forsinket", "2d_forsinket", "februar", "manuel"],
)
def test_monthly_period_start(now, expected):
    assert period_start(MONTHLY, now) == expected


def test_daily_period_start_is_previous_fire():
    assert period_start("0 6 * * *", datetime(2026, 10, 3, 6, 0, 1)) == datetime(2026, 10, 2, 6, 0)


def test_cron_sunday_is_translated_for_apscheduler():
    # Cron 0 = søndag, APScheduler 0 = mandag. Onsdag 7/10 → forrige søndag-kørsel er 27/9.
    assert parse_cron("0 3 * * 0")["day_of_week"] == "sun"
    assert period_start("0 3 * * 0", datetime(2026, 10, 7, 12, 0)) == datetime(2026, 9, 27, 3, 0)


def test_period_start_returns_naive_utc():
    # Databasen gemmer naive UTC-tidsstempler; et aware resultat kan ikke sammenlignes med dem.
    assert period_start(MONTHLY, datetime(2026, 11, 1, 3, 1)).tzinfo is None


def test_nightly_job_runs_late_instead_of_being_skipped():
    """APScheduler-default er 1 sekunds grace: sov Mac'en kl. 03:00 UTC den 1., blev hele
    månedsanalysen sprunget over. Loggen viser fem skippede news-kørsler af samme grund."""
    import main

    config = yaml.safe_load(open("config.yaml"))

    async def nightly_grace():
        scheduler = main._setup_scheduler(config)
        try:
            return scheduler.get_job("nightly").misfire_grace_time
        finally:
            scheduler.shutdown(wait=False)

    assert asyncio.run(nightly_grace()) is None
