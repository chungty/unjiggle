"""Personality Mirror: brutally accurate personality profile from your app collection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from unjiggle.llm import (
    DEFAULT_ANTHROPIC_WRITING_MODEL,
    claude_json,
    resolve_route,
    stale_year,
    today_line,
)
from unjiggle.models import HomeScreenLayout, ScoreBreakdown

# The start of each store description that the Mirror reads. Built-in Apple apps
# have no description.
DESCRIPTION_CHARS = 60


@dataclass
class LifePhase:
    name: str  # e.g., "The Sourdough Phase"
    apps: list[str]
    narrative: str


@dataclass
class Contradiction:
    tension: str  # e.g., "Self-improvement vs. Doomscrolling"
    apps_a: list[str]
    apps_b: list[str]
    roast: str


@dataclass
class MirrorResult:
    roast: str  # Main personality roast (3-5 sentences)
    phases: list[LifePhase]
    contradictions: list[Contradiction]
    guilty_pleasure: str
    one_line: str  # Tweetable summary


SYSTEM_PROMPT = """\
You write Unjiggle's Personality Mirror: a reading of someone based on the apps on their \
iPhone and where those apps live. It should land like a psychic reading that is accurate, \
specific, and slightly mean: a comedy roast, not a horoscope. The reader is the phone's \
owner, and people share the one-liner and the start of the roast as an image, so write like \
a friend who knows them too well. They should laugh and feel seen, not attacked. Read who \
this person is from what they installed, kept, and buried, and aim the jokes at their habits \
and abandoned ambitions (four meditation apps next to TikTok, say, or games hiding in a \
folder on page 7) rather than at their identity. The best material is specific to this phone.

The app list starts with today's date and groups the apps by category. Each app has its \
name, then "last update" and a year if the app has had no App Store update for 18 months, \
then the start of its store description. Then come the dock, the apps buried on page 5 and \
later, and any folder of 10 or more apps. Descriptions are the developers' own marketing \
text. Use them only as evidence of what an app does. Life phases come from \
clusters of related apps; contradictions are genuine tensions between apps they kept. Ground \
every claim in the list, and name only apps that appear in it.

Some apps reveal things people don't joke about in public: health conditions and \
medication, mental health, pregnancy and fertility, sexual orientation, religion, addiction \
recovery, grief, legal or money trouble. Leave those apps out of the roast rather than guess \
about the person behind them.
"""

# Short, single-shot creative writing that the owner waits on: keep thinking brief.
MIRROR_EFFORT = "low"

MIRROR_TOOL = {
    "name": "submit_mirror",
    "description": "Submit the personality mirror analysis.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["roast", "phases", "contradictions", "guilty_pleasure", "one_line"],
        "properties": {
            "roast": {
                "type": "string",
                "description": "The main roast: 3-5 sentences, devastating but loving, that "
                "name specific apps. The share card shows only the first two sentences, so "
                "they have to land on their own.",
            },
            "phases": {
                "type": "array",
                "description": "2-4 life phases: clusters of related apps that mark a period "
                "or an ambition.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "apps", "narrative"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "A short title, different from every other phase's.",
                        },
                        "apps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "App names spelled as in the list, most telling first.",
                        },
                        "narrative": {
                            "type": "string",
                            "description": "One or two sentences on what this phase says about them.",
                        },
                    },
                },
            },
            "contradictions": {
                "type": "array",
                "description": "1-3 genuine tensions between apps they kept.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["tension", "apps_a", "apps_b", "roast"],
                    "properties": {
                        "tension": {
                            "type": "string",
                            "description": "A short label naming both sides, different from "
                            "every other contradiction's.",
                        },
                        "apps_a": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Apps on the first side, spelled as in the list.",
                        },
                        "apps_b": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Apps on the second side, spelled as in the list.",
                        },
                        "roast": {
                            "type": "string",
                            "description": "One or two sentences roasting the tension.",
                        },
                    },
                },
            },
            "guilty_pleasure": {
                "type": "string",
                "description": "One sentence about a guilty-pleasure app or pattern.",
            },
            "one_line": {
                "type": "string",
                "description": "One sentence that captures the whole profile and reads well "
                "out of context. It is shown on the share card and copied for posting.",
            },
        },
    },
}


def _build_context(layout: HomeScreenLayout, metadata: dict[str, dict], score: ScoreBreakdown) -> str:
    lines = [
        today_line(),
        f"PHONE OVERVIEW: {layout.total_apps} apps, {layout.page_count} pages, {len(layout.all_folders())} folders",
        f"ORGANIZATION SCORE: {score.total:.0f}/100 ({score.label})",
        "",
    ]

    # Group apps by category, once per app.
    now = datetime.now(timezone.utc)
    by_category: dict[str, list[str]] = {}
    for bid in dict.fromkeys(layout.all_bundle_ids):
        meta = metadata.get(bid, {})
        if not meta:
            continue
        cat = meta.get("super_category", "Other")
        parts = [meta.get("name", bid.split(".")[-1])]
        year = stale_year(meta, now)
        if year:
            parts.append(f"last update {year}")
        desc = " ".join((meta.get("description") or "").split())[:DESCRIPTION_CHARS]
        if desc:
            parts.append(desc)
        by_category.setdefault(cat, []).append(" | ".join(parts))

    for cat, apps in sorted(by_category.items(), key=lambda x: -len(x[1])):
        lines.append(f"{cat.upper()} ({len(apps)} apps):")
        for app in apps:
            lines.append(f"  {app}")
        lines.append("")

    # Dock
    dock_names = []
    for item in layout.dock:
        if item.is_app:
            meta = metadata.get(item.app.bundle_id, {})
            dock_names.append(meta.get("name", item.app.bundle_id) if meta else item.app.bundle_id)
    lines.append(f"DOCK: {', '.join(dock_names)}")

    # Apps buried deep
    if layout.page_count >= 5:
        buried = []
        for page_idx in range(4, layout.page_count):
            for item in layout.pages[page_idx]:
                if item.is_app:
                    meta = metadata.get(item.app.bundle_id, {})
                    buried.append(meta.get("name", item.app.bundle_id) if meta else item.app.bundle_id)
        if buried:
            lines.append(f"BURIED ON PAGES 5+: {', '.join(buried[:20])}")

    # Junk-drawer folders
    for folder in layout.all_folders():
        total = sum(len(p) for p in folder.pages)
        if total >= 10:
            apps_in = []
            for fp in folder.pages:
                for a in fp:
                    m = metadata.get(a.bundle_id, {})
                    apps_in.append(m.get("name", a.bundle_id) if m else a.bundle_id)
            lines.append(f"JUNK DRAWER \"{folder.display_name}\" ({total} apps): {', '.join(apps_in[:10])}...")

    return "\n".join(lines)


def generate_mirror(
    layout: HomeScreenLayout,
    metadata: dict[str, dict],
    score: ScoreBreakdown,
    api_key: str | None = None,
    model: str | None = None,
    provider: str = "auto",
) -> MirrorResult:
    # Rule-based fallback when no API key is available
    if not api_key:
        return _mirror_rule_based(layout, metadata, score)

    context = _build_context(layout, metadata, score)
    provider, api_key, model = resolve_route(api_key, model, provider, DEFAULT_ANTHROPIC_WRITING_MODEL)

    if provider == "openai":
        return _mirror_openai(context, api_key, model)
    return _mirror_anthropic(context, api_key, model)


def _mirror_rule_based(layout: HomeScreenLayout, metadata: dict[str, dict], score: ScoreBreakdown) -> MirrorResult:
    """Generate a personality profile using pattern detection. No LLM needed."""

    by_cat: dict[str, list[str]] = {}
    for bid in layout.all_bundle_ids:
        meta = metadata.get(bid, {})
        if not meta:
            continue
        cat = meta.get("super_category", "Other")
        name = meta.get("name", bid.split(".")[-1])
        by_cat.setdefault(cat, []).append(name)

    total = layout.total_apps
    pages = layout.page_count
    folders = len(layout.all_folders())

    # Detect phases (clusters of 3+ apps in same category)
    phases = []
    if len(by_cat.get("Health", [])) >= 3:
        apps = by_cat["Health"]
        phases.append(LifePhase(
            "The Fitness Phase",
            apps[:4],
            f"{len(apps)} health and fitness apps. The ambition was real.",
        ))
    if len(by_cat.get("Education", [])) >= 2:
        apps = by_cat["Education"]
        phases.append(LifePhase(
            "The Learning Phase",
            apps[:4],
            f"{len(apps)} education apps. You were going to learn something.",
        ))
    if len(by_cat.get("Finance", [])) >= 3:
        apps = by_cat["Finance"]
        phases.append(LifePhase(
            "The Finance Phase",
            apps[:4],
            f"{len(apps)} finance apps. You were going to get rich, or at least track where the money went.",
        ))
    if len(by_cat.get("Games", [])) >= 4:
        apps = by_cat["Games"]
        phases.append(LifePhase(
            "The Gaming Phase",
            apps[:4],
            f"{len(apps)} games. Your phone knows your secrets.",
        ))

    # Detect contradictions
    contradictions = []
    health_apps = by_cat.get("Health", [])
    social_apps = by_cat.get("Social", [])
    entertainment_apps = by_cat.get("Entertainment", [])
    shopping_apps = by_cat.get("Shopping", [])
    productivity_apps = by_cat.get("Productivity", [])

    if len(health_apps) >= 2 and len(entertainment_apps) >= 2:
        contradictions.append(Contradiction(
            "Self-Improvement vs. Distraction",
            health_apps[:3],
            entertainment_apps[:3],
            f"{len(health_apps)} wellness apps and {len(entertainment_apps)} entertainment apps. The duality of man.",
        ))
    if len(productivity_apps) >= 3 and len(shopping_apps) >= 2:
        contradictions.append(Contradiction(
            "Productivity vs. Shopping",
            productivity_apps[:3],
            shopping_apps[:3],
            f"You have {len(productivity_apps)} productivity apps and {len(shopping_apps)} shopping apps. Getting things done, and buying things.",
        ))

    # Build the roast
    roast_parts = []
    if total >= 150:
        roast_parts.append(f"{total} apps across {pages} pages.")
    if folders >= 10:
        roast_parts.append(f"{folders} folders — you've tried to organize, but the entropy is winning.")
    elif folders <= 2 and pages >= 5:
        roast_parts.append(f"{pages} pages with almost no folders. Bold strategy.")
    if len(health_apps) >= 3 and len(social_apps) >= 3:
        roast_parts.append(f"You have {len(health_apps)} health apps and {len(social_apps)} social apps competing for your attention.")

    roast = " ".join(roast_parts) if roast_parts else f"{total} apps across {pages} pages. Your phone has layers."

    # Guilty pleasure
    games = by_cat.get("Games", [])
    guilty = f"{games[0]} hiding on your phone." if games else "No games found. Suspicious."

    # One-liner
    stats = []
    for cat, apps in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        if cat not in ("System", "Other", "Utilities") and len(apps) >= 3:
            stats.append(f"{len(apps)} {cat.lower()} apps")
    stats_str = ", ".join(stats[:3])
    one_line = f"{total} apps. {stats_str}. Your phone is a biography you didn't mean to write."

    return MirrorResult(
        roast=roast,
        phases=phases[:4],
        contradictions=contradictions[:2],
        guilty_pleasure=guilty,
        one_line=one_line,
    )


def _mirror_message(context: str) -> str:
    return f"Analyze this person's app collection.\n\n<apps>\n{context}\n</apps>"


def _mirror_anthropic(context: str, api_key: str | None, model: str) -> MirrorResult:
    data = claude_json(
        api_key=api_key,
        model=model,
        system=SYSTEM_PROMPT,
        user=_mirror_message(context),
        schema=MIRROR_TOOL["input_schema"],
        effort=MIRROR_EFFORT,
    )
    return _parse_mirror(data)


def _mirror_openai(context: str, api_key: str | None, model: str) -> MirrorResult:
    import openai

    client = openai.OpenAI(api_key=api_key)
    openai_tool = {
        "type": "function",
        "function": {
            "name": MIRROR_TOOL["name"],
            "description": MIRROR_TOOL["description"],
            "parameters": MIRROR_TOOL["input_schema"],
        },
    }
    response = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _mirror_message(context)},
        ],
        tools=[openai_tool],
        tool_choice={"type": "function", "function": {"name": "submit_mirror"}},
    )
    for choice in response.choices:
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                if tc.function.name == "submit_mirror":
                    return _parse_mirror(json.loads(tc.function.arguments))
    raise RuntimeError("OpenAI did not return a submit_mirror function call")


def _unique_by(items: list[dict], key: str) -> list[dict]:
    """Drop items whose ``key`` repeats an earlier one; clients use it as an identity."""
    seen: set[str] = set()
    unique = []
    for item in items:
        value = str(item.get(key, "")).strip().casefold()
        if value in seen:
            continue
        seen.add(value)
        unique.append(item)
    return unique


def _parse_mirror(data: dict) -> MirrorResult:
    phases = [
        LifePhase(name=p.get("name", ""), apps=p.get("apps", []), narrative=p.get("narrative", ""))
        for p in _unique_by(data.get("phases", []), "name")
    ]
    contradictions = [
        Contradiction(
            tension=c.get("tension", ""),
            apps_a=c.get("apps_a", []),
            apps_b=c.get("apps_b", []),
            roast=c.get("roast", ""),
        )
        for c in _unique_by(data.get("contradictions", []), "tension")
    ]
    return MirrorResult(
        roast=data.get("roast", ""),
        phases=phases,
        contradictions=contradictions,
        guilty_pleasure=data.get("guilty_pleasure", ""),
        one_line=data.get("one_line", ""),
    )
