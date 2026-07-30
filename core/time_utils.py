"""Ét sted til "nu" i UTC.

``datetime.utcnow()`` er deprecated fra Python 3.12 og fjernes i en senere version,
men den returnerer et NAIVT datetime. Kodebasen gemmer naive UTC-tidsstempler i
SQLite (``DateTime`` uden timezone) og sammenligner dem indbyrdes — fx cutoffs i
``reflection/extractor.py`` og shadow-signal-evalueringen i ``reflection/news/``.

Derfor beholder vi naiv UTC frem for at skifte til aware datetimes: aware-værdier
kan ikke sammenlignes med de naive rækker der allerede ligger i databasen
(``TypeError: can't compare offset-naive and offset-aware datetimes``), og et skift
ville kræve en migrering af eksisterende data.

``reflection/news/fetcher.py`` bruger bevidst aware UTC — den sammenligner kun med
publiceringstider fra eksterne API'er og rører ikke databasen.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Nuværende UTC-tid som naivt datetime — drop-in erstatning for ``datetime.utcnow()``."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
