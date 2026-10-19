# REVIEW — Consistency & Traceability Audit (pre-Foreman)

**Date:** 2026-08-01 · **Auditor:** consistency/traceability pass over the canonical set
**Set audited:** NORTH-STAR.md (v4 LOCKED) · MASTER-PLAN-v2.md (STAGE-1 APPROVED) · STAGE1-APPROVAL.md · INTAKE.md · stage2-artifacts/BEST-DRAFT.md (NOT stamped) · wave-decomposition.json · HUMAN-LOCKABLE.json · OPEN-FINDINGS.json · hardening-gate-result.json · Ecgberht/NEXT-UX-AND-ANCHOR-ORCHESTRATION.md (LOCKED intent)

**Verdict up front: NOT ready to hand to Foreman as-is.** The prose plan (BEST-DRAFT.md) is strong and traceable, but (1) the machine decomposition Foreman would loop over disagrees with it in count AND content, (2) two of the three named live defects are scheduled NOWHERE in Stage 2, (3) several Master-Plan deliverables serving criteria 3, 8, 11, 12 were lost in decomposition, and (4) the draft is unstamped with 10 BLOCKER-severity residual findings (judge NOT_CONVERGED).

---

## A. Criterion → Phase → Wave traceability matrix

Wave numbers below are **BEST-DRAFT.md numbering** (the 18-wave text). Phase mapping is the Master Plan's own criteria map (MP §"Criteria map").

| NS criterion | Master-Plan phases | Stage-2 waves (draft) | Status |
|---|---|---|---|
| 1 — spoken → proposed scaffolding, batch-confirmed, zero chat persisted | P2, P3, P4, P5, P11 | W2 (fixture shape, non-crediting), W6 (no-chat CI invariant), W8 (scaffolding authoring), W18 | SERVED — but **P4's Face-compile machinery is LOST** (see A-iii) |
| 2 — lightweight envelope covers compiles AND reflections | P1, P4, P11 | W5 (≥20-compile calibration), W9 (envelope, named bounds $5.00/25/240m), W18 | SERVED (envelope survives; Face compile projection lost) |
| 3 — commission FOR a named stage, skill+seat+depth before spend, `who` | P1, P2, P3, P5, P6, P11 | W3 (A1 audit), W4 (executor refuses unconfirmed), W5 (G6 identity), W7 (dossier), W10 (proposal/confirm/who), W17 (confirm surface), W18 | SERVED — but **P6's run-scoped capabilities / intent records / gate-surfacing are LOST** |
| 4 — validated handback → REFLECTION RECEIPT + next-stage proposal | P7, P8, P11 | W13 (receipt always-emitted / compile-when-funded), W18 | SERVED **under a reinterpretation of the locked wording** (see F-1; Contrarian BLOCKER `topic:criterion-deferred-next-proposal-stage-wave`) |
| 5 — progressive elaboration at stage START | P5, P11 | W11, W18 | SERVED |
| 6 — ≥2 commissioned skills in one campaign | P11 | W13 (multi-skill executor proof), W18 (test-bound selection), fed by W4/W5 (`commissionable-skills.json`) | SERVED — feasibility BLOCKER open (`topic:empty-goals-intersection…`) |
| 7 — artifacts render reviewably; spoken correction → new version | P3, P10, P11 | W5 (G2 spike), W17 (chamber, correction path), W18 | SERVED — but **P10's I52 scaffold-exemption renderer test is LOST** |
| 8 — roadmap status truth across park/restart/kill | P3, P6, P11 | W12, W18 | SERVED — but **P6's fsync'd outbox / `status_flip` writer / mediator are LOST** |
| 9 — AUTH ON, outcome-asserted | P1, P9, P11 | W1 (auth-ON suite + negative tests), W15/W16, W18 | SERVED (revalidation-at-seams BLOCKER open) |
| 10 — one `roadmap_events` writer, concurrency-proven | P2, P11 | W1 (hammer/removal-proof), W6 (spine + CI), W18 | SERVED |
| 11 — CONTINUITY: kill-everything, no re-ask, dead run + missing handback NAMED | P7, P11 | W3 (A2 coverage), W7 (dossier read API), W14 (composer, golden determinism, no-re-ask), W18 | SERVED — but **P7's `seen`-receipt/`deltaSinceSeen` and heal-before-brief are LOST**; reconcile-before-compose ordering BLOCKER open |
| 12 — ALTITUDE CONTRACT: typed projection, read-only fold, badge one poll, zero ambient | P9, P11 | W15 (derive/publish seam), W16 (fold/badge), W18 | SERVED — but **the two P9 raise-tier fixes (`waiting_steps`, `precomputeBriefCache`) are LOST** (see G); `unknown`-state enum conflict open |
| 13 — PORTFOLIO AT A GLANCE from the EXISTING index, no walk, loud-unknown | P1, P9, P11 | W3 (A5 audit + field matrix), W15 (index delivery), W16 (glance view), W18 | SERVED — DEGRADED-green tension vs the criterion (BLOCKER `topic:can-degraded-fields-gate-green…`) |

**(i) Criteria with NO implementing wave:** none. All 13 criteria have at least one owning wave in BEST-DRAFT.md.

**(ii) Waves serving NO criterion (inclusion test):** none. Every wave maps to at least one criterion (W1→9/10 + Decision 3; W2→shape-of-1–4 under gate decision 7; W3→3/10/11/13; W4→3/6/9; W5→2/3/6/7; W6→10/1; W7→3/11; W8→1/3; W9→2; W10→3; W11→5; W12→8; W13→4/6; W14→11; W15→12; W16→12/13; W17→7; W18→all). No bloat detected. (W2's crediting risk is a residual finding, not scope creep.)

**(iii) Criteria served by a PHASE but LOST in decomposition** (verified by grep — zero matches in all of `stage2-artifacts/`):

1. **P4 — the Face as a compiled projection (criteria 1, 2).** `face_events`, `source_text`, provenance spans, `dropped_or_generalized`, retraction, bounded compile / circuit breaker, cost ledger: **absent from every wave**. MP P4: "immutable content-hashed `source_text` per description; provenance spans … typed assert/retract/refine events … cost ledger." The draft has no Face-compile wave at all; W8 compiles description→steps only. Either an explicit descope note ("E5's existing Face machinery suffices, consumed as-is") or a wave must exist. Silence is neither.
2. **P6 — hardened launch truth (criteria 3, 8).** Intent records + durable launcher ("never a silent confirmed-but-unlaunched commission"), run-scoped capabilities ("single-purpose, revocable, TTL > budget ceiling; never argv/env"), the fsync'd OUTBOX + mediator ("Python-side durable fsync'd OUTBOX with monotonic sequence"), gate-surfacing "proven on a deliberately gate-heavy REAL Crucible commission": **absent**. This also un-answers INTAKE's open GAP "Who emits `status_flip` without becoming a second writer" — MP P6 answered it ("closed here by the mediator as the single writer's client"); the draft answers it nowhere. W12 derives status but names no `status_flip` writer.
3. **P9 — the two raise-tier revivals (criterion 12).** See §G — both MISSING.
4. **P7 — wake-up wiring details (criterion 11).** `appendSeenReceipt`/`deltaSinceSeen` ("count-anchored, not clock-anchored") and `validateRoadmap`/`healRoadmap` ("a torn roadmap heals before it briefs", `BRIEF_ROADMAP_HEALED`): **absent from W14**.
5. **P10 — I52 scaffold exemption (criterion 7 / NS risk "scaffolding mistaken for a commissioned plan").** MP P10: "the renderer refuses to draw a scaffold step or `scaffold_proposal` in the commissioned-artifact card chrome, and an artifact card never renders without a bundle hash." W8 carries the `steward-authored` provenance flag, but the W17 renderer-refusal test is **absent** (`card chrome`, `I52`: no matches).
6. **P2 — the versioned event-kind allow-list.** MP P2 names `scaffold_proposal` and admits `reflection_receipt`/attention events "ONLY via an explicit allow-list version bump + test." W6 has a typed-STORE allow-list, but the event-KIND names and the version-bump mechanism are absent (`scaffold_proposal`, `reflection_receipt`: no matches in the draft).

## B. Count and label integrity — TRUE wave counts

- **BEST-DRAFT.md: 18 build waves** (headings `## Wave 1` … `## Wave 18`, verified at lines 184–436). The **19th** `## Wave` heading is line 94's `## Wave-0 kill gate` — a section of the North Star pasted into the header, NOT a build wave. Anyone counting `^## Wave` gets 19; the plan's own lane table confirms 18 ("**A — substrate (critical path)** | 1 … → 18", "mechanically blocks Waves 10–18").
- **wave-decomposition.json: 17 waves** (`n: 1..17`, verified). It is **missing the draft's Wave 2 (Vertical slice FIXTURE-ONLY)** entirely, so every JSON wave n≥2 is the draft's wave n+1 (JSON 3 "BUILD-E" = draft 4; JSON 17 "kill gate" = draft 18).
- **The JSON is also content-stale, not just miscounted.** Same generation run (JSON ts `2026-08-01T06:00:10.654Z`, gate-result `…10.660Z`) yet it reflects a pre-hardening draft. Materially: JSON wave 3 says G4 "**FAIL branch documented as direct-launch fallback** with substrate integration named as its own follow-on scope" — which **contradicts the draft's gate decision 4**: "**G4 FAIL is an explicit HALT** — a machine-readable verdict file mechanically blocks Waves 10–18." The JSON likewise lacks: the A5 field-by-field matrix + capped fix-item budget (draft W3), `client_event_id` idempotence primitive + `ROADMAP_EVENTS_MAX` (W6), containment escape tests (W7), named envelope bounds (W9), G4 precondition + table-bound skill selection + confirm idempotence (W10), the emitted-vs-queued split + MULTI-SKILL proof (W13), golden determinism (W14), the derive/publish seam (W15), `PORTFOLIO_MAX_ROWS` + DEGRADED path (W16), five-state tables (W17), and test-bound two-skill selection (W18). Its G5 covers only "Crucible/Foreman" where the draft covers "Crucible/Foreman/researchPrime/Gandalf".
- **Authoritative artifact: BEST-DRAFT.md.** It alone carries the eight gate decisions, the seam table, and the obligation map. **Required change: regenerate wave-decomposition.json from the final draft (18 waves, correct numbering, full deliverables) before Foreman runs** — Foreman's wave loop consumes the JSON, so as shipped it would build the weaker, G4-soft, 17-wave plan.

## C. Stage-1 gate decisions honoured

1. **Unattended reflections never spend — PRESENT, mechanically gated.** W9: "No-live-envelope path: the reflection COMPILE and next-stage PROPOSAL are QUEUED as typed events and never spend (gate Decision 1)". W13: "with NO live envelope both are QUEUED … with zero unattended spend proven by a test that asserts the receipt EXISTS while the compile does NOT"; GWT: "the deterministic reflection RECEIPT is emitted immediately with zero spend, the NL compile and the next-stage proposal are QUEUED". Gate: named tests in W9/W13 done-whens. (Caveat: the emitted/queued split reinterprets criterion 4 — see F-1.)
2. **A5 = Wave-1-era live-wiring audit, fix items only, no re-plan — PRESENT, gated.** W3: "A5 portfolio-index liveness audit … DERIVED ingest fires on a live write"; "audits, never re-plans (NS non-goal 1)"; done-when "with no rebuild of the portfolio index." W16: "DEGRADED PATH (gate Decision 2) … never absorbed, never answered by re-planning or rebuilding the index." **Note:** the CAPPED budget (6 items / 2 waves) + DEGRADED shipping is an EXTENSION beyond the approval text ("gaps are fix items only"), and the Contrarian BLOCKER argues DEGRADED can green the kill gate while criterion 13 is only partially true — John should ratify or reject the cap explicitly.
3. **`briefCacheStale` fixed in Wave 1 under a named-fix fence — PRESENT, gated.** W1: "A3 FIX in engine/brief.mjs: briefCacheStale staleness key extended from Strip-only (as_of + instruments.length + receipts.length) to include roadmap event count + Face version, entered as a named fix item on the diff-fence allow-list"; GWT: "briefCacheStale reports stale and a fresh packet is assembled instead of serving the cached packet stamped further_gathering:false"; the diff-guard GWT "passes for the allow-listed A3 fix."

## D. Invariants preserved to wave level

- **E5 single ledger / chat never persisted — PRESERVED.** W6 CI invariant "no chat-turn persistence"; W8 "Zero-chat-persistence test"; W18 sweep "zero chat turns persisted."
- **Single writer on `roadmap_events` — PRESERVED, extended.** W6 spine + concurrency test; W15 "publishAttention … writes through the Wave-6 single-writer spine (so it is a caller, not a second writer)"; W18 "exactly one roadmap_events writer (publishAttention included)." (Analyst MAJOR: it is a module invariant, not a tenant invariant — cross-project authz unstated.)
- **Commissions FOR roadmap steps carrying `who` — PRESERVED.** W10: "bound to a named step ULID (free-floating steps refused, per the A1 audit)"; "Confirmation verb recording who."
- **Subscription-CLI seats only via `resolveSeats` — SILENTLY DROPPED.** `resolveSeats`, `grok`, `subscription` appear NOWHERE in BEST-DRAFT.md (grep-verified). INTAKE invariant 4 is explicit: "Production seats are subscription CLIs only — cross family/driver through `resolveSeats` (… a bare `grok` DRIVER is refused, family `grok` maps to `grok-cli`)." W10's "Seat family/driver collision guard" is adjacent but undefined (MAJOR finding `topic:collision-rule-seat-undefined`) and does not carry the subscription-CLI-only rule. **Must be restored as a W10 deliverable + test.**
- **AUTH-ON is the only green — PRESERVED.** W1 "one suite, no auth-off variant; … CI guard that fails the build on any bypass flag"; W18 entire campaign auth ON. (Analyst BLOCKER: no revalidation at confirm/launch seams — a gap, not a contradiction.)
- **No adversarial review in the PRODUCT loop — PRESERVED.** W8: "Scaffolding is NEVER routed through adversarial review — asserted by a test that no review path is reachable from the scaffolding compile."

## E. Refuted ideas stay dead — CONFIRMED DEAD

- **e-1 (new handback artifact channel):** no wave adds a channel; "artifact channel" has zero matches in the draft; W15's `deliverable_ready` gates on the EXISTING bundle hash; MP P8's "the existing bundle channel is the only channel" is not contradicted anywhere in Stage 2.
- **e-4 (bind-the-step / derive-status as new work):** W10 wires the EXISTING verbs ("appending commission_bind through the spine", per the A1 audit of `proposeCommission`/`confirmCommission`) — wiring, not rebuild. **Watch item (not resurrection):** W12's "Status derivation that reads live session and run state … and reconciles it against the ledger" never cites the BUILT `roadmap.mjs` projection (`roadmap.mjs`/`buildRoadmapProjection`: zero matches in the draft); Foreman could re-implement derivation innocently. Add one sentence binding W12 to the existing projection.

## F. Contradictions across documents

1. **Criterion 4 wording vs the draft's restatement (the sharpest one).** NS v4: "On a validated handback the steward emits a REFLECTION RECEIPT with Oranges prompts and PROPOSES the next stage through propose → confirm." The draft re-authors this: "the typed reflection RECEIPT is ALWAYS EMITTED … What is QUEUED … is only the two model-spending steps: the NL reflection COMPILE and the next-stage PROPOSAL." Stage-1 Decision 1 supports the queue, but the NS was never amended — an unattended handback produces no PROPOSAL at handback time. Contrarian BLOCKER states it plainly: "That is an amendment of the locked success criterion, not a refinement of mechanism." Related MAJOR (`boundary-deterministic-receipt…`): the deterministic template may be a handback summary, not a "reflection." **John must either amend/annotate NS criterion 4 or the draft must emit a non-spending proposal artifact at handback.**
2. **wave-decomposition.json vs BEST-DRAFT.md on G4 FAIL** — direct contradiction (quoted in §B): JSON = documented direct-launch fallback; draft = mechanical HALT blocking Waves 10–18.
3. **Wave count 17 vs 18 vs "19"** — resolved in §B; the artifacts as shipped disagree.
4. **MP Phase 3 (real-substrate ugly slice) vs draft Wave 2 (FIXTURE-ONLY).** MP P3 done-when: "one hard-coded path runs describe → proposal → confirm → real Crucible process (via BUILD-E) → real handback → plan on screen … **Serves NS criteria 1, 3, 7, 8 (first real proof of each)**." The draft replaces this with a fixture slice ("ships nothing durable", stub executor) and moves real proof to W4/W10–13. Defensible (gate decision 7), but it restructures a STAGE-1-APPROVED phase and shifts "first real proof" several waves later; the approval stamp does not cover this substitution.
5. **Criterion 12's closed enum vs the draft's `unknown` projection state.** NS: "`working | needs_you | deliverable_ready | blocked | idle`." W15: "Projection returns unknown (a named state)." Two independent sharks flagged it (MAJOR ×2). Honest, but out-of-contract until the NS is amended or `unknown` is remapped.
6. **Stage-1 Decision 2 vs the draft's DEGRADED-ship path** (§C-2): "fix items only" has become "fix items up to a cap, then ship DEGRADED with `unknown` fields" — plus the BLOCKER that DEGRADED could green the criterion-13 kill gate.
7. **INTAKE vs draft, stale/unanswered facts:** (a) INTAKE's `resolveSeats` seat invariant dropped (§D); (b) INTAKE open GAP "Who emits `status_flip`" answered by MP P6's mediator, which the draft dropped — the question is live again; (c) INTAKE says `commission_bind` is appended "via the SINGLE WRITER" that already exists in Ecgberht — W6 builds a new spine; the draft never states how the EXISTING Ecgberht writer and the NEW spine relate (one writer, or a writer per store boundary?). Underspecified, echoed by the Skeptic's cross-store BLOCKER.
8. **LOCKED UX intent (NEXT-UX-AND-ANCHOR-ORCHESTRATION.md): no violation found.** §A (seal → project steward dialogue, goal, task list, skill routing, commissions) is exactly what the plan builds; §B's High Seat glance/badge matches criteria 12–13. Two conscious narrowings, both post-dated and NS-sanctioned: §B's write-capable steward ("Control main Anchor dashboard", reorder by speech) is excluded by NS non-goal "any High Seat WRITE path", and §B's token/subscription capacity tracking is not in this effort; §A/§B's speak-first preference is deferred by the Face glossary line ("'talking' = typed NL chat … ASR out of scope"). These are scoping decisions John made IN the NS lock, not contradictions — but worth restating in the Foreman handoff so the UX vault's larger ambitions aren't mistaken for this effort's scope.
9. **HUMAN-LOCKABLE.json vs a "ready" reading:** `humanLockable: true` is only the multi-Shark bar; `judgeDecision: "NOT_CONVERGED"` and "fresh-eyes pass raises 7 accountable BLOCKER concern(s) (lean=not-lockable)". The plan is NOT stamped; hardening-gate-result.json (`pass: true`, 5/5 properties gated) covers property-gate mechanics only.

## G. The three live defects

| Defect | Scheduled? | Evidence |
|---|---|---|
| `briefCacheStale` keys on Strip only | **PRESENT — W1, with test.** | "A3 FIX in engine/brief.mjs … extended … to include roadmap event count + Face version"; regression GWT quoted in §C-3. |
| `waiting_steps` a dead channel (raise tier 2 never fires) | **MISSING.** | `waiting_steps`, `enrichForRaise`, `raiseSeverity` — zero matches in all stage2-artifacts. MP P9 was explicit: "**revives the currently-dead raise tier 2** (`raiseSeverity` → `waiting_on_john_step`, `engine/high-seat.mjs:112–129`, which today never fires because nothing supplies `waiting_steps`)." No wave delivers or tests it. |
| `precomputeBriefCache` never called (raise tier 1 unreal) | **MISSING.** | `precomputeBriefCache`, `bringItUp` — zero matches. MP P9: "**`precomputeBriefCache` (`brief.mjs:954`) fired on every attention-state change** — this **makes raise tier 1 (`human_wait_packet_ready`) real**." No wave delivers or tests it. |

Both missing fixes belong in W15/W16 with named tests. Without them, criterion 12's raise queue ships with two of its three tiers still dead — the exact defect class this effort was chartered to close.

## H. Residual findings (OPEN-FINDINGS.json)

All 40 findings have `agreement: 1` (none met the ≥2-agree bar; hence `isBlocker: false` throughout). **10 BLOCKER-severity + 20 MAJOR-severity.** None are addressed by the current draft text — they were raised AGAINST it in the fresh-eyes round. BLOCKERs, each with the criterion it goes at:

| Finding | Agr. | Goes at | Draft addresses? |
|---|---|---|---|
| `topic:dag-depends-incomplete` — `Depends on:` edges omit real artifact imports (W10→W4/5/7, W9→W5, W13→W4/5/7, W8→W5 `who`) | 1 | NS 3/6/10 + the plan's own "machine-checkable DAG" claim | NO |
| `topic:publishattention-trigger-unspecified` — no named call sites/invoker for `publishAttention` on each edge | 1 | NS 12, 13 | NO (seam table names owner, not trigger) |
| `topic:atomicity-confirm-cross-store-underspecified` — "journaled transaction OR crash-repairable pair" is two mechanisms, neither specified | 1 | NS 3, 8, 10, 11 | NO |
| `topic:empty-goals-intersection…` — nothing early proves `count(commissionable) ≥ 2`; SC6 may be structurally unreachable under the trio non-goal, discovered only at W13/W18 | 1 | **NS 6** | PARTIAL (W13 HALT exists; no early feasibility gate) |
| `topic:cold-ledger-observed-only-race…` — no ordered "reconcile → durable status events → then compose" obligation on reopen | 1 | **NS 11, 8** | NO (DAG order only) |
| `topic:can-degraded-fields-gate-green…` — W16/W18 DEGRADED can green the kill gate while criterion 13 is partially true | 1 | **NS 13** | NO (draft embraces DEGRADED) |
| `topic:criterion-deferred-next-proposal…` — emitted/queued split amends locked criterion 4 | 1 | **NS 4** | NO (the split IS the draft's position) |
| `topic:confirm-content-proposal-unbound` — confirms not bound to a content hash of what was shown (TOCTOU) | 1 | NS 3, spend invariant | NO |
| `topic:secret-shared-unattributed-who` — G6 FAIL normalizes `who = unattributed(shared_secret)` on spend paths | 1 | **NS 3, 9** | NO |
| `topic:auth-revalidated-spend` — no revoked/expired re-check at confirm/launch/debit seams | 1 | **NS 9** | NO |

MAJORs going directly at NS criteria (the rest are implementability): `altitude-attention-enum-outside-unknown` + `attention-enum-extended-state-unknown` (NS 12, the `unknown` enum breach — flagged independently twice, the closest thing to a 2-agree in the set); `after-attention-external-kill-republished` (NS 12/13 — stale badge after external kill); `all-g4-one-pass-path-skills` (NS 6 — one-skill G4 PASS unlocks all skills); `boundary-deterministic-receipt-reflection` (NS 4); `can-compile-envelope-pre-spend-unconfirmed` (NS 2 — W8 compiles before W9's envelope exists); `criteria-does-fixture-production-prove-slice` (NS 1–4 crediting); `addressed-confirmation-envelope-fatigue` (NS 2); `after-commission-confirm-spend-unbounded` (NS 3); `cross-isolation-ledger-missing-project` (NS 10/13); `control-handback-plane-untrusted` (NS 3/4); `bound-envelope-principal` (NS 2/9); `collision-rule-seat-undefined` (NS 3); `model-oranges-reflection-schema-zero` (NS 4/1); `change-index-non-rebuild-schema-vs` (NS 13 / non-goal 1); `commissionable-dual-json-skills-writer` (NS 6); `backend-fail-fork-hammer-storage` (NS 10); `check-ci-second-theater-writer` (NS 10); `before-calibration-compile-envelope-path` (NS 2); `17-dynamic-scope-wave` (NS 7).

---

## MUST-FIX BEFORE FOREMAN (ranked)

1. **Regenerate `wave-decomposition.json` from the final BEST-DRAFT.md** — 17≠18 waves, wrong numbering from Wave 2 on, and its G4-FAIL text contradicts the draft's HALT decision. Foreman loops over this file; as shipped it builds the weaker plan.
2. **Schedule the two MISSING live-defect fixes** (`waiting_steps`→`enrichForRaise`, `precomputeBriefCache` on attention change) into W15/W16 with tests — MP P9 deliverables, currently nowhere.
3. **Resolve criterion 4** — John amends/annotates the NS or the draft emits a non-spending proposal artifact at handback. A locked criterion cannot be re-authored inside a Stage-2 draft.
4. **Restore the `resolveSeats` / subscription-CLI-only seat invariant** to W10 (with the collision predicate defined).
5. **Disposition the dropped MP P6 and P4 machinery** — either add waves (or W12/W8 deliverables) for intent-record launcher, outbox/`status_flip` writer, run-scoped capabilities, gate-surfacing, and the Face-compile projection, or record explicit descopes John signs.
6. **Resolve the criterion-12 `unknown` enum breach** (NS amendment or remap) — flagged twice independently.
7. **Close the four highest-leverage BLOCKERs in the draft text:** complete the DAG edges; name the `publishAttention` triggers (incl. reopen/reconcile republish); pick ONE A4 atomicity mechanism; add the early SC6 feasibility verdict after W4+W5.
8. **Rule that DEGRADED cannot green the criterion-13 kill gate without an explicit John decision** (aligns W16/W18 with Decision 2's actual text).
9. **Auth hardening trio** (revalidation at spend seams; content-hash-bound confirms; unattributed-`who` policy) — or an explicit accepted-risk record.
10. **Smaller restorations:** I52 scaffold-exemption renderer test into W17; `seen`-receipt + heal-before-brief into W14; event-kind allow-list versioning (`scaffold_proposal`/`reflection_receipt`) into W6; W12 bound to the existing `roadmap.mjs` projection; get the plan STAMPED (judge NOT_CONVERGED, 7 fresh-eyes BLOCKERs).

**Bottom line:** the criterion→wave spine is sound (no unbuildable promises, no bloat waves, refuted ideas dead, all three gate decisions present with mechanical gates), but the machine artifact Foreman consumes disagrees with the human-lockable text, two of the three chartered defect fixes vanished in decomposition, and one locked criterion has been quietly rewritten. Fix items 1–3 are non-negotiable before any Foreman handoff; 4–8 should be closed or explicitly signed off by John.
