"""Tests for the layout engine (raw plist operations)."""


from unjiggle.analyzer import LayoutOperation
from unjiggle.layout_engine import apply_operations, compact_to_single_page
from unjiggle.models import HomeScreenLayout


def _make_raw_layout() -> dict:
    """Build a raw plist dict matching a simple layout."""
    return {
        "buttonBar": [
            "com.apple.mobilesafari",
            "com.apple.MobileSMS",
            "com.apple.mobilephone",
            "com.apple.mobilemail",
        ],
        "iconLists": [
            # Page 1
            [
                "com.apple.Maps",
                "com.spotify.client",
                "com.tinyspeck.chatlyio",
                "com.notion.Notion",
                {
                    "displayName": "Social",
                    "iconLists": [["com.facebook.Facebook", "com.twitter.twitter", "com.instagram.Instagram"]],
                    "listType": "folder",
                },
            ],
            # Page 2
            [
                "com.darksky.darksky",
                "com.carrotweather.CARROT",
                "com.apple.weather",
                "com.hp.printer",
                "com.canon.print",
            ],
            # Page 3 (sparse)
            [
                "com.ibm.watson.ios",
                "com.shazam.Shazam",
            ],
        ],
        "ignored": ["com.apple.tips"],
    }


def _make_layout_with_raw(raw: dict) -> HomeScreenLayout:
    """Create a HomeScreenLayout with the raw dict set."""
    from unjiggle.device import _parse_layout_item

    dock = []
    for item in raw.get("buttonBar", []):
        parsed = _parse_layout_item(item)
        if parsed:
            dock.append(parsed)

    pages = []
    for page_items in raw.get("iconLists", []):
        page = []
        for item in page_items:
            parsed = _parse_layout_item(item)
            if parsed:
                page.append(parsed)
        if page:
            pages.append(page)

    return HomeScreenLayout(
        dock=dock,
        pages=pages,
        ignored=raw.get("ignored", []),
        raw=raw,
    )


class TestApplyOperations:
    def test_move_to_app_library(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        ops = [LayoutOperation(
            action="move_to_app_library",
            bundle_ids=["com.darksky.darksky", "com.ibm.watson.ios"],
        )]
        result = apply_operations(layout, ops)

        # Apps should be removed from pages
        all_items = []
        for page in result["iconLists"]:
            for item in page:
                if isinstance(item, str):
                    all_items.append(item)
        assert "com.darksky.darksky" not in all_items
        assert "com.ibm.watson.ios" not in all_items

        # Apps should be in ignored
        assert "com.darksky.darksky" in result["ignored"]
        assert "com.ibm.watson.ios" in result["ignored"]

    def test_empty_pages_cleaned_up(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        # Remove both apps from page 3
        ops = [LayoutOperation(
            action="move_to_app_library",
            bundle_ids=["com.ibm.watson.ios", "com.shazam.Shazam"],
        )]
        result = apply_operations(layout, ops)

        # Page 3 should be gone (was only 2 apps)
        assert len(result["iconLists"]) == 2

    def test_rename_folder(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        ops = [LayoutOperation(
            action="rename_folder",
            bundle_ids=[],
            old_name="Social",
            folder_name="Social Media",
        )]
        result = apply_operations(layout, ops)

        # Find the folder
        for page in result["iconLists"]:
            for item in page:
                if isinstance(item, dict) and item.get("listType") == "folder":
                    if item.get("displayName") == "Social Media":
                        return  # Found it
        assert False, "Renamed folder not found"

    def test_create_folder(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        ops = [LayoutOperation(
            action="create_folder",
            bundle_ids=["com.hp.printer", "com.canon.print"],
            folder_name="Printers",
        )]
        result = apply_operations(layout, ops)

        # Find the new folder
        found = False
        for page in result["iconLists"]:
            for item in page:
                if isinstance(item, dict) and item.get("displayName") == "Printers":
                    found = True
                    # Should contain the printer apps
                    folder_apps = item["iconLists"][0]
                    folder_bids = [a if isinstance(a, str) else a.get("bundleIdentifier", "") for a in folder_apps]
                    assert "com.hp.printer" in folder_bids
                    assert "com.canon.print" in folder_bids
        assert found, "Printers folder not created"

        # Original apps should be removed from page 2
        page2_strings = [item for item in result["iconLists"][1] if isinstance(item, str)]
        assert "com.hp.printer" not in page2_strings
        assert "com.canon.print" not in page2_strings

    def test_move_to_page(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        # Move weather apps to page 1
        ops = [LayoutOperation(
            action="move_to_page",
            bundle_ids=["com.darksky.darksky", "com.carrotweather.CARROT"],
            target_page=0,
        )]
        result = apply_operations(layout, ops)

        page1_strings = [item for item in result["iconLists"][0] if isinstance(item, str)]
        assert "com.darksky.darksky" in page1_strings
        assert "com.carrotweather.CARROT" in page1_strings

    def test_move_to_folder(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        ops = [LayoutOperation(
            action="move_to_folder",
            bundle_ids=["com.apple.Maps"],
            folder_name="Social",
        )]
        result = apply_operations(layout, ops)

        # Maps should be inside the Social folder now
        for page in result["iconLists"]:
            for item in page:
                if isinstance(item, dict) and item.get("displayName") == "Social":
                    all_folder_items = []
                    for fp in item["iconLists"]:
                        all_folder_items.extend(fp)
                    folder_bids = [a if isinstance(a, str) else a.get("bundleIdentifier", "") for a in all_folder_items]
                    assert "com.apple.Maps" in folder_bids
                    return
        assert False, "Social folder not found"

    def test_does_not_modify_original(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)
        original_page_count = len(raw["iconLists"])

        ops = [LayoutOperation(
            action="move_to_app_library",
            bundle_ids=["com.ibm.watson.ios", "com.shazam.Shazam"],
        )]
        apply_operations(layout, ops)

        # Original raw should be unchanged
        assert len(layout.raw["iconLists"]) == original_page_count

    def test_multiple_operations_compound(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        ops = [
            LayoutOperation(action="move_to_app_library", bundle_ids=["com.darksky.darksky"]),
            LayoutOperation(action="rename_folder", bundle_ids=[], old_name="Social", folder_name="Friends"),
            LayoutOperation(action="create_folder", bundle_ids=["com.hp.printer", "com.canon.print"], folder_name="Printers"),
        ]
        result = apply_operations(layout, ops)

        # Dark Sky gone
        all_strings = []
        for page in result["iconLists"]:
            for item in page:
                if isinstance(item, str):
                    all_strings.append(item)
        assert "com.darksky.darksky" not in all_strings

        # Social renamed to Friends
        folder_names = []
        for page in result["iconLists"]:
            for item in page:
                if isinstance(item, dict) and "displayName" in item:
                    folder_names.append(item["displayName"])
        assert "Friends" in folder_names
        assert "Social" not in folder_names
        assert "Printers" in folder_names

    def test_remove_app_from_folder(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        ops = [LayoutOperation(
            action="move_to_app_library",
            bundle_ids=["com.facebook.Facebook"],
        )]
        result = apply_operations(layout, ops)

        # Facebook should be removed from Social folder
        for page in result["iconLists"]:
            for item in page:
                if isinstance(item, dict) and item.get("displayName") == "Social":
                    folder_apps = item["iconLists"][0]
                    folder_bids = [a if isinstance(a, str) else a.get("bundleIdentifier") for a in folder_apps]
                    assert "com.facebook.Facebook" not in folder_bids
                    assert "com.twitter.twitter" in folder_bids  # Others remain
                    return
        assert False, "Social folder not found"

    def test_compact_to_single_page_keeps_only_requested_apps(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        result = compact_to_single_page(
            layout,
            keep_visible_bundle_ids=[
                "com.apple.Maps",
                "com.spotify.client",
                "com.tinyspeck.chatlyio",
            ],
            archive_bundle_ids=[
                "com.darksky.darksky",
                "com.carrotweather.CARROT",
                "com.apple.weather",
                "com.hp.printer",
                "com.canon.print",
                "com.ibm.watson.ios",
                "com.shazam.Shazam",
                "com.facebook.Facebook",
                "com.twitter.twitter",
                "com.instagram.Instagram",
                "com.notion.Notion",
            ],
        )

        assert len(result["iconLists"]) == 1
        page1_strings = [item for item in result["iconLists"][0] if isinstance(item, str)]
        assert page1_strings == [
            "com.apple.Maps",
            "com.spotify.client",
            "com.tinyspeck.chatlyio",
        ]
        assert "com.darksky.darksky" in result["ignored"]

    def test_rebuild_pages_reorders_apps_into_packed_pages(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        ops = [LayoutOperation(
            action="rebuild_pages",
            bundle_ids=[
                "com.tinyspeck.chatlyio",
                "com.spotify.client",
                "com.apple.Maps",
            ],
        )]

        result = apply_operations(layout, ops)

        assert len(result["iconLists"]) == 1
        assert result["iconLists"][0][:3] == [
            "com.tinyspeck.chatlyio",
            "com.spotify.client",
            "com.apple.Maps",
        ]

    def test_move_to_page_keeps_app_when_target_page_is_full(self):
        raw = {
            "buttonBar": [],
            "iconLists": [
                [f"com.test.full{i}" for i in range(24)],
                ["com.test.extra"],
            ],
            "ignored": [],
        }
        layout = _make_layout_with_raw(raw)

        result = apply_operations(layout, [
            LayoutOperation(
                action="move_to_page",
                bundle_ids=["com.test.extra"],
                target_page=0,
            ),
        ])

        assert len(result["iconLists"][0]) == 24
        assert result["iconLists"][1] == ["com.test.extra"]

    def test_move_to_missing_folder_is_no_op(self):
        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)

        result = apply_operations(layout, [
            LayoutOperation(
                action="move_to_folder",
                bundle_ids=["com.apple.Maps"],
                folder_name="Does Not Exist",
            ),
        ])

        assert "com.apple.Maps" in result["iconLists"][0]

    def test_create_folder_adds_new_page_when_existing_pages_are_full(self):
        raw = {
            "buttonBar": [],
            "iconLists": [
                [
                    *[f"com.test.full{i}" for i in range(23)],
                    {
                        "displayName": "Source",
                        "iconLists": [["com.test.extra", "com.test.extra2"]],
                        "listType": "folder",
                    },
                ],
            ],
            "ignored": [],
        }
        layout = _make_layout_with_raw(raw)
        ops = [LayoutOperation(
            action="create_folder",
            bundle_ids=["com.test.extra", "com.test.extra2"],
            folder_name="Overflow",
        )]

        result = apply_operations(layout, ops)

        assert len(result["iconLists"]) == 2
        assert result["iconLists"][1][0]["displayName"] == "Overflow"
