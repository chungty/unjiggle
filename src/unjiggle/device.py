"""iPhone device connection and layout reading via pymobiledevice3.

Modern format (iOS 26+/formatVersion 2): get_icon_state() returns a flat list of lists.
  - state[0] = dock items
  - state[1:] = home screen pages
  - Each app is a dict with bundleIdentifier, displayName, displayIdentifier, etc.
  - Folders use listType: "folder" with iconLists of nested app dicts
    (iconType: "folder" is rejected/silently dropped on iOS 27 writes)
  - Widgets have elementType: "widget" or iconType: "custom"

setIconState on iOS 27:
  - List-format writes omit `ignored`; SpringBoard re-adds missing apps to the HS
  - Dict form {buttonBar, iconLists, ignored} is required to keep apps in App Library
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

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

    # Folder (iOS 27 normalizes to listType=folder; older paths used iconType)
    if (
        raw_item.get("listType") == "folder"
        or raw_item.get("iconType") == "folder"
        or (raw_item.get("iconLists") and any(raw_item.get("iconLists", [])))
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

    # Regular app (dict format in modern IconState)
    if bundle_id:
        return LayoutItem(app=AppItem(
            bundle_id=bundle_id,
            display_name=raw_item.get("displayName"),
        ))

    return None


def parse_layout_state(raw_state) -> HomeScreenLayout:
    """Parse a raw icon-state payload into a HomeScreenLayout."""
    # Modern list format: flat list of lists
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


def _bundle_ids_in_icon_state(state: Any) -> set[str]:
    """Collect every app bundle ID visible on the dock/pages (including inside folders)."""
    if isinstance(state, list):
        pages = state
    elif isinstance(state, dict):
        pages = [state.get("buttonBar", [])] + list(state.get("iconLists", []))
    else:
        return set()

    found: set[str] = set()
    for page in pages:
        if not isinstance(page, list):
            continue
        for item in page:
            if isinstance(item, str):
                found.add(item)
                continue
            if not isinstance(item, dict):
                continue
            bid = item.get("bundleIdentifier")
            if bid:
                found.add(bid)
            for folder_page in item.get("iconLists", []) or []:
                for entry in folder_page:
                    if isinstance(entry, str):
                        found.add(entry)
                    elif isinstance(entry, dict) and entry.get("bundleIdentifier"):
                        found.add(entry["bundleIdentifier"])
    return found


def icon_state_for_write(
    state: Any,
    ignored: list[str] | None = None,
) -> dict:
    """Normalize IconState into the dict form SpringBoard needs for setIconState.

    iOS 27 re-adds omitted apps unless they appear in ``ignored`` (App Library).
    getIconState returns a list and does not include ``ignored``, so writers must
    always send dict form when any app should stay off the home screen.
    """
    if isinstance(state, list):
        payload = {
            "buttonBar": copy.deepcopy(state[0]) if state else [],
            "iconLists": copy.deepcopy(state[1:]) if len(state) > 1 else [],
            "ignored": [],
        }
    elif isinstance(state, dict):
        payload = copy.deepcopy(state)
        payload.setdefault("buttonBar", [])
        payload.setdefault("iconLists", [])
        payload.setdefault("ignored", [])
    else:
        raise TypeError(f"Unexpected icon state type for write: {type(state)!r}")

    on_hs = _bundle_ids_in_icon_state(payload)
    merged: list[str] = []
    for bid in list(payload.get("ignored") or []) + list(ignored or []):
        if bid and bid not in on_hs and bid not in merged:
            merged.append(bid)
    payload["ignored"] = merged
    return payload


def _list_installed_app_bundle_ids(lockdown) -> list[str]:
    """Return installed home-screen-eligible app bundle IDs (User + System).

    User-only listing is not enough: iOS 27 setIconState re-adds omitted *system*
    apps (Tips, Mail, Watch, …) unless they appear in ``ignored``.
    """
    from pymobiledevice3.services.installation_proxy import InstallationProxyService

    async def _list():
        async with InstallationProxyService(lockdown=lockdown) as iproxy:
            # No application_type filter → User + System (+ any other types).
            apps = await iproxy.get_apps()
            if isinstance(apps, dict):
                items = apps.items()
            else:
                items = [
                    (app.get("CFBundleIdentifier"), app)
                    for app in apps
                    if app.get("CFBundleIdentifier")
                ]

            bids: list[str] = []
            for bid, meta in items:
                if not bid:
                    continue
                # Prefer ApplicationType when present; keep unknown types too so we
                # never miss a SpringBoard-visible system app.
                if isinstance(meta, dict):
                    app_type = meta.get("ApplicationType")
                    if app_type is not None and app_type not in ("User", "System"):
                        continue
                bids.append(bid)
            return bids

    return _run(_list())


# Backward-compatible alias
_list_user_app_bundle_ids = _list_installed_app_bundle_ids


def _augment_ignored_with_off_homescreen_apps(lockdown, payload: dict) -> dict:
    """Keep off-home-screen apps (user *and* system) in App Library across writes.

    getIconState does not return ``ignored``. On iOS 27, writing a layout without
    listing omitted apps under ``ignored`` causes SpringBoard to re-materialize
    them on the home screen — including stock Apple apps, not only third-party.
    Seed ``ignored`` from every installed User/System app missing from the HS
    payload.
    """
    try:
        installed = _list_installed_app_bundle_ids(lockdown)
    except Exception:
        return payload

    on_hs = _bundle_ids_in_icon_state(payload)
    ignored = list(payload.get("ignored") or [])
    for bid in installed:
        if bid and bid not in on_hs and bid not in ignored:
            ignored.append(bid)
    payload["ignored"] = ignored
    return payload


# Backward-compatible alias
_augment_ignored_with_off_homescreen_user_apps = _augment_ignored_with_off_homescreen_apps


def write_layout(lockdown, state, ignored: list[str] | None = None) -> None:
    """Write a layout state back to the device.

    Always sends dict-form IconState (buttonBar/iconLists/ignored). On iOS 27,
    list-form setIconState silently puts omitted apps back on the home screen
    (both third-party and system apps) unless they are listed in ``ignored``.
    """
    from pymobiledevice3.services.springboard import SpringBoardServicesService

    payload = icon_state_for_write(state, ignored=ignored)
    payload = _augment_ignored_with_off_homescreen_apps(lockdown, payload)

    async def _write():
        async with SpringBoardServicesService(lockdown) as sbs:
            await sbs.set_icon_state(payload)

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
