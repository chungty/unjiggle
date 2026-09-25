"""Tests for App Obituary dead-app identification (no LLM needed)."""

from datetime import datetime, timedelta, timezone

from unjiggle.models import AppItem, FolderItem, HomeScreenLayout, LayoutItem
from unjiggle.obituary import identify_dead_apps


def _app(bid):
    return LayoutItem(app=AppItem(bundle_id=bid))


def _days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta(name, cat="Other", last_updated=None, desc=""):
    return {
        "name": name,
        "super_category": cat,
        "last_updated": last_updated,
        "description": desc,
    }


def test_deep_page_app_is_dead():
    layout = HomeScreenLayout(
        dock=[],
        pages=[
            [], [], [], [], [],  # pages 1-5
            [_app("com.example.buried")],  # page 6
        ],
    )
    metadata = {"com.example.buried": _meta("BuriedApp", last_updated="2022-01-01T00:00:00Z")}
    dead = identify_dead_apps(layout, metadata)
    assert len(dead) >= 1
    assert dead[0]["bundle_id"] == "com.example.buried"


def test_page1_app_is_not_dead():
    layout = HomeScreenLayout(
        dock=[],
        pages=[[_app("com.example.active")]],
    )
    metadata = {"com.example.active": _meta("ActiveApp", last_updated="2025-12-01T00:00:00Z")}
    dead = identify_dead_apps(layout, metadata)
    assert len(dead) == 0


def test_stale_app_in_large_folder_is_dead():
    folder = FolderItem(
        display_name="Junk",
        pages=[[AppItem(bundle_id=f"com.example.junk{i}") for i in range(15)]],
    )
    layout = HomeScreenLayout(
        dock=[],
        pages=[
            [],
            [],
            [],
            [LayoutItem(folder=folder)],  # page 4
        ],
    )
    metadata = {
        f"com.example.junk{i}": _meta(
            f"Junk{i}", last_updated="2021-06-01T00:00:00Z",
        )
        for i in range(15)
    }
    dead = identify_dead_apps(layout, metadata)
    # All 15 should qualify: page 4 (score 2) + large folder (score 2) + stale (score 3) = 7
    assert len(dead) >= 10


def test_system_apps_are_never_dead():
    layout = HomeScreenLayout(
        dock=[],
        pages=[[], [], [], [], [], [_app("com.apple.calculator")]],
    )
    metadata = {"com.apple.calculator": _meta("Calculator", cat="System")}
    dead = identify_dead_apps(layout, metadata)
    assert len(dead) == 0


def test_limit_to_15_apps():
    layout = HomeScreenLayout(
        dock=[],
        pages=[
            [], [], [], [], [],
            [_app(f"com.example.dead{i}") for i in range(25)],
        ],
    )
    metadata = {
        f"com.example.dead{i}": _meta(f"Dead{i}", last_updated="2020-01-01T00:00:00Z")
        for i in range(25)
    }
    dead = identify_dead_apps(layout, metadata)
    assert len(dead) <= 15


def test_no_metadata_apps_are_skipped():
    layout = HomeScreenLayout(
        dock=[],
        pages=[[], [], [], [], [], [_app("com.unknown.app")]],
    )
    dead = identify_dead_apps(layout, {})
    assert len(dead) == 0


def test_active_social_app_on_late_page_not_flagged():
    """Intentional burial: Instagram on page 6, recently updated, not in a folder."""
    layout = HomeScreenLayout(
        dock=[],
        pages=[[], [], [], [], [], [_app("com.burbn.instagram")]],
    )
    metadata = {
        "com.burbn.instagram": _meta(
            "Instagram", cat="Social",
            last_updated=_days_ago(30),  # recent, relative to today
        ),
    }
    dead = identify_dead_apps(layout, metadata)
    # Score: page 6 = +3, but Social + recent + not in folder = -2 → net 1, below threshold
    assert len(dead) == 0


def test_stale_social_app_on_late_page_still_flagged():
    """Old social app in a junk drawer is genuinely dead."""
    folder = FolderItem(
        display_name="Old",
        pages=[[AppItem(bundle_id=f"com.example.x{i}") for i in range(12)]
               + [AppItem(bundle_id="com.old.social")]],
    )
    layout = HomeScreenLayout(
        dock=[],
        pages=[[], [], [], [], [LayoutItem(folder=folder)]],
    )
    metadata = {
        "com.old.social": _meta("OldApp", cat="Social", last_updated="2021-01-01T00:00:00Z"),
        **{f"com.example.x{i}": _meta(f"X{i}") for i in range(12)},
    }
    dead = identify_dead_apps(layout, metadata)
    bids = [d["bundle_id"] for d in dead]
    assert "com.old.social" in bids


def test_context_numbers_the_dead_apps_without_bundle_ids():
    from unjiggle.obituary import _build_context

    dead = [
        {"bundle_id": "com.example.a", "name": "Alpha", "category": "Games",
         "description": "Fun.\n\nMore fun.", "last_updated": "2019-01-01T00:00:00Z",
         "page": 6, "in_folder": True, "folder_name": "Old", "reasons": ["buried on page 6"]},
        {"bundle_id": "com.example.b", "name": "Beta", "category": "Travel", "description": "",
         "last_updated": None, "page": 4, "in_folder": False, "reasons": []},
    ]
    layout = HomeScreenLayout(dock=[_app("com.example.live")], pages=[[_app("com.example.a")]])
    metadata = {"com.example.live": _meta("Live", "Social")}
    context = _build_context(dead, layout, metadata)

    assert '\n1. Alpha | Games | last update 2019 | page 6, folder "Old" | buried on page 6\n   Fun. More fun.' in context
    assert "\n2. Beta | Travel | last update unknown | page 4 | none\n" in context
    assert "com.example" not in context
    assert context.endswith("ACTIVE APPS (dock + page 1) for 'survived by' references: Live [Social]")


def test_obituaries_are_matched_by_their_number():
    from unjiggle.obituary import _parse_obituaries

    dead = [{"bundle_id": "com.example.a", "name": "A"}, {"bundle_id": "com.example.b", "name": "B"}]
    result = _parse_obituaries({
        "obituaries": [
            {"app": 2, "born": "2015", "eulogy": "second", "cause_of_death": "x"},
            {"app": 3, "born": "2015", "eulogy": "out of range", "cause_of_death": "x"},
            {"app": 0, "born": "2015", "eulogy": "zero", "cause_of_death": "x"},
            {"app": True, "born": "2015", "eulogy": "not a number", "cause_of_death": "x"},
            {"app": 2, "born": "2015", "eulogy": "again", "cause_of_death": "x"},
            {"app": 1, "born": "2014", "eulogy": "first", "cause_of_death": "x"},
        ],
        "graveyard_summary": "Two.",
    }, dead)
    assert [(o.bundle_id, o.app_name, o.eulogy, o.born) for o in result.obituaries] == [
        ("com.example.b", "B", "second", "2015"), ("com.example.a", "A", "first", "2014"),
    ]
