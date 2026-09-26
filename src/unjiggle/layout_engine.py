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
    MAX_PAGES,
    PAGE_SLOTS,
    LayoutOperation,
    add_to_folder_pages,
    first_live_index,
    folder_page_ids,
    item_slots,
    place_new_folder,
    rebuild_room,
    rebuilt_pages,
)
from unjiggle.device import (
    _parse_item,
    entry_app_id,
    is_app_store_entry,
    is_folder_entry,
    is_pinned_entry,
    is_widget_entry,
)
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

    An operation does not act on a fixed icon: a pinned icon (an entry with no
    bundleIdentifier, device.is_pinned_entry) or an app with more than one icon (see
    HomeScreenLayout.fixed_ids()). Its ID is taken out of each operation first, as in
    the preview, and an ID that an operation names twice counts once.
    compact_to_single_page and rebuild_pages keep the widgets, the fixed icons, the
    folders that hold them and the entries that the parser drops (see
    analyzer.rebuilt_pages).

    The final cleanup removes only folders that have no entries left, in the dock
    and on the pages, then the empty pages of the other folders, and then empty
    pages. check_write() compares the result with the preview before anything is
    written.
    """
    raw = copy.deepcopy(layout.raw)
    fixed = _raw_fixed_ids(raw)

    def stays(item: Any) -> list:
        return _raw_stays_in_rebuild(item, fixed)

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
        ids = [b for b in dict.fromkeys(op.bundle_ids) if b not in fixed]
        if op.action in ("move_to_app_library", "delete"):
            _raw_remove_apps(raw, ids)
            # For dict-format raw (legacy), track ignored apps
            if isinstance(raw, dict) and op.action == "move_to_app_library":
                ignored = raw.get("ignored", [])
                for bid in ids:
                    if bid not in ignored:
                        ignored.append(bid)
                raw["ignored"] = ignored
            # Note: actual app deletion (uninstall) happens via a separate
            # pymobiledevice3 API call, not through IconState. The layout
            # engine just removes the icon from the home screen.

        elif op.action == "move_to_page":
            if op.target_page is not None:
                snapshot = copy.deepcopy(raw)
                extracted = _raw_extract_apps(raw, ids, originals)
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
            if op.folder_name and ids:
                snapshot = copy.deepcopy(raw)
                anchor = _raw_page_folder_named(parsed_pages(), op.old_name)
                extracted = _raw_extract_apps(raw, ids, originals)
                if extracted:
                    folder_pages: list[list] = []
                    add_to_folder_pages(folder_pages, extracted)
                    # The keys of a folder that the phone writes (_new_folder).
                    folder_dict = _new_folder(op.folder_name, folder_pages)
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
            if op.folder_name and ids:
                snapshot = copy.deepcopy(raw)
                extracted = _raw_extract_apps(raw, ids, originals)
                if extracted:
                    added = _raw_add_to_folder(raw, op.folder_name, extracted)
                    if not added:
                        raw = snapshot
                else:
                    raw = snapshot

        elif op.action in ("compact_to_single_page", "rebuild_pages"):
            # The rule of the preview: page 1 keeps its widgets and fixed icons, and
            # a compact whose apps do not fit in the room that they leave is skipped.
            # Here, page 1 is the first raw page with an item that takes a slot. The
            # entries of the other raw pages, those that the parser drops included,
            # come after the apps when they stay.
            all_pages = _get_pages(raw)
            index = first_live_index(all_pages, _raw_item_slots)
            first = [(item, _raw_item_slots(item) > 0) for item in all_pages[index]] if index is not None else []
            if op.action == "rebuild_pages" or len(ids) <= rebuild_room(first, stays, _raw_item_slots):
                extracted = _raw_extract_apps(raw, ids, originals)
                later = [item for number, page in enumerate(all_pages) if number != index for item in page]
                _set_pages(raw, rebuilt_pages(first, extracted, later, stays, _raw_item_slots))
                unparsed = {
                    number for number, page in enumerate(_get_pages(raw))
                    if not any(_parse_item(item) for item in page)
                }

    # Clean up folders the operations emptied, then the empty pages of the other
    # folders, then empty pages, as the preview does.
    dock = _get_dock(raw)
    dock[:] = _without_empty_folders(dock)
    pages = [_without_empty_folders(page) for page in _get_pages(raw)]
    cleaned = [page for page in pages if page]
    _set_pages(raw, cleaned)

    return raw


def _without_empty_folders(container: list) -> list:
    """The container without the folders that have no entries, and with no empty
    page in the other folders. A folder page is empty only when it holds no entry
    at all: an entry that the parser drops keeps its page."""
    kept = [item for item in container if not _raw_is_empty_folder(item)]
    for item in kept:
        if is_folder_entry(item) and isinstance(item.get("iconLists"), list):
            item["iconLists"] = [page for page in item["iconLists"] if page]
    return kept


def _new_folder(name: str, pages: list[list]) -> dict:
    """A new folder entry, with the keys that the phone gives a folder in its icon
    state (the iOS 26 list and the older dict): displayName, iconLists and
    listType "folder"."""
    return {"displayName": name, "iconLists": pages, "listType": "folder"}


def check_write(layout: HomeScreenLayout, operations: list[LayoutOperation]):
    """Build the state to write and check it before anything goes to the phone.

    Returns ``(raw, preview, problem)``: the raw state from apply_operations, the
    preview of the same operations (analyzer.preview_operations, all of them and then
    the cleanup), and a short problem text, or None when the state is safe to write.
    The problems:

    - The raw state does not read back as the preview.
    - The raw state lost an entry (an app, a widget or another icon) that no
      operation took off the home screen, any widget or icon that is not an App
      Store app, any icon of an app with more than one icon, or a dock entry that no
      operation names. See lost_entries().
    - The raw state holds an entry more often than before (see doubled_entries()).
    - The raw state has an App Store app that was not on the home screen before (see
      added_apps()).
    - The raw state has more pages than an iPhone shows (analyzer.MAX_PAGES), and
      more than it had before.
    """
    from unjiggle.analyzer import preview_operations
    from unjiggle.device import parse_layout_state

    preview = preview_operations(layout, operations)
    raw = apply_operations(layout, operations)
    if _signature(parse_layout_state(raw)) != _signature(preview):
        return raw, preview, "the written layout would differ from the preview"
    added = added_apps(layout.raw, raw)
    if added:
        verb = "is" if len(added) == 1 else "are"
        return raw, preview, f"the operations name {_listed(added)}, which {verb} not on the home screen"
    lost = lost_entries(layout.raw, raw, operations)
    if lost:
        return raw, preview, f"the write would remove {_listed(lost)}, which no operation names"
    doubled = doubled_entries(layout.raw, raw)
    if doubled:
        return raw, preview, f"the write would put {_listed(doubled)} on the home screen more than once"
    pages = len(_get_pages(raw))
    if pages > max(MAX_PAGES, len(_get_pages(layout.raw))):
        return raw, preview, f"the written layout would have {pages} pages, and an iPhone shows at most {MAX_PAGES}"
    return raw, preview, None


def _listed(labels: list[str]) -> str:
    return ", ".join(labels[:4]) + (f" and {len(labels) - 4} more" if len(labels) > 4 else "")


def _signature(layout: HomeScreenLayout) -> str:
    """The layout as the post-write check of the CLI compares it."""
    def key(item):
        if item.is_app:
            return item.app.bundle_id
        if item.is_folder:
            return {"folder": item.folder.display_name, "apps": folder_page_ids(item.folder)}
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
    """"app:<bundle ID>" for an App Store app entry, and "app:<bundle ID>#<displayIdentifier>"
    when the entry's displayIdentifier is not its bundle ID (such as the UUID of a
    second icon of an app on iOS 26). Any other entry (a widget, a pinned icon, an
    entry that the parser drops) is "entry:" and its displayIdentifier, or its JSON
    when it has none."""
    if is_app_store_entry(item):
        app_id = entry_app_id(item)
        display = item.get("displayIdentifier") if isinstance(item, dict) else None
        return f"app:{app_id}#{display}" if display and display != app_id else f"app:{app_id}"
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

    - An entry that is not an App Store app (a widget, a Smart Stack, a pinned icon or
      an entry that the parser drops) can never leave, so each one must still be
      there, as often as before, after any operations.
    - Each icon of an app with more than one icon is fixed in the same way. The key of
      an app entry holds its displayIdentifier when that is not the bundle ID, so the
      second icon of an app is a different entry from the first.
    - For the other App Store apps: delete and move_to_app_library take the apps that
      they name off the home screen. compact_to_single_page and rebuild_pages take
      the apps that they do not list off the pages by design. Every other app must
      still be there.
    - Each dock entry must still be in the dock, unless an operation names its app.
    """
    fixed = _raw_fixed_ids(before)
    removed = {
        bundle_id for op in operations
        if op.action in ("delete", "move_to_app_library") for bundle_id in op.bundle_ids
    } - fixed
    named = {bundle_id for op in operations for bundle_id in op.bundle_ids} - fixed
    rebuilt = any(op.action in ("compact_to_single_page", "rebuild_pages") for op in operations)
    entries = _entries(_raw_dock_and_pages(before))
    labels = {_entry_key(entry): _entry_label(entry) for entry in entries}
    apps = {_entry_key(entry): entry_app_id(entry) for entry in entries if is_app_store_entry(entry)}
    before_all = Counter(_entry_keys(_raw_dock_and_pages(before)))
    before_dock = Counter(_entry_keys([_get_dock(before)]))
    after_all = Counter(_entry_keys(_raw_dock_and_pages(after)))
    after_dock = Counter(_entry_keys([_get_dock(after)]))
    lost = []
    for key, count in before_all.items():
        app_id = apps.get(key)
        if app_id in removed:
            continue
        if app_id is None or app_id in fixed:
            need = count
        elif rebuilt:
            need = 0 if app_id in named else before_dock.get(key, 0)
        else:
            need = count
        if after_all.get(key, 0) < need:
            lost.append(labels[key])
    for key, count in before_dock.items():
        if apps.get(key) in named or after_dock.get(key, 0) >= count:
            continue
        if labels[key] not in lost:
            lost.append(f"{labels[key]} (from the dock)")
    return lost


def doubled_entries(before, after) -> list[str]:
    """Entries that ``after`` holds more often than ``before`` (an app at least once),
    such as one app entry written in two places. An empty list when there is none."""
    before_all = Counter(_entry_keys(_raw_dock_and_pages(before)))
    after_entries = _entries(_raw_dock_and_pages(after))
    after_all = Counter(_entry_key(entry) for entry in after_entries)
    labels = {_entry_key(entry): _entry_label(entry) for entry in after_entries}
    return [labels[key] for key, count in after_all.items() if count > max(before_all.get(key, 0), 1)]


def added_apps(before, after) -> list[str]:
    """The IDs of the App Store apps in ``after`` that ``before`` does not have, in the
    dock, on the pages or in a folder. An empty list when there is none.

    No operation puts an app on the home screen. An operation that names an app that
    is not there (it was removed after the preview, or the ID is wrong) would write a
    made-up entry for it, {"bundleIdentifier": ..., "iconType": "app"}, with none of
    the fields that the phone gives an app (_raw_extract_apps). The preview shows the
    same entry, so the other checks do not find it.
    """
    def app_ids(state) -> list[str]:
        return [
            entry_app_id(entry) for entry in _entries(_raw_dock_and_pages(state))
            if is_app_store_entry(entry)
        ]

    known = set(app_ids(before))
    return list(dict.fromkeys(app_id for app_id in app_ids(after) if app_id not in known))


def compact_to_single_page(
    layout: HomeScreenLayout,
    keep_visible_bundle_ids: list[str],
    archive_bundle_ids: list[str],
):
    """Rebuild the home screen as a one-page layout of apps.

    This is the public primitive behind the one-page preset: dock apps stay in the
    dock, the archived apps go to the App Library, and the first kept apps that fit
    stay visible on page 1, with page 1's widgets and fixed icons. The other App
    Store apps leave the home screen. The widgets of other pages, the fixed icons and
    the folders that hold them stay, from page 2 on (see analyzer.rebuilt_pages).
    """
    fixed = _raw_fixed_ids(layout.raw)
    pages = _get_pages(layout.raw)
    index = first_live_index(pages, _raw_item_slots)
    first = [(item, _raw_item_slots(item) > 0) for item in pages[index]] if index is not None else []
    room = max(rebuild_room(first, lambda item: _raw_stays_in_rebuild(item, fixed), _raw_item_slots), 0)
    dock = {entry_app_id(entry) for entry in _entries([_get_dock(layout.raw)]) if is_app_store_entry(entry)}
    keep = [b for b in dict.fromkeys(keep_visible_bundle_ids) if b not in fixed and b not in dock][:room]
    archive = [b for b in dict.fromkeys(archive_bundle_ids) if b not in keep and b not in dock and b not in fixed]
    operations = [LayoutOperation(action="move_to_app_library", bundle_ids=archive)] if archive else []
    operations.append(LayoutOperation(action="compact_to_single_page", bundle_ids=keep))
    return apply_operations(layout, operations)


def _raw_find_app(item: Any) -> str | None:
    """The app ID of a raw App Store app entry, as the parser reads it
    (device.entry_app_id). None for a widget, a Smart Stack, a folder, a pinned icon
    (device.is_pinned_entry) or an entry that is not an app: no operation takes
    them out of their place."""
    return entry_app_id(item) if is_app_store_entry(item) else None


def _raw_pinned_ids(raw) -> set[str]:
    """The IDs of the pinned icons in a raw state, as HomeScreenLayout.pinned_ids()
    gives them for the parsed layout: without an ID that an App Store app also has."""
    entries = _entries(_raw_dock_and_pages(raw))
    pinned = {entry_app_id(entry) for entry in entries if is_pinned_entry(entry)}
    apps = {entry_app_id(entry) for entry in entries if is_app_store_entry(entry)}
    return pinned - apps


def _raw_fixed_ids(raw) -> set[str]:
    """The IDs that no operation acts on in a raw state, as HomeScreenLayout.fixed_ids()
    gives them for the parsed layout: the pinned icons, and the IDs of the App Store
    apps that have more than one entry on the home screen."""
    counts = Counter(
        entry_app_id(entry) for entry in _entries(_raw_dock_and_pages(raw)) if is_app_store_entry(entry)
    )
    return _raw_pinned_ids(raw) | {app_id for app_id, count in counts.items() if count > 1}


def _raw_stays_in_rebuild(item: Any, fixed: set[str] | frozenset = frozenset()) -> list:
    """What stays of a raw page entry when compact_to_single_page or rebuild_pages
    replaces the pages, as analyzer.stays_in_rebuild gives it for a parsed item.
    ``fixed`` holds the IDs of the apps that no operation acts on (_raw_fixed_ids()).

    A widget, a Smart Stack, a fixed icon and an entry that the parser drops stay.
    An App Store app that is not fixed leaves. A folder keeps its entries that stay,
    on their own folder pages: a page that has nothing left leaves, and no page gets
    more entries than it had. The folder stays when a fixed icon stays in it, as in
    the preview. The preview does not show a folder page with only entries that the
    parser drops, and the checks leave out empty folder pages (see
    analyzer.folder_page_ids). A folder with no fixed icon leaves; the entries of it
    that the parser drops stay, out of the folder.
    """
    def keeps(entry: Any) -> bool:
        return not is_app_store_entry(entry) or entry_app_id(entry) in fixed

    if is_app_store_entry(item):
        return [item] if keeps(item) else []
    if is_folder_entry(item) or _raw_is_empty_folder(item):
        pages = [[entry for entry in page if keeps(entry)] for page in item.get("iconLists") or []]
        pages = [page for page in pages if page]
        if any(entry_app_id(entry) for page in pages for entry in page):
            return [{**item, "iconLists": pages}]
        return [entry for page in pages for entry in page]
    return [item]


def _raw_is_folder(item: Any) -> bool:
    """A folder, as the parser and SpringBoard read it (device.is_folder_entry). A
    widget or an app with an empty "iconLists" key is not a folder."""
    return is_folder_entry(item)


def _raw_is_empty_folder(item: Any) -> bool:
    """A folder that the operations emptied: no entries of any kind are left in it.
    An entry that the parser does not show still keeps its folder.

    A folder has listType (or iconType) "folder". A folder with no type (an older
    state) is a folder only when its iconLists holds at least one folder page, and
    when it has no identifier, no iconType, no gridSize and no elements: an entry
    such as {"iconType": "custom", "gridSize": "small", "iconLists": []} is not a
    folder, so the cleanup keeps it and lost_entries() counts it."""
    if not isinstance(item, dict) or is_widget_entry(item) or entry_app_id(item):
        return False
    lists = item.get("iconLists")
    typed = item.get("listType") == "folder" or item.get("iconType") == "folder"
    untyped = (
        isinstance(lists, list) and bool(lists)
        and all(isinstance(page, list) for page in lists)
        and not any(item.get(key) for key in ("bundleIdentifier", "displayIdentifier", "iconType", "elementType"))
        and "gridSize" not in item and "elements" not in item
    )
    if not (typed or untyped):
        return False
    return not any(lists or [])


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
