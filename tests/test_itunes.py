"""Tests for iTunes Search API integration."""

from unjiggle.itunes import GENRE_MAP, _is_system_app, _system_app_name


class TestSystemAppDetection:
    def test_apple_apps_are_system(self):
        assert _is_system_app("com.apple.mobilesafari")
        assert _is_system_app("com.apple.Maps")
        assert _is_system_app("com.apple.Preferences")

    def test_third_party_not_system(self):
        assert not _is_system_app("com.spotify.client")
        assert not _is_system_app("com.google.chrome.ios")
        assert not _is_system_app("com.notion.Notion")


class TestSystemAppNames:
    def test_known_apps(self):
        assert _system_app_name("com.apple.mobilesafari") == "Safari"
        assert _system_app_name("com.apple.MobileSMS") == "Messages"
        assert _system_app_name("com.apple.Maps") == "Maps"
        assert _system_app_name("com.apple.weather") == "Weather"

    def test_unknown_apple_app_uses_bundle_suffix(self):
        name = _system_app_name("com.apple.some-new-app")
        assert name == "Some New App"


class TestGenreMap:
    def test_social_networking_maps_to_social(self):
        assert GENRE_MAP["Social Networking"] == "Social"

    def test_games_subcategories_map_to_games(self):
        assert GENRE_MAP["Action"] == "Games"
        assert GENRE_MAP["Puzzle"] == "Games"
        assert GENRE_MAP["Strategy"] == "Games"

    def test_health_fitness_maps_to_health(self):
        assert GENRE_MAP["Health & Fitness"] == "Health"

    def test_developer_tools_maps_to_productivity(self):
        assert GENRE_MAP["Developer Tools"] == "Productivity"
