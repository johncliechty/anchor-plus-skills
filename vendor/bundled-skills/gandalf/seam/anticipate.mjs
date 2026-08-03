// Gandalf advisor — the ANTICIPATE compose SEAM (Wave 5 / the NS3 Oranges-lens premortem).
//
// NS3 ANTICIPATE: Gandalf "looks ahead via Parable-of-the-Oranges foresight to surface
// implicit and coming problems." The locked North-Star reconciliation pins this to a BOUNDED
// premortem applied to a SINGLE effort — NOT Crucible's multi-plan refutation-to-convergence /
// counterfactual-cost-across-competing-paths engine. So each anticipation is:
//
//   a not-yet-present FUTURE-STATE CONDITION  +  the ENABLING ASSUMPTION that would bring it on
//   (subject_cardinality == 1; no regret / counterfactual-cost pricing across competing paths)
//
// Two boundaries are load-bearing here and are enforced at the deterministic gate
// (test/harness.mjs `assertBoundedPremortem` = B3, `assertForwardLooking` = B9), label/semantic
// TRUTH staying the advisory layer's job (PRINCIPLE-D):
//   • B3 PREMORTEM ≠ ORANGES-ENGINE. A regret/counterfactual-cost FIELD, or subject_cardinality
//     > 1, means the finding is doing Crucible's cross-path machinery — it FAILS and is routed to
//     a Crucible commission (`commissionCrucible`).
//   • B9 FORWARD-LOOKING. An anticipation must carry a populated, well-formed future-state
//     condition + enabling assumption; a present-tense finding (no future-state) FAILS.
//
// B3 is a NECESSARY syntactic invariant, not a SUFFICIENT semantic boundary: a finding can keep
// the schema clean yet perform cross-path cost reasoning in its PROSE. That residual is caught by
// `flagCrossPathCostReasoning` — an ADVISORY (PRINCIPLE-D) check that is ISOLATED from the gate:
// the deterministic canaries never call it, so it can never gate `node --test`. It only flags an
// anticipation for routing to a Crucible commission.
//
// Public surface:
//   ANTICIPATE_KIND                          — the finding `kind` for an anticipate leg
//   BOUNDED_SUBJECT_CARDINALITY              — the bounded-premortem cardinality (=1)
//   ORANGES_ENGINE_FIELDS                    — regret/counterfactual-cost fields B3 forbids
//   hasOrangesEngineField(finding)           — predicate: carries a forbidden field / cardinality>1
//   isForwardLookingAnticipation(finding)    — predicate: populated future-state + enabling assumption
//   composeAnticipation(stages)              — assemble a bounded, forward-looking anticipate finding
//   CRUCIBLE_KIND / commissionCrucible(..)   — route a cross-path-cost task OUT to a Crucible commission
//   CROSS_PATH_COST_SIGNALS                  — the advisory cross-path / counterfactual prose vocabulary
//   flagCrossPathCostReasoning(finding)      — ADVISORY (PRINCIPLE-D, isolated): flag cross-path prose

// --- self-contained helpers (the seam imports nothing; harness.mjs imports the seam) ------
function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim() !== '';
}
function isNonEmpty(v) {
  if (v === undefined || v === null) return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === 'string') return v.trim() !== '';
  if (typeof v === 'object') return Object.keys(v).length > 0;
  return true; // numbers, booleans
}

/** The finding `kind` for the ANTICIPATE leg. */
export const ANTICIPATE_KIND = 'anticipate';

/** The bounded-premortem cardinality: Gandalf's Oranges-lens foresight reads a SINGLE effort,
 *  never a field of competing paths. subject_cardinality must be exactly this. */
export const BOUNDED_SUBJECT_CARDINALITY = 1;

// --- B3: premortem ≠ Crucible's Oranges-engine --------------------------------------------
/** The regret / counterfactual-cost FIELDS that belong to Crucible's multi-plan engine, not to
 *  Gandalf's bounded premortem. An anticipate finding carrying any of these is pricing the cost
 *  of NOT taking a competing path — that is Crucible's job, so B3 routes it out. */
export const ORANGES_ENGINE_FIELDS = [
  'regret',
  'regret_cost',
  'counterfactual',
  'counterfactual_cost',
  'cross_path_cost',
  'competing_paths',
  'path_comparison',
];

/** Predicate (the B3 core): does `finding` carry Crucible's Oranges-engine signature — a
 *  populated regret/counterfactual-cost FIELD, or subject_cardinality > 1 (a multi-path read)?
 *  Pure; never throws. (Cross-path cost reasoning carried only in PROSE is NOT caught here — that
 *  residual is the advisory `flagCrossPathCostReasoning`'s job, by assignment / PRINCIPLE-D.) */
export function hasOrangesEngineField(finding) {
  if (finding === null || typeof finding !== 'object' || Array.isArray(finding)) return false;
  if (finding.subject_cardinality !== undefined && finding.subject_cardinality !== BOUNDED_SUBJECT_CARDINALITY) {
    return true;
  }
  return ORANGES_ENGINE_FIELDS.some((f) => isNonEmpty(finding[f]));
}

// --- B9: an anticipation is a not-yet-present future-state ---------------------------------
/** Predicate (the B9 core): is `finding` a well-formed FORWARD-LOOKING anticipation — i.e. does
 *  it carry a populated, non-empty `future_state_condition` (a not-yet-present condition) AND a
 *  populated, non-empty `enabling_assumption` (what would have to hold for it to arrive)? A
 *  present-tense finding (neither future-state field) is NOT forward-looking. Pure; never throws.
 *  (Whether the prose is GENUINELY future-tense is semantic TRUTH owned by the advisory layer;
 *  the gate owns the structural shape — both fields present and non-empty strings.) */
export function isForwardLookingAnticipation(finding) {
  if (finding === null || typeof finding !== 'object' || Array.isArray(finding)) return false;
  return isNonEmptyString(finding.future_state_condition) && isNonEmptyString(finding.enabling_assumption);
}

// --- compose a bounded, forward-looking ANTICIPATE finding ---------------------------------
/** Assemble an ANTICIPATE finding from the premortem stages, enforcing both boundaries:
 *  it stamps subject_cardinality == 1 (bounded), requires a populated future-state condition +
 *  enabling assumption (forward-looking), and refuses to carry any Oranges-engine regret/
 *  counterfactual-cost field (those route to a Crucible commission, never into a Gandalf
 *  anticipation). Anticipations are predictions about a not-yet-present future, so the honest
 *  default rung is UNVERIFIED. `reasoning` precedes `verdict` in the returned key order
 *  (reasoning-before-verdict). Returns a FRESH object; throws if the premortem is incomplete or
 *  smuggles a cross-path-cost field. */
export function composeAnticipation({
  id,
  future_state_condition,
  enabling_assumption,
  reasoning,
  verdict,
  rung = 'UNVERIFIED',
  severity,
} = {}) {
  if (!isNonEmptyString(id)) throw new Error('anticipate: composeAnticipation requires an id');
  if (!isNonEmptyString(future_state_condition)) {
    throw new Error('anticipate: composeAnticipation requires a non-empty future_state_condition (an anticipation is a not-yet-present future state, never present-tense)');
  }
  if (!isNonEmptyString(enabling_assumption)) {
    throw new Error('anticipate: composeAnticipation requires a non-empty enabling_assumption (what would have to hold for the future state to arrive)');
  }
  const finding = {
    id,
    kind: ANTICIPATE_KIND,
    rung,
    reasoning: isNonEmptyString(reasoning) ? reasoning : `ANTICIPATE: if "${enabling_assumption}" holds, the coming problem is "${future_state_condition}".`,
    verdict: isNonEmptyString(verdict) ? verdict : future_state_condition.trim(),
    subject_cardinality: BOUNDED_SUBJECT_CARDINALITY,
    future_state_condition: future_state_condition.trim(),
    enabling_assumption: enabling_assumption.trim(),
  };
  if (isNonEmptyString(severity)) finding.severity = severity;
  // Defence in depth: never let an Oranges-engine field ride along into a bounded premortem.
  if (hasOrangesEngineField(finding)) {
    throw new Error('anticipate: composeAnticipation must not carry a regret/counterfactual-cost field — cross-path cost pricing routes to a Crucible commission (commissionCrucible)');
  }
  return finding;
}

// --- route a cross-path-cost task OUT to Crucible ------------------------------------------
/** The skill a cross-path-cost / multi-plan refutation task is commissioned out to. */
export const CRUCIBLE_KIND = 'crucible';

/** Mint a typed Crucible commission ENVELOPE — the deterministic surface of the bare `agent()`
 *  seam for when an anticipation is actually doing multi-plan refutation / counterfactual-cost-
 *  across-paths work. Gandalf does NOT reimplement that engine (NS6); it routes the task to
 *  Crucible. `commission_id` is honor-system in Increment 1 (the unforgeable orchestrator-minted
 *  ledger is an external, later dependency). Throws on an empty question. */
export function commissionCrucible({ question, commission_id = null } = {}) {
  if (!isNonEmptyString(question)) {
    throw new Error('anticipate: commissionCrucible requires a non-empty question');
  }
  return {
    skill: 'crucible',
    question: question.trim(),
    reason: 'cross-path counterfactual-cost / multi-plan refutation is Crucible\'s engine, not Gandalf\'s bounded premortem',
    crucible_commission_id: commission_id,
  };
}

// --- the ADVISORY cross-path-cost flag (PRINCIPLE-D — ISOLATED, never in the gate) ----------
/** The advisory cross-path / counterfactual-cost prose vocabulary. A schema-clean anticipation
 *  can still REASON across competing paths in its prose; these phrases are the heuristic signal
 *  that it is doing so. Deterministic phrase-matching here STANDS IN for the advisory LLM check
 *  (PRINCIPLE-D); judging the prose's true intent is the advisory layer's job. */
export const CROSS_PATH_COST_SIGNALS = [
  'compared to the alternative',
  'the other path',
  'competing path',
  'across paths',
  'across the paths',
  'versus the alternative',
  'regret of not',
  'cost of not choosing',
  'counterfactual cost',
  'opportunity cost',
  'had we chosen',
  'if we had picked',
  'the path not taken',
];

/** ADVISORY (PRINCIPLE-D) — and ISOLATED FROM THE GATE BY ASSIGNMENT: the deterministic canaries
 *  (assertBoundedPremortem / assertForwardLooking / assertAnticipateSeam) never call this, so it
 *  can never gate `node --test`. It flags a schema-clean anticipation whose PROSE performs
 *  cross-path cost reasoning (the residual B3 cannot catch syntactically) and recommends routing
 *  it to a Crucible commission. Returns an advisory record; pure, never throws. */
export function flagCrossPathCostReasoning(finding) {
  if (finding === null || typeof finding !== 'object' || Array.isArray(finding)) {
    return { advisory: true, flagged: false, signals: [], route_to: null };
  }
  const prose = [
    finding.reasoning,
    finding.verdict,
    finding.future_state_condition,
    finding.enabling_assumption,
  ]
    .filter((s) => typeof s === 'string')
    .join(' \n ')
    .toLowerCase();
  const signals = CROSS_PATH_COST_SIGNALS.filter((p) => prose.includes(p));
  const flagged = signals.length > 0;
  return {
    advisory: true,
    flagged,
    signals,
    route_to: flagged ? CRUCIBLE_KIND : null,
    note: flagged
      ? 'PRINCIPLE-D advisory: prose performs cross-path cost reasoning — route to a Crucible commission (this flag is NEVER a gate)'
      : 'PRINCIPLE-D advisory: no cross-path cost reasoning detected in prose',
  };
}
