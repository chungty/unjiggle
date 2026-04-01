"""Swipe Tax Calculator: the physical cost of your disorganized layout."""

from __future__ import annotations

from dataclasses import dataclass

from unjiggle.models import HomeScreenLayout

# Estimated daily opens by position (heuristic — no Screen Time needed)
_POSITION_OPENS = {
    0: 15,    # dock
    1: 5,     # page 1
    2: 2,     # page 2
    3: 1,     # page 3
    4: 0.5,   # page 4
}
_DEEP_PAGE_OPENS = 0.2

# Category frequency multipliers
_CATEGORY_FREQ = {
    "Social": 2.0,
    "Entertainment": 1.5,
    "News": 1.2,
    "Productivity": 1.3,
    "Games": 1.0,
    "System": 1.0,
    "Utilities": 0.8,
    "Finance": 0.7,
    "Health": 0.6,
    "Shopping": 0.5,
    "Education": 0.4,
    "Travel": 0.3,
    "Other": 0.5,
}


@dataclass
class AppSwipeCost:
    name: str
    bundle_id: str
    category: str
    page: int  # 0 = dock
    in_folder: bool
    swipes_to_reach: int
    estimated_daily_opens: float
    annual_wasted_swipes: int


@dataclass
class SwipeTaxResult:
    total_annual_swipes: int
    optimal_annual_swipes: int
    savings: int
    worst_offenders: list[AppSwipeCost]
    per_app: list[AppSwipeCost]
    headline: str


def compute_swipe_tax(layout: HomeScreenLayout, metadata: dict[str, dict]) -> SwipeTaxResult:
    # Try to get real usage data from Screen Time (graceful fallback to heuristics)
    from unjiggle.screentime import get_usage
    usage = get_usage(layout.all_bundle_ids)

    all_costs: list[AppSwipeCost] = []

    # Dock
    for item in layout.dock:
        if item.is_app:
            cost = _cost(item.app.bundle_id, 0, False, metadata, usage)
            if cost:
                all_costs.append(cost)

    # Pages
    for page_idx, page in enumerate(layout.pages):
        for item in page:
            if item.is_app:
                cost = _cost(item.app.bundle_id, page_idx + 1, False, metadata, usage)
                if cost:
                    all_costs.append(cost)
            elif item.is_folder:
                for fpage in item.folder.pages:
                    for app in fpage:
                        cost = _cost(app.bundle_id, page_idx + 1, True, metadata, usage)
                        if cost:
                            all_costs.append(cost)

    total = sum(int(c.estimated_daily_opens * c.swipes_to_reach * 365) for c in all_costs)
    optimal = _optimal_swipes(all_costs)
    savings = total - optimal

    worst = sorted(all_costs, key=lambda c: -c.annual_wasted_swipes)[:10]

    return SwipeTaxResult(
        total_annual_swipes=total,
        optimal_annual_swipes=optimal,
        savings=savings,
        worst_offenders=worst,
        per_app=all_costs,
        headline=f"You waste {savings:,} swipes per year",
    )


def _cost(bundle_id: str, page: int, in_folder: bool, metadata: dict, usage: dict | None = None) -> AppSwipeCost | None:
    meta = metadata.get(bundle_id, {})
    if not meta:
        return None

    name = meta.get("name", bundle_id.split(".")[-1])
    category = meta.get("super_category", "Other")

    swipes = max(0, page - 1)
    if in_folder:
        swipes += 1

    # Use real Screen Time data if available, otherwise heuristic
    real_usage = (usage or {}).get(bundle_id)
    if real_usage and real_usage.avg_daily_opens > 0:
        daily_opens = real_usage.avg_daily_opens
    else:
        base_opens = _POSITION_OPENS.get(page, _DEEP_PAGE_OPENS)
        if in_folder:
            base_opens *= 0.5
        daily_opens = base_opens * _CATEGORY_FREQ.get(category, 0.5)

    annual_wasted = int(daily_opens * swipes * 365)

    return AppSwipeCost(
        name=name,
        bundle_id=bundle_id,
        category=category,
        page=page,
        in_folder=in_folder,
        swipes_to_reach=swipes,
        estimated_daily_opens=round(daily_opens, 1),
        annual_wasted_swipes=annual_wasted,
    )


def _optimal_swipes(all_costs: list[AppSwipeCost]) -> int:
    """Optimal layout: highest-frequency apps on page 1/dock."""
    sorted_apps = sorted(all_costs, key=lambda c: -c.estimated_daily_opens)
    dock_slots = 4
    page_slots = 24
    total = 0

    for i, app in enumerate(sorted_apps):
        if i < dock_slots:
            opt_swipes = 0
        else:
            opt_page = (i - dock_slots) // page_slots + 1
            opt_swipes = max(0, opt_page - 1)
        total += int(app.estimated_daily_opens * opt_swipes * 365)

    return total
