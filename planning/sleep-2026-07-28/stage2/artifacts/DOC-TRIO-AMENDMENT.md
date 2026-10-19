# DOC-TRIO-AMENDMENT

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W5 — Phase 1: Wave-list freeze + doc-trio amendment procedure

## Purpose

Define exactly how a STUB-forced **build it** wave is inserted into the
doc-trio (`IMPLEMENTATION-PLAN.md` + `EXECUTION-LOG.md`) **without touching
the product root outside this containment tree**. All writes stay under
`planning/sleep-2026-07-28/stage2/`.

## Insertion cap

- At most **3** inserted `build it` waves across the build.
- A **4th** insertion returns `HALT_REBASELINE` from `tools/freeze_gate.py`.
- No surface wave (W10–W21) starts until John records an **explicit
  re-baseline** of scope (recorded on the freeze as `Re-baseline: recorded`).

Planned waves already in `IMPLEMENTATION-PLAN.md` at freeze (W1–W22) do **not**
count against the insertion cap. Only waves **added after freeze** via this
procedure count.

## When to insert

Insert only when:

1. A capability-inventory row is **STUB** (or a mid-build re-probe newly
   returns STUB), and
2. No existing planned wave already owns building that control, and
3. The insertion would not exceed the cap (check
   `attempt_insert_build_it_wave` first).

## Procedure (ordered, atomic intent)

1. **Cap check** — call `tools.freeze_gate.attempt_insert_build_it_wave`.
   If status is `HALT_REBASELINE`, stop. Do not edit the plan.
2. **Draft the wave block** — a full Foreman wave section (Intent,
   Deliverables, Depends on, done-when, Given/When/Then) naming the control
   and the inventory transcript it repairs.
3. **Edit only inside the containment root:**
   - `IMPLEMENTATION-PLAN.md` — insert the wave block in wave-number order;
     renumber only if the orchestrator requires contiguous ids; prefer a
     lettered id (`W14a`) when inserting between existing waves.
   - `EXECUTION-LOG.md` — append an amendment notice: date, reason (STUB
     control id), new wave id, and the pre/post inserted-build-it count.
   - Do **not** edit product-root Foreman artifacts belonging to other
     efforts. Containment is enforced by `tools/containment_smoke.py`.
4. **Re-probe** — the fixing wave's gate must re-run the capability probe and
   rewrite the inventory row (source-hash mismatch makes a stale STUB fail
   closed rather than silently persist).
5. **Re-freeze** — recompute the evidence hash over
   `artifacts/CAPABILITY-INVENTORY.md` + `artifacts/ROLLUP-EVIDENCE.md`,
   update `artifacts/WAVE-LIST-FREEZE.md` (stamp, hash, inserted count,
   decision table if a North-Star control moved), and re-run
   `tools.freeze_gate.phase1_go_decision`. Surface waves stay blocked until
   the new stamp verifies.
6. **John gate** — if the North-Star CONTROL DECISION table changes, John's
   Phase-1 verdict review line must be refreshed on the freeze stamp.

## Explicitly forbidden

- Touching product-root foreign Foreman docs (other efforts' DESCRIPTION /
  IMPLEMENTATION-PLAN / EXECUTION-LOG at the repository root).
- Proceeding on a stale freeze after inventory/rollup bytes change.
- A fourth insert without a recorded re-baseline.
- Closing a STUB with ambient wording, `S1 will catch it`, or
  `covered by the verification task triple`.

## Machine entry points

| call | role |
|------|------|
| `freeze_gate.attempt_insert_build_it_wave` | cap check → GO or HALT_REBASELINE |
| `freeze_gate.compute_evidence_hash` | bind freeze to inventory+rollup bytes |
| `freeze_gate.bootstrap_phase1` / re-render freeze | re-stamp after amendment |
| `freeze_gate.check_surface_wave("W10")` | surface open gate |
| `containment_smoke` | refuse writes outside the containment root |
