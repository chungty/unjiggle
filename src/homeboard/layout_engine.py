"""Layout engine: applies operations directly to the raw IconState plist dict.

This is the critical write path. Operations are applied to the raw dict
that gets written back to the device via set_icon_state(). The raw dict
is the source of truth, not the HomeScreenLayout model.
"""

from __future__ import annotations

import copy
from typing import Any

from homeboard.analyzer import LayoutOperation
from homeboard.models import HomeScreenLayout


def apply_operations(layout: HomeScreenLayout, operations: list[LayoutOperation]) -> dict:
    """Apply operations to a copy of the raw plist and return the modified raw dict.

    This is what gets written to the device.
    """
    raw = copy.deepcopy(layout.raw)

    for op in operations:
        if op.action == "move_to_app_library":
            _raw_remove_apps(raw, op.bundle_ids)
            # Add to ignored list
            ignored = raw.get("ignored", [])
            for bid in op.bundle_ids:
                if bid not in ignored:
                    ignored.append(bid)
            raw["ignored"] = ignored

        elif op.action == "move_to_page":
            if op.target_page is not None:
                # Extract apps from wherever they are
                extracted = _raw_extract_apps(raw, op.bundle_ids)
                # Add to target page
                icon_lists = raw.get("iconLists", [])
                if 0 <= op.target_page < len(icon_lists):
                    page = icon_lists[op.target_page]
                    if len(page) + len(extracted) <= 24:
                        page.extend(extracted)

        elif op.action == "create_folder":
            if op.folder_name and op.bundle_ids:
                extracted = _raw_extract_apps(raw, op.bundle_ids)
                if extracted:
                    folder_dict = {
                        "displayName": op.folder_name,
                        "iconLists": [extracted],
                        "listType": "folder",
                    }
                    # Add folder to first page (or last page with space)
                    icon_lists = raw.get("iconLists", [])
                    placed = False
                    for page in icon_lists:
                        if len(page) < 24:
                            page.append(folder_dict)
                            placed = True
                            break
                    if not placed and icon_lists:
                        icon_lists[0].append(folder_dict)

        elif op.action == "rename_folder":
            if op.old_name and op.folder_name:
                _raw_rename_folder(raw, op.old_name, op.folder_name)

        elif op.action == "move_to_folder":
            if op.folder_name and op.bundle_ids:
                extracted = _raw_extract_apps(raw, op.bundle_ids)
                if extracted:
                    _raw_add_to_folder(raw, op.folder_name, extracted)

    # Clean up empty pages
    raw["iconLists"] = [page for page in raw.get("iconLists", []) if page]

    return raw


def _raw_find_app(item: Any) -> str | None:
    """Extract bundle ID from a raw plist item."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        if "bundleIdentifier" in item:
            return item["bundleIdentifier"]
    return None


def _raw_is_folder(item: Any) -> bool:
    return isinstance(item, dict) and ("iconLists" in item or item.get("listType") == "folder")


def _raw_remove_apps(raw: dict, bundle_ids: list[str]) -> None:
    """Remove apps by bundle ID from all pages and folders in the raw plist."""
    bid_set = set(bundle_ids)

    # Remove from pages
    for page in raw.get("iconLists", []):
        to_remove = []
        for i, item in enumerate(page):
            bid = _raw_find_app(item)
            if bid and bid in bid_set:
                to_remove.append(i)
            elif _raw_is_folder(item):
                # Remove from folder's pages
                for folder_page in item.get("iconLists", []):
                    folder_page[:] = [
                        fi for fi in folder_page
                        if _raw_find_app(fi) not in bid_set
                    ]
        for i in reversed(to_remove):
            page.pop(i)

    # Remove from dock
    dock = raw.get("buttonBar", [])
    dock[:] = [
        item for item in dock
        if _raw_find_app(item) not in bid_set
    ]


def _raw_extract_apps(raw: dict, bundle_ids: list[str]) -> list:
    """Remove apps from the raw plist and return the raw items."""
    bid_set = set(bundle_ids)
    extracted = []

    # Collect the raw items before removing
    for page in raw.get("iconLists", []):
        for item in page:
            bid = _raw_find_app(item)
            if bid and bid in bid_set:
                extracted.append(item)
            elif _raw_is_folder(item):
                for folder_page in item.get("iconLists", []):
                    for fi in folder_page:
                        if _raw_find_app(fi) in bid_set:
                            extracted.append(fi)

    # Now remove them
    _raw_remove_apps(raw, bundle_ids)

    # If we didn't find some, create simple string entries
    found_bids = {_raw_find_app(e) for e in extracted if _raw_find_app(e)}
    for bid in bundle_ids:
        if bid not in found_bids:
            extracted.append(bid)  # Simple string format

    return extracted


def _raw_rename_folder(raw: dict, old_name: str, new_name: str) -> None:
    """Rename a folder in the raw plist."""
    for page in raw.get("iconLists", []):
        for item in page:
            if _raw_is_folder(item) and item.get("displayName") == old_name:
                item["displayName"] = new_name
                return


def _raw_add_to_folder(raw: dict, folder_name: str, items: list) -> None:
    """Add items to an existing folder by name."""
    for page in raw.get("iconLists", []):
        for item in page:
            if _raw_is_folder(item) and item.get("displayName") == folder_name:
                folder_pages = item.get("iconLists", [[]])
                if folder_pages:
                    folder_pages[0].extend(items)
                else:
                    item["iconLists"] = [items]
                return
