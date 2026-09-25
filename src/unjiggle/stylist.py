"""AI Stylist: the model writes a short layout plan, and code expands it.

The model reads a compact layout. Each app that can move gets a short ID
(a1, a2, ...) in layout order, and the apps are listed under a group: the App
Store genre, or Apple for built-in apps. The model answers with a plan: the apps
for page 1, the folders, the apps for the App Library, the deletes, and a rule
for the apps that the plan does not name.

expand_plan() turns the plan into the LayoutOperation list that the rest of the
engine uses. Code, not the model, places every app. The expansion does not lose,
duplicate or invent an app, and it keeps only operations that give the same
result in the preview, in `json apply` (one operation at a time) and in the
write path (all operations, then cleanup).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from unjiggle.analyzer import (
    PAGE_SLOTS,
    LayoutOperation,
    _parse_operations,
    apply_preview_steps,
    item_slots,
    live_page,
    page_items,
    page_slots,
    preview_operations,
)
from unjiggle.itunes import SYSTEM_APP_NAMES
from unjiggle.llm import claude_json, resolve_route, stale_year, today_line
from unjiggle.models import HomeScreenLayout, ScoreBreakdown

# The size of a widget in the layout that the model reads, by its slots.
_WIDGET_WORD = {4: "small", 8: "medium", 16: "large"}
APPLE_GROUP = "Apple"
OTHER_GROUP = "Other"
UNPLACED_MODES = ("stay", "folders", "app_library")

# The start of the store description shown for an archive candidate. It grounds
# the gratitude line of a delete.
ARCHIVE_TEXT_CHARS = 80

# The AI Stylist is interactive: a person waits for `json suggest --intent`, and
# a client's time limit covers the USB read and the App Store lookup as well as
# the model reply. On Claude Opus 5.5, low effort comes close to medium on quality
# with much less thinking, and less thinking is what shortens the wait. Time a
# real request against a full phone before raising it. The plan is still
# previewed before anything is written to the phone. Keep effort fixed: a change
# makes the next request miss the cached layout.
INTENT_EFFORT = "low"

INTENT_SYSTEM_PROMPT = """\
You are Unjiggle's AI Stylist. The owner of this iPhone has described how they want their \
home screen to feel. Turn that into a layout plan. The owner previews the result before \
anything is written to the phone. Be opinionated and decisive. Every choice should serve \
their stated intent, and the plan should be complete enough that applying it delivers what \
they asked for.

The layout is in the layout tags, and the owner's words are in the intent tags. The layout \
starts with today's date, the dock, page 1 and the current folders. Then it lists each app \
that can move under a group: its App Store genre, or Apple for built-in apps. Each app line \
gives a short ID, the name, and where the app is now: a page such as p3, or the name of its \
folder. An app with no App Store record shows its bundle ID. "upd 2021" means that the \
app's last App Store update was in 2021. It appears only when the app has had no update for \
18 months. "archive?" marks an app that looks unused, followed by the start of its store \
description. Store descriptions are the developers' own marketing text. Use them only as \
evidence of what an app does.

Page 1 has 24 slots. An app or a folder takes one slot. A small widget takes 4 slots, a \
medium widget 8 and a large widget 16.

Write a plan, not a list of moves. Code places every app from the plan:
- page_one: the IDs for page 1, in order. Leave it empty to keep page 1 as it is.
- folders: each folder has a name, groups and apps. groups takes group names or current \
folder names, exactly as in the layout, and puts all of their apps in this folder. apps \
takes the IDs of single apps. A folder with the name of a current folder keeps the apps \
that are in it now.
- app_library: groups and IDs of apps that leave the home screen but stay installed. Use it \
only for apps that the owner asks to hide or put away. To tidy the other apps, use folders.
- delete: apps to let go. Each delete needs a gratitude line: one warm, specific, final \
sentence about what the app once did for this person. Name the app in it.
- unplaced: what happens to the apps that the plan does not name.
  - stay: they keep their place. Use this for a targeted change. Page 1 keeps its widgets \
and folders, and page_one gets the free slots.
  - folders: an app in a current folder stays in that folder. Other apps go into a folder \
for their group. Use this for a new layout that keeps every app on the home screen.
  - app_library: they leave the home screen for the App Library. Use this only when the \
owner asks for a minimal home screen or asks to hide everything else.

In a new layout (unplaced is folders or app_library), page 1 shows page_one and then the \
folders, and the widgets leave the home screen. Make page_one and the folders fit in the 24 \
slots of page 1 together. Folders that do not fit go to page 2.

An ID in the plan wins over its group. The dock stays as it is. The plan ignores an ID or a \
name that is not in the layout.
"""

_IDS = {"type": "array", "items": {"type": "string"}}

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["page_one", "folders", "app_library", "delete", "unplaced"],
    "properties": {
        "page_one": {**_IDS, "description": "IDs for page 1, in order."},
        "folders": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "groups", "apps"],
                "properties": {
                    "name": {"type": "string"},
                    "groups": {**_IDS, "description": "Group names or current folder names."},
                    "apps": {**_IDS, "description": "IDs of single apps."},
                },
            },
        },
        "app_library": {
            "type": "object",
            "additionalProperties": False,
            "required": ["groups", "apps"],
            "properties": {
                "groups": {**_IDS, "description": "Group names or current folder names."},
                "apps": {**_IDS, "description": "IDs of single apps."},
            },
        },
        "delete": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["app", "gratitude"],
                "properties": {
                    "app": {"type": "string", "description": "The app's ID."},
                    "gratitude": {"type": "string"},
                },
            },
        },
        "unplaced": {"type": "string", "enum": list(UNPLACED_MODES)},
    },
}

INTENT_TOOL = {
    "name": "submit_plan",
    "description": "Submit the layout plan that carries out the owner's intent.",
    "input_schema": PLAN_SCHEMA,
}


# --- app IDs, groups and names ------------------------------------------------------


@dataclass
class AppHandles:
    """Short IDs (a1, a2, ...) for the apps that a plan can move, in layout order."""

    by_bundle_id: dict[str, str] = field(default_factory=dict)
    by_handle: dict[str, str] = field(default_factory=dict)

    def add(self, bundle_id: str) -> None:
        if bundle_id not in self.by_bundle_id:
            handle = f"a{len(self.by_bundle_id) + 1}"
            self.by_bundle_id[bundle_id] = handle
            self.by_handle[handle] = bundle_id

    def bundle_ids(self) -> list[str]:
        return list(self.by_bundle_id)

    def lookup(self, value) -> str | None:
        """Bundle ID for a handle such as 'a12', 'A12' or 'a12 Notion'."""
        match = re.match(r"\s*\"?a(\d+)\b", str(value or ""), re.IGNORECASE)
        return self.by_handle.get(f"a{int(match.group(1))}") if match else None


def dock_bundle_ids(layout: HomeScreenLayout) -> set[str]:
    """Apps in the dock. No operation may name them, because the preview never
    changes the dock but the write path removes a named app from it."""
    ids: set[str] = set()
    for item in layout.dock:
        if item.is_app:
            ids.add(item.app.bundle_id)
        elif item.is_folder:
            ids.update(app.bundle_id for page in item.folder.pages for app in page)
    return ids


def slot_limit(layout: HomeScreenLayout) -> int:
    """24 slots per page, or more when a page of the phone already uses more."""
    return max([PAGE_SLOTS] + [page_slots(page) for page in layout.pages])


def _page_apps(item) -> list[str]:
    if item.is_app:
        return [item.app.bundle_id]
    if item.is_folder:
        return [app.bundle_id for page in item.folder.pages for app in page]
    return []


def build_handles(layout: HomeScreenLayout) -> AppHandles:
    dock = dock_bundle_ids(layout)
    handles = AppHandles()
    for page in layout.pages:
        for item in page:
            for bundle_id in _page_apps(item):
                if bundle_id not in dock:
                    handles.add(bundle_id)
    return handles


def app_group(bundle_id: str, metadata: dict[str, dict]) -> str:
    meta = metadata.get(bundle_id) or {}
    if not meta:
        return OTHER_GROUP
    if meta.get("super_category") == "System":
        return APPLE_GROUP
    return meta.get("genre") or meta.get("super_category") or OTHER_GROUP


_SUBTITLE = re.compile(r"\s*(?::|\s[-–—|]\s|•)\s*")
_MARKS = re.compile(r"[®™]")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+(?=[:,.!?])")


def _known_name(bundle_id: str, metadata: dict[str, dict]) -> str | None:
    """The App Store name, or the real name of an Apple app. None when neither is known:
    the name of an Apple app outside SYSTEM_APP_NAMES is only a guess from its bundle ID."""
    if bundle_id.startswith("com.apple."):
        return SYSTEM_APP_NAMES.get(bundle_id)
    return (metadata.get(bundle_id) or {}).get("name") or None


def _without_marks(name: str) -> str:
    """'Disneyland® Paris' -> 'Disneyland Paris', 'Chase Mobile®: Bank' -> 'Chase Mobile: Bank'."""
    return " ".join(_SPACE_BEFORE_PUNCTUATION.sub("", _MARKS.sub(" ", name)).split())


def _full_name(bundle_id: str, metadata: dict[str, dict], display_names: dict[str, str]) -> str:
    return _known_name(bundle_id, metadata) or display_names.get(bundle_id) or bundle_id


def short_name(bundle_id: str, metadata: dict[str, dict], display_names: dict[str, str]) -> str:
    """The app's name without its App Store subtitle ('Cal AI - Calorie Tracker' -> 'Cal AI')."""
    name = _without_marks(_full_name(bundle_id, metadata, display_names))
    return _SUBTITLE.split(name, maxsplit=1)[0].strip() or name


def plan_names(
    bundle_ids: list[str], metadata: dict[str, dict], display_names: dict[str, str],
) -> dict[str, str]:
    """The name of each app in the layout that the model reads. No two apps get the
    same name. An app with no known name shows its bundle ID, which tells the model
    the vendor."""
    labels: dict[str, str] = {}
    for bundle_id in bundle_ids:
        if _known_name(bundle_id, metadata):
            labels[bundle_id] = short_name(bundle_id, metadata, display_names)
            continue
        shown = display_names.get(bundle_id) or ""
        if shown and shown.casefold() != bundle_id.rsplit(".", 1)[-1].casefold():
            labels[bundle_id] = f"{shown} ({bundle_id})"
        else:
            labels[bundle_id] = bundle_id

    def full(bundle_id: str) -> str:
        return _without_marks(_full_name(bundle_id, metadata, display_names))

    for rename in (full, lambda bundle_id: f"{full(bundle_id)} ({bundle_id})"):
        counts = Counter(label.casefold() for label in labels.values())
        for bundle_id, label in list(labels.items()):
            if counts[label.casefold()] > 1:
                labels[bundle_id] = rename(bundle_id)
    return labels


def _display_names(layout: HomeScreenLayout) -> dict[str, str]:
    names: dict[str, str] = {}
    for page in [layout.dock, *layout.pages]:
        for item in page:
            if item.is_app and item.app.display_name:
                names.setdefault(item.app.bundle_id, item.app.display_name)
            elif item.is_folder:
                for folder_page in item.folder.pages:
                    for app in folder_page:
                        if app.display_name:
                            names.setdefault(app.bundle_id, app.display_name)
    return names


# --- the layout the model reads --------------------------------------------------------


def context_names(layout: HomeScreenLayout, metadata: dict[str, dict], handles: AppHandles) -> dict[str, str]:
    """plan_names() for the dock apps and the apps that a plan can move."""
    dock_apps = [item.app.bundle_id for item in layout.dock if item.is_app]
    bundle_ids = list(dict.fromkeys(dock_apps + handles.bundle_ids()))
    return plan_names(bundle_ids, metadata, _display_names(layout))


def build_plan_context(
    layout: HomeScreenLayout,
    metadata: dict[str, dict],
    handles: AppHandles,
    archive_candidates: list[dict] | None = None,
) -> str:
    """Compact layout for the plan: short IDs, apps grouped by genre."""
    now = datetime.now(timezone.utc)
    labels = context_names(layout, metadata, handles)
    dock_apps = [item.app.bundle_id for item in layout.dock if item.is_app]
    candidates = {c["bundle_id"] for c in archive_candidates or []}

    where: dict[str, str] = {}
    widgets = 0
    folder_bits = []
    for number, page in enumerate(layout.pages, start=1):
        for item in page:
            if item.is_widget:
                widgets += 1
            elif item.is_app:
                where.setdefault(item.app.bundle_id, f"p{number}")
            elif item.is_folder:
                members = _page_apps(item)
                folder_bits.append(f'"{item.folder.display_name}" p{number} ({len(members)})')
                for bundle_id in members:
                    where.setdefault(bundle_id, f'"{item.folder.display_name}"')

    dock = [labels[bundle_id] for bundle_id in dock_apps]
    page_one = []
    first_page = layout.pages[0] if layout.pages else []
    page_one_widgets = [item for item in first_page if item.is_widget]
    if page_one_widgets:
        sizes = Counter(_WIDGET_WORD[item_slots(item)] for item in page_one_widgets)
        kinds = ", ".join(f"{sizes[word]} {word}" for word in ("large", "medium", "small") if sizes[word])
        page_one.append(
            f"widgets use {page_slots(page_one_widgets)} of {PAGE_SLOTS} slots ({kinds})"
        )
    for item in first_page:
        if item.is_app and item.app.bundle_id in handles.by_bundle_id:
            bundle_id = item.app.bundle_id
            page_one.append(f"{handles.by_bundle_id[bundle_id]} {labels[bundle_id]}")
        elif item.is_folder:
            page_one.append(f'"{item.folder.display_name}"')

    phone = (
        f"PHONE: {layout.total_apps} apps on {layout.page_count} pages, "
        f"{len(layout.all_folders())} folders, {widgets} widgets"
    )
    lines = [
        today_line(),
        phone,
        "DOCK (fixed): " + (", ".join(dock) or "empty"),
        "PAGE 1 NOW: " + (", ".join(page_one) or "empty"),
        "FOLDERS NOW: " + (", ".join(folder_bits) or "none"),
        "",
    ]

    groups: dict[str, list[str]] = {}
    for bundle_id in handles.bundle_ids():
        groups.setdefault(app_group(bundle_id, metadata), []).append(bundle_id)
    for group, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"{group} ({len(members)})")
        for bundle_id in members:
            meta = metadata.get(bundle_id) or {}
            parts = [
                f"{handles.by_bundle_id[bundle_id]} {labels[bundle_id]}",
                where.get(bundle_id, "?"),
            ]
            year = stale_year(meta, now)
            if year:
                parts.append(f"upd {year}")
            if bundle_id in candidates:
                text = " ".join((meta.get("description") or "").split())[:ARCHIVE_TEXT_CHARS]
                parts.append(f'archive? "{text}"' if text else "archive?")
            lines.append("  " + ", ".join(parts))
    return "\n".join(lines)


def plan_messages(context: str, intent: str) -> tuple[str, str]:
    """(layout block, intent block). The layout comes first, so a second intent for
    the same phone reads the layout from the prompt cache."""
    return f"<layout>\n{context}\n</layout>", f"<intent>\n{intent}\n</intent>"


# --- plan expansion --------------------------------------------------------------------


@dataclass
class PlanReport:
    """What the expansion could not follow. Apps it could not place keep their place."""

    unknown_ids: list[str] = field(default_factory=list)
    unknown_groups: list[str] = field(default_factory=list)
    dropped_deletes: list[str] = field(default_factory=list)
    page_one_overflow: list[str] = field(default_factory=list)
    not_moved: list[str] = field(default_factory=list)
    dropped_operations: list[str] = field(default_factory=list)


_GENERIC_WORDS = frozenset({
    "app", "apps", "the", "and", "for", "free", "pro", "lite", "plus", "mobile", "new",
    "your", "with", "official", "by", "com", "net", "org",
})


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", str(text or "").casefold())


def gratitude_names_app(line: str, names: list[str]) -> bool:
    """True when the gratitude line names the app: its whole name, or one
    distinctive word of it. A line about another app points to a wrong ID."""
    words = _words(line)
    padded = f" {' '.join(words)} "
    word_set = set(words)
    for name in names:
        name_words = _words(name)
        if name_words and f" {' '.join(name_words)} " in padded:
            return True
        if any(len(w) >= 3 and w not in _GENERIC_WORDS and w in word_set for w in name_words):
            return True
    return False


def _clean_name(value) -> str:
    """A group or folder name as the model may quote it: 'Games (12)' or '"Social"'."""
    text = " ".join(str(value or "").split()).strip("\"'“”")
    return re.sub(r"\s*\(\d+\)$", "", text).strip()


def expand_plan(
    plan: dict,
    layout: HomeScreenLayout,
    metadata: dict[str, dict],
    handles: AppHandles | None = None,
) -> tuple[list[LayoutOperation], PlanReport]:
    """Turn a plan into operations. Every app gets at most one destination."""
    handles = handles or build_handles(layout)
    report = PlanReport()
    work = _without_raw(layout)
    plan = plan if isinstance(plan, dict) else {}
    mode = plan.get("unplaced") if plan.get("unplaced") in UNPLACED_MODES else "stay"
    names = _display_names(layout)
    labels = context_names(layout, metadata, handles)
    home = handles.bundle_ids()
    home_set = set(home)

    groups: dict[str, list[str]] = {}
    group_title: dict[str, str] = {}
    for bundle_id in home:
        group = app_group(bundle_id, metadata)
        groups.setdefault(group.casefold(), []).append(bundle_id)
        group_title.setdefault(group.casefold(), group)

    current: dict[str, list[str]] = {}  # folder name (casefold) -> movable members
    current_title: dict[str, str] = {}
    # Folders by name, the dock included. The preview finds a folder by its name and
    # looks in the dock first, so an operation names only a folder whose name is unique.
    name_count: Counter = Counter(
        item.folder.display_name.casefold() for item in layout.dock if item.is_folder
    )
    in_folder: dict[str, str] = {}  # bundle ID -> first folder that holds it
    for page in layout.pages:
        for item in page:
            if not item.is_folder:
                continue
            key = item.folder.display_name.casefold()
            name_count[key] += 1
            current_title.setdefault(key, item.folder.display_name)
            members = current.setdefault(key, [])
            for bundle_id in _page_apps(item):
                if bundle_id in home_set:
                    if bundle_id not in members:
                        members.append(bundle_id)
                    in_folder.setdefault(bundle_id, key)

    def ids(values) -> list[str]:
        out: list[str] = []
        for value in values or []:
            bundle_id = handles.lookup(value)
            if bundle_id is None:
                report.unknown_ids.append(str(value))
            elif bundle_id not in out:
                out.append(bundle_id)
        return out

    def named_apps(values) -> list[str]:
        out: list[str] = []
        for value in values or []:
            key = _clean_name(value).casefold()
            found = [source[key] for source in (groups, current) if key in source]
            if not found:
                report.unknown_groups.append(str(value))
            for members in found:
                out.extend(b for b in members if b not in out)
        return out

    dest: dict[str, tuple[str, str]] = {}

    def claim(bundle_ids, kind: str, key: str = "") -> None:
        for bundle_id in bundle_ids:
            if bundle_id in home_set and bundle_id not in dest:
                dest[bundle_id] = (kind, key)

    folder_order: list[str] = []
    folder_title: dict[str, str] = {}

    def folder_key(name) -> str | None:
        title = _clean_name(name)
        if not title:
            return None
        key = title.casefold()
        if key not in folder_title:
            folder_title[key] = current_title.get(key, title)
            folder_order.append(key)
        return key

    # 1. Deletes. A gratitude line that does not name the app points to a wrong ID.
    gratitude: dict[str, str] = {}
    for entry in plan.get("delete") or []:
        if not isinstance(entry, dict):
            continue
        for bundle_id in ids([entry.get("app")]):
            if bundle_id in dest:
                continue
            line = " ".join(str(entry.get("gratitude") or "").split())
            app_names = [
                labels.get(bundle_id, ""),
                short_name(bundle_id, metadata, names),
                _full_name(bundle_id, metadata, names),
            ]
            if line and gratitude_names_app(line, app_names):
                dest[bundle_id] = ("delete", "")
                gratitude[bundle_id] = line
            else:
                report.dropped_deletes.append(handles.by_bundle_id[bundle_id])

    # 2. The plan's folders, merged by name.
    specs: dict[str, dict[str, list]] = {}
    for entry in plan.get("folders") or []:
        if not isinstance(entry, dict):
            continue
        key = folder_key(entry.get("name"))
        if key is None:
            continue
        spec = specs.setdefault(key, {"groups": [], "apps": []})
        spec["groups"].extend(entry.get("groups") or [])
        spec["apps"].extend(entry.get("apps") or [])
    plan_folders = list(specs)

    # 3. Page 1. An app that the plan names for page 1 is never cut for a folder: in a
    # new layout, page 1 shows page_one and then the folders, and the folders that do
    # not fit go to page 2. Apps after the first 24 go to page 2.
    page_one = [b for b in ids(plan.get("page_one")) if b not in dest]
    if mode != "stay" and not page_one:
        first_page = layout.pages[0] if layout.pages else []
        loose = [item.app.bundle_id for item in first_page if item.is_app]
        page_one = [b for b in dict.fromkeys(loose) if b in home_set and b not in dest]
    claim(page_one, "page1")

    # 4. Single apps, then folders kept by name, then whole groups and folders.
    library = plan.get("app_library") if isinstance(plan.get("app_library"), dict) else {}
    for key in plan_folders:
        claim(ids(specs[key]["apps"]), "folder", key)
    claim(ids(library.get("apps")), "library")
    for key in plan_folders:
        claim(current.get(key, []), "folder", key)
    for key in plan_folders:
        claim(named_apps(specs[key]["groups"]), "folder", key)
    claim(named_apps(library.get("groups")), "library")

    # 5. The apps that the plan does not name.
    unclaimed = [b for b in home if b not in dest]
    if mode == "app_library":
        claim(unclaimed, "library")
    elif mode == "folders":
        loose_by_group: dict[str, list[str]] = {}
        for bundle_id in unclaimed:
            if bundle_id in in_folder:
                claim([bundle_id], "folder", folder_key(current_title[in_folder[bundle_id]]))
            else:
                loose_by_group.setdefault(app_group(bundle_id, metadata).casefold(), []).append(bundle_id)
        singles: list[str] = []
        for group_key, members in sorted(loose_by_group.items(), key=lambda kv: -len(kv[1])):
            if len(members) >= 2 or group_key in folder_title:
                claim(members, "folder", folder_key(group_title[group_key]))
            else:
                singles.extend(members)
        if singles:
            claim(singles, "folder", folder_key(OTHER_GROUP))

    members = {key: [b for b in home if dest.get(b) == ("folder", key)] for key in folder_order}
    deletes = [
        LayoutOperation("delete", [b], gratitude=gratitude[b])
        for b in home if dest.get(b, ("",))[0] == "delete"
    ]
    library_apps = [b for b in home if dest.get(b, ("",))[0] == "library"]
    archive = [LayoutOperation("move_to_app_library", library_apps)] if library_apps else []

    sequence = _Sequence(work, report)
    if mode == "stay":
        _stay_operations(
            sequence, handles, plan_folders, folder_title, members, current,
            current_title, name_count, [b for b in page_one if dest.get(b) == ("page1", "")],
            dest, home_set, deletes, library_apps,
        )
    else:
        page1 = [b for b in page_one if dest.get(b) == ("page1", "")]
        if not page1:
            # Something must stay on page 1 for the new layout to replace the old pages.
            for key in folder_order:
                if members[key]:
                    page1 = [members[key].pop(0)]
                    break
        candidates = deletes + archive
        if page1:
            if len(page1) <= PAGE_SLOTS:
                candidates.append(LayoutOperation("compact_to_single_page", page1))
            else:
                # 24 apps per page. The folders follow on the first page with room.
                report.page_one_overflow += [handles.by_bundle_id[b] for b in page1[PAGE_SLOTS:]]
                candidates.append(LayoutOperation("rebuild_pages", page1))
            candidates += [
                LayoutOperation("create_folder", members[key], folder_name=folder_title[key])
                for key in folder_order if members[key]
            ]
        for op in candidates:
            sequence.add(op)

    ops = sequence.ops
    problem = expansion_problem(work, ops)
    if problem:
        report.dropped_operations.append(f"all: {problem}")
        return [], report
    return ops, report


def _stay_operations(
    sequence, handles, plan_folders, folder_title, members, current,
    current_title, name_count, page_one, dest, home_set, deletes, library_apps,
) -> None:
    """A targeted change, in this order:

    1. Apps added to current folders.
    2. Renamed folders, and folders rebuilt in the place of a current folder.
    3. Deletes and App Library moves of loose page 1 apps, when page_one has apps
       and the removal empties no folder and no page. They free slots for page_one.
    4. page_one: its apps come to page 1, and page 1's other loose apps move on.
    5. New folders. While page_one still has apps that did not fit, a new folder
       goes after page 1. Otherwise it takes the first free slot.
    6. The page_one moves again, into the slots that step 5 freed.
    7. The other deletes and App Library moves.

    page_one gets page 1's free slots before a new folder does. Removals that can
    empty a folder come last, so that a folder is not emptied before a later step
    adds to it.
    """
    kept = [key for key in plan_folders if key in current and name_count[key] == 1]
    for key in kept:
        already = set(current[key])
        new = [b for b in members.get(key, []) if b not in already]
        if new:
            sequence.add(LayoutOperation("move_to_folder", new, folder_name=current_title[key]))

    new_folders = []
    for key in plan_folders:
        wanted = members.get(key, [])
        if key in kept or not wanted:
            continue
        if key in current:
            # The dock or another page folder has the same name, so an operation that
            # names this folder could find the wrong one. The folder is rebuilt in its
            # own place.
            sequence.add(LayoutOperation(
                "create_folder", wanted, folder_name=folder_title[key], old_name=current_title[key],
            ))
            continue
        # A rename is safe only when no folder has the new name yet.
        source = next((
            other for other in current
            if other != key and name_count[other] == 1 and other not in members
            and current[other] and all(dest.get(b) == ("folder", key) for b in current[other])
        ), None) if name_count[key] == 0 else None
        if source is None:
            new_folders.append(key)
            continue
        # All of one folder's apps go to a new name: rename it, then add the rest.
        candidates = [LayoutOperation(
            "rename_folder", [], folder_name=folder_title[key], old_name=current_title[source],
        )]
        new = [b for b in wanted if b not in set(current[source])]
        if new:
            candidates.append(LayoutOperation("move_to_folder", new, folder_name=folder_title[key]))
        sequence.add(*candidates)

    early = _early_removals(sequence, deletes, library_apps) if page_one else set()
    removals_first = [op for op in deletes if op.bundle_ids[0] in early]
    removals_last = [op for op in deletes if op.bundle_ids[0] not in early]
    for bucket, apps in ((removals_first, [b for b in library_apps if b in early]),
                         (removals_last, [b for b in library_apps if b not in early])):
        if apps:
            bucket.append(LayoutOperation("move_to_app_library", apps))
    for op in removals_first:
        sequence.add(op)

    moves = _PageOneMoves(sequence, page_one, dest, home_set) if page_one else None
    if moves:
        moves.run()

    for key in new_folders:
        pages = sequence.pages()
        after_page_one = bool(moves and moves.arriving and pages and live_page(pages[0]))
        sequence.add(LayoutOperation(
            "create_folder", members[key], folder_name=folder_title[key],
            target_page=1 if after_page_one else None,
        ))

    if moves:
        moves.finish()
        moves.report(handles)
    for op in removals_last:
        sequence.add(op)


def _early_removals(sequence, deletes, library_apps) -> set[str]:
    """The removed apps that are loose on page 1 and can go before page_one: taking
    them off the home screen together empties no folder and no page. An emptied folder
    or page stays until the cleanup in one preview and goes at once in the other, so a
    later operation could give two different results."""

    def emptied(layout) -> tuple[int, int]:
        folders = sum(1 for page in layout.pages for item in page if item.is_folder and not item_slots(item))
        return folders, sum(1 for page in layout.pages if not live_page(page))

    pages = sequence.pages()
    first = [item.app.bundle_id for item in pages[0] if item.is_app] if pages else []
    removed = [op.bundle_ids[0] for op in deletes] + list(library_apps)
    base = apply_preview_steps(sequence.layout, sequence.ops)
    before = emptied(base)
    early: list[str] = []
    for bundle_id in dict.fromkeys(b for b in removed if b in first):
        trial = apply_preview_steps(base, [LayoutOperation("delete", early + [bundle_id])])
        if emptied(trial) == before:
            early.append(bundle_id)
    return set(early)


class _PageOneMoves:
    """Bring page_one's apps to page 1 and move page 1's other loose apps to later
    pages with free slots. A widget uses the slots of its size. Nothing moves to a
    page after one that is empty at that step, and page 1 is never emptied while
    apps still have to arrive."""

    def __init__(self, sequence, page_one, dest, home_set):
        self.sequence = sequence
        self.page_one = page_one
        pages = sequence.pages()
        self.first = [item.app.bundle_id for item in pages[0] if item.is_app] if pages else []
        self.arriving = [b for b in page_one if b not in self.first] if pages else []
        self.leaving = [
            b for b in dict.fromkeys(self.first) if b in home_set and b not in page_one and b not in dest
        ]

    def run(self) -> None:
        self.move_in()
        self.move_out(keep_one=bool(self.arriving))
        self.move_in()
        self.move_out(keep_one=False)

    def finish(self) -> None:
        """After the new folders: they can free slots on page 1 and on later pages."""
        self.move_out(keep_one=bool(self.arriving))
        self.move_in()
        self.move_out(keep_one=False)

    def move_in(self) -> None:
        pages = self.sequence.pages()
        room = PAGE_SLOTS - page_slots(pages[0]) if pages and live_page(pages[0]) else 0
        if room > 0 and self.arriving:
            batch = self.arriving[:room]
            if self.sequence.add(LayoutOperation("move_to_page", batch, target_page=0)):
                self.arriving = self.arriving[room:]

    def move_out(self, keep_one: bool) -> None:
        index = 1
        while self.leaving:
            pages = self.sequence.pages()
            if index >= len(pages) or not all(live_page(page) for page in pages[: index + 1]):
                break
            free = PAGE_SLOTS - page_slots(pages[index])
            limit = page_items(pages[0]) - 1 if keep_one else len(self.leaving)
            count = min(free, len(self.leaving), limit)
            if count > 0:
                batch = self.leaving[:count]
                if self.sequence.add(LayoutOperation("move_to_page", batch, target_page=index)):
                    self.leaving = self.leaving[count:]
            index += 1

    def report(self, handles) -> None:
        report = self.sequence.report
        report.page_one_overflow += [handles.by_bundle_id[b] for b in self.arriving]
        report.not_moved += [handles.by_bundle_id[b] for b in self.leaving]


# --- consistency checks ----------------------------------------------------------------


def _item_key(item):
    if item.is_app:
        return item.app.bundle_id
    if item.is_folder:
        return {"folder": item.folder.display_name,
                "apps": [[app.bundle_id for app in page] for page in item.folder.pages]}
    return {"widget": item.widget.container_bundle_id, "size": item.widget.grid_size.value}


def _layout_key(layout: HomeScreenLayout) -> str:
    return json.dumps({
        "dock": [_item_key(item) for item in layout.dock],
        "pages": [[_item_key(item) for item in page] for page in layout.pages],
        "ignored": sorted(layout.ignored),
    }, sort_keys=True)


def _dock_key(layout: HomeScreenLayout) -> str:
    return json.dumps([_item_key(item) for item in layout.dock], sort_keys=True)


def _one_at_a_time(layout: HomeScreenLayout, ops: list[LayoutOperation]) -> HomeScreenLayout:
    """What `json apply` predicts: each operation previewed on the result of the last."""
    state = layout
    for op in ops:
        state = preview_operations(state, [op])
    return state


def _without_raw(layout: HomeScreenLayout) -> HomeScreenLayout:
    """The layout without its raw icon state. Previews copy the layout many times here
    and need only the state's format (a list on iOS 26)."""
    return HomeScreenLayout(
        dock=layout.dock,
        pages=layout.pages,
        ignored=list(layout.ignored),
        raw=[] if isinstance(layout.raw, list) else {},
    )


class _Sequence:
    """Operations whose preview is the same all at once and one at a time.

    The preview of all the operations (then cleanup) is what `json suggest` shows,
    and the write path gives the same result. `json apply` predicts the result one
    operation at a time, with cleanup after each. The two can differ when an
    operation empties a page or a folder that a later operation depends on. An
    operation that makes them differ is left out.
    """

    def __init__(self, layout: HomeScreenLayout, report: PlanReport):
        self.layout = layout
        self.report = report
        self.ops: list[LayoutOperation] = []
        self._one_at_a_time = layout
        self.slot_limit = slot_limit(layout)

    def add(self, *ops: LayoutOperation) -> bool:
        """Append the operations together, or none of them. Operations that fill a
        page past its 24 slots are left out too: the preview of move_to_page counts
        a widget as one item, and the stylist counts the slots of its size."""
        state = self._one_at_a_time
        for op in ops:
            state = preview_operations(state, [op])
        together = preview_operations(self.layout, self.ops + list(ops))
        if _layout_key(together) != _layout_key(state) or any(
            page_slots(page) > self.slot_limit for page in together.pages
        ):
            self.report.dropped_operations += [_describe(op) for op in ops]
            return False
        self.ops += ops
        self._one_at_a_time = state
        return True

    def pages(self) -> list:
        """Pages after the operations so far, with emptied pages still in place, as in
        the write path."""
        return apply_preview_steps(self.layout, self.ops).pages


def _describe(op: LayoutOperation) -> str:
    target = op.folder_name if op.folder_name else op.target_page
    return f"{op.action} {'' if target is None else target} ({len(op.bundle_ids)} apps)"


def expansion_problem(layout: HomeScreenLayout, ops: list[LayoutOperation]) -> str | None:
    """None when the operations keep every app. Otherwise a short description.

    The checks:
    - No operation names a dock app or an app that is not on the phone.
    - No app is in two operations.
    - After the preview, each app is on the home screen (once, unless it was there
      more than once before), or an operation deletes it or sends it to the App
      Library.
    - The dock does not change.
    - No page uses more than 24 slots, unless one did before.
    - The preview matches the prediction of `json apply`.
    """
    dock = dock_bundle_ids(layout)
    on_phone = set(layout.all_bundle_ids)
    named = [b for op in ops for b in op.bundle_ids]
    if any(b in dock for b in named):
        return "names a dock app"
    if any(b not in on_phone for b in named):
        return "names an app that is not on the phone"
    if len(named) != len(set(named)):
        return "names an app twice"
    removed = {b for op in ops if op.action in ("delete", "move_to_app_library") for b in op.bundle_ids}
    after = preview_operations(layout, ops)
    before_count = Counter(layout.all_bundle_ids)
    after_count = Counter(after.all_bundle_ids)
    for bundle_id, count in after_count.items():
        if count > max(1, before_count.get(bundle_id, 0)) or bundle_id not in before_count:
            return f"places {bundle_id} {count} times"
        if bundle_id in removed:
            return f"keeps {bundle_id} after removing it"
    for bundle_id in before_count:
        if bundle_id not in after_count and bundle_id not in removed:
            return f"loses {bundle_id}"
    if _dock_key(after) != _dock_key(layout):
        return "changes the dock"
    if any(page_slots(page) > slot_limit(layout) for page in after.pages):
        return "overfills a page"
    if _layout_key(after) != _layout_key(_one_at_a_time(layout, ops)):
        return "differs from the one-at-a-time preview"
    return None


# --- the request -----------------------------------------------------------------------


def plan_intent_operations(
    intent: str,
    layout: HomeScreenLayout,
    metadata: dict[str, dict],
    score: ScoreBreakdown | None = None,
    api_key: str | None = None,
    model: str | None = None,
    provider: str = "auto",
) -> list[LayoutOperation]:
    """AI Stylist: turn the owner's free-text intent into validated layout operations."""
    from unjiggle.obituary import identify_dead_apps

    handles = build_handles(layout)
    context = build_plan_context(layout, metadata, handles, identify_dead_apps(layout, metadata))
    layout_block, intent_block = plan_messages(context, intent)
    provider, api_key, model = resolve_route(api_key, model, provider)

    if provider == "openai":
        plan = _plan_openai(f"{layout_block}\n\n{intent_block}", api_key, model)
    else:
        plan = claude_json(
            api_key=api_key,
            model=model,
            system=INTENT_SYSTEM_PROMPT,
            user=intent_block,
            cached_prefix=layout_block,
            schema=PLAN_SCHEMA,
            effort=INTENT_EFFORT,
        )

    ops, _report = expand_plan(plan, layout, metadata, handles)
    return _parse_operations([_operation_dict(op) for op in ops], set(layout.all_bundle_ids))


def _operation_dict(op: LayoutOperation) -> dict:
    return {
        "action": op.action,
        "bundle_ids": list(op.bundle_ids),
        "target_page": op.target_page,
        "folder_name": op.folder_name,
        "old_name": op.old_name,
        "gratitude": op.gratitude,
    }


def _plan_openai(user: str, api_key: str | None, model: str) -> dict:
    import openai

    client = openai.OpenAI(api_key=api_key)
    openai_tool = {
        "type": "function",
        "function": {
            "name": INTENT_TOOL["name"],
            "description": INTENT_TOOL["description"],
            "parameters": INTENT_TOOL["input_schema"],
        },
    }
    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        tools=[openai_tool],
        tool_choice={"type": "function", "function": {"name": INTENT_TOOL["name"]}},
    )
    for choice in response.choices:
        for tc in choice.message.tool_calls or []:
            if tc.function.name == INTENT_TOOL["name"]:
                return json.loads(tc.function.arguments)
    raise RuntimeError("OpenAI did not return a submit_plan function call")
