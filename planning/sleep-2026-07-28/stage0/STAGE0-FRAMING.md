# Stage 0 — Intake & Framing
## Effort: Anchor sleep cycle 2026-07-28 (v1.2 branch)

**Repo:** `C:\dev\Anchor` · **branch:** `v1.2` (not master, not public release)  
**Intake:** `planning/sleep-2026-07-28/SLEEP-BRIEF.md` (read in full; claims pre-verified)  
**Date:** 2026-07-29  
**Driver seating (prefs):** coding=`claude` · review=`grok` · `cross_model:true` · TRIO_TIER=standard  
**Emit isolation (locked pre-flight):** all Stage-2 docs → `planning/sleep-2026-07-28/stage2/` only — **never** repo root (stale foreign Foreman doc-set landmine confirmed present).

---

## Complexity triage

| Signal | Assessment |
|--------|------------|
| Scope | Multi-surface UI + Doctor subsystem + session lifecycle + preview + honesty rendering |
| Novelty | Medium — mostly fix/harden existing paths; Doctor diagnose path may be new depth |
| Stakes | High — dead controls, silent zeros, real-money test-suite history, steward usability |
| Unknowns | Moderate — per-seat Doctor failures need independent verify; S7 expansion root cause is JS/CSS |
| Irreversibility | Low for code (v1.2 only; v1.1.x steward-free), high for trust if honesty defects ship |

**Recommended band: FULL**  
Rationale: honesty properties will fire Crucible hardening-gate 0080/0081; multi-wave UI with render-level tests; dependency-ordered work spanning several subsystems. Not LITE (too many surfaces and standing honesty law). Not SPIKE-FIRST (brief already verified premises including two corrected ones).

**Depth confirmation:** FULL unless user overrides.

---

## Path & tier

**Brownfield Tier 2** — live repo on `v1.2`, friction journal as source of truth, two records already closed in triage (`3258464`, `4134bcc`). No Tier-3 archaeology required; brief is the verified intake.

---

## Confirmed / Inferred / Gap

### Confirmed
- High Seat token re-prompt fixed (`3258464`); Ecgberht version control fixed (`4134bcc`).
- S4 premise corrected: rollup numbers exist; failure is **surfacing**, not data absence. `cost_usd: 0.0` must not render as `$0.00`.
- Root carries foreign Foreman docs (doctor-ui, share-canonical-onboard, Butler 2026-07-24). Explicit docs block would silently select wrong plan.
- Suite is pytest; money leak history → scoped `gate-command:` per wave with `-v` only.
- Dashboard JS is f-string-generated → render + `node --check` assertions required for UI waves.
- Projects tile markup has no `<details open>` at source; expansion is JS/CSS (S7).
- `tests/test_auth_reprompt_2026_07_28.py` is the pattern for rendered UI tests.
- Steward structure suite exists (`tests/test_ecgberht_steward_v12.py`, 22 tests) — proves structure, not human conversation.

### Inferred
- S2 double-error and dead Retry share the attach-failure path; likely re-append vs replace + unwired Retry handler.
- Doctor diagnose may be plan/seed only for some seats; each seat must be verified independently.
- File preview working path in new window can be reused for in-pane preview.

### Gaps (do not block NS lock if scoped correctly)
- Exact per-seat Doctor failure modes (measure in S3 waves, not invent).
- Whether S8 cadence should be engine-owned timer vs dashboard poll (decide in Stage 1 design).
- S1 is **validation, not build** — see scope decision.

---

## Scope decision (Stage 0 pushback)

The brief’s 8 work items span dead controls, rendering honesty, Doctor, session lifecycle, preview, UX polish, and cadence — **plus** S1 which is a human validation session that produces journal records, not code.

**Recommendation (default for this effort):**

| In scope (build) | Out of scope for Foreman waves |
|------------------|--------------------------------|
| S2 attach/Retry | **S1 steward E2E** — post-build manual session; journal new friction; not a wave that “builds” |
| S4 usage surfacing | Root Foreman landmine cleanup (other efforts own those files) |
| S3 Doctor (diagnose + banner payload + per-seat honesty) | Shipping anything to v1.1.x / collaborators |
| S5 stop/summary/restart | |
| S6 file preview | |
| S7 folders default-collapsed | |
| S8 status cadence (Anchor-owned) | |

**Why not two full efforts:** dependency order is linear (S2 before S5; S4/S3 independent after S2; S6–S8 independent). One FULL plan with ~8–12 waves is coherent if S1 is carved out. Splitting Doctor (S3) into a second effort is viable only if Stage 1 finds S3 larger than the rest combined — re-evaluate at Stage 1, not by default.

**If user prefers smaller first cut:** Ship **S2 + S4 + S6 + S7** first (visible dead-control + honesty + quick wins), then a follow-on for S3/S5/S8. That is the alternate scope.

---

## Candidate North Star (refined — not inherited verbatim)

### Statement

On branch **v1.2**, John can open, run, stop, and restart real Anchor work — including Doctor diagnose and session attach — without meeting a **dead control**, a **silent zero**, a **mislabelled empty**, or a **preview that dumps raw binary**. Every surface that claims health, usage, or diagnose either works end-to-end or fails with a **named, user-visible state** (unknown ≠ empty ≠ zero). Cost never fabricates dollars. Nothing in this effort ships to v1.1.x collaborators. Steward **conversational** proof is a **post-build validation session** (S1), not a silent claim of this build.

### Success criteria (testable)

1. **Dead controls eliminated for in-scope surfaces:** Retry (session attach), Diagnose (Doctor), and the single restart control either perform their action or are not shown; no “looks clickable but does nothing.”
2. **Attach path honesty:** attach timeout is classified and rendered as timeout (not unknown-session); error UI does not double-print; Retry re-issues a viable action or explains why not.
3. **Usage/time/cost surfacing:** project dashboard, workbench tiles, and session chrome render rollup numbers that already exist; `cost_usd == 0` (subscription) renders as `(subscription)` with reason, never `$0.00`; unmeasured engines show labelled unmeasured, never blank or numeric zero pretending to be a measurement.
4. **Doctor actually doctors:** Diagnose runs a real diagnosis (not shell/seed/plan-only theater); banner→Doctor handoff carries issue payload; Claude / Gemini / Grok each report independently (no blended “engine unavailable”).
5. **Stop / summary / restart:** stopping leaves a tile summarizing what was in flight; one restart control; restart quality is documented and testable (no dual competing buttons).
6. **File preview:** shared preview path shows human-friendly Word/PPTX/Excel/PDF (reuse working new-window path); binary no longer dumps as text; related JSONDecodeError on binary confirmed fixed or separately named.
7. **Projects default collapsed:** project folders open collapsed by default; user expand/collapse preference remembered; root cause is the real JS/CSS path (not a wrong template guess).
8. **Cadence is real:** status cadence is owned by Anchor from live telemetry on a timer (or equivalent), not a prose line that looks like a scheduler.
9. **Gates:** every surface-bearing wave has failure-state tables with **unknown** and **empty** as separate rows; scoped pytest `gate-command:` per wave (`-v`); UI waves assert on **rendered** HTML + `node --check` scripts; delta-coverage for new routes/handlers/frontend entries.
10. **Handoff hygiene:** doc-trio + `foreman.config.json` only under `planning/sleep-2026-07-28/stage2/`; Foreman cwd that directory; root foreign artifacts untouched; commits land per wave (GO without SHA is not GO); EXECUTION-LOG appended; attestation count reported.

### Non-goals

- Public release / master / v1.1.x collaborator line.
- Replacing Ecgberht architecture or re-running steward-tracking Stage2.
- Full-suite unscoped pytest as a gate (money risk).
- Cleaning or deleting root stale Foreman artifacts (other efforts).
- Claiming steward E2E conversation works solely because structure tests pass.
- Fabricated dollar pricing tables.
- Auto-remediation that hides failures (Doctor reports; it does not silently “fix everything”).

### Risk taxonomy

| Risk | Mitigation |
|------|------------|
| Wrong-plan Foreman launch at repo root | Isolated stage2 cwd + own config; never touch root trio |
| Silent zero / empty collapse | Hardening-gate tables; render tests for zero vs empty vs unknown |
| Dead Retry/Diagnose regress | Render-level + behavioral tests naming controls |
| Real engine spawns in tests | Scoped gates; conftest fail-closed; no bare full suite |
| Doctor seat flakiness | Per-seat status rows; no blended unavailable |
| Dual-root / vacuous-GREEN thrash | Handoff dir = code-adjacent stage2; proven ledgers if dual-root appears; report attest count |
| S1 mistaken for build | Explicitly out of Foreman waves; manual post-build session |
| GO without commit (journal 0093) | Per-wave commit SHA in EXECUTION-LOG; fail closed if null |

### Foresight (2–3 steps ahead)

1. After dead controls and usage honesty land, Doctor becomes the next trust surface — seed it with banner truth or it re-teaches “broken product.”
2. Once sessions attach/stop/restart cleanly, steward E2E (S1) becomes a fair validation; doing S1 first would only re-discover S2–S5.
3. Cadence (S8) without honest usage tiles (S4) would emit empty status theater — order S4 before S8.

### Standing constraints (carry into every stage)

- Never a silent zero; unknown ≠ empty ≠ zero.
- No pricing table; cost = `(subscription)` when unmeasured.
- Dead control ≡ crash severity.
- v1.1.x steward-free; this is v1.2 only.
- UTF-8 no BOM on emit; mojibake lint before well-formedness.

---

## Pipeline depth stamp

- **Band:** FULL  
- **Tier:** Brownfield T2  
- **In-scope build items:** S2, S4, S3, S5, S6, S7, S8  
- **Post-build (not Foreman):** S1  
- **Emit path:** `planning/sleep-2026-07-28/stage2/` only  

---

## HALT — North Star lock (user is convergence authority)

Stage 0 stops here. No Stage 1 until the North Star (and scope) are locked.
