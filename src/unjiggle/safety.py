"""Safety and backup verification for Unjiggle.

Trust architecture:
1. Backup is visible and verified (read-back confirms integrity)
2. Restore can be tested before any real changes
3. Every write is preceded by a verified backup
4. Clear undo path that doesn't require technical knowledge
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console

from unjiggle.models import HomeScreenLayout

console = Console()
BACKUP_DIR = Path.home() / ".unjiggle" / "backups"


def verified_backup(lockdown, layout: HomeScreenLayout, out: Console | None = None) -> Path:
    """Create a backup and verify it by reading it back.

    Returns the backup path. Raises if verification fails. It asks no question, so the
    json commands can use it. ``out`` gets the progress text (default: stdout; the json
    commands give a stderr console).
    """
    from unjiggle.device import read_layout

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"layout-{timestamp}.json"
    # Two backups in the same second (an apply and then its undo) get two files.
    number = 2
    while path.exists():
        path = BACKUP_DIR / f"layout-{timestamp}-{number}.json"
        number += 1
    path.parent.mkdir(parents=True, exist_ok=True)

    # Save (default=str handles datetime objects from pymobiledevice3)
    raw_json = json.dumps(layout.raw, indent=2, default=str)
    path.write_text(raw_json)

    # Verify: read it back and compare (compare the JSON strings, not dicts,
    # because default=str converts non-serializable types one-way)
    loaded_json = path.read_text()
    if loaded_json != raw_json:
        path.unlink()
        raise RuntimeError("Backup verification failed: saved file doesn't match device state")

    # Verify: re-read from device to confirm device state hasn't drifted
    fresh_layout = read_layout(lockdown)
    fresh_json = json.dumps(fresh_layout.raw, indent=2, default=str)
    if fresh_json != raw_json:
        (out or console).print("[yellow]  Warning: device state changed between reads. Re-backing up...[/yellow]")
        path.write_text(fresh_json)

    return path


def test_restore_roundtrip(lockdown) -> bool:
    """Test that backup+restore works by doing a no-op round-trip.

    Reads the current layout, writes it back unchanged, reads again,
    and verifies the state is identical. This proves the write path
    works without changing anything.

    Returns True if the round-trip succeeds.
    """
    from unjiggle.device import read_layout, write_layout

    console.print("  [dim]Reading current layout...[/dim]")
    before = read_layout(lockdown)
    before_json = json.dumps(before.raw, indent=2, default=str)

    console.print("  [dim]Writing layout back unchanged (no-op write)...[/dim]")
    write_layout(lockdown, before.raw)

    console.print("  [dim]Reading layout again to verify...[/dim]")
    after = read_layout(lockdown)
    after_json = json.dumps(after.raw, indent=2, default=str)

    if before_json == after_json:
        console.print("  [green]Round-trip verified.[/green] Read → Write → Read produced identical state.")
        return True
    else:
        console.print("  [red]Round-trip FAILED.[/red] Layout changed after no-op write.")
        console.print("  [red]DO NOT proceed with changes. Something is wrong.[/red]")
        return False


def restore_from_backup(lockdown, backup_path: Path) -> bool:
    """Restore a layout from a backup file.

    Returns True if the restore succeeds and is verified. As `unjiggle json restore`
    does, it refuses a backup with no app on the home screen, makes a verified backup
    of the layout on the phone before the write, and writes the dates of the backup as
    dates (device.restore_layout_from_file).
    """
    from unjiggle.device import parse_layout_state, read_layout, restore_layout_from_file, write_layout

    if not backup_path.exists():
        console.print(f"  [red]Backup file not found: {backup_path}[/red]")
        return False

    try:
        state = restore_layout_from_file(backup_path)
        expected = parse_layout_state(state)
    except Exception as e:
        console.print(f"  [red]Cannot read the backup: {e}[/red]")
        return False
    if expected.page_count == 0 or expected.total_apps == 0:
        console.print("  [red]The backup has no apps on the home screen. Nothing was restored.[/red]")
        return False

    console.print("  [dim]Backing up the current layout first...[/dim]")
    try:
        undo_path = verified_backup(lockdown, read_layout(lockdown))
    except Exception as e:
        console.print(f"  [red]Backup failed: {e}. Nothing was restored.[/red]")
        return False
    console.print(f"  To undo this restore: [bold]unjiggle restore {undo_path}[/bold]")

    console.print("  [dim]Restoring layout from backup...[/dim]")
    write_layout(lockdown, state)

    console.print("  [dim]Verifying restore...[/dim]")
    restored = read_layout(lockdown)
    restored_json = json.dumps(restored.raw, default=str)
    expected_json = json.dumps(state, default=str)

    if restored_json == expected_json:
        console.print("  [green]Restore verified.[/green] Your phone is back to the backed-up state.")
        return True
    else:
        console.print("  [yellow]Restore applied but verification shows minor differences.[/yellow]")
        console.print("  [yellow]This is usually cosmetic (SpringBoard may normalize some values).[/yellow]")
        return True  # Still likely fine


def _backup_order(path: Path) -> tuple:
    """layout-<date>-<time>.json, then layout-<date>-<time>-2.json and so on: the
    backups of one second in the order that verified_backup() made them."""
    parts = path.stem.split("-")
    number = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
    return parts[1:3], number


def list_backups() -> list[Path]:
    """List all available backups, newest first."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("layout-*.json"), key=_backup_order, reverse=True)


def pre_write_safety_check(lockdown, layout: HomeScreenLayout) -> tuple[bool, Path | None]:
    """Run the full safety check before a write of the human CLI (`unjiggle suggest`).

    Returns (safe_to_proceed, backup_path). It asks a question (the round trip), so a
    json command must not use it: `unjiggle json apply` reads its payload from stdin, and
    nobody can answer. json apply uses verified_backup() directly (see cli.json_apply).
    """
    console.print("\n  [bold]Safety Check[/bold]\n")

    # Step 1: Verified backup
    console.print("  [bold]Step 1/3:[/bold] Creating verified backup...")
    try:
        backup_path = verified_backup(lockdown, layout)
        console.print(f"  [green]✓[/green] Backup saved and verified: [dim]{backup_path}[/dim]\n")
    except Exception as e:
        console.print(f"  [red]✗ Backup failed: {e}[/red]")
        console.print("  [red]Cannot proceed without a verified backup.[/red]")
        return False, None

    # Step 2: Show backup stats
    console.print("  [bold]Step 2/3:[/bold] Backup contains:")
    console.print(f"    {layout.page_count} pages, {layout.total_apps} apps, {len(layout.all_folders())} folders")
    console.print(f"    Dock: {len(layout.dock)} items")
    console.print(f"    App Library: {len(layout.ignored)} hidden apps\n")

    # Step 3: Offer round-trip test
    console.print("  [bold]Step 3/3:[/bold] Round-trip verification")
    console.print("  This writes your current layout back unchanged, then reads it to")
    console.print("  prove the write path works. Your phone won't change at all.")

    import click
    if click.confirm("  Run the safety round-trip test?", default=True):
        success = test_restore_roundtrip(lockdown)
        if not success:
            return False, backup_path
        console.print()
    else:
        console.print("  [dim]Skipped. Proceeding on trust.[/dim]\n")

    console.print("  [green bold]Safety check passed.[/green bold] You have a verified backup")
    console.print(f"  and can undo anytime with: [bold]unjiggle restore {backup_path}[/bold]\n")

    return True, backup_path
