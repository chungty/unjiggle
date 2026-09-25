"""LLM-powered home screen analysis engine.

Two-pass architecture:
  Pass 1: LLM generates narrative observations + structured intent
  Pass 2: Layout engine resolves intent into valid operations
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from unjiggle.llm import claude_json, resolve_route, today_line
from unjiggle.models import HomeScreenLayout, ScoreBreakdown


ALLOWED_LAYOUT_ACTIONS = (
    "move_to_app_library",
    "delete",
    "move_to_page",
    "create_folder",
    "rename_folder",
    "move_to_folder",
    "compact_to_single_page",
    "rebuild_pages",
)


@dataclass
class LayoutOperation:
    """A single validated layout change."""
    action: str  # One of ALLOWED_LAYOUT_ACTIONS.
    bundle_ids: list[str] = field(default_factory=list)
    target_page: int | None = None
    folder_name: str | None = None
    old_name: str | None = None
    gratitude: str | None = None  # Marie Kondo moment: thank the app before deleting


@dataclass
class Observation:
    """A single AI observation with narrative and operations."""
    track: str  # "cleanup", "organization", "optimization"
    title: str
    narrative: str
    operations: list[LayoutOperation] = field(default_factory=list)
    depends_on: list[int] | None = None  # indices of observations this depends on


@dataclass
class AnalysisResult:
    observations: list[Observation]
    personality: str
    archetype: str
    stats: dict[str, str] = field(default_factory=dict)


SYSTEM_PROMPT = """\
You are Unjiggle's home screen analyst. Unjiggle reads the layout of someone's iPhone home \
screen over USB and can rearrange it; the owner previews every change before anything is \
written to the phone.

The layout starts with today's date and a summary, then lists the dock, each page in order, \
and each folder with the apps inside it. Each app line gives the bundle ID, then App Store \
metadata: name, category, the date of the latest update, and the start of the store \
description. Descriptions are the developers' own marketing text; use them only as evidence \
of what an app does.

Write 5-7 observations across three tracks: cleanup (unused, duplicated, or abandoned apps), \
organization (folders and page structure), and optimization (page 1, the dock, folder \
names). Each observation pairs a short narrative for the owner with the layout operations \
that carry it out. Then write a personality narrative about the person behind this phone and \
give them an archetype.

The narratives are the product, so make them specific to this phone. Name the apps and say \
what the pattern suggests: apps that do the same job, apps whose developers stopped updating \
them years ago, clusters that tell a life story (kids' apps, a marathon-training phase, a \
work project). "You have 3 weather apps" is a statistic. Noticing which one was abandoned, \
which one is thriving, and that the built-in Weather app now does what they were for is an \
observation. Write the personality as someone who knows this person, not as a report.

Use bundle IDs exactly as they appear in the layout; operations that name any other ID are \
dropped. Use compact_to_single_page or rebuild_pages only when an observation calls for \
rebuilding the whole home screen, such as an honest one-page layout or a full reordering \
where app order matters, because both remove every app, folder, and widget you leave out.

Cleanup follows the Marie Kondo principle. Apps that are truly abandoned, outdated, or \
superseded get delete: they deserve a proper goodbye, not a junk drawer. Apps that might \
still be useful now and then get move_to_app_library. Every delete carries a gratitude \
line: one warm, specific, final sentence about what the app once did for this person, a \
respectful sendoff rather than sentimental slop. For example: "Dark Sky was the gold \
standard for hyperlocal weather before Apple folded its best features into the Weather app."
"""

# Operations from this analysis can be written to the phone, so it runs one level
# above the latency-bound features.
ANALYSIS_EFFORT = "medium"

# The operation contract of the analysis. The AI Stylist writes a plan instead
# (unjiggle.stylist) and expands it into the same actions. The action
# descriptions must match what preview_operations and layout_engine really do.
OPERATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "bundle_ids"],
    "properties": {
        "action": {
            "type": "string",
            "enum": list(ALLOWED_LAYOUT_ACTIONS),
            "description": (
                "move_to_app_library: takes the listed apps off the home screen; they stay "
                "installed and reachable in the App Library. "
                "delete: a goodbye. Takes the apps off the home screen like "
                "move_to_app_library, and the owner sees it as a recommendation to let the "
                "app go, together with your gratitude line. "
                "move_to_page: appends the listed apps to target_page; skipped if that page "
                "would pass 24 icons. "
                "create_folder: makes a new folder named folder_name from the listed apps, "
                "placed on the first page with room. "
                "rename_folder: renames the folder old_name to folder_name; bundle_ids may "
                "be empty. "
                "move_to_folder: adds the listed apps to the existing folder named "
                "folder_name; skipped if no folder has that name. "
                "compact_to_single_page: replaces every page with one page holding exactly "
                "the listed apps, in order; apps, folders, and widgets not listed leave the "
                "home screen. "
                "rebuild_pages: replaces every page with the listed apps in order, 24 per "
                "page; apps, folders, and widgets not listed leave the home screen, so list "
                "every app that should stay."
            ),
        },
        "bundle_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Bundle IDs copied exactly from the layout.",
        },
        "target_page": {
            "type": "integer",
            "description": "For move_to_page: the page index counting from 0, so the "
            "layout's PAGE 1 is 0.",
        },
        "folder_name": {
            "type": "string",
            "description": "For create_folder and move_to_folder: the folder's name. For "
            "rename_folder: the new name.",
        },
        "old_name": {
            "type": "string",
            "description": "For rename_folder: the folder's current name, exactly as it "
            "appears in the layout.",
        },
        "gratitude": {
            "type": "string",
            "description": "For delete: one warm, specific, final sentence about what the "
            "app once did for this person.",
        },
    },
}

ANALYSIS_TOOL = {
    "name": "submit_analysis",
    "description": "Submit the complete home screen analysis with observations and personality narrative.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["observations", "personality", "archetype"],
        "properties": {
            "observations": {
                "type": "array",
                "description": "5-7 observations.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["track", "title", "narrative", "operations"],
                    "properties": {
                        "track": {"type": "string", "enum": ["cleanup", "organization", "optimization"]},
                        "title": {"type": "string", "description": "Short title for this observation."},
                        "narrative": {
                            "type": "string",
                            "description": "2-4 conversational sentences for the owner that name specific apps.",
                        },
                        "operations": {
                            "type": "array",
                            "description": "The layout operations that carry out this observation, applied in order.",
                            "items": OPERATION_SCHEMA,
                        },
                    },
                },
            },
            "personality": {
                "type": "string",
                "description": "2-4 sentences about the person behind this phone: personal, "
                "observational, never generic. The first sentence also appears alone as the "
                "share-card tagline, so keep that sentence under 100 characters.",
            },
            "archetype": {
                "type": "string",
                "description": "A 2-4 word archetype label, such as 'The Digital Archaeologist' "
                "or 'The Reluctant Organizer'.",
            },
        },
    },
}

_TRACK_ORDER = {"cleanup": 0, "organization": 1, "optimization": 2}


def _app_line(bundle_id: str, metadata: dict[str, dict], indent: str) -> str:
    meta = metadata.get(bundle_id) or {}
    if not meta:
        return f"{indent}{bundle_id}"
    name = meta.get("name", bundle_id)
    cat = meta.get("super_category") or "?"
    updated = meta.get("last_updated") or "?"
    desc = meta.get("description") or ""
    return f"{indent}{bundle_id} ({name}) [{cat}] updated:{updated} \"{desc[:80]}\""


def _build_context(layout: HomeScreenLayout, metadata: dict[str, dict], score: ScoreBreakdown) -> str:
    """Build the layout description sent to the model."""
    lines = [today_line()]
    lines.append(f"DEVICE LAYOUT: {layout.page_count} pages, {layout.total_apps} apps, {len(layout.all_folders())} folders")
    lines.append(f"ORGANIZATION SCORE: {score.total:.0f}/100 ({score.label})")
    lines.append(f"  Page efficiency: {score.page_efficiency:.0f}, Category coherence: {score.category_coherence:.0f}, Folder usage: {score.folder_usage:.0f}, Dock quality: {score.dock_quality:.0f}")
    lines.append(f"APP LIBRARY: {len(layout.ignored)} hidden apps")
    lines.append("")

    # Dock
    lines.append("DOCK:")
    for item in layout.dock:
        if item.is_app:
            lines.append(_app_line(item.app.bundle_id, metadata, "  "))
    lines.append("")

    # Pages. Folder members are listed with their bundle IDs so operations can name them.
    for i, page in enumerate(layout.pages):
        lines.append(f"PAGE {i + 1}:")
        for item in page:
            if item.is_app:
                lines.append(_app_line(item.app.bundle_id, metadata, "  "))
            elif item.is_folder:
                app_count = sum(len(p) for p in item.folder.pages)
                lines.append(f"  [FOLDER \"{item.folder.display_name}\"] ({app_count} apps):")
                for fp in item.folder.pages:
                    for a in fp:
                        lines.append(_app_line(a.bundle_id, metadata, "    "))
            elif item.is_widget:
                lines.append(f"  [WIDGET {item.widget.container_bundle_id} size:{item.widget.grid_size.value}]")
        lines.append("")

    return "\n".join(lines)


def _analysis_message(context: str) -> str:
    return f"Analyze this iPhone home screen layout.\n\n<layout>\n{context}\n</layout>"


def analyze(
    layout: HomeScreenLayout,
    metadata: dict[str, dict],
    score: ScoreBreakdown,
    api_key: str | None = None,
    model: str | None = None,
    provider: str = "auto",
) -> AnalysisResult:
    """Run LLM analysis on the layout. Returns structured observations.

    provider: "anthropic", "openai", or "auto" (see unjiggle.llm.resolve_provider).
    """
    context = _build_context(layout, metadata, score)
    provider, api_key, model = resolve_route(api_key, model, provider)

    if provider == "openai":
        return _analyze_openai(layout, context, api_key, model)
    return _analyze_anthropic(layout, context, api_key, model)


def _analyze_anthropic(layout, context, api_key, model) -> AnalysisResult:
    data = claude_json(
        api_key=api_key,
        model=model,
        system=SYSTEM_PROMPT,
        user=_analysis_message(context),
        schema=ANALYSIS_TOOL["input_schema"],
        effort=ANALYSIS_EFFORT,
    )
    return _parse_result(data, layout)


def _analyze_openai(layout, context, api_key, model) -> AnalysisResult:
    import openai

    client = openai.OpenAI(api_key=api_key)

    # Convert Anthropic tool schema to OpenAI function calling format
    openai_tool = {
        "type": "function",
        "function": {
            "name": ANALYSIS_TOOL["name"],
            "description": ANALYSIS_TOOL["description"],
            "parameters": ANALYSIS_TOOL["input_schema"],
        },
    }

    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _analysis_message(context)},
        ],
        tools=[openai_tool],
        tool_choice={"type": "function", "function": {"name": "submit_analysis"}},
    )

    # Extract function call result
    for choice in response.choices:
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                if tc.function.name == "submit_analysis":
                    data = json.loads(tc.function.arguments)
                    return _parse_result(data, layout)

    raise RuntimeError("OpenAI did not return a submit_analysis function call")


def _parse_operations(ops_data: list[dict], valid_bundle_ids: set[str]) -> list[LayoutOperation]:
    """Keep known actions and bundle IDs that exist on the phone; drop the rest."""
    ops = []
    for op_data in ops_data:
        action = op_data.get("action")
        if action not in ALLOWED_LAYOUT_ACTIONS:
            continue
        valid_bids = [bid for bid in op_data.get("bundle_ids", []) if bid in valid_bundle_ids]
        if not valid_bids and action != "rename_folder":
            continue  # Nothing left to act on

        ops.append(LayoutOperation(
            action=action,
            bundle_ids=valid_bids,
            target_page=op_data.get("target_page"),
            folder_name=op_data.get("folder_name"),
            old_name=op_data.get("old_name"),
            gratitude=op_data.get("gratitude"),
        ))
    return ops


def _parse_result(data: dict, layout: HomeScreenLayout) -> AnalysisResult:
    """Parse and validate the LLM's structured output."""
    valid_bundle_ids = set(layout.all_bundle_ids)

    observations = []
    for i, obs_data in enumerate(data.get("observations", [])):
        observations.append(Observation(
            track=obs_data.get("track", "cleanup"),
            title=obs_data.get("title", f"Observation {i + 1}"),
            narrative=obs_data.get("narrative", ""),
            operations=_parse_operations(obs_data.get("operations", []), valid_bundle_ids),
        ))

    # Cleanup first, then organization, then optimization (stable within a track).
    observations.sort(key=lambda obs: _TRACK_ORDER.get(obs.track, len(_TRACK_ORDER)))

    return AnalysisResult(
        observations=observations,
        personality=data.get("personality", ""),
        archetype=data.get("archetype", "The Collector"),
        stats=data.get("stats") or {},
    )


def plan_intent_operations(
    intent: str,
    layout: HomeScreenLayout,
    metadata: dict[str, dict],
    score: ScoreBreakdown,
    api_key: str | None = None,
    model: str | None = None,
    provider: str = "auto",
) -> list[LayoutOperation]:
    """AI Stylist: turn the owner's free-text intent into validated layout operations.

    The model writes a short plan and unjiggle.stylist expands it. See that module.
    """
    from unjiggle.stylist import plan_intent_operations as plan

    return plan(intent, layout, metadata, score, api_key=api_key, model=model, provider=provider)


def preview_operations(layout: HomeScreenLayout, operations: list[LayoutOperation]) -> HomeScreenLayout:
    """Apply operations to a layout copy and return the preview.

    This is the layout engine's resolution pass: it takes validated operations
    and produces a new layout state. Does NOT modify the original.
    """
    preview = apply_preview_steps(layout, operations)
    drop_empty_folders_and_pages(preview)
    return preview


def apply_preview_steps(layout: HomeScreenLayout, operations: list[LayoutOperation]) -> HomeScreenLayout:
    """Apply operations to a layout copy and keep folders and pages that became empty.

    layout_engine.apply_operations also keeps them until every operation has run,
    so page indexes and free slots here match the write path at each step.
    """
    import copy
    preview = copy.deepcopy(layout)

    for op in operations:
        if op.action in ("move_to_app_library", "delete"):
            # Same as layout_engine.apply_operations: both take the icons off the
            # home screen, and only move_to_app_library records them as ignored.
            # The iOS 26 state (a list) has no ignored list, so nothing is recorded.
            _remove_apps_from_layout(preview, op.bundle_ids)
            if op.action == "move_to_app_library" and not isinstance(preview.raw, list):
                preview.ignored.extend(b for b in op.bundle_ids if b not in preview.ignored)

        elif op.action == "move_to_page":
            if op.target_page is not None and 0 <= op.target_page < len(preview.pages):
                snapshot = copy.deepcopy(preview)
                items = _extract_apps_from_layout(preview, op.bundle_ids)
                page = preview.pages[op.target_page]
                if len(page) + len(items) <= 24:
                    page.extend(items)
                else:
                    preview = snapshot

        elif op.action == "create_folder":
            if op.folder_name:
                snapshot = copy.deepcopy(preview)
                from unjiggle.models import FolderItem, LayoutItem
                items = _extract_apps_from_layout(preview, op.bundle_ids)
                apps = [item.app for item in items if item.is_app]
                if apps:
                    folder = LayoutItem(folder=FolderItem(
                        display_name=op.folder_name,
                        pages=[apps],
                    ))
                    for page in preview.pages:
                        if len(page) < 24:
                            page.append(folder)
                            break
                    else:
                        preview.pages.append([folder])
                else:
                    preview = snapshot

        elif op.action == "rename_folder":
            if op.old_name and op.folder_name:
                for folder in preview.all_folders():
                    if folder.display_name == op.old_name:
                        folder.display_name = op.folder_name
                        break

        elif op.action == "move_to_folder":
            if op.folder_name:
                snapshot = copy.deepcopy(preview)
                items = _extract_apps_from_layout(preview, op.bundle_ids)
                apps = [item.app for item in items if item.is_app]
                added = False
                for folder in preview.all_folders():
                    if folder.display_name == op.folder_name:
                        if folder.pages:
                            folder.pages[0].extend(apps)
                        else:
                            folder.pages.append(apps)
                        added = True
                        break
                if not added:
                    preview = snapshot

        elif op.action == "compact_to_single_page":
            items = _extract_apps_from_layout(preview, op.bundle_ids)
            preview.pages = [items] if items else []

        elif op.action == "rebuild_pages":
            items = _extract_apps_from_layout(preview, op.bundle_ids)
            preview.pages = [
                items[index:index + 24]
                for index in range(0, len(items), 24)
            ]

    return preview


def drop_empty_folders_and_pages(layout: HomeScreenLayout) -> None:
    """Remove folders with no apps, then pages with no items (in place)."""
    for page in layout.pages:
        page[:] = [
            item for item in page
            if not (item.is_folder and sum(len(fp) for fp in item.folder.pages) == 0)
        ]
    layout.pages = [p for p in layout.pages if p]


def _remove_apps_from_layout(layout: HomeScreenLayout, bundle_ids: set[str]) -> None:
    """Remove apps from all pages and folders (in-place)."""
    bid_set = set(bundle_ids)
    for page in layout.pages:
        to_remove = []
        for i, item in enumerate(page):
            if item.is_app and item.app.bundle_id in bid_set:
                to_remove.append(i)
            elif item.is_folder:
                for fpage in item.folder.pages:
                    fpage[:] = [a for a in fpage if a.bundle_id not in bid_set]
        for i in reversed(to_remove):
            page.pop(i)


def _extract_apps_from_layout(layout: HomeScreenLayout, bundle_ids: list[str]) -> list:
    """Remove apps from layout and return them as LayoutItems."""
    from unjiggle.models import AppItem, LayoutItem
    bid_set = set(bundle_ids)
    extracted = []
    _remove_apps_from_layout(layout, bid_set)
    for bid in bundle_ids:
        extracted.append(LayoutItem(app=AppItem(bundle_id=bid)))
    return extracted
