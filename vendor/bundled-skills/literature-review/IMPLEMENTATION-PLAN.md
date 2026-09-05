# literature-review: an on-topic corpus by construction — Implementation Plan (Foreman-ready)

test-command: node --test test/index.mjs

**North Star:** # North Star — literature-review: an on-topic corpus by construction (2026-09-04)

**Statement.** Give the literature-review skill an on-topic corpus by construction: every
user-supplied seed is in the corpus with its text actually sourced, every candidate is ranked
by relevance to the seeds as well as by citations with a PRISMA-style off-topic exclusion
below a floor, and every run stamps how much of its extracted corpus was on-topic and refuses
to call synthesis a success below that floor — so an unattended run can no longer report
"18 grounded claims" over Fiji, PointNet++ and a shape GAN when the question was about learned
bases for 3D microscopy compression (journal 0010, the second live run).

**Why now.** Journal 0008 named the missing relevance term; journal 0010 reproduced it exactly:
132 snowballed papers, the 14 most cited kept, ten of twelve seeds never extracted ("no text
available" though OpenAlex had their abstracts), an unattended gate that rubber-stamped the
list, and a run record that counted papers but never said whether the corpus was about the
question. The steward wrote the review by hand. The engine ran to synthesis and was useless.

## Success criteria (the SURFACE, not the capability)

1. **Seeds always in.** A run with N user-supplied seeds shows all N in the candidate list and
   the PRISMA flow regardless of citation rank, each carrying a per-paper `text_source` stamp
   naming the link of the sourcing chain that supplied its text (provider abstract → OpenAlex
   abstract → Crossref abstract → arXiv/PMC full text → user-supplied PDF) or `none` with the
   chain's attempts listed. On the 0010 seed set, every seed that has an OpenAlex abstract is
   extracted.
2. **Relevance-ranked, off-topic excluded.** Candidate order is citation weight combined with
   similarity to the seed abstracts (TF-IDF cosine over title + abstract; deterministic, no
   network, no model). A candidate below a hard relevance floor is EXCLUDED before extraction
   and appears in the PRISMA exclusions as `off-topic` with its score and the seed it was
   nearest to. On the 0010 reference list, Fiji, U-Net, NumPy, ResNet and the Data Science Bowl
   are excluded as off-topic; the twelve seeds and their on-topic neighbours are not.
3. **A corpus-relevance stamp, and honesty below it.** The run record, the console summary and
   the ledger header carry `corpus_relevance` = the fraction of EXTRACTED papers at or above the
   floor plus the floor value; below a configurable minimum the run's own verdict is
   `corpus:off-topic` (never "synthesized N assumptions" alone) and the ledger is still
   written, stamped as partial.
4. **Nothing regresses.** The 463-test gate (`node --test test/`) stays green; new tests are
   hermetic (providers stubbed, no network); PRISMA discipline, deterministic quote-grounding,
   the safety floor, weighted synthesis and the single governed adversarial round are unchanged.

## Non-goals (parked to the Grasscatcher, named)

- (c) the generic-reference guard, (d) facets from the intent, (e) a coding-seat stand-in at the
  unattended gate, (g) the automatic reverse-arrow facet — follow-ons after (a)(b)(f) land.
- An embedding provider (TF-IDF is enough for this pass), a GUI, any change to the synthesis
  math or the adversarial round, any new external dependency.

## Risk taxonomy

| Risk | Mitigation |
|---|---|
| The relevance floor excludes a true on-topic paper written in different vocabulary | the floor is configurable, exclusions are logged with scores, seeds are exempt by construction |
| A sourcing chain link is slow or rate-limited (S2 429, OpenAlex 404 on a 2026 arXiv id) | bounded per-link timeout, each attempt stamped, the chain never blocks the run |
| TF-IDF over abstracts is noisy for short abstracts | title+abstract weighting; the floor applies to ranking only when a seed set exists |
| A green suite that never exercises the new code | every wave's done-when names a test that reads the new stamps on a fixture corpus |

## Foresight brief (2–3 steps ahead)

Once relevance is a first-class number, the unattended gate can become a real gate (e) and
the corpus can be stratified by facet (d) without re-plumbing; the per-paper `text_source`
stamp is the hook a user-supplied PDF drops into. The reverse-arrow rule (g) becomes one more
facet. None of that is in this pass.


## Success criteria
- Seeds always in: every user-supplied seed is in the candidate list and the PRISMA flow regardless of citation rank, each with a per-paper text_source stamp naming the sourcing-chain link that supplied its text (provider abstract -> OpenAlex abstract -> Crossref abstract -> arXiv/PMC full text -> user PDF) or none with the attempts listed
- Relevance-ranked, off-topic excluded: candidate order = citation weight combined with TF-IDF cosine similarity to the seed abstracts (pure JS, deterministic, no network, no model); below a configurable hard floor a candidate is EXCLUDED before extraction and logged in the PRISMA exclusions as off-topic with its score and nearest seed; seeds are exempt
- Corpus-relevance stamp: the run record, console summary and ledger header carry corpus_relevance (fraction of extracted papers at/above the floor + the floor); below a configurable minimum the run verdict is corpus:off-topic, the ledger is still written and stamped partial, and the run never reports success on counts alone
- No regression, hermetic proof: node --test test/ stays green (463 today); new tests are hermetic with providers injected and a fixture corpus reproducing the 0010 shape (seeds + field-generic giants) as the acceptance oracle; PRISMA discipline, quote grounding, the safety floor, synthesis math and the adversarial round unchanged; no new dependency

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — Canonical seed records and PRISMA retention

**Intent:** Serve Seeds always in by making every user seed a canonical, relevance-exempt candidate before snowballing or rank truncation.

**Deliverables:** Extend the canonical candidate record with stable identity, seed status, relevance exemption, text_source, and text_source_attempts fields.; Upsert every user-supplied seed before snowballing and rank truncation, retaining it regardless of citation rank.; Emit a PRISMA inclusion record for every seed.; Add hermetic injected-provider tests for seed survival through candidate assembly and rank truncation.

**Depends on:** —

**done-when:** A hermetic run with N seeds retains all N in both the canonical candidate list and PRISMA flow, including seeds that would otherwise be rank-truncated.

- **Given** A fixture with seeds below the candidate rank cutoff, **when** candidate assembly and truncation run, **then** all seeds remain candidates, are marked relevance-exempt, and appear in PRISMA.
- **Given** Duplicate representations of one seed, **when** seed ingestion runs, **then** the canonical candidate is upserted by stable identity rather than duplicated.

## Wave 2 — Provenance-bearing text acquisition

**Intent:** Serve Seeds always in by routing seed and non-seed extraction through one bounded, auditable sourcing chain.

**Deliverables:** Implement an injected, bounded sourcing-chain helper ordered provider abstract, OpenAlex abstract, Crossref abstract, arXiv/PMC full text, then user-supplied PDF.; Record structured applicable/skipped, success/failure, timeout, and error outcomes for every attempted source.; Set text_source to the winning source or none only after all applicable links fail.; Route extraction for seeds and ordinary retained candidates through the same provenance shape.; Add hermetic tests for OpenAlex fallback, winning-source stamps, and complete failed-attempt stamps.

**Depends on:** Canonical seed records and PRISMA retention

**done-when:** A seed with no provider text but an injected OpenAlex abstract is extracted with text_source OpenAlex and a complete ordered attempt trail.

- **Given** A seed whose provider abstract is empty and OpenAlex returns an abstract, **when** extraction runs, **then** the seed is extracted and stamped with OpenAlex as text_source.
- **Given** A candidate for which every applicable source fails or times out, **when** extraction runs, **then** it is stamped text_source none with structured attempts for every applicable chain link.

## Wave 3 — Deterministic relevance scoring and pre-extraction screening

**Intent:** Serve Relevance-ranked, off-topic excluded by ranking non-seed candidates with pure-JS TF-IDF relevance plus citation weight and excluding weak matches before extraction.

**Deliverables:** Implement dependency-free deterministic TF-IDF cosine scoring over normalized title and abstract text with explicit title weighting.; Record each candidate's relevance score and nearest_seed identity, with stable behavior for missing text and no-seed runs.; Deterministically normalize citation weight and combine it with relevance using stable identity/order tie-breakers.; Add configurable relevance_floor active only when seeds exist; preserve all seeds by exemption.; Exclude below-floor non-seeds before extraction and synthesis input, recording PRISMA off-topic exclusions with score, floor, and nearest seed.; Add a hermetic 0010-shaped fixture with twelve on-topic seeds/neighbours and high-citation Fiji, U-Net, NumPy, ResNet, and Data Science Bowl candidates.

**Depends on:** Provenance-bearing text acquisition

**done-when:** The hermetic 0010-shaped fixture deterministically retains seeds and on-topic neighbours while excluding Fiji, U-Net, NumPy, ResNet, and Data Science Bowl as off-topic before extraction.

- **Given** The 0010-shaped fixture and a configured relevance floor, **when** ranking and screening run, **then** the named generic high-citation papers receive PRISMA off-topic exclusions and never enter extraction.
- **Given** A seed below the relevance floor or lacking text, **when** screening runs, **then** the seed remains retained and relevance-exempt.
- **Given** The same fixture executed twice, **when** candidate ranking runs, **then** scores, nearest-seed identities, exclusions, and ordering are identical.

## Wave 4 — Corpus-relevance summary and honesty gate

**Intent:** Serve Corpus-relevance stamp by deriving one authoritative corpus-quality summary and using it to prevent false synthesis-success verdicts.

**Deliverables:** Define one run-summary object containing relevance_floor, corpus_relevance_min, extracted count, extracted-at-or-above-floor count, corpus_relevance, verdict, and ledger status.; Compute corpus_relevance from extracted papers only, with deterministic zero-extracted and no-seed compatibility behavior.; Centralize verdict derivation so below-minimum corpus relevance yields corpus:off-topic and partial ledger status while other verdict logic remains governed and unchanged.; Make console summary, ledger header, and machine-readable run record consume the same summary object.; Continue writing partial ledgers for corpus:off-topic runs and suppress success phrasing based only on extracted, grounded, or synthesized counts.; Add hermetic above-minimum and below-minimum surface-consistency tests.

**Depends on:** Deterministic relevance scoring and pre-extraction screening

**done-when:** For a below-minimum hermetic fixture, the console, ledger header, and run record identically report corpus_relevance and floor, verdict corpus:off-topic, and partial ledger status.

- **Given** An extracted fixture corpus whose at-or-above-floor fraction is below corpus_relevance_min, **when** the run summary is emitted, **then** all output surfaces report corpus:off-topic and the written ledger is partial.
- **Given** An extracted fixture corpus at or above corpus_relevance_min, **when** the run summary is emitted, **then** all output surfaces share the same fraction and floor while existing governed verdict behavior is preserved.

## Wave 5 — Hermetic end-to-end acceptance and regression lock

**Intent:** Serve Nothing regresses by proving the complete 0010 failure shape is prevented without changing governed research behavior.

**Deliverables:** Add an end-to-end hermetic injected-provider acceptance test covering seed inclusion, PRISMA flow, OpenAlex-backed extraction, provenance stamps, relevance screening, and corpus-relevance outputs.; Assert PRISMA accounting remains balanced and excluded candidates do not enter extraction or weighted synthesis input.; Add regression assertions preserving deterministic quote grounding, safety-floor behavior, weighted synthesis contracts, and the single governed adversarial round.; Run the full node --test test/ gate and retain 463 as the pre-change baseline, increasing only for intentional hermetic tests.; Add source-level configuration defaults and operational handling for relevance_floor, corpus_relevance_min, seed exemption, and inspectable exclusions.

**Depends on:** Corpus-relevance summary and honesty gate

**done-when:** The full hermetic test suite is green and its 0010-shaped acceptance test proves all North-Star surface criteria without network access or new dependencies.

- **Given** The complete injected 0010-shaped corpus with OpenAlex responses for applicable seeds, **when** an end-to-end run executes, **then** all seeds appear in candidates and PRISMA, OpenAlex-backed seeds are extracted with provenance, generic giants are excluded before extraction, and on-topic neighbours survive.
- **Given** A below-minimum end-to-end fixture outcome, **when** the ledger, console, and run record are produced, **then** each carries matching corpus relevance and floor, the verdict is corpus:off-topic, and the ledger is written as partial.
- **Given** The existing governed research fixtures, **when** the full test suite runs after this pass, **then** PRISMA balance, quote grounding, safety floor, weighted synthesis, and the single adversarial round retain their prior contracts.

## Property gates (hardening law — crucible journal 0080)

### boundedness — asserted by this plan
_an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard_

- [ ] the numeric bound named in the plan
- [ ] a refusal path when the bound is exceeded

A property named in the plan and absent from this list is a BLOCKER:
the plan is claiming a guarantee nothing enforces.

## Hardening-gate obligations (mechanical — journal 0080)

This section is the **emitted** property-gate checklist. A claim in the plan without a matching obligation below is a BLOCKER.

### Property `boundedness`
_an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard_

- **Gate:** the numeric bound named in the plan
- **Gate:** a refusal path when the bound is exceeded

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

See also wave-local failure tables (hardening-gate 0080 format) and generated red stubs.
