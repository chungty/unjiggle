"""Tests for the Swipe Tax Calculator."""

from unjiggle.models import AppItem, FolderItem, HomeScreenLayout, LayoutItem
from unjiggle.swipetax import compute_swipe_tax


def _make_app(bid, page=None, in_folder=False):
    return LayoutItem(app=AppItem(bundle_id=bid))


def _meta(name, cat="Other"):
    return {"name": name, "super_category": cat}


def test_dock_apps_have_zero_swipe_cost():
    layout = HomeScreenLayout(
        dock=[_make_app("com.example.a")],
        pages=[],
    )
    metadata = {"com.example.a": _meta("TestApp", "Social")}
    tax = compute_swipe_tax(layout, metadata)
    assert tax.total_annual_swipes == 0
    assert tax.savings == 0


def test_page1_apps_have_zero_swipe_cost():
    layout = HomeScreenLayout(
        dock=[],
        pages=[[_make_app("com.example.a")]],
    )
    metadata = {"com.example.a": _meta("TestApp", "Social")}
    tax = compute_swipe_tax(layout, metadata)
    # Page 1 = 0 swipes to reach
    assert tax.total_annual_swipes == 0


def test_deep_page_apps_have_swipe_cost():
    layout = HomeScreenLayout(
        dock=[],
        pages=[
            [],  # page 1
            [],  # page 2
            [],  # page 3
            [_make_app("com.example.deep")],  # page 4
        ],
    )
    metadata = {"com.example.deep": _meta("DeepApp", "Social")}
    tax = compute_swipe_tax(layout, metadata)
    # Page 4 = 3 swipes, should have some cost
    assert tax.total_annual_swipes > 0
    assert tax.per_app[0].swipes_to_reach == 3


def test_folder_adds_one_swipe():
    folder = FolderItem(
        display_name="Stuff",
        pages=[[AppItem(bundle_id="com.example.foldered")]],
    )
    layout = HomeScreenLayout(
        dock=[],
        pages=[[LayoutItem(folder=folder)]],
    )
    metadata = {"com.example.foldered": _meta("FolderedApp")}
    tax = compute_swipe_tax(layout, metadata)
    # Page 1 folder = 0 (page) + 1 (folder) = 1 swipe
    assert tax.per_app[0].swipes_to_reach == 1
    assert tax.per_app[0].in_folder is True


def test_optimal_is_less_than_or_equal_to_current():
    layout = HomeScreenLayout(
        dock=[],
        pages=[
            [],
            [],
            [],
            [],
            [_make_app(f"com.example.app{i}") for i in range(10)],
        ],
    )
    metadata = {f"com.example.app{i}": _meta(f"App{i}", "Social") for i in range(10)}
    tax = compute_swipe_tax(layout, metadata)
    assert tax.optimal_annual_swipes <= tax.total_annual_swipes
    assert tax.savings >= 0


def test_worst_offenders_sorted_by_waste():
    layout = HomeScreenLayout(
        dock=[],
        pages=[
            [_make_app("com.example.near")],  # page 1
            [],
            [],
            [],
            [],
            [_make_app("com.example.far")],  # page 6
        ],
    )
    metadata = {
        "com.example.near": _meta("NearApp", "Social"),
        "com.example.far": _meta("FarApp", "Social"),
    }
    tax = compute_swipe_tax(layout, metadata)
    assert len(tax.worst_offenders) >= 1
    # Far app should waste more
    assert tax.worst_offenders[0].name == "FarApp"


def test_headline_format():
    layout = HomeScreenLayout(
        dock=[],
        pages=[[], [], [], [_make_app("com.example.a")]],
    )
    metadata = {"com.example.a": _meta("App", "Social")}
    tax = compute_swipe_tax(layout, metadata)
    assert "App" in tax.headline  # top offender name appears in headline


def test_headline_no_offenders():
    """Headline falls back to generic message when no offenders exist."""
    layout = HomeScreenLayout(dock=[], pages=[])
    tax = compute_swipe_tax(layout, {})
    assert tax.headline == "Your layout is fairly efficient"


def test_empty_layout():
    layout = HomeScreenLayout(dock=[], pages=[])
    tax = compute_swipe_tax(layout, {})
    assert tax.total_annual_swipes == 0
    assert tax.savings == 0
    assert tax.worst_offenders == []
