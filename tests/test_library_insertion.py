"""A read-only insertion proposal must fail closed on ambiguous icon state."""

import copy
import json

import pytest
from click.testing import CliRunner

from unjiggle import cli, device, safety
from tests.test_json_contract import FakePhone, failed, ok, run
from unjiggle.library_insertion import (
    project_library_folder_insertion, project_library_insertion, project_library_insertions,
)


APP = "org.example.library"


def sample():
    raw = {
        "buttonBar": ["org.example.dock"],
        "iconLists": [["org.example.visible", {"listType": "folder", "displayName": "Other", "iconLists": [["org.example.child"]]}]],
        "ignored": [APP],
        "uniqueIdentifier": "untouched metadata",
    }
    layout = device.parse_layout_state(raw)
    inventory = device.reconcile_installed_apps({APP: {"ApplicationType": "User"}}, layout)
    return layout, inventory


def test_projection_changes_only_ignored_and_chosen_page():
    layout, inventory = sample()
    before = copy.deepcopy(layout.raw)
    projected = project_library_insertion(layout, inventory, APP, 0)
    expected = copy.deepcopy(before)
    del expected["ignored"]
    expected["iconLists"][0].append(APP)
    assert layout.raw == before
    assert projected.raw == expected
    assert projected.all_bundle_ids.count(APP) == 1


def test_projection_preserves_other_ignored_apps_in_order():
    layout, _ = sample()
    raw = copy.deepcopy(layout.raw)
    raw["ignored"] = ["org.example.first", APP, "org.example.last"]
    layout = device.parse_layout_state(raw)
    inventory = device.reconcile_installed_apps({APP: {"ApplicationType": "User"}}, layout)
    projected = project_library_insertion(layout, inventory, APP, 0)
    assert projected.raw["ignored"] == ["org.example.first", "org.example.last"]
    assert projected.raw["iconLists"][0][-1] == APP


def test_folder_projection_changes_only_ignored_and_target_folder():
    layout, inventory = sample()
    original = copy.deepcopy(layout.raw)
    projected = project_library_folder_insertion(layout, inventory, APP, "Other")
    expected = copy.deepcopy(original)
    del expected["ignored"]
    expected["iconLists"][0][1]["iconLists"][0].append(APP)
    assert layout.raw == original
    assert projected.raw == expected
    assert projected.all_bundle_ids.count(APP) == 1


def test_folder_projection_appends_page_when_last_folder_page_is_full():
    layout, _ = sample()
    raw = copy.deepcopy(layout.raw)
    raw["iconLists"][0][1]["iconLists"][0].extend(
        f"org.example.child.{index}" for index in range(8)
    )
    layout = device.parse_layout_state(raw)
    inventory = device.reconcile_installed_apps({APP: {"ApplicationType": "User"}}, layout)
    projected = project_library_folder_insertion(layout, inventory, APP, "Other")
    assert len(projected.raw["iconLists"][0][1]["iconLists"][0]) == 9
    assert projected.raw["iconLists"][0][1]["iconLists"][1] == [APP]


@pytest.mark.parametrize("alter", [
    lambda raw: raw["iconLists"][0].append(copy.deepcopy(raw["iconLists"][0][1])),
    lambda raw: raw["buttonBar"].append(copy.deepcopy(raw["iconLists"][0][1])),
    lambda raw: raw["iconLists"][0][1]["iconLists"][0].extend(
        f"org.example.child.{i}" for i in range(9)),
    lambda raw: raw["iconLists"][0][1].update(iconLists=[]),
    lambda raw: raw["ignored"].append(APP),
    lambda raw: raw["iconLists"][0][1]["iconLists"][0].append(APP),
])
def test_folder_projection_refuses_ambiguous_overfull_or_duplicate_source(alter):
    layout, _ = sample()
    raw = copy.deepcopy(layout.raw)
    alter(raw)
    changed = device.parse_layout_state(raw)
    inventory = device.reconcile_installed_apps({APP: {"ApplicationType": "User"}}, changed)
    with pytest.raises(ValueError):
        project_library_folder_insertion(changed, inventory, APP, "Other")


@pytest.mark.parametrize("folder_name", ["Missing", "", None, True])
def test_folder_projection_requires_existing_named_folder(folder_name):
    layout, inventory = sample()
    with pytest.raises(ValueError):
        project_library_folder_insertion(layout, inventory, APP, folder_name)


@pytest.mark.parametrize("application_type,on_home_screen", [("System", False), ("User", True)])
def test_folder_projection_requires_unlisted_installed_user_app(application_type, on_home_screen):
    layout, _ = sample()
    inventory = device.InstalledAppInventory((
        device.InstalledApp(APP, "App", on_home_screen, application_type),
    ), ())
    with pytest.raises(ValueError, match="User app"):
        project_library_folder_insertion(layout, inventory, APP, "Other")


@pytest.mark.parametrize("alter", [
    lambda raw: raw.update(ignored=[]),
    lambda raw: raw.update(ignored=[APP, APP]),
    lambda raw: raw["buttonBar"].append(APP),
    lambda raw: raw["iconLists"][0][1]["iconLists"][0].append(APP),
    lambda raw: raw["iconLists"][0].extend([f"org.example.extra.{i}" for i in range(23)]),
    lambda raw: raw["iconLists"].append([]),
    lambda raw: raw["iconLists"][0].append({"unknown": "icon"}),
])
def test_refuses_missing_duplicate_visible_full_or_incomplete_state(alter):
    layout, inventory = sample()
    raw = copy.deepcopy(layout.raw)
    alter(raw)
    with pytest.raises(ValueError):
        project_library_insertion(device.parse_layout_state(raw), inventory, APP, 0)


@pytest.mark.parametrize("app_type,seen", [("System", False), (None, False), ("User", True)])
def test_requires_installed_unlisted_user_app(app_type, seen):
    layout, _ = sample()
    inventory = device.InstalledAppInventory((device.InstalledApp(APP, "App", seen, app_type),), ())
    with pytest.raises(ValueError):
        project_library_insertion(layout, inventory, APP, 0)


@pytest.mark.parametrize("page", [-1, 1, True, "0"])
def test_requires_exact_existing_page(page):
    layout, inventory = sample()
    with pytest.raises(ValueError):
        project_library_insertion(layout, inventory, APP, page)


def test_cli_checks_fresh_raw_before_and_after_inventory_and_never_writes(monkeypatch):
    layout, inventory = sample()
    monkeypatch.setattr(device, "connect", lambda: ("phone", object()))
    states = [layout, layout]
    monkeypatch.setattr(device, "read_layout", lambda lockdown: states.pop(0))
    monkeypatch.setattr(device, "read_installed_apps", lambda lockdown, current: inventory)
    monkeypatch.setattr(device, "write_layout", lambda *args: pytest.fail("preflight wrote"))
    request = {"bundle_id": APP, "target_page": 0, "snapshot_id": cli._layout_signature(layout),
               "source_raw_sha256": cli._raw_state_fingerprint(layout)}
    result = CliRunner().invoke(cli.main, ["json", "check-library-insertion"], input=json.dumps(request))
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert output["writable"] is False
    assert output["proposed_raw_sha256"] == cli._raw_state_fingerprint(
        project_library_insertion(layout, inventory, APP, 0))
    assert output["proposed_layout"]["pages"][0][-1]["app"]["bundle_id"] == APP
    assert output["parse_integrity"]["structure_preserved"] is True
    assert states == []


def test_cli_checks_folder_destination_without_writing(monkeypatch):
    layout, inventory = sample()
    states = [layout, layout]
    monkeypatch.setattr(device, "connect", lambda: ("phone", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: states.pop(0))
    monkeypatch.setattr(device, "read_installed_apps", lambda lockdown, current: inventory)
    monkeypatch.setattr(device, "write_layout", lambda *args: pytest.fail("preflight wrote"))
    request = {"bundle_id": APP, "target_folder": "Other",
               "snapshot_id": cli._layout_signature(layout),
               "source_raw_sha256": cli._raw_state_fingerprint(layout)}
    result = CliRunner().invoke(cli.main, ["json", "check-library-insertion"], input=json.dumps(request))
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert output["writable"] is False
    assert output["target_folder"] == "Other"
    assert "target_page" not in output
    assert output["proposed_raw_sha256"] == cli._raw_state_fingerprint(
        project_library_folder_insertion(layout, inventory, APP, "Other"))
    assert states == []


def test_cli_rejects_ambiguous_destination_before_connect(monkeypatch):
    layout, _ = sample()
    monkeypatch.setattr(device, "connect", lambda: pytest.fail("invalid plan opened device"))
    base = {"bundle_id": APP, "snapshot_id": cli._layout_signature(layout),
            "source_raw_sha256": cli._raw_state_fingerprint(layout)}
    for destination in ({}, {"target_page": 0, "target_folder": "Other"}):
        request = {**base, **destination}
        result = CliRunner().invoke(cli.main, ["json", "check-library-insertion"], input=json.dumps(request))
        assert result.exit_code != 0
        assert "exactly one" in json.loads(result.stdout)["error"]


def test_cli_rejects_raw_metadata_drift_even_with_same_visible_layout(monkeypatch):
    layout, inventory = sample()
    raw = copy.deepcopy(layout.raw)
    raw["uniqueIdentifier"] = "changed behind inventory read"
    monkeypatch.setattr(device, "connect", lambda: ("phone", object()))
    states = [layout, device.parse_layout_state(raw)]
    monkeypatch.setattr(device, "read_layout", lambda lockdown: states.pop(0))
    monkeypatch.setattr(device, "read_installed_apps", lambda lockdown, current: inventory)
    request = {"bundle_id": APP, "target_page": 0, "snapshot_id": cli._layout_signature(layout),
               "source_raw_sha256": cli._raw_state_fingerprint(layout)}
    result = CliRunner().invoke(cli.main, ["json", "check-library-insertion"], input=json.dumps(request))
    assert result.exit_code != 0
    assert "changed while reading" in json.loads(result.stdout)["error"]


def test_batch_prefixes_preserve_original_and_unrelated_raw_state():
    layout, _ = sample()
    second = "org.example.second"
    raw = copy.deepcopy(layout.raw)
    raw["ignored"] = [APP, second, "org.example.untouched"]
    layout = device.parse_layout_state(raw)
    inventory = device.reconcile_installed_apps({
        APP: {"ApplicationType": "User"}, second: {"ApplicationType": "User"},
    }, layout)
    before = copy.deepcopy(layout.raw)
    steps = project_library_insertions(layout, inventory, [
        {"bundle_id": APP, "target_page": 0},
        {"bundle_id": second, "target_page": 0},
    ])
    assert layout.raw == before
    assert steps[0].raw["ignored"] == [second, "org.example.untouched"]
    assert steps[0].raw["iconLists"][0][-1] == APP
    assert steps[1].raw["ignored"] == ["org.example.untouched"]
    assert steps[1].raw["iconLists"][0][-2:] == [APP, second]
    assert steps[1].raw["buttonBar"] == before["buttonBar"]


def test_batch_rejects_duplicate_and_full_second_destination():
    layout, inventory = sample()
    with pytest.raises(ValueError, match="repeats"):
        project_library_insertions(layout, inventory, [
            {"bundle_id": APP, "target_page": 0},
            {"bundle_id": APP, "target_page": 0},
        ])
    second = "org.example.second"
    raw = copy.deepcopy(layout.raw)
    raw["ignored"].append(second)
    raw["iconLists"][0].extend([f"org.example.filler.{i}" for i in range(21)])
    layout = device.parse_layout_state(raw)
    inventory = device.reconcile_installed_apps({
        APP: {"ApplicationType": "User"}, second: {"ApplicationType": "User"},
    }, layout)
    with pytest.raises(ValueError, match="full"):
        project_library_insertions(layout, inventory, [
            {"bundle_id": APP, "target_page": 0},
            {"bundle_id": second, "target_page": 0},
        ])


def test_batch_cli_binds_one_scan_and_returns_nonwritable_checked_steps(monkeypatch):
    layout, _ = sample()
    raw = copy.deepcopy(layout.raw)
    second = "org.example.second"
    raw["ignored"].append(second)
    layout = device.parse_layout_state(raw)
    inventory = device.reconcile_installed_apps({
        APP: {"ApplicationType": "User"}, second: {"ApplicationType": "User"},
    }, layout)
    states = [layout, layout]
    monkeypatch.setattr(device, "connect", lambda: ("phone", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: states.pop(0))
    monkeypatch.setattr(device, "read_installed_apps", lambda lockdown, current: inventory)
    monkeypatch.setattr(device, "write_layout", lambda *args: pytest.fail("preflight wrote"))
    request = {"insertions": [{"bundle_id": APP, "target_page": 0},
                              {"bundle_id": second, "target_page": 0}],
               "snapshot_id": cli._layout_signature(layout),
               "source_raw_sha256": cli._raw_state_fingerprint(layout)}
    result = CliRunner().invoke(cli.main, ["json", "check-library-insertions"], input=json.dumps(request))
    assert result.exit_code == 0, result.output
    result_data = json.loads(result.stdout)
    assert result_data["writable"] is False
    assert len(result_data["steps"]) == 2
    assert result_data["steps"][-1]["snapshot_id"] == result_data["proposed_snapshot_id"]
    projected = project_library_insertions(layout, inventory, request["insertions"])
    assert [step["raw_sha256"] for step in result_data["steps"]] == [
        cli._raw_state_fingerprint(prefix) for prefix in projected]
    assert result_data["proposed_raw_sha256"] == result_data["steps"][-1]["raw_sha256"]
    assert result_data["steps"][0]["raw_sha256"] != result_data["steps"][1]["raw_sha256"]
    assert result_data["steps"][0]["layout"]["pages"][0][-1]["app"]["bundle_id"] == APP
    assert result_data["proposed_layout"]["pages"][0][-1]["app"]["bundle_id"] == second
    assert states == []


@pytest.fixture
def insertion_phone(monkeypatch, tmp_path):
    layout, inventory = sample()
    fake = FakePhone(layout.raw, {}, tmp_path)
    monkeypatch.setattr(device, "connect", fake.connect)
    monkeypatch.setattr(device, "read_layout", fake.read_layout)
    monkeypatch.setattr(device, "write_layout", fake.write_layout)
    monkeypatch.setattr(device, "read_installed_apps", lambda _lockdown, _layout: inventory)
    monkeypatch.setattr(safety, "BACKUP_DIR", fake.backup_dir)
    monkeypatch.setattr(cli, "BACKUP_DIR", fake.backup_dir)
    monkeypatch.setattr(cli, "UNJIGGLE_DIR", tmp_path / ".unjiggle")
    return fake


def checked_insertion(layout, *, folder=False):
    request = {"bundle_id": APP, "snapshot_id": cli._layout_signature(layout),
               "source_raw_sha256": cli._raw_state_fingerprint(layout)}
    request.update({"target_folder": "Other"} if folder else {"target_page": 0})
    checked = ok(run("check-library-insertion", stdin=json.dumps(request)))
    return {**request, "proposed_snapshot_id": checked["proposed_snapshot_id"],
            "proposed_raw_sha256": checked["proposed_raw_sha256"],
            "experimental_library_write": True}


@pytest.mark.parametrize("folder", [False, True])
def test_experimental_library_apply_journals_writes_once_and_restores(insertion_phone, monkeypatch, folder):
    original = copy.deepcopy(insertion_phone.raw)
    request = checked_insertion(device.parse_layout_state(original), folder=folder)
    assert "disabled" in failed(run("apply-library-checked", stdin=json.dumps(request)))["error"]
    assert not insertion_phone.writes and not insertion_phone.backups()
    monkeypatch.setenv("UNJIGGLE_EXPERIMENTAL_LIBRARY_WRITE", "1")
    applied = ok(run("apply-library-checked", stdin=json.dumps(request)))
    assert applied["recovery"]["applied_raw_sha256"] == request["proposed_raw_sha256"]
    assert len(insertion_phone.writes) == 1
    assert applied["journal"] == ok(run("pending-checked"))["records"][0]["journal"]
    assert json.loads(insertion_phone.backups()[0].read_text()) == original
    ok(run("restore-checked", stdin=json.dumps(applied["recovery"])))
    assert insertion_phone.raw == original


def test_experimental_library_apply_fails_closed_on_drift_and_tampered_destination(insertion_phone, monkeypatch):
    request = checked_insertion(device.parse_layout_state(insertion_phone.raw))
    monkeypatch.setenv("UNJIGGLE_EXPERIMENTAL_LIBRARY_WRITE", "1")
    tampered = {**request, "proposed_raw_sha256": "0" * 64}
    assert "destination" in failed(run("apply-library-checked", stdin=json.dumps(tampered)))["error"]
    assert not insertion_phone.writes and not insertion_phone.backups()
    insertion_phone.raw["uniqueIdentifier"] = "drift"
    assert "changed" in failed(run("apply-library-checked", stdin=json.dumps(request)))["error"]
    assert not insertion_phone.writes and not insertion_phone.backups()


def test_experimental_library_apply_stops_when_inventory_read_changes_raw_state(insertion_phone, monkeypatch):
    request = checked_insertion(device.parse_layout_state(insertion_phone.raw))
    monkeypatch.setenv("UNJIGGLE_EXPERIMENTAL_LIBRARY_WRITE", "1")
    inventory = sample()[1]

    def drift(_lockdown, _layout):
        insertion_phone.raw["uniqueIdentifier"] = "inventory changed icon metadata"
        return inventory

    monkeypatch.setattr(device, "read_installed_apps", drift)
    assert "changed while reading" in failed(run("apply-library-checked", stdin=json.dumps(request)))["error"]
    assert not insertion_phone.writes and not insertion_phone.backups()


def test_experimental_library_apply_fails_before_write_if_journal_fails(insertion_phone, monkeypatch):
    request = checked_insertion(device.parse_layout_state(insertion_phone.raw))
    monkeypatch.setenv("UNJIGGLE_EXPERIMENTAL_LIBRARY_WRITE", "1")

    def no_journal(*_args):
        raise OSError("cannot sync recovery journal")

    monkeypatch.setattr(safety, "checked_recovery_journal", no_journal)
    assert "journal could not be saved" in failed(run("apply-library-checked", stdin=json.dumps(request)))["error"]
    assert not insertion_phone.writes and len(insertion_phone.backups()) == 1


def test_experimental_library_apply_keeps_candidate_if_readback_does_not_match(insertion_phone, monkeypatch):
    request = checked_insertion(device.parse_layout_state(insertion_phone.raw))
    monkeypatch.setenv("UNJIGGLE_EXPERIMENTAL_LIBRARY_WRITE", "1")

    def normalized(raw):
        changed = copy.deepcopy(raw)
        changed["uniqueIdentifier"] = "iOS normalized raw metadata"
        return changed

    insertion_phone.keep = normalized
    failure = failed(run("apply-library-checked", stdin=json.dumps(request)))
    assert "verification failed" in failure["error"]
    assert "recovery" not in failure
    assert len(insertion_phone.writes) == 1
    assert len(ok(run("pending-checked"))["records"]) == 1


@pytest.fixture
def batch_phone(insertion_phone, monkeypatch):
    second = "org.example.second"
    insertion_phone.raw["ignored"].append(second)

    def inventory(_lockdown, layout):
        return device.reconcile_installed_apps({
            APP: {"ApplicationType": "User"}, second: {"ApplicationType": "User"},
        }, layout)

    monkeypatch.setattr(device, "read_installed_apps", inventory)
    return insertion_phone


def checked_batch(layout):
    request = {"insertions": [
        {"bundle_id": APP, "target_page": 0},
        {"bundle_id": "org.example.second", "target_page": 0},
    ], "snapshot_id": cli._layout_signature(layout),
        "source_raw_sha256": cli._raw_state_fingerprint(layout)}
    checked = ok(run("check-library-insertions", stdin=json.dumps(request)))
    return {**request, "proposed_snapshot_id": checked["proposed_snapshot_id"],
            "proposed_raw_sha256": checked["proposed_raw_sha256"],
            "checked_step_raw_sha256": [step["raw_sha256"] for step in checked["steps"]],
            "experimental_library_write": True}


def test_batch_apply_one_write_one_backup_journal_and_exact_restore(batch_phone, monkeypatch):
    original = copy.deepcopy(batch_phone.raw)
    request = checked_batch(device.parse_layout_state(original))
    assert "disabled" in failed(run("apply-library-batch-checked", stdin=json.dumps(request)))["error"]
    assert not batch_phone.writes and not batch_phone.backups()
    monkeypatch.setenv("UNJIGGLE_EXPERIMENTAL_LIBRARY_WRITE", "1")
    assert "disabled" in failed(run("apply-library-batch-checked", stdin=json.dumps({
        **request, "experimental_library_write": False})))["error"]
    assert not batch_phone.writes and not batch_phone.backups()
    applied = ok(run("apply-library-batch-checked", stdin=json.dumps(request)))
    assert len(batch_phone.writes) == 1
    assert len(batch_phone.backups()) == 1
    assert json.loads(batch_phone.backups()[0].read_text()) == original
    assert applied["recovery"]["applied_raw_sha256"] == request["proposed_raw_sha256"]
    assert applied["journal"] == ok(run("pending-checked"))["records"][0]["journal"]
    assert batch_phone.raw["iconLists"][0][-2:] == [APP, "org.example.second"]
    ok(run("restore-checked", stdin=json.dumps(applied["recovery"])))
    assert batch_phone.raw == original


@pytest.mark.parametrize("change", [
    lambda request: request.update(checked_step_raw_sha256=["0" * 64, request["proposed_raw_sha256"]]),
    lambda request: request.update(proposed_raw_sha256="0" * 64),
    lambda request: request["insertions"][1].update(target_page=True),
])
def test_batch_apply_rejects_tampered_plan_without_write(batch_phone, monkeypatch, change):
    request = checked_batch(device.parse_layout_state(batch_phone.raw))
    monkeypatch.setenv("UNJIGGLE_EXPERIMENTAL_LIBRARY_WRITE", "1")
    change(request)
    assert "Not written" in failed(run("apply-library-batch-checked", stdin=json.dumps(request)))["error"]
    assert not batch_phone.writes and not batch_phone.backups()


def test_batch_apply_refuses_inventory_drift_before_backup(batch_phone, monkeypatch):
    request = checked_batch(device.parse_layout_state(batch_phone.raw))
    monkeypatch.setenv("UNJIGGLE_EXPERIMENTAL_LIBRARY_WRITE", "1")
    inventory = device.read_installed_apps

    def drift(lockdown, layout):
        result = inventory(lockdown, layout)
        batch_phone.raw["uniqueIdentifier"] = "drift during inventory"
        return result

    monkeypatch.setattr(device, "read_installed_apps", drift)
    assert "changed while reading" in failed(run("apply-library-batch-checked", stdin=json.dumps(request)))["error"]
    assert not batch_phone.writes and not batch_phone.backups()


def test_batch_apply_journal_failure_keeps_backup_without_write(batch_phone, monkeypatch):
    request = checked_batch(device.parse_layout_state(batch_phone.raw))
    monkeypatch.setenv("UNJIGGLE_EXPERIMENTAL_LIBRARY_WRITE", "1")

    def no_journal(*_args):
        raise OSError("journal unavailable")

    monkeypatch.setattr(safety, "checked_recovery_journal", no_journal)
    assert "journal could not be saved" in failed(run("apply-library-batch-checked", stdin=json.dumps(request)))["error"]
    assert not batch_phone.writes and len(batch_phone.backups()) == 1


def test_batch_apply_readback_mismatch_keeps_recovery_candidate(batch_phone, monkeypatch):
    request = checked_batch(device.parse_layout_state(batch_phone.raw))
    monkeypatch.setenv("UNJIGGLE_EXPERIMENTAL_LIBRARY_WRITE", "1")

    def normalized(raw):
        changed = copy.deepcopy(raw)
        changed["uniqueIdentifier"] = "iOS changed raw metadata"
        return changed

    batch_phone.keep = normalized
    assert "verification failed" in failed(run("apply-library-batch-checked", stdin=json.dumps(request)))["error"]
    assert len(batch_phone.writes) == 1
    assert len(ok(run("pending-checked"))["records"]) == 1


def test_batch_cli_rejects_bad_plan_before_connect_and_stale_state(monkeypatch):
    layout, _ = sample()
    monkeypatch.setattr(device, "connect", lambda: pytest.fail("invalid plan opened device"))
    request = {"insertions": [{"bundle_id": APP, "target_page": True}],
               "snapshot_id": cli._layout_signature(layout),
               "source_raw_sha256": cli._raw_state_fingerprint(layout)}
    result = CliRunner().invoke(cli.main, ["json", "check-library-insertions"], input=json.dumps(request))
    assert result.exit_code != 0
    monkeypatch.setattr(device, "connect", lambda: ("phone", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: layout)
    request["insertions"][0]["target_page"] = 0
    request["source_raw_sha256"] = "0" * 64
    result = CliRunner().invoke(cli.main, ["json", "check-library-insertions"], input=json.dumps(request))
    assert result.exit_code != 0
    assert "changed since the scan" in json.loads(result.stdout)["error"]
