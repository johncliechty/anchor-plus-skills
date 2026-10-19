# DR-04 — Process-telemetry depth + the droppable side-channel

> Phase-0 §4 decision record (foundry-v2 Wave 1). Machine-readable form:
> `foundry_decisions.PROCESS_TELEMETRY_DEPTH` (+ `JOURNAL_ENTRY_FIELDS`, `SIDE_CHANNEL_DESIGN`).
> Traces to North Star: **NS#2 (host-enforced journaling — the corpus fills itself)**.

## Decision

**Depth = `OUTCOME_PLUS_RECOVERY`.**

1. **Always-on skeleton (host-enforced, never honor-system):** every host-mediated run
   auto-appends the 7-field OUTCOME entry to `<skill_dir>/journal/` —
   `provenance · operation_kind · model_cost · inputs_ref · outputs_ref · verdict_timing ·
   outcome_linkage` — capped small (≤ ~2 KB; bulk is referenced, never inlined).
2. **Depth-1 process telemetry:** sub-agent call counts, failed recoveries, and retries are
   captured — but their detail routes to the side channel, with only the summary linkage in
   the skeleton. Rationale: the sleep loop needs to see *that* a run recovered/fanned out
   (failure patterns are the highest-value lessons), not every intermediate token.
3. **Full step-by-step process tracing is explicitly OUT of scope for v2.** The Wave-2 scope
   stamp stays honest: "OUTCOME captured; process-telemetry per Phase-0 §4."

## The droppable side-channel

- **Location:** `<skill_dir>/journal/side/<run_id>/` — holds full transcripts, per-shard
  drafts, sub-agent call detail, failed-recovery traces, raw model I/O.
- **Referenced by** the skeleton's `inputs_ref` / `outputs_ref` fields only.
- **Droppable invariant:** deleting the side channel (disk pressure, retention policy) NEVER
  breaks a skeleton entry — the Wave-5 kernel parser reads skeleton entries only, so the
  corpus survives any side-channel purge.

## Why

- The documented v1 failure mode is honor-system capture starving the loop; the fix is
  capture-as-by-product at the ONE runner seam (Waves 2→3). That seam must be cheap enough
  to be unconditional — hence a small skeleton + heavy I/O shunted sideways.
- Outcome-only (the minimal option) was rejected because recovery/fan-out signals are exactly
  the lessons the sleep kernel clusters on; full tracing (the maximal option) was rejected as
  unbounded I/O that would pressure someone to turn journaling off — the anti-pattern.

## Consumed by

Wave 2 (the journaling write-back seam implements exactly this shape), Wave 5 (the on-disk
`journal/*.md` → kernel parser validates skeleton entries and tolerates a dropped side channel).
