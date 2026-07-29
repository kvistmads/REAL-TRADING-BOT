"""status_writer — skriver bot-tilstand til bot_status.json for dashboardet (Phase 5 Del B).

Dashboardet (dashboard.html) poller denne JSON-fil. Skrivningen er atomisk (temp-fil +
os.replace) så dashboardet aldrig læser en halvskreven fil, og best-effort: en fejl her
må aldrig vælte engine-loopet (kalderen wrapper i try/except).

Funktionen er bevidst løs i sit skema — den tager de sektioner engine'en har og dumper
dem. Ukendte/manglende sektioner bliver til tomme objekter, så dashboardet altid har
noget at rendere.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_PATH = "bot_status.json"


def write_status(
    *,
    mode: str,
    status: str,
    portfolio: dict | None = None,
    positions: list | None = None,
    recent_trades: list | None = None,
    regime: dict | None = None,
    gates: dict | None = None,
    strategies: dict | None = None,
    reflection: dict | None = None,
    path: str = DEFAULT_PATH,
) -> dict:
    """Skriv den samlede status til ``path`` som JSON. Returnér payload'et (til test/log)."""
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "status": status,
        "portfolio": portfolio or {},
        "positions": positions or [],
        "recent_trades": recent_trades or [],
        "regime": regime or {},
        "gates": gates or {},
        "strategies": strategies or {},
        "reflection": reflection or {},
    }
    _atomic_write_json(path, payload)
    return payload


def _atomic_write_json(path: str, data: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, default=str, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
