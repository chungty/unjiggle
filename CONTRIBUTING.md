# Contributing

## First rule

Do not add private product mechanics to the public engine.

Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing commands, JSON endpoints, share cards, or lifecycle state.

## Boundary checklist

Before opening a PR, answer these:

1. Is this a generic engine capability, diagnostic, transform, or contract?
2. Can another client use it without inheriting product strategy?
3. Does it avoid named campaigns, lifecycle loops, milestones, streaks, or conversion logic?
4. Does the README still describe the public surface truthfully after this change?

If any answer is unclear, update `ARCHITECTURE.md` first.

## Required updates for surface changes

If you change the public surface, update all relevant files in the same change:
- `README.md`
- `ARCHITECTURE.md`
- `AGENTS.md` if future agent routing or repo rules changed
- `tests/test_public_surface.py`

## Publishing checklist

Before tagging or publishing:

1. Run `pytest -q`.
2. Confirm `tests/test_public_surface.py` passes.
3. Confirm there is no named private mechanic exposed in CLI help, JSON commands, or README.
4. Confirm the repo can be explained in one sentence as a public engine and CLI.

If you cannot explain the boundary cleanly, do not publish yet.

## Device-write safety checks

Run `pytest -q tests/test_write_consent.py tests/test_safety.py` when changing backup,
restore, or write consent. These tests use a simulated phone. Default diagnostics
and pre-write backups must make zero device writes; explicit write tests must
require consent and fail on read-back differences without retrying. Do not use a
personal phone to reproduce a layout-loss report. Passing simulated tests is not
proof that iOS will preserve a layout or that a customer's backup can be restored.
