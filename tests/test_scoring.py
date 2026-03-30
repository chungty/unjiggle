"""Tests for the scoring engine."""

from tests.conftest import make_app, make_folder

from homeboard.models import HomeScreenLayout
from homeboard.scoring import compute_score


class TestPageEfficiency:
    def test_chaotic_layout_scores_low(self, chaotic_layout, sample_metadata):
        score = compute_score(chaotic_layout, sample_metadata)
        assert score.page_efficiency < 60  # 7 pages with underfilled pages

    def test_clean_layout_scores_higher_than_chaotic(self, clean_layout, chaotic_layout, sample_metadata):
        clean = compute_score(clean_layout, sample_metadata)
        chaotic = compute_score(chaotic_layout, sample_metadata)
        assert clean.page_efficiency > chaotic.page_efficiency

    def test_single_full_page(self, sample_metadata):
        layout = HomeScreenLayout(
            dock=[make_app("com.apple.mobilephone")],
            pages=[[make_app(f"com.test.app{i}") for i in range(24)]],
        )
        score = compute_score(layout, sample_metadata)
        assert score.page_efficiency >= 90

    def test_many_sparse_pages(self, sample_metadata):
        layout = HomeScreenLayout(
            dock=[],
            pages=[[make_app(f"com.test.app{i}")] for i in range(10)],
        )
        score = compute_score(layout, sample_metadata)
        assert score.page_efficiency < 30  # 10 pages with 1 app each


class TestCategoryCoherence:
    def test_chaotic_less_coherent_than_homogeneous(self, chaotic_layout, sample_metadata):
        """Chaotic layout should be less coherent than a page of all-same-category apps."""
        from tests.conftest import make_app
        from homeboard.models import HomeScreenLayout
        homogeneous = HomeScreenLayout(
            dock=[],
            pages=[[
                make_app("com.instagram.Instagram"),
                make_app("com.facebook.Facebook"),
                make_app("com.twitter.twitter"),
                make_app("com.whatsapp.WhatsApp"),
            ]],
        )
        meta = {
            "com.instagram.Instagram": {"super_category": "Social"},
            "com.facebook.Facebook": {"super_category": "Social"},
            "com.twitter.twitter": {"super_category": "Social"},
            "com.whatsapp.WhatsApp": {"super_category": "Social"},
        }
        chaotic_score = compute_score(chaotic_layout, sample_metadata)
        homo_score = compute_score(homogeneous, meta)
        assert homo_score.category_coherence > chaotic_score.category_coherence

    def test_homogeneous_page(self, sample_metadata):
        """A page with all social apps should score high."""
        layout = HomeScreenLayout(
            dock=[],
            pages=[[
                make_app("com.instagram.Instagram"),
                make_app("com.facebook.Facebook"),
                make_app("com.twitter.twitter"),
                make_app("com.whatsapp.WhatsApp"),
            ]],
        )
        # These are all Social in our metadata
        meta = {
            "com.instagram.Instagram": {"super_category": "Social"},
            "com.facebook.Facebook": {"super_category": "Social"},
            "com.twitter.twitter": {"super_category": "Social"},
            "com.whatsapp.WhatsApp": {"super_category": "Social"},
        }
        score = compute_score(layout, meta)
        assert score.category_coherence >= 80


class TestFolderUsage:
    def test_good_folders(self, sample_metadata):
        layout = HomeScreenLayout(
            dock=[],
            pages=[[
                make_folder("Social", [
                    "com.facebook.Facebook",
                    "com.twitter.twitter",
                    "com.instagram.Instagram",
                    "com.whatsapp.WhatsApp",
                    "com.reddit.Reddit",
                ]),
                make_folder("Work", [
                    "com.tinyspeck.chatlyio",
                    "com.notion.Notion",
                    "com.salesforce.chatter",
                    "com.google.calendar",
                ]),
            ]],
        )
        score = compute_score(layout, sample_metadata)
        assert score.folder_usage >= 70  # Good sized folders with clear names

    def test_bad_folders(self, sample_metadata):
        layout = HomeScreenLayout(
            dock=[],
            pages=[[
                make_folder("L BV", ["com.uber.UberClient", "com.lyft.ios"]),
                make_folder("", ["com.test.single"]),
                make_folder("VDG FLOW", ["com.trello.trello"]),
            ]],
        )
        score = compute_score(layout, sample_metadata)
        assert score.folder_usage < 50  # Cryptic names, too few items

    def test_no_folders(self, sample_metadata):
        layout = HomeScreenLayout(
            dock=[],
            pages=[[make_app(f"com.test.app{i}") for i in range(12)]],
        )
        score = compute_score(layout, sample_metadata)
        assert score.folder_usage == 40  # No folders = mild penalty


class TestDockQuality:
    def test_core_apps_in_dock(self, clean_layout, sample_metadata):
        score = compute_score(clean_layout, sample_metadata)
        assert score.dock_quality >= 80  # Phone, Messages, Safari, Mail

    def test_core_dock_scores_higher_than_mixed(self, clean_layout, chaotic_layout, sample_metadata):
        clean = compute_score(clean_layout, sample_metadata)
        chaotic = compute_score(chaotic_layout, sample_metadata)
        assert clean.dock_quality >= chaotic.dock_quality


class TestOverallScore:
    def test_chaotic_scores_lower_than_clean(self, chaotic_layout, clean_layout, sample_metadata):
        chaotic = compute_score(chaotic_layout, sample_metadata)
        clean = compute_score(clean_layout, sample_metadata)
        assert chaotic.total < clean.total

    def test_clean_scores_above_60(self, clean_layout, sample_metadata):
        score = compute_score(clean_layout, sample_metadata)
        assert score.total > 60
