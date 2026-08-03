# Tidy-Idy

**One sentence:** Folder hygiene with a human triage panel — propose removals, saves, reorg, and secret flags, then apply once with reversible trash (not silent mass delete).

## Use this when
- A project or folder is cluttered and you want guided cleanup
- You want to approve each class of change before anything moves
- You need restore-friendly trash rather than permanent delete-first

## Do not use this when
- You want an unsupervised “delete everything junk-looking” bot
- You need source-code refactoring or feature builds
- You’re hunting live process zombies (use Zombie Hunter)

## What you get
- A scan plus a decision-first triage panel in the browser
- Cards for removals, SAVE, reorg proposals, and secrets
- One Apply per run into a reversible trash move-set (restore supported)
- Optional git commit when the folder is a repo

## What it is not
- Not auto-apply — nothing settles until you Apply
- Not a second Apply on the same run without a re-scan
- Not a silent security product; secrets findings still need your judgment

## How to start (human)
1. Launch Tidy-Idy on the folder (terminal or Anchor’s button).
2. Open the triage panel and approve/reject items.
3. Press Apply once when the set looks right.
4. Use trash restore (or git) if something should come back; re-scan for leftovers.

## Limits (honest)
- One Apply settles that run’s approved set; leftovers need another pass
- Plain folders work; git is an upgrade, not a requirement
- Capability/auth for the panel stays in-session — don’t expect a shareable secret URL

## For agents / engines
Full protocol and wiring live in `SKILL.md` next to this file. Load that only when running the skill — this card is for people.
