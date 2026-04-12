"""Card rendering: HTML → PNG export + clipboard integration.

Uses Chrome headless (already on every Mac) for PNG rendering.
Zero additional Python dependencies.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CARD_WIDTH = 1080
CARD_HEIGHT = 1350

# Chrome paths on macOS (checked in order)
_CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Arc.app/Contents/MacOS/Arc",
]


def _find_chrome() -> str | None:
    for p in _CHROME_PATHS:
        if Path(p).exists():
            return p
    return None


def render_to_png(html_path: Path, png_path: Path) -> bool:
    """Render HTML card to PNG using Chrome headless. No Python deps needed."""
    chrome = _find_chrome()
    if not chrome:
        return False

    try:
        subprocess.run(
            [
                chrome,
                "--headless=new",
                f"--screenshot={png_path.resolve()}",
                f"--window-size={CARD_WIDTH},{CARD_HEIGHT}",
                "--hide-scrollbars",
                "--disable-gpu",
                "--no-sandbox",
                f"file://{html_path.resolve()}",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return png_path.exists()
    except (subprocess.SubprocessError, OSError):
        return False


def copy_text(text: str) -> bool:
    """Copy text to system clipboard (macOS)."""
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def copy_image(png_path: Path) -> bool:
    """Copy PNG to system clipboard (macOS). User can Cmd+V to paste anywhere."""
    if sys.platform != "darwin" or not png_path.exists():
        return False
    try:
        script = (
            f'set the clipboard to '
            f'(read (POSIX file "{png_path.resolve()}") as «class PNGf»)'
        )
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def export_card(html_path: Path, console=None) -> Path | None:
    """Render card to PNG, copy to clipboard. Returns PNG path or None."""
    png_path = html_path.with_suffix(".png")

    if render_to_png(html_path, png_path):
        copied = copy_image(png_path)
        if console:
            if copied:
                console.print("  [green bold]Share card copied to clipboard.[/green bold] Cmd+V to paste anywhere.")
            else:
                console.print(f"  [green]Share card saved:[/green] {png_path}")
        return png_path

    # Fallback: open HTML in browser
    if console:
        import webbrowser
        webbrowser.open(f"file://{html_path.resolve()}")
        console.print("  [green]Share card opened in browser.[/green]")
    return None
