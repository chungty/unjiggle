"""Unit tests for IconState write normalization (iOS 27 App Library)."""

from unjiggle.device import _bundle_ids_in_icon_state, icon_state_for_write


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
