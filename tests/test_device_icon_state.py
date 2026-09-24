"""Unit tests for IconState write normalization (iOS 27 App Library)."""

from unjiggle.device import (
    _augment_ignored_with_off_homescreen_apps,
    _bundle_ids_in_icon_state,
    icon_state_for_write,
)


def test_icon_state_for_write_converts_list_to_dict():
    # IT之家 already removed from pages; ignored keeps it in App Library.
    state = [
        [{"bundleIdentifier": "com.apple.mobilephone"}],
        [{"bundleIdentifier": "com.atebits.Tweetie2"}],
    ]
    payload = icon_state_for_write(state, ignored=["com.ruanmei.ithome"])

    assert isinstance(payload, dict)
    assert payload["buttonBar"][0]["bundleIdentifier"] == "com.apple.mobilephone"
    assert len(payload["iconLists"]) == 1
    assert payload["iconLists"][0][0]["bundleIdentifier"] == "com.atebits.Tweetie2"
    assert payload["ignored"] == ["com.ruanmei.ithome"]


def test_icon_state_for_write_drops_ignored_entries_still_on_homescreen():
    state = {
        "buttonBar": [],
        "iconLists": [[{"bundleIdentifier": "com.ruanmei.ithome"}]],
        "ignored": ["com.ruanmei.ithome", "com.example.hidden"],
    }
    payload = icon_state_for_write(state)

    # Still on HS → must not stay ignored (would fight the placement).
    assert "com.ruanmei.ithome" not in payload["ignored"]
    assert payload["ignored"] == ["com.example.hidden"]


def test_bundle_ids_in_icon_state_includes_folder_apps():
    state = {
        "buttonBar": [{"bundleIdentifier": "com.apple.mobilephone"}],
        "iconLists": [
            [
                {
                    "displayName": "News",
                    "listType": "folder",
                    "iconLists": [[{"bundleIdentifier": "com.ruanmei.ithome"}]],
                }
            ]
        ],
    }
    assert _bundle_ids_in_icon_state(state) == {
        "com.apple.mobilephone",
        "com.ruanmei.ithome",
    }


def test_augment_ignored_includes_system_apps_not_just_user(monkeypatch):
    """iOS 27 re-adds stock apps unless ignored covers System as well as User."""
    payload = {
        "buttonBar": [{"bundleIdentifier": "com.apple.mobilephone"}],
        "iconLists": [[{"bundleIdentifier": "com.tencent.xin"}]],
        "ignored": [],
    }

    monkeypatch.setattr(
        "unjiggle.device._list_installed_app_bundle_ids",
        lambda lockdown: [
            "com.apple.mobilephone",  # on HS → must not be ignored
            "com.tencent.xin",        # on HS → must not be ignored
            "com.apple.tips",         # system, off HS
            "com.apple.mobilemail",   # system, off HS
            "com.example.thirdparty", # user, off HS
        ],
    )

    out = _augment_ignored_with_off_homescreen_apps(lockdown=object(), payload=payload)
    assert "com.apple.tips" in out["ignored"]
    assert "com.apple.mobilemail" in out["ignored"]
    assert "com.example.thirdparty" in out["ignored"]
    assert "com.apple.mobilephone" not in out["ignored"]
    assert "com.tencent.xin" not in out["ignored"]


# These tests exercise the public write path: a failed inventory must never
# construct a SpringBoard writer, even when the caller supplies ignored IDs.
def test_write_layout_inventory_failure_never_opens_writer(monkeypatch):
    import pytest

    from unjiggle import device

    cause = OSError("device disconnected")

    def fail(_lockdown):
        raise cause

    def forbidden_writer(*args, **kwargs):
        pytest.fail("SpringBoard writer opened without an installed-app inventory")

    monkeypatch.setattr(device, "_list_installed_app_bundle_ids", fail)
    monkeypatch.setattr(
        "pymobiledevice3.services.springboard.SpringBoardServicesService", forbidden_writer
    )
    with pytest.raises(RuntimeError, match="layout was not written") as error:
        device.write_layout(object(), [[], []], ignored=["com.example.library"])
    assert error.value.__cause__ is cause


def test_write_layout_empty_inventory_never_opens_writer(monkeypatch):
    import pytest

    from unjiggle import device

    monkeypatch.setattr(device, "_list_installed_app_bundle_ids", lambda _: [])

    def forbidden_writer(*args, **kwargs):
        pytest.fail("SpringBoard writer opened with an empty inventory")

    monkeypatch.setattr(
        "pymobiledevice3.services.springboard.SpringBoardServicesService", forbidden_writer
    )
    with pytest.raises(RuntimeError, match="empty; layout was not written"):
        device.write_layout(object(), [[], []])


def test_write_layout_automatically_preserves_library_apps_across_writes(monkeypatch):
    import copy

    from unjiggle import device

    state = [
        [{"bundleIdentifier": "com.example.dock"}],
        [{"listType": "folder", "iconLists": [[
            {"bundleIdentifier": "com.example.folder-app"}
        ]]}],
    ]
    original = copy.deepcopy(state)
    inventory_calls = []
    writes = []

    def inventory(_lockdown):
        inventory_calls.append(True)
        return ["com.example.dock", "com.example.folder-app",
                "com.example.library", "com.apple.tips"]

    class Writer:
        def __init__(self, _lockdown):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def set_icon_state(self, payload):
            writes.append(copy.deepcopy(payload))

    monkeypatch.setattr(device, "_list_installed_app_bundle_ids", inventory)
    monkeypatch.setattr(
        "pymobiledevice3.services.springboard.SpringBoardServicesService", Writer
    )
    # getIconState returns a list without ignored on every read.
    for _ in range(2):
        device.write_layout(object(), copy.deepcopy(state))
    assert len(inventory_calls) == 2
    assert len(writes) == 2
    for payload in writes:
        assert payload["buttonBar"] == state[0]
        assert payload["iconLists"] == state[1:]
        assert set(payload["ignored"]) == {"com.example.library", "com.apple.tips"}
    assert state == original
