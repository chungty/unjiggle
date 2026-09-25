"""Tests for the AI Stylist plan: the compact layout, the expansion and its guarantees.

The property tests expand many random plans on several synthetic phones. For each
plan they check that the expansion never loses, duplicates or invents an app, and
that the preview, the prediction of `json apply` and the written icon state agree.
"""

from __future__ import annotations

import json
import random
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


def _widget(index):
    return {"iconType": "widget", "containerBundleIdentifier": f"com.widget.w{index}", "gridSize": "small"}


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


PHONES = {
    "big-ios26": lambda: big_phone(1, "ios26"),
    "big-legacy": lambda: big_phone(2, "legacy"),
    "big-ios26-b": lambda: big_phone(3, "ios26"),
    "full-one-page": lambda: full_one_page_phone("ios26"),
    "sparse-legacy": lambda: sparse_phone("legacy"),
    "sparse-ios26": lambda: sparse_phone("ios26"),
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
    if all(len(page) <= stylist.PAGE_SLOTS for page in layout.pages):
        assert all(len(page) <= stylist.PAGE_SLOTS for page in after.pages)

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
    assert "com.example" not in context  # no bundle IDs
    assert "T00:00:00Z" not in context  # no timestamps
    assert "DOCK (fixed): " in context
    assert "PAGE 1 NOW: 4 widgets, a1 " in context
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
                for app in item.folder.pages[0]:
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
    # Page 1 fills up to 24 items (4 widgets + 20 apps). What does not fit is reported.
    assert len(after.pages[0]) == 24
    assert len(placed) == 20
    assert len(report.page_one_overflow) == 2
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
    }
    assert [stylist.short_name(k, metadata, {}) for k in "abcd"] == ["Cal AI", "Notion", "Disneyland", "Mercury"]
    assert stylist.short_name("com.x.layouts", {}, {}) == "layouts"


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
