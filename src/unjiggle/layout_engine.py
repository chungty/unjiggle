"""Layout engine: applies operations directly to the raw IconState plist dict.

This is the critical write path. Operations are applied to the raw dict
that gets written back to the device via set_icon_state(). The raw dict
is the source of truth, not the HomeScreenLayout model.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any

from unjiggle.analyzer import (
    PAGE_SLOTS,
    LayoutOperation,
    add_to_folder_pages,
    item_slots,
    place_new_folder,
)
from unjiggle.device import _parse_item, entry_app_id, is_folder_entry, is_widget_entry
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

    The preview works on the parsed layout, so this function counts pages and slots
    as the parser sees them. A raw entry that device._parse_item drops takes no slot
    and stays where it is. A raw page with no entry that the parser keeps has no page
    index, so target_page and folder placement skip it.

    The final cleanup removes only folders that have no entries left, in the dock
    and on the pages, and then empty pages. check_write() compares the result with
    the preview before anything is written.
    """
    raw = copy.deepcopy(layout.raw)
    # An app that an earlier operation took off the home screen (compact_to_single_page
    # or rebuild_pages) can come back in a later one (create_folder). It comes back as
    # the item it was in the original state, with all of its fields.
    originals = _raw_app_items(layout.raw)
    # Raw indexes of the pages that parse_layout_state drops. Until the cleanup, an
    # operation only adds pages at the end or replaces all of them, so the indexes stay
    # valid. Pages that the operations empty keep their index until the cleanup, as in
    # analyzer.apply_preview_steps.
    unparsed = {
        index for index, page in enumerate(_get_pages(raw))
        if not any(_parse_item(item) for item in page)
    }

    def parsed_pages() -> list[list]:
        return [page for index, page in enumerate(_get_pages(raw)) if index not in unparsed]

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
                snapshot = copy.deepcopy(raw)
                extracted = _raw_extract_apps(raw, op.bundle_ids, originals)
                pages = parsed_pages()
                if 0 <= op.target_page < len(pages):
                    page = pages[op.target_page]
                    # Each moved app takes one slot. A widget takes the slots of its size.
                    if _raw_page_slots(page) + len(extracted) <= PAGE_SLOTS:
                        page.extend(extracted)
                    else:
                        raw = snapshot
                else:
                    raw = snapshot

        elif op.action == "create_folder":
            if op.folder_name and op.bundle_ids:
                snapshot = copy.deepcopy(raw)
                anchor = _raw_page_folder_named(parsed_pages(), op.old_name)
                extracted = _raw_extract_apps(raw, op.bundle_ids, originals)
                if extracted:
                    folder_pages: list[list] = []
                    add_to_folder_pages(folder_pages, extracted)
                    folder_dict = {
                        "displayName": op.folder_name,
                        "iconLists": folder_pages,
                        "iconType": "folder",
                    }
                    pages = parsed_pages()
                    count = len(pages)
                    place_new_folder(pages, folder_dict, _raw_item_slots, anchor, op.target_page)
                    if len(pages) > count:
                        _set_pages(raw, _get_pages(raw) + pages[count:])
                else:
                    raw = snapshot

        elif op.action == "rename_folder":
            if op.old_name and op.folder_name:
                _raw_rename_folder(raw, op.old_name, op.folder_name)

        elif op.action == "move_to_folder":
            if op.folder_name and op.bundle_ids:
                snapshot = copy.deepcopy(raw)
                extracted = _raw_extract_apps(raw, op.bundle_ids, originals)
                if extracted:
                    added = _raw_add_to_folder(raw, op.folder_name, extracted)
                    if not added:
                        raw = snapshot
                else:
                    raw = snapshot

        elif op.action == "compact_to_single_page":
            # One page holds 24 apps. A longer list is skipped, as in the preview.
            if len(op.bundle_ids) <= PAGE_SLOTS:
                extracted = _raw_extract_apps(raw, op.bundle_ids, originals)
                _set_pages(raw, [extracted] if extracted else [])
                unparsed.clear()

        elif op.action == "rebuild_pages":
            extracted = _raw_extract_apps(raw, op.bundle_ids, originals)
            rebuilt_pages = [
                extracted[index:index + 24]
                for index in range(0, len(extracted), 24)
            ]
            _set_pages(raw, rebuilt_pages)
            unparsed.clear()

    # Clean up folders the operations emptied, then empty pages, as the preview does.
    dock = _get_dock(raw)
    dock[:] = [item for item in dock if not _raw_is_empty_folder(item)]
    pages = [
        [item for item in page if not _raw_is_empty_folder(item)]
        for page in _get_pages(raw)
    ]
    cleaned = [page for page in pages if page]
    _set_pages(raw, cleaned)

    return raw


def check_write(layout: HomeScreenLayout, operations: list[LayoutOperation]):
    """Build the state to write and check it before anything goes to the phone.

    Returns ``(raw, preview, problem)``: the raw state from apply_operations, the
    preview of the same operations (analyzer.preview_operations, all of them and then
    the cleanup), and a short problem text, or None when the state is safe to write.
    The problems:

    - The raw state does not read back as the preview.
    - The raw state lost an entry (an app, a widget or another icon) that no
      operation took off the home screen. See lost_entries().
    """
    from unjiggle.analyzer import preview_operations
    from unjiggle.device import parse_layout_state

    preview = preview_operations(layout, operations)
    raw = apply_operations(layout, operations)
    if _signature(parse_layout_state(raw)) != _signature(preview):
        return raw, preview, "the written layout would differ from the preview"
    lost = lost_entries(layout.raw, raw, operations)
    if lost:
        shown = ", ".join(lost[:4]) + (f" and {len(lost) - 4} more" if len(lost) > 4 else "")
        return raw, preview, f"the write would remove {shown}, which no operation names"
    return raw, preview, None


def _signature(layout: HomeScreenLayout) -> str:
    """The layout as the post-write check of the CLI compares it."""
    def key(item):
        if item.is_app:
            return item.app.bundle_id
        if item.is_folder:
            return {"folder": item.folder.display_name,
                    "apps": [[app.bundle_id for app in page] for page in item.folder.pages]}
        return {"widget": item.widget.container_bundle_id, "size": item.widget.grid_size.value}

    return json.dumps({
        "dock": [key(item) for item in layout.dock],
        "pages": [[key(item) for item in page] for page in layout.pages],
        "ignored": sorted(layout.ignored),
    }, sort_keys=True)


def raw_state_matches(layout: HomeScreenLayout) -> bool:
    """True when layout.raw is the icon state that the layout was parsed from. A
    layout that code builds directly has no such state, and the write path has
    nothing to check."""
    from unjiggle.device import parse_layout_state

    if not isinstance(layout.raw, (list, dict)) or not layout.raw:
        return False
    try:
        return _signature(parse_layout_state(layout.raw)) == _signature(layout)
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        return False


def _entry_key(item: Any) -> str:
    app_id = entry_app_id(item)
    if app_id:
        return f"app:{app_id}"
    if isinstance(item, dict) and item.get("displayIdentifier"):
        return f"entry:{item['displayIdentifier']}"
    return "entry:" + json.dumps(item, sort_keys=True, default=str)


def _entry_label(item: Any) -> str:
    """A name for an entry in a problem text: the app ID, or a widget's bundle ID."""
    app_id = entry_app_id(item)
    if app_id:
        return app_id
    if isinstance(item, dict):
        for key in ("bundleIdentifier", "containerBundleIdentifier", "displayName", "displayIdentifier"):
            if item.get(key):
                return str(item[key])
    return "an icon"


def _entries(containers: list[list]) -> list:
    """Each entry in these containers and in their folders. A folder is not an entry
    of its own: it is a place for other entries."""
    entries = []
    for container in containers:
        for item in container:
            if is_folder_entry(item) or _raw_is_empty_folder(item):
                for folder_page in item.get("iconLists") or []:
                    entries.extend(folder_page)
            else:
                entries.append(item)
    return entries


def _entry_keys(containers: list[list]) -> list[str]:
    return [_entry_key(entry) for entry in _entries(containers)]


def lost_entries(before, after, operations: list[LayoutOperation]) -> list[str]:
    """Entries of the raw state ``before`` that ``after`` lost, and that no operation
    took off the home screen. An empty list when nothing was lost.

    delete and move_to_app_library take the apps that they name off the home screen.
    An app that another operation names must still be there at least once (a copy in
    the dock and one on a page can become one). compact_to_single_page and
    rebuild_pages replace all pages by design, so after them only the dock is checked.
    """
    removed = {
        f"app:{bundle_id}" for op in operations
        if op.action in ("delete", "move_to_app_library") for bundle_id in op.bundle_ids
    }
    named = {f"app:{bundle_id}" for op in operations for bundle_id in op.bundle_ids}
    rebuilt = any(op.action in ("compact_to_single_page", "rebuild_pages") for op in operations)
    labels = {_entry_key(entry): _entry_label(entry) for entry in _entries(_raw_dock_and_pages(before))}
    before_all = Counter(_entry_keys(_raw_dock_and_pages(before)))
    before_dock = Counter(_entry_keys([_get_dock(before)]))
    after_all = Counter(_entry_keys(_raw_dock_and_pages(after)))
    lost = []
    for key, count in before_all.items():
        if key in removed:
            continue
        if rebuilt:
            need = 0 if key in named else before_dock.get(key, 0)
        else:
            need = 1 if key in named else count
        if after_all.get(key, 0) < need:
            lost.append(labels[key])
    return lost


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
    """The app ID of a raw entry, as the parser reads it (device.entry_app_id). None
    for a widget, a Smart Stack, a folder or an entry that is not an app."""
    return entry_app_id(item)


def _raw_is_folder(item: Any) -> bool:
    """A folder, as the parser and SpringBoard read it (device.is_folder_entry). A
    widget or an app with an empty "iconLists" key is not a folder."""
    return is_folder_entry(item)


def _raw_is_empty_folder(item: Any) -> bool:
    """A folder that the operations emptied: no entries of any kind are left in it.
    An entry that the parser does not show still keeps its folder."""
    if not isinstance(item, dict) or is_widget_entry(item) or entry_app_id(item):
        return False
    typed = item.get("listType") == "folder" or item.get("iconType") == "folder"
    untyped = "iconLists" in item and not (item.get("bundleIdentifier") or item.get("displayIdentifier"))
    if not (typed or untyped):
        return False
    return not any(item.get("iconLists") or [])


def _raw_is_widget(item: Any) -> bool:
    return is_widget_entry(item)


def _raw_item_slots(item: Any) -> int:
    """The icon slots of a raw item, as analyzer.item_slots counts the parsed item.
    An entry that the parser drops takes no slot, and neither does a folder with no apps."""
    parsed = _parse_item(item)
    return 0 if parsed is None else item_slots(parsed)


def _raw_page_slots(page: list) -> int:
    """The slots that a page uses, as analyzer.page_slots counts them."""
    return sum(_raw_item_slots(item) for item in page)


def _raw_page_folder_named(pages: list[list], name: str | None):
    """The first folder on these pages with this name and at least one app."""
    if not name:
        return None
    for page in pages:
        for item in page:
            if _raw_is_folder(item) and item.get("displayName") == name and not _raw_is_empty_folder(item):
                return item
    return None


def _raw_app_items(raw) -> dict[str, Any]:
    """Every app item in a raw state by bundle ID, from the dock, pages and folders."""
    items: dict[str, Any] = {}
    all_pages = raw if isinstance(raw, list) else ([raw.get("buttonBar", [])] + raw.get("iconLists", []))
    for page in all_pages:
        for item in page:
            if _raw_is_widget(item):
                continue
            if _raw_is_folder(item):
                for folder_page in item.get("iconLists", []):
                    for fi in folder_page:
                        fi_bid = _raw_find_app(fi)
                        if fi_bid and not _raw_is_widget(fi):
                            items.setdefault(fi_bid, fi)
                continue
            bid = _raw_find_app(item)
            if bid:
                items.setdefault(bid, item)
    return items


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


def _raw_extract_apps(raw, bundle_ids: list[str], originals: dict[str, Any] | None = None) -> list:
    """Remove apps from the raw state and return the raw items.

    An app that is no longer in the state comes back as its item in ``originals``
    when it has one, and otherwise as a minimal app item.
    """
    bid_set = set(bundle_ids)
    extracted_by_bid: dict[str, Any] = {}

    all_pages = raw if isinstance(raw, list) else ([raw.get("buttonBar", [])] + raw.get("iconLists", []))

    for page in all_pages:
        for item in page:
            bid = _raw_find_app(item)
            if bid and bid in bid_set:
                extracted_by_bid[bid] = item
            elif _raw_is_folder(item):
                for folder_page in item.get("iconLists", []):
                    for fi in folder_page:
                        fi_bid = _raw_find_app(fi)
                        if fi_bid in bid_set:
                            extracted_by_bid[fi_bid] = fi

    _raw_remove_apps(raw, bundle_ids)

    extracted = []
    for bid in bundle_ids:
        item = extracted_by_bid.get(bid)
        if item is None and originals and bid in originals:
            item = copy.deepcopy(originals[bid])
        extracted.append(item if item is not None else {"bundleIdentifier": bid, "iconType": "app"})

    return extracted


def _raw_dock_and_pages(raw) -> list[list]:
    """The dock, then the pages: the order in which the preview finds a folder by name."""
    return raw if isinstance(raw, list) else [raw.get("buttonBar", [])] + raw.get("iconLists", [])


def _raw_rename_folder(raw, old_name: str, new_name: str) -> None:
    """Rename a folder in the raw state."""
    for page in _raw_dock_and_pages(raw):
        for item in page:
            if _raw_is_folder(item) and item.get("displayName") == old_name:
                item["displayName"] = new_name
                return


def _raw_add_to_folder(raw, folder_name: str, items: list) -> bool:
    """Add items to an existing folder by name."""
    for page in _raw_dock_and_pages(raw):
        for item in page:
            if _raw_is_folder(item) and item.get("displayName") == folder_name:
                add_to_folder_pages(item.setdefault("iconLists", []), items)
                return True
    return False
