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
