"""Unjiggle CLI entry point."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from unjiggle import __version__

console = Console()
UNJIGGLE_DIR = Path.home() / ".unjiggle"
BACKUP_DIR = UNJIGGLE_DIR / "backups"


WEBSITE_URL = "https://unjiggle.com"
GITHUB_URL = "https://github.com/chungty/unjiggle"


@click.group(invoke_without_command=True)
@click.version_option(version=__version__)
@click.pass_context
def main(ctx):
    """Unjiggle: AI-powered iPhone home screen organizer."""
    if ctx.invoked_subcommand is None:
        # First-run experience: guide the user
        console.print("\n[bold]Unjiggle[/bold] v" + __version__ + "\n")
        console.print("  Connect your iPhone via USB, then:\n")
        console.print("  [bold]unjiggle go[/bold]              Full experience: scan → score → AI analysis → share card")
        console.print("  [bold]unjiggle safety-test[/bold]     Prove read/write works (changes nothing)")
        console.print("  [bold]unjiggle scan[/bold]            See your home screen layout")
        console.print("  [bold]unjiggle score[/bold]           Get your organization score")
        console.print("  [bold]unjiggle analyze[/bold]         AI-powered observations")
        console.print("  [bold]unjiggle suggest[/bold]         Interactive walkthrough with apply")
        console.print("  [bold]unjiggle report[/bold]          Generate shareable report card")
        console.print()
        console.print("  [bold magenta]Viral features:[/bold magenta]")
        console.print("  [bold]unjiggle mirror[/bold]           Personality roast from your app collection")
        console.print("  [bold]unjiggle obituary[/bold]         Eulogies for your dead apps")
        console.print("  [bold]unjiggle swipetax[/bold]         How many swipes your layout wastes")
        console.print()
        console.print(f"  [dim]GUI coming soon → {WEBSITE_URL}[/dim]")
        console.print(f"  [dim]Star us on GitHub → {GITHUB_URL}[/dim]\n")


@main.command()
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], help="API key (auto-detected)")
@click.option("--model", default=None, help="Model override")
def go(api_key: str | None, model: str | None):
    """Full experience: scan → score → AI analysis → share card. One command."""
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.scoring import compute_score

    console.print("\n[bold]Unjiggle[/bold] — Let's see your phone.\n")

    # Connect
    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] Connect via USB and tap Trust.\n{e}")
        sys.exit(1)

    console.print(f"  Device: [cyan]{device.name}[/cyan] ({device.model}, iOS {device.ios_version})\n")

    # Read layout
    layout = read_layout(lockdown)
    console.print(f"  [bold]{layout.total_apps}[/bold] apps across [bold]{layout.page_count}[/bold] pages")
    console.print(f"  {len(layout.dock)} dock items, {len(layout.all_folders())} folders\n")

    # Fetch metadata
    console.print("[dim]Looking up your apps...[/dim]")
    from rich.progress import Progress
    with Progress() as progress:
        task = progress.add_task("Fetching metadata...", total=len(layout.all_bundle_ids))
        metadata = enrich_layout(layout, lambda done, total: progress.update(task, completed=done))

    # Score
    score = compute_score(layout, metadata)
    console.print(f"\n  Organization Score: [bold]{score.total:.0f}/100[/bold] — {score.label}\n")

    # Archetype assignment (always works, no API key needed)
    from unjiggle.archetypes import assign_archetype
    archetype, tagline = assign_archetype(layout, metadata)
    personality = tagline
    observations_text = []

    console.print(f"  [bold magenta]{archetype}[/bold magenta]")
    console.print(f"  [dim]{tagline}[/dim]\n")

    # Swipe Tax (always works, no API key needed)
    from unjiggle.swipetax import compute_swipe_tax
    tax = compute_swipe_tax(layout, metadata)
    if tax.savings > 0:
        console.print(f"  [bold yellow]Swipe Tax:[/bold yellow] {tax.headline}")
        if tax.worst_offenders:
            worst = tax.worst_offenders[0]
            console.print(f"  [dim]Worst offender: {worst.name} on page {worst.page} ({worst.annual_wasted_swipes:,} wasted swipes/yr)[/dim]")
        console.print(f"  [dim]Run [bold]unjiggle swipetax[/bold] for the full breakdown.[/dim]\n")

    # AI analysis (optional, needs API key)
    if api_key:
        try:
            from unjiggle.analyzer import analyze as run_analysis
            console.print("[dim]Running AI analysis for deeper insights...[/dim]\n")
            result = run_analysis(layout, metadata, score, api_key=api_key, model=model)
            archetype = result.archetype
            personality = result.personality or tagline
            observations_text = [obs.narrative for obs in result.observations]

            console.print(f"  [bold magenta]{archetype}[/bold magenta]\n")
            for i, obs in enumerate(result.observations[:3]):
                console.print(f"  {obs.narrative}\n")
            if len(result.observations) > 3:
                console.print(f"  [dim]...and {len(result.observations) - 3} more insights in the full report.[/dim]\n")
            if result.personality:
                console.print(f"  [italic dim]{result.personality}[/italic dim]\n")
        except ImportError:
            console.print("[dim]Install AI extras for deeper analysis: pip install unjiggle[ai][/dim]\n")
    else:
        console.print("[dim]Tip: Set ANTHROPIC_API_KEY or OPENAI_API_KEY for AI-powered observations.[/dim]\n")

    # Generate share card + full report
    from unjiggle.visualize import generate_report, generate_share_card, save_report

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')

    share_html = generate_share_card(layout, metadata, score, archetype=archetype, personality=personality)
    share_path = UNJIGGLE_DIR / "reports" / f"share-{timestamp}.html"
    save_report(share_html, share_path)

    report_html = generate_report(
        layout, metadata, score,
        archetype=archetype, observations=observations_text, personality=personality,
    )
    report_path = UNJIGGLE_DIR / "reports" / f"report-{timestamp}.html"
    save_report(report_html, report_path)

    # Open share card
    import webbrowser
    webbrowser.open(f"file://{share_path.resolve()}")

    console.print(f"  [green]Share card opened in browser.[/green]")
    console.print(f"  [dim]Full report: {report_path}[/dim]\n")

    # The funnel
    console.print("  ─────────────────────────────────────────")
    console.print()
    console.print(f"  [bold]What's next?[/bold]")
    console.print(f"    🔧 [bold]unjiggle suggest[/bold] to fix your layout with AI")
    console.print(f"    🪞 [bold]unjiggle mirror[/bold] for your personality roast")
    console.print(f"    ⚰️  [bold]unjiggle obituary[/bold] for eulogies of your dead apps")
    console.print(f"    ⭐ Star us: {GITHUB_URL}")
    console.print()
    console.print(f"  [dim]A native Mac app with live preview, drag-and-drop, and animated before/after is coming soon.[/dim]")
    console.print(f"  [dim]Sign up: {WEBSITE_URL}[/dim]\n")


@main.command()
def scan():
    """Read and display your iPhone's home screen layout."""
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout

    console.print("\n[bold]Unjiggle[/bold] — Scanning your iPhone...\n")

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

    console.print("[green]Scan complete.[/green]")
    console.print(f"  Next: [bold]unjiggle score[/bold] to see your organization score")
    console.print(f"  Or:   [bold]unjiggle go[/bold] for the full experience (scan → score → AI → share card)\n")


@main.command()
def score():
    """Score your home screen organization (0-100)."""
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.scoring import compute_score

    console.print("\n[bold]Unjiggle[/bold] — Scoring your layout...\n")

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
    console.print(f"  Next: [bold]unjiggle analyze[/bold] for AI-powered insights")
    console.print(f"  Or:   [bold]unjiggle suggest[/bold] to fix it interactively\n")


@main.command()
def backup():
    """Backup your current home screen layout."""
    from unjiggle.device import backup_layout, connect, read_layout

    console.print("\n[bold]Unjiggle[/bold] — Backing up layout...\n")

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
    from unjiggle.device import connect
    from unjiggle.safety import list_backups, restore_from_backup

    console.print("\n[bold]Unjiggle[/bold] — Restore\n")

    if not backup_file:
        backups = list_backups()
        if not backups:
            console.print("  No backups found. Run [bold]unjiggle backup[/bold] first.\n")
            return
        console.print("  Available backups (newest first):\n")
        for i, bp in enumerate(backups[:10]):
            size = bp.stat().st_size
            console.print(f"    {i + 1}. {bp.name} ({size:,} bytes)")
        console.print(f"\n  Usage: [bold]unjiggle restore {backups[0]}[/bold]\n")
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
    from unjiggle.device import connect, read_layout
    from unjiggle.safety import test_restore_roundtrip, verified_backup

    console.print("\n[bold]Unjiggle[/bold] — Safety Test\n")
    console.print("  This test proves that Unjiggle can safely read and write")
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
        console.print("  Unjiggle can safely read and write your home screen layout.")
        console.print(f"  Your backup is at: {backup_path}")
        console.print(f"\n  You're safe to run [bold]unjiggle suggest[/bold] now.\n")
    else:
        console.print("  [red bold]Safety test failed.[/red bold]")
        console.print("  Do NOT run unjiggle suggest until this is resolved.\n")
        sys.exit(1)


@main.command()
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], help="API key (Anthropic or OpenAI, auto-detected)")
@click.option("--model", default=None, help="Model override (auto-detected from API key)")
def analyze(api_key: str | None, model: str):
    """AI-powered analysis of your home screen."""
    from unjiggle.analyzer import analyze as run_analysis
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.scoring import compute_score

    if not api_key:
        console.print("[red]No API key found.[/red] Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or pass --api-key.")
        sys.exit(1)

    console.print("\n[bold]Unjiggle[/bold] — AI Analysis...\n")

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
                action_label = {
                    "delete": "[red]🙏 delete[/red]",
                    "move_to_app_library": "[yellow]📦 archive[/yellow]",
                    "move_to_page": "[blue]📄 move to page[/blue]",
                    "create_folder": "[green]📁 create folder[/green]",
                    "rename_folder": "[cyan]✏️  rename folder[/cyan]",
                    "move_to_folder": "[blue]📁 move to folder[/blue]",
                }.get(op.action, op.action)
                console.print(f"    {action_label}: {names_str}")
                if op.gratitude:
                    console.print(f"    [dim italic]  \"{op.gratitude}\"[/dim italic]")
                if op.folder_name:
                    console.print(f"      → folder: {op.folder_name}")
            console.print()

    if result.personality:
        console.print(f"\n  [italic dim]{result.personality}[/italic dim]\n")

    console.print("[green]Analysis complete.[/green]")
    console.print(f"  Next: [bold]unjiggle suggest[/bold] to apply changes interactively")
    console.print(f"        [bold]unjiggle report --open[/bold] to generate your shareable report card\n")


@main.command()
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], help="API key (auto-detected)")
@click.option("--model", default=None, help="Model override (auto-detected)")
@click.option("--apply-all", is_flag=True, help="Apply all suggestions without stepping through (Just Fix It mode)")
def suggest(api_key: str | None, model: str, apply_all: bool):
    """AI-powered suggestions with live preview. Accept/skip each change."""
    from unjiggle.analyzer import analyze as run_analysis, preview_operations
    from unjiggle.device import backup_layout, connect, read_layout, write_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.scoring import compute_score

    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    console.print("\n[bold]Unjiggle[/bold] — Smart Suggestions...\n")

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

            # For cleanup observations with delete actions, offer granular choices
            has_deletes = any(op.action == "delete" for op in obs.operations)
            if has_deletes and obs.track == "cleanup":
                console.print("    For each app:")
                kept_ops = []
                for op in obs.operations:
                    if op.action == "delete":
                        for bid in op.bundle_ids:
                            meta = metadata.get(bid, {})
                            name = meta.get("name", bid.split(".")[-1]) if meta else bid.split(".")[-1]
                            if op.gratitude:
                                console.print(f"\n    [bold]{name}[/bold]")
                                console.print(f"    [dim italic]\"{op.gratitude}\"[/dim italic]")
                            choice = click.prompt(
                                f"    [D]elete / [A]rchive / [K]eep",
                                type=click.Choice(["d", "a", "k"], case_sensitive=False),
                                default="d",
                            )
                            if choice.lower() == "d":
                                kept_ops.append(LayoutOperation(action="delete", bundle_ids=[bid], gratitude=op.gratitude))
                                console.print(f"    [red]Goodbye, {name}.[/red]")
                            elif choice.lower() == "a":
                                kept_ops.append(LayoutOperation(action="move_to_app_library", bundle_ids=[bid]))
                                console.print(f"    [yellow]Archived.[/yellow]")
                            else:
                                console.print(f"    [dim]Kept.[/dim]")
                    else:
                        kept_ops.append(op)
                accepted_ops.extend(kept_ops)
                console.print()
            else:
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
        from unjiggle.layout_engine import apply_operations
        from unjiggle.safety import pre_write_safety_check

        safe, backup_path = pre_write_safety_check(lockdown, layout)
        if not safe:
            console.print("  [red]Safety check failed. No changes made.[/red]\n")
            return

        # Build the modified raw plist using the layout engine
        modified_raw = apply_operations(layout, accepted_ops)

        # Write the modified layout to device
        write_layout(lockdown, modified_raw)

        # Verify the write took effect
        from unjiggle.device import read_layout as re_read
        verify = re_read(lockdown)
        console.print(f"  [dim]Verifying write... {verify.page_count} pages, {verify.total_apps} apps read back.[/dim]")

        console.print(f"\n  [green bold]Done![/green bold] Your iPhone has been reorganized.")
        console.print(f"  Undo anytime: [bold]unjiggle restore {backup_path}[/bold]")
        console.print()
        console.print(f"  [bold]Share your transformation:[/bold]")
        console.print(f"    [bold]unjiggle report --open[/bold] to generate a before/after share card")
        console.print()
        console.print(f"  [dim]Love Unjiggle? A native Mac app with live preview is coming.[/dim]")
        console.print(f"  [dim]Sign up: {WEBSITE_URL}  |  Star us: {GITHUB_URL}[/dim]\n")
    else:
        console.print("  [yellow]Cancelled.[/yellow] No changes made.\n")


@main.command()
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], help="API key (auto-detected)")
@click.option("--model", default=None, help="Model override (auto-detected)")
@click.option("--output", "-o", type=click.Path(), help="Output path for HTML report")
@click.option("--open", "open_browser", is_flag=True, help="Open the report in your browser")
def report(api_key: str | None, model: str, output: str | None, open_browser: bool):
    """Generate a shareable HTML report card with AI personality narrative."""
    from unjiggle.analyzer import analyze as run_analysis
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.scoring import compute_score
    from unjiggle.visualize import generate_report, save_report

    console.print("\n[bold]Unjiggle[/bold] — Generating Report...\n")

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

    # Generate both full report and share card
    from unjiggle.visualize import generate_share_card

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')

    # Share card (1080x1350, Wrapped-style)
    share_html = generate_share_card(
        layout, metadata, score,
        archetype=archetype,
        personality=personality,
    )
    share_path = UNJIGGLE_DIR / "reports" / f"share-{timestamp}.html"
    save_report(share_html, share_path)

    # Full report (detailed)
    html = generate_report(
        layout, metadata, score,
        archetype=archetype,
        observations=observations_text,
        personality=personality,
    )
    out_path = Path(output) if output else UNJIGGLE_DIR / "reports" / f"report-{timestamp}.html"
    save_report(html, out_path)

    console.print(f"\n  [green]Share card:[/green] {share_path}")
    console.print(f"  [green]Full report:[/green] {out_path}")

    if open_browser:
        import webbrowser
        webbrowser.open(f"file://{share_path.resolve()}")
        console.print("  [dim]Opened share card in browser.[/dim]")

    console.print()
    console.print(f"  [bold]Share it:[/bold] Screenshot the card and post it!")
    console.print(f"  [bold]Fix it:[/bold]  [bold]unjiggle suggest[/bold] to apply AI recommendations")
    console.print()
    console.print(f"  [dim]Love Unjiggle? A native Mac app with live preview + slider is coming.[/dim]")
    console.print(f"  [dim]Sign up: {WEBSITE_URL}  |  Star us: {GITHUB_URL}[/dim]\n")


@main.command()
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], help="API key (auto-detected)")
@click.option("--model", default=None, help="Model override")
def mirror(api_key: str | None, model: str | None):
    """Personality roast: what your app collection says about you."""
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.mirror import generate_mirror
    from unjiggle.scoring import compute_score

    if not api_key:
        console.print("[red]No API key found.[/red] Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")
        sys.exit(1)

    console.print("\n[bold]Unjiggle[/bold] — Personality Mirror\n")
    console.print("  [dim]Scanning your apps and preparing your roast...[/dim]\n")

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] {e}")
        sys.exit(1)

    layout = read_layout(lockdown)
    metadata = enrich_layout(layout)
    score = compute_score(layout, metadata)

    console.print("[dim]Generating your personality profile...[/dim]\n")
    result = generate_mirror(layout, metadata, score, api_key=api_key, model=model)

    # The roast
    console.print(f"  [bold magenta]The Roast[/bold magenta]\n")
    console.print(f"  {result.roast}\n")

    # Life phases
    if result.phases:
        console.print(f"  [bold cyan]Life Phases Detected[/bold cyan]\n")
        for phase in result.phases:
            console.print(f"  [bold]{phase.name}[/bold]")
            console.print(f"  {phase.narrative}")
            console.print(f"  [dim]Evidence: {', '.join(phase.apps[:5])}[/dim]\n")

    # Contradictions
    if result.contradictions:
        console.print(f"  [bold yellow]Contradictions[/bold yellow]\n")
        for c in result.contradictions:
            console.print(f"  [bold]{c.tension}[/bold]")
            console.print(f"  {c.roast}")
            console.print(f"  [dim]{', '.join(c.apps_a[:3])} vs. {', '.join(c.apps_b[:3])}[/dim]\n")

    # Guilty pleasure
    if result.guilty_pleasure:
        console.print(f"  [bold red]Guilty Pleasure[/bold red]")
        console.print(f"  {result.guilty_pleasure}\n")

    # Tweetable one-liner
    console.print("  ─────────────────────────────────────────")
    console.print(f"\n  [italic]\"{result.one_line}\"[/italic]\n")

    # Generate share card → clipboard
    from unjiggle.cards import generate_mirror_card, save_card
    from unjiggle.render import copy_text, export_card

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    card_html = generate_mirror_card(layout, metadata, result)
    card_path = UNJIGGLE_DIR / "reports" / f"mirror-{timestamp}.html"
    save_card(card_html, card_path)
    export_card(card_path, console)

    # Also copy the one-liner for Twitter/text posts
    copy_text(result.one_line)
    console.print(f"  [dim]One-liner also copied — Cmd+V to tweet it.[/dim]")
    console.print(f"  [dim]{WEBSITE_URL}[/dim]\n")


@main.command()
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], help="API key (auto-detected)")
@click.option("--model", default=None, help="Model override")
def obituary(api_key: str | None, model: str | None):
    """Eulogies for your dead apps. RIP."""
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.obituary import generate_obituaries

    if not api_key:
        console.print("[red]No API key found.[/red] Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")
        sys.exit(1)

    console.print("\n[bold]Unjiggle[/bold] — The Digital Graveyard\n")

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] {e}")
        sys.exit(1)

    layout = read_layout(lockdown)
    console.print("[dim]Fetching app metadata...[/dim]")
    metadata = enrich_layout(layout)

    console.print("[dim]Identifying dead apps and writing eulogies...[/dim]\n")
    result = generate_obituaries(layout, metadata, api_key=api_key, model=model)

    if not result.obituaries:
        console.print("  [green]No dead apps found.[/green] Your phone is pristine.\n")
        return

    console.print(f"  [bold]{result.total_dead} apps didn't make it.[/bold]\n")

    for i, obit in enumerate(result.obituaries):
        console.print(f"  [dim]{'─' * 50}[/dim]")
        console.print(f"  [bold]⚰️  {obit.app_name}[/bold]", end="")
        if obit.born:
            console.print(f" [dim]({obit.born} – {obit.died})[/dim]")
        else:
            console.print()
        console.print()
        console.print(f"  {obit.eulogy}")
        if obit.cause_of_death:
            console.print(f"  [dim italic]Cause of death: {obit.cause_of_death}[/dim italic]")
        if obit.survived_by:
            console.print(f"  [dim]Survived by: {obit.survived_by}[/dim]")
        console.print()

    # Summary + share card
    console.print(f"  [dim]{'─' * 50}[/dim]")
    console.print(f"\n  [italic]\"{result.graveyard_summary}\"[/italic]\n")

    # Generate share card → clipboard
    from unjiggle.cards import generate_obituary_card, save_card
    from unjiggle.render import copy_text, export_card

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    card_html = generate_obituary_card(layout, metadata, result)
    card_path = UNJIGGLE_DIR / "reports" / f"obituary-{timestamp}.html"
    save_card(card_html, card_path)
    export_card(card_path, console)

    copy_text(result.graveyard_summary)
    console.print(f"  [dim]Summary also copied — Cmd+V to tweet it.[/dim]")
    console.print(f"  [dim]{WEBSITE_URL}[/dim]\n")


@main.command()
def swipetax():
    """Calculate the physical cost of your disorganized layout."""
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.swipetax import compute_swipe_tax

    console.print("\n[bold]Unjiggle[/bold] — Swipe Tax Calculator\n")

    try:
        lockdown, device = connect()
    except Exception as e:
        console.print(f"[red]No iPhone detected.[/red] {e}")
        sys.exit(1)

    layout = read_layout(lockdown)
    console.print("[dim]Fetching app metadata...[/dim]")
    metadata = enrich_layout(layout)

    tax = compute_swipe_tax(layout, metadata)

    console.print(f"\n  [bold yellow]{tax.headline}[/bold yellow]\n")
    console.print(f"  Current layout:  [red]{tax.total_annual_swipes:>8,} swipes/year[/red]")
    console.print(f"  Optimal layout:  [green]{tax.optimal_annual_swipes:>8,} swipes/year[/green]")
    console.print(f"  [bold]You could save:  {tax.savings:>8,} swipes/year[/bold]\n")

    if tax.worst_offenders:
        table = Table(title="Top Offenders", show_header=True, header_style="bold")
        table.add_column("App", style="bold")
        table.add_column("Page", justify="center")
        table.add_column("Swipes to Reach", justify="center")
        table.add_column("Wasted/Year", justify="right", style="red")

        for app in tax.worst_offenders:
            loc = f"{'📁 ' if app.in_folder else ''}Page {app.page}"
            table.add_row(
                app.name,
                loc,
                str(app.swipes_to_reach),
                f"{app.annual_wasted_swipes:,}",
            )
        console.print(table)
        console.print()

    # Generate share card → clipboard
    from unjiggle.cards import generate_swipetax_card, save_card
    from unjiggle.render import copy_text, export_card

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    card_html = generate_swipetax_card(layout, metadata, tax)
    card_path = UNJIGGLE_DIR / "reports" / f"swipetax-{timestamp}.html"
    save_card(card_html, card_path)
    export_card(card_path, console)

    copy_text(tax.headline)
    console.print(f"  [dim]Headline also copied — Cmd+V to tweet it.[/dim]")
    console.print(f"  [bold]Fix it:[/bold] [bold]unjiggle suggest[/bold] to reorganize with AI")
    console.print(f"  [dim]{WEBSITE_URL}[/dim]\n")


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
