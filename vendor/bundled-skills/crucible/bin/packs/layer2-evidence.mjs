// crucible/bin/packs/layer2-evidence.mjs — LAYER 2: evidence-faithfulness.
//
// Two mechanically-auditable checks per claim:
//   (a) real-reference cross-ref — the claim's citation MUST resolve to a known source;
//       an unresolved citation is a fabricated reference (flagged without a model).
//   (b) entailment — a model-as-judge decides whether the cited SOURCE TEXT entails the
//       claim. Over-claims (source present but doesn't support the assertion) are flagged.
//
// The model call is injected as `entail({claim, source}) => {entailed, rationale}` so the
// gate LOGIC is unit-tested deterministically; the live wiring builds `entail` from the
// SR-5-attested agent seam + ENTAILMENT_SCHEMA (the entailment-judge model the pack names).

import { HaltError } from '../crucible-lib.mjs';

/** The entailment judge's reply. */
export const ENTAILMENT_SCHEMA = {
  type: 'object',
  required: ['entailed'],
  properties: {
    entailed: { type: 'boolean' },
    rationale: { type: 'string' },
    confidence: { type: 'number' },
  },
};

/** Build an `entail()` from the agent seam (live path). The named model is attested
 *  via the driver's SR-5 rec at the spawn site. */
export function makeEntailFromAgent({ agent, model, log = () => {} }) {
  if (typeof agent !== 'function') throw new HaltError('makeEntailFromAgent requires agent()', 'pass the Wave-1 seam');
  return async ({ claim, source }) => {
    const prompt = [
      `You are an ENTAILMENT JUDGE. Decide ONLY whether the SOURCE TEXT below logically`,
      `ENTAILS the CLAIM. Do not use outside knowledge. If the source does not support the`,
      `claim (or supports only a weaker version), answer entailed:false.`,
      ``,
      `=== CLAIM ===\n${claim.text}\n=== SOURCE TEXT ===\n${source?.text ?? '(source text unavailable)'}\n=== END ===`,
    ].join('\n');
    const out = await agent(prompt, { label: `entail:${claim.id}:${model}`, schema: ENTAILMENT_SCHEMA });
    return { entailed: out?.entailed === true, rationale: out?.rationale ?? '' };
  };
}

/**
 * Assess one deliverable's claims against its cited sources.
 * @param {object} o
 * @param {{id:string,text:string,citation:string}[]} o.claims
 * @param {Record<string,{id:string,text:string}>}    o.sources   citation id -> source
 * @param {Function} [o.entail]   injected `({claim,source})=>{entailed}` (test/live)
 * @param {Function} [o.agent]    OR the agent seam (live) — built into `entail`
 * @param {object}    o.pack      validated doc pack (names the entailment-judge model)
 * @returns {Promise<{pass:boolean, results:object[], flagged:object[], model:?string}>}
 */
export async function assessEvidenceFaithfulness({ claims = [], sources = {}, entail, agent, pack, log = () => {} }) {
  const model = pack?.evidence_standard?.entailment_judge_model ?? null;
  const entailFn = entail || (agent ? makeEntailFromAgent({ agent, model, log }) : null);
  if (!entailFn) throw new HaltError('Layer 2 needs an entailment judge', 'pass { entail } (test) or { agent } (live)');

  const results = [];
  for (const claim of claims) {
    const source = sources[claim.citation] || null;
    const citationResolved = !!source;
    let entailed = false;
    let reason = '';
    if (!citationResolved) {
      reason = 'citation does not resolve to any known source (fabricated reference)';
    } else {
      const v = await entailFn({ claim, source });
      entailed = v.entailed === true;
      if (!entailed) reason = v.rationale || 'source does not entail the claim (over-claim)';
    }
    const flagged = !citationResolved || !entailed;
    results.push({ id: claim.id, citation: claim.citation, citationResolved, entailed, flagged, reason });
  }
  const flagged = results.filter((r) => r.flagged);
  return { pass: flagged.length === 0, results, flagged, model };
}

/**
 * Run the labeled BATTERY (Phase 2.3 done-when). Battery = N entailed + N fabricated +
 * N over-claimed, each with the source map. Computes catch-rate on planted-bad and the
 * false-positive rate on the entailed set, then checks the pack's stated minima.
 * @param {object} o
 * @param {{entailed:object[], fabricated:object[], overclaimed:object[], sources:object}} o.battery
 * @param {Function} [o.entail]
 * @param {Function} [o.agent]
 * @param {object}    o.pack
 * @returns {Promise<{catchRate:number, falsePositiveRate:number, caught:number,
 *   plantedBad:number, falsePositives:number, entailedCount:number,
 *   meetsMinima:boolean, minima:object}>}
 */
export async function runEntailmentBattery({ battery, entail, agent, pack, log = () => {} }) {
  const sources = battery.sources || {};
  const entailedItems = battery.entailed || [];
  const plantedBadItems = [...(battery.fabricated || []), ...(battery.overclaimed || [])];

  const judge = async (claims) =>
    (await assessEvidenceFaithfulness({ claims, sources, entail, agent, pack, log })).results;

  const goodRes = await judge(entailedItems);
  const badRes = await judge(plantedBadItems);

  const falsePositives = goodRes.filter((r) => r.flagged).length;     // entailed wrongly flagged
  const caught = badRes.filter((r) => r.flagged).length;               // planted-bad correctly flagged
  const entailedCount = entailedItems.length;
  const plantedBad = plantedBadItems.length;

  const catchRate = plantedBad ? caught / plantedBad : 1;
  const falsePositiveRate = entailedCount ? falsePositives / entailedCount : 0;

  const minima = pack?.evidence_standard?.minima ?? { catch_rate_min: 0.9, false_positive_max: 0.1 };
  const meetsMinima = catchRate >= minima.catch_rate_min && falsePositiveRate <= minima.false_positive_max;

  return { catchRate, falsePositiveRate, caught, plantedBad, falsePositives, entailedCount, meetsMinima, minima };
}
