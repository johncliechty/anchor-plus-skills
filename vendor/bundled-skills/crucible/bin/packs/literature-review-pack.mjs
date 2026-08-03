// crucible/bin/packs/literature-review-pack.mjs — the literature-review doc pack (Wave 1).
//
// A `PACK_SCHEMA` instance (kind:'doc') over the human-built Phase-2 gate kit — NOT a new
// engine (SR-6). It supplies the three-layer doc-deliverable gate's CONFIG only:
//   Layer 1  doc_contract      — the PRISMA-style required sections (model-free, exit 0/1)
//   Layer 2  evidence_standard — primary-source standard + the named entailment-judge model
//   Layer 3  rubric            — a frozen 5-criterion (3-7) rubric + the named rubric-judge model
//
// Wave 1 wires this pack through `loadPack` + `provenanceStamp` (the SR-5 reserved `pack`
// field) and proves Layer 1 GREEN/RED on lit-review fixtures. Layers 2-3 are DEFINED here
// but NOT executed until Wave 2 (lit-review end-to-end).
//
// Model tier (SR-7): the entailment-judge and rubric-judge are STANDARD-tier Judge roles,
// so both name `claude-fable-5` — the current frontier tier (2026-07 refresh; the served
// tier is attested per SR-5 at run time).

export const literatureReviewPack = {
  id: 'literature-review',
  kind: 'doc',
  version: '1.0.0',

  // Layer 1 — PRISMA 2020-style required sections. Section presence is matched by a
  // Markdown heading whose text contains the title (the kit's default; no regex needed).
  doc_contract: {
    required_sections: [
      { id: 'methods', title: 'Methods' },
      { id: 'search-strategy', title: 'Search Strategy' },
      { id: 'prisma-flow', title: 'PRISMA Flow' },
      { id: 'results', title: 'Results' },
      { id: 'discussion', title: 'Discussion' },
    ],
  },

  // Layer 2 — evidence standard: primary sources only, with the named (attested) judge.
  evidence_standard: {
    entailment_judge_model: 'claude-fable-5',
    primary_source_kinds: [
      'peer-reviewed-primary-study',
      'registered-trial-report',
      'preregistration-record',
    ],
    minima: { catch_rate_min: 0.9, false_positive_max: 0.1 },
  },

  // Layer 3 — frozen, evidence-anchored rubric (RULERS-style), 5 criteria (within 3-7).
  rubric: {
    rubric_judge_model: 'claude-fable-5',
    criteria: [
      { id: 'c1', statement: 'The search strategy is reproducible (databases, dates, and full query strings are stated).', pass_threshold: 0.6 },
      { id: 'c2', statement: 'Every quantitative or causal claim is anchored to a cited primary source that entails it.', pass_threshold: 0.6 },
      { id: 'c3', statement: 'The PRISMA flow accounts for all records (identified -> screened -> included) with reasons for exclusion.', pass_threshold: 0.6 },
      { id: 'c4', statement: 'Risk-of-bias / study quality is assessed for the included studies.', pass_threshold: 0.6 },
      { id: 'c5', statement: 'Limitations and threats to validity are stated explicitly.', pass_threshold: 0.6 },
    ],
    boundary: { pass_score_min: 0.7 },
  },

  provenance: {
    note: 'PRISMA-style systematic literature-review pack (Wave 1); Layers 2-3 defined, executed from Wave 2.',
    standard: 'PRISMA 2020',
  },
};

export default literatureReviewPack;
