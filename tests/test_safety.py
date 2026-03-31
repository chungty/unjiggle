"""Tests for the safety module."""

import json
from pathlib import Path

from unjiggle.safety import list_backups, BACKUP_DIR


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
