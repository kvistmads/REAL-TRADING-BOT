"""Formatter og sender reflection-rapporter (Telegram + markdown-fil).

Synkron med vilje — reflection-loopsene er synkrone. Telegram-POST går via stdlib
urllib (ingen ekstra dep), splittes i <=4096-tegns chunks og fejler aldrig loud.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_TG_LIMIT = 4096
REPORTS_DIR = "reflection/reports"


class TelegramReporter:
    def __init__(self, config: dict):
        tg = config.get("notifications", {}).get("telegram", {})
        self.enabled: bool = tg.get("enabled", False)
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if self.enabled and (not self.token or not self.chat_id):
            logger.warning("Telegram enabled men token/chat_id mangler — deaktiverer.")
            self.enabled = False

    def send(self, text: str) -> None:
        """Send besked (chunk'et hvis > 4096 tegn). No-op hvis deaktiveret."""
        if not self.enabled:
            logger.info("Telegram deaktiveret — rapport ikke sendt (len=%d).", len(text))
            return
        for chunk in _chunk(text, _TG_LIMIT):
            self._post(chunk)

    def _post(self, text: str) -> None:
        url = _TELEGRAM_API.format(token=self.token)
        payload = json.dumps({"chat_id": self.chat_id, "text": text}).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    logger.warning("Telegram-fejl %s", resp.status)
        except Exception as e:  # netværksfejl må ikke crashe loopet
            logger.warning("Kunne ikke sende Telegram-besked: %s", e)


def _chunk(text: str, limit: int) -> list[str]:
    """Split på linjeskift så ingen chunk overstiger limit."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        # Enkelt-linje længere end limit: hard-split.
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------------------
# Nightly (Loop A) formattering
# ---------------------------------------------------------------------------

def format_nightly_telegram(
    date_str: str,
    n_trades: int,
    auto_applied: list[dict],
    pending: list[dict],
    report_only: list[dict],
    report_path: str,
) -> str:
    """Byg den ene Telegram-besked per nightly-kørsel (PRD Opgave 4)."""
    lines = [f"🔄 Nightly analyse {date_str} — {n_trades} trades analyseret", ""]

    lines.append(f"AUTO-APPLIED ({len(auto_applied)}):")
    if auto_applied:
        for a in auto_applied:
            lines.append(
                f"• {a['strategy_id'] or 'global'} › {a['parameter']}: "
                f"{a['old_value']} → {a['new_value']}"
            )
    else:
        lines.append("Ingen ændringer i dag.")
    lines.append("")

    lines.append(f"AFVENTER DIN GODKENDELSE ({len(pending)}):")
    for i, p in enumerate(pending, start=1):
        lines.append(
            f"{i}. {p['strategy_id'] or 'global'} › {p['parameter']}: "
            f"{p['current_value']} → {p['suggested_value']}"
        )
        lines.append(f"   {p.get('reasoning', '')} | conf: {p.get('confidence', 0):.2f}")
        lines.append(f"   Svar: /approve_{i} eller /reject_{i}")
    if not pending:
        lines.append("Ingen.")
    lines.append("")

    lines.append(f"RAPPORT ({len(report_only)} observationer):")
    lines.append(f"Se {report_path}")
    return "\n".join(lines)


def write_nightly_report(date_str: str, observations: list[dict], reports_dir: str = REPORTS_DIR) -> str:
    """Skriv fuld nightly-markdownrapport. Returnér stien."""
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    path = f"{reports_dir}/nightly_{date_str}.md"
    lines = [f"# Nightly analyse-rapport {date_str}", ""]
    if not observations:
        lines.append("Ingen observationer genereret.")
    for o in observations:
        lines.append(
            f"## [{o.get('type', '?')}] {o.get('strategy_id') or 'portfolio'}"
            f" › {o.get('parameter', '-')}"
        )
        lines.append(f"- Nuværende: {o.get('current_value')}  →  Foreslået: {o.get('suggested_value')}")
        lines.append(f"- Evidence: {json.dumps(o.get('evidence', {}), ensure_ascii=False)}")
        lines.append(f"- Confidence: {o.get('confidence', 0):.2f}")
        lines.append(f"- Beslutning: {o.get('_gate_action', '?')} ({o.get('_gate_reason', '')})")
        if o.get("reasoning"):
            lines.append(f"- Begrundelse: {o['reasoning']}")
        lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# Weekly (Loop B) formattering — altid rapport, aldrig auto-apply
# ---------------------------------------------------------------------------

_CATEGORY_HEADINGS = {
    "performance": "Performance",
    "architecture": "Arkitektur",
    "reliability": "Pålidelighed",
    "testing": "Testdækning",
    "consistency": "Sammenhæng",
}

_IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}


def format_weekly_markdown(date_str: str, findings: list[dict], research_section: str = "") -> str:
    """Byg weekly arkitektur-rapport (PRD Opgave 3c) + valgfrit research-afsnit (Phase 5)."""
    lines = [f"# Weekly Arkitektur-rapport {date_str}", ""]

    for cat, heading in _CATEGORY_HEADINGS.items():
        items = [f for f in findings if f.get("category") == cat]
        if not items:
            continue
        lines.append(f"## {heading}")
        for f in items:
            lines.append(
                f"- [{f.get('file', '?')}] {f.get('description', '')} "
                f"— impact: {str(f.get('impact', '')).upper()}, "
                f"effort: {f.get('effort_hours', '?')}h"
            )
            if f.get("suggested_change"):
                lines.append(f"  - Forslag: {f['suggested_change']}")
        lines.append("")

    # Prioriteret næste-skridt: sortér efter impact, dernæst mindst effort.
    ranked = sorted(
        findings,
        key=lambda f: (
            _IMPACT_RANK.get(str(f.get("impact", "")).lower(), 3),
            f.get("effort_hours", 99),
        ),
    )
    lines.append("## Foreslåede næste skridt (prioriteret)")
    if ranked:
        for i, f in enumerate(ranked[:10], start=1):
            lines.append(
                f"{i}. [{str(f.get('impact', '')).upper()}] "
                f"{f.get('file', '')}: {f.get('description', '')}"
            )
    else:
        lines.append("Ingen fund denne uge.")

    if research_section:
        lines.append("")
        lines.append("## Anbefalede A/B-eksperimenter baseret på ekstern research")
        lines.append("*Forslag fra research-laget — aldrig auto-apply.*")
        lines.append("")
        lines.append(research_section)
    return "\n".join(lines)


def write_weekly_report(
    date_str: str, findings: list[dict], reports_dir: str = REPORTS_DIR, research_section: str = ""
) -> str:
    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    path = f"{reports_dir}/weekly_{date_str}.md"
    with open(path, "w") as f:
        f.write(format_weekly_markdown(date_str, findings, research_section))
    return path
