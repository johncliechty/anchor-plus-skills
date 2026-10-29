# 0002-cancer-human-capital-l7

- **id**: 0002-cancer-human-capital-l7
- **skill**: financial-analyst@2026-07-29
- **situation**: Valuing a health/mortality benefit in market-productivity terms alongside an existing
  willingness-to-pay headline, where the two frames are mutually exclusive and the client wants both numbers.
- **context**: Axmra "Holding Company" — RBS2418 oncology asset, L7 leg of a multi-run economic model
  (L4/L5 upstream). Deliverable `L7-WORKING-AGE-PRODUCTIVITY.md`.
- **observation**:
  1. **A template inherited from a prior aborted run had a silent methodological hole**: the human-capital
     lattice had **no mortality weighting** — future earnings were not multiplied by the probability of
     living to earn them, which the standard method requires. All-zero placeholder defaults meant tests
     passed and nothing flagged it. *Lesson: when inheriting a template, audit the METHOD, not just whether
     it runs. Placeholder defaults hide missing terms as effectively as wrong ones.*
  2. **Defaulting a newly added correction to the NULL value (1.0) was the right call.** The survival inputs
     default to 1.0, so the un-parameterised model returns an explicit upper bound and any correction must be
     entered as a sourced schedule. This made "we could not source it" and "we chose not to correct"
     distinguishable in the output.
  3. **I inferred a bias, applied a ×0.85 correction, and was wrong.** A model-vs-published YPWLL gap
     (10.04 vs 8.41 yrs) looked like band-midpoint bias. When finer-grained source data arrived, the
     midpoints proved accurate to <0.6 yr in every material band — the gap was the *age distribution*, not
     the binning. *Lesson: a discrepancy between model and literature has at least two candidate causes
     (method vs population); do not attribute it to the one you can fix without testing the other.*
     Retracted in place in the deliverable rather than silently edited out.
  4. **A gap recorded as NOT LOCATED by a prior high-effort run was retrievable.** Upstream L5 recorded the
     global age distribution of cancer deaths as unavailable (IARC API empty, WHO 404/403). A fresh agent
     found it on IARC's undocumented production API and validated it against the published fact sheet. It
     changed the headline by +78%. *Lesson: inherited NOT LOCATED is a lead, not a settled fact — especially
     when the earlier run disclosed a capability constraint (there, exhausted search budget).*
  5. **Frame-exclusivity was the highest-value output, not the valuation.** The client's instinct was to
     switch frames to the more "concrete" one; the analysis showed it yields 6–12% of the incumbent frame
     for a reason unrelated to the asset's merit, and that regulators explicitly rejected it for this use.
     Recommending *against* the requested reframe, with the burden statistics retained as a non-additive
     floor exhibit, was the useful answer.
  6. A delegated retrieval agent caught a **fabricated quotation** produced by a page-summarising model
     (a purported EPA sentence absent from the source PDF) by grepping the extracted text. Line-verifying
     quotes against source text, not summariser output, caught it.
- **outcome**: worked — deliverable shipped; tie-out clean (22 leaf nodes, max delta 0, two scenarios);
  31/31 python tests green; 13/13 quoted headline figures verified against node values.
- **provenance**: genuine-execution
