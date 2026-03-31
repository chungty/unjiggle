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
from pathlib import Path

from homeboard.models import (
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


def _parse_item(raw_item) -> LayoutItem | None:
    """Parse a single item from the iOS 26 icon state format."""
    if isinstance(raw_item, str):
        return LayoutItem(app=AppItem(bundle_id=raw_item))

    if not isinstance(raw_item, dict):
        return None

    icon_type = raw_item.get("iconType", raw_item.get("elementType", ""))
    bundle_id = raw_item.get("bundleIdentifier", "")

    # Widget (standalone or in smart stack)
    if icon_type == "widget" or raw_item.get("elementType") == "widget":
        size_str = raw_item.get("gridSize", "small")
        try:
            size = WidgetSize(size_str)
        except ValueError:
            size = WidgetSize.SMALL
        return LayoutItem(widget=WidgetItem(
            container_bundle_id=raw_item.get("containerBundleIdentifier", bundle_id),
            grid_size=size,
            raw=raw_item,
        ))

    # Smart Stack (has elements array with multiple widgets)
    if raw_item.get("elements") and raw_item.get("iconType") == "custom":
        size_str = raw_item.get("gridSize", "small")
        try:
            size = WidgetSize(size_str)
        except ValueError:
            size = WidgetSize.SMALL
        return LayoutItem(widget=WidgetItem(
            container_bundle_id="smartstack",
            grid_size=size,
            raw=raw_item,
        ))

    # Folder (has iconLists with actual content)
    if raw_item.get("iconType") == "folder" or (
        raw_item.get("iconLists") and any(raw_item.get("iconLists", []))
    ):
        folder_pages = []
        for folder_page in raw_item.get("iconLists", []):
            apps = []
            for entry in folder_page:
                if isinstance(entry, str):
                    apps.append(AppItem(bundle_id=entry))
                elif isinstance(entry, dict):
                    bid = entry.get("bundleIdentifier", "")
                    name = entry.get("displayName")
                    if bid:
                        apps.append(AppItem(bundle_id=bid, display_name=name))
            folder_pages.append(apps)
        return LayoutItem(folder=FolderItem(
            display_name=raw_item.get("displayName", "Unnamed Folder"),
            pages=folder_pages,
            raw=raw_item,
        ))

    # Regular app (dict format in iOS 26)
    if bundle_id:
        return LayoutItem(app=AppItem(
            bundle_id=bundle_id,
            display_name=raw_item.get("displayName"),
        ))

    return None


def read_layout(lockdown) -> HomeScreenLayout:
    """Read the current home screen layout from the connected device."""
    from pymobiledevice3.services.springboard import SpringBoardServicesService

    async def _read():
        async with SpringBoardServicesService(lockdown) as sbs:
            return await sbs.get_icon_state(format_version="2")

    raw_state = _run(_read())

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


def restore_layout_from_file(path: Path) -> dict:
    """Load a raw layout state from a JSON backup file."""
    return json.loads(path.read_text())


# Keep old name as alias for tests
_parse_layout_item = _parse_item
