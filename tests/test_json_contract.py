"""The contract of `unjiggle json`: what a client such as the Mac app reads.

A client starts `unjiggle json <command>`, writes the JSON payload (or nothing) to stdin,
closes stdin, and decodes stdout. So every json command must:

- ask no question (no click.confirm, click.prompt or input()), because nobody can answer;
- write exactly one JSON document to stdout, and all other text to stderr;
- exit 0 with a document that decodes as the model that the client expects, or exit 1
  with {"error": ...}.

The models below copy the Codable types that the Mac app decodes (PhoneData, TransformPreview,
AppliedTransform, RestoredLayout and the others): a key without Opt must be there and not
null, and each value must have the type that Swift's JSONDecoder expects. Extra keys are
allowed.

The phone is in memory. The device functions are fakes, so no test touches an iPhone,
and no test calls an AI model. The fakes print to stdout, as a library can do, to show
that such text goes to stderr.
"""

from __future__ import annotations

import builtins
import base64
import copy
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from tests.fake_springboard import UNLISTED_APP, adds_unlisted_app, page_of, put_in_first_free_slot, without_app
from tests.test_preservation import owner_shaped_phone
from unjiggle import cli, device, itunes, layout_engine, llm, render, safety, screentime, stylist
from unjiggle.cli import PRESET_CHOICES
from unjiggle.models import DeviceInfo, HomeScreenLayout

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"


# --- the Swift models -------------------------------------------------------------------
# int is Swift Int, float is Double, str is String, bool is Bool.


class Opt:
    """A Swift optional: the key can be missing or null."""

    def __init__(self, kind):
        self.kind = kind


class ArrayOf:
    def __init__(self, kind):
        self.kind = kind


class DictOf:
    """A Swift [String: T]."""

    def __init__(self, kind):
        self.kind = kind


LAYOUT_ITEM = "LayoutItem"  # a Swift enum with a "type" tag

APP_INFO = {
    "bundle_id": str, "display_name": str, "category": Opt(str),
    "icon_url": Opt(str), "last_updated": Opt(str),
}
FOLDER_INFO = {"display_name": str, "apps": ArrayOf(ArrayOf(APP_INFO))}
WIDGET_INFO = {"container_bundle_id": str, "grid_size": str}
LAYOUT_ITEM_CASES = {"app": APP_INFO, "folder": FOLDER_INFO, "widget": WIDGET_INFO}

DEVICE_INFO = {"name": str, "model": str, "ios_version": str}
PARSE_INTEGRITY = {
    "structure_preserved": bool, "raw_page_count": Opt(int),
    "unparsed_items": Opt(int), "dropped_empty_pages": Opt(int),
}
PHONE_DATA = {
    "device": DEVICE_INFO, "total_apps": int, "page_count": int, "folder_count": int,
    "dock_items": int, "dock": ArrayOf(LAYOUT_ITEM), "pages": ArrayOf(ArrayOf(LAYOUT_ITEM)),
    "parse_integrity": PARSE_INTEGRITY,
    "source_raw_sha256": str,
}

SCORE_BREAKDOWN = {
    "page_efficiency": float, "category_coherence": float, "folder_usage": float, "dock_quality": float,
}
APP_SWIPE_COST = {
    "name": str, "bundle_id": str, "page": int, "in_folder": bool, "annual_wasted_swipes": int,
    "category": Opt(str), "swipes_to_reach": Opt(int), "estimated_daily_opens": Opt(float),
}
SWIPE_TAX_SUMMARY = {
    "total_annual": int, "optimal_annual": int, "savings": int, "headline": Opt(str),
    "worst_offenders": ArrayOf(APP_SWIPE_COST),
}
DIAGNOSIS_RESULT = {
    "score": SCORE_BREAKDOWN, "archetype": str, "tagline": str, "swipe_tax": SWIPE_TAX_SUMMARY,
}

LIFE_PHASE = {"name": str, "apps": ArrayOf(str), "narrative": str}
CONTRADICTION = {"tension": str, "apps_a": ArrayOf(str), "apps_b": ArrayOf(str), "roast": str}
MIRROR_RESULT = {
    "roast": str, "phases": ArrayOf(LIFE_PHASE), "contradictions": ArrayOf(CONTRADICTION),
    "guilty_pleasure": str, "one_line": str,
}

OBITUARY = {
    "app_name": str, "bundle_id": str, "eulogy": str, "born": Opt(str), "died": Opt(str),
    "cause_of_death": Opt(str), "survived_by": Opt(str),
}
OBITUARY_RESULT = {"total_dead": int, "obituaries": ArrayOf(OBITUARY), "graveyard_summary": str}

TRANSFORM_OPERATION = {
    "action": str, "bundle_ids": ArrayOf(str), "target_page": Opt(int), "folder_name": Opt(str),
    "old_name": Opt(str), "gratitude": Opt(str),
}
TRANSFORM_LAYOUT = {
    "total_apps": int, "page_count": int, "folder_count": int, "dock_items": int,
    "dock": ArrayOf(LAYOUT_ITEM), "pages": ArrayOf(ArrayOf(LAYOUT_ITEM)),
}
LAYOUT_CHANGE = {
    "app_name": str, "bundle_id": Opt(str), "from_page": int, "to_page": Opt(int),
    "action": str, "detail": Opt(str),
}
TRANSFORM_PREVIEW = {
    "intent": str, "before_score": int, "after_score": int, "score_delta": Opt(int),
    "score_trend": Opt(str), "score_improved": Opt(bool), "before_pages": Opt(int),
    "after_pages": Opt(int), "moved": Opt(int), "archived": Opt(int), "new_folders": Opt(int),
    "changes": ArrayOf(LAYOUT_CHANGE), "operations": ArrayOf(TRANSFORM_OPERATION), "summary": str,
    "current_layout": Opt(TRANSFORM_LAYOUT), "proposed_layout": Opt(TRANSFORM_LAYOUT),
}
PRESETS_RESPONSE = {
    "presets": DictOf(TRANSFORM_PREVIEW), "preset_order": Opt(ArrayOf(str)),
    "layout_signature": Opt(str), "snapshot_id": Opt(str),
}

LAYOUT_MUTATION_RESULT = {"page_count": int, "total_apps": int}
# An app that iOS added to the home screen at the write (layout_engine.ios_added_apps).
IOS_ADDED_APP = {"bundle_id": str, "name": str, "page": int}
APPLIED_TRANSFORM = {
    "applied": int, "backup": str, "result": LAYOUT_MUTATION_RESULT, "ios_added": Opt(ArrayOf(IOS_ADDED_APP)),
}
RESTORED_LAYOUT = {
    "restored": bool, "backup": str, "result": LAYOUT_MUTATION_RESULT, "undo_backup": Opt(str),
    "ios_added": Opt(ArrayOf(IOS_ADDED_APP)),
}
RENDERED_CARD = {"success": bool, "action": str, "card": str, "html_path": str, "path": Opt(str)}
DEVICE_STATUS = {"connected": bool, "device_name": Opt(str), "model": Opt(str), "ios_version": Opt(str)}
INSTALLED_APP = {
    "bundle_id": str, "display_name": Opt(str), "application_type": Opt(str), "on_home_screen": bool,
}
INSTALLED_INVENTORY = {
    "device": DEVICE_INFO, "snapshot_id": str, "apps": ArrayOf(INSTALLED_APP),
    "unmatched_home_screen_ids": ArrayOf(str),
}
APP_ICON = {"bundle_id": str, "png_base64": Opt(str)}
LIBRARY_INSERTION = {
    "writable": bool, "bundle_id": str, "target_page": int,
    "snapshot_id": str, "source_raw_sha256": str, "proposed_snapshot_id": str,
    "proposed_layout": TRANSFORM_LAYOUT, "parse_integrity": PARSE_INTEGRITY,
    "warning": str,
}


def decodes(value, kind, path="$"):
    """Fail unless `value` decodes as the Swift type `kind` (see the models above)."""
    if isinstance(kind, dict):
        assert isinstance(value, dict), f"{path}: expected an object, got {value!r}"
        for key, sub in kind.items():
            if isinstance(sub, Opt):
                if value.get(key) is not None:
                    decodes(value[key], sub.kind, f"{path}.{key}")
            else:
                assert value.get(key) is not None, f"{path}.{key}: missing or null"
                decodes(value[key], sub, f"{path}.{key}")
    elif isinstance(kind, ArrayOf):
        assert isinstance(value, list), f"{path}: expected an array, got {value!r}"
        for index, item in enumerate(value):
            decodes(item, kind.kind, f"{path}[{index}]")
    elif isinstance(kind, DictOf):
        assert isinstance(value, dict), f"{path}: expected an object, got {value!r}"
        for key, item in value.items():
            decodes(item, kind.kind, f"{path}.{key}")
    elif kind == LAYOUT_ITEM:
        assert isinstance(value, dict), f"{path}: expected an object, got {value!r}"
        assert value.get("type") in LAYOUT_ITEM_CASES, f"{path}.type: unknown type {value.get('type')!r}"
        decodes({value["type"]: value.get(value["type"])}, {value["type"]: LAYOUT_ITEM_CASES[value["type"]]}, path)
    elif kind is int:
        assert isinstance(value, int) and not isinstance(value, bool), f"{path}: expected Int, got {value!r}"
    elif kind is float:
        assert isinstance(value, (int, float)) and not isinstance(value, bool), f"{path}: expected Double, got {value!r}"
    elif kind is bool:
        assert isinstance(value, bool), f"{path}: expected Bool, got {value!r}"
    elif kind is str:
        assert isinstance(value, str), f"{path}: expected String, got {value!r}"
    else:
        raise TypeError(f"unknown kind {kind!r}")


def test_the_model_check_finds_a_missing_key_and_a_wrong_type():
    decodes({"applied": 1, "backup": "/b.json", "result": {"page_count": 2, "total_apps": 9}}, APPLIED_TRANSFORM)
    with pytest.raises(AssertionError, match=r"\$\.backup: missing or null"):
        decodes({"applied": 1, "backup": None, "result": {"page_count": 2, "total_apps": 9}}, APPLIED_TRANSFORM)
    with pytest.raises(AssertionError, match=r"\$\.applied: expected Int"):
        decodes({"applied": True, "backup": "/b.json", "result": {"page_count": 2, "total_apps": 9}}, APPLIED_TRANSFORM)


# --- the in-memory phone ----------------------------------------------------------------


class FakePhone:
    """An iPhone in memory. It prints to stdout and uses the CLI's Rich console, as a
    library or the engine can do, so that the tests see where that text goes."""

    def __init__(self, raw, metadata, home: Path):
        self.raw = copy.deepcopy(raw)
        self.metadata = metadata
        self.home = home
        self.backup_dir = home / ".unjiggle" / "backups"
        self.connected = True
        self.writes: list = []
        self.keep = None  # what the phone keeps of a write (None: all of it)
        self.write_error: Exception | None = None

    def connect(self):
        if not self.connected:
            raise RuntimeError("No device connected")
        print("fake usbmux: connected")
        return "LOCKDOWN", DeviceInfo(name="Test iPhone", model="iPhone18,4", ios_version="26.0", udid="FAKE")

    def read_layout(self, _lockdown):
        print("fake springboard: get_icon_state")
        cli.console.print("[dim]fake springboard: read[/dim]")
        return device.parse_layout_state(copy.deepcopy(self.raw))

    def write_layout(self, _lockdown, state):
        print("fake springboard: set_icon_state")
        if self.write_error:
            raise self.write_error
        self.writes.append(copy.deepcopy(state))
        self.raw = copy.deepcopy(self.keep(state) if self.keep else state)

    def backups(self) -> list[Path]:
        return sorted(self.backup_dir.glob("layout-*.json")) if self.backup_dir.exists() else []


def _no_question(*_args, **_kwargs):
    raise AssertionError("a json command asked a question, and a client cannot answer it")


def _no_ai(*_args, **_kwargs):
    raise AssertionError("a test called an AI model")


@pytest.fixture
def phone(monkeypatch, tmp_path):
    layout, metadata = owner_shaped_phone()
    fake = FakePhone(layout.raw, metadata, tmp_path)
    monkeypatch.setattr(device, "connect", fake.connect)
    monkeypatch.setattr(device, "read_layout", fake.read_layout)
    monkeypatch.setattr(device, "write_layout", fake.write_layout)
    monkeypatch.setattr(itunes, "enrich_layout", lambda layout, progress_callback=None: fake.metadata)
    monkeypatch.setattr(screentime, "get_usage", lambda bundle_ids=None, iphone_only=True: {})
    # Nothing goes to the owner's home folder.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(safety, "BACKUP_DIR", fake.backup_dir)
    monkeypatch.setattr(cli, "UNJIGGLE_DIR", tmp_path / ".unjiggle")
    monkeypatch.setattr(cli, "BACKUP_DIR", fake.backup_dir)
    monkeypatch.setattr(render, "render_to_png", lambda html, png: png.write_bytes(b"png") or True)
    monkeypatch.setattr(render, "copy_image", lambda png: True)
    # No AI model, no question.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_anthropic_client", _no_ai)
    monkeypatch.setattr(click, "confirm", _no_question)
    monkeypatch.setattr(click, "prompt", _no_question)
    monkeypatch.setattr(builtins, "input", _no_question)
    return fake


def run(*args, stdin=None):
    """`unjiggle json <args>` with stdin that holds only `stdin` (empty when None)."""
    return CliRunner().invoke(cli.main, ["json", *args], input=stdin, catch_exceptions=False)


def one_document(result) -> dict:
    """The one JSON document on stdout. Nothing else may be on stdout."""
    out = result.stdout
    assert out.endswith("\n") and out.count("\n") == 1, f"stdout must be one JSON line, got {out!r}"
    return json.loads(out)


def ok(result, model=None) -> dict:
    assert result.exit_code == 0, result.stderr
    payload = one_document(result)
    if model is not None:
        decodes(payload, model)
    return payload


def failed(result) -> dict:
    assert result.exit_code == 1, result.stdout + result.stderr
    payload = one_document(result)
    assert isinstance(payload.get("error"), str) and payload["error"]
    # A client that reads only stderr after a failure also gets the message.
    assert payload["error"] in result.stderr
    return payload


def app_payload(operations: list[dict], snapshot_id: str | None = None) -> str:
    """The stdin of `json apply`, as the Mac app encodes it: only the TransformOperation
    keys, no null values, the snapshot_id of the preview when there is one, and the
    escaped slashes of Swift's JSONEncoder."""
    ops = [{key: op[key] for key in TRANSFORM_OPERATION if op.get(key) is not None} for op in operations]
    payload = {"operations": ops}
    if snapshot_id is not None:
        payload["snapshot_id"] = snapshot_id
    return json.dumps(payload, separators=(",", ":")).replace("/", "\\/")


# --- each command -----------------------------------------------------------------------


CONTRACT_COMMANDS = {"status", "scan", "inventory", "icon", "diagnose", "mirror", "obituary", "suggest", "presets", "restore", "render", "apply", "check-operations", "check-library-insertion", "check-library-insertions", "check-mixed-operations", "apply-mixed-checked", "apply-library-checked", "apply-library-batch-checked", "apply-checked", "pending-checked", "check-recovery", "restore-checked"}


def test_the_contract_version_is_2():
    # A client can require this version before it bundles the engine. Raise it when a
    # client must refuse the engines before a change of this contract.
    assert cli.JSON_CONTRACT == 2


def test_every_json_command_has_a_contract_test():
    assert set(cli.json.commands) == CONTRACT_COMMANDS


def test_every_json_command_sends_other_text_to_stderr():
    assert all(isinstance(command, cli._JsonCommand) for command in cli.json.commands.values())


def test_help_of_a_json_command_goes_to_stdout():
    result = CliRunner().invoke(cli.main, ["json", "apply", "--help"])

    assert result.exit_code == 0
    assert result.stdout.startswith("Usage:")
    assert result.stderr == ""


def test_other_text_goes_to_stderr(phone):
    result = run("scan")

    ok(result, PHONE_DATA)
    assert "fake springboard: get_icon_state" in result.stderr
    assert "fake springboard: read" in result.stderr


def test_status_connected(phone):
    payload = ok(run("status"), DEVICE_STATUS)

    assert payload["connected"] is True
    assert (payload["device_name"], payload["model"], payload["ios_version"]) == ("Test iPhone", "iPhone18,4", "26.0")
    decodes(payload["device"], DEVICE_INFO)


def test_status_not_connected(phone):
    phone.connected = False

    payload = ok(run("status"), DEVICE_STATUS)

    assert payload["connected"] is False


def test_scan(phone):
    payload = ok(run("scan"), PHONE_DATA)

    assert payload["total_apps"] > 0
    assert payload["parse_integrity"]["structure_preserved"] is True
    assert payload["source_raw_sha256"] == cli._raw_state_fingerprint(phone.read_layout("LOCKDOWN"))
    assert phone.writes == []


@pytest.mark.parametrize("mutate,expected", [
    (lambda raw: raw.append([]), {"dropped_empty_pages": 1, "unparsed_items": 0}),
    (lambda raw: raw[1].append({"iconType": "unknown"}), {"dropped_empty_pages": 0, "unparsed_items": 1}),
    (lambda raw: next(item for page in raw[1:] for item in page if device.is_folder_entry(item))["iconLists"][0].append(
        {"iconType": "unknown"}), {"dropped_empty_pages": 0, "unparsed_items": 1}),
], ids=["empty-page", "unknown-icon", "unknown-folder-child"])
def test_scan_reports_unparsed_structure_without_writing(phone, mutate, expected):
    mutate(phone.raw)
    payload = ok(run("scan"), PHONE_DATA)
    integrity = payload["parse_integrity"]
    assert integrity["structure_preserved"] is False
    for key, value in expected.items():
        assert integrity[key] == value
    assert phone.writes == []


def test_inventory_contract_is_read_only(phone, monkeypatch):
    def fake_inventory(lockdown, layout):
        assert lockdown == "LOCKDOWN"
        return device.reconcile_installed_apps(
            {"com.example.library": {"CFBundleDisplayName": "Library", "ApplicationType": "User"}},
            layout,
        )

    monkeypatch.setattr(device, "read_installed_apps", fake_inventory)
    payload = ok(run("inventory"), INSTALLED_INVENTORY)

    assert payload["apps"][0]["on_home_screen"] is False
    assert payload["snapshot_id"]
    assert phone.writes == []


def test_library_insertion_contract_is_read_only(phone, monkeypatch):
    phone.raw = {"buttonBar": [], "iconLists": [["org.example.visible"]],
                 "ignored": ["org.example.library"]}
    monkeypatch.setattr(device, "read_installed_apps", lambda lockdown, layout:
                        device.reconcile_installed_apps({"org.example.library": {"ApplicationType": "User"}}, layout))
    source = device.parse_layout_state(phone.raw)
    request = {"bundle_id": "org.example.library", "target_page": 0,
               "snapshot_id": cli._layout_signature(source),
               "source_raw_sha256": cli._raw_state_fingerprint(source)}
    payload = ok(run("check-library-insertion", stdin=json.dumps(request)), LIBRARY_INSERTION)
    assert payload["writable"] is False
    assert payload["proposed_layout"]["pages"][0][-1]["app"]["bundle_id"] == request["bundle_id"]
    assert phone.writes == []
    assert phone.backups() == []


def test_library_insertions_contract_returns_checked_prefixes_without_writing(phone, monkeypatch):
    phone.raw = {"buttonBar": [], "iconLists": [["org.example.visible"]],
                 "ignored": ["org.example.library", "org.example.second"]}
    monkeypatch.setattr(device, "read_installed_apps", lambda lockdown, layout:
                        device.reconcile_installed_apps({
                            "org.example.library": {"ApplicationType": "User"},
                            "org.example.second": {"ApplicationType": "User"}}, layout))
    source = device.parse_layout_state(phone.raw)
    request = {"insertions": [{"bundle_id": name, "target_page": 0} for name in
                              ("org.example.library", "org.example.second")],
               "snapshot_id": cli._layout_signature(source),
               "source_raw_sha256": cli._raw_state_fingerprint(source)}
    payload = ok(run("check-library-insertions", stdin=json.dumps(request)))
    assert payload["writable"] is False
    assert len(payload["steps"]) == 2
    assert len(payload["steps"][0]["layout"]["pages"][0]) == 2
    assert payload["steps"][-1]["layout"] == payload["proposed_layout"]
    assert phone.writes == []
    assert phone.backups() == []


def test_icon_contract_returns_device_bytes_without_writing(phone, monkeypatch):
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==")
    monkeypatch.setattr(device, "fetch_icon", lambda lockdown, bundle_id: png if bundle_id == "com.example.notes" else None)

    payload = ok(run("icon", "--bundle-id", "com.example.notes"), APP_ICON)
    assert base64.b64decode(payload["png_base64"]) == png
    assert ok(run("icon", "--bundle-id", "com.example.missing"), APP_ICON)["png_base64"] is None
    assert phone.writes == []


def test_icon_rejects_invalid_or_oversized_device_data(phone, monkeypatch):
    monkeypatch.setattr(device, "fetch_icon", lambda *_: b"not png")
    assert "invalid or oversized" in failed(run("icon", "--bundle-id", "com.example.notes"))["error"]
    monkeypatch.setattr(device, "fetch_icon", lambda *_: b"\x89PNG\r\n\x1a\n" + b"test-icon")
    assert "invalid or oversized" in failed(run("icon", "--bundle-id", "com.example.notes"))["error"]
    monkeypatch.setattr(device, "fetch_icon", lambda *_: b"\x89PNG\r\n\x1a\n" + b"a" * 1_000_000)
    failed(run("icon", "--bundle-id", "com.example.notes"))
    assert phone.writes == []


def test_diagnose(phone):
    ok(run("diagnose"), DIAGNOSIS_RESULT)


def test_mirror_without_a_key(phone):
    ok(run("mirror"), MIRROR_RESULT)


def test_obituary_without_a_key(phone):
    ok(run("obituary"), OBITUARY_RESULT)


@pytest.mark.parametrize("preset", PRESET_CHOICES)
def test_suggest_preset(phone, preset):
    payload = ok(run("suggest", "--preset", preset), TRANSFORM_PREVIEW)

    assert payload["intent"] == preset


def test_suggest_intent(phone, monkeypatch):
    layout = device.parse_layout_state(phone.raw)
    operations = cli._PRESET_BUILDERS["focus"](layout, phone.metadata)
    monkeypatch.setattr(
        stylist, "plan_intent",
        lambda intent, layout, metadata, score, api_key=None, model=None: stylist.IntentPlan(operations, []),
    )

    payload = ok(run("suggest", "--intent", "work first", "--api-key", "sk-ant-test"), TRANSFORM_PREVIEW)

    assert payload["intent"] == "work first"
    assert payload["plan_warnings"] == []


def test_suggest_without_a_mode(phone):
    payload = ok(run("suggest"))

    assert payload["observations"] == []
    assert isinstance(payload["archetype"], str)


def test_presets(phone):
    payload = ok(run("presets"), PRESETS_RESPONSE)

    assert list(payload["presets"]) == list(PRESET_CHOICES)


@pytest.mark.parametrize("card", ["score", "mirror", "obituary", "swipetax", "transform"])
@pytest.mark.parametrize("action", ["preview", "clipboard", "save"])
def test_render(phone, card, action):
    (phone.home / "Downloads").mkdir()
    backup = phone.home / "before.json"
    backup.write_text(json.dumps(phone.raw, default=str))
    extra = ["--backup", str(backup)] if card == "transform" else []

    payload = ok(run("render", "--card", card, "--action", action, *extra), RENDERED_CARD)

    assert (payload["card"], payload["action"]) == (card, action)
    assert Path(payload["path"]).exists()


def test_render_transform_with_a_missing_backup(phone):
    failed(run("render", "--card", "transform", "--backup", str(phone.home / "missing.json")))


# --- apply ------------------------------------------------------------------------------


def _focus_preview() -> dict:
    return ok(run("suggest", "--preset", "focus"), TRANSFORM_PREVIEW)


def test_check_operations_predicts_a_write_without_backup_or_mutation(phone):
    preview = _focus_preview()
    before = copy.deepcopy(phone.raw)

    payload = ok(run("check-operations", stdin=app_payload(preview["operations"], preview["snapshot_id"])))

    assert payload["writable"] is True
    assert payload["snapshot_id"] == preview["snapshot_id"]
    def identities(pages):
        return [[item["app"]["bundle_id"] if item["type"] == "app"
                 else (item["folder"]["display_name"] if item["type"] == "folder"
                       else item["widget"]["container_bundle_id"])
                 for item in page] for page in pages]

    assert identities(payload["proposed_layout"]["pages"]) == identities(preview["proposed_layout"]["pages"])
    assert payload["parse_integrity"]["structure_preserved"] is True
    assert len(payload["source_raw_sha256"]) == 64
    assert payload["proposed_snapshot_id"] != payload["snapshot_id"]
    assert "physical iOS" in payload["warning"]
    assert phone.raw == before
    assert phone.writes == []
    assert phone.backups() == []


def test_check_operations_projects_every_prefix_from_one_read_only_source(phone, monkeypatch):
    preview = _focus_preview()
    assert len(preview["operations"]) >= 2
    operations = preview["operations"][:2]
    before = copy.deepcopy(phone.raw)
    reads = []
    original_read = phone.read_layout

    def counted_read(lockdown):
        reads.append(1)
        return original_read(lockdown)

    monkeypatch.setattr(device, "read_layout", counted_read)
    request = json.loads(app_payload(operations, preview["snapshot_id"]))
    request["include_steps"] = True
    result = ok(run("check-operations", stdin=json.dumps(request)))
    assert len(reads) == 1
    assert len(result["steps"]) == len(operations)
    assert result["steps"][-1]["layout"] == result["proposed_layout"]
    assert result["steps"][-1]["snapshot_id"] == result["proposed_snapshot_id"]
    for count, step in enumerate(result["steps"], 1):
        assert step["index"] == count
        independent = ok(run("check-operations", stdin=app_payload(operations[:count], preview["snapshot_id"])))
        assert step["layout"] == independent["proposed_layout"]
        assert step["snapshot_id"] == independent["proposed_snapshot_id"]
        assert result["source_raw_sha256"] == independent["source_raw_sha256"]
    assert phone.raw == before and not phone.writes and not phone.backups()


def test_check_operations_rejects_malformed_or_oversized_step_requests_before_device_read(phone, monkeypatch):
    preview = _focus_preview()
    monkeypatch.setattr(device, "read_layout", lambda _: pytest.fail("device should not be read"))
    request = json.loads(app_payload(preview["operations"], preview["snapshot_id"]))
    for flag in ("true", 1, None):
        request["include_steps"] = flag
        assert "include_steps" in failed(run("check-operations", stdin=json.dumps(request)))["error"]
    request["include_steps"] = True
    request["operations"] = preview["operations"] * 51
    assert "at most 50" in failed(run("check-operations", stdin=json.dumps(request)))["error"]
    assert not phone.writes and not phone.backups()


def test_check_operations_rejects_stale_or_missing_snapshot_without_write(phone):
    preview = _focus_preview()
    absent = failed(run("check-operations", stdin=app_payload(preview["operations"])))
    _remove_app(phone.raw, _first_moved_app(preview))
    stale = failed(run("check-operations", stdin=app_payload(preview["operations"], preview["snapshot_id"])))

    assert "snapshot_id" in absent["error"]
    assert "changed since the scan" in stale["error"]
    assert phone.writes == []
    assert phone.backups() == []


def test_check_operations_rejects_unparsed_icon_state_without_write(phone):
    phone.raw[-1].append({"listType": "unsupported"})
    snapshot = ok(run("scan"), PHONE_DATA)["snapshot_id"]
    operations = _focus_preview()["operations"]

    payload = failed(run("check-operations", stdin=app_payload(operations, snapshot)))

    assert "complete icon-state structure" in payload["error"]
    assert phone.writes == []
    assert phone.backups() == []


def test_check_operations_rejects_app_library_addition_without_write(phone):
    snapshot = ok(run("scan"), PHONE_DATA)["snapshot_id"]
    operations = [{"action": "move_to_page", "bundle_ids": ["com.example.library-only"], "target_page": 1}]

    payload = failed(run("check-operations", stdin=app_payload(operations, snapshot)))

    assert "not on the home screen" in payload["error"]
    assert phone.writes == []
    assert phone.backups() == []


def _checked_request(preview=None):
    preview = preview or _focus_preview()
    proposal = ok(run("check-operations", stdin=app_payload(preview["operations"], preview["snapshot_id"])))
    request = json.loads(app_payload(preview["operations"], preview["snapshot_id"]))
    request["proposed_snapshot_id"] = proposal["proposed_snapshot_id"]
    request["source_raw_sha256"] = proposal["source_raw_sha256"]
    request["proposed_raw_sha256"] = proposal["proposed_raw_sha256"]
    return request


def test_checked_apply_writes_once_after_verified_backup_and_exact_proposal(phone):
    before = copy.deepcopy(phone.raw)
    request = _checked_request()
    result = ok(run("apply-checked", stdin=json.dumps(request)), APPLIED_TRANSFORM)

    assert result["changed"] is True
    assert len(phone.writes) == 1
    assert json.loads(Path(result["backup"]).read_text()) == json.loads(json.dumps(before, default=str))
    assert result["snapshot_id"] == request["proposed_snapshot_id"]
    assert result["recovery"]["applied_raw_sha256"] == request["proposed_raw_sha256"]
    assert result["verified_raw_sha256"] == request["proposed_raw_sha256"]
    assert result["verified_raw_sha256"] == cli._raw_state_fingerprint(phone.read_layout("LOCKDOWN"))
    assert Path(result["journal"]).is_file()
    records = ok(run("pending-checked"))["records"]
    assert records == [{"journal": result["journal"], "recovery": result["recovery"]}]


def test_checked_apply_fails_closed_when_journal_cannot_be_saved(phone, monkeypatch):
    request = _checked_request()

    def no_journal(*_args):
        raise OSError("storage full")

    monkeypatch.setattr(safety, "checked_recovery_journal", no_journal)
    result = failed(run("apply-checked", stdin=json.dumps(request)))
    assert "journal could not be saved" in result["error"]
    assert phone.writes == [] and len(phone.backups()) == 1


def test_interrupted_checked_apply_retains_recoverable_candidate(phone, monkeypatch):
    before = copy.deepcopy(phone.raw)
    request = _checked_request()
    original_write = phone.write_layout

    def applied_then_disconnected(lockdown, state):
        original_write(lockdown, state)
        raise OSError("connection lost after SpringBoard accepted write")

    monkeypatch.setattr(device, "write_layout", applied_then_disconnected)
    failure = failed(run("apply-checked", stdin=json.dumps(request)))
    records = ok(run("pending-checked"))["records"]
    assert len(phone.writes) == 1 and len(records) == 1
    assert records[0]["journal"] == failure["journal"]
    monkeypatch.setattr(device, "write_layout", original_write)
    ok(run("restore-checked", stdin=json.dumps(records[0]["recovery"])), RESTORED_LAYOUT)
    assert json.loads(json.dumps(phone.raw, default=str)) == json.loads(json.dumps(before, default=str))


def test_checked_journal_survives_process_failure_before_any_response(phone, monkeypatch):
    before = copy.deepcopy(phone.raw)
    request = _checked_request()
    original_output = cli._json_out

    def process_stopped_before_response(payload, *args, **kwargs):
        if payload.get("changed") and payload.get("journal"):
            raise SystemExit(137)
        return original_output(payload, *args, **kwargs)

    monkeypatch.setattr(cli, "_json_out", process_stopped_before_response)
    stopped = run("apply-checked", stdin=json.dumps(request))
    assert stopped.exit_code == 137
    assert not stopped.stdout
    monkeypatch.setattr(cli, "_json_out", original_output)

    assert len(phone.writes) == 1
    records = ok(run("pending-checked"))["records"]
    assert len(records) == 1
    ok(run("restore-checked", stdin=json.dumps(records[0]["recovery"])), RESTORED_LAYOUT)
    assert json.loads(json.dumps(phone.raw, default=str)) == json.loads(json.dumps(before, default=str))


def test_checked_journal_does_not_allow_restore_if_write_never_happened(phone):
    phone.write_error = OSError("USB disconnected before write")
    failed(run("apply-checked", stdin=json.dumps(_checked_request())))
    records = ok(run("pending-checked"))["records"]
    assert len(records) == 1
    assert "changed after" in failed(run("restore-checked", stdin=json.dumps(records[0]["recovery"])))["error"]
    assert phone.writes == []


def test_check_recovery_only_reads_and_requires_exact_live_state(phone):
    ok(run("apply-checked", stdin=json.dumps(_checked_request())))
    receipt = ok(run("pending-checked"))["records"][0]["recovery"]
    backups_before = len(phone.backups())
    result = ok(run("check-recovery", stdin=json.dumps(receipt)))
    assert result["eligible_for_restore_attempt"] is True
    assert "physical recovery is unverified" in result["warning"]
    assert len(phone.writes) == 1 and len(phone.backups()) == backups_before
    phone.raw[1][0]["unused_metadata"] = "changed since checked apply"
    assert "changed after" in failed(run("check-recovery", stdin=json.dumps(receipt)))["error"]
    assert len(phone.writes) == 1 and len(phone.backups()) == backups_before


def test_check_recovery_rejects_unapplied_or_tampered_candidate(phone):
    phone.write_error = OSError("USB disconnected before write")
    failed(run("apply-checked", stdin=json.dumps(_checked_request())))
    receipt = ok(run("pending-checked"))["records"][0]["recovery"]
    assert "changed after" in failed(run("check-recovery", stdin=json.dumps(receipt)))["error"]
    assert phone.writes == []
    phone.write_error = None
    applied = ok(run("apply-checked", stdin=json.dumps(_checked_request())))
    receipt = applied["recovery"]
    receipt["backup_sha256"] = "0" * 64
    assert "backup changed" in failed(run("check-recovery", stdin=json.dumps(receipt)))["error"]
    assert len(phone.writes) == 1


def test_pending_checked_rejects_corrupted_journal(phone):
    result = ok(run("apply-checked", stdin=json.dumps(_checked_request())))
    Path(result["journal"]).write_text("{broken")
    assert "could not be read" in failed(run("pending-checked"))["error"]


def test_checked_apply_backup_can_restore_original_in_memory_layout(phone):
    before = copy.deepcopy(phone.raw)
    request = _checked_request()
    applied = ok(run("apply-checked", stdin=json.dumps(request)), APPLIED_TRANSFORM)
    assert len(phone.writes) == 1

    restored = ok(run("restore", applied["backup"]), RESTORED_LAYOUT)
    assert restored["restored"] is True
    assert len(phone.writes) == 2
    assert json.loads(json.dumps(phone.raw, default=str)) == json.loads(json.dumps(before, default=str))
    assert Path(restored["undo_backup"]).is_file()


def test_checked_restore_recovers_only_the_verified_applied_layout(phone):
    before = copy.deepcopy(phone.raw)
    applied = ok(run("apply-checked", stdin=json.dumps(_checked_request())), APPLIED_TRANSFORM)
    receipt = applied["recovery"]
    assert receipt["device_id_sha256"] != "FAKE"
    restored = ok(run("restore-checked", stdin=json.dumps(receipt)), RESTORED_LAYOUT)
    assert restored["restored_raw_sha256"] == receipt["source_raw_sha256"]
    assert len(phone.writes) == 2
    assert json.loads(json.dumps(phone.raw, default=str)) == json.loads(json.dumps(before, default=str))
    assert Path(restored["undo_backup"]).is_file()
    reverse = next(record for record in ok(run("pending-checked"))["records"]
                   if record.get("operation") == "restore")
    assert reverse["journal"] == restored["journal"]
    assert reverse["recovery"]["backup"] == restored["undo_backup"]
    assert ok(run("check-recovery", stdin=json.dumps(reverse["recovery"])))["eligible_for_restore_attempt"] is True
    assert "changed after" in failed(run("restore-checked", stdin=json.dumps(receipt)))["error"]
    assert len(phone.writes) == 2


def test_checked_restore_requires_a_durable_reverse_journal_before_write(phone, monkeypatch):
    receipt = ok(run("apply-checked", stdin=json.dumps(_checked_request())))["recovery"]
    original = safety.checked_recovery_journal

    def reject_restore_journal(path, data, *, operation="apply"):
        if operation == "restore":
            raise OSError("disk full")
        return original(path, data, operation=operation)

    monkeypatch.setattr(safety, "checked_recovery_journal", reject_restore_journal)
    result = failed(run("restore-checked", stdin=json.dumps(receipt)))
    assert "restore recovery journal could not be saved" in result["error"]
    assert len(phone.writes) == 1
    assert Path(result["undo_backup"]).is_file()


def test_interrupted_checked_restore_keeps_reverse_candidate(phone, monkeypatch):
    receipt = ok(run("apply-checked", stdin=json.dumps(_checked_request())))["recovery"]
    original_write = phone.write_layout

    def restored_then_disconnected(lockdown, state):
        original_write(lockdown, state)
        raise OSError("USB disconnected after restore")

    monkeypatch.setattr(device, "write_layout", restored_then_disconnected)
    failure = failed(run("restore-checked", stdin=json.dumps(receipt)))
    assert "Checked restore failed" in failure["error"]
    reverse = next(record for record in ok(run("pending-checked"))["records"]
                   if record.get("operation") == "restore")
    assert reverse["journal"] == failure["journal"]
    assert ok(run("check-recovery", stdin=json.dumps(reverse["recovery"])))["eligible_for_restore_attempt"] is True
    assert len(phone.writes) == 2


@pytest.mark.parametrize("tamper", ["missing", "hash", "source", "device", "applied", "backup_bytes", "current_state"])
def test_checked_restore_refuses_tampering_before_a_second_backup(phone, tamper):
    receipt = ok(run("apply-checked", stdin=json.dumps(_checked_request())), APPLIED_TRANSFORM)["recovery"]
    if tamper == "missing":
        del receipt["device_id_sha256"]
    elif tamper == "hash":
        receipt["backup_sha256"] = "0" * 64
    elif tamper == "source":
        receipt["source_raw_sha256"] = "0" * 64
    elif tamper == "device":
        receipt["device_id_sha256"] = "0" * 64
    elif tamper == "applied":
        receipt["applied_raw_sha256"] = "0" * 64
    elif tamper == "backup_bytes":
        Path(receipt["backup"]).write_text(Path(receipt["backup"]).read_text() + " ")
    elif tamper == "current_state":
        phone.raw[1][0]["unused_metadata"] = "after apply"
    result = failed(run("restore-checked", stdin=json.dumps(receipt)))
    assert "Not restored" in result["error"]
    assert len(phone.writes) == 1
    assert len(phone.backups()) == 1


def test_checked_restore_refuses_drift_after_backup(phone, monkeypatch):
    receipt = ok(run("apply-checked", stdin=json.dumps(_checked_request())), APPLIED_TRANSFORM)["recovery"]
    reads = []

    def drifting_read(lockdown):
        reads.append(1)
        if len(reads) == 3:
            phone.raw[1][0]["unused_metadata"] = "after backup"
        return phone.read_layout(lockdown)

    monkeypatch.setattr(device, "read_layout", drifting_read)
    result = failed(run("restore-checked", stdin=json.dumps(receipt)))
    assert "after backup" in result["error"]
    assert len(phone.backups()) == 2
    assert len(phone.writes) == 1


def test_checked_restore_refuses_an_actual_device_swap(phone, monkeypatch):
    receipt = ok(run("apply-checked", stdin=json.dumps(_checked_request())), APPLIED_TRANSFORM)["recovery"]
    monkeypatch.setattr(device, "connect", lambda: (
        "LOCKDOWN", DeviceInfo(name="Other iPhone", model="iPhone18,4", ios_version="26.0", udid="OTHER")
    ))
    result = failed(run("restore-checked", stdin=json.dumps(receipt)))
    assert "different or unidentified iPhone" in result["error"]
    assert len(phone.writes) == 1 and len(phone.backups()) == 1


def test_checked_restore_write_failure_retains_recovery_backup_without_retry(phone):
    receipt = ok(run("apply-checked", stdin=json.dumps(_checked_request())), APPLIED_TRANSFORM)["recovery"]
    phone.write_error = RuntimeError("USB disconnected")
    result = failed(run("restore-checked", stdin=json.dumps(receipt)))
    assert "Checked restore failed" in result["error"]
    assert Path(result["undo_backup"]).is_file()
    assert len(phone.writes) == 1


def test_checked_restore_rejects_raw_only_readback_drift_without_retry(phone):
    receipt = ok(run("apply-checked", stdin=json.dumps(_checked_request())), APPLIED_TRANSFORM)["recovery"]

    def add_unreviewed_metadata(state):
        changed = copy.deepcopy(state)
        changed[1][0]["unused_metadata"] = "normalized after restore"
        return changed

    phone.keep = add_unreviewed_metadata
    result = failed(run("restore-checked", stdin=json.dumps(receipt)))
    assert "raw icon state differs" in result["error"]
    assert Path(result["undo_backup"]).is_file()
    assert len(phone.writes) == 2


@pytest.mark.parametrize("tamper", ["missing_proposal", "wrong_proposal", "missing_raw", "wrong_raw", "missing_destination_raw", "wrong_destination_raw", "changed_operation", "stale_scan", "raw_only_drift"])
def test_checked_apply_refuses_unreviewed_or_stale_input_before_backup(phone, tamper):
    request = _checked_request()
    if tamper == "missing_proposal":
        del request["proposed_snapshot_id"]
    elif tamper == "wrong_proposal":
        request["proposed_snapshot_id"] = "not the checked layout"
    elif tamper == "missing_raw":
        del request["source_raw_sha256"]
    elif tamper == "wrong_raw":
        request["source_raw_sha256"] = "0" * 64
    elif tamper == "missing_destination_raw":
        del request["proposed_raw_sha256"]
    elif tamper == "wrong_destination_raw":
        request["proposed_raw_sha256"] = "0" * 64
    elif tamper == "changed_operation":
        request["operations"][0]["target_page"] = 42
    elif tamper == "stale_scan":
        _remove_app(phone.raw, _first_moved_app(_focus_preview()))
    elif tamper == "raw_only_drift":
        phone.raw[1][0]["unused_metadata"] = "new"

    failed(run("apply-checked", stdin=json.dumps(request)))
    assert phone.writes == []
    assert phone.backups() == []


def test_checked_apply_rejects_unreviewed_destination_metadata_before_backup(phone, monkeypatch):
    request = _checked_request()
    prepare = cli._prepare_write

    def altered_destination(layout, operations):
        raw, predicted, problem = prepare(layout, operations)
        raw[1][0]["unused_metadata"] = "unreviewed destination"
        return raw, predicted, problem

    monkeypatch.setattr(cli, "_prepare_write", altered_destination)
    result = failed(run("apply-checked", stdin=json.dumps(request)))
    assert "proposed raw icon state" in result["error"]
    assert phone.writes == [] and phone.backups() == []


def test_checked_apply_refuses_drift_after_backup(phone, monkeypatch):
    request = _checked_request()
    before = copy.deepcopy(phone.raw)
    reads = []

    def drifting_read(lockdown):
        reads.append(1)
        if len(reads) == 3:
            phone.raw[1][0]["unused_metadata"] = "changed after backup"
        return phone.read_layout(lockdown)

    monkeypatch.setattr(device, "read_layout", drifting_read)
    result = failed(run("apply-checked", stdin=json.dumps(request)))

    assert "after the backup" in result["error"]
    assert len(phone.backups()) == 1
    assert json.loads(phone.backups()[0].read_text()) == json.loads(json.dumps(before, default=str))
    assert phone.writes == []


def test_checked_apply_refuses_unparsed_state(phone):
    phone.raw[-1].append({"listType": "unsupported"})
    snapshot = ok(run("scan"), PHONE_DATA)["snapshot_id"]
    request = {"operations": [{"action": "move_to_page", "bundle_ids": ["com.example.library-only"], "target_page": 1}],
               "snapshot_id": snapshot, "source_raw_sha256": cli._raw_state_fingerprint(phone.read_layout("LOCKDOWN")),
               "proposed_snapshot_id": "some destination", "proposed_raw_sha256": "0" * 64}
    result = failed(run("apply-checked", stdin=json.dumps(request)))
    assert "complete icon-state structure" in result["error"]
    assert phone.writes == [] and phone.backups() == []


def test_checked_apply_refuses_app_library_source(phone):
    snapshot = ok(run("scan"), PHONE_DATA)["snapshot_id"]
    request = {"operations": [{"action": "move_to_page", "bundle_ids": ["com.example.library-only"], "target_page": 1}],
               "snapshot_id": snapshot, "source_raw_sha256": cli._raw_state_fingerprint(phone.read_layout("LOCKDOWN")),
               "proposed_snapshot_id": "some destination", "proposed_raw_sha256": "0" * 64}
    result = failed(run("apply-checked", stdin=json.dumps(request)))
    assert "not on the home screen" in result["error"]
    assert phone.writes == [] and phone.backups() == []


def test_checked_apply_preserves_backup_on_readback_mismatch(phone):
    request = _checked_request()
    phone.keep = lambda state: state[:1] + [list(reversed(state[1]))] + state[2:]
    result = failed(run("apply-checked", stdin=json.dumps(request)))
    assert "verification failed" in result["error"]
    assert len(phone.writes) == 1 and len(phone.backups()) == 1
    assert result["backup"] == str(phone.backups()[0])


def test_checked_apply_rejects_raw_only_readback_drift_without_receipt(phone):
    request = _checked_request()

    def add_unreviewed_metadata(state):
        changed = copy.deepcopy(state)
        changed[1][0]["unused_metadata"] = "normalized after apply"
        return changed

    phone.keep = add_unreviewed_metadata
    result = failed(run("apply-checked", stdin=json.dumps(request)))
    assert "raw icon state does not match" in result["error"]
    assert "recovery" not in result
    assert Path(result["backup"]).is_file()
    assert len(phone.writes) == 1


def test_apply_writes_once_and_returns_the_backup(phone):
    before = copy.deepcopy(phone.raw)
    preview = _focus_preview()
    assert preview["operations"]

    payload = ok(run("apply", stdin=app_payload(preview["operations"], preview["snapshot_id"])), APPLIED_TRANSFORM)

    assert payload["changed"] is True
    assert payload["applied"] >= 1
    # One write: the change. There is no round trip (a second write of the same layout).
    assert len(phone.writes) == 1
    # The backup is on disk before the write, and it holds the layout from before it.
    backup = Path(payload["backup"])
    assert phone.backups() == [backup]
    assert json.loads(backup.read_text()) == json.loads(json.dumps(before, default=str))
    # The phone reads back as the preview.
    assert payload["result"]["page_count"] == preview["proposed_layout"]["page_count"]
    assert payload["result"]["total_apps"] == preview["proposed_layout"]["total_apps"]


def test_apply_aborts_if_layout_drifts_during_backup(phone, monkeypatch):
    preview = _focus_preview()
    before = copy.deepcopy(phone.raw)
    reads = []

    def drifting_read(lockdown):
        reads.append(1)
        if len(reads) == 2:
            phone.raw = phone.raw[:1] + [list(reversed(phone.raw[1]))] + phone.raw[2:]
        return phone.read_layout(lockdown)

    monkeypatch.setattr(device, "read_layout", drifting_read)

    result = run("apply", stdin=app_payload(preview["operations"]))

    assert result.exit_code == 1
    assert "Device layout changed" in json.loads(result.stdout)["error"]
    assert "No changes made" in result.stderr
    assert phone.writes == []
    assert len(phone.backups()) == 1
    assert json.loads(phone.backups()[0].read_text()) == json.loads(json.dumps(before, default=str))


def _remove_app(raw: list, bundle_id: str) -> None:
    """Take the app off the phone (the owner deleted it), from the pages and folders."""
    for page in raw:
        page[:] = [e for e in page if not (isinstance(e, dict) and e.get("bundleIdentifier") == bundle_id)]
        for entry in page:
            if isinstance(entry, dict) and isinstance(entry.get("iconLists"), list):
                entry["iconLists"] = [
                    [f for f in folder_page if not (isinstance(f, dict) and f.get("bundleIdentifier") == bundle_id)]
                    for folder_page in entry["iconLists"]
                ]


def _first_moved_app(preview: dict) -> str:
    return next(op["bundle_ids"][0] for op in preview["operations"] if op["action"] == "move_to_page")


def test_apply_with_the_snapshot_id_of_the_presets(phone):
    presets = ok(run("presets"), PRESETS_RESPONSE)
    focus = presets["presets"]["focus"]

    payload = ok(run("apply", stdin=app_payload(focus["operations"], presets["snapshot_id"])), APPLIED_TRANSFORM)

    assert payload["changed"] is True


@pytest.mark.parametrize("change", ["app_removed", "app_added"])
def test_apply_after_the_phone_changed_since_the_preview_writes_nothing(phone, change):
    preview = _focus_preview()
    if change == "app_removed":
        _remove_app(phone.raw, _first_moved_app(preview))
    else:
        phone.raw[-1].append({"bundleIdentifier": "com.owner.new-app", "displayIdentifier": "com.owner.new-app"})

    payload = failed(run("apply", stdin=app_payload(preview["operations"], preview["snapshot_id"])))

    assert payload["error"] == (
        "Not written: the layout on the iPhone changed since the preview. Make a new preview."
    )
    assert "backup" not in payload
    assert phone.writes == []
    assert phone.backups() == []


def test_apply_that_names_an_app_that_is_not_on_the_phone_writes_nothing(phone):
    # A client that sends no snapshot_id: the check of the new icon state still refuses
    # the made-up entry for an app that left the phone after the preview.
    preview = _focus_preview()
    moved = _first_moved_app(preview)
    _remove_app(phone.raw, moved)

    payload = failed(run("apply", stdin=app_payload(preview["operations"])))

    assert payload["error"].startswith(f"Not written: the operations name {moved}, which is not on the home screen")
    assert phone.writes == []


def test_apply_that_changes_nothing_still_returns_a_backup(phone):
    before = copy.deepcopy(phone.raw)
    operations = [{"action": "move_to_app_library", "bundle_ids": ["com.example.not-on-this-phone"]}]

    payload = ok(run("apply", stdin=app_payload(operations)), APPLIED_TRANSFORM)

    assert payload["changed"] is False
    assert payload["applied"] == 0
    assert phone.writes == []
    # Undo restores the layout that the phone already has.
    assert json.loads(Path(payload["backup"]).read_text()) == json.loads(json.dumps(before, default=str))


def test_apply_that_the_check_refuses_writes_and_backs_up_nothing(phone, monkeypatch):
    preview = _focus_preview()
    monkeypatch.setattr(
        layout_engine, "check_write",
        lambda layout, ops: (layout.raw, HomeScreenLayout(dock=[], pages=[]), "the write would remove Maps, which no operation names"),
    )

    payload = failed(run("apply", stdin=app_payload(preview["operations"])))

    assert payload["error"] == "Not written: the write would remove Maps, which no operation names. No changes made."
    assert phone.writes == []
    assert phone.backups() == []


def test_apply_that_the_phone_does_not_take_names_the_backup(phone):
    before = copy.deepcopy(phone.raw)
    phone.keep = lambda state: before  # SpringBoard ignores the write
    preview = _focus_preview()

    payload = failed(run("apply", stdin=app_payload(preview["operations"])))

    assert payload["error"].startswith("Write verification failed")
    assert payload["backup"] == str(phone.backups()[0])
    assert payload["backup"] in payload["error"]
    assert len(phone.writes) == 1


def test_apply_with_a_write_error_names_the_backup(phone):
    phone.write_error = OSError("USB connection lost")
    preview = _focus_preview()

    payload = failed(run("apply", stdin=app_payload(preview["operations"])))

    assert "USB connection lost" in payload["error"]
    assert payload["backup"] == str(phone.backups()[0])


def test_apply_with_a_failed_backup_writes_nothing(phone, monkeypatch):
    preview = _focus_preview()

    def broken_backup(*_args, **_kwargs):
        raise RuntimeError("Backup verification failed: saved file doesn't match device state")

    monkeypatch.setattr(safety, "verified_backup", broken_backup)

    payload = failed(run("apply", stdin=app_payload(preview["operations"])))

    assert payload["error"].startswith("Backup failed:")
    assert phone.writes == []


@pytest.mark.parametrize("stdin", [
    None,
    "",
    "not json",
    "[]",
    '{"operations": []}',
    '{"operations": {"action": "delete"}}',
    '{"operations": [{"bundle_ids": ["com.apple.Maps"]}]}',
    '{"operations": ["delete"]}',
])
def test_apply_with_bad_input_writes_nothing(phone, stdin):
    failed(run("apply", stdin=stdin))

    assert phone.writes == []
    assert phone.backups() == []


@pytest.mark.parametrize("field, value", [
    ("target_page", "1"),
    ("target_page", 1.5),
    ("target_page", True),
    ("bundle_ids", [["com.owner.app100"]]),
    ("bundle_ids", "com.owner.app100"),
    ("folder_name", 5),
    ("old_name", ["Work"]),
    ("gratitude", {"text": "thanks"}),
])
def test_apply_with_a_wrong_type_writes_nothing(phone, field, value):
    operation = {"action": "move_to_page", "bundle_ids": ["com.owner.app100"], "target_page": 1, field: value}

    payload = failed(run("apply", stdin=json.dumps({"operations": [operation]})))

    assert payload["error"].startswith("Invalid operation:")
    assert f'"{field}"' in payload["error"]
    assert phone.writes == []
    assert phone.backups() == []


@pytest.mark.parametrize("snapshot_id", [5, ["x"], {"a": 1}])
def test_apply_with_a_snapshot_id_that_is_not_text_writes_nothing(phone, snapshot_id):
    operations = [{"action": "move_to_page", "bundle_ids": ["com.owner.app100"], "target_page": 1}]

    failed(run("apply", stdin=json.dumps({"operations": operations, "snapshot_id": snapshot_id})))

    assert phone.writes == []


def test_an_unexpected_error_is_a_json_document(phone, monkeypatch):
    def broken(_layout, _ops):
        raise KeyError("iconLists")

    monkeypatch.setattr(layout_engine, "check_write", broken)
    operations = [{"action": "move_to_page", "bundle_ids": ["com.owner.app100"], "target_page": 1}]

    payload = failed(run("apply", stdin=app_payload(operations)))

    assert payload["error"] == "Unexpected error: KeyError: 'iconLists'"
    assert "Traceback" in run("apply", stdin=app_payload(operations)).stderr
    assert phone.writes == []


def test_apply_with_the_phone_not_connected(phone):
    phone.connected = False
    preview_operations = [{"action": "move_to_app_library", "bundle_ids": ["com.owner.app100"]}]

    payload = failed(run("apply", stdin=app_payload(preview_operations)))

    assert payload["error"] == "No iPhone detected"


# --- restore ----------------------------------------------------------------------------


def _changed_phone(phone) -> tuple[list, Path]:
    """Save a backup of the phone, then change the phone. Returns (the raw state of the
    backup, its path)."""
    before = copy.deepcopy(phone.raw)
    backup = phone.home / "layout-before.json"
    backup.write_text(json.dumps(before, indent=2, default=str))
    phone.raw = before[:-1]  # the last page is gone
    return json.loads(backup.read_text()), backup


def _as_backup(state) -> list:
    """The state as a backup file holds it: dates as text."""
    return json.loads(json.dumps(state, default=str))


def _icon_dates(state) -> list:
    dates = []
    for page in state:
        for entry in page:
            if isinstance(entry, dict):
                if "iconModDate" in entry:
                    dates.append(entry["iconModDate"])
                for folder_page in entry.get("iconLists") or []:
                    dates.extend(f["iconModDate"] for f in folder_page if isinstance(f, dict) and "iconModDate" in f)
    return dates


def test_restore(phone):
    expected, backup = _changed_phone(phone)
    changed = copy.deepcopy(phone.raw)

    payload = ok(run("restore", str(backup)), RESTORED_LAYOUT)

    assert payload["restored"] is True
    assert payload["backup"] == str(backup)
    assert len(phone.writes) == 1
    assert _as_backup(phone.writes[0]) == expected
    assert _as_backup(phone.raw) == expected
    # Before the write, a verified backup of the layout on the phone then, for undo.
    undo_backup = Path(payload["undo_backup"])
    assert phone.backups() == [undo_backup]
    assert json.loads(undo_backup.read_text()) == _as_backup(changed)


def test_restore_writes_the_dates_of_the_backup_as_dates(phone):
    _expected, backup = _changed_phone(phone)

    ok(run("restore", str(backup)), RESTORED_LAYOUT)

    dates = _icon_dates(phone.writes[0])
    assert dates, "the phone has icon dates"
    # The phone gave a date (a plist <date>), and a restore must send a date too, not
    # the text of the JSON file.
    assert all(isinstance(date, datetime) for date in dates)
    assert str(dates[0]) == "2026-01-01 00:00:00"


def test_undo_of_an_apply_in_the_same_second_keeps_both_backups(phone, monkeypatch):
    class OneSecond(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 25, 15, 40, 39)

    monkeypatch.setattr(safety, "datetime", OneSecond)
    preview = _focus_preview()
    applied = ok(run("apply", stdin=app_payload(preview["operations"], preview["snapshot_id"])), APPLIED_TRANSFORM)

    undone = ok(run("restore", applied["backup"]), RESTORED_LAYOUT)

    assert undone["undo_backup"] != applied["backup"]
    assert len(phone.backups()) == 2
    # The backup of the apply still holds the layout from before the apply.
    assert _as_backup(phone.raw) == json.loads(Path(applied["backup"]).read_text())


@pytest.mark.parametrize("content", ["[]", "{}", "[[]]", "[[], []]", '{"iconLists": []}'])
def test_restore_refuses_a_backup_with_no_apps(phone, content):
    before = copy.deepcopy(phone.raw)
    backup = phone.home / "layout-empty.json"
    backup.write_text(content)

    payload = failed(run("restore", str(backup)))

    assert payload["error"] == f"Not restored: the backup {backup} has no apps on the home screen. No changes made."
    assert phone.writes == []
    assert phone.backups() == []
    assert phone.raw == before


def test_restore_with_a_failed_backup_writes_nothing(phone, monkeypatch):
    _expected, backup = _changed_phone(phone)

    def broken_backup(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(safety, "verified_backup", broken_backup)

    payload = failed(run("restore", str(backup)))

    assert payload["error"] == "Backup failed: disk full. No changes made."
    assert phone.writes == []


def test_restore_accepts_values_that_springboard_changes(phone):
    expected, backup = _changed_phone(phone)

    def new_icon_dates(state):
        state = copy.deepcopy(state)
        for page in state:
            for entry in page:
                if isinstance(entry, dict) and "iconModDate" in entry:
                    entry["iconModDate"] = "2026-09-25 00:00:00"
        return state

    phone.keep = new_icon_dates

    payload = ok(run("restore", str(backup)), RESTORED_LAYOUT)

    assert payload["restored"] is True
    assert phone.raw != expected


def test_restore_fails_when_the_layout_differs(phone):
    _expected, backup = _changed_phone(phone)
    phone.keep = lambda state: state[:-1]

    payload = failed(run("restore", str(backup)))

    assert payload["error"].startswith("Restore verification failed")
    assert payload["undo_backup"] == str(phone.backups()[0])
    assert payload["error"].endswith(f"To undo, restore {payload['undo_backup']}.")


def test_restore_with_a_write_error(phone):
    _expected, backup = _changed_phone(phone)
    phone.write_error = OSError("USB connection lost")

    payload = failed(run("restore", str(backup)))

    assert "USB connection lost" in payload["error"]
    assert payload["undo_backup"] == str(phone.backups()[0])


def test_restore_with_a_missing_file(phone):
    missing = phone.home / ".unjiggle" / "backups" / "layout-gone.json"

    payload = failed(run("restore", str(missing)))

    assert payload["error"] == f"Backup not found: {missing}"
    assert phone.writes == []


def test_restore_with_a_file_that_is_not_a_backup(phone):
    backup = phone.home / "not-a-backup.json"
    backup.write_text("not json")

    failed(run("restore", str(backup)))

    assert phone.writes == []


# --- apps that iOS adds at a write --------------------------------------------------------
# On the owner's iPhone (iOS 26.0), SpringBoard added an installed app from the App Library
# (Amazon) to the home screen after the write of json apply, and again after the undo. See
# tests/fake_springboard.py.

AMAZON = UNLISTED_APP["bundleIdentifier"]
WRITE_CHECK_FAILED = {"apply": "Write verification failed", "restore": "Restore verification failed"}


def _write(phone, command: str):
    """Run a command that writes: json apply of the focus preset, or json restore of a
    backup after a change of the phone."""
    if command == "apply":
        preview = _focus_preview()
        return run("apply", stdin=app_payload(preview["operations"], preview["snapshot_id"]))
    _expected, backup = _changed_phone(phone)
    return run("restore", str(backup))


def _loose_apps(state: list) -> list[tuple[int, int]]:
    """(page index, entry index) of each loose App Store app on the pages of a raw state,
    but not the app that iOS adds."""
    return [
        (page_index, entry_index)
        for page_index, page in enumerate(state)
        if page_index > 0
        for entry_index, entry in enumerate(page)
        if device.is_app_store_entry(entry) and device.entry_app_id(entry) != AMAZON
    ]


def _single_icon_app(state: list) -> dict:
    """A loose App Store app entry with no other icon of its app on the home screen."""
    icons = device.parse_layout_state(copy.deepcopy(state)).all_bundle_ids
    for page_index, entry_index in reversed(_loose_apps(state)):
        entry = state[page_index][entry_index]
        if icons.count(device.entry_app_id(entry)) == 1:
            return entry
    raise AssertionError("the phone has no app with one icon")


def test_apply_passes_when_ios_adds_an_app_from_the_app_library(phone):
    phone.keep = adds_unlisted_app
    preview = _focus_preview()

    result = run("apply", stdin=app_payload(preview["operations"], preview["snapshot_id"]))

    payload = ok(result, APPLIED_TRANSFORM)
    page = page_of(phone.raw, AMAZON)
    assert payload["changed"] is True
    assert payload["ios_added"] == [{"bundle_id": AMAZON, "name": "Amazon", "page": page}]
    assert f"iOS added an app that the preview does not have: Amazon (page {page})." in result.stderr
    # One write, with no entry for the app. The command did not move or remove the app.
    assert len(phone.writes) == 1
    assert AMAZON not in device.parse_layout_state(phone.writes[0]).all_bundle_ids
    assert without_app(phone.raw, AMAZON) == phone.writes[0]
    # The output tells what the phone has now, with the app.
    assert payload["result"]["total_apps"] == preview["proposed_layout"]["total_apps"] + 1
    assert payload["snapshot_id"] == cli._layout_signature(device.parse_layout_state(phone.raw))


def test_restore_passes_when_ios_adds_an_app_from_the_app_library(phone):
    expected, backup = _changed_phone(phone)
    phone.keep = adds_unlisted_app

    result = run("restore", str(backup))

    payload = ok(result, RESTORED_LAYOUT)
    page = page_of(phone.raw, AMAZON)
    assert payload["restored"] is True
    assert payload["ios_added"] == [{"bundle_id": AMAZON, "name": "Amazon", "page": page}]
    assert f"iOS added an app that the backup does not have: Amazon (page {page})." in result.stderr
    assert len(phone.writes) == 1
    assert _as_backup(phone.writes[0]) == expected
    assert _as_backup(without_app(phone.raw, AMAZON)) == expected


def test_apply_and_undo_pass_when_ios_adds_the_app_at_each_write(phone):
    # The finding on the owner's iPhone. After the apply, the app is on the home screen.
    # The undo writes the backup, which does not have the app, and iOS adds the app
    # again. json restore compares with the backup only, so the undo passes.
    before = _as_backup(phone.raw)
    phone.keep = adds_unlisted_app
    preview = _focus_preview()

    applied = ok(run("apply", stdin=app_payload(preview["operations"], preview["snapshot_id"])), APPLIED_TRANSFORM)
    assert [app["bundle_id"] for app in applied["ios_added"]] == [AMAZON]

    undone = ok(run("restore", applied["backup"]), RESTORED_LAYOUT)

    assert undone["ios_added"] == [{"bundle_id": AMAZON, "name": "Amazon", "page": page_of(phone.raw, AMAZON)}]
    assert _as_backup(without_app(phone.raw, AMAZON)) == before
    assert len(phone.writes) == 2


def test_apply_names_each_app_that_ios_adds(phone):
    news = {**UNLISTED_APP, "bundleIdentifier": "com.example.news", "displayIdentifier": "com.example.news",
            "displayName": "News [Daily]"}
    deals = {**UNLISTED_APP, "bundleIdentifier": "com.example.deals", "displayIdentifier": "com.example.deals",
             "displayName": "Deals :fire:"}
    phone.keep = lambda state: adds_unlisted_app(adds_unlisted_app(adds_unlisted_app(state), news), deals)

    result = _write(phone, "apply")

    payload = ok(result, APPLIED_TRANSFORM)
    assert [(app["bundle_id"], app["name"]) for app in payload["ios_added"]] == [
        (AMAZON, "Amazon"), ("com.example.news", "News [Daily]"), ("com.example.deals", "Deals :fire:"),
    ]
    # The names come from the phone. They are not read as Rich markup or emoji codes.
    assert "iOS added 3 apps that the preview does not have: Amazon (page " in result.stderr
    assert "News [Daily] (page " in result.stderr
    assert "Deals :fire: (page " in result.stderr


def test_apply_with_no_app_that_ios_adds_has_no_ios_added_key(phone):
    payload = ok(_write(phone, "apply"), APPLIED_TRANSFORM)

    assert "ios_added" not in payload


@pytest.mark.parametrize("command", ["apply", "restore"])
def test_the_check_fails_when_ios_adds_a_second_icon_of_an_app(phone, command):
    # The app is already on the home screen, in another place.
    def second_icon(state):
        return put_in_first_free_slot(state, {**_single_icon_app(state), "displayIdentifier": "UUID-NEW"})

    phone.keep = second_icon

    payload = failed(_write(phone, command))

    assert payload["error"].startswith(WRITE_CHECK_FAILED[command])
    assert "ios_added" not in payload
    assert len(phone.writes) == 1


@pytest.mark.parametrize("command", ["apply", "restore"])
def test_the_check_fails_when_the_phone_ignores_the_write(phone, command):
    # The owner put an app on the home screen after the backup (or after the preview),
    # and SpringBoard ignores the write. The phone then differs from the backup only by
    # a loose app in the first free slot, as an app that iOS adds. But the phone reads
    # back the layout that it had before the write, so the write had no effect.
    backup = phone.home / "layout-before.json"
    backup.write_text(json.dumps(phone.raw, default=str))
    phone.raw = put_in_first_free_slot(phone.raw, {
        "bundleIdentifier": "com.example.userapp", "displayIdentifier": "com.example.userapp", "displayName": "UserApp",
    })
    unchanged = copy.deepcopy(phone.raw)
    phone.keep = lambda _state: copy.deepcopy(unchanged)

    if command == "apply":
        preview = _focus_preview()
        result = run("apply", stdin=app_payload(preview["operations"], preview["snapshot_id"]))
    else:
        result = run("restore", str(backup))

    payload = failed(result)
    assert payload["error"].startswith(WRITE_CHECK_FAILED[command])
    assert "ios_added" not in payload
    assert "iOS added" not in result.stderr
    assert len(phone.writes) == 1
    assert phone.raw == unchanged


def test_apply_fails_when_the_phone_puts_back_an_app_that_an_operation_took_off(phone):
    # The app was on the home screen before the write, so iOS did not add it: the write
    # did not do what the preview shows.
    entry = _single_icon_app(phone.raw)
    bundle_id = device.entry_app_id(entry)
    phone.keep = lambda state: put_in_first_free_slot(state, entry)
    operations = [{"action": "move_to_app_library", "bundle_ids": [bundle_id]}]

    payload = failed(run("apply", stdin=app_payload(operations)))

    assert payload["error"].startswith("Write verification failed")
    assert payload["backup"] == str(phone.backups()[0])
    assert bundle_id not in device.parse_layout_state(phone.writes[0]).all_bundle_ids


def _drop(state):
    page_index, entry_index = _loose_apps(state)[-1]
    del state[page_index][entry_index]


def _move(state):
    # The first loose app goes to the end of the last page.
    page_index, entry_index = _loose_apps(state)[0]
    state[-1].append(state[page_index].pop(entry_index))


def _reorder(state):
    places = _loose_apps(state)
    for (page_a, index_a), (page_b, index_b) in zip(places, places[1:]):
        a, b = state[page_a][index_a], state[page_b][index_b]
        if page_a == page_b and device.entry_app_id(a) != device.entry_app_id(b):
            state[page_a][index_a], state[page_b][index_b] = b, a
            return
    raise AssertionError("no two apps to swap")


@pytest.mark.parametrize("command", ["apply", "restore"])
@pytest.mark.parametrize("change", [_drop, _move, _reorder], ids=["dropped", "moved", "reordered"])
def test_the_check_fails_when_an_expected_entry_changes_and_ios_adds_an_app(phone, command, change):
    def keep(state):
        state = adds_unlisted_app(state)
        change(state)
        return state

    phone.keep = keep

    payload = failed(_write(phone, command))

    assert payload["error"].startswith(WRITE_CHECK_FAILED[command])
    assert "ios_added" not in payload


def _in_dock(state):
    state[0].append(copy.deepcopy(UNLISTED_APP))
    return state


def _in_a_folder(state):
    folder = next(entry for page in state[1:] for entry in page if device.is_folder_entry(entry))
    folder["iconLists"][0].append(copy.deepcopy(UNLISTED_APP))
    return state


@pytest.mark.parametrize("command", ["apply", "restore"])
@pytest.mark.parametrize("keep", [
    lambda state: put_in_first_free_slot(state, {
        "widgetIdentifier": "com.w.new.w", "iconLists": [], "elementType": "widget", "containerBundleIdentifier": "com.w.new",
        "bundleIdentifier": "com.w.new.ext", "displayIdentifier": "W-new", "gridSize": "small", "iconType": "custom"}),
    lambda state: put_in_first_free_slot(state, {"displayIdentifier": "com.apple.webapp.new", "displayName": "Web"}),
    lambda state: put_in_first_free_slot(state, {
        "displayName": "New", "listType": "folder", "iconLists": [[copy.deepcopy(UNLISTED_APP)]]}),
    lambda state: _in_dock(copy.deepcopy(state)),
    lambda state: _in_a_folder(copy.deepcopy(state)),
    # The parser shows these two entries as apps, because they have a bundleIdentifier.
    lambda state: put_in_first_free_slot(state, {
        "iconType": "custom", "bundleIdentifier": "com.x.thing", "displayIdentifier": "T1"}),
    lambda state: put_in_first_free_slot(state, {
        **UNLISTED_APP, "displayIdentifier": "UUID-NEW", "iconType": "app", "iconLists": []}),
], ids=["widget", "pinned-icon", "folder", "app-in-the-dock", "app-in-a-folder", "custom-entry-with-a-bundle-id",
        "second-icon-shape"])
def test_the_check_fails_when_the_phone_adds_an_entry_that_is_not_a_loose_app(phone, command, keep):
    phone.keep = keep

    payload = failed(_write(phone, command))

    assert payload["error"].startswith(WRITE_CHECK_FAILED[command])
    assert "ios_added" not in payload


# --- the app's flow in a real process ---------------------------------------------------


def _phone_files(tmp_path: Path, source: str) -> tuple[list, dict]:
    if source == "real":
        path = os.environ.get("UNJIGGLE_REAL_BACKUP")
        if not path:
            pytest.skip("set UNJIGGLE_REAL_BACKUP to the path of an icon state backup")
        raw = json.loads(Path(path).read_text())
        metadata_path = os.environ.get("UNJIGGLE_REAL_METADATA")
        metadata = json.loads(Path(metadata_path).read_text()) if metadata_path else {}
        return raw, metadata
    layout, metadata = owner_shaped_phone()
    return json.loads(json.dumps(layout.raw, default=str)), metadata


def _process(
    tmp_path: Path, *args: str, stdin: str | None = None, ios_adds: dict | None = None,
) -> subprocess.CompletedProcess:
    """`unjiggle json <args>` in a new process, as the Mac app starts it: stdin is a pipe
    that holds only the payload and is then closed, or /dev/null. With ``ios_adds``, the
    phone adds that app at each write that does not have it (FAKE_PHONE_IOS_ADDS)."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FAKE_PHONE_IOS_ADDS")}
    if ios_adds is not None:
        env["FAKE_PHONE_IOS_ADDS"] = json.dumps(ios_adds)
    env.update(
        HOME=str(tmp_path),
        PYTHONPATH=os.pathsep.join([str(SRC), str(TESTS.parent)]),
        PYTHONDONTWRITEBYTECODE="1",
        FAKE_PHONE_STATE=str(tmp_path / "phone.json"),
        FAKE_PHONE_METADATA=str(tmp_path / "metadata.json"),
        FAKE_PHONE_WRITES=str(tmp_path / "writes.log"),
        FAKE_PHONE_BACKUPS=str(tmp_path / "backups"),
    )
    return subprocess.run(
        [sys.executable, str(TESTS / "fake_phone_cli.py"), "json", *args],
        input=stdin,
        stdin=None if stdin is not None else subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


def _process_ok(completed: subprocess.CompletedProcess, model) -> dict:
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout
    assert out.endswith("\n") and out.count("\n") == 1, f"stdout must be one JSON line, got {out[:300]!r}"
    payload = json.loads(out)
    decodes(payload, model)
    return payload


@pytest.mark.parametrize("preset", PRESET_CHOICES)
@pytest.mark.parametrize("source", ["synthetic", "real"])
def test_preview_apply_and_undo_in_a_process(tmp_path, source, preset):
    raw, metadata = _phone_files(tmp_path, source)
    state = tmp_path / "phone.json"
    state.write_text(json.dumps(raw))
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    writes = tmp_path / "writes.log"

    status = _process_ok(_process(tmp_path, "status"), DEVICE_STATUS)
    assert status["connected"] is True

    preview = _process_ok(_process(tmp_path, "suggest", "--preset", preset), TRANSFORM_PREVIEW)
    assert preview["operations"], f"{preset} has nothing to apply on this phone"

    # The app sends the snapshot_id of the preview. The phone has not changed, so the
    # apply must accept it.
    applied = _process(tmp_path, "apply", stdin=app_payload(preview["operations"], preview["snapshot_id"]))
    assert "Aborted" not in applied.stderr
    applied_payload = _process_ok(applied, APPLIED_TRANSFORM)
    assert applied_payload["changed"] is True
    assert writes.read_text().count("write") == 1
    assert applied_payload["result"]["page_count"] == preview["proposed_layout"]["page_count"]

    undo = _process_ok(_process(tmp_path, "restore", applied_payload["backup"]), RESTORED_LAYOUT)
    assert undo["restored"] is True
    assert writes.read_text().count("write") == 2
    assert json.loads(state.read_text()) == raw


def _unlisted_app(raw) -> dict:
    """The entry of an app that the phone does not have on the home screen: the app that
    iOS added on the owner's iPhone, or a made-up app when the phone has that one."""
    if AMAZON not in device.parse_layout_state(copy.deepcopy(raw)).all_bundle_ids:
        return copy.deepcopy(UNLISTED_APP)
    return {**UNLISTED_APP, "bundleIdentifier": "com.example.unlisted", "displayIdentifier": "com.example.unlisted",
            "displayName": "Unlisted"}


@pytest.mark.parametrize("preset", PRESET_CHOICES)
@pytest.mark.parametrize("source", ["synthetic", "real"])
def test_preview_apply_and_undo_in_a_process_when_ios_adds_an_app(tmp_path, source, preset):
    # The flow of the finding on the owner's iPhone: iOS adds an app at the apply and
    # again at the undo. Both commands pass, name the app, and leave it where iOS put it.
    raw, metadata = _phone_files(tmp_path, source)
    entry = _unlisted_app(raw)
    bundle_id = entry["bundleIdentifier"]
    state = tmp_path / "phone.json"
    state.write_text(json.dumps(raw))
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    writes = tmp_path / "writes.log"

    preview = _process_ok(_process(tmp_path, "suggest", "--preset", preset, ios_adds=entry), TRANSFORM_PREVIEW)
    assert preview["operations"], f"{preset} has nothing to apply on this phone"

    applied = _process(tmp_path, "apply", stdin=app_payload(preview["operations"], preview["snapshot_id"]), ios_adds=entry)
    applied_payload = _process_ok(applied, APPLIED_TRANSFORM)
    assert applied_payload["changed"] is True
    phone_now = json.loads(state.read_text())
    assert applied_payload["ios_added"] == [
        {"bundle_id": bundle_id, "name": entry["displayName"], "page": page_of(phone_now, bundle_id)},
    ]
    assert "iOS added an app that the preview does not have" in applied.stderr
    assert applied_payload["result"]["total_apps"] == preview["proposed_layout"]["total_apps"] + 1
    assert writes.read_text().count("write") == 1

    undo = _process(tmp_path, "restore", applied_payload["backup"], ios_adds=entry)
    undo_payload = _process_ok(undo, RESTORED_LAYOUT)
    assert undo_payload["restored"] is True
    assert [app["bundle_id"] for app in undo_payload["ios_added"]] == [bundle_id]
    assert "iOS added an app that the backup does not have" in undo.stderr
    assert writes.read_text().count("write") == 2
    assert without_app(json.loads(state.read_text()), bundle_id) == raw
