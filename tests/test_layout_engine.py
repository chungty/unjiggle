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


def _ios26_state():
    """The item shapes of a real iOS 26 icon state (the owner's phone, 2026-09).

    Page 1 has widgets, a Smart Stack and two apps, and all of them have an empty
    "iconLists" key. Folders have listType "folder" and no iconType. Some icons have no
    bundleIdentifier, only a displayIdentifier: pinned icons that are not App Store
    apps (such as web shortcuts), loose and in folders.
    """
    def app(b):
        return {"bundleIdentifier": b, "displayIdentifier": b, "displayName": b.rsplit(".", 1)[-1]}

    def off(b):
        return {"displayIdentifier": b, "displayName": b.rsplit(".", 1)[-1]}

    widget = {"bundleIdentifier": "com.whoop.widget", "containerBundleIdentifier": "com.whoop",
              "displayIdentifier": "W-1", "elementType": "widget", "gridSize": "medium",
              "iconType": "custom", "iconLists": []}
    small = {"bundleIdentifier": "com.sleep.widget", "containerBundleIdentifier": "com.sleep",
             "displayIdentifier": "W-2", "elementType": "widget", "gridSize": "small",
             "iconType": "custom", "iconLists": []}
    stack = {"displayIdentifier": "STACK-1", "gridSize": "small", "iconType": "custom", "iconLists": [],
             "elements": [{"bundleIdentifier": "com.photos.widget", "elementType": "widget"}]}
    notes = {"bundleIdentifier": "com.apple.mobilenotes", "displayIdentifier": "com.apple.mobilenotes",
             "iconType": "app", "iconLists": []}
    health = {"bundleIdentifier": "com.apple.Health", "displayIdentifier": "com.apple.Health",
              "iconType": "app", "iconLists": []}
    return [
        [app("com.apple.mobilesafari")],
        [widget, small, stack, notes, health],
        [{"displayName": "Pictures", "listType": "folder", "iconLists": [[app("com.p.one"), app("com.p.two")]]},
         {"displayName": "Games Archive", "listType": "folder",
          "iconLists": [[app("com.g.installed"), off("com.g.off1"), off("com.g.off2")]]}]
        + [app(f"com.x.a{i:02d}") for i in range(20)] + [off("com.microsoft.Office.Word"), off("com.apple.clips")],
        [app("com.y.b0"), app("com.y.b1")],
    ]


class TestRealIconStateShapes:
    """A widget, a Smart Stack or an app with an empty "iconLists" key is not a folder,
    and an icon without a bundleIdentifier is a pinned icon on the phone."""

    @staticmethod
    def _check(raw, ops):
        from unjiggle.analyzer import preview_operations
        from unjiggle.cli import _layout_signature
        from unjiggle.device import parse_layout_state
        from unjiggle.layout_engine import check_write

        layout = parse_layout_state(raw)
        written, _shown, problem = check_write(layout, ops)
        assert problem is None, problem
        assert _layout_signature(parse_layout_state(written)) == _layout_signature(preview_operations(layout, ops))
        return layout, written

    def test_the_parser_reads_every_shape(self):
        from unjiggle.analyzer import page_slots
        from unjiggle.device import parse_layout_state

        layout = parse_layout_state(_ios26_state())
        first = layout.pages[0]
        assert [item.is_widget for item in first] == [True, True, True, False, False]
        assert [item.app.bundle_id for item in first if item.is_app] == ["com.apple.mobilenotes", "com.apple.Health"]
        assert page_slots(first) == 8 + 4 + 4 + 2
        # The icons without a bundleIdentifier are pinned, found by their displayIdentifier.
        assert page_slots(layout.pages[1]) == 24
        games = layout.pages[1][1].folder
        assert [app.bundle_id for app in games.pages[0]] == ["com.g.installed", "com.g.off1", "com.g.off2"]
        assert [app.pinned for app in games.pages[0]] == [False, True, True]
        assert "com.microsoft.Office.Word" in layout.all_bundle_ids
        assert layout.pinned_ids() == {"com.g.off1", "com.g.off2", "com.microsoft.Office.Word", "com.apple.clips"}

    def test_a_rename_keeps_the_widgets_and_page_one(self):
        raw = _ios26_state()
        op = LayoutOperation(action="rename_folder", bundle_ids=[], folder_name="Photos", old_name="Pictures")
        _layout, written = self._check(raw, [op])
        assert written[1] == raw[1]
        assert len(written) == len(raw)

    def test_a_targeted_change_keeps_the_widgets(self):
        raw = _ios26_state()
        ops = [
            LayoutOperation(action="move_to_page", bundle_ids=["com.y.b0"], target_page=0),
            LayoutOperation(action="move_to_app_library", bundle_ids=["com.x.a00"]),
            LayoutOperation(action="create_folder", bundle_ids=["com.x.a01", "com.x.a02"], folder_name="Work"),
        ]
        _layout, written = self._check(raw, ops)
        assert written[1][:5] == raw[1]
        assert written[1][5]["bundleIdentifier"] == "com.y.b0"

    def test_a_folder_with_pinned_icons_stays_when_its_app_leaves(self):
        raw = _ios26_state()
        op = LayoutOperation(action="move_to_app_library", bundle_ids=["com.g.installed"])
        _layout, written = self._check(raw, [op])
        games = [item for item in written[2] if item.get("displayName") == "Games Archive"]
        assert games and games[0]["iconLists"] == [[raw[2][1]["iconLists"][0][1], raw[2][1]["iconLists"][0][2]]]

    def test_a_pinned_icon_takes_a_slot(self):
        from unjiggle.device import parse_layout_state

        raw = _ios26_state()
        # Page 2 is full: 2 folders, 20 apps and 2 pinned icons.
        op = LayoutOperation(action="move_to_page", bundle_ids=["com.y.b0"], target_page=1)
        layout, written = self._check(raw, [op])
        assert written == raw
        assert parse_layout_state(written).pages == layout.pages

    def test_move_to_page_counts_widget_slots(self):
        raw = _ios26_state()
        # Page 1 uses 18 of 24 slots, so 6 apps fit and a 7th does not.
        six = [f"com.x.a{i:02d}" for i in range(6)]
        _layout, written = self._check(raw, [LayoutOperation(action="move_to_page", bundle_ids=six, target_page=0)])
        assert [item.get("bundleIdentifier") for item in written[1][5:]] == six
        seven = [f"com.x.a{i:02d}" for i in range(7)]
        _layout, written = self._check(raw, [LayoutOperation(action="move_to_page", bundle_ids=seven, target_page=0)])
        assert written == raw

    def test_compact_to_single_page_takes_the_apps_that_fit_beside_the_widgets(self):
        raw = _ios26_state()
        # The widgets of page 1 use 16 slots, so 8 apps fit and 9 do not.
        apps = [f"com.x.a{i:02d}" for i in range(9)]
        _layout, written = self._check(raw, [LayoutOperation(action="compact_to_single_page", bundle_ids=apps)])
        assert written == raw
        _layout, written = self._check(raw, [LayoutOperation(action="compact_to_single_page", bundle_ids=apps[:8])])
        # Page 1: the widgets in their places, then the apps.
        assert written[1][:3] == raw[1][:3]
        assert [item["bundleIdentifier"] for item in written[1][3:]] == apps[:8]
        # Page 2: the folder with only its pinned icons, then the loose pinned icons.
        games = raw[2][1]
        assert written[2] == [{**games, "iconLists": [games["iconLists"][0][1:]]}, raw[2][-2], raw[2][-1]]
        assert len(written) == 3

    def test_an_operation_on_a_dock_app_changes_the_preview_dock_too(self):
        from unjiggle.analyzer import preview_operations

        raw = _ios26_state()
        op = LayoutOperation(action="move_to_page", bundle_ids=["com.apple.mobilesafari"], target_page=0)
        layout, written = self._check(raw, [op])
        assert written[0] == []
        assert preview_operations(layout, [op]).dock == []

    def test_a_legacy_app_library_move_of_a_dock_app_matches_the_preview(self):
        raw = _make_raw_layout()
        op = LayoutOperation(action="move_to_app_library", bundle_ids=["com.apple.mobilesafari"])
        _layout, written = self._check(raw, [op])
        assert "com.apple.mobilesafari" not in written["buttonBar"]
        assert "com.apple.mobilesafari" in written["ignored"]


class TestLostEntries:
    def test_an_entry_that_no_operation_removes_must_stay(self):
        from unjiggle.layout_engine import lost_entries

        before = _ios26_state()
        after = [list(page) for page in before]
        after[2] = [item for item in after[2] if item.get("displayIdentifier") != "com.x.a05"]
        assert lost_entries(before, after, []) == ["com.x.a05"]
        remove = LayoutOperation(action="move_to_app_library", bundle_ids=["com.x.a05"])
        assert lost_entries(before, after, [remove]) == []

    def test_a_pinned_icon_is_lost_even_when_an_operation_names_it(self):
        from unjiggle.layout_engine import lost_entries

        before = _ios26_state()
        after = [list(page) for page in before]
        after[2] = [item for item in after[2] if item.get("displayIdentifier") != "com.apple.clips"]
        for action in ("move_to_app_library", "delete", "rebuild_pages"):
            op = LayoutOperation(action=action, bundle_ids=["com.apple.clips"])
            assert lost_entries(before, after, [op]) == ["com.apple.clips"]

    def test_a_lost_widget_is_found(self):
        from unjiggle.layout_engine import lost_entries

        before = _ios26_state()
        after = [list(page) for page in before]
        after[1] = after[1][3:]
        assert lost_entries(before, after, []) == ["com.whoop.widget", "com.sleep.widget", "STACK-1"]

    def test_after_a_rebuild_the_dock_widgets_and_pinned_icons_are_checked(self):
        from unjiggle.device import parse_layout_state
        from unjiggle.layout_engine import lost_entries

        before = _ios26_state()
        rebuild = LayoutOperation(action="rebuild_pages", bundle_ids=["com.y.b0"])
        # Apps that the rebuild does not list may leave. Widgets and pinned icons may not.
        assert lost_entries(before, [before[0], [before[3][0]]], [rebuild]) == [
            "com.whoop.widget", "com.sleep.widget", "STACK-1",
            "com.g.off1", "com.g.off2", "com.microsoft.Office.Word", "com.apple.clips",
        ]
        written = apply_operations(parse_layout_state(before), [rebuild])
        assert lost_entries(before, written, [rebuild]) == []
        written[0] = []
        assert lost_entries(before, written, [rebuild]) == ["com.apple.mobilesafari"]

    def test_check_write_stops_a_write_that_loses_an_entry(self, monkeypatch):
        from unjiggle import layout_engine
        from unjiggle.device import parse_layout_state

        raw = _ios26_state()
        clip = {"iconType": "custom", "displayName": "Web clip"}  # the parser does not show it
        raw[3].append(clip)
        layout = parse_layout_state(raw)
        real = layout_engine.apply_operations

        def losing(layout, ops, drop=None):
            written = real(layout, ops)
            written[3] = [item for item in written[3] if item != drop]
            return written

        op = LayoutOperation(action="rename_folder", bundle_ids=[], folder_name="Photos", old_name="Pictures")
        # A lost app shows in the layout that the write reads back as.
        monkeypatch.setattr(layout_engine, "apply_operations", lambda layout, ops: losing(layout, ops, raw[3][0]))
        assert layout_engine.check_write(layout, [op])[2] == "the written layout would differ from the preview"
        # A lost entry that the parser does not show is found in the raw state.
        monkeypatch.setattr(layout_engine, "apply_operations", lambda layout, ops: losing(layout, ops, clip))
        assert layout_engine.check_write(layout, [op])[2] == "the write would remove Web clip, which no operation names"


class TestPinnedIconsStay:
    """An icon with no bundleIdentifier is not an App Store app. The App Library cannot
    hold it, so no operation moves or removes it, in the preview and in the write."""

    _check = staticmethod(TestRealIconStateShapes._check)

    def test_no_operation_moves_or_removes_a_pinned_icon(self):
        raw = _ios26_state()
        for op in (
            LayoutOperation(action="move_to_app_library", bundle_ids=["com.apple.clips", "com.g.off1"]),
            LayoutOperation(action="delete", bundle_ids=["com.microsoft.Office.Word"]),
            LayoutOperation(action="move_to_page", bundle_ids=["com.apple.clips"], target_page=2),
            LayoutOperation(action="create_folder", bundle_ids=["com.g.off1", "com.g.off2"], folder_name="Old"),
            LayoutOperation(action="move_to_folder", bundle_ids=["com.apple.clips"], folder_name="Pictures"),
        ):
            _layout, written = self._check(raw, [op])
            assert written == raw, op.action

    def test_an_operation_acts_on_the_apps_and_leaves_the_pinned_icons(self):
        raw = _ios26_state()
        op = LayoutOperation(action="move_to_app_library", bundle_ids=["com.g.installed", "com.g.off1", "com.x.a00"])
        _layout, written = self._check(raw, [op])
        games = next(item for item in written[2] if item.get("displayName") == "Games Archive")
        assert [entry["displayIdentifier"] for entry in games["iconLists"][0]] == ["com.g.off1", "com.g.off2"]
        assert "com.x.a00" not in parse_layout_state_ids(written)

    def test_an_id_that_an_app_and_a_pinned_icon_share_moves_only_the_app(self):
        from unjiggle.device import parse_layout_state

        raw = _ios26_state()
        raw[3].append({"displayIdentifier": "com.y.b0", "displayName": "b0 shortcut"})
        layout = parse_layout_state(raw)
        assert "com.y.b0" not in layout.pinned_ids()
        op = LayoutOperation(action="move_to_app_library", bundle_ids=["com.y.b0"])
        _layout, written = self._check(raw, [op])
        assert written[3] == [raw[3][1], raw[3][2]]


def parse_layout_state_ids(raw) -> list[str]:
    from unjiggle.device import parse_layout_state

    return parse_layout_state(raw).all_bundle_ids


def _entry(b):
    return {"bundleIdentifier": b, "displayIdentifier": b, "displayName": b}


def _widget(name, size):
    return {"bundleIdentifier": f"{name}.ext", "containerBundleIdentifier": name, "displayIdentifier": name.upper(),
            "elementType": "widget", "gridSize": size, "iconType": "custom", "iconLists": []}


class TestRebuildsKeepWidgetsAndPinnedIcons:
    """compact_to_single_page and rebuild_pages keep page 1's widgets and pinned icons
    in their places, fit the apps around them, and keep what stays of the other pages
    (widgets, pinned icons, folders with pinned icons) from page 2 on."""

    _check = staticmethod(TestRealIconStateShapes._check)

    def test_page_one_widgets_keep_their_places_among_the_apps(self):
        pin = {"displayIdentifier": "com.web.clip", "displayName": "Clip"}
        raw = [
            [_entry("com.dock")],
            [_entry("com.p1.a"), _entry("com.p1.b"), _widget("com.w.medium", "medium"), pin, _entry("com.p1.c")],
            [_entry(f"com.p2.a{i:02d}") for i in range(20)] + [_widget("com.w.large", "large")],
        ]
        apps = [f"com.p2.a{i:02d}" for i in range(20)]
        _layout, written = self._check(raw, [LayoutOperation(action="rebuild_pages", bundle_ids=apps)])
        first = written[1]
        # The two apps before the widget give their places to the first two apps, and
        # the widget and the pinned icon stay where they were.
        assert first[:5] == [_entry(apps[0]), _entry(apps[1]), raw[1][2], pin, _entry(apps[2])]
        # Page 1: 8 + 1 + 15 apps = 24 slots. The other 5 apps go to page 2, then the
        # large widget of page 2 (16 slots) fits after them.
        assert len(first) == 5 + 12 and [e.get("bundleIdentifier") for e in first[5:]] == apps[3:15]
        assert written[2] == [_entry(b) for b in apps[15:]] + [raw[2][-1]]
        assert len(written) == 3

    def test_the_apps_take_the_places_of_the_page_one_apps_that_leave(self):
        raw = _ios26_state()
        apps = ["com.x.a00", "com.x.a01"]
        _layout, written = self._check(raw, [LayoutOperation(action="rebuild_pages", bundle_ids=apps)])
        assert written[1] == raw[1][:3] + [_entry_like(raw, "com.x.a00"), _entry_like(raw, "com.x.a01")]

    def test_a_page_one_full_of_widgets_takes_no_app_in_a_compact(self):
        raw = [
            [_entry("com.dock")],
            [_widget("com.w.l1", "large"), _widget("com.w.m1", "medium")],
            [_entry("com.p2.a"), _entry("com.p2.b")],
        ]
        compact = LayoutOperation(action="compact_to_single_page", bundle_ids=["com.p2.a"])
        _layout, written = self._check(raw, [compact])
        assert written == raw
        rebuild = LayoutOperation(action="rebuild_pages", bundle_ids=["com.p2.a"])
        _layout, written = self._check(raw, [rebuild])
        assert written == [raw[0], raw[1], [raw[2][0]]]

    def test_widgets_of_later_pages_and_unparsed_entries_stay(self):
        web = {"iconType": "custom", "displayName": "Web clip"}  # the parser drops it
        raw = [
            [_entry("com.dock")],
            [_entry("com.p1.a"), web],
            [],
            [web, {"displayName": "Mixed", "listType": "folder",
                   "iconLists": [[_entry("com.f.a"), web], [{"displayIdentifier": "com.f.pin"}]]}],
            [_widget("com.w.s", "small"), _entry("com.p4.a")],
        ]
        op = LayoutOperation(action="compact_to_single_page", bundle_ids=["com.p4.a"])
        _layout, written = self._check(raw, [op])
        # Page 1: the app in the place of com.p1.a, and the web clip in its place.
        assert written[1] == [_entry("com.p4.a"), web]
        # Page 2: the web clip of page 3, the folder with what is not an App Store app
        # (on one page: the page with the pinned icon), and the small widget of page 4.
        folder = {"displayName": "Mixed", "listType": "folder", "iconLists": [[web, {"displayIdentifier": "com.f.pin"}]]}
        assert written[2] == [web, folder, raw[4][0]]
        assert len(written) == 3

    def test_a_legacy_state_keeps_its_widgets_and_pinned_icons(self):
        raw = {
            "buttonBar": ["com.dock"],
            "iconLists": [
                [{"iconType": "widget", "containerBundleIdentifier": "com.w", "gridSize": "medium"}, "com.a", "com.b"],
                ["com.c", {"displayIdentifier": "com.pin", "displayName": "Pin"}],
            ],
            "ignored": [],
        }
        ops = [
            LayoutOperation(action="move_to_app_library", bundle_ids=["com.b", "com.pin"]),
            LayoutOperation(action="compact_to_single_page", bundle_ids=["com.c"]),
        ]
        _layout, written = self._check(raw, ops)
        assert written["iconLists"] == [[raw["iconLists"][0][0], "com.c"], [raw["iconLists"][1][1]]]
        assert written["ignored"] == ["com.b"]

    def test_the_one_page_primitive_keeps_widgets_and_pinned_icons(self):
        from unjiggle.device import parse_layout_state

        raw = _ios26_state()
        keep = [f"com.x.a{i:02d}" for i in range(12)]
        written = compact_to_single_page(parse_layout_state(raw), keep, ["com.y.b0", "com.apple.clips"])
        # 8 apps fit beside the widgets. The pinned icons stay on page 2.
        assert written[1][:3] == raw[1][:3]
        assert [item["bundleIdentifier"] for item in written[1][3:]] == keep[:8]
        pinned = [e for page in written[2:] for item in page
                  for e in ([item] if "listType" not in item else item["iconLists"][0])]
        assert {e["displayIdentifier"] for e in pinned} == {
            "com.g.off1", "com.g.off2", "com.microsoft.Office.Word", "com.apple.clips"}


def _entry_like(raw, bundle_id):
    for page in raw:
        for item in page:
            if isinstance(item, dict) and item.get("bundleIdentifier") == bundle_id:
                return item
    raise KeyError(bundle_id)
