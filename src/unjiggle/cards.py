"""Share card generators for shareable diagnostics and transforms.

Each card is 1080x1920 (Instagram Stories / iMessage optimized).
Design system: #0a0a0a background, ambient category glow, SF Pro Display,
gradient hero text, action-oriented CTA.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from jinja2 import Template

from unjiggle.itunes import CATEGORY_COLORS
from unjiggle.models import HomeScreenLayout


def _glow_colors(layout: HomeScreenLayout, metadata: dict) -> tuple[str, str, str]:
    cat_counter = Counter()
    for bid in layout.all_bundle_ids:
        meta = metadata.get(bid, {})
        cat = meta.get("super_category", "Other") if meta else "Other"
        cat_counter[cat] += 1

    priority = [
        c for c in cat_counter.most_common()
        if c[0] not in ("System", "Other", "Utilities")
    ]
    defaults = ["#60a5fa", "#a78bfa", "#f472b6"]
    colors = []
    for cat, _ in priority[:3]:
        colors.append(CATEGORY_COLORS.get(cat, defaults[len(colors)]))
    while len(colors) < 3:
        colors.append(defaults[len(colors)])
    return (colors[0], colors[1], colors[2])


def save_card(html: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)


# ──────────────────────────────────────────────────
# Shared base CSS — 1080x1920 Stories format
# ──────────────────────────────────────────────────

_BASE_CSS = """\
@keyframes glowPulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 0.75; }
}
@keyframes gradientShift {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
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
  align-items: center;
}

.card::before {
  content: '';
  position: absolute; top: -100px; left: 50%; transform: translateX(-50%);
  width: 1000px; height: 900px;
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
  padding: 56px 80px 48px;
  width: 100%; height: 100%;
  justify-content: space-between;
}

.brand {
  font-size: 13px; font-weight: 400; letter-spacing: 6px;
  text-transform: uppercase; color: rgba(255,255,255,0.25);
}
.top { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.card-title {
  font-size: 48px; font-weight: 800; letter-spacing: -1px;
  background: linear-gradient(135deg, {{ glow_1 }}, {{ glow_2 }}, {{ glow_3 }});
  background-size: 200% 200%;
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: gradientShift 8s ease-in-out infinite;
}
.top-stat {
  font-size: 16px; font-weight: 500; letter-spacing: 4px;
  text-transform: uppercase; color: rgba(255,255,255,0.3);
  margin-top: 4px;
}

.middle {
  display: flex; flex-direction: column;
  align-items: center; gap: 40px;
  width: 100%;
}

.bottom {
  display: flex; flex-direction: column; align-items: center; gap: 12px;
}
.cta {
  font-size: 20px; font-weight: 600; letter-spacing: 1px;
  color: rgba(255,255,255,0.5);
}
.cta strong {
  color: rgba(255,255,255,0.8);
  background: linear-gradient(90deg, {{ glow_1 }}, {{ glow_2 }});
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
"""


# ──────────────────────────────────────────────────
# MIRROR CARD — one-liner is the hero
# ──────────────────────────────────────────────────

MIRROR_CARD_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Unjiggle — Personality Mirror</title>
<style>
""" + _BASE_CSS + """

.one-liner {
  font-size: 46px; font-weight: 700; line-height: 1.3;
  color: rgba(255,255,255,0.92);
  max-width: 880px;
}

.phases {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
  max-width: 800px; width: 100%;
}
.phase {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px; padding: 24px 28px;
  text-align: left;
}
.phase-name {
  font-size: 20px; font-weight: 700; color: rgba(255,255,255,0.8);
  margin-bottom: 6px;
}
.phase-apps {
  font-size: 14px; color: rgba(255,255,255,0.3); line-height: 1.4;
}

.roast {
  font-size: 22px; font-weight: 400; color: rgba(255,255,255,0.4);
  line-height: 1.65; max-width: 820px;
  font-style: italic;
}
</style>
</head>
<body>
<div class="card">
  <div class="content">
    <div class="top">
      <div class="brand">Unjiggle</div>
      <div class="card-title">Personality Mirror</div>
      <div class="top-stat">{{ total_apps }} apps analyzed</div>
    </div>

    <div class="middle">
      <div class="one-liner">&ldquo;{{ one_line }}&rdquo;</div>

      {% if phases %}
      <div class="phases">
        {% for phase in phases[:4] %}
        <div class="phase">
          <div class="phase-name">{{ phase.name }}</div>
          <div class="phase-apps">{{ phase.apps[:3]|join(', ') }}</div>
        </div>
        {% endfor %}
      </div>
      {% endif %}

      <div class="roast">{{ roast_short }}</div>
    </div>

    <div class="bottom">
      <div class="cta">Get roasted &rarr; <strong>unjiggle.com</strong></div>
    </div>
  </div>
</div>
</body>
</html>
""")


def generate_mirror_card(layout: HomeScreenLayout, metadata: dict, mirror_result) -> str:
    g1, g2, g3 = _glow_colors(layout, metadata)
    # Truncate roast to ~2 sentences for the card
    roast = mirror_result.roast
    sentences = roast.split(". ")
    roast_short = ". ".join(sentences[:2]).strip()
    if not roast_short.endswith("."):
        roast_short += "."

    return MIRROR_CARD_TEMPLATE.render(
        total_apps=layout.total_apps,
        one_line=mirror_result.one_line,
        phases=[{"name": p.name, "apps": p.apps} for p in mirror_result.phases],
        roast_short=roast_short,
        glow_1=g1, glow_2=g2, glow_3=g3,
    )


# ──────────────────────────────────────────────────
# OBITUARY CARD
# ──────────────────────────────────────────────────

OBITUARY_CARD_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Unjiggle — Digital Graveyard</title>
<style>
""" + _BASE_CSS + """

.death-count {
  font-size: 200px; font-weight: 800; line-height: 1;
  background: linear-gradient(180deg, #fff 30%, rgba(255,255,255,0.25) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.death-label {
  font-size: 20px; font-weight: 500; letter-spacing: 5px;
  text-transform: uppercase; color: rgba(255,255,255,0.3);
  margin-top: 8px;
}

.tombstones {
  display: flex; flex-direction: column; gap: 16px;
  max-width: 880px; width: 100%;
}
.tombstone {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 14px; padding: 24px 32px;
  text-align: left;
}
.tomb-header {
  display: flex; align-items: baseline; gap: 10px;
  margin-bottom: 10px;
}
.tomb-name {
  font-size: 20px; font-weight: 700; color: rgba(255,255,255,0.85);
}
.tomb-dates {
  font-size: 14px; color: rgba(255,255,255,0.25);
}
.tomb-eulogy {
  font-size: 17px; color: rgba(255,255,255,0.45);
  line-height: 1.55;
}
.tomb-cause {
  font-size: 13px; color: rgba(255,255,255,0.2);
  margin-top: 8px; font-style: italic;
}

.summary {
  font-size: 24px; font-weight: 500; color: rgba(255,255,255,0.6);
  max-width: 820px; line-height: 1.45;
}
</style>
</head>
<body>
<div class="card">
  <div class="content">
    <div class="top">
      <div class="brand">Unjiggle</div>
      <div class="card-title">Digital Graveyard</div>
    </div>

    <div class="middle">
      <div style="text-align: center;">
        <div class="death-count">{{ total_dead }}</div>
        <div class="death-label">apps didn't make it</div>
      </div>

      <div class="tombstones">
        {% for obit in obituaries[:4] %}
        <div class="tombstone">
          <div class="tomb-header">
            <span class="tomb-name">&#x26B0;&#xFE0F; {{ obit.app_name }}</span>
            {% if obit.born %}<span class="tomb-dates">{{ obit.born }} &ndash; {{ obit.died }}</span>{% endif %}
          </div>
          <div class="tomb-eulogy">{{ obit.eulogy }}</div>
          {% if obit.cause_of_death %}<div class="tomb-cause">{{ obit.cause_of_death }}</div>{% endif %}
        </div>
        {% endfor %}
      </div>

      <div class="summary">&ldquo;{{ graveyard_summary }}&rdquo;</div>
    </div>

    <div class="bottom">
      <div class="cta">Bury yours &rarr; <strong>unjiggle.com</strong></div>
    </div>
  </div>
</div>
</body>
</html>
""")


def generate_obituary_card(layout: HomeScreenLayout, metadata: dict, obituary_result) -> str:
    g1, g2, g3 = _glow_colors(layout, metadata)
    return OBITUARY_CARD_TEMPLATE.render(
        total_dead=obituary_result.total_dead,
        obituaries=[{
            "app_name": o.app_name, "born": o.born, "died": o.died,
            "eulogy": o.eulogy, "cause_of_death": o.cause_of_death,
        } for o in obituary_result.obituaries],
        graveyard_summary=obituary_result.graveyard_summary,
        glow_1=g1, glow_2=g2, glow_3=g3,
    )


# ──────────────────────────────────────────────────
# SWIPE TAX CARD
# ──────────────────────────────────────────────────

SWIPE_TAX_CARD_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Unjiggle — Swipe Tax</title>
<style>
""" + _BASE_CSS + """

.tax-hero {
  font-size: 140px; font-weight: 800; line-height: 1;
  background: linear-gradient(180deg, #fbbf24 20%, #ef4444 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.tax-label {
  font-size: 18px; font-weight: 500; letter-spacing: 5px;
  text-transform: uppercase; color: rgba(255,255,255,0.3);
  margin-top: 4px;
}

.comparison {
  display: flex; flex-direction: column; gap: 14px; width: 720px;
}
.bar-row { display: flex; align-items: center; gap: 16px; }
.bar-label {
  font-size: 16px; color: rgba(255,255,255,0.4);
  width: 100px; text-align: right;
}
.bar-track {
  flex: 1; height: 32px; background: rgba(255,255,255,0.04);
  border-radius: 8px; overflow: hidden;
}
.bar-fill { height: 100%; border-radius: 8px; }
.bar-fill.current { background: linear-gradient(90deg, #ef4444, #f97316); }
.bar-fill.optimal { background: linear-gradient(90deg, #22c55e, #4ade80); }
.bar-value {
  font-size: 16px; font-weight: 600; color: rgba(255,255,255,0.6);
  width: 110px;
}

.offenders {
  display: flex; flex-direction: column; gap: 8px;
  max-width: 720px; width: 100%;
}
.offender {
  display: flex; align-items: center; gap: 16px;
  padding: 12px 20px;
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
}
.offender-rank {
  font-size: 14px; font-weight: 800; color: rgba(255,255,255,0.15);
  width: 28px;
}
.offender-name {
  font-size: 16px; font-weight: 600; color: rgba(255,255,255,0.65);
  flex: 1;
}
.offender-page { font-size: 13px; color: rgba(255,255,255,0.25); }
.offender-waste { font-size: 16px; font-weight: 700; color: #f87171; }

.savings-text {
  font-size: 22px; font-weight: 500; color: rgba(255,255,255,0.5);
}
.savings-text strong { color: #4ade80; font-weight: 700; }

.headline {
  font-size: 24px; font-weight: 600; color: rgba(255,255,255,0.68);
  max-width: 780px; line-height: 1.45;
}
</style>
</head>
<body>
<div class="card">
  <div class="content">
    <div class="top">
      <div class="brand">Unjiggle</div>
      <div class="card-title">Swipe Tax</div>
    </div>

    <div class="middle">
      <div style="text-align: center;">
        <div class="tax-hero">{{ savings_formatted }}</div>
        <div class="tax-label">wasted swipes per year</div>
      </div>

      <div class="comparison">
        <div class="bar-row">
          <div class="bar-label">Current</div>
          <div class="bar-track"><div class="bar-fill current" style="width: 100%;"></div></div>
          <div class="bar-value">{{ current_formatted }}/yr</div>
        </div>
        <div class="bar-row">
          <div class="bar-label">Optimal</div>
          <div class="bar-track"><div class="bar-fill optimal" style="width: {{ optimal_pct }}%;"></div></div>
          <div class="bar-value">{{ optimal_formatted }}/yr</div>
        </div>
      </div>

      {% if offenders %}
      <div class="offenders">
        {% for app in offenders[:5] %}
        <div class="offender">
          <div class="offender-rank">#{{ loop.index }}</div>
          <div class="offender-name">{{ app.name }}</div>
          <div class="offender-page">Page {{ app.page }}</div>
          <div class="offender-waste">{{ app.waste_formatted }}/yr</div>
        </div>
        {% endfor %}
      </div>
      {% endif %}

      {% if headline %}
      <div class="headline">{{ headline }}</div>
      {% endif %}

      <div class="savings-text">
        Current vs. calm: <strong>{{ savings_formatted }} swipes saved</strong> every year
      </div>
    </div>

    <div class="bottom">
      <div class="cta">Get your number &rarr; <strong>unjiggle.com</strong></div>
    </div>
  </div>
</div>
</body>
</html>
""")


def generate_swipetax_card(layout: HomeScreenLayout, metadata: dict, tax_result) -> str:
    g1, g2, g3 = _glow_colors(layout, metadata)
    total = max(tax_result.total_annual_swipes, 1)
    optimal_pct = int(tax_result.optimal_annual_swipes / total * 100)

    offenders = [{
        "name": a.name, "page": a.page,
        "waste_formatted": f"{a.annual_wasted_swipes:,}",
    } for a in tax_result.worst_offenders[:5]]

    return SWIPE_TAX_CARD_TEMPLATE.render(
        savings_formatted=f"{tax_result.savings:,}",
        current_formatted=f"{tax_result.total_annual_swipes:,}",
        optimal_formatted=f"{tax_result.optimal_annual_swipes:,}",
        optimal_pct=optimal_pct,
        offenders=offenders,
        headline=tax_result.headline,
        glow_1=g1, glow_2=g2, glow_3=g3,
    )


# ──────────────────────────────────────────────────
# TRANSFORMATION CARD
# ──────────────────────────────────────────────────

TRANSFORM_CARD_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Unjiggle — Transformation</title>
<style>
""" + _BASE_CSS + """

.scores {
  display: flex; align-items: center; gap: 28px;
}
.score-box {
  min-width: 280px;
  padding: 28px 32px;
  border-radius: 18px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
}
.score-label {
  font-size: 16px; font-weight: 600; letter-spacing: 3px;
  text-transform: uppercase; color: rgba(255,255,255,0.3);
}
.score-value {
  font-size: 120px; font-weight: 800; line-height: 1;
  margin-top: 12px;
}
.score-value.before {
  background: linear-gradient(180deg, #f97316 20%, #ef4444 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.score-value.after {
  background: linear-gradient(180deg, #22c55e 20%, #4ade80 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.score-sub {
  font-size: 24px; font-weight: 600; color: rgba(255,255,255,0.65);
  margin-top: 10px;
}
.transform-arrow {
  font-size: 52px; color: rgba(255,255,255,0.25);
}
.transform-summary {
  font-size: 28px; font-weight: 600; color: rgba(255,255,255,0.75);
  max-width: 840px; line-height: 1.45;
}
.transform-stats {
  display: flex; gap: 40px;
}
.transform-stat {
  min-width: 180px;
  padding: 20px 24px;
  border-radius: 16px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
}
.transform-stat-value {
  font-size: 42px; font-weight: 800; color: rgba(255,255,255,0.85);
}
.transform-stat-label {
  font-size: 14px; font-weight: 600; letter-spacing: 3px;
  text-transform: uppercase; color: rgba(255,255,255,0.3);
  margin-top: 6px;
}
</style>
</head>
<body>
<div class="card">
  <div class="content">
    <div class="top">
      <div class="brand">Unjiggle</div>
      <div class="card-title">Transformation</div>
      <div class="top-stat">{{ headline }}</div>
    </div>

    <div class="middle">
      <div class="scores">
        <div class="score-box">
          <div class="score-label">Before</div>
          <div class="score-value before">{{ before_score }}</div>
          <div class="score-sub">{{ before_pages }} pages &middot; {{ before_apps }} apps</div>
        </div>
        <div class="transform-arrow">&rarr;</div>
        <div class="score-box">
          <div class="score-label">After</div>
          <div class="score-value after">{{ after_score }}</div>
          <div class="score-sub">{{ after_pages }} page{% if after_pages != 1 %}s{% endif %} &middot; {{ after_apps }} apps</div>
        </div>
      </div>

      <div class="transform-summary">{{ summary }}</div>

      <div class="transform-stats">
        <div class="transform-stat">
          <div class="transform-stat-value">{{ score_delta }}</div>
          <div class="transform-stat-label">Score Delta</div>
        </div>
        <div class="transform-stat">
          <div class="transform-stat-value">{{ page_delta }}</div>
          <div class="transform-stat-label">Pages Removed</div>
        </div>
        <div class="transform-stat">
          <div class="transform-stat-value">{{ apps_delta }}</div>
          <div class="transform-stat-label">Apps Hidden</div>
        </div>
      </div>
    </div>

    <div class="bottom">
      <div class="cta">Fix your home screen &rarr; <strong>unjiggle.com</strong></div>
    </div>
  </div>
</div>
</body>
</html>
""")


def generate_transform_card(
    before_layout: HomeScreenLayout,
    after_layout: HomeScreenLayout,
    before_score: int,
    after_score: int,
    summary: str,
    metadata: dict,
) -> str:
    g1, g2, g3 = _glow_colors(after_layout, metadata)
    score_delta = after_score - before_score
    page_delta = max(before_layout.page_count - after_layout.page_count, 0)
    apps_delta = max(before_layout.total_apps - after_layout.total_apps, 0)
    headline = "Before and after."
    if after_score > before_score:
        headline = "Cleaner, faster, calmer."
    elif after_score == before_score:
        headline = "Same score, better clarity."

    return TRANSFORM_CARD_TEMPLATE.render(
        before_score=before_score,
        after_score=after_score,
        before_pages=before_layout.page_count,
        after_pages=after_layout.page_count,
        before_apps=before_layout.total_apps,
        after_apps=after_layout.total_apps,
        summary=summary,
        headline=headline,
        score_delta=f"{score_delta:+d}",
        page_delta=page_delta,
        apps_delta=apps_delta,
        glow_1=g1, glow_2=g2, glow_3=g3,
    )

