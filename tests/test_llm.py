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
from unjiggle.analyzer import (
    ANALYSIS_TOOL,
    _build_context,
    _parse_result,
    analyze,
    plan_intent_operations,
)
from unjiggle.mirror import MIRROR_TOOL, _parse_mirror, generate_mirror
from unjiggle.obituary import OBITUARY_TOOL, _parse_obituaries, generate_obituaries
from unjiggle.scoring import compute_score
from unjiggle.stylist import INTENT_TOOL

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
# The AI Stylist replies with a plan. In chaotic_layout, a3 is com.apple.weather:
# IDs follow the page order and skip the dock apps.
INTENT_REPLY = {
    "page_one": [],
    "folders": [],
    "app_library": {"groups": [], "apps": ["a3"]},
    "delete": [],
    "unplaced": "stay",
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
        self.status = 200
        self.requests = []
        self.api_keys = []

    def handle(self, request):
        self.requests.append(SimpleNamespace(
            url=str(request.url),
            headers=request.headers,
            body=json.loads(request.content),
        ))
        return httpx2.Response(self.status, json=self.reply)

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
    fake_claude.reply = _json_reply(INTENT_REPLY)
    score = compute_score(chaotic_layout, sample_metadata)
    ops = plan_intent_operations(
        "calm and minimal", chaotic_layout, sample_metadata, score, api_key=ANTHROPIC_KEY,
    )

    request = fake_claude.last
    _assert_opus_request(request, INTENT_TOOL["input_schema"], "low")
    # The layout comes first and is cached with the system prompt. The intent comes last.
    layout_block, intent_block = request.body["messages"][0]["content"]
    assert layout_block["text"].startswith("<layout>\nTODAY: ")
    assert layout_block["cache_control"] == {"type": "ephemeral"}
    assert intent_block == {"type": "text", "text": "<intent>\ncalm and minimal\n</intent>"}
    assert request.body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert [op.action for op in ops] == ["move_to_app_library"]
    assert ops[0].bundle_ids == ["com.apple.weather"]


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


@pytest.mark.parametrize("model", [
    "claude-sonnet-4-20250514",
    "claude-sonnet-4-0",
    "claude-opus-4-20250514",
    "claude-opus-4-0",
    "claude-3-haiku-20240307",
])
def test_models_without_structured_outputs_are_refused_before_any_request(
    fake_claude, chaotic_layout, sample_metadata, model,
):
    score = compute_score(chaotic_layout, sample_metadata)
    with pytest.raises(llm.LLMUnsupportedModelError, match="does not support structured outputs"):
        analyze(chaotic_layout, sample_metadata, score, api_key=ANTHROPIC_KEY, model=model)
    assert fake_claude.requests == []


@pytest.mark.parametrize(("model", "has_effort"), [
    ("claude-haiku-4-5", False),
    ("claude-sonnet-4-5", False),
    ("claude-opus-4-1", False),
    ("claude-opus-4-5", True),
    ("claude-sonnet-4-6", True),
    ("claude-opus-5", True),
])
def test_older_models_with_structured_outputs_are_still_served(
    fake_claude, chaotic_layout, sample_metadata, model, has_effort,
):
    score = compute_score(chaotic_layout, sample_metadata)
    analyze(chaotic_layout, sample_metadata, score, api_key=ANTHROPIC_KEY, model=model)

    output_config = fake_claude.last.body["output_config"]
    assert output_config["format"]["type"] == "json_schema"
    assert ("effort" in output_config) is has_effort


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

    for tool in (ANALYSIS_TOOL, INTENT_TOOL, MIRROR_TOOL, OBITUARY_TOOL):
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


def test_cached_prefix_puts_breakpoints_on_the_system_prompt_and_the_prefix(fake_claude):
    fake_claude.reply = _json_reply({"ok": True})
    llm.claude_json(
        api_key=ANTHROPIC_KEY, model="claude-opus-5-5", system="S", user="U",
        schema={"type": "object"}, effort="low", cached_prefix="P",
    )
    body = fake_claude.last.body
    breakpoint_ = {"type": "ephemeral"}
    assert body["system"] == [{"type": "text", "text": "S", "cache_control": breakpoint_}]
    assert body["messages"] == [{"role": "user", "content": [
        {"type": "text", "text": "P", "cache_control": breakpoint_},
        {"type": "text", "text": "U"},
    ]}]


def test_request_without_a_cached_prefix_sends_plain_strings(fake_claude):
    fake_claude.reply = _json_reply({"ok": True})
    llm.claude_json(
        api_key=ANTHROPIC_KEY, model="claude-opus-5-5", system="S", user="U",
        schema={"type": "object"}, effort="low",
    )
    body = fake_claude.last.body
    assert body["system"] == "S"
    assert body["messages"] == [{"role": "user", "content": "U"}]


def test_stale_year_needs_18_months_without_an_update():
    from datetime import datetime, timezone

    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    assert llm.stale_year({"last_updated": "2025-03-01T00:00:00Z"}, now) == 2025
    assert llm.stale_year({"last_updated": "2025-06-01T00:00:00Z"}, now) is None
    assert llm.stale_year({"last_updated": "2019-01-01"}, now) == 2019
    assert llm.stale_year({"last_updated": None}, now) is None
    assert llm.stale_year({"last_updated": "soon"}, now) is None
    assert llm.stale_year(None, now) is None


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
    fake = FakeOpenAI(INTENT_REPLY)
    monkeypatch.setitem(sys.modules, "openai", fake)
    score = compute_score(chaotic_layout, sample_metadata)

    ops = plan_intent_operations(
        "calm", chaotic_layout, sample_metadata, score, api_key=OPENAI_KEY,
    )

    call = fake.calls[-1]
    assert call["model"] == "gpt-4.1"
    assert call["tools"][0]["function"]["parameters"] == INTENT_TOOL["input_schema"]
    assert [op.bundle_ids for op in ops] == [["com.apple.weather"]]


# --- prompt inputs and output contracts ------------------------------------------------


def test_analysis_context_lists_folder_members_by_bundle_id(chaotic_layout, sample_metadata):
    score = compute_score(chaotic_layout, sample_metadata)
    context = _build_context(chaotic_layout, sample_metadata, score)

    assert context.startswith("TODAY: ")
    assert '[FOLDER "Social"] (4 apps):' in context
    assert "\n    com.facebook.Facebook" in context
    assert "\n    com.linkedin.LinkedIn" in context


def test_mirror_and_obituary_contexts_start_with_today(
    fake_claude, no_screen_time, chaotic_layout, sample_metadata,
):
    fake_claude.reply = _json_reply(MIRROR_REPLY)
    _mirror(fake_claude, chaotic_layout, sample_metadata)
    assert "<apps>\nTODAY: " in fake_claude.last.body["messages"][0]["content"]

    layout, metadata = _dead_app_layout()
    fake_claude.reply = _json_reply({"obituaries": [], "graveyard_summary": "Quiet."})
    generate_obituaries(layout, metadata, api_key=ANTHROPIC_KEY)
    user = fake_claude.last.body["messages"][0]["content"]
    assert "<graveyard>\nTODAY: " in user
    assert "APP: Dead0 (com.example.dead0)" in user


def test_observations_are_ordered_by_track(chaotic_layout):
    data = {
        "observations": [
            {"track": "optimization", "title": "C", "narrative": "", "operations": []},
            {"track": "cleanup", "title": "A", "narrative": "", "operations": []},
            {"track": "organization", "title": "B", "narrative": "", "operations": []},
            {"track": "cleanup", "title": "A2", "narrative": "", "operations": []},
        ],
        "personality": "",
        "archetype": "X",
    }
    result = _parse_result(data, chaotic_layout)
    assert [obs.title for obs in result.observations] == ["A", "A2", "B", "C"]


def test_mirror_drops_repeated_phases_and_tensions():
    result = _parse_mirror({
        "roast": "r",
        "phases": [
            {"name": "The Fitness Phase", "apps": ["Strava"], "narrative": "a"},
            {"name": "the fitness phase ", "apps": ["Peloton"], "narrative": "b"},
        ],
        "contradictions": [
            {"tension": "Calm vs. chaos", "apps_a": [], "apps_b": [], "roast": "a"},
            {"tension": "Calm vs. chaos", "apps_a": [], "apps_b": [], "roast": "b"},
        ],
        "guilty_pleasure": "g",
        "one_line": "o",
    })
    assert [p.apps for p in result.phases] == [["Strava"]]
    assert [c.roast for c in result.contradictions] == ["a"]


def test_obituaries_keep_only_candidates_once_each():
    dead_apps = [
        {"bundle_id": "com.example.a", "name": "A"},
        {"bundle_id": "com.example.b", "name": "B"},
    ]
    result = _parse_obituaries({
        "obituaries": [
            {"bundle_id": "com.example.a", "eulogy": "first", "cause_of_death": "x"},
            {"bundle_id": "com.example.invented", "eulogy": "?", "cause_of_death": "x"},
            {"bundle_id": "com.example.a", "eulogy": "again", "cause_of_death": "x"},
            {"bundle_id": "com.example.b", "eulogy": "second", "cause_of_death": "x"},
        ],
        "graveyard_summary": "Two.",
    }, dead_apps)
    assert [(o.bundle_id, o.eulogy) for o in result.obituaries] == [
        ("com.example.a", "first"), ("com.example.b", "second"),
    ]
    assert result.total_dead == 2


def test_obituary_bundle_ids_match_despite_whitespace_or_case():
    dead_apps = [
        {"bundle_id": "com.example.a", "name": "A"},
        {"bundle_id": "com.Example.B", "name": "B"},
    ]
    result = _parse_obituaries({
        "obituaries": [
            {"bundle_id": "com.example.a ", "eulogy": "first", "cause_of_death": "x"},
            {"bundle_id": "COM.EXAMPLE.B", "eulogy": "second", "cause_of_death": "x"},
            {"bundle_id": "com.example.A", "eulogy": "again", "cause_of_death": "x"},
        ],
        "graveyard_summary": "Two.",
    }, dead_apps)
    # Each obituary carries the candidate's own ID, once.
    assert [(o.bundle_id, o.app_name, o.eulogy) for o in result.obituaries] == [
        ("com.example.a", "A", "first"), ("com.Example.B", "B", "second"),
    ]


def test_obituary_schema_always_asks_for_an_approximate_birth_year():
    # Every client shows the "born - died" line only when born is present.
    item = OBITUARY_TOOL["input_schema"]["properties"]["obituaries"]["items"]
    assert "born" in item["required"]
    assert "approximate" in item["properties"]["born"]["description"].lower()


@pytest.fixture
def phone(monkeypatch, chaotic_layout, sample_metadata):
    """A connected phone with the chaotic layout, for CLI tests."""
    from unjiggle import device, itunes

    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: chaotic_layout)
    monkeypatch.setattr(itunes, "enrich_layout", lambda layout: sample_metadata)


def _json_suggest_intent():
    from click.testing import CliRunner

    from unjiggle.cli import json as json_group

    return CliRunner().invoke(
        json_group, ["suggest", "--intent", "calm", "--api-key", ANTHROPIC_KEY],
    )


def test_json_suggest_intent_keeps_the_transform_preview_contract(fake_claude, phone):
    fake_claude.reply = _json_reply(INTENT_REPLY)

    result = _json_suggest_intent()

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["intent"] == "calm"
    assert payload["operations"] == [
        {"action": "move_to_app_library", "bundle_ids": ["com.apple.weather"]},
    ]
    for key in ("summary", "changes", "before_score", "after_score", "before_pages", "after_pages"):
        assert key in payload
    assert fake_claude.last.body["model"] == "claude-opus-5-5"


def test_json_suggest_intent_reports_a_refusal_as_json_error(fake_claude, phone):
    fake_claude.reply = _message([], stop_reason="refusal")

    result = _json_suggest_intent()

    assert result.exit_code == 1
    assert "declined" in json.loads(result.output)["error"]


def _run_go(monkeypatch, tmp_path, chaotic_layout, sample_metadata, *args):
    import webbrowser

    from click.testing import CliRunner

    from unjiggle import archetypes, cli, device, itunes, telemetry

    monkeypatch.setattr(device, "connect", lambda: (
        "LOCKDOWN", SimpleNamespace(name="iPhone", model="iPhone16,1", ios_version="26.0"),
    ))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: chaotic_layout)
    monkeypatch.setattr(itunes, "enrich_layout", lambda layout, progress=None: sample_metadata)
    monkeypatch.setattr(archetypes, "assign_archetype", lambda layout, metadata: ("The Offline One", "Tagline."))
    monkeypatch.setattr(cli, "UNJIGGLE_DIR", tmp_path)
    monkeypatch.setattr(webbrowser, "open", lambda url: True)
    monkeypatch.setattr(telemetry, "prompt_analytics_opt_in", lambda console: None)
    monkeypatch.setattr(telemetry, "send_event", lambda *args, **kwargs: None)
    return CliRunner().invoke(cli.main, ["go", "--api-key", ANTHROPIC_KEY, *args])


def test_go_falls_back_to_the_offline_archetype_when_claude_declines(
    monkeypatch, tmp_path, fake_claude, chaotic_layout, sample_metadata,
):
    fake_claude.reply = _message([], stop_reason="refusal")

    result = _run_go(monkeypatch, tmp_path, chaotic_layout, sample_metadata)

    assert result.exit_code == 0, result.output
    assert len(fake_claude.requests) == 1
    assert "AI analysis unavailable: Claude declined this request." in result.output
    assert "The Offline One" in result.output
    assert list((tmp_path / "reports").glob("report-*.html"))


@pytest.mark.parametrize(("status", "error_type"), [
    (404, "not_found_error"),
    (429, "rate_limit_error"),
    (529, "overloaded_error"),
])
def test_go_falls_back_to_the_offline_archetype_when_the_api_call_fails(
    monkeypatch, tmp_path, fake_claude, chaotic_layout, sample_metadata, status, error_type,
):
    fake_claude.status = status
    fake_claude.reply = {"type": "error", "error": {"type": error_type, "message": "nope"}}

    result = _run_go(monkeypatch, tmp_path, chaotic_layout, sample_metadata)

    assert result.exit_code == 0, result.output
    assert len(fake_claude.requests) == 1  # the test client does not retry
    output = " ".join(result.output.split())  # the console wraps long lines
    assert "AI analysis unavailable:" in output
    assert error_type in output
    assert "The Offline One" in result.output
    assert list((tmp_path / "reports").glob("share-*.html"))
    assert list((tmp_path / "reports").glob("report-*.html"))


def test_go_falls_back_when_the_model_lacks_structured_outputs(
    monkeypatch, tmp_path, fake_claude, chaotic_layout, sample_metadata,
):
    result = _run_go(
        monkeypatch, tmp_path, chaotic_layout, sample_metadata,
        "--model", "claude-opus-4-20250514",
    )

    assert result.exit_code == 0, result.output
    assert fake_claude.requests == []
    output = " ".join(result.output.split())  # the console wraps long lines
    assert "AI analysis unavailable: claude-opus-4-20250514 does not support structured outputs" in output
    assert list((tmp_path / "reports").glob("report-*.html"))
