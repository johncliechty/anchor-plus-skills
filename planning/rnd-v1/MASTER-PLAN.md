# Anchor R&D Control Surface — Master Plan (frozen design)

> Forged via Crucible (Stage 0→1→2), 2026-06-07/08. Three adversarial Shark rounds at
> Stage 1, one at Stage 2, plus an empirical Spike-0 on the live host. This document is
> the **frozen design**. The buildable waves live in `IMPLEMENTATION-PLAN.md`; decisions
> and Shark findings in `DECISION-LOG.md`; human prerequisites in `SETUP.md`.

## North Star (locked)

Turn Anchor from a task/project tracker into a **per-project R&D control surface**: each
code project is a folder (e.g. `C:\dev\Agentic-Home`, `C:\dev\Anchor`); a single-instance
dashboard window drives the **researchPrime → Crucible → Foreman** trio as durable,
server-owned Claude Code jobs on gwl-server, with versioned effort history, task↔project
integration, project lifecycle states, deliverable execution, and a data-free public
distribution.

### Success criteria
- **C1** Register a code folder as an R&D project (name + path); it shows as a tab with a summary + a 4-state status line for Research / Planning / Build / Deliverables.
- **C2** Single-instance project window (re-opening focuses the existing one, best-effort).
- **C3** Durable jobs: launch research/plan/build; runs on gwl-server; survives browser close; reopening (local or Tailscale) reattaches (replays history + live tail). Multiple lanes run concurrently.
- **C4** Live log view + answer gates in-session (a collapsible console drawer).
- **C5** Versioned effort history, current-on-top, nothing lost.
- **C6** Tasks link to a project; the project view shows its tasks.
- **C7** Project lifecycle: priority change, archive, future-work (kept in a separate part of the store, not deleted).
- **C8** Deliverables (doc | script/skill | standalone program) run locally on gwl-server (read or execute), reporting status to the dashboard; deliverables integrate the trio.
- **C9** Durability/backup: registry + per-project R&D data persisted and git-trackable. Honest restart: artifacts/checkpoints persist; a live process is **restart-from-checkpoint, not transparently resumed** across a server restart.
- **C10** Shareable, **zero personal data**: Anchor is publishable to the trio's GitHub repo such that a collaborator clones a clean, empty-state tool.
- **D5** Iterative/non-linear: any project can start a new research/plan/build effort at any time, repeatedly; versioned.

### Locked decisions
- **D1 — One uniform job primitive.** A job = `claude -p --input-format stream-json --output-format stream-json` running the relevant **skill** (researchPrime / crucible / foreman) in the project cwd, **owned by the Anchor server**. Lane = which skill + prompt template. No per-lane orchestration code; no PTY; stdlib only.
- **D2 — Gate handling = in-session.** A skill's `AskUserQuestion` gate **surfaces in the stream** (it auto-dismisses headless, but the structured question is visible); Anchor renders it in a prompt box and **sends the user's choice as a plain text turn**, which drives continuation. A "gate adapter" + prompt-seed treats the auto-dismiss as "answer incoming."
- **D3 — Run as `john`.** The Anchor NSSM service is reconfigured to log on as `john`, so jobs use john's subscription OAuth directly (no LocalSystem→john handoff). *(Human prerequisite — see `SETUP.md`.)*
- **D4 — Remote = Tailscale + token.** Bind to the Tailscale interface; require a shared-secret token on every mutating `/api/*` call. No public bind.
- **D5 — New parallel R&D registry; 1 folder : N projects.** An R&D project = `{id, name, folder_path, priority, state}`, keyed by **`id`** — `folder_path` is **not** unique, so multiple projects may share one folder. A thin index distinct from the existing life-domain projects. Anchor itself is registerable (dogfood).

## Architecture (frozen)

- **Server:** existing stdlib `http.server`, upgraded to `ThreadingHTTPServer` with write-locks around every markdown **and** JSON mutation. Bound to the Tailscale interface with token auth on mutations. `ANCHOR_DATA_DIR` decouples data from code (one shared `paths` helper imported by GUI + CLI + healthcheck).
- **Job runner (the keystone):** an `ANCHOR_RUNNER_CMD`-indirected launcher spawns a server-owned `claude -p` stream-json subprocess (cwd = project), captures stdout to a durable log + ring buffer, captures `session_id` + the cost/usage/duration from each `result` envelope. Watch = long-poll (`?since=N`, 25s ceiling, swallow client disconnects). Cancel = `taskkill /T /F` (tree-kill incl. grandchildren — spike-proven). Liveness poll + startup reconciliation mark dead jobs `interrupted`.
- **Gate adapter:** parse the `AskUserQuestion` tool_use from the stream → prompt-box record persisted to the job record (`{state: awaiting-input, question, tool_use_id}`) so a reattaching client (incl. Tailscale) can answer; **single-consumer** answer (concurrent POSTs → exactly one stdin turn); answer sent as a text turn.
- **Lanes & concurrency:** research = researchPrime skill (runs to completion, no gate; project-scoped output, non-mutating); plan = crucible skill (doc-producing, project-scoped, non-mutating); build = foreman skill (**mutates the shared working tree**; `run-live.mjs` is a later optional adapter). *Within a project:* same-lane serialized, cross-lane concurrent. *Across projects sharing a folder:* **build (tree-mutating) jobs are serialized at the FOLDER level** — at most one build per folder at a time, with a clear folder-build-lock indicator — while research/plan run concurrently (project-scoped, non-mutating). The trio forbids parallel coders in one tree; the folder lock enforces it.
- **Per-project store (folder-shared safe):** each project namespaces artifacts under `<folder>/.anchor/projects/<id>/` = `research/ planning/ build/ deliverables/ jobs/`, so projects sharing a folder never collide. Anchor passes these **per-project output paths into the engines** (Crucible output dir, Foreman `--status`/checkpoint path, researchPrime output dir) so engine-native artifacts land in the project's namespace, **not** the folder root. Records are JSON **pointer-records**; a documented `.gitignore`/tracking policy reconciles C9 (git-trackable) with C10 (no leak).
- **Report viewer:** serves an effort's artifacts; **defaults to PDF** when present (LaTeX compiled via `latexmk` as a subprocess — optional host TeX toolchain), falls back to a **Reader** (markdown rendered with vendored **KaTeX** for math — no install, no Python dep). The browser renders PDF natively. The **same viewer serves plan/build docs** (`MASTER-PLAN.md`, wave docs, etc.).
- **Deliverables:** run via the same launch+watch primitive + execution timeout + stdin-closed + non-interactive enforcement; per-type success contract (doc = exists+nonempty; script/skill = exit 0 / result-no-error; program = exit 0 within timeout).
- **Distribution:** a deny-by-default shippable-file manifest + a no-personal-data scan (`C:\Users`, `john.liechty@gmail.com`, absolute paths, registry, `.anchor/`, the auth-token pattern) with a planted-secret fixture that fails the build; publish from a clean export.

## Spike-0 — empirically proven on the live host (2026-06-07)
- Headless `claude -p` authenticates on the subscription as `john`; clean result envelopes.
- Multi-turn stdin into a long-lived stream-json session works; context carries; stdlib-only.
- `AskUserQuestion` auto-dismisses headless **but surfaces in the stream**; answering as a plain text turn continues the session (keystone mechanism viable — D2).
- `taskkill /PID <pid> /T /F` reaps the full tree incl. `git`/`python` grandchildren (clean cancel, no orphan).
- "Survive browser close" is inherent (the server owns the subprocess); survive-server-restart is best-effort via re-launch (Phase F).
- **Residual (gated in `SETUP.md` go/no-go):** confirm the *real Crucible skill* drives cleanly through auto-dismiss + text-answer; its captured transcript becomes the Wave-5 test fixture.
- Cost/time/tokens are present in every `result` envelope (`total_cost_usd`, `usage`, `duration_ms`, `modelUsage`) — captured per job.

## UX design (frozen)

- **New Project & folder grouping:** a **"+ New Project"** action with two modes — *create new folder* (Anchor creates the folder + optional `git init` + `.anchor/` scaffold) or *select existing* (a server-side directory browser, since browsers can't do native folder pickers). Selecting a folder that **already hosts projects is not blocked** — it lists the existing projects and offers **"+ Add another project in this folder."** The projects view **groups projects by folder** (a collapsible folder header → its project tiles), with a **folder-level build-lock badge** when a build is running anywhere in that folder. This is how "multiple projects per folder" stays clearly managed.
- **Project tile = "Rich" (Tile A):** name + priority + state chip, one-line summary, all four lane statuses (state + age, running pulse), an **overall cost/time/tokens rollup**, and an Open button. Archived/future projects behind a filter.
- **Project dashboard = "Kanban" (Dashboard A):** four lane columns (current effort on top, history beneath, per-lane launch); **per-effort cost/time/tokens** shown within each lane section.
- **Console = collapsible drawer:** hidden when idle, slides up when a job is live/needs input. It is **one pane that attaches to the selected job**; **session tabs** list live sessions to hop between; **per-lane attention badges** (`● live`, `⚠ input`) ensure a background gate isn't missed. Clicking a **done** effort opens the report viewer instead.
- **Report viewer:** left = effort files + provenance (incl. cost/time/tokens); right = **PDF by default** (compiled from LaTeX when a TeX toolchain is present) with a **Reader (md + KaTeX)** fallback. Used for research **and** plan/build docs.
- Visual styling matches the existing Anchor dark theme (`--bg #0f1117`, `--accent #6c9cfc`, card/badge system). Reference mockups: `_mockups/rnd_mockups.html`, `_mockups/rnd_mockups_v2.html`.

## Constraints
- Anchor product is **Python stdlib only** (system tools like `claude`, `latexmk`, `git` are invoked as subprocesses — allowed; **pytest is a dev/test dependency**, not shipped).
- Markdown/JSON plain-text source of truth; no DB.
- Runs under the `anchor` NSSM service on port 8777; must not break existing task/dashboard behavior.

## Out of scope (Phase F / deferred)
Stall/heartbeat timeout, automatic interrupted→resume relaunch, weekly live-smoke test, richer status contract, Foreman `run-live.mjs` adapter, Gemini CLI, full PTY/xterm terminal, multi-user.
