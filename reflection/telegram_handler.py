"""Håndterer /approve_N og /reject_N fra Telegram.

Der er (endnu) ingen web-server i projektet, så i stedet for en webhook bruger vi
long-polling mod getUpdates. Kernen — ``handle_command`` — er dog ren og testbar
uafhængigt af netværk.

N-mapping: N refererer til den N'te observation der afventer brugerens svar,
ordnet efter created_at faldende (nyeste nightly-kørsel først). Det matcher
nummereringen i den seneste nightly-rapport, som brugeren normalt svarer på kort efter.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request

from sqlalchemy import select

from core.database import Observation
from reflection.applier import ParameterApplier

logger = logging.getLogger(__name__)

_CMD_RE = re.compile(r"^/(approve|reject)_(\d+)\b")
_TELEGRAM_BASE = "https://api.telegram.org/bot{token}/{method}"


def pending_observations(session) -> list[Observation]:
    """Observationer der afventer brugerens godkendelse (nyeste først)."""
    return list(
        session.execute(
            select(Observation)
            .where(
                Observation.approved_by_user.is_(None),
                Observation.auto_applied.is_(False),
                Observation.observation_type == "parameter_suggestion",
                Observation.parameter.is_not(None),
            )
            .order_by(Observation.created_at.desc(), Observation.id.desc())
        )
        .scalars()
        .all()
    )


def handle_command(command_text: str, session, applier: ParameterApplier | None = None,
                   notify=None, cfg_path: str = "config.yaml") -> str:
    """Parse og udfør en /approve_N | /reject_N kommando. Returnér svartekst.

    Committer selv DB-ændringen (approved_by_user, evt. auto_applied via applier).
    """
    m = _CMD_RE.match(command_text.strip())
    if not m:
        return ""  # ikke en kommando vi håndterer

    action, num = m.group(1), int(m.group(2))
    pending = pending_observations(session)
    if num < 1 or num > len(pending):
        return f"Ingen ventende observation #{num} (der er {len(pending)})."

    obs = pending[num - 1]

    if action == "reject":
        obs.approved_by_user = False
        session.commit()
        logger.info("Observation %s afvist af bruger (#%d).", obs.id, num)
        return f"❌ Afvist: {obs.strategy_id or 'global'} › {obs.parameter}"

    # approve
    obs.approved_by_user = True
    applier = applier or ParameterApplier()
    record = applier.apply(obs, cfg_path=cfg_path, notify=notify)
    session.commit()
    logger.info("Observation %s godkendt + applied af bruger (#%d).", obs.id, num)
    return (
        f"✅ Godkendt & anvendt: {obs.strategy_id or 'global'} › {obs.parameter}: "
        f"{record['old_value']} → {record['new_value']}"
    )


# ---------------------------------------------------------------------------
# Long-polling loop (valgfri — kaldes fra en baggrundstask, ikke fra tests)
# ---------------------------------------------------------------------------

def _api(method: str, params: dict) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = _TELEGRAM_BASE.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(url, data=data, timeout=40) as resp:
        return json.loads(resp.read().decode())


def poll_once(session, offset: int | None = None, applier: ParameterApplier | None = None,
              reply=None) -> int | None:
    """Hent nye Telegram-updates og håndter kommandoer. Returnér næste offset.

    reply: valgfri callable(str) til at sende svar tilbage til brugeren.
    """
    params = {"timeout": 30}
    if offset is not None:
        params["offset"] = offset
    try:
        result = _api("getUpdates", params)
    except Exception as e:
        logger.warning("getUpdates fejlede: %s", e)
        return offset

    next_offset = offset
    for upd in result.get("result", []):
        next_offset = upd["update_id"] + 1
        text = (upd.get("message") or {}).get("text", "")
        if not text:
            continue
        answer = handle_command(text, session, applier=applier)
        if answer and reply is not None:
            reply(answer)
    return next_offset
