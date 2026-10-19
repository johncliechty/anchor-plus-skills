# FINDINGS E — log sweep + pytest live-spawn audit (2026-07-26)

## Log sinks
`logs/errors.log` (303KB, boot-size rotation only, `anchor_gui.py:59-63`) ·
`logs/nssm-stdout.log` (~85k lines HTTP access, **no dates, only [HH:MM:SS]**) ·
`logs/nssm-stderr.log` (tracebacks) · `logs/YYYY-MM-DD.md` · `health_reports/YYYY-MM-DD.md`
· `docs/friction/2026-07-25-*.md` (4 files).

## John's two asks — CONFIRMED with hard evidence
**(a) Terminal double-print** — `nssm-stdout.log:82259` + `:82260`: TWO
`GET /api/rnd/term_stream2?session=d0e92cf5…` in the SAME second = two consumers on one
PTY ⇒ every byte rendered twice. Same shape at `:78310/:78313/:78315` (3 in 3s),
`:78507/:78515`, `:12319/:12332/:12355`, `:75493/:75532/:75954`.
"Not tracking" half = duplicated timer registration: `:82264-:82270` shows
term_sessions/board_html/grass each fired TWICE in one second; `:18-:28` shows FIVE
`/api/version` in one second; **20,899 `/api/version` total** in one rotation, 12,598
orphan_check|zombie_spenders|session_summary|session_narration.
Corroborated by John's own `logs/2026-07-25.md:20-23` and
`docs/friction/2026-07-25-dual-terminal-screens.md` (severity high; root cause:
`openEffortDock` never tears down `PANELS[sessionId]`, `_mountTerminal` doesn't enforce
one mount per session).
**(b) iPad dictation** — user report + traffic signature: `nssm-stdout.log:82261-82320`
= **~50 `POST /api/rnd/term_input2` in 3 seconds** (1,755 total). **ZERO instrumentation
exists**: grep ipad|dictat|voice|speech|compos over logs/ = 0 hits. No payload size, no
client UA, no per-session input-rate metric. The failure is invisible to Anchor itself.

## TOP 8 ERROR CLUSTERS
1. **`ensure_zh_node` RECYCLE STORM — 74 cycles**, every 6-8s: "port 48484 listening but
   /api/state dead — recycling" → "killed wedged listener" → "launched server.js"
   (`errors.log:1066-1068`, `:1168-1233`, `:1234-1237`, `:977`). **No backoff, no
   circuit breaker, no give-up.** It is the loudest thing in the log AND it belongs to
   zombie-hunter — the subsystem John wants to demo as trustworthy.
2. **Terminal double-subscribe + duplicated pollers** (above) — user-visible AND
   multiplies load on a render already taking 8-16s.
3. **AUTH TOKEN IN PLAINTEXT IN THE ACCESS LOG** — every authed GET writes
   `?token=kKWUVEG4…` verbatim into `logs/nssm-stdout.log` (`:1` and tens of thousands
   more; 8 hits in errors.log.1). A collaborator told to inspect logs for debugging sees
   the live capability token. **Collaborator-embarrassment risk: HIGH.** Systemic (the
   GET-with-?token design is in CLAUDE.md), not an accident.
4. **Orphan-worktree reaper permanently disarmed — 160 occurrences**: DRY-RUN
   "would_reap=[24 → 27 → 40 ids] kept=[] — live reaping held (report not clean)"
   (`errors.log:117, :138, :943, :981`). Grows monotonically, never reaps; ~3KB line per
   boot = the bulk of errors.log volume. Plus 32× "reaper sweep armed report-only".
5. **Healthcheck RED — R&D v12 surface**, 3 red days in-window (5 in July):
   `handoff_to_fresh: worktree creation failed (git-worktree-add-failed): HEAD points to
   an invalid (or orphaned) reference` (`health_reports/2026-07-21.md:30`, `07-12:27`,
   `07-09:27`). Same root cause every time (temp project created with unborn HEAD). A
   SECOND independent failure rides masked inside it: `n_efforts=3 view_ok=False`.
6. **Chronic perf breach, permanently yellow**: home page **321-329 KB HTML, 8.5-16.1s**
   (`health_reports/2026-07-14.md:42` 16.1s; 07-16 15.0s; 07-17 13.5s); journal overhead
   **26-51%** vs a 15% budget, EVERY day (07-26: 50.8%). Per the locked severity rule
   these can never redden the banner — so "Status: OK" coexists with a 3.4× budget
   breach. **A collaborator waits 10+s for first paint.**
7. **Boot-path exceptions** (`nssm-stderr.log`): `RuntimeError: can't start new thread`
   (`:3-16` — OS thread exhaustion under load; thread-per-request + leaked SSE pumps ties
   to cluster 2); `UnicodeEncodeError: '\u2192'` × 9 (`:58-73` — **boot log lines are
   silently LOST** when a message contains `→`); ~20 `SyntaxWarning: invalid escape
   sequence '\/'` on every start (`anchor_gui.py:13322/13317/8399/8431/8472…`).
8. **Restart/duplicate-instance churn**: `gandalf boot reconcile failed …: boom` ×9
   (**a test placeholder string reaching production logs**, `errors.log:1050`);
   "Anchor already running on 8777 — exiting" ×16; **reaper blast-cap defers the SAME
   two ids forever** ×23 (`errors.log:152-154`); "rejected terminal transition
   cancelled→running" ×10; **18 service restarts in 4 days**; "test port 8778 busy" in
   24 of 24 July health reports (a permanent "auto-fix").

### Hygiene
**`errors.log` has MIXED ENCODINGS** — most separators are cp1252 `—` (invalid UTF-8);
`rg`/grep SILENTLY SKIPS those lines ⇒ **any collaborator grepping this log gets
false-clean results**. Same cp1252 root cause as cluster 7. Access log has no dates.

## PART 2 — TEST LIVE-SPAWN AUDIT
Guard: `tests/conftest.py:50-55` sets ANCHOR_RUNNER_CMD→fake_claude + ANCHOR_PTY_BACKEND
→stub; incident documented at `:39-49` (**8,816 live sessions leaked 2026-06-20→07-14**).
**~85% paid, three structural holes:**
- **H1 FAIL-OPEN**: uses `setdefault`, so any ambient env wins; and
  `pty_manager.select_backend` treats ANYTHING ≠ `"stub"` as the REAL backend
  (`pty_manager.py:15-19, 61-62, 71-80`) — a typo re-arms live spawns across 62 files.
  Already flagged in `planning/anchor-shareable-2026-07/HANDOFF-TO-AGY.md:71`, still open.
- **H2 NO SEAM ON THE TERMINAL PATH**: `ANCHOR_RUNNER_CMD` covers only job_runner;
  `terminal_session.py:436-457 _resolve_engine_cmd` resolves the RAW binary
  (`claude`/`gemini`/`agy`/`grok`) with no override → `ANCHOR_PTY_BACKEND=stub` is a
  SINGLE POINT OF FAILURE for every terminal test.
- **H3**: nothing asserts "the resolved command is not a real engine."
DANGEROUS: Tier A (no local stub, drives real start path) = `test_cockpit_substrate.py`
(fixture `:22-23`), `test_rnd_project_window_kanban.py` (`:41`, `:165`),
`rearch_flows.py` (`:66-68`, `:83`). Tier B (deliberately `delenv` the guard; safe only
because PRODUCT code re-sets it) = 13 healthcheck/verification/cli files —
**`test_healthcheck_v8.py:46` and `test_cli_v8.py:31` also delenv `ANCHOR_GH_CMD` ⇒ the
REAL `gh` CLI, incl. `gh repo create`** (network + possible real repo creation).
Tier C verified inert: runner_cmd_contract, engine_selector, supervisor_w16,
posix_pty_backend, all Playwright (in-process server, inherits stubs).
SAFE: ~183/263 files never touch a spawn path; 59 of the 62 PTY-touching files set the
stub locally; stubs exist (fake_claude, stub_gh, stub_summarizer, …).
**The shipped release is NOT exposed**: `C:\dev\Anchor-release-v1.0` has no tests/ and no
conftest.py — the risk is John's working copy only.
FIXES: **Fix 0** conftest → hard `os.environ[...] = ` (not setdefault) + add
ANCHOR_GH_CMD→stub_gh + ANCHOR_CLAUDE_CMD; **Fix 1** add `ANCHOR_ENGINE_CMD` override at
the top of `_resolve_engine_cmd`; **Fix 2** fail-closed assertion in `start_session`
(refuse a real engine basename under the test guard); **Fix 3** 3 Tier-A fixtures get the
stub lines; **Fix 4** Tier B: swap `delenv(ANCHOR_GH_CMD)` → `setenv(stub_gh)`, and pair
the PTY delenv with an inert `ANCHOR_ENGINE_CMD`; **Fix 5** pyproject: `--timeout=120` +
a `live` marker (no timeout today ⇒ a wedged real spawn hangs the suite while burning).
SAFE SMOKE SUBSET (verified zero spawn paths): test_narration_floor_w3,
test_effort_view_v12, test_effort_view_drift_v12, test_token_hygiene,
test_artifact_route_safety, test_report_route_safety, test_route_table, test_doc_roles,
test_branding, test_anchor_marker, test_cli_efforts_v12 — with
`ANCHOR_PTY_BACKEND=stub ANCHOR_RUNNER_CMD=python tests\fake_claude.py
ANCHOR_GH_CMD=python tests\stub_gh.py` belt-and-braces.
DO NOT RUN before Fix 0/1/2: test_cockpit_substrate, test_rnd_project_window_kanban,
test_healthcheck_v*, test_healthcheck_rnd_v3, test_verification_w7, test_cli_v8, or the
full `pytest tests/`.

## Ecgberht
Zero logs, zero health entries, zero tests. Only reference anywhere under C:\dev\Anchor
is the exclusion note in this effort's PLAN.md. Nothing to exclude beyond this line.
