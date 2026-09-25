"""Tests for the Claude request construction and provider routing (no network).

Requests go through the real Anthropic SDK with a mock HTTP transport, so these
tests check the JSON body and headers the API would receive.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from unjiggle import llm
from unjiggle.analyzer import ANALYSIS_TOOL, analyze, plan_intent_operations
from unjiggle.mirror import MIRROR_TOOL, generate_mirror
from unjiggle.obituary import OBITUARY_TOOL, generate_obituaries
from unjiggle.scoring import compute_score

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

ANTHROPIC_KEY = "sk-ant-api03-test"
OPENAI_KEY = "sk-proj-test"

ANALYSIS_REPLY = {
    "observations": [{
        "track": "cleanup",
        "title": "Weather overload",
        "narrative": "Three weather apps.",
        "operations": [{"action": "move_to_app_library", "bundle_ids": ["com.apple.weather"]}],
    }],
    "personality": "Organized chaos.",
    "archetype": "The Collector",
}
MIRROR_REPLY = {
    "roast": "You have apps.",
    "phases": [{"name": "The Streaming Phase", "apps": ["Netflix"], "narrative": "Binge."}],
    "contradictions": [],
    "guilty_pleasure": "Netflix.",
    "one_line": "A phone.",
}


def _message(content, stop_reason="end_turn", stop_details=None):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": llm.DEFAULT_ANTHROPIC_MODEL,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def _json_reply(data):
    # Claude Opus 5.5 thinks on every request; under the default display the
    # thinking block comes back first, with empty text.
    return _message([
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": json.dumps(data)},
    ])


class FakeClaude:
    """Records every request the SDK sends and answers with ``reply``."""

    def __init__(self, reply):
        self.reply = reply
        self.requests = []
        self.api_keys = []

    def handle(self, request):
        self.requests.append(SimpleNamespace(
            url=str(request.url),
            headers=request.headers,
            body=json.loads(request.content),
        ))
        return httpx2.Response(200, json=self.reply)

    def client(self, api_key):
        self.api_keys.append(api_key)
        return anthropic.Anthropic(
            api_key=api_key,
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self.handle)),
        )

    @property
    def last(self):
        return self.requests[-1]


@pytest.fixture
def fake_claude(monkeypatch):
    fake = FakeClaude(_json_reply(ANALYSIS_REPLY))
    monkeypatch.setattr(llm, "_anthropic_client", fake.client)
    return fake


@pytest.fixture(autouse=True)
def _no_provider_env(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def no_screen_time(monkeypatch):
    from unjiggle import screentime

    monkeypatch.setattr(screentime, "get_usage", lambda *args, **kwargs: {})


def _dead_app_layout():
    from unjiggle.models import AppItem, HomeScreenLayout, LayoutItem

    buried = [LayoutItem(app=AppItem(bundle_id=f"com.example.dead{i}")) for i in range(3)]
    layout = HomeScreenLayout(dock=[], pages=[[], [], [], [], [], buried])
    metadata = {
        f"com.example.dead{i}": {
            "name": f"Dead{i}",
            "super_category": "Education",
            "last_updated": "2019-01-01T00:00:00Z",
            "description": "Learn a language",
        }
        for i in range(3)
    }
    return layout, metadata


def _assert_opus_request(request, schema, effort):
    body = request.body
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] >= 16000
    # Opus 5.5 rejects forced tool use; the JSON comes from structured outputs.
    assert "tools" not in body
    assert "tool_choice" not in body
    # Thinking is always on and cannot be disabled; effort is the control.
    assert "thinking" not in body
    assert body["output_config"] == {
        "effort": effort,
        "format": {"type": "json_schema", "schema": schema},
    }
    assert body["fallbacks"] == "default"
    assert llm.FALLBACK_BETA in request.headers["anthropic-beta"]
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"


# --- request construction, one test per call site ---------------------------------


def test_analysis_request_targets_opus_5_5_with_structured_output(
    fake_claude, chaotic_layout, sample_metadata,
):
    score = compute_score(chaotic_layout, sample_metadata)
    result = analyze(chaotic_layout, sample_metadata, score, api_key=ANTHROPIC_KEY)

    _assert_opus_request(fake_claude.last, ANALYSIS_TOOL["input_schema"], "medium")
    assert fake_claude.api_keys == [ANTHROPIC_KEY]
    assert result.archetype == "The Collector"
    assert result.observations[0].operations[0].bundle_ids == ["com.apple.weather"]


def test_intent_request_targets_opus_5_5_with_structured_output(
    fake_claude, chaotic_layout, sample_metadata,
):
    fake_claude.reply = _json_reply(ANALYSIS_REPLY)
    score = compute_score(chaotic_layout, sample_metadata)
    ops = plan_intent_operations(
        "calm and minimal", chaotic_layout, sample_metadata, score, api_key=ANTHROPIC_KEY,
    )

    request = fake_claude.last
    _assert_opus_request(request, ANALYSIS_TOOL["input_schema"], "medium")
    assert "calm and minimal" in request.body["messages"][0]["content"]
    assert [op.action for op in ops] == ["move_to_app_library"]


def test_mirror_request_targets_opus_5_5_at_low_effort(
    fake_claude, chaotic_layout, sample_metadata,
):
    fake_claude.reply = _json_reply(MIRROR_REPLY)
    score = compute_score(chaotic_layout, sample_metadata)
    result = generate_mirror(chaotic_layout, sample_metadata, score, api_key=ANTHROPIC_KEY)

    _assert_opus_request(fake_claude.last, MIRROR_TOOL["input_schema"], "low")
    assert result.one_line == "A phone."


def test_obituary_request_targets_opus_5_5_at_low_effort(fake_claude, no_screen_time):
    layout, metadata = _dead_app_layout()
    fake_claude.reply = _json_reply({
        "obituaries": [{
            "bundle_id": "com.example.dead0",
            "cause_of_death": "Google Translate.",
            "eulogy": "It tried.",
        }],
        "graveyard_summary": "Three languages, zero fluency.",
    })
    result = generate_obituaries(layout, metadata, api_key=ANTHROPIC_KEY)

    _assert_opus_request(fake_claude.last, OBITUARY_TOOL["input_schema"], "low")
    assert [o.bundle_id for o in result.obituaries] == ["com.example.dead0"]
    assert result.obituaries[0].app_name == "Dead0"


def test_model_override_passes_through(fake_claude, chaotic_layout, sample_metadata):
    score = compute_score(chaotic_layout, sample_metadata)
    analyze(chaotic_layout, sample_metadata, score, api_key=ANTHROPIC_KEY, model="claude-opus-5")

    assert fake_claude.last.body["model"] == "claude-opus-5"
    assert fake_claude.last.body["fallbacks"] == "default"


def test_model_without_effort_or_fallbacks_gets_a_plain_request(
    fake_claude, chaotic_layout, sample_metadata,
):
    score = compute_score(chaotic_layout, sample_metadata)
    analyze(chaotic_layout, sample_metadata, score, api_key=ANTHROPIC_KEY, model="claude-haiku-4-5")

    request = fake_claude.last
    assert request.body["model"] == "claude-haiku-4-5"
    assert "effort" not in request.body["output_config"]
    assert "fallbacks" not in request.body
    assert "anthropic-beta" not in request.headers
    assert "tool_choice" not in request.body


def test_schemas_are_valid_for_structured_outputs():
    """Structured outputs require additionalProperties: false on every object."""

    def walk(node, path):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, path
                assert set(node.get("required", [])) <= set(node.get("properties", {})), path
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    for tool in (ANALYSIS_TOOL, MIRROR_TOOL, OBITUARY_TOOL):
        walk(tool["input_schema"], tool["name"])


# --- response handling ---------------------------------------------------------------


def _mirror(fake_claude, chaotic_layout, sample_metadata):
    score = compute_score(chaotic_layout, sample_metadata)
    return generate_mirror(chaotic_layout, sample_metadata, score, api_key=ANTHROPIC_KEY)


def test_refusal_raises_with_category(fake_claude, chaotic_layout, sample_metadata):
    fake_claude.reply = _message(
        [], stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": None},
    )
    with pytest.raises(llm.LLMRefusalError) as excinfo:
        _mirror(fake_claude, chaotic_layout, sample_metadata)
    assert excinfo.value.category == "cyber"


def test_refusal_without_details_still_raises(fake_claude, chaotic_layout, sample_metadata):
    fake_claude.reply = _message([], stop_reason="refusal")
    with pytest.raises(llm.LLMRefusalError) as excinfo:
        _mirror(fake_claude, chaotic_layout, sample_metadata)
    assert excinfo.value.category is None


def test_truncated_reply_is_not_parsed(fake_claude, chaotic_layout, sample_metadata):
    fake_claude.reply = _message(
        [{"type": "text", "text": '{"roast": "You have'}], stop_reason="max_tokens",
    )
    with pytest.raises(llm.LLMTruncatedError):
        _mirror(fake_claude, chaotic_layout, sample_metadata)


def test_reply_without_text_block_raises(fake_claude, chaotic_layout, sample_metadata):
    fake_claude.reply = _message([{"type": "thinking", "thinking": "", "signature": "sig"}])
    with pytest.raises(llm.LLMOutputError):
        _mirror(fake_claude, chaotic_layout, sample_metadata)


def test_malformed_json_raises(fake_claude, chaotic_layout, sample_metadata):
    fake_claude.reply = _message([{"type": "text", "text": "Here is your roast!"}])
    with pytest.raises(llm.LLMOutputError):
        _mirror(fake_claude, chaotic_layout, sample_metadata)


def test_reply_after_a_fallback_is_read_by_block_type(fake_claude, chaotic_layout, sample_metadata):
    fake_claude.reply = _message([
        {
            "type": "fallback",
            "from": {"model": "claude-opus-5-5"},
            "to": {"model": "claude-opus-5"},
            "trigger": {"type": "refusal", "category": "cyber"},
        },
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": json.dumps(MIRROR_REPLY)},
    ])
    result = _mirror(fake_claude, chaotic_layout, sample_metadata)
    assert result.roast == "You have apps."


def test_missing_sdk_raises_import_error_with_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ImportError, match=r"unjiggle\[ai\]"):
        llm._require_anthropic()


# --- provider routing ----------------------------------------------------------------


@pytest.mark.parametrize(("key", "model", "expected"), [
    ("sk-ant-api03-abc", None, "anthropic"),
    ("sk-proj-abc", None, "openai"),
    ("sk-abc", None, "openai"),
    ("some-proxy-token", None, "anthropic"),
    (None, None, "anthropic"),
    ("sk-proj-abc", "claude-opus-5-5", "anthropic"),
    ("sk-ant-api03-abc", "gpt-4.1", "openai"),
    ("sk-ant-api03-abc", "o3-mini", "openai"),
])
def test_resolve_provider(key, model, expected):
    assert llm.resolve_provider(key, model) == expected


def test_explicit_provider_wins():
    assert llm.resolve_provider("sk-ant-api03-abc", provider="openai") == "openai"
    with pytest.raises(ValueError):
        llm.resolve_provider("sk-ant-api03-abc", provider="gemini")


def test_default_models():
    assert llm.resolve_route(ANTHROPIC_KEY) == ("anthropic", ANTHROPIC_KEY, "claude-opus-5-5")
    assert llm.resolve_route(OPENAI_KEY) == ("openai", OPENAI_KEY, "gpt-4.1")


def test_openai_model_with_both_keys_set_uses_the_openai_key(monkeypatch):
    # The CLI reads ANTHROPIC_API_KEY first, so --model gpt-4.1 arrives with it.
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    assert llm.resolve_route(ANTHROPIC_KEY, "gpt-4.1") == ("openai", OPENAI_KEY, "gpt-4.1")


def test_anthropic_key_reaches_claude_not_openai(fake_claude, chaotic_layout, sample_metadata):
    score = compute_score(chaotic_layout, sample_metadata)
    analyze(chaotic_layout, sample_metadata, score, api_key=ANTHROPIC_KEY)
    assert len(fake_claude.requests) == 1


# --- OpenAI path (kept working) ------------------------------------------------------


class FakeOpenAI:
    """Stands in for the openai module and records chat.completions.create calls."""

    def __init__(self, arguments):
        self.arguments = arguments
        self.calls = []

    def OpenAI(self, api_key):  # mirrors the SDK's class name
        self.api_key = api_key

        def create(**kwargs):
            self.calls.append(kwargs)
            name = kwargs["tool_choice"]["function"]["name"]
            call = SimpleNamespace(function=SimpleNamespace(
                name=name, arguments=json.dumps(self.arguments),
            ))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_openai_key_uses_function_calling(monkeypatch, fake_claude, chaotic_layout, sample_metadata):
    fake = FakeOpenAI(ANALYSIS_REPLY)
    monkeypatch.setitem(sys.modules, "openai", fake)
    score = compute_score(chaotic_layout, sample_metadata)

    result = analyze(chaotic_layout, sample_metadata, score, api_key=OPENAI_KEY)

    assert fake_claude.requests == []
    call = fake.calls[-1]
    assert call["model"] == "gpt-4.1"
    assert call["tools"][0]["function"]["parameters"] == ANALYSIS_TOOL["input_schema"]
    assert result.archetype == "The Collector"


def test_openai_intent_path_returns_operations(monkeypatch, chaotic_layout, sample_metadata):
    fake = FakeOpenAI(ANALYSIS_REPLY)
    monkeypatch.setitem(sys.modules, "openai", fake)
    score = compute_score(chaotic_layout, sample_metadata)

    ops = plan_intent_operations(
        "calm", chaotic_layout, sample_metadata, score, api_key=OPENAI_KEY,
    )

    assert fake.calls[-1]["model"] == "gpt-4.1"
    assert [op.bundle_ids for op in ops] == [["com.apple.weather"]]
