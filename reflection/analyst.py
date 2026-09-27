"""Anthropic-klient: bygger prompts, kalder LLM, parser JSON-svar til observationer.

Robusthed:
- Uden ANTHROPIC_API_KEY kører analysten *offline*: den kalder ikke API'et og
  returnerer [] (tom liste). Så kan nightly/weekly --dry-run køre uden nøgle/uden fejl.
- LLM'en instrueres til at svare med et rent JSON-array. Vi stripper markdown-fences
  og tåler at svaret pakkes i et objekt eller er tomt.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _extract_first_json(text: str) -> str | None:
    """Udtræk det første komplette JSON-objekt ({}) eller array ([]) fra en streng.

    Bruges når modellen returnerer ekstra tekst efter det afsluttende }  — fx en
    forklaring på dansk eller endnu et ``` -afsnit. Brace-tælling er mere robust
    end regex fordi den håndterer nestede strukturer.
    """
    for start_char, end_char in (("{", "}"), ("[", "]")):
        idx = text.find(start_char)
        if idx == -1:
            continue
        depth = 0
        in_string = False
        escape = False
        for i, ch in enumerate(text[idx:], start=idx):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return text[idx : i + 1]
    return None


class ReflectionAnalyst:
    def __init__(self, model: str, store=None, client=None):
        """
        model: fx "claude-opus-4-8".
        store: valgfri ObservationStore til at berige prompten med historik.
        client: injicér en færdig anthropic-klient (bruges i tests). Hvis None
                oprettes en rigtig klient — men kun hvis ANTHROPIC_API_KEY findes.
        """
        self.model = model
        self.store = store
        self.client = client
        self.offline = False

        if self.client is None:
            if not os.getenv("ANTHROPIC_API_KEY"):
                logger.warning(
                    "ANTHROPIC_API_KEY mangler — ReflectionAnalyst kører offline "
                    "(0 observationer genereres)."
                )
                self.offline = True
            else:
                import anthropic

                self.client = anthropic.Anthropic()

    def analyse(self, prompt: str, context_text: str = "") -> list[dict]:
        """Kald LLM med prompt + evt. historik-kontekst. Returnér liste af observationer.

        Kaster aldrig videre: fejl (netværk, parse) logges og giver [].
        """
        if self.offline or self.client is None:
            return []

        history_block = ""
        if self.store is not None and context_text:
            try:
                similar = self.store.query_similar(context_text, n=5)
                history_block = self._format_history(similar)
            except Exception as e:  # historik er best-effort
                logger.warning("Kunne ikke hente ChromaDB-historik: %s", e)

        content = prompt if not history_block else f"{prompt}\n\n{history_block}"

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": content}],
            )
            raw = message.content[0].text.strip()
        except Exception as e:
            logger.error("Anthropic-kald fejlede: %s", e)
            return []

        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> list[dict]:
        """Parse LLM-output til en liste af dicts. Tolerant over for fences/wrapping."""
        if not raw:
            return []
        text = raw.strip()
        # Strip markdown code-fences (```json ... ```).
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # drop åbnings-fence (evt. ```json)
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            # "Extra data" = modellen returnerede tekst efter JSON-objektet.
            # Prøv at udtrække det første komplette objekt/array via simpel
            # brace-tælling frem for regex (håndterer nested strukturer korrekt).
            extracted = _extract_first_json(text)
            if extracted is not None:
                try:
                    data = json.loads(extracted)
                except json.JSONDecodeError:
                    pass
                else:
                    # Gennemfør parsing med det udtrukne fragment.
                    if isinstance(data, dict):
                        if "observations" in data and isinstance(data["observations"], list):
                            return data["observations"]
                        return [data]
                    if isinstance(data, list):
                        return data
                    return []
            logger.error("Kunne ikke parse LLM-JSON: %s | raw=%.300s", e, raw)
            return []
        if isinstance(data, dict):
            # Tillad {"observations": [...]} eller en enkelt observation.
            if "observations" in data and isinstance(data["observations"], list):
                return data["observations"]
            return [data]
        if isinstance(data, list):
            return data
        return []

    @staticmethod
    def _format_history(similar: list[dict]) -> str:
        if not similar:
            return ""
        lines = ["## Relevante tidligere observationer (fra ChromaDB):"]
        for s in similar:
            meta_type = (s.get("metadata") or {}).get("type", "")
            lines.append(f"- [{meta_type}] {s.get('text', '')}")
        return "\n".join(lines)
