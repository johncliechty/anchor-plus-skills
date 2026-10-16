# Host-agnostic status-ingestion seam (Wave 13)

**Authority:** Master-Plan P6 · Wave 13 of the steward-handoff plan  
**Seam:** `ingestStatusEvents(producer)` in `engine/status-ingestion.mjs`  
**Projection binding:** existing `roadmap.mjs` `buildRoadmapProjection` (e-4 closed by name)

## What this is

The **one** named path through which any host's run-status truth reaches the campaign ledger. Producers emit named events with a monotonic per-producer sequence; the seam acknowledges an idempotent drain and routes spine-bound flips through the Wave-6 single writer (`appendRoadmapEventThroughSpine`). No host peeks at live pids inside the brief composer.

## Producers

| # | Host | How it reaches the seam | Wave |
|---|---|---|---|
| 1 | Anchor | Python fsync'd outbox (S12) → Node mediator `drainOutboxThroughSeam` | 13 |
| 2 | In-session executor | Direct producer on this seam (never a parallel path) | 20 |

Anchor Python **never** writes `roadmap.json`. The mediator is the spine's client.

## Outbox (S12)

Relative path inside a run worktree:

- `.ecgberht/status/outbox.json` — monotonic `records[]` + `next_seq`
- `.ecgberht/status/outbox-ack.json` — mediator-owned last-acked seq per producer

Write discipline: temp + fsync + rename (`writeFileAtomicSync` / Python `_atomic_write` with Windows sharing-violation retry).

## Lease law

| Constant | Role |
|---|---|
| `LEASE_TTL_MS` | Hard TTL — past this without renew → **dead** |
| soft fraction (0.8) | Soft zone → **stale** (distinct from dead) |
| `LEASE_HYSTERESIS_MS` | Anti-flap hold before a committed flip |
| clock | Monotonic / seq-anchored (wall skew cannot move TTL) |

`state_since` is edge-triggered. Sampled-across-boundary tests include jittered renewals and skewed wall clock.

## Run liveness vs roadmap step status

Run liveness (`running` / `stale` / `dead` / `parked` / …) is the seam's vocabulary. Roadmap step statuses stay schema-legal (`active` / `waiting` / `parked` / …). A **dead** run flips the step to `waiting` with receipt `why` carrying `status_flip->DEAD cause=lease_expired` so the bound view reports dead **by name**.

## Failure states (P6 table)

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (launcher down) | `LAUNCH_INTENT_STRANDED` | Confirmed but not launched — the launcher is down; intent preserved, will reconcile at boot. |
| dependency-slow-or-killed (lease expired) | `RUN_DEAD_LEASE_EXPIRED` | The run died (lease expired \<t\>) — marked DEAD, not RUNNING. |
| dependency-returns-garbage (outbox gap) | `STATUS_SEQUENCE_GAP` | Status sequence gap detected — status shown as of seq \<n\>, gap flagged. |
| backing-store-unreadable | `OUTBOX_UNREADABLE` | Status outbox unreadable — last durable status shown with its timestamp. |
| empty-but-valid (no runs) | `NO_LIVE_RUNS` | Nothing is running. |
| unknown (reconciler cannot decide) | `RUN_LIVENESS_UNKNOWN` | Run liveness UNKNOWN — neither RUNNING nor DEAD is claimed. |

## Parity matrix

Checked-in table: `artifacts/w13-parity-matrix.json` (park / restart / kill).

## Gate-surfacing

`gate_surface` is a first-class event kind. Wave-local real-run proof: `gate/w13-real-run.mjs` (excluded from the standing suite), measured against the Wave-5 gate budget.
