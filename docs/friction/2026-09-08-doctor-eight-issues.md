# Doctor eight-issue verification - 2026-09-08

John requested sequential reproduction, repair, focused verification and a receipt
for each of the eight saved failures, followed by one standard healthcheck.

The starting worktree already contains unfinished repairs documented in
`2026-09-08-doctor-flag-repair.md`: scoped read-only summary launches, explicit
fixture protocols, stub transport model-discovery isolation, and supervisor
launch diagnostics. Preserve these and unrelated existing work.

- Issue 1: the current minimal v2 HTTP walk passes (2 tests), so the saved 500
  is not reproducible with the existing repair. Session summary adapter and
  fixture regressions also pass (2 tests). Add a full v2 HTTP walk with saved
  ChatGPT preferences and forbidden live discovery to retain the triggering
  configuration; the original HTTP fixture did not assert that configuration.
- Issue 1 receipt: all 5 focused checks passed, including saved-ChatGPT HTTP.
- Issue 2: current v3 walk passes; scoped project summaries share the existing
  repaired launch helper. Added saved-ChatGPT coverage. All 5 v3 checks passed;
  independent summary-contract review also passed all 7 contract tests.
- Issue 3: current v4 walk and saved-ChatGPT regression pass (5 tests). The
  existing repair seats the stdin-seed fixture on Claude and avoids provider
  discovery only for the actual in-memory PTY. Validate both stub availability
  and retained real-provider rejection contracts before closing this item.
- Independent review found one adjacent summary test fixture still starting a
  fake planning job without an explicit backend. It inherits ChatGPT and fails
  before summarization; handle alongside the remaining summary checks.
- Issue 3 receipt: 5 v4 checks and all 12 stub/real-transport contract tests pass.
- Issue 4: current v5 walk passes. Added saved-ChatGPT coverage (5 v5 checks
  pass), and explicitly selected Claude for the adjacent fake planning-job
  fixture. All 17 summarizer tests now pass, including captured effort metrics,
  concurrent caching, regeneration, and failure retry behavior.
- Issue 5: current v6 surface passes; added saved-ChatGPT coverage. All 6 v6
  checks plus 13 stream-json/content/grounding regressions pass. These exercise
  actual local stub processes and cache output, not mocked summary results.
- Issue 6: current v7 walk passes; added saved-ChatGPT coverage. All 8 tests pass,
  including summarize-on-finish cached output, nonempty blurb and cleanup.
- Issue 7: the repaired inline-supervisor walk passes under saved ChatGPT
  preferences. Explicit Claude fixture selection preserves the stub flags; the
  check proves same-job restart survival, advancing durable cursor and cancel.
- Issue 8: both external-supervisor focused checks pass, covering launch/tail/
  cancel, restart cursor persistence and actionable rejection diagnostics rather
  than `KeyError: job_id`. All eight reported failures are absent in the current
  focused probes. Run the expanded combined preference regressions before the
  single final standard healthcheck; do not manually clear or rewrite its report.
- Combined verification: all 28 saved-preference, summary-adapter and stub-policy
  regressions pass together; `git diff --check` passes. Launching the standard
  `python anchor_healthcheck.py` once to refresh the canonical report.
- Final standard healthcheck: exit 0, 98.8 seconds, started 12:26:52. The canonical
  `health_reports/2026-09-08.md` reports `Status: OK`, all 31 correctness checks
  passed, and no open issues. All eight requested rows are green. One non-blocking
  warning reports that the sidecar drift probe was skipped in hermetic context
  without an explicit sidecar directory; no live sidecar data was probed.
- SHA-256 checks confirm both `settings.json` and the user model-preferences
  mirror are unchanged across the standard healthcheck. Independent read-only
  code review found no blocking issue in the requested repairs.
- The first live `/api/doctor/status` request used `X-Anchor-Token` and returned
  401 because this GET route requires query/Bearer auth. Retrying with the same
  configured token via `Authorization: Bearer` succeeded: `ok=true`,
  `status=yellow`, `issues=[]`. The live Doctor page returned HTTP 200, includes
  the new report, and contains no `ISSUES FOUND` text. Yellow reflects the
  documented skipped-probe warning, not an open correctness issue.
