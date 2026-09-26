"""What SpringBoard can do to an icon state that it gets from a write.

On the owner's iPhone (iOS 26.0), a write of `json apply` listed each icon in the
intended order. Then SpringBoard added one more app: an installed app that was only in
the App Library before the write (Amazon). It put the app in the first free slot. The
undo (`json restore` of the backup, which does not have the app) did the same: the
backup came back, and SpringBoard put the app in the first free slot again.

The fake phones of the tests use these functions. Nothing here touches an iPhone.
"""

from __future__ import annotations

import copy

from unjiggle.analyzer import PAGE_SLOTS
from unjiggle.device import entry_app_id, parse_layout_state
from unjiggle.layout_engine import _raw_item_slots, _raw_page_slots

# The entry that SpringBoard added on the owner's iPhone.
UNLISTED_APP = {
    "displayIdentifier": "com.amazon.Amazon",
    "displayName": "Amazon",
    "iconModDate": "2026-09-17 16:02:26.858528",
    "bundleVersion": "881853.0",
    "bundleIdentifier": "com.amazon.Amazon",
}


def put_in_first_free_slot(state: list, entry: dict) -> list:
    """A copy of the list-format ``state`` with ``entry`` at the end of the first page
    that has room for it, or on a new last page when no page has room."""
    state = copy.deepcopy(state)
    for page in state[1:]:
        if _raw_page_slots(page) + _raw_item_slots(entry) <= PAGE_SLOTS:
            page.append(copy.deepcopy(entry))
            return state
    state.append([copy.deepcopy(entry)])
    return state


def adds_unlisted_app(state: list, entry: dict = UNLISTED_APP) -> list:
    """What SpringBoard did on the owner's iPhone: when the written ``state`` does not
    have the app of ``entry`` on the home screen, SpringBoard puts it in the first free
    slot. Otherwise the phone keeps the state as it is."""
    if entry_app_id(entry) in parse_layout_state(copy.deepcopy(state)).all_bundle_ids:
        return copy.deepcopy(state)
    return put_in_first_free_slot(state, entry)


def without_app(state: list, bundle_id: str) -> list:
    """A copy of ``state`` with no loose entry of this app on a page. A page that has
    no entry after that is removed too."""
    pages = []
    for page in copy.deepcopy(state)[1:]:
        rest = [entry for entry in page if not (isinstance(entry, dict) and entry.get("bundleIdentifier") == bundle_id)]
        if rest or not page:
            pages.append(rest)
    return [copy.deepcopy(state[0]), *pages]


def page_of(state: list, bundle_id: str) -> int:
    """The page number (from 1, as the owner counts pages) of the loose icon of this
    app, as the parser reads the state."""
    layout = parse_layout_state(copy.deepcopy(state))
    for number, page in enumerate(layout.pages, start=1):
        if any(item.is_app and item.app.bundle_id == bundle_id for item in page):
            return number
    raise AssertionError(f"{bundle_id} is not loose on a page")
