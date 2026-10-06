"""Safety and backup verification for Unjiggle.

Trust architecture:
1. Backup is visible and verified (read-back confirms integrity)
2. A write test requires explicit consent and can change the phone
3. Every write is preceded by a verified backup
4. Restore failures are reported without an automatic retry
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
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Save (default=str handles datetime objects from pymobiledevice3)
    raw_json = json.dumps(layout.raw, indent=2, default=str)
    number = 1
    while True:
        suffix = f"-{number}" if number > 1 else ""
        path = BACKUP_DIR / f"layout-{timestamp}{suffix}.json"
        try:
            with path.open("x") as backup:
                backup.write(raw_json)
            break
        except FileExistsError:
            number += 1

    # Verify: read it back and compare (compare the JSON strings, not dicts,
    # because default=str converts non-serializable types one-way)
    loaded_json = path.read_text()
    if loaded_json != raw_json:
        path.unlink()
        raise RuntimeError("Backup verification failed: saved file doesn't match device state")

    # Verify: re-read from device to confirm device state hasn't drifted
    try:
        fresh_layout = read_layout(lockdown)
    except Exception as error:
        raise RuntimeError(
            f"The backup was saved at {path}, but the phone could not be read again: {error}. "
            "No changes were sent to the phone."
        ) from error
    fresh_json = json.dumps(fresh_layout.raw, indent=2, default=str)
    if fresh_json != raw_json:
        raise RuntimeError(
            f"Device layout changed while verifying the backup. No device write was performed. "
            f"The original read is saved at {path}. Refresh the layout before trying again."
        )

    return path


def print_ios_added(added: list[dict], reference: str, out: Console | None = None) -> None:
    """Tell the owner about the apps that iOS added at a write
    (layout_engine.ios_added_apps), on one line, so a client can show it. ``out`` gets
    the text (default: stdout). The names come from the phone, so Rich does not read
    them as markup or as emoji codes (such as ":fire:")."""
    from unjiggle.layout_engine import describe_ios_added

    (out or console).print(
        f"  {describe_ios_added(added, reference)}",
        markup=False, emoji=False, highlight=False, soft_wrap=True,
    )


def test_restore_roundtrip(lockdown, backup_path: Path) -> bool:
    """Write the current layout and check for an identical read-back.

    The caller must obtain write consent and retain a verified backup first.
    SpringBoard can change the layout even when the input is unchanged.
    Returns False for any difference; never retries or writes a rollback.
    """
    from unjiggle.device import read_layout, write_layout

    console.print("  [dim]Reading current layout...[/dim]")
    before = read_layout(lockdown)
    before_json = json.dumps(before.raw, indent=2, default=str)
    backup_json = json.dumps(json.loads(backup_path.read_text()), indent=2, default=str)
    if before_json != backup_json:
        console.print("  [red]Write test cancelled.[/red] The layout changed since the backup. No device write was performed.")
        return False

    console.print("  [yellow]Writing the current layout. iOS may add or move icons.[/yellow]")
    write_layout(lockdown, before.raw)

    console.print("  [dim]Reading layout again to verify...[/dim]")
    after = read_layout(lockdown)
    after_json = json.dumps(after.raw, indent=2, default=str)

    if before_json == after_json:
        console.print("  [green]Round-trip verified.[/green] Read → Write → Read produced identical state.")
        return True
    from unjiggle.layout_engine import ios_added_apps

    ios_added = ios_added_apps(after, before, before)
    if ios_added:
        print_ios_added(ios_added, "layout before the write")
    console.print("  [red]Round-trip FAILED.[/red] The read-back state differs from before the write.")
    console.print("  [red]Stop here. Keep the backup; do not retry or restore automatically.[/red]")
    return False


def _backup_is_supported(state) -> bool:
    from unjiggle.device import _parse_item

    if isinstance(state, list):
        pages = state
    elif isinstance(state, dict):
        dock = state.get("buttonBar", [])
        screens = state.get("iconLists", [])
        if not isinstance(dock, list) or not isinstance(screens, list):
            return False
        pages = [dock, *screens]
    else:
        return False
    has_items = False
    for page in pages:
        if not isinstance(page, list):
            return False
        for raw_item in page:
            item = _parse_item(raw_item)
            if item is None:
                return False
            if item.app or item.widget or (item.folder and any(item.folder.pages)):
                has_items = True
    return has_items


def restore_from_backup(lockdown, backup_path: Path) -> bool:
    """Restore a layout from a backup file.

    Returns True only for an exact read-back match. Unlike the JSON restore contract,
    extra apps and metadata-only differences also fail. Refuses an empty backup,
    backs up the current layout first, and restores icon dates to their original type.
    """
    from unjiggle.device import parse_layout_state, read_layout, restore_layout_from_file, write_layout

    if not backup_path.exists():
        console.print(f"  [red]Backup file not found: {backup_path}[/red]")
        return False

    try:
        state = restore_layout_from_file(backup_path)
        if not _backup_is_supported(state):
            console.print("  [red]The backup is empty or has an unsupported layout. Nothing was restored.[/red]")
            return False
        expected = parse_layout_state(state)
    except Exception as e:
        console.print(f"  [red]Cannot read the backup: {e}[/red]")
        return False

    console.print("  [dim]Backing up the current layout first...[/dim]")
    try:
        current = read_layout(lockdown)
        undo_path = verified_backup(lockdown, current)
    except Exception as e:
        console.print(f"  [red]Backup failed: {e}. Nothing was restored.[/red]")
        return False
    console.print(f"  Layout before this restore saved at: [bold]{undo_path}[/bold]")

    try:
        console.print("  [dim]Restoring layout from backup...[/dim]")
        write_layout(lockdown, state)

        console.print("  [dim]Verifying restore...[/dim]")
        restored = read_layout(lockdown)
    except Exception as error:
        console.print(f"  [red]Restore could not be verified: {error}[/red]")
        console.print("  The phone may have changed. Do not retry or restore automatically.")
        console.print(f"  Requested backup: {backup_path}", markup=False, highlight=False, soft_wrap=True)
        console.print(f"  Layout before this restore: {undo_path}", markup=False, highlight=False, soft_wrap=True)
        return False
    restored_json = json.dumps(restored.raw, default=str)
    expected_json = json.dumps(state, default=str)

    if restored_json == expected_json:
        console.print("  [green]Restore verified.[/green] The phone currently matches the backup.")
        console.print("  This does not guarantee that the layout will stay the same after a reboot.")
        return True
    # iOS can add an app from the App Library to the home screen at the write. As in
    # `unjiggle json restore`, only the backup tells which apps were on the home screen,
    # and the layout before the restore only tells when the write had no effect.
    from unjiggle.layout_engine import ios_added_apps

    ios_added = ios_added_apps(restored, expected, current, apps_of_before=False)
    if ios_added:
        print_ios_added(ios_added, "backup")
    console.print("  [red]Restore verification failed.[/red] The read-back state does not match the backup.")
    console.print("  Keep both backups. Do not retry or restore automatically; another write may change the layout again.")
    return False


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
    """Verify a backup before the requested write, without a separate test write.

    Returns (backup_verified, backup_path). A verified backup does not guarantee that
    iOS will preserve the requested layout or that a later restore will succeed.
    """
    console.print("\n  [bold]Safety Check[/bold]\n")

    # Step 1: Verified backup
    console.print("  [bold]Step 1/2:[/bold] Creating verified backup...")
    try:
        backup_path = verified_backup(lockdown, layout)
        console.print(f"  [green]✓[/green] Backup saved and verified: [dim]{backup_path}[/dim]\n")
    except Exception as e:
        console.print(f"  [red]✗ Backup failed: {e}[/red]")
        console.print("  [red]Cannot proceed without a verified backup.[/red]")
        return False, None

    # Step 2: Show backup stats
    console.print("  [bold]Step 2/2:[/bold] Backup contains:")
    console.print(f"    {layout.page_count} pages, {layout.total_apps} apps, {len(layout.all_folders())} folders")
    console.print(f"    Dock: {len(layout.dock)} items")
    console.print(f"    App Library: {len(layout.ignored)} hidden apps\n")

    console.print("  [green bold]Backup verified.[/green bold] No test write was performed.")
    console.print("  iOS may add or move icons when applying a layout. A backup does not guarantee a successful restore.\n")

    return True, backup_path
