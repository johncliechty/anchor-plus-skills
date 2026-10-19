# Axmra Snapshot — 2026-05-02

This is a frozen copy of the contents of `C:\Users\jcl12\OneDrive - Axmra\Anchor Axmra\` taken on 2026-05-02, immediately before the Axmra sibling was merged into the main `C:\dev\Anchor\` folder and decommissioned.

## What's here

- `.anchor/DASHBOARD.md`, `.anchor/PROJECTS.md`, `.anchor/INBOX.md` — the commercial-side state files (last live edit 2026-04-09)
- `.anchor/logs/2026-04-09.md` — only surviving Axmra log file
- `.claude/skills/dashboard/SKILL.md` — Axmra-specific dashboard skill (the Anchor folder picked up its own version during the merge)
- `CLAUDE.md` — Axmra CLAUDE.md as it stood
- `dashboard.jsx` — stale React mockup (predecessor of the current Python-served HTML dashboard)

## What's NOT here (intentionally)

These files in Axmra were duplicates of what already lives in `C:\dev\Anchor\` (the canonical copy). They were not copied to keep the snapshot lean:

- `anchor.py`
- `anchor_gui.py`
- `launch_anchor.pyw`
- `setup_shortcut.py`
- `dashboard.html` (auto-generated artifact)
- `.write_test` (empty marker file)

If you ever need any of the above as they existed in Axmra, they may still be on the OneDrive trash/version history.

## Why this snapshot exists

Up until 2026-05-02 the productivity system had two synced folders: an "Anchor PSU" OneDrive folder (primary) and an "Anchor Axmra" OneDrive folder (commercial sibling). On 2026-05-02 the active folder was moved to `C:\dev\Anchor` to escape OneDrive instability. Sibling discovery silently broke at that point because Axmra was no longer in the same parent directory, so dev became the sole live folder and Axmra froze.

This snapshot was taken right before merging the Axmra commercial detail into `C:\dev\Anchor\domains\commercial.md`, `PROJECTS.md`, and `DASHBOARD.md`, so that the proprietary commercial data (e.g. the Nexia/Axmra fundraising details, OpX redo, Archty, NextGen Nuclear wind-down) is preserved exactly as it was.
