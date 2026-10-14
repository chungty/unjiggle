"""Tests for iTunes Search API integration."""

import json

import httpx
from click.testing import CliRunner

from unjiggle.cli import main

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


def test_app_context_covers_off_home_apps_and_keeps_unmatched_unknown(monkeypatch, tmp_path):
    from unjiggle import itunes

    monkeypatch.setattr(itunes, "CACHE_FILE", tmp_path / "itunes.json")
    monkeypatch.setattr(itunes, "CACHE_DIR", tmp_path)
    seen = []

    def respond(request):
        bundle_id = request.url.params["bundleId"]
        seen.append(bundle_id)
        return httpx.Response(200, json={"results": [{
            "bundleId": "com.example.reader" if bundle_id.endswith("reader") else "wrong.app",
            "primaryGenreName": "Books", "description": "Reads articles and books",
        }]})

    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(respond)))
    result = CliRunner().invoke(main, ["json", "app-context"], input=json.dumps({
        "bundle_ids": ["com.example.reader", "com.example.unknown"],
    }))
    assert result.exit_code == 0, result.output
    apps = json.loads(result.output)["apps"]
    assert apps["com.example.reader"] == {"category": "Books", "description": "Reads articles and books"}
    assert apps["com.example.unknown"] is None
    assert seen == ["com.example.reader", "com.example.unknown"]


def test_app_context_rejects_invalid_input_before_network(monkeypatch):
    def unexpected(**kwargs):
        raise AssertionError("no network for invalid input")

    monkeypatch.setattr(httpx, "Client", unexpected)
    for payload in ({"bundle_ids": []}, {"bundle_ids": ["x", "x"]},
                    {"bundle_ids": ["x"], "other": "y"}):
        result = CliRunner().invoke(main, ["json", "app-context"], input=json.dumps(payload))
        assert result.exit_code != 0


def test_app_context_retries_old_negative_cache_and_covers_full_inventory(monkeypatch, tmp_path):
    from unjiggle import itunes

    monkeypatch.setattr(itunes, "CACHE_FILE", tmp_path / "itunes.json")
    monkeypatch.setattr(itunes, "CACHE_DIR", tmp_path)
    itunes._save_cache({"org.example.0": None})
    seen = []

    def respond(request):
        bundle_id = request.url.params["bundleId"]
        seen.append(bundle_id)
        return httpx.Response(200, json={"results": [{
            "bundleId": bundle_id, "primaryGenreName": "Books",
            "description": "Reads books",
        }]})

    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(respond)))
    ids = [f"org.example.{index}" for index in range(40)]
    result = CliRunner().invoke(main, ["json", "app-context"],
                                input=json.dumps({"bundle_ids": ids}))
    assert result.exit_code == 0, result.output
    assert set(seen) == set(ids)
    assert len(json.loads(result.output)["apps"]) == 40
    assert json.loads(result.output)["apps"]["org.example.0"]["category"] == "Books"


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
