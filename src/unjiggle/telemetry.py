"""Lightweight opt-in analytics and share feedback.

Analytics are strictly opt-in, prompted once on first run, never again.
Only anonymous aggregate stats are sent — never app names, bundle IDs, or personal data.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console

CONFIG_PATH = Path.home() / ".unjiggle" / "config.json"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def is_analytics_enabled() -> bool:
    return _load_config().get("analytics_enabled", False)


def prompt_analytics_opt_in(console: Console) -> None:
    """Ask the user once if they want to opt in to anonymous analytics."""
    config = _load_config()
    if config.get("analytics_prompted"):
        return

    console.print()
    console.print("  [dim]We're building the world's first phone messiness index. Want in?[/dim]")
    choice = click.prompt(
        "  [dim]Anonymous stats only (app count, pages, score — no app names, nothing personal).[/dim]",
        type=click.Choice(["y", "n"], case_sensitive=False),
        default="n",
        show_default=True,
    )

    config["analytics_prompted"] = True
    config["analytics_enabled"] = choice.lower() == "y"
    _save_config(config)

    if config["analytics_enabled"]:
        console.print("  [dim]You're in. Thanks.[/dim]\n")
    else:
        console.print("  [dim]No problem. Never asked again.[/dim]\n")


def ask_did_share(console: Console) -> str | None:
    """One-keystroke share feedback. Returns 'y', 'n', or None (skipped)."""
    try:
        response = click.prompt(
            "  [dim]Did you share it?[/dim] [dim](y/n, Enter to skip)[/dim]",
            default="",
            show_default=False,
            show_choices=False,
        )
        response = response.strip().lower()
        if response in ("y", "n"):
            return response
        return None
    except (click.Abort, EOFError):
        return None


def send_event(event: str, data: dict) -> None:
    """Send an analytics event if opted in. Fire-and-forget, never blocks."""
    if not is_analytics_enabled():
        return

    # For now, log to a local file. Upgrade to an API endpoint when ready.
    log_path = Path.home() / ".unjiggle" / "analytics.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    from datetime import datetime, timezone
    entry = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **data,
    }

    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # never break the product for analytics
