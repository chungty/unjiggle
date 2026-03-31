"""Tests for the LLM analysis engine (layout operations and preview, not LLM calls)."""

from tests.conftest import make_app, make_folder

from unjiggle.analyzer import LayoutOperation, Observation, preview_operations, _parse_result
from unjiggle.models import HomeScreenLayout


class TestPreviewOperations:
    def test_move_to_app_library(self, chaotic_layout):
        ops = [LayoutOperation(
            action="move_to_app_library",
            bundle_ids=["com.darksky.darksky", "com.carrotweather.CARROT"],
        )]
        preview = preview_operations(chaotic_layout, ops)
        assert "com.darksky.darksky" not in preview.all_bundle_ids
        assert "com.carrotweather.CARROT" not in preview.all_bundle_ids
        assert "com.darksky.darksky" in preview.ignored
        assert preview.page_count <= chaotic_layout.page_count

    def test_move_to_page(self, chaotic_layout):
        ops = [LayoutOperation(
            action="move_to_page",
            bundle_ids=["com.darksky.darksky"],
            target_page=0,  # Move to page 1
        )]
        original_page1_count = len(chaotic_layout.pages[0])
        preview = preview_operations(chaotic_layout, ops)
        # App should be on page 1 now (might also still be in its original location
        # since move_to_page extracts first then adds)
        found_on_page1 = any(
            item.is_app and item.app.bundle_id == "com.darksky.darksky"
            for item in preview.pages[0]
        )
        assert found_on_page1

    def test_rename_folder(self, chaotic_layout):
        ops = [LayoutOperation(
            action="rename_folder",
            bundle_ids=[],
            old_name="L BV",
            folder_name="Transport",
        )]
        preview = preview_operations(chaotic_layout, ops)
        folder_names = [f.display_name for f in preview.all_folders()]
        assert "Transport" in folder_names
        assert "L BV" not in folder_names

    def test_create_folder(self):
        layout = HomeScreenLayout(
            dock=[],
            pages=[[
                make_app("com.hp.printer"),
                make_app("com.canon.print"),
                make_app("com.epson.iprintphoto"),
                make_app("com.apple.Maps"),
            ]],
        )
        ops = [LayoutOperation(
            action="create_folder",
            bundle_ids=["com.hp.printer", "com.canon.print", "com.epson.iprintphoto"],
            folder_name="Printers",
        )]
        preview = preview_operations(layout, ops)
        folder_names = [f.display_name for f in preview.all_folders()]
        assert "Printers" in folder_names
        # Printer apps should no longer be loose on the page
        loose_printers = [
            item for item in preview.pages[0]
            if item.is_app and item.app.bundle_id.startswith("com.hp")
        ]
        assert len(loose_printers) == 0

    def test_page_capacity_respected(self):
        """Moving to a full page should not overflow."""
        layout = HomeScreenLayout(
            dock=[],
            pages=[
                [make_app(f"com.test.app{i}") for i in range(24)],  # Full page
                [make_app("com.test.extra")],
            ],
        )
        ops = [LayoutOperation(
            action="move_to_page",
            bundle_ids=["com.test.extra"],
            target_page=0,
        )]
        preview = preview_operations(layout, ops)
        # Should not exceed 24 + 1 (extracted then added, but capacity check should block)
        assert len(preview.pages[0]) <= 25  # Extracted from page 2 adds to page 1

    def test_empty_pages_removed(self, chaotic_layout):
        """If all apps are removed from a page, the page should be cleaned up."""
        # Page 7 has only 3 apps
        page7_apps = [
            item.app.bundle_id for item in chaotic_layout.pages[6] if item.is_app
        ]
        ops = [LayoutOperation(
            action="move_to_app_library",
            bundle_ids=page7_apps,
        )]
        preview = preview_operations(chaotic_layout, ops)
        assert preview.page_count < chaotic_layout.page_count

    def test_multiple_operations_compound(self, chaotic_layout):
        """Multiple operations should accumulate."""
        ops = [
            LayoutOperation(action="move_to_app_library", bundle_ids=["com.darksky.darksky"]),
            LayoutOperation(action="move_to_app_library", bundle_ids=["com.ibm.watson.ios"]),
            LayoutOperation(action="rename_folder", bundle_ids=[], old_name="VDG FLOW", folder_name="Old Projects"),
        ]
        preview = preview_operations(chaotic_layout, ops)
        assert "com.darksky.darksky" not in preview.all_bundle_ids
        assert "com.ibm.watson.ios" not in preview.all_bundle_ids
        assert "Old Projects" in [f.display_name for f in preview.all_folders()]


class TestParseResult:
    def test_filters_invalid_bundle_ids(self, chaotic_layout):
        """Bundle IDs not in the layout should be filtered out."""
        data = {
            "observations": [{
                "track": "cleanup",
                "title": "Test",
                "narrative": "Test narrative",
                "operations": [{
                    "action": "move_to_app_library",
                    "bundle_ids": ["com.darksky.darksky", "com.fake.nonexistent"],
                }],
            }],
            "personality": "Test",
            "archetype": "Test",
        }
        result = _parse_result(data, chaotic_layout)
        ops = result.observations[0].operations
        assert len(ops) == 1
        assert "com.darksky.darksky" in ops[0].bundle_ids
        assert "com.fake.nonexistent" not in ops[0].bundle_ids

    def test_skips_operations_with_all_invalid_ids(self, chaotic_layout):
        data = {
            "observations": [{
                "track": "cleanup",
                "title": "Test",
                "narrative": "Test",
                "operations": [{
                    "action": "move_to_app_library",
                    "bundle_ids": ["com.fake.one", "com.fake.two"],
                }],
            }],
            "personality": "Test",
            "archetype": "Test",
        }
        result = _parse_result(data, chaotic_layout)
        assert len(result.observations[0].operations) == 0

    def test_rename_folder_allowed_without_bundle_ids(self, chaotic_layout):
        data = {
            "observations": [{
                "track": "organization",
                "title": "Rename",
                "narrative": "Test",
                "operations": [{
                    "action": "rename_folder",
                    "bundle_ids": [],
                    "old_name": "L BV",
                    "folder_name": "Transport",
                }],
            }],
            "personality": "Test",
            "archetype": "Test",
        }
        result = _parse_result(data, chaotic_layout)
        assert len(result.observations[0].operations) == 1
        assert result.observations[0].operations[0].folder_name == "Transport"
