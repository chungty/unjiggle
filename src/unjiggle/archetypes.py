"""Rule-based archetype assignment. No LLM needed.

Works with just the layout + metadata. This powers the share card
for users who don't have an API key.
"""

from __future__ import annotations

from collections import Counter

from unjiggle.models import HomeScreenLayout


def assign_archetype(layout: HomeScreenLayout, metadata: dict[str, dict]) -> tuple[str, str]:
    """Assign an archetype and one-line tagline based on layout analysis.

    Returns (archetype_name, tagline).
    """
    total_apps = layout.total_apps
    page_count = layout.page_count
    folder_count = len(layout.all_folders())
    bundle_ids = layout.all_bundle_ids

    # Count categories
    cat_counter = Counter()
    for bid in bundle_ids:
        meta = metadata.get(bid, {})
        cat = meta.get("super_category", "Other") if meta else "Other"
        cat_counter[cat] += 1

    top_cat = cat_counter.most_common(1)[0][0] if cat_counter else "Other"
    unique_cats = len([c for c, n in cat_counter.items() if c not in ("System", "Other") and n > 0])
    games = cat_counter.get("Games", 0)
    productivity = cat_counter.get("Productivity", 0)
    social = cat_counter.get("Social", 0)
    health = cat_counter.get("Health", 0)

    # Detect patterns
    has_many_folders = folder_count >= 10
    has_few_folders = folder_count <= 2
    is_sprawling = page_count >= 6
    is_compact = page_count <= 3
    is_heavy = total_apps >= 150
    is_light = total_apps <= 50

    # Archetype rules (first match wins)
    if is_heavy and has_few_folders and is_sprawling:
        return ("The Digital Hoarder",
                f"{total_apps} apps across {page_count} pages with almost no folders. "
                "You collect apps like some people collect grocery bags.")

    if is_heavy and has_many_folders:
        return ("The Organized Maximalist",
                f"{total_apps} apps, but {folder_count} folders show you've tried to impose order. "
                "The effort is real, even if the entropy is winning.")

    if games >= 15:
        return ("The Closet Gamer",
                f"{games} games hiding across your pages. Your phone knows your secret.")

    if productivity >= 20 and social <= 5:
        return ("The Productivity Machine",
                f"{productivity} productivity apps and only {social} social apps. "
                "Your phone is a tool, not a distraction.")

    if social >= 15:
        return ("The Social Butterfly",
                f"{social} social and communication apps. "
                "Your phone is how you stay connected to everyone.")

    if health >= 8:
        return ("The Wellness Seeker",
                f"{health} health and fitness apps. "
                "January resolutions leave a digital trail.")

    if is_compact and is_light:
        return ("The Minimalist",
                f"Only {total_apps} apps on {page_count} pages. "
                "You know what you need and nothing more.")

    if unique_cats >= 10 and is_sprawling:
        return ("The Renaissance Phone",
                f"Apps across {unique_cats} different categories on {page_count} pages. "
                "Your phone reflects a life with range.")

    if is_heavy and is_sprawling and unique_cats >= 8:
        return ("The Digital Archaeologist",
                f"{total_apps} apps tell the story of every phase, project, and ambition. "
                "Your phone is a time capsule.")

    if has_many_folders and is_compact:
        return ("The Folder Architect",
                f"{folder_count} folders on just {page_count} pages. "
                "You file everything, and it shows.")

    if productivity >= 10 and games >= 5 and social >= 5:
        return ("The Balanced Juggler",
                "Work, play, and social life all represented. "
                "Your phone mirrors a full life.")

    # Default
    return ("The Collector",
            f"{total_apps} apps across {page_count} pages. "
            "Every app had a reason once.")
