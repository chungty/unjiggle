# HomeBoard

A Mac app for reorganizing iPhone home screens with intelligence.

**Status**: Research & Validation phase

## What is this?

HomeBoard is a native macOS app that lets you visually reorganize your iPhone home screen from your Mac — with smart suggestions, before/after comparisons, and an organization score. Think "Apple Configurator for normal people, with a brain."

## Why?

- Jiggle mode on iPhone is universally despised (TechRadar, March 2026: "It's 2026, and I still can't believe Apple won't change the most frustrating thing about iOS")
- No free, reliable, consumer-grade tool exists for this
- Apple explicitly rejected building AI home screen features (Federighi, Jan 2026)
- Every past attempt (AnyTrans, iCareFone, iTunes) abandoned this as a side feature — nobody has built a purpose-built app with modern UX and algorithms

## Research

- [Design Document](docs/design-document.md) — Full product design (UX, algorithms, architecture, market)
- [Technical Feasibility](docs/technical-feasibility.md) — How to read/write iPhone layouts, APIs, libraries
- [Algorithm Research](docs/algorithm-research.md) — Clustering, spatial optimization, analogous domains
- [UX Research](docs/ux-research.md) — Interaction design, precedent apps, visual direction
- [Current Landscape](docs/current-landscape.md) — Competitive analysis, user complaints, Apple's tools
- [Market Analysis](docs/market-analysis.md) — TAM, pricing, business model, risks

## First Validation Step

Before writing any product code:

```bash
pip3 install pymobiledevice3
pymobiledevice3 springboard get-icon-state > before.json
# swap two app positions in the JSON
pymobiledevice3 springboard set-icon-state < modified.json
# check your iPhone — if the apps moved, green light to build
```

## Tech Stack (Planned)

- Swift + SwiftUI (native macOS)
- libimobiledevice / pymobiledevice3 (USB device communication)
- HDBSCAN clustering + Hungarian algorithm (layout optimization)
- Developer ID + notarization + Sparkle (distribution)
