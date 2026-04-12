"""Tests for the JSON API serialization helpers in cli.py.

These test the conversion functions using mock data — no device connection needed.
"""

from __future__ import annotations

import json

import pytest

from unjiggle.cli import (
    _analysis_to_json,
    _device_dict,
    _layout_signature,
    _layout_to_pages_json,
    _layout_summary_to_json,
    _mirror_to_json,
    _obituary_to_json,
    _operation_to_json,
    _score_trend,
    _swipe_tax_to_json,
    _transform_preview_payload,
    _generate_preset_transform,
)
from unjiggle.models import (
    AppItem,
    DeviceInfo,
    FolderItem,
    HomeScreenLayout,
    LayoutItem,
    ScoreBreakdown,
    WidgetItem,
    WidgetSize,
)


# -- Fixtures ----------------------------------------------------------------

@pytest.fixture
def device():
    return DeviceInfo(
        name="iPhone",
        model="iPhone18,4",
        ios_version="26.0",
        udid="FAKE-UDID-1234",
    )


@pytest.fixture
def simple_layout():
    return HomeScreenLayout(
        dock=[LayoutItem(app=AppItem(bundle_id="com.apple.mobilesafari"))],
        pages=[
            [
                LayoutItem(app=AppItem(bundle_id="com.burbn.instagram")),
                LayoutItem(app=AppItem(bundle_id="com.spotify.client")),
                LayoutItem(folder=FolderItem(
                    display_name="Social",
                    pages=[[
                        AppItem(bundle_id="com.twitter.twitter"),
                        AppItem(bundle_id="com.whatsapp.WhatsApp"),
                    ]],
                )),
                LayoutItem(widget=WidgetItem(
                    container_bundle_id="com.apple.weather",
                    grid_size=WidgetSize.MEDIUM,
                )),
            ],
        ],
    )


@pytest.fixture
def simple_metadata():
    return {
        "com.apple.mobilesafari": {"name": "Safari", "super_category": "System"},
        "com.burbn.instagram": {"name": "Instagram", "super_category": "Social"},
        "com.spotify.client": {"name": "Spotify", "super_category": "Entertainment"},
        "com.twitter.twitter": {"name": "X", "super_category": "Social"},
        "com.whatsapp.WhatsApp": {"name": "WhatsApp", "super_category": "Social"},
    }


# -- Tests: _device_dict ----------------------------------------------------

class TestDeviceDict:
    def test_has_required_fields(self, device):
        result = _device_dict(device)
        assert result["name"] == "iPhone"
        assert result["model"] == "iPhone18,4"
        assert result["ios_version"] == "26.0"

    def test_does_not_expose_udid(self, device):
        result = _device_dict(device)
        assert "udid" not in result

    def test_serializable(self, device):
        result = _device_dict(device)
        text = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(text)
        assert parsed == result


# -- Tests: _layout_to_pages_json -------------------------------------------

class TestLayoutToJson:
    def test_apps_have_tagged_format(self, simple_layout, simple_metadata):
        pages = _layout_to_pages_json(simple_layout, simple_metadata)
        assert len(pages) == 1
        first_item = pages[0][0]
        assert first_item["type"] == "app"
        assert first_item["app"]["bundle_id"] == "com.burbn.instagram"
        assert first_item["app"]["display_name"] == "Instagram"
        assert first_item["app"]["category"] == "Social"

    def test_folder_tagged_format(self, simple_layout, simple_metadata):
        pages = _layout_to_pages_json(simple_layout, simple_metadata)
        folder_item = pages[0][2]
        assert folder_item["type"] == "folder"
        assert folder_item["folder"]["display_name"] == "Social"
        assert len(folder_item["folder"]["apps"]) == 1  # one folder page
        assert folder_item["folder"]["apps"][0][0]["bundle_id"] == "com.twitter.twitter"

    def test_widget_tagged_format(self, simple_layout, simple_metadata):
        pages = _layout_to_pages_json(simple_layout, simple_metadata)
        widget_item = pages[0][3]
        assert widget_item["type"] == "widget"
        assert widget_item["widget"]["container_bundle_id"] == "com.apple.weather"
        assert widget_item["widget"]["grid_size"] == "medium"

    def test_fallback_name_for_unknown_app(self, simple_layout):
        """Apps not in metadata should get a name from the bundle ID."""
        pages = _layout_to_pages_json(simple_layout, {})
        first_item = pages[0][0]
        assert first_item["app"]["display_name"] == "instagram"
        assert first_item["app"]["category"] == "Other"

    def test_round_trips_as_json(self, simple_layout, simple_metadata):
        pages = _layout_to_pages_json(simple_layout, simple_metadata)
        text = json.dumps(pages, ensure_ascii=False)
        parsed = json.loads(text)
        assert parsed == pages

    def test_empty_layout(self):
        layout = HomeScreenLayout(dock=[], pages=[])
        pages = _layout_to_pages_json(layout, {})
        assert pages == []


class TestLayoutSignature:
    def test_stable_for_identical_layouts(self, simple_layout):
        duplicate = HomeScreenLayout(
            dock=simple_layout.dock,
            pages=simple_layout.pages,
            ignored=list(simple_layout.ignored),
        )

        assert _layout_signature(simple_layout) == _layout_signature(duplicate)

    def test_changes_when_layout_changes(self, simple_layout):
        changed = HomeScreenLayout(
            dock=simple_layout.dock,
            pages=[list(simple_layout.pages[0][1:])],
            ignored=list(simple_layout.ignored),
        )

        assert _layout_signature(simple_layout) != _layout_signature(changed)


# -- Tests: _swipe_tax_to_json ----------------------------------------------

class TestSwipeTaxToJson:
    def test_structure(self):
        from unjiggle.swipetax import AppSwipeCost, SwipeTaxResult

        tax = SwipeTaxResult(
            total_annual_swipes=114835,
            optimal_annual_swipes=103406,
            savings=11429,
            worst_offenders=[
                AppSwipeCost(
                    name="TikTok",
                    bundle_id="com.zhiliaoapp.musically",
                    category="Entertainment",
                    page=4,
                    in_folder=False,
                    swipes_to_reach=3,
                    estimated_daily_opens=5.0,
                    annual_wasted_swipes=5475,
                ),
            ],
            per_app=[],
            headline="You waste 11,429 swipes per year",
        )
        result = _swipe_tax_to_json(tax)
        assert result["total_annual"] == 114835
        assert result["optimal_annual"] == 103406
        assert result["savings"] == 11429
        assert len(result["worst_offenders"]) == 1
        assert result["worst_offenders"][0]["name"] == "TikTok"
        assert result["worst_offenders"][0]["bundle_id"] == "com.zhiliaoapp.musically"

    def test_serializable(self):
        from unjiggle.swipetax import SwipeTaxResult

        tax = SwipeTaxResult(
            total_annual_swipes=0,
            optimal_annual_swipes=0,
            savings=0,
            worst_offenders=[],
            per_app=[],
            headline="No waste",
        )
        result = _swipe_tax_to_json(tax)
        text = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(text)
        assert parsed == result


# -- Tests: _mirror_to_json -------------------------------------------------

class TestMirrorToJson:
    def test_structure(self):
        from unjiggle.mirror import Contradiction, LifePhase, MirrorResult

        mirror = MirrorResult(
            roast="You have 226 apps. That is too many apps.",
            phases=[
                LifePhase(
                    name="The Fitness Phase",
                    apps=["Headspace", "Calm", "Nike Run Club"],
                    narrative="Three meditation apps and a running tracker.",
                ),
            ],
            contradictions=[
                Contradiction(
                    tension="Self-Improvement vs. Doomscrolling",
                    apps_a=["Headspace", "Calm"],
                    apps_b=["TikTok", "Instagram"],
                    roast="The duality of man.",
                ),
            ],
            guilty_pleasure="Candy Crush hiding in a folder.",
            one_line="226 apps. Your phone is a biography you didn't mean to write.",
        )
        result = _mirror_to_json(mirror)
        assert result["roast"] == mirror.roast
        assert len(result["phases"]) == 1
        assert result["phases"][0]["name"] == "The Fitness Phase"
        assert len(result["contradictions"]) == 1
        assert result["contradictions"][0]["tension"] == "Self-Improvement vs. Doomscrolling"
        assert result["guilty_pleasure"] == mirror.guilty_pleasure
        assert result["one_line"] == mirror.one_line

    def test_empty_mirror(self):
        from unjiggle.mirror import MirrorResult

        mirror = MirrorResult(
            roast="",
            phases=[],
            contradictions=[],
            guilty_pleasure="",
            one_line="",
        )
        result = _mirror_to_json(mirror)
        text = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(text)
        assert parsed["phases"] == []
        assert parsed["contradictions"] == []


# -- Tests: _obituary_to_json -----------------------------------------------

class TestObituaryToJson:
    def test_structure(self):
        from unjiggle.obituary import Obituary, ObituaryResult

        obits = ObituaryResult(
            total_dead=2,
            obituaries=[
                Obituary(
                    app_name="Dark Sky",
                    bundle_id="com.darksky.weather",
                    born="2015",
                    died="2022",
                    cause_of_death="Apple acquired it and folded it into Weather.",
                    eulogy="Born in 2015, Dark Sky brought hyperlocal forecasts. RIP.",
                    survived_by="Apple Weather",
                ),
                Obituary(
                    app_name="Clubhouse",
                    bundle_id="com.clubhouse.app",
                    born="2020",
                    died="2023",
                    cause_of_death="The hype died.",
                    eulogy="Briefly the hottest app in the world.",
                    survived_by=None,
                ),
            ],
            graveyard_summary="2 apps that didn't make it.",
        )
        result = _obituary_to_json(obits)
        assert result["total_dead"] == 2
        assert len(result["obituaries"]) == 2
        assert result["obituaries"][0]["app_name"] == "Dark Sky"
        assert result["obituaries"][0]["survived_by"] == "Apple Weather"
        assert result["obituaries"][1]["survived_by"] is None
        assert result["graveyard_summary"] == "2 apps that didn't make it."

    def test_empty_obituary(self):
        from unjiggle.obituary import ObituaryResult

        obits = ObituaryResult(
            total_dead=0,
            obituaries=[],
            graveyard_summary="No dead apps.",
        )
        result = _obituary_to_json(obits)
        assert result["total_dead"] == 0
        assert result["obituaries"] == []


# -- Tests: _analysis_to_json -----------------------------------------------

class TestAnalysisToJson:
    def test_structure(self):
        from unjiggle.analyzer import AnalysisResult, LayoutOperation, Observation

        analysis = AnalysisResult(
            observations=[
                Observation(
                    track="cleanup",
                    title="Remove dead apps",
                    narrative="You have 3 weather apps but only use one.",
                    operations=[
                        LayoutOperation(
                            action="delete",
                            bundle_ids=["com.darksky.weather"],
                            gratitude="Dark Sky served you well.",
                        ),
                        LayoutOperation(
                            action="move_to_folder",
                            bundle_ids=["com.headspace.headspace"],
                            folder_name="Wellness",
                        ),
                    ],
                ),
                Observation(
                    track="organization",
                    title="Create a Travel folder",
                    narrative="Your travel apps are scattered.",
                    operations=[
                        LayoutOperation(
                            action="create_folder",
                            bundle_ids=["com.airbnb.app", "com.uber.UberClient"],
                            folder_name="Travel",
                        ),
                    ],
                ),
            ],
            personality="You are a collector with taste.",
            archetype="The Digital Archaeologist",
        )
        result = _analysis_to_json(analysis)
        assert result["archetype"] == "The Digital Archaeologist"
        assert result["personality"] == "You are a collector with taste."
        assert len(result["observations"]) == 2

        first_obs = result["observations"][0]
        assert first_obs["track"] == "cleanup"
        assert first_obs["title"] == "Remove dead apps"
        assert len(first_obs["operations"]) == 2
        assert first_obs["operations"][0]["action"] == "delete"
        assert first_obs["operations"][0]["gratitude"] == "Dark Sky served you well."
        assert first_obs["operations"][1]["folder_name"] == "Wellness"
        assert "gratitude" not in first_obs["operations"][1]

    def test_optional_fields_omitted(self):
        from unjiggle.analyzer import AnalysisResult, LayoutOperation, Observation

        analysis = AnalysisResult(
            observations=[
                Observation(
                    track="cleanup",
                    title="Test",
                    narrative="Test narrative.",
                    operations=[
                        LayoutOperation(
                            action="move_to_app_library",
                            bundle_ids=["com.test.app"],
                        ),
                    ],
                ),
            ],
            personality="",
            archetype="The Collector",
        )
        result = _analysis_to_json(analysis)
        op = result["observations"][0]["operations"][0]
        assert "target_page" not in op
        assert "folder_name" not in op
        assert "old_name" not in op
        assert "gratitude" not in op

    def test_empty_analysis(self):
        from unjiggle.analyzer import AnalysisResult

        analysis = AnalysisResult(
            observations=[],
            personality="",
            archetype="The Collector",
        )
        result = _analysis_to_json(analysis)
        assert result["observations"] == []
        assert result["archetype"] == "The Collector"


class TestTransformHelpers:
    def test_operation_to_json_omits_empty_fields(self):
        from unjiggle.analyzer import LayoutOperation

        op = LayoutOperation(
            action="move_to_page",
            bundle_ids=["com.example.app"],
            target_page=0,
        )

        result = _operation_to_json(op)
        assert result == {
            "action": "move_to_page",
            "bundle_ids": ["com.example.app"],
            "target_page": 0,
        }

    def test_layout_summary_to_json_includes_dock_and_pages(self, simple_layout, simple_metadata):
        result = _layout_summary_to_json(simple_layout, simple_metadata)
        assert result["total_apps"] == simple_layout.total_apps
        assert result["page_count"] == simple_layout.page_count
        assert result["dock_items"] == 1
        assert result["dock"][0]["app"]["display_name"] == "Safari"
        assert result["pages"][0][0]["app"]["display_name"] == "Instagram"

    @pytest.mark.parametrize(
        ("before_score", "after_score", "expected"),
        [
            (41, 58, "improved"),
            (58, 41, "worse"),
            (41, 41, "neutral"),
        ],
    )
    def test_score_trend(self, before_score, after_score, expected):
        assert _score_trend(before_score, after_score) == expected

    def test_transform_preview_payload_carries_contract_fields(self, simple_layout, simple_metadata):
        from unjiggle.analyzer import LayoutOperation

        changes = [
            {
                "action": "move_to_page",
                "bundle_id": "com.burbn.instagram",
                "app_name": "Instagram",
                "from_page": 1,
                "to_page": 2,
            },
            {
                "action": "move_to_app_library",
                "bundle_id": "com.spotify.client",
                "app_name": "Spotify",
                "from_page": 1,
                "to_page": None,
            },
        ]
        operations = [
            LayoutOperation(
                action="move_to_page",
                bundle_ids=["com.burbn.instagram"],
                target_page=1,
            ),
            LayoutOperation(
                action="move_to_app_library",
                bundle_ids=["com.spotify.client"],
            ),
        ]

        payload = _transform_preview_payload(
            intent="focus",
            layout=simple_layout,
            metadata=simple_metadata,
            before_score=41,
            after_score=58,
            before_pages=2,
            after_pages=1,
            changes=changes,
            operations=operations,
            proposed_layout=simple_layout,
        )

        assert payload["score_delta"] == 17
        assert payload["score_trend"] == "improved"
        assert payload["score_improved"] is True
        assert payload["moved"] == 1
        assert payload["archived"] == 1
        assert payload["operations"][0]["target_page"] == 1
        assert payload["current_layout"]["page_count"] == simple_layout.page_count
        assert payload["proposed_layout"]["page_count"] == simple_layout.page_count

    def test_minimal_preset_truthfully_compacts_to_one_page(self, chaotic_layout, sample_metadata):
        from unjiggle.scoring import compute_score

        score = compute_score(chaotic_layout, sample_metadata)
        payload = _generate_preset_transform("minimal", chaotic_layout, sample_metadata, score)

        actions = [op["action"] for op in payload["operations"]]
        assert "compact_to_single_page" in actions
        assert payload["after_pages"] == 1
        assert payload["proposed_layout"]["page_count"] == 1


# -- Tests: full JSON round-trip ---------------------------------------------

class TestJsonRoundTrip:
    """Verify that all output types survive JSON serialization."""

    def test_score_serialization(self):
        score = ScoreBreakdown(
            page_efficiency=45.3,
            category_coherence=60.7,
            folder_usage=80.0,
            dock_quality=95.0,
        )
        data = {
            "total": round(score.total),
            "label": score.label,
            "page_efficiency": round(score.page_efficiency),
            "category_coherence": round(score.category_coherence),
            "folder_usage": round(score.folder_usage),
            "dock_quality": round(score.dock_quality),
        }
        text = json.dumps(data, ensure_ascii=False)
        parsed = json.loads(text)
        assert isinstance(parsed["total"], int)
        assert isinstance(parsed["label"], str)
        assert parsed["page_efficiency"] == 45

    def test_unicode_app_names(self, simple_layout):
        """Apps with non-ASCII names should serialize correctly."""
        metadata = {
            "com.burbn.instagram": {
                "name": "Instagram \u2014 Photos & Reels",
                "super_category": "Social",
            },
        }
        pages = _layout_to_pages_json(simple_layout, metadata)
        text = json.dumps(pages, ensure_ascii=False)
        assert "\u2014" in text
        parsed = json.loads(text)
        assert parsed[0][0]["app"]["display_name"] == "Instagram \u2014 Photos & Reels"

    def test_all_converters_produce_valid_json(self, simple_layout, simple_metadata, device):
        """Smoke test: every converter produces valid JSON."""
        from unjiggle.analyzer import AnalysisResult
        from unjiggle.mirror import MirrorResult
        from unjiggle.obituary import ObituaryResult
        from unjiggle.swipetax import SwipeTaxResult

        outputs = [
            _device_dict(device),
            _layout_to_pages_json(simple_layout, simple_metadata),
            _swipe_tax_to_json(SwipeTaxResult(0, 0, 0, [], [], "")),
            _mirror_to_json(MirrorResult("", [], [], "", "")),
            _obituary_to_json(ObituaryResult(0, [], "")),
            _analysis_to_json(AnalysisResult([], "", "")),
        ]
        for output in outputs:
            text = json.dumps(output, ensure_ascii=False)
            assert json.loads(text) is not None
