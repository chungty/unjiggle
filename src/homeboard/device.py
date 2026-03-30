"""iPhone device connection and layout reading via pymobiledevice3."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.springboard import SpringBoardServicesService

from homeboard.models import (
    AppItem,
    DeviceInfo,
    FolderItem,
    HomeScreenLayout,
    LayoutItem,
    WidgetItem,
    WidgetSize,
)


def connect() -> tuple:
    """Connect to the first USB-attached iPhone. Returns (lockdown_client, device_info)."""
    lockdown = create_using_usbmux()
    info = DeviceInfo(
        name=lockdown.all_values.get("DeviceName", "Unknown"),
        model=lockdown.all_values.get("ProductType", "Unknown"),
        ios_version=lockdown.all_values.get("ProductVersion", "Unknown"),
        udid=lockdown.all_values.get("UniqueDeviceID", "Unknown"),
    )
    return lockdown, info


def _parse_layout_item(raw_item) -> LayoutItem:
    """Parse a single item from IconState into a LayoutItem."""
    if isinstance(raw_item, str):
        return LayoutItem(app=AppItem(bundle_id=raw_item))

    if isinstance(raw_item, dict):
        # Widget
        if raw_item.get("elementType") == "widget":
            size_str = raw_item.get("gridSize", "small")
            try:
                size = WidgetSize(size_str)
            except ValueError:
                size = WidgetSize.SMALL
            return LayoutItem(widget=WidgetItem(
                container_bundle_id=raw_item.get("containerBundleIdentifier", "unknown"),
                grid_size=size,
                raw=raw_item,
            ))

        # Folder
        if "iconLists" in raw_item or raw_item.get("listType") == "folder":
            folder_pages = []
            for folder_page in raw_item.get("iconLists", []):
                apps = []
                for entry in folder_page:
                    if isinstance(entry, str):
                        apps.append(AppItem(bundle_id=entry))
                    elif isinstance(entry, dict) and "bundleIdentifier" in entry:
                        apps.append(AppItem(bundle_id=entry["bundleIdentifier"]))
                folder_pages.append(apps)
            return LayoutItem(folder=FolderItem(
                display_name=raw_item.get("displayName", "Unnamed Folder"),
                pages=folder_pages,
                raw=raw_item,
            ))

        # App as dict (some iOS versions use dicts with bundleIdentifier)
        if "bundleIdentifier" in raw_item:
            return LayoutItem(app=AppItem(bundle_id=raw_item["bundleIdentifier"]))

    # Unknown format, skip
    return None


def read_layout(lockdown) -> HomeScreenLayout:
    """Read the current home screen layout from the connected device."""
    raw_state = asyncio.run(_read_layout_async(lockdown))

    # Parse dock
    dock = []
    for item in raw_state.get("buttonBar", []):
        parsed = _parse_layout_item(item)
        if parsed:
            dock.append(parsed)

    # Parse pages
    pages = []
    for page_items in raw_state.get("iconLists", []):
        page = []
        for item in page_items:
            parsed = _parse_layout_item(item)
            if parsed:
                page.append(parsed)
        if page:
            pages.append(page)

    # Parse ignored (App Library)
    ignored = raw_state.get("ignored", [])

    return HomeScreenLayout(dock=dock, pages=pages, ignored=ignored, raw=raw_state)


async def _read_layout_async(lockdown) -> dict:
    async with SpringBoardServicesService(lockdown) as sbs:
        return await sbs.get_icon_state(format_version="2")


def write_layout(lockdown, state: dict) -> None:
    """Write a layout state dict back to the device."""
    asyncio.run(_write_layout_async(lockdown, state))


async def _write_layout_async(lockdown, state: dict) -> None:
    async with SpringBoardServicesService(lockdown) as sbs:
        await sbs.set_icon_state(state)


def fetch_icon(lockdown, bundle_id: str) -> bytes | None:
    """Fetch an app icon as PNG bytes from the device."""
    return asyncio.run(_fetch_icon_async(lockdown, bundle_id))


async def _fetch_icon_async(lockdown, bundle_id: str) -> bytes | None:
    async with SpringBoardServicesService(lockdown) as sbs:
        return await sbs.get_icon_pngdata(bundle_id)


def backup_layout(layout: HomeScreenLayout, path: Path) -> None:
    """Save the raw layout state to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(layout.raw, indent=2, default=str))


def restore_layout_from_file(path: Path) -> dict:
    """Load a raw layout state from a JSON backup file."""
    return json.loads(path.read_text())
