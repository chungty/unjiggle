"""iPhone device connection and layout reading via pymobiledevice3.

iOS 26 format: get_icon_state() returns a flat list of lists.
  - state[0] = dock items
  - state[1:] = home screen pages
  - Each item is a dict with bundleIdentifier, displayName, iconType, etc.
  - Folders have iconLists with nested app dicts
  - Widgets have elementType: "widget" or iconType: "custom"
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from unjiggle.models import (
    AppItem,
    DeviceInfo,
    FolderItem,
    HomeScreenLayout,
    LayoutItem,
    WidgetItem,
    WidgetSize,
)

_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def reset_connection():
    """Reset the event loop for a fresh connection."""
    global _loop
    if _loop and not _loop.is_closed():
        _loop.close()
    _loop = None


def _run(coro):
    return _get_loop().run_until_complete(coro)


def connect() -> tuple:
    """Connect to the first USB-attached iPhone. Returns (lockdown_client, device_info)."""
    from pymobiledevice3.lockdown import create_using_usbmux

    reset_connection()  # Fresh loop for each connect
    lockdown = _run(create_using_usbmux())
    info = DeviceInfo(
        name=lockdown.all_values.get("DeviceName", "Unknown"),
        model=lockdown.all_values.get("ProductType", "Unknown"),
        ios_version=lockdown.all_values.get("ProductVersion", "Unknown"),
        udid=str(lockdown.all_values.get("UniqueDeviceID", "Unknown")),
    )
    return lockdown, info


def is_widget_entry(raw_item) -> bool:
    """True for a widget or a Smart Stack entry of the icon state."""
    if not isinstance(raw_item, dict):
        return False
    return (
        raw_item.get("iconType") == "widget"
        or raw_item.get("elementType") == "widget"
        or (bool(raw_item.get("elements")) and raw_item.get("iconType") == "custom")
    )


def is_folder_entry(raw_item) -> bool:
    """True for a folder entry of the icon state.

    SpringBoard marks a folder with listType "folder" (older states use iconType
    "folder"). On iOS 26, widgets, Smart Stacks and some apps also have an
    "iconLists" key, often an empty list, so that key alone does not make a folder.
    An entry with no type and no identifier of its own is a folder only when its
    iconLists holds entries.
    """
    if not isinstance(raw_item, dict) or is_widget_entry(raw_item):
        return False
    if raw_item.get("listType") == "folder" or raw_item.get("iconType") == "folder":
        return True
    if raw_item.get("bundleIdentifier") or raw_item.get("displayIdentifier"):
        return False
    return any(raw_item.get("iconLists") or [])


def entry_app_id(raw_item) -> str | None:
    """The ID of an app entry: its bundleIdentifier, or for an icon that the phone
    shows without one (a pinned icon, see is_pinned_entry) its displayIdentifier.
    None for a widget, a folder or an entry that the parser does not show.

    The parser and the write path (layout_engine) find an app by this ID, so both
    see the same apps.
    """
    if isinstance(raw_item, str):
        return raw_item or None
    if not isinstance(raw_item, dict) or is_widget_entry(raw_item) or is_folder_entry(raw_item):
        return None
    bundle_id = raw_item.get("bundleIdentifier")
    if bundle_id:
        return bundle_id
    if raw_item.get("iconType") in (None, "app"):
        return raw_item.get("displayIdentifier") or None
    return None


def is_pinned_entry(raw_item) -> bool:
    """True for an icon that the parser shows as an app, but that has no
    bundleIdentifier (only a displayIdentifier): an icon that is not an App Store app,
    such as a web shortcut or an App Clip. The App Library cannot hold it, so the
    engine never moves or removes it (see models.AppItem.pinned)."""
    return (
        isinstance(raw_item, dict)
        and not raw_item.get("bundleIdentifier")
        and entry_app_id(raw_item) is not None
    )


def is_app_store_entry(raw_item) -> bool:
    """True for an app entry with a bundle ID: an App Store app (or an Apple app) that
    can go to the App Library. A widget, a folder, a pinned icon and an entry that the
    parser does not show are not."""
    return entry_app_id(raw_item) is not None and not is_pinned_entry(raw_item)


# Keys of a widget, a Smart Stack or a folder. The entry of an app icon has none of them.
_NOT_APP_KEYS = ("elementType", "elements", "listType", "containerBundleIdentifier", "widgetIdentifier", "gridSize")


def is_plain_app_entry(raw_item) -> bool:
    """True for an entry that is only the icon of an App Store app, as SpringBoard adds
    an app from the App Library: a bundle ID (the legacy format), or a dict with a
    bundleIdentifier, an iconType that is absent or "app", a displayIdentifier that is
    absent or the bundleIdentifier, no folder pages and no key of a widget or a folder.

    A widget, a folder, a pinned icon, a second icon of an app (its displayIdentifier
    is a UUID) and an entry of another type (for example iconType "custom") are not.
    """
    if isinstance(raw_item, str):
        return bool(raw_item)
    if not is_app_store_entry(raw_item):
        return False
    return (
        raw_item.get("iconType") in (None, "app")
        and raw_item.get("displayIdentifier") in (None, raw_item["bundleIdentifier"])
        and not raw_item.get("iconLists")
        and not any(key in raw_item for key in _NOT_APP_KEYS)
    )


def _parse_item(raw_item) -> LayoutItem | None:
    """Parse a single item from the iOS 26 icon state format."""
    if isinstance(raw_item, str):
        return LayoutItem(app=AppItem(bundle_id=raw_item, plain_entry=bool(raw_item)))

    if not isinstance(raw_item, dict):
        return None

    bundle_id = raw_item.get("bundleIdentifier", "")

    if is_widget_entry(raw_item):
        # A Smart Stack is a custom entry with an elements array of widgets.
        stack = raw_item.get("iconType") != "widget" and raw_item.get("elementType") != "widget"
        return LayoutItem(widget=WidgetItem(
            container_bundle_id="smartstack" if stack else raw_item.get("containerBundleIdentifier", bundle_id),
            grid_size=WidgetSize.parse(raw_item.get("gridSize")),
            raw=raw_item,
        ))

    if is_folder_entry(raw_item):
        folder_pages = []
        for folder_page in raw_item.get("iconLists", []):
            apps = []
            for entry in folder_page:
                app_id = entry_app_id(entry)
                if app_id:
                    name = entry.get("displayName") if isinstance(entry, dict) else None
                    apps.append(AppItem(
                        bundle_id=app_id,
                        display_name=name,
                        pinned=is_pinned_entry(entry),
                        plain_entry=is_plain_app_entry(entry),
                    ))
            folder_pages.append(apps)
        return LayoutItem(folder=FolderItem(
            display_name=raw_item.get("displayName", "Unnamed Folder"),
            pages=folder_pages,
            raw=raw_item,
        ))

    # An app (a dict on iOS 26). An icon with no bundleIdentifier is found by its
    # displayIdentifier: it takes a slot, and it is pinned (not an App Store app).
    app_id = entry_app_id(raw_item)
    if app_id:
        return LayoutItem(app=AppItem(
            bundle_id=app_id,
            display_name=raw_item.get("displayName"),
            pinned=is_pinned_entry(raw_item),
            plain_entry=is_plain_app_entry(raw_item),
        ))

    return None


def parse_layout_state(raw_state) -> HomeScreenLayout:
    """Parse a raw icon-state payload into a HomeScreenLayout."""
    # iOS 26 format: flat list of lists
    # state[0] = dock, state[1:] = pages
    if isinstance(raw_state, list):
        dock_raw = raw_state[0] if raw_state else []
        pages_raw = raw_state[1:] if len(raw_state) > 1 else []

        dock = []
        for item in dock_raw:
            parsed = _parse_item(item)
            if parsed:
                dock.append(parsed)

        pages = []
        for page_items in pages_raw:
            page = []
            for item in page_items:
                parsed = _parse_item(item)
                if parsed:
                    page.append(parsed)
            if page:
                pages.append(page)

        return HomeScreenLayout(dock=dock, pages=pages, ignored=[], raw=raw_state)

    # Legacy format (dict with buttonBar/iconLists/ignored keys)
    elif isinstance(raw_state, dict):
        dock = []
        for item in raw_state.get("buttonBar", []):
            parsed = _parse_item(item)
            if parsed:
                dock.append(parsed)

        pages = []
        for page_items in raw_state.get("iconLists", []):
            page = []
            for item in page_items:
                parsed = _parse_item(item)
                if parsed:
                    page.append(parsed)
            if page:
                pages.append(page)

        ignored = raw_state.get("ignored", [])
        return HomeScreenLayout(dock=dock, pages=pages, ignored=ignored, raw=raw_state)

    raise RuntimeError(f"Unexpected icon state format: {type(raw_state)}")


def read_layout(lockdown) -> HomeScreenLayout:
    """Read the current home screen layout from the connected device."""
    from pymobiledevice3.services.springboard import SpringBoardServicesService

    async def _read():
        async with SpringBoardServicesService(lockdown) as sbs:
            return await sbs.get_icon_state(format_version="2")

    raw_state = _run(_read())
    return parse_layout_state(raw_state)


def write_layout(lockdown, state) -> None:
    """Write a layout state back to the device."""
    from pymobiledevice3.services.springboard import SpringBoardServicesService

    async def _write():
        async with SpringBoardServicesService(lockdown) as sbs:
            await sbs.set_icon_state(state)

    _run(_write())


def fetch_icon(lockdown, bundle_id: str) -> bytes | None:
    """Fetch an app icon as PNG bytes from the device."""
    from pymobiledevice3.services.springboard import SpringBoardServicesService

    async def _fetch():
        async with SpringBoardServicesService(lockdown) as sbs:
            return await sbs.get_icon_pngdata(bundle_id)

    return _run(_fetch())


def backup_layout(layout: HomeScreenLayout, path: Path) -> None:
    """Save the raw layout state to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(layout.raw, indent=2, default=str))


def restore_layout_from_file(path: Path):
    """Load a raw layout state from a JSON backup file.

    A backup is the icon state as json.dumps(default=str) writes it
    (safety.verified_backup), so each date that the phone gave (the iconModDate of an
    app) is text in the file, such as "2026-09-23 19:06:58.692950". Each such text
    becomes a datetime again (see dates_from_backup), so that a restore writes the same
    types that the phone gave, as a write of `json apply` does.
    """
    return dates_from_backup(json.loads(path.read_text()))


# The keys of the icon state that hold a date. JSON has no date type, so a backup
# holds each one as text.
_DATE_KEYS = frozenset({"iconModDate"})


def dates_from_backup(value):
    """A copy of a raw state from a backup file, with each iconModDate text that is an
    ISO date changed back to a datetime. Other values stay as they are."""
    if isinstance(value, list):
        return [dates_from_backup(item) for item in value]
    if isinstance(value, dict):
        restored = {}
        for key, item in value.items():
            if key in _DATE_KEYS and isinstance(item, str):
                try:
                    item = datetime.fromisoformat(item)
                except ValueError:
                    pass
            else:
                item = dates_from_backup(item)
            restored[key] = item
        return restored
    return value


# Keep old name as alias for tests
_parse_layout_item = _parse_item
