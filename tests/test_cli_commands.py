from __future__ import annotations

import json
from pathlib import Path

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

    seen_categories = []
    for page in payload["proposed_layout"]["pages"]:
        assert len(page) <= 24
        for item in page:
            if item["type"] != "app":
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
    assert json.loads(result.output)["error"] == "--backup is required for transform cards."


def test_json_apply_rejects_missing_operations():
    result = CliRunner().invoke(json_group, ["apply"], input=json.dumps({"operations": []}))

    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == 'No operations provided. Expected {"operations": [...]}'


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
    monkeypatch.setattr(layout_engine, "apply_operations", lambda layout, ops: {"iconLists": [["done"]]})
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
    monkeypatch.setattr(layout_engine, "apply_operations", lambda layout, ops: {"iconLists": [["done"]]})
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
    monkeypatch.setattr(layout_engine, "apply_operations", lambda layout, ops: applied_layout.raw)
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
