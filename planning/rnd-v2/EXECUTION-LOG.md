# Anchor R&D Surface v2 — Execution Log

> Foreman appends per-wave EXECUTE / REVIEW / FIX / JUDGE entries here. Seeded by
> the Crucible→Foreman handoff on 2026-06-11. Frozen design: `MASTER-PLAN.md`.
> Plan: `IMPLEMENTATION-PLAN.md`. Ground-truth gate: `python -m pytest -v`.

## Handoff (2026-06-11)

- Crucible Stage 0 (North Star locked), Stage 1 (Master Plan approved), Stage 2
  (8-wave plan, internal Shark-Tank converged with no ≥2-agree blocker) complete.
- User decisions: one comprehensive build (not phased); interactive terminal =
  stream-json REPL (stdlib-honoring, no ConPTY); reconcile folds retired sibling
  history into the active id then hard-deletes the test ids; summaries generated
  once with multi-run validation and cached.
- Awaiting Foreman Wave 1.

---

## Wave 1 — Session model + grouping — GO (2026-06-11)

- EXECUTE: new `sessions.py` wrapping `effort_history` (no UI touched, storage unforked); `list_sessions` groups run efforts by job_id, discovered by parent dir, fallback skill+timestamp cluster; `merge_sessions`/`split_session` via `sessions-overrides.json` sidecar; `tests/test_sessions.py` (11 tests).
- GATE (orchestrator-run): 295 passed, 1 skipped.
- REVIEW (2 independent): both agreed test_sessions.py:96 OR-assertion was loose (confirmed). Single-reviewer findings: missing-job_id run grouping (A), `*-overrides.json` not in .gitignore allow-list (B) — neither a ≥2-agree blocker nor gate-failing, but both legitimate + cheap → fixed. Reviewer-A "test against live store" MAJOR rejected (hermetic tests are mandated).
- FIX (1 iter): .gitignore allow-lists `*-overrides.json` (C9); empty-job_id run efforts → unique stable session each (Wave-6 cache determinism); tightened the ordering assertion; +1 test.
- RE-GATE (orchestrator-run): **296 passed, 1 skipped**. Converged.
- Acceptance proven: active-project planning fixture (7 discovered files / 2 dirs) → exactly 2 sessions, newest-first, no dup/dropped members.

---

## Wave 2 — Folder-history unification + reconcile + deliverable pinning — GO (2026-06-11)

- EXECUTE: sibling-store adoption (`effort_history.sibling_store_ids`/`adopt_sibling_sessions`), `rnd_registry.reconcile_folder(active_id, apply=False|True)` (preview-then-fold-then-hard-delete, all under WRITE_LOCK, never touches active or different-folder ids), new `deliverables.py` (Anchor.md marker parse + pin), `POST /api/rnd/pin_deliverable`. Ids read from registry by folder at runtime (not hard-coded). New `tests/test_reconcile.py` + extended `tests/test_deliverables.py`/`test_brownfield_adopt.py`.
- GATE (orchestrator-run): 312 passed, 1 skipped. Live registry untouched (hermetic tests).
- REVIEW (2 independent): Reviewer A raised a path-traversal BLOCKER in `deliverables._relpath` (relative `..` stored unvalidated); Reviewer B independently judged path handling safe → not a ≥2-agree blocker, and serve-time guard (`test_artifact_route_safety`) already limits exploitability. Fixed anyway (defense-in-depth, data-sensitive wave). Idempotency test-gap (A major / B minor) also closed.
- FIX (1 iter): `_relpath` now resolves against the folder and raises ValueError on any escape (reusing the report_viewer/`/artifact` containment pattern); endpoint returns 400 not 500; +2 tests (traversal-reject, fallback-jid idempotent). One resolved ambiguity: malicious-Anchor.md hardening left out — Anchor.md is a trusted repo-committed file; ValueError still can't crash the endpoint. Sound default, no user HALT.
- RE-GATE (orchestrator-run): **314 passed, 1 skipped**. Converged.

---

## Wave 3 — First-class imported history (status-line, tiles, blurb) — GO (2026-06-11)

- EXECUTE: `status_line` reshaped to per-lane `{count, imported, running}` built from `sessions.list_sessions` (session = unit, so 7 discovered planning files = 2); all callers + 3 dependent tests updated; tile/window render a real per-lane summary line + per-lane "imported" chip (no more "import"/"none-yet" masquerade); per-project `blurb` field + `POST /api/rnd/set_blurb` + `seed_blurb` (CLAUDE.md→README→Anchor.md, bounded, escaped). New `tests/test_tile_render.py`.
- GATE (orchestrator-run): 326 passed, 1 skipped; `import anchor_gui` clean (f-string discipline held).
- REVIEW (2 independent): no BLOCKERs; both confirm HTML escaping correct, counts session-based, graceful degradation, acceptance renders exactly per spec. Single-reviewer MAJORs (B): CSS inconsistency across the two style blocks; benign idempotent blurb-seed race. "running always 0 for discovered" rejected (correct behavior).
- FIX (1 iter): aligned `.rnd-status-line`/`.rnd-lane`/`.rnd-imported` across both style blocks (brace conventions preserved); added XSS-escaping regression test. Seed-race left as-is (idempotent, exception-guarded).
- RE-GATE (orchestrator-run): **327 passed, 1 skipped**. Converged.

---

## Wave 4 — Project window restructure — GO (2026-06-11)

- EXECUTE: Kanban now renders SESSIONS (Wave-1 list_sessions) as most-recent card + "previous sessions (N)" expander per lane (one trio run = one card, multi-file collapses behind "files (N)"); 5th "Grass Catchers" column added (structure only; grass added to LANE_DIRS + effort_history LANE_SUBDIR); dead "no tasks linked yet" replaced by a working linked-tasks strip (Link/Unlink via existing link_task). Extended tests/test_project_window.py.
- GATE (orchestrator-run): 334 passed, 1 skipped; imports clean.
- REVIEW (2 independent): Reviewer B GREEN/zero-blockers (verified ordering, integration w/ W2-3, crash-resilience, XSS escaping, scope-tight). Reviewer A single-reviewer BLOCKER on rndUnlinkTask — mechanism muddled but underlying defect real (inline onclick string arg breaks for task text with apostrophes/quotes). Fixed.
- FIX (1 iter): task identity now rides via HTML-escaped data-attributes (`data-task`/`data-project`) + `rndUnlinkTask(this)`/`rndLinkTask(this)` reading `el.dataset` — no inline JS string arg carries task text; backend by-text match now round-trips for special chars; +1 test (`Fix it's "weird" bug`).
- RE-GATE (orchestrator-run): **335 passed, 1 skipped**. Converged.

---

## Wave 5 — Grass Catchers content sources — GO (2026-06-11)

- EXECUTE: `add_idea` + `POST /api/rnd/add_idea` (real source=run grass card, honesty contract kept); `promote_inbox` + `POST /api/rnd/promote_inbox` (reuses existing inbox parser, copy-by-default/non-destructive); brownfield `_classify` grass rules (SAVED_FOR_LATER, bare PLAN.md stubs → grass) ordered AFTER the named-trio planning check so real trio docs are never demoted; grass column affordances wired; CLI mirror in anchor.py. New tests/test_grass_catchers.py + extended test_brownfield_scan.py.
- GATE (orchestrator-run): 351 passed, 1 skipped.
- REVIEW (2 independent): Reviewer A full PASS (classification conservatism, honesty contract, auth, distro-scan integrity — tok-123 is a pre-existing allowlisted placeholder, no scan weakened). Reviewer B single-reviewer MAJOR-1: reconcile/sibling-adoption folded only cost-rollup lanes, so a retired id's grass ideas would be hard-deleted without folding — data-loss path contradicting the locked "fold history then delete" decision.
- FIX (1 iter): added `FOLD_LANES` (rollup lanes + grass); `adopt_sibling_sessions` + `reconcile_folder` now fold ALL content lanes incl. grass before hard-delete; COST rollup (`ROLLUP_LANES`) deliberately unchanged (grass has no cost); +1 test proving grass ideas survive reconcile and add no cost.
- RE-GATE (orchestrator-run): **352 passed, 1 skipped**. Converged.

---

## Wave 6 — Validated, cached summaries — GO (2026-06-11)

- EXECUTE: new `summarizer.py` (extraction-seed → generate twice via job_runner/ANCHOR_RUNNER_CMD seam → grounded-claim validation → cache summary.json+summary.md, run-once); `GET /summary/<pid>/<lane>/<session_id>` (reuses report_viewer markdown→HTML, member links to /report or /artifact); `POST /api/rnd/regenerate_summary` (auth-gated, force). New tests/test_summarizer.py + tests/stub_summarizer.py (no live claude — counter file proves run count).
- GATE (orchestrator-run): 356 passed, 1 skipped; no live claude in code paths.
- REVIEW (2 independent): **≥2-AGREE BLOCKER** — concurrency race (cache-check→generate unlocked → double model run on ThreadingHTTPServer; A=MAJOR, B=BLOCKER). Plus single-reviewer: cache-poisoning on model failure (B), weak 50%-token grounding (A), and several missing edge-case tests.
- FIX (1 iter): per-session lock + double-checked cache read → run-once under concurrency (proven by a 2-thread test = exactly GENERATE_RUNS); failed/empty runner job no longer caches (retryable error state + honest /summary message); model-succeeded-but-all-ungrounded caches with an explicit "no grounded claims" note (never a silent blank); grounding strengthened (ratio 0.5→0.7, ≥2 grounded terms) + documented as a hint filter, not a guarantee; explicit `.anchor/.gitignore` allow for summary.json/summary.md; +5 tests (concurrency, failure-no-poison, all-ungrounded, zero-member, grounding units).
- RE-GATE (orchestrator-run): **361 passed, 1 skipped**. Converged.

---

## Wave 7 — Interactive terminal (stream-json REPL) — GO (2026-06-11)

- EXECUTE: new `rnd_terminal.py` (persistent per-lane stream-json process via job_runner.launch_guarded, auto-seeded with lane skill; send_turn→stdin reusing gate_adapter sink; read_since; discover_produced; adopt_produced→one run session); SSE `GET /api/rnd/term_stream` (stdlib, bounded/heartbeat); `POST /api/rnd/term_input|start_terminal|term_discover|term_adopt` (auth-gated); vendored lightweight `vendor/anchor-term/` console; openTerminal replaces the raw-log launch console. New tests/test_terminal_repl.py.
- DECISION (deviation flagged): plan said vendor real xterm.js if available offline; agent vendored a lightweight `anchor-term` console instead (rationale in PROVENANCE.txt; swappable behind `window.AnchorTerm.mount`). Surfacing to user as a post-build product decision — does not block.
- GATE (orchestrator-run): 369 passed, 1 skipped; no live claude.
- REVIEW (2 independent): diverged — Reviewer A zero-blockers/all-justified; Reviewer B 2 BLOCKERs + 5 MAJORs. §5: neither B blocker corroborated by A → not auto-blockers, but several were real robustness gaps for a process-spawning feature → fixed.
- FIX (1 iter): abandoned-terminal reaping (beforeunload→cancel_job tree-kill + `cancel_terminal` helper); SSE broad-exception → terminal error frame (no client hang); snapshot-before-launch (race); send_turn validation (reject empty/oversized/dead-stdin); filename HTML-escape at propose time (rel_raw kept for resolution); +10 tests (adopt idempotency, send_turn edges, SSE-exception-graceful, cancel path).
- RE-GATE (orchestrator-run): **379 passed, 1 skipped**. Converged.

---

## Wave 8 — CLI mirror + healthcheck + docs — GO (2026-06-11)

- EXECUTE: `anchor.py rnd <subcommand>` mirror (sessions/status/reconcile[--apply dry-run default]/add-idea/promote-inbox/pin-deliverable/set-blurb/regenerate-summary, all delegating to shared modules, ASCII output for cp1252); `anchor_healthcheck.py` `check_rnd_v2_surface` walks the full v2 surface on the throwaway port, fully stubbed via fake_claude with finally-teardown (no real-data pollution, no live claude); CLAUDE.md documents the v2 surface + endpoint table. New tests/test_cli_rnd.py + tests/test_healthcheck_rnd_v2.py.
- GATE (orchestrator-run): 391 passed, 1 skipped.
- REVIEW (2 independent): both full PASS, zero blockers — CLI delegates (no forked logic), reconcile dry-run non-mutating, healthcheck teardown-in-finally + stubbed, docs accurate, lane constants consistent (FOLD_LANES vs LANE_DIRS vs STATUS_LANES), no scope creep. Only 2 MINOR doc gaps (paths.py, vendor/ missing from File Structure).
- FIX (orchestrator, trivial): added paths.py + vendor/anchor-term/ to the CLAUDE.md File Structure block.
- RE-GATE (orchestrator-run): **391 passed, 1 skipped**. Converged.

---

## PROJECT DONE — 2026-06-11

All 8 waves GREEN on the orchestrator-run gate `python -m pytest -v` (**391 passed, 1 skipped**; baseline was 284). Terminal wave (Wave 8) complete → Foreman emits final-state verdict and stops.

**Built:** session model (1 trio run = 1 card) · folder reconcile + sibling adoption + deliverable pin · first-class imported history (counts+provenance, blurb) · window restructure (most-recent+expander, grass column, task-linking) · Grass Catchers feeds (manual/INBOX/discovery) · validated cached summaries (run-once, grounding hint-filter, concurrency-safe) · interactive terminal (stream-json REPL over SSE, vendored anchor-term, exit→discover→adopt) · CLI mirror + healthcheck + docs.

**Open product decision surfaced to user:** terminal UI uses a vendored lightweight `anchor-term` console rather than real xterm.js (the plan permitted the lightweight console only if xterm.js was unavailable offline; it was available). Swappable behind `window.AnchorTerm.mount`. Awaiting user call.

**Not done by this build (data debris, flagged):** `domains/test.md` is untracked junk with a cp1252 byte that breaks the LIVE healthcheck/server markdown-parse path — should be deleted by the user.

**Deploy note:** changes live on branch `foreman/rnd-surface-v2`; the live server (NSSM `anchor`) still runs the old code until merged to master + `nssm restart anchor` (elevated).

---

## Follow-up — real xterm.js swap (user decision) — GO (2026-06-11)

- User chose real xterm.js over the lightweight anchor-term console. EXECUTE: vendored real `@xterm/xterm 6.0.0` (offline copy, MIT LICENSE + PROVENANCE) into `vendor/xterm/`; rewrote `vendor/anchor-term/anchor-term.js` as an ADAPTER over `new window.Terminal(...)` preserving the SAME `window.AnchorTerm.mount` API, gates, discover→adopt panel, and beforeunload reap; added traversal-safe `/vendor/xterm/` static route + includes (xterm before anchor-term). Backend `rnd_terminal.py` + SSE/term endpoints **byte-unchanged** (verified via empty git diff).
- GATE (orchestrator-run): **394 passed, 1 skipped** (+3 asset/route tests).
- REVIEW (1 focused, adversarial): full PASS on API parity, backend-unchanged, route safety, real-asset reality, adapter correctness, brace discipline, no stale refs. (Its lone "git hygiene" flag was a protocol misread — commit happens on GO, post-review.)
- Note: full visual/behavioral terminal validation is in-browser (out of gate scope) — verify after deploy.
