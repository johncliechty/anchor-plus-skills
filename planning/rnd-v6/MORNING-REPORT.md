# v6 "Linked Pipeline" — Morning Report for John (2026-06-14, overnight)

You said: do the Crucible plan, then go right into the Foreman build. Done — **all 8
waves GREEN**, on a branch, nothing merged, your live Anchor at :8777 untouched.

## TL;DR
- **Plan forged** (Crucible) and frozen in `planning/rnd-v6/` — passes Foreman's
  `locate-plan.mjs` gate (8 waves). Centerpiece for your review.
- **Built** (Foreman-style: fresh-context execute → orchestrator-run gate → adversarial
  review → screenshot → commit) on branch **`foreman/rnd-surface-v6`**.
- **Full suite: 807 passed, 1 skipped** (the 1 skip is the pre-existing host git-symlink
  skip). Started from 724 (with the summarizer fix); v6 added ~83 tests.
- **NOT merged to master. Service NOT restarted.** Your v5/v6 rule = your sign-off on UI
  before merge, and you were asleep. Everything waits for you.

## What got fixed (your asks, mapped)
| Your ask | Wave | State |
|----------|------|-------|
| Session windows: minimize / **resize** / **maximize** | W3 | ✅ built + screenshot |
| Every new session = a new tile (not reused) | W4 | ✅ verified all 5 start paths |
| Finished tiles stay, newest up top + "previously done" | W4 | ✅ built + screenshot |
| Research → Planning advance **on my click** | W5 | ✅ "Advance to Planning →" button |
| Planning → Build advance **automatically** (when a real plan exists) | W6 | ✅ fires on hard-kill; idempotent |
| All same-problem sessions **linked** into one chain | W2+W5 | ✅ parent/chain + clickable breadcrumb |
| **Summary still old/uninformative** | W1 | ✅ root-caused + fixed (was empty in prod) |
| **Main dashboard reflect project activity** | W7 | ✅ running count + objective + latest-activity |
| Calendar / app-builder | — | ⛔ out of scope, as you said |

## Review the UI (5 screenshots — no setup needed)
Open these PNGs (I looked at each against the mockup):
- `_devtest/wave3_normal.png` / `wave3_maxed.png` — the 5 window controls; maximize fills
  the screen and the terminal re-fits.
- `_devtest/wave4_tiles.png` — multiple tiles; finished ones greyed + "previously done".
- `_devtest/wave5_advance.png` — the green "Advance to Planning →" bar on a research panel.
- `_devtest/wave6_autobuild.png` — kill a planning session → a linked **Build** tile
  auto-opens with a "→ auto-opened Build … from this plan" banner + a `P planning →
  build` breadcrumb.
- `_devtest/wave7_dashboard.png` — the home row now shows objective + `running: 1` +
  `latest: Planning · …` instead of a bare dot.

The approved interaction mockup is `_mockups/rnd-v6/session_pipeline.html` (the
plain-English walkthrough you signed the decisions off against).

Want it live before merging? From the branch, a throwaway preview that never touches
:8777 or real data:
```
git checkout foreman/rnd-surface-v6
python anchor_gui.py --port 8799 --no-browser   # then open http://localhost:8799
```

## 3 small decisions I left for you
1. **Auto plan→build trigger.** It fires when you **hard-kill** a planning session that
   produced a plan (the deliberate "I'm done planning" gesture). If you'd rather a
   dedicated **"Finish → Build"** button, that's a tiny add — say the word.
2. **Wave 3 vertical resize.** Dragging a window *taller* grows the summary area, not the
   terminal rows (width-drag + maximize re-fit the terminal correctly). Want vertical drag
   to grow the terminal instead? Quick polish.
3. **Reconcile fallback.** The auto-advance also has a "reconcile-dead" fallback (built +
   tested) but it isn't auto-run by the live server yet — hard-kill is the wired trigger.
   Wiring an auto-reconcile-on-load is a separate, slightly behavior-changing decision.

## To ship it (after you sign off)
```
git checkout master
git merge --no-ff foreman/rnd-surface-v6
nssm restart anchor        # elevated shell
# then in the dashboard, Rescan each project — this HEALS the empty summaries
#   (the parse fix only regenerates caches on rescan)
```
The summarizer fix (`1bd8b85`, your own in-session fix that never got merged) is the base
of this branch, so merging v6 also finally lands it on master.

## Commit trail (branch `foreman/rnd-surface-v6`)
`a43273d` summarizer fix → `f48e5d2` plan → W1 729 → W2 747 → W3 753 → W4 760 → W5 766 →
W6 778 → W7 787 → `ecf5b6b` W8 807. Per-wave detail in `EXECUTION-LOG.md`.
