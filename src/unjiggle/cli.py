"""Unjiggle CLI entry point."""

from __future__ import annotations

import json as _json
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
        console.print("  [bold magenta]Shareable diagnostics:[/bold magenta]")
        console.print("  [bold]unjiggle mirror[/bold]           Personality roast from your app collection")
        console.print("  [bold]unjiggle obituary[/bold]         Eulogies for your dead apps")
        console.print("  [bold]unjiggle swipetax[/bold]         How many swipes your layout wastes")
        console.print()
        console.print(f"  [dim]Separate native Mac app → {WEBSITE_URL}[/dim]")
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
        console.print("  [dim]Run [bold]unjiggle swipetax[/bold] for the full breakdown.[/dim]\n")

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

    console.print("  [green]Share card opened in browser.[/green]")
    console.print(f"  [dim]Full report: {report_path}[/dim]\n")

    # The funnel
    console.print("  ─────────────────────────────────────────")
    console.print()
    console.print("  [bold]What's next?[/bold]")
    console.print("    🔧 [bold]unjiggle suggest[/bold] to fix your layout with AI")
    console.print("    🪞 [bold]unjiggle mirror[/bold] for your personality roast")
    console.print("    ⚰️  [bold]unjiggle obituary[/bold] for eulogies of your dead apps")
    console.print(f"    ⭐ Star us: {GITHUB_URL}")
    console.print()
    console.print("  [dim]A separate native Mac app uses this engine for live preview and before/after flows.[/dim]")
    console.print(f"  [dim]Sign up: {WEBSITE_URL}[/dim]\n")

    # Analytics opt-in (once, first run only)
    from unjiggle.telemetry import prompt_analytics_opt_in, send_event
    prompt_analytics_opt_in(console)
    send_event("go", {
        "app_count": layout.total_apps,
        "page_count": layout.page_count,
        "folder_count": len(layout.all_folders()),
        "score": round(score.total),
        "archetype": archetype,
        "has_api_key": bool(api_key),
    })


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
                row.append("[dim]⬛ Widget[/dim]")

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
    console.print("  Next: [bold]unjiggle score[/bold] to see your organization score")
    console.print("  Or:   [bold]unjiggle go[/bold] for the full experience (scan → score → AI → share card)\n")


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
    console.print("  Next: [bold]unjiggle analyze[/bold] for AI-powered insights")
    console.print("  Or:   [bold]unjiggle suggest[/bold] to fix it interactively\n")


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
        console.print("\n  You're safe to run [bold]unjiggle suggest[/bold] now.\n")
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
    console.print("  Next: [bold]unjiggle suggest[/bold] to apply changes interactively")
    console.print("        [bold]unjiggle report --open[/bold] to generate your shareable report card\n")


@main.command()
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], help="API key (auto-detected)")
@click.option("--model", default=None, help="Model override (auto-detected)")
@click.option("--apply-all", is_flag=True, help="Apply all suggestions without stepping through (Just Fix It mode)")
def suggest(api_key: str | None, model: str, apply_all: bool):
    """AI-powered suggestions with live preview. Accept/skip each change."""
    from unjiggle.analyzer import LayoutOperation, analyze as run_analysis, preview_operations
    from unjiggle.device import connect, read_layout, write_layout
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
                                "    [D]elete / [A]rchive / [K]eep",
                                type=click.Choice(["d", "a", "k"], case_sensitive=False),
                                default="d",
                            )
                            if choice.lower() == "d":
                                kept_ops.append(LayoutOperation(action="delete", bundle_ids=[bid], gratitude=op.gratitude))
                                console.print(f"    [red]Goodbye, {name}.[/red]")
                            elif choice.lower() == "a":
                                kept_ops.append(LayoutOperation(action="move_to_app_library", bundle_ids=[bid]))
                                console.print("    [yellow]Archived.[/yellow]")
                            else:
                                console.print("    [dim]Kept.[/dim]")
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

    console.print("\n  [bold]Summary:[/bold]")
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

        console.print("\n  [green bold]Done![/green bold] Your iPhone has been reorganized.")
        console.print(f"  Undo anytime: [bold]unjiggle restore {backup_path}[/bold]")
        console.print()
        console.print("  [bold]Share your transformation:[/bold]")
        console.print("    [bold]unjiggle report --open[/bold] to generate a before/after share card")
        console.print()
        console.print("  [dim]Love Unjiggle? A separate native Mac app builds on this engine.[/dim]")
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
    console.print("  [bold]Share it:[/bold] Screenshot the card and post it!")
    console.print("  [bold]Fix it:[/bold]  [bold]unjiggle suggest[/bold] to apply AI recommendations")
    console.print()
    console.print("  [dim]Love Unjiggle? A separate native Mac app builds on this engine.[/dim]")
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

    console.print("\n[bold]Unjiggle[/bold] — Personality Mirror\n")
    console.print("  [dim]Scanning your apps...[/dim]\n")

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
    console.print("  [bold magenta]The Roast[/bold magenta]\n")
    console.print(f"  {result.roast}\n")

    # Life phases
    if result.phases:
        console.print("  [bold cyan]Life Phases Detected[/bold cyan]\n")
        for phase in result.phases:
            console.print(f"  [bold]{phase.name}[/bold]")
            console.print(f"  {phase.narrative}")
            console.print(f"  [dim]Evidence: {', '.join(phase.apps[:5])}[/dim]\n")

    # Contradictions
    if result.contradictions:
        console.print("  [bold yellow]Contradictions[/bold yellow]\n")
        for c in result.contradictions:
            console.print(f"  [bold]{c.tension}[/bold]")
            console.print(f"  {c.roast}")
            console.print(f"  [dim]{', '.join(c.apps_a[:3])} vs. {', '.join(c.apps_b[:3])}[/dim]\n")

    # Guilty pleasure
    if result.guilty_pleasure:
        console.print("  [bold red]Guilty Pleasure[/bold red]")
        console.print(f"  {result.guilty_pleasure}\n")

    # Tweetable one-liner
    console.print("  ─────────────────────────────────────────")
    console.print(f"\n  [italic]\"{result.one_line}\"[/italic]\n")

    # Upsell when using rule-based fallback
    if not api_key:
        console.print("  ─────────────────────────────────────────")
        console.print("  Want a sharper roast? With a free API key, the mirror references")
        console.print("  your specific apps by name and finds contradictions you didn't")
        console.print("  know you had. [dim]Get a key at anthropic.com → set ANTHROPIC_API_KEY[/dim]\n")

    # Generate share card → clipboard
    from unjiggle.cards import generate_mirror_card, save_card
    from unjiggle.render import copy_text, export_card

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    card_html = generate_mirror_card(layout, metadata, result)
    card_path = UNJIGGLE_DIR / "reports" / f"mirror-{timestamp}.html"
    save_card(card_html, card_path)
    export_card(card_path, console)

    copy_text(result.one_line)
    console.print("  [dim]One-liner also copied — Cmd+V to tweet it.[/dim]")

    from unjiggle.telemetry import ask_did_share, send_event
    shared = ask_did_share(console)
    send_event("mirror", {"shared": shared or "skip", "has_api_key": bool(api_key)})
    console.print(f"  [dim]{WEBSITE_URL}[/dim]\n")


@main.command()
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], help="API key (auto-detected)")
@click.option("--model", default=None, help="Model override")
def obituary(api_key: str | None, model: str | None):
    """Eulogies for your dead apps. RIP."""
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.obituary import generate_obituaries

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

    # Summary + upsell
    console.print(f"  [dim]{'─' * 50}[/dim]")
    console.print(f"\n  [italic]\"{result.graveyard_summary}\"[/italic]\n")

    if not api_key:
        console.print("  Want funnier eulogies? With a free API key, each app gets a custom")
        console.print("  obituary with a cause of death and \"survived by\" line.")
        console.print("  [dim]Get a key at anthropic.com → set ANTHROPIC_API_KEY[/dim]\n")

    # Generate share card → clipboard
    from unjiggle.cards import generate_obituary_card, save_card
    from unjiggle.render import copy_text, export_card

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    card_html = generate_obituary_card(layout, metadata, result)
    card_path = UNJIGGLE_DIR / "reports" / f"obituary-{timestamp}.html"
    save_card(card_html, card_path)
    export_card(card_path, console)

    copy_text(result.graveyard_summary)
    console.print("  [dim]Summary also copied — Cmd+V to tweet it.[/dim]")

    from unjiggle.telemetry import ask_did_share, send_event
    shared = ask_did_share(console)
    send_event("obituary", {"shared": shared or "skip", "dead_count": result.total_dead})
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
    console.print("  [dim]Headline also copied — Cmd+V to tweet it.[/dim]")

    from unjiggle.telemetry import ask_did_share, send_event
    shared = ask_did_share(console)
    send_event("swipetax", {"shared": shared or "skip", "savings": tax.savings})

    console.print("  [bold]Fix it:[/bold] [bold]unjiggle suggest[/bold] to reorganize with AI")
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


@main.command()
def demo():
    """Try Unjiggle without a phone — see what the output looks like."""
    from unjiggle.models import AppItem, FolderItem, HomeScreenLayout, LayoutItem
    from unjiggle.scoring import compute_score
    from unjiggle.swipetax import compute_swipe_tax
    from unjiggle.mirror import generate_mirror
    from unjiggle.obituary import generate_obituaries

    console.print("\n[bold]Unjiggle[/bold] — Demo Mode\n")
    console.print("  [dim]Using a sample phone layout (no iPhone needed).[/dim]\n")

    # Build a realistic mock layout
    meta = {
        "com.apple.mobilesafari": {"name": "Safari", "super_category": "System", "last_updated": "2025-09-01T00:00:00Z", "description": "Web browser"},
        "com.burbn.instagram": {"name": "Instagram", "super_category": "Social", "last_updated": "2025-12-01T00:00:00Z", "description": "Photo sharing"},
        "com.spotify.client": {"name": "Spotify", "super_category": "Entertainment", "last_updated": "2025-12-01T00:00:00Z", "description": "Music streaming"},
        "com.zhiliaoapp.musically": {"name": "TikTok", "super_category": "Entertainment", "last_updated": "2025-12-01T00:00:00Z", "description": "Short video"},
        "com.slack.Slack": {"name": "Slack", "super_category": "Productivity", "last_updated": "2025-12-01T00:00:00Z", "description": "Team messaging"},
        "com.notion.Notion": {"name": "Notion", "super_category": "Productivity", "last_updated": "2025-12-01T00:00:00Z", "description": "Notes and docs"},
        "com.headspace.headspace": {"name": "Headspace", "super_category": "Health", "last_updated": "2025-06-01T00:00:00Z", "description": "Meditation"},
        "com.calm.Calm": {"name": "Calm", "super_category": "Health", "last_updated": "2025-05-01T00:00:00Z", "description": "Meditation and sleep"},
        "com.wakingup.app": {"name": "Waking Up", "super_category": "Health", "last_updated": "2025-03-01T00:00:00Z", "description": "Mindfulness"},
        "com.nike.nrc": {"name": "Nike Run Club", "super_category": "Health", "last_updated": "2025-10-01T00:00:00Z", "description": "Running tracker"},
        "com.duolingo.DuolingoMobile": {"name": "Duolingo", "super_category": "Education", "last_updated": "2025-10-01T00:00:00Z", "description": "Learn languages"},
        "com.rosettastone.rosettastone": {"name": "Rosetta Stone", "super_category": "Education", "last_updated": "2023-06-01T00:00:00Z", "description": "Language learning"},
        "com.memrise.app": {"name": "Memrise", "super_category": "Education", "last_updated": "2023-01-01T00:00:00Z", "description": "Learn with flashcards"},
        "com.robinhood.release": {"name": "Robinhood", "super_category": "Finance", "last_updated": "2025-12-01T00:00:00Z", "description": "Stock trading"},
        "com.coinbase.Coinbase": {"name": "Coinbase", "super_category": "Finance", "last_updated": "2025-12-01T00:00:00Z", "description": "Crypto trading"},
        "com.mint.internal": {"name": "Mint", "super_category": "Finance", "last_updated": "2023-12-01T00:00:00Z", "description": "Budgeting (discontinued)"},
        "com.doordash.DoorDash": {"name": "DoorDash", "super_category": "Shopping", "last_updated": "2025-12-01T00:00:00Z", "description": "Food delivery"},
        "com.amazon.Amazon": {"name": "Amazon", "super_category": "Shopping", "last_updated": "2025-12-01T00:00:00Z", "description": "Online shopping"},
        "com.king.candycrush": {"name": "Candy Crush", "super_category": "Games", "last_updated": "2025-10-01T00:00:00Z", "description": "Match-three puzzle"},
        "com.nianticlabs.pokemongo": {"name": "Pokemon GO", "super_category": "Games", "last_updated": "2025-09-01T00:00:00Z", "description": "Catch Pokemon"},
        "com.darksky.weather": {"name": "Dark Sky", "super_category": "Utilities", "last_updated": "2022-01-01T00:00:00Z", "description": "Weather (discontinued by Apple)"},
        "com.clubhouse.app": {"name": "Clubhouse", "super_category": "Social", "last_updated": "2023-09-01T00:00:00Z", "description": "Audio chat rooms"},
        "com.purify.app": {"name": "Purify", "super_category": "Utilities", "last_updated": "2021-03-01T00:00:00Z", "description": "Ad blocker (discontinued)"},
    }

    def _a(bid):
        return LayoutItem(app=AppItem(bundle_id=bid))

    junk = [AppItem(bundle_id=bid) for bid in ["com.darksky.weather", "com.clubhouse.app", "com.purify.app",
            "com.rosettastone.rosettastone", "com.memrise.app", "com.mint.internal",
            "com.duolingo.DuolingoMobile", "com.king.candycrush", "com.nianticlabs.pokemongo"]]

    layout = HomeScreenLayout(
        dock=[_a("com.apple.mobilesafari")],
        pages=[
            [_a("com.burbn.instagram"), _a("com.spotify.client"), _a("com.zhiliaoapp.musically")],
            [_a("com.slack.Slack"), _a("com.notion.Notion")],
            [_a("com.headspace.headspace"), _a("com.calm.Calm"), _a("com.wakingup.app"), _a("com.nike.nrc")],
            [_a("com.robinhood.release"), _a("com.coinbase.Coinbase"), _a("com.doordash.DoorDash"), _a("com.amazon.Amazon")],
            [LayoutItem(folder=FolderItem(display_name="Stuff", pages=[junk]))],
        ],
    )

    # Score
    score = compute_score(layout, meta)
    console.print(f"  Organization Score: [bold]{score.total:.0f}/100[/bold] — {score.label}\n")

    from unjiggle.archetypes import assign_archetype
    archetype, tagline = assign_archetype(layout, meta)
    console.print(f"  [bold magenta]{archetype}[/bold magenta]")
    console.print(f"  [dim]{tagline}[/dim]\n")

    # Swipe Tax
    tax = compute_swipe_tax(layout, meta)
    console.print(f"  [bold yellow]Swipe Tax:[/bold yellow] {tax.headline}\n")

    # Mirror (rule-based, no API key)
    mirror = generate_mirror(layout, meta, score)
    console.print("  [bold cyan]Personality Mirror[/bold cyan]\n")
    console.print(f"  {mirror.roast}\n")
    if mirror.one_line:
        console.print(f"  [italic]\"{mirror.one_line}\"[/italic]\n")

    # Obituary (rule-based, no API key)
    obits = generate_obituaries(layout, meta)
    if obits.obituaries:
        console.print(f"  [bold]Digital Graveyard[/bold] — {obits.total_dead} apps didn't make it.\n")
        for obit in obits.obituaries[:3]:
            console.print(f"  [bold]⚰️  {obit.app_name}[/bold]")
            console.print(f"  {obit.eulogy}\n")

    console.print("  ─────────────────────────────────────────\n")
    console.print("  [bold]That was demo mode.[/bold] To scan your actual phone:\n")
    console.print("    1. Connect your iPhone via USB")
    console.print("    2. [bold]unjiggle go[/bold]\n")
    console.print("  [dim]With a free API key from anthropic.com, the roasts and obituaries[/dim]")
    console.print("  [dim]get much sharper — personal, witty, and specific to your apps.[/dim]\n")
    console.print(f"  [dim]{WEBSITE_URL}[/dim]\n")


# ---------------------------------------------------------------------------
# JSON API command group — structured output for the Mac app (no Rich, no TTY)
# ---------------------------------------------------------------------------


def _json_out(data: dict) -> None:
    """Print JSON to stdout and exit cleanly."""
    click.echo(_json.dumps(data, ensure_ascii=False))


def _json_err(message: str) -> None:
    """Print a JSON error to stdout and exit with code 1."""
    click.echo(_json.dumps({"error": message}, ensure_ascii=False))
    sys.exit(1)


def _device_dict(device) -> dict:
    return {
        "name": device.name,
        "model": device.model,
        "ios_version": device.ios_version,
    }


def _layout_items_to_json(items, metadata: dict) -> list:
    """Convert layout items into tagged JSON matching the Swift LayoutItem enum."""
    output = []
    for item in items:
        if item.is_app:
            meta = metadata.get(item.app.bundle_id, {})
            output.append({
                "type": "app",
                "app": {
                    "bundle_id": item.app.bundle_id,
                    "display_name": meta.get("name", item.app.bundle_id.split(".")[-1]) if meta else item.app.bundle_id.split(".")[-1],
                    "category": meta.get("super_category", "Other") if meta else "Other",
                },
            })
        elif item.is_folder:
            folder_pages = []
            for fpage in item.folder.pages:
                fpage_apps = []
                for app in fpage:
                    fmeta = metadata.get(app.bundle_id, {})
                    fpage_apps.append({
                        "bundle_id": app.bundle_id,
                        "display_name": fmeta.get("name", app.bundle_id.split(".")[-1]) if fmeta else app.bundle_id.split(".")[-1],
                        "category": fmeta.get("super_category", "Other") if fmeta else "Other",
                    })
                folder_pages.append(fpage_apps)
            output.append({
                "type": "folder",
                "folder": {
                    "display_name": item.folder.display_name,
                    "apps": folder_pages,
                },
            })
        elif item.is_widget:
            output.append({
                "type": "widget",
                "widget": {
                    "container_bundle_id": item.widget.container_bundle_id,
                    "grid_size": item.widget.grid_size.value,
                },
            })
    return output


def _layout_to_pages_json(layout, metadata: dict) -> list:
    """Convert layout pages to tagged JSON matching the Swift LayoutItem enum."""
    return [_layout_items_to_json(page, metadata) for page in layout.pages]


def _layout_summary_to_json(layout, metadata: dict) -> dict:
    return {
        "total_apps": layout.total_apps,
        "page_count": layout.page_count,
        "folder_count": len(layout.all_folders()),
        "dock_items": len(layout.dock),
        "dock": _layout_items_to_json(layout.dock, metadata),
        "pages": _layout_to_pages_json(layout, metadata),
    }


def _operation_to_json(op) -> dict:
    op_dict = {
        "action": op.action,
        "bundle_ids": op.bundle_ids,
    }
    if op.target_page is not None:
        op_dict["target_page"] = op.target_page
    if op.folder_name is not None:
        op_dict["folder_name"] = op.folder_name
    if op.old_name is not None:
        op_dict["old_name"] = op.old_name
    if op.gratitude is not None:
        op_dict["gratitude"] = op.gratitude
    return op_dict


def _score_trend(before_score: int, after_score: int) -> str:
    if after_score > before_score:
        return "improved"
    if after_score < before_score:
        return "worse"
    return "neutral"


def _swipe_tax_to_json(tax) -> dict:
    worst = []
    for app in tax.worst_offenders:
        worst.append({
            "name": app.name,
            "bundle_id": app.bundle_id,
            "page": app.page,
            "in_folder": app.in_folder,
            "annual_wasted_swipes": app.annual_wasted_swipes,
        })
    return {
        "total_annual": tax.total_annual_swipes,
        "optimal_annual": tax.optimal_annual_swipes,
        "savings": tax.savings,
        "headline": tax.headline,
        "worst_offenders": worst,
    }


def _mirror_to_json(result) -> dict:
    return {
        "roast": result.roast,
        "phases": [
            {"name": p.name, "apps": p.apps, "narrative": p.narrative}
            for p in result.phases
        ],
        "contradictions": [
            {
                "tension": c.tension,
                "apps_a": c.apps_a,
                "apps_b": c.apps_b,
                "roast": c.roast,
            }
            for c in result.contradictions
        ],
        "guilty_pleasure": result.guilty_pleasure,
        "one_line": result.one_line,
    }


def _obituary_to_json(result) -> dict:
    return {
        "total_dead": result.total_dead,
        "obituaries": [
            {
                "app_name": o.app_name,
                "bundle_id": o.bundle_id,
                "born": o.born,
                "died": o.died,
                "cause_of_death": o.cause_of_death,
                "eulogy": o.eulogy,
                "survived_by": o.survived_by,
            }
            for o in result.obituaries
        ],
        "graveyard_summary": result.graveyard_summary,
    }


def _analysis_to_json(result) -> dict:
    observations = []
    for obs in result.observations:
        observations.append({
            "track": obs.track,
            "title": obs.title,
            "narrative": obs.narrative,
            "operations": [_operation_to_json(op) for op in obs.operations],
        })
    return {
        "observations": observations,
        "personality": result.personality,
        "archetype": result.archetype,
    }


@main.group()
def json():
    """Machine-readable JSON output for the Mac app. No Rich formatting."""
    pass


@json.command(name="status")
def json_status():
    """Check device connection. Returns JSON with connected status."""
    from unjiggle.device import connect

    try:
        _lockdown, device = connect()
        _json_out({"connected": True, "device": _device_dict(device)})
    except Exception:
        _json_out({"connected": False})


@json.command(name="scan")
def json_scan():
    """Full layout data as JSON."""
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout

    try:
        lockdown, device = connect()
    except Exception:
        _json_err("No iPhone detected")

    layout = read_layout(lockdown)
    metadata = enrich_layout(layout)

    _json_out({
        "device": _device_dict(device),
        "total_apps": layout.total_apps,
        "page_count": layout.page_count,
        "folder_count": len(layout.all_folders()),
        "dock_items": len(layout.dock),
        "pages": _layout_to_pages_json(layout, metadata),
    })


@json.command(name="diagnose")
def json_diagnose():
    """Score + archetype + swipe tax in one call."""
    from unjiggle.archetypes import assign_archetype
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.scoring import compute_score
    from unjiggle.swipetax import compute_swipe_tax

    try:
        lockdown, device = connect()
    except Exception:
        _json_err("No iPhone detected")

    layout = read_layout(lockdown)
    metadata = enrich_layout(layout)
    score = compute_score(layout, metadata)
    archetype, tagline = assign_archetype(layout, metadata)
    tax = compute_swipe_tax(layout, metadata)

    _json_out({
        "score": {
            "total": round(score.total),
            "label": score.label,
            "page_efficiency": round(score.page_efficiency),
            "category_coherence": round(score.category_coherence),
            "folder_usage": round(score.folder_usage),
            "dock_quality": round(score.dock_quality),
        },
        "archetype": archetype,
        "tagline": tagline,
        "swipe_tax": _swipe_tax_to_json(tax),
    })


@json.command(name="mirror")
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], default=None)
@click.option("--model", default=None)
def json_mirror(api_key: str | None, model: str | None):
    """Personality roast as JSON."""
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.mirror import generate_mirror
    from unjiggle.scoring import compute_score

    try:
        lockdown, device = connect()
    except Exception:
        _json_err("No iPhone detected")

    layout = read_layout(lockdown)
    metadata = enrich_layout(layout)
    score = compute_score(layout, metadata)

    try:
        result = generate_mirror(layout, metadata, score, api_key=api_key, model=model)
    except Exception as e:
        _json_err(f"Mirror generation failed: {e}")

    _json_out(_mirror_to_json(result))


@json.command(name="obituary")
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], default=None)
@click.option("--model", default=None)
def json_obituary(api_key: str | None, model: str | None):
    """Dead app eulogies as JSON."""
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.obituary import generate_obituaries

    try:
        lockdown, device = connect()
    except Exception:
        _json_err("No iPhone detected")

    layout = read_layout(lockdown)
    metadata = enrich_layout(layout)

    try:
        result = generate_obituaries(layout, metadata, api_key=api_key, model=model)
    except Exception as e:
        _json_err(f"Obituary generation failed: {e}")

    _json_out(_obituary_to_json(result))


PRESET_CHOICES = ("focus", "relax", "minimal", "beautiful")

# Category priority tiers for preset-based transformations
_FOCUS_PAGE1_CATS = {"Productivity", "Utilities", "System", "Finance", "Education"}
_FOCUS_LATER_CATS = {"Social", "Entertainment", "Games"}
_RELAX_PAGE1_CATS = {"Entertainment", "Games", "Social"}
_RELAX_LATER_CATS = {"Productivity", "Finance", "Education"}
_MINIMAL_KEEP_CATS = {"Social", "Productivity", "Utilities", "System"}

# Color sort order for the "beautiful" preset (based on CATEGORY_COLORS hues)
_CATEGORY_COLOR_ORDER = [
    "Games",          # Red
    "Health",         # Orange
    "News",           # Yellow
    "Productivity",   # Green
    "Finance",        # Teal
    "Education",      # Cyan
    "Social",         # Blue
    "Entertainment",  # Purple
    "Travel",         # Violet
    "Shopping",       # Pink
    "Utilities",      # Gray
    "System",         # Dark gray
    "Other",          # Light gray
]


def _get_app_category(bundle_id: str, metadata: dict) -> str:
    """Get the super_category for a bundle_id from metadata."""
    meta = metadata.get(bundle_id, {})
    return meta.get("super_category", "Other") if meta else "Other"


def _get_app_name(bundle_id: str, metadata: dict) -> str:
    """Get the display name for a bundle_id from metadata."""
    meta = metadata.get(bundle_id, {})
    return meta.get("name", bundle_id.split(".")[-1]) if meta else bundle_id.split(".")[-1]


def _collect_all_apps_with_positions(layout, metadata: dict) -> list[dict]:
    """Build a list of all non-dock apps with their current page, category, name."""
    apps = []
    for page_idx, page in enumerate(layout.pages):
        for item in page:
            if item.is_app:
                bid = item.app.bundle_id
                apps.append({
                    "bundle_id": bid,
                    "name": _get_app_name(bid, metadata),
                    "category": _get_app_category(bid, metadata),
                    "from_page": page_idx + 1,  # 1-indexed for display
                })
            elif item.is_folder:
                for fpage in item.folder.pages:
                    for app in fpage:
                        bid = app.bundle_id
                        apps.append({
                            "bundle_id": bid,
                            "name": _get_app_name(bid, metadata),
                            "category": _get_app_category(bid, metadata),
                            "from_page": page_idx + 1,
                        })
    return apps


def _transform_preview_payload(
    intent: str,
    layout,
    metadata: dict,
    before_score: int,
    after_score: int,
    before_pages: int,
    after_pages: int,
    changes: list[dict],
    operations: list,
    proposed_layout=None,
) -> dict:
    moved = sum(1 for c in changes if c["action"] == "move_to_page")
    archived = sum(1 for c in changes if c["action"] in ("move_to_app_library", "delete"))
    new_folders = sum(1 for c in changes if c["action"] == "create_folder")
    parts = []
    if moved:
        parts.append(f"Moved {moved} apps")
    if archived:
        parts.append(f"archived {archived}")
    if new_folders:
        parts.append(f"created {new_folders} folders")
    summary = ", ".join(parts) if parts else "No changes needed"
    trend = _score_trend(before_score, after_score)

    payload = {
        "intent": intent,
        "before_score": before_score,
        "after_score": after_score,
        "score_delta": after_score - before_score,
        "score_trend": trend,
        "score_improved": trend == "improved",
        "before_pages": before_pages,
        "after_pages": after_pages,
        "moved": moved,
        "archived": archived,
        "new_folders": new_folders,
        "changes": changes,
        "operations": [_operation_to_json(op) for op in operations],
        "summary": summary,
        "current_layout": _layout_summary_to_json(layout, metadata),
    }
    if proposed_layout is not None:
        payload["proposed_layout"] = _layout_summary_to_json(proposed_layout, metadata)
    return payload


def _build_minimal_one_page_plan(layout, metadata: dict) -> tuple[list[str], list[str]]:
    """Return (keep_visible_bundle_ids, archive_bundle_ids) for the one-page preset."""
    all_apps = _collect_all_apps_with_positions(layout, metadata)

    dock_bids = set()
    for item in layout.dock:
        if item.is_app:
            dock_bids.add(item.app.bundle_id)

    priority_apps = [a for a in all_apps if a["category"] in _MINIMAL_KEEP_CATS]
    keep_visible = []
    seen = set()
    for app in priority_apps:
        bid = app["bundle_id"]
        if bid in seen or bid in dock_bids:
            continue
        keep_visible.append(bid)
        seen.add(bid)
        if len(keep_visible) >= 24:
            break

    if len(keep_visible) < 24:
        for app in all_apps:
            bid = app["bundle_id"]
            if bid in seen or bid in dock_bids:
                continue
            keep_visible.append(bid)
            seen.add(bid)
            if len(keep_visible) >= 24:
                break

    archive_bids = []
    archived_seen = set()
    for app in all_apps:
        bid = app["bundle_id"]
        if bid in dock_bids or bid in keep_visible or bid in archived_seen:
            continue
        archive_bids.append(bid)
        archived_seen.add(bid)

    return keep_visible, archive_bids


def _generate_preset_transform(preset: str, layout, metadata: dict, score) -> dict:
    """Generate a TransformPreview dict for a rule-based preset."""
    from unjiggle.analyzer import LayoutOperation, preview_operations
    from unjiggle.scoring import compute_score

    all_apps = _collect_all_apps_with_positions(layout, metadata)
    changes = []
    operations = []

    if preset == "focus":
        for app in all_apps:
            cat = app["category"]
            if cat in _FOCUS_PAGE1_CATS and app["from_page"] != 1:
                changes.append({
                    "action": "move_to_page",
                    "bundle_id": app["bundle_id"],
                    "app_name": app["name"],
                    "from_page": app["from_page"],
                    "to_page": 1,
                })
                operations.append(LayoutOperation(
                    action="move_to_page",
                    bundle_ids=[app["bundle_id"]],
                    target_page=0,  # 0-indexed
                ))
            elif cat in _FOCUS_LATER_CATS and app["from_page"] <= 2:
                target = max(3, layout.page_count)
                changes.append({
                    "action": "move_to_page",
                    "bundle_id": app["bundle_id"],
                    "app_name": app["name"],
                    "from_page": app["from_page"],
                    "to_page": target,
                })
                operations.append(LayoutOperation(
                    action="move_to_page",
                    bundle_ids=[app["bundle_id"]],
                    target_page=min(target - 1, len(layout.pages) - 1),
                ))

    elif preset == "relax":
        for app in all_apps:
            cat = app["category"]
            if cat in _RELAX_PAGE1_CATS and app["from_page"] != 1:
                changes.append({
                    "action": "move_to_page",
                    "bundle_id": app["bundle_id"],
                    "app_name": app["name"],
                    "from_page": app["from_page"],
                    "to_page": 1,
                })
                operations.append(LayoutOperation(
                    action="move_to_page",
                    bundle_ids=[app["bundle_id"]],
                    target_page=0,
                ))
            elif cat in _RELAX_LATER_CATS and app["from_page"] <= 2:
                target = max(3, layout.page_count)
                changes.append({
                    "action": "move_to_page",
                    "bundle_id": app["bundle_id"],
                    "app_name": app["name"],
                    "from_page": app["from_page"],
                    "to_page": target,
                })
                operations.append(LayoutOperation(
                    action="move_to_page",
                    bundle_ids=[app["bundle_id"]],
                    target_page=min(target - 1, len(layout.pages) - 1),
                ))

    elif preset == "minimal":
        keep_visible_bids, archive_bids = _build_minimal_one_page_plan(layout, metadata)
        keep_visible_set = set(keep_visible_bids)

        for app in all_apps:
            if app["bundle_id"] in archive_bids:
                changes.append({
                    "action": "move_to_app_library",
                    "bundle_id": app["bundle_id"],
                    "app_name": app["name"],
                    "from_page": app["from_page"],
                    "to_page": None,
                })
                operations.append(LayoutOperation(
                    action="move_to_app_library",
                    bundle_ids=[app["bundle_id"]],
                ))
            elif app["bundle_id"] in keep_visible_set and app["from_page"] != 1:
                changes.append({
                    "action": "move_to_page",
                    "bundle_id": app["bundle_id"],
                    "app_name": app["name"],
                    "from_page": app["from_page"],
                    "to_page": 1,
                })

        if keep_visible_bids:
            operations.append(LayoutOperation(
                action="compact_to_single_page",
                bundle_ids=keep_visible_bids,
            ))

    elif preset == "beautiful":
        # Sort all apps by category color, grouping same-color apps together
        color_order = {cat: i for i, cat in enumerate(_CATEGORY_COLOR_ORDER)}

        sorted_apps = sorted(all_apps, key=lambda a: (
            color_order.get(a["category"], 99),
            a["name"],
        ))

        # Assign to pages (24 per page)
        for i, app in enumerate(sorted_apps):
            target_page = (i // 24) + 1  # 1-indexed
            if app["from_page"] != target_page:
                changes.append({
                    "action": "move_to_page",
                    "bundle_id": app["bundle_id"],
                    "app_name": app["name"],
                    "from_page": app["from_page"],
                    "to_page": target_page,
                })
                # Only create operations for pages that exist
                target_idx = min(target_page - 1, len(layout.pages) - 1)
                operations.append(LayoutOperation(
                    action="move_to_page",
                    bundle_ids=[app["bundle_id"]],
                    target_page=target_idx,
                ))

    # Compute before/after scores and page counts
    before_score = round(score.total)
    before_pages = layout.page_count
    if operations:
        proposed_layout = preview_operations(layout, operations)
        after_breakdown = compute_score(proposed_layout, metadata)
        after_score = round(after_breakdown.total)
        after_pages = proposed_layout.page_count
    else:
        proposed_layout = None
        after_score = before_score
        after_pages = before_pages

    return _transform_preview_payload(
        intent=preset,
        layout=layout,
        metadata=metadata,
        before_score=before_score,
        after_score=after_score,
        before_pages=before_pages,
        after_pages=after_pages,
        changes=changes,
        operations=operations,
        proposed_layout=proposed_layout,
    )


def _generate_intent_transform(
    intent: str, layout, metadata: dict, score, api_key: str, model: str | None,
) -> dict:
    """Generate a TransformPreview using LLM analysis framed around the user's intent."""
    from unjiggle.analyzer import (
        ANALYSIS_TOOL,
        _build_context,
        _parse_result,
        preview_operations,
    )
    from unjiggle.scoring import compute_score as _compute_score

    context = _build_context(layout, metadata, score)

    intent_prompt = (
        f"The user wants to transform their home screen with this intent: \"{intent}\"\n\n"
        f"Analyze the layout and generate observations and operations that specifically "
        f"serve this intent. Focus your suggestions on achieving what the user asked for.\n\n"
        f"{context}"
    )

    intent_system = (
        "You are Unjiggle's AI layout transformation engine. The user has a specific "
        "intent for how they want their home screen to feel. Generate observations and "
        "operations that transform the layout to match their intent.\n\n"
        "Follow the same output format as a standard analysis, but tailor every suggestion "
        "to the user's stated intent. Be opinionated and decisive.\n\n"
        "RULES:\n"
        "- Reference apps by EXACT bundle ID from the input\n"
        "- Each observation should directly serve the user's intent\n"
        "- Be specific about which apps to move and where\n"
        "- 3-5 observations is ideal\n"
    )

    # Detect provider
    if api_key.startswith("sk-"):
        provider = "openai"
    else:
        provider = "anthropic"

    if provider == "openai":
        import openai as _openai

        client = _openai.OpenAI(api_key=api_key)
        openai_tool = {
            "type": "function",
            "function": {
                "name": ANALYSIS_TOOL["name"],
                "description": ANALYSIS_TOOL["description"],
                "parameters": ANALYSIS_TOOL["input_schema"],
            },
        }
        response = client.chat.completions.create(
            model=model or "gpt-4.1",
            max_tokens=4096,
            messages=[
                {"role": "system", "content": intent_system},
                {"role": "user", "content": intent_prompt},
            ],
            tools=[openai_tool],
            tool_choice={"type": "function", "function": {"name": "submit_analysis"}},
        )
        for choice in response.choices:
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    if tc.function.name == "submit_analysis":
                        data = _json.loads(tc.function.arguments)
                        result = _parse_result(data, layout)
                        break
                else:
                    continue
                break
        else:
            raise RuntimeError("OpenAI did not return a submit_analysis function call")
    else:
        try:
            import anthropic as _anthropic
        except ImportError:
            raise RuntimeError("anthropic package required. pip install anthropic")

        client = _anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model or "claude-sonnet-4-20250514",
            max_tokens=4096,
            system=intent_system,
            tools=[ANALYSIS_TOOL],
            tool_choice={"type": "tool", "name": "submit_analysis"},
            messages=[{"role": "user", "content": intent_prompt}],
        )
        result = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_analysis":
                result = _parse_result(block.input, layout)
                break
        if result is None:
            raise RuntimeError("Anthropic did not return a submit_analysis tool call")

    # Convert AnalysisResult into TransformPreview format
    all_ops = []
    for obs in result.observations:
        all_ops.extend(obs.operations)

    changes = []
    for op in all_ops:
        for bid in op.bundle_ids:
            change = {
                "action": op.action,
                "bundle_id": bid,
                "app_name": _get_app_name(bid, metadata),
            }
            # Find current page
            for page_idx, page in enumerate(layout.pages):
                for item in page:
                    if item.is_app and item.app.bundle_id == bid:
                        change["from_page"] = page_idx + 1
                        break
                    elif item.is_folder:
                        for fpage in item.folder.pages:
                            if any(a.bundle_id == bid for a in fpage):
                                change["from_page"] = page_idx + 1
                                break
            if "from_page" not in change:
                change["from_page"] = None
            change["to_page"] = (op.target_page + 1) if op.target_page is not None else None
            changes.append(change)

    before_score = round(score.total)
    before_pages = layout.page_count
    if all_ops:
        proposed_layout = preview_operations(layout, all_ops)
        after_breakdown = _compute_score(proposed_layout, metadata)
        after_score = round(after_breakdown.total)
        after_pages = proposed_layout.page_count
    else:
        proposed_layout = None
        after_score = before_score
        after_pages = before_pages

    return _transform_preview_payload(
        intent=intent,
        layout=layout,
        metadata=metadata,
        before_score=before_score,
        after_score=after_score,
        before_pages=before_pages,
        after_pages=after_pages,
        changes=changes,
        operations=all_ops,
        proposed_layout=proposed_layout,
    )


@json.command(name="suggest")
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], default=None)
@click.option("--model", default=None)
@click.option(
    "--preset",
    type=click.Choice(PRESET_CHOICES, case_sensitive=False),
    default=None,
    help="Rule-based layout preset: focus, relax, minimal, beautiful. No API key needed.",
)
@click.option(
    "--intent",
    default=None,
    help="Free-text intent for LLM-powered transformation (requires API key).",
)
def json_suggest(
    api_key: str | None,
    model: str | None,
    preset: str | None,
    intent: str | None,
):
    """AI analysis with suggested operations as JSON.

    Three modes:
      --preset NAME    Rule-based transformation (no API key needed)
      --intent TEXT    LLM-powered custom transformation (API key required)
      (neither)        Rule-based archetype + observations (no API key needed),
                       or full LLM analysis if --api-key is provided
    """
    from unjiggle.device import connect, read_layout
    from unjiggle.itunes import enrich_layout
    from unjiggle.scoring import compute_score

    if preset and intent:
        _json_err("Cannot use both --preset and --intent. Pick one.")

    if intent and not api_key:
        _json_err("--intent requires an API key. Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or pass --api-key.")

    try:
        lockdown, device = connect()
    except Exception:
        _json_err("No iPhone detected")

    layout = read_layout(lockdown)
    metadata = enrich_layout(layout)
    score = compute_score(layout, metadata)

    # Mode 1: Preset-based transformation (no API key needed)
    if preset:
        try:
            result = _generate_preset_transform(preset, layout, metadata, score)
        except Exception as e:
            _json_err(f"Preset transformation failed: {e}")
        _json_out(result)
        return

    # Mode 2: Intent-based LLM transformation
    if intent:
        try:
            result = _generate_intent_transform(
                intent, layout, metadata, score, api_key, model,
            )
        except Exception as e:
            _json_err(f"Intent transformation failed: {e}")
        _json_out(result)
        return

    # Mode 3: No preset, no intent
    if api_key:
        # Full LLM analysis (original behavior)
        from unjiggle.analyzer import analyze as run_analysis

        try:
            result = run_analysis(layout, metadata, score, api_key=api_key, model=model)
        except Exception as e:
            _json_err(f"Analysis failed: {e}")
        _json_out(_analysis_to_json(result))
    else:
        # Rule-based fallback: archetype + observations without API key
        from unjiggle.archetypes import assign_archetype
        from unjiggle.swipetax import compute_swipe_tax

        archetype, tagline = assign_archetype(layout, metadata)
        tax = compute_swipe_tax(layout, metadata)

        _json_out({
            "observations": [],
            "personality": tagline,
            "archetype": archetype,
            "score": {
                "total": round(score.total),
                "label": score.label,
            },
            "swipe_tax": _swipe_tax_to_json(tax),
        })


@json.command(name="restore")
@click.argument("backup_file", type=click.Path(exists=True), required=True)
def json_restore(backup_file: str):
    """Restore a previously backed up layout and verify it."""
    from unjiggle.device import connect, read_layout, restore_layout_from_file, write_layout

    try:
        lockdown, _device = connect()
    except Exception:
        _json_err("No iPhone detected")

    try:
        raw_state = restore_layout_from_file(Path(backup_file))
    except Exception as e:
        _json_err(f"Failed to read backup: {e}")

    write_layout(lockdown, raw_state)
    verify = read_layout(lockdown)

    expected_json = _json.dumps(raw_state, default=str, sort_keys=True)
    restored_json = _json.dumps(verify.raw, default=str, sort_keys=True)
    if expected_json != restored_json:
        _json_err("Restore verification failed.")

    _json_out({
        "restored": True,
        "backup": str(Path(backup_file)),
        "result": {
            "page_count": verify.page_count,
            "total_apps": verify.total_apps,
        },
    })


@json.command(name="render")
@click.option(
    "--card",
    type=click.Choice(("score", "mirror", "obituary", "swipetax", "transform"), case_sensitive=False),
    required=True,
)
@click.option(
    "--action",
    type=click.Choice(("preview", "clipboard", "save"), case_sensitive=False),
    default="preview",
)
@click.option("--backup", default=None, help="Backup path required for transform cards.")
@click.option("--api-key", envvar=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], default=None)
@click.option("--model", default=None)
def json_render(card: str, action: str, backup: str | None, api_key: str | None, model: str | None):
    """Render a share card to PNG for preview, clipboard, or save."""
    import shutil

    from unjiggle.archetypes import assign_archetype
    from unjiggle.cards import (
        generate_mirror_card,
        generate_obituary_card,
        generate_swipetax_card,
        generate_transform_card,
        save_card,
    )
    from unjiggle.device import (
        connect,
        parse_layout_state,
        read_layout,
        restore_layout_from_file,
    )
    from unjiggle.itunes import enrich_layout
    from unjiggle.mirror import generate_mirror
    from unjiggle.obituary import generate_obituaries
    from unjiggle.render import copy_image, render_to_png
    from unjiggle.scoring import compute_score
    from unjiggle.swipetax import compute_swipe_tax
    from unjiggle.visualize import generate_share_card

    try:
        lockdown, _device = connect()
    except Exception:
        _json_err("No iPhone detected")

    current_layout = read_layout(lockdown)
    current_metadata = enrich_layout(current_layout)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    html_path = UNJIGGLE_DIR / "reports" / f"{card}-{timestamp}.html"

    if card == "score":
        score = compute_score(current_layout, current_metadata)
        archetype, personality = assign_archetype(current_layout, current_metadata)
        card_html = generate_share_card(
            current_layout,
            current_metadata,
            score,
            archetype=archetype,
            personality=personality,
        )
    elif card == "mirror":
        score = compute_score(current_layout, current_metadata)
        mirror_result = generate_mirror(
            current_layout, current_metadata, score, api_key=api_key, model=model,
        )
        card_html = generate_mirror_card(current_layout, current_metadata, mirror_result)
    elif card == "obituary":
        obituary_result = generate_obituaries(
            current_layout, current_metadata, api_key=api_key, model=model,
        )
        card_html = generate_obituary_card(current_layout, current_metadata, obituary_result)
    elif card == "swipetax":
        tax = compute_swipe_tax(current_layout, current_metadata)
        card_html = generate_swipetax_card(current_layout, current_metadata, tax)
    else:
        if not backup:
            _json_err("--backup is required for transform cards.")
        before_raw = restore_layout_from_file(Path(backup))
        before_layout = parse_layout_state(before_raw)
        before_metadata = enrich_layout(before_layout)
        before_score = round(compute_score(before_layout, before_metadata).total)
        after_score = round(compute_score(current_layout, current_metadata).total)
        summary = (
            f"{before_layout.page_count} pages down to {current_layout.page_count}. "
            f"{max(before_layout.total_apps - current_layout.total_apps, 0)} apps tucked away."
        )
        merged_metadata = dict(before_metadata)
        merged_metadata.update(current_metadata)
        card_html = generate_transform_card(
            before_layout,
            current_layout,
            before_score,
            after_score,
            summary,
            merged_metadata,
        )

    save_card(card_html, html_path)
    png_path = html_path.with_suffix(".png")
    if not render_to_png(html_path, png_path):
        _json_err("PNG render failed. Install a supported Chromium browser.")

    output_path = png_path
    if action == "clipboard":
        if not copy_image(png_path):
            _json_err("Failed to copy image to clipboard.")
    elif action == "save":
        output_path = Path.home() / "Downloads" / png_path.name
        shutil.copy2(png_path, output_path)

    _json_out({
        "success": True,
        "action": action,
        "card": card,
        "html_path": str(html_path),
        "path": str(output_path),
    })


@json.command(name="apply")
def json_apply():
    """Apply operations from JSON on stdin."""
    from unjiggle.analyzer import LayoutOperation
    from unjiggle.device import connect, read_layout, write_layout
    from unjiggle.layout_engine import apply_operations

    try:
        raw_input = click.get_text_stream("stdin").read()
        data = _json.loads(raw_input)
    except (ValueError, _json.JSONDecodeError) as e:
        _json_err(f"Invalid JSON input: {e}")

    operations_data = data.get("operations", [])
    if not operations_data:
        _json_err("No operations provided. Expected {\"operations\": [...]}")

    try:
        lockdown, device = connect()
    except Exception:
        _json_err("No iPhone detected")

    layout = read_layout(lockdown)

    # Parse operations
    ops = []
    for op_data in operations_data:
        ops.append(LayoutOperation(
            action=op_data["action"],
            bundle_ids=op_data.get("bundle_ids", []),
            target_page=op_data.get("target_page"),
            folder_name=op_data.get("folder_name"),
            old_name=op_data.get("old_name"),
            gratitude=op_data.get("gratitude"),
        ))

    # Safety: backup first
    from unjiggle.safety import pre_write_safety_check
    safe, backup_path = pre_write_safety_check(lockdown, layout)
    if not safe:
        _json_err("Safety check failed. No changes made.")

    # Apply and write
    modified_raw = apply_operations(layout, ops)
    write_layout(lockdown, modified_raw)

    # Verify
    from unjiggle.device import read_layout as re_read
    verify = re_read(lockdown)

    _json_out({
        "applied": len(ops),
        "backup": str(backup_path),
        "result": {
            "page_count": verify.page_count,
            "total_apps": verify.total_apps,
        },
    })


if __name__ == "__main__":
    main()
