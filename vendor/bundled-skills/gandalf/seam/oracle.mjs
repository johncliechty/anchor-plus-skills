// Gandalf advisor — the ADVISORY elevation-oracle / cross-family judge ADAPTER (Wave 7).
//
// PRINCIPLE-D, made CONCRETE and PROVABLE. The locked North Star's NS5 ("elevates, not merely
// critique") is eventually PROVEN by a measurable elevation oracle that runs a paired A/B with a
// CROSS-FAMILY LLM judge. That judging is, by assignment, ADVISORY: it is recorded as an
// artifact and READ by a human, and it is NEVER part of the deterministic Foreman gate
// (`node --test test/*.test.mjs`). This module is the adapter for that cross-family judge.
//
// The load-bearing PRINCIPLE-D property this module exists to make TESTABLE:
//   the deterministic gate (test/harness.mjs + the seams it imports) does NOT import this module,
//   so the gate's outcome is PROVABLY INDEPENDENT of whether the judge endpoint is reachable.
//   The PRINCIPLE-D meta-isolation test makes the endpoint UNREACHABLE and shows the gate still
//   passes on a conformant fixture (and statically, that the gate's import closure excludes it).
//
// Two entry points, deliberately separated so the test can prove BOTH halves:
//   • callCrossFamilyJudge(elevation, {endpoint})  — the RAW adapter. Throws
//     CrossFamilyJudgeUnreachable when the endpoint is missing or itself throws. This is what
//     proves the endpoint is genuinely unreachable (the test asserts it throws).
//   • adviseElevationOracle(output, {endpoint})    — the ADVISORY wrapper. NEVER throws on an
//     unreachable judge and NEVER gates: it CATCHES unreachability and returns an honest DEGRADED
//     advisory artifact stamped `gating:false`. This is the surface a human reads; it cannot fail
//     `node --test` because nothing in the deterministic gate calls it.
//
// Public surface:
//   CROSS_FAMILY_JUDGE_KIND                 — the advisory judge adapter marker
//   CrossFamilyJudgeUnreachable             — error class: the judge endpoint is unreachable
//   unreachableEndpoint                     — a ready-made endpoint that is always unreachable
//   callCrossFamilyJudge(elevation, opts)   — raw adapter (throws when unreachable)
//   adviseElevationOracle(output, opts)     — ADVISORY, NEVER-GATING wrapper (degrades, never throws)

/** The advisory cross-family judge adapter marker (stamped on the advisory artifact). */
export const CROSS_FAMILY_JUDGE_KIND = 'advisory-cross-family-judge';

/** Thrown by the RAW adapter when the cross-family judge endpoint is missing or unreachable. A
 *  distinct class so the meta-isolation test can assert the judge is GENUINELY unreachable (and so
 *  the advisory wrapper can catch exactly this and degrade). */
export class CrossFamilyJudgeUnreachable extends Error {
  constructor(message = 'cross-family judge endpoint is unreachable') {
    super(`PRINCIPLE-D advisory: ${message} — the oracle/judge is ADVISORY and NEVER gates node --test`);
    this.name = 'CrossFamilyJudgeUnreachable';
  }
}

/** A ready-made endpoint that is ALWAYS unreachable — calling it throws CrossFamilyJudgeUnreachable.
 *  The meta-isolation test injects this to make the judge endpoint "UNREACHABLE." */
export function unreachableEndpoint() {
  throw new CrossFamilyJudgeUnreachable('endpoint refused the connection (simulated network failure)');
}

function isObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/** The RAW cross-family judge adapter. Dispatches `elevation` to the injected `endpoint` (the live
 *  cross-family LLM transport) and returns its advisory verdict. THROWS CrossFamilyJudgeUnreachable
 *  when no endpoint is wired or the endpoint itself throws — this is how the test proves the judge
 *  is genuinely unreachable. (This raw form is NEVER called by the deterministic gate.) */
export function callCrossFamilyJudge(elevation, { endpoint } = {}) {
  if (typeof endpoint !== 'function') {
    throw new CrossFamilyJudgeUnreachable('no cross-family judge endpoint is wired');
  }
  let response;
  try {
    response = endpoint({ elevation });
  } catch (err) {
    if (err instanceof CrossFamilyJudgeUnreachable) throw err;
    throw new CrossFamilyJudgeUnreachable(`endpoint failed: ${err?.message ?? err}`);
  }
  return {
    kind: CROSS_FAMILY_JUDGE_KIND,
    advisory: true,
    verdict: isObject(response) ? response.verdict ?? null : null,
    note: 'ADVISORY cross-family judge verdict — recorded as an artifact, NEVER a gate',
  };
}

/** The ADVISORY, NEVER-GATING elevation-oracle wrapper. Runs the cross-family judge over each
 *  elevation in `output` and returns an advisory artifact. The contract that makes PRINCIPLE-D
 *  real: it NEVER throws on an unreachable judge and ALWAYS stamps `gating:false`. When the
 *  endpoint is unreachable it returns an HONEST DEGRADED artifact (judged:false, degraded:true)
 *  rather than failing — so even if some caller wired this into a path, it could not turn judge
 *  unreachability into a gate failure. Pure w.r.t. `output` (does not mutate it). */
export function adviseElevationOracle(output, { endpoint } = {}) {
  const elevations = Array.isArray(output?.elevations) ? output.elevations : [];
  const verdicts = [];
  let degraded = false;
  let unreachableReason = null;
  for (const elevation of elevations) {
    try {
      verdicts.push(callCrossFamilyJudge(elevation, { endpoint }));
    } catch (err) {
      degraded = true;
      unreachableReason = err?.message ?? String(err);
      verdicts.push({
        kind: CROSS_FAMILY_JUDGE_KIND,
        advisory: true,
        judged: false,
        verdict: null,
        note: 'judge unreachable for this elevation — advisory degraded, NOT a gate',
      });
    }
  }
  return {
    kind: CROSS_FAMILY_JUDGE_KIND,
    advisory: true,
    gating: false, // PRINCIPLE-D: this artifact is NEVER a gate, reachable judge or not
    judged: !degraded && elevations.length > 0,
    degraded,
    reason: degraded ? unreachableReason : null,
    verdicts,
    note: 'PRINCIPLE-D: the elevation oracle / cross-family judge is ADVISORY — recorded for a human to read, NEVER part of node --test',
  };
}
