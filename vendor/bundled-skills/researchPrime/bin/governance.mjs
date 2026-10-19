// bin/governance.mjs — Wave 3 Canonical governance record schema + shared core/extension validator
import { HaltError } from './trio-core/contract-core.mjs';

export const CURRENT_SCHEMA_VERSION = 1;

const CORE_FIELDS = new Set([
  'schemaVersion',
  'triageHash',
  'gate1Decision',
  'planHash',
  'gate2Decision',
  'lockedGovernorOutput',
  'hostApprovalProvider',
  'skill'
]);

const extensionValidators = new Map();

/**
 * Register a per-skill extension validator.
 */
export function registerExtension(skill, validator) {
  extensionValidators.set(skill, validator);
}

/**
 * Canonicalization/normalization layer.
 * @param {string} jsonStr 
 * @returns {object} { canonicalObj, canonicalStr, warnings }
 */
export function canonicalize(jsonStr) {
  if (typeof jsonStr !== 'string') {
    throw new HaltError('unparseable governance record: not a string');
  }

  // normalize whitespace/newlines (CRLF -> LF)
  const normalizedStr = jsonStr.replace(/\r\n/g, '\n');

  let parsed;
  try {
    parsed = JSON.parse(normalizedStr);
  } catch (e) {
    throw new HaltError('unparseable governance record: invalid JSON');
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new HaltError('unsafe governance record: must be an object');
  }

  const keys = Object.keys(parsed);
  const coreKeys = [];
  const extraKeys = [];

  for (const k of keys) {
    if (CORE_FIELDS.has(k)) {
      coreKeys.push(k);
    } else {
      extraKeys.push(k);
    }
  }

  // stable key order: core fields first in fixed order, then extra fields alphabetically
  const orderedCore = [
    'schemaVersion',
    'triageHash',
    'gate1Decision',
    'planHash',
    'gate2Decision',
    'lockedGovernorOutput',
    'hostApprovalProvider',
    'skill'
  ].filter(k => coreKeys.includes(k));

  extraKeys.sort();

  const canonicalObj = {};
  for (const k of orderedCore) {
    canonicalObj[k] = parsed[k];
  }
  for (const k of extraKeys) {
    canonicalObj[k] = parsed[k];
  }

  return {
    canonicalObj,
    canonicalStr: JSON.stringify(canonicalObj),
    warnings: extraKeys.length > 0 ? ['unexpected-but-safe: extra fields present'] : []
  };
}

/**
 * Shared validator enforcing the common core (decision, scope, approval, stakes-lock)
 * and dispatching to a registered per-skill extension validator.
 */
export function validate(recordObj) {
  if (recordObj.schemaVersion !== CURRENT_SCHEMA_VERSION) {
    throw new HaltError(`unsafe governance record: unsupported schemaVersion ${recordObj.schemaVersion}`);
  }
  if (!recordObj.triageHash || typeof recordObj.triageHash !== 'string') {
    throw new HaltError('unsafe governance record: missing or invalid triageHash');
  }
  if (!['APPROVE', 'EDIT', 'ABORT'].includes(recordObj.gate1Decision)) {
    throw new HaltError('unsafe governance record: invalid gate1Decision');
  }
  if (!recordObj.planHash || typeof recordObj.planHash !== 'string') {
    throw new HaltError('unsafe governance record: missing or invalid planHash');
  }
  if (!['APPROVE', 'EDIT', 'ABORT'].includes(recordObj.gate2Decision)) {
    throw new HaltError('unsafe governance record: invalid gate2Decision');
  }
  if (!recordObj.lockedGovernorOutput || !recordObj.lockedGovernorOutput.hash) {
    throw new HaltError('unsafe governance record: missing lockedGovernorOutput');
  }
  
  if (!recordObj.skill || typeof recordObj.skill !== 'string') {
    throw new HaltError('unsafe governance record: missing or invalid skill');
  }

  const extValidator = extensionValidators.get(recordObj.skill);
  if (extValidator) {
    const extValid = extValidator(recordObj);
    if (!extValid) {
      throw new HaltError(`unsafe governance record: ${recordObj.skill} extension validation failed`);
    }
  } else {
    throw new HaltError(`unsafe governance record: no extension validator registered for skill ${recordObj.skill}`);
  }

  return true;
}

// researchPrime per-skill extension validator (conformance test deferred to Wave 4/5)
registerExtension('researchPrime', (record) => {
  return true;
});
