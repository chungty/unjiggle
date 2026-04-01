"""Personality Mirror: brutally accurate personality profile from your app collection."""

from __future__ import annotations

import json
from dataclasses import dataclass

try:
    import anthropic
except ImportError:
    anthropic = None

from unjiggle.models import HomeScreenLayout, ScoreBreakdown


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
You are a brutally perceptive personality analyst. You analyze someone's iPhone app \
collection and generate a personality profile that feels like a psychic reading — \
accurate, specific, and slightly mean (like a comedy roast, not a horoscope).

You receive a complete app list with App Store metadata. Find the STORY in their apps:
- Life phases encoded in the graveyard (the sourdough phase, the day-trading phase, \
the "I'm going to learn Japanese" phase)
- Contradictions (4 meditation apps + TikTok = commitment issues with self-improvement)
- Guilty pleasures hiding in folders on page 7
- What the collection says about who this person IS

RULES:
- Be SPECIFIC. Reference actual app names from the input. Never be generic.
- Be WITTY. Make the user laugh and feel seen, not attacked. Comedy roast, not cruelty.
- Be ACCURATE. Only claim things supported by the data. Don't invent apps.
- Phases should be inferred from clusters of apps in similar categories.
- Contradictions should highlight genuine tensions (productivity vs. distraction, etc.)
"""

MIRROR_TOOL = {
    "name": "submit_mirror",
    "description": "Submit the personality mirror analysis.",
    "input_schema": {
        "type": "object",
        "required": ["roast", "phases", "contradictions", "guilty_pleasure", "one_line"],
        "properties": {
            "roast": {
                "type": "string",
                "description": "Main personality roast: 3-5 sentences, devastating but loving. Reference specific apps.",
            },
            "phases": {
                "type": "array",
                "description": "2-4 detected life phases",
                "items": {
                    "type": "object",
                    "required": ["name", "apps", "narrative"],
                    "properties": {
                        "name": {"type": "string"},
                        "apps": {"type": "array", "items": {"type": "string"}},
                        "narrative": {"type": "string"},
                    },
                },
            },
            "contradictions": {
                "type": "array",
                "description": "1-3 contradictions",
                "items": {
                    "type": "object",
                    "required": ["tension", "apps_a", "apps_b", "roast"],
                    "properties": {
                        "tension": {"type": "string"},
                        "apps_a": {"type": "array", "items": {"type": "string"}},
                        "apps_b": {"type": "array", "items": {"type": "string"}},
                        "roast": {"type": "string"},
                    },
                },
            },
            "guilty_pleasure": {
                "type": "string",
                "description": "One-liner about a guilty pleasure app or pattern",
            },
            "one_line": {
                "type": "string",
                "description": "A single tweetable sentence that captures the whole profile.",
            },
        },
    },
}


def _build_context(layout: HomeScreenLayout, metadata: dict[str, dict], score: ScoreBreakdown) -> str:
    lines = [
        f"PHONE OVERVIEW: {layout.total_apps} apps, {layout.page_count} pages, {len(layout.all_folders())} folders",
        f"ORGANIZATION SCORE: {score.total:.0f}/100 ({score.label})",
        "",
    ]

    # Group apps by category
    by_category: dict[str, list[str]] = {}
    for bid in layout.all_bundle_ids:
        meta = metadata.get(bid, {})
        if not meta:
            continue
        cat = meta.get("super_category", "Other")
        name = meta.get("name", bid.split(".")[-1])
        desc = (meta.get("description") or "")[:100]
        updated = meta.get("last_updated", "?")
        by_category.setdefault(cat, []).append(f"{name} (updated: {updated}) — {desc}")

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

    if provider == "auto":
        provider = "openai" if api_key.startswith("sk-") else "anthropic"

    if provider == "openai":
        return _mirror_openai(context, api_key, model or "gpt-4.1")
    return _mirror_anthropic(context, api_key, model or "claude-sonnet-4-20250514")


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


def _mirror_anthropic(context: str, api_key: str | None, model: str) -> MirrorResult:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[MIRROR_TOOL],
        tool_choice={"type": "tool", "name": "submit_mirror"},
        messages=[{"role": "user", "content": f"Analyze this person's app collection:\n\n{context}"}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_mirror":
            return _parse_mirror(block.input)
    raise RuntimeError("LLM did not return a submit_mirror tool call")


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
            {"role": "user", "content": f"Analyze this person's app collection:\n\n{context}"},
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


def _parse_mirror(data: dict) -> MirrorResult:
    phases = [
        LifePhase(name=p.get("name", ""), apps=p.get("apps", []), narrative=p.get("narrative", ""))
        for p in data.get("phases", [])
    ]
    contradictions = [
        Contradiction(
            tension=c.get("tension", ""),
            apps_a=c.get("apps_a", []),
            apps_b=c.get("apps_b", []),
            roast=c.get("roast", ""),
        )
        for c in data.get("contradictions", [])
    ]
    return MirrorResult(
        roast=data.get("roast", ""),
        phases=phases,
        contradictions=contradictions,
        guilty_pleasure=data.get("guilty_pleasure", ""),
        one_line=data.get("one_line", ""),
    )
