# Unjiggle Launch Posts — Ready to Ship

## 1. Show HN

**Title:** `Show HN: Unjiggle – AI-powered iPhone home screen organizer via USB (Python CLI)`

**Body:**
```
I built a CLI tool that reads your iPhone home screen over USB and tells you
everything that's wrong with it.

It scores your organization (0-100), assigns you an archetype ("The Digital
Hoarder", "The Organized Maximalist"), calculates how many swipes you waste
per year, writes obituaries for your dead apps, and generates a personality
roast based on your app collection.

Then it fixes your layout — one suggestion at a time, with a preview before
each change and one-click undo.

  pip install unjiggle
  unjiggle go

Technical details:
- Reads/writes iPhone home screen via pymobiledevice3 (USB, no jailbreak)
- Validated on iPhone 16 Pro, iOS 18+
- Safety-first: verified backup before any write, round-trip tested
- AI analysis via Claude or GPT-4.1 (optional — scoring/swipe tax work without API keys)
- Share cards render to PNG via Chrome headless, auto-copy to clipboard
- GPL-3.0

The share cards are designed to be posted — each one copies to your clipboard
when generated. The personality roast and app obituaries are the most fun part.

Website: https://unjiggle.com
Source: https://github.com/chungty/unjiggle
PyPI: https://pypi.org/project/unjiggle/
```

**Notes:** HN likes technical depth. Lead with what it does, include the install command early, mention the stack. Don't oversell — let them try it.

---

## 2. Twitter/X — Launch Thread

**Tweet 1 (standalone, attach the Personality Mirror card):**
```
I built a tool that roasts your iPhone based on your app collection.

"226 apps, 4 meditation apps, 4 language apps, 0 inner peace, 0 new languages."

It scans your phone over USB, writes obituaries for your dead apps, and
calculates how many swipes you waste per year.

pip install unjiggle

[attach: mirror share card PNG]
```

**Tweet 2 (reply, attach the Swipe Tax card):**
```
It also calculates your Swipe Tax — how many unnecessary swipes your
layout costs you per year.

Mine was 11,429.

[attach: swipetax share card PNG]
```

**Tweet 3 (reply, attach the Obituary card):**
```
And it writes obituaries for your dead apps.

"Clubhouse (2021–2023): Downloaded during two frenzied weeks when everyone
pretended they wanted to listen to strangers talk."

Each one is a standalone tweet.

unjiggle.com
```

**Notes:** Twitter is about the content, not the product. The roast quote IS the hook. Attach the actual share card PNGs from your phone. Post the standalone tweet first, thread the rest.

---

## 3. Reddit r/iphone

**Title:** `I built a free tool that scans your iPhone home screen and roasts your app collection`

**Body:**
```
Connect your phone via USB, run one command, and it:

- Scores your organization (0-100)
- Assigns you an archetype (I'm "The Organized Maximalist" — 226 apps
  with 14 folders. "The effort is real, even if the entropy is winning.")
- Calculates your "swipe tax" — how many unnecessary swipes your layout
  costs per year (mine: 11,429)
- Writes obituaries for your dead apps
- Generates a personality roast you'll want to screenshot

Then it offers to fix your layout with AI suggestions — one at a time,
with preview and undo.

It's a Python CLI (Mac only, since you need USB):

  pip install unjiggle
  unjiggle go

No jailbreak needed. Free. Open source.

What's your swipe tax? I'm curious if anyone beats 20,000.

https://unjiggle.com
```

**Notes:** r/iphone cares about the user experience, not the tech. Lead with what it reveals about THEIR phone. End with a question to drive comments.

---

## 4. Reddit r/python

**Title:** `I used pymobiledevice3 to build an AI-powered iPhone home screen analyzer`

**Body:**
```
Unjiggle is a CLI that reads your iPhone home screen layout via USB,
scores it, and uses Claude/GPT to generate observations and suggestions.

The interesting technical bits:

- pymobiledevice3 for USB communication with SpringBoard services
  (reads and writes the IconState plist — the actual home screen layout)
- Two-pass AI architecture: LLM generates narrative observations with
  structured intent, then a layout engine resolves intent into valid
  operations against iPhone grid constraints
- Share cards rendered to PNG via Chrome headless (--headless=new flag),
  auto-copied to macOS clipboard via osascript
- Screen Time integration reads knowledgeC.db for real app usage data
  (graceful fallback to positional heuristics on macOS 26 where Apple
  locked it down)
- Safety-first: verified backup with read-back, round-trip tested before
  any write

  pip install unjiggle

The viral features (personality roast, app obituaries, swipe tax calculator)
work without an API key. The AI analysis and suggestions need Claude or GPT.

Source: https://github.com/chungty/unjiggle
GPL-3.0
```

**Notes:** r/python cares about the implementation. Lead with the technical choices. Mention pymobiledevice3 — that community will appreciate it.

---

## 5. Posting Order

1. **Show HN** first (morning, ~10am ET Tuesday-Thursday for best traction)
2. **Twitter** thread 30 minutes after HN goes live (so the HN link exists to share)
3. **r/iphone** same day, afternoon
4. **r/python** next day (don't flood, and it gives you a second day of momentum)

## 6. Assets Needed

Before posting, generate fresh cards from YOUR phone:
```bash
unjiggle go                    # → score card (already have)
unjiggle swipetax              # → swipe tax card
unjiggle mirror --api-key ...  # → personality mirror card
unjiggle obituary --api-key .. # → obituary card
```

All four PNGs auto-copy to clipboard. Save them to a folder for attachment.

The Twitter thread needs the Mirror card for tweet 1, Swipe Tax for tweet 2,
and Obituary for tweet 3.
