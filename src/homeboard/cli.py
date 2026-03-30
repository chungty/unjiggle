"""HomeBoard CLI entry point."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from homeboard import __version__

console = Console()
HOMEBOARD_DIR = Path.home() / ".homeboard"
BACKUP_DIR = HOMEBOARD_DIR / "backups"


@click.group()
@click.version_option(version=__version__)
def main():
    """HomeBoard: AI-powered iPhone home screen organizer."""
    pass


@main.command()
def scan():
    """Read and display your iPhone's home screen layout."""
    from homeboard.device import connect, read_layout
    from homeboard.itunes import enrich_layout

    console.print("\n[bold]HomeBoard[/bold] — Scanning your iPhone...\n")

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] Connect via USB and tap Trust.\n{e}")
        sys.exit(1)

    console.print(f"  Device: [cyan]{device.name}[/cyan] ({device.model})")
    console.print(f"  iOS:    [cyan]{device.ios_version}[/cyan]")
    console.print(f"  UDID:   [dim]{device.udid}[/dim]\n")

    layout = read_layout(lockdown)
    console.print(f"  Pages:  [yellow]{layout.page_count}[/yellow]")
    console.print(f"  Apps:   [yellow]{layout.total_apps}[/yellow]")
    console.print(f"  Dock:   [yellow]{len(layout.dock)}[/yellow] items")
    console.print(f"  App Library: [yellow]{len(layout.ignored)}[/yellow] hidden apps\n")

    console.print("[dim]Fetching app metadata from iTunes...[/dim]")
    with Progress() as progress:
        task = progress.add_task("Looking up apps...", total=len(layout.all_bundle_ids))
        metadata = enrich_layout(layout, lambda done, total: progress.update(task, completed=done))

    # Display pages
    for i, page in enumerate(layout.pages):
        table = Table(title=f"Page {i + 1}", show_header=False, box=None, padding=(0, 2))
        for _ in range(4):
            table.add_column(width=20)

        row = []
        for item in page:
            if item.is_app:
                meta = metadata.get(item.app.bundle_id, {})
                cat = meta.get("super_category", "?")
                name = meta.get("name", item.app.bundle_id.split(".")[-1])
                row.append(f"[{_cat_color(cat)}]{name}[/]")
            elif item.is_folder:
                app_count = sum(len(p) for p in item.folder.pages)
                row.append(f"[bold]📁 {item.folder.display_name}[/bold] ({app_count})")
            elif item.is_widget:
                row.append(f"[dim]⬛ Widget[/dim]")

            if len(row) == 4:
                table.add_row(*row)
                row = []

        if row:
            while len(row) < 4:
                row.append("")
            table.add_row(*row)

        console.print(table)
        console.print()

    console.print("[green]Scan complete.[/green] Run [bold]homeboard score[/bold] to see your organization score.\n")


@main.command()
def score():
    """Score your home screen organization (0-100)."""
    from homeboard.device import connect, read_layout
    from homeboard.itunes import enrich_layout
    from homeboard.scoring import compute_score

    console.print("\n[bold]HomeBoard[/bold] — Scoring your layout...\n")

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] {e}")
        sys.exit(1)

    layout = read_layout(lockdown)
    metadata = enrich_layout(layout)
    breakdown = compute_score(layout, metadata)

    console.print(f"  [bold]Organization Score: {breakdown.total:.0f}/100[/bold] — {breakdown.label}\n")
    console.print(f"  Page Efficiency:    {breakdown.page_efficiency:.0f}/100 (weight 30%)")
    console.print(f"  Category Coherence: {breakdown.category_coherence:.0f}/100 (weight 30%)")
    console.print(f"  Folder Usage:       {breakdown.folder_usage:.0f}/100 (weight 20%)")
    console.print(f"  Dock Quality:       {breakdown.dock_quality:.0f}/100 (weight 20%)")
    console.print()


@main.command()
def backup():
    """Backup your current home screen layout."""
    from homeboard.device import backup_layout, connect, read_layout

    console.print("\n[bold]HomeBoard[/bold] — Backing up layout...\n")

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] {e}")
        sys.exit(1)

    layout = read_layout(lockdown)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"layout-{timestamp}.json"
    backup_layout(layout, path)
    console.print(f"  [green]Saved to:[/green] {path}\n")


@main.command()
@click.argument("backup_file", type=click.Path(exists=True), required=False)
def restore(backup_file: str | None):
    """Restore a previously backed up layout. If no file specified, shows available backups."""
    from homeboard.device import connect
    from homeboard.safety import list_backups, restore_from_backup

    console.print("\n[bold]HomeBoard[/bold] — Restore\n")

    if not backup_file:
        backups = list_backups()
        if not backups:
            console.print("  No backups found. Run [bold]homeboard backup[/bold] first.\n")
            return
        console.print("  Available backups (newest first):\n")
        for i, bp in enumerate(backups[:10]):
            size = bp.stat().st_size
            console.print(f"    {i + 1}. {bp.name} ({size:,} bytes)")
        console.print(f"\n  Usage: [bold]homeboard restore {backups[0]}[/bold]\n")
        return

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] {e}")
        sys.exit(1)

    console.print(f"  Device: [cyan]{device.name}[/cyan] (iOS {device.ios_version})\n")
    restore_from_backup(lockdown, Path(backup_file))
    console.print()


@main.command(name="safety-test")
def safety_test():
    """Test that backup and restore work correctly (no-op round-trip)."""
    from homeboard.device import connect, read_layout
    from homeboard.safety import test_restore_roundtrip, verified_backup

    console.print("\n[bold]HomeBoard[/bold] — Safety Test\n")
    console.print("  This test proves that HomeBoard can safely read and write")
    console.print("  your home screen without changing anything.\n")

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] {e}")
        sys.exit(1)

    console.print(f"  Device: [cyan]{device.name}[/cyan] (iOS {device.ios_version})\n")

    # Step 1: Verified backup
    console.print("  [bold]1. Creating verified backup...[/bold]")
    layout = read_layout(lockdown)
    try:
        backup_path = verified_backup(lockdown, layout)
        console.print(f"     [green]✓[/green] Backup saved: {backup_path}")
        console.print(f"     [green]✓[/green] {layout.page_count} pages, {layout.total_apps} apps captured\n")
    except Exception as e:
        console.print(f"     [red]✗ Backup failed: {e}[/red]\n")
        sys.exit(1)

    # Step 2: Round-trip test
    console.print("  [bold]2. Round-trip test (write current layout back, read again)...[/bold]")
    success = test_restore_roundtrip(lockdown)
    console.print()

    if success:
        console.print("  [green bold]All safety tests passed.[/green bold]")
        console.print("  HomeBoard can safely read and write your home screen layout.")
        console.print(f"  Your backup is at: {backup_path}")
        console.print(f"\n  You're safe to run [bold]homeboard suggest[/bold] now.\n")
    else:
        console.print("  [red bold]Safety test failed.[/red bold]")
        console.print("  Do NOT run homeboard suggest until this is resolved.\n")
        sys.exit(1)


@main.command()
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", help="Anthropic API key (or set ANTHROPIC_API_KEY)")
@click.option("--model", default="claude-sonnet-4-20250514", help="Model to use for analysis")
def analyze(api_key: str | None, model: str):
    """AI-powered analysis of your home screen."""
    from homeboard.analyzer import analyze as run_analysis
    from homeboard.device import connect, read_layout
    from homeboard.itunes import enrich_layout
    from homeboard.scoring import compute_score

    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set.[/red] Set it or pass --api-key.")
        sys.exit(1)

    console.print("\n[bold]HomeBoard[/bold] — AI Analysis...\n")

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] {e}")
        sys.exit(1)

    console.print(f"  Device: [cyan]{device.name}[/cyan] ({device.model}, iOS {device.ios_version})\n")

    layout = read_layout(lockdown)
    console.print("[dim]Fetching app metadata...[/dim]")
    metadata = enrich_layout(layout)
    score = compute_score(layout, metadata)

    console.print(f"  Score: [bold]{score.total:.0f}/100[/bold] ({score.label})\n")
    console.print("[dim]Running AI analysis (Claude Sonnet)...[/dim]\n")

    result = run_analysis(layout, metadata, score, api_key=api_key, model=model)

    console.print(f"  [bold magenta]{result.archetype}[/bold magenta]\n")

    for i, obs in enumerate(result.observations):
        track_color = {"cleanup": "red", "organization": "blue", "optimization": "green"}.get(obs.track, "white")
        console.print(f"  [{track_color}]#{i + 1} [{obs.track.upper()}][/{track_color}] [bold]{obs.title}[/bold]")
        console.print(f"  {obs.narrative}\n")
        if obs.operations:
            for op in obs.operations:
                app_names = []
                for bid in op.bundle_ids[:5]:
                    meta = metadata.get(bid, {})
                    app_names.append(meta.get("name", bid.split(".")[-1]) if meta else bid.split(".")[-1])
                names_str = ", ".join(app_names)
                if len(op.bundle_ids) > 5:
                    names_str += f" +{len(op.bundle_ids) - 5} more"
                console.print(f"    → {op.action}: {names_str}")
                if op.folder_name:
                    console.print(f"      folder: {op.folder_name}")
            console.print()

    if result.personality:
        console.print(f"\n  [italic dim]{result.personality}[/italic dim]\n")

    console.print("[green]Analysis complete.[/green] Run [bold]homeboard suggest[/bold] to apply changes interactively.\n")


@main.command()
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", help="Anthropic API key")
@click.option("--model", default="claude-sonnet-4-20250514", help="Model for analysis")
@click.option("--apply-all", is_flag=True, help="Apply all suggestions without stepping through (Just Fix It mode)")
def suggest(api_key: str | None, model: str, apply_all: bool):
    """AI-powered suggestions with live preview. Accept/skip each change."""
    from homeboard.analyzer import analyze as run_analysis, preview_operations
    from homeboard.device import backup_layout, connect, read_layout, write_layout
    from homeboard.itunes import enrich_layout
    from homeboard.scoring import compute_score

    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    console.print("\n[bold]HomeBoard[/bold] — Smart Suggestions...\n")

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] {e}")
        sys.exit(1)

    layout = read_layout(lockdown)
    metadata = enrich_layout(layout)
    score_before = compute_score(layout, metadata)

    console.print(f"  Score: [bold]{score_before.total:.0f}/100[/bold] ({score_before.label})")
    console.print(f"  Pages: {layout.page_count}, Apps: {layout.total_apps}\n")
    console.print("[dim]Running AI analysis...[/dim]\n")

    result = run_analysis(layout, metadata, score_before, api_key=api_key, model=model)

    # Collect accepted operations
    accepted_ops = []

    if apply_all:
        # Just Fix It mode: collect all operations
        for obs in result.observations:
            accepted_ops.extend(obs.operations)
        console.print(f"  [bold]Just Fix It mode:[/bold] applying all {len(result.observations)} suggestions\n")
    else:
        # Stepwise mode
        for i, obs in enumerate(result.observations):
            track_color = {"cleanup": "red", "organization": "blue", "optimization": "green"}.get(obs.track, "white")
            console.print(f"  [{track_color}]#{i + 1}/{len(result.observations)} [{obs.track.upper()}][/{track_color}]")
            console.print(f"  [bold]{obs.title}[/bold]")
            console.print(f"  {obs.narrative}\n")

            if obs.operations:
                # Show what would change
                preview = preview_operations(layout, accepted_ops + obs.operations)
                preview_score = compute_score(preview, metadata)
                current_score = compute_score(
                    preview_operations(layout, accepted_ops) if accepted_ops else layout,
                    metadata,
                )
                delta = preview_score.total - current_score.total
                delta_pages = preview.page_count - (preview_operations(layout, accepted_ops).page_count if accepted_ops else layout.page_count)

                console.print(f"    Preview: score {current_score.total:.0f} → {preview_score.total:.0f} ({'+' if delta >= 0 else ''}{delta:.0f})")
                if delta_pages != 0:
                    console.print(f"    Pages: {'+' if delta_pages >= 0 else ''}{delta_pages}")
                console.print()

            choice = click.prompt(
                "    [A]pply / [S]kip / [Q]uit",
                type=click.Choice(["a", "s", "q"], case_sensitive=False),
                default="a",
            )

            if choice.lower() == "a":
                accepted_ops.extend(obs.operations)
                console.print("    [green]Applied.[/green]\n")
            elif choice.lower() == "q":
                console.print("    [yellow]Stopped.[/yellow]\n")
                break
            else:
                console.print("    [dim]Skipped.[/dim]\n")

    if not accepted_ops:
        console.print("  No changes to apply.\n")
        return

    # Show final summary
    final_preview = preview_operations(layout, accepted_ops)
    final_score = compute_score(final_preview, metadata)

    console.print(f"\n  [bold]Summary:[/bold]")
    console.print(f"    Score: {score_before.total:.0f} → {final_score.total:.0f}")
    console.print(f"    Pages: {layout.page_count} → {final_preview.page_count}")
    console.print(f"    Operations: {len(accepted_ops)}")

    if result.personality:
        console.print(f"\n  [italic dim]{result.personality}[/italic dim]")

    console.print()
    if click.confirm("  Apply these changes to your iPhone?", default=True):
        from homeboard.safety import pre_write_safety_check

        safe, backup_path = pre_write_safety_check(lockdown, layout)
        if not safe:
            console.print("  [red]Safety check failed. No changes made.[/red]\n")
            return

        # Write the new layout
        write_layout(lockdown, final_preview.raw)

        # Verify the write took effect
        from homeboard.device import read_layout as re_read
        verify = re_read(lockdown)
        console.print(f"  [dim]Verifying write... {verify.page_count} pages read back.[/dim]")

        console.print(f"\n  [green bold]Done![/green bold] Your iPhone has been reorganized.")
        console.print(f"  Undo anytime: [bold]homeboard restore {backup_path}[/bold]\n")
    else:
        console.print("  [yellow]Cancelled.[/yellow] No changes made.\n")


@main.command()
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", help="Anthropic API key")
@click.option("--model", default="claude-sonnet-4-20250514", help="Model for analysis")
@click.option("--output", "-o", type=click.Path(), help="Output path for HTML report")
@click.option("--open", "open_browser", is_flag=True, help="Open the report in your browser")
def report(api_key: str | None, model: str, output: str | None, open_browser: bool):
    """Generate a shareable HTML report card with AI personality narrative."""
    from homeboard.analyzer import analyze as run_analysis
    from homeboard.device import connect, read_layout
    from homeboard.itunes import enrich_layout
    from homeboard.scoring import compute_score
    from homeboard.visualize import generate_report, save_report

    console.print("\n[bold]HomeBoard[/bold] — Generating Report...\n")

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] {e}")
        sys.exit(1)

    layout = read_layout(lockdown)
    console.print("[dim]Fetching app metadata...[/dim]")
    metadata = enrich_layout(layout)
    score = compute_score(layout, metadata)

    observations_text = []
    archetype = "The Collector"
    personality = None

    if api_key:
        console.print("[dim]Running AI analysis...[/dim]")
        result = run_analysis(layout, metadata, score, api_key=api_key, model=model)
        archetype = result.archetype
        personality = result.personality
        observations_text = [obs.narrative for obs in result.observations]
    else:
        console.print("[dim]No API key — generating report without AI narrative.[/dim]")

    html = generate_report(
        layout, metadata, score,
        archetype=archetype,
        observations=observations_text,
        personality=personality,
    )

    out_path = Path(output) if output else HOMEBOARD_DIR / "reports" / f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
    save_report(html, out_path)
    console.print(f"\n  [green]Report saved:[/green] {out_path}")

    if open_browser:
        import webbrowser
        webbrowser.open(f"file://{out_path.resolve()}")
        console.print("  [dim]Opened in browser.[/dim]")

    console.print()


def _cat_color(category: str) -> str:
    colors = {
        "Social": "blue",
        "Entertainment": "magenta",
        "Games": "red",
        "Productivity": "green",
        "Utilities": "white",
        "Health": "bright_red",
        "Finance": "cyan",
        "Shopping": "bright_magenta",
        "News": "yellow",
        "Education": "bright_cyan",
        "Travel": "bright_magenta",
        "System": "dim",
        "Other": "dim",
    }
    return colors.get(category, "white")


if __name__ == "__main__":
    main()
