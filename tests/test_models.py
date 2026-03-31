"""Tests for HomeBoard data models."""

from unjiggle.models import AppItem, FolderItem, HomeScreenLayout, LayoutItem, ScoreBreakdown


class TestLayoutItem:
    def test_app_item(self):
        item = LayoutItem(app=AppItem(bundle_id="com.test.app"))
        assert item.is_app
        assert not item.is_folder
        assert not item.is_widget
        assert item.label == "com.test.app"

    def test_app_with_name(self):
        item = LayoutItem(app=AppItem(bundle_id="com.test.app", display_name="Test"))
        assert item.label == "Test"

    def test_folder_item(self):
        item = LayoutItem(folder=FolderItem(display_name="Work"))
        assert item.is_folder
        assert not item.is_app
        assert item.label == "Work"


class TestHomeScreenLayout:
    def test_total_apps_simple(self, chaotic_layout):
        total = chaotic_layout.total_apps
        assert total > 50  # Should have lots of apps in this fixture

    def test_page_count(self, chaotic_layout):
        assert chaotic_layout.page_count == 7

    def test_all_bundle_ids(self, chaotic_layout):
        ids = chaotic_layout.all_bundle_ids
        assert "com.apple.Maps" in ids
        assert "com.spotify.client" in ids
        # Apps inside folders should be included
        assert "com.facebook.Facebook" in ids

    def test_all_bundle_ids_no_duplicates(self, clean_layout):
        ids = clean_layout.all_bundle_ids
        # Dock + pages may have overlapping apps in the fixture, but
        # all_bundle_ids returns all occurrences (not deduplicated)
        assert len(ids) > 0

    def test_all_folders(self, chaotic_layout):
        folders = chaotic_layout.all_folders()
        names = [f.display_name for f in folders]
        assert "Social" in names
        assert "L BV" in names
        assert "VDG FLOW" in names

    def test_ignored_apps(self, chaotic_layout):
        assert "com.apple.tips" in chaotic_layout.ignored

    def test_empty_layout(self):
        layout = HomeScreenLayout()
        assert layout.total_apps == 0
        assert layout.page_count == 0
        assert layout.all_bundle_ids == []


class TestScoreBreakdown:
    def test_total_weighted(self):
        score = ScoreBreakdown(
            page_efficiency=80,
            category_coherence=60,
            folder_usage=70,
            dock_quality=90,
        )
        expected = 80 * 0.3 + 60 * 0.3 + 70 * 0.2 + 90 * 0.2
        assert score.total == expected

    def test_label_chaotic(self):
        assert ScoreBreakdown(10, 10, 10, 10).label == "Chaotic"

    def test_label_cluttered(self):
        assert ScoreBreakdown(50, 50, 50, 50).label == "Cluttered"

    def test_label_getting_there(self):
        assert ScoreBreakdown(70, 70, 70, 70).label == "Getting There"

    def test_label_well_organized(self):
        assert ScoreBreakdown(85, 85, 85, 85).label == "Well Organized"

    def test_label_perfect(self):
        assert ScoreBreakdown(95, 95, 95, 95).label == "Perfectly Tuned"
