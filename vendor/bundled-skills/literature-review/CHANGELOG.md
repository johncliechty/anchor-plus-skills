# CHANGELOG — literature-review

## 2026-07-25 (journal-hardening P1/P2)
- fetchWithBackoff: Retry-After honored; 1s jittered base (60s cap); `S2_API_KEY` sent
  as `x-api-key`; sleep/fetch injectable.
- Seed-resolution (ingest) calls routed through the backoff (had zero retry).
- Mid-walk fetch failures stamped as PRISMA `fetch-failed` exclusions + a
  `fetchFailures` result field (was a silent empty catch).
- NORTH-STAR.md / LESSONS.md / CHANGELOG.md created at the skill root.

## 2026-07-11
- REWIRED REAL: the CLI never fabricates; honest-stop when live seats are absent;
  trio-module imports with parity/fence tests.
