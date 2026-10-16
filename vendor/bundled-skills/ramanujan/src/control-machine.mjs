// Wave 17 — Metacognitive CONTROL state machine + ABANDON fixture (C3).
//
// The SOLVE pillar's METACOGNITIVE EXECUTIVE (NS2 — "generative SOLVE + executable CONTROL"). Where
// Wave-15 generation (C1) PROPOSES a candidate and decomposes it into typed claims, and Wave-16 (C2)
// DISPATCHES each claim to a verification route, this pass is the SCHOENFELD-style control layer that
// drives a solution ATTEMPT step by step and DECIDES — from a metacognitive read of whether the attempt
// is making PROGRESS — when to keep going, when to SWITCH strategy, and when to give up (ABANDON).
//
// It is a pure STATE MACHINE graded over a PROGRESS-BOOLEAN STREAM (one boolean per executed step:
// did this step make progress toward the goal?). In production the stream is the solver's own
// metacognitive self-assessment; here it is a PINNED canned stream so the control logic is graded
// deterministically.
//
// THE S1 THRESHOLDS + GAP-FUNCTION (pinned in DESCRIPTION.md §Residuals · S1). All three are constants
// of this module, not tunables of the fixture:
//
//   BUDGET           = 8   — at most 8 steps; reaching the budget with no resolution ABANDONs
//                            (reason=budget-exhausted).
//   SWITCH_WINDOW    = 3   — the GAP-FUNCTION: if NO step in the last m=3 steps made progress, the
//                            attempt is stuck => SWITCH strategy. (A switch resets the progress window:
//                            the new strategy is graded on its own fresh window.)
//   ABANDON_SWITCHES = 2   — 2 CONSECUTIVE switches (no progress step between them) => ABANDON
//                            (reason=gap-function). A single switch followed by real progress resets the
//                            consecutive-switch streak, so one switch never abandons.
//
// THE DEFINING INVARIANT (the done-when). On the pinned canned NON-CONVERGING fixture (a stream that
// never makes progress) the machine ABANDONs via the GAP-FUNCTION strictly BEFORE step 8
// (reason=gap-function, NOT budget-exhausted), and the claim is left UNVERIFIED/CONJECTURAL. Trace:
//
//   step 1 (no progress)  window=[F]        — window not yet full
//   step 2 (no progress)  window=[F,F]      — window not yet full
//   step 3 (no progress)  window=[F,F,F]    — GAP => SWITCH #1 (window reset); consecutive=1
//   step 4 (no progress)  window=[F]
//   step 5 (no progress)  window=[F,F]
//   step 6 (no progress)  window=[F,F,F]    — GAP => SWITCH #2; consecutive=2 => ABANDON @ step 6
//
// Step 6 < budget 8, so the ABANDON reason is gap-function and never budget-exhausted — exactly as S1
// pins it. CONTROL NEVER settles a claim: on every exit (ABANDON or a converged HANDOFF) the rung is
// held at UNVERIFIED. The honest lift to a higher rung is the Wave-7 VERIFY router's job alone; this
// module wires no dispatcher, mints no artifact, and never calls promote() — it physically cannot raise
// a rung. (assert() admits only at/below the floor and is sticky, so binding a claim can never flip it.)
//
// Pure node built-ins + the project's own A1 ledger (only to bind the claim CONTROL drives and to PROVE
// it is left UNVERIFIED). Runs under `node --test test/`.

import { ClaimLedger, RUNG, BELIEF, FLOOR_RUNG } from './claim-ledger.mjs';

// ---------------------------------------------------------------------------
// The S1 thresholds (pinned constants — DESCRIPTION.md §Residuals · S1).
// ---------------------------------------------------------------------------

/**
 * The pinned S1 control thresholds. Frozen so the fixture grades the REAL constants, not a tunable.
 *   BUDGET           — max steps before a budget-exhausted ABANDON.
 *   SWITCH_WINDOW    — m: a window of this many consecutive no-progress steps triggers a strategy SWITCH.
 *   ABANDON_SWITCHES — consecutive switches (no progress between them) that trigger a gap-function ABANDON.
 */
export const CONTROL_THRESHOLDS = Object.freeze({
  BUDGET: 8,
  SWITCH_WINDOW: 3,
  ABANDON_SWITCHES: 2,
});

// ---------------------------------------------------------------------------
// The state + reason vocabulary.
// ---------------------------------------------------------------------------

/**
 * The terminal/transient states of the CONTROL machine.
 *   RUNNING   — executing steps (the live, non-terminal state).
 *   ABANDONED — terminal: gave up (reason = gap-function or budget-exhausted). Claim left UNVERIFIED.
 *   HANDOFF   — terminal: the attempt converged on a candidate; CONTROL hands it to the VERIFY router
 *               (it NEVER settles the claim itself — honesty law). Claim left UNVERIFIED.
 */
export const CONTROL_STATE = Object.freeze({
  RUNNING: 'running',
  ABANDONED: 'abandoned',
  HANDOFF: 'handoff',
});

/** The CONTROL states, as an array (introspection + exhaustiveness checks). */
export const CONTROL_STATES = Object.freeze(Object.values(CONTROL_STATE));

/**
 * The two reasons CONTROL ABANDONs.
 *   GAP_FUNCTION     — ABANDON_SWITCHES consecutive switches via the gap-function (the early, S1-pinned
 *                      exit; on the non-converging fixture it MUST be this, strictly before the budget).
 *   BUDGET_EXHAUSTED — ran the full BUDGET of steps without converging or hitting the gap-function.
 */
export const ABANDON_REASON = Object.freeze({
  GAP_FUNCTION: 'gap-function',
  BUDGET_EXHAUSTED: 'budget-exhausted',
});

/**
 * The per-step transitions CONTROL records in its trace.
 *   CONTINUE — progress (or a not-yet-full window): keep the current strategy.
 *   SWITCH   — the gap-function fired: abandon the current strategy for a new one (window reset).
 *   ABANDON  — a terminal give-up (gap-function or budget-exhausted).
 *   CONVERGE — a terminal handoff to VERIFY (the attempt reached a candidate).
 */
export const CONTROL_TRANSITION = Object.freeze({
  CONTINUE: 'continue',
  SWITCH: 'switch',
  ABANDON: 'abandon',
  CONVERGE: 'converge',
});

// ---------------------------------------------------------------------------
// The gap-function (pure).
// ---------------------------------------------------------------------------

/**
 * THE GAP-FUNCTION. Given the current progress WINDOW (the run of progress-booleans observed since the
 * last switch, capped at the most recent SWITCH_WINDOW entries), returns true iff the attempt is stuck:
 * the window is FULL (SWITCH_WINDOW entries) and EVERY entry is no-progress (false). A not-yet-full
 * window is never "stuck" — the strategy has not had m steps to show progress.
 *
 * @param {boolean[]} window — the recent progress-booleans (most recent last), length <= SWITCH_WINDOW.
 * @param {{SWITCH_WINDOW:number}} [thresholds]
 * @returns {boolean} true iff the gap-function says "switch strategy".
 */
export function gapFunction(window, thresholds = CONTROL_THRESHOLDS) {
  const m = thresholds.SWITCH_WINDOW;
  if (!Array.isArray(window) || window.length < m) return false;
  // Only the most recent m matter (the caller keeps the window capped, but be defensive).
  const recent = window.slice(-m);
  return recent.length === m && recent.every((p) => p === false);
}

// ---------------------------------------------------------------------------
// Step normalization.
// ---------------------------------------------------------------------------

/**
 * Normalize one entry of the progress stream to { progress, converged }. An entry is either a bare
 * boolean (progress) or an object { progress:boolean, converged?:boolean }. `converged` marks a step
 * whose progress carried the attempt to a candidate solution (a terminal HANDOFF — never a settle).
 */
function normalizeStep(raw, index) {
  if (typeof raw === 'boolean') return { progress: raw, converged: false };
  if (raw && typeof raw === 'object' && typeof raw.progress === 'boolean') {
    return { progress: raw.progress, converged: raw.converged === true };
  }
  throw new Error(
    `CONTROL step #${index} must be a boolean or { progress:boolean, converged?:boolean } (got ${JSON.stringify(raw)})`,
  );
}

// ---------------------------------------------------------------------------
// The CONTROL state machine.
// ---------------------------------------------------------------------------

function isLedgerLike(l) {
  return l && typeof l.assert === 'function' && typeof l.has === 'function' && typeof l.rungOf === 'function' && typeof l.beliefOf === 'function';
}

/**
 * The metacognitive CONTROL state machine. Stateless across runs (the only persistence is the optional
 * injected A1 ledger): each run() is independent. It drives a solution attempt over a progress-boolean
 * stream under the pinned S1 thresholds and exits ABANDONED (gap-function or budget-exhausted) or
 * HANDOFF (converged) — NEVER settling the claim's rung.
 */
export class ControlMachine {
  #ledger;
  #thresholds;

  /**
   * @param {{ledger?:object, thresholds?:object}} [o] — optional A1 ledger to bind the claim CONTROL
   *   drives (so the run can prove the claim is left UNVERIFIED); thresholds default to the pinned S1
   *   constants (overridable only for focused unit tests).
   */
  constructor({ ledger = null, thresholds = CONTROL_THRESHOLDS } = {}) {
    if (ledger !== null && !isLedgerLike(ledger)) {
      throw new Error('ControlMachine ledger (when given) must be an A1 ClaimLedger ({assert, has, rungOf, beliefOf})');
    }
    this.#ledger = ledger;
    this.#thresholds = Object.freeze({ ...CONTROL_THRESHOLDS, ...thresholds });
  }

  /** The bound ledger (if any). */
  get ledger() {
    return this.#ledger;
  }

  /** The pinned S1 thresholds in force. */
  get thresholds() {
    return this.#thresholds;
  }

  /** Bind the claim CONTROL drives into the ledger at the floor rung (UNVERIFIED). Returns its id. */
  #bindClaim(claim) {
    if (!this.#ledger) {
      // No ledger: just resolve an id for the trace; CONTROL still cannot settle anything.
      if (typeof claim === 'string') return claim;
      if (claim && typeof claim === 'object' && typeof claim.id === 'string') return claim.id;
      return null;
    }
    if (typeof claim === 'string') {
      if (!this.#ledger.has(claim)) throw new Error(`run(): claim id "${claim}" is not in the bound ledger`);
      return claim;
    }
    if (!claim || typeof claim !== 'object' || typeof claim.id !== 'string') {
      throw new Error('run(): with a bound ledger, claim must be an id string or a spec { id, type, ... }');
    }
    // Emit at the floor (UNVERIFIED) if new; sticky re-assert if it already exists. Either way: no lift.
    this.#ledger.assert({ id: claim.id, type: claim.type || 'proof-bearing', statement: claim.statement, meta: { driven_by: 'C3-control-machine' } });
    return claim.id;
  }

  /**
   * Run CONTROL over a progress-boolean stream for one solution attempt.
   *
   * @param {string|{id:string, type?:string, statement?:string}} claim — the claim CONTROL drives
   *   (a bound-ledger id, or a spec emitted at the floor when a ledger is bound; a bare object/null is
   *   accepted without a ledger, used only to label the trace).
   * @param {Array<boolean|{progress:boolean, converged?:boolean}>} stream — one entry per attempted step.
   * @returns {object} a frozen CONTROL result (see #assemble): final state + reason, the step it exited
   *   on, the per-step trace, and the claim's held rung/belief (UNVERIFIED/CONJECTURAL).
   */
  run(claim, stream) {
    if (!Array.isArray(stream)) {
      throw new Error('run(): the progress stream must be an array of booleans / { progress } steps');
    }
    const claim_id = this.#bindClaim(claim);
    const { BUDGET, ABANDON_SWITCHES } = this.#thresholds;

    const trace = [];
    let window = []; // progress-booleans since the last switch, capped at SWITCH_WINDOW.
    let consecutiveSwitches = 0;
    let switches = 0;
    let state = CONTROL_STATE.RUNNING;
    let reason = null;
    let exitStep = 0;

    for (let i = 0; i < stream.length; i++) {
      const step = i + 1;
      // Budget is a HARD ceiling: never execute beyond BUDGET steps.
      if (step > BUDGET) break;

      const { progress, converged } = normalizeStep(stream[i], i);
      window.push(progress);
      if (window.length > this.#thresholds.SWITCH_WINDOW) window.shift();

      let transition = CONTROL_TRANSITION.CONTINUE;

      if (converged) {
        // The attempt reached a candidate: terminal HANDOFF to the VERIFY router (never a settle).
        state = CONTROL_STATE.HANDOFF;
        transition = CONTROL_TRANSITION.CONVERGE;
        exitStep = step;
        trace.push(Object.freeze({ step, progress, transition, consecutiveSwitches, window: Object.freeze([...window]) }));
        break;
      }

      if (progress) {
        // Real progress breaks the consecutive-switch streak (one switch + recovery never abandons).
        consecutiveSwitches = 0;
      } else if (gapFunction(window, this.#thresholds)) {
        // GAP-FUNCTION: no progress in the last m steps — switch strategy (and reset the window so the
        // new strategy is graded on its own fresh m steps).
        switches += 1;
        consecutiveSwitches += 1;
        window = [];
        transition = CONTROL_TRANSITION.SWITCH;
        if (consecutiveSwitches >= ABANDON_SWITCHES) {
          // ABANDON_SWITCHES consecutive switches => ABANDON via the gap-function (the S1 early exit).
          state = CONTROL_STATE.ABANDONED;
          reason = ABANDON_REASON.GAP_FUNCTION;
          transition = CONTROL_TRANSITION.ABANDON;
          exitStep = step;
          trace.push(Object.freeze({ step, progress, transition, consecutiveSwitches, window: Object.freeze([]) }));
          break;
        }
      }

      trace.push(Object.freeze({ step, progress, transition, consecutiveSwitches, window: Object.freeze([...window]) }));
      exitStep = step;

      // Budget reached with no convergence and no gap-function ABANDON => budget-exhausted ABANDON.
      if (step >= BUDGET) {
        state = CONTROL_STATE.ABANDONED;
        reason = ABANDON_REASON.BUDGET_EXHAUSTED;
        // Rewrite the final trace entry's transition to the terminal ABANDON for an honest trace.
        trace[trace.length - 1] = Object.freeze({ ...trace[trace.length - 1], transition: CONTROL_TRANSITION.ABANDON });
        break;
      }
    }

    // Stream ran dry before any terminal exit: the attempt simply ran out of supplied steps without
    // converging or abandoning. Treat an unresolved run as a budget-style ABANDON (no progress lift),
    // reason = budget-exhausted ONLY if it reached the budget; otherwise it is an incomplete attempt
    // that still never settled. We mark it ABANDONED/budget-exhausted-style as "ran out of steps".
    if (state === CONTROL_STATE.RUNNING) {
      state = CONTROL_STATE.ABANDONED;
      reason = ABANDON_REASON.BUDGET_EXHAUSTED;
    }

    return this.#assemble(claim_id, state, reason, exitStep, switches, trace);
  }

  #assemble(claim_id, state, reason, exitStep, switches, trace) {
    const { BUDGET } = this.#thresholds;

    // The claim CONTROL drove is ALWAYS left UNVERIFIED/CONJECTURAL — CONTROL never settles.
    let claim_rung = RUNG.UNVERIFIED;
    let claim_belief = BELIEF.CONJECTURAL;
    if (this.#ledger && claim_id && this.#ledger.has(claim_id)) {
      claim_rung = this.#ledger.rungOf(claim_id);
      claim_belief = this.#ledger.beliefOf(claim_id);
    }

    const abandoned = state === CONTROL_STATE.ABANDONED;
    return Object.freeze({
      claim_id,
      state,
      reason, // null unless ABANDONED
      exitStep, // the step number the machine exited on
      switches,
      thresholds: this.#thresholds,
      trace: Object.freeze(trace),
      claim_rung,
      claim_belief,
      // THE DONE-WHEN invariants:
      // 1. If abandoned via the gap-function, it exited STRICTLY BEFORE the budget (not budget-exhausted).
      abandonedByGapFunction: abandoned && reason === ABANDON_REASON.GAP_FUNCTION,
      beforeBudget: exitStep < BUDGET,
      // 2. The claim is left UNVERIFIED/CONJECTURAL — CONTROL settles nothing.
      claimLeftUnverified: claim_rung === RUNG.UNVERIFIED && claim_belief === BELIEF.CONJECTURAL,
    });
  }
}

/** Convenience: run CONTROL over a stream in one call. Returns the frozen control result. */
export function runControl(claim, stream, { ledger = null, thresholds = CONTROL_THRESHOLDS } = {}) {
  return new ControlMachine({ ledger, thresholds }).run(claim, stream);
}

// ---------------------------------------------------------------------------
// THE PINNED FIXTURES — canned progress-boolean streams that grade the control logic deterministically.
// ---------------------------------------------------------------------------

/**
 * THE PINNED NON-CONVERGING FIXTURE (the done-when's fixture). A stream that NEVER makes progress. The
 * length is the full budget (8 no-progress steps) so the budget COULD be the exit — but the gap-function
 * fires first, ABANDONing at step 6 (strictly before step 8) with reason=gap-function. This is the
 * fixture S1 pins: ABANDON via the gap-function strictly before the budget, claim left UNVERIFIED.
 */
export const NON_CONVERGING_FIXTURE = Object.freeze([false, false, false, false, false, false, false, false]);

/**
 * A CONVERGING fixture — the attempt makes progress and reaches a candidate, exiting HANDOFF (handed to
 * the VERIFY router). CONTROL still settles nothing: the claim is left UNVERIFIED.
 */
export const CONVERGING_FIXTURE = Object.freeze([true, true, { progress: true, converged: true }]);

/**
 * A BUDGET-EXHAUSTED fixture — sporadic progress that never lets 2 switches go CONSECUTIVE (a single
 * switch is always followed by real progress that resets the streak) and never converges, so the
 * machine runs the full budget and ABANDONs with reason=budget-exhausted (NOT gap-function). This
 * proves the two ABANDON reasons are distinct and that one switch + recovery never abandons by gap.
 */
export const BUDGET_EXHAUSTED_FIXTURE = Object.freeze([false, false, false, true, false, false, true, false]);

/** Run CONTROL over the pinned NON_CONVERGING_FIXTURE end-to-end (binds a fresh claim in a fresh ledger). */
export function runNonConvergingFixture({ ledger = new ClaimLedger() } = {}) {
  return new ControlMachine({ ledger }).run(
    { id: 'c3::non-converging-attempt', type: 'proof-bearing', statement: 'a solution attempt that never makes progress (the pinned non-converging fixture)' },
    NON_CONVERGING_FIXTURE,
  );
}

// A note for readers verifying the floor: FLOOR_RUNG is UNVERIFIED, so a claim bound by CONTROL enters
// at UNVERIFIED and — since CONTROL never promotes — is left there on every exit.
void FLOOR_RUNG;
