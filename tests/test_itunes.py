"""Tests for iTunes Search API integration."""

import httpx

from unjiggle.itunes import GENRE_MAP, _is_system_app, _system_app_name, lookup_app


def _client(results, seen):
    def respond(request):
        seen.append(request.url.params["bundleId"])
        return httpx.Response(200, json={"results": results})

    return httpx.Client(transport=httpx.MockTransport(respond))


def test_lookup_uses_only_exact_bundle_id_even_if_it_is_not_first():
    seen = []
    cache = {}
    with _client([
        {"bundleId": "other.app", "trackName": "Wrong", "description": "Wrong app"},
        {"bundleId": "target.app", "trackName": "Right", "description": "Actual app"},
    ], seen) as client:
        result = lookup_app("target.app", cache, client)
        assert result["name"] == "Right"
        assert result["description"] == "Actual app"
        assert result["bundle_id"] == "target.app"
        assert lookup_app("target.app", cache, client) == result
    assert seen == ["target.app"]


def test_lookup_rejects_mismatched_results_and_unverified_old_cache():
    seen = []
    cache = {"target.app": {"name": "Unverified old lookup"}}
    with _client([{"bundleId": "other.app", "trackName": "Wrong"}], seen) as client:
        assert lookup_app("target.app", cache, client) is None
    assert seen == ["target.app"]
    assert cache["target.app"] is None


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
