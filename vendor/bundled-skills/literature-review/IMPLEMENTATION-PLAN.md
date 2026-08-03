# 2D breadth scoping (literature-review + researchPrime) — Implementation Plan (Foreman-ready)

test-command: node --test test/
# Wave-5 dual-suite (orchestrator-owned second measurement; both must be green):
#   researchPrime: (cd <RP_ROOT> && npm test)  # package.json scripts.test = "node --test test/"
# dual-suite-gate.test.mjs may only assert presence/wiring; it MUST NOT substitute for the RP suite run.

**North Star:** Give literature-review and researchPrime Deep-Research-style 2D coverage: after plan APPROVE, fan out across PlanArtifact.branches as facets, gather breadth in parallel (isolated workers, per-facet snowball), merge+dedupe, then existing depth+verification — without inventing silent facets or breaking RP convergent verification / lit-review PRISMA honesty.

## Success criteria
- Facets from approved PlanArtifact.branches after APPROVE; empty → honest stamp, no invented facets.
- Breadth after APPROVE before main snowball/Phase-2; ordering test-proven.
- Parallel isolated-worker per-facet gather; cap; failure isolation; stable merge order.
- Merge+dedupe; multi-seed shared across facets (not seeds×facets).
- researchPrime pre-Phase-2 facet coverage; oranges prunes answer-branches only.
- literature-review wires GAP C; matrixScheduler not v1 primary.
- No regression; honesty stamps; suites green.

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — Wave 1 — Facet materialization (facetsFromPlan)

**Intent:** Close GAP C: materialize stable Facet records from approved PlanArtifact.branches with honest empty/axis stamps so both skills can fan out without inventing silent facets.

**Deliverables:** Facet type/shape: { id, question, sourceBranchId?, order }; Pure facetsFromPlan(plan) → { facets, stamp } with stamps breadth:from-branches | breadth:axis-only | breadth:none; Unit tests: N≥2 branches → N facets; 0 branches → no invented facets; stable order; Skill-local module (prefer lit-review src/ as first home; pure helper importable by RP)

**Depends on:** —

**done-when:** facetsFromPlan is pure, tested, and never invents facets when branches are empty.

- **Given** An approved PlanArtifact with N≥2 branches, **when** facetsFromPlan is called, **then** Exactly N facets are returned in stable order with stamp breadth:from-branches and each facet traces to a sourceBranchId
- **Given** An approved PlanArtifact with empty branches (and no axis fallback usable as facets), **when** facetsFromPlan is called, **then** facets is empty or a single honest non-invented path with stamp breadth:none or breadth:axis-only — no silent synthetic facets
- **Given** The same plan object twice, **when** facetsFromPlan is called twice, **then** Facet ids and order are identical (deterministic)

## Wave 2 — Wave 2 — Lit-review post-APPROVE breadth hook (sequential)

**Intent:** Wire literature-review post-APPROVE to call facetsFromPlan before any main snowball; prove breadth-before-depth ordering with a sequential per-facet gather path (no parallelism yet).

**Deliverables:** Post-APPROVE CLI/path hook: facetsFromPlan before snowball/Phase-2-equivalent; Sequential per-facet scoped gather using shared multi-seed set + facet question as scope bias; Gate: path active only when plan APPROVED and facets.length ≥ 1; empty → honest no-breadth stamp, existing single path; Ordering/integration tests proving breadth stage runs after APPROVE and before main snowball

**Depends on:** Wave 1 — Facet materialization (facetsFromPlan)

**done-when:** Lit-review after APPROVE materializes facets and gathers breadth sequentially before main snowball; empty facets honest-stamp without invented work.

- **Given** An APPROVED plan with ≥1 facets and multi-seed set S, **when** lit-review runs the post-APPROVE path, **then** facetsFromPlan runs first; per-facet gathers use shared S (not |S|×|facets| cartesian); main snowball/depth starts only after breadth stage completes
- **Given** An APPROVED plan with 0 facets (breadth:none), **when** lit-review runs post-APPROVE, **then** No invented facets; honest stamp recorded; existing non-breadth path proceeds unchanged
- **Given** Plan not yet APPROVED, **when** breadth path is considered, **then** Facet breadth gather does not run

## Wave 3 — Wave 3 — Parallel per-facet workers + merge/dedupe

**Intent:** Ship Deep-Research-style parallel breadth: isolated-worker per-facet gather with concurrency cap, failure isolation, deterministic merge order, and identity-stable dedupe into one corpus.

**Deliverables:** Schedule per-facet jobs via existing concurrency manager / isolated-worker stack; default cap ≤2–3; Per-facet failure isolation: failed facet stamps honest error; siblings complete; Deterministic merge by facet.order then paper/source id; Dedupe by existing lit-review stable identity rules; multi-seed shared across facets; Integration test: fixture plan with 2 facets and overlapping papers → single corpus entry

**Depends on:** Wave 2 — Lit-review post-APPROVE breadth hook (sequential)

**done-when:** Parallel isolated per-facet gather merges to one deduped corpus with stable order, capped concurrency, and sibling-safe failures.

- **Given** APPROVED plan with 2 facets and overlapping paper identities across facets, **when** parallel breadth gather + merge runs, **then** Merged corpus has one entry per stable identity; merge order is facet.order then paper id
- **Given** One facet worker fails mid-gather, **when** siblings are still running, **then** Failed facet records an honest error stamp; other facets complete and contribute to the merge
- **Given** Default concurrency settings, **when** ≥3 facets are scheduled, **then** At most 2–3 facet workers run concurrently (cap enforced)

## Wave 4 — Wave 4 — researchPrime pre-Phase-2 facet coverage

**Intent:** Insert RP pre-Phase-2 coverage stage: gather evidence per facet into a coverage substrate without treating facets as answer-branches; oranges still prunes answer branches only; Phase-2+ uses merged substrate.

**Deliverables:** Pre-Phase-2 stage after plan gate: facetsFromPlan + per-facet evidence/context gather (reuse RP/search primitives; no oranges on facets); facetCoverage: { facets, hits, stamp } written into run record; Phase-2+ continues on merged coverage substrate; self-review/verification seats unchanged (REVIEW_FAMILY); Tests: 2-branch plan records facetCoverage before Phase-2; oranges never receives facets as answer branches; RP suite green for this path

**Depends on:** Wave 3 — Parallel per-facet workers + merge/dedupe

**done-when:** RP records facet coverage before Phase-2 from approved branches; verification/oranges semantics unchanged for answer branches.

- **Given** A 2-branch approved PlanArtifact entering RP post-plan-gate, **when** pre-Phase-2 facet coverage runs, **then** Run record includes facetCoverage with both facets and hits before Phase-2 depth/verification starts
- **Given** Facet coverage substrate is present, **when** oranges pruning runs in Phase-2+, **then** Only answer-branches are pruned; facets are not modeled or pruned as answer branches
- **Given** Empty branches on approved plan, **when** RP pre-Phase-2 coverage is considered, **then** Honest no-breadth/axis stamp; no silent facets; existing Phase-2 path proceeds

## Wave 5 — Wave 5 — Honesty stamps, telemetry, dual-suite gate

**Intent:** Lock honesty/telemetry for the breadth stage across both skills, keep degraded live posture, ban API-style Gemini ids, and make full lit-review + researchPrime suites the terminal green gate (no regression to North Star verification/PRISMA).

**Deliverables:** Breadth-stage stamps in run telemetry for lit-review and RP (including empty/failure/from-branches); LITREVIEW_LIVE degraded posture preserved; no API-style Gemini model ids; review seats via gemini-cli labels; If trio-shared was not used, keep skill-local; if any shared surface was added earlier, verify-then-advance with tests in the tree Foreman measures; Terminal gate: full lit-review suite + RP suite green; document matrixScheduler broad-first as optional v1.1 non-goal follow-on only

**Depends on:** Wave 4 — researchPrime pre-Phase-2 facet coverage

**done-when:** literature-review full suite green (Foreman-measured) with breadth honesty stamps present; RP facet-coverage seam live (thin import of lit-review helpers); no regression to lit-review PRISMA honesty. Dual-suite: orchestrator records a second RP measurement when claimed — presence-only tests must not substitute. Nested Crucible/Foreman suite pins inside RP’s trio-green harness are portfolio health, not this wave’s product gate (see SHIP-RECEIPT.md).

- Orchestrator must record a second gate artifact for the RP suite (command + exit + pass/fail counts), not only literature-review `node --test test/`.
- **Given** A successful multi-facet lit-review run and a multi-branch RP run, **when** run telemetry/records are inspected, **then** Breadth stage is stamped (from-branches / none / facet errors as applicable) and no invented facets appear
- **Given** Existing lit-review test suite after Waves 1–5, **when** full suite runs, **then** All lit-review tests pass; RP verification/oranges semantics for answer branches unchanged
- **Given** Review/check seats in either skill path, **when** model labels are resolved, **then** No API-style Gemini product ids; gemini-cli / family labels only

## Wave 6 — Wave 6 — Shared extract only if proven duplication

**Intent:** Inclusion-test extract: if facetsFromPlan + merge helpers are still duplicated byte-for-byte after Waves 1–5, lift once to trio-shared/breadth (or brownfield-intake extension) with one import surface and tests in the measured tree; otherwise leave skill-local and stop.

**Deliverables:** Duplication audit of facetsFromPlan + merge/dedupe helpers across lit-review and RP; IF duplicated: single trio-shared (or agreed) module + both skills import it + tests that exercise the shared path in Foreman-measured trees (verify-then-advance); IF thin/not duplicated: no extract; interface note only as non-blocking comment in code or existing skill docs (no docs-only ship)

**Depends on:** Wave 5 — Honesty stamps, telemetry, dual-suite gate

**done-when:** Either one shared import surface is live with green tests in both consumers, or skill-local is retained with an explicit no-extract decision recorded in code comments/stamps.

- **Given** facetsFromPlan + merge helpers are byte-equivalent in both skills, **when** Wave 6 extract runs, **then** One shared module is the sole implementation; both skills import it; suites that exercise the shared path stay green
- **Given** Helpers differ or remain thin single-file pure functions with one test owner, **when** duplication audit completes, **then** No trio-shared change; skill-local retained; no vacuous shared package for greenwash
