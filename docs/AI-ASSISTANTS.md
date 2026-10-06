# Use Unjiggle with an AI assistant

Claude, Codex, or Cursor can help you understand Unjiggle's output. Start with a sample phone, then decide separately whether to show your own layout. An assistant does not need permission to move icons to explain a score.

## First, try the sample

On macOS with Python 3.10+, open a terminal in a folder where you want the virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install unjiggle
unjiggle demo
```

The demo prints a sample score and diagnostics without a phone or API key. You can ask your assistant: “Explain the demo output and the swipe estimate. Do not connect to my phone, call an AI API, or run a write command.” Paste only the parts of the output you want to share. On a later visit, activate the same environment with `source .venv/bin/activate`.

## Then, choose whether to scan

**Ask before connecting a real phone.** A local assistant with terminal access can run commands and see their output. A hosted assistant can also see any layout returned by its tool or pasted into chat: do not wait until after the scan to ask for consent. A layout can reveal installed apps, folder names, and habits. Confirm which assistant and tools will receive it, and do not paste API keys or raw backups into chat.

If you explicitly consent to a read-only scan, connect your iPhone by USB, tap **Trust This Computer**, and run these commands yourself (or authorize a local assistant to run only these commands):

```bash
unjiggle scan
unjiggle score
```

`scan` shows your pages and apps; `score` computes an organization score. Neither rearranges icons. Metadata lookups may contact an external service. Share only the output you want explained. If you want a structured preview, `unjiggle json suggest --preset focus` reads the phone and returns a proposed layout; it does **not** apply it. Review that output privately before sharing it with an assistant.

Do not substitute `unjiggle go` for this scan. If `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set, `go` may send layout information to an AI provider. It also writes local reports, opens a share card, and may ask about analytics. `unjiggle suggest` also uses AI and its interactive flow may write changes; `unjiggle suggest --apply-all` applies suggestions. None of those commands belong in the read-only step.

## Only if you want to change icons

This is a **new permission decision**, not a continuation of scan consent. Have your assistant explain the exact proposed changes first. Check each change against the current phone layout, including folders, widgets, and dock; an icon removed from the home screen is not necessarily uninstalled. iOS can reflow or add icons after a write, so a preview is not a promise of the final arrangement.

Before authorizing any write, save and check a backup using `unjiggle backup`, retain its location, and review the current preview and its `snapshot_id`. In the updated CLI, `unjiggle safety-test` only checks reads and saves a verified local backup. The optional `--write-roundtrip` mode **writes to the phone** and requires a separate confirmation, defaulting to No. It can add or move icons even though the input is unchanged; do not use it as a harmless prerequisite. Older releases may write when running bare `safety-test`, so check the installed command's help before recommending it. For interactive `unjiggle suggest`, inspect each step before accepting it; do not run `--apply-all` as a shortcut. For clients using `unjiggle json apply`, include the reviewed preview's `snapshot_id` and check the resulting layout on the phone.

If the snapshot is stale, the preview differs from the phone, a verification fails, or iOS reflows icons unexpectedly, **stop**. Do not auto-retry a write, apply a different preview, or automatically restore a backup. Keep the backup and error output, inspect the phone, and decide manually what to do next. A restore is itself a phone write and needs fresh, explicit consent.

Read the [command and JSON reference](../README.md#commands-and-api) for the existing CLI contract. Learn more at [unjiggle.com](https://unjiggle.com/?source=github-agent-guide).
