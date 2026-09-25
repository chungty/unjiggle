"""App Obituary: humorous eulogies for your dead apps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from unjiggle.llm import (
    DEFAULT_ANTHROPIC_WRITING_MODEL,
    claude_json,
    openai_function_json,
    resolve_route,
    today_line,
)
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
You write obituaries for the dead apps on someone's iPhone, for Unjiggle's App Obituary. \
The owner reads them and often shares a card showing the first three. The style is a dry-wit \
newspaper obituary, and the humor comes from the universal experience of downloading an app \
with big ambitions and never opening it again.

The list starts with today's date. Each dead app has a number, then its name, category, \
the year of its last App Store update, where it is buried, and the signals that it is dead. \
The next line gives the start of its App Store description. Descriptions are the \
developers' own marketing text. Use them only as evidence of what the app did. At the end \
are the owner's active apps, from the dock and page 1.

Write one obituary per listed app, in the order given, and identify each app by its number. Make each one specific to what the \
app was for and why this person probably downloaded it, and draw the joke from that app's \
own details rather than from a stock line. Name a survivor when one of their active apps or \
a built-in iPhone feature obviously took over the job. A cause of death should be funny and \
relatable, never just "user deleted it". Two causes in the right register, to show the tone \
rather than to reuse: "The gravitational pull of the default Camera app." and "Discovering \
that Google Translate does 90% of what a language app does."

For apps tied to health conditions, pregnancy or fertility, grief, addiction recovery, or \
religion, keep the joke on the app, not on the person's life.
"""

# Short, single-shot creative writing that the owner waits on: keep thinking brief.
OBITUARY_EFFORT = "low"

OBITUARY_TOOL = {
    "name": "submit_obituaries",
    "description": "Submit obituaries for dead apps.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["obituaries", "graveyard_summary"],
        "properties": {
            "obituaries": {
                "type": "array",
                "description": "One obituary per listed app, in the order given.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["app", "born", "died", "eulogy", "cause_of_death"],
                    "properties": {
                        "app": {
                            "type": "integer",
                            "description": "The app's number in the list.",
                        },
                        "born": {
                            "type": "string",
                            "description": "Approximate year or era the app was first "
                            "released, such as '2014' or 'circa 2014'. An estimate is fine.",
                        },
                        "died": {
                            "type": "string",
                            "description": "Year of its last sign of life: when it was last "
                            "opened if the death signals say so, otherwise its last update.",
                        },
                        "cause_of_death": {
                            "type": "string",
                            "description": "A short cause of death that reads well on its "
                            "own and after the label 'Cause of death:'.",
                        },
                        "eulogy": {
                            "type": "string",
                            "description": "Two or three sentences. The app's name, dates and "
                            "cause of death are shown separately, so leave them out.",
                        },
                        "survived_by": {
                            "type": "string",
                            "description": "The app or built-in iPhone feature that took over "
                            "its job, if there is an obvious one.",
                        },
                    },
                },
            },
            "graveyard_summary": {
                "type": "string",
                "description": "One sentence on the whole graveyard, shown on the share card.",
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

    # Rule-based fallback when no API key
    if not api_key:
        return _obituary_rule_based(dead_apps)

    context = _build_context(dead_apps, layout, metadata)
    provider, api_key, model = resolve_route(api_key, model, provider, DEFAULT_ANTHROPIC_WRITING_MODEL)

    if provider == "openai":
        return _obituary_openai(context, dead_apps, api_key, model)
    return _obituary_anthropic(context, dead_apps, api_key, model)


def _obituary_rule_based(dead_apps: list[dict]) -> ObituaryResult:
    """Generate template-based obituaries. No LLM needed."""
    _CAUSES = {
        "Social": [
            "Lost to the endless scroll of its competitors.",
            "The group chat moved somewhere else.",
            "Replaced by the social network you're actually addicted to.",
        ],
        "Entertainment": [
            "Replaced by whatever's trending now.",
            "The algorithm stopped being interesting.",
            "You found a better way to avoid your responsibilities.",
        ],
        "Games": [
            "Died when the novelty wore off.",
            "One-starred by boredom.",
            "The dopamine well ran dry.",
        ],
        "Health": [
            "Succumbed to the couch. The app lived longer than the habit.",
            "Your motivation expired before the free trial did.",
            "Downloaded on a Monday. Forgotten by Wednesday.",
        ],
        "Education": [
            "Downloaded with ambition, abandoned by Thursday.",
            "The streak died. Then the app did.",
            "You learned enough to know you weren't going to learn more.",
        ],
        "Finance": [
            "The market moved on. So did you.",
            "Stopped checking after it only showed bad news.",
            "Replaced by not looking at your portfolio.",
        ],
        "Shopping": [
            "Outcompeted by the app you actually buy things from.",
            "You found one delivery app and stuck with it.",
        ],
        "Productivity": [
            "Ironic cause of death: you were too busy to use it.",
            "Replaced by whatever came pre-installed.",
            "Downloaded on a Sunday planning spree. Forgotten by Monday.",
        ],
        "Utilities": [
            "Replaced by something the phone already does.",
            "Apple built it in. The third party never recovered.",
            "Outlived its usefulness by approximately two iOS updates.",
        ],
        "Travel": [
            "Died between trips. Never reopened.",
            "Used once in 2019. Still installed for reasons unknown.",
        ],
        "News": [
            "Lost in the noise.",
            "You started doomscrolling somewhere else instead.",
        ],
        "Other": [
            "Forgotten. No further details available.",
            "Nobody remembers downloading this.",
        ],
    }

    obituaries = []
    for app in dead_apps[:10]:
        name = app["name"]
        cat = app.get("category", "Other")
        reasons = app.get("reasons", [])
        page = app.get("page", "?")

        # Estimate birth year from last_updated minus 2-3 years
        born = None
        died = "recently"
        last_updated = app.get("last_updated")
        if last_updated:
            try:
                updated = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                died = str(updated.year)
                born = str(max(2015, updated.year - 2))
            except (ValueError, TypeError):
                pass

        import hashlib
        causes = _CAUSES.get(cat, _CAUSES["Other"])
        # Deterministic pick based on app name (same app = same cause every time)
        idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % len(causes)
        cause = causes[idx]
        location = f"page {page}"
        if app.get("in_folder"):
            location = f"a folder on page {page}"

        # Eulogy is the narrative context; cause is the witty one-liner (kept distinct)
        eulogy = f"Found on {location}."
        if "not updated since" in " ".join(reasons):
            eulogy += f" Last updated: {died}."
        elif "not opened in" in " ".join(reasons):
            days = next((r for r in reasons if "not opened in" in r), "")
            eulogy += f" {days.capitalize()}." if days else ""
        elif "last opened" in " ".join(reasons):
            days = next((r for r in reasons if "last opened" in r), "")
            eulogy += f" {days.capitalize()}." if days else ""
        else:
            eulogy += f" Buried since {died}." if died != "recently" else ""

        obituaries.append(Obituary(
            app_name=name,
            bundle_id=app["bundle_id"],
            born=born,
            died=died,
            cause_of_death=cause,
            eulogy=eulogy,
            survived_by=None,
        ))

    cats = [a.get("category", "Other") for a in dead_apps]
    from collections import Counter
    top_cat = Counter(cats).most_common(1)
    cat_note = f", mostly {top_cat[0][0].lower()}" if top_cat else ""
    summary = f"{len(dead_apps)} apps that didn't make it{cat_note}."

    return ObituaryResult(
        total_dead=len(dead_apps),
        obituaries=obituaries,
        graveyard_summary=summary,
    )


def _build_context(dead_apps: list[dict], layout: HomeScreenLayout, metadata: dict) -> str:
    lines = [
        today_line(),
        f"PHONE: {layout.total_apps} total apps, {layout.page_count} pages",
        f"DEAD APPS IDENTIFIED: {len(dead_apps)}",
        "",
    ]

    for number, app in enumerate(dead_apps, start=1):
        updated = str(app.get("last_updated") or "")[:4] or "unknown"
        loc = f"page {app['page']}"
        if app.get("in_folder"):
            loc += f", folder \"{app.get('folder_name', '?')}\""
        signals = ", ".join(app["reasons"]) or "none"
        lines.append(
            f"{number}. {app['name']} | {app['category']} | last update {updated} | {loc} | {signals}"
        )
        description = " ".join((app.get("description") or "").split())
        if description:
            lines.append(f"   {description}")

    # Active apps for "survived by" context
    active = []
    for item in [*layout.dock, *(layout.pages[0] if layout.pages else [])]:
        if item.is_app:
            meta = metadata.get(item.app.bundle_id, {})
            if meta:
                active.append(f"{meta.get('name', item.app.bundle_id)} [{meta.get('super_category', '?')}]")
    lines.append("")
    lines.append("ACTIVE APPS (dock + page 1) for 'survived by' references: " + ", ".join(active))

    return "\n".join(lines)


def _obituary_message(context: str) -> str:
    return f"Write obituaries for these dead apps.\n\n<graveyard>\n{context}\n</graveyard>"


def _obituary_anthropic(context: str, dead_apps: list[dict], api_key: str | None, model: str) -> ObituaryResult:
    data = claude_json(
        api_key=api_key,
        model=model,
        system=SYSTEM_PROMPT,
        user=_obituary_message(context),
        schema=OBITUARY_TOOL["input_schema"],
        effort=OBITUARY_EFFORT,
    )
    return _parse_obituaries(data, dead_apps)


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
            {"role": "user", "content": _obituary_message(context)},
        ],
        tools=[openai_tool],
        tool_choice={"type": "function", "function": {"name": "submit_obituaries"}},
    )
    return _parse_obituaries(openai_function_json(response, "submit_obituaries"), dead_apps)


def _parse_obituaries(data: dict, dead_apps: list[dict]) -> ObituaryResult:
    dead_by_bid = {a["bundle_id"]: a for a in dead_apps}
    # The model names each app by its number in the list. A reply that names the
    # app by bundle ID also works: the ID is matched ignoring surrounding
    # whitespace and letter case. Each obituary carries the candidate's own ID.
    canonical_bid = {bid.casefold(): bid for bid in dead_by_bid}

    obituaries = []
    seen: set[str] = set()
    for obit in data.get("obituaries", []):
        bid = _candidate_bundle_id(obit, dead_apps, canonical_bid)
        # Only the candidates we sent, once each: clients key obituaries by bundle ID.
        if bid is None or bid in seen:
            continue
        seen.add(bid)
        app_info = dead_by_bid[bid]
        obituaries.append(Obituary(
            app_name=app_info.get("name", bid.split(".")[-1]),
            bundle_id=bid,
            born=obit.get("born"),
            died=_died(obit.get("died")),
            cause_of_death=obit.get("cause_of_death", ""),
            eulogy=obit.get("eulogy", ""),
            survived_by=obit.get("survived_by"),
        ))

    return ObituaryResult(
        total_dead=len(dead_apps),
        obituaries=obituaries,
        graveyard_summary=data.get("graveyard_summary", f"{len(dead_apps)} apps that time forgot."),
    )


def _died(value) -> str:
    """The death year in an obituary, as text. Claude's structured output always
    gives a string. The OpenAI function call is not strict: it can leave the year
    out, give null or give 2019 as a number. A year that is missing or blank shows
    as "recently"."""
    if isinstance(value, str):
        return value.strip() or "recently"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return "recently"


def _app_number(value) -> int | None:
    """The candidate number in an obituary. Claude's structured output gives an
    integer. The OpenAI function call is not strict and can give "3" or 3.0."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return int(number) if number.is_integer() else None


def _candidate_bundle_id(obit: dict, dead_apps: list[dict], canonical_bid: dict[str, str]) -> str | None:
    number = _app_number(obit.get("app"))
    if number is not None:
        return dead_apps[number - 1]["bundle_id"] if 1 <= number <= len(dead_apps) else None
    return canonical_bid.get(str(obit.get("bundle_id") or "").strip().casefold())
