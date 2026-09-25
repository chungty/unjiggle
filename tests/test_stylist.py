"""Tests for the AI Stylist plan: the compact layout, the expansion and its guarantees.

The property tests expand many random plans on several synthetic phones. For each
plan they check that the expansion never loses, duplicates or invents an app, and
that the preview, the prediction of `json apply` and the written icon state agree.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

import pytest
from click.testing import CliRunner

from unjiggle import device, stylist
from unjiggle.analyzer import preview_operations
from unjiggle.cli import _layout_signature, _preview_effective_operations
from unjiggle.cli import json as json_group
from unjiggle.layout_engine import apply_operations

GENRES = [
    "Productivity", "Social Networking", "Games", "Finance", "Travel", "Health & Fitness",
    "Photo & Video", "Business", "Sports", "Utilities", "News", "Entertainment", "Weather",
]
STALE = "2019-03-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _no_screen_time(monkeypatch):
    from unjiggle import screentime

    monkeypatch.setattr(screentime, "get_usage", lambda *args, **kwargs: {})


# --- synthetic phones ---------------------------------------------------------------


def _app(bid, fmt):
    if fmt == "legacy":
        return bid
    return {"bundleIdentifier": bid, "iconType": "app", "displayName": _label(bid)}


def _label(bid):
    return "Label " + bid.rsplit(".", 1)[-1]


def _folder(name, bids, fmt):
    apps = [_app(b, fmt) for b in bids]
    if fmt == "legacy":
        return {"displayName": name, "iconLists": [apps], "listType": "folder"}
    return {"displayName": name, "iconLists": [apps], "iconType": "folder"}


def _widget(index, size="small"):
    return {"iconType": "widget", "containerBundleIdentifier": f"com.widget.w{index}", "gridSize": size}


def _state(dock, pages, fmt, ignored=()):
    if fmt == "legacy":
        return {"buttonBar": dock, "iconLists": pages, "ignored": list(ignored)}
    return [dock, *pages]


def _metadata(bids, rng):
    metadata = {}
    for i, bid in enumerate(bids):
        if i % 31 == 5:
            continue  # not in the App Store
        if i % 4 == 0:
            metadata[bid] = {"name": f"Tool{i}", "genre": "Utilities", "super_category": "System",
                             "last_updated": None, "description": None}
            continue
        genre = rng.choice(GENRES)
        metadata[bid] = {
            "name": f"Brand{i} - {genre} helper",
            "genre": genre,
            "super_category": genre,
            "last_updated": rng.choice([STALE, "2023-07-06T18:14:08Z", "2026-09-01T00:00:00Z", None]),
            "description": f"Brand{i} does {genre.lower()} things.\n\nIt also does more.",
        }
    return metadata


def big_phone(seed: int, fmt: str = "ios26"):
    """About 220 apps on 8 pages, 14 folders, 4 widgets, a duplicate app on page 1 and
    in a folder, a dock app that is also on page 3, two folders with one name."""
    rng = random.Random(seed)
    bids = [f"com.example.app{i:03d}" for i in range(222)]
    metadata = _metadata(bids, rng)
    dock, rest = bids[:4], bids[4:]
    rng.shuffle(rest)
    folder_names = ["Social", "Work", "Games", "Money", "Travel", "Eat", "Read", "Games",
                    "work stuff", "Kids", "Photos", "Shop", "Home", "Old"]
    folders = []
    for name in folder_names:
        size = rng.randint(2, 12)
        folders.append((name, [rest.pop() for _ in range(size)]))
    items = [("app", b) for b in rest] + [("folder", n, m) for n, m in folders]
    rng.shuffle(items)
    page_one = [_widget(i) for i in range(4)] + [_app(rest[0], fmt)]
    pages = [page_one]
    page = []
    for entry in items:
        page.append(_app(entry[1], fmt) if entry[0] == "app" else _folder(entry[1], entry[2], fmt))
        if len(page) == rng.choice([24, 24, 22]):
            pages.append(page)
            page = []
    if page:
        pages.append(page)
    # Duplicates: a folder app also sits loose on page 1, and a dock app on page 3.
    pages[0].append(_app(folders[0][1][0], fmt))
    pages[2] = pages[2][:23] + [_app(dock[1], fmt)]
    state = _state([_app(b, fmt) for b in dock], pages, fmt)
    return device.parse_layout_state(state), metadata


def full_one_page_phone(fmt: str = "ios26"):
    bids = [f"com.example.one{i:02d}" for i in range(30)]
    metadata = _metadata(bids, random.Random(7))
    page = [_widget(0)] + [_app(b, fmt) for b in bids[4:24]]
    page += [_folder("A", bids[24:27], fmt), _folder("B", bids[27:30], fmt)]
    page.append(_app(bids[0], fmt))  # a dock app, also on the page
    return device.parse_layout_state(_state([_app(b, fmt) for b in bids[:4]], [page], fmt)), metadata


def sparse_phone(fmt: str = "legacy"):
    bids = [f"com.example.sp{i:02d}" for i in range(16)]
    metadata = _metadata(bids, random.Random(3))
    pages = [
        [_app(bids[2], fmt), _folder("Tools", bids[3:6], fmt)],
        [_app(bids[6], fmt)],
        [_app(b, fmt) for b in bids[7:12]] + [_folder("Solo", [bids[12]], fmt)],
        [_app(b, fmt) for b in bids[13:16]],
    ]
    dock = [_app(bids[0], fmt), _folder("Dock folder", [bids[1]], fmt)]
    return device.parse_layout_state(_state(dock, pages, fmt, ignored=["com.example.hidden"])), metadata


def widget_phone(fmt: str = "ios26"):
    """Page 1: a medium and three small widgets (20 of 24 slots) and two apps. The dock
    holds a folder named "Work", and page 2 holds another folder named "Work"."""
    bids = [f"com.example.wd{i:02d}" for i in range(70)]
    metadata = _metadata(bids, random.Random(11))
    page_one = [_widget(0, "medium"), _widget(1), _widget(2), _widget(3),
                _app(bids[2], fmt), _app(bids[3], fmt)]
    pages = [
        page_one,
        [_folder("Work", bids[4:8], fmt), _folder("Games", bids[8:12], fmt)] + [_app(b, fmt) for b in bids[12:34]],
        [_widget(4, "extraLarge")] + [_app(b, fmt) for b in bids[34:42]],
        [_app(b, fmt) for b in bids[42:70]][:24],
    ]
    dock = [_app(bids[0], fmt), _folder("Work", [bids[1]], fmt)]
    return device.parse_layout_state(_state(dock, pages, fmt)), metadata


def unparsed_raw_phone():
    """widget_phone (iOS 26) with raw entries that the parser drops: an empty raw page
    after page 1, and an entry with no bundle ID on page 2."""
    layout, metadata = widget_phone("ios26")
    raw = [list(page) for page in layout.raw]
    raw[2].append({"iconType": "custom", "displayName": "Web clip"})
    raw.insert(2, [])
    return device.parse_layout_state(raw), metadata


PHONES = {
    "big-ios26": lambda: big_phone(1, "ios26"),
    "big-legacy": lambda: big_phone(2, "legacy"),
    "big-ios26-b": lambda: big_phone(3, "ios26"),
    "full-one-page": lambda: full_one_page_phone("ios26"),
    "sparse-legacy": lambda: sparse_phone("legacy"),
    "sparse-ios26": lambda: sparse_phone("ios26"),
    "widgets-ios26": lambda: widget_phone("ios26"),
    "widgets-legacy": lambda: widget_phone("legacy"),
    "unparsed-raw-ios26": unparsed_raw_phone,
}


# --- random plans and the checks ------------------------------------------------------


def random_plan(rng: random.Random, layout, metadata) -> dict:
    handles = stylist.build_handles(layout)
    ids = list(handles.by_handle)
    groups = sorted({stylist.app_group(b, metadata) for b in handles.bundle_ids()})
    folders_now = [item.folder.display_name for page in layout.pages for item in page if item.is_folder]
    names = groups + folders_now
    names_by_bid = stylist._display_names(layout)

    def some(pool, most):
        return rng.sample(pool, min(len(pool), rng.randint(0, most)))

    junk_ids = ["a0", "a9999", "b12", "", "A3", "a2 Some name"]
    junk_names = ["Nope", '"Work"', "Games (3)", "", "social"]
    deletes = []
    for handle in some(ids, 4):
        bid = handles.by_handle[handle]
        name = stylist.short_name(bid, metadata, names_by_bid)
        deletes.append({"app": handle, "gratitude": rng.choice([
            f"{name} was there for you.", "Thanks for everything.", "",
        ])})
    return {
        "page_one": some(ids, 30) + some(junk_ids, 2),
        "folders": [
            {
                "name": rng.choice(names + ["Work", "Play", "work", "", "  Daily  "]),
                "groups": some(names, 3) + some(junk_names, 1),
                "apps": some(ids, 6) + some(junk_ids, 1),
            }
            for _ in range(rng.randint(0, 8))
        ],
        "app_library": {"groups": some(names, 2), "apps": some(ids, 8)},
        "delete": deletes,
        "unplaced": rng.choice(["stay", "stay", "folders", "app_library", "bogus"]),
    }


def check_expansion(layout, metadata, plan):
    """Expand a plan and check every guarantee. Returns (ops, report)."""
    handles = stylist.build_handles(layout)
    ops, report = stylist.expand_plan(plan, layout, metadata, handles)

    dock = stylist.dock_bundle_ids(layout)
    before = Counter(layout.all_bundle_ids)
    named = [b for op in ops for b in op.bundle_ids]
    assert not set(named) & dock, "an operation names a dock app"
    assert set(named) <= set(before), "an operation names an app that is not on the phone"
    assert len(named) == len(set(named)), "an app is in two operations"

    removed = {b for op in ops if op.action in ("delete", "move_to_app_library") for b in op.bundle_ids}
    after = preview_operations(layout, ops)
    after_count = Counter(after.all_bundle_ids)
    for bid, count in after_count.items():
        assert bid in before, f"invented {bid}"
        assert count <= max(1, before[bid]), f"duplicated {bid}"
        assert bid not in removed, f"{bid} is removed and still on the home screen"
    for bid in before:
        assert bid in after_count or bid in removed, f"lost {bid}"
    moved = set(named) - removed
    assert all(after_count[b] == 1 for b in moved), "a moved app is not on the home screen once"
    assert [i.app.bundle_id if i.is_app else i.folder.display_name for i in after.dock] == \
        [i.app.bundle_id if i.is_app else i.folder.display_name for i in layout.dock]
    # No page uses more grid slots than the phone can show. A widget uses 4, 8 or 16.
    if all(stylist.page_slots(page) <= stylist.PAGE_SLOTS for page in layout.pages):
        assert all(stylist.page_slots(page) <= stylist.PAGE_SLOTS for page in after.pages)
    # A folder page that gets apps holds at most 9 of them, as on the phone.
    foldered = {b for op in ops if op.action in ("create_folder", "move_to_folder") for b in op.bundle_ids}
    assert all(len(folder_page) <= 9 for folder in after.all_folders() for folder_page in folder.pages
               if foldered & {app.bundle_id for app in folder_page})

    # `json apply` predicts the same layout, one operation at a time.
    predicted, effective = _preview_effective_operations(layout, ops)
    assert _layout_signature(predicted) == _layout_signature(after)
    # The written icon state reads back as that same layout.
    if layout.raw:
        written = device.parse_layout_state(apply_operations(layout, effective))
        assert _layout_signature(written) == _layout_signature(predicted)
    assert stylist.expansion_problem(layout, ops) is None
    return ops, report


# Big phones take longer to check, so they get fewer seeds.
CASES = [(phone, seed) for phone in PHONES for seed in range(8 if phone.startswith("big") else 30)]


@pytest.mark.parametrize(("phone", "seed"), CASES)
def test_random_plans_never_lose_duplicate_or_invent_apps(phone, seed):
    layout, metadata = PHONES[phone]()
    plan = random_plan(random.Random(f"{phone}-{seed}"), layout, metadata)
    check_expansion(layout, metadata, plan)


def test_random_plans_on_the_chaotic_fixture(chaotic_layout, sample_metadata):
    for seed in range(25):
        plan = random_plan(random.Random(seed), chaotic_layout, sample_metadata)
        check_expansion(chaotic_layout, sample_metadata, plan)


@pytest.mark.parametrize("plan", [None, {}, [], {"unplaced": "folders"}, {"unplaced": "app_library"},
                                  {"page_one": "a1", "folders": "x", "delete": [1], "app_library": []}])
def test_malformed_plans_are_safe(plan):
    layout, metadata = big_phone(5)
    check_expansion(layout, metadata, plan)


# --- the compact layout ----------------------------------------------------------------


def test_handles_skip_dock_apps_and_follow_the_layout():
    layout, _ = full_one_page_phone()
    handles = stylist.build_handles(layout)
    assert "com.example.one00" not in handles.by_bundle_id  # in the dock and on the page
    assert handles.by_bundle_id["com.example.one04"] == "a1"
    assert handles.lookup("A1") == handles.lookup("a1 Some name") == "com.example.one04"
    assert handles.lookup("a0") is None


def test_context_is_compact_and_marks_archive_candidates():
    layout, metadata = big_phone(4)
    handles = stylist.build_handles(layout)
    candidate = handles.bundle_ids()[5]
    context = stylist.build_plan_context(layout, metadata, handles, [{"bundle_id": candidate}])

    assert context.startswith("TODAY: ")
    assert "ORGANIZATION SCORE" not in context
    # Only an app with no App Store record shows its bundle ID.
    unnamed = {b for b in layout.all_bundle_ids if b not in metadata}
    assert unnamed and set(re.findall(r"com\.example\.app\d+", context)) == unnamed
    assert "T00:00:00Z" not in context  # no timestamps
    assert "DOCK (fixed): " in context
    assert "PAGE 1 NOW: widgets use 16 of 24 slots (4 small), a1 " in context
    assert '"Work" p' in context  # current folders with their page and size
    assert context.count("archive?") == 1
    assert f"{handles.by_bundle_id[candidate]} " in context.split("archive?")[0].splitlines()[-1]
    stale = [b for b in handles.bundle_ids() if (metadata.get(b) or {}).get("last_updated") == STALE]
    assert context.count("upd 2019") == len(stale)
    # A description appears only for the archive candidate.
    assert context.count("things.") <= 1


def test_plan_messages_put_the_layout_first():
    layout_block, intent_block = stylist.plan_messages("TODAY: x", "calm")
    assert layout_block == "<layout>\nTODAY: x\n</layout>"
    assert intent_block == "<intent>\ncalm\n</intent>"


# --- expansion rules ----------------------------------------------------------------------


def _small_phone():
    """Page 1: two apps and a widget. Page 2: a folder and loose apps. Page 3: loose apps."""
    fmt = "ios26"
    pages = [
        [_widget(0), _app("com.p1.a", fmt), _app("com.p1.b", fmt)],
        [_folder("Games", ["com.g.one", "com.g.two"], fmt), _app("com.w.one", fmt),
         _app("com.w.two", fmt), _app("com.n.one", fmt), _app("com.lonely", fmt)],
        [_app("com.w.three", fmt), _app("com.old.app", fmt)],
    ]
    layout = device.parse_layout_state(_state([_app("com.dock", fmt)], pages, fmt))
    metadata = {
        "com.p1.a": {"name": "Alpha", "genre": "Utilities", "super_category": "Utilities"},
        "com.p1.b": {"name": "Beta: Daily", "genre": "Utilities", "super_category": "Utilities"},
        "com.g.one": {"name": "Gem Quest", "genre": "Games", "super_category": "Games"},
        "com.g.two": {"name": "Tile Town", "genre": "Games", "super_category": "Games"},
        "com.w.one": {"name": "Slack", "genre": "Business", "super_category": "Productivity"},
        "com.w.two": {"name": "Linear", "genre": "Business", "super_category": "Productivity"},
        "com.w.three": {"name": "Zoom", "genre": "Business", "super_category": "Productivity"},
        "com.n.one": {"name": "Daily Paper", "genre": "News", "super_category": "News"},
        "com.lonely": {"name": "Lonely", "genre": "Weather", "super_category": "Utilities"},
        "com.old.app": {"name": "Purify: Block Ads", "genre": "Utilities", "super_category": "Utilities",
                        "last_updated": STALE, "description": "Block ads."},
    }
    return layout, metadata


def _where(layout):
    """bundle ID -> 'p1' or folder name, after the preview."""
    out = {}
    for number, page in enumerate(layout.pages, start=1):
        for item in page:
            if item.is_app:
                out[item.app.bundle_id] = f"p{number}"
            elif item.is_folder:
                for folder_page in item.folder.pages:
                    for app in folder_page:
                        out[app.bundle_id] = item.folder.display_name
    return out


def test_folders_mode_keeps_every_app_on_the_home_screen():
    layout, metadata = _small_phone()
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    plan = {
        "page_one": [h("com.p1.b"), h("com.w.one")],
        "folders": [{"name": "Work", "groups": ["Business"], "apps": []}],
        "app_library": {"groups": [], "apps": []},
        "delete": [{"app": h("com.old.app"), "gratitude": "Purify kept the ads away for years."}],
        "unplaced": "folders",
    }
    ops, report = check_expansion(layout, metadata, plan)
    after = preview_operations(layout, ops)
    where = _where(after)

    assert after.page_count == 1
    assert [i.app.bundle_id for i in after.pages[0] if i.is_app] == ["com.p1.b", "com.w.one"]
    assert where["com.w.two"] == where["com.w.three"] == "Work"
    # Apps in a current folder that the plan does not name stay in that folder.
    assert where["com.g.one"] == where["com.g.two"] == "Games"
    # Loose apps that the plan does not name go into a folder for their group. Single
    # apps share one folder.
    assert where["com.p1.a"] == where["com.n.one"] == where["com.lonely"] == "Other"
    assert "com.old.app" not in where
    assert [op.action for op in ops][:2] == ["delete", "compact_to_single_page"]
    assert report.dropped_deletes == [] and report.dropped_operations == []


def test_a_folder_with_a_current_name_keeps_its_apps():
    layout, metadata = _small_phone()
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    plan = {
        "page_one": [h("com.p1.a")],
        "folders": [{"name": "games", "groups": [], "apps": [h("com.lonely")]}],
        "app_library": {"groups": [], "apps": []},
        "delete": [],
        "unplaced": "app_library",
    }
    ops, _ = check_expansion(layout, metadata, plan)
    where = _where(preview_operations(layout, ops))
    # The current folder is "Games": its apps stay, and the name keeps its spelling.
    assert where["com.g.one"] == where["com.g.two"] == where["com.lonely"] == "Games"
    archived = {b for op in ops if op.action == "move_to_app_library" for b in op.bundle_ids}
    assert archived == {"com.p1.b", "com.w.one", "com.w.two", "com.w.three", "com.n.one", "com.old.app"}


def test_a_delete_whose_gratitude_names_another_app_is_dropped():
    layout, metadata = _small_phone()
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    plan = {
        "page_one": [], "folders": [], "app_library": {"groups": [], "apps": []},
        "delete": [
            {"app": h("com.w.one"), "gratitude": "Purify kept the ads away."},  # wrong ID
            {"app": h("com.old.app"), "gratitude": "PURIFY kept the ads away."},
            {"app": h("com.p1.b"), "gratitude": "Beta got you through the day."},
        ],
        "unplaced": "stay",
    }
    ops, report = check_expansion(layout, metadata, plan)
    deleted = [op.bundle_ids[0] for op in ops if op.action == "delete"]
    assert deleted == ["com.p1.b", "com.old.app"]
    assert ops[0].gratitude == "Beta got you through the day."
    assert report.dropped_deletes == [h("com.w.one")]


def test_stay_mode_moves_only_what_the_plan_names():
    layout, metadata = _small_phone()
    plan = {
        "page_one": [], "folders": [{"name": "Work", "groups": ["Business"], "apps": []}],
        "app_library": {"groups": ["Games"], "apps": []}, "delete": [], "unplaced": "stay",
    }
    ops, _ = check_expansion(layout, metadata, plan)
    assert [(op.action, sorted(op.bundle_ids)) for op in ops] == [
        ("create_folder", ["com.w.one", "com.w.three", "com.w.two"]),
        ("move_to_app_library", ["com.g.one", "com.g.two"]),
    ]


def test_stay_mode_renames_a_folder_whose_apps_all_move_to_a_new_name():
    layout, metadata = _small_phone()
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    plan = {
        "page_one": [], "folders": [{"name": "Play", "groups": ["Games"], "apps": [h("com.lonely")]}],
        "app_library": {"groups": [], "apps": []}, "delete": [], "unplaced": "stay",
    }
    ops, _ = check_expansion(layout, metadata, plan)
    assert [(op.action, op.old_name, op.folder_name, op.bundle_ids) for op in ops] == [
        ("rename_folder", "Games", "Play", []),
        ("move_to_folder", None, "Play", ["com.lonely"]),
    ]


def test_stay_mode_page_one_makes_room_on_later_pages():
    layout, metadata = big_phone(8)
    handles = stylist.build_handles(layout)
    page_one_now = [i.app.bundle_id for i in layout.pages[0] if i.is_app]
    wanted = [b for b in handles.bundle_ids() if b not in page_one_now][:22]
    plan = {
        "page_one": [handles.by_bundle_id[b] for b in wanted],
        "folders": [], "app_library": {"groups": [], "apps": []}, "delete": [], "unplaced": "stay",
    }
    ops, report = check_expansion(layout, metadata, plan)
    after = preview_operations(layout, ops)
    first = [i.app.bundle_id for i in after.pages[0] if i.is_app]
    placed = [b for b in wanted if b in first]
    # Page 1 fills up to 24 slots: 4 small widgets use 16, and 8 apps fit. What does
    # not fit is reported.
    assert stylist.page_slots(after.pages[0]) == 24
    assert len(placed) == 8
    assert len(report.page_one_overflow) == 14
    assert not set(page_one_now) & set(first)  # the apps that were there moved on


def test_stay_mode_page_one_on_a_full_single_page_phone_changes_nothing_it_cannot_do():
    layout, metadata = full_one_page_phone()
    handles = stylist.build_handles(layout)
    folder_app = "com.example.one25"  # inside folder A
    plan = {
        "page_one": [handles.by_bundle_id[folder_app]],
        "folders": [], "app_library": {"groups": [], "apps": []}, "delete": [], "unplaced": "stay",
    }
    ops, report = check_expansion(layout, metadata, plan)
    # No later page exists, so nothing can leave page 1 and nothing can arrive.
    assert ops == []
    assert report.page_one_overflow == [handles.by_bundle_id[folder_app]]
    assert len(report.not_moved) == 20


def _genre_phone():
    """Loose apps only: 30 apps in the genre Daily, then 8 genres of 5 apps."""
    fmt = "ios26"
    genres = ["Daily"] * 30 + [g for g in GENRES[:8] for _ in range(5)]
    bids = [f"com.genre.app{i:02d}" for i in range(len(genres))]
    metadata = {b: {"name": f"App {i}", "genre": g, "super_category": g} for i, (b, g) in enumerate(zip(bids, genres))}
    pages = [[_app(b, fmt) for b in bids[i:i + 20]] for i in range(0, len(bids), 20)]
    return device.parse_layout_state(_state([_app("com.dock", fmt)], pages, fmt)), metadata


@pytest.mark.parametrize("count", [20, 30])
def test_a_new_layout_never_hides_an_app_that_the_plan_names_for_page_one(count):
    layout, metadata = _genre_phone()
    handles = stylist.build_handles(layout)
    daily = [b for b in handles.bundle_ids() if metadata[b]["genre"] == "Daily"][:count]
    plan = {
        "page_one": [handles.by_bundle_id[b] for b in daily],
        "folders": [{"name": f"{g} folder", "groups": [g], "apps": []} for g in GENRES[:8]],
        "app_library": {"groups": [], "apps": []},
        "delete": [],
        "unplaced": "app_library",
    }
    ops, report = check_expansion(layout, metadata, plan)
    after = preview_operations(layout, ops)
    archived = {b for op in ops if op.action == "move_to_app_library" for b in op.bundle_ids}
    pages = [[i.app.bundle_id if i.is_app else i.folder.display_name for i in page] for page in after.pages]

    # Every app that the plan names for page 1 stays on the home screen, in order.
    assert not archived & set(daily)
    assert [x for page in pages for x in page if x in daily] == daily
    assert pages[0][:min(count, 24)] == daily[:24]
    # The folders follow. The ones that do not fit on page 1 go to page 2.
    assert [x for page in pages for x in page if x.endswith(" folder")] == [f"{g} folder" for g in GENRES[:8]]
    assert len(pages[0]) == 24
    assert report.page_one_overflow == [handles.by_bundle_id[b] for b in daily[24:]]
    # Daily apps that the plan does not name follow the unplaced rule.
    assert archived == {b for b in handles.bundle_ids() if metadata[b]["genre"] == "Daily"} - set(daily)


def test_stay_mode_page_one_counts_widget_slots():
    for fmt in ("ios26", "legacy"):
        layout, metadata = widget_phone(fmt)
        handles = stylist.build_handles(layout)
        assert stylist.page_slots(layout.pages[0]) == 22  # medium 8 + 3 small 12 + 2 apps
        wanted = [b for b in handles.bundle_ids() if b.endswith(tuple(f"wd{i}" for i in range(50, 62)))]
        plan = {
            "page_one": [handles.by_bundle_id[b] for b in wanted],
            "folders": [], "app_library": {"groups": [], "apps": []}, "delete": [], "unplaced": "stay",
        }
        ops, report = check_expansion(layout, metadata, plan)
        after = preview_operations(layout, ops)
        first = [i.app.bundle_id for i in after.pages[0] if i.is_app]
        # 4 app slots: the 2 apps that were there move on, and 4 of the 12 arrive.
        assert stylist.page_slots(after.pages[0]) == 24
        assert first == wanted[:4]
        assert len(report.page_one_overflow) == 8


def test_stay_mode_new_folders_skip_a_page_that_its_widgets_fill():
    layout, metadata = widget_phone()
    handles = stylist.build_handles(layout)
    last = [b for b in handles.bundle_ids() if b >= "com.example.wd42"]
    plan = {
        "page_one": [],
        "folders": [{"name": f"New {i}", "groups": [], "apps": [handles.by_bundle_id[b] for b in last[2 * i:2 * i + 2]]}
                    for i in range(4)],
        "app_library": {"groups": [], "apps": []}, "delete": [], "unplaced": "stay",
    }
    ops, report = check_expansion(layout, metadata, plan)
    after = preview_operations(layout, ops)
    assert [op.action for op in ops] == ["create_folder"] * 4
    assert report.dropped_operations == []
    assert all(stylist.page_slots(page) <= 24 for page in after.pages)
    where = {i.folder.display_name: n for n, page in enumerate(after.pages) for i in page if i.is_folder}
    assert where["New 0"] == where["New 1"] == 0  # page 1 had 2 free slots
    assert where["New 2"] == where["New 3"] == 3  # pages 2 and 3 are full


def test_a_dock_folder_with_a_page_folder_name_does_not_stop_the_plan():
    for fmt in ("ios26", "legacy"):
        layout, metadata = widget_phone(fmt)
        handles = stylist.build_handles(layout)
        h = handles.by_bundle_id.__getitem__
        names = stylist._display_names(layout)
        gone = "com.example.wd40"
        plan = {
            "page_one": [],
            "folders": [{"name": "Work", "groups": [], "apps": [h("com.example.wd20"), h("com.example.wd21")]}],
            "app_library": {"groups": [], "apps": [h("com.example.wd41")]},
            "delete": [{"app": h(gone), "gratitude": f"{stylist.short_name(gone, metadata, names)} was great."}],
            "unplaced": "stay",
        }
        ops, report = check_expansion(layout, metadata, plan)
        # Two folders are named Work (one in the dock), so the plan makes a new folder
        # with the page folder's apps and the two new ones. The dock does not change.
        assert [op.action for op in ops] == ["create_folder", "delete", "move_to_app_library"]
        assert sorted(ops[0].bundle_ids) == [f"com.example.wd{i:02d}" for i in (4, 5, 6, 7, 20, 21)]
        assert report.dropped_operations == []

        rename = {**plan, "folders": [{"name": "Tools", "groups": ["Work"], "apps": []}], "delete": []}
        ops, report = check_expansion(layout, metadata, rename)
        assert [(op.action, op.folder_name) for op in ops] == [("create_folder", "Tools"), ("move_to_app_library", None)]
        assert report.dropped_operations == []


def _stay_plan(**parts):
    plan = {"page_one": [], "folders": [], "app_library": {"groups": [], "apps": []},
            "delete": [], "unplaced": "stay"}
    plan.update(parts)
    return plan


def _page_one_apps(layout):
    return [i.app.bundle_id for i in layout.pages[0] if i.is_app]


def _folder_pages(layout):
    return {i.folder.display_name: n for n, page in enumerate(layout.pages) for i in page if i.is_folder}


@pytest.mark.parametrize("fmt", ["ios26", "legacy"])
def test_stay_mode_page_one_gets_the_free_slots_before_a_new_folder(fmt):
    layout, metadata = widget_phone(fmt)
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    wanted = ["com.example.wd02", "com.example.wd03", "com.example.wd50", "com.example.wd51"]
    plan = _stay_plan(
        page_one=[h(b) for b in wanted],
        folders=[{"name": "Trips", "groups": [], "apps": [h(f"com.example.wd{i}") for i in (52, 53, 54)]}],
    )
    ops, report = check_expansion(layout, metadata, plan)
    after = preview_operations(layout, ops)
    # The widgets use 20 slots and page_one fills the other 4. The new folder goes later.
    assert _page_one_apps(after) == wanted
    assert stylist.page_slots(after.pages[0]) == 24
    assert _folder_pages(after)["Trips"] > 0
    assert report.page_one_overflow == [] and report.dropped_operations == []


def test_stay_mode_new_folder_waits_behind_page_one_apps_that_did_not_fit():
    layout, metadata = widget_phone()
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    wanted = ["com.example.wd02", "com.example.wd03"] + [f"com.example.wd{i}" for i in range(50, 55)]
    # Trips takes both loose apps of page 1, so page 1 has 4 free slots for 5 apps.
    plan = _stay_plan(
        page_one=[h(b) for b in wanted[2:]],
        folders=[{"name": "Trips", "groups": [], "apps": [h(b) for b in wanted[:2]]}],
    )
    ops, report = check_expansion(layout, metadata, plan)
    after = preview_operations(layout, ops)
    assert _page_one_apps(after) == wanted[2:6]
    assert _folder_pages(after)["Trips"] > 0
    assert report.page_one_overflow == [h(wanted[6])]


@pytest.mark.parametrize("fmt", ["ios26", "legacy"])
def test_stay_mode_rebuilds_a_folder_with_a_dock_twin_in_its_own_place(fmt):
    layout, metadata = widget_phone(fmt)
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    plan = _stay_plan(folders=[{"name": "Work", "groups": [], "apps": [h("com.example.wd20")]}])
    ops, report = check_expansion(layout, metadata, plan)
    after = preview_operations(layout, ops)
    assert [(op.action, op.folder_name, op.old_name) for op in ops] == [("create_folder", "Work", "Work")]
    # Page 1 does not change, and the Work folder stays first on page 2.
    assert [stylist._item_key(i) for i in after.pages[0]] == [stylist._item_key(i) for i in layout.pages[0]]
    assert after.pages[1][0].is_folder and after.pages[1][0].folder.display_name == "Work"
    assert sorted(a.bundle_id for p in after.pages[1][0].folder.pages for a in p) == \
        [f"com.example.wd{i:02d}" for i in (4, 5, 6, 7, 20)]
    assert report.dropped_operations == []


@pytest.mark.parametrize("kind", ["delete", "app_library"])
def test_stay_mode_removed_page_one_apps_free_their_slots_for_page_one(kind):
    layout, metadata = widget_phone()
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    names = stylist._display_names(layout)
    gone = ["com.example.wd02", "com.example.wd03"]
    wanted = [f"com.example.wd{i}" for i in range(50, 54)]
    plan = _stay_plan(page_one=[h(b) for b in wanted])
    if kind == "delete":
        plan["delete"] = [{"app": h(b), "gratitude": f"{stylist.short_name(b, metadata, names)} helped."}
                          for b in gone]
    else:
        plan["app_library"] = {"groups": [], "apps": [h(b) for b in gone]}
    ops, report = check_expansion(layout, metadata, plan)
    after = preview_operations(layout, ops)
    assert _page_one_apps(after) == wanted
    assert stylist.page_slots(after.pages[0]) == 24
    assert report.page_one_overflow == [] and report.dropped_deletes == []


def _split_phone():
    """Page 1: 22 of 24 slots. Page 2: 24 items, with the folders Social (6) and
    Pictures (3). Page 3: 10 loose apps."""
    fmt = "ios26"
    bids = [f"com.split.app{i:02d}" for i in range(44)]
    metadata = _metadata(bids, random.Random(5))
    pages = [
        [_widget(0, "medium"), _widget(1), _widget(2), _widget(3), _app(bids[1], fmt), _app(bids[2], fmt)],
        [_folder("Social", bids[3:9], fmt), _folder("Pictures", bids[9:12], fmt)]
        + [_app(b, fmt) for b in bids[12:34]],
        [_app(b, fmt) for b in bids[34:44]],
    ]
    return device.parse_layout_state(_state([_app(bids[0], fmt)], pages, fmt)), metadata


def test_splitting_current_folders_into_new_folders_keeps_every_new_folder():
    layout, metadata = _split_phone()
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    social = [f"com.split.app{i:02d}" for i in range(3, 9)]
    pictures = [f"com.split.app{i:02d}" for i in range(9, 12)]
    plan = _stay_plan(folders=[
        {"name": "Chat", "groups": [], "apps": [h(b) for b in social[:4]]},
        {"name": "Feeds", "groups": [], "apps": [h(b) for b in social[4:]]},
        {"name": "Camera", "groups": [], "apps": [h(b) for b in pictures[:2]]},
        {"name": "Art", "groups": [], "apps": [h(b) for b in pictures[2:]]},
    ])
    ops, report = check_expansion(layout, metadata, plan)
    after = preview_operations(layout, ops)
    # An emptied folder takes no slot while the operations run, so every preview
    # places each new folder on the same page, and none is dropped.
    assert [op.folder_name for op in ops] == ["Chat", "Feeds", "Camera", "Art"]
    assert report.dropped_operations == []
    assert set(_folder_pages(after)) == {"Chat", "Feeds", "Camera", "Art"}


def test_many_small_new_folders_are_all_kept():
    layout, metadata = _split_phone()
    handles = stylist.build_handles(layout)
    ids = list(handles.by_handle)
    plan = _stay_plan(folders=[{"name": f"F{i}", "groups": [], "apps": ids[2 * i:2 * i + 2]}
                               for i in range(len(ids) // 2)])
    ops, report = check_expansion(layout, metadata, plan)
    assert report.dropped_operations == []
    assert len(ops) == len(ids) // 2


def test_plan_warnings_name_the_apps_that_the_preview_leaves_out():
    layout, metadata = widget_phone()
    handles = stylist.build_handles(layout)
    h = handles.by_bundle_id.__getitem__
    wanted = [f"com.example.wd{i}" for i in range(50, 56)]
    plan = _stay_plan(
        page_one=[h(b) for b in wanted],
        delete=[{"app": h("com.example.wd40"), "gratitude": "Thanks for everything."}],
    )
    _ops, report = check_expansion(layout, metadata, plan)
    names = stylist.context_names(layout, metadata, handles)
    warnings = stylist.plan_warnings(report, handles, names)

    assert [w["kind"] for w in warnings] == ["page_one_overflow", "dropped_delete"]
    overflow, delete = warnings
    assert overflow["bundle_ids"] == wanted[4:]
    assert overflow["message"] == (
        f"No room on page 1 for {names[wanted[4]]}, {names[wanted[5]]}. They stay where they are."
    )
    assert delete["bundle_ids"] == ["com.example.wd40"]
    assert names["com.example.wd40"] in delete["message"]


def test_plan_warnings_report_a_rejected_plan_and_a_dropped_step():
    layout, metadata = widget_phone()
    handles = stylist.build_handles(layout)
    names = stylist.context_names(layout, metadata, handles)
    rejected = stylist.PlanReport(rejected="loses com.example.wd20")
    assert stylist.plan_warnings(rejected, handles, names) == [{
        "kind": "plan_rejected",
        "message": "The AI Stylist's plan did not pass the safety checks (loses com.example.wd20), "
                   "so nothing changes.",
        "bundle_ids": [],
    }]
    step = stylist.LayoutOperation("create_folder", ["com.example.wd20"], folder_name="Trips")
    dropped = stylist.PlanReport(dropped=[step, step])
    warnings = stylist.plan_warnings(dropped, handles, names)
    assert warnings == [{
        "kind": "dropped_step",
        "message": f'Left out: a new folder "Trips" with {names["com.example.wd20"]}. This step gave '
                   "a different result in the preview and on the phone.",
        "bundle_ids": ["com.example.wd20"],
    }]


def test_unknown_ids_and_names_are_reported_and_ignored():
    layout, metadata = _small_phone()
    plan = {
        "page_one": ["a999"], "folders": [{"name": "X", "groups": ["Nope"], "apps": ["zz"]}],
        "app_library": {"groups": [], "apps": []}, "delete": [], "unplaced": "stay",
    }
    ops, report = check_expansion(layout, metadata, plan)
    assert ops == []
    assert report.unknown_ids == ["a999", "zz"]
    assert report.unknown_groups == ["Nope"]


def test_a_gratitude_line_about_another_app_of_the_same_vendor_is_dropped():
    fmt = "ios26"
    raw = [[_app("com.apple.mobilephone", fmt)],
           [{"bundleIdentifier": "com.google.Maps", "iconType": "app", "displayName": "Google Maps"},
            {"bundleIdentifier": "com.google.OnHub", "iconType": "app", "displayName": "OnHub"},
            _app("com.x.y", fmt)]]
    layout = device.parse_layout_state(raw)
    metadata = {"com.google.Maps": {"name": "Google Maps - Transit & Food", "genre": "Navigation",
                                    "super_category": "Navigation"}}
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    # OnHub has no App Store record, so the layout shows its bundle ID.
    assert f"{h('com.google.OnHub')} com.google.OnHub, p1" in stylist.build_plan_context(
        layout, metadata, stylist.build_handles(layout))
    wrong = _stay_plan(delete=[{"app": h("com.google.OnHub"), "gratitude": "Google Maps got you home."}])
    ops, report = check_expansion(layout, metadata, wrong)
    assert ops == [] and report.dropped_deletes == [h("com.google.OnHub")]
    right = _stay_plan(delete=[{"app": h("com.google.OnHub"), "gratitude": "OnHub ran your Wi-Fi."}])
    ops, report = check_expansion(layout, metadata, right)
    assert [op.bundle_ids for op in ops] == [["com.google.OnHub"]]


def test_gratitude_names_leave_out_the_bundle_id():
    assert stylist.gratitude_names("com.google.OnHub", ["com.google.OnHub", "OnHub (com.google.OnHub)"]) == \
        ["OnHub"]
    assert stylist.gratitude_names("com.b.calc", ["Calculator (com.b.calc)", "Calculator"]) == ["Calculator"]
    assert stylist.gratitude_names("io.x", ["io.x"]) == ["x"]


@pytest.mark.parametrize("mode", ["stay", "folders"])
def test_a_folder_name_that_ends_in_a_count_is_kept(mode):
    fmt = "ios26"
    raw = [[_app("com.d.00", fmt)],
           [_app("com.p.01", fmt), _folder("Kids (5)", ["com.p.02", "com.p.03"], fmt), _app("com.p.04", fmt)]]
    layout = device.parse_layout_state(raw)
    h = stylist.build_handles(layout).by_bundle_id.__getitem__
    plan = _stay_plan(folders=[{"name": "Kids (5)", "groups": [], "apps": [h("com.p.04")]}], unplaced=mode)
    ops, _ = check_expansion(layout, {}, plan)
    after = preview_operations(layout, ops)
    folders = {i.folder.display_name: sorted(a.bundle_id for p in i.folder.pages for a in p)
               for page in after.pages for i in page if i.is_folder}
    assert folders["Kids (5)"] == ["com.p.02", "com.p.03", "com.p.04"]
    assert "Kids" not in folders
    # A count that the model copies from the layout is still removed: "Kids (5) (2)".
    plan["folders"][0]["name"] = '"Kids (5)" (2)'
    ops, _ = check_expansion(layout, {}, plan)
    assert "Kids (5)" in {i.folder.display_name for page in preview_operations(layout, ops).pages
                          for i in page if i.is_folder}


def test_gratitude_names_app():
    assert stylist.gratitude_names_app("1Password guarded you.", ["1Password 7"])
    assert stylist.gratitude_names_app("Match Tennis Team kept score.", ["Match Tennis Team"])
    assert not stylist.gratitude_names_app("Thanks for the ride.", ["Match Tennis Team"])
    assert not stylist.gratitude_names_app("The best app for you.", ["The App"])


def test_short_name_drops_the_app_store_subtitle():
    metadata = {
        "a": {"name": "Cal AI - Calorie Tracker"},
        "b": {"name": "Notion: Notes, Docs, Tasks"},
        "c": {"name": "Disneyland®"},
        "d": {"name": "Mercury | Banking"},
        "e": {"name": "Disneyland® Paris"},
        "f": {"name": "Chase Mobile®: Bank & Invest"},
    }
    assert [stylist.short_name(k, metadata, {}) for k in "abcdef"] == [
        "Cal AI", "Notion", "Disneyland", "Mercury", "Disneyland Paris", "Chase Mobile",
    ]
    # With no App Store record, the name is the bundle ID.
    assert stylist.short_name("com.x.layouts", {}, {}) == "com.x.layouts"


def test_plan_names_are_unique_and_show_unknown_apps_by_bundle_id():
    metadata = {
        "com.a.hunters": {"name": "Star Wars: Hunters"},
        "com.a.galaxy": {"name": "Star Wars: Galaxy of Heroes"},
        "com.b.calc": {"name": "Calculator"},
        "com.c.calc": {"name": "Calculator"},
        "com.d.notes": {"name": "Notes+ - Quick notes"},
        # The App Store cache holds only a guess for an Apple app.
        "com.apple.DocumentsApp": {"name": "Documentsapp", "super_category": "System"},
        "com.apple.NewThing": {"name": "Newthing", "super_category": "System"},
    }
    display = {"com.chillingo.cuttherope": "Cut the Rope", "com.google.OnHub": "OnHub"}
    bids = list(metadata) + ["com.chillingo.cuttherope", "com.google.OnHub", "com.webex.meeting"]
    names = stylist.plan_names(bids, metadata, display)
    assert names == {
        "com.a.hunters": "Star Wars: Hunters",
        "com.a.galaxy": "Star Wars: Galaxy of Heroes",
        "com.b.calc": "Calculator (com.b.calc)",
        "com.c.calc": "Calculator (com.c.calc)",
        "com.d.notes": "Notes+",
        "com.apple.DocumentsApp": "Files",
        "com.apple.NewThing": "com.apple.NewThing",
        "com.chillingo.cuttherope": "Cut the Rope (com.chillingo.cuttherope)",
        "com.google.OnHub": "com.google.OnHub",
        "com.webex.meeting": "com.webex.meeting",
    }
    assert len({n.casefold() for n in names.values()}) == len(names)


def test_two_apps_with_one_short_name_get_their_full_names_in_the_context():
    fmt = "ios26"
    pages = [[_app("com.disney.DLR", fmt), _app("fr.disneylandparis.iphone", fmt), _app("com.x.other", fmt)]]
    layout = device.parse_layout_state(_state([_app("com.dock", fmt)], pages, fmt))
    metadata = {
        "com.disney.DLR": {"name": "Disneyland®: Resort", "genre": "Travel", "super_category": "Travel"},
        "fr.disneylandparis.iphone": {"name": "Disneyland®: Paris", "genre": "Travel", "super_category": "Travel"},
        "com.x.other": {"name": "Other", "genre": "Travel", "super_category": "Travel"},
    }
    context = stylist.build_plan_context(layout, metadata, stylist.build_handles(layout))
    assert "a1 Disneyland: Resort, p1" in context
    assert "a2 Disneyland: Paris, p1" in context


# --- the write path -------------------------------------------------------------------------


def test_json_apply_writes_and_verifies_a_full_restyle(monkeypatch, sample_metadata):
    """A full restyle through `json apply` on an iOS 26 phone: the icon state read back
    after the write matches the prediction, and apps keep their original items."""
    from unjiggle import safety

    layout, metadata = big_phone(11, "ios26")
    handles = stylist.build_handles(layout)
    ids = list(handles.by_handle)
    plan = {
        "page_one": ids[:10],
        "folders": [{"name": "Work", "groups": ["Business", "Productivity"], "apps": []}],
        "app_library": {"groups": ["Games"], "apps": []},
        "delete": [],
        "unplaced": "folders",
    }
    ops, _ = check_expansion(layout, metadata, plan)
    payload_ops = [{k: v for k, v in stylist._operation_dict(op).items() if v not in (None, [])}
                   for op in ops]

    state = {"raw": layout.raw}
    writes = []

    def write_layout(lockdown, raw):
        writes.append(raw)
        state["raw"] = raw

    monkeypatch.setattr(device, "connect", lambda: ("LOCKDOWN", object()))
    monkeypatch.setattr(device, "read_layout", lambda lockdown: device.parse_layout_state(state["raw"]))
    monkeypatch.setattr(device, "write_layout", write_layout)
    monkeypatch.setattr(safety, "pre_write_safety_check", lambda lockdown, layout: (True, Path("/tmp/b.json")))

    result = CliRunner().invoke(json_group, ["apply"], input=json.dumps({"operations": payload_ops}))

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["changed"] is True
    written = writes[0]
    folder_items = [item for page in written[1:] for item in page if item.get("iconType") == "folder"]
    members = [app for folder in folder_items for app in folder["iconLists"][0]]
    assert members and all(app["displayName"] == _label(app["bundleIdentifier"]) for app in members)
