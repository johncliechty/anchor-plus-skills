// crucible/bin/packs/investment-memo-pack.mjs — the investment-memo doc pack (Wave 4).
//
// The SECOND `PACK_SCHEMA` instance (kind:'doc'), built by REUSING the SAME human-built
// Phase-2 gate kit as the literature-review pack (Wave 1 pattern) — config over the same
// two-gate engine, NOT a new engine (SR-6 inclusion test). It supplies only the three-layer
// doc-deliverable gate's CONFIG:
//   Layer 1  doc_contract      — the canonical VC investment-memo required sections (model-free)
//   Layer 2  evidence_standard — audited-filings/data as PRIMARY evidence (with as-of +
//                                jurisdiction fields) + the named entailment-judge model
//   Layer 3  rubric            — a frozen 5-criterion (3-7) rubric + the named rubric-judge model
//
// Wave 4 runs this pack end-to-end on one real memo on the DEFAULT (Claude) substrate. It
// proves the kit generalizes to a second domain WITHOUT touching the gate engine: only this
// config file + fixtures are new (see pack-investment-memo-e2e.test.mjs's inclusion-test).
//
// Model tier (SR-7): the entailment-judge and rubric-judge are STANDARD-tier Judge roles,
// so both name `claude-fable-5` — the current frontier tier (2026-07 refresh; the served
// tier is attested per SR-5 at run time).

export const investmentMemoPack = {
  id: 'investment-memo',
  kind: 'doc',
  version: '1.0.0',

  // Layer 1 — canonical VC investment-memo sections. Section presence is matched by a
  // Markdown heading whose text contains the title (the kit's default; no regex needed).
  doc_contract: {
    required_sections: [
      { id: 'thesis', title: 'Investment Thesis' },
      { id: 'company', title: 'Company Overview' },
      { id: 'market', title: 'Market' },
      { id: 'financials', title: 'Financials' },
      { id: 'valuation', title: 'Valuation' },
      { id: 'risks', title: 'Risks' },
      { id: 'recommendation', title: 'Recommendation' },
    ],
  },

  // Layer 2 — evidence standard: audited filings / regulated disclosures are the PRIMARY
  // evidence, and every such source must carry an `as_of` date + a `jurisdiction` (so a
  // financial claim is anchored to a dated, jurisdiction-scoped audited record, not a
  // marketing deck). `required_source_fields` is pure pack-config the fixtures honor — the
  // gate engine is unchanged (the inclusion test forbids a memo-specific engine fork).
  evidence_standard: {
    entailment_judge_model: 'claude-fable-5',
    primary_source_kinds: [
      'audited-financial-statement',
      'regulatory-filing',
      'audited-cap-table',
    ],
    required_source_fields: ['as_of', 'jurisdiction'],
    minima: { catch_rate_min: 0.9, false_positive_max: 0.1 },
  },

  // Layer 3 — frozen, evidence-anchored rubric (RULERS-style), 5 criteria (within 3-7).
  rubric: {
    rubric_judge_model: 'claude-fable-5',
    criteria: [
      { id: 'c1', statement: 'The investment thesis is explicit and falsifiable (states what must be true for the investment to win).', pass_threshold: 0.6 },
      { id: 'c2', statement: 'Every quantitative or financial claim is anchored to a cited audited primary source (with as-of date and jurisdiction) that entails it.', pass_threshold: 0.6 },
      { id: 'c3', statement: 'The valuation is justified with a stated method, assumptions, and comparables.', pass_threshold: 0.6 },
      { id: 'c4', statement: 'The key risks are identified together with their mitigants.', pass_threshold: 0.6 },
      { id: 'c5', statement: 'A clear recommendation with proposed terms / conditions is stated.', pass_threshold: 0.6 },
    ],
    boundary: { pass_score_min: 0.7 },
  },

  provenance: {
    note: 'Canonical VC investment-memo pack (Wave 4); reuses the Wave-1 kit, executed end-to-end from Wave 4.',
    standard: 'audited-filings-primary',
  },
};

export default investmentMemoPack;
