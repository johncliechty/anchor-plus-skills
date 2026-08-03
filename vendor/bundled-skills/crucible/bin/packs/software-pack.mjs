// crucible/bin/packs/software-pack.mjs — the EXTRACTED software reference pack (Phase 2.5).
//
// SR-6 mechanical guarantee: the trio's DEFAULT (software) behavior is expressed as a
// pack so it runs THROUGH the same pack shell as the doc packs — but as kind:'software'
// it routes ONLY through the existing machine well-formedness gate, and Layers 2-3
// (entailment, rubric) are PROVABLY never invoked. The runtime extraction proof
// (pack-software-extraction.test.mjs) runs the frozen gate suite through this pack and
// asserts byte-identical pass/fail with zero entailment/rubric spawns.

export const softwarePack = {
  id: 'software',
  kind: 'software',
  version: '1.0.0',
  provenance: {
    note: 'extracted reference — default trio behavior; machine well-formedness gate only',
  },
  // Intentionally NO doc_contract / evidence_standard / rubric: Layers 2-3 are inert.
};

export default softwarePack;
