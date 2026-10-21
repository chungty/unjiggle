"""The inventory read must not imply that a device write or completeness is proven."""

import pytest
import json
from click.testing import CliRunner

from unjiggle import device


def test_reconcile_app_library_candidates_and_unmatched_icons():
    layout = device.parse_layout_state([
        [{"bundleIdentifier": "com.example.visible", "iconType": "app"}],
        [{"displayIdentifier": "shortcut.id", "displayName": "Shortcut"}],
    ])
    records = {
        "com.example.library": {"CFBundleDisplayName": "Library", "ApplicationType": "User"},
        "com.example.visible": {"CFBundleName": "Visible", "ApplicationType": "User"},
    }
    inventory = device.reconcile_installed_apps(records, layout)
    assert [app.bundle_id for app in inventory.apps] == ["com.example.library", "com.example.visible"]
    assert [app.on_home_screen for app in inventory.apps] == [False, True]
    assert inventory.unmatched_home_screen_ids == ("shortcut.id",)


@pytest.mark.parametrize("records", [
    {},
    {"": {}},
    {"com.example.app": {"CFBundleIdentifier": "com.example.other"}},
    {"com.example.app": {"CFBundleDisplayName": ["bad"]}},
])
def test_rejects_invalid_inventory(records):
    with pytest.raises(ValueError):
        device.reconcile_installed_apps(records, device.parse_layout_state([[]]))


def test_read_installed_apps_uses_lookup_without_writing(monkeypatch):
    from pymobiledevice3.services import installation_proxy

    calls = []

    class FakeService:
        def __init__(self, lockdown):
            assert lockdown == "fake phone"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get_apps(self, application_type):
            calls.append(application_type)
            return {"com.example.library": {"CFBundleDisplayName": "Library"}}

    monkeypatch.setattr(installation_proxy, "InstallationProxyService", FakeService)
    inventory = device.read_installed_apps("fake phone", device.parse_layout_state([[]]))
    assert calls == ["Any"]
    assert inventory.apps[0].on_home_screen is False


def test_json_inventory_is_read_only_and_preserves_unknown_icons(monkeypatch):
    from unjiggle import cli

    layout = device.parse_layout_state([
        [],
        [{"bundleIdentifier": "com.example.visible"}, {"displayIdentifier": "shortcut.id"}],
    ])
    phone = type("Phone", (), {"name": "Test", "model": "iPhone", "ios_version": "27.0.1"})()
    monkeypatch.setattr(device, "connect", lambda: ("lockdown", phone))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: layout)
    monkeypatch.setattr(device, "read_installed_apps", lambda lockdown, current: device.reconcile_installed_apps({
        "com.example.library": {"CFBundleDisplayName": "Notes", "ApplicationType": "User"},
        "com.example.visible": {"CFBundleDisplayName": "Mail", "ApplicationType": "User"},
    }, current))
    monkeypatch.setattr(device, "write_layout", lambda *args: pytest.fail("inventory wrote to device"))

    result = CliRunner().invoke(cli.main, ["json", "inventory"])
    assert result.exit_code == 0, result.output
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert payload["snapshot_id"]
    assert payload["unmatched_home_screen_ids"] == ["shortcut.id"]
    assert [(app["bundle_id"], app["on_home_screen"]) for app in payload["apps"]] == [
        ("com.example.library", False), ("com.example.visible", True),
    ]


def test_json_inventory_refuses_missing_response(monkeypatch):
    from unjiggle import cli

    monkeypatch.setattr(device, "connect", lambda: ("lockdown", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: device.parse_layout_state([[]]))
    monkeypatch.setattr(device, "read_installed_apps", lambda lockdown, layout: device.reconcile_installed_apps({}, layout))
    result = CliRunner().invoke(cli.main, ["json", "inventory"])
    assert result.exit_code != 0
    assert "error" in json.loads(result.stdout)
