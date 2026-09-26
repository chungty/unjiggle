"""Tests for Personality Mirror context building (no LLM needed)."""

from unjiggle.mirror import _build_context
from unjiggle.models import AppItem, HomeScreenLayout, LayoutItem, ScoreBreakdown


def _app(bid):
    return LayoutItem(app=AppItem(bundle_id=bid))


def _meta(name, cat="Other"):
    return {"name": name, "super_category": cat, "description": "test", "last_updated": "?"}


def test_context_includes_app_categories():
    layout = HomeScreenLayout(
        dock=[_app("com.example.social")],
        pages=[[_app("com.example.prod")]],
    )
    metadata = {
        "com.example.social": _meta("Twitter", "Social"),
        "com.example.prod": _meta("Notion", "Productivity"),
    }
    score = ScoreBreakdown(50, 50, 50, 50)
    context = _build_context(layout, metadata, score)

    assert "SOCIAL" in context
    assert "PRODUCTIVITY" in context
    assert "Twitter" in context
    assert "Notion" in context


def test_context_includes_dock():
    layout = HomeScreenLayout(
        dock=[_app("com.example.a")],
        pages=[],
    )
    metadata = {"com.example.a": _meta("Safari", "System")}
    score = ScoreBreakdown(50, 50, 50, 50)
    context = _build_context(layout, metadata, score)

    assert "DOCK:" in context
    assert "Safari" in context


def test_context_includes_score():
    layout = HomeScreenLayout(dock=[], pages=[])
    score = ScoreBreakdown(30, 40, 50, 60)
    context = _build_context(layout, {}, score)

    assert "ORGANIZATION SCORE:" in context
    assert str(int(score.total)) in context


def test_context_lists_each_app_once_with_a_short_description_and_no_timestamps():
    from unjiggle.mirror import DESCRIPTION_CHARS

    layout = HomeScreenLayout(dock=[], pages=[[_app("com.a"), _app("com.b"), _app("com.c"), _app("com.a")]])
    metadata = {
        "com.a": {"name": "Alpha", "super_category": "Games", "last_updated": "2019-05-01T00:00:00Z",
                  "description": "A long\n\ndescription " * 10},
        "com.b": {"name": "Beta", "super_category": "System", "last_updated": None, "description": None},
        "com.c": {"name": "Gamma", "super_category": "Games", "last_updated": "2099-01-01T00:00:00Z",
                  "description": "Short."},
    }
    context = _build_context(layout, metadata, ScoreBreakdown(50, 50, 50, 50))

    assert context.count("Alpha") == 1
    alpha = next(line for line in context.splitlines() if "Alpha" in line)
    assert alpha.startswith("  Alpha | last update 2019 | A long description")
    assert len(alpha.split(" | ")[-1]) == DESCRIPTION_CHARS
    assert "\n  Gamma | Short.\n" in context
    assert "\n  Beta\n" in context
    assert "T00:00:00Z" not in context
    assert "None" not in context
