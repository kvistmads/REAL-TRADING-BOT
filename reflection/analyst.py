"""Anthropic-klient: kalder LLM'en og returnerer svaret som en liste af dicts.

Robusthed:
- Uden ANTHROPIC_API_KEY kører analysten *offline*: den kalder ikke API'et og
  returnerer [] (tom liste). Så kan nightly/weekly --dry-run køre uden nøgle/uden fejl.
- Svaret er låst til et JSON-skema via structured outputs (``output_config.format``):
  API'et garanterer gyldig JSON der matcher skemaet. Før forsøgte vi at liste JSON ud
  af fritekst. Det fejlede enten højlydt (modellen svarede i markdown-prosa) eller
  tavst (efter et array med efterfølgende tekst blev kun det første objekt beholdt).
- Hver instans har ét skema, fordi hver kalder beder om én slags svar: nightly om
  observationer (default), Loop C om en nyhedsforudsigelse, weekly om arkitekturfund.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# Structured outputs kræver additionalProperties: false på alle objekter og
# understøtter ikke minimum/maximum — intervaller (fx confidence 0-1) står i prompten.
_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_NUMBER = {"anyOf": [{"type": "number"}, {"type": "null"}]}
_PARAM_VALUE = {
    "anyOf": [{"type": "number"}, {"type": "string"}, {"type": "boolean"}, {"type": "null"}]
}

OBSERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy_id": _NULLABLE_STRING,  # null for portefølje-observationer (lag 3)
        "type": {
            "type": "string",
            "enum": [
                "parameter_suggestion",
                "regime_correlation",
                "temporal_drift",
                "symbol_filter",
                "observation",
                "portfolio_pattern",
                "correlation_warning",
                "diversification_gap",
            ],
        },
        "parameter": _NULLABLE_STRING,
        "current_value": _PARAM_VALUE,
        "suggested_value": _PARAM_VALUE,
        "evidence": {
            "type": "object",
            "properties": {
                "win_above": _NULLABLE_NUMBER,
                "win_below": _NULLABLE_NUMBER,
                "n": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "threshold": _NULLABLE_NUMBER,
            },
            "required": ["win_above", "win_below", "n", "threshold"],
            "additionalProperties": False,
        },
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": [
        "strategy_id", "type", "parameter", "current_value", "suggested_value",
        "evidence", "confidence", "reasoning",
    ],
    "additionalProperties": False,
}


def _response_schema(item_schema: dict) -> dict:
    """Pak item-skemaet i et objekt med en liste — en tom liste er et gyldigt svar."""
    return {
        "type": "object",
        "properties": {"results": {"type": "array", "items": item_schema}},
        "required": ["results"],
        "additionalProperties": False,
    }


class ReflectionAnalyst:
    def __init__(self, model: str, store=None, client=None, schema: dict = OBSERVATION_SCHEMA):
        """
        model: fx "claude-opus-5-5".
        store: valgfri ObservationStore til at berige prompten med historik.
        client: injicér en færdig anthropic-klient (bruges i tests). Hvis None
                oprettes en rigtig klient — men kun hvis ANTHROPIC_API_KEY findes.
        schema: JSON-skema for ÉT element i svaret. Default er nightly-observationer.
        """
        self.model = model
        self.store = store
        self.client = client
        self.schema = schema
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
        """Kald LLM med prompt + evt. historik-kontekst. Returnér listen af resultater.

        Kaster aldrig videre: fejl (netværk, API, afkortet svar) logges og giver [].
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
                # Thinking-tokens tæller med i max_tokens på modeller hvor thinking
                # altid er slået til (Opus 5.5). 4096 kunne afkorte selve svaret.
                max_tokens=16000,
                messages=[{"role": "user", "content": content}],
                output_config={
                    "format": {"type": "json_schema", "schema": _response_schema(self.schema)}
                },
            )
        except Exception as e:
            logger.error("Anthropic-kald fejlede: %s", e)
            return []

        return self._results(message)

    @staticmethod
    def _results(message) -> list[dict]:
        # Ved refusal eller max_tokens matcher svaret ikke nødvendigvis skemaet.
        if message.stop_reason in ("refusal", "max_tokens"):
            logger.error("LLM-svar ufuldstændigt (stop_reason=%s) — ingen resultater.", message.stop_reason)
            return []
        # Modeller med thinking lægger en thinking-blok FØR tekst-blokken,
        # så content[0] er ikke nødvendigvis svaret.
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            return json.loads(text)["results"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Uventet LLM-svar trods skema: %s | raw=%.300s", e, text)
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
