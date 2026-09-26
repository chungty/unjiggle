"""Every write keeps the widgets, the pinned icons and the apps.

A pinned icon has no bundleIdentifier: it is not an App Store app (such as a web
shortcut or an App Clip), so the App Library cannot hold it. For each preset and for
representative AI Stylist plans, the tests write the operations to the raw icon state
and count what the written state holds:

- the widgets and Smart Stacks: the same, and page 1's stay on page 1;
- the pinned icons: the same;
- the App Store apps: the same, less the apps that an operation deletes or sends to
  the App Library;
- the written state reads back as the preview.

The phones are synthetic. To run the same checks on a real icon state backup, set
UNJIGGLE_REAL_BACKUP to its path (and UNJIGGLE_REAL_METADATA to an App Store metadata
cache in JSON, if there is one). Those tests are skipped otherwise.
"""

from __future__ import annotations

import json
import os
import random
from collections import Counter
from pathlib import Path

import pytest

from unjiggle import cli, stylist
from unjiggle.analyzer import LayoutOperation, preview_operations
from unjiggle.device import (
    entry_app_id,
    is_app_store_entry,
    is_folder_entry,
    is_widget_entry,
    parse_layout_state,
)
from unjiggle.layout_engine import check_write

PRESETS = ("focus", "relax", "minimal", "beautiful")
CATEGORIES = ["Productivity", "Utilities", "System", "Finance", "Education", "Social",
              "Entertainment", "Games", "Health", "Travel", "Shopping", "News"]


@pytest.fixture(autouse=True)
def _no_screen_time(monkeypatch):
    from unjiggle import screentime

    monkeypatch.setattr(screentime, "get_usage", lambda *args, **kwargs: {})


# --- the census of a raw icon state ------------------------------------------------------


def _containers(raw) -> list[list]:
    return raw if isinstance(raw, list) else [raw.get("buttonBar", []), *raw.get("iconLists", [])]


def census(raw) -> dict:
    """What a raw icon state holds: widget keys, pinned icon keys, App Store app IDs
    (with their copies), folders, and the widgets of page 1."""
    widgets: Counter = Counter()
    pinned: Counter = Counter()
    apps: Counter = Counter()
    folders = 0

    def entry(item):
        if is_widget_entry(item):
            widgets[json.dumps(item, sort_keys=True, default=str)] += 1
        elif is_app_store_entry(item):
            apps[entry_app_id(item)] += 1
        else:
            pinned[json.dumps(item, sort_keys=True, default=str)] += 1

    for container in _containers(raw):
        for item in container:
            if is_folder_entry(item) or (isinstance(item, dict) and "listType" in item):
                folders += 1
                for folder_page in item.get("iconLists") or []:
                    for member in folder_page:
                        entry(member)
            else:
                entry(item)
    pages = _containers(raw)[1:]
    live = [page for page in pages if parse_layout_state(_with_pages(raw, [page])).pages]
    first = live[0] if live else []
    return {
        "widgets": widgets,
        "pinned": pinned,
        "apps": apps,
        "folders": folders,
        "page_one_widgets": [json.dumps(i, sort_keys=True) for i in first if is_widget_entry(i)],
    }


def _with_pages(raw, pages):
    if isinstance(raw, list):
        return [raw[0] if raw else [], *pages]
    return {**raw, "iconLists": pages}


def check_preserved(layout, operations, exact_apps: bool = False, rebuild_drops: bool = False):
    """Write the operations and check the census. Returns the written raw state.

    exact_apps: each app keeps all of its copies. rebuild_drops: a rebuild may take
    apps that it does not list off the home screen (the presets and the AI Stylist
    name each such app in an App Library move or a delete).
    """
    written, shown, problem = check_write(layout, operations)
    assert problem is None, problem
    assert cli._layout_signature(parse_layout_state(written)) == cli._layout_signature(shown)
    assert cli._layout_signature(shown) == cli._layout_signature(preview_operations(layout, operations))

    before, after = census(layout.raw), census(written)
    assert after["widgets"] == before["widgets"], "a widget or a Smart Stack is lost"
    assert after["pinned"] == before["pinned"], "an icon that is not an App Store app is lost"
    assert after["page_one_widgets"] == before["page_one_widgets"], "page 1 widgets moved"
    removed = {b for op in operations if op.action in ("delete", "move_to_app_library") for b in op.bundle_ids}
    if rebuild_drops:
        assert set(after["apps"]) <= set(before["apps"]) - removed, "an app is invented"
    else:
        assert set(after["apps"]) == set(before["apps"]) - removed, "an app is lost or invented"
    if exact_apps:
        assert after["apps"] == before["apps"], "the copies of an app changed"
    return written


# --- synthetic phones --------------------------------------------------------------------


def _app(bundle_id):
    return {"bundleIdentifier": bundle_id, "displayIdentifier": bundle_id, "displayName": bundle_id.rsplit(".", 1)[-1],
            "bundleVersion": "1", "iconModDate": "2026-01-01 00:00:00"}


def _pin(bundle_id):
    return {"displayIdentifier": bundle_id, "displayName": bundle_id.rsplit(".", 1)[-1].title()}


def _widget(name, size):
    return {"widgetIdentifier": f"{name}.w", "iconLists": [], "elementType": "widget",
            "containerBundleIdentifier": name, "bundleIdentifier": f"{name}.ext",
            "displayIdentifier": f"W-{name}", "gridSize": size, "iconType": "custom"}


def _stack(name):
    return {"iconLists": [], "displayIdentifier": f"S-{name}", "gridSize": "small", "iconType": "custom",
            "elements": [{"elementType": "widget", "bundleIdentifier": f"{name}.one"},
                         {"elementType": "widget", "bundleIdentifier": f"{name}.two"}]}


def _folder(name, pages):
    return {"displayName": name, "listType": "folder", "iconLists": pages}


def _metadata(bundle_ids, seed):
    rng = random.Random(seed)
    out = {}
    for index, bundle_id in enumerate(bundle_ids):
        if index % 17 == 3:
            continue
        category = rng.choice(CATEGORIES)
        out[bundle_id] = {"name": f"App {index}", "genre": category, "super_category": category,
                          "last_updated": None, "description": None}
    return out


def owner_shaped_phone():
    """The shape of a real iOS 26 icon state (made-up IDs). The dock has 4 apps. Page 1
    has a medium widget, a small widget, a small Smart Stack, a small widget (20 of 24
    slots) and two app entries with a UUID displayIdentifier, whose apps are also in a
    folder. 14 folders; three of them hold pinned icons (4, 2 and 10), on two folder
    pages. Three pinned icons are loose on later pages."""
    rng = random.Random(2609)
    apps = [f"com.owner.app{i:03d}" for i in range(214)]
    pins = [f"com.old.pin{i:02d}" for i in range(19)]
    dock = [_app(f"com.owner.dock{i}") for i in range(4)]
    page_one = [_widget("com.w.rings", "medium"), _widget("com.w.sleep", "small"), _stack("photos"),
                _widget("com.w.weather", "small")]
    page_one += [{"displayIdentifier": "UUID-1", "iconLists": [], "iconType": "app", "bundleIdentifier": apps[0]},
                 {"displayIdentifier": "UUID-2", "iconLists": [], "iconType": "app", "bundleIdentifier": apps[1]}]
    pool = list(apps)

    def take(count):
        return [_app(pool.pop(0)) for _ in range(count)]

    folders = [
        _folder("Flow", [take(5), [_pin(pins[0]), _pin(pins[1])] + take(2) + [_pin(pins[2])] + take(2)
                         + [_pin(pins[3])] + take(1)]),
        _folder("Books", [take(1) + [_pin(pins[4])] + take(2) + [_pin(pins[5])]]),
        _folder("Games Archive", [[_pin(p) for p in pins[6:10]] + take(2) + [_pin(pins[10])],
                                  [_pin(pins[11]), _pin(pins[12])] + take(1) + [_pin(p) for p in pins[13:16]]]),
    ]
    for name in ["Pictures", "Social", "Work", "Read", "Exercise", "Eat", "Fun", "Money", "Shop", "Sports", "Kids"]:
        folders.append(_folder(name, [take(rng.randint(1, 9))]))
    items = folders + [_app(b) for b in pool]
    rng.shuffle(items)
    # Two loose pinned icons on page 5 and one on page 6.
    items[3 * 24 + 3:3 * 24 + 3] = [_pin(pins[16]), _pin(pins[17])]
    items[4 * 24 + 5:4 * 24 + 5] = [_pin(pins[18])]
    raw = [dock, page_one] + [items[i:i + 24] for i in range(0, len(items), 24)]
    return parse_layout_state(raw), _metadata(apps + [f"com.owner.dock{i}" for i in range(4)], 1)


def legacy_phone():
    """A legacy (dict) state: a widget and apps on page 1, a folder with a pinned icon,
    a loose pinned icon and a widget on a later page."""
    apps = [f"com.legacy.app{i:02d}" for i in range(40)]
    pages = [
        [{"iconType": "widget", "containerBundleIdentifier": "com.w.cal", "gridSize": "medium"}] + apps[:6],
        [{"displayName": "Old", "listType": "folder", "iconLists": [[apps[6], _pin("com.old.shortcut"), apps[7]]]}]
        + apps[8:24] + [_pin("com.old.clip")],
        [{"iconType": "widget", "containerBundleIdentifier": "com.w.news", "gridSize": "large"}] + apps[24:40],
    ]
    raw = {"buttonBar": ["com.legacy.dock"], "iconLists": pages, "ignored": ["com.hidden"]}
    return parse_layout_state(raw), _metadata(apps, 2)


def widgets_after_apps_phone():
    """Page 1: four apps, then a large widget, then a pinned icon."""
    apps = [f"com.late.app{i:02d}" for i in range(50)]
    pages = [
        [_app(b) for b in apps[:4]] + [_widget("com.w.big", "large"), _pin("com.web.clip")],
        [_app(b) for b in apps[4:28]],
        [_folder("Kids", [[_app(apps[28]), _pin("com.kids.clip")]])] + [_app(b) for b in apps[29:50]],
    ]
    return parse_layout_state([[_app("com.late.dock")], *pages]), _metadata(apps, 3)


def full_widget_page_phone():
    """Page 1 holds only widgets (24 slots), so a new layout has no room for apps on it."""
    apps = [f"com.full.app{i:02d}" for i in range(30)]
    pages = [
        [_widget("com.w.l", "large"), _widget("com.w.m", "medium")],
        [_app(b) for b in apps[:20]] + [_pin("com.full.pin")],
        [_folder("Misc", [[_app(b) for b in apps[20:25]]])] + [_app(b) for b in apps[25:]],
    ]
    return parse_layout_state([[_app("com.full.dock")], *pages]), _metadata(apps, 4)


PHONES = {
    "owner-shaped": owner_shaped_phone,
    "legacy": legacy_phone,
    "widgets-after-apps": widgets_after_apps_phone,
    "full-widget-page": full_widget_page_phone,
}


def test_the_owner_shaped_phone_has_the_shapes_of_the_real_one():
    layout, _metadata = owner_shaped_phone()
    counts = census(layout.raw)
    assert sum(counts["widgets"].values()) == 4 and len(counts["page_one_widgets"]) == 4
    assert sum(counts["pinned"].values()) == 19
    assert counts["folders"] == 14
    assert len(layout.pinned_ids()) == 19
    assert all(len(page) <= 24 for page in layout.raw[1:])


# --- presets -------------------------------------------------------------------------------


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("phone", PHONES)
def test_every_preset_keeps_widgets_pinned_icons_and_apps(phone, preset):
    layout, metadata = PHONES[phone]()
    operations = cli._PRESET_BUILDERS[preset](layout, metadata)
    assert not {b for op in operations for b in op.bundle_ids} & layout.pinned_ids()
    # focus, relax and beautiful remove no app, and keep each copy of an app.
    check_preserved(layout, operations, exact_apps=preset != "minimal")


def test_the_minimal_preset_fills_only_the_room_beside_the_widgets():
    layout, metadata = owner_shaped_phone()
    operations = cli._build_minimal_preset_operations(layout, metadata)
    compact = [op for op in operations if op.action == "compact_to_single_page"]
    assert len(compact) == 1 and len(compact[0].bundle_ids) == 4
    written = check_preserved(layout, operations)
    after = parse_layout_state(written)
    first = after.pages[0]
    assert [item.is_widget for item in first] == [True] * 4 + [False] * 4
    # Page 2 holds the pinned icons and the folders that hold them.
    kept = [item for page in after.pages[1:] for item in page]
    assert {item.folder.display_name for item in kept if item.is_folder} == {"Flow", "Books", "Games Archive"}
    assert all(app.pinned for item in kept if item.is_folder for page in item.folder.pages for app in page)


def test_the_beautiful_preset_keeps_page_one_widgets_and_puts_pinned_icons_last():
    layout, metadata = owner_shaped_phone()
    written = check_preserved(layout, cli._build_beautiful_preset_operations(layout, metadata), exact_apps=True)
    after = parse_layout_state(written)
    assert [item.is_widget for item in after.pages[0][:4]] == [True] * 4
    assert all(item.is_app and not item.app.pinned for item in after.pages[0][4:])
    last = [item for page in after.pages[-2:] for item in page]
    assert sum(1 for item in last if item.is_app and item.app.pinned) == 3


# --- AI Stylist plans ------------------------------------------------------------------------


def _handles(layout, metadata):
    handles = stylist.build_handles(layout)
    groups = sorted({stylist.app_group(b, metadata) for b in handles.bundle_ids()})
    return handles, list(handles.by_handle), groups


def representative_plans(layout, metadata) -> dict[str, dict]:
    """A targeted change, a new layout with folders, a minimal layout, a new layout
    whose page 1 does not fit, and App Library moves of whole folders."""
    handles, ids, groups = _handles(layout, metadata)
    names = stylist._display_names(layout)
    folders_now = [item.folder.display_name for page in layout.pages for item in page if item.is_folder]
    first = ids[0]
    gone = handles.by_handle[ids[-1]]
    delete = [{"app": ids[-1], "gratitude": f"{stylist.short_name(gone, metadata, names)} did its job."}]
    return {
        "stay": {"page_one": ids[5:8], "folders": [{"name": "Work", "groups": [], "apps": ids[10:16]}],
                 "app_library": {"groups": [], "apps": ids[20:23]}, "delete": delete, "unplaced": "stay",
                 "note": ""},
        "folders": {"page_one": ids[:3], "folders": [{"name": g, "groups": [g], "apps": []} for g in groups[:6]],
                    "app_library": {"groups": [], "apps": []}, "delete": [], "unplaced": "folders", "note": ""},
        "minimal": {"page_one": [first] + ids[30:33], "folders": [{"name": "Work", "groups": [], "apps": ids[40:50]}],
                    "app_library": {"groups": [], "apps": []}, "delete": delete, "unplaced": "app_library",
                    "note": ""},
        "page-one-overflow": {"page_one": ids[:30], "folders": [{"name": "Rest", "groups": groups[:2], "apps": []}],
                              "app_library": {"groups": [], "apps": []}, "delete": [], "unplaced": "app_library",
                              "note": ""},
        "hide-folders": {"page_one": [], "folders": [],
                         "app_library": {"groups": folders_now, "apps": []}, "delete": [], "unplaced": "stay",
                         "note": ""},
    }


def check_plan(layout, metadata, plan):
    handles = stylist.build_handles(layout)
    ops, report = stylist.expand_plan(plan, layout, metadata, handles)
    assert report.rejected is None, report.rejected
    assert not {b for op in ops for b in op.bundle_ids} & layout.pinned_ids()
    check_preserved(layout, ops)
    return ops, report


PLAN_KINDS = ("stay", "folders", "minimal", "page-one-overflow", "hide-folders")


@pytest.mark.parametrize("kind", PLAN_KINDS)
@pytest.mark.parametrize("phone", PHONES)
def test_ai_plans_keep_widgets_pinned_icons_and_apps(phone, kind):
    layout, metadata = PHONES[phone]()
    ops, _report = check_plan(layout, metadata, representative_plans(layout, metadata)[kind])
    assert ops


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("phone", PHONES)
def test_random_ai_plans_keep_widgets_pinned_icons_and_apps(phone, seed):
    from tests.test_stylist import random_plan

    layout, metadata = PHONES[phone]()
    plan = random_plan(random.Random(f"{phone}-{seed}"), layout, metadata)
    ops, report = stylist.expand_plan(plan, layout, metadata, stylist.build_handles(layout))
    if not report.rejected:
        check_preserved(layout, ops)


def test_a_new_layout_puts_apps_back_in_a_folder_that_keeps_its_pinned_icons():
    layout, metadata = owner_shaped_phone()
    _handles_now, ids, _groups = _handles(layout, metadata)
    plan = {"page_one": ids[:2], "folders": [], "app_library": {"groups": [], "apps": []},
            "delete": [], "unplaced": "folders", "note": ""}
    ops, _report = check_plan(layout, metadata, plan)
    # The rebuild keeps "Games Archive" with its pinned icons, and its apps go back in.
    moves = {op.folder_name: op for op in ops if op.action == "move_to_folder"}
    assert {"Flow", "Books", "Games Archive"} <= set(moves)
    after = preview_operations(layout, ops)
    games = [item.folder for page in after.pages for item in page
             if item.is_folder and item.folder.display_name == "Games Archive"]
    assert len(games) == 1
    assert sorted(app.pinned for page in games[0].pages for app in page) == [False] * 3 + [True] * 10


def test_a_minimal_plan_warns_that_the_pinned_icons_stay():
    layout, metadata = owner_shaped_phone()
    handles = stylist.build_handles(layout)
    plan = representative_plans(layout, metadata)["minimal"]
    _ops, report = check_plan(layout, metadata, plan)
    warnings = stylist.plan_warnings(report, handles, stylist.context_names(layout, metadata, handles))
    kept = [w for w in warnings if w["kind"] == "fixed_kept"]
    assert len(kept) == 1 and len(kept[0]["bundle_ids"]) == 19
    assert kept[0]["message"].startswith("Kept on the home screen: ")
    assert kept[0]["message"].endswith("so the App Library cannot hold them.")


def test_analysis_operations_that_name_pinned_icons_keep_them():
    layout, _metadata = owner_shaped_phone()
    pinned = sorted(layout.pinned_ids())
    apps = [b for b in stylist.build_handles(layout).bundle_ids()]
    for operations in (
        [LayoutOperation("move_to_app_library", pinned + apps[:5])],
        [LayoutOperation("delete", pinned[:3], gratitude="Thanks.")],
        [LayoutOperation("rebuild_pages", pinned + apps)],
        [LayoutOperation("compact_to_single_page", pinned + apps[:4])],
        [LayoutOperation("move_to_app_library", apps[40:]), LayoutOperation("rebuild_pages", apps[:40])],
    ):
        check_preserved(layout, operations, rebuild_drops=True)


# --- a real backup (opt-in) ------------------------------------------------------------------


def _real_phone():
    path = os.environ.get("UNJIGGLE_REAL_BACKUP")
    if not path:
        pytest.skip("set UNJIGGLE_REAL_BACKUP to the path of an icon state backup")
    layout = parse_layout_state(json.loads(Path(path).read_text()))
    metadata_path = os.environ.get("UNJIGGLE_REAL_METADATA")
    metadata = json.loads(Path(metadata_path).read_text()) if metadata_path else {}
    return layout, metadata


@pytest.mark.parametrize("preset", PRESETS)
def test_real_backup_every_preset_keeps_everything(preset):
    layout, metadata = _real_phone()
    operations = cli._PRESET_BUILDERS[preset](layout, metadata)
    check_preserved(layout, operations, exact_apps=preset != "minimal")


@pytest.mark.parametrize("kind", PLAN_KINDS)
def test_real_backup_ai_plans_keep_everything(kind):
    layout, metadata = _real_phone()
    check_plan(layout, metadata, representative_plans(layout, metadata)[kind])


@pytest.mark.parametrize("seed", range(10))
def test_real_backup_random_ai_plans_keep_everything(seed):
    from tests.test_stylist import random_plan

    layout, metadata = _real_phone()
    plan = random_plan(random.Random(f"real-{seed}"), layout, metadata)
    ops, report = stylist.expand_plan(plan, layout, metadata, stylist.build_handles(layout))
    if not report.rejected:
        check_preserved(layout, ops)
