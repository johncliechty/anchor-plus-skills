# Anchor R&D Surface v8 — "Durable Artifacts" — Master Plan (frozen design)

> Crucible Stage 1 output, locked 2026-06-16. Follows the merged+deployed v7
> "Integrated Board". Comes from J.C. Liechty's dense live-use feedback after running
> real trio sessions. Build cwd = repo root `C:\dev\Anchor`. Each wave ends GREEN on
> `python -m pytest -v` and extends v6/v7 seams (no new modules unless justified).

## The keystone finding (verified in code)

Trio sessions run in a throwaway git **worktree**, and Anchor commits only tiny
`.pointer.json` *metadata* — **the actual documents a session produces (MASTER-PLAN.md,
the research report, EXEC-LOG, etc.) are never saved to the project and are deleted when
the session's worktree is reaped on kill.** Consequences the user hit directly: the
Build session (checked out from main HEAD) "has no idea where the planning documents
are"; killing a session loses the work; `discover_recent_plan_set` (reads the main
folder) can't find the docs; the chain breadcrumb points at vanished artifacts. **Making
trio documents durable is the keystone that makes the handoff, the no-loss lifecycle,
and the chain navigation all actually work.**

## North Star (locked — John's Stage-0 answers)

Make every trio session's **work durable, discoverable, and resumable**, and make the
project a real git-backed home for it:

1. **No project starts broken.** Opening Research/Planning on a project with no git repo
   must not error. On register / open / **rescan**, if there's no local git repo →
   `git init`; if there's no `CLAUDE.md` → create a starter one; and offer a
   permission-gated **"Link GitHub"** (create a new private repo via `gh`, or paste an
   existing URL). Once linked + opted in, **auto-push after each session finishes**
   (Option A) plus a manual "Push now"; rescan sets up git/remote if missing.
2. **Trio documents are durable.** A research/planning/build session's produced
   documents are **persisted to the project** (committed to the project repo) on finish
   — surviving kill, discoverable by later stages, and present in the next stage's
   checkout. No work is ever stranded in a reaped worktree.
3. **Handoffs carry the documents.** Advancing a session (research→plan, plan→build)
   seeds the next session with a **generated prompt containing the actual document
   paths** (and a short "read these first" instruction) plus the **correct skill**
   (research→researchPrime, plan→Crucible, build→Foreman). The build genuinely picks up
   the plan.
4. **Nothing is lost; kill is a graceful close-out.** When a session is killed, **before
   the reap completes** Anchor compiles + persists a **summary (with references + a
   stable ID)** and the produced **deliverable/docs**; the session is then promoted to
   the **big board tiles** and its little top-strip chip disappears. Clicking the big
   tile shows the **deliverable + the produced docs + the summary context + a "continue
   the dialog"** (continue-live) action. Same for research / plan / build.
5. **The Grass Catcher is a self-contained brainstorming bench.** Inside an idea's
   workbench, **Research and Plan each open exactly ONE contained session** — clicking
   again **focuses** the existing one (never a new stacked session) — and these are
   **contained in the workbench**, never leaking to the top strip or board tiles. Each
   idea has a **cumulative history** of research/plan efforts with kept summaries
   (resumable/continuable). **No Build in grass.** An **"Export to project"** button
   promotes an idea's work UP into the real lane tiles, **carrying its docs/summaries/
   efforts** (Option B: a copy — the idea stays in grass marked "promoted" with a link
   to where it went).
6. **The chain is fully navigable.** From any session (research/plan/build) you can move
   **back and forth** across its linked siblings, each opening that session's real
   summary/docs/continue — built on the now-durable artifacts.

## Why v8 (what John hit in live use)

1. New/sparse projects **error** on the Research/Planning tab ("not-a-git-repo");
   there's no auto git-init, no CLAUDE.md, no remote.
2. Going planning→build opens a build window that **doesn't know where the plan docs
   are** (they were never persisted).
3. Killing a session **loses the work** — no durable summary/docs, no clean promotion
   to the board.
4. The **Grass** Research/Plan buttons **stack new sessions** and leak them into the top
   strip; there's no contained, cumulative, exportable idea bench.
5. The chain links exist but point at **vanished artifacts**, so navigation isn't useful.

## Locked decisions (Stage 0 user gates)

1. **#1 GitHub = Option A (approved).** Permission-gated link prompt (create-new private
   via `gh` — John is authed as `johncliechty`; or paste-existing). After a project is
   linked + opted in, auto-push after each session finishes, plus a manual "Push now".
   Local commits are automatic+unconditional (needed for the keystone); offsite push is
   opt-in per project. Rescan sets up git/remote if missing.
2. **#2 keystone = commit-to-project.** Trio docs are committed to the project's own git
   repo on session finish (and captured before reap). The build worktree, created off
   main HEAD, then contains them.
3. **#5 Grass Export = Option B (approved).** Export copies the idea's work up into the
   real lane tiles (carrying docs/summaries/efforts as linked sessions) AND leaves the
   idea in grass marked "promoted" with a link to its new project sessions. Inside grass:
   one Research + one Plan contained session per idea (re-click focuses), cumulative
   history, no Build.
4. **Verification standard (non-negotiable, the v4 lesson).** Every UI wave's "GREEN" =
   rendered-DOM (positive+negative) + a real Playwright/Chromium interaction test + an
   orchestrator screenshot vs the rnd-v8 mockup + the user's sign-off before merge. A
   string-grep gate is an automatic HALT.
5. **Scope = one build** on `C:\dev\Anchor`, every wave GREEN on `python -m pytest -v`.
   Branch `foreman/rnd-surface-v8`. No merge to master / no service restart without
   John's sign-off.

## Out of scope (inclusion test)

- Calendar integration, the app-builder version, floating windows (carry the fences).
- Building inside Grass (research/plan only there).
- Auto-pushing a project the user hasn't linked + opted in.
- Auto-creating GitHub repos without the permission prompt.

## Hard constraints (from CLAUDE.md — non-negotiable)

- **Python stdlib only** (+ lazy `pywinpty` in `pty_manager.py`). `gh`/`git` are invoked
  as **external CLIs via subprocess** (like the existing `git` calls in `worktrees.py`)
  — NOT python deps; degrade gracefully when absent (offer paste-URL when `gh` missing;
  never crash when `git` missing — surface a clean message). **Playwright is DEV-ONLY**
  (`pytest.importorskip`), never in product code; `distro.py` scan stays green.
- **Never bind/touch `:8777` or real data, and NEVER hit real GitHub / real `gh` /
  real `git push` in tests/healthcheck.** All git/gh/network must go through an
  injectable seam stubbed in tests (model the runner seam). Model calls via stubs; PTY
  via `ANCHOR_PTY_BACKEND=stub`; temp repos only.
- **All mutating / terminal / git-remote / push endpoints** behind the `do_POST` token
  gate; GET read-only (token via `?token=`).
- **f-string brace discipline** in `anchor_gui.py` (`_PROJECT_WINDOW_JS` RAW single-brace;
  doubled braces in f-string HTML/CSS).
- **Reuse, don't fork:** `worktrees.py`, `terminal_session.py`, `handoff.py`,
  `effort_history.py`, `session_registry.py`, `summarizer.py`, `sessions.py`,
  `brownfield_scan.py`, the v6/v7 board/tile/chain/blurb seams. **Mirror** new read
  seams into `anchor.py`; **extend** `anchor_healthcheck.py` (`check_rnd_v8_surface`,
  fully stubbed); **update** `CLAUDE.md`.
- **Scoped commits only** — never sweep runtime-data churn.

## Risks & mitigations

- **R1 — committing trio docs pollutes/!fits the project's own git history.** Commit
  ONLY the produced trio documents (+ existing pointer-records) with a clear
  `anchor: <lane> session <id>` message, honoring the project's `.gitignore`; never
  force, never touch the user's unrelated working changes. Capture docs BEFORE the
  worktree reap (extend `capture_plan_set` to a generic `capture_session_docs`). Test:
  finishing a session commits exactly its produced docs to the project repo; the build
  worktree then contains them; the user's other files are untouched.
- **R2 — git/gh absent or auth-less.** All git/gh through an injectable seam; absent
  `git` → a clean "git not available" surface (never a crash); absent/un-authed `gh` →
  the link prompt offers paste-URL only. Test (stubbed): each degraded path surfaces
  cleanly; no real network.
- **R3 — auto-push surprises / leaks.** No push until a project is BOTH linked AND
  opted-in; private repos by default; the distro secret-scan ethos (never commit
  secrets) extends to the push path. Test: a non-opted project never pushes; opt-in +
  finish pushes once (stubbed); manual push works.
- **R4 — Grass "one session per idea+lane" dedupe races / leaks.** Key the contained
  session by (idea_id, lane); re-click resolves the existing live session and focuses it
  (no new start); the develop session is NOT added to `MANAGED`/`renderSessionBar`
  (contained). Test: two clicks → one session, focused; no top-strip chip; export
  carries efforts; idea stays "promoted".
- **R5 — summary-on-kill blocks/!races the reap.** Capture docs + compile the summary
  synchronously enough to PERSIST before reap, but the heavy model summary stays the
  background path (v7) keyed to the now-durable docs; the kill response is not blocked on
  the model. The promotion to the big tile happens on the durable record. Test: kill
  persists docs + a summary record with an ID before reap; the big tile shows them;
  continue-live works; the little chip is gone.
- **R6 — chain navigation on partial chains.** A research with no downstream, or a build
  with no upstream, navigates only to existing siblings (honest); no fabricated nodes.
  Test: each partial chain navigates correctly.
- **R7 — another vacuous UI gate.** Decision 4 (DOM + Playwright + screenshot + sign-off)
  mandatory per UI wave.

## Definition of done (project)

All waves GREEN on `python -m pytest -v` AND: a non-git project auto-inits git + a
starter CLAUDE.md on open/rescan and never errors on the Research/Planning tab; the
permission-gated "Link GitHub" works (create-new via gh / paste-existing) with Option-A
opt-in auto-push + a manual push; trio documents are committed to the project repo on
finish and ride into the next stage's checkout; advancing seeds the next session with the
real doc paths + the correct skill; killing a session persists its summary+docs (stable
ID) before reap, promotes it to the big tiles (little chip gone), and the big tile shows
deliverable+docs+summary+continue; the Grass workbench opens one contained Research/one
Plan session per idea (re-click focuses, no top-strip leak), is cumulative, and "Export to
project" copies the work up (Option B) while the idea stays "promoted"; the chain is
navigable back-and-forth across real artifacts; the CLI/healthcheck/distro/docs mirror the
new seams; and every UI wave is verified by Playwright + a screenshot + John's sign-off.
