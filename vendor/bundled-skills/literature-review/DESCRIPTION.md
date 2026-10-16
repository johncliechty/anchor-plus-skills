# literature-review: an on-topic corpus by construction — Description

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


Seeds always in with a text-sourcing chain; a relevance term in candidate ranking with a PRISMA-style off-topic floor; a corpus-relevance stamp that refuses to call synthesis a success below the floor (journal 0010).

## Success criteria
- Seeds always in: every user-supplied seed is in the candidate list and the PRISMA flow regardless of citation rank, each with a per-paper text_source stamp naming the sourcing-chain link that supplied its text (provider abstract -> OpenAlex abstract -> Crossref abstract -> arXiv/PMC full text -> user PDF) or none with the attempts listed
- Relevance-ranked, off-topic excluded: candidate order = citation weight combined with TF-IDF cosine similarity to the seed abstracts (pure JS, deterministic, no network, no model); below a configurable hard floor a candidate is EXCLUDED before extraction and logged in the PRISMA exclusions as off-topic with its score and nearest seed; seeds are exempt
- Corpus-relevance stamp: the run record, console summary and ledger header carry corpus_relevance (fraction of extracted papers at/above the floor + the floor); below a configurable minimum the run verdict is corpus:off-topic, the ledger is still written and stamped partial, and the run never reports success on counts alone
- No regression, hermetic proof: node --test test/ stays green (463 today); new tests are hermetic with providers injected and a fixture corpus reproducing the 0010 shape (seeds + field-generic giants) as the acceptance oracle; PRISMA discipline, quote grounding, the safety floor, synthesis math and the adversarial round unchanged; no new dependency

## Provenance

Generated by Crucible Stage 2 from an approved Master Plan, vetted by the Shark-Tank loop and the well-formedness gate before handoff.
