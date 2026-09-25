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
                        "iconLists": [["com.test.extra", "com.test.extra2", "com.test.stays"]],
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

    def test_a_folder_that_the_operation_empties_frees_its_slot(self):
        raw = {
            "buttonBar": [],
            "iconLists": [[
                *[f"com.test.full{i}" for i in range(23)],
                {"displayName": "Source", "iconLists": [["com.test.extra", "com.test.extra2"]], "listType": "folder"},
            ]],
            "ignored": [],
        }
        layout = _make_layout_with_raw(raw)
        ops = [LayoutOperation(
            action="create_folder", bundle_ids=["com.test.extra", "com.test.extra2"], folder_name="Overflow",
        )]

        result = apply_operations(layout, ops)

        assert len(result["iconLists"]) == 1
        assert [item["displayName"] for item in result["iconLists"][0] if isinstance(item, dict)] == ["Overflow"]


class TestWritePathMatchesPreview:
    def test_apps_brought_back_after_a_compact_keep_their_original_items(self):
        from unjiggle.device import parse_layout_state

        raw = [
            [{"bundleIdentifier": "com.dock", "iconType": "app"}],
            [
                {"bundleIdentifier": "com.a", "iconType": "app", "displayName": "A"},
                {"bundleIdentifier": "com.b", "iconType": "app", "displayName": "B", "extra": 1},
            ],
            [{"bundleIdentifier": "com.c", "iconType": "app", "displayName": "C"}],
        ]
        layout = parse_layout_state(raw)
        ops = [
            LayoutOperation(action="compact_to_single_page", bundle_ids=["com.a"]),
            LayoutOperation(action="create_folder", bundle_ids=["com.b", "com.c"], folder_name="F"),
        ]
        result = apply_operations(layout, ops)

        assert result[0] == raw[0]
        folder = result[1][1]
        assert folder["displayName"] == "F"
        assert folder["iconLists"] == [[raw[1][1], raw[2][0]]]
        assert raw[1][1] == {"bundleIdentifier": "com.b", "iconType": "app", "displayName": "B", "extra": 1}

    def test_folders_that_the_operations_empty_are_removed(self):
        from unjiggle.analyzer import preview_operations

        raw = _make_raw_layout()
        layout = _make_layout_with_raw(raw)
        social = ["com.facebook.Facebook", "com.twitter.twitter", "com.instagram.Instagram"]
        ops = [LayoutOperation(action="move_to_app_library", bundle_ids=social)]
        result = apply_operations(layout, ops)

        assert not any(isinstance(item, dict) for item in result["iconLists"][0])
        preview = preview_operations(layout, ops)
        assert [len(page) for page in preview.pages] == [len(page) for page in result["iconLists"]]

    def test_app_library_moves_on_an_ios26_state_match_the_preview(self):
        from unjiggle.analyzer import preview_operations
        from unjiggle.device import parse_layout_state

        raw = [
            [{"bundleIdentifier": "com.dock", "iconType": "app"}],
            [{"bundleIdentifier": "com.a", "iconType": "app"}, {"bundleIdentifier": "com.b", "iconType": "app"}],
        ]
        layout = parse_layout_state(raw)
        ops = [LayoutOperation(action="move_to_app_library", bundle_ids=["com.b"])]
        written = parse_layout_state(apply_operations(layout, ops))
        preview = preview_operations(layout, ops)

        # The iOS 26 state has no ignored list, so the preview records nothing either.
        assert preview.ignored == written.ignored == []
        assert preview.all_bundle_ids == written.all_bundle_ids == ["com.dock", "com.a"]

    def test_folders_get_pages_of_nine_apps_as_on_the_phone(self):
        from unjiggle.analyzer import preview_operations
        from unjiggle.cli import _layout_signature
        from unjiggle.device import parse_layout_state

        apps = [f"com.f.app{i:02d}" for i in range(24)]
        raw = [
            [{"bundleIdentifier": "com.dock", "iconType": "app"}],
            [{"displayName": "Old", "iconType": "folder",
              "iconLists": [[{"bundleIdentifier": b, "iconType": "app"} for b in apps[:6]],
                            [{"bundleIdentifier": b, "iconType": "app"} for b in apps[6:10]]]}]
            + [{"bundleIdentifier": b, "iconType": "app"} for b in apps[10:]],
        ]
        layout = parse_layout_state(raw)
        ops = [
            LayoutOperation(action="create_folder", bundle_ids=apps[10:21], folder_name="New"),
            LayoutOperation(action="move_to_folder", bundle_ids=apps[21:], folder_name="Old"),
        ]
        result = apply_operations(layout, ops)
        folders = {item["displayName"]: item for item in result[1] if item.get("iconType") == "folder"}

        # A new folder: pages of 9. An existing folder: the last page fills to 9 first.
        assert [len(p) for p in folders["New"]["iconLists"]] == [9, 2]
        assert [len(p) for p in folders["Old"]["iconLists"]] == [6, 7]
        preview = preview_operations(layout, ops)
        assert _layout_signature(parse_layout_state(result)) == _layout_signature(preview)

    def test_a_new_folder_goes_to_a_page_with_a_free_slot(self):
        from unjiggle.analyzer import page_slots, preview_operations
        from unjiggle.cli import _layout_signature
        from unjiggle.device import parse_layout_state

        widgets = [{"iconType": "widget", "containerBundleIdentifier": f"com.w{i}", "gridSize": size}
                   for i, size in enumerate(["medium", "small", "small", "small"])]
        raw = [
            [{"bundleIdentifier": "com.dock", "iconType": "app"}],
            widgets + [{"bundleIdentifier": f"com.p1.a{i}", "iconType": "app"} for i in range(4)],
            [{"bundleIdentifier": f"com.p2.a{i}", "iconType": "app"} for i in range(3)],
        ]
        layout = parse_layout_state(raw)
        assert len(layout.pages[0]) == 8 and page_slots(layout.pages[0]) == 24
        ops = [LayoutOperation(action="create_folder", bundle_ids=["com.p2.a0", "com.p2.a1"], folder_name="F")]
        result = apply_operations(layout, ops)

        # Page 1 has 8 items but no free slot, so the folder goes to page 2.
        assert result[1] == raw[1]
        assert result[2][-1]["displayName"] == "F"
        preview = preview_operations(layout, ops)
        assert _layout_signature(parse_layout_state(result)) == _layout_signature(preview)

    @staticmethod
    def _agree(raw, op):
        from unjiggle.analyzer import preview_operations
        from unjiggle.cli import _layout_signature
        from unjiggle.device import parse_layout_state

        layout = parse_layout_state(raw)
        written = parse_layout_state(apply_operations(layout, [op]))
        preview = preview_operations(layout, [op])
        return _layout_signature(written) == _layout_signature(preview), written

    def test_raw_entries_that_the_parser_drops_take_no_slot_and_no_page_index(self):
        from unjiggle.device import parse_layout_state

        def app(b):
            return {"bundleIdentifier": b, "iconType": "app"}

        clip = {"iconType": "custom", "displayName": "Web clip"}  # no bundle ID: the parser drops it
        new_folder = LayoutOperation(action="create_folder", bundle_ids=["com.p2.x", "com.p2.y"], folder_name="New")
        move = LayoutOperation(action="move_to_page", bundle_ids=["com.p1.a0"], target_page=1)
        states = [
            [[app("com.d")], [app(f"com.p1.a{i}") for i in range(23)] + [clip], [app("com.p2.x"), app("com.p2.y")]],
            [[app("com.d")], [app(f"com.p1.a{i}") for i in range(24)], [], [app("com.p2.x"), app("com.p2.y")]],
            [[app("com.d")], [app(f"com.p1.a{i}") for i in range(24)], [clip], [app("com.p2.x"), app("com.p2.y")]],
        ]
        for raw in states:
            for op in (new_folder, move):
                same, _written = self._agree(raw, op)
                assert same, (raw, op.action)
        # The entry that the parser drops stays where it was.
        result = apply_operations(parse_layout_state(states[0]), [new_folder])
        assert clip in result[1]

    def test_a_dock_folder_is_found_first_in_the_legacy_state(self):
        dock = ["com.d1", {"displayName": "Work", "iconLists": [["com.d2"]], "listType": "folder"}]
        pages = [["com.p1", {"displayName": "Work", "iconLists": [["com.p2"]], "listType": "folder"}, "com.p3"]]
        raw = {"buttonBar": dock, "iconLists": pages, "ignored": []}
        for op in (
            LayoutOperation(action="move_to_folder", bundle_ids=["com.p3"], folder_name="Work"),
            LayoutOperation(action="rename_folder", bundle_ids=[], folder_name="Tools", old_name="Work"),
        ):
            same, written = self._agree(raw, op)
            assert same, op.action
            assert written.dock[1].folder.display_name == ("Work" if op.action == "move_to_folder" else "Tools")
