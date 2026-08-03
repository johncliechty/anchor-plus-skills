// bin/formal-governor.mjs — Wave 1: Formal stakes governor

import crypto from 'node:crypto';

export const CONTRACT_VERSION = 1;
import { resolveTier } from './governor.mjs';
import { loopThresholds } from './round.mjs';

/**
 * Input classification table tagging each governor input 'known-by-Stage-1' 
 * vs 'emergent-during-rounds'. The initial budget is locked on Stage-1-known inputs only.
 */
export const INPUT_CLASSIFICATION = Object.freeze({
  stakesTier: 'known-by-Stage-1',
  maxRounds: 'known-by-Stage-1',
  N: 'known-by-Stage-1',
  K: 'known-by-Stage-1',
  M: 'known-by-Stage-1',
  // Anything discovered mid-run goes here, and will not affect the Stage-1 lock
  emergentConflict: 'emergent-during-rounds',
  emergentItem: 'emergent-during-rounds'
});

/**
 * Filter inputs to only include those known by Stage-1.
 */
function extractStage1Inputs(inputs) {
  const stage1 = {};
  for (const [k, v] of Object.entries(inputs || {})) {
    if (INPUT_CLASSIFICATION[k] === 'known-by-Stage-1') {
      stage1[k] = v;
    }
  }
  return stage1;
}

/**
 * Serialize an object canonically (stable key order, no whitespace variation).
 */
export function canonicalSerialize(obj) {
  if (obj === null || typeof obj !== 'object') {
    return JSON.stringify(obj);
  }
  if (Array.isArray(obj)) {
    return `[${obj.map(canonicalSerialize).join(',')}]`;
  }
  const keys = Object.keys(obj).sort();
  let result = '{';
  for (let i = 0; i < keys.length; i++) {
    const k = keys[i];
    if (i > 0) result += ',';
    result += JSON.stringify(k) + ':' + canonicalSerialize(obj[k]);
  }
  result += '}';
  return result;
}

/**
 * Hash a canonical serialization of the locked OUTPUT artifact.
 */
export function hashLockedOutput(output) {
  const serialized = canonicalSerialize(output);
  return crypto.createHash('sha256').update(serialized).digest('hex');
}

/**
 * The Formal Stakes Governor.
 * Exposes a stable typed output contract covering round budget, bounds, and thresholds.
 */
export function lockGovernorOutput(inputs) {
  // Only Stage-1-known inputs determine the initial lock
  const stage1Inputs = extractStage1Inputs(inputs);
  
  const inputsHash = crypto.createHash('sha256').update(canonicalSerialize(stage1Inputs)).digest('hex');
  
  const roundBudget = typeof stage1Inputs.maxRounds === 'number' ? stage1Inputs.maxRounds : 8;
  const thresholds = {
    N: typeof stage1Inputs.N === 'number' ? stage1Inputs.N : 3,
    K: typeof stage1Inputs.K === 'number' ? stage1Inputs.K : 4,
    M: typeof stage1Inputs.M === 'number' ? stage1Inputs.M : 2,
  };
  const bounds = {
    // placeholders for future bounds run-rounds might read
  };
  
  return {
    roundBudget,
    bounds,
    thresholds,
    provenance: {
      inputsHash,
      contractVersion: CONTRACT_VERSION
    }
  };
}

/**
 * Derive the FULL governor contract from raw run inputs: the locked Stage-1 output
 * plus the resolved stakes tier. Accepts the flat Stage-1 shape (stakesTier/N/K/M/
 * maxRounds) and the run/legacy shapes — `preregThresholds: {N,K,M}` folds into the
 * flat thresholds before the lock, and `stakes` (a tier string OR a declared stakes
 * vector) resolves through the Wave-4 adjudicator (I6 floor applied). An absent
 * stakes declaration adjudicates to `low` (never a silent upgrade).
 */
export function deriveGovernorContract(inputs) {
  const src = inputs && typeof inputs === 'object' && !Array.isArray(inputs) ? inputs : {};
  const prereg = src.preregThresholds && typeof src.preregThresholds === 'object'
    ? src.preregThresholds
    : {};
  const locked = lockGovernorOutput({ ...src, ...prereg });
  const tier = resolveTier(src.stakes ?? src.stakesTier ?? {});
  return { ...locked, tier };
}
