// crucible/bin/packs/pack-schema.mjs — the domain-pack CONTRACT (Phase 2.1).
//
// A pack is a SEAM OVER the existing two-gate engine (machine well-formedness +
// Shark/Judge), NOT a new engine. It parameterizes a THREE-LAYER doc-deliverable gate:
//   Layer 1  doc-contract     — required sections/format, NO model, exit 0/1
//   Layer 2  evidence         — claim<->cited-source entailment (model-as-judge) + xref
//   Layer 3  rubric           — frozen 3-7 criterion rubric, scored by the reused Judge
//
// kind:'software' is the EXTRACTED REFERENCE pack: it routes ONLY through the existing
// machine gate and MUST NOT invoke Layers 2-3 (SR-6 byte-identical default behavior).
// kind:'doc' packs (literature-review, investment-memo) supply all three layers.

import { HaltError } from '../crucible-lib.mjs';

/** Human-readable JSON-Schema-ish description of a pack (for docs / Foundry scaffold). */
export const PACK_SCHEMA = {
  type: 'object',
  required: ['id', 'kind', 'version'],
  properties: {
    id: { type: 'string' },
    kind: { enum: ['software', 'doc'] },
    version: { type: 'string' },
    // Layer 1 — required for doc packs; absent/ignored for software.
    doc_contract: {
      type: 'object',
      properties: {
        required_sections: {
          type: 'array',
          items: {
            type: 'object',
            required: ['id', 'title'],
            properties: {
              id: { type: 'string' },
              title: { type: 'string' },
              pattern: { type: 'string' }, // optional regex; defaults to a heading match on title
            },
          },
        },
      },
    },
    // Layer 2 — evidence standard + the NAMED, attested entailment-judge model.
    evidence_standard: {
      type: 'object',
      properties: {
        entailment_judge_model: { type: 'string' },
        primary_source_kinds: { type: 'array', items: { type: 'string' } },
        minima: {
          type: 'object',
          properties: {
            catch_rate_min: { type: 'number' },        // >= fraction of planted-bad caught
            false_positive_max: { type: 'number' },     // <= fraction of entailed wrongly flagged
          },
        },
      },
    },
    // Layer 3 — frozen, immutable rubric + the NAMED, attested rubric-judge model.
    rubric: {
      type: 'object',
      properties: {
        rubric_judge_model: { type: 'string' },
        criteria: {
          type: 'array',
          items: {
            type: 'object',
            required: ['id', 'statement'],
            properties: {
              id: { type: 'string' },
              statement: { type: 'string' },
              pass_threshold: { type: 'number' }, // 0..1 per-criterion bar
            },
          },
        },
        boundary: {
          type: 'object',
          properties: { pass_score_min: { type: 'number' } }, // aggregate pass bar
        },
      },
    },
    provenance: { type: 'object' },
  },
};

const SEMVERISH = /^\d+\.\d+(\.\d+)?([-+].+)?$/;

/**
 * Validate a pack object against the contract. Returns `{ ok, errors }` — never throws
 * (the registry decides whether to HALT). Enforces the kind-specific shape:
 *   - doc:      >=1 required section; rubric of 3-7 criteria; entailment+rubric models named.
 *   - software: MUST NOT carry doc_contract/evidence_standard/rubric (Layers 2-3 inert).
 * @param {*} pack
 * @returns {{ ok:boolean, errors:string[] }}
 */
export function validatePackSchema(pack) {
  const errors = [];
  if (!pack || typeof pack !== 'object' || Array.isArray(pack)) {
    return { ok: false, errors: ['pack must be a plain object'] };
  }
  if (typeof pack.id !== 'string' || !pack.id) errors.push('id: required non-empty string');
  if (pack.kind !== 'software' && pack.kind !== 'doc') errors.push("kind: must be 'software' or 'doc'");
  if (typeof pack.version !== 'string' || !SEMVERISH.test(pack.version)) errors.push('version: required semver-ish string');

  if (pack.kind === 'doc') {
    const secs = pack.doc_contract?.required_sections;
    if (!Array.isArray(secs) || secs.length < 1) {
      errors.push('doc_contract.required_sections: doc pack needs >=1 required section');
    } else {
      secs.forEach((s, i) => {
        if (!s || typeof s.id !== 'string' || !s.id) errors.push(`doc_contract.required_sections[${i}].id: required`);
        if (!s || typeof s.title !== 'string' || !s.title) errors.push(`doc_contract.required_sections[${i}].title: required`);
        if (s && s.pattern != null) { try { new RegExp(s.pattern); } catch { errors.push(`doc_contract.required_sections[${i}].pattern: invalid regex`); } }
      });
    }
    if (typeof pack.evidence_standard?.entailment_judge_model !== 'string' || !pack.evidence_standard.entailment_judge_model) {
      errors.push('evidence_standard.entailment_judge_model: doc pack must NAME its (attested) entailment-judge model');
    }
    const crit = pack.rubric?.criteria;
    if (!Array.isArray(crit) || crit.length < 3 || crit.length > 7) {
      errors.push('rubric.criteria: doc pack needs a frozen 3-7 criterion rubric');
    } else {
      crit.forEach((c, i) => {
        if (!c || typeof c.id !== 'string' || !c.id) errors.push(`rubric.criteria[${i}].id: required`);
        if (!c || typeof c.statement !== 'string' || !c.statement) errors.push(`rubric.criteria[${i}].statement: required`);
      });
    }
    if (typeof pack.rubric?.rubric_judge_model !== 'string' || !pack.rubric.rubric_judge_model) {
      errors.push('rubric.rubric_judge_model: doc pack must NAME its (attested) rubric-judge model');
    }
  }

  if (pack.kind === 'software') {
    // SR-6: the extracted reference MUST stay a pure machine-gate pack. Carrying any
    // doc-layer config would risk Layers 2-3 firing on the software path.
    for (const f of ['doc_contract', 'evidence_standard', 'rubric']) {
      if (pack[f] != null) errors.push(`software pack must NOT carry '${f}' (Layers 2-3 are inert for software)`);
    }
  }

  return { ok: errors.length === 0, errors };
}

/** Assert a pack is valid or HALT with the collected reasons. */
export function assertValidPack(pack) {
  const { ok, errors } = validatePackSchema(pack);
  if (!ok) {
    throw new HaltError(
      `invalid pack "${pack?.id ?? '(no id)'}"`,
      `pack schema violations:\n - ${errors.join('\n - ')}`,
    );
  }
  return pack;
}
