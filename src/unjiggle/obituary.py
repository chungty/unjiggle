"""App Obituary: humorous eulogies for your dead apps."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    import anthropic
except ImportError:
    anthropic = None

from unjiggle.models import HomeScreenLayout


@dataclass
class Obituary:
    app_name: str
    bundle_id: str
    born: str | None
    died: str
    cause_of_death: str
    eulogy: str  # 2-3 sentences
    survived_by: str | None


@dataclass
class ObituaryResult:
    total_dead: int
    obituaries: list[Obituary]
    graveyard_summary: str  # One tweetable sentence


def identify_dead_apps(layout: HomeScreenLayout, metadata: dict[str, dict]) -> list[dict]:
    """Identify likely-dead apps. Uses Screen Time if available, falls back to heuristics."""
    from unjiggle.screentime import get_usage
    usage = get_usage(layout.all_bundle_ids)

    candidates = []

    for page_idx, page in enumerate(layout.pages):
        for item in page:
            if item.is_app:
                _maybe_dead(item.app.bundle_id, page_idx, False, None, None, metadata, layout, candidates, usage)
            elif item.is_folder:
                folder_size = sum(len(p) for p in item.folder.pages)
                for fpage in item.folder.pages:
                    for app in fpage:
                        _maybe_dead(
                            app.bundle_id, page_idx, True,
                            item.folder.display_name, folder_size,
                            metadata, layout, candidates, usage,
                        )

    candidates.sort(key=lambda x: -x["death_score"])
    return candidates[:15]


def _maybe_dead(
    bundle_id: str, page_idx: int, in_folder: bool,
    folder_name: str | None, folder_size: int | None,
    metadata: dict, layout: HomeScreenLayout, out: list,
    usage: dict | None = None,
) -> None:
    meta = metadata.get(bundle_id, {})
    if not meta or meta.get("super_category") == "System":
        return

    # If we have real Screen Time data, use it as a strong signal
    app_usage = (usage or {}).get(bundle_id)
    if app_usage and app_usage.avg_daily_opens >= 1.0:
        return  # App is actively used — not dead regardless of position

    score = 0
    reasons = []

    # Screen Time: not opened in 30+ days is a strong death signal
    if app_usage and app_usage.last_opened:
        days_since = (datetime.now(timezone.utc) - app_usage.last_opened).days
        if days_since >= 90:
            score += 3
            reasons.append(f"not opened in {days_since} days")
        elif days_since >= 30:
            score += 2
            reasons.append(f"last opened {days_since} days ago")

    # Page depth
    if page_idx >= 5:
        score += 3
        reasons.append(f"buried on page {page_idx + 1}")
    elif page_idx >= 3:
        score += 2
        reasons.append(f"page {page_idx + 1}")
    elif page_idx >= 2:
        score += 1

    # Folder burial
    if in_folder and folder_size and folder_size >= 12:
        score += 2
        reasons.append(f"in a {folder_size}-app folder")
    elif in_folder:
        score += 1

    # Stale App Store updates (weaker signal than Screen Time)
    last_updated = meta.get("last_updated")
    if last_updated and not app_usage:  # only use if no Screen Time data
        try:
            updated_date = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            years_stale = (datetime.now(timezone.utc) - updated_date).days / 365
            if years_stale >= 3:
                score += 3
                reasons.append(f"not updated since {updated_date.year}")
            elif years_stale >= 2:
                score += 2
                reasons.append(f"last updated {updated_date.year}")
            elif years_stale >= 1:
                score += 1
        except (ValueError, TypeError):
            pass

    # Actively-maintained popular apps on late pages (not in junk drawers)
    # are likely intentionally buried, not dead.
    cat = meta.get("super_category", "Other")
    actively_maintained = last_updated and score > 0
    if actively_maintained:
        try:
            updated_date = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            actively_maintained = (datetime.now(timezone.utc) - updated_date).days < 180
        except (ValueError, TypeError):
            actively_maintained = False

    if actively_maintained and cat in ("Social", "Entertainment") and not (in_folder and folder_size and folder_size >= 8):
        score -= 2

    if score >= 3:
        entry = {
            "bundle_id": bundle_id,
            "name": meta.get("name", bundle_id.split(".")[-1]),
            "category": meta.get("super_category", "Other"),
            "description": (meta.get("description") or "")[:150],
            "last_updated": last_updated,
            "page": page_idx + 1,
            "in_folder": in_folder,
            "death_score": score,
            "reasons": reasons,
        }
        if folder_name:
            entry["folder_name"] = folder_name
        out.append(entry)


SYSTEM_PROMPT = """\
You write obituaries for dead iPhone apps. Each obituary is 2-3 sentences, written \
in dry-wit obituary style. The humor comes from the universal human experience of \
downloading-with-ambition-then-never-opening-again.

RULES:
- Format: "AppName (born circa YEAR, died YEAR): ..."
- Be SPECIFIC to the app's actual purpose and why it was probably downloaded
- Include a "survived by" replacement app when an obvious one exists
- Cause of death should be funny and relatable, never just "user deleted it"

Great causes of death:
- "Died when the user discovered Google Translate does 90% of what a language app does"
- "Succumbed to the gravitational pull of the default Camera app"
- "Passed peacefully in a folder labeled 'Stuff' after a 3-year coma"
"""

OBITUARY_TOOL = {
    "name": "submit_obituaries",
    "description": "Submit obituaries for dead apps.",
    "input_schema": {
        "type": "object",
        "required": ["obituaries", "graveyard_summary"],
        "properties": {
            "obituaries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["bundle_id", "eulogy", "cause_of_death"],
                    "properties": {
                        "bundle_id": {"type": "string"},
                        "born": {"type": "string", "description": "Approximate era"},
                        "died": {"type": "string"},
                        "cause_of_death": {"type": "string"},
                        "eulogy": {"type": "string", "description": "Full 2-3 sentence obituary"},
                        "survived_by": {"type": "string", "description": "Replacement app, if any"},
                    },
                },
            },
            "graveyard_summary": {
                "type": "string",
                "description": "One tweetable sentence summarizing the carnage",
            },
        },
    },
}


def generate_obituaries(
    layout: HomeScreenLayout,
    metadata: dict[str, dict],
    api_key: str | None = None,
    model: str | None = None,
    provider: str = "auto",
) -> ObituaryResult:
    dead_apps = identify_dead_apps(layout, metadata)

    if not dead_apps:
        return ObituaryResult(
            total_dead=0,
            obituaries=[],
            graveyard_summary="Your phone is surprisingly well-maintained. No funerals today.",
        )

    context = _build_context(dead_apps, layout, metadata)

    if provider == "auto":
        provider = "openai" if api_key and api_key.startswith("sk-") else "anthropic"

    if provider == "openai":
        return _obituary_openai(context, dead_apps, api_key, model or "gpt-4.1")
    return _obituary_anthropic(context, dead_apps, api_key, model or "claude-sonnet-4-20250514")


def _build_context(dead_apps: list[dict], layout: HomeScreenLayout, metadata: dict) -> str:
    lines = [
        f"PHONE: {layout.total_apps} total apps, {layout.page_count} pages",
        f"DEAD APPS IDENTIFIED: {len(dead_apps)}",
        "",
    ]

    for app in dead_apps:
        lines.append(f"APP: {app['name']} ({app['bundle_id']})")
        lines.append(f"  Category: {app['category']}")
        lines.append(f"  Description: {app['description']}")
        lines.append(f"  Last updated: {app.get('last_updated', 'unknown')}")
        loc = f"Page {app['page']}"
        if app.get("in_folder"):
            loc += f", in folder \"{app.get('folder_name', '?')}\""
        lines.append(f"  Location: {loc}")
        lines.append(f"  Death signals: {', '.join(app['reasons'])}")
        lines.append("")

    # Active apps for "survived by" context
    lines.append("ACTIVE APPS (dock + page 1) for 'survived by' references:")
    for item in layout.dock:
        if item.is_app:
            meta = metadata.get(item.app.bundle_id, {})
            if meta:
                lines.append(f"  {meta.get('name', item.app.bundle_id)} [{meta.get('super_category', '?')}]")
    if layout.pages:
        for item in layout.pages[0]:
            if item.is_app:
                meta = metadata.get(item.app.bundle_id, {})
                if meta:
                    lines.append(f"  {meta.get('name', item.app.bundle_id)} [{meta.get('super_category', '?')}]")

    return "\n".join(lines)


def _obituary_anthropic(context: str, dead_apps: list[dict], api_key: str | None, model: str) -> ObituaryResult:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        tools=[OBITUARY_TOOL],
        tool_choice={"type": "tool", "name": "submit_obituaries"},
        messages=[{"role": "user", "content": f"Write obituaries for these dead apps:\n\n{context}"}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_obituaries":
            return _parse_obituaries(block.input, dead_apps)
    raise RuntimeError("LLM did not return obituaries")


def _obituary_openai(context: str, dead_apps: list[dict], api_key: str | None, model: str) -> ObituaryResult:
    import openai

    client = openai.OpenAI(api_key=api_key)
    openai_tool = {
        "type": "function",
        "function": {
            "name": OBITUARY_TOOL["name"],
            "description": OBITUARY_TOOL["description"],
            "parameters": OBITUARY_TOOL["input_schema"],
        },
    }
    response = client.chat.completions.create(
        model=model,
        max_tokens=3000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Write obituaries for these dead apps:\n\n{context}"},
        ],
        tools=[openai_tool],
        tool_choice={"type": "function", "function": {"name": "submit_obituaries"}},
    )
    for choice in response.choices:
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                if tc.function.name == "submit_obituaries":
                    return _parse_obituaries(json.loads(tc.function.arguments), dead_apps)
    raise RuntimeError("OpenAI did not return obituaries")


def _parse_obituaries(data: dict, dead_apps: list[dict]) -> ObituaryResult:
    dead_by_bid = {a["bundle_id"]: a for a in dead_apps}

    obituaries = []
    for obit in data.get("obituaries", []):
        bid = obit.get("bundle_id", "")
        app_info = dead_by_bid.get(bid, {})
        obituaries.append(Obituary(
            app_name=app_info.get("name", bid.split(".")[-1]),
            bundle_id=bid,
            born=obit.get("born"),
            died=obit.get("died", "recently"),
            cause_of_death=obit.get("cause_of_death", ""),
            eulogy=obit.get("eulogy", ""),
            survived_by=obit.get("survived_by"),
        ))

    return ObituaryResult(
        total_dead=len(dead_apps),
        obituaries=obituaries,
        graveyard_summary=data.get("graveyard_summary", f"{len(dead_apps)} apps that time forgot."),
    )
