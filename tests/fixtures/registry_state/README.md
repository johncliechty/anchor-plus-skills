# Anonymized registry-state fixtures (telemetry-resume W1)

Captured real `session_registry` + effort-store states, **anonymized**, so the
B2 reproductions (`tests/test_b2_repro_w1.py`) and the W3 narration-template
property test run against **captured real states** rather than hand-built toys.

## What's here

- `sessions.json` — the `{session_id: record}` map exactly as
  `.anchor/sessions.json` stores it, one record per managed terminal session,
  spanning every tile class (see `MANIFEST.json`).
- `efforts/proj-0000_build.json` — the build lane's effort pointer-records
  (flattened one file per `(project, lane)`), carrying the **finished one-shot
  job** with a real cost block.
- `MANIFEST.json` — maps each record to its tile class and flags the two
  **mandatory** classes required by the W1 done-when.
- `README.md` — this file.

## Mandatory classes (W1 done-when)

The capture set **must** include, and does:

- **≥1 evicted-parked session** → `sess-0003` (worktree reaped, everything else
  survives — the locked evicted-tile sub-contract).
- **≥1 finished one-shot job** → effort `run-1783775099001` (durable job with a
  cost block; no PTY record).

## Anonymization (honesty + safety)

Produced by `tools/capture_registry_fixture.py`, which **scrubs** every sensitive
or host-identifying field before writing: `worktree_path` and `branch` (host
paths) → `<scrubbed-worktree>/…` / `<scrubbed-branch>`; `seed_text` /
`prompt_seed` (may contain user text) → `<scrubbed-…>`; `crypt_token` (the session
auth secret) → `""`; `pid` / `proc_create_time` (process identity) → `null`;
`label` (free text) → `""`. Structural fields (status, lane, chain lineage,
stage, timestamps, effort_managed, cost) are preserved so the reproductions are
faithful. No real session UUIDs, host paths, tokens, or prompt/response text
survive into the fixture.

## The S1 stale-cache subject

`sess-0006` is the **server-dead / client-stale-running** case that drives the S1
blank-window reproduction: its server-truth status is `reaped-orphan` (reconciled
dead), yet a client tab that was open when it died still caches it as
`MANAGED['sess-0006'].status === 'running'`. `openEffortDock` decides liveness
from that client cache alone (`static/project-window.js`), so it picks the live
transport, which closes silently on `unknown-session` → a blank pane. The repro
asserts exactly this decision + the zero-byte close.
