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
- read-only installed-app identity lookup and reconciliation with a Home Screen snapshot
- read-only lookup of a single app's PNG icon by exact bundle identifier
- read-only projection of one installed, ignored User app onto one existing page

Diagnostics must not test the device write path implicitly. `safety-test` reads and
backs up by default; its write-roundtrip mode requires explicit confirmation.
The pre-write backup for a requested transform does not perform a test write.
Interactive restore fails on any read-back mismatch and never retries automatically.
These checks cannot guarantee how iOS will normalize a write or behave after reboot.
Manual and pre-write backups use exclusive file creation. If the layout changes
during verification, the operation stops and keeps the original backup. A failed
second read reports where that backup was saved.

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
- `json check-operations`, `json apply-checked`, `json pending-checked`, `json check-recovery`, `json restore-checked`: generic snapshot-bound preflight, verified write, recovery-journal lookup, read-only recovery eligibility, and device/state-bound restore; none guarantees visible iOS placement or physical recovery
- `compact_to_single_page`
- `json inventory`: provisional installed-app names and IDs; no icon, placement, or write guarantee
- `json icon`: one local device icon, or an explicit missing result; no App Library or placement guarantee
- `json check-library-insertion`: strict raw-snapshot-bound, read-only projection onto one existing page or into one unambiguous existing folder for one ignored User app; always non-writable, with no physical-placement guarantee
- `json check-library-insertions`: read-only, scan-bound prefix projections for up to fifty distinct ignored User apps; always non-writable, with no physical-placement guarantee
- `json check-mixed-operations`: read-only, source-snapshot and raw-fingerprint-bound ordered projections for page/folder moves and installed ignored User app additions to existing pages/folders. Each step is checked from the preceding raw state; results are never write authorization.
- `json apply-library-checked`: experimental single-app checked insertion behind both an explicit request opt-in and an environment gate. Rechecks installed identity and source/destination fingerprints, then uses the same verified backup, recovery journal, single write and exact raw readback as `apply-checked`. Offline tests exercise it; no physical icon placement or recovery is certified. Clients must not enable the gate from a preview alone.
- `json apply-library-batch-checked`: experimental generic batch of up to fifty checked insertions, bound to each prefix raw fingerprint and the final source/destination state. Uses one verified backup, recovery journal, raw write and exact readback; offline tests cannot certify physical placement or recovery. It shares the explicit request and environment gates above.
- `json apply-mixed-checked`: experimental ordered Home Screen moves and installed Library additions; independently gated by an explicit request opt-in and a separate process environment setting. Rechecks every prefix and the final raw state, then uses one verified backup, a recovery journal, one write and exact raw readback. Offline success cannot certify visible placement or physical recovery.

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
