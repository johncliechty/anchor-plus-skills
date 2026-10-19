# Anchor Re-architecture — the Butler substrate — Implementation Plan (Foreman-ready)

test-command: python -m pytest tests/test_rearch_2026_07.py tests/test_review_fixes_2026_07.py tests/test_model_flex_w8.py -v

**North Star:** # NORTH STAR — LOCKED

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


> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — W1 — Ground-Truth Instrumentation (census · anchors · tripwire)

**Intent:** Replace hope with mechanical evidence before any wave is sized: size the C1 extraction, make structural references durable, and enumerate the TRUE mutation-of-record set for C3 (Master Plan Phase 0; Integrated 1, 4, 20; Mitigations 1, 5, 14).

**Deliverables:** tools/interpolation_census.py — mechanically classifies EVERY {…} interpolation in generate_html and render_project_window_html as data/flag/markup-emitting with counts, asserts _PROJECT_WINDOW_JS has zero, and derives the actual shrink number; if markup-emitting exceeds the small threshold, the C1 amendment is raised NOW via the North-Star amendment path; Sentinel-comment anchors landed in a tiny pre-wave commit + an anchor-freshness gate test that re-locates each structural anchor (the _PROJECT_WINDOW_JS assignment, the generate_html def, sentinels) and fails loudly on ambiguity — no line numbers anywhere in later waves; Write-site tripwire: a test-mode wrapper around file writes under .anchor/ (journal path allowlisted) run across the full suite + healthcheck to emit the mechanical mutation-of-record inventory; wired to become the permanent C3 completeness gate when the journal lands; Checked-in census report + mutation-set inventory as gate artifacts consumed by later waves

**Depends on:** —

**done-when:** The census emits classified counts + the derived shrink number (with the C1 amendment raised now if forced), the freshness gate relocates every anchor unambiguously, and the tripwire run over the full suite + healthcheck produces the complete mutation-of-record inventory.

- **Given** the full test suite plus a stubbed healthcheck running under the write-site tripwire, **when** any test path mutates a file under .anchor/, **then** the tripwire captures the write site into the inventory, and (in enforce mode) fails any mutation not paired with a journal event, with the journal path itself allowlisted
- **Given** a refactor has moved or renamed the _PROJECT_WINDOW_JS assignment or the generate_html def, **when** the anchor-freshness gate runs before an EXECUTE, **then** it fails loudly on the ambiguous/missing anchor instead of letting a stale structural reference proceed

## Wave 2 — W2 — Regression Rails (Playwright flows · contract shim · consumer token paths)

**Intent:** Manufacture the permanent regression assets and deploy-safety shims every later pillar depends on: the top-5 stateful Playwright flows, the frontend↔backend contract-versioning shim, and a token path for every consumer of every currently-open route (Master Plan Phase 0; Integrated 5, 8, 13; Mitigations 4, 12).

**Deliverables:** Five scripted Playwright flows as permanent regression assets: terminal open+type via stub PTY, pending-paste flush, drag-to-group, maximize/restore, v12 dock click — runnable in the extraction gate and every later pillar; Contract-versioning shim shipped as the LAST pre-migration release: window.ANCHOR_BOOT carries a build id, every _postJson sends it, mismatches answer a structured 409 the old client renders as a 'reload required' banner (stale tab / PWA-cached iPad client protection); Consumer-enumeration inventory (repo code, anchor_healthcheck.py endpoint walk, .bat/.vbs launchers, scheduled tasks, personal scripts) with Authorization-header token acceptance implemented everywhere, ?token= retained only for WS/SSE; Tests: 409-on-mismatch contract test + Authorization-header acceptance tests on representative routes

**Depends on:** W1 — Ground-Truth Instrumentation (census · anchors · tripwire)

**done-when:** All five Playwright flows are green against the current server, a build-id mismatch returns the structured 409 rendered as the reload banner, and every enumerated open-route consumer has a verified token path.

- **Given** a browser tab loaded before a deploy (stale ANCHOR_BOOT build id), **when** its JS issues any _postJson call to the upgraded server, **then** the server answers a structured 409 and the old client renders the 'reload required' banner instead of failing opaquely
- **Given** a consumer currently calling an open GET route (e.g. the healthcheck endpoint walk), **when** it presents the token via the Authorization header, **then** the route accepts it, with ?token= needed only on WS/SSE transports

## Wave 3 — W3 — Spikes, Pillar Flags & Process Rails

**Intent:** Run both time-boxed spikes against pre-written acceptance questions so Phases 2 and 5 consume verdicts (not hope), implement the four per-pillar off-switch flags + hybrid-state assertion, pre-design the PTY drain fallback, and codify the standing rituals + traceability ledger (Master Plan Phase 0; Integrated 14, 23, 33, 34, 42, 43, 44, 45, 52; Mitigations 10, 13, 15, 20).

**Deliverables:** ConPTY-across-processes spike harness + recorded verdict against the pre-written acceptance questions (latency bound, re-attach behavior, complexity budget); Cookie-through-WS-upgrade spike on the REAL clients (desktop browser + iPhone PWA over Tailscale HTTPS) + recorded verdict, with ?token= declared as the WS fallback if the Cookie header doesn't survive; Pre-designed graceful pre-restart drain script: close_session park + capture_session_docs + W3 warm-resume seed for every live PTY, proven against a stub PTY session; Four per-pillar off-switch flags implemented (journal emission · auth warn/enforce · supervisor inline/external · static-vs-embedded frontend) + the named hybrid-state matrix + a healthcheck assertion that the CURRENT live configuration is a named state; Three Butler user stories checked in as the binding Phase-4 envelope validation target; cross-pillar dependency DAG with the revert-compatibility rule; Codified rituals: per-wave live-service smoke checklist, healthcheck SLO (wall-time cap, zero-known-flakes, 20× nightly before 5AM), auth-flip sequencing rule, soft merge-freeze protocol for the extraction wave; Checked-in Appendix-A traceability ledger (ideas 1–52 + mitigations 1–20, Mitigation 9 explicitly reconciled)

**Depends on:** W2 — Regression Rails (Playwright flows · contract shim · consumer token paths)

**done-when:** Both spike verdicts are recorded against their pre-written acceptance questions, the four pillar flags exist with the healthcheck asserting the live config is a named hybrid state, the drain script runs green against a stub PTY, and the traceability ledger (including Mitigation 9's reconciliation) is committed.

- **Given** a live stub-PTY session with unsaved produced docs, **when** the pre-restart drain script runs, **then** the session is parked via close_session, its docs are captured to main, and a warm-resume seed exists so the post-restart reopen is warm, not cold
- **Given** the four pillar off-switch flags set to any supported combination, **when** the healthcheck configuration assertion runs, **then** it passes only when the combination matches a named row of the hybrid-state matrix and fails loudly on an unnamed state

## Wave 4 — W4 — Extraction Increment 1: _PROJECT_WINDOW_JS → static file

**Intent:** The safest, biggest single cut of C1: move the census-confirmed zero-interpolation _PROJECT_WINDOW_JS raw string verbatim to a static file served by the existing traversal-safe asset-route idiom, behind the byte-parity gate (Master Plan Phase 1; Integrated 2, 3, 6, 7, 50; Mitigation 2).

**Deliverables:** static/ app JS file containing the verbatim _PROJECT_WINDOW_JS body; one new static root served via the proven resolve()+relative_to idiom (zero new security surface); window.ANCHOR_BOOT as the ONLY server→client state channel for the project window (token presence, project id, build id, feature flags, initial counts), documented as a versioned dict in one module; Content-hash cache-busting (?v=<hash8> minted at startup from file bytes); Byte-parity golden-file gate: render via the OLD f-string path and the NEW static path, diff emitted JS byte-for-byte after {{/}} de-escaping; Static-vs-embedded off-switch flag functional (revert without reverting later waves); soft merge-freeze on anchor_gui.py active; anchor-freshness gate re-run before EXECUTE

**Depends on:** W3 — Spikes, Pillar Flags & Process Rails

**done-when:** The byte-parity diff between the old f-string emission and the new static-file emission is empty, the project-window Playwright flows are green, and the live-service smoke (restart → GET / 200 → project window loads → healthcheck green) passes.

- **Given** the service restarted onto the static-file path, **when** the project window loads and the top-5 Playwright flows run, **then** behavior is identical, the JS arrives from the traversal-safe static route with a content-hash query, and the only changed seam is the ANCHOR_BOOT bootstrap JSON
- **Given** the static-vs-embedded flag flipped back to embedded, **when** the service restarts, **then** the pre-wave embedded path serves byte-identical JS and the dashboard remains fully operational

## Wave 5 — W5 — Extraction Increment 2: project-window HTML/CSS shell → static

**Intent:** Second C1 increment: the project-window HTML/CSS shell moves to static files with server state entering only through ANCHOR_BOOT, byte-gated and live-smoked like increment 1 (Master Plan Phase 1; Integrated 2, 3, 50).

**Deliverables:** Project-window HTML/CSS shell as static assets served through the same static root + cache-busting; render_project_window_html reduced to bootstrap-JSON assembly + static shell serving; Byte-parity gate extended to the shell's emitted HTML/CSS; Playwright project-window parity re-run

**Depends on:** W4 — Extraction Increment 1: _PROJECT_WINDOW_JS → static file

**done-when:** Shell byte-parity is green, project-window Playwright flows are green, live smoke passes, and the increment merged independently of increment 3.

- **Given** a project window rendered pre- and post-increment, **when** the emitted shell HTML/CSS is diffed after de-escaping, **then** the bytes match, with divergence permitted only in the documented ANCHOR_BOOT injection block

## Wave 6 — W6 — Extraction Increment 3: generate_html JS/CSS → static (C1 exit gate)

**Intent:** The one genuinely fiddly increment, sized and gated by the W1 census: extract the generate_html f-string JS/CSS, close C1's shrink bar, and lift the merge freeze (Master Plan Phase 1; Integrated 1, 9, 50).

**Deliverables:** Home-dashboard JS/CSS as static assets; generate_html reduced to data assembly + bootstrap JSON, handling the census-classified data/flag interpolations through ANCHOR_BOOT (or the amended include layer if W1 forced the amendment); Byte-parity gate for the home dashboard; Playwright home-dashboard + project-window + top-5 flows green; C1 exit-gate artifact: measured anchor_gui.py shrink ≥ 7,000 lines (or the census-amended bar), no embedded frontend blob > ~50 lines remaining; Merge freeze on anchor_gui.py formally lifted after merge

**Depends on:** W5 — Extraction Increment 2: project-window HTML/CSS shell → static

**done-when:** The census-derived shrink number is achieved (≥7,000 lines unless amended up front), byte-parity and full Playwright parity are green, no embedded frontend blob over ~50 lines remains in anchor_gui.py, and the live smoke passes.

- **Given** the completed three-increment extraction, **when** the C1 exit gate runs, **then** anchor_gui.py measures ≥7,000 lines smaller than the pre-wave sentinel commit and the census re-run finds no embedded frontend blob larger than ~50 lines
- **Given** John's long-lived browser tab from before the deploy, **when** the new build starts and mints new content hashes, **then** the tab's next navigation fetches fresh assets via the changed ?v= hash (no stale-browser flavor of the documented pitfall)

## Wave 7 — W7 — Route Table Core + Strangler Dispatch

**Intent:** Stand up the single declarative route table with default-deny-by-construction auditing and strangler fallthrough, so C2 progress becomes a measurable count (Master Plan Phase 2; D3; Integrated 10, 16, 18, 46; Mitigation 16).

**Deliverables:** Route-table module: every route — including streaming/upgrade specials — gets a ROW (method, pattern, auth policy, handler kind: standard|stream|upgrade); kind≠standard is honestly special-cased at the pre-dispatch hook with the row's auth check invoked FIRST; Strangler dispatch: table first, unmatched falls through to the legacy if-elif chains; a coverage test counts remaining legacy arms; OPEN_ROUTES as a checked-in reviewed artifact with a mandatory justification string per entry + a test asserting the live open set matches it exactly; distro.py-style AST scan failing on any in-method import that shadows a module-level name; First migration batch of handlers to module-level functions; /api/routes (token-authed) dumping the live table (path, method, auth policy, handler kind, legacy-or-migrated)

**Depends on:** W6 — Extraction Increment 3: generate_html JS/CSS → static (C1 exit gate)

**done-when:** The table dispatches with legacy fallthrough and the audit test proves no route exists without a declared row, OPEN_ROUTES exactly matches the live open set, the legacy-arm counter is wired, and /api/routes serves the live table.

- **Given** a developer adds a new endpoint without a table row, **when** the route-audit test runs, **then** it fails — the auditable invariant 'no route exists without a declared row' holds by construction
- **Given** a new route added with auth policy 'open', **when** the OPEN_ROUTES exact-match test runs, **then** it fails until the reviewed OPEN_ROUTES file is edited with a justification string

## Wave 8 — W8 — Route Migration Completion + Warn-Mode Auth Soak

**Intent:** Migrate the remaining dispatch arms in reviewed batches, harden the special transports, rewire the healthcheck to the declared rows, and soak the auth flip in log-only mode on the live service (Master Plan Phase 2; Integrated 11, 12, 17, 45, 51; Mitigation 4).

**Deliverables:** Remaining do_GET/do_POST arms migrated batch-wise to module-level handlers (legacy-arm counter driven to zero or a small named residual), killing the os/datetime import-shadowing class structurally; Socket-level 401-before-101 regression test for term_ws: an unauthenticated upgrade attempt receives 401 before any handshake bytes; Healthcheck endpoint walk rewired to iterate the declared rows (skipping kind=upgrade), asserting auth behavior per declared policy; ANCHOR_AUTH_WARN log-only mode: the gated data-plane batch (/artifact, /report, /summary, /project, /api/rnd/projects, /api/rnd/tail, /api/rnd/jobs) flipped to 'warn' on the live service for a soak day; the warn log reviewed as a gate artifact; Sequencing rule honored in the merge checklist: no auth flip ships in the same deploy as JS calling the flipped routes

**Depends on:** W7 — Route Table Core + Strangler Dispatch

**done-when:** The healthcheck walks the declared rows asserting per-policy behavior, the 401-before-101 test is green, the AST shadowing scan is green with handlers module-level, and the live warn-mode soak log shows zero unexplained would-401 consumers.

- **Given** ANCHOR_TOKEN set and a term_ws upgrade attempted without credentials, **when** the socket-level test inspects the response, **then** a 401 arrives before any 101/handshake bytes, preserving the hand-rolled RFC-6455 ordering
- **Given** the data-plane routes in warn mode on the live service for the soak day, **when** the warn log is reviewed, **then** every would-401 entry maps to a W2-enumerated consumer with a token path, or the flip is held until it does

## Wave 9 — W9 — Auth Enforce + Cookie Navigation + Ops Cutover (C2 gate)

**Intent:** Apply the W3 cookie-through-WS verdict, flip the gated data plane from warn to enforce, and execute the ops cutover with the live tokenless-401 assert that makes C2 demonstrated, not narrated (Master Plan Phase 2; D3; Integrated 14, 15; Mitigation 3).

**Deliverables:** Cookie-based browser page navigation per the spike verdict; ?token= retained only where the spike proved WS/SSE demands it (no URL tokens elsewhere); Enforce flip for the gated data plane, deployed separately from any JS change per the sequencing rule; Ops cutover with teeth: mint token → set NSSM AppEnvironmentExtra → restart → a healthcheck probe asserting the LIVE :8777 returns 401 on tokenless /api/rnd/projects (a John-declines outcome is recorded via the amendment path, never silently); Cookie/auth healthcheck walk entering the 20× nightly repetition pipeline

**Depends on:** W8 — Route Migration Completion + Warn-Mode Auth Soak

**done-when:** The live :8777 service returns 401 on tokenless /api/rnd/projects while browser navigation (desktop + iPhone PWA over Tailscale) still works via cookie, and the zero-shadowing-imports scan and full suite are green.

- **Given** ANCHOR_TOKEN set on the live service after the cutover, **when** a tokenless GET hits /api/rnd/projects, **then** the healthcheck probe observes a 401 from the real :8777 service
- **Given** the same cutover state, **when** John navigates the dashboard and a project window in a browser holding the auth cookie, **then** pages load and WS/SSE terminals attach, with URL tokens present only on the transports the spike proved need them

## Wave 10 — W10 — anchor_md.py De-fork + anchor_server.py Deletion (C5)

**Intent:** Collapse the three markdown-parser copies to one: extract the shared parsing module, prove parse-identity on the real corpus, and delete the confirmed-dead anchor_server.py after the pre-deletion sweep (Master Plan Phase 3; Integrated 37, 38; Mitigation 17).

**Deliverables:** anchor_md.py: the byte-identical twin parsers (task/project/inbox/archived) extracted to one shared module imported by both anchor_gui.py and anchor.py; Golden-corpus gate: today's REAL markdown files parsed identically pre/post de-fork; Pre-deletion sweep results (Get-ScheduledTask scan, *.lnk target search for :5000/anchor_server, _archive/ grep) checked in; anchor_server.py DELETED with a one-line changelog tombstone

**Depends on:** W9 — Auth Enforce + Cookie Navigation + Ops Cutover (C2 gate)

**done-when:** anchor_gui.py and anchor.py both import anchor_md with the golden-corpus gate proving identical parses of the real markdown files, anchor_server.py is deleted with sweep results recorded, and the full suite plus live smoke are green.

- **Given** the complete set of real DASHBOARD.md/domains/INBOX/archive files as a golden corpus, **when** parsed via the pre-de-fork copies and via anchor_md, **then** the parsed structures are identical, byte-for-byte on serialization

## Wave 11 — W11 — Data-Dir Migration + Git Hygiene (C6)

**Intent:** Move runtime state out of the repo as ONE scripted, rollback-able unit — before the journal exists, so journals are born outside the repo — and make the repo provably stay clean (Master Plan Phase 3; Integrated 39, 40, 41; Mitigation 11).

**Deliverables:** Path-audit tool scanning every durable store (registry folder_path, worktree_path, discovery.json, job dirs, session records) for repo-rooted absolute paths, emitting a rewrite map; Scripted migration unit: stop service → migrate_data (existing paths.py seam) → path-rewrite pass → start → healthcheck, with rollback; old dir preserved read-only for a week; ANCHOR_REAPER_DRYRUN: worktrees.reap_orphans report-only on the first post-move boot, re-armed only after a clean report; Git hygiene as its own commit + gate: git rm --cached the ~62 tracked runtime artifacts + .gitignore, then a gate running a full healthcheck cycle and asserting `git status --porcelain` is empty

**Depends on:** W10 — anchor_md.py De-fork + anchor_server.py Deletion (C5)

**done-when:** The live service runs with ANCHOR_DATA_DIR outside C:\dev\Anchor with the healthcheck green from the relocated dir, and `git status --porcelain` is empty and STAYS empty through a full healthcheck cycle.

- **Given** the migration script run against the live data set, **when** the service restarts from the relocated ANCHOR_DATA_DIR, **then** the dashboard is fully operational, the reaper's dry-run report shows zero would-delete parked/live worktrees from path misses, and rollback restores the pre-move state if any step fails
- **Given** the post-hygiene repo, **when** a full healthcheck cycle runs (which writes reports, journals-to-be, job records), **then** `git status --porcelain` remains empty — runtime writes all land outside the repo

## Wave 12 — W12 — journal.py Core: emit() Choke Point + Butler Envelope

**Intent:** Lay the C3 spine: one schema-validated append-only emit() path, the Butler-shaped envelope proven against the three user stories, journal-first write order, and the first blessed wrappers on session lifecycle (Master Plan Phase 4; D1; Integrated 19, 21, 23, 24; Mitigations 6, 13).

**Deliverables:** journal.py with ONE emit() choke point: schema validation, monotonic per-project seq, atomic append under WRITE_LOCK, O(1) open-append-close, configurable fsync policy; journals born in the relocated data dir; Butler envelope: mandatory correlation_id, causation_id, actor{kind,id} (user-click|auto-advance|healthcheck-synthetic|cli), per-project seq + wall ts, schema_ver; a test answering the three W3 Butler user stories from envelope fields alone; Schema-evolution rule (additive-only within a major ver, unknown-field-tolerant readers) as a binding module-docstring convention + a v1-through-v-current round-trip test; distro.py-style scan forbidding json.dump/open-for-write to journal paths outside the module; blessed legacy-store wrappers as the only emit() call sites; Journal-first-then-legacy write order by decree on the first instrumented class (session started/closed/killed/advanced), with 'journal-ahead' documented as benign crash residue; journal-emission off-switch flag functional

**Depends on:** W11 — Data-Dir Migration + Git Hygiene (C6)

**done-when:** emit() is the scan-enforced only journal write path, session-lifecycle mutations write journal-first alongside (never instead of) the legacy stores, the v1→current round-trip test is green, and the three Butler user stories are answerable from envelope fields in a passing test.

- **Given** a session started, advanced, and killed through the normal terminal_session paths, **when** the per-project journal is read back, **then** schema-versioned events exist for each transition with monotonic seq, correct actor kind, and correlation/causation ids linking the advance to its parent — while the registry/index stores remain byte-equivalent to their pre-journal behavior
- **Given** a crash between emit() and the legacy-store write, **when** the parity classification (landing in W14) later inspects the divergence, **then** the orphaned journal event classifies as benign journal-ahead intent, replayable idempotently — never a lost legacy write

## Wave 13 — W13 — Full Mutation-Set Instrumentation + Events CLI + Perf Budget

**Intent:** Instrument every mutation class the W1 tripwire enumerated, flip the tripwire to the permanent enforcing completeness gate, and ship the first queryable taste of the journal — under a hard perf budget (Master Plan Phase 4; Integrated 20, 26, 47; Mitigation 19).

**Deliverables:** All enumerated mutation-of-record classes instrumented via blessed wrappers: doc persisted, job launched/finished/cancelled, effort promoted, grass idea lifecycle, deliverable pinned/launched, project lifecycle, handoff recorded, boneyard capture (per-tick/telemetry writes excluded BY RULE); Write-site tripwire flipped to permanent enforce mode — the C3 completeness gate, on forever; `anchor.py rnd events <pid> [--since seq]` journal-tail CLI following the v3–v12 CLI-mirror convention; Perf budget gate: the healthcheck's v2–v5 walks timed journal-on vs journal-off with a hard <5% regression budget

**Depends on:** W12 — journal.py Core: emit() Choke Point + Butler Envelope

**done-when:** The full suite + healthcheck run green under the ENFORCING tripwire (every mutation-of-record journals; nothing else does), the events CLI tails a real project journal with --since, and the measured journal-on overhead is <5%.

- **Given** the enforcing tripwire active across the full suite and stubbed healthcheck, **when** any code path mutates a store under the data dir without a paired journal event, **then** the run fails naming the write site — completeness is mechanical, not narrated
- **Given** a project with recent session, job, and grass activity, **when** `anchor.py rnd events <pid> --since <seq>` runs, **then** it prints the schema-versioned events after seq, newest-last, with no model call and no server dependency

## Wave 14 — W14 — Parity Gate + Recovery & Replay Tools (C3 gate)

**Intent:** Close C3's proof obligations: the quiescent classifying parity gate in tests AND the healthcheck, rebuild_index.py proving the 'lost from an index' class recoverable-by-construction, and the idempotent replay/reconcile tools (Master Plan Phase 4; D1; Integrated 22, 25, 48; Mitigation 6).

**Deliverables:** Quiescent classifying parity gate: derive session/effort views from a WRITE_LOCK-bracketed snapshot copy, tolerate a bounded tail window, classify divergence (journal-ahead=OK/crash-residue · legacy-ahead=BUG · conflict=BUG); wired into tests AND a healthcheck walk entering the 20× nightly pipeline; rebuild_index.py: re-derives a deleted/torn index.json (and sessions.json rows) from the journal, proven by a test that deletes the index mid-suite; documented operator runbook; Idempotent event-replay tool (bounded, dry-run-first) converging legacy stores to the journal — the operational answer to legacy-ahead/conflict; reconcile-report tool alongside

**Depends on:** W13 — Full Mutation-Set Instrumentation + Events CLI + Perf Budget

**done-when:** The parity gate reports zero divergence (bounded-tail-tolerant, classified) in tests and in the healthcheck walk, and the mid-suite delete-then-rebuild test restores index.json from the journal to parity.

- **Given** a project's index.json deleted mid-suite after real journaled activity, **when** rebuild_index.py runs against the journal, **then** the rebuilt index passes the parity gate with zero divergence against the derived views
- **Given** a seeded legacy-ahead divergence (legacy store mutated without its journal event), **when** the parity gate runs, **then** it classifies the row as BUG (never OK), and the replay/reconcile tooling reports it dry-run-first without mutating anything unasked

## Wave 15 — W15 — Supervisor Core: Inline Seam + IPC Contract + Restart Matrix

**Intent:** Move job ownership behind the ANCHOR_SUPERVISOR=inline|external interface with the IPC contract table written BEFORE code, durable gate answers, the in-memory rebuild table, and the literal automated restart-survival test matrix (Master Plan Phase 5; D2; Integrated 27, 28, 29, 30, 35, 49; Mitigations 7, 8).

**Deliverables:** IPC contract table as a checked-in artifact BEFORE code: every dashboard↔job interaction (launch, tail-since, cancel, gate-answer, cost/rollup, swarm-register) with state owner, idempotency key, defined behavior when EITHER side restarts mid-interaction — including the tail-cursor-durability row (per-job read offsets persisted in the job dir); ANCHOR_SUPERVISOR=inline|external Python interface with the in-process implementation (tests, healthcheck, degraded mode) fully wired: job_runner ownership routed through the seam; Gate-answer durability: an AskUserQuestion answer durably queued + persisted to the job dir and ACKed before the dashboard POST returns; the stdin write happens supervisor-side against the handle it owns; In-memory-structure rebuild table: every dashboard-side structure (_LIVE, _JOB_DIRS, _ACTIVE_LANE, _FOLDER_BUILD, lane locks, SSE attach points) with a rebuild-source column (durable record | supervisor query); zero unresolved rows before EXECUTE; The LITERAL automated gate: a stub-seam test matrix that kills each side mid-interaction per contract row, and restarts the dashboard side with a job in flight asserting the restarted dashboard lists the SAME job_id running, serves an advancing tail cursor, and can cancel it

**Depends on:** W14 — Parity Gate + Recovery & Replay Tools (C3 gate)

**done-when:** The full suite + healthcheck run green through the inline supervisor seam, the rebuild table has no unresolved rows, and the restart test matrix passes for every contract-table row including dashboard-restart-mid-job with same-job_id/advancing-tail/cancellable asserted.

- **Given** a fake_claude-driven job in flight through the inline seam, **when** the dashboard side is torn down and restarted in-test, **then** the restarted dashboard lists the SAME job_id as running, its /api/rnd/tail cursor advances, and cancel tree-kills it
- **Given** a gate question answered via POST /api/rnd/answer_gate while the IPC hop is killed mid-interaction, **when** the interaction retries per the contract row, **then** the durably-queued answer is delivered exactly once to the job's stdin — retryable, never lost, never doubled

## Wave 16 — W16 — External Supervisor Service + Live Probes

**Intent:** Stand up the real second process: the stdlib supervisor as its own NSSM service with loopback token-authed IPC, the scripted installer honoring John's account + no-console discipline, durable tail cursors, and the two live probes the inline seam can never cover (Master Plan Phase 5; D2; Integrated 31, 32, 49).

**Deliverables:** Stdlib supervisor process: loopback token-authed HTTP IPC implementing the contract table; the external client implementation of the ANCHOR_SUPERVISOR seam; defined degraded behavior when the supervisor is down; install_supervisor.ps1 — scripted, not documented: nssm install + ObjectName .\john + AppEnvironmentExtra cloned from the anchor service + CREATE_NO_WINDOW discipline throughout; Per-job persisted read offsets in the job dir so /api/rnd/tail cursors survive a SUPERVISOR restart; Two live healthcheck probes: (a) the LIVE supervisor spawns a trivial claude.exe --version child and reports output (credentials + PATH under the real service account); (b) the SUPERVISOR restarts with a sacrificial child running and the child survives (job-object breakaway proven)

**Depends on:** W15 — Supervisor Core: Inline Seam + IPC Contract + Restart Matrix

**done-when:** The supervisor NSSM service is installed via the script and running as .\john with no visible console, both live probes are green, the dashboard operates in external mode on the live service while tests/healthcheck stay green in inline mode, and a supervisor restart preserves tail cursors.

- **Given** the live supervisor service installed by install_supervisor.ps1, **when** the healthcheck asks it to spawn claude.exe --version, **then** the child runs under John's profile with output reported and no console window appears
- **Given** a sacrificial long-running child owned by the live supervisor, **when** the SUPERVISOR service is restarted, **then** the child survives the restart and the restarted supervisor re-adopts it with its persisted tail offset intact

## Wave 17 — W17 — C4 Live Demo + ConPTY Verdict Application

**Intent:** Prove restart survival on the real service with John per the runbook — the criterion is honestly unmet until the runbook has run once — and apply the W3 ConPTY spike verdict for PTYs (adoption follow-on or the drain + honestly-recorded narrowing) (Master Plan Phase 5; Integrated 33, 34, 36; Mitigations 10, 18).

**Deliverables:** C4 runbook as an executed artifact: dedicated throwaway R&D project on the real service, a harmless long-running real job through the REAL launch path (fake_claude-driven), exact elevated commands, expected observations, rollback steps (supervisor stop + lane-lock clear) — run WITH John; `nssm restart anchor` executed mid-flight on the real service: the job keeps running and the restarted dashboard reports it live; ConPTY verdict applied: if YES — the PTY-adoption follow-on wave scheduled inside this phase's plan; if NO — the W3 pre-designed drain (close_session park + capture_session_docs + warm-resume seed, automated in the deploy script) ships in THIS wave together with the narrowing recorded via the North-Star amendment path

**Depends on:** W16 — External Supervisor Service + Live Probes

**done-when:** The C4 runbook has run once on the real service with the in-flight job surviving `nssm restart anchor` and reporting live afterward, and the ConPTY verdict's branch (PTY adoption scheduled, or drain shipped + narrowing recorded) is merged.

- **Given** a real fake_claude-driven lane job in flight on the live :8777 service, launched through the real path with John observing, **when** `nssm restart anchor` runs from an elevated shell, **then** the job never stops, and the restarted dashboard lists the same job_id live with an advancing tail — the C4 live demo recorded in the runbook artifact
- **Given** the ConPTY spike verdict was NO, **when** any subsequent deploy of this effort restarts the dashboard, **then** the automated drain parks every live PTY with docs captured and warm-resume seeds, so the restart costs a warm reconnect, not dead context, and the narrowing is recorded via the amendment path — never silently

## Wave 18 — W18 — Closure: Hybrid Hardening + North-Star Scorecard (C7)

**Intent:** Convert 'we built it' into 'the daily 5AM run and the live service prove it, continuously': finalize the hybrid-state matrix, promote the four soaked healthcheck walks, run the one-sitting live sign-offs with John, and emit the demonstrated scorecard + Appendix-A reconciliation (Master Plan Phase 6; Integrated 15, 36, 41, 43, 44, 52).

**Deliverables:** Finalized named hybrid-state matrix with a one-line support statement per flag combination; the healthcheck asserting the CURRENT live configuration is a named state; The four new walks (journal parity, supervisor probes, cookie/auth, relocated-data-dir) joined to the 5AM run — each only after 20× green nightly repetition under the SLO (wall-time cap, zero-known-flakes, quiescence, retry-with-classification, 'Auto-fixes applied' degradation); Final live sign-offs in one sitting with John: the C4 runbook re-confirmation, the C2 tokenless-401 live assert, a C6 healthcheck-cycle-then-clean-git check, the per-wave smoke on the final merged state; North-Star scorecard: C1–C7 each marked met/narrowed/unmet with its proving gate artifact (census+byte-diff · OPEN_ROUTES+live-401 · parity+rebuild test · runbook execution · golden-corpus+tombstone · clean-porcelain gate · green suite+smoke log); any narrowing recorded via the amendment path; Appendix-A reconciliation: every idea 1–52 + mitigation 1–20 resolved to a landed or explicitly-amended item; scaffolding retired (legacy-arm counter at zero or named debt, merge freeze formally lifted, old data dir's read-only week concluded + archived)

**Depends on:** W17 — C4 Live Demo + ConPTY Verdict Application

**done-when:** The scorecard is emitted with every C1–C7 criterion met or narrowed-by-recorded-amendment and its proving artifact linked, the 5AM healthcheck carries all four new walks green after their 20× soak, the Appendix-A reconciliation shows zero silently-dropped ideas, and the final live smoke on the merged state passes.

- **Given** the four pillar flags in the final production configuration, **when** the 5AM healthcheck runs, **then** it asserts the configuration is a named hybrid state and all four new walks (parity, supervisor, auth, data-dir) pass within the SLO's wall-time cap with zero known flakes
- **Given** the completed effort, **when** the scorecard's Appendix-A reconciliation runs, **then** every integrated idea 1–52 and mitigation 1–20 (including Mitigation 9) resolves to a landed phase item or a documented amendment — demonstrated, not narrated
