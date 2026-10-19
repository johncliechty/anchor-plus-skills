# Doctor R&D v12 isolation repair - 2026-09-14

- Reported failure: research persistence succeeded but research-to-plan lost its
  session record; the subsequent plan-to-build, attribution, deliverable and
  effort-view checks failed. The saved report omits the actual advance error.
- The existing isolated green-check test passes (1 passed in 6.21 seconds).
  Inspection confirms the scheduled v12 probe never sets `ANCHOR_DATA_DIR`:
  its synthetic sessions share the live registry with dashboard processes,
  despite the probe's documented promise to use temporary data. Session writes
  serialize only within each process and replace the entire registry snapshot.
- Reproduction adds a separate process saving an earlier ambient registry
  snapshot immediately after research persistence. A second regression retains
  an existing session and PTY across the walk, covering its global recovery and
  cleanup effects. The precise overnight interleaving is not recoverable from
  the original report.
- Both new regressions failed against the original code. The registry-writer
  case reproduced the complete reported failure string, including the later
  build/effort-view failures. The second case confirmed that v12 cleanup killed
  an unrelated live stub PTY. Repair isolates v12's data root and scopes cleanup,
  while preserving advance error reasons and exact session-set differences.
- Verification: the combined healthcheck, advance, conversation, non-reaping
  finish, stage-baseline and build-deliverable tests passed (41 tests, 56.92s).
  After adding absent/empty/configured data-root restoration regressions and
  verifying private-registry teardown, the final v12 healthcheck suite passed
  (11 tests, 36.58s). This covers 44 distinct passing tests. Scoped
  `git diff --check` passed.
- A fresh Python process then invoked the actual `check_rnd_v12_surface` with
  the ambient data setting, outside pytest. All 13 steps passed, the data-root
  setting was restored and all owned temporary directories were removed.
  Receipt: `2026-09-14-doctor-v12-verification.json` beside this journal.
- No production service restart or full daily healthcheck was performed. The
  targeted check verifies the requested component; the existing daily report
  remains a historical record until the next full run. The full runner's
  age-based process cleanup and other probes' shared-registry behavior were
  left outside this repair. All existing unrelated workspace edits were kept.
