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
@keyframes scoreReveal {
  0% { stroke-dashoffset: 283; }
  100% { stroke-dashoffset: {{ 283 - (score_total|int / 100 * 283) }}; }
}
@keyframes fadeUp {
  0% { opacity: 0; transform: translateY(20px); }
  100% { opacity: 1; transform: translateY(0); }
}
@keyframes glowPulse {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 0.85; }
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #0a0a0a; color: #e5e5e5;
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif;
}

.report-card {
  width: 1080px; min-height: 1920px; margin: 0 auto;
  background: #0a0a0a;
  position: relative; overflow: hidden;
  display: flex; flex-direction: column; align-items: center;
}

/* === Ambient background glow from user's category colors === */
.report-card::before {
  content: '';
  position: absolute; top: -200px; left: 50%; transform: translateX(-50%);
  width: 900px; height: 900px;
  background: radial-gradient(ellipse at 30% 40%, {{ glow_color_1 }}33 0%, transparent 60%),
              radial-gradient(ellipse at 70% 60%, {{ glow_color_2 }}28 0%, transparent 55%),
              radial-gradient(ellipse at 50% 30%, {{ glow_color_3 }}1a 0%, transparent 70%);
  filter: blur(80px);
  animation: glowPulse 6s ease-in-out infinite;
  pointer-events: none; z-index: 0;
}

/* === Brand watermark === */
.brand {
  font-size: 13px; font-weight: 400; letter-spacing: 6px; text-transform: uppercase;
  color: rgba(255,255,255,0.2); text-align: center;
  padding-top: 48px; padding-bottom: 8px;
  position: relative; z-index: 1;
}

/* === Hero section: archetype + phone + score === */
.hero {
  position: relative; z-index: 1;
  text-align: center; padding: 0 50px;
  display: flex; flex-direction: column; align-items: center;
}

.archetype {
  font-size: 58px; font-weight: 800; line-height: 1.1;
  margin-bottom: 10px;
  background: linear-gradient(135deg, {{ glow_color_1 }}, {{ glow_color_2 }}, {{ glow_color_3 }});
  background-size: 200% 200%;
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -1px;
}

.hero-stats {
  font-size: 18px; color: rgba(255,255,255,0.4); letter-spacing: 0.5px;
  margin-bottom: 36px;
}
.hero-stats strong { color: rgba(255,255,255,0.7); font-weight: 600; }

/* === Phone + Score composite === */
.phone-score-composite {
  position: relative; display: inline-block;
}

/* Glow behind the phone */
.phone-glow {
  position: absolute;
  top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: 500px; height: 700px;
  background: radial-gradient(ellipse, {{ glow_color_1 }}20 0%, {{ glow_color_2 }}10 40%, transparent 70%);
  filter: blur(60px);
  pointer-events: none; z-index: 0;
}

.phone-frame {
  position: relative; z-index: 1;
  background: rgba(20,20,20,0.95);
  border: 2.5px solid rgba(255,255,255,0.12);
  border-radius: 48px;
  padding: 50px 22px 36px;
  width: 400px;
  display: inline-block;
  box-shadow: 0 0 0 1px rgba(255,255,255,0.05),
              0 25px 60px rgba(0,0,0,0.5),
              0 0 120px {{ glow_color_1 }}15;
}

/* Dynamic Island notch */
.phone-frame::before {
  content: '';
  position: absolute; top: 14px; left: 50%; transform: translateX(-50%);
  width: 120px; height: 32px;
  background: #000; border-radius: 20px;
}

.icon-grid {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 10px; margin-bottom: 16px;
  justify-items: center;
}
.icon-cell { text-align: center; }
.icon {
  width: 64px; height: 64px; border-radius: 15px;
  display: flex; align-items: center; justify-content: center;
  font-size: 9px; color: rgba(255,255,255,0.6); text-align: center;
  overflow: hidden; line-height: 1.1; padding: 2px;
}
.icon img { width: 100%; height: 100%; border-radius: 15px; object-fit: cover; }
.icon-label {
  font-size: 10px; color: rgba(255,255,255,0.5); text-align: center;
  margin-top: 4px; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; width: 64px;
}

.page-dots { text-align: center; margin-top: 10px; }
.page-dots span {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: rgba(255,255,255,0.2); margin: 0 3px;
}
.page-dots span.active { background: rgba(255,255,255,0.8); }

.dock {
  display: flex; gap: 10px; justify-content: center;
  background: rgba(255,255,255,0.06); border-radius: 24px;
  padding: 10px 16px; margin-top: 14px;
}

/* === Score ring: floats over bottom-right of phone === */
.score-badge {
  position: absolute; bottom: -30px; right: -30px; z-index: 2;
  width: 120px; height: 120px;
}
.score-ring-bg {
  fill: none; stroke: rgba(255,255,255,0.08); stroke-width: 6;
}
.score-ring-fill {
  fill: none; stroke: url(#scoreGradient); stroke-width: 6;
  stroke-linecap: round;
  stroke-dasharray: 283;
  stroke-dashoffset: {{ 283 - (score_total|int / 100 * 283) }};
  transform: rotate(-90deg); transform-origin: center;
  animation: scoreReveal 1.5s ease-out;
}
.score-badge-num {
  font-size: 36px; font-weight: 800; fill: #fff;
  text-anchor: middle; dominant-baseline: central;
}
.score-badge-label {
  font-size: 10px; fill: rgba(255,255,255,0.4);
  text-anchor: middle; text-transform: uppercase; letter-spacing: 1px;
}

/* === Category legend === */
.category-legend {
  display: flex; flex-wrap: wrap; gap: 14px; justify-content: center;
  padding: 32px 60px 20px; position: relative; z-index: 1;
  max-width: 700px;
}
.legend-item {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; color: rgba(255,255,255,0.45);
}
.legend-dot { width: 10px; height: 10px; border-radius: 4px; }

/* === Score breakdown section === */
.score-section {
  width: 100%; padding: 0 80px;
  position: relative; z-index: 1;
}
.score-section-title {
  font-size: 14px; font-weight: 500; letter-spacing: 3px;
  text-transform: uppercase; color: rgba(255,255,255,0.25);
  text-align: center; margin-bottom: 24px;
}
.score-bars { display: flex; flex-direction: column; gap: 16px; }
.score-bar-row {
  display: flex; align-items: center; gap: 16px;
}
.score-bar-label {
  font-size: 14px; color: rgba(255,255,255,0.5); width: 160px;
  text-align: right; flex-shrink: 0;
}
.score-bar-track {
  flex: 1; height: 8px; background: rgba(255,255,255,0.06);
  border-radius: 4px; overflow: hidden;
}
.score-bar-fill {
  height: 100%; border-radius: 4px;
  background: linear-gradient(90deg, {{ glow_color_1 }}, {{ glow_color_2 }});
}
.score-bar-value {
  font-size: 14px; font-weight: 600; color: rgba(255,255,255,0.7);
  width: 40px; flex-shrink: 0;
}

/* === Observations === */
.observations {
  padding: 10px 80px; position: relative; z-index: 1;
}
.observations-title {
  font-size: 14px; font-weight: 500; letter-spacing: 3px;
  text-transform: uppercase; color: rgba(255,255,255,0.25);
  text-align: center; margin-bottom: 24px;
}
.observation {
  background: rgba(255,255,255,0.03);
  border-left: 3px solid {{ glow_color_1 }}80;
  padding: 18px 24px; margin-bottom: 14px;
  border-radius: 0 14px 14px 0;
}
.observation p { font-size: 15px; line-height: 1.7; color: rgba(255,255,255,0.6); }

/* === Personality === */
.personality {
  text-align: center; padding: 20px 80px;
  font-size: 17px; line-height: 1.8;
  color: rgba(255,255,255,0.35); font-style: italic;
  position: relative; z-index: 1;
  max-width: 800px;
}

/* === Footer === */
.footer {
  text-align: center; padding: 30px 0 40px;
  position: relative; z-index: 1;
}
.footer .url {
  font-size: 14px; color: rgba(255,255,255,0.15);
  letter-spacing: 3px; text-transform: lowercase;
}

/* === Divider === */
.section-gap { height: 40px; }
</style>
</head>
<body>
<div class="report-card">

<div class="brand">HomeBoard</div>

<div class="hero">
  <div class="archetype">{{ archetype }}</div>
  <div class="hero-stats">
    <strong>{{ total_apps }}</strong> apps &middot;
    <strong>{{ page_count }}</strong> pages &middot;
    <strong>{{ folder_count }}</strong> folders
  </div>

  <div class="phone-score-composite">
    <div class="phone-glow"></div>
    <div class="phone-frame">
      <div class="icon-grid">
        {% for item in page1_items[:24] %}
        <div class="icon-cell">
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
        <div class="icon-cell">
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

    <!-- Score ring badge -->
    <svg class="score-badge" viewBox="0 0 120 120">
      <defs>
        <linearGradient id="scoreGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color: {{ glow_color_1 }}" />
          <stop offset="100%" style="stop-color: {{ glow_color_2 }}" />
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="45" class="score-ring-bg" />
      <circle cx="60" cy="60" r="45" class="score-ring-fill" />
      <text x="60" y="55" class="score-badge-num">{{ score_total|int }}</text>
      <text x="60" y="76" class="score-badge-label">/ 100</text>
    </svg>
  </div>
</div>

<div class="section-gap"></div>

<div class="category-legend">
  {% for cat, color in categories.items() %}
  <div class="legend-item">
    <div class="legend-dot" style="background: {{ color }};"></div>
    {{ cat }} ({{ category_counts.get(cat, 0) }})
  </div>
  {% endfor %}
</div>

<div class="section-gap"></div>

<div class="score-section">
  <div class="score-section-title">Score Breakdown</div>
  <div class="score-bars">
    <div class="score-bar-row">
      <div class="score-bar-label">Page Efficiency</div>
      <div class="score-bar-track"><div class="score-bar-fill" style="width: {{ score_page_efficiency|int }}%;"></div></div>
      <div class="score-bar-value">{{ score_page_efficiency|int }}</div>
    </div>
    <div class="score-bar-row">
      <div class="score-bar-label">Category Coherence</div>
      <div class="score-bar-track"><div class="score-bar-fill" style="width: {{ score_category_coherence|int }}%;"></div></div>
      <div class="score-bar-value">{{ score_category_coherence|int }}</div>
    </div>
    <div class="score-bar-row">
      <div class="score-bar-label">Folder Usage</div>
      <div class="score-bar-track"><div class="score-bar-fill" style="width: {{ score_folder_usage|int }}%;"></div></div>
      <div class="score-bar-value">{{ score_folder_usage|int }}</div>
    </div>
    <div class="score-bar-row">
      <div class="score-bar-label">Dock Quality</div>
      <div class="score-bar-track"><div class="score-bar-fill" style="width: {{ score_dock_quality|int }}%;"></div></div>
      <div class="score-bar-value">{{ score_dock_quality|int }}</div>
    </div>
  </div>
</div>

<div class="section-gap"></div>

{% if observations %}
<div class="observations">
  <div class="observations-title">Insights</div>
  {% for obs in observations %}
  <div class="observation"><p>{{ obs }}</p></div>
  {% endfor %}
</div>
{% endif %}

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
            "name": f"\U0001f4c1 {item.folder.display_name}",
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


def _top_glow_colors(cat_counter: dict) -> tuple[str, str, str]:
    """Pick the top 3 category colors for the ambient glow, excluding System/Other."""
    priority = [
        c for c in cat_counter.most_common()
        if c[0] not in ("System", "Other", "Utilities", "Folder", "Widget", "Unknown")
    ]
    # Fallback defaults: vibrant, saturated colors
    defaults = ["#60a5fa", "#a78bfa", "#f472b6"]
    colors = []
    for cat, _count in priority[:3]:
        colors.append(CATEGORY_COLORS.get(cat, defaults[len(colors)]))
    while len(colors) < 3:
        colors.append(defaults[len(colors)])
    return (colors[0], colors[1], colors[2])


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

    # Determine glow colors from user's top categories
    glow1, glow2, glow3 = _top_glow_colors(cat_counter)

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
        score_page_efficiency=score.page_efficiency,
        score_category_coherence=score.category_coherence,
        score_folder_usage=score.folder_usage,
        score_dock_quality=score.dock_quality,
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
        glow_color_1=glow1,
        glow_color_2=glow2,
        glow_color_3=glow3,
    )


SHARE_CARD_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HomeBoard — {{ archetype }}</title>
<style>
@keyframes gradientShift {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}
@keyframes glowPulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 0.75; }
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #000; color: #fff;
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif;
  display: flex; justify-content: center; align-items: center;
  min-height: 100vh;
}

.card {
  width: 1080px; height: 1350px;
  background: #0a0a0a;
  position: relative; overflow: hidden;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 0;
}

/* Ambient glow */
.card::before {
  content: '';
  position: absolute; top: -100px; left: 50%; transform: translateX(-50%);
  width: 1000px; height: 800px;
  background: radial-gradient(ellipse at 30% 30%, {{ glow_1 }}40 0%, transparent 55%),
              radial-gradient(ellipse at 70% 50%, {{ glow_2 }}30 0%, transparent 50%),
              radial-gradient(ellipse at 50% 70%, {{ glow_3 }}20 0%, transparent 60%);
  filter: blur(100px);
  animation: glowPulse 6s ease-in-out infinite;
  pointer-events: none;
}

.content {
  position: relative; z-index: 1;
  display: flex; flex-direction: column;
  align-items: center; text-align: center;
  padding: 60px 80px;
  gap: 0;
  width: 100%; height: 100%;
  justify-content: space-between;
}

/* Top zone */
.top { display: flex; flex-direction: column; align-items: center; gap: 8px; padding-top: 20px; }

.brand {
  font-size: 13px; font-weight: 400; letter-spacing: 6px;
  text-transform: uppercase; color: rgba(255,255,255,0.25);
}

/* Hero archetype */
.archetype {
  font-size: 82px; font-weight: 800; line-height: 1.0;
  letter-spacing: -2px;
  background: linear-gradient(135deg, {{ glow_1 }}, {{ glow_2 }}, {{ glow_3 }});
  background-size: 200% 200%;
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: gradientShift 8s ease-in-out infinite;
  max-width: 900px;
  margin-top: 16px;
}

/* Middle zone: score + mosaic + tagline */
.middle {
  display: flex; flex-direction: column;
  align-items: center; gap: 32px;
  flex: 1; justify-content: center;
}

.score-display { display: flex; align-items: baseline; gap: 12px; }
.score-num {
  font-size: 140px; font-weight: 800; line-height: 1;
  background: linear-gradient(180deg, #fff 30%, rgba(255,255,255,0.4) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.score-max {
  font-size: 48px; font-weight: 300; color: rgba(255,255,255,0.2);
}
.score-label {
  font-size: 18px; font-weight: 500; letter-spacing: 4px;
  text-transform: uppercase; color: rgba(255,255,255,0.35);
  margin-top: -8px;
}

/* App DNA mosaic: tiny grid of all pages */
.mosaic {
  display: flex; gap: 8px; justify-content: center; flex-wrap: wrap;
  max-width: 600px;
}
.mosaic-page {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 2px;
}
.mosaic-cell {
  width: 10px; height: 10px; border-radius: 2px; opacity: 0.85;
}

/* Tagline */
.tagline {
  font-size: 22px; font-weight: 400; color: rgba(255,255,255,0.55);
  max-width: 700px; line-height: 1.5;
}
.tagline strong { color: rgba(255,255,255,0.85); font-weight: 600; }

/* Stats line */
.stats-line {
  font-size: 16px; color: rgba(255,255,255,0.3);
  letter-spacing: 0.5px;
}
.stats-line strong { color: rgba(255,255,255,0.55); font-weight: 600; }

/* Bottom zone */
.bottom {
  display: flex; flex-direction: column; align-items: center; gap: 16px;
  padding-bottom: 20px;
}
.url {
  font-size: 18px; font-weight: 500; letter-spacing: 3px;
  color: rgba(255,255,255,0.3);
}
</style>
</head>
<body>
<div class="card">
  <div class="content">
    <div class="top">
      <div class="brand">HomeBoard</div>
      <div class="archetype">{{ archetype }}</div>
    </div>

    <div class="middle">
      <div class="score-display">
        <div class="score-num">{{ score_total|int }}</div>
        <div class="score-max">/ 100</div>
      </div>
      <div class="score-label">{{ score_label }}</div>

      <div class="mosaic">
        {% for page_colors in all_page_colors %}
        <div class="mosaic-page">
          {% for color in page_colors %}
          <div class="mosaic-cell" style="background: {{ color }};"></div>
          {% endfor %}
        </div>
        {% endfor %}
      </div>

      {% if tagline %}
      <div class="tagline">{{ tagline }}</div>
      {% endif %}

      <div class="stats-line">
        <strong>{{ total_apps }}</strong> apps &middot;
        <strong>{{ page_count }}</strong> pages &middot;
        <strong>{{ folder_count }}</strong> folders
      </div>
    </div>

    <div class="bottom">
      <div class="url">homeboard.app</div>
    </div>
  </div>
</div>
</body>
</html>
""")


def generate_share_card(
    layout: HomeScreenLayout,
    metadata: dict[str, dict],
    score: ScoreBreakdown,
    archetype: str = "The Collector",
    personality: str | None = None,
) -> str:
    """Generate the compact shareable card (1080x1350, single screen).

    This is the Spotify Wrapped-style artifact. One archetype, one score,
    a tiny mosaic visualization, one tagline, and a URL. That's it.
    """
    from collections import Counter

    cat_counter = Counter()
    for bid in layout.all_bundle_ids:
        meta = metadata.get(bid, {})
        cat = meta.get("super_category", "Other") if meta else "Other"
        cat_counter[cat] += 1

    glow1, glow2, glow3 = _top_glow_colors(cat_counter)

    # Build the App DNA mosaic: color grid for each page
    all_page_colors = []
    for page in layout.pages:
        page_colors = []
        for item in page:
            if item.is_app:
                meta = metadata.get(item.app.bundle_id, {})
                cat = meta.get("super_category", "Other") if meta else "Other"
                page_colors.append(CATEGORY_COLORS.get(cat, CATEGORY_COLORS["Other"]))
            elif item.is_folder:
                page_colors.append("#374151")
            elif item.is_widget:
                page_colors.append("#1f2937")
        all_page_colors.append(page_colors)

    # Compress personality into a single tagline (first sentence or truncated)
    tagline = None
    if personality:
        first_sentence = personality.split(".")[0].strip()
        if len(first_sentence) > 100:
            first_sentence = first_sentence[:97] + "..."
        tagline = first_sentence + "."

    return SHARE_CARD_TEMPLATE.render(
        archetype=archetype,
        score_total=score.total,
        score_label=score.label,
        total_apps=layout.total_apps,
        page_count=layout.page_count,
        folder_count=len(layout.all_folders()),
        all_page_colors=all_page_colors,
        tagline=tagline,
        glow_1=glow1,
        glow_2=glow2,
        glow_3=glow3,
    )


def save_report(html: str, path: Path) -> None:
    """Save the HTML report to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
