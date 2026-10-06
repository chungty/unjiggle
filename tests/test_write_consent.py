import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from tests.fake_springboard import adds_unlisted_app
from tests.test_safety import _FixedClock, _Phone, _phone_state
from unjiggle import cli, device, safety


@pytest.fixture
def phone(monkeypatch, tmp_path):
    simulated = _Phone(_phone_state())
    monkeypatch.setattr(device, "connect", lambda: (
        None, SimpleNamespace(name="Test phone", ios_version="27"),
    ))
    monkeypatch.setattr(device, "read_layout", simulated.read_layout)
    monkeypatch.setattr(device, "write_layout", simulated.write_layout)
    monkeypatch.setattr(safety, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(cli, "BACKUP_DIR", tmp_path / "backups", raising=False)
    return simulated


def test_safety_test_defaults_to_no_device_write(phone):
    result = CliRunner().invoke(cli.main, ["safety-test"], input="y\n")

    assert result.exit_code == 0, result.output
    assert phone.writes == []
    assert len(safety.list_backups()) == 1
    assert "Read-only checks passed" in result.output
    assert "write path was not tested" in result.output
    assert "You're safe" not in result.output


@pytest.mark.parametrize("answer", ["n\n", "\n", ""])
def test_write_roundtrip_needs_confirmation(phone, answer):
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input=answer)

    assert phone.writes == []
    assert "iOS may add or move icons" in result.output
    assert "[y/N]" in result.output


def test_explicit_roundtrip_writes_once_after_backup(phone, monkeypatch):
    def write(lockdown, state):
        assert len(safety.list_backups()) == 1
        phone.write_layout(lockdown, state)

    monkeypatch.setattr(device, "write_layout", write)
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input="y\n")

    assert result.exit_code == 0, result.output
    assert len(phone.writes) == 1
    assert "Round-trip verified" in result.output
    assert "guarantee" in result.output
    assert "You're safe" not in result.output


def test_failed_backup_prevents_explicit_write(phone, monkeypatch):
    def fail_backup(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(safety, "verified_backup", fail_backup)
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input="y\n")

    assert result.exit_code == 1, result.output
    assert phone.writes == []


def test_added_icons_fail_roundtrip_without_retry(phone, monkeypatch):
    def write(lockdown, state):
        phone.write_layout(lockdown, state)
        phone.raw = adds_unlisted_app(copy.deepcopy(state))

    monkeypatch.setattr(device, "write_layout", write)
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input="y\n")

    assert result.exit_code == 1, result.output
    assert len(phone.writes) == 1
    assert "Round-trip FAILED" in result.output
    assert "Round-trip verified" not in result.output
    assert "do not retry or restore automatically" in result.output


def test_pre_write_backup_does_not_run_a_roundtrip(phone, monkeypatch):
    def unexpected_write(*args, **kwargs):
        pytest.fail("pre-write backup must not write to the phone")

    monkeypatch.setattr(device, "write_layout", unexpected_write)
    ready, backup = safety.pre_write_safety_check(None, phone.read_layout(None))

    assert ready is True
    assert backup.is_file()


def test_restore_command_reports_failed_verification(phone, monkeypatch, tmp_path):
    backup = tmp_path / "restore.json"
    backup.write_text("[]")
    result = CliRunner().invoke(cli.main, ["restore", str(backup)])

    assert result.exit_code == 1, result.output
    assert phone.writes == []


def test_restore_command_fails_after_added_icons_without_retry(phone, monkeypatch, tmp_path):
    backup = tmp_path / "restore.json"
    backup.write_text(json.dumps(_phone_state()))

    def write(lockdown, state):
        phone.write_layout(lockdown, state)
        phone.raw = adds_unlisted_app(copy.deepcopy(state))

    monkeypatch.setattr(device, "write_layout", write)
    result = CliRunner().invoke(cli.main, ["restore", str(backup)])

    assert result.exit_code == 1, result.output
    assert len(phone.writes) == 1
    assert "Restore verification failed" in result.output
    assert "cosmetic" not in result.output
    assert "Restore verified" not in result.output


def test_backup_drift_aborts_and_preserves_original_read(phone, monkeypatch):
    original = copy.deepcopy(phone.raw)
    reads = []

    def read(lockdown):
        reads.append(None)
        if len(reads) == 2:
            phone.raw = adds_unlisted_app(copy.deepcopy(phone.raw))
        return phone.read_layout(lockdown)

    monkeypatch.setattr(device, "read_layout", read)
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input="y\n")

    assert result.exit_code == 1, result.output
    assert "Device layout changed" in result.output
    assert phone.writes == []
    backups = safety.list_backups()
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == original


def test_roundtrip_refuses_layout_changed_during_confirmation(phone, monkeypatch):
    def confirm(*args, **kwargs):
        phone.raw = adds_unlisted_app(copy.deepcopy(phone.raw))
        return True

    monkeypatch.setattr(cli.click, "confirm", confirm)
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"])

    assert result.exit_code == 1, result.output
    assert "layout changed since the backup" in result.output
    assert phone.writes == []


def test_pre_write_check_refuses_stale_layout(phone):
    previewed = phone.read_layout(None)
    phone.raw = adds_unlisted_app(copy.deepcopy(phone.raw))

    ready, backup = safety.pre_write_safety_check(None, previewed)

    assert ready is False
    assert backup is None
    assert phone.writes == []
    assert json.loads(safety.list_backups()[0].read_text()) == previewed.raw


@pytest.mark.parametrize("stage", ["write", "readback"])
def test_restore_transport_error_reports_uncertain_state_and_backups(phone, monkeypatch, tmp_path, stage):
    backup = tmp_path / "restore.json"
    backup.write_text(json.dumps(_phone_state()))

    def write(lockdown, state):
        phone.write_layout(lockdown, state)
        if stage == "write":
            raise OSError("USB disconnected")

    def read(lockdown):
        if phone.writes and stage == "readback":
            raise OSError("USB disconnected")
        return phone.read_layout(lockdown)

    monkeypatch.setattr(device, "write_layout", write)
    monkeypatch.setattr(device, "read_layout", read)
    result = CliRunner().invoke(cli.main, ["restore", str(backup)])

    assert result.exit_code == 1, result.output
    assert len(phone.writes) == 1
    assert "phone may have changed" in result.output
    assert str(backup) in result.output
    assert len(safety.list_backups()) == 1
    assert "Layout before this restore" in result.output
    assert "Restore verified" not in result.output


def test_manual_backup_preserves_same_second_safety_backup(phone, monkeypatch):
    monkeypatch.setattr(safety, "datetime", _FixedClock)
    monkeypatch.setattr(cli, "datetime", _FixedClock)
    original = safety.verified_backup(None, phone.read_layout(None))
    contents = original.read_bytes()
    phone.raw = adds_unlisted_app(copy.deepcopy(phone.raw))

    result = CliRunner().invoke(cli.main, ["backup"])

    assert result.exit_code == 0, result.output
    assert original.read_bytes() == contents
    assert len(safety.list_backups()) == 2
    assert phone.writes == []


def test_backup_creation_preserves_a_concurrent_file(phone, monkeypatch):
    original_open = Path.open
    competing_path = None

    def racing_open(path, mode="r", *args, **kwargs):
        nonlocal competing_path
        if path.parent == safety.BACKUP_DIR and mode in ("w", "x"):
            assert mode == "x", "Backup creation must be exclusive"
            if competing_path is None:
                competing_path = path
                with original_open(path, "x") as competing:
                    competing.write("existing backup")
                raise FileExistsError(path)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", racing_open)
    saved = safety.verified_backup(None, phone.read_layout(None))

    assert competing_path.read_text() == "existing backup"
    assert saved != competing_path
    assert json.loads(saved.read_text()) == phone.raw
    assert phone.writes == []


def test_backup_read_error_reports_retained_file(phone, monkeypatch):
    before = phone.read_layout(None)

    def disconnected(lockdown):
        raise OSError("USB disconnected")

    monkeypatch.setattr(device, "read_layout", disconnected)
    with pytest.raises(RuntimeError) as raised:
        safety.verified_backup(None, before)

    saved = safety.list_backups()[0]
    assert str(saved) in str(raised.value)
    assert json.loads(saved.read_text()) == before.raw
    assert phone.writes == []


@pytest.mark.parametrize("command", [["backup"], ["safety-test", "--write-roundtrip"]])
def test_initial_read_error_stops_cleanly(phone, monkeypatch, command):
    def disconnected(lockdown):
        raise OSError("USB disconnected")

    monkeypatch.setattr(device, "read_layout", disconnected)
    result = CliRunner().invoke(cli.main, command, input="y\n")

    assert result.exit_code == 1, result.output
    assert "USB disconnected" in result.output
    assert "Backup failed" in result.output
    assert phone.writes == []


@pytest.mark.parametrize("stage", ["write", "readback"])
def test_write_test_error_warns_about_possible_changes(phone, monkeypatch, stage):
    def write(lockdown, state):
        phone.write_layout(lockdown, state)
        if stage == "write":
            raise OSError("USB disconnected")

    def read(lockdown):
        if phone.writes and stage == "readback":
            raise OSError("USB disconnected")
        return phone.read_layout(lockdown)

    monkeypatch.setattr(device, "write_layout", write)
    monkeypatch.setattr(device, "read_layout", read)
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input="y\n")

    assert result.exit_code == 1, result.output
    assert "phone may have changed" in result.output.lower()
    assert len(phone.writes) == 1


@pytest.mark.parametrize("raw", [
    [[], [{"iconType": "widget", "containerBundleIdentifier": "example.widget"}]],
    [[{"bundleIdentifier": "example.dock"}], []],
])
def test_restore_supports_widgets_or_dock_without_page_apps(phone, tmp_path, raw):
    backup = tmp_path / "restore.json"
    backup.write_text(json.dumps(raw))

    assert safety.restore_from_backup(None, backup) is True
    assert phone.writes == [raw]


@pytest.mark.parametrize("raw", [
    "invalid", [42], [[{}]], [[{"bundleIdentifier": "example.app"}, None]],
])
def test_restore_refuses_unsupported_backup_without_writing(phone, tmp_path, raw):
    backup = tmp_path / "restore.json"
    backup.write_text(json.dumps(raw))

    assert safety.restore_from_backup(None, backup) is False
    assert phone.writes == []
