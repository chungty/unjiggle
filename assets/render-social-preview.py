"""Render social-preview.svg with Chrome at its native 1280x640 size.

Run `python assets/render-social-preview.py` with Chrome installed.
"""

from pathlib import Path
import shutil
from struct import unpack
import subprocess


def main():
    source = Path(__file__).with_name("social-preview.svg")
    output = source.with_suffix(".png")
    mac_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    browser = next(
        (path for path in (shutil.which("google-chrome"), shutil.which("chromium"),
                           str(mac_chrome) if mac_chrome.is_file() else None) if path),
        None,
    )
    if not browser:
        raise SystemExit("Install Google Chrome or Chromium to render the social preview")
    subprocess.run(
        [browser, "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--hide-scrollbars", "--force-device-scale-factor=1", "--window-size=1280,640",
         f"--screenshot={output}", source.resolve().as_uri()],
        check=True,
    )
    header = output.read_bytes()[:24]
    if header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" or unpack(">II", header[16:24]) != (1280, 640):
        raise SystemExit("Chrome did not produce a 1280x640 PNG")


if __name__ == "__main__":
    main()
