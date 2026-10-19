# Anchor R&D Surface v5 — "Durable Work" — Master Plan (frozen design)

> Crucible Stage 1 output, locked 2026-06-14. Builds on the v4.1 "Project Cockpit"
> (merged): clean Paradigm-2 project window (tile board → inline panels with split
> summary + terminal), engine toggle, grass idea board, deliverable launch-by-type,
> flat dashboard rows, Option B branding, plus the terminal fixes (full-width fit,
> Ctrl+V paste, no-freeze pump). v5 makes the surface **durable and resumable**:
> sessions don't vanish, past work opens to a real summary you can continue, ideas
> are a filterable two-pane workbench, every build has a listed deliverable, and
> project summaries actually say what the project is for.

## North Star (locked)

Make every R&D session and idea a **durable, resumable, well-summarized unit of
work**. Closing a session never loses it (it stays a reopenable tile); a *separate*
deliberate action kills it. Opening a past session shows a **real summary** — the
skill invoked, the prompts asked, the actions/files produced — with one click to
**continue it in a fresh live session** seeded from that context. The Grass Catcher
is a **filterable two-pane idea workbench**: ideas carry stable ids and a
raw→refined→promoted status, are developed in-place with Research/Plan, versioned,
and pulled into other efforts. **Every Foreman build has a clearly identified
deliverable**, listed both in the Deliverables lane and inside that build's panel.
And the **project summary** on the dashboard row and project header conveys the
project's actual objective/purpose — not boilerplate.

## Why v5 (what's wrong today, from live use)

1. **Closing a run destroys it.** X on a session panel removes it entirely — a
   started research run vanished. There's no "keep it around to reopen" vs.
   "deliberately kill it" distinction.
2. **A past session is a dead end.** Opening a done/historical session shows only
   "session complete" — no sense of what it did, and no way to pick it back up.
3. **Project summaries are uninformative.** The one-liner (row) and project-header
   summary don't capture the project's objective/task/purpose.
4. **Foreman builds have no visible deliverable.** A build runs but no deliverable
   is identified or listed — neither in the Deliverables lane nor in the build's
   own panel.
5. **The Grass Catcher is thin.** It needs to be a real idea workbench (filter by
   status, switch between ideas fast, develop an idea with a tool, version and pull
   refinements into efforts).

## Locked decisions (Stage 0/1 user gates)

1. **Run lifecycle = close-to-tile vs. deliberate kill.** The panel's **X closes
   the panel but KEEPS the session as a reopenable tile** (the session/record
   persists; a running session keeps running; a done one stays done). A **separate,
   clearly-distinct control hard-KILLS** the session (terminate + remove worktree +
   drop the tile), behind an "Are you sure?" confirm. The two are visually and
   behaviorally distinct; closing must never lose work.
2. **Past-session view = real summary + continue-live.** Opening a done/historical
   session shows a summary: **the skill invoked, the prompts/turns asked, and the
   actions/files produced** (built from the session's transcript/log + member docs,
   through the validated `summarizer` seam — cached, generate-once). A **"Continue
   in a live session"** button starts a NEW live terminal session in the same lane,
   **seeded with that session's context** (its summary/transcript), so the user can
   pick the work back up. Reuses the Wave-1 seed path (`terminal_session.start_session`
   with `seed_context`).
3. **Better project summaries.** Improve `summarizer.summarize_project`: a stronger
   seed (CLAUDE.md / README / Anchor.md + newest plan docs + pinned deliverables +
   lane activity) and a prompt that extracts the **objective/task/purpose** in 1–2
   sentences, grounding-filtered. Cached (generate-once on rescan; `force`
   regenerates). The dashboard row + project header READ the cache; never a
   synchronous model run on render.
4. **Deliverable per Foreman build.** Every Foreman build run resolves a
   **deliverable** (the artifact it produced — from the run's output / pinned path /
   `foreman.config` `docs`/declared marker). **Backfill:** scan existing build
   sessions per project and resolve their deliverables. List deliverables in the
   **Deliverables lane** AND inside each **Build session's panel**. When a build
   genuinely has no resolvable deliverable yet, say so honestly ("no deliverable
   pinned yet") — never fabricate one.
5. **Grass Catcher = B+C hybrid workbench** (approved mockup
   `_mockups/grass_catcher_refined.html`): a **filter-tab row** (All / raw / refined
   / promoted [+ search]) over a **two-pane workbench** — idea list left, the
   selected idea's workbench right (idea text + **Develop: Research / Plan** in the
   workbench terminal + engine toggle + **Promote to a lane**). Ideas carry stable
   ids (`grass-<hash>`) and a **raw→refined→promoted** status; refinements are
   **versioned** (`grass-<id>/dev-N`), logged, and **pullable into other efforts**;
   a **promoted** idea links to the run it became. **Project-scoped** (a
   cross-project Grass view is out of scope for v5). Developing happens in the
   workbench terminal (with a "Promote to a lane" when an idea graduates).
6. **Terminal vertical resize is already shipped** (v4.1 fit fix) — v5 only adds a
   guard test; no rework.
7. **Verification standard (non-negotiable, baked into every UI wave).** "Done" for
   any UI change = **rendered-DOM assertions** (parse the served HTML, positive AND
   negative) **+ a real Playwright/Chromium interaction test** (click the thing,
   assert the result) **+ a screenshot the orchestrator visually checks against the
   mockup** **+ the user's sign-off before merge**. A string-grep test is NEVER
   sufficient. This is the lesson from v4 (a vacuous gate shipped a broken UI).
8. **Scope = one Foreman build** on `C:\dev\Anchor`, every wave GREEN on
   `python -m pytest -v`.

## Inclusion test (the size rule)

Every wave serves a North-Star criterion. **Out of scope** (bloat / later):
cross-project Grass view, a full transcript replay/scrubber (a summary suffices),
re-architecting the summarizer pipeline (extend it), multi-user, and any change to
the proven terminal substrate beyond what items above require.

## Hard constraints (from CLAUDE.md — non-negotiable)

- **Python stdlib only**, except the declared lazy `pywinpty` (in `pty_manager.py`
  only). **Playwright is a DEV-ONLY test dependency** (`pytest.importorskip`), never
  imported by product code; `distro.py`'s import scan must stay green.
- **Never bind/touch the live `:8777` service or real data in tests/healthcheck.**
  Model calls via `tests/fake_claude.py` (`ANCHOR_RUNNER_CMD`); PTY via the stub
  backend (`ANCHOR_PTY_BACKEND=stub`); any spawned preview/service on an OS-assigned
  port **HARD-guarded `!= 8777`** with an isolated temp `ANCHOR_DATA_DIR`.
- **All mutating / terminal / launch endpoints** behind the `do_POST` token gate;
  GET read-only (token via `?token=`).
- **f-string brace discipline** in `anchor_gui.py` (`_PROJECT_WINDOW_JS` is a RAW
  single-brace string; doubled braces in f-string HTML/CSS).
- **Mirror** new data seams into `anchor.py`; **extend** `anchor_healthcheck.py`
  (`check_rnd_v5_surface`, fully stubbed); **update** `CLAUDE.md`.

## Risks & mitigations

- **R1 — "keep as tile" leaks running PTYs.** Closing a panel must not kill the PTY,
  but a killed/closed-then-forgotten running session shouldn't run forever.
  Mitigation: closing keeps the registry record + tile; the session reconciler
  already re-statuses dead sessions; hard-kill is the explicit reap. Test: close
  keeps the record + a live PTY; kill reaps it with no orphan.
- **R2 — continue-live duplicates/!diverges work.** Continue seeds a NEW session
  (new worktree) from the prior summary; it does not mutate the original. Test:
  continue starts a fresh session seeded with the prior context; original intact.
- **R3 — summary fabrication.** Both session and project summaries go through the
  generate-twice + grounding filter; ungrounded claims dropped; honest "no
  metrics"/"no deliverable" when data is absent.
- **R4 — deliverable backfill mis-identifies.** Resolve from explicit signals
  (pinned path / config docs / declared marker / known build output) only; when
  ambiguous, list "unresolved — pin one" rather than guessing.
- **R5 — another vacuous UI gate.** Mitigated by Locked Decision 7 (Playwright +
  screenshot + sign-off mandatory per UI wave).

## Definition of done (project)

All waves GREEN on `python -m pytest -v`; closing a session keeps it as a reopenable
tile and a separate control hard-kills it; a past session opens to a real summary
(skill + prompts + actions) with a working "continue in a live session"; project
summaries convey the objective on the row + header; every Foreman build's deliverable
is listed in the Deliverables lane and its build panel (honest when none); the Grass
Catcher is the B+C hybrid workbench (filter tabs + two-pane + develop terminal +
versioned/pullable refinements + promote links + search); the CLI mirrors the new
seams; `check_rnd_v5_surface` passes fully stubbed; `distro` scan clean; CLAUDE.md
updated; and every UI wave is verified by Playwright + a screenshot + user sign-off.
