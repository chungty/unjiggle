"""Guards for the public CLI and documentation boundary."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from unjiggle.cli import json as json_group
from unjiggle.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_public_cli_excludes_private_challenge_mechanic():
    assert "challenge" not in main.commands
    assert "challenge-status" not in json_group.commands
    assert "challenge-take" not in json_group.commands
    assert "challenge-giveup" not in json_group.commands


def test_public_json_api_exposes_batch_preset_previews():
    assert "presets" in json_group.commands


def test_first_run_help_uses_public_boundary_language():
    result = CliRunner().invoke(main, [])

    assert result.exit_code == 0
    assert "Shareable diagnostics:" in result.output
    assert "viral features" not in result.output.lower()
    assert "challenge" not in result.output.lower()


def test_readme_does_not_advertise_private_mechanics():
    readme = (REPO_ROOT / "README.md").read_text()

    assert "One-Page Challenge" not in readme
    assert "unjiggle challenge take" not in readme
    assert "unjiggle challenge status" not in readme
    assert "unjiggle challenge giveup" not in readme


def test_private_challenge_module_is_not_in_public_repo():
    assert not (REPO_ROOT / "src" / "unjiggle" / "challenge.py").exists()
