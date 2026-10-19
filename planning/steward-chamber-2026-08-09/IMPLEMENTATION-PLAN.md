# Crucible-planned project — Implementation Plan (Foreman-ready)
# LOCKED 2026-08-09 by John (conditional approval resolved by the Fable
# verification review; verdict YES-WITH-NOTED-RISKS; risks folded below as
# V1-V6 — the "Verification fold" section at the end AMENDS the named waves
# and is NORMATIVE plan text, equal in authority to the wave bodies.)

test-command: node scripts/run-all-tests.mjs

**North Star:** MASTER PLAN LOCKED 2026-08-09 by John ("lock plus hardening fold") — full file: C:/dev/Ecgberht/planning/steward-assessment-2026-08-08/crucible-s4/MASTER-PLAN-LOCKED.md. The NORTH STAR is the plan's own header block; the UI spec is C:/dev/Ecgberht/planning/steward-assessment-2026-08-08/mockups.html sections M1 + overlays + deliv (markup/classes normative; inventing different UI is a defect). Settled-brief context:

# Stage 4 — Crucible brief (SETTLED by John 2026-08-09, "carry on")

**NORMATIVE INPUTS (bound by path — the build may not invent UI):**
- `C:\dev\Ecgberht\planning\steward-assessment-2026-08-08\mockups.html`
  §M1 + §overlays + §deliv — markup/classes are the UI spec (M1 v2, LOCKED).
- `C:\dev\Ecgberht\planning\steward-assessment-2026-08-08\S3-REFINED-PROPOSAL.md`
  — E1–E9 are acceptance criteria; the ease metric is instrumented.
- Reference behavior: the Stage-2 Fable-driver session
  (`C:\dev\MBA Teaching AI\MBA Teaching with AI\journal\0001-…md`).

**NORTH STAR (the build's):** The Anchor project-level steward chamber is
rebuilt to the locked M1 "Mission Flow" mockup on the EXISTING Ecgberht
engine. Opening the Seal paints in under 2 seconds from the ledger with
zero model calls. The rail IS the declared pipeline: typed edges, per-step
yields, the live ⏱ table inside the running step, a declared deliverable
that goes live when it lands. The steward speaks first and drives; gates
are serialized prose cards; the STATUS and REFINE-THE-PLAN overlays behave
as drawn. E1–E9 hold — E1 (telemetry-injected visibility + answer-last),
E2 (worktree sweep before re-pay), E3 (resurrection-regression diffs) are
ENGINE-ENFORCED. The ease metric (overhead messages/session) is counted
and reported at campaign close. NON-GOALS: no engine-spine changes
(ledger/receipts/envelopes/reflection/autonomy rails stay as-is); no UI
beyond the mockup; no High Seat/portfolio work; no new commission lanes;
the bottom run tiles are RETIRED.

**BUILD-vs-WIRE honesty (much exists — rearrange, don't reinvent):**
ALREADY BUILT (wire into M1): run_pulse endpoint (⏱ scan + North-star
parse), step_detail/step_note bridge + endpoints, status_flip on produced
runs, compose-first directive cards, reflection + findings ledger, live
status line, paced-PTY writes, campaign auto-commit.
NOT BUILT (real new code): deterministic-first chamber render (<2s, no
model call), pipeline EDGES + artifact contracts + declared-deliverable
object on the scaffold, per-skill rolling ETA medians, E1's turn gate,
E2's ingest sweep, E3's correction-ledger diff, the ease-metric counter,
M1's flow-rail render + overlays as drawn, tile retirement.

**Repos:** Anchor (anchor_gui.py, static/project-window.*) + Ecgberht
(engine/*, scripts/*-bridge.mjs). Single-writer law on roadmap_events
holds; auth-ON assertions required (the surface shipped broken twice
auth-off).

**Run:** Crucible Stage 1 (Master Plan) headless via
`crucible/bin/_steward_redesign_stage1.mjs`, regular tier, cross-family
per prefs; output lands in `crucible-s4/` beside this file. John approves
the Master Plan, then Stage 2 → Foreman.


## Success criteria
- C1 Instant open — done-when: performance marks bracket the paint (mark 'seal-open' at the Seal click, mark 'seal-painted' on the first frame after the full M1 shell commits) and CI asserts seal-painted minus seal-open < 2000ms from ledger/run-record/reflection/roadmap projections alone; zero model calls until John speaks is asserted by BOTH a network/API trace (no model endpoint hit) AND a process-spawn audit (no model-CLI child process spawned during open — a spawn, not just a network hit, fails). The FIRST SEAL AFTER A DEPLOY binds exactly ONE named behavior — drawn-degraded-until-rebuilt (chosen over auto-rebuild-in-budget and operator-pre-flight): an open that finds sidecar projections absent or schema-stale paints the drawn degraded-rail state within the SAME <2s and zero-model-call bounds and surfaces the explicit W5 cold-open rebuild affordance; an inline rebuild on the open path is a test failure. Falsified by the W6 first-open-after-deploy CI test (projections deleted, Seal opened, degraded paint asserted under both bounds with the rebuild affordance present). The NS gloss ('paints from the ledger' = paints from projections; absent projections paint degraded until the rebuild runs) is routed to John as a recorded gloss row in the W1 batched amendment gate. Instruments: W6 budget + trace + spawn-audit + first-open-after-deploy CI tests; re-verified in W12.
- C2 The flow rail is the pipeline: versioned JSON-schema manifest (F2) with typed edges + declared deliverable; done-step yields with report links; run_pulse re-homed into the running step; per-skill rolling-median ETAs guarded at n>=3.
- C3 The steward drives: template-contract situation brief on open (stand / running-and-doing-what / one next move / goal-guard line), compose-first directive card pushes it.
- C4 E1 engine-enforced: telemetry-clock injection of the status table + footer, and the turn-completion hook refusing to close on an unanswered ratified question (the ratified bound is a recorded NS amendment, F7).
- C5 E2 engine-enforced: died/quiet/timeout triggers the two-tier containment-checked worktree sweep (F4: symlink- and junction/reparse-resolved, worktree/project containment, unclaimed listed never executed) whose card must be BOUND into the queue before any re-commission can enqueue.
- C6 E3 engine-enforced: resumed/re-briefed rewrites diff against the triaged correction ledger with positive containment assertions; a regression blocks the handback with a named finding; unassertable entries honestly demoted in every report.
- C7 Prose gates serialized with preference preload and mid-flight re-brief (mode fixed by the Phase-0 inbox audit; boundary-mode honesty drawn into the confirm card).
- C8 The ease metric live from the first input-taking surface with the pre-registered FROZEN classifier; the Stage-2 baseline is RE-SCORED by running the same frozen classifier of record over the Stage-2 reference-session transcript (re-score protocol, recorded before campaign close) so the 5->0 comparison is same-ruler — if the transcript cannot be re-scored, the numeric comparison is reported as descriptive only and the verdict falls back to John's audit alone. Campaign-close report requires John's one-pass audit. Auth-ON everywhere; state-changing surfaces get the F6 CSRF-class assertion set. Instruments: W3 frozen classifier fixtures, W8 live logging, W12 re-scored report; home W8, re-verified W12.
- C9 Mockup fidelity (kill gate) — done-when: the DOM/class structure of every painted chamber surface diffs mechanically green against the SIGNED amended mockups.html (M1/overlays/deliv), pinned to the post-amendment markup hash recorded when John signs the W1 batched amendment gate; the diff co-lands with the FIRST painted markup (W6 slice subset, then W7 full M1, W9 overlays) and any deviation fails CI unless logged through the amendment gate; the diff hard-fails if the signed hash is absent or mismatched, so no mockup-verbatim claim can precede the signature. Instruments: W6 slice DOM-diff, W7 full-M1 DOM-diff, W9 overlays DOM-diff; re-verified in W12.
- C10 Security folds engine-tested — done-when: F3 deliverable-action execution bounds (symlink-resolved containment, pinned cwd, spawn with shell:false and list-argv, CODE-OWNED verb allow-list frozen in source — never config or data an agent can write) pass an escape-fixture suite ('..', absolute path, symlink, Windows junction/reparse point) plus hostile-argv cases (embedded quotes, spaces, '&', '|', ';', newline, NUL — each asserted inert); the F5 hostile-string DOM suite is green over a REGISTERED slot inventory with a growth rule (CI fails when an agent-influenced DOM slot is added without a hostile-fixture row); and F6 auth-ON + CSRF-class assertions cover the FULL both-tree living routes inventory (Anchor handlers AND Ecgberht bridge verbs) with the threat model SPLIT by caller class (browser: token + POST-only + CSRF-refusal; bridge/CLI: auth still required and asserted NON-exempt), proven red-to-green (each route's auth test shown FAILING auth-off before passing auth-on) — for EXISTING routes in W3 and for every NEW mutator in its landing wave (W8-W11), not just new-test tagging. Instruments: W3 living inventory + red-to-green pass, W8-W11 per-wave red-to-green, W9 F3 escape + hostile-argv suites + F5 slot-registered hostile-string suite; re-verified in W12.
- C11 Tile retirement on signed parity — done-when: the bottom run tiles are removed ONLY after the tile-affordance functional inventory + parity map (landed in W9, BEFORE the STATUS overlay is called complete) maps every affordance to a live rail/STATUS equivalent or a John-signed accepted loss, and rail+STATUS parity is SIGNED; no tile code is deleted before the signature. Instruments: W9 inventory + parity map, W12 signed-parity retirement gate; re-verified in W12.
- C12 Build-vs-wire honesty — done-when: run_pulse/step_detail/step_note/status_flip/compose-first/reflection/findings/live-line/paced-PTY/auto-commit are WIRED and re-homed, never reimplemented, each resolved through the wire-homing registry (owner file + grep-verifiable symbol, M1 consumer, committed-fixture or hermetic-replay characterization oracle — a live run on John's desktop is never the oracle — wave of record, and a kill branch symmetric to W2's), with parity proven against the committed oracles BEFORE any existing code is deleted; deterministic-first render, manifest+edges+deliverable schema, ETA medians, E1 turn gate, E2 sweep, E3 diff, ease counter, M1 render + overlays, tile retirement are NEW code. Instrument: the wire-homing registry CI symbol-check (every row's symbol grep-resolves in its owner file) + W7 committed-fixture characterization-parity tests plus the no-deletion-before-parity rule in every wire wave; re-verified in W12.
- NON-GOALS (restate in every wave): no engine-spine changes; no UI beyond the amended locked mockup; no High Seat work; no new commission lanes; tiles retired only per C11.
- Two-repo execution contract: Foreman drives the ANCHOR git root (C:\dev\Anchor) — its per-wave commits land there. `node scripts/run-all-tests.mjs` is a MULTI-ROOT runner LIVING IN THE ANCHOR ROOT, DELIVERED BY W1: it runs the Anchor suite (anchor_gui.py, static/project-window.*) AND spawns the sibling Ecgberht suite (C:\dev\Ecgberht\scripts\run-all-tests.mjs — scripts/*-bridge.mjs seam wrappers; engine/* spine untouched) and exits nonzero if EITHER tree's NS-critical suite fails. Foreman mutates Anchor first (chamber host), Ecgberht second (bridge-seam wrappers only), in that order within any wave touching both; Ecgberht-side changes are committed in the Ecgberht root with a wave-tagged message (`steward-m1 W<k>: ...`) recorded in that wave's deliverable record, and a both-repo wave is done only when BOTH commits exist. roadmap_events keeps exactly ONE writer, NAMED: engine/roadmap.mjs :: appendRoadmapEvent / appendRoadmapEventDurable — enforced by a DENY assertion (a static scan over both trees failing any chamber/bridge source that appends roadmap_events outside that module, plus the W4 runtime zero-spine-write tests).

### Criteria ledger (binding rule)

A wave's "Serves" tag may cite only IDs defined in this section (C1–C12, E1–E9). An ID cited anywhere in this plan without a falsifiable row here is a plan defect and a BLOCKER by this plan's own rule.

C-instrument map (each re-verified by W12's cross-criterion audit + release bundle): C1 -> W6 budget/trace/spawn + first-open-after-deploy tests; C2 -> W4 manifest-schema lint + W7 rail render, DOM diff, ETA tests; C3 -> W5 brief-precompute tests + W10 E4 template fixture; C4 -> W8 joint negative-path test; C5 -> W10 E2 enqueue-gate test; C6 -> W11 E3 handback-block test; C7 -> W10 E5 serialization + W11 E6/E7 tests; C8 -> W3 frozen classifier + W8 live count + W12 re-scored report; C9 -> W6/W7/W9 hash-pinned DOM diffs; C10 -> W3 living routes inventory red-to-green + W8-W11 per-wave red-to-green + W9 F3 escape/hostile-argv + F5 slot-registered suites; C11 -> W9 inventory/parity map + W12 signed retirement; C12 -> W7 committed-fixture characterization parity + the wire-homing registry CI symbol-check.

Each E-criterion is a top-level acceptance criterion with a named instrument, home wave, and W12 re-verify row:

| ID | Criterion (falsifiable done-when) | Instrument (named test) | Home | Re-verify |
|----|-----------------------------------|-------------------------|------|-----------|
| E1 | A steward turn structurally CANNOT close while a ratified direct question id lacks a typed answer-reference; ⏱ table + footer inject on the telemetry clock with zero model involvement | W8 joint negative-path test (blocked close, named finding) + telemetry-injection DOM test | W8 | W12 |
| E2 | A re-commission CANNOT enqueue before the containment-checked sweep card is bound into the queue | W10 enqueue-gate negative-path test on the W2 seam | W10 | W12 |
| E3 | A resumed/re-briefed rewrite that regresses a predicate-bearing correction CANNOT hand back; unassertables demoted in every report | W11 handback-block negative-path test + coverage report | W11 | W12 |
| E4 | Every directive/gate card is compose-first prose with the question LAST; a bare option dialog fails CI | W10 template fixture suite | W10 | W12 |
| E5 | Gates serialize FIFO; only the head card renders; resolve/skip releases the next | W10 head-only serialization test | W10 | W12 |
| E6 | The preload projection lists exactly the loaded preference entries; a missing entry is a diffable failure | W11 preload diff test | W11 | W12 |
| E7 | Mid-flight re-brief reaches the running commission in the W2-audited mode with NO relaunch | W11 re-brief test per audited mode | W11 | W12 |
| E8 | Brief precompute lives in the steward-plane chamber sidecar; zero spine writes from chamber code | W5 sidecar-derivation test + W4 zero-spine-write assertions | W5 | W12 |
| E9 | Reflection and delta verification stay distinct stages; run records beat reflection claims (last-writer-wins) | W4 collapsed-stage manifest-lint refusal + W5 died-after-last-reflection fixture | W4/W5 | W12 |

### Wire-homing registry (C12 — the ten wired items)

Committed in W1 as versioned machine-readable data (`wire-homing.json`, schema_version + named owner file) and CI-gated from W1 forward: a check greps each row's owner file for its symbol and fails naming the row when a symbol moves or vanishes — a living registry, never a Phase-0 snapshot. Each row's oracle and parity tests land in the row's wave of record. Every row carries a kill branch symmetric to W2's: if the owned code cannot serve the M1 consumer without behavior change, the wave HALTs with a scoped wire-amendment to John re-costing that row as a REWRITE — never a silent reimplementation.

| # | Item | Owner (file :: symbol) | M1 consumer | Characterization oracle (committed) | Wave |
|---|------|------------------------|-------------|--------------------------------------|------|
| 1 | run_pulse | Anchor anchor_gui.py :: handle_ecgberht_run_pulse (GET /api/ecgberht/run_pulse) | running-step ⏱ slot (tiles keep consuming until C11) | committed pulse-stream replay fixtures | W7 |
| 2 | step_detail | Ecgberht scripts/seal-chamber-bridge.mjs :: buildStepDetailPayload + Anchor :: handle_ecgberht_step_detail | rail step expansion | committed payload fixtures | W7 |
| 3 | step_note | Ecgberht scripts/seal-chamber-bridge.mjs :: buildStepNotePayload + Anchor :: handle_ecgberht_step_note | rail step note affordance | committed payload fixtures | W7 |
| 4 | status_flip | Ecgberht engine/exec-insession.mjs status_flip emission + engine/job-lifecycle.mjs, through the single writer | rail per-step state render | recorded roadmap-event fixtures | W7 |
| 5 | compose-first | Ecgberht engine/steward-conversation.mjs :: buildStewardPrompt (COMPOSE-the-directive contract) + parseStewardReply (commission_directive) | W10 directive-card template slots (composer WIRED; card template NEW) | committed steward-reply JSON fixtures | W10 |
| 6 | reflection | Ecgberht engine/handback-ingest.mjs :: emitReflectionReceipt | W5 brief precompute + rail yields | the module's committed golden emitter fixtures (loadGolden / goldenEmitterInputs) | W5 |
| 7 | findings ledger | Ecgberht engine/step-findings.mjs | chamber findings surfaces + E3 triage input | committed ledger fixtures | W11 |
| 8 | live-line | Ecgberht engine/status-outbox.mjs + engine/anchor-status-outbox-surface.mjs | M1 live status line slot | committed outbox fixtures | W8 |
| 9 | paced-PTY | Anchor pty_manager.py :: write (>512-char payloads chunked at 256 chars, paced) | say-box talk path + re-brief writes | hermetic PTY-echo replay fixture | W8 |
| 10 | auto-commit | Anchor commission_session.py :: commit_campaign_state (called from the scaffold-confirm handler) | campaign banking on chamber confirms | hermetic temp-repo git fixture | W10 |

### Living-registry law

Every inventory this plan creates — the W1 provenance table and state matrix/rulebook, the W3 both-tree routes inventory, this wire-homing registry, the W9 F5 slot inventory and tile-affordance inventory + parity map — is a VERSIONED machine-readable artifact (schema_version + named owner file) with a CI gate (coverage lint or diff guard) that keeps it true as code moves. A registry without its CI gate is a plan defect and a BLOCKER by this plan's own rule.

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — W1 Phase-0 Ground Truth: provenance table, state matrix + rulebook, collision rule

**Intent:** Make the data and the spec provably complete before anything paints: a machine-checked provenance table mapping every M1 datum to a concrete ledger/run-record/reflection/roadmap field (roadmap IS in the open read set), a reachable-state matrix vs mockups.html with an in-repo derivation rulebook, all undrawn states batched into ONE mockup-amendment gate for John, and the NS-hard collision rule published. Serves C1/C9; blocks all UI waves until green. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Provenance table as machine-readable data (every M1 cell -> source field) + CI lint failing on any unsourced cell; Reachable-state matrix (drawn / derivable / undrawn) + in-repo derivation rulebook + lint requiring a rule per derivable state; Batched mockup-amendment gate artifact enumerating ALL undrawn states (died run, stacked overlays, zero-history ETA, empty campaign, held gate, pre-emission open, degraded rail) for John's single HALT — John's signature on this gate records the POST-AMENDMENT markup hash of mockups.html (M1/overlays/deliv) in the decision log; every later mockup-verbatim claim and C9 DOM diff pins to that hash, and no wave may claim mockup-verbatim before the signature lands; C1 deploy-gloss row (drawn-degraded-until-rebuilt on the first Seal after a deploy) included in the batched gate for John's signature; NS-hard collision rule entry in the decision log (non-tradeable properties, HALT-to-John on collision); Written NS-amendment request template for any deterministically-unreadable roadmap datum (never a silent drop); Multi-root test runner DELIVERED in the Anchor root (scripts/run-all-tests.mjs — the plan's test-command): runs the Anchor suite and spawns the sibling Ecgberht suite (C:\dev\Ecgberht\scripts\run-all-tests.mjs) per the two-repo execution contract, exiting nonzero if either tree fails, so the gate exists from the first wave; Wire-homing registry (wire-homing.json) committed with all ten rows and their grep-verifiable symbols, its CI symbol-check active from this wave forward

**Depends on:** —

**done-when:** CI lints pass with zero unsourced provenance cells and a derivation rule for every derivable state, and the undrawn-state set is enumerated in exactly one batched mockup-amendment gate artifact with the NS-hard collision rule published in the decision log; the gate artifact specifies that John's signature records the post-amendment markup hash all later C9 DOM diffs pin to. The batched gate includes the C1 deploy-gloss row; the multi-root runner runs both trees from the Anchor root; and the wire-homing registry's CI symbol-check is green.

- **Given** the provenance table with one M1 datum cell left unsourced, **when** the provenance lint runs in CI, **then** the build fails naming the unsourced cell, and UI waves stay blocked
- **Given** a state classified as mechanically derivable in the matrix, **when** the rulebook lint runs, **then** a missing derivation rule fails the suite so two developers derive the same UI
- **Given** the full undrawn-state enumeration, **when** Phase-0 closes, **then** the states appear in exactly ONE batched mockup-amendment gate artifact awaiting John, not scattered asks

## Wave 2 — W2 Phase-0 Seam-Proof Spike + Inbox Audit

**Intent:** Prove the three enforcement seams exist on the EXISTING engine before any rendering work, each pinned to grep-verifiable symbols: leg a on the steward turn path (Ecgberht engine/steward-conversation.mjs :: converse, consumed by scripts/seal-chamber-bridge.mjs :: buildConversePayload, served by Anchor anchor_gui.py :: handle_ecgberht_converse at POST /api/ecgberht/converse), leg b on the enqueue path (Anchor :: handle_ecgberht_commission_go at POST /api/ecgberht/commission_go -> commission_session.py :: confirm_and_launch -> scripts/commission-run-bridge.mjs, commissions built by engine/commission.mjs :: buildCommission), leg c on the handback path (engine/handback-ingest.mjs :: ingestHandback / ingestValidatedHandbackBody) — using only existing extension points — and fix Phase-3's re-brief design by auditing the commission-runtime message channel. This is the plan's seam-proof gate (Wave-0 in effect: its legs consume nothing from W1's outputs and run before ANY rendering spend); every leg records an explicit PASS/FAIL outcome naming module path + symbol (a seam described by role rather than symbol is itself a FAIL), and the kill branch is defined — any FAIL halts the build and routes to the John-signed third-outcome gate in this wave's deliverables; no later wave starts. Serves C4/C5/C6/C7 by construction-order. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Seam test leg a: chamber-level wrapper on the converse return path (engine/steward-conversation.mjs :: converse -> scripts/seal-chamber-bridge.mjs :: buildConversePayload) blocks steward turn completion (passing test); Seam test leg b: wrapper on the commission-go path (handle_ecgberht_commission_go -> commission_session.py :: confirm_and_launch -> scripts/commission-run-bridge.mjs) gates a re-commission card enqueue (passing test); Seam test leg c: wrapper on engine/handback-ingest.mjs :: ingestHandback / ingestValidatedHandbackBody intercepts a handback (passing test); Route/path inventory: every route by which a steward turn can close, a re-commission can enqueue, or a handback can land (chamber UI, bridge scripts, CLI verbs, engine-internal timers) enumerated with proof each crosses the enforced seam — an uninventoried route discovered later is a BLOCKER; Negative tests at the engine/bridge boundary where the chamber is NOT the caller: a bridge-initiated turn close, enqueue, and handback are each blocked by the same seam wrapper; Explicit per-leg PASS/FAIL outcome record naming module path + symbol per seam (role-only description = FAIL) incl. the exercised kill branch; The FAIL branch's John-signed THIRD-OUTCOME gate resolving the ENGINE-ENFORCED-vs-no-spine-change deadlock: for any failed leg John signs exactly one of (1) proceed on the proven wrapper seam, (2) a named bridge-seam extension point added in scripts/seal-chamber-bridge.mjs / scripts/commission-run-bridge.mjs / the handback ingest call site, recorded in the decision log as BRIDGE code, not engine-spine, or (3) an NS amendment relaxing the ENGINE-ENFORCED wording for that criterion — the outcome record names which one John signed; Commission-runtime inbox/message-channel audit with a machine-readable outcome record fixing re-brief mode (live-with-receipt vs next-step-boundary); HALT + seam-amendment request path wired for any failed leg

**Depends on:** W1 Phase-0 Ground Truth: provenance table, state matrix + rulebook, collision rule

**done-when:** All three seam legs (block turn close, gate re-commission enqueue, intercept handback) pass as tests using only existing extension points at their NAMED symbols (converse/buildConversePayload; handle_ecgberht_commission_go/confirm_and_launch; ingestHandback/ingestValidatedHandbackBody), each leg ALSO blocks a non-chamber (bridge-boundary) caller, the route inventory proves every turn-close/enqueue/handback path crosses the enforced seam, the per-leg PASS/FAIL record names module path + symbol with the kill branch exercised in test and the John-signed third-outcome gate defined for any FAIL, and the inbox audit's machine-readable record fixes the Phase-3 re-brief mode.

- **Given** a fixture steward turn ending with an open question id, **when** seam leg a runs, **then** the chamber-level wrapper blocks turn completion using only existing extension points — including when the close is initiated by a bridge-boundary caller rather than the chamber
- **Given** a fixture re-commission card and a fixture handback, **when** seam legs b and c run, **then** the enqueue is gateable at confirm_and_launch and the handback interceptable at ingestHandback; any failed leg HALTs the build before rendering work and routes to the John-signed third-outcome gate (proceed on the proven wrapper / a named bridge-seam extension recorded as bridge code, not spine / an NS-wording amendment)
- **Given** the commission runtime as it exists, **when** the inbox audit runs, **then** a machine-readable record states whether a live re-brief channel exists, fixing Phase-3's design (acknowledgment receipt vs honest next-step-boundary)

## Wave 3 — W3 Phase-0 Enforcement Infra: auth+CSRF fixture, ease classifier, E1 bound parser

**Intent:** Ship the acceptance infrastructure every later surface depends on: the scripted-login auth-ON fixture with the CI coverage rule, the F6 CSRF-class assertion set for state-changing surfaces, the pre-registered ease classifier (rule table + frozen labeled fixtures, John-reviewed before any surface exists), and the deterministic E1 question-parse module with the F7 NS-amendment artifact for John's ratification HALT. Serves C4/C8/C10; the chamber shipped broken twice auth-off. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Scripted-login auth fixture producing a real authenticated session, wired into the test harness; CI rule failing any new-surface test not tagged auth-ON; F6 assertion helpers for state-changing surfaces: token required, POST-only, CSRF-class forged-request-refused test, with the threat model SPLIT by caller class and recorded in the inventory artifact (browser callers: token + POST-only + CSRF-refusal; bridge and CLI callers: auth token still required and asserted NON-exempt — a forged non-browser caller cannot skip the checks); BOTH-TREE living routes inventory as versioned machine-readable data (routes-inventory.json, schema_version + named owner file): every EXISTING Anchor state-changing handler (handle_ecgberht_* and peers) AND every Ecgberht bridge verb (seal-chamber-bridge.mjs modes, commission-run-bridge.mjs verbs), with a CI diff guard failing when a route or verb exists in code without an inventory row; red-to-green pass over every EXISTING inventory row — each route's auth-ON + F6 assertion shown FAILING auth-off, then green auth-on (not just new-test tagging); Ease classifier module + committed rule table (decision/correction/restatement/are-you-working) + frozen labeled fixture set, passing tests; Stage-2 traceability matrix v1: named moments from the reference-session journal mapped to the ease-classifier labeled fixtures and the E1 question-parse fixtures (each fixture cites its journal moment; extended to brief-shape/question-last fixtures in W10); E1 deterministic question parser (terminal-'?' sentences + explicit ask affordance, per-question ids, typed answer-references) with tests; F7 NS-amendment artifact recording the ratified E1 bound for John's ratification gate

**Depends on:** W2 Phase-0 Seam-Proof Spike + Inbox Audit

**done-when:** The auth-ON scripted-login fixture and F6 CSRF assertion set are enforced by a CI coverage rule AND proven red-to-green across the full BOTH-TREE living routes inventory (CI diff guard active, caller-class threat split recorded in the artifact), the pre-registered ease classifier passes its frozen fixture set with every labeled fixture citing its Stage-2 traceability-matrix moment, and the E1 bound parser passes its tests with the F7 NS-amendment artifact prepared for John's ratification HALT.

- **Given** a new-surface test lacking the auth-ON tag, and a state-changing surface without the F6 set, **when** CI runs, **then** the coverage rule fails the suite; state-changing surfaces require token, POST-only, and a refused cross-origin forged request
- **Given** the frozen labeled fixture set, **when** the pre-registered classifier runs, **then** every fixture message classifies per the committed rule table — committed and John-reviewable BEFORE any surface exists, so it can never be tuned to flatter the build
- **Given** fixture text containing terminal-'?' sentences and non-question prose, **when** the E1 bound parser runs, **then** per-question ids emit deterministically, known misses are documented as out-of-scope by agreement, and the ratified bound is recorded as a formal NS amendment (F7)

## Wave 4 — W4 Phase-1 Substrate: event-time projections + versioned manifest schema, lint, hash

**Intent:** Build the deterministic data substrate the 2-second open reads: chamber-local append-only event-time projections (rebuildable derived data, never source of truth — roadmap_events keeps its single writer, zero spine writes), and the chamber-owned sidecar pipeline manifest as a VERSIONED JSON-schema'd document (F2) with typed edges, declared deliverable, per-step yield contracts, commission-time lint, and the receipt-keyed manifest hash whose mismatch renders a named error state. Serves C1/C2/E9. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Chamber-local persisted projection writers (commission start, step yield, deliverable landing, run death) + open-path readers, append-only JSON written atomically (temp + fsync + rename) with a kill-during-write crash test, documented single-writer serialization, and a two-real-process concurrency test asserting no event dropped; In-repo manifest JSON schema file with schema_version + migration-note convention (F2); Commission-time manifest lint refusing NEW commissions without a valid manifest (hard error; campaigns predating the manifest take the W5 brownfield-derivation dual path until derived, and hard-refuse extends to them only after W5 lands) and keeping reflection + delta verification distinct scaffold stages (E9); Manifest hash recorded in the chamber sidecar keyed to the commission id read from EXISTING receipt fields; recompute-and-verify with named mismatch error state; Tests asserting zero receipt-schema / reflection-payload / roadmap_events writes from chamber code, plus the roadmap_events DENY assertion: a static scan over both trees failing any chamber/bridge source that appends roadmap_events outside the NAMED sole writer (engine/roadmap.mjs :: appendRoadmapEvent / appendRoadmapEventDurable)

**Depends on:** W3 Phase-0 Enforcement Infra: auth+CSRF fixture, ease classifier, E1 bound parser

**done-when:** Event-time projection writers/readers and the versioned JSON-schema manifest (F2) pass their tests INCLUDING the named durability gates (atomic temp+fsync+rename kill-during-write crash test; documented single-writer serialization; two-real-process concurrency test with no event dropped); commissioning a NEW scaffold without a valid manifest is refused while pre-existing campaigns route to the W5 derivation dual path; a post-commission manifest edit renders a named hash-mismatch state; and zero spine writes are asserted.

- **Given** a NEW scaffold without a valid sidecar manifest, **when** commissioning is attempted, **then** the commission-time lint refuses with a hard error — never a render-time guess; a campaign predating the manifest routes to the W5 brownfield derivation (derive-or-degraded) instead of a refusal it cannot satisfy
- **Given** a manifest edited after commission, **when** the rail data layer recomputes the hash against the sidecar record keyed to the existing receipt's commission id, **then** a named hash-mismatch error state is produced and the receipt schema is untouched
- **Given** a manifest fixture collapsing reflection and delta verification into one stage, **when** the lint validates against the versioned schema, **then** the manifest is refused (E9's layered-verification discipline holds at the data layer)
- **Given** two real processes appending projection events while a kill lands mid-write, **when** the W4 crash + concurrency tests run, **then** no event is dropped, the interrupted write leaves the prior snapshot readable (temp + fsync + rename), and the documented single-writer serialization holds

## Wave 5 — W5 Phase-1 Substrate: brownfield derivation, reconciliation, brief precompute, cold-open rebuild

**Intent:** Make every REAL campaign openable deterministically: the brownfield derivation builds sidecar manifests from existing scaffold/ledger records (tested against copies of the real on-disk ledgers, degraded-rail state where underivable), the reconciliation pass makes run records last-writer-wins over reflection claims across the reflection+roadmap+run-record read set, the brief projector precomputes situation-brief fields at reflection-landing time, and the one-time cold-open rebuild covers campaigns predating the projectors. Serves C1/C3/E8/E9, zero spine writes. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Deterministic re-runnable brownfield manifest derivation, chamber-side reads only, fixture-tested against copies of every real live-campaign ledger; Degraded-rail-state mapping for underivable campaigns (the drawn state from the W1 amendment batch), never a guess; Reconciliation pass over last reflection + roadmap + run records with last-writer-wins run states; died-after-last-reflection fixture; Brief precompute projector subscribed to existing reflection output deriving stand/running/next-move/goal-guard fields into the chamber projection (steward-plane sidecar, E8 separation); One-time cold-open rebuild command deriving full projections from the ledger, incl. real pre-emission reflection fixtures; Fixture-size record: the largest real ledger's measured size (event count, MB on disk, run-record count) committed to a fixture manifest — W6's budget fixtures MUST be generated at >= 2x each measured number

**Depends on:** W4 Phase-1 Substrate: event-time projections + versioned manifest schema, lint, hash

**done-when:** Every real live campaign either derives a deterministic sidecar manifest or maps to the drawn degraded-rail state; reconciliation + brief precompute pass the died-after-last-reflection and pre-emission fixtures; the cold-open rebuild command works; and the fixture-size record (events / MB / run-record counts of the largest real ledger) is committed for W6's >=2x budget fixtures — all with zero spine writes.

- **Given** copies of every real live-campaign ledger on disk (not synthetic shapes), **when** the brownfield derivation runs, **then** each campaign yields a deterministic manifest or the explicitly drawn degraded-rail state, with zero spine writes
- **Given** a run that died after the last reflection, **when** reconciliation and brief precompute run, **then** the precomputed brief cites the reconciled record and says the run died — reflection text is narrative color only (E9)
- **Given** a campaign predating the projectors, **when** the one-time cold-open rebuild runs, **then** the full chamber projection derives from the existing ledger, and pre-emission reflections either derive deterministically or paint the drawn degraded brief

## Wave 6 — W6 Phase-1 Proof: painted M1 vertical slice, <2s + zero-model-call CI

**Intent:** Prove C1 on the PAINTED surface, not a headless read: a thin full-markup M1 shell over the W4/W5 projections, open-to-paint measured on John's actual machine on a real campaign with a dated decision-log entry, the <2s budget test at synthetic months-scale in CI (structural fixes — ledger tail-read, capped run-record reads — before any cache), and the zero-model-call network-trace assertion running on every chamber change from here forward. Auth-ON per W3. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Vertical-slice M1 mount: thin verbatim-markup shell over projections in Anchor (anchor_gui.py + static/project-window.*), DOM/class-diffed against the SIGNED amended mockup for the slice's rendered subset from FIRST paint (the C9 kill gate co-lands with the first painted markup; W7 extends it to full M1); CI <2s open-budget test instrumented with performance marks ('seal-open' at the Seal click -> 'seal-painted' at first full-frame commit; asserted delta < 2000ms) at NAMED fixture sizes: >= 2x the W5-recorded largest real ledger in events, MB, and run records, concrete numbers committed in the fixture manifest; CI zero-model-call test on the painted Seal: network/API trace PLUS a process-spawn audit (no model-CLI child process spawned during open), wired to run on every chamber change; First-open-after-deploy CI test (C1's drawn-degraded-until-rebuilt binding): with sidecar projections deleted or schema-stale (simulated fresh deploy), the Seal paints the drawn degraded-rail state within the SAME <2s and zero-model-call bounds and surfaces the explicit W5 cold-open rebuild affordance — an inline rebuild on the open path fails the test; Dated first-open decision-log entry naming the real campaign, the machine, and the measured mark-delta paint time; Structural read-path fixes (tail-read from last snapshot line; run-record reads capped to active scaffold steps with a hard numeric backstop of 200 reads per open and a refusal path — exceeding the cap renders the drawn degraded-rail state, never an unbounded read). This wave is the EARLY MEASURED PAINT MILESTONE: no Phase-2 wave starts until it is green

**Depends on:** W5 Phase-1 Substrate: brownfield derivation, reconciliation, brief precompute, cold-open rebuild

**done-when:** The painted vertical-slice M1 Seal opens with a measured 'seal-open'->'seal-painted' mark delta under 2 seconds on a real campaign (dated decision-log entry recorded); the <2s budget test at the committed >=2x-real fixture sizes, the zero-model-call network-trace test, the process-spawn audit, AND the first-open-after-deploy degraded-paint test are in CI and green; and the slice-subset DOM/class diff against the signed amended mockup is green. No Phase-2 wave starts before this milestone.

- **Given** a real campaign on John's actual machine, **when** the Seal opens on the vertical-slice shell, **then** the 'seal-open' -> 'seal-painted' mark delta is <2s from ledger/run-record/reflection/roadmap projections alone, a dated first-open entry lands in the decision log, and the slice's rendered markup subset diffs green against the signed amended mockup (C9 co-lands with first paint)
- **Given** the network/API trace harness AND the process-spawn audit around the painted Seal, **when** the Seal opens and no user message is sent, **then** zero model endpoints are hit and zero model-CLI child processes are spawned until John speaks — asserted by CI tests that run on every subsequent chamber change
- **Given** synthetic ledger fixtures generated at the committed sizes (>= 2x the W5-recorded largest real ledger in events, MB, and run records), **when** the <2s CI budget test runs, **then** it passes using structural fixes only, the run-record read cap refuses into the drawn degraded-rail state when exceeded, and any cache would require an explicit John-classified rebuildable-cache decision, never smuggled in

## Wave 7 — W7 Phase-2 Rail: verbatim M1 mount + DOM-diff kill gate, run_pulse re-home, ETA medians

**Intent:** Harden the slice into the full M1 rail rendered ONLY from manifest+projections: style-isolated mount importing the mockup CSS verbatim with the mechanical DOM/class diff in CI (the mockup kill gate — deviations only via the W1 batched amendment gate), typed edges and yield-contract renders with a labeled 'yield missing' state, run_pulse characterized then split into a data core with tile + chamber consumers (parity against committed replay fixtures before any deletion, per the wire-homing registry), and the per-skill rolling-median ETA module guarded at n>=3. Serves C2/C9/C12 (wire, don't reinvent). Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Full M1 mount in a style-isolated container (shadow root / scoped stylesheet) importing mockup CSS verbatim; CI DOM/class-structure diff test against mockups.html §M1 pinned to the SIGNED post-amendment markup hash recorded at the W1 gate (kill gate, extending the W6 slice diff to the full mount; the diff hard-fails if the signed hash is absent or mismatched, so no mockup-verbatim claim can precede the signature; deviations require a logged spec amendment); Rail renderer from manifest+projections: typed edges, rulebook-derived per-step states, done-step one-line yields with report links, labeled 'yield missing' state; run_pulse characterization tests + split into data-producing core with two consumers (existing tiles, chamber step slot), parity proven against COMMITTED pulse-stream replay fixtures (recorded once via the record-steward-fixture.mjs pattern and checked in — a live run on John's desktop is never the oracle) BEFORE any deletion, with this wave's wire-homing rows (run_pulse, step_detail, step_note, status_flip) resolved and the registry CI symbol-check green (C12); Per-skill rolling-median ETA module over the project's own run records, n>=3 guard, drawn 'no history yet' fallback, labeled basis

**Depends on:** W6 Phase-1 Proof: painted M1 vertical slice, <2s + zero-model-call CI

**done-when:** The full style-isolated M1 rail renders solely from manifest+projections with the CI DOM/class diff green against the hash-pinned signed §M1, run_pulse parity is proven against the committed replay fixtures before anything is deleted with the wire-homing registry check green for this wave's rows, and ETAs honor the n>=3 guard with labeled basis.

- **Given** the mounted chamber and the SIGNED amended mockups.html §M1 (post-amendment markup hash recorded at the W1 gate), **when** the CI DOM/class diff runs, **then** structure and classes match verbatim against that hash-pinned spec, an absent or mismatched hash hard-fails, and any deviation fails CI unless logged through the batched mockup-amendment gate
- **Given** committed pulse-stream replay fixtures recorded from real runs, **when** run_pulse splits into a data core with tile and chamber consumers, **then** characterization tests prove parity against the committed fixtures before any code is deleted; infeasibility triggers the wire-homing kill branch — HALT + a scoped wire-amendment to John re-costing the row as a rewrite, never a silent reimplementation
- **Given** a skill with fewer than 3 run records, **when** the ETA module renders, **then** the drawn 'no history yet' presentation shows — never a one-record extrapolation; at n>=3 the basis is labeled (e.g. 'median of 4 runs')

## Wave 8 — W8 Phase-2 Talk: E1 co-landed whole, say box live, ease count starts

**Intent:** The first talking, input-taking surface ships WITH its enforcement, whole not in halves: the in-step live status table + campaign footer inject on the telemetry clock from the re-homed Anchor terminal-session emitter (never model output), the steward turn-completion hook on the W2-proven seam per the W3-ratified bound wires to the say box's talk path so a turn structurally cannot close on an unanswered question, and the pre-registered ease classifier goes live logging every say-box message. Serves C1/C4/C8; talk path gets F6 state-changing assertions. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Telemetry-clock injection of the in-step ⏱ status table + campaign footer from the re-homed emitter (zero model involvement); Say box wired under the last message per M1, writing through the EXISTING paced-PTY path (pty_manager.py :: write) with this wave's wire-homing rows (live-line via engine/status-outbox.mjs + anchor-status-outbox-surface.mjs, paced-PTY) resolved against their committed oracles; auth-ON + F6 (token, POST-only, CSRF-refusal) on the talk path shown RED-TO-GREEN in this wave (failing auth-off before green auth-on) with its row added to the living routes inventory before the surface merges; Steward turn-completion hook on the W2-proven converse seam enforcing the ratified bound (typed answer-references at turn close); Joint landing-wave negative-path test: turn closed on an open question id -> engine blocks with named finding; Ease classifier live: every say-box message logged with classification + the rule that fired, counting from this surface onward

**Depends on:** W7 Phase-2 Rail: verbatim M1 mount + DOM-diff kill gate, run_pulse re-home, ETA medians

**done-when:** The ⏱ table and footer inject on the telemetry clock with zero model involvement, the turn-completion hook blocks a close on an unanswered ratified question with a named finding (joint negative-path test green), and every say-box message is classified live by the pre-registered rules.

- **Given** a running step with the Seal open, **when** the telemetry clock ticks, **then** the ⏱ table and campaign footer update in the DOM from the re-homed emitter with zero model involvement
- **Given** a steward turn ending while a direct question id from John lacks a typed answer-reference, **when** the turn attempts to close, **then** the engine structurally blocks the close with a named finding (E1 negative path, per the ratified F7 bound)
- **Given** the say box as the first shipped input-taking surface, **when** John sends any message, **then** the pre-registered classifier logs a classification with the rule that fired — the campaign-close count covers the whole surfaced period

## Wave 9 — W9 Phase-2 Close: deliverable action registry (F3), DOM injection law (F5), STATUS overlay

**Intent:** Complete Phase 2: the type-aware deliverable action registry with explicit F3 execution bounds (symlink-resolved containment, pinned cwd, list-argv from fixed verbs, verb allow-list, labeled inert fallback) and live engine-fed deliverable push on the injection clock; the F5 DOM injection law (textContent/attribute-safe setters only, link-scheme validation) with the hostile-string CI suite; and the STATUS overlay exactly as drawn — shipping WITH the first rail because tile retirement is gated on rail+STATUS parity. Serves C2/C10/C11. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Chamber-local deliverable action registry (type -> open file / open report / run command) with F3 bounds — spawn with shell:false and list-argv from a CODE-OWNED verb allow-list frozen in source (never config or data an agent can write) — a named escape-attempt test suite ('..', absolute path, symlink, Windows junction/reparse-point fixtures) plus hostile-argv cases (embedded quotes, spaces, '&', '|', ';', newline, NUL — each asserted inert), and labeled inert state with named reason for unknown/out-of-bounds; Deliverable-landing live push into the open session on the injection clock (engine-fed, no reopen, never model-remembered); F5 injection discipline across all agent-influenced strings + hostile-string fixture suite (markup/script/handler payloads in every slot) green in CI over a REGISTERED slot inventory (versioned, owned) with a growth rule: CI fails when an agent-influenced DOM slot is added without a hostile-fixture row; STATUS overlay: latest status table + remaining steps with median ETAs, DOM-diffed against the hash-pinned mockups.html overlays section; Tile-affordance functional inventory + parity map (log links, kill control, historical runs, raw output -> live rail/STATUS equivalent or proposed accepted loss) as a versioned owned artifact landed BEFORE STATUS is called complete — W12 retirement may only execute against this map once signed (C11); Auth-ON + F6 shown red-to-green in this wave for every NEW mutator (deliverable actions, overlay endpoints) with rows added to the living routes inventory; zero-model-call and <2s CI tests kept green

**Depends on:** W8 Phase-2 Talk: E1 co-landed whole, say box live, ease count starts

**done-when:** The deliverable action registry enforces the F3 bounds (shell:false, list-argv, code-owned allow-list) with labeled inert fallback and passes the named escape-fixture suite ('..', absolute path, symlink, junction/reparse) plus the hostile-argv cases, the F5 hostile-string DOM suite is green in CI over the registered slot inventory with its growth rule enforced, the STATUS overlay ships matching the hash-pinned amended mockup DOM diff, every new mutator is red-to-green with its routes-inventory row landed, and the tile-affordance inventory + parity map are landed (STATUS is not complete without them) with all CI gates still green.

- **Given** a declared deliverable whose outputPath resolves (symlinks and Windows junctions/reparse points first) outside the project tree, or an action verb outside the code-owned allow-list, or an argv containing hostile content (quotes, '&', '|', newline, NUL), **when** the deliverable affordance renders or is invoked, **then** a labeled inert state with a named reason shows and nothing executes — the spawn is shell:false, argv is a list from the registry's fixed verb + contained path only, cwd pinned to the project
- **Given** hostile-string fixtures (markup, script, event-handler payloads) in every agent-influenced DOM slot, **when** the F5 CI suite runs, **then** zero markup executes; strings enter via textContent/attribute-safe setters and link targets validate against the fixed internal schemes
- **Given** the Seal open with a run in flight and remaining steps, **when** the STATUS overlay opens, **then** it renders the latest status table plus remaining steps with n>=3 median ETAs, and the DOM diff against the overlays section is green

## Wave 10 — W10 Phase-3 Drive: compose-first directive cards + serialized gate queue with E2 co-landed

**Intent:** The steward drives and decisions serialize, with E2 shipping IN the same wave as the queue: the compose-first directive-card template (stand / running-and-doing-what / one next move / goal-guard line / question LAST) fills from reconciled state — WIRING the existing composer contract (engine/steward-conversation.mjs :: buildStewardPrompt's compose-the-directive rule + parseStewardReply's commission_directive field) for card content while the fixed-slot template render is NEW code; a composer that cannot fill the slots triggers the wire-homing kill branch (HALT + re-cost as rewrite), never a silent reimplementation — the E4 template fixture outlaws bare dialogs, the FIFO gate queue renders one prose card at a time (E5), and the died->sweep-card state-machine transition runs the two-tier containment-checked sweep (F4) whose card must be BOUND into the queue before any re-commission can enqueue. Serves C3/C5/C7. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Compose-first directive-card template with fixed slots incl. goal-guard line, filled from reconciled state + precomputed brief, WIRING the existing composer (buildStewardPrompt / parseStewardReply's commission_directive) per the wire-homing registry — the template render is NEW, the composition is not reimplemented; E4 CI template fixture: prose, context + recommendation before the question, question LAST; bare dialog or clipped preview fails; fixtures cite their rows in the Stage-2 traceability matrix (brief-shape + question-last moments, extended from W3); Serialized FIFO decision-gate queue visible as state; head-only render; resolve/skip releases the next (E5 test); died/quiet/timeout -> sweep-card state machine overriding any composed narrative next-move; Two-tier sweep: tier 1 lands declared-deliverable-glob matches onto the step; tier 2 git-status diffs the worktree into an explicit 'unclaimed changes' card — F4 symlink- and junction/reparse-resolved containment both directions (named escape-attempt tests incl. junction fixtures), unclaimed listed by path only, never executed or rendered as markup; E2 enqueue gate + landing-wave negative-path test on the W2-proven confirm_and_launch seam; Auth-ON + F6 red-to-green in this wave for the new mutators (gate resolve/skip, sweep-card binding) with rows added to the living routes inventory; wire-homing rows compose-first and auto-commit (commission_session.py :: commit_campaign_state on chamber confirms) resolved against their committed oracles; Contended-interaction refusal tests co-landed in this wave: a sweep card and a directive card contending for the queue head resolve deterministically (the sweep card takes the head; the directive re-queues) with a named finding on any double-render, and a run dying WHILE a gate is held routes into the sweep-card state machine without dropping the held gate

**Depends on:** W9 Phase-2 Close: deliverable action registry (F3), DOM injection law (F5), STATUS overlay

**done-when:** Directive and gate cards pass the E4 question-last template fixture (fixtures matrix-cited), gates serialize FIFO with head-only render (E5), the E2 negative-path test proves a re-commission cannot enqueue before the containment-checked sweep card is bound into the queue, and the queue-head contention and died-while-gate-held refusal tests co-land green in this wave (W12 re-runs them, never first-exercises them).

- **Given** any rendered directive or gate card, **when** the CI template fixture runs, **then** context and recommendation precede the question, the question is the LAST line, and a bare option dialog or clipped preview fails the suite (E4)
- **Given** two gates enqueued while the campaign is busy, **when** the chamber renders, **then** only the head card shows and the second appears only after the head resolves or is skipped (E5)
- **Given** a fixture commission killed quiet/died/timeout, **when** a re-commission card attempts to enqueue before the sweep completes and its card is bound into the queue, **then** the engine blocks the enqueue with a named finding, and the sweep's own tests assert symlink- and junction-resolved worktree/project containment with unclaimed content listed but never executed (E2/F4)

## Wave 11 — W11 Phase-3 Refine: preference preload, REFINE overlay, re-brief, E3 co-landed

**Intent:** Close Phase 3 with the remaining talking surfaces and E3 shipping on its surface: deterministic standing-preferences preload with a diffable projection (E6), the REFINE overlay with section-scoped hash confirm surviving a concurrent writer and showing the drawn 'plan moved' card on genuine conflict, mid-flight re-brief in the mode fixed by the W2 inbox audit (E7, no relaunch), and the E3 resurrection guard: predicate-required corrections, one-time triage of the existing correction ledger, positive-containment handback diffs blocking regressions, unassertables honestly demoted in every report. F6 CSRF set on refine-confirm and re-brief writes. Serves C6/C7. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Standing-preferences preload (feedback ledger + global rules) into the talk instruction + projection listing exactly the loaded entries (E6 diffable test); REFINE overlay per mockup: talk-to-edit draft, section-scoped hash-bound confirm, 'plan moved' card WITH diff, simulated-concurrent-writer test at steward-loop cadence, DOM-diffed against the hash-pinned overlays spec; Mid-flight re-brief per the audited mode: live channel with acknowledgment receipt on the step, or boundary mode with the effective-time statement drawn into the confirm card (E7 test, no relaunch); Correction-recording contract: machine predicate (grep/length/structural) or explicit 'unassertable — manual review' mark; One-time triage of ALL existing correction-ledger entries + published predicate-coverage threshold with unassertables honestly demoted; E3 handback interception on the W2-proven seam (engine/handback-ingest.mjs :: ingestHandback / ingestValidatedHandbackBody): positive-assertion diff, regression blocks with named finding, landing-wave negative-path test; Auth-ON + F6 red-to-green in this wave for the new mutators (refine-confirm write, re-brief write) with rows added to the living routes inventory; wire-homing row findings-ledger (engine/step-findings.mjs) resolved against committed ledger fixtures; Contended-interaction refusal test co-landed in this wave: a re-brief landing DURING an active sweep is refused or queued behind the sweep's card binding with a named finding, never interleaved

**Depends on:** W10 Phase-3 Drive: compose-first directive cards + serialized gate queue with E2 co-landed

**done-when:** Preference preload is diffably exact (E6), the REFINE overlay survives a concurrent writer with hash-bound confirm and the drawn 'plan moved' card, re-brief works without relaunch per the audited mode (E7), the E3 negative-path test blocks a regressing handback with unassertable entries honestly demoted, and the re-brief-during-sweep contention test co-lands green in this wave (W12 re-runs it).

- **Given** a fixture feedback ledger and global standing rules, **when** the talk instruction composes at session start, **then** the preload projection lists exactly the loaded entries and each is present in the instruction — a missing entry is a diffable failure, not a vibe (E6)
- **Given** a REFINE confirm bound to a section hash while reflections and landings occur elsewhere, and separately a genuine plan-region conflict, **when** John confirms, **then** the unrelated activity never invalidates the confirm, and the genuine conflict shows the drawn 'plan moved' card WITH a diff — ledger writes only on hash-bound confirm
- **Given** a resumed/re-briefed rewrite that regresses a predicate-bearing correction, **when** handback is attempted, **then** the mechanical diff blocks the handback with the named finding, and the coverage report shows the unassertable remainder demoted, never silently blessed (E3)

## Wave 12 — W12 Phase-4 Close: cross-criterion audit, tile retirement on signed parity, ease report, release bundle

**Intent:** Audit the ASSEMBLED system rather than first-exercise anything: re-run every landing-wave refusal end-to-end plus the interaction cases no landing wave could see, publish honestly-bounded E1/E3 enforcement reports, retire the bottom tiles ONLY after the affordance inventory maps every capability to a rail/STATUS equivalent or a John-signed accepted loss with parity signed, re-verify all of E1–E9 at their named seams, close with the pre-registered John-audited ease report against the Stage-2 5->0 baseline, and land the release-gate CI bundle green on the final commit. Serves C8/C11 and the full E1–E9 table. Non-goals hold: no engine-spine changes, no UI beyond the amended locked mockup, no High Seat work, no new commission lanes; tiles retire only on signed rail+STATUS parity.

**Deliverables:** Cross-criterion negative-path audit suite: all landing-wave refusals re-run end-to-end + the interaction cases co-landed in W10/W11 (run dies while a gate is held; sweep card vs directive card contend for queue head; re-brief lands during a sweep) each re-blocked with its named finding — nothing is first-exercised here; Tile retirement executed against the W9-landed inventory + parity map: every row resolved to a live rail/STATUS equivalent or a John-signed accepted loss; tile removal code gated on signed rail+STATUS parity (C11); E1 enforcement report (agreed out-of-bound misses of the ratified parse) + E3 report (predicate-coverage threshold, every unassertable named); Full E1–E9 re-verification pass: each criteria-ledger row's named instrument re-run at its named seam (the ledger's W12 re-verify column), plus C9–C12 re-checks (hash-pinned DOM diffs, F3 escape + F5 hostile-string + F6 red-to-green suites, signed parity, characterization parity); Campaign-close ease report from the frozen classifier of record: count since the W8 say box, classified excerpts, stated error bars, Stage-2 baseline RE-SCORED by the same classifier over the reference-session transcript (same-ruler protocol; if unscoreable, the numeric comparison is descriptive only), John's one-pass audit HALT; Release-gate CI bundle green on final commit: zero-model-call network trace + process-spawn audit, <2s budget at the committed >=2x-real fixture sizes, first-open-after-deploy degraded-paint test, DOM/class diff pinned to the signed post-amendment mockup hash, auth-ON + F6 coverage over the living routes inventory with its diff guard green, F3 escape + hostile-argv suite, F4 sweep-containment suite (symlink + junction/reparse), F5 slot-registered hostile-string suite with the growth rule enforced, F2 manifest-schema lint, wire-homing registry symbol-check

**Depends on:** W11 Phase-3 Refine: preference preload, REFINE overlay, re-brief, E3 co-landed

**done-when:** The cross-criterion audit including interaction cases is green, tiles are removed only after signed rail+STATUS parity with every inventory row resolved, the full E1–E9 re-verification passes at the named seams, the release CI bundle is green on the final commit, and the John-audited ease report ships with the 5->0 baseline comparison.

- **Given** the fully assembled chamber, **when** the cross-criterion audit runs, including a run dying WHILE a gate is held, a sweep card and a directive card contending for the queue head, and a re-brief landing during a sweep, **then** every case is blocked with its named finding and every landing-wave refusal test re-passes end-to-end — a criterion first exercised here would be a plan defect
- **Given** the tile-affordance inventory, **when** tile retirement is proposed, **then** every row maps to a live rail/STATUS equivalent or an explicit John-signed accepted loss, and no tile is removed before rail+STATUS parity is SIGNED
- **Given** campaign close with the pre-registered classifier of record and no post-hoc tuning, **when** the ease report generates, **then** it reports the count since the W8 say box with classified excerpts, error bars, and the Stage-2 5->0 baseline, and requires John's one-pass audit before the number is treated as the verdict

## Property gates (hardening law — crucible journal 0080)

### durability — asserted by this plan
_a durability claim is a STORAGE claim; validating a rule is not providing it_

- [x] atomic write (temp + fsync + rename) — W4 projection writers; kill-during-write crash test named in W4's done-when
- [x] lock or documented serialization — W4 documented single-writer serialization on the chamber projection store
- [x] a concurrency test — W4 two-real-process append test (no event dropped) + W11 simulated-concurrent-writer REFINE test at steward-loop cadence

### boundedness — asserted by this plan
_an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard_

- [x] the numeric bound named in the plan — W6: budget fixtures at >= 2x the W5-recorded largest real ledger (events / MB / run-records, numbers committed); run-record reads capped to active scaffold steps with a hard backstop of 200 reads per open
- [x] a refusal path when the bound is exceeded — W6: exceeding the read cap renders the drawn degraded-rail state, never an unbounded read

### containment — asserted by this plan
_containment is asserted far more often than it is exercised_

- [x] an escape-attempt test (.., absolute path, symlink, Windows junction/reparse) — W9 F3 escape-fixture suite + hostile-argv cases on deliverable actions + W10 F4 both-direction symlink- and junction-resolved sweep containment tests

A property named in the plan and absent from this list is a BLOCKER:
the plan is claiming a guarantee nothing enforces.

## Hardening-gate obligations (mechanical — journal 0080)

This section is the **emitted** property-gate checklist. A claim in the plan without a matching obligation below is a BLOCKER.

### Property `durability`
_a durability claim is a STORAGE claim; validating a rule is not providing it_

- **Gate:** atomic write (temp + fsync + rename) — bound to W4 (kill-during-write crash test in W4's done-when)
- **Gate:** lock or documented serialization — bound to W4 (documented single-writer serialization on the projection store)
- **Gate:** a concurrency test — bound to W4 (two real processes, no event dropped) and W11 (concurrent-writer REFINE test)

### Property `boundedness`
_an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard_

- **Gate:** the numeric bound named in the plan — bound to W6 (>= 2x-real committed fixture sizes; 200-read hard backstop per open)
- **Gate:** a refusal path when the bound is exceeded — bound to W6 (cap exceeded -> drawn degraded-rail state)

### Property `containment`
_containment is asserted far more often than it is exercised_

- **Gate:** an escape-attempt test (.., absolute path, symlink, Windows junction/reparse) — bound to W9 (F3 escape-fixture suite + hostile-argv cases) and W10 (F4 sweep containment both directions incl. junction fixtures)

### Storage mechanism vocabulary (required when durability is claimed)

- **atomic write** via **temp** + **fsync** + **rename** for snapshot (and durable JSON) paths
- cross-process **lock** or documented **serialization** around multi-writer index paths
- a **concurrency test** (two real processes; assert no event/receipt dropped)
- where "exactly once" / identity is claimed: a **repeat-invocation test**
- where containment is claimed: an **escape-attempt** test (`..`, absolute path, symlink/junction)
- where bounds are claimed: the **numeric bound** named (e.g. 10000 rows / 50000 events) and a **refusal** path when exceeded

### Failure-state table vocabulary (required when addsSurface)

Every surface-bearing wave answers these **five** states with named status code AND user-visible text.
**unknown** and **empty** are SEPARATE rows (never collapsed).

- **dependency-missing** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **dependency-slow-or-killed** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **dependency-returns-garbage** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **backing-store-unreadable** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **empty-but-valid** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)

Binding: the surface-bearing waves are W6–W11. Each answers the five rows through its NAMED states — W4's hash-mismatch error, W5/W6's drawn degraded-rail state (backing-store-unreadable / dependency-returns-garbage), the W1-amendment-batch drawn states for empty campaign and pre-emission open (empty-but-valid, kept separate from unknown), W7's 'yield missing' and 'no history yet' states, W9's labeled inert-with-named-reason state, W10's sweep / 'unclaimed changes' cards (dependency-slow-or-killed), W11's 'plan moved' card — and W12's cross-criterion audit re-checks each surface's table.

See also wave-local failure tables (hardening-gate 0080 format) and generated red stubs.



## Verification fold (V1-V6) — NORMATIVE amendments from the Fable review (2026-08-09)

The independent Fable traceability review (VERIFICATION-REVIEW.md, this
folder) traced all 14 reference-session behaviors to plan gates: 9
DELIVERED outright, several gated STRONGER than the session's own fixes.
It found three gates weaker than the journal's bar and one structural
hole. These amendments close them; Foreman treats each as part of the
named wave's acceptance criteria.

- **V1 (amends W3 + W8, closes the E1 bound gap):** the W3 question-parser
  fixture set MUST include imperative request forms with no question mark
  ("confirm you got…", "tell me…", "did you get…", "can you please…") and
  realistic garbled-dictation rows, WITH the journal's verbatim T+15
  trigger ("confirm you got comments on the whole deck") as a named
  fixture. Each form is either IN-BOUND (the parser fires) or an
  explicitly John-signed known miss at the F7 ratification gate — no
  silent out-of-bound. The W8 negative-path test exercises at least one
  imperative in-bound form.
- **V2 (amends W2 + W11, closes the E7 downgrade):** if the W2 inbox audit
  finds NO live re-brief channel, that outcome is a JOHN HALT — a gate
  presenting accept-boundary-mode vs fund-the-live-channel with costs —
  never a silent design input. Boundary mode may only ship John-signed.
- **V3 (amends W10 + W12, closes the commit-coverage gap):** commit
  coverage widens from confirm-scoped to landing-scoped: a fixture
  asserts NO uncommitted campaign state after each landing class (step
  yield, sweep landing, correction fix, deliverable landing) — the
  journal's bar is "everything committed at every step" and the W12
  audit asserts it on the assembled system.
- **V4 (amends W10 + W12, closes the structural hole):** a DATED
  FIRST-LAUNCH decision-log entry, symmetric to W6's first-open: one named
  end-to-end LIVE run on a real campaign (Go → running → telemetry
  ticking → produced → yield on the rail → sweep-or-handback) recorded
  with campaign, machine, and timestamps. "Work never waiting on John"
  is not sign-off-able from fixtures alone.
- **V5 (amends W1):** "blocked turn" (the E1 refusal state — engine
  refused to close a turn with an unanswered question) joins the W1
  undrawn-state enumeration for the batched mockup-amendment gate, so
  the cure never looks like the disease ("are you working").
- **V6 (amends W8 + W12):** spoken-turn latency is MEASURED from day one
  (say-box submit → first steward text visible, logged per turn) and
  reported in the W12 close report alongside the ease count. No hard
  budget is imposed (model latency is not this build's to fix), but an
  unmeasured regression is — the number must be on the table.

Known limits acknowledged, NOT folded (out of this build's scope, named
so they are audit facts): the steward's seat/model and context budget are
configuration, not plan criteria; scroll-while-dictating is host/OS.
