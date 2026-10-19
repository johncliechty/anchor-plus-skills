# Anchor R&D Surface v8 — "Durable Artifacts" — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, locked 2026-06-16. Frozen design: `MASTER-PLAN.md` (this
> folder). Build cwd = repo root `C:\dev\Anchor`, branch `foreman/rnd-surface-v8` (off
> master, v7 merged). Each wave ends GREEN on the ground-truth gate and adds/extends
> tests. Wave order honors the keystone dependency: git-init (W1) → doc persistence
> (W2) → everything that needs durable docs (W3–W7).

test-command: python -m pytest -v

## Conventions (read before any wave)

- **Active Anchor project id:** read from `rnd_registry.json` at build time; never
  hard-code.
- **No live `claude`/`gemini`/real-PTY in the gate, and NEVER real `git push`/`gh`/
  network/real GitHub.** Model calls via `tests/fake_claude.py`/`tests/stub_streamjson.py`
  (`ANCHOR_RUNNER_CMD`); PTY via `ANCHOR_PTY_BACKEND=stub`. **git/gh/remote operations go
  through an injectable seam** (a `_run`-style indirection or env-gated command, like the
  existing `worktrees._git`) that tests stub — temp local repos only, no network, no real
  `gh`. Never `:8777` or real data.
- **`git` + `gh` are external CLIs** (subprocess), not python deps — degrade gracefully
  when absent. **pywinpty** stays the only native dep (lazy, `pty_manager.py`). **Playwright
  is DEV-ONLY** (`pytest.importorskip`), never in product code; `distro.py` scan green
  (W8 asserts it).
- **f-string discipline** in `anchor_gui.py`: `_PROJECT_WINDOW_JS` is RAW single-brace;
  double literal braces in f-string HTML/CSS.
- **Security:** every new mutating / terminal / git-remote / push endpoint behind the
  `do_POST` token gate; GET read-only (`?token=`). Default new GitHub repos to **private**.
- **Reuse, don't fork:** `worktrees.py`, `terminal_session.py`, `handoff.py`,
  `effort_history.py`, `session_registry.py`, `summarizer.py`, `sessions.py`,
  `brownfield_scan.py`, the v6/v7 board/tile/chain/blurb seams.
- **Scoped commits only** — never the runtime-data churn (`dashboard.html`, `PROJECTS.md`,
  `DASHBOARD.md`, `domains/*`, `INBOX.md`, `.anchor/`, `rnd_jobs/`, `rnd_registry.json`,
  `logs/`). Commit only the code/test files each wave touched.
- **Baseline before Wave 1:** the v7 merge baseline was **888 passed, 1 skipped**.
  Re-establish at Wave 1 start; each wave holds or grows it.
- **UI VERIFICATION IS MANDATORY (the v4 lesson)** for every wave that changes rendered
  UI (Waves 3, 4, 5, 6, 7): (a) rendered-DOM (positive+negative, `html.parser`); (b) a
  real Playwright+Chromium interaction test; (c) an orchestrator screenshot (PNG under
  `_devtest/`) Read + checked vs the rnd-v8 mockup; (d) user sign-off before merge. A
  string-grep-only test is an automatic HALT.

---

## Wave 1 — Project bootstrap: auto git-init + starter CLAUDE.md (backend; the prerequisite)

Fix the "not-a-git-repo" error and give the keystone a repo to commit to. Add a
`project_bootstrap.ensure_git_repo(folder)` + `ensure_claude_md(folder, name)` (best-effort,
idempotent, through the injectable git seam): on `select_existing_project` /
`create_new_folder_project` / `open_project` / `discover_and_adopt` (the rescan path), if
the folder is not a git repo → `git init` (+ an initial commit of existing files honoring
`.gitignore`), and if there's no `CLAUDE.md` → write a minimal starter (project name +
"R&D project managed by Anchor"). `worktrees.create_worktree` no longer dead-ends a
session start: if the project became a repo via bootstrap, the worktree succeeds; if git
is genuinely unavailable, surface a clean message (not a stack trace).

- **Done-when:** `pytest` GREEN; registering/opening/rescanning a non-git folder makes it
  a git repo (idempotent — a second call is a no-op) + creates a starter CLAUDE.md if
  absent; starting a research session on a freshly-bootstrapped project no longer returns
  `not-a-git-repo`; git-absent degrades to a clean surfaced message.
- **G/W/T:** **Given** a temp folder with a few files and no `.git`, **When** it is
  registered/opened/rescanned, **Then** it becomes a git repo with an initial commit and a
  starter `CLAUDE.md`, and a subsequent `create_worktree`/session start succeeds; **Given**
  an already-git repo with a CLAUDE.md, **Then** bootstrap is a no-op (nothing clobbered).
- **Tests:** `tests/test_project_bootstrap_v8.py` — ensure_git_repo (init + idempotent +
  honors .gitignore), ensure_claude_md (created when absent, never overwrites), the
  register/open/rescan paths invoke it, worktree-after-bootstrap succeeds, git-absent
  clean. Backend (git seam stubbed; temp repos only).

## Wave 2 — Trio document persistence (THE KEYSTONE; backend)

Make produced documents durable. Add `effort_history.persist_session_docs(folder, pid,
lane, session_id, worktree_path)` (or extend the finish path) that, on session finish/kill
**before the worktree is reaped**, collects the documents the session produced in its
worktree (the new/changed files under the lane's output dirs — e.g. `planning/**`,
`research/**`, the report/plan/exec-log) and **persists them into the main project**
(copy into the main folder AND/OR commit to the project repo) so they survive and are
discoverable. Generalize `capture_plan_set` → `capture_session_docs` (capture before
reap). Wire it into `terminal_session.kill` / the finish hooks so EVERY trio session's
docs land in the project. `discover_recent_plan_set` and the build worktree (off main
HEAD) then find them.

- **Done-when:** `pytest` GREEN; finishing/killing a planning session persists its plan
  docs to the project (present in the main folder + committed); a build worktree created
  afterward CONTAINS those docs; nothing is lost when the worktree is reaped; only the
  session's produced docs (+ pointer-records) are committed (user's unrelated files
  untouched); idempotent (re-persist doesn't duplicate-commit).
- **G/W/T:** **Given** a planning session that wrote `planning/rnd-x/MASTER-PLAN.md` +
  `IMPLEMENTATION-PLAN.md` in its worktree, **When** it is killed, **Then** those files are
  persisted to the main project (and committed) BEFORE the worktree is reaped, and a
  subsequently-created build worktree contains them; **and** `discover_recent_plan_set`
  finds the plan set from the main folder.
- **Tests:** `tests/test_doc_persistence_v8.py` — capture-before-reap (docs survive a kill;
  worktree gone); persisted into the project + committed (scoped to produced docs); build
  worktree contains them; discover_recent_plan_set finds them; idempotent. Backend (stub
  PTY + temp git project + git seam).

## Wave 3 — Link GitHub + Option-A auto-push (UI + backend)

The offsite layer. Add `project_remote.link_github(folder, mode, url_or_name)` (through the
git/gh seam): `mode='create'` → `gh repo create <name> --private` then `git remote add` (gh
authed as johncliechty; degrade to paste-URL if gh absent/un-authed), `mode='existing'` →
`git remote add origin <url>`. Add a per-project **auto-push opt-in** flag (persisted) and
`push_project(folder)` (`git push`). A permission-gated **"Link GitHub"** UI control
(project-window header) with the create-new / paste-existing / not-now choices; once linked,
an **opt-in toggle** ("auto-push this project's work") + a manual **"Push now"** button.
Wire auto-push into the session-finish path (push only when linked + opted-in). Rescan
sets up git/remote if missing (reusing W1 + this).

- **Done-when:** the UI-verification set passes — "Link GitHub" creates-or-links a remote
  (stubbed gh/git), the opt-in toggle persists, finishing a session auto-pushes ONLY when
  linked+opted-in, the manual "Push now" works, and a non-opted/non-linked project never
  pushes; gh-absent shows paste-URL only.
- **G/W/T:** **Given** a bootstrapped project with no remote, **When** the user picks
  "Create new private repo", **Then** a remote is linked (stubbed) and shown; **When** the
  user enables auto-push and finishes a session, **Then** the project is pushed once
  (stubbed); **Given** a project not linked/opted-in, **When** a session finishes, **Then**
  no push occurs.
- **Tests:** `tests/test_github_link_v8.py` — link create/existing (seam-stubbed, no
  network) + opt-in persist + auto-push-on-finish only when linked+opted + manual push +
  gh-absent paste-only + token-gated endpoints + DOM/Playwright (the Link prompt + opt-in
  toggle + Push button) + screenshot.

## Wave 4 — Handoff that carries the documents (backend + UI)

Now docs are durable, make the handoff real. Replace `_build_seed_for_plan` (and add the
research→plan analog) with a generated seed that lists the **actual persisted document
paths** + a short "read these first, then proceed" instruction + the correct skill. The
advance/auto-advance/finish-to-build paths pass this as `seed_context`; `prime_worktree`'s
HANDOFF.md now references paths that genuinely exist in the checkout. Verify build loads
**Foreman** (not Crucible) and research→plan loads **Crucible** (the user's confusion —
assert the mapping + surface the loaded skill in the panel header so it's unambiguous).

- **Done-when:** the UI-verification set passes — advancing planning→build seeds the build
  with the real plan-doc paths + Foreman; the build's HANDOFF.md references existing files;
  research→plan seeds with the report path + Crucible; the panel header shows which skill
  loaded.
- **G/W/T:** **Given** a finished planning session whose docs are persisted (W2), **When**
  the user advances to build, **Then** the build session's seed contains the real
  `planning/.../IMPLEMENTATION-PLAN.md` path + a read-first instruction and loads Foreman,
  and HANDOFF.md points at files that exist in the build checkout.
- **Tests:** `tests/test_handoff_docs_v8.py` — seed contains real persisted paths +
  correct skill (plan→build Foreman; research→plan Crucible); HANDOFF.md references exist;
  panel shows the loaded skill (DOM) + Playwright (advance → build seeded with paths) +
  screenshot.

## Wave 5 — No-loss lifecycle: summary+docs on kill, promote to big tiles, detail view (UI + backend)

Make kill a graceful close-out. On kill, BEFORE reap: persist the produced docs (W2) +
compile/persist a **summary record with a stable ID + references** (reuse v7 summarize +
the durable docs). Then promote the session to the **big board tiles** (it becomes a lane
session via the persisted effort) and remove its **little top-strip chip**. Clicking the
big tile opens a **detail view**: the deliverable, the produced docs (links), the summary
context, and a **"Continue the dialog"** (continue-live, v6 seed) button. Same for
research/plan/build.

- **Done-when:** the UI-verification set passes — killing a session writes a summary+docs
  record (stable id) before reap; the little chip disappears and a big lane tile appears;
  the big tile's detail view shows deliverable + docs + summary + a working "Continue"; no
  work is lost.
- **G/W/T:** **Given** a running build session that produced an artifact, **When** the user
  kills it, **Then** before reap a summary+docs record (with an id + references) is
  persisted, the top-strip chip is removed, a big Build lane tile appears, and clicking it
  shows the deliverable + docs + summary + a Continue button that starts a seeded live
  session.
- **Tests:** `tests/test_no_loss_lifecycle_v8.py` — kill persists summary+docs+id before
  reap; chip→big-tile promotion; detail view content (deliverable/docs/summary/continue);
  continue-live seeded from the durable summary (DOM + Playwright + screenshot).

## Wave 6 — Grass: self-contained, cumulative, exportable (UI + backend)

Rebuild the grass workbench per the locked decision. (a) **One contained session per
(idea, lane):** `develop_grass_idea` resolves an EXISTING live research/plan session for
that idea+lane and **focuses** it instead of starting a new one; a develop session is
**contained** — NOT added to `MANAGED`/`renderSessionBar`/the board (it lives only in the
workbench pane). (b) **Cumulative history:** per-idea research/plan efforts are logged with
kept summaries, resumable/continuable (extend the versioned-refinement store). (c) **No
Build** in grass. (d) **"Export to project" (Option B):** copies the idea's research/plan
work UP into the real lane tiles (as linked sessions carrying the persisted docs/summaries)
AND leaves the idea in grass marked **"promoted"** with a link to its new project sessions.

- **Done-when:** the UI-verification set passes — clicking Research/Plan in an idea opens
  ONE contained session; clicking again FOCUSES it (no new session, no top-strip chip, no
  board tile); the idea accumulates resumable efforts with summaries; "Export to project"
  creates real linked lane tiles carrying the docs and marks the idea "promoted" (still in
  grass); no Build control in grass.
- **G/W/T:** **Given** an idea workbench, **When** the user clicks "Develop with Research"
  twice, **Then** exactly one research session exists (the second click focuses it) and it
  does NOT appear in the top strip or board; **When** the user clicks "Export to project",
  **Then** the idea's research/plan work appears as real linked lane tiles (with docs) and
  the idea remains in grass marked "promoted" linking to them.
- **Tests:** `tests/test_grass_contained_v8.py` — dedupe/focus (two clicks → one session) +
  contained (not in MANAGED/board) + cumulative efforts + export carries docs + idea stays
  "promoted" + no build + DOM/Playwright (workbench focus + export) + screenshot.

## Wave 7 — Full chain navigation (UI)

Make the chain navigable on durable artifacts. From any session's panel/tile, render the
**linked chain** (research↔plan↔build via `chain_members`) as clickable nodes; clicking a
sibling opens THAT session's detail (summary + docs + continue) or focuses it if live.
Works for partial chains (research with no downstream; build with no upstream — honest, no
fabricated nodes). Build on the v6 breadcrumb + the now-durable W2/W5 records.

- **Done-when:** the UI-verification set passes — opening a build session shows its linked
  planning + research siblings and clicking them opens their detail; opening a research
  session shows its downstream plan/build; a partial chain shows only the existing siblings.
- **G/W/T:** **Given** a build session with an upstream plan + research, **When** its panel
  opens, **Then** the chain shows research→plan→build and clicking the plan node opens the
  plan's detail (summary+docs+continue); **Given** a research session with no downstream,
  **Then** the chain shows only research (no fabricated nodes).
- **Tests:** `tests/test_chain_nav_v8.py` — chain renders linked siblings; click opens the
  sibling detail/focus; partial chains honest (DOM + Playwright back-and-forth navigation) +
  screenshot.

## Wave 8 — CLI mirror + healthcheck v8 + distro scan + docs (PROJECT DONE)

Mirror the new read seams into `anchor.py` (e.g. `rnd remote <pid>` [link/opt-in status,
read-only]; `rnd docs <pid> --session` [persisted doc list]). Extend `anchor_healthcheck.py`
with `check_rnd_v8_surface` (fully stubbed: stub PTY + stream-json stub runner + temp
worktree base + temp git project + **stubbed git/gh seam, no network**): walk (a) bootstrap
(non-git temp → git-init + CLAUDE.md, idempotent); (b) doc persistence (kill persists docs;
build worktree contains them; discover finds them); (c) handoff seed carries real paths +
correct skill; (d) no-loss (kill → summary+docs+id before reap, promotion); (e) grass
contained+export; (f) link/opt-in/push seam (stubbed, no real push). Tear everything down,
restore env, never `:8777`, never real network. Confirm `python -m distro` scan clean.
Update `CLAUDE.md` (a v8 "Durable Artifacts" section + the new endpoints/CLI + the git/gh
seam + the bootstrap/persistence/handoff/grass changes).

- **Done-when:** the **full** suite GREEN; the new CLI subcommands work; `check_rnd_v8_surface`
  passes fully stubbed + tears down (no `:8777`, no real network/push, no orphan
  PTY/worktree); `python -m distro` scan clean; `CLAUDE.md` documents v8.
- **G/W/T:** **Given** the stubbed env, **When** `check_rnd_v8_surface` runs, **Then** it
  walks bootstrap + persistence + handoff + no-loss + grass + remote and tears down with no
  orphan, never binding `:8777` and never hitting real GitHub; **and** distro reports only
  the declared `pywinpty` exception (no Playwright in product code).
- **Tests:** `tests/test_cli_v8.py`, `tests/test_healthcheck_v8.py`, `tests/test_distro_scan_v8.py`
  — and the whole suite GREEN.

## Project DONE

DONE = Wave 8 GREEN on `python -m pytest -v` AND the Master Plan "Definition of done" met
— including the UI waves' (3–7) Playwright + screenshot + **John's sign-off**. Terminal wave
= Wave 8. **No merge to master / no `nssm restart anchor` until John signs off** (then:
merge → `nssm restart anchor` elevated → rescan to bootstrap git/CLAUDE.md + heal).
