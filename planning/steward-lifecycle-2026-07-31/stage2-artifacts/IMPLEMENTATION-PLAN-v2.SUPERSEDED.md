# IMPLEMENTATION PLAN v2 — Anchor steward: campaign orchestration by conversation (Foreman-ready)

test-command: node scripts/run-all-tests.mjs

> **AUTHORITY.** This document is the AUTHORITATIVE Stage-2 build input. It supersedes
> `BEST-DRAFT.md` (18 waves) and the stale `wave-decomposition.json` (17 waves).
> `wave-decomposition-v2.json` is GENERATED from this document and must agree exactly;
> the mechanical equivalence check (Wave 1 deliverable `scripts/check-decomposition-equivalence.mjs`,
> test id `T-EQUIV-01`) fails the build loudly on any divergence in wave count, wave ids,
> titles, done-whens, dependency edges, or gate semantics. If the two ever disagree,
> THIS FILE wins and the build STOPS until the JSON is regenerated.
>
> **Corrected per the 13-item must-fix set (2026-08-01)** — see `../FIXES-APPLIED.md`.
> Reviews applied: `../REVIEW-CONSISTENCY.md`, `../REVIEW-HARDENING.md`, and the ten
> residual BLOCKERs in `OPEN-FINDINGS.json` (disposition table below).

**North Star:** NORTH STAR v4 LOCKED 2026-07-31 by John — `C:/dev/Anchor/planning/steward-lifecycle-2026-07-31/NORTH-STAR.md` is the anti-drift authority. **Master Plan:** `MASTER-PLAN-v2.md` (Stage-1 APPROVED). **Fact base:** `INTAKE.md`. **Gate decisions:** `STAGE1-APPROVAL.md` decisions 1–5 plus the SIGNED Descope D-1 (decision 4, 2026-08-01, governs criterion 4; decision 5, 2026-08-01, governs the `who` policy — claimed identity stamped `claimed_unauthenticated`; D-1 SIGNED 2026-08-01 — the no-credential handback-file design proceeds).

## Wave map (19 waves; renumbered from the 18-wave draft)

| v2 wave | Title | Was (draft) |
|---|---|---|
| 1 | Ground truth I — durability law, auth substrate gate, fences, A3 fix, equivalence check | 1 |
| 2 | Vertical slice (FIXTURE-ONLY) | 2 |
| 3 | Ground truth II — audits + fix-item ledger (A5 ingest outcome PRE-DECIDED) | 3 |
| 4 | BUILD-E — anti-stub executor, durable handback files, boot reconcile, G4 verdict | 4 |
| 5 | Decision records, spikes, cost model, skills table, SC6 feasibility verdict | 5 |
| 6 | Ledger spine — one writer IN PRODUCTION (live-writer migration), event-kind allow-list | 6 |
| 7 | Commission dossier — confirm journal (ONE mechanism), containment | 7 |
| 8 | Session envelope (moved BEFORE authoring — no pre-envelope spend) | 9 |
| 9 | Scaffolding authoring — dialogue → step_create, batch confirm (hash-bound) | 8 |
| 10 | Face compile projection (RESTORED — Master Plan P4) | — (new) |
| 11 | Commission proposal in Anchor — seats law, table-bound skills, G4+SC6 preconditions | 10 |
| 12 | Progressive elaboration | 11 |
| 13 | Session-state truth + hardened launch truth (RESTORED — Master Plan P6: outbox, status_flip, leases, gate-surfacing) | 12 |
| 14 | Handback validation, deterministic reflection + proposal (gate decision 4), multi-skill proof | 13 |
| 15 | Rehydration + the ONE boot/open-project pipeline (RESTORED — Master Plan P7: seen-receipt, heal-before-brief) | 14 |
| 16 | Attention contract — publish call sites named, raise tiers revived (RESTORED — Master Plan P9) | 15 |
| 17 | High Seat fold + THE BADGE PATH BOUNDED — portfolio at a glance | 16 |
| 18 | Chamber UI (+ I52 scaffold-exemption renderer test — Master Plan P10) | 17 |
| 19 | Wave-0 kill gate (DEGRADED cannot green criterion 13 without a signed decision) | 18 |

## Success criteria (restated; full text in NORTH-STAR.md)

- 1. Spoken description → PROPOSED multi-stage scaffolding (coarse steps + Oranges annotations), batch-confirmed; zero chat turns persisted.
- 2. Scaffolding authoring LIGHTWEIGHT: one confirmed session ENVELOPE covers compiles AND orchestrator-loop reflections (each shown; exhaustion hard-stops). No per-sentence confirmation dialog.
- 3. Commission proposed FOR a named stage showing skill + seat + depth before spend; nothing runs until John confirms; confirmation records who.
- 4. On a validated handback the steward emits a REFLECTION RECEIPT with Oranges prompts and PROPOSES the next stage through propose → confirm. **Implemented per STAGE1-APPROVAL gate decision 4 (John, 2026-08-01): on a validated handback the steward IMMEDIATELY emits a ZERO-MODEL, ZERO-SPEND reflection receipt AND a ZERO-MODEL next-stage proposal, both deterministically rendered from ledger facts (the `assembleBriefPacket` / narration-floor pattern). The richer, model-authored reflection narrative compiles at next session open inside the confirmed envelope. Criterion 4 is met LITERALLY at handback time — no NS amendment, no emitted/queued split of the criterion's obligations. The draft's self-authored split is REMOVED.**
- 5. PROGRESSIVE ELABORATION: starting a stage triggers targeted questions or offered researchPrime commission — never demanded at scaffold time.
- 6. One campaign exercises AT LEAST TWO different commissioned skills (early feasibility verdict at Wave 5 — see SC6 gate).
- 7. Stage artifacts render reviewably; spoken correction → new version through propose→confirm.
- 8. Roadmap status reflects ACTUAL session state across park, restart, kill.
- 9. All of it passes with AUTH ON, asserted on outcomes rather than plumbing — and AUTH-ON CANNOT BE VACUOUS: the suite preflight ASSERTS `expected_token()` is non-None and the auth pillar flag is `enforce` before any test counts (closes the `paths.py:398–416` silent fallback where an unset `ANCHOR_TOKEN` makes `auth_ok()` return True). Auth is REVALIDATED at every spend/write seam (confirm, launch, debit) with negative tests.
- 10. roadmap_events has exactly ONE writer IN PRODUCTION, proven by a separate-OS-process concurrency test including a kill-mid-write case — and proven by the retirement/migration of every live writer call site enumerated in Wave 6.
- 11. CONTINUITY: full restart with every context gone → first message states campaign state from ledger only; no re-ask; dead run + missing handback NAMED. The boot pipeline (Wave 15) mandates reconcile → ingest → publish → compose ORDER so "entirely from the ledger" and "dead run named" are simultaneously true.
- 12. ALTITUDE CONTRACT: typed attention projection (working|needs_you|deliverable_ready|blocked|idle) from one pure read-only function; High Seat fold write_authority none; badge within one poll; zero ambient beyond badge. **`unknown` enum resolution (closes the twice-flagged MAJOR): the five-state enum is the complete set of PUBLISHED projection states — `deriveAttention` over a readable ledger always returns one of the five. `unknown` is NOT a sixth projection state; it is the READ-SIDE honest answer (criterion 13's own word) when a project's store or projection CANNOT BE READ. No NS amendment required.**
- 13. PORTFOLIO AT A GLANCE from EXISTING portfolio index (no root walk); unreadable → unknown row, never silently shorter list. **DEGRADED fields CANNOT green the criterion-13 kill gate without an explicit signed decision from John (Wave 19).**
- GATE DECISIONS: (1) unattended MODEL spend never occurs — only the NL-polish reflection compile queues; the receipt AND the deterministic next-stage proposal always emit at handback (decision 4); (2) A5 audit not re-plan, field-by-field coverage matrix with capped fix budget — with the DERIVED-ingest probe outcome PRE-DECIDED (see Wave 3) so the cap cannot blow on a fact the code already states; (3) briefCacheStale FIXED in Wave 1 under the named-fix diff fence, staleness key = last event seq/hash + Face version (content-anchored, not counts); (4) G4 FAIL is an explicit HALT — `g4-verdict.json` mechanically blocks Waves 11–19; PASS is ANTI-STUB (trio-CLI cmdline evidence + `receipt-validate` pass + `(pid, proc_create_time)` identity); (5) the attention publish seam is named, WITH its mandatory call sites (Wave 16 table); (6) commissionable skills from a machine-readable intersection table generated by ONE pure function, with an EARLY SC6 feasibility verdict at Wave 5; (7) early vertical slice fixture-only; (8) audits/spikes in parallel lanes.
- NON-GOALS: no portfolio-index rebuild; no High Seat WRITE; no Crucible/Foreman/researchPrime internals; no adversarial review in product loop; no unattended spend; refuted e-1/e-4 stay dead (no new handback artifact channel — the durable handback FILE of Wave 4 is the delivery of the EXISTING bundle/receipt over the existing channel, made restart-safe, not a new artifact channel; no bind-and-derive rebuild — Wave 13 binds to the EXISTING `roadmap.mjs buildRoadmapProjection`).
- BUILD-vs-WIRE: Ecgberht propose/confirm/bind, packet-view, receipt-validate, brief.assembleBriefPacket, high-seat, rank, engine/portfolio/* are BUILT — wire/audit/fix. MISSING: Anchor commission executor (.py), dialogue→step_create, attention emitters, deliverable_ready state, chamber UI steps/proposal/confirm/artifact, the durable handback-file protocol, the outbox/mediator, the Face compiler.
- HARDENING: every asserted property emits a mechanical gate; every surface wave has a failure-state table with unknown≠empty; durability obligations are PER STORE INSTANCE (see the Durable-store obligations map) — each new durable store carries a NAMED atomic write, a NAMED lock/serialization, and a NAMED concurrency test id. An unmapped store or checkbox is a BLOCKER.

## BUILD CONTRACT (cross-repo — names what Foreman needs to execute at all)

- **Build root:** `C:\dev\Ecgberht`. `test-command: node scripts/run-all-tests.mjs` resolves there (verified: `C:\dev\Ecgberht\scripts\run-all-tests.mjs` exists; Anchor has no `scripts/`). The plan document lives in the Anchor repo; the BUILD runs from the Ecgberht root.
- **Cross-repo test runner:** `run-all-tests.mjs` is extended (Wave 1) with a pytest bridge: when a wave's manifest lists Anchor-side paths, the runner additionally invokes `python -m pytest <wave test paths>` with cwd `C:\dev\Anchor` and folds the result into the single pass/fail. One command, both ecosystems.
- **Per-wave commit repo:** each wave's manifest declares `repos: ["ecgberht"] | ["anchor"] | ["ecgberht","anchor"]`; the runner commits EVERY listed repo per wave with the wave tag. Primary repo by wave: Ecgberht — 1, 2, 3, 6, 7, 8, 9, 10, 12, 14, 15, 16; Anchor — 4, 13 (Python outbox side + executor), 17 (badge endpoint + `static/high-seat.js` wiring), 18 (chamber UI); both — 5, 11, 19.
- **Endpoints:** every new `/api/ecgberht/*` (or other) endpoint ships its `route_table.py` row AND the reviewed `OPEN_ROUTES.json` entry in the same wave — the default-deny gate (the live `open` set must equal `OPEN_ROUTES.json`) must pass. Waves 15–18 are MODIFY/EXTEND of the named existing files (`route_table.py:239–261`, `anchor_gui.py:10360–10701`, `static/high-seat.js`) — never greenfield rebuilds that collide with `tests/test_rearch_2026_07.py`.
- **Real-run tests are wave-local gate scripts**, EXCLUDED from the standing suite (Foreman's EXECUTE→REVIEW→FIX loop re-runs gates repeatedly; a real trio run in the standing suite poisons every later wave). Waves 4, 13, 14, 19 name their real-run gates `gate/<wave>-real-run.mjs` and use the named CHEAP COMMISSION PROFILE (a LITE researchPrime run, smallest depth) for repeatability. Stage-2 approval itself authorizes the named real-run budgets of Waves 4, 5, 13, 14, 19 — stated here so the builder does not violate the spend invariant it is building.
- **Token provisioning:** the auth-ON suite bootstrap (Wave 1) MINTS an ephemeral `ANCHOR_TOKEN` for the run, sets the auth pillar to `enforce`, and asserts both before any test counts. No developer secret required on a fresh box/worktree.

## Schedule, lanes, and the PRE-SPINE FIXTURE-ONLY rule

`Depends on:` encodes the machine-checkable DAG — edges are COMPLETE (every artifact a wave imports appears as an edge; closes BLOCKER `dag-depends-incomplete`). A single-lane run follows wave order and violates nothing.

| Lane | Waves | Gate into the next lane |
|---|---|---|
| **A — substrate (critical path)** | 1 → 3 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18 → 19 | each wave's done-when |
| **B — proving slice (off path)** | 2 (fixture-only) | informs Waves 9–14 shape; ships nothing durable |
| **C — executor + substrate verdict (off path, joins at 11)** | 4 | `g4-verdict.json` verdict=PASS (anti-stub) — mechanically blocks Waves 11–19 |
| **D — decision records + spikes (off path, joins at 8/9/11/18; requires C's evidence)** | 5 | decision records + `commissionable-skills.json` + `sc6-feasibility.json` (count≥2 or HALT) |

**PRE-SPINE FIXTURE-ONLY RULE (normative, unchanged in force).** Any wave exercising campaign behaviour before the spine (Wave 6) — today Wave 2 only — runs against a temp-directory fixture ledger and MUST NOT write a durable `roadmap_events` record, mint a real `job_id`, or spend: (a) fixture handle injected, module guard throws on durable-path resolution; (b) CI hashes the real `roadmap_events` before/after the slice suite and FAILS on any difference; (c) the slice executor is a labelled STUB refusing unconfirmed commissions. Slice assertions re-point at the real spine in Waves 9–14; the fixture suite is retained as regression harness, never as proof of criteria 1–4.

## Durable-store obligations map (per INSTANCE — closes the "PASS per property class" hole)

Every durable store this plan introduces or touches, each with its OWN named atomic write, named lock/serialization, and named concurrency test. The hardening gate is earned per row, not per property class. An asserted store absent from this table is a BLOCKER.

| # | Store | Sole writer (production) | Atomic write (named) | Lock / serialization (named) | Concurrency test id | Wave |
|---|---|---|---|---|---|---|
| S1 | `roadmap_events` (per-project, inside `roadmap.json`) | Wave-6 spine (`appendRoadmapEventDurable` path made live) | `writeFileAtomicSync` (`durable-write.mjs`) | `withFileLock` (`durable-write.mjs:191`) | T-DUR-S1: N separate OS processes × M appends, zero torn/lost/dup, total order, PLUS kill-writer-mid-append crash case; FAILS if lock or atomic write removed | 6 |
| S2 | Strip receipts + instruments | spine (via `write-authority.mjs` durable path `:327/:348` made live) | `writeFileAtomicSync` | `withFileLock` | T-DUR-S2: two-process receipt append hammer | 6 |
| S3 | Commission dossier | dossier module, a spine caller | `writeFileAtomicSync` | `withFileLock` | T-DUR-S3 two-process; T-ATOM-CONFIRM kill-between-writes (confirm journal) | 7 |
| S4 | Session-envelope ledger | envelope module, a spine caller | `writeFileAtomicSync` | `withFileLock` | T-DUR-S4: two OS processes racing a debit; exactly one succeeds past the bound | 8 |
| S5 | `face_events` + content-hashed `source_text` blobs | Face compiler, a spine caller (blobs write-once by content hash) | `writeFileAtomicSync` | `withFileLock`; blobs immutable-by-hash (documented serialization) | T-DUR-S5: concurrent compile attempts; byte-identical projection | 10 |
| S6 | Durable handback FILE + terminal marker (in the run's worktree) | the commissioned run's wrapper (single writer per run, by construction) | temp + fsync + rename inside the wrapper | one writer per run dir (documented serialization) | T-DUR-S6: kill-mid-write → marker absent → NOT ingested; complete pair → ingested exactly once | 4 |
| S7 | Handback quarantine store | handback ingester, a spine caller | `writeFileAtomicSync` | `withFileLock` | T-DUR-S7: duplicate delivery from two processes → one quarantine entry | 14 |
| S8 | `artifacts/g4-evidence.json`, `artifacts/halt-inventory.json`, DERIVED `artifacts/commissionable-skills.json`, `artifacts/sc6-feasibility.json` | one writer each; skills table + feasibility DERIVED by ONE pure generator function (kills the dual-writer shape) | `writeFileAtomicSync` | `withFileLock` | T-DUR-S8: regenerate twice → byte-identical; two-process regen race safe | 4, 5 |
| S9 | Typed `attention` cell + portfolio-index ingest | `publishAttention` (spine caller); index side already uses `withFileLock`/`updateJsonSync` | `writeFileAtomicSync` | `withFileLock` | T-DUR-S9: two-process publish of same edge → one event (edge-only idempotence) | 16 |
| S10 | Fix-item ledger + `artifacts/degraded.json` (append-only) | Wave-3 harness / gate reporters | `writeFileAtomicSync` | `withFileLock` | T-DUR-S10: concurrent append preserves rows | 3 |
| S11 | Brief cache | `precomputeBriefCache`/`writeBriefCache` | FIX: `writeFileAtomicSync` (today bare `fs.writeFileSync`, `brief.mjs:902`, despite importing the helper) | corrupt-reads-as-absent semantics retained (`brief.mjs:910–924`), documented | T-DUR-S11: torn write injected → cache read as absent, never garbage served | 1 |
| S12 | Python-side fsync'd OUTBOX (monotonic seq) | Anchor executor process (single appender per run) | `_atomic_replace` bounded-retry pattern (reuse `session_registry.py:539–559`) + fsync | monotonic sequence + idempotent acknowledged drain by the Node mediator | T-DUR-S12: kill-the-mediator convergence test; Windows sharing-violation retry exercised | 13 |
| S13 | Queued NL-polish reflection compiles | none of their own — typed events IN `roadmap_events` via the spine (inherit S1) | S1 | S1 | T-DUR-S1 covers | 14 |

## Property-gate obligation map (checkbox → owning wave → deliverable → test id)

| Property | Gate checkbox | Owning wave(s) | Deliverable | Test id(s) |
|---|---|---|---|---|
| durability | atomic write (temp + fsync + rename) | per-store (map above) | named helper per store row | T-DUR-S1…S13 |
| durability | lock / documented serialization | per-store (map above) | named lock per store row | T-DUR-S1…S13 |
| durability | a concurrency test | per-store (map above) | separate-OS-process hammers + kill-mid-write | T-DUR-S1…S13 |
| honesty | a failure-state table | 2,4,6,7,8,9,10,11,12,13,14,15,16,17,18 | per-wave table (below) | each wave's done-when |
| honesty | unknown and empty as SEPARATE rows | every surface table | five-state+unknown tables | T-HON-17, T-HON-18 |
| idempotence | a repeat-invocation test | 6,8,9,11,14,16 | `client_event_id` primitive + double-submit tests | T-IDEM-06/08/09/11/14/16 |
| boundedness | numeric bound named | 6,8,17 | `ROADMAP_EVENTS_MAX=50000`; `ENVELOPE_MAX_SPEND_USD=5.00`, `ENVELOPE_MAX_COMPILES=25`, `ENVELOPE_TTL_MINUTES=240`; `PORTFOLIO_MAX_ROWS=500` | T-BND-06/08/17 |
| boundedness | refusal path when exceeded | 6,8,17 | `events-bound-exceeded`; `envelope-exhausted`/`envelope-expired`; `portfolio-bound-exceeded` | T-BND-06/08/17 |
| containment | escape-attempt test (`..`, absolute, symlink/junction) | 7, 18 | dossier/handback/artifact resolver; chamber artifact read | T-CON-07, T-CON-18 (+ long-path MAX_PATH case in T-CON-07) |

## Commissionable-skill intersection (machine-readable, ONE generator, test-bound)

`artifacts/commissionable-skills.json` — one row per candidate skill: `{ skill, executor_proven, executor_evidence:{pid, proc_create_time, handback_id}|null, halt_class: "EXTERNALLY-OBSERVABLE"|"REQUIRES-TRIO-CHANGE"|"INVISIBLE", excluded_reason, commissionable }`.

- INPUTS (one writer each): `artifacts/g4-evidence.json` (Wave 4, observed evidence only) and `artifacts/halt-inventory.json` (Wave 5's G5 classification — which MUST absorb the documented gated-lane fragility, `job_runner.py:574–578`, into the class of any skill whose commission path rides a gated lane).
- The table is DERIVED by one checked-in pure function `deriveCommissionableSkills(g4Evidence, haltInventory)` with a unit test; `commissionable === (executor_proven && halt_class === "EXTERNALLY-OBSERVABLE")`. Never hand-edited (closes the dual-writer finding).
- **EARLY SC6 FEASIBILITY VERDICT (closes BLOCKER `empty-goals-intersection`):** Wave 5's done-when includes emitting `artifacts/sc6-feasibility.json { commissionable_count, verdict: "FEASIBLE"|"HALT" }`; `commissionable_count < 2` HALTs the effort for John's North-Star/non-goal decision BEFORE Waves 6–13 spend the bulk of the build. Wave 11's precondition test imports BOTH `g4-verdict.json` and `sc6-feasibility.json`.
- Consumers TEST-BOUND: Waves 14 and 19 select only `commissionable: true` rows; `< 2` rows HALTs, never substitutes, never downgrades criterion 6.

## Attention projection publish seam (criteria 12 AND 13 simultaneously)

| Seam element | Exact mechanism | Owning wave |
|---|---|---|
| **Derivation** | `deriveAttention(ledgerView) -> { state, state_since, reason, provenance }` — ONE pure engine function; zero writes, zero model calls, zero I/O beyond the passed view; write-trap test. Over a READABLE ledger it always returns one of the five NS states — `unknown` is the read-side answer for an unreadable store, never a sixth published state. | 16 |
| **Publish writer** | `publishAttention()` — the ONLY code persisting a projection, a CALLER of the Wave-6 spine. | 16 |
| **Mandatory call sites** | the Wave-16 CALL-SITE TABLE — every state-transition edge names its publishing call site with a removal-proof test; the High Seat NEVER publishes (closes BLOCKER `publishattention-trigger-unspecified`). | 16 |
| **Event** | `attention_projection_published { state, state_since, derived_from_event_seq, bundle_hash? }` — edge-only; no-change republish appends nothing. | 16 |
| **Published cell** | typed `attention` cell written in the SAME journaled transaction as the event. | 16 |
| **Index delivery** | DERIVED ingest via `engine/portfolio/anchor-contract.mjs` (`ingestAck`, `:395`) — expected NEEDS-WIRE per the Wave-3 probe (the seam is an in-process ES-module function with no bridge exposure; `C7B_STATUS.open: true`); the bridge deliverable is Wave 16 scope, planned, not an afterthought. The project PUSHES; the index never walks. | 3 (probe) → 16 (wire) |
| **Read API** | `engine/portfolio/query.mjs` no-walk read returning `{ project, stage, runs{live,waiting,blocked}, last_movement, attention }`. | 17 |
| **High Seat** | folds N rows with `write_authority:'none'` PROVEN by an `indexOnlyFs`-style read trap (the string field at `high-seat.mjs:752` is a declaration, not enforcement — the trap and the byte-identity test are the enforcement). | 17 |

## Residual-findings disposition (OPEN-FINDINGS.json — all 10 BLOCKERs closed or explicitly deferred)

| Finding | Disposition |
|---|---|
| `dag-depends-incomplete` | RESOLVED — every wave's `Depends on:` now lists every wave whose artifact it imports (see waves; e.g. 8→5, 9→5/8, 11→4/5/7/9, 14→4/5/7/13). |
| `publishattention-trigger-unspecified` | RESOLVED — Wave 16 call-site table + removal-proof tests; High Seat never publishes. |
| `atomicity-confirm-cross-store-underspecified` | RESOLVED — ONE mechanism chosen: the CONFIRM JOURNAL two-phase apply with boot repair (Wave 7). "Or" is forbidden in the done-when. |
| `empty-goals-intersection` (SC6 feasibility) | RESOLVED — `sc6-feasibility.json` verdict at Wave 5 done-when; `< 2` HALTs before Wave 6+ spend; Wave 11 precondition imports it. |
| `cold-ledger-observed-only-race` | RESOLVED — Wave 15's `openProjectPipeline` mandates reconcile → durable status events → ingest pending handbacks → publishAttention → compose, kill-between-stages tested; the composer reads only the post-reconcile ledger. |
| `can-degraded-fields-gate-green` | RESOLVED — Wave 19 FAILS (HALT) if any criterion-13 field ships DEGRADED, unless an explicit SIGNED scope decision from John exists in `artifacts/degraded.json`. Naming a shortfall no longer discharges SC13. |
| `criterion-deferred-next-proposal` | RESOLVED — by John's gate decision 4 (STAGE1-APPROVAL.md): deterministic zero-model receipt + proposal AT handback; rich compile at next open. Implemented in Wave 14. |
| `confirm-content-proposal-unbound` (TOCTOU) | RESOLVED — every confirm verb (batch scaffold, envelope, commission, correction) requires the payload to carry the CONTENT HASH of the rendered proposal; mismatch → named `confirm-hash-mismatch` refusal, zero launch/append/debit; post-render-mutation tests in Waves 8, 9, 11, 18. |
| `secret-shared-unattributed-who` | RESOLVED — by John's GATE DECISION 5 (STAGE1-APPROVAL.md, 2026-08-01): record the CLAIMED identity, stamped UNAUTHENTICATED. Every confirmation receipt carries `who: { claimed: "<supplied name>", provenance: "claimed_unauthenticated" }` — the supplied name (e.g. `john`) together with the explicit provenance stamp. A claimed `who` is NEVER rendered as though proven and `unattributed` is NEVER silently substituted (the same honesty law as unknown-is-never-rendered-as-empty); credential CLASS still recorded; the machine gate still proves token presence + enforce mode. Wave 19's gate report still names criterion 3 as met-under-shared-secret — that visibility is unchanged. Building real subject identity (accounts/sessions/subjects) is explicitly OUT of this North Star's scope (its own future effort, not a TODO here). |
| `auth-revalidated-spend` | RESOLVED — revoked/expired/wrong-principal negative tests AT the confirm, launch and debit seams are done-when clauses of Waves 4, 8, 11; Wave 19's sweep asserts the refusals on outcomes (zero pid / zero append / zero debit). |

**Twice-flagged MAJOR (`unknown` enum):** resolved by the criterion-12 read-side interpretation above — no NS amendment. **MAJOR `after-attention-external-kill-republished` (stale badge):** covered by Wave 13's reconciler publishing on death edges + Wave 15's boot pipeline.

## Descope record (no silent drops)

| # | Descoped item | What is lost | Criterion weakened | Rationale | Status |
|---|---|---|---|---|---|
| D-1 | Master-Plan P6 **run-scoped capability minting** (single-purpose, revocable, TTL-bounded capability handed to the commissioned run; never argv/env) | A commissioned run holds no revocable write credential | 3 (defense-in-depth on the write-back path) | The Wave-4 durable handback-FILE protocol removes the need for the child to hold ANY Anchor credential: the run writes its handback + terminal marker into its own worktree; Anchor's boot reconcile INGESTS and validates. No secret crosses argv/env because no secret is passed at all. The redaction/no-capability-in-artifacts test is kept in spirit as a no-token-in-child-env test (Wave 4). | **SIGNED by John 2026-08-01** (STAGE1-APPROVAL.md "Descope D-1 — SIGNED"): a credential that never exists cannot leak, expire mid-run, or be replayed; the handback-file protocol is also what lets commissioned runs survive an `nssm restart`. Proceed on the no-credential design. |

All other clusters the audit found lost are SCHEDULED, not descoped: P4 → Wave 10; P6 intent records/launch truth/outbox/`status_flip`/gate-surfacing → Waves 4 + 13; P7 seen-receipt/heal-before-brief → Wave 15; P9 raise-tier revivals → Wave 16; P10 I52 renderer test → Wave 18; P2 versioned event-kind allow-list → Wave 6; INTAKE invariant 4 `resolveSeats` → Wave 11.

---

## Wave 1 — Ground truth I — durability law, auth substrate gate, fences, A3 fix, equivalence check

**Intent:** Establish the non-negotiable substrate before any feature code: a proven storage primitive on the target box, an auth-ON suite that CANNOT be vacuously green, CI fences, the A3 defect fixed with a content-anchored key, and the plan/JSON equivalence check that keeps the build inputs from diverging again.

**Serves:** 9, 10; precondition for all.

**Deliverables:** Storage-primitive hammer test on the TARGET box: N concurrent appenders x M records asserting zero torn/lost/duplicated records, and the hammer RECORDS machine + concurrent-load evidence (scanner/sync process list captured during the run) in its artifact — an idle-box green does not satisfy the environmental claim; FAIL branch is a HALT for a storage decision (SQLite WAL is the candidate, but an architecture swap is John's call, never a silent escalation inside a ground-truth wave — it collides with the stdlib-only posture); Durability in hardening-law form PER STORE per the Durable-store obligations map: named atomic write helper + named lock helper (`withFileLock`, `durable-write.mjs:191`) + removal-proof concurrency test; AUTH SUBSTRATE GATE: suite bootstrap mints an ephemeral ANCHOR_TOKEN, sets the auth pillar to enforce, and a preflight assertion FAILS the whole suite if `expected_token()` is None or the flag is not enforce (closes the `paths.py:398-416` silent auth-off fallback); negative auth tests (absent / expired / wrong-principal / revoked) first-class; CI guard fails the build on any bypass flag; CI diff guard: build fails on any modification under the Crucible, Foreman or researchPrime trees, or under Ecgberht/planning/steward-tracking-2026-07 and engine/portfolio/ beyond the named-fix allow-list — the grep spans BOTH repos including Python and `scripts/`; A3 FIX in engine/brief.mjs: `briefCacheStale` staleness key extended to LAST ROADMAP EVENT SEQ/HASH + Face VERSION (content-anchored — counts are a weak key: a healed/replaced-in-place roadmap preserves count; the regression test includes a count-preserving mutation), entered on the diff-fence allow-list; S11 fix: `writeBriefCache` uses `writeFileAtomicSync` (T-DUR-S11); Cross-repo test runner bridge (BUILD CONTRACT): `run-all-tests.mjs` gains the pytest bridge + per-wave repo manifest handling; EQUIVALENCE CHECK `scripts/check-decomposition-equivalence.mjs` (T-EQUIV-01): parses IMPLEMENTATION-PLAN-v2.md and wave-decomposition-v2.json and FAILS loudly on any divergence in wave count, ids, titles, done-whens, depends-on edges, or gate semantics; wired into CI

**Depends on:** —

**done-when:** The concurrency hammer (with load evidence), the removal-proof durability test, the auth preflight + negative tests, the A3 content-anchored staleness regression (including a count-preserving mutation), the atomic brief-cache fix, the cross-repo runner bridge, and T-EQUIV-01 are all green in one auth-ON suite whose preflight proves auth is really enforced, and the CI diff guard fails a deliberate out-of-fence edit while passing the named A3 fix.

- **Given** `ANCHOR_TOKEN` unset or the auth pillar not in enforce, **when** the suite starts, **then** the preflight FAILS the entire run before any test counts — an auth-off green is structurally impossible
- **Given** A roadmap healed in place so its event COUNT is unchanged, **when** `assembleBriefPacket` is called against a cached packet, **then** `briefCacheStale` reports stale (seq/hash key) and a fresh packet is assembled
- **Given** wave-decomposition-v2.json diverging from this plan in any wave id, title, done-when or dependency edge, **when** CI runs T-EQUIV-01, **then** the build fails naming the divergent field
- **Given** The atomic-write helper or the lock helper deleted from any mapped store's durability path, **when** that store's T-DUR test runs on the target box under recorded load, **then** the test fails loudly

## Wave 2 — Vertical slice (FIXTURE-ONLY) — describe → propose → batch-confirm → commission → handback → reflection

**Intent:** Prove the SHAPE of criteria 1–4 end to end in one narrow fixture-only slice before the spine, executor or UI exists — including the gate-decision-4 shape: receipt AND deterministic next-stage proposal emitted at handback.

**Serves:** shape-of-1–4 (non-crediting, gate decision 7).

**Deliverables:** Fixture ledger harness (temp-directory typed-event store, injected, never resolved from the real root); FIXTURE-ONLY enforcement (module guard throws on durable-path resolution; CI before/after hash of the real roadmap_events); End-to-end slice: typed NL description -> compiled coarse scaffolding with Oranges annotations -> ONE batch confirmation with who -> commission PROPOSAL rendering skill + seat + depth -> STUB executor returning a canned validated handback -> a deterministically EMITTED reflection receipt AND a deterministically EMITTED zero-model next-stage proposal (gate decision 4 shape — no queued-proposal split); Zero-chat-persistence assertion; Stub-executor honesty (NAMED as stub in every artifact; refuses unconfirmed commissions; can never be read as the G4 verdict); Slice findings as a checked-in shape report feeding Waves 9–14; Failure states (fixture-internal, prose): compile-failed / confirm-refused / stub-handback-invalid / reflection-blocked, unknown distinct from empty

**Depends on:** Wave 1

**done-when:** The full describe → propose → batch-confirm → commission → handback → reflection-receipt-plus-deterministic-proposal loop runs green over the fixture ledger under auth ON, with zero durable roadmap_events writes proven by the before/after hash test and zero spend outside a stub.

- **Given** A typed NL description on a fixture project, **when** the slice runs to a canned validated handback, **then** a proposed scaffolding, a batch confirmation recording who, a commission proposal, an emitted reflection receipt AND an emitted deterministic next-stage proposal all exist as typed fixture events, and no chat turn is persisted
- **Given** The real project store, **when** the slice suite completes, **then** roadmap_events is byte-identical before and after, and resolving the durable path from slice code throws at import time
- **Given** The stub executor handed an unconfirmed commission, **when** invoked, **then** it refuses, and every artifact it produces is labelled STUB

## Wave 3 — Ground truth II — A1/A2/A4/A5 audit harnesses and the fix-item ledger (A5 ingest outcome PRE-DECIDED)

**Intent:** Prove empirically what INTAKE asserts about the BUILT halves — audits, never re-plans — with the one outcome the code has already decided PRE-DECIDED so the fix-item cap cannot blow on a scripted surprise.

**Serves:** 3, 10, 11, 13.

**Deliverables:** A1 commission-half wiring audit harness (proposeCommission :141 / confirmCommission :250 / verbCommissionPropose :769 / verbCommissionConfirm :836 → checked-in seam table); A2 assembleBriefPacket coverage harness (real campaign fixture incl. one dead run, Q1-Q12 → coverage table marking ANSWERED vs NEEDS-DOSSIER-JOIN); A4 non-atomic confirm-pair defect harness (kill-between-writes probe over job-lifecycle.mjs:929-944; defect row; fix = Wave 7 confirm journal); A5 portfolio-index liveness audit (index home resolves, snapshot rebuilds, steward query answers no-walk, anchor-contract reachable) — with the DERIVED-INGEST PROBE OUTCOME PRE-DECIDED: `appendRoadmapEventDurable` (roadmap.mjs:791) and the write-authority durable paths (:327/:348) have ZERO production callers; every live verb persists via bare `writeProjectRoadmap`/`writeFileAtomicSync` with no lock — so the probe CONFIRMS the known FAIL, the verb migration is ALREADY SCHEDULED as Wave-6 scope (not an A5 fix item, not counted against the cap), and no HALT fires for this known fact; A5 FIELD-BY-FIELD COVERAGE MATRIX: one row per criterion-13 field (stage / runs.live / runs.waiting / runs.blocked / last_movement) per real project, ANSWERED | PARTIAL | ABSENT with answering index key + per-field no_walk observation — the checked-in input Wave 17 is built against; A5 attention-delivery probe: expected NEEDS-WIRE (`ingestAck` is in-process only, C7B open) — recorded, wired in Wave 16; CAPPED FIX-ITEM BUDGET for RESIDUAL findings only (max 6 items / 2 waves; overflow → DEGRADED list + HALT for John — but see Wave 19: DEGRADED cannot green criterion 13 without John's signature); Single checked-in FIX-ITEM LEDGER (S10 durability triple, T-DUR-S10)

**Depends on:** Wave 1

**done-when:** All four audit harnesses run green under auth ON against real fixtures, the A5 field matrix covers every criterion-13 field for every real project, the DERIVED-ingest probe confirms the pre-decided FAIL with the migration pointed at Wave 6 rather than the cap, and every residual gap is either a capped fix item with an owning wave or a named DEGRADED row with a HALT raised — with no rebuild of the portfolio index.

- **Given** A real campaign fixture containing one dead run, **when** the A2 harness drives Q1-Q12 with zero model calls, **then** each continuity fact is marked ANSWERED or NEEDS-DOSSIER-JOIN and none is reported answered when the packet returns honest-unknown
- **Given** The live portfolio index, **when** the A5 audit performs a live write, **then** the DERIVED-ingest probe records the pre-decided FAIL (durable path has no production callers), the verb migration is confirmed as Wave-6 scope, and NO cap-blowing HALT fires for it
- **Given** A confirmed commission interrupted between writeProjectRoadmap and the Strip write, **when** the A4 probe restarts, **then** the orphaned bind is demonstrated with file:line evidence and the defect row points at Wave 7
- **Given** The real portfolio, **when** the field matrix is emitted, **then** every project has a row per criterion-13 field with its answering key, and only RESIDUAL findings count against the 6-item cap

## Wave 4 — BUILD-E — anti-stub executor, durable handback files, boot reconcile, G4 verdict

**Intent:** Build the verified-ABSENT Anchor half so it CANNOT be stubbed green and CANNOT lose a handback to a service restart: a minimal executor driving a real trio run through `job_runner.py`, a durable handback-FILE protocol replacing stdout-tethered completion, a boot reconcile that adopts or honestly fails orphaned runs, and the machine-readable G4 verdict earned only by anti-stub evidence.

**Serves:** 3, 6, 8, 9, 11.

**Deliverables:** Minimal Anchor commission executor (.py): CONFIRMED commission -> real trio run through job_runner.py / terminal_session.py / lanes.py, one-run-at-a-time as declared DEGRADED mode; INTENT RECORD (Master-Plan P6 restored): the confirm writes a durable launch-intent before spawn; boot reconciles intents so a confirmed-but-unlaunched commission is NEVER silent (named `LAUNCH_INTENT_STRANDED`); DURABLE HANDBACK-FILE PROTOCOL (the restart-safety keystone — Anchor completion detection today is a live stdout reader + exit code, `job_runner.py:734/:982`, and children sit in a KILL_ON_JOB_CLOSE Job Object, `job_runner.py:659-666`, so an `nssm restart` kills or orphans commissioned runs with no handback captured): the commissioned run's wrapper writes the handback JSON + a terminal MARKER file (temp+fsync+rename, S6/T-DUR-S6) into its own worktree at a contract path; the executor sets `kill_on_job_close=False` FOR COMMISSIONS (an explicit, recorded decision — commissions outlive the service) and liveness is tracked by `(pid, proc_create_time)` — never pid alone (`job_runner.py:683-687` already records create_time; `_pid_alive` at :1249-1259 checks pid only, a real PID-reuse hazard); BOOT RECONCILE: on service start, scan launch-intents + worktrees for terminal markers — a complete handback pair is ADOPTED (ingested exactly once, idempotent via client_event_id), a dead run with no marker is HONESTLY FAILED by name (`EXEC_RUN_DIED` / `EXEC_HANDBACK_MISSING`), never silently absorbed; NO-TOKEN-IN-CHILD test: the commissioned run's env/argv carries no ANCHOR_TOKEN or capability (see descope D-1); ANTI-STUB G4 GATE — `artifacts/g4-verdict.json { verdict, path, pid, proc_create_time, handback_id, evidence_paths[], recorded_at }` where PASS requires ALL of: (a) captured child cmdline naming the trio CLI entry, (b) the returned handback file passing `receipt-validate.mjs`, (c) `(pid, proc_create_time)` process identity observed live then terminal — a launcher spawning `node -e` with a canned JSON satisfies NONE of these; G4 FAIL IS AN EXPLICIT HALT: precondition test imported by Wave 11 fails the build unless verdict PASS, blocking Waves 11–19; the only non-HALT alternative is an ANCHOR-OWNED fallback executor discharging IDENTICAL obligations under the SAME suite (auth ON, refuses unconfirmed, anti-stub evidence, durable handback file written into the dossier, full failure-state table) — anything less HALTs for John; `artifacts/g4-evidence.json` written from observed evidence only (S8) — the executor writes evidence, never `commissionable`; AUTH REVALIDATION AT LAUNCH: a revoked/expired token at the launch seam refuses with a named state, zero pid observed; Executor refuses anything not confirmed (negative test); Substrate refusal states surfaced by name: `LaneBusyError`, spawn-cap-reached, folder-build-lock (`job_runner.py:1672-1697`); Real-run gate is wave-local (`gate/w4-real-run.mjs`, cheap commission profile), excluded from the standing suite

**Depends on:** Wave 1, Wave 3

**done-when:** A confirmed commission drives a real trio run to anti-stub G4 PASS evidence (trio cmdline + receipt-validate + (pid, proc_create_time)) under auth ON with the handback captured from the durable FILE, a mid-run service restart is survived with the handback adopted at boot, a dead run and a missing handback are named rather than absorbed, and the Wave-11 precondition test passes only because of the recorded verdict.

- **Given** A confirmed commission with recorded who, **when** the executor runs it, **then** a real trio run starts, its cmdline names the trio entry, its `(pid, proc_create_time)` is recorded, and the handback FILE passes receipt-validate and lands in the dossier
- **Given** A commissioned run alive when the Anchor service is restarted, **when** boot reconcile runs, **then** the run was NOT killed (kill_on_job_close=False for commissions), its completed handback file is adopted exactly once, and a run that died restart-adjacent is named dead — never silently absorbed
- **Given** A stub launcher producing an observed pid and a canned handback JSON, **when** the G4 gate evaluates it, **then** verdict PASS is REFUSED (no trio cmdline, no receipt-validate pass, no live-then-terminal process identity)
- **Given** A revoked or expired token at the launch seam, **when** launch is attempted, **then** it refuses with a named state and zero processes start
- **Given** g4-verdict.json not reading PASS and no qualifying fallback, **when** any wave from 11 on runs its precondition, **then** the build FAILS with the G4 HALT named

**Failure states (executor surface):**

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (trio CLI absent) | `EXEC_SUBSTRATE_MISSING` | "The build substrate is not available on this box — commission cannot launch." |
| launch-refused (unconfirmed) | `EXEC_REFUSED_UNCONFIRMED` | "Commission not confirmed — nothing launched, nothing spent." |
| substrate-busy (LaneBusy / spawn cap / build lock) | `EXEC_SUBSTRATE_BUSY` | "Substrate refused the launch (<reason>) — commission intact; retry when clear." |
| launched-then-died | `EXEC_RUN_DIED` | "Run <id> died (process identity no longer live) — named dead, not absorbed." |
| no-handback (marker absent past TTL) | `EXEC_HANDBACK_MISSING` | "Run <id> ended with no handback file — named missing, not absorbed." |
| adopted-after-restart | `EXEC_RUN_ADOPTED` | "Run <id> survived a service restart — handback adopted from its durable file." |
| auth-refused at launch | `EXEC_AUTH_REFUSED` | "Launch refused — credential invalid at the launch seam; nothing started." |
| backing-store-unreadable | `EXEC_DOSSIER_UNREADABLE` | "Commission dossier unreadable — launch refused rather than launched blind." |
| empty-but-valid | `EXEC_NO_RUNS` | "No commissioned runs." |
| unknown (liveness undeterminable) | `EXEC_LIVENESS_UNKNOWN` | "Run liveness UNKNOWN — shown as unknown, not running." |

## Wave 5 — Decision records and spikes — G2 / G3 / G5 / G6, step-type map, cost model, skills table, SC6 feasibility

**Intent:** Settle the remaining hypotheses with executable spikes, lock the decision records later waves import, produce the deterministic cost model that makes every dollar figure falsifiable on subscription seats, generate the skills intersection table with ONE pure function, and emit the EARLY SC6 feasibility verdict.

**Serves:** 2, 3, 6, 7.

**Deliverables:** G2 artifact-rendering spike (real converged Crucible doc-trio through packet-view.mjs classifyArtifact / buildArtifactCard; verbatim verdict; FAIL routes a plan-shaped renderer into Wave 18 AS A RECORDED SCOPE ADDITION, not a silent mutation); G3 handback-validation spike (receipt-validate.mjs passes a real trio handback, refuses a corrupted one, both as tests); G5 HALT inventory + classification → `artifacts/halt-inventory.json` (every human gate on the real Crucible/Foreman/researchPrime/Gandalf commission path at file:line, classed EXTERNALLY-OBSERVABLE / REQUIRES-TRIO-CHANGE / INVISIBLE — ABSORBING the documented gated-lane fragility `job_runner.py:574-578` into the class of any skill riding a gated lane; INVISIBLE-HALT profiles named excluded in the Face); DERIVED `artifacts/commissionable-skills.json` via the ONE pure generator `deriveCommissionableSkills` (unit-tested; never hand-edited; S8); EARLY SC6 FEASIBILITY VERDICT `artifacts/sc6-feasibility.json`: `commissionable_count >= 2` or HALT for John's scope decision BEFORE Wave 6+ builds; G6 identity resolution PRE-RECORDED per GATE DECISION 5 (John, 2026-08-01, STAGE1-APPROVAL.md; the code decides the substrate: ANCHOR_TOKEN is a bare shared secret, constant-time compared, no subject/expiry/claims, `paths.py:384-446`) → every confirmation receipt records the CLAIMED identity STAMPED UNAUTHENTICATED: `who: { claimed: "<supplied name>", provenance: "claimed_unauthenticated" }` — the supplied name (e.g. `john`) plus the explicit provenance stamp; a claimed `who` is NEVER rendered as proven and `unattributed` is NEVER silently substituted (the unknown-never-rendered-as-empty honesty law); credential CLASS recorded on spend confirmations; building real subject identity (accounts/sessions/subjects) is explicitly OUT of this North Star's scope — its own future effort, not a TODO here; no IdP; DETERMINISTIC COST MODEL `artifacts/cost-model.json` (tokens × rate table): production seats are subscription CLIs with no per-token billing, so every $ figure in calibration and envelope debits is SYNTHETIC-BUT-DETERMINISTIC, computed by one named function — stated as such wherever rendered; Decision record — step-type -> skill -> confirmation map (RESEARCH -> researchPrime, PLAN -> Crucible, BUILD -> Foreman, REVIEW -> Gandalf dispatch entry only; CONFIRM-TO-PLAN binds a step ULID, CONFIRM-TO-BUILD binds an approved plan artifact VERSION; auto-flow refused by test); Compile-cost calibration over >=20 real compiles priced through the cost model (median + p90 as a NUMERIC RELATION the Wave-8 test checks: `ENVELOPE_MAX_SPEND_USD >= 3 × p90(compile_cost)` — machine-checked, not a prose note); Face glossary line ('talking' = typed NL chat, ASR out of scope); amendment-vs-recommission decision recorded

**Depends on:** Wave 1, Wave 4 (g4-evidence input for the skills table + feasibility verdict)

**done-when:** Every spike has a checked-in verdict backed by a passing test, the step-type map / identity policy / cost model are machine-readable records later waves import, `commissionable-skills.json` is derived by the tested pure generator from the two evidence inputs, and `sc6-feasibility.json` records `commissionable_count >= 2` — or the effort HALTs here for John.

- **Given** An approved plan artifact returned as a PLAN handback, **when** the lifecycle attempts to flow it onward, **then** no BUILD starts automatically; CONFIRM-TO-BUILD bound to that artifact VERSION is required, proven by a test
- **Given** `g4-evidence.json` and `halt-inventory.json`, **when** `deriveCommissionableSkills` runs twice, **then** the output is byte-identical, `commissionable` is computed never hand-set, and a hand-edit is detected by regeneration in CI
- **Given** Fewer than two commissionable rows, **when** Wave 5 completes, **then** `sc6-feasibility.json` records HALT and the effort stops for John's decision before Wave 6 spends
- **Given** An ANCHOR_TOKEN with no recoverable subject, **when** a spend confirmation records who, **then** it is written as the CLAIMED identity with the explicit stamp — `who: { claimed: "<name>", provenance: "claimed_unauthenticated" }` — with credential CLASS recorded, renders as claimed-not-authenticated (never as proven), and no `unattributed` value is silently substituted

## Wave 6 — Ledger spine — one writer IN PRODUCTION: live-writer migration, typed-store + event-KIND allow-lists, invariants in CI

**Intent:** Make criterion 10 true in the SHIPPED TOPOLOGY, not a lab: `roadmap_events` is today a whole-file JSON rewrite with unlocked read-modify-write from short-lived Node bridge spawns the platform kills on timeout (`anchor_gui.py:10381-10388/:10494-10501`, `subprocess.run(timeout=20/30)`), and the durable path is dead code. This wave names the lock, migrates every live writer, and proves it with separate OS processes and a kill-mid-write.

**Serves:** 1, 10.

**Deliverables:** Single-writer spine module owning all roadmap_events appends, built on the EXISTING `withFileLock` (`durable-write.mjs:191`) + `writeFileAtomicSync` — the lock is NAMED, the whole-file-rewrite reality is stated and serialized under it; LIVE-WRITER MIGRATION, ENUMERATED AND RETIRED BY NAME (each a named fix item with its own test): `job-lifecycle.mjs:283 / :637 / :715 / :933-944`, `roadmap.mjs:819 / :1000 / :1139`, `packet-view.mjs:304` (the `status_flip` appender reached from the LIVE `scripts/high-seat-bridge.mjs --decide` path, which imports `writeProjectRoadmap` directly at :41/:237 and is spawned by `anchor_gui.py:10495`), `pe-gate.mjs:443` — after migration every production persist routes through the spine's locked durable path (`appendRoadmapEventDurable` and the write-authority durable paths gain their first production callers, closing the Wave-3 pre-decided FAIL); Typed-store ALLOW-LIST (undeclared store write refused by name) PLUS the VERSIONED EVENT-KIND ALLOW-LIST (Master-Plan P2 restored): `ROADMAP_EVENT_KINDS` = step_create, step_set, status_flip, commission_bind + `scaffold_proposal` now; `reflection_receipt`, `next_stage_proposal`, attention events admitted ONLY via an explicit allow-list VERSION BUMP + test — this allow-list IS the mechanical chat-turn detector (an event kind outside the list fails the build; a "temporary transcript sink" is structurally impossible); Concurrency proof T-DUR-S1: N SEPARATE OS PROCESSES × M events (not workers in one process), total ordering, zero lost/torn, PLUS a kill-the-writer-mid-append crash case (the platform kills bridge processes by design), and the test FAILS if the lock or atomic write is removed; APPEND IDEMPOTENCE PRIMITIVE: caller-supplied `client_event_id`; re-append is a no-op returning the original seq (T-IDEM-06) — the primitive Waves 8/9/11/14/16 build on; NAMED BOUND `ROADMAP_EVENTS_MAX = 50000` with refusal `events-bound-exceeded` + bounded-read API; CI invariant check in the auth-ON suite: no second writer (grep spans BOTH repos, Python and scripts/ included), no untyped store, no event kind outside the versioned allow-list

**Depends on:** Wave 1, Wave 3

**done-when:** Every enumerated live writer call site is migrated onto the named locked spine path with its own regression test, the separate-OS-process concurrency test with kill-mid-write proves exactly one writer, a repeated client_event_id is a proven no-op, the event-kind allow-list rejects an undeclared kind, and CI fails any branch introducing a second writer or an unlisted event kind in either repo.

- **Given** N separate OS processes each appending M events, **when** T-DUR-S1 runs on the target box, **then** every event appears exactly once in total order, a writer killed mid-append leaves no torn record, and removing the lock or atomic write makes the test fail
- **Given** The `high-seat-bridge --decide` path after migration, **when** it persists a decision, **then** the append goes through the spine's locked path and the CI grep finds zero direct `writeProjectRoadmap` production callers outside the spine
- **Given** An event of a kind not on the versioned allow-list (e.g. a chat turn), **when** the spine receives it, **then** it is refused by name and the CI invariant check fails any code path that would admit it without a version bump + test
- **Given** An append already committed, **when** the same client_event_id is resubmitted, **then** no second event exists and the original seq returns; at ROADMAP_EVENTS_MAX further appends refuse with events-bound-exceeded

**Failure states (spine surface):**

| State | Status code | User-visible text |
|---|---|---|
| lock-contended (timeout) | `SPINE_LOCK_TIMEOUT` | "Ledger busy — write retried then refused; nothing partial was written." |
| store-not-declared | `SPINE_STORE_REFUSED` | "Write aimed at an undeclared store — refused by name." |
| event-kind-not-allowed | `SPINE_KIND_REFUSED` | "Event kind <k> is not on the versioned allow-list — refused; no transcript sink." |
| events-bound-exceeded | `SPINE_EVENTS_BOUND` | "Ledger at its 50000-event bound — append refused by name, never truncated." |
| backing-store-unreadable | `SPINE_LEDGER_UNREADABLE` | "Campaign ledger unreadable — writes refused rather than guessed." |
| empty-but-valid | `SPINE_LEDGER_EMPTY` | "No campaign events yet." |
| unknown (lock state undeterminable) | `SPINE_STATE_UNKNOWN` | "Ledger state unknown — reported as unknown, not healthy." |

## Wave 7 — Commission dossier — one key across the lifecycle, the CONFIRM JOURNAL (A4 fix, ONE mechanism)

**Intent:** Join propose → confirm → run → handback under a single dossier key, and close A4 with ONE specified mechanism — the confirm journal two-phase apply — so a bound commission can never exist without its receipt and no future maintainer must choose between unspecified alternatives.

**Serves:** 3, 8, 11.

**Deliverables:** Commission dossier store keyed by job_id/commissioned_as joining proposal, confirmation (who), launch intent + record (pid, proc_create_time), and handback under one key (S3); A4 FIX — THE CONFIRM JOURNAL (the single chosen mechanism; "journaled transaction OR crash-repairable pair" is retired): a confirm appends ONE atomic `confirm_intent` journal record (client_event_id keyed) BEFORE any store write; the apply step then writes roadmap bind + Strip receipt; a `confirm_applied` marker closes the journal entry; BOOT REPAIR `repairConfirmJournal()` replays any open journal entry idempotently (client_event_id) to full application or rolls it back whole, with the user-visible `repair-applied` state — the detector is the open journal entry, the repair verb is named, the idempotence key is named, and the unrepaired state renders as `DOSSIER_PARTIAL`; Kill-between-writes test T-ATOM-CONFIRM: killed between roadmap and Strip writes → on restart either fully committed or fully repaired, never a bind without receipt; Dossier read API (rehydration + attention consumers) returning honest-unknown for absent facts; CONTAINMENT: dossier/handback/artifact path resolver confined to the project root with escape-attempt tests (`..`, absolute, symlink/junction — T-CON-07) each refused as `path-escape-refused`, PLUS a long-path (MAX_PATH) case (worktree + planning + bundle names can cross it; git and stdlib differ with/without longpaths)

**Depends on:** Wave 6

**done-when:** The whole commission lifecycle reads under one dossier key, the confirm journal's kill-between-writes test proves atomic-or-repaired with no orphaned bind, boot repair is idempotent under client_event_id, and the three escape-attempt tests plus the long-path case are refused by name.

- **Given** A confirm killed between the roadmap write and the Strip write, **when** the process restarts and repairConfirmJournal runs, **then** the dossier reads fully confirmed with receipt or cleanly rolled back, the A4 defect row closes against T-ATOM-CONFIRM, and a second repair pass changes nothing
- **Given** A commission proposed, confirmed, launched and handed back, **when** the dossier is read by key, **then** all four lifecycle facts return with who, pid and proc_create_time present
- **Given** A handback naming a path escaping the project root via `..`, absolute path, or symlink/junction — or exceeding MAX_PATH, **when** the resolver reads it, **then** each is refused with the named state and nothing outside the root is touched

**Failure states (dossier surface):**

| State | Status code | User-visible text |
|---|---|---|
| dossier-missing | `DOSSIER_MISSING` | "No dossier for commission <id> — shown as missing, not empty." |
| dossier-partial (journal open) | `DOSSIER_PARTIAL` | "Commission <id> confirm incomplete — repair pending; not shown as confirmed." |
| repair-applied | `DOSSIER_REPAIRED` | "Commission <id> was repaired at boot — now fully consistent; noted." |
| path-escape-refused | `DOSSIER_PATH_REFUSED` | "Handback path escapes the project root — refused; nothing read or written." |
| backing-store-unreadable | `DOSSIER_UNREADABLE` | "Dossier store unreadable — facts withheld rather than guessed." |
| empty-but-valid | `DOSSIER_EMPTY` | "No commissions yet." |
| unknown | `DOSSIER_STATE_UNKNOWN` | "Dossier state unknown — reported as unknown." |

## Wave 8 — Session envelope — one confirmed budget, BEFORE any authoring spend exists

**Intent:** Implement the confirmed compile ENVELOPE — moved ahead of scaffolding authoring so no compile path ever exists before the law that governs its spend (closes the pre-envelope-spend MAJOR). John confirms one bounded budget; every compile and orchestrator reflection is SHOWN, not re-authorized; exhaustion hard-stops.

**Serves:** 2, 9.

**Deliverables:** Session envelope object with NAMED NUMERIC BOUNDS `ENVELOPE_MAX_SPEND_USD = 5.00`, `ENVELOPE_MAX_COMPILES = 25`, `ENVELOPE_TTL_MINUTES = 240` (whichever first), justified against the Wave-5 calibration by the MACHINE-CHECKED relation `ENVELOPE_MAX_SPEND_USD >= 3 × p90(compile_cost)` (T-BND-08 imports `cost-model.json` + the calibration record); confirmed once at session open as a typed event with who; HASH-BOUND CONFIRM (TOCTOU): the envelope confirmation payload carries the content hash of the rendered budget terms; mismatch → `confirm-hash-mismatch`, nothing minted; Envelope enforcement in the spend path: spend only inside a live envelope; every debit priced through the deterministic Wave-5 cost model and individually SHOWN; TTL measured against a MONOTONIC-OR-SEQ-ANCHORED clock with a clock-skew test (wall-clock skew cannot silently extend or expire an envelope); REFUSAL PATHS `envelope-exhausted` / `envelope-expired` hard-stop all spend until fresh confirmation; AUTH REVALIDATION AT DEBIT: a revoked/expired token at the debit seam refuses with a named state and zero debit; Envelope-confirm IDEMPOTENCE (T-IDEM-08 on client_event_id): double submit mints exactly one envelope; Commissions explicitly NOT covered (test: a commission still requires its own confirmation inside a live envelope); No-live-envelope path per gate decision 4: ONLY the model-authored NL-polish reflection compile queues as a typed event (S13, in-ledger); the deterministic receipt AND deterministic next-stage proposal are NEVER queued (they are zero-spend — Wave 14); Envelope ledger durability triple (S4, T-DUR-S4)

**Depends on:** Wave 5 (cost model + calibration), Wave 6 (spine, client_event_id)

**done-when:** One confirmed, hash-bound envelope governs all compile/reflection spend with each debit shown and priced by the deterministic cost model, each named bound hard-stops by name (TTL skew-proof), a double-submitted confirmation mints exactly one envelope, a revoked token at the debit seam debits nothing, and no spend of any kind can occur outside a live envelope.

- **Given** A session opened with one confirmed envelope, **when** several compiles and a reflection run, **then** each is shown and debited via the cost model with no additional confirmation dialog
- **Given** An exhausted or expired envelope (including expiry under deliberate wall-clock skew), **when** another spend is attempted, **then** it hard-stops with the named state and spends nothing
- **Given** An envelope confirmation whose payload hash does not match the rendered terms (post-render mutation), **when** submitted, **then** it refuses with confirm-hash-mismatch and mints nothing
- **Given** A revoked token mid-session, **when** a debit is attempted, **then** the debit seam refuses with a named state and the envelope balance is unchanged

**Failure states (envelope surface):**

| State | Status code | User-visible text |
|---|---|---|
| envelope-absent | `ENVELOPE_ABSENT` | "No confirmed session envelope — spend refused; confirm a budget to proceed." |
| envelope-exhausted | `ENVELOPE_EXHAUSTED` | "Session budget exhausted — hard stop; confirm a fresh envelope to continue." |
| envelope-expired | `ENVELOPE_EXPIRED` | "Session envelope expired — hard stop; confirm a fresh envelope to continue." |
| confirm-hash-mismatch | `ENVELOPE_CONFIRM_HASH_MISMATCH` | "The budget shown changed before you confirmed — refused; review the current terms." |
| auth-refused at debit | `ENVELOPE_AUTH_REFUSED` | "Credential invalid at spend time — nothing debited." |
| backing-store-unreadable | `ENVELOPE_LEDGER_UNREADABLE` | "Envelope ledger unreadable — spend refused rather than run blind." |
| empty-but-valid | `ENVELOPE_NONE_YET` | "No envelopes confirmed yet this session." |
| unknown | `ENVELOPE_STATE_UNKNOWN` | "Envelope balance unknown (ledger gap) — spend refused until repaired." |

## Wave 9 — Scaffolding authoring — dialogue to step_create, coarse roadmap proposed and batch-confirmed

**Intent:** Turn a spoken description into a PROPOSED multi-stage scaffolding with Oranges annotations, batch-confirmed in one hash-bound action, authored by the steward, visibly labelled, zero chat persisted — with every compile inside the Wave-8 envelope.

**Serves:** 1, 3.

**Deliverables:** dialogue -> step_create path: NL description compiled into coarse roadmap steps with Oranges annotation fields, emitted as a typed `scaffold_proposal` event through the spine; every scaffold compile debits the live envelope (a compile with no live envelope refuses — the Wave-8 law binds this path from birth); Batch-confirm verb: ONE confirmation binds the whole scaffolding, recording who, HASH-BOUND to the rendered proposal content (post-render mutation → `confirm-hash-mismatch`, zero steps written); atomicity: all steps or none; Steward-authored provenance flag on every scaffolded step; Zero-chat-persistence test (typed events only, enforced structurally by the Wave-6 event-kind allow-list); No adversarial review reachable from the scaffolding compile (test); Batch-confirm IDEMPOTENCE (T-IDEM-09): double submit commits exactly once, ledger byte-identical to single-submit

**Depends on:** Wave 5 (identity decision, step-type map), Wave 6 (spine), Wave 8 (envelope)

**done-when:** A spoken description produces a proposed multi-stage scaffolding with Oranges annotations committed by a single hash-bound batch confirmation recording who, with all compiles envelope-debited, zero chat turns persisted, and a double-submitted or post-render-mutated confirmation unable to double-commit or commit the wrong content.

- **Given** A fresh project and a typed NL description, **when** the steward compiles it inside a live envelope, **then** a PROPOSED scaffolding emits as a typed event marked steward-authored, the compile is shown and debited, and nothing is written to the roadmap
- **Given** A proposed scaffolding, **when** John issues ONE batch confirmation carrying the proposal hash, **then** all steps commit through the spine with who recorded; a payload whose hash mismatches the current proposal refuses and writes nothing
- **Given** A completed describe-and-confirm session, **when** every store is scanned, **then** zero chat turns exist and the campaign reconstructs from typed events alone
- **Given** An already-committed batch confirmation, **when** resubmitted identically, **then** no duplicate steps exist, the response reports already-confirmed, and the ledger is byte-identical

**Failure states (scaffolding surface — Master-Plan P5 table):**

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (no Face to anchor) | `SCAFFOLD_NO_FACE` | "No project Face yet — describe the project first; the scaffolding anchors to it." |
| dependency-slow-or-killed (compile dies) | `SCAFFOLD_PROPOSAL_LOST` | "The scaffolding proposal did not complete; nothing was written. Ask again." |
| dependency-returns-garbage | `SCAFFOLD_PROPOSAL_INVALID` | "Proposed scaffolding failed validation — shown for reference, not confirmable." |
| confirm-hash-mismatch | `SCAFFOLD_CONFIRM_HASH_MISMATCH` | "The proposal changed since it was shown — confirm refused; review the current version." |
| backing-store-unreadable | `ROADMAP_STORE_UNREADABLE` | "Roadmap store unreadable — batch confirm refused rather than partially written." |
| empty-but-valid (no steps derivable) | `SCAFFOLD_EMPTY` | "I couldn't derive any stages from that description — tell me more." |
| unknown (roadmap state unclear) | `ROADMAP_STATE_UNKNOWN` | "Existing roadmap health unknown (validate failed) — heal before scaffolding." |

## Wave 10 — Face compile projection (RESTORED — Master-Plan P4)

**Intent:** Restore the chartered Face-as-compiled-projection: the campaign's narrative memory as typed `face_events` over immutable content-hashed `source_text`, with provenance, visible drops, retraction, bounded compile and a cost ledger — all inside the envelope. Without this, criteria 1–2's "description COMPILES into the Face" (INTAKE invariant 1) has no implementation.

**Serves:** 1, 2.

**Deliverables:** Immutable content-hashed `source_text` blob per description (write-once by hash, S5); typed assert/retract/refine `face_events` through the spine (event kinds admitted via the Wave-6 allow-list version bump + test); provenance spans (source_hash + offsets) on every compiled field, with the property test that any Face version reproduces its exact source text byte-identically; `dropped_or_generalized` rendered as part of the proposal and seen before acceptance; retraction preserves content + why and is a hard exclusion set on recompile; park/restart equivalence (byte-identical projection); bounded compile: max passes + fixed-point check + circuit breaker that HALTs to John (`COMPILE_CIRCUIT_BREAK`); incremental diff-based rewrites; COST LEDGER: every compile logged with tokens + deterministic cost-model dollars, debiting the Wave-8 envelope; provenance VIEWER UI deferred to Wave 18's artifact surface (Master Plan's own deferral)

**Depends on:** Wave 6, Wave 8, Wave 9

**done-when:** The Face is a projection over face_events with content-hashed source_text and provenance spans, any Face version reproduces its source byte-identically, retraction excludes on recompile, the bounded compiler circuit-breaks to John rather than looping, and every compile event references a live envelope with remaining budget (ledger query).

- **Given** A compiled Face field, **when** its provenance span is resolved, **then** the exact source text reproduces byte-identically from the content-hashed blob
- **Given** A retracted fact, **when** the Face recompiles, **then** the retracted content is excluded, its why preserved, and the exclusion visible
- **Given** A compiler that does not converge in max passes, **when** the circuit breaker trips, **then** compile HALTs to John with `COMPILE_CIRCUIT_BREAK` and no partial Face version lands
- **Given** The campaign ledger at any point, **when** the envelope query runs, **then** every compile event references a live confirmed envelope with remaining budget

**Failure states (compile surface — Master-Plan P4 table):**

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (no live envelope) | `COMPILE_NO_ENVELOPE` | "No confirmed session envelope — compile queued; confirm a budget to run it." |
| dependency-slow-or-killed (non-convergent) | `COMPILE_CIRCUIT_BREAK` | "The compiler could not converge in <N> passes — halted; your call." |
| dependency-returns-garbage | `COMPILE_OUTPUT_INVALID` | "Compile output failed validation and was discarded; the Face is unchanged." |
| backing-store-unreadable | `FACE_EVENTS_UNREADABLE` | "Face history cannot be read — compile refused rather than compiled blind." |
| empty-but-valid | `COMPILE_SOURCE_EMPTY` | "Nothing new to compile — the Face already reflects everything recorded." |
| unknown (envelope state undeterminable) | `ENVELOPE_STATE_UNKNOWN` | "Envelope balance unknown (ledger gap) — compile refused until it is repaired." |

## Wave 11 — Commission proposal in Anchor — skill, seat and depth shown before spend; the seats law restored

**Intent:** Wire the audited Ecgberht propose/confirm/bind verbs into the Anchor steward loop: a commission proposed FOR a named step, skill from the intersection table, seat through the SUBSCRIPTION-CLI-ONLY law, hash-bound confirm with who, launched by the Wave-4 executor — all behind the G4 and SC6 preconditions.

**Serves:** 3, 6.

**Deliverables:** G4 + SC6 PRECONDITION GATE at the head of this wave: imports the Wave-4 precondition test (verdict PASS or qualifying Anchor-owned fallback) AND `sc6-feasibility.json` (FEASIBLE) — otherwise this wave and every wave after FAIL to build; Commission proposal bound to a named step ULID (free-floating refused per A1), rendering skill + seat + depth + estimated spend (deterministic cost model) BEFORE confirmation; SKILL SELECTION TABLE-BOUND (`commissionable: true` rows only; otherwise `skill-not-commissionable` with excluded_reason); SEATS LAW RESTORED (INTAKE invariant 4): every seat resolves through `resolveSeats` (`engine/seating.mjs:252`) — production seats are SUBSCRIPTION CLIs ONLY; a MAPPING ASSERTION test walks EVERY `default_cli` value Anchor can emit (including the bare `grok`) and asserts each resolves to a subscription CLI seat or is refused (bare `grok` DRIVER refused; family `grok` maps to `grok-cli`); SEAT-COLLISION PREDICATE DEFINED: a proposal naming a (family, driver) pair already held by a live run's seat is refused `seat-collision` — the predicate is a named pure function with a unit test, not an adjective; HASH-BOUND CONFIRM: the confirmation payload carries the content hash of the rendered proposal (skill + seat + depth + estimate); post-render mutation → `confirm-hash-mismatch`, zero launch; Confirmation records who, mints job_id / commissioned_as, appends commission_bind through the spine (via the Wave-7 confirm journal); COMMISSION-CONFIRM IDEMPOTENCE (T-IDEM-11): double submit → one job_id, one launch, original returned; AUTH REVALIDATION AT CONFIRM: revoked/expired token at the confirm seam refuses, zero append; Dispatch by the locked step-type map; confirmed commission handed to the Wave-4 executor; observed (pid, proc_create_time) into the dossier

**Depends on:** Wave 4, Wave 5, Wave 7, Wave 9

**done-when:** With G4 PASS and SC6 FEASIBLE, a commission is proposed for a named stage showing skill, seat and depth, every seat Anchor can emit provably resolves through resolveSeats to a subscription CLI or refuses, nothing runs until a hash-bound confirmation records who and drives a real run whose process identity lands in the dossier, and a double-submitted or post-render-mutated confirmation cannot double-launch or wrong-launch.

- **Given** A confirmed roadmap with a named BUILD step, **when** the steward proposes a commission, **then** the proposal renders skill=Foreman, seat and depth with an estimate, and no run has started
- **Given** Every `default_cli` value Anchor can emit, **when** the seats mapping assertion runs, **then** each resolves through resolveSeats to a subscription-CLI seat or is refused by name — a bare `grok` driver is refused, family `grok` maps to `grok-cli`
- **Given** A rendered proposal mutated after display, **when** the original confirmation is submitted, **then** confirm-hash-mismatch refuses it and zero processes launch
- **Given** A confirmation already minted and launched, **when** resubmitted identically, **then** the original job_id returns, no second bind appends, no second process starts
- **Given** g4-verdict.json not PASS or sc6-feasibility.json not FEASIBLE, **when** this wave's suite runs, **then** the precondition fails the build with the HALT named and no commission path is exercised

**Failure states (commission-proposal surface):**

| State | Status code | User-visible text |
|---|---|---|
| step-not-found / free-floating | `COMMISSION_STEP_UNBOUND` | "Commission must name an existing roadmap step — refused." |
| skill-not-commissionable | `COMMISSION_SKILL_REFUSED` | "<skill> is not commissionable (<excluded_reason>) — choose from the proven set." |
| seat-collision | `COMMISSION_SEAT_COLLISION` | "Seat <family/driver> is already driving a live run — refused." |
| seat-not-subscription | `COMMISSION_SEAT_REFUSED` | "Seat does not resolve to a subscription CLI — refused by the seats law." |
| confirm-hash-mismatch | `COMMISSION_CONFIRM_HASH_MISMATCH` | "The proposal changed since it was shown — confirm refused; review it again." |
| unconfirmed-refused | `EXEC_REFUSED_UNCONFIRMED` | "Commission not confirmed — nothing launched, nothing spent." |
| g4-halt / sc6-halt | `COMMISSION_PRECONDITION_HALT` | "Substrate or skill-feasibility verdict missing — commissioning is blocked, not degraded." |
| backing-store-unreadable | `COMMISSION_STORE_UNREADABLE` | "Proposal store unreadable — refused rather than guessed." |
| empty-but-valid | `COMMISSION_NONE_YET` | "No commissions proposed yet." |
| unknown | `COMMISSION_STATE_UNKNOWN` | "Commission state unknown — reported as unknown." |

## Wave 12 — Progressive elaboration — targeted questions or an offered researchPrime commission at stage START

**Intent:** Detail arrives when a stage starts, never at scaffold time — via the unit-tested commissionability predicate whose questions must name the MISSING element (anti-stub).

**Serves:** 5.

**Deliverables:** Stage-start hook: entering a scaffolded step runs the PURE COMMISSIONABILITY PREDICATE (named deliverable + acceptance sentence + >=1 Face-anchored constraint with a provenance pointer — Master-Plan P5); failing it emits a typed elaboration event whose targeted questions NAME THE MISSING PREDICATE ELEMENT (a question not naming a missing element fails the test — echoing annotation text cannot pass); Offered-commission branch: research-shaped gaps OFFER a researchPrime commission through standard propose -> confirm (never auto-runs); Scaffold-time-demands-nothing test: the authoring flow fails if any stage-detail question is raised before stage start; Answers recorded as typed elaboration events joined to the step

**Depends on:** Wave 11

**done-when:** Starting a stage runs the commissionability predicate and produces targeted questions that each name a missing predicate element or an offered researchPrime commission, and no stage detail is ever demanded at scaffold time.

- **Given** A batch-confirmed coarse scaffolding, **when** authoring completes, **then** no stage-level detail question was asked during authoring
- **Given** A scaffolded stage failing the predicate on its acceptance sentence, **when** John starts it, **then** the targeted question names the missing acceptance sentence specifically — a generic echo of the Oranges annotation fails the gate
- **Given** A research-shaped gap, **when** the stage starts, **then** a researchPrime commission is OFFERED via propose -> confirm and nothing runs until confirmed

**Failure states (elaboration surface):**

| State | Status code | User-visible text |
|---|---|---|
| no-questions-derivable | `ELAB_NO_QUESTIONS` | "Stage passes the readiness predicate — no elaboration needed (named, not blank)." |
| elaboration-declined | `ELAB_DECLINED` | "Elaboration declined — stage remains coarse; commission will re-check readiness." |
| offered-commission-refused | `ELAB_OFFER_REFUSED` | "Offered research commission declined — recorded; stage can still be elaborated by hand." |
| backing-store-unreadable | `ELAB_STORE_UNREADABLE` | "Elaboration store unreadable — questions withheld rather than invented." |
| empty-but-valid | `ELAB_NONE_YET` | "No stages started yet." |
| unknown | `ELAB_STATE_UNKNOWN` | "Stage readiness unknown — reported as unknown." |

## Wave 13 — Session-state truth + hardened launch truth (RESTORED — Master-Plan P6: outbox, status_flip, leases, gate-surfacing)

**Intent:** Make roadmap status reflect ACTUAL session/run state across park, restart and kill — by BUILDING the substrate that makes it possible: lease emission (none exists in job_runner today), the Python-side fsync'd outbox with the Node mediator as the spine's client (the single answer to INTAKE's "who emits `status_flip`"), and gate-surfacing proven on a real gate-heavy commission.

**Serves:** 3, 8.

**Deliverables:** LEASE EMISSION BUILT (no lease/heartbeat exists in job_runner — verified): the executor's run wrapper renews a durable lease (S12 outbox record) on an interval; liveness decisions use `(pid, proc_create_time)` everywhere, with BATCHED tasklist probes and TTL-cached results (never per-render — the June O(everything) lesson); PYTHON-SIDE FSYNC'D OUTBOX with monotonic sequence + acknowledged idempotent drain by the NODE MEDIATOR, which is the SPINE'S CLIENT — the mediator emits `status_flip` through the Wave-6 single writer; Anchor Python NEVER writes the ledger (closes the INTAKE GAP without a second writer; kill-the-mediator convergence test T-DUR-S12); Status derivation BOUND TO THE EXISTING `roadmap.mjs buildRoadmapProjection` (wiring, not a re-derivation — the e-4 watch item is closed by name); drift resolved toward observed reality via durable status events, never by the composer peeking at live pids; Park path (parked session reports parked, envelope preserved, zero spend while parked); Kill/restart path (killed run reported dead BY NAME via status_flip -> DEAD, cause=lease_expired; STALE vs DEAD distinct); Anti-FLAP: edge-triggered state_since + hysteresis near lease TTL, sampled-across-boundary test, clock-skew case included (TTL is monotonic/seq-anchored); GATE-SURFACING as a first-class path proven on a deliberately gate-heavy REAL Crucible commission from the EXTERNALLY-OBSERVABLE class (wave-local real-run gate `gate/w13-real-run.mjs`), measured against the Wave-5 gate budget; the three kill -9 self-healing tests (job / Anchor / steward); park/restart/kill parity matrix as ONE checked-in table

**Depends on:** Wave 4, Wave 11

**done-when:** After park, after restart and after kill, roadmap status matches actual session/run state via durable status events emitted by the mediator through the single writer, a killed run is reported dead by name with STALE distinct from DEAD, status does not flap across lease TTL under jitter or skew, and a gate-heavy real Crucible commission surfaces its gates within the recorded budget.

- **Given** A campaign with one live commissioned run, **when** the run is killed -9 and the reconciler sweeps, **then** status_flip(-> DEAD, cause=lease_expired) lands through the single writer and the roadmap reports dead by name — not still-working
- **Given** A parked session with a live envelope, **when** the project reopens, **then** status reports parked with the envelope preserved and zero spend while parked
- **Given** A lease approaching TTL with jittered renewals and skewed wall clock, **when** status is sampled repeatedly across the boundary, **then** state_since is edge-triggered with hysteresis and the state does not flap
- **Given** A real gate-heavy Crucible commission, **when** its HALT question fires, **then** the gate surfaces as a first-class event within the gate budget, answered through the standard path

**Failure states (status/gate surface — Master-Plan P6 table):**

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (launcher down) | `LAUNCH_INTENT_STRANDED` | "Confirmed but not launched — the launcher is down; intent preserved, will reconcile at boot." |
| dependency-slow-or-killed (lease expired) | `RUN_DEAD_LEASE_EXPIRED` | "The run died (lease expired <t>) — marked DEAD, not RUNNING." |
| dependency-returns-garbage (outbox gap) | `STATUS_SEQUENCE_GAP` | "Status sequence gap detected — status shown as of seq <n>, gap flagged." |
| backing-store-unreadable | `OUTBOX_UNREADABLE` | "Status outbox unreadable — last durable status shown with its timestamp." |
| empty-but-valid (no runs) | `NO_LIVE_RUNS` | "Nothing is running." |
| unknown (reconciler cannot decide) | `RUN_LIVENESS_UNKNOWN` | "Run liveness UNKNOWN — neither RUNNING nor DEAD is claimed." |

## Wave 14 — Handback validation, DETERMINISTIC reflection + next-stage proposal (gate decision 4), and the MULTI-SKILL proof

**Intent:** Close the orchestration loop per John's DECIDED criterion-4 interpretation: a validated handback IMMEDIATELY produces a zero-model reflection receipt AND a zero-model next-stage proposal from ledger facts; the richer model-authored narrative compiles at next session open inside the envelope. Plus the two-skill executor proof, before the High Seat waves.

**Serves:** 4, 6.

**Deliverables:** Handback ingestion FROM THE DURABLE HANDBACK FILES (Wave-4 protocol — never stdout-tethered) through receipt-validate.mjs (6 campaign-memory fields; corrupted → quarantined S7, refused-repairable, never reflected on); THE DETERMINISTIC EMITTER, NAMED AND TESTED (gate decision 4's required implementation): `emitReflectionReceipt(dossier, ledgerView)` and `proposeNextStageDeterministic(dossier, ledgerView)` — ZERO-MODEL, ZERO-SPEND, ZERO-NETWORK pure renders over the dossier + ledger (the assembleBriefPacket / narration-floor pattern): the receipt carries what the stage produced + its Oranges prompts; the proposal names the next roadmap step with its why and enters the standard propose -> confirm path; a NO-MODEL/NO-NETWORK ASSERTION test (model-call trap + network trap) fails if either emitter ever calls a model or socket; GOLDEN DETERMINISM: both emitters byte-identical on repeat over the same ledger, pinned to golden files; BOTH ALWAYS EMIT AT HANDBACK — regardless of envelope state (they spend nothing); ONLY the NL-polish reflection compile queues without a live envelope and fires at next session open inside the envelope (the draft's emitted/queued split of the proposal is REMOVED); MULTI-SKILL EXECUTOR PROOF: two DIFFERENT skills selected TEST-BOUND from commissionable-skills.json each driven propose -> confirm -> execute -> validated handback -> emitted receipt + proposal in one campaign (criterion 6 proven here, not first at the kill gate); < 2 rows HALTs; HANDBACK IDEMPOTENCE (T-IDEM-14): duplicate delivery → exactly one receipt, one proposal, `duplicate-handback-ignored`; Missing handback NAMED (`HANDBACK_NEVER_ARRIVED`), never absorbed; Real-run gate wave-local (`gate/w14-real-run.mjs`)

**Depends on:** Wave 4, Wave 5, Wave 7, Wave 13

**done-when:** A validated handback ALWAYS immediately yields the named zero-model reflection receipt AND zero-model next-stage proposal (proven no-model/no-network, byte-deterministic, golden-pinned) with the NL-polish compile alone deferring to the next envelope, two different commissionable skills are proven end to end in one campaign, and a duplicate handback produces no second receipt or proposal.

- **Given** A commissioned stage returning a valid handback file with NO live envelope (overnight case), **when** it is ingested, **then** the reflection receipt AND the deterministic next-stage proposal are emitted immediately with zero spend and zero model calls (trap-asserted), and only the NL-polish compile waits for the next confirmed envelope
- **Given** The same ledger state, **when** either emitter runs twice, **then** outputs are byte-identical and match the golden files
- **Given** A corrupted handback missing campaign-memory fields, **when** ingested, **then** receipt-validate refuses it into quarantine with a named repairable state and no receipt or proposal is produced
- **Given** commissionable-skills.json at this wave, **when** the multi-skill proof selects skills, **then** two commissionable rows are each driven to a validated handback — fewer than two HALTs rather than proving criterion 6 with one
- **Given** A handback already ingested, **when** delivered again, **then** exactly one receipt and one proposal exist and the duplicate is recorded ignored

**Failure states (handback surface — Master-Plan P8 table):**

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (bundle absent) | `HANDBACK_NO_BUNDLE` | "Handback arrived without its artifact bundle — quarantined; nothing accepted." |
| dependency-slow-or-killed (never arrived) | `HANDBACK_NEVER_ARRIVED` | "Commission <id> confirmed <t> ago; no handback. Named as overdue, not absorbed." |
| dependency-returns-garbage | `HANDBACK_REFUSED_REPAIRABLE` | "Handback failed validation on <fields> — quarantined for repair; work preserved." |
| duplicate-handback-ignored | `HANDBACK_DUPLICATE_IGNORED` | "Handback <id> already ingested — duplicate ignored; one receipt stands." |
| backing-store-unreadable | `QUARANTINE_UNREADABLE` | "Quarantine store unreadable — validation refused; raw handback untouched." |
| empty-but-valid (all fields unavailable) | `HANDBACK_HONEST_EMPTY` | "Handback valid but <n>/<m> fields honestly unavailable — coverage ratio shown." |
| unknown (derivation source missing) | `FIELD_SOURCE_UNKNOWN` | "Field <f> cites no source artifact — rejected; shown as unknown, not filled." |

## Wave 15 — Rehydration + the ONE boot/open-project pipeline (RESTORED — Master-Plan P7)

**Intent:** Deliver continuity through ONE NAMED PIPELINE — `engine/session-open.mjs openProjectPipeline()`: reconcile → ingest pending handbacks → publishAttention → compose brief — owned here, kill-tested between every stage. This is how "derived ENTIRELY from the ledger" and "dead run NAMED" are simultaneously true: reconcile commits observed reality to the ledger FIRST; the composer then reads only the ledger.

**Serves:** 11, 8, 12.

**Deliverables:** `openProjectPipeline()` in a named module, the ONLY open-project path, ordered: (1) RECONCILE — the Wave-13 reconciler sweeps intents/leases/markers and commits durable status events through the spine (dead run → status_flip DEAD; overdue handback → named event); (2) INGEST — pending durable handback files adopted via Wave 14 (receipts + deterministic proposals emitted, idempotent); (3) PUBLISH — publishAttention on any resulting edges; (4) COMPOSE — the wake-up brief from the POST-RECONCILE ledger only; KILL-BETWEEN-STAGES TESTS: process killed between each adjacent pair → rerun converges, no duplicate events (client_event_id), composer never runs against a pre-reconcile ledger; Rehydration joining assembleBriefPacket (Q1-Q12, zero model calls) with the dossier read API, closing the A2 NEEDS-DOSSIER-JOIN gaps; HEAL-BEFORE-BRIEF (P7 restored): `validateRoadmap` / `healRoadmap` (`roadmap.mjs:322/:414`) run before composing — a torn roadmap heals first, surfaced as `BRIEF_ROADMAP_HEALED` (and the healed write goes through the spine); SEEN-RECEIPT (P7 restored): `appendSeenReceipt` (`brief.mjs:183/:138`) appended after assembly so `deltaSinceSeen` (`brief.mjs:241`) stays COUNT-ANCHORED, not clock-anchored (skew-proof "since you last looked"); First-message composer as ZERO-MODEL DETERMINISTIC RENDER: byte-identical on repeat, golden-pinned; a reintroduced model call fails the trap; ANTI-STUB NO-RE-ASK: one test binds BOTH obligations — the brief asks no question whose answer is recorded AND proposes the next step with its why (a composer that asks nothing and proposes nothing fails); Dead run + never-arrived handback NAMED in the wake-up message; Kill-everything-then-resume integration test (deliberately seeded with the Wave-4 restart case); Honest-unknown rendering; NL polish is a SEPARATE envelope-debited layer, absent by default at cold start

**Depends on:** Wave 3, Wave 7, Wave 14

**done-when:** After killing everything and reopening, openProjectPipeline runs reconcile → ingest → publish → compose in proven order (kill-tested between stages), and the first message — zero-model, byte-identical, golden-pinned — states stage, run liveness and everything waiting on John from the post-reconcile ledger alone, names the dead run and the missing handback, proposes the next step with its why, and asks no already-answered question.

- **Given** A campaign with one dead run and one never-arrived handback, **when** everything is killed and the project reopens, **then** reconcile commits both facts to the ledger BEFORE compose, and the first message names both, states the stage, and proposes the next step with its why
- **Given** A kill between reconcile and compose (and between each other adjacent stage pair), **when** the pipeline reruns, **then** it converges with no duplicate events and the composer never reads a pre-reconcile ledger
- **Given** A ledger recording the objective, scaffolding and last confirmation, **when** the brief composes, **then** no question about those facts is asked AND a next step with its why is proposed — one test asserts both
- **Given** The same ledger state, **when** the composer runs twice, **then** outputs are byte-identical, match the golden file, and zero model calls and zero spend are observed

**Failure states (wake-up brief surface — Master-Plan P7 table):**

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (no ledger yet) | `BRIEF_NO_CAMPAIGN` | "No campaign recorded for this project yet — describe it to begin." |
| dependency-slow-or-killed (assembly interrupted) | `BRIEF_ASSEMBLY_FAILED` | "Could not assemble the wake-up brief — nothing partial is shown; retry." |
| dependency-returns-garbage (torn roadmap) | `BRIEF_ROADMAP_HEALED` | "Roadmap had <n> invalid events — healed and noted; brief reflects the healed state." |
| backing-store-unreadable | `BRIEF_LEDGER_UNREADABLE` | "Campaign ledger unreadable — brief refused rather than invented." |
| empty-but-valid (campaign quiet) | `BRIEF_ALL_QUIET` | "Campaign at stage <s>; nothing running, nothing waiting on you." |
| unknown (run liveness unresolvable) | `BRIEF_RUN_UNKNOWN` | "Run <id>: liveness UNKNOWN — reported as unknown, not as running." |

## Wave 16 — Attention contract — pure derivation, NAMED publish call sites, raise tiers revived (RESTORED — Master-Plan P9)

**Intent:** Publish the altitude contract along the named seam with every publish TRIGGER named and removal-tested, and revive the two dead raise tiers — `waiting_steps` (tier 2) and `precomputeBriefCache` (tier 1) — so criterion 12 does not ship with two of three tiers dead.

**Serves:** 12, 9.

**Deliverables:** `deriveAttention(ledgerView)` — ONE pure engine function returning working | needs_you | deliverable_ready | blocked | idle with state_since, reason, provenance; PURE (write-trap test); over a READABLE ledger always one of the five — `unknown` is the read-side state for an unreadable store only (criterion-12 enum resolution); `publishAttention()` — the single publisher, a spine caller, persisting the typed attention cell + `attention_projection_published` event in one journaled transaction (event kind via allow-list version bump); MANDATORY CALL-SITE TABLE, each with a removal-proof test (deleting the call fails a test): commission proposed/awaiting confirm → publish at the propose verb (T-ATT-CS1); confirm/launch recorded → publish from the mediator drain (T-ATT-CS2); validated handback ingested → publish from the Wave-14 ingester (T-ATT-CS3); run dead / lease expired → publish from the Wave-13 reconciler (T-ATT-CS4); queued NL-polish compile pending → publish at queue append (T-ATT-CS5); boot/open-project → openProjectPipeline stage 3 (T-ATT-CS6); the High Seat NEVER publishes (T-ATT-CS7 asserts absence); EDGE-ONLY PUBLISH + IDEMPOTENCE (T-IDEM-16): no-change republish appends nothing, byte-identical ledger; INDEX DELIVERY: the anchor-contract ingest BRIDGE built here (the Wave-3 probe recorded NEEDS-WIRE — `ingestAck` is in-process only), so the projection lands in the already-built index; the project pushes, the index never walks; RAISE TIER 2 REVIVED: `waiting_steps` DERIVED from the EXISTING `buildRoadmapProjection` step statuses and fed to `enrichForRaise` so `raiseSeverity → waiting_on_john_step` (`high-seat.mjs:112–129`) fires, with a test that a waiting-on-John step raises tier 2; RAISE TIER 1 MADE REAL: `precomputeBriefCache` (`brief.mjs:954`) fired on EVERY attention-state change (a publishAttention hook), so `bringItUp` (`high-seat.mjs:539`) serves a FRESH packet with `further_gathering:false` honestly (the Wave-1 A3 fix guarantees fresh means fresh) — test: attention change → cache precomputed → raise tier 1 `human_wait_packet_ready` fires; deliverable_ready PROVENANCE gate (bundle-hash match required); Anti-FLAP edge-triggered state_since + hysteresis (shared with Wave 13)

**Depends on:** Wave 6, Wave 15

**done-when:** Each project publishes a typed attention projection whose derivation is proven pure and whose delivery reaches the built index through the new bridge, every named transition edge has a removal-tested publish call site and the High Seat provably never publishes, a no-change republish writes nothing, deliverable_ready is bundle-hash gated, and both previously-dead raise tiers demonstrably fire from real ledger states.

- **Given** A commission proposal awaiting John, **when** the projection derives, **then** needs_you returns, nothing is written by derivation (trap), and the propose-verb call site published the edge — deleting that call fails T-ATT-CS1
- **Given** A roadmap with one waiting-on-John step, **when** the High Seat ranks, **then** waiting_steps is supplied from the existing projection and raise tier 2 (waiting_on_john_step) fires — the tier is no longer dead
- **Given** An attention-state change, **when** publishAttention runs, **then** precomputeBriefCache fires, and bringItUp serves the fresh packet with raise tier 1 real
- **Given** A handback whose bundle hash does not match, **when** derived, **then** deliverable_ready is NOT emitted; provenance-unproven is recorded
- **Given** A published projection with no state change, **when** publishAttention reruns, **then** no event appends and the attention cell is byte-identical

**Failure states (projection surface):**

| State | Status code | User-visible text |
|---|---|---|
| store-unreadable (read side) | `ATTENTION_UNKNOWN` | "<project>: attention state unknown (store unreadable) — never rendered as idle." |
| provenance-unproven | `ATTENTION_PROVENANCE_UNPROVEN` | "Deliverable claimed but bundle hash unverified — not shown as ready." |
| stale (edge older than lease truth) | `ATTENTION_STALE` | "Attention state predates last reconcile — republish pending." |
| publish-refused (spine refusal) | `ATTENTION_PUBLISH_REFUSED` | "Projection publish refused by the ledger — prior state stands, refusal named." |
| empty-but-valid (no campaign) | `ATTENTION_NONE_YET` | "No campaign activity to project yet." |
| unknown (derivation input unresolvable) | `ATTENTION_INPUT_UNKNOWN` | "Projection inputs unreadable — state unknown, not guessed." |

## Wave 17 — High Seat fold + THE BADGE PATH BOUNDED — portfolio at a glance

**Intent:** Fold N projections into the High Seat read-only, answer portfolio-at-a-glance from the existing no-walk index — and BOUND THE AMBIENT BADGE PATH BY NAME: the shipped `--badge` → `verbStatus` → `discoverStrips` root-walk is retired, the badge is served index-only behind a read trap, and the client's hardened poll gating is preserved and imported into the latency test.

**Serves:** 12, 13.

**Deliverables:** High Seat fold consuming N typed projections into the raise queue and ⚑ badge, `write_authority:'none'` ENFORCED by an `indexOnlyFs`-style read/write trap (the pattern that actually throws, `query.mjs:392-422` — the string field at `high-seat.mjs:752` is a declaration, not enforcement) + byte-identity test (every project tree hash-identical after a full assembly + badge poll + tile render); BADGE PATH RETIRED BY NAME: the `GET /api/ecgberht/high_seat_badge` → `high-seat-bridge.mjs --badge` → `verbStatus` → `discoverStrips` filesystem walk (`anchor_gui.py:10599-10617/:10483`, `high-seat.mjs:681-686/:654`, `verb-bodies.mjs:451`) is REWIRED to answer from the portfolio-index read (`query.mjs`) behind the index-only trap with a files-opened bound asserted — the walk path is deleted or unreachable, proven by a test that fails if `discoverStrips` is reached from the badge route; per-poll process spawn bounded: badge served from a cached cell the ingest path updates, at most one short-lived bridge process per poll interval; CLIENT GATING PRESERVED: `static/high-seat.js:485-528` visibility gating (`document.hidden` skip), MIN_MS=90000, geometric backoff to MAX_MS=15min, `pagehide` cleanup are kept — a rebuild that loses them fails review; the LATENCY TEST IMPORTS the client's own `MIN_MS` constant: "one poll" is DEFINED as one healthy visible-tab interval (90 s); under failure backoff latency may reach MAX_MS and under a hidden tab polls skip entirely — both documented as the contract, not silently violated; Portfolio-at-a-glance from `query.mjs` through the Wave-16 read API: stage, live/waiting/blocked runs, last movement, attention per active project; FIELD-BY-FIELD COVERAGE BINDING: every criterion-13 field in the Wave-3 A5 matrix is ANSWERED from the index or rendered as a named per-field `unknown` — never quietly omitted; DELIMITER GUARD: project roots crossing the process boundary as a `';'`-joined argv string (`_ECGBERHT_ROOT_DELIM`, `anchor_gui.py:10542`; `high-seat-bridge.mjs:24`) — semicolon-skipped roots RENDER AS `unknown` ROWS, never a shorter list, with a delimiter round-trip test; STDOUT-PURITY test on both bridges (one JSON line, nothing else; a stray console.log corrupts every caller) + `bridge_bad_json` mapped into the dependency-returns-garbage row; Unreadable project → explicit unknown ROW (row count never shrinks); NAMED BOUND `PORTFOLIO_MAX_ROWS = 500` with `portfolio-bound-exceeded` refusal; Ambient-signal containment test (campaign needing nothing → zero ambient beyond badge count); DEGRADED PATH: any A5 field beyond the cap ships as named unknown + gate-report DEGRADED entry — and per Wave 19, DEGRADED cannot green the kill gate without John's signed decision; New/changed endpoints ship `route_table.py` rows + `OPEN_ROUTES.json` review (default-deny gate passes)

**Depends on:** Wave 3, Wave 16

**done-when:** Opening the High Seat shows every active project's stage, runs and last movement from the existing index with zero root walks (trap-proven, files-opened bounded), the legacy badge walk path is unreachable by test, needs_you/deliverable_ready reach the badge within one MIN_MS poll on a healthy visible tab with the client's gating preserved, semicolon-skipped and unreadable roots render as unknown rows with the row count preserved, and every criterion-13 field is answered or named unknown.

- **Given** A portfolio with one unreadable store and one semicolon-containing root, **when** the High Seat opens, **then** both projects appear as named unknown rows, the row count is never shorter, and no project root was walked (trap)
- **Given** A project transitioning to needs_you, **when** one MIN_MS interval elapses on a healthy visible tab, **then** the ⚑ badge reflects it — the test imports MIN_MS from static/high-seat.js rather than hard-coding 90s
- **Given** The badge route invoked, **when** its code path is traced under the index-only trap, **then** discoverStrips is never reached, the files-opened count stays within the asserted bound, and at most one short-lived process serves the interval
- **Given** The fold running over N projections, **when** project trees are hashed after, **then** every tree is byte-identical (write_authority none proven) 
- **Given** A bridge emitting a stray non-JSON line, **when** the stdout-purity test runs, **then** it fails naming the bridge, and the surface maps the failure to bridge_bad_json rather than a blank panel

**Failure states (High Seat surface — Master-Plan P9 table + additions):**

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (index absent) | `GLANCE_INDEX_MISSING` | "Portfolio index not found — no project list is shown; run the index audit fix." |
| dependency-slow-or-killed (query over cap) | `GLANCE_QUERY_REFUSED` | "Portfolio query exceeded its bound — refused, not truncated-as-complete." |
| dependency-returns-garbage (bridge_bad_json / snapshot invalid) | `GLANCE_INDEX_UNPARSEABLE` | "Index snapshot or bridge output unreadable — nothing is guessed." |
| backing-store-unreadable (one project) | `GLANCE_PROJECT_UNKNOWN` | "<project>: state unknown (store unreadable) — row kept, marked unknown." |
| skipped-root (delimiter) | `GLANCE_ROOT_SKIPPED` | "<project>: root name unsupported by the transport — row kept, marked unknown." |
| portfolio-bound-exceeded | `GLANCE_BOUND_EXCEEDED` | "More than 500 active projects — list refused by name, never silently truncated." |
| empty-but-valid | `GLANCE_PORTFOLIO_EMPTY` | "No active projects registered." |
| unknown (attention underivable) | `ATTENTION_UNKNOWN` | "<project>: attention state unknown — never rendered as idle." |

## Wave 18 — Chamber UI — steps, proposals, confirmations, artifacts, corrections (+ I52 renderer refusal — Master-Plan P10)

**Intent:** The reviewable campaign surface: steps, hash-bound proposal/confirm affordances, artifacts, corrections as new versions — with the restored I52 test that a scaffolding can NEVER wear commissioned-artifact chrome, and every new poller adopting the hardened gating pattern by name.

**Serves:** 7.

**Deliverables:** Chamber steps view rendering the confirmed roadmap with per-step status from Wave 13; Proposal + confirm surface for scaffolding batch-confirm, commission confirmation and next-stage proposals — each showing what will be spent before it is spent, each wired to the idempotent HASH-BOUND confirm verbs (double-click cannot double-commit; post-render mutation surfaces `confirm-hash-mismatch`); Artifact view via packet-view.mjs classifyArtifact / buildArtifactCard (plus the plan-shaped renderer if the G2 spike FAILED — a recorded Wave-5 scope addition); I52 SCAFFOLD EXEMPTION TEST (P10 restored): the renderer REFUSES to draw a scaffold step or `scaffold_proposal` in commissioned-artifact card chrome, and an artifact card NEVER renders without a bundle hash — the "scaffolding mistaken for a commissioned plan" risk closed by test; Artifact reads through the Wave-7 contained resolver with the chamber's own escape-attempt test (T-CON-18); Correction path: a typed spoken correction emits a NEW VERSION proposal through propose -> confirm (hash-bound); prior version addressable; Reflection receipts + deterministic next-stage proposals rendered into conversation as typed artifacts, never persisted chat; POLLER DISCIPLINE: every new chamber poller adopts the `static/high-seat.js:485-528` pattern BY NAME (visibility gating, min interval, geometric backoff, pagehide cleanup) — verified against each new setInterval; New endpoints ship route_table.py rows + OPEN_ROUTES.json review

**Depends on:** Wave 5, Wave 7, Wave 17

**done-when:** Stage artifacts, steps, proposals, receipts and deterministic proposals render reviewably, a scaffold step can never render in commissioned-artifact chrome and no artifact card renders without a bundle hash, every chamber surface answers all five failure states plus unknown with distinct codes and text, a contained-path escape is surfaced as refused, every new poller carries the named gating pattern, and a spoken correction produces a hash-bound new version with the prior still addressable.

- **Given** A converged Crucible doc-trio as a stage artifact, **when** John opens the artifact view, **then** it renders as a classified artifact card carrying its bundle hash — and a scaffold_proposal fed to the same renderer is REFUSED the card chrome
- **Given** A rendered artifact John corrects by typing, **when** he confirms, **then** a NEW VERSION lands hash-bound through propose -> confirm with the previous version addressable
- **Given** Each failure state injected behind each chamber surface, **when** it renders, **then** each shows its own code and text — empty never borrows unreadable's text, loading never masks garbage
- **Given** Any new chamber poller, **when** the poller audit runs, **then** it demonstrates visibility gating, a minimum interval, and failure backoff per the named pattern

**Failure states (chamber surfaces — per surface: steps view, proposal/confirm, artifact view, receipt render):**

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing | `CHAMBER_DEP_MISSING` | "<surface>: its data source is not available — shown as unavailable, not blank." |
| dependency-slow-or-killed | `CHAMBER_DEP_DEAD` | "<surface>: the data source stopped responding — last good state shown with its age." |
| dependency-returns-garbage | `CHAMBER_DEP_GARBAGE` | "<surface>: the data source returned something unreadable — shown as an error, nothing invented." |
| backing-store-unreadable | `CHAMBER_STORE_UNREADABLE` | "<surface>: backing store unreadable — content withheld rather than guessed." |
| path-escape-refused | `CHAMBER_PATH_REFUSED` | "Artifact path escapes the project root — refused, not rendered." |
| empty-but-valid | `CHAMBER_EMPTY` | "<surface>: nothing here yet." |
| unknown | `CHAMBER_STATE_UNKNOWN` | "<surface>: state unknown — reported as unknown, distinct from empty." |

## Wave 19 — Wave-0 kill gate — end-to-end campaign proof, two skills, auth ON, DEGRADED cannot green silently

**Intent:** Prove the whole North Star in one campaign on a fresh project under enforced auth: describe → propose → batch confirm → commission → execute → validated handback → deterministic reflection + proposal, two test-bound skills, kill everything and resume — with DEGRADED items unable to green criterion 13 without John's signature, and auth refusals asserted on outcomes.

**Serves:** all 13 (Wave-0 kill gate realized).

**Deliverables:** End-to-end campaign test on a FRESH project with the auth preflight enforced, asserted on OUTCOMES; TEST-BOUND TWO-SKILL SELECTION from commissionable-skills.json (never hand-named; < 2 HALTs with the shortfall named); G4 + SC6 preconditions re-asserted at the gate; Kill-everything-then-resume leg through openProjectPipeline naming the dead run and missing handback via the zero-model composer; AUTH OUTCOME SWEEP: revoked/expired-token refusals at the confirm, launch and debit seams asserted on outcomes (zero pid, zero append, zero debit) — not on env plumbing; Whole-campaign invariant sweep: zero chat turns (event-kind allow-list), zero spend outside a live envelope, exactly one roadmap_events writer (publishAttention and the mediator included; CI grep both repos), no High Seat write (trap + byte-identity), no project-root walk, no trio-tree modification, no pre-spine durable write; DEGRADED RULE (closes the DEGRADED-green BLOCKER): the gate FAILS (HALT for John) if ANY criterion-13 field ships DEGRADED — unless an explicit SIGNED scope decision from John for that named field exists in `artifacts/degraded.json`; the same rule governs the one-run-at-a-time executor DEGRADED mode and any Anchor-owned G4 fallback: each must carry John's signed acceptance or the gate HALTs; the gate report additionally names the shared-secret `who` policy per GATE DECISION 5 — criterion 3 reported as met-under-shared-secret (claimed identities stamped `claimed_unauthenticated`, never rendered as proven), the visibility John decided stays surfaced, not hidden; Criteria traceability report mapping each NS criterion 1-13 to its passing tests and each property-gate checkbox to its owning wave's test id (the T-* registry); Real-run gate wave-local (`gate/w19-real-run.mjs`)

**Depends on:** Wave 18 (transitively all)

**done-when:** One fresh-project campaign under enforced auth runs description → proposed scaffolding → hash-bound batch confirm → commissioned stage → validated handback → deterministic reflection receipt + next-stage proposal across two test-bound skills, survives kill-and-resume through openProjectPipeline with the true state named, passes the auth outcome sweep and the whole-campaign invariant sweep, maps every criterion and checkbox to a passing test id — and HALTs rather than greens if any DEGRADED item lacks John's signed acceptance.

- **Given** A fresh project with enforced auth, **when** John describes, batch-confirms, confirms a commission, and the stage hands back validated, **then** the deterministic reflection receipt AND next-stage proposal are produced at handback and the path is asserted on ledger and rendered outcomes
- **Given** That campaign mid-flight with one run dead and one handback never arrived, **when** everything is killed and the project reopens, **then** the first message names both anomalies and asks nothing already recorded
- **Given** A revoked token injected mid-campaign, **when** a confirm, a launch and a debit are attempted, **then** each refuses with its named state and the outcome sweep shows zero pid, zero append, zero debit
- **Given** Any criterion-13 field shipping DEGRADED without a signed decision record, **when** the gate evaluates, **then** it HALTs naming the field — a DEGRADED portfolio view cannot produce a green kill gate on John's behalf
- **Given** commissionable-skills.json at gate time, **when** the campaign selects skills, **then** both come from commissionable rows, neither hand-named — fewer than two HALTs with the shortfall named

---

## Property gates (hardening law — crucible journal 0080)

Earned PER INSTANCE via the Durable-store obligations map (S1–S13 × T-DUR ids) and the Property-gate obligation map (T-IDEM/T-BND/T-CON/T-HON/T-ATT/T-ATOM/T-EQUIV ids). The five property classes below are the vocabulary; the maps above are the binding. A property or store asserted anywhere in this plan and absent from those maps is a BLOCKER.

- durability: atomic write (temp + fsync + rename) · lock or documented serialization · a concurrency test — per store row S1–S13
- honesty: a failure-state table · unknown and empty as SEPARATE rows — per surface wave table
- idempotence: a repeat-invocation test — T-IDEM-06/08/09/11/14/16
- boundedness: numeric bound named + refusal path — T-BND-06/08/17
- containment: escape-attempt test (`..`, absolute, symlink/junction, long-path) — T-CON-07/18

### Storage mechanism vocabulary (required when durability is claimed)

- atomic write via temp + fsync + rename for snapshot and durable JSON paths (Node: `writeFileAtomicSync`; Python: the `_atomic_replace` bounded-retry pattern + fsync)
- cross-process lock (`withFileLock`) or documented serialization around multi-writer paths
- a concurrency test with SEPARATE OS PROCESSES (never worker threads standing in) including a kill-mid-write case where the store is platform-killed by design
- where exactly-once is claimed: a repeat-invocation test on `client_event_id`
- where containment is claimed: an escape-attempt test (`..`, absolute path, symlink/junction) plus the long-path case
- where bounds are claimed: the numeric bound named and a refusal path when exceeded

### Failure-state table vocabulary (required when addsSurface)

Every surface-bearing wave answers dependency-missing / dependency-slow-or-killed / dependency-returns-garbage / backing-store-unreadable / empty-but-valid — with **unknown** and **empty** as SEPARATE rows, each naming a status code AND user-visible text, per the wave tables above.
