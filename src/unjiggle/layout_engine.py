"""Layout engine: applies operations directly to the raw IconState plist dict.

This is the critical write path. Operations are applied to the raw dict
that gets written back to the device via set_icon_state(). The raw dict
is the source of truth, not the HomeScreenLayout model.
"""

from __future__ import annotations

import copy
from typing import Any

from unjiggle.analyzer import LayoutOperation
from unjiggle.models import HomeScreenLayout


def _get_pages(raw) -> list[list]:
    """Get the pages list from raw state, handling both formats."""
    if isinstance(raw, list):
        # iOS 26: raw[0] = dock, raw[1:] = pages
        return raw[1:] if len(raw) > 1 else []
    else:
        # Legacy dict format
        return raw.get("iconLists", [])


def _set_pages(raw, pages: list[list]) -> None:
    """Set the pages in raw state, handling both formats."""
    if isinstance(raw, list):
        # iOS 26: keep dock (raw[0]), replace pages
        dock = raw[0] if raw else []
        raw.clear()
        raw.append(dock)
        raw.extend(pages)
    else:
        raw["iconLists"] = pages


def _get_dock(raw) -> list:
    """Get the dock from raw state."""
    if isinstance(raw, list):
        return raw[0] if raw else []
    else:
        return raw.get("buttonBar", [])


def apply_operations(layout: HomeScreenLayout, operations: list[LayoutOperation]):
    """Apply operations to a copy of the raw state and return the modified state.

    This is what gets written to the device. Handles both iOS 26 (list format)
    and legacy (dict format).
    """
    raw = copy.deepcopy(layout.raw)

    for op in operations:
        if op.action in ("move_to_app_library", "delete"):
            _raw_remove_apps(raw, op.bundle_ids)
            # For dict-format raw (legacy), track ignored apps
            if isinstance(raw, dict) and op.action == "move_to_app_library":
                ignored = raw.get("ignored", [])
                for bid in op.bundle_ids:
                    if bid not in ignored:
                        ignored.append(bid)
                raw["ignored"] = ignored
            # Note: actual app deletion (uninstall) happens via a separate
            # pymobiledevice3 API call, not through IconState. The layout
            # engine just removes the icon from the home screen.

        elif op.action == "move_to_page":
            if op.target_page is not None:
                extracted = _raw_extract_apps(raw, op.bundle_ids)
                pages = _get_pages(raw)
                if 0 <= op.target_page < len(pages):
                    page = pages[op.target_page]
                    if len(page) + len(extracted) <= 24:
                        page.extend(extracted)

        elif op.action == "create_folder":
            if op.folder_name and op.bundle_ids:
                extracted = _raw_extract_apps(raw, op.bundle_ids)
                if extracted:
                    folder_dict = {
                        "displayName": op.folder_name,
                        "iconLists": [extracted],
                        "iconType": "folder",
                    }
                    pages = _get_pages(raw)
                    placed = False
                    for page in pages:
                        if len(page) < 24:
                            page.append(folder_dict)
                            placed = True
                            break
                    if not placed and pages:
                        pages[0].append(folder_dict)

        elif op.action == "rename_folder":
            if op.old_name and op.folder_name:
                _raw_rename_folder(raw, op.old_name, op.folder_name)

        elif op.action == "move_to_folder":
            if op.folder_name and op.bundle_ids:
                extracted = _raw_extract_apps(raw, op.bundle_ids)
                if extracted:
                    _raw_add_to_folder(raw, op.folder_name, extracted)

        elif op.action == "compact_to_single_page":
            extracted = _raw_extract_apps(raw, op.bundle_ids)
            _set_pages(raw, [extracted] if extracted else [])

    # Clean up empty pages
    pages = _get_pages(raw)
    cleaned = [page for page in pages if page]
    _set_pages(raw, cleaned)

    return raw


def compact_to_single_page(
    layout: HomeScreenLayout,
    keep_visible_bundle_ids: list[str],
    archive_bundle_ids: list[str],
):
    """Rebuild the home screen as a true one-page layout.

    This is the public primitive behind the one-page preset: dock apps stay in
    the dock, up to 24 kept apps stay visible on page 1, and everything else
    disappears from the home screen so the result is honestly one page.
    """
    raw = copy.deepcopy(layout.raw)

    keep_visible_bundle_ids = list(dict.fromkeys(keep_visible_bundle_ids))[:24]
    archive_bundle_ids = list(dict.fromkeys(archive_bundle_ids))

    first_page = _raw_extract_apps(raw, keep_visible_bundle_ids) if keep_visible_bundle_ids else []
    _set_pages(raw, [first_page] if first_page else [])

    if isinstance(raw, dict):
        ignored = raw.get("ignored", [])
        for bid in archive_bundle_ids:
            if bid not in ignored:
                ignored.append(bid)
        raw["ignored"] = ignored

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


def _raw_remove_apps(raw, bundle_ids: list[str]) -> None:
    """Remove apps by bundle ID from all pages, folders, and dock."""
    bid_set = set(bundle_ids)

    # Remove from all pages (including dock for list format)
    all_pages = raw if isinstance(raw, list) else ([raw.get("buttonBar", [])] + raw.get("iconLists", []))

    for page in all_pages:
        to_remove = []
        for i, item in enumerate(page):
            bid = _raw_find_app(item)
            if bid and bid in bid_set:
                to_remove.append(i)
            elif _raw_is_folder(item):
                for folder_page in item.get("iconLists", []):
                    folder_page[:] = [
                        fi for fi in folder_page
                        if _raw_find_app(fi) not in bid_set
                    ]
        for i in reversed(to_remove):
            page.pop(i)


def _raw_extract_apps(raw, bundle_ids: list[str]) -> list:
    """Remove apps from the raw state and return the raw items."""
    bid_set = set(bundle_ids)
    extracted = []

    all_pages = raw if isinstance(raw, list) else ([raw.get("buttonBar", [])] + raw.get("iconLists", []))

    for page in all_pages:
        for item in page:
            bid = _raw_find_app(item)
            if bid and bid in bid_set:
                extracted.append(item)
            elif _raw_is_folder(item):
                for folder_page in item.get("iconLists", []):
                    for fi in folder_page:
                        if _raw_find_app(fi) in bid_set:
                            extracted.append(fi)

    _raw_remove_apps(raw, bundle_ids)

    found_bids = {_raw_find_app(e) for e in extracted if _raw_find_app(e)}
    for bid in bundle_ids:
        if bid not in found_bids:
            extracted.append({"bundleIdentifier": bid, "iconType": "app"})

    return extracted


def _raw_rename_folder(raw, old_name: str, new_name: str) -> None:
    """Rename a folder in the raw state."""
    all_pages = raw if isinstance(raw, list) else raw.get("iconLists", [])
    for page in all_pages:
        for item in page:
            if _raw_is_folder(item) and item.get("displayName") == old_name:
                item["displayName"] = new_name
                return


def _raw_add_to_folder(raw, folder_name: str, items: list) -> None:
    """Add items to an existing folder by name."""
    all_pages = raw if isinstance(raw, list) else raw.get("iconLists", [])
    for page in all_pages:
        for item in page:
            if _raw_is_folder(item) and item.get("displayName") == folder_name:
                folder_pages = item.get("iconLists", [[]])
                if folder_pages:
                    folder_pages[0].extend(items)
                else:
                    item["iconLists"] = [items]
                return
