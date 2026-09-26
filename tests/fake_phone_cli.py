"""Run the unjiggle CLI in a subprocess with an in-memory iPhone.

tests/test_json_contract.py starts this file as `python fake_phone_cli.py json <command>`,
as a client starts `unjiggle json <command>`: stdin holds only the JSON payload (or
nothing), and the test reads stdout and stderr. Nothing touches a real iPhone. The device
functions read and write the icon state in the file FAKE_PHONE_STATE.

Environment:
- FAKE_PHONE_STATE: JSON file with the raw icon state.
- FAKE_PHONE_METADATA: JSON file with the App Store metadata (optional).
- FAKE_PHONE_WRITES: file that gets one line for each write to the phone.
- FAKE_PHONE_BACKUPS: directory for the backups.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from unjiggle import cli, device, itunes, safety, screentime
from unjiggle.models import DeviceInfo

STATE = Path(os.environ["FAKE_PHONE_STATE"])
WRITES = Path(os.environ["FAKE_PHONE_WRITES"])
METADATA_PATH = os.environ.get("FAKE_PHONE_METADATA")
METADATA = json.loads(Path(METADATA_PATH).read_text()) if METADATA_PATH else {}


def _connect():
    return "LOCKDOWN", DeviceInfo(name="Test iPhone", model="iPhone18,4", ios_version="26.0", udid="FAKE")


def _read_layout(_lockdown):
    # A library that prints to stdout must not put text before or after the JSON.
    print("fake springboard: get_icon_state")
    return device.parse_layout_state(json.loads(STATE.read_text()))


def _write_layout(_lockdown, state):
    print("fake springboard: set_icon_state")
    STATE.write_text(json.dumps(state, default=str))
    with WRITES.open("a") as log:
        log.write("write\n")


device.connect = _connect
device.read_layout = _read_layout
device.write_layout = _write_layout
itunes.enrich_layout = lambda layout, progress_callback=None: METADATA
screentime.get_usage = lambda bundle_ids=None, iphone_only=True: {}
safety.BACKUP_DIR = Path(os.environ["FAKE_PHONE_BACKUPS"])


if __name__ == "__main__":
    cli.main(prog_name="unjiggle")
