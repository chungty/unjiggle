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
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

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
PHONE_DATA = {
    "device": DEVICE_INFO, "total_apps": int, "page_count": int, "folder_count": int,
    "dock_items": int, "pages": ArrayOf(ArrayOf(LAYOUT_ITEM)),
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
APPLIED_TRANSFORM = {"applied": int, "backup": str, "result": LAYOUT_MUTATION_RESULT}
RESTORED_LAYOUT = {"restored": bool, "backup": str, "result": LAYOUT_MUTATION_RESULT}
RENDERED_CARD = {"success": bool, "action": str, "card": str, "html_path": str, "path": Opt(str)}
DEVICE_STATUS = {"connected": bool, "device_name": Opt(str), "model": Opt(str), "ios_version": Opt(str)}


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


CONTRACT_COMMANDS = {"status", "scan", "diagnose", "mirror", "obituary", "suggest", "presets", "restore", "render", "apply"}


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


def test_apply_sends_the_text_of_the_backup_to_stderr(phone, monkeypatch):
    preview = _focus_preview()
    reads = []

    def drifting_read(lockdown):
        # The phone changes after the first read, so the backup check warns.
        reads.append(1)
        if len(reads) == 2:
            phone.raw = phone.raw[:1] + [list(reversed(phone.raw[1]))] + phone.raw[2:]
        return phone.read_layout(lockdown)

    monkeypatch.setattr(device, "read_layout", drifting_read)

    result = run("apply", stdin=app_payload(preview["operations"]))

    ok(result, APPLIED_TRANSFORM)
    assert "device state changed between reads" in result.stderr


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


def test_restore(phone):
    expected, backup = _changed_phone(phone)

    payload = ok(run("restore", str(backup)), RESTORED_LAYOUT)

    assert payload["restored"] is True
    assert payload["backup"] == str(backup)
    assert phone.writes == [expected]
    assert phone.raw == expected


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


def test_restore_with_a_write_error(phone):
    _expected, backup = _changed_phone(phone)
    phone.write_error = OSError("USB connection lost")

    payload = failed(run("restore", str(backup)))

    assert "USB connection lost" in payload["error"]


def test_restore_with_a_file_that_is_not_a_backup(phone):
    backup = phone.home / "not-a-backup.json"
    backup.write_text("not json")

    failed(run("restore", str(backup)))

    assert phone.writes == []


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


def _process(tmp_path: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """`unjiggle json <args>` in a new process, as the Mac app starts it: stdin is a pipe
    that holds only the payload and is then closed, or /dev/null."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
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
