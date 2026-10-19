# Stage-1 APPROVAL — Master Plan v2

**Status:** **APPROVED by John 2026-07-31**  
**Artifact:** `MASTER-PLAN-v2.md` (HTML: `MASTER-PLAN-v2.html`)  
**Under:** North Star v4 (`NORTH-STAR.md`, LOCKED 2026-07-31)

## Gate decisions locked at approval

1. **Unattended reflections never spend** — handbacks with no live session envelope
   queue a typed reflection event; compile + next-stage proposal at next session open.
2. **Portfolio index** — Wave-1 audit A5 proves live wiring; gaps are fix items only;
   no re-plan of `steward-tracking-2026-07` / `engine/portfolio/`.
3. **`briefCacheStale` (A3)** — FIXED in Wave 1 / Phase 1 (not deferred to Phase 7);
   CI diff guard still fences the rest of the 19-wave GREEN tree.

## What this unlocks

Crucible **Stage 2** — wave decomposition + Shark-Tank + Foreman-ready doc-trio
handoff — then Foreman build.

## What this does NOT unlock

- No re-open of North Star v4 without explicit re-lock.
- No rebuild of the portfolio tracking index.
- No unattended spend path.
- No product-loop adversarial review of steward scaffolding.

---

## Gate decision 4 — criterion 4 interpretation (John, 2026-08-01)

**Context.** North Star criterion 4 says the steward reflects and proposes ON a
validated handback; gate decision 1 says nothing spends unattended. The Stage-2 draft
resolved that tension on its own authority with an emitted/queued split — flagged by
the consistency review as re-authoring a LOCKED criterion, and raised as a Contrarian
BLOCKER.

**DECIDED — deterministic now, rich later.** On a validated handback the steward
IMMEDIATELY emits a **zero-model, zero-spend** reflection receipt + next-stage proposal
built from ledger facts only (the `assembleBriefPacket` / Anchor narration-floor
pattern — both are established zero-model paths). The richer, model-authored version
compiles at next session open inside the confirmed envelope.

**Consequences:** criterion 4 is met LITERALLY (reflection lands on handback, not at
next open); the spend invariant is untouched (nothing unattended costs anything); John
returns to a real proposal rather than a queue marker. **No North Star amendment is
required** — this is an interpretation that satisfies the locked text, not a change to
it. The Stage-2 plan must implement the deterministic emitter as a named, tested
zero-model path with an assertion that it makes no model/network call.

## Descope D-1 — SIGNED by John 2026-08-01

**Descope:** run-scoped capability minting for commissioned runs is REPLACED by the
no-credential handback-FILE design (the run writes its handback to a durable file and
never holds a token).

**Named weakening:** criterion-3 defense-in-depth loses one layer.

**Rationale accepted:** a credential that never exists cannot leak, expire mid-run, or
be replayed; the handback-file protocol is also what allows commissioned runs to
survive an `nssm restart` (a known real failure on this host, `job_runner.py`
KILL_ON_JOB_CLOSE). The layer given up guarded a credential the new design does not
create. SIGNED — proceed on the no-credential design.

## Gate decision 5 — the `who` policy (John, 2026-08-01)

**Problem.** Criterion 3 requires a commission confirmation to record WHO confirmed.
Anchor's auth is a BARE SHARED SECRET (`paths.auth_ok`) — it proves a token holder
acted, not which person. There is no subject, no user table, no identity.

**DECIDED — record the CLAIMED identity, stamped UNAUTHENTICATED.** The confirmation
receipt carries the supplied name (e.g. `john`) TOGETHER WITH an explicit provenance
stamp marking it claimed-not-authenticated. The plan must never render a claimed `who`
as though it were proven, and must never silently substitute `unattributed`.

**Consequences.** The audit trail is readable and nominally attributed; the honesty
law holds (a claim is labelled a claim, exactly as `unknown` is never rendered as
`empty`). Wave 19's gate report continues to surface criterion 3 as **met under
shared secret**, not fully met — that stays visible, not hidden. Building real subject
identity (accounts/sessions/subjects) is explicitly OUT of this North Star's scope and
would be its own effort.

## Gate decision 6 — real-run budgets (John, 2026-08-02)

**APPROVED — cheap profile for both.** Wave 20 (in-session executor gate,
`exec2-verdict.json`) and Wave 22 (T-HOST-0) may spawn REAL trio-CLI child processes
under the cheap profile.

**Rationale.** Without real runs both gates are stub-satisfiable: an "executor" that
never executes, and a host-independence test that never proves independence. That is
precisely the anti-stub failure class this plan set was hardened to prevent. Tests
still fail closed and must not spend without explicit opt-in.

## Gate decision 7 — Ecgberht is the skill; Anchor is the reference host (John, 2026-08-02)

**ONE SKILL, TWO ENTRY SURFACES** (seal = project, high seat = portfolio) — no split,
per the locked UX intent. **IN-SESSION EXECUTOR BUILT NOW** (not grasscatched): the
skill executes confirmed commissions itself with no Anchor present. **Divergence
mitigation is a condition of that decision** — the in-session executor and Anchor's
executor implement ONE skill-owned handback contract, proven by a SHARED CONFORMANCE
SUITE both must pass (NS v5 criterion 15, Wave 21). Anchor implements host contracts
only; no steward logic in Anchor Python (NS v5 non-goal).
