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
