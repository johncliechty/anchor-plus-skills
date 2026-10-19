# Crucible-planned project — Implementation Plan (Foreman-ready)

test-command: python -m pytest -v tests/ -k "2026_07_29" --tb=line

**North Star:** On branch v1.2, John can open, run, stop, and restart real Anchor work — including Doctor diagnose and session attach — without meeting a dead control, a silent zero, a mislabelled empty, or a preview that dumps raw binary. Every surface that claims health, usage, or diagnose either works end-to-end or fails with a named, user-visible state (unknown ≠ empty ≠ zero). Cost never fabricates dollars. Nothing in this effort ships to v1.1.x collaborators. Steward conversational proof is a post-build validation session (S1), not a silent claim of this build.

## Binding definitions (one vocabulary, binding on every wave, gate, enum, and table)

**The state trichotomy (canonical — W6's NamedState enum, W4's rollup gate, W12's tiles, and every failure-state table use these four words with exactly these meanings and no others):**
- **empty** — the read succeeded and there is legitimately no series and no scope: nothing was ever in scope (no sessions, no projects, no files).
- **zero_measured** — the aggregation ran successfully over a scope that exists, and the total is 0. A real, trustworthy zero.
- **unknown** — we did not successfully read. Query failed, store unreadable, probe errored, or the value was never fetched.
- **pending** — no aggregator exists yet. The code that would produce this value has not been built.
A surface may not render a word outside this set unless that word maps, in `STATE-VOCABULARY-MAP.md` (W8), to one of these four or to ok / unmeasured / measurement_failed / timeout / stale / cannot_*. There is no fifth trichotomy word and no wave may coin one.

**"end-to-end" as this build proves it — the plan-level, user-visible declaration.** In waves W10–W21, *end-to-end* means exactly: a traced path from control invocation to handler to capability call to rendered state, asserted on real rendered output (visible text nodes in `generate_html` output plus `node --check` on emitted script blocks), under at least one induced fault per named failure reason. It does **not** mean a human drove the real UI. Every trace artifact stamps `proof_level: rendered-string`. The human-path claim — the North Star's sense of "works end-to-end" — is deferred to **S1 (W22)** and is disclosed in the terminal status string, so structural conformance can never be read as the North Star being met.

**"Close criterion N" is structural-candidate language only.** A wave that says it closes a criterion produces a **CANDIDATE-MET** stamp: the structure exists and is machine-proven at the rendered-string level. No wave, gate, audit, or report may stamp a criterion **MET**. Only S1 (W22), run live with John, converts CANDIDATE-MET to MET; a criterion S1 fails reverts to OPEN. A MET stamp anywhere before S1 is a validator failure.

**Vocabulary bijection — one canonical map, machine-enforced.** Two vocabularies exist in this build: the hardening-gate dependency vocabulary (dependency-missing, dependency-slow-or-killed, dependency-returns-garbage, backing-store-unreadable, empty-but-valid) and the surface-native NamedState vocabulary. "Both are documented" is not the standard. `planning/sleep-2026-07-28/stage2/artifacts/STATE-VOCABULARY-MAP.md` (W8) is a machine-read bijection — every term on both sides appears exactly once — and `tests/conformance/table_validator.py` fails a wave whose failure-state table omits a required row or uses a term absent from the map. Surface tables are written in surface-native rows; index / rebuild / reconcile language on a user-facing tile (a Doctor tile, a cost tile) is honesty theater and fails the validator.

**Named numeric bounds (so nothing here is an untestable adjective):** capability-inventory staleness bound = **14 days**; inserted 'build it' waves = **at most 3** before a mandatory re-baseline HALT; cost spot-check minimum sample = **20 sessions** (or all, if fewer) and **at least 3 per engine** over a **30-day** window; cost agreement tolerance = **0 cents**; exit conjunction ceiling = **2 on one criterion / 4 across the build**.

## Success criteria
- Open and Run each get one of exactly two closures — no third answer: (a) the W10 surface wave, with a dead-control contract, a failure-state table, named cannot-open / cannot-run states, and an e2e trace each; or (b) a frozen inventory row carrying PRESENT, its transcript, a matching source hash, and John's dated 'no further work' signature at the W5 freeze. Ambient precondition, 'the task triple covers it', and 'S1 will catch it' are not closures.
- Criteria close as CANDIDATE-MET only; MET is S1's stamp alone.
- Dead controls eliminated for Retry, Diagnose, and exactly one restart control per restart context — work or not shown.
- Attach honesty: timeout classified as timeout; no double-print; Retry viable or named cannot-retry.
- Usage/time/cost: only after rollup evidence gate; cost labels from cost_state never 0⇒subscription; never $0.00 as fact; unmeasured labelled.
- Doctor: real diagnose; banner payload; Claude/Gemini/Grok independent with depth labels.
- Stop summary + restart: inventory-backed summary; per-context restart contract; no dual competing controls in one context.
- File preview: human-friendly Office/PDF via shared path; no raw binary as text.
- Projects collapsed by default; preference remembered; dual-profile verify.
- Cadence real from live telemetry with as_of/staleness named states.
- Gates: failure-state tables with unknown and empty SEPARATE rows, every row mapped through STATE-VOCABULARY-MAP.md and written in surface-native language; scoped pytest -v per wave; UI render+node --check; delta-coverage.
- Handoff: doc-trio only under planning/sleep-2026-07-28/stage2/; commits+EXECUTION-LOG per wave; host-computed attestations; root foreign Foreman artifacts untouched.

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — W1 — Phase 0: John task triple, containment smoke, shared-artifact ledger

**Intent:** Establish the hard-blocking evidence floor before any code claims anything: a reproducible verification task triple confirmed live by John, a containment smoke run proving Foreman writes only under planning/sleep-2026-07-28/stage2/, and a signed shared-artifact ledger. No E5 is available on the task triple.

**Deliverables:** planning/sleep-2026-07-28/stage2/artifacts/verification-task-triple.json — the three reproducible Anchor v1.2 tasks (open/run/stop-restart) with exact invocation, expected observable, and John's dated confirmation line; planning/sleep-2026-07-28/stage2/artifacts/shared-artifact-ledger.md — every artifact this build reads or writes, owner, path, and John's sign-off; tools/containment_smoke.py — asserts every write target resolves under planning/sleep-2026-07-28/stage2/ and that C:\dev\Anchor root foreign Foreman artifacts are byte-identical before/after, including an escape-attempt suite (`..` traversal, absolute path, symlink/junction) each of which must be refused by name; tools/coverage_toolchain_probe.py — records the real coverage tool, version, and whether delta-coverage is actually available on this box (truth, not assumption); tests/test_containment_smoke_2026_07_29.py; tests/test_verification_task_triple_2026_07_29.py; gate-command: python -c "from tools.verification_task_triple import phase0_go_decision; r=phase0_go_decision(); raise SystemExit(0 if r.is_go else 1)" && pytest -v tests/test_containment_smoke_2026_07_29.py tests/test_verification_task_triple_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** —

**done-when:** The task triple carries John's dated confirmation, the containment smoke run passes with root foreign artifacts proven untouched, the shared-artifact ledger is signed, and the coverage-toolchain probe has recorded ground truth — all with a commit SHA in EXECUTION-LOG.md.

- **Given** a verification-task-triple.json with no John confirmation line, **when** the wave gate runs, **then** the gate HALTs with 'live-John item — no E5 available on the task triple' and the wave is not GO, regardless of how many tests pass
- **Given** a build step that attempts to write to C:\dev\Anchor\DESCRIPTION.md, **when** containment_smoke.py runs, **then** it fails naming the offending path and the pre/post hash of the root foreign artifact it would have clobbered
- **Given** a box where delta-coverage tooling is not installed, **when** coverage_toolchain_probe.py runs, **then** it records 'delta-coverage unavailable' as a fact rather than defaulting to available, so later waves must use the enumerated per-handler test list under E4

## Wave 2 — W2 — Phase 0: Exit register engine + status-string generator

**Intent:** Make the six exits E1–E6 machine-enforced rather than prose: unsigned exit is a HALT, E2 is illegal for dollars, E6 is closed for the four North-Star violation classes, no exit may be justified by another exit, and the conjunction scorer forces a re-baseline HALT at two-per-criterion or four total.

**Deliverables:** anchor/build/exit_register.py — ExitId enum E1–E6, register row schema (exit id, criterion, forcing evidence, what the user sees instead, date, John confirmation), signature validator; anchor/build/exit_register.py::score_conjunction — HALT at 2 exits on one criterion or 4 across the build; anchor/build/exit_register.py::terminal_status — emits verbatim 'ten criteria CANDIDATE-MET (structural, rendered-string level) with N signed exits (E<ids>); North Star pending S1'; the unqualified 'ten criteria met' string is unreachable until N==0 AND S1 has recorded PASS, so no amount of green structure can emit it; anchor/build/exit_register.py::validate_justification — rejects E1 justified by a STUB verdict, E2 justified by an unproven accessor, E3 justified by an upstream E1; planning/sleep-2026-07-28/stage2/artifacts/EXIT-REGISTER.md — starts with zero signed exits; tests/test_exit_register_2026_07_29.py; gate-command: pytest -v tests/test_exit_register_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W1 — Phase 0: John task triple, containment smoke, shared-artifact ledger

**done-when:** exit_register.py rejects unsigned rows, refuses E2 on any cost criterion, refuses E6 for dead-control/silent-zero/mislabelled-empty/raw-binary findings, refuses exit-justified-by-exit chains, and terminal_status cannot emit the unqualified phrase while any exit is signed or while S1 has no recorded PASS — all proven by scoped tests.

- **Given** a register row taking E2 against the cost-labelling criterion with an as_of stamp, **when** validate() runs, **then** it raises IllegalExit('E2 does not apply to dollars — cost surfaces render measurement_failed') and the row is not written
- **Given** a Phase 1 inventory verdict of STUB for Doctor Diagnose, **when** a caller attempts to sign E1 'not available on this build' citing that STUB, **then** validate_justification rejects it and requires either a 'build it' wave or an ABSENT verdict with an independent absence transcript
- **Given** three signed exits across three distinct criteria and a fourth being signed, **when** score_conjunction runs, **then** it returns HALT_REBASELINE and no subsequent wave may start until John records an explicit re-baseline

## Wave 3 — W3 — Phase 1: Capability Inventory harness (PRESENT / STUB / ABSENT with transcripts)

**Intent:** Produce the artifact that decides what every surface wave is allowed to claim: for each control named by the ten criteria, a tri-state verdict backed by a transcript from John's real v1.2 environment, so 'wire it' can be reclassified to 'build it' or to a signed E1.

**Deliverables:** tools/capability_inventory.py — per-control probe returning PRESENT | STUB | ABSENT plus the transcript path that proves it; STUB is never auto-downgraded to ABSENT; every row carries a probe date and the SHA-256 of the source file(s) under test, so the row is bound to the code it describes; planning/sleep-2026-07-28/stage2/artifacts/CAPABILITY-INVENTORY.md — one row per control: the open control, the run control, Retry, Diagnose, each restart control per context, stop-summary inventory source, preview path, projects-collapse handler, cadence telemetry source, per-engine Claude/Gemini/Grok diagnose; staleness rule with a number — a row older than **14 days**, or whose recorded source hash no longer matches the code at HEAD, is **STALE**; STALE fails closed: it is treated as UNKNOWN, not as its last verdict, and it may not authorize rendering any live control until re-probed; replay authority rule — a PRESENT verdict established only by replaying a stored transcript may authorize *documentation*, never the *shipping of a live control*: shipping requires a live probe inside the staleness bound against a matching source hash; mid-build reclassification — when a STUB is fixed by a 'build it' wave, that wave's gate must re-run the probe and rewrite the row; the source-hash mismatch makes the stale STUB row fail closed rather than silently persist; artifacts/transcripts/ — captured-once, replayed-many transcripts so John is not needed live to re-run a probe; tests/test_capability_inventory_2026_07_29.py — asserts STUB→ABSENT reclassification is impossible, that every verdict has a non-empty transcript reference and a source hash, that a 15-day-old row and a hash-mismatched row both resolve to STALE/fail-closed, and a repeat-invocation (idempotence) test asserting a re-probe against an unchanged source hash returns a byte-identical verdict row; gate-command: pytest -v tests/test_capability_inventory_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W2 — Phase 0: Exit register engine + status-string generator

**done-when:** CAPABILITY-INVENTORY.md carries a transcript-backed, hash-linked, in-bound PRESENT/STUB/ABSENT verdict for every control named by criteria 1–8 plus the open and run controls, and the harness provably refuses a verdict with no transcript, refuses STUB→ABSENT downgrade, resolves an out-of-bound or hash-mismatched row to STALE/fail-closed, and refuses to let a replay-only PRESENT authorize a live control.

- **Given** a Diagnose probe whose handler is bound but returns canned seed output, **when** capability_inventory.py classifies it, **then** the verdict is STUB with the transcript showing the canned output, and the row is marked 'build it' — not 'wire it' and not E1
- **Given** a control with no probe transcript captured, **when** the inventory gate runs, **then** the wave fails with 'verdict without evidence' naming the control, rather than defaulting the verdict to ABSENT or PRESENT
- **Given** a Diagnose row marked STUB that a later 'build it' wave repairs without re-probing, **when** any surface wave reads the inventory, **then** the recorded source hash no longer matches HEAD, the row resolves to STALE, and the wave HALTs demanding a re-probe — the stale STUB neither blocks silently nor passes silently
- **Given** a PRESENT verdict whose only evidence is a replayed transcript 20 days old, **when** a surface wave asks whether it may render that live control, **then** the inventory refuses and requires a live probe inside the 14-day bound against a matching source hash

## Wave 4 — W4 — Phase 1: Rollup Evidence Gate (query + row count + sample row)

**Intent:** Prove, per rollup, what is actually true — and stop the gate from collapsing three different facts into one verdict. 'No aggregator exists', 'the aggregator ran and returned zero rows', and 'we could not read' are three separate verdicts with three separate surface consequences. A legitimate measured zero must survive this gate as a measured zero; mislabelling it pending is precisely the defect this plan exists to kill.

**Deliverables:** tools/rollup_evidence_gate.py — per rollup: the exact query, the row count, one sample row, and a run receipt (run timestamp, window, scope size); emits exactly one of **PROVEN | NO_AGGREGATOR | READ_FAILED**, and PROVEN carries a sub-verdict of **nonzero | zero_measured | empty** per the binding definitions — aggregator ran and returned zero rows over a scope that exists is PROVEN/zero_measured; the scope itself is empty is PROVEN/empty; these are never merged with each other or with NO_AGGREGATOR; planning/sleep-2026-07-28/stage2/artifacts/ROLLUP-EVIDENCE.md — one block per rollup consumed by dashboard, workbench tiles, and session chrome, recording verdict, sub-verdict, and receipt; artifacts/rollup-spot-check.md — the cost spot-check executed to this replicable protocol: **population** = every engine carrying cost instrumentation, over a named 30-day window; **minimum sample** = 20 sessions, or all sessions if fewer than 20, and at least 3 per engine; **independent source-row sum** = a second procedure that reads the source rows directly and does not import the aggregation module; **independence rule** = the agent that authored or last edited the aggregation module may not compute the second side, and no single agent may compute both sides; **agreement tolerance = 0 cents (exact match)**, because 'never fabricates dollars' is absolute; any disagreement, or any sampled engine the second procedure cannot compute, forces measurement_failed for that engine — never a 'provisional' number; anchor/build/rollup_registry.py — the machine list of PROVEN rollups that surface waves import, each with its sub-verdict; rendering a numeral from a NO_AGGREGATOR rollup raises at test time, and a READ_FAILED rollup may render only unknown; tests/test_rollup_evidence_gate_2026_07_29.py — includes a fixture per verdict and per sub-verdict, asserting the four outcomes are never collapsed; gate-command: pytest -v tests/test_rollup_evidence_gate_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W3 — Phase 1: Capability Inventory harness (PRESENT / STUB / ABSENT with transcripts)

**done-when:** Every rollup named by criterion 3 carries exactly one of PROVEN (with sub-verdict) / NO_AGGREGATOR / READ_FAILED, backed by query + row count + sample row + receipt; the cost spot-check has been run to the written protocol with its population, minimum sample, independence rule, and 0-cent tolerance all satisfied and recorded; and rollup_registry.py makes a numeral from a NO_AGGREGATOR rollup a test failure.

- **Given** a rollup whose aggregator exists and whose query correctly returns zero rows for the window over a scope that does exist, **when** rollup_evidence_gate.py evaluates it, **then** the verdict is PROVEN with sub-verdict zero_measured, the consuming surface is registered to render the measured zero — not pending, not unknown, not blank — and no aggregation wave is created
- **Given** a rollup with no aggregator anywhere in the codebase, **when** the gate evaluates it, **then** the verdict is NO_AGGREGATOR, an aggregation wave is required, and the consuming surface is registered to render pending naming the wave it awaits
- **Given** a rollup whose query raises at read time, **when** the gate evaluates it, **then** the verdict is READ_FAILED and the surface is registered to render unknown — the gate may not emit the same verdict it would give an absent aggregator
- **Given** a spot-check where both sides were computed by the same agent, or where fewer than 3 sessions were sampled for an instrumented engine, **when** the gate validates the spot-check record, **then** it rejects the spot-check as non-independent or under-sampled and the wave is not GO
- **Given** a cost spot-check where the aggregated dollar figure disagrees with the source rows, **when** the gate records the result, **then** the cost surface is registered as measurement_failed and any attempt to sign E2 against it is rejected by the exit register from W2

## Wave 5 — W5 — Phase 1: Wave-list freeze + doc-trio amendment procedure

**Intent:** Stamp the wave list against the actual inventory and rollup verdicts, review it with John, and define exactly how the doc-trio is amended when a STUB forces a new 'build it' wave — so the surface waves cannot start on a stale plan.

**Deliverables:** planning/sleep-2026-07-28/stage2/artifacts/WAVE-LIST-FREEZE.md — frozen wave list, owner (orchestrator), gate (John's Phase-1 verdict review), dated freeze stamp, and the delta vs this plan caused by inventory verdicts; **NORTH-STAR CONTROL DECISION table** — one row per North-Star verb/control (open, run, stop, restart, Doctor diagnose, session attach), each row forced into exactly one of two states: **build now**, naming the wave that builds it, or **signed exit**, carrying the PRESENT verdict, its in-bound transcript, its matching source hash, and John's dated 'no further work' line; a row left blank, deferred, marked 'ambient', or annotated 'S1 will catch it' fails the freeze; planning/sleep-2026-07-28/stage2/artifacts/DOC-TRIO-AMENDMENT.md — the written procedure for inserting a 'build it' wave into IMPLEMENTATION-PLAN.md + EXECUTION-LOG.md without touching C:\dev\Anchor root; **insertion cap** — at most **3** inserted 'build it' waves across the build; a 4th returns HALT_REBASELINE and no wave proceeds until John re-baselines scope explicitly; tools/freeze_gate.py — refuses to report GO for any surface wave while the freeze stamp is absent, its inventory hash does not match CAPABILITY-INVENTORY.md + ROLLUP-EVIDENCE.md, any NORTH-STAR CONTROL DECISION row is undecided, any cited inventory row is STALE (older than 14 days or hash-mismatched), or the insertion cap is exceeded; planning/sleep-2026-07-28/stage2/artifacts/INSTRUMENTATION-BUDGET.md — load-bearing vs discretionary items and the E4 reduced-instrument trigger, recorded before it is needed; tests/test_freeze_gate_2026_07_29.py; gate-command: pytest -v tests/test_freeze_gate_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W4 — Phase 1: Rollup Evidence Gate (query + row count + sample row)

**done-when:** WAVE-LIST-FREEZE.md is stamped after John's verdict review, its hash matches the inventory and rollup artifacts, every North-Star control carries a build-now or signed-exit decision with no third state, the insertion cap is recorded and unexceeded, and freeze_gate.py blocks every surface wave until all of that verifies.

- **Given** an unstamped WAVE-LIST-FREEZE.md, **when** W10 (open + run) attempts to open, **then** freeze_gate.py HALTs the wave with 'wave-list freeze not stamped — surface waves blocked'
- **Given** a NORTH-STAR CONTROL DECISION table whose 'run' row says 'covered by the verification task triple', **when** freeze_gate.py validates it, **then** the freeze fails naming the run row, because the only legal values are build-now-naming-a-wave or a signed exit with transcript and source hash
- **Given** a fourth 'build it' wave being inserted, **when** the amendment procedure runs, **then** freeze_gate.py returns HALT_REBASELINE and no surface wave starts until John records an explicit re-baseline
- **Given** a freeze stamped against an inventory that is later edited to add a 'build it' wave, **when** freeze_gate.py re-verifies the hash, **then** it fails as stale and requires re-freeze via the DOC-TRIO-AMENDMENT procedure rather than proceeding

## Wave 6 — W6 — Phase 2: Named-state vocabulary + render primitive (unknown ≠ empty ≠ zero)

**Intent:** Ship the load-bearing primitive every surface wave renders through, so no wave hand-invents a label and no ambiguous zero can reach the screen.

**Deliverables:** anchor/ui/named_state.py — NamedState enum: ok, unknown, empty, zero_measured, pending, unmeasured, measurement_failed, timeout, stale, cannot_retry, cannot_open, cannot_run, cannot_restart — each with a distinct user-visible string, and each carrying the wording of the 'Binding definitions' section as its docstring, with a test asserting the docstring matches that section verbatim so a second vocabulary cannot drift into existence; anchor/ui/named_state.py::render_state() — the single render primitive; returns a labelled visible text node for every state and raises on None/blank input; anchor/ui/named_state.py::FAILURE_STATE_TABLE — schema requiring unknown and empty as SEPARATE rows for any surface-bearing table; tools/zero_inference_lint.py — flags any code path that derives a user-facing label from a numeric value being zero; tests/test_named_state_2026_07_29.py — asserts unknown, empty, zero_measured, and pending produce four distinct rendered strings matching the binding definitions, that no two of the thirteen states share a rendered string, and that blank/None is never rendered; gate-command: pytest -v tests/test_named_state_2026_07_29.py; node --check on any emitted script block; assertion on generate_html rendered output; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W5 — Phase 1: Wave-list freeze + doc-trio amendment procedure

**done-when:** render_state() emits a distinct, non-blank visible label for all thirteen named states, the trichotomy members carry the binding definitions verbatim, the failure-state table schema rejects a table that merges unknown and empty (or pending and zero_measured), and zero_inference_lint.py flags a zero-derived label.

- **Given** a tile whose value is None because the query never ran, **when** render_state is called, **then** the rendered HTML contains the 'unknown' label as a visible text node and does not contain '0', '—', or an empty cell
- **Given** a failure-state table declaring one combined 'unknown/empty' row, **when** the table schema validator runs, **then** it fails naming the merged row, satisfying hardening gates 0080/0081
- **Given** code that renders '(subscription)' when cost == 0, **when** zero_inference_lint.py scans it, **then** it reports a zero-inference violation with file and line, and the wave gate fails

## Wave 7 — W7 — Phase 2: cost_state enum + migration + dollar-fabrication ban

**Intent:** Make cost labelling derive from state, never from the number: zero renders (subscription) only when cost_state == subscription_covered, and $0.00 can never be emitted as a fact.

**Deliverables:** anchor/cost/cost_state.py — CostState enum: subscription_covered, measured, unmeasured, measurement_failed; migrations/<dated>_add_cost_state.sql — schema migration plus backfill that maps existing rows to unmeasured rather than to measured-zero; anchor/cost/read_cost_state.py — fail-closed partial-migration behaviour: a row whose cost_state column is absent, NULL, or unreadable — mid-deploy, failed migration, rolled-back migration, or a replica that has not caught up — resolves to measurement_failed, never to measured and never to subscription_covered, and the surface renders the labelled measurement_failed state with no dollar figure and no '(subscription)'; anchor/cost/render_cost.py — the only sanctioned cost renderer; imports render_state from W6; raises if asked to emit '$0.00' without cost_state == measured; tests/test_cost_state_2026_07_29.py — includes the four-way matrix (zero×each state) and a regression asserting no code path emits '$0.00' as fact; gate-command: pytest -v tests/test_cost_state_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W6 — Phase 2: Named-state vocabulary + render primitive (unknown ≠ empty ≠ zero)

**done-when:** Every cost render path goes through render_cost.py, the zero×cost_state matrix is fully covered by tests, and emitting '$0.00' outside cost_state == measured raises.

- **Given** a session with cost 0 and cost_state == unmeasured, **when** render_cost runs, **then** the surface shows the labelled unmeasured state, never '(subscription)', never '$0.00', and never blank
- **Given** a session with cost 0 and cost_state == subscription_covered, **when** render_cost runs, **then** the surface shows '(subscription)' and the test asserts the label came from the enum, not from the value
- **Given** a mid-deploy database where the cost_state column does not yet exist, **when** any cost surface renders, **then** every affected row shows measurement_failed, the rendered HTML contains no '$' figure and no '(subscription)' for those rows, and the failure is visible rather than degrading to a plausible-looking dollar amount
- **Given** the cost spot-check from W4 recorded a wrong figure, **when** render_cost is asked for that engine, **then** it renders measurement_failed and no numeric dollar value appears anywhere in the rendered HTML

## Wave 8 — W8 — Phase 2: Tri-state conformance harness + failure-state table validator

**Intent:** Give every surface wave a shared assertion engine so conformance to unknown ≠ empty ≠ zero is machine-checked instead of hand-written per wave.

**Deliverables:** tests/conformance/tri_state.py — parameterized harness driving each surface through unknown, empty, and zero fixtures and asserting three distinct visible text nodes; planning/sleep-2026-07-28/stage2/artifacts/STATE-VOCABULARY-MAP.md — the machine-read bijection between the hardening-gate dependency vocabulary (dependency-missing, dependency-slow-or-killed, dependency-returns-garbage, backing-store-unreadable, empty-but-valid) and the surface-native NamedState members; every term on both sides appears exactly once, and a term appearing on neither side is a build failure; tests/conformance/table_validator.py — validates each wave's failure-state table against that map and FAILS the wave when a required row is missing or any row uses a term absent from the map: unknown and empty as separate rows, every required row present, every row naming the user-visible string and its trigger; surface-native enforcement — a user-facing table whose rows name index / rebuild / reconcile actions instead of the surface's own actions (open, run, attach, diagnose, preview, restart, tile render) fails as honesty theater, not as a style note; tests/conformance/html_assert.py — visible-text-node assertions over generate_html output plus node --check over extracted <script> blocks (pattern: tests/test_auth_reprompt_2026_07_28.py); tools/delta_coverage.py — names new routes/handlers/frontend and requires each to appear in a dated tests/test_<subject>_2026_07_29.py; degrades to the enumerated per-handler list when W1's probe recorded the tooling absent (E4); tests/test_conformance_harness_2026_07_29.py; gate-command: pytest -v tests/test_conformance_harness_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W7 — Phase 2: cost_state enum + migration + dollar-fabrication ban

**done-when:** The tri-state harness, table validator, HTML/node --check asserters, and delta-coverage checker all run from a single scoped gate-command and are importable by every surface wave.

- **Given** a surface that renders the same string for unknown and empty, **when** the tri-state harness runs against it, **then** it fails naming the collapsed pair and the offending render call site
- **Given** a new route added without a dated test file naming it, **when** delta_coverage.py runs, **then** the wave gate fails listing the uncovered route, or records a signed E4 with the enumerated per-handler list as substitute
- **Given** a Doctor tile failure-state table written in index/rebuild/reconcile language, **when** table_validator.py runs, **then** it fails naming each unmapped row and requires surface-native rows describing the Doctor tile's own actions
- **Given** a surface table that omits the required backing-store-unreadable row, **when** table_validator.py runs, **then** the wave fails naming the missing row — a table is conformant only when complete, not when merely present

## Wave 9 — W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema

**Intent:** Ship the evidence plumbing that makes a surface wave's GREEN mean 'traced end to end under induced faults', not 'handler is bound'.

**Deliverables:** anchor/build/trace_artifact.py — trace schema: control invocation → handler → capability call → rendered state, one artifact per surface wave; each hop records the payload id and payload hash it carried, and every artifact stamps proof_level: rendered-string, the binding definition of end-to-end for this build, so no trace can be read as a human-driven user path; tools/fault_inject.py — induce one fault per named failure reason (timeout, missing capability, empty result set, unmeasured cost, stale telemetry); reduced to one-per-reason under E4; anchor/build/execution_log.py — EXECUTION-LOG append schema requiring wave id, commit SHA, gate-command, attestation source (orchestrator-written only), and exit-register delta; tools/attestation.py — host-computed attestation; a sub-agent-authored attestation is rejected and does not count; tests/test_trace_and_faults_2026_07_29.py; gate-command: pytest -v tests/test_trace_and_faults_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W8 — Phase 2: Tri-state conformance harness + failure-state table validator

**done-when:** Each surface wave can emit a schema-valid end-to-end trace, inject one fault per named failure reason, and append an EXECUTION-LOG row whose attestation is host-computed and whose commit SHA is present.

- **Given** a surface wave reporting GREEN with no trace artifact, **when** execution_log.append runs, **then** it rejects the row citing 'no end-to-end trace' and the wave is not GO
- **Given** an attestation string written by a sub-agent into its report, **when** attestation.py counts attestations, **then** it counts zero and reports the sub-agent-authored claim as non-evidence
- **Given** a trace artifact with no proof_level stamp, or one claiming a human-driven user path, **when** the schema validator runs, **then** it rejects the artifact — only S1 may claim the user path, and every build-time trace must say so on its face

## Wave 10 — W10 — Phase 3: Open + Run control honesty (dead-control contract, named cannot-* states, e2e traces)

**Intent:** Engineer the leading clause of the North Star instead of assuming it. 'Open' and 'run' each get a live control governed by a dead-control contract, a surface-native failure-state table, named cannot-open / cannot-run states, and their own end-to-end traces. This wave also ships the shared dead-control primitive that attach (W11) and restart (W17) import, and it is the **named early vertical slice**: after W10 the build reaches one honest user-facing path — explicitly labelled PARTIAL, because usage, cost, Doctor, stop/restart, preview, and cadence are still unbuilt.

**Deliverables:** anchor/ui/dead_control.py — the shared dead-control contract: a control is emitted only when its capability verdict is PRESENT on a non-STALE inventory row (W3/W5); otherwise the surface renders a named cannot-* state through render_state (W6) and emits no clickable element at all; anchor/session/open_work.py — the open path, returning opened work or CannotOpen(reason) with reasons enumerated (no such project, project store unreadable, workspace locked, capability absent); anchor/session/run_work.py — the run path, returning a live run handle or CannotRun(reason) with reasons enumerated (no runnable target, engine unavailable, prior run still in flight, capability absent); anchor/ui/open_run_view.py — both controls rendered exclusively through dead_control.py + render_state; a dead Open or Run button is a build failure, not a finding to file later; planning/sleep-2026-07-28/stage2/artifacts/failure-states/open-run.md — surface-native failure-state table, unknown and empty as SEPARATE rows, every row mapped through STATE-VOCABULARY-MAP.md (W8); trace artifacts artifacts/traces/open-e2e.json and artifacts/traces/run-e2e.json — control invocation → handler → capability call → rendered state, one induced fault per enumerated reason, proof_level: rendered-string; planning/sleep-2026-07-28/stage2/artifacts/EARLY-SLICE-PARTIAL.md — the labelled partial-slice declaration: what is honest after W10 and what is still unbuilt, written so no reader can mistake the slice for the North Star; tests/test_open_run_2026_07_29.py — dead-control audit over both controls, cannot-* rendering per enumerated reason, tri-state conformance, visible-text-node assertions, node --check; gate-command: pytest -v tests/test_open_run_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema

**done-when:** Open and Run each render a working control or a named cannot-open / cannot-run state with no dead button in any state, both carry schema-valid e2e traces under one induced fault per enumerated reason, their failure-state table separates unknown from empty and maps cleanly to the vocabulary file, and EARLY-SLICE-PARTIAL.md states in plain words that this slice is partial.

- **Given** the run capability is ABSENT on this build, **when** the workbench renders, **then** no Run button is emitted at all, a named cannot-run state with its reason is visible, and the dead-control audit finds zero clickable no-ops
- **Given** an open request for a project whose store cannot be read, **when** the open surface renders, **then** the unknown state appears — not 'no projects' — visibly distinct from the empty state shown when the project list is legitimately empty
- **Given** W3 recorded open or run as PRESENT and W5 signed 'no further work' for it, **when** this wave runs, **then** that control still emits its e2e trace and failure-state table: a PRESENT verdict removes build work, never evidence

## Wave 11 — W11 — Phase 3: Session attach honesty (timeout classified, no double-print, Retry viable or named)

**Intent:** Close criterion 2 and the Retry dead control from criterion 1: attach timeouts are classified as timeout, the error UI prints once, and Retry either re-issues a viable action or is replaced by a named cannot-retry state.

**Deliverables:** anchor/session/attach.py — timeout path classified as NamedState.timeout, distinct from unknown_session; single error emission (double-print regression killed); anchor/session/attach.py::retry_contract — returns a viable re-issue action or CannotRetry(reason); the control is not rendered when neither exists; anchor/ui/attach_view.py — renders through render_state (W6); Retry hidden rather than dead; planning/sleep-2026-07-28/stage2/artifacts/failure-states/attach.md — failure-state table with unknown and empty as separate rows; trace artifact: artifacts/traces/attach-e2e.json; tests/test_session_attach_2026_07_29.py — tri-state conformance + one induced fault per reason (timeout, unknown session, empty session list) + visible-text-node assertions + node --check; gate-command: pytest -v tests/test_session_attach_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W10 — Phase 3: Open + Run control honesty (dead-control contract, named cannot-* states, e2e traces)

**done-when:** An attach timeout renders the timeout state exactly once, Retry re-issues a viable action or is replaced by a named cannot-retry state with no dead control rendered, and the failure-state table separates unknown from empty.

- **Given** an attach request that exceeds the attach timeout, **when** John attaches from the session list, **then** the UI shows the timeout state (not 'unknown session'), the error text appears exactly once in the rendered HTML, and the trace artifact records control→handler→capability→state
- **Given** a session whose underlying process is gone so no retry is possible, **when** the attach error view renders, **then** no Retry control is present and a named cannot-retry state with its reason is shown instead
- **Given** an empty session list versus a session list that could not be queried, **when** the attach surface renders each, **then** two distinct visible labels appear (empty vs unknown) and the tri-state harness passes

## Wave 12 — W12 — Phase 3: Usage + time surfacing gated on the Rollup Evidence Gate

**Intent:** Produce the usage/time half of criterion 3 as a CANDIDATE-MET structure: dashboard, workbench tiles, and session chrome render only PROVEN rollups; a NO_AGGREGATOR rollup renders pending, a READ_FAILED rollup renders unknown, and a PROVEN rollup totalling 0 over a real scope renders zero_measured — three different labels, and never a silent zero.

**Deliverables:** anchor/usage/rollup_read.py — reads only rollups marked PROVEN in rollup_registry.py (W4); a NO_AGGREGATOR read raises at test time and a READ_FAILED read resolves to unknown, never to 0 and never to pending; anchor/ui/usage_tiles.py — dashboard tile, workbench tile, and session chrome all rendering through render_state; pending / unknown / empty / zero_measured are four distinct visible labels carrying the binding definitions; as_of stamping on any E2 'provisional data' usage or time count, with the post-hoc reconciliation hook; planning/sleep-2026-07-28/stage2/artifacts/failure-states/usage-time.md — surface-native rows, unknown and empty as separate rows, mapped through STATE-VOCABULARY-MAP.md; trace artifact: artifacts/traces/usage-e2e.json; tests/test_usage_time_surfacing_2026_07_29.py — tri-state conformance across all three surfaces, induced faults (scope legitimately empty, aggregator returns a measured zero, query failure, absent aggregator), rendered-HTML assertions, node --check; gate-command: pytest -v tests/test_usage_time_surfacing_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema

**done-when:** Every usage and time value on the dashboard, workbench tiles, and session chrome traces to a PROVEN rollup or renders the correct named state for its verdict, a genuine measured zero renders as zero_measured rather than pending or empty, and no surface renders a bare 0 for a value that was never aggregated.

- **Given** a usage rollup marked NO_AGGREGATOR by W4, **when** the dashboard renders, **then** the tile shows the labelled pending state naming the aggregation wave it awaits, and no numeral appears in that tile
- **Given** a rollup that is PROVEN with sub-verdict zero_measured for today over sessions that do exist, **when** the workbench tile renders, **then** it shows the measured zero with the zero_measured label — visibly distinct from empty, pending, and unknown — because a legitimate zero is a fact this build must be able to tell
- **Given** a rollup marked READ_FAILED, **when** the session chrome renders, **then** the unknown state appears and the tile carries no numeral and no pending wording
- **Given** a usage count shipped under a signed E2, **when** the surface renders it, **then** an as_of stamp is visible alongside the number and a reconciliation entry exists in EXECUTION-LOG.md

## Wave 13 — W13 — Phase 3: Cost surfacing from cost_state (never a fabricated dollar)

**Intent:** Close the cost half of criterion 3 on real surfaces: every dollar rendering derives from cost_state, unmeasured engines show a labelled unmeasured state, and a failed measurement shows measurement_failed rather than a number under a disclaimer.

**Deliverables:** anchor/ui/cost_view.py — dashboard, workbench, and session chrome cost renderings routed exclusively through render_cost.py (W7); removal of every direct dollar-format call site; zero_inference_lint.py wired into this wave's gate; unmeasured-engine path: labelled unmeasured state, never blank, never $0.00; planning/sleep-2026-07-28/stage2/artifacts/failure-states/cost.md — unknown and empty as separate rows, plus unmeasured and measurement_failed rows; trace artifact: artifacts/traces/cost-e2e.json; tests/test_cost_surfacing_2026_07_29.py — zero×cost_state matrix on real rendered HTML, induced measurement failure, node --check; gate-command: pytest -v tests/test_cost_surfacing_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema

**done-when:** No rendered surface can produce a dollar figure that is not backed by cost_state == measured, the zero×state matrix is green on real HTML, and zero_inference_lint.py reports no violations in cost code.

- **Given** an engine with no cost instrumentation, **when** the session chrome renders its cost, **then** a labelled unmeasured state is visible and the rendered HTML contains no '$' figure for that engine
- **Given** a cost aggregation that raises at read time, **when** the dashboard cost tile renders, **then** measurement_failed is shown and no attempt to sign E2 for that tile is accepted by the exit register

## Wave 14 — W14 — Phase 3: Doctor really diagnoses + banner→Doctor issue payload

**Intent:** Close criterion 4's core and the Diagnose dead control from criterion 1: Diagnose performs a real diagnosis rather than shell/seed/plan-only theater, and the banner hands its issue payload to Doctor.

**Deliverables:** anchor/doctor/diagnose.py — real diagnosis routine per the W3 inventory verdict ('build it' where the probe returned STUB): every finding is derived from a reading taken at diagnose time (a value, path, version, or count read from the live system) and carries that reading with it; **fixed seed strings are banned** — no rendered finding text may be a source literal, and no branch may map an injector tag to pre-written prose; planning/sleep-2026-07-28/stage2/artifacts/FAULT-FINDING-CONTRACTS.md — one row per injectable fault: the fault, the reading it must change, and the expected finding *shape* (never its wording), so 'the outputs differ' is not accepted as proof of diagnosis; **a multi-branch template mapping injector tags to polished prose fails this wave by construction**, because the anti-template test drives a fault absent from the contract table and requires the finding to still quote a live reading; anchor/doctor/banner_handoff.py — banner passes the issue payload (issue id, source, observed symptom) into the Doctor entry point; 'not re-derived from scratch' is defined mechanically: the payload id and the hash of (issue id, source, observed symptom) computed at the banner are byte-identical to those the Doctor entry point receives and records in the trace, and Doctor re-running its own detection to reconstruct the issue is a test failure; anchor/ui/doctor_view.py — Diagnose control rendered only when the capability is PRESENT after this wave; otherwise a named unavailable state, never a dead button; planning/sleep-2026-07-28/stage2/artifacts/failure-states/doctor-diagnose.md — unknown and empty as separate rows; trace artifact: artifacts/traces/doctor-diagnose-e2e.json (banner click → payload → diagnosis → rendered findings); tests/test_doctor_diagnose_2026_07_29.py — a fault-to-finding contract test for every row of FAULT-FINDING-CONTRACTS.md; an anti-template test injecting a fault absent from the contract table, asserting the finding still quotes a live reading (or renders the named no-finding state) rather than falling through to generic prose; a literal-scan test asserting no rendered finding string appears as a literal in the source; payload propagation asserted by id and hash; rendered-HTML assertions; node --check; gate-command: pytest -v tests/test_doctor_diagnose_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema

**done-when:** Clicking Diagnose from the banner runs a diagnosis whose findings carry live readings and satisfy every fault-to-finding contract — including for a fault absent from the contract table — the issue payload arrives with an identical id and hash, no finding string is a source literal, and no dead Diagnose control is rendered in any state.

- **Given** each fault listed in FAULT-FINDING-CONTRACTS.md, **when** Diagnose runs, **then** the finding matches that row's expected shape and quotes the reading the fault changed — differing output alone does not pass
- **Given** a fault that is NOT in the contract table, **when** Diagnose runs, **then** the finding still quotes a live reading, or the named no-finding state renders; falling through to generic prose fails the wave, which is what makes a tag-to-prose template unable to pass
- **Given** a health banner reporting a specific issue, **when** John clicks through to Doctor, **then** the Doctor view shows that issue's payload with a byte-identical id and hash recorded in the trace, and any re-detection by Doctor fails the test
- **Given** the diagnose capability unavailable in a given environment, **when** the Doctor view renders, **then** a named unavailable state appears in place of the control and the tri-state harness confirms it is not a clickable no-op

## Wave 15 — W15 — Phase 3: Per-engine independent diagnose for Claude, Gemini, Grok with depth labels

**Intent:** Close the rest of criterion 4: each engine reports independently rather than one engine's result being echoed for all three, and each report carries its depth label.

**Deliverables:** anchor/doctor/engines/{claude,gemini,grok}.py — independent probes, each with its own failure path and its own named state; anchor/doctor/depth_label.py — depth vocabulary (e.g. deep, shallow, unavailable) attached to each engine report; an unlabelled report is rejected; anchor/ui/doctor_view.py — three independently-stated rows; one engine failing does not blank or fake the other two; planning/sleep-2026-07-28/stage2/artifacts/failure-states/doctor-engines.md — unknown and empty as separate rows, per engine; trace artifact: artifacts/traces/doctor-engines-e2e.json; tests/test_doctor_engines_2026_07_29.py — per-engine isolation test (fault one, assert other two unaffected), depth-label presence, rendered-HTML assertions, node --check; gate-command: pytest -v tests/test_doctor_engines_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W14 — Phase 3: Doctor really diagnoses + banner→Doctor issue payload

**done-when:** Claude, Gemini, and Grok each produce a depth-labelled report from their own probe, and inducing a fault in one engine leaves the other two reports intact and correctly labelled.

- **Given** Gemini's probe timing out while Claude and Grok succeed, **when** the Doctor view renders, **then** Gemini shows the timeout state with its depth label, and Claude and Grok show their own real results — no shared verdict, no blanked rows
- **Given** an engine report produced without a depth label, **when** depth_label validation runs, **then** the wave gate fails naming the engine and the unlabelled report

## Wave 16 — W16 — Phase 3: Stop summary tile backed by real in-flight inventory

**Intent:** Close the stop/summary half of criterion 5: stopping leaves a tile that summarizes actual in-flight work from an inventory source proven by W3, not a placeholder.

**Deliverables:** anchor/session/stop_summary.py — collects in-flight work at stop time from the inventory source named in CAPABILITY-INVENTORY.md; returns structured items with counts; anchor/ui/stop_summary_tile.py — renders through render_state; distinguishes 'nothing was in flight' (empty) from 'in-flight state could not be read' (unknown); planning/sleep-2026-07-28/stage2/artifacts/failure-states/stop-summary.md — unknown and empty as separate rows; trace artifact: artifacts/traces/stop-summary-e2e.json; tests/test_stop_summary_2026_07_29.py — induced faults (inventory unreadable, zero items, partial items), rendered-HTML assertions, node --check; gate-command: pytest -v tests/test_stop_summary_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema

**done-when:** Stopping a session with known in-flight work produces a tile listing that work from the proven inventory source, and an unreadable inventory renders unknown rather than an empty-looking summary.

- **Given** a session stopped with three in-flight items, **when** the stop summary tile renders, **then** all three items appear with counts traceable to the inventory query, asserted as visible text nodes
- **Given** a session stopped while the in-flight inventory read fails, **when** the tile renders, **then** the unknown state is shown, visibly distinct from the 'nothing in flight' empty state

## Wave 17 — W17 — Phase 3: Per-context restart contract — exactly one control, scope + preserved/lost named

**Intent:** Close criterion 5's restart half and criterion 1's restart clause: enumerate every restart context, guarantee exactly one restart control per context, and make each control state its scope name and preserved/lost contract. Cross-context unification is explicitly out of scope.

**Deliverables:** planning/sleep-2026-07-28/stage2/artifacts/RESTART-CONTEXTS.md — the enumeration, each with its single control, scope name, and written preserved/lost contract; anchor/session/restart.py — one restart entry point per enumerated context, each returning a viable action or a named cannot-restart state; anchor/ui/restart_controls.py — render-time invariant: a context offering two restart controls fails the build; tools/restart_control_audit.py — scans rendered HTML per context and asserts control count == 1; planning/sleep-2026-07-28/stage2/artifacts/failure-states/restart.md — unknown and empty as separate rows; trace artifact: artifacts/traces/restart-e2e.json per context; tests/test_restart_contract_2026_07_29.py — per-context restart executes and the preserved/lost outcome matches the written contract; dual-control detection test; node --check; gate-command: pytest -v tests/test_restart_contract_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W10 — Phase 3: Open + Run control honesty (dead-control contract, named cannot-* states, e2e traces)

**done-when:** Each enumerated restart context renders exactly one working restart control that names its scope and preserved/lost contract, and a test proves the restart's actual preserved/lost behaviour matches that written contract.

- **Given** a context that currently renders both a 'Restart' and a 'Restart session' control, **when** restart_control_audit.py runs against its rendered HTML, **then** the wave fails naming the context and both controls, until one is removed
- **Given** a restart control whose contract says 'transcript preserved, running tool calls lost', **when** the restart executes in test, **then** the transcript is present and the tool calls are absent afterwards, matching the contract line asserted by the test
- **Given** a context where restart is not possible on this build, **when** its view renders, **then** a named cannot-restart state appears instead of a control, and no dead button is present

## Wave 18 — W18 — Phase 3: File preview via the shared human-friendly path (no raw binary as text)

**Intent:** Close criterion 6: route Word/PPTX/Excel/PDF preview through the already-working new-window path so binary never dumps as text.

**Deliverables:** anchor/files/preview.py — single shared preview path reusing the working new-window renderer for docx, pptx, xlsx, pdf; binary guard: any content-type without a human-friendly renderer yields a named unsupported-preview state plus a download affordance — never a raw byte dump; anchor/ui/preview_view.py — rendering through render_state; unknown (probe failed) distinct from empty (zero-byte file); planning/sleep-2026-07-28/stage2/artifacts/failure-states/preview.md — unknown and empty as separate rows; trace artifact: artifacts/traces/preview-e2e.json; tests/test_file_preview_2026_07_29.py — one fixture per format asserting human-friendly output, a binary-guard test asserting no raw byte sequence in rendered HTML, node --check; gate-command: pytest -v tests/test_file_preview_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema

**done-when:** docx, pptx, xlsx, and pdf previews render human-friendly output through the shared path, and no code path can emit raw binary into a text view — proven by a fixture asserting the absence of raw bytes.

- **Given** a .docx file opened from the file list, **when** preview renders, **then** human-readable document content appears via the shared new-window path and the rendered HTML contains no 'PK\x03\x04' or other raw byte signature
- **Given** a file type with no human-friendly renderer, **when** preview renders, **then** a named unsupported-preview state with a download option is shown rather than a text dump
- **Given** a zero-byte file versus a file whose type probe failed, **when** each is previewed, **then** the empty state and the unknown state render as two distinct visible labels

## Wave 19 — W19 — Phase 3: Projects collapsed by default + remembered preference (dual-profile verified)

**Intent:** Close criterion 7 at the real root cause: folders open collapsed by default via the actual JS/CSS path, and the user's expand/collapse preference persists — verified across two profiles.

**Deliverables:** anchor/ui/projects_tree.py + static/js/projects_tree.js — collapsed-by-default default state fixed at the real JS/CSS path identified in the inventory, not by a cosmetic override; preference persistence: per-user stored collapse state with a named unknown state when the preference store is unreadable; planning/sleep-2026-07-28/stage2/artifacts/root-cause-projects-collapse.md — the actual defect mechanism, written down; planning/sleep-2026-07-28/stage2/artifacts/failure-states/projects-collapse.md — unknown and empty as separate rows (no projects vs project list unreadable); tests/test_projects_collapse_2026_07_29.py — rendered-HTML assertion that folders carry the collapsed class on first load, dual-profile persistence test, node --check on the tree script block; gate-command: pytest -v tests/test_projects_collapse_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema

**done-when:** A fresh load renders every project folder collapsed, a changed preference survives reload for each of two distinct profiles, and the written root cause matches the code that was changed.

- **Given** a first-ever load for profile A, **when** the projects panel renders, **then** the rendered HTML shows all folders in the collapsed state and node --check passes on the tree script block
- **Given** profile A expands two folders and profile B expands none, **when** each profile reloads, **then** profile A sees its two folders expanded and profile B sees all collapsed — no cross-profile bleed
- **Given** the preference store is unreadable, **when** the panel renders, **then** it falls back to collapsed and shows the named unknown-preference state rather than silently appearing as a user choice

## Wave 20 — W20 — Phase 3: Status cadence owned by Anchor from live telemetry with as_of + staleness

**Intent:** Close criterion 8: a real timer-driven cadence reading live telemetry, with as_of stamping and named staleness states — not prose that resembles a scheduler.

**Deliverables:** anchor/status/cadence.py — timer-owned cadence loop reading live telemetry; emits as_of on every status; anchor/status/staleness.py — named states: fresh, stale (with age), unknown (telemetry unreachable); no status renders without an as_of; anchor/ui/status_view.py — renders cadence through render_state; a stale status is visibly labelled stale, never presented as current; planning/sleep-2026-07-28/stage2/artifacts/failure-states/cadence.md — unknown and empty as separate rows; trace artifact: artifacts/traces/cadence-e2e.json; tests/test_status_cadence_2026_07_29.py — timer fires and updates as_of, induced telemetry outage yields unknown, aged sample yields stale-with-age, rendered-HTML assertions, node --check; gate-command: pytest -v tests/test_status_cadence_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema

**done-when:** Status updates are produced by an Anchor-owned timer from live telemetry, every rendered status carries an as_of, and stale and unknown telemetry render as distinct named states.

- **Given** live telemetry available and the cadence timer running, **when** two cadence intervals elapse, **then** the rendered status as_of advances and the test asserts the value came from telemetry, not from a static string
- **Given** telemetry unreachable for longer than the staleness threshold, **when** the status renders, **then** the stale label with its age appears, and on total unreachability the unknown state appears — never a confidently current-looking status

## Wave 21 — W21 — Phase 4: Unnamed-control sweep + dead-control audit + traceability matrix

**Intent:** Close the controls the ten criteria do not name and prove coverage: sweep for remaining dead controls, ambiguous zeros, and mislabelled empties; close each out-of-criteria surface honestly (E3 only where the surface is already honest or removed); and complete the traceability matrix.

**Deliverables:** tools/dead_control_audit.py — enumerates every rendered control and asserts each is wired, hidden, or replaced by a named state; tools/ambiguous_zero_audit.py — sweeps rendered HTML for numerals and blanks not produced by render_state / render_cost; planning sleep-2026-07-28/stage2/artifacts/TRACEABILITY-MATRIX.md — criterion → wave → test file → commit SHA → trace artifact → status, one row per criterion 1–10; status may only be CANDIDATE-MET (structural, rendered-string level) or OPEN, and a MET stamp before S1 fails the validator; **surface-wave join gate** — this wave cannot report GO until every surface wave W10–W20 has a GREEN row with a commit SHA in EXECUTION-LOG.md, so the sweep can never run over an unbuilt surface and mistake absence for cleanliness; planning/sleep-2026-07-28/stage2/artifacts/OUT-OF-CRITERIA-SURFACES.md — each closed as fixed, disabled, or a signed E3 with proof the surface is already honest; exit-register reconciliation: conjunction score recomputed; a fourth exit or a second on one criterion triggers the re-baseline HALT; tests/test_sweep_and_traceability_2026_07_29.py; gate-command: pytest -v tests/test_sweep_and_traceability_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded

**Depends on:** W20 — Phase 3: Status cadence owned by Anchor from live telemetry with as_of + staleness

**done-when:** Every surface wave W10–W20 is GREEN with a commit SHA in EXECUTION-LOG.md, the dead-control and ambiguous-zero audits report zero findings across all surfaces, every criterion 1–10 has a complete traceability row stamped CANDIDATE-MET with no row claiming MET, and every out-of-criteria surface is fixed, disabled, or closed under a signed E3 that proves the surface is honest.

- **Given** a control outside the ten criteria that is bound to a missing capability, **when** dead_control_audit.py runs, **then** it is reported as a finding and E3 is rejected for it until the control is fixed or removed from view
- **Given** a criterion row with a test file but no commit SHA or trace artifact, **when** the traceability matrix validator runs, **then** the wave fails naming the incomplete row rather than reporting the criterion as met

## Wave 22 — W22 — Phase 5: S1 post-build validation session + terminal status emission

**Intent:** Run S1 — the only gate authorized to declare the North Star met — as an explicit live validation session with John, route findings correctly (the four violation classes are build-blocking, never E6), and emit the terminal status string from the exit register rather than by hand.

**Deliverables:** planning/sleep-2026-07-28/stage2/artifacts/S1-VALIDATION.md — the live session script over the W1 verification task triple: open, run, stop, restart, Doctor diagnose, session attach on branch v1.2, with John's dated result per step; anchor/build/s1_findings.py — classifies each finding; dead control / silent zero / mislabelled empty / raw-binary preview are BUILD_BLOCKING and cannot be routed to E6; terminal status emitted by exit_register.terminal_status() — 'ten criteria CANDIDATE-MET (structural, rendered-string level) with N signed exits (E<ids>); North Star pending S1' until S1 returns a verdict; unqualified phrasing only at zero exits and S1 PASS; S1 is the only gate that converts a criterion's CANDIDATE-MET stamp to MET, and a criterion S1 fails reverts to OPEN in TRACEABILITY-MATRIX.md; release guard: tools/release_guard.py — asserts nothing from this effort is publishable to v1.1.x collaborators (branch and channel check); tests/test_s1_and_status_2026_07_29.py — finding-classification tests, status-string tests, release-guard test; gate-command: pytest -v tests/test_s1_and_status_2026_07_29.py; EXECUTION-LOG.md append + commit SHA recorded; host-computed attestation count reported

**Depends on:** W21 — Phase 4: Unnamed-control sweep + dead-control audit + traceability matrix

**done-when:** S1 has been run live with John over the verification task triple, every finding is classified with the four violation classes held build-blocking, the release guard proves nothing ships to v1.1.x, and the terminal status string is machine-emitted from the exit register — S1's recorded verdict being the only thing that can declare the North Star met.

- **Given** S1 reproduces a dead Diagnose control, **when** s1_findings.py classifies it, **then** it is BUILD_BLOCKING, E6 routing is rejected, and the build does not report the North Star as met
- **Given** S1 passes every step and zero exits are signed, **when** terminal_status() runs, **then** it emits the unqualified 'ten criteria met' phrasing with S1's PASS verdict attached
- **Given** S1 has not yet been run while all structural gates are green, **when** status is reported, **then** it reads 'ten criteria CANDIDATE-MET (structural, rendered-string level) with N signed exits (E<ids>); North Star pending S1' and no silent green is derived from structure tests alone

## Property gates (hardening law — crucible journal 0080)

### honesty — asserted by this plan
_the recurring defect is a confident wrong answer, not a crash_

- [ ] a failure-state table
- [ ] unknown and empty as SEPARATE rows

### idempotence — asserted by this plan
_idempotence is only real if something re-invokes and asserts no change_

- [ ] a repeat-invocation test

### boundedness — asserted by this plan
_an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard_

- [ ] the numeric bound named in the plan
- [ ] a refusal path when the bound is exceeded

### containment — asserted by this plan
_containment is asserted far more often than it is exercised_

- [ ] an escape-attempt test (.., absolute path, symlink)

A property named in the plan and absent from this list is a BLOCKER:
the plan is claiming a guarantee nothing enforces.

## Hardening-gate obligations (mechanical — journal 0080)

This section is the **emitted** property-gate checklist. A claim in the plan without a matching obligation below is a BLOCKER.

### Property `honesty`
_the recurring defect is a confident wrong answer, not a crash_

- **Gate:** a failure-state table
- **Gate:** unknown and empty as SEPARATE rows

### Property `idempotence`
_idempotence is only real if something re-invokes and asserts no change_

- **Gate:** a repeat-invocation test

### Property `boundedness`
_an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard_

- **Gate:** the numeric bound named in the plan
- **Gate:** a refusal path when the bound is exceeded

### Property `containment`
_containment is asserted far more often than it is exercised_

- **Gate:** an escape-attempt test (.., absolute path, symlink)

### Storage mechanism vocabulary (required when durability is claimed)

- **atomic write** via **temp** + **fsync** + **rename** for snapshot (and durable JSON) paths
- cross-process **lock** or documented **serialization** around multi-writer index paths
- a **concurrency test** (two real processes; assert no event/receipt dropped)
- where "exactly once" / identity is claimed: a **repeat-invocation test**
- where containment is claimed: an **escape-attempt** test (`..`, absolute path, symlink/junction)
- where bounds are claimed: the **numeric bound** named (e.g. 10000 rows / 50000 events) and a **refusal** path when exceeded

### Failure-state table vocabulary (required when addsSurface)

Every surface-bearing wave answers these **five** states with named status code AND user-visible text.
**unknown** and **empty** are SEPARATE rows (never collapsed), and each row is written in the surface's own actions
(open, run, attach, diagnose, preview, restart, tile render) — index / rebuild / reconcile verbs belong only to
index-bearing surfaces, and using them on a user-facing tile fails `table_validator.py` as honesty theater.
Every row's term must resolve through `STATE-VOCABULARY-MAP.md`; a missing required row or an unmapped term fails the wave.

- **dependency-missing** — status code + user-visible text per surface, in that surface's own actions; maps to a NamedState via the vocabulary file
- **dependency-slow-or-killed** — status code + user-visible text per surface, in that surface's own actions; maps to a NamedState via the vocabulary file
- **dependency-returns-garbage** — status code + user-visible text per surface, in that surface's own actions; maps to a NamedState via the vocabulary file
- **backing-store-unreadable** — status code + user-visible text per surface, in that surface's own actions; maps to unknown (never to empty, never to a zero)
- **empty-but-valid** — status code + user-visible text per surface, in that surface's own actions; splits into **empty** (no scope) and **zero_measured** (measured zero) per the binding definitions, plus **pending** where no aggregator exists yet

See also wave-local failure tables (hardening-gate 0080 format) and generated red stubs.
