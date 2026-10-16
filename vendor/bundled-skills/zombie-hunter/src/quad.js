// Four-leg joint-quad predicate (W3 skeleton + W4 spend atlas).
//
// Zombie ⇔ engine ∧ paid-spend ∧ unsupervised ∧ not Anchor-owned
// Any UNCERTAIN leg ⇒ ABSTAIN (never actionable RED).
// Owned / fail-closed ownership ⇒ KEEP.
//
// Spend leg accepts evaluateSpendLeg (W4): SPEND_POSITIVE only on process-owned
// atlas-matched hosts; SPEND_ATLAS_STALE / UNCERTAIN never invents spend.

const {
  filterKnownReasonCodes,
} = require('./reason-catalog.js');

const {
  OWNERSHIP_IPC_FAIL_CLOSED,
  OWNERSHIP_REGISTERED_KEEP,
  OWNERSHIP_NOT_REGISTERED,
  OWNERSHIP_IPC_STUB,
} = require('./ownership.js');

/** Leg status vocabulary. */
const LEG_POSITIVE = 'POSITIVE';
const LEG_NEGATIVE = 'NEGATIVE';
const LEG_UNCERTAIN = 'UNCERTAIN';

/** Quad verdicts. */
const VERDICT_WOULD_BE_RED = 'WOULD_BE_RED';
const VERDICT_KEEP = 'KEEP';
const VERDICT_ABSTAIN = 'ABSTAIN';

/**
 * Normalize a free-form leg input to { status, reason, reasonCodes }.
 * Accepts string status, boolean, or object.
 * @param {unknown} leg
 * @param {object} map — { positive, negative, uncertain, trueAs, falseAs }
 */
function normalizeLeg(leg, map) {
  if (leg == null) {
    return {
      status: LEG_UNCERTAIN,
      reason: map.nullReason || 'LEG_NULL',
      reasonCodes: [map.nullReason || 'LEG_NULL'].filter(Boolean),
    };
  }
  if (typeof leg === 'boolean') {
    const status = leg ? (map.trueAs || LEG_POSITIVE) : (map.falseAs || LEG_NEGATIVE);
    const reason = leg ? map.trueReason : map.falseReason;
    return {
      status,
      reason: reason || status,
      reasonCodes: [reason || status].filter(Boolean),
    };
  }
  if (typeof leg === 'string') {
    const s = leg.toUpperCase();
    let status = LEG_UNCERTAIN;
    if (s === LEG_POSITIVE || s === 'TRUE' || s === 'YES' || s === map.positiveAlias) {
      status = LEG_POSITIVE;
    } else if (s === LEG_NEGATIVE || s === 'FALSE' || s === 'NO' || s === map.negativeAlias) {
      status = LEG_NEGATIVE;
    } else if (s === LEG_UNCERTAIN || s === 'UNKNOWN') {
      status = LEG_UNCERTAIN;
    } else if (map.stringMap && map.stringMap[s]) {
      status = map.stringMap[s];
    }
    return { status, reason: s, reasonCodes: [s] };
  }
  if (typeof leg === 'object') {
    let status = leg.status != null ? String(leg.status).toUpperCase() : null;
    if (!status && leg.positive === true) status = LEG_POSITIVE;
    if (!status && leg.negative === true) status = LEG_NEGATIVE;
    if (!status && leg.uncertain === true) status = LEG_UNCERTAIN;
    if (!status && typeof leg.value === 'boolean') {
      status = leg.value ? LEG_POSITIVE : LEG_NEGATIVE;
    }
    if (!status) status = LEG_UNCERTAIN;
    if (status !== LEG_POSITIVE && status !== LEG_NEGATIVE && status !== LEG_UNCERTAIN) {
      status = LEG_UNCERTAIN;
    }
    const reason = leg.reason || status;
    const reasonCodes = Array.isArray(leg.reasonCodes)
      ? leg.reasonCodes.slice()
      : [reason];
    return { status, reason, reasonCodes };
  }
  return {
    status: LEG_UNCERTAIN,
    reason: 'LEG_INVALID',
    reasonCodes: ['LEG_INVALID'],
  };
}

/**
 * Map engine-leg evaluateEngineLeg result → quad engine leg.
 * Engine positive ⇒ POSITIVE; otherwise NEGATIVE (closed allowlist; no uncertain
 * except invalid proc which is UNCERTAIN).
 * @param {object|boolean|string} engine
 */
function mapEngineLeg(engine) {
  if (engine && typeof engine === 'object' && engine.isEnginePositive != null) {
    if (engine.reason === 'INVALID_PROC') {
      return {
        status: LEG_UNCERTAIN,
        reason: 'ENGINE_INVALID_PROC',
        reasonCodes: ['ENGINE_UNCERTAIN', 'ENGINE_INVALID_PROC'],
      };
    }
    if (engine.isEnginePositive) {
      return {
        status: LEG_POSITIVE,
        reason: engine.reason || 'E1_CLOSED_ALLOWLIST',
        reasonCodes: [engine.reason || 'E1_CLOSED_ALLOWLIST'],
      };
    }
    return {
      status: LEG_NEGATIVE,
      reason: engine.reason || 'ENGINE_NEGATIVE',
      reasonCodes: ['ENGINE_NEGATIVE', engine.reason].filter(Boolean),
    };
  }
  return normalizeLeg(engine, {
    trueAs: LEG_POSITIVE,
    falseAs: LEG_NEGATIVE,
    trueReason: 'E1_CLOSED_ALLOWLIST',
    falseReason: 'ENGINE_NEGATIVE',
    nullReason: 'ENGINE_UNCERTAIN',
    stringMap: {
      ENGINE_POSITIVE: LEG_POSITIVE,
      ENGINE_NEGATIVE: LEG_NEGATIVE,
      ENGINE_UNCERTAIN: LEG_UNCERTAIN,
    },
  });
}

/**
 * Map spend signal → quad spend leg (W4 atlas-aware).
 * Accepts evaluateSpendLeg result: status SPEND_POSITIVE|NEGATIVE|UNCERTAIN,
 * spendPositive/spendingNow booleans, or atlasStale.
 * @param {object|boolean|string} spend
 */
function mapSpendLeg(spend) {
  if (spend && typeof spend === 'object') {
    // Atlas stale / SPEND_ATLAS_STALE always UNCERTAIN (never invent positive).
    if (spend.atlasStale === true || spend.reason === 'SPEND_ATLAS_STALE') {
      const codes = Array.isArray(spend.reasonCodes)
        ? spend.reasonCodes.slice()
        : ['SPEND_ATLAS_STALE', 'SPEND_UNCERTAIN'];
      if (!codes.includes('SPEND_ATLAS_STALE')) codes.unshift('SPEND_ATLAS_STALE');
      if (!codes.includes('SPEND_UNCERTAIN')) codes.push('SPEND_UNCERTAIN');
      return {
        status: LEG_UNCERTAIN,
        reason: 'SPEND_ATLAS_STALE',
        reasonCodes: codes,
      };
    }

    const rawStatus = spend.status != null ? String(spend.status).toUpperCase() : '';
    if (rawStatus === 'SPEND_POSITIVE' || rawStatus === LEG_POSITIVE) {
      return {
        status: LEG_POSITIVE,
        reason: spend.reason || 'SPEND_POSITIVE',
        reasonCodes: Array.isArray(spend.reasonCodes) && spend.reasonCodes.length
          ? spend.reasonCodes.slice()
          : ['SPEND_POSITIVE'],
      };
    }
    if (rawStatus === 'SPEND_NEGATIVE' || rawStatus === LEG_NEGATIVE) {
      return {
        status: LEG_NEGATIVE,
        reason: spend.reason || 'SPEND_NEGATIVE',
        reasonCodes: Array.isArray(spend.reasonCodes) && spend.reasonCodes.length
          ? spend.reasonCodes.slice()
          : ['SPEND_NEGATIVE'],
      };
    }
    if (rawStatus === 'SPEND_UNCERTAIN' || rawStatus === LEG_UNCERTAIN) {
      return {
        status: LEG_UNCERTAIN,
        reason: spend.reason || 'SPEND_UNCERTAIN',
        reasonCodes: Array.isArray(spend.reasonCodes) && spend.reasonCodes.length
          ? spend.reasonCodes.slice()
          : ['SPEND_UNCERTAIN'],
      };
    }

    if (spend.spendingNow === true || spend.spendPositive === true) {
      return {
        status: LEG_POSITIVE,
        reason: 'SPEND_POSITIVE',
        reasonCodes: ['SPEND_POSITIVE'],
      };
    }
    if (spend.spendUncertain === true) {
      return {
        status: LEG_UNCERTAIN,
        reason: 'SPEND_UNCERTAIN',
        reasonCodes: ['SPEND_UNCERTAIN'],
      };
    }
    if (spend.spendingNow === false || spend.spendPositive === false) {
      return {
        status: LEG_NEGATIVE,
        reason: 'SPEND_NEGATIVE',
        reasonCodes: ['SPEND_NEGATIVE'],
      };
    }
  }
  return normalizeLeg(spend, {
    trueAs: LEG_POSITIVE,
    falseAs: LEG_NEGATIVE,
    trueReason: 'SPEND_POSITIVE',
    falseReason: 'SPEND_NEGATIVE',
    nullReason: 'SPEND_UNCERTAIN',
    stringMap: {
      SPEND_POSITIVE: LEG_POSITIVE,
      SPEND_NEGATIVE: LEG_NEGATIVE,
      SPEND_UNCERTAIN: LEG_UNCERTAIN,
    },
  });
}

/**
 * Map host-walk supervision → "unsupervised" leg.
 * POSITIVE means unsupervised (reap-shaped); SUPERVISED is NEGATIVE for this leg;
 * UNCERTAIN stays UNCERTAIN.
 * @param {object|boolean|string} supervision
 */
function mapSupervisionLeg(supervision) {
  if (supervision && typeof supervision === 'object') {
    const st = supervision.status || supervision.supervisionStatus;
    if (st === 'SUPERVISED' || supervision.supervised === true) {
      return {
        status: LEG_NEGATIVE,
        reason: supervision.reason || 'SUPERVISED',
        reasonCodes: ['SUPERVISED', supervision.reason].filter(Boolean),
      };
    }
    if (st === 'UNSUPERVISED' || supervision.unsupervised === true) {
      return {
        status: LEG_POSITIVE,
        reason: supervision.reason || 'UNSUPERVISED',
        reasonCodes: ['UNSUPERVISED', supervision.reason].filter(Boolean),
      };
    }
    if (st === 'UNCERTAIN') {
      return {
        status: LEG_UNCERTAIN,
        reason: supervision.reason || 'SUPERVISION_UNCERTAIN',
        reasonCodes: ['SUPERVISION_UNCERTAIN', supervision.reason].filter(Boolean),
      };
    }
  }
  // Boolean: true = supervised (leg NEGATIVE for unsupervised requirement)
  if (typeof supervision === 'boolean') {
    return supervision
      ? {
        status: LEG_NEGATIVE,
        reason: 'SUPERVISED',
        reasonCodes: ['SUPERVISED'],
      }
      : {
        status: LEG_POSITIVE,
        reason: 'UNSUPERVISED',
        reasonCodes: ['UNSUPERVISED'],
      };
  }
  return normalizeLeg(supervision, {
    trueAs: LEG_POSITIVE,
    falseAs: LEG_NEGATIVE,
    trueReason: 'UNSUPERVISED',
    falseReason: 'SUPERVISED',
    nullReason: 'SUPERVISION_UNCERTAIN',
    positiveAlias: 'UNSUPERVISED',
    negativeAlias: 'SUPERVISED',
    stringMap: {
      UNSUPERVISED: LEG_POSITIVE,
      SUPERVISED: LEG_NEGATIVE,
      SUPERVISION_UNCERTAIN: LEG_UNCERTAIN,
      UNCERTAIN: LEG_UNCERTAIN,
    },
  });
}

/**
 * Map ownership lookup → "not owned" leg.
 * POSITIVE = not owned (reap allowed by ownership); owned/fail-closed = NEGATIVE keep.
 * @param {object|boolean|string} ownership
 */
function mapOwnershipLeg(ownership) {
  if (ownership && typeof ownership === 'object') {
    if (ownership.failClosed === true || ownership.reason === OWNERSHIP_IPC_FAIL_CLOSED) {
      return {
        status: LEG_NEGATIVE,
        reason: OWNERSHIP_IPC_FAIL_CLOSED,
        reasonCodes: (ownership.reasonCodes || [OWNERSHIP_IPC_STUB, OWNERSHIP_IPC_FAIL_CLOSED]).slice(),
        keep: true,
        owned: true,
      };
    }
    if (ownership.owned === true || ownership.keep === true) {
      return {
        status: LEG_NEGATIVE,
        reason: ownership.reason || OWNERSHIP_REGISTERED_KEEP,
        reasonCodes: (ownership.reasonCodes || [OWNERSHIP_IPC_STUB, OWNERSHIP_REGISTERED_KEEP]).slice(),
        keep: true,
        owned: true,
      };
    }
    if (ownership.owned === false) {
      return {
        status: LEG_POSITIVE,
        reason: ownership.reason || OWNERSHIP_NOT_REGISTERED,
        reasonCodes: (ownership.reasonCodes || [OWNERSHIP_IPC_STUB, OWNERSHIP_NOT_REGISTERED]).slice(),
        keep: false,
        owned: false,
      };
    }
  }
  if (typeof ownership === 'boolean') {
    // true = owned → not-owned leg NEGATIVE
    return ownership
      ? {
        status: LEG_NEGATIVE,
        reason: OWNERSHIP_REGISTERED_KEEP,
        reasonCodes: [OWNERSHIP_IPC_STUB, OWNERSHIP_REGISTERED_KEEP],
        keep: true,
        owned: true,
      }
      : {
        status: LEG_POSITIVE,
        reason: OWNERSHIP_NOT_REGISTERED,
        reasonCodes: [OWNERSHIP_IPC_STUB, OWNERSHIP_NOT_REGISTERED],
        keep: false,
        owned: false,
      };
  }
  const n = normalizeLeg(ownership, {
    trueAs: LEG_POSITIVE,
    falseAs: LEG_NEGATIVE,
    trueReason: OWNERSHIP_NOT_REGISTERED,
    falseReason: OWNERSHIP_REGISTERED_KEEP,
    nullReason: OWNERSHIP_IPC_FAIL_CLOSED,
    stringMap: {
      NOT_OWNED: LEG_POSITIVE,
      OWNED: LEG_NEGATIVE,
      OWNERSHIP_NOT_REGISTERED: LEG_POSITIVE,
      OWNERSHIP_REGISTERED_KEEP: LEG_NEGATIVE,
      OWNERSHIP_IPC_FAIL_CLOSED: LEG_NEGATIVE,
    },
  });
  n.owned = n.status === LEG_NEGATIVE;
  n.keep = n.status === LEG_NEGATIVE;
  return n;
}

/**
 * Evaluate the four-leg joint-quad skeleton.
 *
 * @param {object} legs
 * @param {object|boolean|string} [legs.engine]
 * @param {object|boolean|string} [legs.spend]
 * @param {object|boolean|string} [legs.supervision]
 * @param {object|boolean|string} [legs.ownership]
 * @returns {{
 *   verdict: 'WOULD_BE_RED'|'KEEP'|'ABSTAIN',
 *   jointPositive: boolean,
 *   wouldBeActionableRed: boolean,
 *   abstain: boolean,
 *   keep: boolean,
 *   reasonCodes: string[],
 *   legs: object,
 *   uncertainLegs: string[],
 * }}
 */
function evaluateQuad(legs = {}) {
  const engine = mapEngineLeg(legs.engine);
  const spend = mapSpendLeg(legs.spend);
  const supervision = mapSupervisionLeg(legs.supervision);
  const ownership = mapOwnershipLeg(legs.ownership);

  const legMap = {
    engine,
    spend,
    supervision,
    ownership,
  };

  const uncertainLegs = [];
  for (const [name, leg] of Object.entries(legMap)) {
    if (leg.status === LEG_UNCERTAIN) uncertainLegs.push(name);
  }

  const reasonCodes = [];
  for (const leg of Object.values(legMap)) {
    for (const c of leg.reasonCodes || []) {
      if (c && !reasonCodes.includes(c)) reasonCodes.push(c);
    }
  }

  // Any uncertain leg ⇒ ABSTAIN (never RED).
  if (uncertainLegs.length > 0) {
    reasonCodes.push('QUAD_ABSTAIN_UNCERTAIN_LEG', 'VERDICT_ABSTAIN');
    return {
      verdict: VERDICT_ABSTAIN,
      jointPositive: false,
      wouldBeActionableRed: false,
      abstain: true,
      keep: false,
      reasonCodes: filterKnownReasonCodes(reasonCodes),
      legs: legMap,
      uncertainLegs,
    };
  }

  // Owned / fail-closed ownership ⇒ KEEP.
  if (ownership.status === LEG_NEGATIVE) {
    reasonCodes.push('QUAD_KEEP', 'VERDICT_KEEP');
    return {
      verdict: VERDICT_KEEP,
      jointPositive: false,
      wouldBeActionableRed: false,
      abstain: false,
      keep: true,
      reasonCodes: filterKnownReasonCodes(reasonCodes),
      legs: legMap,
      uncertainLegs: [],
    };
  }

  // Supervised (supervision leg NEGATIVE) ⇒ KEEP (not reap-shaped).
  if (supervision.status === LEG_NEGATIVE) {
    reasonCodes.push('QUAD_KEEP', 'VERDICT_KEEP');
    return {
      verdict: VERDICT_KEEP,
      jointPositive: false,
      wouldBeActionableRed: false,
      abstain: false,
      keep: true,
      reasonCodes: filterKnownReasonCodes(reasonCodes),
      legs: legMap,
      uncertainLegs: [],
    };
  }

  // Joint positive: all four POSITIVE
  // engine ∧ paid-spend ∧ unsupervised ∧ not-owned
  const joint =
    engine.status === LEG_POSITIVE
    && spend.status === LEG_POSITIVE
    && supervision.status === LEG_POSITIVE
    && ownership.status === LEG_POSITIVE;

  if (joint) {
    reasonCodes.push('QUAD_JOINT_POSITIVE', 'VERDICT_WOULD_BE_RED', 'WOULD_BE_ACTIONABLE_RED');
    return {
      verdict: VERDICT_WOULD_BE_RED,
      jointPositive: true,
      wouldBeActionableRed: true,
      abstain: false,
      keep: false,
      reasonCodes: filterKnownReasonCodes(reasonCodes),
      legs: legMap,
      uncertainLegs: [],
    };
  }

  // Incomplete joint (e.g. engine-negative or spend-negative) ⇒ KEEP / non-RED
  reasonCodes.push('QUAD_KEEP', 'VERDICT_KEEP');
  return {
    verdict: VERDICT_KEEP,
    jointPositive: false,
    wouldBeActionableRed: false,
    abstain: false,
    keep: true,
    reasonCodes: filterKnownReasonCodes(reasonCodes),
    legs: legMap,
    uncertainLegs: [],
  };
}

/**
 * Fail-SAFE matrix helper: under shadow, joint-positive still cannot be
 * actionable RED on dual-write surfaces (observe-only).
 *
 * @param {object} quad — evaluateQuad result
 * @param {string} classifierMode
 * @param {boolean} actionableRedAllowed
 */
function failSafeMatrixEntry(quad, classifierMode, actionableRedAllowed) {
  const mode = String(classifierMode || 'shadow').toLowerCase();
  const scare = !!actionableRedAllowed;
  return {
    classifierMode: mode,
    verdict: quad.verdict,
    jointPositive: !!quad.jointPositive,
    wouldBeActionableRed: !!quad.wouldBeActionableRed,
    actionableRed: scare && !!quad.wouldBeActionableRed,
    observeOnly: !scare,
    reasonCodes: (quad.reasonCodes || []).slice(),
    uncertainLegs: (quad.uncertainLegs || []).slice(),
  };
}

module.exports = {
  LEG_POSITIVE,
  LEG_NEGATIVE,
  LEG_UNCERTAIN,
  VERDICT_WOULD_BE_RED,
  VERDICT_KEEP,
  VERDICT_ABSTAIN,
  mapEngineLeg,
  mapSpendLeg,
  mapSupervisionLeg,
  mapOwnershipLeg,
  evaluateQuad,
  failSafeMatrixEntry,
};
