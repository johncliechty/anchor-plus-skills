# Anchor — Productivity System for J.C. Liechty

> **Single-folder layout (as of 2026-05-02):** Everything lives in `C:\dev\Anchor`. There is no Axmra sibling, no PSU sibling, no syncing — one folder, one tool.
>
> Historical note: this system used to be split across two OneDrive folders (Anchor PSU + Anchor Axmra) that synced to each other via a sibling-discovery mechanism. On 2026-05-02 the active folder moved to `C:\dev\Anchor` and the Axmra sibling was merged in and decommissioned. The frozen Axmra contents are preserved at `_archive/axmra-snapshot-2026-05-02/`. The old `Anchor PSU` OneDrive folder remains as an inert backup.

## Runtime / Host (as of 2026-05-12)
The Anchor server runs **persistently in the background** — you do not normally launch it by hand. Its lifecycle is owned by the **NSSM service `anchor`** (Windows service, `Automatic` start), which runs `python anchor_gui.py --no-browser` and binds `http://localhost:8777`.

**Host:** this is the same physical machine throughout — hostname `PUTER`, also referred to as **`gwl-server`** (its friendly / Tailscale name). Any code comment, doc, or plan that says `gwl-server` means this desktop; they are not two different boxes.

- **Restart the server:** `nssm restart anchor` (requires an elevated shell)
- **Stop / start:** `nssm stop anchor` / `nssm start anchor`
- **Status:** `Get-Service anchor`

Because the service owns the process, the dashboard no longer has a Stop button and the `/api/shutdown` endpoint has been removed — the UI cannot kill its own server.

> ⚡ **Dashboard perf fix (2026-06-16) — no more global `rnd_jobs/` full-scans on `GET /`.** Two hot paths used to scan the entire global `rnd_jobs/` dir for *every* project×lane on each dashboard render, making the home page O(projects × lanes × all-jobs); once `rnd_jobs/` grew to ~1k records it pushed `GET /` past the health check's 5s timeout (the red banner). Both are now **targeted lookups**: `anchor_gui._gather_project_efforts` loads ONLY the job records the project's efforts actually reference (per-`job_id` `load_record`, never `list_records()`), and `rnd_registry.status_line` does the same. The dashboard no longer slows as `rnd_jobs/` grows.

> ✅ **Resolved (2026-06-08) — duplicate supervisor was a rogue NSSM service.** The real cause of stale-code-on-8777 was a **second NSSM service `Anchor-Server`** (WinGet nssm, created 2026-05-16, running old code) racing the legit `anchor` service for the port. Because the old code bound with `SO_REUSEADDR`, *both* servers could listen on 8777 at once and requests randomly hit old or new — and `nssm restart anchor` only restarts one supervisor. Fixes shipped: (1) a **single-instance guard** — the server now binds with `SO_EXCLUSIVEADDRUSE` (Windows) so only one Anchor process can own 8777; a duplicate exits(0) cleanly instead of squatting (see `paths.classify_bind_error`/`use_exclusive_bind`, `anchor_gui._ExclusiveThreadingHTTPServer`). (2) Every desktop launcher (`AnchorDashboard.vbs/.bat`, `launch_anchor.pyw`, `pin_anchor_to_taskbar.vbs`, `create_shortcut.py`) now **only opens the browser**, never spawns a server. (3) `fix_anchor_stale.ps1` (run elevated) removes the rogue `Anchor-Server` service, reaps 8777 by PID, restarts `anchor`, and verifies the new code is live. The Task Scheduler task **"Anchor Server"** is already Disabled and was NOT the cause. The `ledger` NSSM service (`ledger_gui.py`, port 8778) is unrelated — leave it alone.

## Quick Start
When the user says "Dashboard", "dashboard", "anchor", or "start":
1. The server is already running (NSSM service). Just open **http://localhost:8777** in the browser — no launch step needed. If it doesn't respond, run `nssm restart anchor` (elevated) or check `Get-Service anchor`.
2. Give a brief status summary (date, active tasks, upcoming deadlines, inbox count)
3. The GUI is fully interactive — user can check tasks done, add tasks, capture ideas directly in the browser. All changes save to markdown files automatically and are logged.

**IMPORTANT:** `anchor_gui.py` is the application. It runs as a persistent local web server (under the `anchor` service) and writes directly to the markdown files — no Cowork sandbox limitations. Only run `python3 anchor_gui.py` manually for local debugging when the service is stopped.

## Fallback (if GUI can't launch)
If the browser-based GUI can't be launched, fall back to:
1. Run `python3 anchor.py dashboard` to rebuild dashboard.html
2. Present `dashboard.html` using a computer:// link
3. User gives text commands: "done: [task]", "add: [task]", "capture: [idea]"

## CLI Commands (anchor.py)
- **"done: David Leavitt"** → Run: `python3 anchor.py done "David Leavitt"`
- **"cancel: Review paper"** → Run: `python3 anchor.py cancel "Review paper"` (moves to CANCELLED.md)
- **"save: Review paper"** → Run: `python3 anchor.py save "Review paper"` (moves to SAVED_FOR_LATER.md)
- **"restore: Review paper"** → Run: `python3 anchor.py restore "Review paper" --from saved` (or `--from cancelled`)
- **"add task: Review paper"** → Run: `python3 anchor.py add "Review paper" --domain academic --priority 2 --energy high --notes "See email from Dr. Smith"`
- **"capture: Look into MIT"** → Run: `python3 anchor.py capture "Look into MIT" --domain academic`
- **"update"** or **"refresh"** → Run: `python3 anchor.py dashboard` and re-present

## Task Lifecycle
Tasks can be moved through these states:
- **Active** → on the dashboard (DASHBOARD.md / domain files)
- **Done** → checked off in markdown (`[x]`), visible in Completed view
- **Cancelled** → removed from dashboard, stored in CANCELLED.md, reviewable in Cancelled view
- **Saved for Later** → removed from dashboard, stored in SAVED_FOR_LATER.md, reviewable in Saved view
- **Restored** → moved back from Cancelled or Saved for Later to active dashboard

Each task can have an optional **Notes** field for storing emails, links, references, or context.

## Daily Health Check
A self-test script (`anchor_healthcheck.py`) runs every morning at 5:00 AM via the Windows Task Scheduler task **"Anchor Health Check"**. It verifies file integrity, parses every markdown file, boots a throwaway server on test port 8778, exercises every endpoint, walks a synthetic `__healthcheck__` task through every state, then writes `health_reports/YYYY-MM-DD.md`. If anything failed, the dashboard shows a red banner at the top until the next clean run.

It also exercises the **v2 R&D surface** (`check_rnd_v2_surface`): it registers a synthetic project in a throwaway temp folder and walks `add_idea` / `promote_inbox` (grass) → `pin_deliverable` → reconcile preview → `status_line` shape → a discovered planning session → `GET /summary` + `regenerate_summary` → a terminal session start → `term_input` → `term_discover` → `term_adopt`. **Every model call is stubbed via `ANCHOR_RUNNER_CMD` → `tests/fake_claude.py` — never live `claude`.** The synthetic project and its temp folder are torn down afterward, the `ANCHOR_RUNNER_CMD` env is restored, and the existing `__healthcheck__` filtering is unaffected, so no real data is polluted.

It additionally walks the **v3 "Mission Control" surface** (`check_rnd_v3_surface`), **fully stubbed** — `ANCHOR_PTY_BACKEND=stub` (no real ConPTY/pywinpty) + `ANCHOR_RUNNER_CMD` → `fake_claude.py` + a temp `ANCHOR_WORKTREE_BASE` (never the build repo) + a throwaway temp git project. It exercises: (1) the **session registry** — register a synthetic session → `reconcile` re-statuses a dead "running" one → remove; (2) the **stub-PTY lifecycle** — `pty_manager` `start`→`write`→`read_since` (echo round-trip)→`kill` (reaped), AND `terminal_session.start_session`→`attach` (replay)→`input`→`kill` against the temp git repo; (3) the **proactive project summary** — `summarizer.summarize_project` through the stub runner → cached; (4) the **deliverable preview guard** — it does **NOT spawn a real server** at the 5 AM check; it walks `preview_server.pick_free_port` (asserting `≠ 8777`) + `reap_orphans` with an **injected dead-pid record** to prove the never-8777 guard and the reconcile path without spawning; and (5) **handoffs** — `discover_recent_plan_set` + `record_handoff`, asserting the record **survives a rescan**. The `ANCHOR_PTY_BACKEND` / `ANCHOR_WORKTREE_BASE` env and all temp dirs are restored/torn down afterward; nothing touches the live `:8777` service or real data.

It then walks the **v4 "Project Cockpit" surface** (`check_rnd_v4_surface`), **fully stubbed** the same way (`ANCHOR_PTY_BACKEND=stub` + `ANCHOR_RUNNER_CMD` → `fake_claude.py` + temp `ANCHOR_WORKTREE_BASE` + a temp `ANCHOR_SKILLS_DIR` (never the live one) + a deterministic `ANCHOR_TERMINAL_SEED` + a throwaway temp git project). It exercises: (a) **seed-once** — `terminal_session.start_session` writes the lane skill seed exactly once (`record.seeded` True; no re-emit on repeated `read_since`); (b) **engine switch** — `switch_engine` swaps the backend in the same worktree with no orphan PTY and `last_engine_for_project` reflects it; (c) **doc-roles** — `summarizer.session_doc_roles` returns a dict; (d) **rollup** — `effort_history.project_effort_rollup` for both lifetime and 30d; (e) **grass promote** — `promote_grass_to_lane` starts a seeded stub session and the idea stays in grass (copy); and (f) **type-aware deliverable launch** — a skill VERIFY (no spawn) AND a service launch through a **STUBBED** `preview_server` on a guaranteed-free injected port asserted `≠ 8777` (no real long-lived server bound). All forced env (`ANCHOR_PTY_BACKEND`/`ANCHOR_WORKTREE_BASE`/`ANCHOR_SKILLS_DIR`/`ANCHOR_TERMINAL_SEED`) and temp dirs are restored/torn down; nothing touches `:8777` or real data.

Finally it walks the **v5 "Durable Work" surface** (`check_rnd_v5_surface`), **fully stubbed** the same way (`ANCHOR_PTY_BACKEND=stub` + `ANCHOR_RUNNER_CMD` → `fake_claude.py` + temp `ANCHOR_WORKTREE_BASE` + a throwaway temp git project). It exercises: (1) **run lifecycle** — `terminal_session.start_session` (stub PTY), then **close-keeps-record** (no reap: the registry record + live PTY persist) vs **kill-reaps** (`kill` → PTY gone + worktree removed + record terminal); (2) **session summary + continue** — `summarizer.summarize_session` through the stub runner captures `skill`/`prompts`/`actions` and caches (read path serves the cache), then `start_session(seed_context=…)` starts a NEW seeded session in the same lane with the original record intact; (3) **project summary** — `summarizer.summarize_project` through the stub runner yields a non-empty summary that is cached; (4) **build deliverable** — `deliverables.resolve_build_deliverable` + `backfill_build_deliverables` resolve a session-scoped product (honest unresolved + `deliverable=None` when no explicit signal; nothing fabricated); (5) **grass workbench** — `add_idea` → `develop_grass_idea` (seeded stub session) → `save_grass_refinement` (`grass-<id>/dev-N`) → status flips to `refined` and the idea STAYS in grass (copy), with the refinement listed. All forced env (`ANCHOR_PTY_BACKEND`/`ANCHOR_WORKTREE_BASE`/`ANCHOR_TERMINAL_SEED`) and temp dirs are restored/torn down, every stub PTY + synthetic session row is reaped, and nothing touches `:8777` or real data. **Playwright is a DEV-ONLY test dependency** (`pytest.importorskip`) — it is NEVER imported by product code (including `anchor.py`/`anchor_healthcheck.py`), so it never appears in `distro.py`'s import scan; every UI wave is gated by Playwright + a screenshot + user sign-off (the v4 lesson).

If port 8778 is already occupied (e.g. by a stale/orphaned server the non-elevated check can't reap), the self-test automatically falls back to an OS-assigned free port and logs that under "Auto-fixes applied" — it no longer aborts the whole run over a busy test port.

- **Install / re-register scheduled task:** `powershell -ExecutionPolicy Bypass -File .\register_healthcheck.ps1` (run once; safe to re-run)
- **Run on demand:** double-click `Anchor Healthcheck.bat`, or `python anchor_healthcheck.py`
- **Disable:** `Unregister-ScheduledTask -TaskName "Anchor Health Check" -Confirm:$false`
- **Reports:** kept indefinitely in `health_reports/`. See `health_reports/README.md` for the format.

The synthetic `__healthcheck__` task is filtered out of every dashboard view by `gather_all()`, so it never shows up even if a check is mid-run when you refresh.

## File Structure
```
anchor_gui.py           ← Standalone GUI (local web server + browser dashboard)
anchor.py               ← CLI engine (reads/writes markdown, generates HTML; `rnd` v2 + v3 inspection mirror)
anchor_healthcheck.py   ← Daily self-test (runs at 5:00 AM via Task Scheduler; walks the v2, v3 AND v4 R&D surfaces, fully stubbed)
rnd_registry.py         ← Id-keyed R&D project registry (status_line, blurb, reconcile_folder)
effort_history.py       ← Append-only per-lane effort pointer-records (add_idea, promote_inbox, adopt_sibling_sessions)
sessions.py             ← Session model — one trio run = one session (list_sessions, merge/split)
summarizer.py           ← Validated, cached SESSION + PROJECT summaries (generate-twice + grounding filter; v3 added the project-summary path)
rnd_terminal.py         ← v2 interactive terminal substrate (persistent stream-json REPL over SSE; not ConPTY)
deliverables.py         ← Deliverable declare/pin + per-type run contract
brownfield_scan.py      ← Discovery of on-disk trio artifacts + idea-docs (grass). NOTE (2026-06-17): the Foreman `*EXECUTION-LOG*.md` now classifies as **build** (not planning), even when it lives under `planning/<ver>/`, so every build session — including builds run OUTSIDE Anchor (e.g. on a branch) — appears in the Build lane, tied back to its planning session (shared source dir → `linked_planning` chip + panel breadcrumb). MASTER-PLAN/IMPLEMENTATION-PLAN/DECISION-LOG stay planning. Discovered BUILD session ids are lane-qualified (`build::…`) so they never collide with the same-dir planning session's id.
lanes.py / job_runner.py / gate_adapter.py ← Lane→skill mapping, durable job runner, gate stdin wiring
report_viewer.py        ← Markdown→HTML report/summary rendering (vendored KaTeX)
paths.py                ← Shared path/data-dir constants, WRITE_LOCK, auth + bind helpers (imported everywhere)
distro.py               ← Deny-by-default distribution builder + no-PII/secrets scan + stdlib-only import scan (declares the lone pywinpty exception)
pty_manager.py          ← ConPTY PTY substrate; backend seam (real pywinpty | stub via ANCHOR_PTY_BACKEND). The ONLY module that imports `winpty`, LAZILY, terminal-only
session_registry.py     ← Durable managed-terminal-session registry under .anchor/ (register/list/update/remove/reconcile; status→color mapping)
worktrees.py            ← Per-session git worktree+branch isolation under a git-ignored managed base (create/remove/reap_orphans)
terminal_session.py     ← Ties pty_manager + registry + worktrees into a live session (start_session/attach/input/resize/kill)
handoff.py              ← Stage handoffs: discover_recent_plan_set → prime_worktree (HANDOFF.md) → record_handoff (rescan-durable in discovery.json); list_handoffs
preview_server.py       ← Ephemeral deliverable-run preview on an OS-assigned port (HARD-guarded ≠ 8777); start/stop/list/reap_orphans
project_bootstrap.py    ← NEW: auto git-init + starter CLAUDE.md (ensure_git_repo / ensure_claude_md / bootstrap_project) — idempotent, best-effort, reuses worktrees._git (git as an external CLI, never a dep)
project_remote.py       ← NEW: link GitHub + auto-push (link_github create/existing · set_auto_push/get_auto_push · push_project · auto_push_if_opted · remote_status) through the ANCHOR_GH_CMD seam (gh/push stubbed in tests; never real network)
project_move.py         ← NEW: the GUARDED atomic on-disk project-folder move (move_to_group · is_anchor_repo · has_live_sessions · slug_group) — refuses the Anchor repo / live-session projects, atomic with full rollback, re-points registry+worktrees+discovery; stdlib only (shutil/pathlib/re) + the worktrees seam
boneyard.py             ← NEW: per-project, searchable INDEX over DISCARDED material (record_entry idempotent upsert · list_entries/get_entry SAFE projections · stdlib token/substring search · build_session_entry/build_grass_entry). Three sources: killed / deleted (v9) / grass-deleted. REFERENCES the already-persisted docs (D9, no second copy); stdlib only (hashlib/json/os/pathlib)
effort_view.py          ← NEW: derived/drift-safe/deduped effort view-layer (build_effort_view groups registry records by chain_id → ONE effort per chain [legacy 3-member chains + new single-session efforts uniform]; rebuilt each call, a member deleted drops [no ghost], deduped [migration overlap → one effort, live wins], SAFE projections [no worktree/branch], read-only · effort_for_session · effort_rollup [per-effort Σtok·time·$, DISCOVERED→0, deduped by (store_lane,job_id)]). Stdlib only (session_registry/effort_history/summarizer read accessors)
vendor/anchor-term/     ← Vendored lightweight terminal console (anchor-term.js/.css; the v2 REPL fallback)
vendor/xterm/           ← Vendored xterm.js console (v3 + v4 ConPTY terminal windows)
vendor/brand/           ← Ghost World Labs brand mark (gwl-m-icon.svg; favicon + home-page lockup)
register_healthcheck.ps1 ← One-time setup for the scheduled task
Anchor Healthcheck.bat  ← Manual trigger for the health check (with console output)
launch_anchor.pyw       ← Silent launcher (no terminal window, used by shortcuts)
Anchor Dashboard.bat    ← Double-click to launch (Windows)
pin_anchor_to_taskbar.vbs ← Run once to create a pinnable Desktop shortcut
setup_shortcut.py       ← Alternative shortcut creator (uses pywin32)
dashboard.html          ← Static HTML dashboard (auto-generated by anchor.py)
health_reports/         ← Daily health-check reports (YYYY-MM-DD.md, one per run)
_archive/               ← Frozen historical snapshots (axmra-snapshot-2026-05-02 lives here)
CLAUDE.md               ← This file (project instructions for Cowork / Claude Code)
DASHBOARD.md            ← Daily dashboard with calendar, focus items, priorities
PROJECTS.md             ← Master project list across all domains
INBOX.md                ← Quick capture inbox
CANCELLED.md            ← Cancelled tasks (reviewable archive)
SAVED_FOR_LATER.md      ← Tasks saved for later (reviewable archive)
WEEKLY_REVIEW.md        ← Weekly retrospectives
domains/
  academic.md           ← Research projects, teaching, service
  commercial.md         ← Commercial projects (Nexia/Axmra Capital, OpX, Archty, NextGen Nuclear) — full detail, was previously summary-only
  family.md             ← Trusts, travel, personal finance
  writing.md            ← Chronicles of the Dragon-Kept, Artificial Magi
logs/
  YYYY-MM-DD.md         ← Daily activity logs (auto-created)
```

## Architecture (for developers / future sessions)

### anchor_gui.py — The Main Application
This is a self-contained Python HTTP server that generates the full dashboard HTML on every request. No external dependencies — just Python stdlib.

**Key sections (in order):**
1. **Paths** (top of file): All file path constants rooted at `ANCHOR_DIR = Path(__file__).parent`
2. **Parsing**: `parse_tasks_from_md()`, `parse_projects_from_md()`, `parse_inbox_from_md()`, `parse_archived_tasks()` — read markdown into Python dicts
3. **Data Gathering**: `gather_all()` — reads DASHBOARD.md + all `domains/*.md` files, deduplicates tasks by first 60 chars of lowercased text
4. **Change Operations**: `log_change()`, `mark_done()`, `mark_undone()`, `add_task()`, `capture_inbox()`, `edit_task()`, `edit_project()`, `cancel_task()`, `save_for_later()`, `restore_task()`
5. **HTML Generation**: `generate_html()` — one function that builds the entire dashboard as a single HTML string with embedded CSS and JS
6. **HTTP Server**: `AnchorHandler` class with GET `/` and POST `/api/*` endpoints

**Task markdown format:**
```
- [ ] Task text — Priority: 2 — energy: med — [domain] — Due: 2026-04-15 — Notes: some reference
```

**Archived task format (CANCELLED.md / SAVED_FOR_LATER.md):**
```
- 2026-04-11: Task text — [domain] — P2 — Notes: some reference
```

**API Endpoints:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve dashboard HTML |
| GET | `/api/status` | JSON status summary |
| POST | `/api/done` | Mark task done |
| POST | `/api/undone` | Reopen a completed task |
| POST | `/api/add` | Add new task (with notes) |
| POST | `/api/capture` | Add to inbox |
| POST | `/api/edit_task` | Edit task properties |
| POST | `/api/edit_project` | Edit project properties |
| POST | `/api/promote_task` | Move task to P1 |
| POST | `/api/demote_task` | Move task to P2 |
| POST | `/api/promote_project` | Move project to P1 |
| POST | `/api/demote_project` | Move project to P2 |
| POST | `/api/cancel` | Cancel task → CANCELLED.md |
| POST | `/api/save_for_later` | Save task → SAVED_FOR_LATER.md |
| POST | `/api/restore` | Restore from archive to active |
| GET | `/project/<id>` | R&D project window (rich Kanban "Dashboard A") |
| GET | `/summary/<pid>/<lane>/<session_id>` | Cached, validated session summary page (run-once on first view; rendered via `report_viewer`) |
| GET | `/report/<pid>/<lane>/<job_id>` | Read-only report viewer for one effort (PDF-by-default else Reader) |
| GET | `/artifact/<pid>?path=<rel>` | Serve a discovered (brownfield) artifact, traversal-safe |
| GET | `/api/rnd/projects` | List R&D projects (grouped by folder) |
| GET | `/api/rnd/term_stream?session=<id>` | SSE stream of a terminal session's output (bounded by `max_ticks`, heartbeated, ends on terminal status) |
| GET | `/api/rnd/tail?job_id=<id>&since=<n>` | Cursor-stable incremental job log read (long-poll-safe) |
| POST | `/api/rnd/new_project` / `open_project` / `rescan` | Register / open / re-discover a project |
| POST | `/api/rnd/set_priority` / `archive_project` / `future_project` / `retire_project` / `reactivate_project` | Project lifecycle (retained, never deleted) |
| POST | `/api/rnd/set_notes` | Set a project's free-text notes |
| POST | `/api/rnd/set_blurb` | Set the project blurb ("what this project is"); seeded once from `CLAUDE.md`/`README`/`Anchor.md` |
| POST | `/api/rnd/link_task` | Link/unlink a task to an R&D project (`Project: <id>` field) |
| POST | `/api/rnd/launch_lane` | One-shot lane job launch (research→researchPrime, plan→Crucible, build→Foreman) |
| POST | `/api/rnd/answer_gate` | Answer an in-flight AskUserQuestion gate (plan/build) |
| POST | `/api/rnd/start_terminal` | Start a PERSISTENT interactive terminal session for a lane (stream-json REPL; stdin kept open). Returns the `job_id` = session id |
| POST | `/api/rnd/term_input` | Write ONE user turn onto a live terminal session's stdin (reuses the gate-adapter stdin sink) |
| POST | `/api/rnd/term_discover` | On exit, return the adoption PROPOSAL (files this session produced) |
| POST | `/api/rnd/term_adopt` | Confirm-adopt a terminal session's produced files as ONE session in the lane |
| POST | `/api/rnd/regenerate_summary` | Force re-run + re-cache a session's validated summary (through the runner seam) |
| POST | `/api/rnd/add_idea` | Add a manual idea to a project's Grass Catchers lane |
| POST | `/api/rnd/promote_inbox` | Promote an `INBOX.md` item into a project's Grass Catchers (copy-by-default; inbox untouched) |
| POST | `/api/rnd/pin_deliverable` | Pin any path (e.g. `anchor_gui.py`) as a deliverable; `{declare:true}` instead pins everything in the folder's `Anchor.md` marker block |
| POST | `/api/rnd/run_deliverable` | Run a declared/pinned deliverable per its type contract (doc/script/skill/program) |
| POST | `/api/rnd/cancel_job` | Stop one R&D lane job (tree-kill via `job_runner.cancel`); 404 on unknown id. Used by the project-window console "Stop job" button, scoped to the ATTACHED session |
| **v3 — ConPTY terminals (all token-authed; GET transports gate via `?token=`)** | | |
| GET | `/api/rnd/term_sessions?project_id=<id>` | Read-only: SAFE projection of the project's managed terminal sessions (NO `worktree_path`/`branch`); the window-manager button-bar repopulate hook |
| GET | `/api/rnd/term_ws?session=<id>&token=<t>` | Stdlib hand-rolled **WebSocket** (RFC-6455) carrying PTY bytes both ways; 401 before the 101 upgrade if unauthed |
| GET | `/api/rnd/term_stream2?session=<id>&token=<t>` | **SSE-out** fallback transport for a session's PTY output (bounded/heartbeated) |
| POST | `/api/rnd/term_start` | Start a worktree-isolated, registered, **bare interactive** ConPTY session for a lane; on a BUILD launch it discovers→primes→records the most-recent plan-set handoff. Returns the session record |
| POST | `/api/rnd/term_input2` | Write one user turn onto a live session's PTY stdin (SSE/POST fallback path) |
| POST | `/api/rnd/term_resize` | Resize a session's PTY (cols×rows) |
| POST | `/api/rnd/term_kill` | Kill a session (reap PTY + remove worktree + mark registry terminal); the window-manager "X" gates this behind an "Are you sure?" confirm |
| **v3 — proactive summary / handoff / preview** | | |
| GET | `/api/rnd/session_summary?pid=&lane=&session=` | Read-only cached SESSION summary for the in-place accordion (cache → `ready`; uncached → background gen + `generating`; never a synchronous model run) |
| GET | `/api/rnd/handoff_proposal?project_id=&lane=&seed_session=` | Read-only: the most-recent plan set a build launch would execute on (`{has_plan_set, plan_set, message}`) |
| GET | `/api/rnd/previews?project_id=<id>` | Read-only: SAFE projection of the project's ephemeral deliverable previews (NO absolute paths; reconciles dead → stopped) |
| POST | `/api/rnd/preview_start` | Start an ephemeral `anchor_gui.py` preview on an OS-assigned port (HARD-guarded ≠ 8777), isolated temp `ANCHOR_DATA_DIR` + loopback bind; returns its URL |
| POST | `/api/rnd/preview_stop` | Stop + tree-kill + scrub a preview |
| GET | `/vendor/brand/<file>` | Traversal-safe static route serving the Ghost World Labs brand mark (also the dashboard favicon) |
| **v4 — "Project Cockpit" (engine toggle · doc-roles · rollup · grass promote · deliverable launch)** | | |
| POST | `/api/rnd/term_set_engine` | Toggle a live session to the other engine (`claude`↔`gemini`): reap the PTY, relaunch in the SAME worktree, re-seed once, update the registry backend (rollback on failure); token-authed (`terminal_session.switch_engine`) |
| GET | `/api/rnd/session_doc_roles?pid=&lane=&session=` | Read-only per-lane ROLE→doc map for one session (research: exec/report/agent/provenance · planning: master/impl/northstar · build: northstar/deliverable/execlog/plan); links via `/report` / `/artifact`; absent roles omitted (`summarizer.session_doc_roles`) |
| GET | `/api/rnd/project_rollup?project_id=&window=lifetime\|30d` | Read-only cost/tokens/time rollup over RUN-provenance sessions only (imported/discovered contribute 0); lifetime or 30-day window (`effort_history.project_effort_rollup`) |
| POST | `/api/rnd/promote_grass` | Promote a Grass idea into a NEW seeded session in `research`/`plan` (reuses the Wave-1 seed path; idea stays — copy, never destroy); token-authed (`effort_history.promote_grass_to_lane`) |
| POST | `/api/rnd/launch_deliverable` | Type-aware launch of a pinned deliverable: skill/tool→VERIFY (no spawn) · service→persistent preview (free port ≠ 8777, isolated temp data dir, health-check; pull-up if already running) · program→run-to-result · doc→rendered href; token-authed (`deliverables.launch_deliverable`) |
| **v5 — "Durable Work" (close-to-tile vs kill · past-session summary + continue-live · per-build deliverable · grass B+C workbench)** | | |
| POST | `/api/rnd/continue_session` | Open a NEW live session in the SAME lane as a done/historical one, SEEDED with that prior session's context (`_build_continue_seed` → its cached summary, else a member digest) via `terminal_session.start_session(seed_context=…)`; the ORIGINAL record is NEVER mutated (read-only); token-authed |
| GET | `/api/rnd/build_deliverable?pid=&lane=build&session=` | Read-only: the deliverable a BUILD session produced — EXPLICIT signals only (`deliverables.resolve_build_deliverable`); honest `{resolved:false, deliverable:null, reason}` when none (never fabricated); no spawn / no model call; `?token=` |
| GET | `/api/rnd/grass?project_id=<id>` | Read-only: the project's Grass ideas + status (raw/refined/promoted) + versioned refinements for the two-pane idea workbench (`effort_history.grass_workbench_data`); project-scoped; `?token=` |
| POST | `/api/rnd/grass_develop` | DEVELOP a grass idea in a seeded workbench session in `research`/`plan` (`effort_history.develop_grass_idea` → `start_session(seed_context=idea+refinements)`); the idea stays in grass (copy); token-authed |
| POST | `/api/rnd/grass_save_refinement` | Save a NEW versioned refinement (`grass-<id>/dev-N`) for an idea (`effort_history.save_grass_refinement`); marks the idea REFINED; append-only history; token-authed |
| POST | `/api/rnd/grass_set_status` | Set a grass idea's lifecycle status (raw→refined→promoted; validated transition; a promoted idea links to the run it became) (`effort_history.set_grass_status`); token-authed |
| POST | `/api/rnd/grass_pull` | Pull a saved refinement's text into another effort's seed/context (the develop seed path); token-authed |
| GET | `/api/rnd/projects_html` | Read-only: the flat dashboard project rows re-rendered (each row's cached objective summary + rollup) for in-place refresh after a background `summarize_project` |
| **v6 — "Linked Pipeline" (durable chain · maximize/free-resize windows · persistent finished tiles · manual research→plan advance · auto plan→build advance · dashboard reflection)** | | |
| POST | `/api/rnd/advance_session` | Manual advance from a research session to a NEW linked **planning** session: `terminal_session.start_session(lane='planning', parent_session_id=<research>, seed_context=<research summary>)` — joins the research's `chain_id`, seeds from the research; the research record is never mutated; token-authed |
| GET | `/api/rnd/chain?project_id=&session=` | Read-only: the ordered lineage chain a session belongs to (`chain_for` → `chain_members`), as a SAFE projection of each member (`session_id`·`lane`·`label`·`status`·`parent_session_id`·`chain_id` — never `worktree_path`/`branch`) for the panel-header breadcrumb (R-1 → P-2 → …); `?token=` |
| POST | `/api/rnd/term_sessions` *(projection)* | The read-only `term_sessions` projection now **includes terminal-status** (done/failed) sessions (greyed reopenable tiles) and carries `parent_session_id`/`chain_id`; still SAFE (never `worktree_path`/`branch`) |
| POST | `/api/rnd/term_kill` *(+ `auto_build`)* | On a planning-session hard-kill that produces a plan set, the response now reports an **`auto_build`** field (the auto-opened linked, primed build session) — `terminal_session.auto_advance_planning_to_build` (idempotent on `parent_session_id`); no plan set ⇒ no `auto_build` |
| POST | `/api/rnd/finish_to_build` | **(v6 Wave 9)** Explicit, NON-destructive plan→build advance for a PLANNING session `{project_id, session}`: captures the plan set, marks the planning session **DONE via `session_registry.update_session` WITHOUT reaping its worktree** (it stays a reopenable finished tile), then `auto_advance_planning_to_build` (idempotent on `parent_session_id`) → `{ok, auto_build:<record\|null>, reason?}`; no plan set ⇒ `auto_build:null` + an honest `reason` (never fabricated); token-authed. (The plan→build advance also fires on a hard-kill AND on a reconcile-dead transition surfaced by the `GET /api/rnd/term_sessions` refresh, which now calls `terminal_session.reconcile_and_advance`.) |
| **v7 — "Integrated Board" (short+clean summaries · live sessions in the lane columns · summarize-on-finish · bare "Open terminal" general session)** | | |
| GET | `/project/<id>` *(board render)* | The 5 trio lane columns now **bridge in the project's LIVE managed sessions** (`session_registry`) alongside the effort-history sessions — `_gather_project_sessions` merges them **deduped by `session_id`**, newest-first (most-recent prominent, older under the "previous sessions" expander). A just-started session shows as a running (green) tile in its lane column immediately AND keeps its top-active-strip chip; a finished session stays as a grey reopenable tile. Each tile carries a **short, clean blurb** (`summarizer.session_blurb`). `general`/`grass` are NOT trio columns and are excluded from the merge. Render stays cache/registry-only (no model call). |
| (button) | "Open terminal" *(project window top)* | Starts a **bare `general` session** (`newTermSession('general', <engine>)` → `POST /api/rnd/term_start` with `lane='general'`): a lane intentionally NOT in `LANE_SKILL`, so `seed_for_lane('general')` is `None` → a bare PTY (no trio skill seeded), with the Claude/Gemini engine toggle, opened in a session window + the top active strip. It is NOT a board lane column and **never auto-advances** (not a planning lane). It can be summarized/continued like any other session. |
| *(hook)* | summarize-on-finish | `anchor_gui._trigger_session_summary_on_finish(pid, lane, session_id)` schedules a **background** session summary when a session reaches a terminal state (hard-kill / finish→build / reconcile-dead) — non-blocking, idempotent (skips a cached one), a failed gen never poisons the cache. It is the source of the tile/`session_blurb` text and the v6 restart seed. |
| **v8 — "Durable Artifacts" (doc persistence keystone · link GitHub + Option-A auto-push · handoff carries docs · no-loss kill · grass export · chain nav)** | | |
| POST | `/api/rnd/link_github` | Link the project repo to a GitHub remote: `{mode:'create'}` → `gh repo create <name> --private` through the `ANCHOR_GH_CMD` seam (gh stubbed in tests; degrades to paste-url when gh absent) + wire `origin`; `{mode:'existing', value:<url>}` → `git remote add origin <url>` (local). Persists the remote on the project record. Default new repos **PRIVATE**. Token-authed (`project_remote.link_github`). |
| POST | `/api/rnd/set_auto_push` | Persist the per-project **auto-push opt-in** flag (`{enabled:bool}`); token-authed (`project_remote.set_auto_push`). |
| POST | `/api/rnd/push_now` | Manual `git push -u origin <branch>` (in tests the remote is a LOCAL BARE `file://` repo → no network); token-authed (`project_remote.push_project`). Wired into the session-finish path as `auto_push_if_opted` — pushes ONLY when linked **AND** opted-in. |
| GET | `/api/rnd/remote_status?project_id=<id>` | Read-only `{linked, remote_url, auto_push}` — the offsite link + opt-in state; `?token=`. |
| POST | `/api/rnd/grass_export` | **Export to project** (Option B): copy a grass idea's contained research/plan work UP into real lane tiles carrying the persisted docs, and mark the idea **promoted** (idea stays in grass) (`effort_history.export_grass_to_project`); token-authed. |
| **v9 — "Tidy" (true session delete + ghost cleanup · grass idea delete · project folders/group · guarded on-disk move)** | | |
| POST | `/api/rnd/term_delete` | **Permanently delete** a managed session (distinct from `term_kill`): kill first if live, then drop the registry record (tile gone + STAYS gone across reload) + its lane effort pointer-records/index + cached summary — **produced documents KEPT** (Option A). Requires explicit `confirm`; token-authed (`terminal_session.delete_session`). |
| POST | `/api/rnd/cleanup_ghost_sessions` | Sweep a project's empty GHOST sessions — non-running records with NO efforts (`{project_id}`); RUNNING + has-efforts sessions untouched; token-authed (`terminal_session.cleanup_ghost_sessions`). |
| POST | `/api/rnd/grass_delete` | **Permanently delete** one grass idea + its pointer-record + grass index entry + refinements dir + contained dev-sessions (`{project_id, idea_id, confirm}`); project-scoped (siblings/other projects untouched); token-authed (`effort_history.delete_grass_idea`). |
| POST | `/api/rnd/set_group` | Re-label a project's dashboard `group` (collapsible folder) (`{project_id, group}`; `""` = Ungrouped) — **dashboard-only, NO disk move**; token-authed (`rnd_registry.set_group`). |
| POST | `/api/rnd/move_project` | **Guarded on-disk move**: `shutil.move` the project dir into `<root>/<slug(group)>/<dir>` + re-point registry `folder_path` + worktrees + `discovery.json` (`{project_id, group, confirm}`); REFUSES the Anchor repo / a live-session project; atomic with full rollback on failure; token-authed (`project_move.move_to_group`). |
| **v10 — "Live Handoff & Boneyard" (paste-NOT-submit handoff · both-artifact advance · grass two-terminals/archive/lineage/advance · per-project Boneyard)** | | |
| GET | `/api/rnd/boneyard` | Read-only per-project Boneyard: `?project_id=<id>&q=<query>` → SAFE projection of DISCARDED entries (`killed` / `deleted` / `grass-deleted`), NEWEST-FIRST, never absolute paths/worktree (`boneyard.list_entries`/`search`); the per-project Boneyard tab's list + live search box; docs open via the traversal-safe `/artifact?path=<rel>` route for ALL sources (uniform + robust — `deleted`/`grass-deleted` have no pointer-records, and the file survives on disk by rel path). `?token=`. |
| POST | `/api/rnd/grass_archive` | **Archive** a grass dev session's produced docs + summary into a per-idea bundle (`effort_history.archive_grass_session`); the idea STAYS in grass (distinct from Save, a text snapshot); token-authed. |
| POST | `/api/rnd/grass_advance` | Grass research→plan **live handoff** inside the workbench: builds the next-stage prompt from the research dev session's docs, opens the CONTAINED, LINKED grass plan dev session with the prompt as a PENDING PASTE (`effort_history.advance_grass_research_to_plan`); honest no-mint when there's no research material; token-authed. |

> **v10 advance delivers BOTH artifacts + a pending paste:** `/api/rnd/advance_session` and `/api/rnd/finish_to_build` (and the unattended `auto_advance_planning_to_build` / `reconcile_and_advance`) now write **NEXT-PROMPT.md** (always) — plus **HANDOFF.md** when an upstream plan set is discoverable (always for plan→build; research→plan has no plan set, so only NEXT-PROMPT.md) — into the next worktree, link the sessions (`parent_session_id` + shared `chain_id`), and deliver the reviewable task prompt as a v10 **PENDING PASTE** — phase-1 (load+greet) auto-submits, then the task prompt sits in the next terminal's input line UNSENT (`terminal_session.pending_paste` / `_flush_pending_paste`, flushed once after the greet is observed, no trailing newline) until the user presses Enter. Nothing is auto-submitted on the user's behalf, attended or unattended.

> **v8 keystone — document persistence:** every trio session's produced docs are **copied + committed into the main project before the worktree is reaped** (`effort_history.persist_session_docs`, wired into `terminal_session.kill` via `capture_session_docs`), so they survive, are discoverable from the main folder, and ride into later worktrees (checked out off main HEAD). `git`/`gh` are external CLIs through an injectable seam (`worktrees._git` / `ANCHOR_GH_CMD`) — never python deps, fully stubbed in tests, never real network.

> **R&D project window (`GET /project/<id>`):** `render_project_window_html` serves the rich "Dashboard A" — a 5-column Kanban (Research|Planning|Build|Deliverables|Grass Catchers) showing the **most-recent session per lane** as the visible card with a **"previous sessions" expander** holding the rest, a multi-session console / interactive terminal drawer, a lifecycle header (priority/notes/blurb/archive/retire/reactivate, all token-aware via `_postJson`), and the linked-tasks strip. Done sessions link to the cached summary (`/summary/<pid>/<lane>/<session_id>`); individual effort docs link to the report viewer (`/report/<pid>/<lane>/<job_id>`). The window JS lives in the `_PROJECT_WINDOW_JS` RAW (single-brace) string — NOT an f-string.

### anchor.py — CLI Engine
Mirror of anchor_gui.py's logic but as a command-line tool. Also generates the static `dashboard.html` file. Shares the same markdown format and file paths.

**R&D v2 CLI mirror** (`anchor.py rnd <subcommand>`) — each subcommand resolves a project by id and **delegates to the shared v2 module** (no forked logic):

- `rnd sessions <pid> --lane <lane>` — list a lane's sessions (`sessions.list_sessions`)
- `rnd status <pid>` — per-lane counts+provenance (`rnd_registry.status_line`)
- `rnd reconcile <pid> [--apply]` — folder reconcile; default is a dry-run preview (`rnd_registry.reconcile_folder`)
- `rnd add-idea <pid> "text" [--notes "..."]` — manual Grass Catchers idea (`effort_history.add_idea`)
- `rnd promote-inbox <pid> "inbox item"` — promote an INBOX item to grass (`effort_history.promote_inbox`)
- `rnd pin-deliverable <pid> <path> [--name N] [--type T] [--desc "..."]` — pin a deliverable (`deliverables.pin_deliverable`)
- `rnd set-blurb <pid> "blurb"` — set the project blurb (`rnd_registry.set_blurb`)
- `rnd regenerate-summary <pid> --lane <lane> --session <id>` — force re-cache a session summary (`summarizer.summarize_session(force=True)`, through the runner seam)

**R&D v3 "Mission Control" inspection mirror** (read-only — DATA/INSPECTION only, no live-terminal/preview control):

- `rnd term-sessions <pid>` — list the project's managed ConPTY terminal sessions (`session_registry.list_sessions`)
- `rnd previews <pid>` — list the project's ephemeral deliverable-run previews (`preview_server.list_previews`; reconciles dead → stopped, never spawns)
- `rnd handoff <pid> [--lane build] [--seed-session <id>]` — show the most-recent plan set a build session would execute on (`handoff.propose_handoff`) + the recorded handoffs (`handoff.list_handoffs`)

**R&D v4 "Project Cockpit" inspection mirror** (read-only DATA seams; the live terminal start/engine-switch + deliverable LAUNCH are interactive/mutating and have NO CLI form):

- `rnd rollup <pid> [--window lifetime|30d]` — cost/tokens/time rollup over RUN sessions (`effort_history.project_effort_rollup`)
- `rnd doc-roles <pid> --lane <lane> --session <id>` — per-lane ROLE→doc map for one session (`summarizer.session_doc_roles`)
- `rnd deliverable-type <pid> <deliverable_id>` — detect a pinned deliverable's type; for skill/tool also add the no-spawn verify status (`deliverables.get_pinned_deliverable` + `infer_type` + `verify_skill_or_tool`)
- `rnd engine <pid>` — the project's last-used engine (`terminal_session.last_engine_for_project`)

**R&D v5 "Durable Work" inspection mirror** (read-only DATA seams; continue-live, grass develop/promote, save-refinement, and deliverable LAUNCH are interactive/mutating and have NO CLI form):

- `rnd session-summary <pid> --lane <lane> --session <id>` — the CACHED validated session summary (skill · prompts · actions · member links); read-only, cache-only — never a synchronous model run (use `rnd regenerate-summary` to force) (`summarizer.load_cached`)
- `rnd grass <pid>` — list the project's grass ideas with id + status (raw/refined/promoted) + refinement count + source + promote link (`effort_history.grass_workbench_data`)
- `rnd build-deliverable <pid> --session <id> [--lane build]` — the deliverable a build session produced, resolved from EXPLICIT signals; honest UNRESOLVED (`deliverable=None`) when none (`deliverables.resolve_build_deliverable`)

**R&D v6 "Linked Pipeline" inspection mirror** (read-only DATA seam; the manual `advance_session` + the auto planning→build advance + continue-live are interactive/mutating and have NO CLI form):

- `rnd chain <pid> --session <id>` — the ordered lineage chain the session belongs to (research → planning → build, then by `created_at`), as a SAFE projection (`session_id` · `lane` · `label` · `status` · `parent_session_id` · `chain_id` — never `worktree_path`/`branch`); honest `{chain_id: None, members: []}` for an unknown session (`session_registry.chain_for` + `chain_members`)

**R&D v7 "Integrated Board" inspection mirror** (read-only DATA seam; the board live-session render + the "Open terminal" general session are interactive and have NO CLI form):

- `rnd blurb <pid> --lane <lane> --session <id>` — the short, clean one-line session blurb (the same text the board tile shows) from the CACHED session summary, glyph/markdown-stripped + capped; read-only, cache-only — never a synchronous model run; honest "(no summary yet)" when uncached (`summarizer.session_blurb`)

**R&D v8 "Durable Artifacts" inspection mirror** (read-only DATA seams; link/push, grass develop/export, continue-live are interactive and have NO CLI form):

- `rnd remote <pid>` — the project's GitHub remote link + auto-push opt-in state (`{linked, remote_url, auto_push}`); read-only — never touches the network / real `gh` / github.com and never pushes; honest "NOT LINKED" when unlinked (`project_remote.remote_status`)
- `rnd docs <pid> --session <id> [--lane <lane>]` — the documents a session PERSISTED into the project (the v8 Wave-2 keystone tags each persisted doc effort with the originating managed `session_id`); read-only; honest "No persisted documents" when none (`effort_history.efforts_for_session_id`)

**R&D v9 "Tidy" inspection mirror** (read-only DATA seams; session/grass delete + the guarded on-disk move are interactive/mutating and have NO one-shot CLI form):

- `rnd folders` — the project folders (groups) + their members as an ordered listing (named groups alphabetical first, `Ungrouped` always last); read-only — the `group` field is dashboard-only organization, this NEVER moves anything on disk; honest Ungrouped bucketing for projects with no group (`rnd_registry.group_by_group`)
- `rnd ghost-sessions <pid>` — the empty/ghost managed sessions `cleanup_ghost_sessions` WOULD remove (non-running records with no effort pointer-records in their lane), as a SAFE projection (`session_id` · `lane` · `status` · `label`); a pure LISTING — never deletes/kills; a RUNNING session is never a ghost; honest "No ghost (empty) sessions" when none (`session_registry.list_sessions` + `effort_history.efforts_for_session_id`)

**R&D v10 "Live Handoff & Boneyard" inspection mirror** (read-only DATA seams; session/grass delete, the guarded move, and the live paste/advance are interactive/mutating and have NO one-shot CLI form):

- `rnd boneyard <pid> [--search <q>]` — the project's Boneyard: the DISCARDED material (a hard-KILLED session that produced docs, a v9-DELETED session, a DELETED grass idea), NEWEST-FIRST, as SAFE projections (source badge · title · lane · doc count + doc rels · `entry_id` — never an absolute path/worktree/branch); with `--search` it delegates to the stdlib token/substring search over title + summary + idea text + doc paths. Pure read — never deletes (the Boneyard is additive); honest "No discarded material" when empty (`boneyard.list_entries` / `boneyard.search`)
- `rnd next-prompt <pid> --session <id>` — the generated next-stage handoff prompt a v10 advance delivered as a PENDING PASTE (the prompt sitting in the next terminal's input UNSENT). Resolves from the cleanest DURABLE source — the record's `pending_paste`, else the durable `NEXT-PROMPT.md` in the session's worktree, else a rebuild via `handoff.build_next_stage_prompt` from the linked parent — and NEVER starts a session / runs a model; honest "(no handoff prompt)" when absent

**R&D v12 "Efforts" inspection mirror** (read-only DATA seams; the in-session advance/handoff/dock + grass workbench are interactive live ops with NO one-shot CLI form):

- `rnd efforts <pid>` — the project's efforts (legacy research→plan→build chains + new v12 single-session efforts rendered UNIFORMLY as one effort each), each a SAFE projection `{effort_id, current_stage, status, stage_count}` — NEVER `worktree_path`/`branch` (`effort_view.build_effort_view`, rebuilt from the registry each call); honest "No efforts" when none
- `rnd effort <pid> --session <id>` — the effort the session belongs to + its ordered `stage_history` as a SAFE projection of each entry `{stage, state, doc_count, summary_ref}` — NEVER `baseline_ref` (a git SHA) / `store_lane` / `worktree_path` / `branch` (`effort_view.effort_for_session`); honest-absent (`effort_id==None`, `stage_history==[]`) for an unknown session
- `rnd effort-deliverable <pid> --session <id>` — the deliverable the effort's BUILD stage produced, resolved by feeding the live session record to the resolver as a v12 effort subject (build-stage docs ONLY — a plan-stage `MASTER-PLAN.md` decoy is never resolved, Shark C6); honest UNRESOLVED when not at build / no build signal (`deliverables.resolve_build_deliverable`)

**Gandalf v1 inspection mirror** (read-only DATA seam; the Gandalf run/re-run is interactive — NO one-shot CLI form):

- `rnd gandalf <pid>` — the project's Gandalf reads (the honest "what's really going on here" reads), NEWEST-FIRST, as SAFE projections (`ts · run_id · verdict · cross_model · degraded · ok · report_rel · exec_rel · advisor_rel · reason?` — never an absolute path); each OK row prints the verdict + chips (single-family/cross-model, degraded) + the report path; an error row prints the honest reason. Pure read — NEVER runs the model / the host (reads the internal index only); honest "No Gandalf read yet" when absent (`gandalf.list_runs`)

There is intentionally **no CLI form** for the live interactive terminal (start/input/SSE/WS/engine-switch/continue-live, the bare `general` "Open terminal" session), the manual `advance_session` / auto planning→build advance, the v2 SSE stream, preview **START/STOP**, deliverable **LAUNCH**, grass **develop/promote/save-refinement/set-status/pull/export**, GitHub **link/push/auto-push toggle**, the v9 **session/grass DELETE** + **ghost CLEANUP** + the guarded on-disk **MOVE** (`set_group`/`move_to_group`), the v10 **live paste/advance** (`advance_session` / `grass_advance` / `grass_archive` / pending-paste flush), the v12 **in-session advance/handoff/dock** (`advance_stage` / `handoff_to_fresh` / the grass one-session workbench), or the merge/split escape hatch — those are inherently interactive / mutating live operations driven by the dashboard, and exposing them as one-shot CLI calls would not be meaningful. The v3–v12 CLI mirrors only the data/inspection seams.

### How to Add a New Feature
1. Add the backend function in **anchor_gui.py** (in the "Change Operations" section)
2. Add the API endpoint in `AnchorHandler.do_POST()`
3. Add UI elements in `generate_html()` — CSS in the `<style>` block, HTML in the view, JS in the `<script>` block
4. Mirror the backend function in **anchor.py** and add the CLI command in `main()`
5. Update this CLAUDE.md

### GUI Views
The dashboard has these views (toggled by `showView()` in JS):
- `view-dashboard` — main view with top tasks, projects, stats
- `view-completed` — completed tasks (can reopen)
- `view-cancelled` — cancelled tasks (can restore)
- `view-saved` — saved-for-later tasks (can restore)
- `view-inbox` — quick capture inbox
- `view-{domain}` — per-domain views (academic, writing, family, commercial, personal)

### Common Pitfalls
- **Browser caching:** The server sends no-cache headers, but if a user reports stale content, tell them Ctrl+Shift+R
- **Port conflict:** If port 8777 misbehaves, restart the service: `nssm restart anchor` (elevated). Do **not** blanket-kill `taskkill /F /IM pythonw.exe` — that also kills the service's server and any unrelated `pythonw` processes on this host. To target one process, find it with `Get-NetTCPConnection -State Listen -LocalPort 8777` and kill that specific PID.
- **Local Filesystem:** Project lives in `C:\dev\Anchor`. No OneDrive, no syncing. Version control via local Git.
- **F-string escaping:** The HTML is generated inside Python f-strings, so all literal `{` and `}` in CSS/JS must be doubled: `{{` and `}}`

## Important Rules
- **Summary formatting:** Project and session summaries should be simple, human-readable paragraphs (3-5 sentences, no dense bulleted lists). Conversely, Gandalf executive summaries MUST be short, easy-to-read bulleted lists.
- **anchor_gui.py is the primary interface.** It reads/writes markdown directly via a local API.
- **Single folder.** Everything lives in `C:\dev\Anchor`. No siblings, no syncing.
- **commercial.md is now full detail** — proprietary commercial info (Nexia/Axmra fundraising, drug detail, key relationships) lives directly in `domains/commercial.md`. The old "summary-only" rule no longer applies.
- **Markdown files are the source of truth.** No database, no lock files. Everything is plain text.
- **No external dependencies (one declared exception).** Python stdlib only, EXCEPT the v3 terminal subsystem's optional `pywinpty` (`import winpty`, LAZY, in `pty_manager.py` ONLY; `pip install .[terminal]`). It degrades gracefully if absent. `distro.py`'s import scan enforces this — it refuses any other native/third-party import in product code. Must run on any machine with Python 3.8+ (terminals require Windows + the optional extra).
- **All files must remain accessible** from Cowork, Claude Code, or any CLI tool. No binary formats, no compiled assets.

# Explicit Driver Initialization Rule
When running ANY agentic skill via a CLI or script (e.g., Foreman, Crucible, Gandalf, ResearchPrime), NEVER rely on hardcoded tool defaults that bypass proper transport error handling (like raw `claude` binaries). ALWAYS explicitly set the transport driver and active model environment variables to match the current session. For example, if running inside Antigravity CLI, always set `TRIO_DRIVER="gemini-cli"` and `CRUCIBLE_AGENT_LIVE="1"` alongside the corresponding `GEMINI_MODEL="gemini-X"` so that rate limits and transient network errors are caught and gracefully retried by the underlying reliability wrappers, rather than crashing the skill.

# Silent Background Tools Rule
# Zero Terminal Popups Rule
1. Agents must never use the terminal `run_command` tool for simple file reads, writes, `list_dir`, or `grep` searches. Always strictly prioritize the native silent background tools (`view_file`, `grep_search`, `list_dir`) to prevent spawning visible PowerShell windows that steal focus and disrupt the user's typing.
2. **Background Scripts & Orchestrators:** When launching any script, Node process, or background orchestrator (e.g., Foreman) that runs autonomously, the agent MUST guarantee it executes silently without spawning child console windows (e.g., using `windowsHide: true`, `-WindowStyle Hidden`, or equivalent). 
3. **Test Gates:** If a background process executes a test gate (like `pytest` on Windows) that inherently pops up terminal windows (e.g., ConPTY/pty tests) and cannot be trivially suppressed, the agent **MUST NOT** run it in the background without explicit user consent. In such cases, prefer manual code adjustments or running the task synchronously when the user is not actively typing.
