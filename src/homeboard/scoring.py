"""Organization scoring engine for HomeBoard."""

from __future__ import annotations

from collections import Counter

from homeboard.models import HomeScreenLayout, ScoreBreakdown


def compute_score(layout: HomeScreenLayout, metadata: dict[str, dict]) -> ScoreBreakdown:
    """Compute the organization score from a layout and app metadata."""
    return ScoreBreakdown(
        page_efficiency=_score_page_efficiency(layout),
        category_coherence=_score_category_coherence(layout, metadata),
        folder_usage=_score_folder_usage(layout),
        dock_quality=_score_dock_quality(layout, metadata),
    )


def _score_page_efficiency(layout: HomeScreenLayout) -> float:
    """Fewer pages = better. Penalize pages with <50% fill."""
    if not layout.pages:
        return 100.0

    max_per_page = 24  # 6x4 grid
    total_items = sum(len(page) for page in layout.pages)
    ideal_pages = max(1, -(-total_items // max_per_page))  # ceil division
    actual_pages = layout.page_count

    # Base score: ratio of ideal to actual pages
    if actual_pages <= ideal_pages:
        base = 100.0
    else:
        base = max(0, 100 - (actual_pages - ideal_pages) * 15)

    # Penalty for underfilled pages (< 50% capacity)
    underfilled = sum(1 for page in layout.pages if len(page) < max_per_page * 0.5)
    penalty = underfilled * 10

    return max(0, min(100, base - penalty))


def _score_category_coherence(layout: HomeScreenLayout, metadata: dict) -> float:
    """Apps on the same page should share categories."""
    if not layout.pages:
        return 100.0

    page_scores = []
    for page in layout.pages:
        categories = []
        for item in page:
            if item.is_app:
                meta = metadata.get(item.app.bundle_id, {})
                cat = meta.get("super_category") if meta else None
                if cat:
                    categories.append(cat)
            elif item.is_folder:
                # Folders are inherently organized, count as coherent
                pass

        if len(categories) < 2:
            page_scores.append(100.0)
            continue

        # Measure: what fraction of apps share the most common category?
        counter = Counter(categories)
        most_common_count = counter.most_common(1)[0][1]
        coherence = (most_common_count / len(categories)) * 100

        # Also consider: fewer unique categories = more coherent
        unique_ratio = len(counter) / len(categories)
        diversity_penalty = unique_ratio * 30

        page_scores.append(max(0, min(100, coherence + 20 - diversity_penalty)))

    return sum(page_scores) / len(page_scores) if page_scores else 50.0


def _score_folder_usage(layout: HomeScreenLayout) -> float:
    """Good folders: 4-12 related apps. Bad: 1-2 items or 20+ items. Opaque names penalized."""
    folders = layout.all_folders()
    if not folders:
        # No folders at all is mildly bad (no organization attempt)
        return 40.0

    folder_scores = []
    for folder in folders:
        total_apps = sum(len(page) for page in folder.pages)

        # Size scoring
        if total_apps == 0:
            size_score = 0
        elif total_apps <= 2:
            size_score = 20  # Too few, noise
        elif total_apps <= 12:
            size_score = 100  # Sweet spot
        elif total_apps <= 20:
            size_score = 60  # Getting large
        else:
            size_score = 30  # Junk drawer

        # Name quality: short/cryptic names are worse
        name = folder.display_name
        name_score = 100
        if len(name) <= 2:
            name_score = 20  # Cryptic
        elif len(name) <= 4 and not name.isalpha():
            name_score = 40  # Abbreviation like "L BV"
        elif name.lower() in ("new folder", "folder", "unnamed folder", ""):
            name_score = 10  # Default name

        folder_scores.append(size_score * 0.7 + name_score * 0.3)

    return sum(folder_scores) / len(folder_scores) if folder_scores else 50.0


def _score_dock_quality(layout: HomeScreenLayout, metadata: dict) -> float:
    """Dock should contain high-value apps. Penalize if it has niche/enterprise apps."""
    if not layout.dock:
        return 50.0

    # Core apps that commonly belong in the dock
    core_bundles = {
        "com.apple.mobilephone", "com.apple.MobileSMS", "com.apple.mobilesafari",
        "com.apple.mobilemail", "com.apple.mobileslideshow", "com.apple.camera",
        "com.apple.Maps", "com.apple.Music",
    }
    # High-value third-party dock apps
    high_value_categories = {"Social", "Entertainment", "Productivity"}

    score = 0
    dock_apps = 0
    for item in layout.dock:
        if item.is_app:
            dock_apps += 1
            bid = item.app.bundle_id
            if bid in core_bundles:
                score += 25
            else:
                meta = metadata.get(bid, {})
                cat = meta.get("super_category") if meta else None
                if cat in high_value_categories:
                    score += 20
                else:
                    score += 10  # Niche app in dock

    if dock_apps == 0:
        return 50.0

    return min(100, score)
