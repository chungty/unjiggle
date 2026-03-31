"""Tests for rule-based archetype assignment."""

from unjiggle.archetypes import assign_archetype


class TestArchetypes:
    def test_chaotic_layout_gets_archetype(self, chaotic_layout, sample_metadata):
        archetype, tagline = assign_archetype(chaotic_layout, sample_metadata)
        assert len(archetype) > 0
        assert len(tagline) > 0

    def test_clean_layout_gets_archetype(self, clean_layout, sample_metadata):
        archetype, tagline = assign_archetype(clean_layout, sample_metadata)
        assert len(archetype) > 0

    def test_archetype_is_not_default_for_chaotic(self, chaotic_layout, sample_metadata):
        archetype, _ = assign_archetype(chaotic_layout, sample_metadata)
        # Chaotic layout with 7 pages and many apps should get something specific
        assert archetype != "The Minimalist"

    def test_tagline_references_numbers(self, chaotic_layout, sample_metadata):
        _, tagline = assign_archetype(chaotic_layout, sample_metadata)
        # Tagline should mention specific numbers from the layout
        assert any(char.isdigit() for char in tagline)
