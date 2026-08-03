// crucible/bin/packs/registry.mjs — pack registry + loader + provenance stamp (Phase 2.1).
//
// `loadPack` is the single entry the engine calls to obtain a validated pack (by id, by
// object, or from a JSON file). `provenanceStamp` produces the value that rides the SR-5
// reserved `pack` field so every role stamp records which pack governed the gate and
// which entailment/rubric models it named.

import fs from 'node:fs';

import { HaltError } from '../crucible-lib.mjs';
import { PACK_SCHEMA, validatePackSchema, assertValidPack } from './pack-schema.mjs';
import { softwarePack } from './software-pack.mjs';
import { literatureReviewPack } from './literature-review-pack.mjs';
import { investmentMemoPack } from './investment-memo-pack.mjs';

export { PACK_SCHEMA, validatePackSchema };

/** id -> validated pack. Seeded with the extracted software reference (always present). */
const REGISTRY = new Map();

/** Register (validate then store) a pack. Replacing an id is allowed (explicit). */
export function registerPack(pack) {
  assertValidPack(pack);
  REGISTRY.set(pack.id, pack);
  return pack;
}

// The software pack is the EXTRACTED REFERENCE (SR-6): default behavior routes through
// it and Layers 2-3 never fire. Seed it so `loadPack('software')` always resolves.
registerPack(softwarePack);

// The literature-review doc pack (Wave 1): seed it so `loadPack('literature-review')`
// resolves by id. It is a pure PACK_SCHEMA instance — config over the same gate shell,
// no engine fork (SR-6 inclusion test).
registerPack(literatureReviewPack);

// The investment-memo doc pack (Wave 4): the SECOND doc pack, seeded so
// `loadPack('investment-memo')` resolves by id. Like the lit-review pack it is config-only
// over the SAME gate shell (no engine fork — the Wave-4 inclusion test).
registerPack(investmentMemoPack);

/** The registered pack ids (software always present). */
export function listPacks() {
  return [...REGISTRY.keys()];
}

/**
 * Resolve a validated pack from an id (registered), a pack object, or a JSON file path.
 * HALTs on unknown id / invalid pack rather than silently degrading.
 * @param {string|object} idOrPackOrPath
 * @returns {object} the validated pack
 */
export function loadPack(idOrPackOrPath) {
  if (idOrPackOrPath && typeof idOrPackOrPath === 'object') {
    return assertValidPack(idOrPackOrPath);
  }
  if (typeof idOrPackOrPath !== 'string' || !idOrPackOrPath) {
    throw new HaltError('loadPack requires a pack id, object, or path', 'e.g. loadPack("software") or loadPack(packObject)');
  }
  if (REGISTRY.has(idOrPackOrPath)) return REGISTRY.get(idOrPackOrPath);
  // Not a registered id — try it as a JSON file path.
  if (fs.existsSync(idOrPackOrPath)) {
    let parsed;
    try { parsed = JSON.parse(fs.readFileSync(idOrPackOrPath, 'utf8')); }
    catch (e) { throw new HaltError(`pack file is not valid JSON: ${idOrPackOrPath}`, String(e?.message ?? e)); }
    return assertValidPack(parsed);
  }
  throw new HaltError(
    `unknown pack "${idOrPackOrPath}"`,
    `registered packs: ${listPacks().join(', ')}. Pass a registered id, a pack object, or a JSON file path.`,
  );
}

/**
 * The provenance value for the SR-5 reserved `pack` field. Records the governing pack
 * + the NAMED entailment/rubric models (which Layers 2-3 then attest as SERVED).
 * @param {object} pack
 * @returns {{pack:string, pack_kind:string, pack_version:string,
 *           entailment_judge_model:?string, rubric_judge_model:?string}}
 */
export function provenanceStamp(pack) {
  return {
    pack: pack.id,
    pack_kind: pack.kind,
    pack_version: pack.version,
    entailment_judge_model: pack.evidence_standard?.entailment_judge_model ?? null,
    rubric_judge_model: pack.rubric?.rubric_judge_model ?? null,
  };
}
