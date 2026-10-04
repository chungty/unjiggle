"""Guards for the public CLI and documentation boundary."""

from __future__ import annotations

from pathlib import Path
from struct import unpack

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


def test_quickstart_keeps_demo_before_phone_and_json_reference():
    readme = (REPO_ROOT / "README.md").read_text()

    assert readme.index("unjiggle demo") < readme.index("unjiggle scan")
    assert readme.index("unjiggle scan") < readme.index("## Commands and API")
    assert "`unjiggle.cli.JSON_CONTRACT`" in readme
    assert "https://unjiggle.com/?source=github-readme" in readme
    assert "docs/AI-ASSISTANTS.md" in readme


def test_assistant_guide_distinguishes_scan_and_write_consent():
    guide = (REPO_ROOT / "docs" / "AI-ASSISTANTS.md").read_text()

    assert guide.index("unjiggle demo") < guide.index("unjiggle scan")
    assert "https://unjiggle.com/?source=github-agent-guide" in guide
    for requirement in (
        "Claude, Codex, or Cursor",
        "hosted assistant",
        "`unjiggle go`",
        "`unjiggle safety-test`",
        "`snapshot_id`",
        "backup",
        "**stop**",
        "Do not auto-retry",
    ):
        assert requirement in guide


def test_social_preview_has_source_and_correct_png_dimensions():
    asset = REPO_ROOT / "assets" / "social-preview"
    assert 'width="1280" height="640"' in asset.with_suffix(".svg").read_text()
    png_header = asset.with_suffix(".png").read_bytes()[:24]
    assert png_header[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    assert unpack(">II", png_header[16:24]) == (1280, 640)
    assert (REPO_ROOT / "assets" / "render-social-preview.py").is_file()
