# NORTH STAR v5 — Ecgberht: a host-independent steward skill

> **LOCKED 2026-08-02 by John.** Supersedes v4 (`NORTH-STAR-v4-superseded.md`).
> Depth FULL · Heavy · cross-family. Anti-drift authority: every element of the
> plan must serve a criterion below. v5 reframes the effort from "an Anchor
> feature" to "a host-independent SKILL that Anchor consumes".

## Statement

A project is stood up, planned across MANY stages, and driven OVER TIME by talking to
its steward — the **Ecgberht foundry skill, a host-independent engine**. **Anchor is
the reference host**: it supplies execution, auth and the browser surfaces, consuming
the skill exactly as it consumes Gandalf — never absorbing it. The steward AUTHORS a
coarse scaffolding (campaign roadmap + Parable-of-the-Oranges prompts), proposed and
batch-confirmed; it ORCHESTRATES stage by stage (reflection → next-stage proposal →
progressive elaboration); it COMMISSIONS researchPrime / Gandalf / Crucible / Foreman
for stage work, never authoring it. Reflections and proposals are typed ledger
artifacts rendered into conversation, never chat that must survive as chat. Every
project publishes a typed attention projection, and the portfolio altitude — reading
the built index — shows live status across ALL projects, coming forward only when a
decision or deliverable needs John. Nothing is spent, written or started without a
human confirmation, and the campaign ledger remains the single source of truth.

## Success criteria

1. A spoken description produces a PROPOSED multi-stage scaffolding (coarse steps +
   Oranges annotations), batch-confirmed; zero chat turns persisted.
2. Scaffolding authoring is LIGHTWEIGHT: one confirmed session ENVELOPE covers compiles
   AND orchestrator-loop reflections; exhaustion hard-stops. No per-sentence confirm.
3. A commission is proposed FOR a named stage showing skill + seat + depth before spend;
   nothing runs until confirmed; the confirmation records `who` (CLAIMED identity,
   stamped unauthenticated).
4. On a validated handback the steward emits a REFLECTION RECEIPT with Oranges prompts
   and PROPOSES the next stage — the immediate emission being ZERO-MODEL and
   ZERO-NETWORK, trap-asserted.
5. PROGRESSIVE ELABORATION: starting a stage triggers targeted questions or an offered
   researchPrime commission — never demanded at scaffold time.
6. One campaign exercises AT LEAST TWO different commissioned skills.
7. Stage artifacts render reviewably; a spoken correction produces a new version through
   propose → confirm.
8. Roadmap status reflects the ACTUAL session state across park, restart and kill.
9. All of it passes with AUTH ON **at the host seams**: the engine exposes an INJECTED
   AUTHORIZER HOOK exercised by these tests; Anchor supplies token enforcement. **The
   engine itself contains no `ANCHOR_TOKEN` logic.**
10. `roadmap_events` has exactly ONE writer, proven by a cross-process concurrency test.
11. CONTINUITY — after a full restart with every context window gone, the steward's
    first message states where the campaign is, derived entirely from the ledger,
    proposes the next step, and asks nothing already recorded. A died-mid-flight run and
    a never-arrived handback are NAMED, never silently absorbed.
12. ATTENTION CONTRACT — every project publishes a typed projection
    (`working | needs_you | deliverable_ready | blocked | idle`) derived READ-ONLY by one
    engine function; the portfolio altitude folds N projections into the raise queue and
    the ⚑ badge WITHOUT writing to any project store.
13. PORTFOLIO AT A GLANCE — the portfolio surface shows every active project's stage and
    progress, answered from the EXISTING index without walking roots; an unreadable
    project reports `unknown`, never a shorter list.
14. **HOST-INDEPENDENCE** — the **T-HOST-0** acceptance test passes on a box with NO
    Anchor service, NO `ANCHOR_TOKEN` and NO Anchor prefs: stand-up, scaffold propose →
    batch-confirm, roadmap, brief, portfolio status across roots, and **a confirmed
    commission that actually EXECUTES via the skill's own IN-SESSION EXECUTOR**, yielding
    a validated handback and a deterministic reflection + next-stage proposal. Seats
    resolve from env families or report honest source `defaults` — never a crash, never a
    hardcoded model id. Where no executor is available at all, the named state
    **`no-executor-host`** is returned — never a silent queue.
15. **ONE CONTRACT, TWO HOSTS** — the skill's in-session executor and Anchor's executor
    implement the SAME durable handback-file contract (SKILL-OWNED spec), proven by a
    SHARED CONFORMANCE SUITE both must pass. Neither implementation may drift from the
    contract, and the contract lives in the skill repo.

## Non-goals

- **No steward logic in Anchor Python** — no proposal/confirm decisions, reflection,
  attention derivation, or roadmap/status law. Anchor implements HOST CONTRACTS ONLY:
  executor, outbox producer, authorizer, UI.
- Do not re-plan or rebuild the portfolio tracking index (BUILT: 19 waves GREEN, 671
  tests, `engine/portfolio/` 32 modules) — CONSUME it.
- Cross-project pause, resource arbitration, portfolio-level commissioning, any
  portfolio WRITE path.
- Changes to Crucible / Foreman / researchPrime internals.
- **Splitting the steward into two skills** — ONE SKILL, TWO ENTRY SURFACES (seal =
  project, high seat = portfolio), per the locked UX intent
  (`Ecgberht/NEXT-UX-AND-ANCHOR-ORCHESTRATION.md`: "two altitudes of the same steward …
  they do not fork a second brain").
- Steward persona/livery, mobile/iPad.
- Adversarial review anywhere in the product loop.

## Risk taxonomy

Carried from v4 (second ledger writer · chat-log persistence · auth-off green ·
unconfirmed spend · status drift · seat family/driver collision · scaffolding mistaken
for a commissioned plan · attention flapping · ambient poll cost · stale packet ·
deliverable provenance · confirmation fatigue), PLUS v5:

- **Two executors DRIFTING** — mitigated by criterion 15's shared conformance suite.
- **In-session process supervision on Windows** (kill semantics, orphan reconcile) is
  genuinely hard and is now owned TWICE.
- **Scope growth** from the in-session executor raising the wave count.

## Prior art this effort MUST build on (verified)

| Artifact | Status |
|---|---|
| `~/.claude/skills/ecgberht` → `C:\dev\Ecgberht` | LIVE registered foundry skill, `SKILL.md`, bare CLI `bin/ecgberht.mjs` |
| Project altitude (E5) | BUILT — Face/Strip, roadmap events, brief, dispatch, commission verbs (56 tests) |
| Portfolio altitude | BUILT — high-seat/rank + `engine/portfolio/` index (671 tests), home `~/.steward/portfolio`, ZERO Anchor dependence |
| `Ecgberht/NEXT-UX-AND-ANCHOR-ORCHESTRATION.md` | John's LOCKED UX intent — §A seal, §B high seat |
| Anchor consumer precedent | `Anchor/gandalf.py` — how Anchor consumes a foundry skill |
