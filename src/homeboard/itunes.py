"""iTunes Search API integration for app metadata and icons."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

CACHE_DIR = Path.home() / ".homeboard" / "cache"
CACHE_FILE = CACHE_DIR / "itunes.json"
LOOKUP_URL = "https://itunes.apple.com/lookup"

# Super-categories mapped from App Store genres
GENRE_MAP = {
    "Social Networking": "Social",
    "Photo & Video": "Social",
    "Entertainment": "Entertainment",
    "Music": "Entertainment",
    "Games": "Games",
    "Action": "Games",
    "Adventure": "Games",
    "Arcade": "Games",
    "Board": "Games",
    "Card": "Games",
    "Casino": "Games",
    "Casual": "Games",
    "Family": "Games",
    "Puzzle": "Games",
    "Racing": "Games",
    "Role Playing": "Games",
    "Simulation": "Games",
    "Sports": "Games",
    "Strategy": "Games",
    "Trivia": "Games",
    "Word": "Games",
    "Productivity": "Productivity",
    "Business": "Productivity",
    "Developer Tools": "Productivity",
    "Utilities": "Utilities",
    "Health & Fitness": "Health",
    "Medical": "Health",
    "Finance": "Finance",
    "Shopping": "Shopping",
    "Food & Drink": "Shopping",
    "News": "News",
    "Magazines & Newspapers": "News",
    "Reference": "News",
    "Education": "Education",
    "Books": "Education",
    "Travel": "Travel",
    "Navigation": "Travel",
    "Weather": "Utilities",
    "Lifestyle": "Other",
    "Stickers": "Other",
    "Graphics & Design": "Productivity",
}

# Category colors for visualization (hex)
CATEGORY_COLORS = {
    "Social": "#3B82F6",       # Blue
    "Entertainment": "#8B5CF6", # Purple
    "Games": "#EF4444",        # Red
    "Productivity": "#22C55E",  # Green
    "Utilities": "#6B7280",    # Gray
    "Health": "#F97316",       # Orange
    "Finance": "#14B8A6",      # Teal
    "Shopping": "#EC4899",     # Pink
    "News": "#EAB308",         # Yellow
    "Education": "#06B6D4",    # Cyan
    "Travel": "#A855F7",       # Violet
    "Other": "#9CA3AF",        # Light gray
    "System": "#374151",       # Dark gray (Apple built-in apps)
}


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _is_system_app(bundle_id: str) -> bool:
    return bundle_id.startswith("com.apple.")


def lookup_app(bundle_id: str, cache: dict, client: httpx.Client) -> dict | None:
    """Look up a single app by bundle ID. Returns metadata dict or None."""
    if bundle_id in cache:
        return cache[bundle_id]

    if _is_system_app(bundle_id):
        # Apple system apps aren't on the iTunes Search API
        result = {
            "name": _system_app_name(bundle_id),
            "genre": "Utilities",
            "super_category": "System",
            "icon_url": None,
            "last_updated": None,
            "description": None,
        }
        cache[bundle_id] = result
        return result

    try:
        resp = client.get(LOOKUP_URL, params={"bundleId": bundle_id})
        if resp.status_code == 429:
            time.sleep(2)
            resp = client.get(LOOKUP_URL, params={"bundleId": bundle_id})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        cache[bundle_id] = None
        return None

    results = data.get("results", [])
    if not results:
        cache[bundle_id] = None
        return None

    app = results[0]
    genre = app.get("primaryGenreName", "Other")
    result = {
        "name": app.get("trackName", bundle_id.split(".")[-1]),
        "genre": genre,
        "super_category": GENRE_MAP.get(genre, "Other"),
        "icon_url": app.get("artworkUrl512") or app.get("artworkUrl100"),
        "last_updated": app.get("currentVersionReleaseDate"),
        "description": (app.get("description") or "")[:200],
    }
    cache[bundle_id] = result
    return result


def _system_app_name(bundle_id: str) -> str:
    """Guess a display name for Apple system apps."""
    known = {
        "com.apple.mobilesafari": "Safari",
        "com.apple.mobilephone": "Phone",
        "com.apple.mobilemail": "Mail",
        "com.apple.mobilenotes": "Notes",
        "com.apple.mobileipod": "Music",
        "com.apple.mobileslideshow": "Photos",
        "com.apple.camera": "Camera",
        "com.apple.Maps": "Maps",
        "com.apple.weather": "Weather",
        "com.apple.AppStore": "App Store",
        "com.apple.Preferences": "Settings",
        "com.apple.facetime": "FaceTime",
        "com.apple.MobileSMS": "Messages",
        "com.apple.Health": "Health",
        "com.apple.Fitness": "Fitness",
        "com.apple.iBooks": "Books",
        "com.apple.podcasts": "Podcasts",
        "com.apple.news": "News",
        "com.apple.stocks": "Stocks",
        "com.apple.reminders": "Reminders",
        "com.apple.calculator": "Calculator",
        "com.apple.compass": "Compass",
        "com.apple.measure": "Measure",
        "com.apple.tips": "Tips",
        "com.apple.shortcuts": "Shortcuts",
        "com.apple.Translate": "Translate",
        "com.apple.VoiceMemos": "Voice Memos",
        "com.apple.findmy": "Find My",
        "com.apple.tv": "TV",
        "com.apple.Home": "Home",
        "com.apple.Wallet": "Wallet",
        "com.apple.clips": "Clips",
        "com.apple.iMovie": "iMovie",
        "com.apple.garage-band": "GarageBand",
        "com.apple.Pages": "Pages",
        "com.apple.Numbers": "Numbers",
        "com.apple.Keynote": "Keynote",
    }
    return known.get(bundle_id, bundle_id.split(".")[-1].replace("-", " ").title())


def enrich_layout(layout, progress_callback=None) -> dict[str, dict]:
    """Look up metadata for all apps in a layout. Returns {bundle_id: metadata}."""
    cache = _load_cache()
    bundle_ids = layout.all_bundle_ids
    total = len(bundle_ids)
    metadata = {}

    with httpx.Client(timeout=10.0) as client:
        for i, bid in enumerate(bundle_ids):
            result = lookup_app(bid, cache, client)
            if result:
                metadata[bid] = result
            if progress_callback:
                progress_callback(i + 1, total)

    _save_cache(cache)
    return metadata
