# Anchor — Honest Telemetry + Warm Resume — Execution Log

Foreman records per-wave build outcomes below. 7 wave(s) planned.

## Waves

### Wave 1 — W1 Ground Truth — artifacts (cited by path; Foreman appends its GREEN/HALT verdict below)

All Wave-1 deliverables exist in the repo at these paths:

- **Pinned sidecar fixtures** (real observed shape, anonymized):
  `tests/fixtures/sidecar/canonical_3turn.jsonl`, `resumed_segment.jsonl`,
  `corrupted_zero_usage.jsonl`, `corrupted_malformed.jsonl`, `EXPECTED.json`,
  `README.md`. Load-bearing finding: **dedup by `message.id`** (87% of real sidecars
  carry verbatim-duplicated usage records; naive summing double-counts).
- **Sidecar spike findings + narration-floor cost arithmetic + orientation plan-mode
  verification**: `planning/telemetry-resume-2026-07/W1-GROUND-TRUTH.md`
  (§1 sidecar shape · §2 `permission_mode='plan'` ENFORCEABLE — primary fork branch holds ·
  §3 arithmetic: 33/33 real managed sessions summary-less, managed enrichment coverage 0%).
- **Wave-0 closed-world audit** (v4 rollup + v8 persist, additive-compatible vs superseded):
  `planning/telemetry-resume-2026-07/W1-CLOSED-WORLD-AUDIT.md`. `ANCHOR_SIDECAR_DIR` is
  unset in every test → new cost source OFF; only 2 shape-assertions flagged SUPERSEDED
  (`test_cli_v4::test_cli_rollup_shape_and_delegates`, `test_effort_rollup::test_zero_when_no_run_metrics`).
- **Registry-state fixture capture tool**: `tools/capture_registry_fixture.py`
  (anonymized; scrubs `crypt_token`/host paths/free text). **Captured fixture set**:
  `tests/fixtures/registry_state/sessions.json`, `efforts/proj-0000_build.json`,
  `MANIFEST.json`, `README.md` — includes the two MANDATORY classes: ≥1 **evicted-parked**
  session (`sess-0003`) + ≥1 **finished one-shot job** (`run-1783775099001`).
- **Playwright B2 reproduction suite** (reproduce + classify; no fixes): `tests/test_b2_repro_w1.py`
  — all three symptoms reproduced and classified as SEPARATE plan items: S1 (state-bug),
  S2 (state-bug), S3 (state-bug facet + attach-race facet needing the WS attach-ack change).
  Root-cause source: `planning/telemetry-resume-2026-07/intake/gap-closures-b2.md`.
- **North Star doc amendment** (single citation target; ALL locked contracts verbatim;
  Gemini-segment stub **status=RULED, letter=C**):
  `planning/telemetry-resume-2026-07/NORTH-STAR-AMENDMENT.md`.

_(Foreman appends a GREEN/HALT entry per wave below.)_

## Stage-1/2 gate — APPROVED (John, 2026-07-11)
- Master Plan APPROVED (Stage-1 gate). Implementation Plan APPROVED for build ("run foreman", Stage-2 gate).
- Tier: STANDARD (Opus 4.8 on Claude seats — John: "not heavy, let opus 4.8 do the claude work"); Gemini on review seats (5:1).
- Gemini-segment scope: RULED Option C (badge now + dated fast-follow spike, recorded here at deploy).
- Fix applied pre-handoff: test-command changed pytest -q to pytest -v (Foreman anti-forgery gate requires per-test events); well-formedness gate re-run PASS.
- Honest caveats carried from planning: Stage-2 shark rounds 2-5 were false-dry (>32KB prompt argv defect); Stage-2 judge ran same-model persona. Foreman's own per-wave adversarial Gemini reviewers are the compensating rigor.

## W1 amendment (2026-07-11) — non-skipping B2 repros (John: "rework repros to not skip")
- Launch #4 wave-1 EXECUTE completed OK ($11.74) and the full-suite GATE ran to completion (956s), but HALTed on Foreman's §5 test-integrity guard: the B2 repro tests were authored skip-gated (pytest.importorskip("playwright") + pytest.skip("inconclusive")), raising skip/xfail markers 126->138 with 7 actually skipped. The guard hard-refuses any skip rise absent a plan citation.
- Resolution (John-approved): W1's B2-repro deliverable + G/W/T + done-when amended to mandate NON-SKIPPING pure-Python repros that are GREEN in the standard gate (S1 blank-window = unit test of the stale-live-cache + silent-unknown-session-close decision logic; S2/S3 = rendered-HTML/source inspection). Any genuinely browser-only assertion is DEFERRED to W6 (fix + Playwright sign-off). No skip/xfail on the gate path.
- Prior infra fixes retained: Opus standard tier (execute/fix=claude-opus-4-8, review=gemini-3.1-pro), FOREMAN_GATE_TIMEOUT_MS=1500000, --call-timeout-min 90, detached Start-Process launch, gitignored logs.

### Wave 7 — W7 Verification, Deploy, and the Measured Undercount — artifacts (cited by path; Foreman appends its GREEN/HALT verdict below)

**Source deliverables (in the repo, gated under the standard `pytest tests/ -v`):**

- **Healthcheck capture+finalize walk** — `anchor_healthcheck.check_telemetry_capture_surface`
  (wired into `main()` after `check_gandalf_surface`). FULLY STUBBED (temp
  `ANCHOR_SIDECAR_DIR` with the pinned `tests/fixtures/sidecar/` fixtures + stub PTY +
  fake runner + temp git repo): the CLEAN leg finalizes ONE `measured` RUN cost record
  whose token totals + duration equal `EXPECTED.json` exactly (`$`==0.0, no-own-pricing-
  table); the CORRUPTED leg (`corrupted_zero_usage.jsonl`) finalizes ONE RED-classified
  `capture-failed` record (`cost=None`, reason `zero-usage-despite-message-lines`) with
  the session lifecycle intact — the RED-surfacing path is exercised against a throwaway
  probe report (`_surface_capture_failed` → `report.check(False)`) so the SEVERITY is
  proven WITHOUT reddening the daily banner. Throwaway ledger docs are removed in
  `finally`; the W2 fail-closed seam means no real `~/.claude` home path is ever
  resolvable; never `:8777`.
- **Auth-enumeration wired into the walk** — `_telemetry_routes_auth_enumeration` asserts
  every NEW telemetry route is declared token-gated in `route_table.ROUTES`
  (`GET /api/rnd/session_narration`, `GET /api/rnd/usage_ledger`,
  `POST /api/rnd/resume_live`, `POST /api/rnd/orient_session`); a missing/ungated route is
  a BLOCKER. The generic `check_route_table_walk` additionally 401-walks every declared
  row against the live throwaway server.
- **Split-severity live drift tripwire** — `anchor_healthcheck.check_sidecar_drift_tripwire`
  (wired into `main()`). Deterministic + load-independent (it parses bytes, never times):
  zero sidecars → `report.warn` (environmental, never red); ≥1 recent sidecar PRESENT but
  parse-raising OR zero-usage-despite-message-lines → `report.check(False)` RED, its meaning
  documented in the detail ("NEW sessions land capture-failed until the parser is fixed;
  capture never halts, nothing zeroed"); clean recent sidecars → green. `_drift_scan_root`
  reads the REAL `~/.claude/projects` on the production 5AM run but returns None (warn-skip)
  in a hermetic test context without an explicit `ANCHOR_SIDECAR_DIR` — it never reads a
  test-runner's home.
- **STUB-GATE test** — `tests/test_verification_w7.py`: the walk is green (clean+corrupted
  legs), leaves no ledger/env leak, never binds `:8777`; the tripwire's zero→warn /
  clean→green / present-but-unparseable→RED / hermetic→warn-skip legs; the auth enumeration
  passes and flags a pruned route; both checks are wired into `main()`.

**Deploy-time verification + follow-ups (executed by the orchestrator/John at deploy; live
numbers recorded here THEN, not silently deferred):**

- **Deploy sign-off smoke run (live).** After deploy, start one real interactive Claude
  session, do a few turns, kill it, and compare the project rollup delta to the session's
  own sidecar (`~/.claude/projects/<slug>/<uuid>.jsonl`, summed per-message deduped by
  `message.id`). PASS ⇔ tokens match EXACTLY and time is within tolerance. This is the ONLY
  place a real sidecar meets the parser outside the tripwire. RESULT: _pending deploy —
  fill in (before-rollup, after-rollup, sidecar tokens/time)._
- **Undercount before/after (derived-I1 → observed).** On ≥1 real project, record the rollup
  BEFORE (pre-feature: mostly `unmeasured`) vs AFTER (prospectively measured). Frame per
  defer-and-badge as "prospectively measured spend now visible" + "N pre-feature sessions
  PERMANENTLY unmeasured" — never a recovery percentage (pre-feature sessions are never
  retro-attributed). METHOD: `rollup_honesty.project_capture_rate(pid, window)` +
  `capture_rate_line` for the stamped rate; `rnd narration-coverage` for the two-number
  coverage. The per-project COUNT of `unmeasured (pre-feature)` sessions is an environment
  fact of John's live `.anchor/` store (hermetic build cannot read it — the W2 seam is the
  point; cf. W1-GROUND-TRUTH §3). RESULT: _pending deploy — fill in per-project (N
  pre-feature unmeasured; before/after visible spend)._
- **One-week prospective capture-rate follow-up.** Owner: John. Due **2026-07-20** (one week
  after the 2026-07-13 build). Target: ≥90% of Claude-engine sessions `measured`, 0
  `capture-failed` on the dashboard capture-rate stamp. If any `capture-failed` persists, the
  drift tripwire's RED meaning applies — fix the parser; capture was never halted.
- **Option-C Gemini/agy telemetry — dated fast-follow spike.** Per the RULED Option C
  (NORTH-STAR-AMENDMENT.md, status=RULED letter=C): mixed sessions badge `partial (gemini
  segment unmeasured)` NOW; the agy/Gemini per-message usage capture is a scheduled spike,
  NOT abandoned. Owner: John / Crucible. Target: **2026-08-31** (Crucible scope → Foreman
  build). Deliverable: an agy/Gemini sidecar-shape spike + a ledger-segment for the Gemini
  part, flipping mixed sessions from `partial` to fully `measured`.

_(Foreman appends a GREEN/HALT entry per wave below.)_
