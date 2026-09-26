"""Tests for the safety module."""

import copy
import json
from datetime import datetime

from unjiggle import device, safety
from unjiggle.device import parse_layout_state
from unjiggle.safety import list_backups


class TestVerifiedBackup:
    def test_backup_file_contents_match_raw(self, chaotic_layout, tmp_path):
        """Verify that what we save to disk matches the layout.raw."""
        # Simulate the save portion (without device re-read)
        raw_json = json.dumps(chaotic_layout.raw, indent=2, default=str)
        path = tmp_path / "test-backup.json"
        path.write_text(raw_json)

        loaded = json.loads(path.read_text())
        assert loaded == chaotic_layout.raw

    def test_backup_roundtrip_json(self, chaotic_layout, tmp_path):
        """Layout raw state survives JSON serialization."""
        raw = chaotic_layout.raw
        path = tmp_path / "roundtrip.json"
        path.write_text(json.dumps(raw, indent=2, default=str))
        loaded = json.loads(path.read_text())
        assert loaded == raw


class TestListBackups:
    def test_empty_when_no_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("unjiggle.safety.BACKUP_DIR", tmp_path / "nonexistent")
        assert list_backups() == []

    def test_finds_backup_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("unjiggle.safety.BACKUP_DIR", tmp_path)
        (tmp_path / "layout-20260330-120000.json").write_text("{}")
        (tmp_path / "layout-20260330-130000.json").write_text("{}")
        (tmp_path / "not-a-backup.txt").write_text("nope")

        backups = list_backups()
        assert len(backups) == 2
        # Newest first
        assert backups[0].name == "layout-20260330-130000.json"

    def test_sorted_newest_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr("unjiggle.safety.BACKUP_DIR", tmp_path)
        (tmp_path / "layout-20260101-000000.json").write_text("{}")
        (tmp_path / "layout-20261231-235959.json").write_text("{}")
        (tmp_path / "layout-20260615-120000.json").write_text("{}")

        backups = list_backups()
        names = [b.name for b in backups]
        assert names[0] == "layout-20261231-235959.json"
        assert names[-1] == "layout-20260101-000000.json"

    def test_backups_of_one_second_are_newest_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr("unjiggle.safety.BACKUP_DIR", tmp_path)
        for name in ("layout-20260925-154039.json", "layout-20260925-154039-2.json",
                     "layout-20260925-154039-10.json", "layout-20260925-154038.json"):
            (tmp_path / name).write_text("{}")

        assert [b.name for b in list_backups()] == [
            "layout-20260925-154039-10.json", "layout-20260925-154039-2.json",
            "layout-20260925-154039.json", "layout-20260925-154038.json",
        ]


class _FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 25, 15, 40, 39)


def _phone_state() -> list:
    def app(bundle_id):
        return {"bundleIdentifier": bundle_id, "displayIdentifier": bundle_id,
                "iconModDate": "2026-09-23 19:06:58.692950"}

    return [[app("com.dock.a")], [app("com.page.a"), app("com.page.b"),
            {"displayName": "F", "listType": "folder", "iconLists": [[app("com.folder.a")]]}]]


class _Phone:
    def __init__(self, raw):
        self.raw = raw
        self.writes = []

    def read_layout(self, _lockdown):
        return parse_layout_state(copy.deepcopy(self.raw))

    def write_layout(self, _lockdown, state):
        self.writes.append(copy.deepcopy(state))
        self.raw = copy.deepcopy(state)


class TestBackupNames:
    def test_two_backups_in_one_second_get_two_files(self, tmp_path, monkeypatch):
        phone = _Phone(_phone_state())
        monkeypatch.setattr(safety, "BACKUP_DIR", tmp_path)
        monkeypatch.setattr(safety, "datetime", _FixedClock)
        monkeypatch.setattr(device, "read_layout", phone.read_layout)
        layout = phone.read_layout(None)

        first = safety.verified_backup(None, layout)
        second = safety.verified_backup(None, layout)
        third = safety.verified_backup(None, layout)

        assert [first.name, second.name, third.name] == [
            "layout-20260925-154039.json", "layout-20260925-154039-2.json", "layout-20260925-154039-3.json",
        ]


class TestRestoreFromBackup:
    def _setup(self, tmp_path, monkeypatch, backup_content):
        phone = _Phone([[], [{"bundleIdentifier": "com.now.only"}]])
        monkeypatch.setattr(safety, "BACKUP_DIR", tmp_path / "backups")
        monkeypatch.setattr(device, "read_layout", phone.read_layout)
        monkeypatch.setattr(device, "write_layout", phone.write_layout)
        backup = tmp_path / "layout-before.json"
        backup.write_text(backup_content)
        return phone, backup

    def test_restore_backs_up_first_and_writes_dates_as_dates(self, tmp_path, monkeypatch):
        phone, backup = self._setup(tmp_path, monkeypatch, json.dumps(_phone_state()))

        assert safety.restore_from_backup(None, backup) is True

        assert len(phone.writes) == 1
        written = phone.writes[0]
        assert written[1][0]["iconModDate"] == datetime(2026, 9, 23, 19, 6, 58, 692950)
        assert written[1][2]["iconLists"][0][0]["iconModDate"] == datetime(2026, 9, 23, 19, 6, 58, 692950)
        undo = list_backups()
        assert len(undo) == 1
        assert json.loads(undo[0].read_text()) == [[], [{"bundleIdentifier": "com.now.only"}]]

    def _phone_that_adds_an_app(self, tmp_path, monkeypatch, change=None):
        from tests.fake_springboard import adds_unlisted_app

        phone, backup = self._setup(tmp_path, monkeypatch, json.dumps(_phone_state()))

        def write_layout(lockdown, state):
            phone.write_layout(lockdown, state)
            phone.raw = adds_unlisted_app(phone.raw)
            if change:
                change(phone.raw)

        monkeypatch.setattr(device, "write_layout", write_layout)
        return phone, backup

    def test_restore_names_an_app_that_ios_adds(self, tmp_path, monkeypatch, capsys):
        phone, backup = self._phone_that_adds_an_app(tmp_path, monkeypatch)

        assert safety.restore_from_backup(None, backup) is True

        out = capsys.readouterr().out
        assert "Restore verified." in out
        assert "iOS added an app that the backup does not have: Amazon (page 1)." in out
        assert "minor differences" not in out
        assert len(phone.writes) == 1

    def test_restore_with_another_difference_says_what_it_said_before(self, tmp_path, monkeypatch, capsys):
        def drop_page_b(state):
            del state[1][1]

        _phone, backup = self._phone_that_adds_an_app(tmp_path, monkeypatch, change=drop_page_b)

        assert safety.restore_from_backup(None, backup) is True

        out = capsys.readouterr().out
        assert "minor differences" in out
        assert "iOS added" not in out

    def test_restore_refuses_a_backup_with_no_apps(self, tmp_path, monkeypatch):
        for content in ("[]", "{}", "[[]]"):
            phone, backup = self._setup(tmp_path, monkeypatch, content)

            assert safety.restore_from_backup(None, backup) is False
            assert phone.writes == []


class TestDatesFromBackup:
    def test_only_icon_dates_that_are_iso_dates_change(self):
        state = [[{"iconModDate": "2026-09-23 19:06:58.692950", "displayName": "2026-09-23 19:06:58",
                   "iconLists": [[{"iconModDate": "2026-01-01 00:00:00"}, {"iconModDate": "not a date"}]]}]]

        restored = device.dates_from_backup(state)

        entry = restored[0][0]
        assert entry["iconModDate"] == datetime(2026, 9, 23, 19, 6, 58, 692950)
        assert entry["displayName"] == "2026-09-23 19:06:58"
        assert entry["iconLists"][0][0]["iconModDate"] == datetime(2026, 1, 1)
        assert entry["iconLists"][0][1]["iconModDate"] == "not a date"
        # The file text comes back when the state is saved again.
        assert json.loads(json.dumps(restored, default=str)) == state
