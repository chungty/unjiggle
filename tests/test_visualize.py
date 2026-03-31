"""Tests for HTML visualization."""

from homeboard.models import ScoreBreakdown
from homeboard.visualize import generate_report


class TestGenerateReport:
    def test_produces_valid_html(self, chaotic_layout, sample_metadata):
        score = ScoreBreakdown(40, 30, 50, 60)
        html = generate_report(chaotic_layout, sample_metadata, score)
        assert "<!DOCTYPE html>" in html
        assert "HomeBoard" in html
        assert "</html>" in html

    def test_includes_score(self, chaotic_layout, sample_metadata):
        score = ScoreBreakdown(40, 30, 50, 60)
        html = generate_report(chaotic_layout, sample_metadata, score)
        # Score value should appear in the report (as the number)
        assert str(int(score.total)) in html

    def test_includes_archetype(self, chaotic_layout, sample_metadata):
        score = ScoreBreakdown(50, 50, 50, 50)
        html = generate_report(
            chaotic_layout, sample_metadata, score,
            archetype="The Digital Hoarder",
        )
        assert "The Digital Hoarder" in html

    def test_includes_observations(self, chaotic_layout, sample_metadata):
        score = ScoreBreakdown(50, 50, 50, 50)
        html = generate_report(
            chaotic_layout, sample_metadata, score,
            observations=["You have 3 weather apps.", "Your dock has an obscure app."],
        )
        assert "3 weather apps" in html
        assert "obscure app" in html

    def test_includes_personality(self, chaotic_layout, sample_metadata):
        score = ScoreBreakdown(50, 50, 50, 50)
        html = generate_report(
            chaotic_layout, sample_metadata, score,
            personality="An iPhone user since the early days.",
        )
        assert "early days" in html

    def test_includes_category_colors(self, chaotic_layout, sample_metadata):
        score = ScoreBreakdown(50, 50, 50, 50)
        html = generate_report(chaotic_layout, sample_metadata, score)
        assert "#3B82F6" in html or "#22C55E" in html  # Social blue or Productivity green

    def test_includes_app_count(self, chaotic_layout, sample_metadata):
        score = ScoreBreakdown(50, 50, 50, 50)
        html = generate_report(chaotic_layout, sample_metadata, score)
        assert str(chaotic_layout.total_apps) in html

    def test_empty_layout(self, sample_metadata):
        from homeboard.models import HomeScreenLayout
        layout = HomeScreenLayout()
        score = ScoreBreakdown(0, 0, 0, 0)
        html = generate_report(layout, sample_metadata, score)
        assert "<!DOCTYPE html>" in html
        assert "0" in html  # 0 apps
