"""Conservative, read-only projection for one App Library icon on an existing page.

The dict/ignored format is observed on an iOS simulator. This module does not
establish that a physical handset accepts the projected raw state.
"""

import copy
from collections import Counter

from unjiggle.analyzer import FOLDER_PAGE_SLOTS, PAGE_SLOTS
from unjiggle.device import is_folder_entry, layout_parse_integrity, parse_layout_state
from unjiggle.layout_engine import _raw_page_slots, raw_state_matches


def project_library_insertion(layout, inventory, bundle_id: str, target_page: int):
    """Return the exact projected model; raise ValueError on any uncertain input."""
    raw = layout.raw
    if not isinstance(bundle_id, str) or not bundle_id.strip():
        raise ValueError("A nonempty bundle ID is required")
    if isinstance(target_page, bool) or not isinstance(target_page, int):
        raise ValueError("The destination must be an existing page index")
    if not isinstance(raw, dict) or not all(
        isinstance(raw.get(key), list) for key in ("buttonBar", "iconLists", "ignored")
    ):
        raise ValueError("This icon-state format has no verified App Library ignored list")
    integrity = layout_parse_integrity(layout)
    if not integrity["structure_preserved"] or not raw_state_matches(layout):
        raise ValueError("The source icon state was not completely preserved")
    if len(raw["iconLists"]) != len(layout.pages):
        raise ValueError("A source page could not be mapped exactly")
    if target_page < 0 or target_page >= len(layout.pages):
        raise ValueError("The destination must be an existing page")
    if any(not isinstance(value, str) or not value for value in raw["ignored"]):
        raise ValueError("The ignored list contains an unknown entry")
    if Counter(raw["ignored"])[bundle_id] != 1:
        raise ValueError("The app must appear exactly once in the ignored list")
    if bundle_id in layout.all_bundle_ids:
        raise ValueError("The app already has a Home Screen icon")
    matches = [app for app in inventory.apps if app.bundle_id == bundle_id]
    if len(matches) != 1 or matches[0].application_type != "User" or matches[0].on_home_screen:
        raise ValueError("The app is not one unlisted, installed User app")
    if _raw_page_slots(raw["iconLists"][target_page]) >= PAGE_SLOTS:
        raise ValueError("The destination page is full")

    projected_raw = copy.deepcopy(raw)
    projected_raw["ignored"].remove(bundle_id)
    # SpringBoard omits the key after its final ignored icon is re-added. Keep
    # any remaining ignored entries and their order untouched.
    if not projected_raw["ignored"]:
        del projected_raw["ignored"]
    projected_raw["iconLists"][target_page].append(bundle_id)
    projected = parse_layout_state(projected_raw)
    if (
        not layout_parse_integrity(projected)["structure_preserved"]
        or not raw_state_matches(projected)
        or projected.all_bundle_ids.count(bundle_id) != 1
        or len(projected.pages) != len(layout.pages)
        or projected.ignored.count(bundle_id) != 0
    ):
        raise ValueError("The projected icon state did not preserve its structure")
    return projected


def project_library_insertions(layout, inventory, insertions):
    """Project an ordered sequence from one source and return each checked prefix.

    Installation inventory is deliberately kept fixed: every candidate must
    have been an unlisted User app in the original inventory. No write occurs.
    """
    if not isinstance(insertions, list) or not 1 <= len(insertions) <= 50:
        raise ValueError("Provide one to fifty insertions")
    seen = set()
    steps = []
    current = layout
    for index, insertion in enumerate(insertions, 1):
        if not isinstance(insertion, dict) or set(insertion) != {"bundle_id", "target_page"}:
            raise ValueError(f"Insertion {index} needs a bundle ID and destination page")
        bundle_id = insertion["bundle_id"]
        if not isinstance(bundle_id, str) or bundle_id in seen:
            raise ValueError(f"Insertion {index} repeats or lacks a bundle ID")
        seen.add(bundle_id)
        current = project_library_insertion(current, inventory, bundle_id, insertion["target_page"])
        steps.append(current)
    return steps


def project_library_folder_insertion(layout, inventory, bundle_id: str, folder_name: str):
    """Project one ignored User app into a uniquely named existing Home Screen folder.

    The projection is only a model of page membership. It does not establish
    whether SpringBoard will accept or display this change on a real phone.
    """
    if not isinstance(folder_name, str) or not folder_name.strip():
        raise ValueError("A nonempty existing folder name is required")
    raw = layout.raw
    if not isinstance(bundle_id, str) or not bundle_id.strip():
        raise ValueError("A nonempty bundle ID is required")
    if not isinstance(raw, dict) or not all(
        isinstance(raw.get(key), list) for key in ("buttonBar", "iconLists", "ignored")
    ):
        raise ValueError("This icon-state format has no verified App Library ignored list")
    if not layout_parse_integrity(layout)["structure_preserved"] or not raw_state_matches(layout):
        raise ValueError("The source icon state was not completely preserved")
    if len(raw["iconLists"]) != len(layout.pages):
        raise ValueError("A source page could not be mapped exactly")
    if any(not isinstance(value, str) or not value for value in raw["ignored"]):
        raise ValueError("The ignored list contains an unknown entry")
    if Counter(raw["ignored"])[bundle_id] != 1 or bundle_id in layout.all_bundle_ids:
        raise ValueError("The app must appear only in the ignored list")
    matches = [app for app in inventory.apps if app.bundle_id == bundle_id]
    if len(matches) != 1 or matches[0].application_type != "User" or matches[0].on_home_screen:
        raise ValueError("The app is not one unlisted, installed User app")

    # Names are not identifiers; duplicate names (including the dock) make
    # selection ambiguous. Keep the target within an existing Home Screen page.
    locations = [(page_index, item_index, item) for page_index, page in
                 enumerate(raw["iconLists"]) for item_index, item in enumerate(page)
                 if is_folder_entry(item) and item.get("displayName") == folder_name]
    if any(is_folder_entry(item) and item.get("displayName") == folder_name
           for item in raw["buttonBar"]):
        raise ValueError("The folder name also occurs in the dock")
    if len(locations) != 1:
        raise ValueError("The destination must be one unambiguous existing Home Screen folder")
    page_index, item_index, folder = locations[0]
    folder_pages = folder.get("iconLists")
    if not isinstance(folder_pages, list) or not folder_pages or any(
        not isinstance(page, list) or not 1 <= len(page) <= FOLDER_PAGE_SLOTS
        for page in folder_pages
    ):
        raise ValueError("The existing folder pages are incomplete or overfull")

    projected_raw = copy.deepcopy(raw)
    projected_raw["ignored"].remove(bundle_id)
    if not projected_raw["ignored"]:
        del projected_raw["ignored"]
    target_pages = projected_raw["iconLists"][page_index][item_index]["iconLists"]
    if len(target_pages[-1]) == FOLDER_PAGE_SLOTS:
        target_pages.append([])
    target_pages[-1].append(bundle_id)
    projected = parse_layout_state(projected_raw)
    if (
        not layout_parse_integrity(projected)["structure_preserved"]
        or not raw_state_matches(projected)
        or projected.all_bundle_ids.count(bundle_id) != 1
        or len(projected.pages) != len(layout.pages)
        or projected.ignored.count(bundle_id) != 0
    ):
        raise ValueError("The projected icon state did not preserve its structure")
    return projected
