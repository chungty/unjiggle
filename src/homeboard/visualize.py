"""HTML visualization for HomeBoard layouts."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from homeboard.itunes import CATEGORY_COLORS
from homeboard.models import HomeScreenLayout, ScoreBreakdown

REPORT_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HomeBoard Report</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #0a0a0a; color: #e5e5e5; font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif; }

.report-card {
  width: 1080px; min-height: 1920px; margin: 0 auto;
  background: linear-gradient(180deg, #111 0%, #1a1a2e 50%, #111 100%);
  padding: 60px 50px; display: flex; flex-direction: column; gap: 40px;
}

.header { text-align: center; }
.header h1 { font-size: 28px; font-weight: 300; letter-spacing: 4px; text-transform: uppercase; color: #666; }
.header .archetype { font-size: 52px; font-weight: 700; margin-top: 16px; background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.header .score-line { font-size: 24px; color: #999; margin-top: 12px; }
.header .score-num { font-size: 72px; font-weight: 700; color: #fff; }
.header .score-label { font-size: 20px; color: #666; }

.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.stat { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; }
.stat .num { font-size: 36px; font-weight: 700; color: #fff; }
.stat .desc { font-size: 16px; color: #888; margin-top: 4px; }

.grid-section { display: flex; gap: 30px; justify-content: center; align-items: flex-start; }
.grid-container { text-align: center; }
.grid-container h3 { font-size: 16px; color: #666; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 16px; }
.phone-frame {
  background: #1a1a1a; border: 2px solid #333; border-radius: 40px;
  padding: 40px 16px 30px; width: 320px; display: inline-block;
}
.page-label { font-size: 11px; color: #555; text-align: center; margin-bottom: 8px; }
.icon-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 16px; }
.icon {
  width: 56px; height: 56px; border-radius: 13px; display: flex; align-items: center; justify-content: center;
  font-size: 8px; color: rgba(255,255,255,0.7); text-align: center; overflow: hidden; line-height: 1.1;
  padding: 2px;
}
.icon img { width: 100%; height: 100%; border-radius: 13px; object-fit: cover; }
.icon-label { font-size: 9px; color: #888; text-align: center; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; width: 56px; }
.page-dots { text-align: center; margin-top: 8px; }
.page-dots span { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #444; margin: 0 3px; }
.page-dots span.active { background: #fff; }

.dock { display: flex; gap: 8px; justify-content: center; background: rgba(255,255,255,0.06); border-radius: 20px; padding: 8px 12px; margin-top: 12px; }

.observations { padding: 0 10px; }
.observation { background: rgba(255,255,255,0.03); border-left: 3px solid #60a5fa; padding: 16px 20px; margin-bottom: 12px; border-radius: 0 12px 12px 0; }
.observation p { font-size: 16px; line-height: 1.6; color: #ccc; }

.personality { text-align: center; padding: 30px; font-size: 18px; line-height: 1.8; color: #999; font-style: italic; }

.footer { text-align: center; padding: 20px; }
.footer .url { font-size: 16px; color: #555; letter-spacing: 2px; }

.category-legend { display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; padding: 10px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #888; }
.legend-dot { width: 10px; height: 10px; border-radius: 3px; }

.before-after-header { display: flex; justify-content: space-between; align-items: center; padding: 0 40px; }
.delta { font-size: 48px; font-weight: 700; text-align: center; }
.delta .arrow { color: #22c55e; }
</style>
</head>
<body>
<div class="report-card">

<div class="header">
  <h1>HomeBoard</h1>
  <div class="archetype">{{ archetype }}</div>
  <div class="score-line">Organization Score</div>
  <div class="score-num">{{ score_total|int }}</div>
  <div class="score-label">{{ score_label }}</div>
</div>

<div class="stats">
  <div class="stat"><div class="num">{{ total_apps }}</div><div class="desc">apps on home screen</div></div>
  <div class="stat"><div class="num">{{ page_count }}</div><div class="desc">pages</div></div>
  <div class="stat"><div class="num">{{ folder_count }}</div><div class="desc">folders</div></div>
  <div class="stat"><div class="num">{{ app_library_count }}</div><div class="desc">in App Library</div></div>
</div>

{% if observations %}
<div class="observations">
  {% for obs in observations %}
  <div class="observation"><p>{{ obs }}</p></div>
  {% endfor %}
</div>
{% endif %}

<div class="grid-section">
  <div class="grid-container">
    <h3>Page 1</h3>
    <div class="phone-frame">
      <div class="icon-grid">
        {% for item in page1_items[:24] %}
        <div>
          <div class="icon" style="background: {{ item.color }};">
            {% if item.icon_url %}
            <img src="{{ item.icon_url }}" alt="{{ item.name }}">
            {% else %}
            {{ item.name[:6] }}
            {% endif %}
          </div>
          <div class="icon-label">{{ item.name }}</div>
        </div>
        {% endfor %}
      </div>
      <div class="page-dots">
        {% for i in range(page_count) %}
        <span {% if i == 0 %}class="active"{% endif %}></span>
        {% endfor %}
      </div>
      <div class="dock">
        {% for item in dock_items %}
        <div>
          <div class="icon" style="background: {{ item.color }};">
            {% if item.icon_url %}
            <img src="{{ item.icon_url }}" alt="{{ item.name }}">
            {% else %}
            {{ item.name[:6] }}
            {% endif %}
          </div>
        </div>
        {% endfor %}
      </div>
    </div>
  </div>
</div>

<div class="category-legend">
  {% for cat, color in categories.items() %}
  <div class="legend-item">
    <div class="legend-dot" style="background: {{ color }};"></div>
    {{ cat }} ({{ category_counts.get(cat, 0) }})
  </div>
  {% endfor %}
</div>

{% if personality %}
<div class="personality">{{ personality }}</div>
{% endif %}

<div class="footer">
  <div class="url">homeboard.app</div>
</div>

</div>
</body>
</html>
""")


def _item_to_viz(item, metadata: dict) -> dict:
    """Convert a LayoutItem to a visualization dict."""
    if item.is_app:
        meta = metadata.get(item.app.bundle_id, {})
        cat = meta.get("super_category", "Other") if meta else "Other"
        return {
            "name": meta.get("name", item.app.bundle_id.split(".")[-1]) if meta else item.app.bundle_id.split(".")[-1],
            "color": CATEGORY_COLORS.get(cat, CATEGORY_COLORS["Other"]),
            "icon_url": meta.get("icon_url") if meta else None,
            "category": cat,
        }
    if item.is_folder:
        return {
            "name": f"📁 {item.folder.display_name}",
            "color": "#374151",
            "icon_url": None,
            "category": "Folder",
        }
    if item.is_widget:
        return {
            "name": "Widget",
            "color": "#1f2937",
            "icon_url": None,
            "category": "Widget",
        }
    return {"name": "?", "color": "#374151", "icon_url": None, "category": "Unknown"}


def generate_report(
    layout: HomeScreenLayout,
    metadata: dict[str, dict],
    score: ScoreBreakdown,
    archetype: str = "The Collector",
    observations: list[str] | None = None,
    personality: str | None = None,
) -> str:
    """Generate the HTML report card."""
    from collections import Counter

    # Build category counts
    cat_counter = Counter()
    for bid in layout.all_bundle_ids:
        meta = metadata.get(bid, {})
        cat = meta.get("super_category", "Other") if meta else "Other"
        cat_counter[cat] += 1

    # Build page 1 items
    page1_items = []
    if layout.pages:
        for item in layout.pages[0]:
            page1_items.append(_item_to_viz(item, metadata))

    # Build dock items
    dock_items = [_item_to_viz(item, metadata) for item in layout.dock]

    return REPORT_TEMPLATE.render(
        archetype=archetype,
        score_total=score.total,
        score_label=score.label,
        total_apps=layout.total_apps,
        page_count=layout.page_count,
        folder_count=len(layout.all_folders()),
        app_library_count=len(layout.ignored),
        page1_items=page1_items,
        dock_items=dock_items,
        categories={k: v for k, v in CATEGORY_COLORS.items() if cat_counter.get(k, 0) > 0},
        category_counts=dict(cat_counter),
        observations=observations or [],
        personality=personality,
    )


def save_report(html: str, path: Path) -> None:
    """Save the HTML report to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
