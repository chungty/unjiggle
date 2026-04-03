# Architecture

## Repository role

`unjiggle` is the public engine and CLI.

It owns:
- iPhone device connection and layout read/write
- layout models and metadata enrichment
- scoring, diagnostics, and analysis
- safe transforms, backup, restore, and verification
- share cards for single-snapshot diagnostics and before/after transforms
- the public JSON contract under `unjiggle json`

It does not own the private product strategy layer.

## Boundary

Public belongs here when the feature is a generic capability:
- a reusable layout primitive such as `compact_to_single_page`
- a diagnostic that can be computed from one snapshot
- a transform preview or apply/restore workflow
- a render/export facility used by multiple clients
- a stable contract another client can call without inheriting product strategy

Private belongs outside this repo when the feature is a named product mechanic:
- challenges, streaks, milestones, or give-up flows
- lifecycle loops designed for conversion or retention
- branded campaign wrappers around otherwise generic primitives
- paywalls, activation funnels, or growth experiments
- product strategy docs, launch copy, and GTM tuning

## Decision rule

Use this test before adding any feature:

1. Can this be described as a generic engine primitive or diagnostic without product copy?
2. Would it still make sense if a third-party client used the capability?
3. Does it avoid storing lifecycle state beyond backup and restore?
4. Does it avoid named campaign framing or conversion logic?

If the answer is "no" to any of 1-3, or "yes" to 4, it is probably private.

## Concrete examples

Public:
- `mirror`, `obituary`, `swipetax`
- `suggest`, `backup`, `restore`
- `json suggest`, `json apply`, `json restore`, `json render`
- `compact_to_single_page`

Private:
- "One-Page Challenge"
- "what broke you" streak logic
- milestone cards tied to retention loops
- conversion copy and product funnel orchestration

## Process guard

Every boundary-sensitive change should do all of the following:
- update this file if the boundary moved
- update `README.md` if the public surface changed
- update `CONTRIBUTING.md` if the classification process changed
- keep `tests/test_public_surface.py` passing

If a new feature needs a boundary exception, document the reasoning here before code lands.
