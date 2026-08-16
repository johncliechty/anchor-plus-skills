# Verb: commission-confirm

**Closed list:** yes · **Primary:** commission-confirm

John confirms a steward `commission_proposal`. THE write step — durable engine state, never UI-only:

- Creates the job in state `queued`, **composing Anchor's job_runner** (spawn contract only; the runner is never reimplemented).
- Appends `commission_bind` to `roadmap_events` via the single writer (`appendRoadmapEvent`) — projection derives `commissioned_as`.
- Appends a Strip instrument (`commission_confirm`) — history append-only.

Lifecycle from here (M2): `queued → running → done | failed | orphaned | reaped`. Any abnormal exit (crash/timeout/kill/orphan/reap) appends a `commission_abnormal` receipt (`who/when/last_known_state/why_known`) — a dead terminal never persists as silent green. Orphan/reap detection composes out-of-process liveness evidence (no in-engine reaper).

- `--who <name>` (required) — human confirm receipt.
- `--proposal <json>` — a prior proposal; or pass `--step` + `--skill` to build-and-confirm in one call.
- `--dry-run` / `--no-persist` — skip writing `roadmap.json` / `strip.json`.

Usage: `node bin/ecgberht.mjs commission-confirm --step <id> --skill Foreman --who john [--project <path>]`

TW3 (M2). Module: `engine/job-lifecycle.mjs`.
