// crucible/bin/packs/pack-gate.mjs — the three-layer doc-deliverable gate orchestrator.
//
// doc pack:      Layer 1 (contract, model-free, BEFORE any judge) -> Layer 2 (evidence
//                faithfulness) -> Layer 3 (frozen rubric). Short-circuits at the first
//                failing layer (Layer 1 never spends a model call on a malformed doc).
// software pack: routes ONLY through the injected machine well-formedness gate; Layers
//                2-3 are PROVABLY never invoked (SR-6 — the extraction proof asserts the
//                `layers_invoked` ledger shows layer2/layer3 === false for software).
//
// Every result carries the SR-5 `pack` provenance (which pack governed, which models it
// named). The orchestrator NEVER runs the ground-truth test gate itself.

import { provenanceStamp } from './registry.mjs';
import { validateDocContract } from './layer1-contract.mjs';
import { assessEvidenceFaithfulness, runEntailmentBattery } from './layer2-evidence.mjs';
import { scoreAgainstRubric } from './layer3-rubric.mjs';

/**
 * @param {object} o
 * @param {object} o.pack                       a validated pack
 * @param {string} [o.doc]                      the deliverable (doc packs)
 * @param {object[]} [o.claims]                 claims for Layer 2 (doc packs)
 * @param {object} [o.sources]                  citation id -> source (Layer 2)
 * @param {object} [o.battery]                  optional labeled battery (gates Layer 2 by minima)
 * @param {Function} [o.entail] / [o.agent]     Layer 2 entailment judge (test/live)
 * @param {Function} [o.score]                  Layer 3 scorer (test); else agent
 * @param {Function} [o.machineGate]            software pack: () => {pass, ...}
 * @param {Function} [o.probeCrossModel]        Layer 3 cross-family probe (reused Judge machinery)
 * @param {Function} [o.log=()=>{}]
 * @returns {Promise<{pass:boolean, kind:string, stoppedAt:?string,
 *   layers_invoked:{layer1:boolean,layer2:boolean,layer3:boolean,machineGate:boolean},
 *   layer1?:object, layer2?:object, layer3?:object, machine?:object, provenance:object}>}
 */
export async function runPackGate({
  pack, doc, claims = [], sources = {}, battery = null,
  entail, agent, score, machineGate, probeCrossModel, log = () => {},
}) {
  const provenance = provenanceStamp(pack);
  const layers_invoked = { layer1: false, layer2: false, layer3: false, machineGate: false };

  if (pack.kind === 'software') {
    // SR-6: software default behavior is machine-gate ONLY. Layers 2-3 stay inert.
    layers_invoked.machineGate = true;
    const machine = machineGate ? await machineGate() : { pass: true, note: 'no machineGate injected' };
    return { pass: machine.pass !== false, kind: 'software', stoppedAt: null, layers_invoked, machine, provenance };
  }

  // --- doc pack: Layer 1 (model-free) first ---
  layers_invoked.layer1 = true;
  const layer1 = validateDocContract({ doc, pack });
  if (!layer1.pass) {
    log(`pack-gate ${pack.id}: Layer 1 FAIL (missing ${layer1.missing.map((m) => m.id).join(', ')})`);
    return { pass: false, kind: 'doc', stoppedAt: 'layer1', layers_invoked, layer1, provenance };
  }

  // --- Layer 2: evidence-faithfulness (optionally minima-gated by a battery) ---
  layers_invoked.layer2 = true;
  let layer2;
  if (battery) {
    const b = await runEntailmentBattery({ battery, entail, agent, pack, log });
    layer2 = { ...b, pass: b.meetsMinima };
    // The battery CALIBRATES the entailment judge (measured catch-rate / false-positive vs
    // the pack minima); it does NOT evaluate THIS deliverable. When the deliverable's own
    // claims are supplied, also run them so the end-to-end gate actually checks the
    // deliverable's evidence faithfulness — the pass then requires BOTH a calibrated judge
    // AND a faithful deliverable.
    if (layer2.pass && claims.length) {
      const deliverable = await assessEvidenceFaithfulness({ claims, sources, entail, agent, pack, log });
      layer2 = { ...layer2, deliverable, pass: layer2.meetsMinima && deliverable.pass };
    }
  } else {
    layer2 = await assessEvidenceFaithfulness({ claims, sources, entail, agent, pack, log });
  }
  if (!layer2.pass) {
    log(`pack-gate ${pack.id}: Layer 2 FAIL`);
    return { pass: false, kind: 'doc', stoppedAt: 'layer2', layers_invoked, layer1, layer2, provenance };
  }

  // --- Layer 3: frozen rubric ---
  layers_invoked.layer3 = true;
  const layer3 = await scoreAgainstRubric({ doc, pack, score, agent, probeCrossModel, log });
  const pass = layer3.verdict === 'PASS';
  log(`pack-gate ${pack.id}: ${pass ? 'PASS' : 'FAIL'} (rubric ${layer3.aggregate_score.toFixed(2)})`);
  return { pass, kind: 'doc', stoppedAt: pass ? null : 'layer3', layers_invoked, layer1, layer2, layer3, provenance };
}
