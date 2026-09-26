from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from unjiggle.cli import (
    _generate_all_preset_transforms,
    _generate_preset_transform,
    _preview_effective_operations,
    json as json_group,
)
from unjiggle.models import HomeScreenLayout


def _patch_device_stack(monkeypatch, layout, metadata):
    import unjiggle.device as device
    import unjiggle.itunes as itunes

    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: layout)
    monkeypatch.setattr(itunes, "enrich_layout", lambda current_layout: metadata)


def test_minimal_preset_truthfully_limits_visible_apps(chaotic_layout, sample_metadata):
    from unjiggle.scoring import compute_score

    score = compute_score(chaotic_layout, sample_metadata)
    payload = _generate_preset_transform("minimal", chaotic_layout, sample_metadata, score)

    assert payload["after_pages"] == 1
    assert payload["proposed_layout"]["page_count"] == 1
    assert len(payload["proposed_layout"]["pages"][0]) <= 24
    assert payload["archived"] > 0


def test_focus_preset_pushes_distractions_out_of_the_front(chaotic_layout, sample_metadata):
    from unjiggle.scoring import compute_score

    score = compute_score(chaotic_layout, sample_metadata)
    payload = _generate_preset_transform("focus", chaotic_layout, sample_metadata, score)

    page_lookup = {}
    for page_index, page in enumerate(payload["proposed_layout"]["pages"], start=1):
        for item in page:
            if item["type"] == "app":
                page_lookup[item["app"]["bundle_id"]] = page_index

    assert page_lookup["com.google.calendar"] == 1
    assert page_lookup["com.tinyspeck.chatlyio"] == 1
    assert page_lookup["com.notion.Notion"] == 1
    assert page_lookup["com.instagram.Instagram"] >= 3
    assert page_lookup["com.netflix.Netflix"] >= 3


def test_relax_preset_brings_leisure_forward_and_work_back(chaotic_layout, sample_metadata):
    from unjiggle.scoring import compute_score

    score = compute_score(chaotic_layout, sample_metadata)
    payload = _generate_preset_transform("relax", chaotic_layout, sample_metadata, score)

    page_lookup = {}
    for page_index, page in enumerate(payload["proposed_layout"]["pages"], start=1):
        for item in page:
            if item["type"] == "app":
                page_lookup[item["app"]["bundle_id"]] = page_index

    assert page_lookup["com.instagram.Instagram"] == 1
    assert page_lookup["com.netflix.Netflix"] == 1
    assert page_lookup["com.google.calendar"] >= 3
    assert page_lookup["com.notion.Notion"] >= 3
    assert page_lookup["com.tinyspeck.chatlyio"] >= 3


def test_beautiful_preset_sorts_known_categories_by_visual_order(chaotic_layout, sample_metadata):
    from unjiggle.cli import _CATEGORY_COLOR_ORDER
    from unjiggle.scoring import compute_score

    score = compute_score(chaotic_layout, sample_metadata)
    payload = _generate_preset_transform("beautiful", chaotic_layout, sample_metadata, score)
    order = {category: index for index, category in enumerate(_CATEGORY_COLOR_ORDER)}
    # Phone is in the dock and on page 1: it is fixed, so it stays in both places.
    fixed = chaotic_layout.fixed_ids()
    assert "com.apple.mobilephone" in fixed
    assert payload["proposed_layout"]["dock"] == payload["current_layout"]["dock"]

    seen_categories = []
    for page in payload["proposed_layout"]["pages"]:
        assert len(page) <= 24
        for item in page:
            if item["type"] != "app" or item["app"]["bundle_id"] in fixed:
                continue
            category = item["app"]["category"]
            if category != "Other":
                seen_categories.append(order[category])

    assert seen_categories == sorted(seen_categories)


def test_generate_all_preset_transforms_returns_every_preset(chaotic_layout, sample_metadata):
    from unjiggle.scoring import compute_score

    score = compute_score(chaotic_layout, sample_metadata)
    presets = _generate_all_preset_transforms(chaotic_layout, sample_metadata, score)

    assert set(presets) == {"focus", "relax", "minimal", "beautiful"}
    assert presets["minimal"]["after_pages"] == 1


def test_preview_effective_operations_drops_noops(clean_layout):
    from unjiggle.analyzer import LayoutOperation

    preview, effective_ops = _preview_effective_operations(
        clean_layout,
        [LayoutOperation(action="move_to_folder", bundle_ids=["com.apple.Maps"], folder_name="Missing")],
    )

    assert preview.page_count == clean_layout.page_count
    assert effective_ops == []


def test_json_render_score_preview_returns_generated_png(monkeypatch, clean_layout, sample_metadata, tmp_path):
    import unjiggle.archetypes as archetypes
    import unjiggle.render as render_mod
    import unjiggle.scoring as scoring
    import unjiggle.visualize as visualize
    import unjiggle.cli as cli

    _patch_device_stack(monkeypatch, clean_layout, sample_metadata)
    monkeypatch.setattr(cli, "UNJIGGLE_DIR", tmp_path)
    monkeypatch.setattr(scoring, "compute_score", lambda layout, metadata: scoring.ScoreBreakdown(90, 88, 87, 91))
    monkeypatch.setattr(archetypes, "assign_archetype", lambda layout, metadata: ("The Sorted One", "Clean enough"))
    monkeypatch.setattr(visualize, "generate_share_card", lambda *args, **kwargs: "<html>score</html>")
    monkeypatch.setattr(render_mod, "render_to_png", lambda html, png: png.write_bytes(b"png") or True)

    result = CliRunner().invoke(json_group, ["render", "--card", "score"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["card"] == "score"
    assert payload["action"] == "preview"
    assert payload["path"].endswith(".png")
    assert Path(payload["path"]).exists()


def test_json_presets_returns_batch_payload(monkeypatch, clean_layout, sample_metadata):
    import unjiggle.cli as cli

    _patch_device_stack(monkeypatch, clean_layout, sample_metadata)
    monkeypatch.setattr(
        cli,
        "_generate_all_preset_transforms",
        lambda layout, metadata, score: {
            "focus": {"intent": "focus"},
            "relax": {"intent": "relax"},
            "minimal": {"intent": "minimal"},
            "beautiful": {"intent": "beautiful"},
        },
    )

    result = CliRunner().invoke(json_group, ["presets"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["preset_order"] == ["focus", "relax", "minimal", "beautiful"]
    assert payload["presets"]["focus"]["intent"] == "focus"
    assert payload["layout_signature"] == payload["snapshot_id"]


def test_json_render_transform_requires_backup(monkeypatch, clean_layout, sample_metadata):
    _patch_device_stack(monkeypatch, clean_layout, sample_metadata)

    result = CliRunner().invoke(json_group, ["render", "--card", "transform"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"] == "--backup is required for transform cards."
    # The message also goes to stderr, for a client that reads only stderr on failure.
    assert result.stderr.strip() == "--backup is required for transform cards."


def test_json_apply_rejects_missing_operations():
    result = CliRunner().invoke(json_group, ["apply"], input=json.dumps({"operations": []}))

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"] == 'No operations provided. Expected {"operations": [...]}'
    assert result.stderr.strip() == 'No operations provided. Expected {"operations": [...]}'


def test_json_apply_applies_operations_and_reports_backup(monkeypatch, clean_layout):
    import unjiggle.cli as cli
    import unjiggle.device as device
    import unjiggle.layout_engine as layout_engine
    import unjiggle.safety as safety

    backup_path = Path("/tmp/layout-backup.json")
    written_raw: list[dict] = []
    predicted_layout = HomeScreenLayout(dock=[], pages=[[clean_layout.pages[0][0]]], raw={"iconLists": [["done"]]})
    reads = iter([clean_layout, predicted_layout])

    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: next(reads))
    monkeypatch.setattr(safety, "pre_write_safety_check", lambda lockdown, layout: (True, backup_path))
    monkeypatch.setattr(layout_engine, "check_write", lambda layout, ops: ({"iconLists": [["done"]]}, predicted_layout, None))
    monkeypatch.setattr(device, "write_layout", lambda lockdown, raw: written_raw.append(raw))
    monkeypatch.setattr(cli, "_preview_effective_operations", lambda layout, ops: (predicted_layout, ops))

    result = CliRunner().invoke(
        json_group,
        ["apply"],
        input=json.dumps({"operations": [{"action": "move_to_page", "bundle_ids": ["com.instagram.Instagram"], "target_page": 0}]}),
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["requested"] == 1
    assert payload["applied"] == 1
    assert payload["backup"] == str(backup_path)
    assert payload["changed"] is True
    assert written_raw == [{"iconLists": [["done"]]}]


def test_json_apply_skips_noop_batches(monkeypatch, clean_layout):
    import unjiggle.cli as cli
    import unjiggle.device as device
    import unjiggle.safety as safety

    writes: list[dict] = []

    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: clean_layout)
    monkeypatch.setattr(cli, "_preview_effective_operations", lambda layout, ops: (layout, []))
    monkeypatch.setattr(device, "write_layout", lambda lockdown, raw: writes.append(raw))
    monkeypatch.setattr(
        safety,
        "pre_write_safety_check",
        lambda lockdown, layout: (_ for _ in ()).throw(AssertionError("safety should not run for no-ops")),
    )

    result = CliRunner().invoke(
        json_group,
        ["apply"],
        input=json.dumps({"operations": [{"action": "move_to_page", "bundle_ids": ["com.apple.Maps"], "target_page": 0}]}),
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["requested"] == 1
    assert payload["applied"] == 0
    assert payload["backup"] is None
    assert payload["changed"] is False
    assert payload["layout_signature"] == payload["snapshot_id"]
    assert writes == []


def test_json_apply_accepts_compact_to_single_page(monkeypatch, clean_layout):
    import unjiggle.cli as cli
    import unjiggle.device as device
    import unjiggle.layout_engine as layout_engine
    import unjiggle.safety as safety

    backup_path = Path("/tmp/layout-backup.json")
    predicted_layout = HomeScreenLayout(
        dock=clean_layout.dock,
        pages=[[clean_layout.pages[0][0], clean_layout.pages[0][1]]],
        raw={"iconLists": [["done"]]},
    )
    reads = iter([clean_layout, predicted_layout])
    written_raw: list[dict] = []

    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: next(reads))
    monkeypatch.setattr(cli, "_preview_effective_operations", lambda layout, ops: (predicted_layout, ops))
    monkeypatch.setattr(safety, "pre_write_safety_check", lambda lockdown, layout: (True, backup_path))
    monkeypatch.setattr(layout_engine, "check_write", lambda layout, ops: ({"iconLists": [["done"]]}, predicted_layout, None))
    monkeypatch.setattr(device, "write_layout", lambda lockdown, raw: written_raw.append(raw))

    result = CliRunner().invoke(
        json_group,
        ["apply"],
        input=json.dumps(
            {
                "operations": [{
                    "action": "compact_to_single_page",
                    "bundle_ids": ["com.apple.Maps", "com.spotify.client"],
                }],
            }
        ),
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["applied"] == 1
    assert payload["changed"] is True
    assert written_raw == [{"iconLists": [["done"]]}]


def test_json_apply_writes_nothing_when_the_check_finds_a_problem(monkeypatch, clean_layout):
    from unjiggle import device, layout_engine, safety

    changed = HomeScreenLayout(dock=[], pages=[[clean_layout.pages[0][0]]], raw={"iconLists": [["x"]]})
    writes: list = []
    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: clean_layout)
    monkeypatch.setattr(
        layout_engine, "check_write",
        lambda layout, ops: ({"iconLists": [["x"]]}, changed, "the written layout would differ from the preview"),
    )
    monkeypatch.setattr(device, "write_layout", lambda lockdown, raw: writes.append(raw))
    monkeypatch.setattr(
        safety,
        "pre_write_safety_check",
        lambda lockdown, layout: (_ for _ in ()).throw(AssertionError("no backup before a refused write")),
    )

    result = CliRunner().invoke(
        json_group,
        ["apply"],
        input=json.dumps({"operations": [{"action": "move_to_page", "bundle_ids": ["com.apple.weather"], "target_page": 1}]}),
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"] == (
        "Not written: the written layout would differ from the preview. No changes made."
    )
    assert writes == []


def test_json_apply_predicts_all_operations_together(monkeypatch):
    """json apply writes the operations together, as the preview of json suggest shows
    them. Here the delete empties page 2, and one operation at a time would give a
    different page for the move."""
    from unjiggle import device, safety

    def app(b):
        return {"bundleIdentifier": b, "iconType": "app"}

    raw = [[app("com.dock")], [app("com.p1")], [app("com.a")], [app("com.b")], [app("com.c"), app("com.d")]]
    state = {"raw": raw}
    writes = []

    def write_layout(lockdown, new_raw):
        writes.append(new_raw)
        state["raw"] = new_raw

    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: device.parse_layout_state(state["raw"]))
    monkeypatch.setattr(device, "write_layout", write_layout)
    monkeypatch.setattr(safety, "pre_write_safety_check", lambda lockdown, layout: (True, Path("/tmp/backup.json")))

    operations = [
        {"action": "delete", "bundle_ids": ["com.a"]},
        {"action": "move_to_page", "bundle_ids": ["com.c"], "target_page": 2},
    ]
    result = CliRunner().invoke(json_group, ["apply"], input=json.dumps({"operations": operations}))

    assert result.exit_code == 0, result.output
    assert len(writes) == 1
    pages = [[item.app.bundle_id for item in page] for page in device.parse_layout_state(writes[0]).pages]
    # Page index 2 is the page of com.b while page 2 is still there, as in the preview.
    assert pages == [["com.p1"], ["com.b", "com.c"], ["com.d"]]


def test_json_scan_and_diagnose_include_snapshot_identity(monkeypatch, clean_layout, sample_metadata):
    import unjiggle.archetypes as archetypes
    import unjiggle.device as device
    import unjiggle.itunes as itunes
    import unjiggle.scoring as scoring
    import unjiggle.swipetax as swipetax

    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", type("Device", (), {"name": "iPhone", "model": "Test", "ios_version": "18.0"})()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: clean_layout)
    monkeypatch.setattr(itunes, "enrich_layout", lambda layout: sample_metadata)
    monkeypatch.setattr(archetypes, "assign_archetype", lambda layout, metadata: ("The Sorted One", "Calm"))
    monkeypatch.setattr(scoring, "compute_score", lambda layout, metadata: scoring.ScoreBreakdown(90, 88, 87, 91))
    monkeypatch.setattr(
        swipetax,
        "compute_swipe_tax",
        lambda layout, metadata: swipetax.SwipeTaxResult(0, 0, 0, [], [], "No waste"),
    )

    scan_result = CliRunner().invoke(json_group, ["scan"])
    diagnose_result = CliRunner().invoke(json_group, ["diagnose"])

    assert scan_result.exit_code == 0
    assert diagnose_result.exit_code == 0
    scan_payload = json.loads(scan_result.output)
    diagnose_payload = json.loads(diagnose_result.output)
    assert scan_payload["layout_signature"] == scan_payload["snapshot_id"]
    assert diagnose_payload["layout_signature"] == diagnose_payload["snapshot_id"]


def test_json_restore_returns_new_snapshot_identity(monkeypatch, clean_layout, tmp_path):
    import unjiggle.device as device

    backup_file = tmp_path / "layout.json"
    backup_file.write_text("{}")

    restored_layout = HomeScreenLayout(
        dock=[],
        pages=[[clean_layout.pages[0][0]]],
        raw={"iconLists": [["done"]]},
    )
    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", object()))
    monkeypatch.setattr(device, "restore_layout_from_file", lambda path: {"iconLists": [["done"]]})
    monkeypatch.setattr(device, "write_layout", lambda lockdown, raw: None)
    monkeypatch.setattr(device, "read_layout", lambda lockdown: restored_layout)

    result = CliRunner().invoke(json_group, ["restore", str(backup_file)])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["restored"] is True
    assert payload["layout_signature"] == payload["snapshot_id"]


def test_preset_preload_lifecycle_invalidates_after_apply_and_restore(monkeypatch, clean_layout, sample_metadata, tmp_path):
    import unjiggle.cli as cli
    import unjiggle.device as device
    import unjiggle.itunes as itunes
    import unjiggle.layout_engine as layout_engine
    import unjiggle.safety as safety

    initial_layout = HomeScreenLayout(
        dock=clean_layout.dock,
        pages=clean_layout.pages,
        raw={"iconLists": [["initial"]]},
    )
    applied_layout = HomeScreenLayout(
        dock=clean_layout.dock,
        pages=[[clean_layout.pages[0][0], clean_layout.pages[0][1]]],
        raw={"iconLists": [["applied"]]},
    )
    current_layout = {"value": initial_layout}
    backup_file = tmp_path / "layout.json"
    backup_file.write_text("{}")

    monkeypatch.setattr(
        device,
        "connect",
        lambda: ("LOCKDOWN", type("Device", (), {"name": "iPhone", "model": "Test", "ios_version": "18.0"})()),
    )
    monkeypatch.setattr(device, "read_layout", lambda lockdown: current_layout["value"])
    monkeypatch.setattr(itunes, "enrich_layout", lambda layout: sample_metadata)
    monkeypatch.setattr(safety, "pre_write_safety_check", lambda lockdown, layout: (True, backup_file))
    monkeypatch.setattr(layout_engine, "check_write", lambda layout, ops: (applied_layout.raw, applied_layout, None))
    monkeypatch.setattr(cli, "_preview_effective_operations", lambda layout, ops: (applied_layout, ops))
    monkeypatch.setattr(
        device,
        "restore_layout_from_file",
        lambda path: initial_layout.raw,
    )

    def write_layout(_lockdown, raw):
        if raw == applied_layout.raw:
            current_layout["value"] = applied_layout
            return
        if raw == initial_layout.raw:
            current_layout["value"] = initial_layout
            return
        raise AssertionError(f"unexpected raw write: {raw!r}")

    monkeypatch.setattr(device, "write_layout", write_layout)

    initial_presets = CliRunner().invoke(json_group, ["presets"])
    apply_result = CliRunner().invoke(
        json_group,
        ["apply"],
        input=json.dumps({"operations": [{"action": "move_to_page", "bundle_ids": ["com.apple.weather"], "target_page": 0}]}),
    )
    refreshed_presets = CliRunner().invoke(json_group, ["presets"])
    restore_result = CliRunner().invoke(json_group, ["restore", str(backup_file)])
    restored_presets = CliRunner().invoke(json_group, ["presets"])

    assert initial_presets.exit_code == 0
    assert apply_result.exit_code == 0
    assert refreshed_presets.exit_code == 0
    assert restore_result.exit_code == 0
    assert restored_presets.exit_code == 0

    initial_payload = json.loads(initial_presets.output)
    apply_payload = json.loads(apply_result.output)
    refreshed_payload = json.loads(refreshed_presets.output)
    restore_payload = json.loads(restore_result.output)
    restored_payload = json.loads(restored_presets.output)

    assert initial_payload["layout_signature"] == initial_payload["snapshot_id"]
    assert initial_payload["layout_signature"] != apply_payload["layout_signature"]
    assert refreshed_payload["layout_signature"] == apply_payload["layout_signature"]
    assert restore_payload["layout_signature"] == initial_payload["layout_signature"]
    assert restored_payload["layout_signature"] == initial_payload["layout_signature"]


def _delete_test_state(raw_format: str):
    """A phone with Maps and Dark Sky on page 1 and a two-app folder on page 2."""
    dock = [{"bundleIdentifier": "com.apple.mobilephone", "iconType": "app"}]
    page_1 = [
        {"bundleIdentifier": "com.apple.Maps", "iconType": "app"},
        {"bundleIdentifier": "com.darksky.darksky", "iconType": "app"},
    ]
    page_2 = [{
        "displayName": "Travel",
        "iconType": "folder",
        "iconLists": [["com.airbnb.app", "com.uber.UberClient", "com.tripit.TripIt"]],
    }]
    if raw_format == "ios26":
        return [dock, page_1, page_2]
    return {"buttonBar": dock, "iconLists": [page_1, page_2], "ignored": ["com.old.app"]}


@pytest.mark.parametrize("raw_format", ["legacy", "ios26"])
def test_delete_is_previewed_applied_and_verified(monkeypatch, sample_metadata, raw_format):
    from unjiggle import device, safety
    from unjiggle.analyzer import LayoutOperation
    from unjiggle.cli import _resolve_transform_preview
    from unjiggle.scoring import compute_score

    layout = device.parse_layout_state(_delete_test_state(raw_format))
    delete = LayoutOperation(
        action="delete",
        bundle_ids=["com.darksky.darksky", "com.uber.UberClient"],
        gratitude="Thanks for the rides.",
    )

    # The preview shows both apps leaving the home screen.
    payload = _resolve_transform_preview(
        "let go of old apps", layout, sample_metadata, compute_score(layout, sample_metadata), [delete],
    )
    assert payload["archived"] == 2
    assert sorted((c["action"], c["bundle_id"]) for c in payload["changes"]) == [
        ("delete", "com.darksky.darksky"),
        ("delete", "com.uber.UberClient"),
    ]
    # Each delete row carries the gratitude line, and a detail line that says the
    # write only takes the icon off the home screen.
    for change in payload["changes"]:
        assert change["gratitude"] == "Thanks for the rides."
        assert change["detail"] == (
            "Thanks for the rides. The icon leaves the home screen. "
            "The app stays installed until you delete it."
        )

    # Applying writes the change, and the layout read back matches the preview.
    state = {"raw": layout.raw}
    writes = []

    def write_layout(lockdown, raw):
        writes.append(raw)
        state["raw"] = raw

    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: device.parse_layout_state(state["raw"]))
    monkeypatch.setattr(device, "write_layout", write_layout)
    monkeypatch.setattr(safety, "pre_write_safety_check", lambda lockdown, layout: (True, Path("/tmp/backup.json")))

    result = CliRunner().invoke(
        json_group,
        ["apply"],
        input=json.dumps({"operations": payload["operations"]}),
    )

    assert result.exit_code == 0, result.output
    applied = json.loads(result.output)
    assert applied["applied"] == 1
    assert applied["changed"] is True
    assert len(writes) == 1
    remaining = device.parse_layout_state(writes[0])
    assert "com.darksky.darksky" not in remaining.all_bundle_ids
    assert "com.uber.UberClient" not in remaining.all_bundle_ids
    assert "com.airbnb.app" in remaining.all_bundle_ids
    assert remaining.ignored == layout.ignored
