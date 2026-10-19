# NORTH STAR — LOCKED

**Effort:** Anchor Re-architecture — the Butler substrate
**Project:** C:\dev\Anchor · **Locked:** 2026-07-02 by John (as-is, via AskUserQuestion; FULL triage confirmed)
**Pipeline:** Crucible FULL (Stage 0 ✓ → Stage 1 → Stage 2 → Foreman)
**Drift rule:** drift detection is ACTIVE from this lock. Amendments only via the
documented North-Star-amendment path with John's approval.

---

## Objective

Re-architect Anchor from an 18,441-line monolith into a maintainable, observable,
restart-resilient substrate — the architectural foundation for the Butler (an always-on
agent that manages John's projects and workflow) — by (1) extracting the embedded
frontend to static files, (2) replacing the if-elif dispatch with a declarative
route table whose auth is default-deny by construction, (3) laying an append-only
per-project event-log spine (dual-write; legacy stores stay authoritative), and
(4) splitting spawned work into a supervisor process so the dashboard can restart
without killing in-flight jobs or terminals — all delivered incrementally, with the
dashboard fully working on :8777 at every merged step.

## Success criteria (measurable)

1. **Frontend extracted.** anchor_gui.py contains no embedded frontend blob larger than
   ~50 lines: `_PROJECT_WINDOW_JS` (5623–10285), the `generate_html` f-string JS/CSS
   (10966–13671), and the project-window HTML/CSS shell are served as static files via
   the existing traversal-safe asset-route idiom, with server state injected only
   through a small bootstrap JSON. Bar: behavior parity, Playwright-verified on the
   home dashboard and the project window; anchor_gui.py shrinks by ≥ 7,000 lines.
2. **One route table, declarative auth, default-deny.** All HTTP routes (~125 dispatch
   arms across do_GET/do_POST) dispatch through a single declarative table where EVERY
   route declares its auth policy; token is the default; unauthenticated routes exist
   only on an explicit, reviewed allowlist. The currently-unauthenticated GET data
   plane (/artifact, /report, /summary, /project, /api/rnd/projects, /api/rnd/tail,
   /api/rnd/jobs) is gated when ANCHOR_TOKEN is set, with browser page navigation still
   working (cookie or equivalent — no URL tokens except where WS demands it). Zero
   in-branch imports shadowing module names (the os/datetime class) remain.
3. **Event-log spine, dual-write, provably derivable.** Every mutation-of-record
   (session started/closed/killed/advanced, doc persisted, job launched/finished/
   cancelled, effort promoted, grass idea lifecycle, deliverable pinned/launched,
   project lifecycle, handoff recorded, boneyard capture) appends a schema-versioned
   event to an append-only per-project journal, written alongside — never instead of —
   the existing index/pointer/registry stores. A parity gate (in tests AND the daily
   healthcheck) re-derives the session/effort views from the journal and reports zero
   divergence; a recovery tool rebuilds a deleted index.json from the journal in a
   test. The "lost from an index" bug class becomes recoverable-by-construction.
4. **Supervisor split — restart survival, live-proven.** Spawned lane jobs are owned by
   a separate stdlib supervisor process (own NSSM service, loopback token-authed IPC,
   inline seam for tests/healthcheck): `nssm restart anchor` with a job in flight
   leaves the job running and the restarted dashboard reporting it live — demonstrated
   on the real service. PTY sessions follow behind a mandated ConPTY-across-processes
   spike; if the spike refutes economic feasibility, PTYs remain dashboard-owned and
   that narrowing is recorded honestly in the plan (jobs-half is non-negotiable).
5. **One markdown-parsing layer.** A single shared parsing module; anchor_gui.py and
   anchor.py import it (today's byte-identical twins de-forked); the drifted third copy
   dies with anchor_server.py, which is **deleted** (confirmed dead: Flask, port 5000,
   referenced by nothing).
6. **Runtime state out of the repo.** The live deployment runs with ANCHOR_DATA_DIR
   pointing outside C:\dev\Anchor (using the existing paths.py seam + migrate_data);
   `git status` on the repo is clean of runtime artifacts (~62 today) and stays clean
   through a healthcheck cycle.
7. **Never-broken increments.** Every merged step keeps the dashboard fully operational
   as the NSSM `anchor` service on :8777 (John's daily use never breaks); Python stdlib
   only (pywinpty exception stands); markdown files remain the source of truth for
   tasks; the full test suite stays green (modulo the 2–3 documented pre-existing
   flakes) and each pillar lands with its own test gate.

## Non-goals (explicit)

- **NOT building the Butler itself** — no autonomous scheduling/decision agent, no
  proactive actions; this effort delivers the substrate only.
- **NOT promoting the event log to source of truth** — no read-path cutover, no removal
  of index/pointer/registry stores; that is a later, separate effort.
- **NOT a UI redesign** — extraction is verbatim/behavior-parity; no visual or
  interaction changes beyond what parity requires.
- **NOT replacing markdown** as the task source of truth, and no new storage engines
  (no SQLite, no third-party deps).
- **NOT decomposing terminal_session.py** (Plan-1 Wave D item 13) — separate effort.
- **NOT changing John's ops surface** beyond adding the one supervisor service — the
  dashboard stays the NSSM `anchor` service on :8777.
- **NOT a big-bang rewrite** — any step that would leave the dashboard down or require
  a multi-day freeze is out.

## Constraints (inherited, binding)

Python stdlib only (pywinpty exception) · NSSM service `anchor` on :8777 · markdown
source of truth for tasks · incremental migration, dashboard working at every step ·
no visible console windows from spawned processes · sequenced after the
fix/review-wave-a-2026-07 merge to master (DONE — deployed 2026-07-02).

## Locked architectural decisions (Stage-0 D1–D3, John-approved with the lock)

- **D1:** per-project append-only JSONL journal, DUAL-WRITE (legacy stores stay
  authoritative for reads); parity gate + recovery tool are mandatory consumers.
- **D2:** separate stdlib supervisor as its own NSSM service, loopback token-authed
  IPC, inline seam for tests; JOBS first, PTYs behind the mandated ConPTY spike.
- **D3:** default-deny declarative route auth; `open` is an explicit reviewed
  allowlist; cookie-based browser navigation; strangler-style migration.
