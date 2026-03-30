"""LLM-powered home screen analysis engine.

Two-pass architecture:
  Pass 1: LLM generates narrative observations + structured intent
  Pass 2: Layout engine resolves intent into valid operations
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import anthropic

from homeboard.models import HomeScreenLayout, ScoreBreakdown


@dataclass
class LayoutOperation:
    """A single validated layout change."""
    action: str  # "move_to_app_library", "move_to_page", "create_folder", "rename_folder", "move_to_folder"
    bundle_ids: list[str] = field(default_factory=list)
    target_page: int | None = None
    folder_name: str | None = None
    old_name: str | None = None


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
You are HomeBoard's AI analysis engine. You analyze iPhone home screen layouts and produce structured observations with narrative explanations.

You receive a complete home screen layout (bundle IDs, positions, folders, widgets) enriched with App Store metadata (app name, category, description, last update date).

Your job:
1. Generate 5-7 observations grouped into tracks (cleanup, organization, optimization)
2. Each observation has a narrative (conversational, personal, insightful) and structured intent (which apps to move where)
3. Generate a personality narrative that tells the story of this phone
4. Assign an archetype label

TRACKS:
- cleanup: Removing/archiving unused, duplicate, or defunct apps
- organization: Grouping, foldering, and page restructuring
- optimization: Fine-tuning page 1, dock, and folder names

RULES:
- Reference apps by EXACT bundle ID from the input. Never invent bundle IDs.
- Be specific and personal. "You have 3 weather apps" is boring. "Dark Sky hasn't been updated since Apple acquired it in 2020. CARROT Weather is actively maintained. The built-in Weather app absorbed most of Dark Sky's features. You're carrying a ghost." is good.
- Detect patterns: duplicate-function apps, abandoned apps (last_updated years ago), apps from the same ecosystem, apps that tell a life story (kids apps, fitness apps, project-specific apps)
- The personality narrative should feel like someone who KNOWS this person, not a database report
- Observations should be ordered: cleanup first, then organization, then optimization

OUTPUT FORMAT: You must respond with a JSON object matching this exact schema.
"""

ANALYSIS_TOOL = {
    "name": "submit_analysis",
    "description": "Submit the complete home screen analysis with observations and personality narrative.",
    "input_schema": {
        "type": "object",
        "required": ["observations", "personality", "archetype"],
        "properties": {
            "observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["track", "title", "narrative", "operations"],
                    "properties": {
                        "track": {"type": "string", "enum": ["cleanup", "organization", "optimization"]},
                        "title": {"type": "string", "description": "Short title for this observation"},
                        "narrative": {"type": "string", "description": "The conversational, insightful narrative (2-4 sentences)"},
                        "operations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["action", "bundle_ids"],
                                "properties": {
                                    "action": {
                                        "type": "string",
                                        "enum": ["move_to_app_library", "move_to_page", "create_folder", "rename_folder", "move_to_folder"]
                                    },
                                    "bundle_ids": {"type": "array", "items": {"type": "string"}},
                                    "target_page": {"type": "integer", "description": "0-indexed page number for move_to_page"},
                                    "folder_name": {"type": "string", "description": "Folder name for create_folder, rename_folder, or move_to_folder"},
                                    "old_name": {"type": "string", "description": "Old folder name for rename_folder"},
                                },
                            },
                        },
                    },
                },
            },
            "personality": {"type": "string", "description": "A 2-4 sentence narrative about the person behind this phone. Personal, observational, never generic."},
            "archetype": {"type": "string", "description": "A 2-4 word archetype label (e.g., 'The Digital Archaeologist', 'The Reluctant Organizer')"},
            "stats": {
                "type": "object",
                "description": "Key statistics to highlight",
                "properties": {
                    "duplicate_groups": {"type": "string"},
                    "defunct_apps": {"type": "string"},
                    "category_spread": {"type": "string"},
                    "folder_insight": {"type": "string"},
                },
            },
        },
    },
}


def _build_context(layout: HomeScreenLayout, metadata: dict[str, dict], score: ScoreBreakdown) -> str:
    """Build the context string sent to the LLM."""
    lines = []
    lines.append(f"DEVICE LAYOUT: {layout.page_count} pages, {layout.total_apps} apps, {len(layout.all_folders())} folders")
    lines.append(f"ORGANIZATION SCORE: {score.total:.0f}/100 ({score.label})")
    lines.append(f"  Page efficiency: {score.page_efficiency:.0f}, Category coherence: {score.category_coherence:.0f}, Folder usage: {score.folder_usage:.0f}, Dock quality: {score.dock_quality:.0f}")
    lines.append(f"APP LIBRARY: {len(layout.ignored)} hidden apps")
    lines.append("")

    # Dock
    lines.append("DOCK:")
    for item in layout.dock:
        if item.is_app:
            meta = metadata.get(item.app.bundle_id, {})
            name = meta.get("name", item.app.bundle_id) if meta else item.app.bundle_id
            cat = meta.get("super_category", "?") if meta else "?"
            lines.append(f"  {item.app.bundle_id} ({name}) [{cat}]")
    lines.append("")

    # Pages
    for i, page in enumerate(layout.pages):
        lines.append(f"PAGE {i + 1}:")
        for item in page:
            if item.is_app:
                meta = metadata.get(item.app.bundle_id, {})
                if meta:
                    name = meta.get("name", item.app.bundle_id)
                    cat = meta.get("super_category", "?")
                    updated = meta.get("last_updated", "?")
                    desc = meta.get("description") or ""
                    lines.append(f"  {item.app.bundle_id} ({name}) [{cat}] updated:{updated} \"{desc[:80]}\"")
                else:
                    lines.append(f"  {item.app.bundle_id}")
            elif item.is_folder:
                app_count = sum(len(p) for p in item.folder.pages)
                folder_apps = []
                for fp in item.folder.pages:
                    for a in fp:
                        m = metadata.get(a.bundle_id, {})
                        folder_apps.append(m.get("name", a.bundle_id) if m else a.bundle_id)
                lines.append(f"  [FOLDER \"{item.folder.display_name}\"] ({app_count} apps): {', '.join(folder_apps)}")
            elif item.is_widget:
                lines.append(f"  [WIDGET {item.widget.container_bundle_id} size:{item.widget.grid_size.value}]")
        lines.append("")

    return "\n".join(lines)


def analyze(
    layout: HomeScreenLayout,
    metadata: dict[str, dict],
    score: ScoreBreakdown,
    api_key: str | None = None,
    model: str | None = None,
    provider: str = "auto",
) -> AnalysisResult:
    """Run LLM analysis on the layout. Returns structured observations.

    provider: "anthropic", "openai", or "auto" (detect from api_key prefix).
    """
    context = _build_context(layout, metadata, score)

    if provider == "auto":
        if api_key and api_key.startswith("sk-"):
            provider = "openai"
        else:
            provider = "anthropic"

    if provider == "openai":
        return _analyze_openai(layout, context, api_key, model or "gpt-4o")
    else:
        return _analyze_anthropic(layout, context, api_key, model or "claude-sonnet-4-20250514")


def _analyze_anthropic(layout, context, api_key, model) -> AnalysisResult:
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "submit_analysis"},
        messages=[
            {"role": "user", "content": f"Analyze this iPhone home screen layout:\n\n{context}"}
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_analysis":
            return _parse_result(block.input, layout)

    raise RuntimeError("Anthropic did not return a submit_analysis tool call")


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
            {"role": "user", "content": f"Analyze this iPhone home screen layout:\n\n{context}"},
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


def _parse_result(data: dict, layout: HomeScreenLayout) -> AnalysisResult:
    """Parse and validate the LLM's structured output."""
    valid_bundle_ids = set(layout.all_bundle_ids)
    valid_folder_names = {f.display_name for f in layout.all_folders()}

    observations = []
    for i, obs_data in enumerate(data.get("observations", [])):
        ops = []
        for op_data in obs_data.get("operations", []):
            # Validate bundle IDs exist
            valid_bids = [bid for bid in op_data.get("bundle_ids", []) if bid in valid_bundle_ids]
            if not valid_bids and op_data.get("action") != "rename_folder":
                continue  # Skip operations with all-invalid bundle IDs

            ops.append(LayoutOperation(
                action=op_data["action"],
                bundle_ids=valid_bids,
                target_page=op_data.get("target_page"),
                folder_name=op_data.get("folder_name"),
                old_name=op_data.get("old_name"),
            ))

        observations.append(Observation(
            track=obs_data.get("track", "cleanup"),
            title=obs_data.get("title", f"Observation {i + 1}"),
            narrative=obs_data.get("narrative", ""),
            operations=ops,
        ))

    return AnalysisResult(
        observations=observations,
        personality=data.get("personality", ""),
        archetype=data.get("archetype", "The Collector"),
        stats=data.get("stats", {}),
    )


def preview_operations(layout: HomeScreenLayout, operations: list[LayoutOperation]) -> HomeScreenLayout:
    """Apply operations to a layout copy and return the preview.

    This is the layout engine's resolution pass: it takes validated operations
    and produces a new layout state. Does NOT modify the original.
    """
    import copy
    preview = copy.deepcopy(layout)

    for op in operations:
        if op.action == "move_to_app_library":
            _remove_apps_from_layout(preview, op.bundle_ids)
            preview.ignored.extend(op.bundle_ids)

        elif op.action == "move_to_page":
            if op.target_page is not None and 0 <= op.target_page < len(preview.pages):
                items = _extract_apps_from_layout(preview, op.bundle_ids)
                page = preview.pages[op.target_page]
                if len(page) + len(items) <= 24:
                    page.extend(items)

        elif op.action == "create_folder":
            if op.folder_name:
                from homeboard.models import AppItem, FolderItem, LayoutItem
                items = _extract_apps_from_layout(preview, op.bundle_ids)
                apps = [item.app for item in items if item.is_app]
                if apps:
                    folder = LayoutItem(folder=FolderItem(
                        display_name=op.folder_name,
                        pages=[apps],
                    ))
                    if preview.pages:
                        preview.pages[0].append(folder)

        elif op.action == "rename_folder":
            if op.old_name and op.folder_name:
                for folder in preview.all_folders():
                    if folder.display_name == op.old_name:
                        folder.display_name = op.folder_name
                        break

        elif op.action == "move_to_folder":
            if op.folder_name:
                items = _extract_apps_from_layout(preview, op.bundle_ids)
                apps = [item.app for item in items if item.is_app]
                for folder in preview.all_folders():
                    if folder.display_name == op.folder_name:
                        if folder.pages:
                            folder.pages[0].extend(apps)
                        else:
                            folder.pages.append(apps)
                        break

    # Clean up empty pages
    preview.pages = [p for p in preview.pages if p]

    return preview


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
    from homeboard.models import AppItem, LayoutItem
    bid_set = set(bundle_ids)
    extracted = []
    _remove_apps_from_layout(layout, bid_set)
    for bid in bundle_ids:
        extracted.append(LayoutItem(app=AppItem(bundle_id=bid)))
    return extracted
