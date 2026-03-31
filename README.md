# Unjiggle

**Your iPhone home screen is a mess. You know it. You've given up fixing it. Unjiggle fixes it for you.**

Unjiggle is an AI-powered CLI that reads your iPhone home screen, scores your organization, tells you what's wrong (and why), and fixes it — one step at a time or all at once.

## Quick Start

```bash
pip install unjiggle
```

Connect your iPhone via USB, then:

```bash
unjiggle go
```

That's it. One command. It scans your phone, scores your organization, runs AI analysis, and generates a shareable report card.

## What It Does

**`unjiggle go`** — The full experience in one command:
- Reads your entire home screen layout over USB (226 apps, 8 pages, 14 folders... or whatever yours looks like)
- Scores your organization (0-100) across four dimensions
- Runs AI analysis that actually *sees* your phone: duplicate apps, abandoned apps, scattered categories, cryptic folder names
- Generates a Wrapped-style share card with your archetype and App DNA mosaic
- Opens it in your browser. Screenshot it. Post it.

**`unjiggle suggest`** — Interactive AI walkthrough:
- The AI walks you through 5-7 observations, each with a specific fix
- For cleanup suggestions: choose **Delete** (with a Marie Kondo gratitude moment), **Archive** (App Library), or **Keep**
- Every change is previewed before applying
- Auto-backup before any write. One-command undo.

**`unjiggle safety-test`** — Prove it's safe first:
- Reads your layout, writes it back unchanged, reads again
- Verifies the result is identical
- Your phone doesn't change at all. Run this first if you're nervous.

## Commands

| Command | What it does |
|---------|-------------|
| `unjiggle go` | Full experience: scan → score → AI → share card |
| `unjiggle scan` | See your layout color-coded by category |
| `unjiggle score` | Organization score (0-100) with breakdown |
| `unjiggle analyze` | AI observations (Claude or GPT-4.1) |
| `unjiggle suggest` | Interactive walkthrough — apply changes step by step |
| `unjiggle suggest --apply-all` | Just Fix It mode — apply everything at once |
| `unjiggle report --open` | Generate share card + full report |
| `unjiggle safety-test` | Prove read/write works (changes nothing) |
| `unjiggle backup` | Save current layout |
| `unjiggle restore` | Undo any changes |

## Requirements

- **macOS** (USB communication with iPhone)
- **iPhone connected via USB** with "Trust This Computer" accepted
- **Python 3.10+**
- **API key** for AI features: set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`

## How It Works

Unjiggle uses [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) to communicate with your iPhone's SpringBoard services over USB. It reads the `IconState` (your home screen layout), enriches it with App Store metadata, and uses an LLM to generate observations and layout suggestions.

The write path is validated on iPhone 16 Pro, iOS 26.0. Every write is preceded by a verified backup and an optional round-trip safety test.

## The Share Card

Unjiggle generates a Wrapped-style share card (1080x1350) with:
- Your **archetype** ("The Agile Optimizer", "The Digital Archaeologist", etc.)
- Your **organization score** (0-100)
- An **App DNA mosaic** — tiny color-coded grids showing the category pattern across all your pages
- A **one-line personality tagline** from the AI

Screenshot it. Post it. Challenge your friends.

## GUI Coming Soon

A native Mac app with live preview, drag-and-drop editing, animated before/after transformations, and a slider to control aggressiveness is in development.

The CLI validates the core value prop. The GUI is the full product.

**Sign up for early access:** [unjiggle.com](https://unjiggle.com)

## License

GPL-3.0 (matching pymobiledevice3)
