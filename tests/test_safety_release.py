"""Safety checks must not write without consent or hide a failed restore."""

import copy
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from unjiggle import cli, safety
from unjiggle.models import HomeScreenLayout


@pytest.fixture
def phone(monkeypatch, tmp_path):
    raw = [[{"bundleIdentifier": "example.dock"}], [{"bundleIdentifier": "example.app"}]]
    layout = HomeScreenLayout(raw=raw)
    read = Mock(return_value=layout)
    write = Mock()
    monkeypatch.setattr("unjiggle.device.connect", Mock(return_value=(
        object(), SimpleNamespace(name="Test phone", ios_version="test")
    )))
    monkeypatch.setattr("unjiggle.device.read_layout", read)
    monkeypatch.setattr("unjiggle.device.write_layout", write)
    monkeypatch.setattr(safety, "BACKUP_DIR", tmp_path / "backups")
    return SimpleNamespace(layout=layout, read=read, write=write, root=tmp_path)


def saved_backup(phone, raw=None):
    path = phone.root / "original.json"
    path.write_text(json.dumps(phone.layout.raw if raw is None else raw, default=str))
    return path


def changed_layout(phone):
    raw = copy.deepcopy(phone.layout.raw)
    raw.append([{"bundleIdentifier": "example.extra"}])
    return HomeScreenLayout(raw=raw)


def test_default_safety_test_never_writes(phone):
    result = CliRunner().invoke(cli.main, ["safety-test"])
    assert result.exit_code == 0, result.output
    phone.write.assert_not_called()
    assert "Read-only checks passed" in result.output
    assert len(safety.list_backups()) == 1


@pytest.mark.parametrize("answer", ["n\n", "\n", ""])
def test_write_test_requires_yes(phone, answer):
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input=answer)
    phone.write.assert_not_called()
    assert "may add or move icons" in result.output


def test_confirmed_test_writes_once_after_backup(phone):
    def check_backup(lockdown, raw):
        assert json.loads(safety.list_backups()[0].read_text()) == raw

    phone.write.side_effect = check_backup
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input="y\n")
    assert result.exit_code == 0, result.output
    phone.write.assert_called_once()
    assert "does not guarantee" in result.output


def test_backup_drift_stops_and_preserves_original(phone):
    phone.read.return_value = changed_layout(phone)
    with pytest.raises(RuntimeError, match="changed"):
        safety.verified_backup(object(), phone.layout)
    phone.write.assert_not_called()
    assert json.loads(safety.list_backups()[0].read_text()) == phone.layout.raw


def test_drift_during_confirmation_prevents_write(phone):
    phone.read.side_effect = [phone.layout, phone.layout, changed_layout(phone)]
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input="y\n")
    assert result.exit_code == 1, result.output
    phone.write.assert_not_called()


def test_drift_during_backup_prevents_write(phone):
    phone.read.side_effect = [phone.layout, changed_layout(phone)]
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input="y\n")
    assert result.exit_code == 1, result.output
    phone.write.assert_not_called()


def test_pre_write_check_only_saves_backup(phone, monkeypatch):
    confirm = Mock(return_value=True)
    monkeypatch.setattr("click.confirm", confirm)
    success, path = safety.pre_write_safety_check(object(), phone.layout)
    assert success and path.exists()
    phone.write.assert_not_called()
    confirm.assert_not_called()


def test_write_test_detects_added_icons_without_retry(phone):
    phone.read.side_effect = [phone.layout, phone.layout, phone.layout, changed_layout(phone)]
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input="y\n")
    assert result.exit_code == 1, result.output
    phone.write.assert_called_once()
    assert "do not retry" in result.output.lower()


@pytest.mark.parametrize("stage", ["write", "read"])
def test_write_test_error_warns_phone_may_have_changed(phone, stage):
    if stage == "write":
        phone.write.side_effect = OSError("Disconnected")
    else:
        phone.read.side_effect = [phone.layout] * 3 + [OSError("Disconnected")]
    result = CliRunner().invoke(cli.main, ["safety-test", "--write-roundtrip"], input="y\n")
    assert result.exit_code == 1, result.output
    phone.write.assert_called_once()
    assert "phone may have changed" in result.output.lower()
    assert "do not retry" in result.output.lower()


def test_backup_names_never_overwrite(phone, monkeypatch):
    clock = Mock()
    clock.now.return_value = datetime(2026, 1, 1, 12)
    monkeypatch.setattr(safety, "datetime", clock)
    paths = [safety.verified_backup(object(), phone.layout) for _ in range(12)]
    assert len(set(paths)) == 12
    assert safety.list_backups() == list(reversed(paths))


def test_manual_backup_preserves_safety_backup(phone, monkeypatch):
    clock = Mock()
    clock.now.return_value = datetime(2026, 1, 1, 12)
    monkeypatch.setattr(safety, "datetime", clock)
    path = safety.verified_backup(object(), phone.layout)
    original = path.read_bytes()
    phone.read.return_value = changed_layout(phone)
    result = CliRunner().invoke(cli.main, ["backup"])
    assert result.exit_code == 0, result.output
    assert path.read_bytes() == original
    assert len(safety.list_backups()) == 2
    phone.write.assert_not_called()


def test_backup_read_failure_reports_saved_file(phone):
    phone.read.side_effect = OSError("Disconnected")
    with pytest.raises(RuntimeError) as raised:
        safety.verified_backup(object(), phone.layout)
    assert str(safety.list_backups()[0]) in str(raised.value)
    assert json.loads(safety.list_backups()[0].read_text()) == phone.layout.raw
    phone.write.assert_not_called()


def test_restore_mismatch_is_failure_and_keeps_both_backups(phone):
    path = saved_backup(phone)
    original = path.read_bytes()
    phone.read.side_effect = [phone.layout, phone.layout, changed_layout(phone)]
    result = CliRunner().invoke(cli.main, ["restore", str(path)])
    assert result.exit_code == 1, result.output
    phone.write.assert_called_once()
    assert "Restore verification failed" in result.output
    assert path.read_bytes() == original
    assert len(safety.list_backups()) == 1


def test_restore_metadata_difference_fails(phone):
    path = saved_backup(phone)
    different = copy.deepcopy(phone.layout.raw)
    different[1][0]["displayName"] = "Changed"
    phone.read.side_effect = [phone.layout, phone.layout, HomeScreenLayout(raw=different)]
    assert safety.restore_from_backup(object(), path) is False
    phone.write.assert_called_once()


@pytest.mark.parametrize("stage", ["write", "read"])
def test_restore_error_reports_uncertain_state(phone, stage):
    path = saved_backup(phone)
    if stage == "write":
        phone.write.side_effect = OSError("Disconnected")
    else:
        phone.read.side_effect = [phone.layout, phone.layout, OSError("Disconnected")]
    result = CliRunner().invoke(cli.main, ["restore", str(path)])
    assert result.exit_code == 1, result.output
    phone.write.assert_called_once()
    assert "phone may have changed" in result.output.lower()
    assert "Layout before this restore" in result.output


def test_restore_checks_current_backup_before_writing(phone):
    path = saved_backup(phone)
    phone.read.side_effect = [phone.layout, changed_layout(phone)]
    assert safety.restore_from_backup(object(), path) is False
    phone.write.assert_not_called()


@pytest.mark.parametrize("raw", [[], [[]], {}, {"iconLists": []}, "bad", [42], [[{}]]])
def test_restore_rejects_empty_or_invalid_backups(phone, raw):
    path = saved_backup(phone, raw)
    assert safety.restore_from_backup(object(), path) is False
    phone.read.assert_not_called()
    phone.write.assert_not_called()


def test_restore_invalid_json_does_not_write(phone):
    path = saved_backup(phone)
    path.write_text("{")
    assert safety.restore_from_backup(object(), path) is False
    phone.write.assert_not_called()


def test_restore_unchanged_succeeds(phone):
    path = saved_backup(phone)
    assert safety.restore_from_backup(object(), path) is True
    phone.write.assert_called_once()


def test_restore_recovers_icon_date_type(phone):
    date = datetime(2026, 1, 1, 12, 30)
    phone.layout.raw[1][0]["iconModDate"] = date
    phone.layout.raw[1][0]["displayName"] = "2026-01-01"
    path = saved_backup(phone)
    assert safety.restore_from_backup(object(), path) is True
    state = phone.write.call_args.args[1]
    assert state[1][0]["iconModDate"] == date
    assert state[1][0]["displayName"] == "2026-01-01"


def test_restore_widget_only_layout(phone):
    phone.layout.raw = [[], [{"iconType": "widget", "containerBundleIdentifier": "example.widget"}]]
    path = saved_backup(phone)
    assert safety.restore_from_backup(object(), path) is True
    phone.write.assert_called_once()


def test_restore_legacy_layout(phone):
    phone.layout.raw = {
        "buttonBar": [],
        "iconLists": [["example.app"]],
        "ignored": ["example.hidden"],
    }
    path = saved_backup(phone)
    assert safety.restore_from_backup(object(), path) is True
    assert phone.write.call_args.args[1] == phone.layout.raw
