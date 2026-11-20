// bin/matrix-planner.mjs — Deterministic Question-Decomposing Research Plan Matrix + Domain Certifiers.
//
// Upgrades the Gate-2 matrix planner from a static 4-row stub into a pure, deterministic
// question-decomposing planner that extracts concrete sub-claims, explicit falsifiers,
// required evidence rungs (OBSERVED / CORROBORATED), and portfolio domain-certifier hooks
// (Ramanujan, Literature-Review, Financial-Analyst, Legal-Beagle).
//
// PURE FUNCTION OF INPUTS: no clock, no randomness, no ambient host state — identical inputs
// serialize to byte-identical JSON and therefore an identical `planHash` (required by Wave-5
// EDIT re-hashing and Wave-8 replay-bound approval fixtures).

import crypto from 'node:crypto';

export const PLAN_VERSION = 2;

export const EVIDENCE_RUNGS = Object.freeze(['OBSERVED', 'CORROBORATED']);

const CERTIFIER_CATALOG = Object.freeze([
  {
    skill: 'Ramanujan',
    domain: 'mathematics',
    requiredRung: 'OBSERVED',
    re: /\b(?:theorem|proof|lemma|equation|derivation|bound|asymptotic|eigenvalue|jacobian|hessian|convex|stochastic|markov|integral|differential|closed[- ]form|formal\s+verif(?:y|ication)|z3|lean4?)\b/i,
    gateTask: 'Run Ramanujan exact-arithmetic / symbolic / Z3 ground-equation certifier over derived mathematical claims',
  },
  {
    skill: 'Literature-Review',
    domain: 'literature',
    requiredRung: 'CORROBORATED',
    re: /\b(?:systematic\s+review|meta[- ]analysis|literature\s+review|prisma|citation|peer[- ]reviewed|clinical\s+trial|cohort\s+study|randomized|rct|pubmed|arxiv|consensus\s+across\s+papers|drug[- ]interaction)\b/i,
    gateTask: 'Run Literature-Review PRISMA quote-grounding & cross-paper consensus verification over cited studies',
  },
  {
    skill: 'Financial-Analyst',
    domain: 'financial',
    requiredRung: 'OBSERVED',
    re: /\b(?:valuation|dcf|discounted\s+cash\s+flow|cap[- ]table|equity\s+waterfall|liquidation\s+preference|irr\b|npv\b|multiple|ebitda|solvency|pro[- ]forma|round\s+math|fiduciary\s+return)\b/i,
    gateTask: 'Run Financial-Analyst exact-Decimal model tie-out over quantitative valuation / waterfall claims',
  },
  {
    skill: 'Legal-Beagle',
    domain: 'legal',
    requiredRung: 'CORROBORATED',
    re: /\b(?:statute|case[- ]law|precedent|contract(?:ual)?|indemnif(?:y|ication)|liability|fiduciary\s+duty|jurisdiction|compliance|regulation|hipaa|gdpr|sec\s+filing|clause|tort)\b/i,
    gateTask: 'Run Legal-Beagle jurisdiction/date-pinned primary-source citation & anti-hallucination audit',
  },
]);

const EMPIRICAL_SIGNAL_RE =
  /\b(?:benchmark|latency|throughput|p95|p99|runtime|memory|measure|empirical|execute|reproduce|proof|equation|bound|valuation|dcf|waterfall|irr\b|npv\b|exact|compile|test)\b/i;

/**
 * Detect portfolio domain certifiers triggered by the objective / explicit domain hint.
 * @param {{ objective: string, domain?: string }} o
 * @returns {Array<{ skill: string, domain: string, requiredRung: string, trigger: string, gateTask: string }>}
 */
export function detectDomainCertifiers({ objective = '', domain = '' } = {}) {
  const text = `${String(domain || '')} ${String(objective || '')}`.trim();
  const matched = [];
  for (const entry of CERTIFIER_CATALOG) {
    const m = entry.re.exec(text);
    const domainExact = typeof domain === 'string' && domain.trim().toLowerCase() === entry.domain;
    if (m || domainExact) {
      matched.push({
        skill: entry.skill,
        domain: entry.domain,
        requiredRung: entry.requiredRung,
        trigger: m ? m[0] : `domain:${entry.domain}`,
        gateTask: entry.gateTask,
      });
    }
  }
  return matched;
}

/**
 * Deterministically decompose a research objective into atomic sub-claims, each with
 * an explicit falsifier condition and minimum required evidence rung.
 *
 * @param {string} objective
 * @param {Array<{ skill: string, requiredRung: string }>} [certifiers=[]]
 * @returns {Array<{ id: string, claim: string, falsifier: string, requiredRung: 'OBSERVED'|'CORROBORATED' }>}
 */
export function decomposeObjectiveClaims(objective, certifiers = []) {
  const cleaned = String(objective || '').replace(/\s+/g, ' ').trim();
  // Split compound research questions on semicolons, numbered clauses, explicit conjunctions
  // ("and whether", "versus", "vs.", "compared to"), or multi-sentence question marks.
  const rawParts = cleaned
    .split(/(?:;\s+|\?\s+(?=[A-Z0-9])|\b(?:and\s+whether|and\s+how|and\s+what|versus|vs\.)\b)/i)
    .map((s) => s.replace(/^\s*(?:\(\d+\)|\d+[.)])\s*/, '').trim())
    .filter((s) => s.length >= 6);

  const segments = rawParts.length > 0 ? rawParts : [cleaned];
  const hasObservedCertifier = certifiers.some((c) => c.requiredRung === 'OBSERVED');

  return segments.map((seg, idx) => {
    const id = `sc-${idx + 1}`;
    const needsObserved = EMPIRICAL_SIGNAL_RE.test(seg) || (idx === 0 && hasObservedCertifier);
    const requiredRung = needsObserved ? 'OBSERVED' : 'CORROBORATED';
    const falsifier = needsObserved
      ? `Falsified if reproducible execution, direct measurement, or exact calculation contradicts "${seg}" or fails under boundary conditions.`
      : `Falsified if >=2 independent primary sources or attested lineages refute "${seg}" or show the claim rests solely on unverified secondary repetition.`;
    return {
      id,
      claim: seg,
      falsifier,
      requiredRung,
    };
  });
}

/**
 * Build the deterministic research plan matrix for an objective.
 *
 * @param {{ objective: string, domain?: string, stakes?: object|string }} params
 * @returns {{
 *   planVersion: number,
 *   objective: string,
 *   objectiveHash: string,
 *   subClaims: Array<{ id: string, claim: string, falsifier: string, requiredRung: string }>,
 *   domainCertifiers: Array<{ skill: string, domain: string, requiredRung: string, trigger: string, gateTask: string }>,
 *   matrix: Array<{ stage: string, gate: string, task: string, subClaimId?: string, falsifier?: string, requiredRung?: string, certifier?: string }>
 * }}
 */
export function planMatrix({ objective, domain = '', stakes = null } = {}) {
  if (typeof objective !== 'string' || objective.trim().length === 0) {
    throw new TypeError('planMatrix requires a non-empty objective string');
  }
  const hashInput = domain ? `${objective}\0domain=${domain}` : objective;
  const objectiveHash = crypto.createHash('sha256').update(hashInput, 'utf8').digest('hex');

  const domainCertifiers = detectDomainCertifiers({ objective, domain });
  const subClaims = decomposeObjectiveClaims(objective, domainCertifiers);

  const matrix = [
    {
      stage: 'scope',
      gate: 'gate1',
      task: `Bound AXIS, scope exclusions, and ${subClaims.length} decomposed sub-claim(s) for: ${objective}`,
    },
  ];

  for (const sc of subClaims) {
    matrix.push({
      stage: 'evidence',
      gate: 'rounds',
      subClaimId: sc.id,
      requiredRung: sc.requiredRung,
      falsifier: sc.falsifier,
      task: `[${sc.id} -> ${sc.requiredRung}] Gather primary evidence & test falsifier for: ${sc.claim}`,
    });
  }

  for (const cert of domainCertifiers) {
    matrix.push({
      stage: 'certifier',
      gate: 'rounds',
      certifier: cert.skill,
      requiredRung: cert.requiredRung,
      task: `[${cert.skill}] ${cert.gateTask}`,
    });
  }

  matrix.push({
    stage: 'adversarial',
    gate: 'rounds',
    requiredRung: stakes === 'high' ? 'OBSERVED' : 'CORROBORATED',
    task: `Cross-family G3 panel + Judge falsification attempt against all ${subClaims.length} sub-claim(s) for: ${objective}`,
  });

  matrix.push({
    stage: 'synthesis',
    gate: 'gate2',
    task: `Assemble three-level source-graded deliverable (full / executive / agent-implementation) for: ${objective}`,
  });

  return {
    planVersion: PLAN_VERSION,
    objective,
    objectiveHash,
    subClaims,
    domainCertifiers,
    matrix,
  };
}
