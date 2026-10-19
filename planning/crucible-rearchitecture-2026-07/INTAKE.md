# Crucible Stage 0 — Intake & Framing
## Anchor Re-architecture (Butler substrate) — BROWNFIELD

- **Date:** 2026-07-02
- **Project:** C:\dev\Anchor (NSSM service `anchor`, :8777, Python stdlib only)
- **Effort dir:** planning/crucible-rearchitecture-2026-07
- **Pipeline stage:** Stage 0 (Intake & Framing) — HALTED at the North-Star lock gate
- **Convergence authority:** John (the user). Nothing below is locked.

---

## 1. Intent (as received)

Re-architect Anchor from an 18k-line monolith into a maintainable substrate pointing at
the mid-term **Butler** vision (an always-on agent that manages John's projects/workflow).
Four pillars: (1) extract the embedded frontend to static files; (2) route-table dispatch
with declarative auth; (3) an event-log spine (append-only per-project journal, dual-write
first); (4) a control-plane/work-plane supervisor split. Plus: de-fork the 3x markdown
parser, delete vestigial anchor_server.py, move runtime state out of the repo via
ANCHOR_DATA_DIR.

Source plans: `C:\dev\plans\2026-07-review\Plan-1-Anchor-Stabilization.md` (Wave D) and
`C:\dev\plans\2026-07-review\EXECUTION-LOG.md` (Task 8: "the Butler prerequisites …
recommend Crucible — it is genuinely architectural, not pre-diagnosed").

## 2. Hard constraints (from the repo's own rules — Confirmed via CLAUDE.md)

- **Python stdlib only** (single pywinpty exception, isolated in pty_manager.py).
- Runs as the **NSSM service `anchor` on :8777**; dashboard must keep working at every
  step — John uses it daily. **No big-bang rewrite; incremental migration only.**
- **Markdown files remain the source of truth for tasks.**
- No visible console windows from any spawned process (NO_WINDOW discipline, Wave B).
- Wave A+B+durability fixes live on branch `fix/review-wave-a-2026-07`, **not yet merged
  to master** — this effort must sequence after (or atop) that merge. *(Confirmed via
  EXECUTION-LOG "STATE AT CLOSE".)*

---

## 3. Tiered brownfield ingest — findings

Labels: **Confirmed** (read directly), **Inferred** (deduced), **Gap** (unknown; gates planning).

### T1 — Inventory (Confirmed)

`anchor_gui.py` is **18,441 lines**. Structure in file order:
markdown parsing (194–332) → hand-rolled RFC-6455 WebSocket (471–651) → traversal-safe
static-asset resolvers (653–770) → background trigger orchestration (991–1601) →
~2,800 lines of server-side `_render_*` helpers (1601–4394) → `render_project_window_html`
(4395–5622, ~1,230 lines embedded HTML/CSS) → **`_PROJECT_WINDOW_JS` raw string
(5623–10285, ~4,660 lines of client JS)** → change ops (10531–10964) → **`generate_html`
(10966–13671, ~2,700-line f-string: the whole dashboard CSS+HTML+JS)** →
**`class AnchorHandler` (13762–18129)** → server classes + `main()` boot/reconcile
(18130–end).

Supporting modules are already well-factored (paths.py 379, job_runner.py 1,580,
terminal_session.py 3,547, session_registry.py 658, effort_history.py 3,115,
pty_manager.py 760, worktrees.py 370, effort_view.py 625, …). **The monolith problem is
almost entirely anchor_gui.py**: embedded frontend (~8,600 lines of string/f-string) +
the two dispatch chains (~3,900 lines) + render helpers.

### T2 — Pillar-by-pillar ground truth

**Pillar 1 — Embedded frontend (Confirmed).**
Three big embedded blobs: `_PROJECT_WINDOW_JS` (5623–10285, raw single-brace string —
deliberately NOT an f-string, so it can move verbatim), the `generate_html` f-string
(10966–13671 — CSS/HTML/JS with real `{expr}` interpolations), and
`render_project_window_html`'s f-string HTML/CSS shell (4395–5622). Smaller:
`_CACHE_BUST_JS_TEMPLATE` (118), `_ORPHAN_ALERT_JS` (13682). The repo already has **four
traversal-safe static routes** using the identical containment idiom
(`resolve()` + `relative_to(BASE)`, ValueError → None): `anchor_term_asset` 678,
`xterm_asset` 707, `brand_asset` 743, plus `report_viewer.katex_asset`. Extraction target
exists; the pattern is proven. *(Inferred)* the f-string JS needs its server-side
interpolations replaced by a small injected bootstrap JSON (`window.ANCHOR_BOOT = {...}`)
— the only genuinely fiddly part of Pillar 1.

**Pillar 2 — Route dispatch + auth (Confirmed).**
`do_GET` = lines 14220–16019 (~40 dispatch arms + 2 pre-dispatch specials: term_ws 14223,
term_stream2 14230). `do_POST` = 16020–18129 (~85 arms). **Auth is asymmetric:**
- POST has ONE central gate at the top (16025–16035: header/body token →
  `paths.auth_ok`, 401 on fail). Every POST branch is covered.
- **GET has NO global gate.** Terminal/RCE-surface GET routes each self-check
  `_term_token_ok()` (defined 13959; 20 call sites). But `/`, `/api/status`,
  `/report/…`, `/summary/…`, **`/artifact/…` (15522)**, `/project/<id>` (15696),
  `/api/rnd/projects`, `/api/rnd/tail`, `/api/rnd/jobs` serve project data
  **unauthenticated** to any client that reaches the port. This is the per-branch
  auth-omission class the route table must close **by construction**.
- **Local-import shadowing (Confirmed):** `import os` at 14506 (do_GET) and 16063
  (do_POST); `from datetime import datetime` at 15019 and 16911 — each makes the name
  local to the ENTIRE ~2,000-line method (latent UnboundLocalError). Other in-branch
  imports are lazy-by-design (names not module-bound) and harmless.

**Pillar 3 — Event-log spine (Confirmed state / Inferred failure mode).**
Durable state today: `session_registry` (`.anchor/sessions.json`, atomic
tmp+`os.replace` under `paths.WRITE_LOCK`) and `effort_history` (per-lane
`efforts/<job_id>.pointer.json` + ordered `index.json`, same atomic discipline).
**The atomicity is per-file, not transactional across pointer+index** — a crash between
the two writes strands an index entry with no pointer or an invisible pointer absent from
`index.json` (reads go newest-first off `index.json`, so an unindexed pointer is
invisible). Deletes touch pointer + index + refinements dir + cached summary as distinct
best-effort steps. This is exactly the "lost from an index" class (the July review's
gandalf-runs-in-the-wrong-index bug is the same shape one level up). An append-only
journal that every view can be re-derived from removes the class.

**Pillar 4 — Supervisor split (Confirmed).**
Live process state is **in-memory**: `pty_manager._LIVE` (ConPTY children + daemon reader
threads), `job_runner._LIVE`/`_JOB_DIRS`/`_ACTIVE_LANE`/`_FOLDER_BUILD`. Children die
with the service process → `nssm restart anchor` kills every in-flight job and live
terminal. Durable residue: job records/logs, `sessions.json` rows (stale "running"),
worktrees. Boot reconcile (main(), 18344–18424) demotes dead-PID records
(proc_probe.creation_time), reaps orphan worktrees (keeping parked STATUS_IDLE ones),
purges healthcheck rows, starts the zombie-hunter — **it reconciles death; it never
resumes life.** Useful assets for the split: Windows job-object attach
(proc_probe.attach_to_job_object, job_runner 610), creation-time identity (631) so PID
reuse can't lie, and the swarm-session registration hook (870).

**De-fork markdown (Confirmed).** Three parser copies: `anchor_gui.parse_tasks_from_md`
194–231 and `anchor.py` 127–178 are **byte-identical twins** (modern regex, `Project:`
link); `anchor_server.py parse_domain_tasks` 92–142 is a **drifted legacy** copy (older
grammar, case-sensitive `[ x]`). Companion project/inbox parsers are likewise
triplicated.

**anchor_server.py (Confirmed DEAD).** 453 lines, Flask (violates stdlib-only), binds
127.0.0.1:5000, references the retired Anchor-PSU layout, imported by **nothing** in
runtime code, absent from dist manifest/NSSM/launchers/healthcheck. Safe to delete.

**ANCHOR_DATA_DIR seam (Confirmed).** paths.py resolves the data dir lazily per call;
unset → code dir (the current live deployment). `migrate_data()` already exists
(idempotent, never overwrites). The repo currently carries ~62 uncommitted runtime-state
files (EXECUTION-LOG Task 3 note) — the seam exists; the live deployment just doesn't
use it yet.

### T3 — Gaps (unknowns that gate planning)

- **GAP-1 (ConPTY across processes):** can the supervisor own pywinpty ConPTY children
  and proxy bytes to the dashboard over loopback with acceptable latency, and does
  re-attach survive a dashboard restart cleanly? No evidence in repo. → mandate a
  **spike wave** in Stage 1 before committing the PTY half of Pillar 4.
- **GAP-2 (browser auth for GET pages):** browsers navigating to `/` and
  `/project/<id>` send no token. Default-deny GET requires a cookie (or equivalent)
  mechanism, or an explicit declared-open set for page routes. Design decision, not
  research — but it must be decided at Stage 1, not discovered mid-build.
- **GAP-3 (event taxonomy):** the full set of mutations-of-record must be enumerated
  (session lifecycle, doc persistence, job lifecycle, effort/grass lifecycle,
  deliverable pin/launch, project lifecycle, handoffs, boneyard). Stage-1 work; the
  write sites are all in effort_history/session_registry/terminal_session/job_runner,
  so the enumeration is bounded.
- **GAP-4 (healthcheck + tests vs supervisor):** anchor_healthcheck.py (4,970 lines)
  boots throwaway servers with stubbed backends; the supervisor needs the same seam
  (e.g. `ANCHOR_SUPERVISOR=inline|external`) so tests/healthcheck never require a second
  real process.

---

## 4. Oranges framing — the REAL goal

John is not buying "cleaner code." He is buying the **Butler**: an always-on agent that
watches, remembers, and manages his project portfolio. Thinking 2–3 steps ahead, each
pillar is a Butler organ, and that ordering of value should drive the plan:

1. **The event log is the Butler's memory and perception.** An agent cannot manage what
   it cannot reliably observe. Today "what happened" is scattered across mutable
   index/pointer/registry files that can silently lose entries. An append-only,
   schema-versioned journal is the ONE artifact the Butler will consume directly —
   it is the highest-Butler-value pillar, not an internals cleanup.
2. **The supervisor split is the Butler's body.** "Always-on" requires work to outlive
   any single process — including, later, the Butler's own restarts and upgrades. A
   work-plane that survives control-plane restarts is the precondition for an agent that
   acts continuously. (It also fixes today's real pain: `nssm restart anchor` kills
   in-flight Foreman runs.)
3. **The route table with declarative default-deny auth is the Butler's hands.** The
   Butler will drive Anchor programmatically. Today's surface has an unauthenticated GET
   plane and an auth model you must re-verify branch-by-branch. A declarative table
   turns the surface into an auditable API contract a trusted agent can safely hold a
   token for.
4. **Frontend extraction is the enabling excavation.** It removes ~8,600 embedded-string
   lines (47% of the file), making every subsequent server change reviewable and making
   room for the route-table migration. Low risk (verbatim move onto a proven
   traversal-safe route), do it first for velocity.

**Assumptions surfaced (each needs John's confirmation or Stage-1 disposal):**
- A1: The Butler itself is OUT of scope here — this effort builds the substrate only.
- A2: Dual-write means the legacy index/pointer stores remain authoritative for reads
  throughout this effort; event-log becomes source of truth in a LATER effort.
- A3: A second NSSM service (the supervisor) is acceptable on the host. (John already
  runs `anchor` + `ledger`; adding `anchor-supervisor` fits the ops model.)
- A4: UI behavior parity is the bar for Pillar 1 — no redesign, byte-similar behavior,
  Playwright-verified.
- A5: terminal_session.py decomposition (Plan-1 Wave D item 13) is NOT in this effort.

## 5. The 2–3 biggest architectural decisions (with recommendations)

**D1 — Event-log write model: derived-views-later vs source-of-truth-now.**
*Recommendation:* per-project append-only **JSONL journal**
(`.anchor/projects/<pid>/events.jsonl`), each event `{seq, ts, schema_ver, type, actor,
payload}`, appended atomically under WRITE_LOCK at every mutation-of-record site,
**dual-write** alongside the existing stores. Legacy stores stay authoritative for all
reads in this effort. Ship two consumers immediately so the journal is honest, not
ornamental: a **parity gate** (derive the effort/session views from events; diff against
the index/pointer-derived views; runs in tests + the daily healthcheck) and a **recovery
tool** (rebuild a lost `index.json` from the journal). Promotion of the journal to
source of truth is explicitly a later effort. Why: irreversibility is the risk axis —
dual-write is reversible at every step; a read-cutover is not.

**D2 — Supervisor split boundary and IPC.**
*Recommendation:* a small **separate stdlib process** (`anchor_supervisor.py`) run as its
own NSSM service, owning ALL child processes (jobs first, PTYs second), speaking
loopback HTTP+token IPC (same auth_ok discipline), with the dashboard as its client and
an `inline` mode seam for tests/healthcheck (GAP-4). **Phase it: jobs first** — job_runner
already has durable records + job-object + creation-time identity, so moving spawn/hold
to the supervisor is low-risk and immediately delivers "restart the dashboard without
killing a Foreman run." **PTYs second, behind the GAP-1 spike** (ConPTY ownership +
byte-proxy + re-attach). If the spike fails economically, PTYs stay dashboard-owned and
the criterion narrows honestly to jobs — declared now, not discovered later.

**D3 — Route-table auth default: default-deny with a declared-open allowlist.**
*Recommendation:* one declarative table (method, pattern, auth policy, handler) driving
a single dispatch loop; **every route must declare** `token` (default) or `open`;
unauthenticated routes exist only on an explicit, reviewed allowlist. Close GAP-2 with a
cookie set at first tokened visit (stdlib `http.cookies`) so browser page-loads
(`/`, `/project/<id>`) authenticate without URL tokens; keep `?token=` only where WS
demands it (per Plan-1 Wave B item 8). Migrate **strangler-style**: table dispatch first,
with fallthrough to the legacy if-elif chains, moving branches in batches — the dashboard
never breaks mid-migration. The `os`/`datetime` shadowing class dies as a free
consequence of handlers becoming module-level functions.

## 6. Complexity triage (assessComplexity)

**Recommendation: FULL.** Signals: scope is broad (4 architectural pillars across an
18,441-line hub + 30 modules); stakes are high (John's daily-use tool; the service must
never break; data-model changes have loss-of-record risk); irreversibility is real
(event schema, process topology, auth surface are all long-lived contracts);
unknowns exist but are bounded (GAP-1..4). This is exactly the "genuinely architectural,
not pre-diagnosed" case the EXECUTION-LOG itself routed to Crucible. LITE is refuted by
stakes + scope; **SPIKE-FIRST is refuted as the overall mode** because 3 of 4 pillars
are fully grounded by this ingest — instead the single genuine uncertainty (ConPTY
across processes) becomes a **mandated spike wave inside the FULL pipeline** (D2).
Per protocol, rigor is never silently downgraded: FULL it is, pending John's
confirmation at the lock gate.

## 7. Stage-0 exit state

- Candidate North Star: `NORTH-STAR-CANDIDATE.md` (standalone, verbatim-lockable).
- **HALT.** Stage 1 (Master Plan + Shark-Tank) does not begin until John locks the
  North Star (verbatim or amended) and confirms the FULL triage.
