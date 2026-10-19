# Implementation Plan: Anchor Doctor UI V3 — Honest Agentic Diagnostics

test-command: python -m pytest -v tests/test_doctor_v3.py

**North Star:** The `/doctor` page is an HONEST diagnostic surface styled like the rest of the Anchor dashboard (same CSS idiom/palette as `anchor_gui.py`'s home page — NOT a standalone-product mock). Every number on it is real or absent — never fabricated. Its terminal is a REAL interactive agentic session on Anchor's existing PTY substrate: engine-honest per the W8 model-flex policy (`lanes.detect_host_profile` / `select_engine_plan` — the subscription CLIs `claude`/`agy`, NEVER an API key, NEVER a third-party Python import), read-only (plan permission mode), seeded with live doctor context, streamed over the EXISTING token-authed WS/SSE terminal transports.

**Locked decisions (2026-07-18, John):**
- Backend = real agentic session on the existing `pty_manager`/`session_registry` substrate. The V2 `anchor_doctor_agent.py` (`google.generativeai` + `GEMINI_API_KEY`) is WRONG — it violates the repo's stdlib-only rule (`distro.py` import scan), bypasses the engine substrate, and cannot run on this host (no API key; subscriptions only). Remove it entirely.
- Look = match the existing Anchor dashboard style. No fake disk-usage card, no fake SVG chart, no dead nav items, no invented counts. The V2 `{{fname}}`-in-f-string literal-brace bug class must be regression-tested (assert rendered HTML contains no literal `{` placeholder text).
- All tests stubbed: `ANCHOR_PTY_BACKEND=stub` + `ANCHOR_RUNNER_CMD` → `tests/fake_claude.py`. Never a live model call, never a real ConPTY in the gate.

## Wave 1
**Title:** Rip out the API-key backend + swept-in scratch
**Deliverables:**
- Delete `anchor_doctor_agent.py`, `test_doctor.py`, `test/test_doctor_ui.mjs`, `prototypes.html` (its images live outside the repo), and the scratch files swept into master by 65e93e1: `test.py`, `test_quote.js`, `test_agy_out.txt`, `touch_loop.ps1`.
- Remove the `/api/doctor/run` agent branch from `anchor_gui.py` (the `anchor_doctor_agent.py` spawn path). The synchronous 75s in-thread `anchor_healthcheck.py` spawn is also removed (replaced in Wave 3 by a background run with tail).
- `tests/test_doctor_v3.py` STUB GATE asserting: no module in the repo imports `google.generativeai`; the deleted files stay deleted; `/api/doctor/run` no longer routes to a Gemini API wrapper.
**done-when:** The repo has zero references to `google.generativeai`; the doctor test gate is green.

## Wave 2
**Title:** The doctor agentic session backend
**Deliverables:**
- `POST /api/doctor/session_start` (token-authed, default-deny middleware): starts ONE interactive doctor session via the existing PTY substrate — engine resolved honestly via `lanes.detect_host_profile()` / `select_engine_plan('general')` (Claude driver when present; `agy`/`gemini` on a Gemini-only host; honest `unavailable` status when neither — never a crash). The engine CLI is launched in READ-ONLY plan permission mode, cwd = `ANCHOR_DIR` (no worktree — diagnostics run against the live folder but cannot mutate it).
- Seed (one-time, reusing the existing seed-once mechanism): the latest `health_reports/*.md` (graceful "no reports yet" when absent), fresh `doctor.py run_doctor()` output, the CORRECTNESS-vs-PERFORMANCE severity rule (red vs yellow warnings), and a capability list. ASCII-safe.
- The session is registered in `session_registry` under the reserved pseudo-project id `__doctor__`, which is FILTERED from every dashboard/board/rollup surface (same pattern as `__healthcheck__` task filtering). Idempotent: a second `session_start` while one doctor session is live attaches to it, never stacks a duplicate.
- Output/input ride the EXISTING `term_ws` / `term_stream2` / `term_input2` / `term_kill` transports keyed by session id — NO new transport code.
- STUB GATE: session starts under `ANCHOR_PTY_BACKEND=stub`, seed contains the report + doctor output, engine honesty for claude-only / gemini-only / neither profiles (via `ANCHOR_CLAUDE_AVAILABLE`/`ANCHOR_GEMINI_AVAILABLE` seams), `__doctor__` filtered from `term_sessions` project listings, 401-before-substance on the new endpoint.
**done-when:** A doctor session starts stubbed, seeded, engine-honest, invisible to the boards, and reachable over the existing transports; gate green.

## Wave 3
**Title:** The /doctor page in Anchor's own style + background diagnostics
**Deliverables:**
- Rebuild the `/doctor` route's HTML in the Anchor dashboard's existing visual idiom (reuse its palette/card/button CSS patterns). Content: REAL stat cards only — overall status from the latest report (ISSUES FOUND red / warnings-present yellow / clean green, honoring the severity rule), last-run date + how many days ago, report count on disk; a recent-reports list where each row shows the actual report date and links to the actual file; the xterm terminal panel attached to the Wave-2 doctor session. NOTHING fabricated: no disk-usage card, no fake chart, no placeholder nav.
- "Run diagnostics" button: launches `anchor_healthcheck.py` as a BACKGROUND process whose output tails live into the page (cursor-stable incremental read, reusing the existing tail pattern) — never a 75s synchronous request-thread block. On completion the stat cards refresh from the new report.
- Empty/corrupt `health_reports/` renders gracefully (honest empty states, no 500s).
- Regression test: the rendered `/doctor` HTML contains no literal `{`-placeholder text (the V2 f-string bug class), no `google.generativeai` reference, and no hardcoded fake values ("68%", the fake polyline).
**done-when:** `/doctor` renders real data in Anchor's style with a live agentic terminal; STUB GATE green; Playwright + screenshot captured for John's sign-off (the v4 lesson: no UI wave is done without it).

## Wave 4 [test-only]
**Title:** Hardening, suite health, deploy (verification wave — new tests + docs only; product code lands in waves 1–3)
**Deliverables:**
- `distro.py` import scan passes (no third-party imports anywhere in product code).
- `anchor_healthcheck.py` non-regression: the daily check still passes end-to-end with the doctor changes in place.
- Full doctor gate + the repo's existing test conventions green; EXECUTION-LOG updated per wave.
- Deploy notes: warm restart via `restart_anchor.ps1`, then live-verify `/doctor` (200, real data, terminal attaches).
**done-when:** All gates green; deploy path documented; branch ready for John's merge sign-off.
