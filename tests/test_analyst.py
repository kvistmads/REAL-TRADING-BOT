"""Tests for ReflectionAnalyst — structured outputs i stedet for JSON-udtræk af fritekst.

Baggrund: den gamle parser fejlede på to måder. Højlydt, når modellen svarede i
markdown-prosa (lag 3 bad aldrig om JSON), og tavst, når et array blev efterfulgt
af tekst: så blev kun det første objekt beholdt. Testene her låser at svaret nu
tages fra et skema-bundet svar, at ALLE elementer kommer med, og at hver loop
sender sit eget skema.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from reflection import analyst as analyst_mod
from reflection.analyst import OBSERVATION_SCHEMA, ReflectionAnalyst
from reflection.news.shadow_trader import NEWS_PREDICTION_SCHEMA
from reflection.weekly import ARCH_FINDING_SCHEMA


def _message(payload=None, *, stop_reason="end_turn", thinking=False, text=None):
    blocks = []
    if thinking:
        blocks.append(SimpleNamespace(type="thinking", thinking="", signature="sig"))
    if text is None:
        text = json.dumps(payload)
    blocks.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class _FakeClient:
    """Optager kwargs fra messages.create og returnerer et fast svar (eller kaster)."""

    def __init__(self, response=None, error=None):
        self.calls = []
        self._response = response
        self._error = error
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _obs(**over):
    base = {
        "strategy_id": "trend_momentum", "type": "parameter_suggestion",
        "parameter": "adx_min", "current_value": 20, "suggested_value": 22,
        "evidence": {"win_above": 0.6, "win_below": 0.4, "n": 40, "threshold": 22},
        "confidence": 0.7, "reasoning": "ADX over 22 skiller vindere fra tabere.",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Kaldet
# ---------------------------------------------------------------------------

def test_request_binds_response_to_schema():
    client = _FakeClient(_message({"results": []}))
    ReflectionAnalyst("claude-opus-5-5", client=client).analyse("prompt")

    fmt = client.calls[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["properties"]["results"]["items"] is OBSERVATION_SCHEMA


def test_request_sends_no_effort_or_thinking():
    # Samme analyst kører både Opus (nightly) og Haiku (news); Haiku 4.5 afviser effort.
    client = _FakeClient(_message({"results": []}))
    ReflectionAnalyst("claude-haiku-4-5", client=client, schema=NEWS_PREDICTION_SCHEMA).analyse("p")
    call = client.calls[0]
    assert "thinking" not in call
    assert "effort" not in call["output_config"]


# ---------------------------------------------------------------------------
# Svaret
# ---------------------------------------------------------------------------

def test_every_result_is_returned_not_only_the_first():
    # Regression: den gamle brace-udtrækker beholdt kun første objekt i et array.
    two = [_obs(), _obs(parameter="atr_period", current_value=14, suggested_value=10)]
    client = _FakeClient(_message({"results": two}))
    assert ReflectionAnalyst("m", client=client).analyse("p") == two


def test_empty_result_list_is_a_valid_answer():
    client = _FakeClient(_message({"results": []}))
    assert ReflectionAnalyst("m", client=client).analyse("p") == []


def test_thinking_block_before_text_is_skipped():
    # Opus 5.5 har altid thinking på: content[0] er en thinking-blok, ikke svaret.
    client = _FakeClient(_message({"results": [_obs()]}, thinking=True))
    assert ReflectionAnalyst("claude-opus-5-5", client=client).analyse("p") == [_obs()]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_incomplete_response_gives_empty_list(stop_reason, caplog):
    client = _FakeClient(_message(text='{"results": [{"strateg', stop_reason=stop_reason))
    assert ReflectionAnalyst("m", client=client).analyse("p") == []
    assert stop_reason in caplog.text


def test_api_error_is_logged_not_raised(caplog):
    client = _FakeClient(error=RuntimeError("credit balance is too low"))
    assert ReflectionAnalyst("m", client=client).analyse("p") == []
    assert "credit balance is too low" in caplog.text


def test_offline_without_key_never_calls_api(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = ReflectionAnalyst("m")
    assert a.offline is True
    assert a.analyse("p") == []


# ---------------------------------------------------------------------------
# Skemaerne overholder structured outputs' regler
# ---------------------------------------------------------------------------

_UNSUPPORTED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                "multipleOf", "minLength", "maxLength", "minItems", "maxItems"}


def _walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


@pytest.mark.parametrize(
    "schema",
    [OBSERVATION_SCHEMA, NEWS_PREDICTION_SCHEMA, ARCH_FINDING_SCHEMA,
     analyst_mod._response_schema(OBSERVATION_SCHEMA)],
    ids=["observation", "news", "arch", "wrapper"],
)
def test_schema_is_valid_for_structured_outputs(schema):
    for path, node in _walk(schema):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, f"{path}: additionalProperties skal være False"
            assert set(node.get("required", [])) == set(node["properties"]), f"{path}: alle felter skal være required"
        bad = _UNSUPPORTED & set(node)
        assert not bad, f"{path}: ikke understøttet af structured outputs: {bad}"


# ---------------------------------------------------------------------------
# Hver loop sender sit eget skema
# ---------------------------------------------------------------------------

class _Captured(Exception):
    pass


def _capture_ctor(store):
    def ctor(*args, **kwargs):
        store.update(kwargs, model=args[0] if args else kwargs.get("model"))
        raise _Captured
    return ctor


def test_loop_c_gives_its_analyst_the_news_schema(monkeypatch):
    from reflection import loop_c

    seen = {}
    monkeypatch.setattr(loop_c, "ReflectionAnalyst", _capture_ctor(seen))
    monkeypatch.setattr(loop_c, "ObservationStore", lambda: None)
    config = {"reflection": {"anthropic_model": "claude-opus-5-5",
                             "news_intelligence": {"enabled": True, "model": "claude-haiku-4-5"}}}
    with pytest.raises(_Captured):
        loop_c.run_loop_c(config, session_factory=object())
    assert seen["schema"] is NEWS_PREDICTION_SCHEMA
    assert seen["model"] == "claude-haiku-4-5"


def test_weekly_gives_its_analyst_the_arch_schema(monkeypatch):
    from reflection import weekly

    seen = {}
    monkeypatch.setattr(weekly, "ReflectionAnalyst", _capture_ctor(seen))
    monkeypatch.setattr(weekly, "collect_codebase_snapshot", lambda *a, **k: {"files": []})
    config = {"reflection": {"enabled": True, "anthropic_model": "claude-opus-5-5", "weekly": {}}}
    with pytest.raises(_Captured):
        weekly.run_weekly(config, dry_run=True)
    assert seen["schema"] is ARCH_FINDING_SCHEMA
