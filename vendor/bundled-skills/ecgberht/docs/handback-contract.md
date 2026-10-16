# Durable handback-file contract (skill-owned)

**Authority:** North Star criterion 15 · Wave 4 of the steward-handoff plan  
**Schema:** `schema/handback-contract.schema.json`  
**Validator for handback body:** existing `engine/receipt-validate.mjs` (no second validator)  
**Contract version:** `1.0.0`

## What this is

Every executor that runs a confirmed commission — Anchor's reference executor (implementation #1) and the skill's in-session executor (implementation #2) — implements **this** durable handback-file protocol. Ownership of the spec is the skill; hosts implement, they do not fork.

This is **not** a new handback channel (refuted e-1 stays dead). It is the existing bundle/receipt shape, delivered as a **restart-safe file pair** inside the run's own worktree so an `nssm restart` (or calling-session death) cannot lose a completed handback that was only sitting in a live stdout reader.

## Path convention (inside the run worktree)

| Path | Role |
|---|---|
| `.ecgberht/handback/handback.json` | Handback body — receipt schema, `kind: "handback"` |
| `.ecgberht/handback/TERMINAL.marker` | Terminal marker — present only after the handback write is durable |

Helpers:

- `handbackDir(worktree)` → `<worktree>/.ecgberht/handback`
- `handbackJsonPath(worktree)` → `…/handback.json`
- `terminalMarkerPath(worktree)` → `…/TERMINAL.marker`

Relative segments are fixed by the schema (`handback_rel_dir`, `handback_json_name`, `terminal_marker_name`). Do not invent alternate paths per host.

## Handback JSON shape

The body is a structured receipt validated by **`validateReceipt`** from `engine/receipt-validate.mjs`:

- `schema`: `ecgberht-receipt-v0`
- `kind`: `handback`
- required campaign-memory fields: `active_effort`, `why_next`, `grasscatch_why` (nullable), `tool_depth_why`, `human_wait`, `uncertainty_flags` (array)

Optional but recommended for executors: `commission_id`, `skill`, `depth`, `client_event_id` (idempotence key for ingestion), `handback_id` (stable id for G4 evidence).

## Terminal marker semantics

1. Write **handback.json** first (temp + fsync + rename).
2. Write **TERMINAL.marker** second (temp + fsync + rename).
3. A pair is **ingestable** only when **both** files exist.
4. Marker absent (including kill between steps, or kill mid-handback write) → **not ingestable** — never partially adopt.

The marker content is opaque (may be empty or a short JSON with `contract_version` + timestamp). Presence is the signal.

## S6 write discipline

- **Atomic write:** temp file in the **same directory** as the target → write → `fsync` → `rename` over target.
- **Single writer per run dir** by construction (one commissioned wrapper owns the dir).
- Test id **T-DUR-S6** (re-run against both executors in Wave 21): kill-mid-write → marker absent → not ingested; complete pair → ingested exactly once.

## Kill-mid-write

| Observed state | Meaning |
|---|---|
| neither file | incomplete / not started — not ingestable |
| handback.json only | torn / interrupted — **not** ingestable |
| both files | complete pair — ingestable exactly once |

## Duplicate-delivery idempotence

Ingestion keys on **`client_event_id`** (or `handback_id` when `client_event_id` is absent). Re-delivery of an already-ingested id is a no-op (`ingest_exactly_once`). The Wave-14 ingester and Wave-4 boot adopt share this key.

## No credential in the child (Descope D-1)

The commissioned child env and argv carry **no** `ANCHOR_TOKEN` and no capability secret. The run writes its handback into its own worktree; the host reconciles and ingests. A credential that never exists cannot leak.

## Implementations

| # | Host | Module | Proven by |
|---|---|---|---|
| 1 | Anchor (reference) | `commission_executor.py` | Wave 4 G4 + Wave 21 conformance (auth-on lane) |
| 2 | In-session (skill) | `engine/exec-insession.mjs` (Wave 20) | Wave 20 exec2 + Wave 21 conformance (skill lane) |

## G4 / anti-stub (related, not the contract body)

Anti-stub G4 PASS requires observed evidence:

1. **cmdline names a trio CLI entry by path segment** — a path segment (directory name or exact basename like `researchPrime.mjs`) equals a known trio token. A free substring in a filename (e.g. `researchPrime-lite-standin.mjs`) does **not** count. Classic `node -e` canned-JSON launchers are refused.
2. **handback file** at the contract path passes `receipt-validate.mjs`
3. **`(pid, proc_create_time)`** observed live then terminal

See `engine/g4-verdict.mjs` and `artifacts/g4-verdict.json`. The Wave-4 standing suite records the project verdict via the cheap profile at `gate/w4-cheap-profile/researchPrime/cli.mjs` (path segment = `researchPrime`) — that recorder lives in `test/w4-g4-record-verdict.test.mjs` and is **not** the wave-local real-run gate. The wave-local real-run gate is `gate/w4-real-run.mjs` (excluded from the standing suite; no handback-synthesize escape hatch). Shipped G4 artifacts redact host-absolute user/temp paths.
