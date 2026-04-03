## Skill routing

When the user's request matches an available gstack skill, use that skill as your first action.
Do not answer directly first and do not start with unrelated tools.
The skill has specialized workflows, checklists, and review loops that are better than ad hoc execution.

Key routing rules:
- Product ideas, brainstorming, "is this worth building" -> `gstack-office-hours`
- Bugs, errors, broken flows, root-cause analysis -> `gstack-investigate`
- Ship, deploy, push, create a PR -> `gstack-ship`
- QA, test the site, find bugs -> `gstack-qa`
- Code review, check my diff, pre-landing review -> `gstack-review`
- Update docs after shipping -> `gstack-document-release`
- Weekly retro or project retrospective -> `gstack-retro`
- Design system, brand, visual direction -> `gstack-design-consultation`
- Visual audit, polish, UI cleanup -> `gstack-design-review`
- Architecture review, plan hardening, edge cases -> `gstack-plan-eng-review`
- Save progress, checkpoint, resume context -> `gstack-checkpoint`
- Code quality or repo health audit -> `gstack-health`

If a request clearly spans multiple skills, start with the highest-leverage one and chain into the others only when needed.

## Repository Boundary

This repository is the public `unjiggle` engine and CLI.

It owns:
- device access, layout parsing, scoring, diagnostics, transforms, backup/restore
- shareable single-snapshot diagnostics and before/after transform rendering
- the public JSON API consumed by other clients

It does not own:
- named growth mechanics, challenges, streaks, milestones, or give-up flows
- product funnel logic, lifecycle loops, or private GTM strategy

Before adding a command, JSON endpoint, or share card:
1. Check [ARCHITECTURE.md](/Users/chungty/Projects/unjiggle/ARCHITECTURE.md).
2. Keep the public/private split explicit in code and docs.
3. Update [README.md](/Users/chungty/Projects/unjiggle/README.md), [CONTRIBUTING.md](/Users/chungty/Projects/unjiggle/CONTRIBUTING.md), and the public-surface tests when the boundary changes.

If a requested feature sounds like a branded conversion mechanic, do not implement it here by default.
