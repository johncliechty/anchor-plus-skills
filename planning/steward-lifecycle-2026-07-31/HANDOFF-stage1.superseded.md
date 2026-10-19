# HANDOFF — steward campaign orchestration (2026-07-31)

Paste the CARRY-ON PROMPT below into a fresh session. Everything it references is on
disk. Anchor `master` and `v1.2` are both at `8c47317`, pushed (as of Stage-1 handoff).

---

## CARRY-ON PROMPT

Carry on the **Anchor steward campaign-orchestration effort**. Read these first, in
order, before doing anything:

1. `C:\dev\Anchor\planning\steward-lifecycle-2026-07-31\NORTH-STAR.md` — **North Star
   v4, LOCKED by John 2026-07-31.** Anti-drift authority, 13 criteria. Do not re-open
   without an explicit re-lock.
2. `...\MASTER-PLAN-v2.md` — **Master Plan v2, STAGE-1 APPROVED 2026-07-31**
   (see `STAGE1-APPROVAL.md`, which now also carries GATE DECISION 4).
2b. **THE STAGE-2 BUILD INPUT IS THE v2 PAIR ONLY:**
   `stage2-artifacts\IMPLEMENTATION-PLAN-v2.md` (19 waves, AUTHORITATIVE) +
   `stage2-artifacts\wave-decomposition-v2.json` (generated from it; embeds a
   sha256 of the plan text that MATCHES). The old 17-wave decomposition is
   renamed `wave-decomposition.STALE-DO-NOT-USE.json` — it contradicted the plan
   on G4 semantics and must NEVER reach a builder. Reviews:
   `REVIEW-CONSISTENCY.md`, `REVIEW-HARDENING.md`, `FIXES-APPLIED.md`.
3. `C:\dev\Anchor\planning\steward-lifecycle-2026-07-31\INTAKE.md` — verified
   build-vs-wire fact base.
4. `C:\dev\Ecgberht\NEXT-UX-AND-ANCHOR-ORCHESTRATION.md` — John's LOCKED UX intent
   (§A project steward, §B portfolio/High Seat). Binding.

### Where we are — and the immediate next action
Crucible **Stage 0 COMPLETE** (NS v4 locked). **Stage 1 APPROVED** (Master Plan v2 +
three gate decisions). **Stage 2 RUNNING or HALTed** under
`stage2-artifacts/` / `_crucible-status-stage2.log` / `handoff/` — launcher
`C:\Users\john\.claude\skills\crucible\bin\_steward_stage2.mjs` via schtask
`crucible-steward-s2`.

**YOUR NEXT ACTION:** if Stage 2 is still running, post the locked status table ~10 min
from `_crucible-status-stage2.log`. When it HALTs human-lockable or converges, take
John through the **Stage-2 approval gate** (show implementation plan / doc-trio IN
FULL + HTML if large). After Stage-2 approve → well-formedness gate → Foreman builds.

### Stage-1 gate decisions (LOCKED)
1. Unattended reflections never spend — queue; compile at next session open.
2. Portfolio index: A5 Wave-1 live-wiring audit; fix items only; no re-plan.
3. `briefCacheStale` (A3) FIXED in Wave 1 / Phase 1 under named-fix diff fence.

### What the effort is
Make a project in Anchor stand-up-able, plannable across MANY stages, and drivable
OVER TIME by talking to its steward: scaffolding AUTHOR + stage ORCHESTRATION +
specialist COMMISSIONS + High Seat attention projection from the built portfolio index.

### Hard-won facts — do NOT re-derive or contradict
- Ecgberht engine largely BUILT (propose/confirm, bind, packet-view, receipt-validate,
  roadmap, brief.assembleBriefPacket, high-seat, rank).
- Portfolio index BUILT (19 waves GREEN, 671 tests, engine/portfolio 32 modules) —
  CONSUME; Wave-1 A5 audits live wiring.
- MISSING: Anchor commission executor (no commission in Anchor .py), dialogue→
  step_create, attention emitters, deliverable_ready state, chamber UI.
- REFUTED stay dead: new handback artifact channel; bind-and-derive as new work.
- Live defects: briefCacheStale (fix Wave 1), waiting_steps dead, precomputeBriefCache
  never called.

### Invariants
E5 single ledger · single writer · commissions FOR roadmap steps with `who` ·
subscription-CLI seats only · AUTH-ON green is the only green · no product-loop
adversarial review.

### How John wants to work
Decisions ONE AT A TIME, plain-English + recommendation. SHOW-THE-ARTIFACT at every
gate. Long runs: schtasks detach, statusLog, locked status table ~10 min, lead with
what the effort is FOR.

### Also outstanding (ask separately, not on this path)
- (a) `test_session_continue` 3 pre-existing failures — product call (stale tests vs
  contract drift).
- (b) Service restart pending for shipped UI: elevated
  `powershell -ExecutionPolicy Bypass -File .\restart_anchor.ps1` then Ctrl+Shift+R.

---

## UPDATE 2026-08-01 — Stage-2 reviewed, corrected, awaiting re-gate

Two independent Fable reviews (consistency + hardening) found the Stage-2 draft NOT
safe to hand to Foreman. Both independently named the same top risk: the machine
artifact (`wave-decomposition.json`, 17 waves) contradicted the human plan (18 waves)
on G4 HALT semantics while `hardening-gate-result.json` said PASS — one wrong
file-pick would have silently reverted the whole hardening layer with all gates green.

All 13 must-fixes were applied (`FIXES-APPLIED.md`). Result: **19 waves**, the envelope
moved BEFORE authoring (closes a pre-envelope-spend hole), Master-Plan P4 restored as
Wave 10, per-instance durability obligations (S1–S13), anti-stub G4, real single-writer
migration of 8 named call sites, non-vacuous auth assertions, both dead raise tiers
revived, `resolveSeats` restored, and gate decision 4 implemented as a named zero-model
`emitReflectionReceipt` / `proposeNextStageDeterministic` path.

**PENDING JOHN (do not proceed past these):**
1. **Sign or reject descope D-1** — run-scoped capability minting, replaced by the
   no-credential handback-file design (weakens criterion-3 defense-in-depth).
2. **Ratify the shared-secret `who` policy** — `unattributed(shared_secret)` surfaced
   as DEGRADED-by-name; criterion 3 reports met-under-shared-secret, not fully met.
3. **Re-gate the v2 pair** — corrected but UNSTAMPED (prior judge NOT_CONVERGED).
