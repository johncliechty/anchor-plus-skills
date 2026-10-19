// judge.mjs — Crucible's model-side DECIDER of convergence (Wave 3).
//
// The Judge is the model-side decider (the human is the final authority; the
// Synthesizer DIRECTS but never decides — see bin/synthesizer.mjs). It runs as a
// FRESH, CONTEXT-FREE sub-agent with ALL the evidence placed in its prompt — the
// round's surviving findings, the North Star, the per-wave acceptance criteria,
// and (when present) the fresh-eyes cold pass. It never reads the anchored
// Synthesizer's direction log, so it cannot inherit the Director's position.
//
// Two modes (MASTER-PLAN §10):
//   - Default (subscription-only): a SAME-MODEL judge persona run as a fresh,
//     context-free sub-agent through the Wave-1 `agent` seam.
//   - Enhanced (a different model family is reachable): a CROSS-MODEL judge — the
//     strongest model from a family OTHER than the plan's author. Wave 3 builds the
//     selection + the per-role STAMP and routes both paths through the injected
//     `agent` seam; Wave 9 binds the real cross-model CLIs to the probe.
//
// Either way the run STAMPS which model filled the Judge role, so a plan's
// provenance shows exactly how much cross-model independence it actually got.

import { HaltError } from './crucible-lib.mjs';
import { makeReliableAgent } from '../../drivers/reliability.mjs';

export const JUDGE_ROLE = 'Judge';

// ---------------------------------------------------------------------------
// Per-role model stamp (shared by the Judge and the Synthesizer).
// ---------------------------------------------------------------------------

/**
 * The provenance stamp for one role: which model/family filled it, under which
 * substrate mode, and whether that was genuine cross-model independence. Both the
 * Judge and the Synthesizer stamp themselves with this so every run records who
 * filled which role (MASTER-PLAN §10 "stamp which model filled which role").
 *
 * @param {object} o
 * @param {string}  o.role                  e.g. 'Judge' | 'Synthesizer'
 * @param {string} [o.model='claude']       the concrete model that ran the role
 * @param {string} [o.family='claude']      its model family
 * @param {string} [o.mode='default']       'default' | 'enhanced'
 * @param {boolean}[o.reachable=false]      was a different-family model reachable?
 * @returns {{role:string,model:string,family:string,mode:string,cross_model:boolean}}
 */
export function stampRole({ role, model = 'claude', family = 'claude', mode = 'default', reachable = false } = {}) {
  if (!role) {
    throw new HaltError('stampRole requires a role', 'pass { role: "Judge" | "Synthesizer" | ... }');
  }
  return {
    role,
    model,
    family,
    mode,
    // Genuine cross-model independence only when Enhanced mode actually reached a
    // different family — Default mode (same-model persona) is never cross-model.
    cross_model: mode === 'enhanced' && !!reachable,
  };
}

// ---------------------------------------------------------------------------
// Judge-model selection (Default vs Enhanced).
//
// Wave 3 establishes the contract + stamp; the probe is INJECTABLE so Wave 9 can
// bind the real Gemini/GPT/Grok CLIs. The default probe returns null => Default
// mode, exactly like Foreman on the bare subscription.
// ---------------------------------------------------------------------------

/** Default capability probe: nothing reachable ⇒ Default (same-model) mode. */
export function defaultProbeCrossModel() {
  return null;
}

/**
 * Pick the Judge's model. Enhanced when the probe surfaces a model from a family
 * OTHER than the plan's author (the highest-leverage place to break same-family
 * self-preference); otherwise the same-model judge persona (Default mode).
 *
 * @param {object} o
 * @param {string}   [o.authorFamily='claude']            the family that AUTHORED the plan
 * @param {Function} [o.probe=defaultProbeCrossModel]     ()=> ({model,family}) | null
 * @returns {{model:string,family:string,mode:string,reachable:boolean}}
 */
export function selectJudgeModel({ authorFamily = 'claude', probe = defaultProbeCrossModel } = {}) {
  const reachable = typeof probe === 'function' ? probe() : null;
  if (reachable && reachable.family && reachable.family !== authorFamily) {
    // Enhanced: a genuinely different family decides at the lock gate.
    return { model: reachable.model || reachable.family, family: reachable.family, mode: 'enhanced', reachable: true };
  }
  // Default: a same-model judge persona, run fresh + context-free.
  return { model: authorFamily, family: authorFamily, mode: 'default', reachable: false };
}

/**
 * T7 (2026-07-11): derive the Judge's selection from the run's ROLE ROUTES — the
 * ground truth of where the judge role's calls actually dispatch. When a role-routed
 * agent sends `role:'judge'` to a non-author family (the DEFAULT_CRUCIBLE_ROUTES
 * shape: judge → gemini-cli), the stamp is honestly `enhanced`/cross_model — the old
 * default probe returned null and UNDERSTATED a genuinely cross-family run as a
 * same-model persona (and the observed live pathology was the inverse: the default
 * Claude substrate judging its own family's plan across 4 held dry rounds).
 *
 * @param {object} o
 * @param {?object} [o.routes=null]         role → { driver, model } (judge ?? default)
 * @param {string}  [o.authorFamily='claude']
 * @returns {{model:string,family:string,mode:string,reachable:boolean}}
 */
export function selectJudgeFromRoutes({ routes = null, authorFamily = 'claude' } = {}) {
  const r = routes && (routes.judge ?? routes.default);
  const drv = r && r.driver ? String(r.driver).trim().toLowerCase() : null;
  const family = !drv ? null
    : drv.startsWith('gemini') ? 'gemini'
    : drv.startsWith('claude') ? 'claude'
    : drv.split(/[-\s]/)[0] || null;
  if (family && family !== authorFamily) {
    return { model: (r.model || r.driver), family, mode: 'enhanced', reachable: true };
  }
  return { model: authorFamily, family: authorFamily, mode: 'default', reachable: false };
}

// ---------------------------------------------------------------------------
// The Judge's decision schema + its context-free prompt.
// ---------------------------------------------------------------------------

/** The Judge's reply: a binding verdict (it DECIDES — this is not advisory). */
export const JUDGE_SCHEMA = {
  type: 'object',
  required: ['decision'],
  properties: {
    decision: { enum: ['CONVERGED', 'NOT_CONVERGED', 'CHALLENGE'] },
    reasons: { type: 'array', items: { type: 'string' } },
    blocking: {
      type: 'array',
      items: {
        type: 'object',
        properties: { id: { type: 'string' }, severity: { type: 'string' }, note: { type: 'string' } },
      },
    },
  },
};

function judgePrompt({ northStar, findings, acceptanceCriteria, freshEyes }) {
  return [
    `You are the JUDGE — the model-side DECIDER of convergence — running in a FRESH,`,
    `CONTEXT-FREE sub-agent. You have NO prior context: no memory of any prior round and`,
    `no access to any Director's direction log. Decide ONLY from the evidence below.`,
    ``,
    `=== THE NORTH STAR (verbatim) ===`,
    String(northStar ?? '(none provided)'),
    `=== END NORTH STAR ===`,
    ``,
    `=== SURVIVING FINDINGS (the round's tallied, non-demoted findings) ===`,
    findings.length
      ? findings.map((f, i) => `(${i + 1}) [${f.severity || '?'}] ${f.message || f.id || JSON.stringify(f)}`).join('\n')
      : '(none — the round is clean)',
    `=== END FINDINGS ===`,
    ``,
    `=== PER-WAVE ACCEPTANCE CRITERIA ===`,
    acceptanceCriteria.length ? acceptanceCriteria.map((c, i) => `(${i + 1}) ${c}`).join('\n') : '(none provided)',
    `=== END ACCEPTANCE CRITERIA ===`,
    freshEyes
      ? `\n=== FRESH-EYES COLD PASS ===\nlean=${freshEyes.lean}; ${freshEyes.note || ''}\n=== END FRESH-EYES ===\n`
      : '',
    ``,
    `DECIDE:`,
    `  - CONVERGED only if there is NO open BLOCKER/MAJOR, the round is dry, and the`,
    `    fresh-eyes pass raises no material divergence.`,
    `  - CHALLENGE if the fresh-eyes pass materially diverges and one more adversarial`,
    `    round is warranted before any lock.`,
    `  - otherwise NOT_CONVERGED.`,
  ].join('\n');
}

// ---------------------------------------------------------------------------
// The Judge.
// ---------------------------------------------------------------------------

/**
 * Build the Judge from the injected Wave-1 `agent` seam. The Judge holds NO
 * reference to the Synthesizer — its only inputs are the evidence handed to
 * `decide()`, keeping it genuinely context-free.
 *
 * @param {object} o
 * @param {Function}  o.agent                                the Wave-1 agent seam
 * @param {string}   [o.authorFamily='claude']               family that authored the plan
 * @param {Function} [o.probeCrossModel=defaultProbeCrossModel]
 * @param {Function} [o.log=()=>{}]
 */
export function makeJudge({ agent, authorFamily = 'claude', probeCrossModel = defaultProbeCrossModel, routes = null, log = () => {} } = {}) {
  if (typeof agent !== 'function') {
    throw new HaltError(
      'makeJudge requires an agent() function',
      'pass the Wave-1 seam: makeJudge({ agent: makeAgentSeam(...).agent })',
    );
  }
  // Wave 1: the injected seam is reliability-wrapped HERE, at its injection point,
  // so the Judge's adjudication call inherits typed retry + round-aware idempotency.
  // Transparent on the success path (one inner call, opts unchanged).
  const reliableAgent = makeReliableAgent({ agent });
  // T7: routes (where the judge role ACTUALLY dispatches) beat the probe when supplied.
  const selection = routes
    ? selectJudgeFromRoutes({ routes, authorFamily })
    : selectJudgeModel({ authorFamily, probe: probeCrossModel });
  const stamp = stampRole({ role: JUDGE_ROLE, model: selection.model, family: selection.family, mode: selection.mode, reachable: selection.reachable });

  return {
    selection,
    stamp,

    /**
     * DECIDE convergence from the injected evidence (and nothing else). Returns a
     * binding verdict carrying the model stamp. An abstain/unparseable judge reply
     * cannot silently pass — the Judge synthesizes a HALT for human review instead.
     *
     * @param {object} o
     * @param {string}   o.northStar
     * @param {object[]}[o.findings=[]]             the round's surviving (non-demoted) findings
     * @param {string[]}[o.acceptanceCriteria=[]]   the per-wave oracle
     * @param {?object} [o.freshEyes=null]          the fresh-eyes cold-pass assessment
     * @param {number}  [o.round=0]
     */
    async decide({ northStar, findings = [], acceptanceCriteria = [], freshEyes = null, round = 0 } = {}) {
      const prompt = judgePrompt({ northStar, findings, acceptanceCriteria, freshEyes });
      const out = await reliableAgent(prompt, { label: `judge:r${round}:${selection.model}`, schema: JUDGE_SCHEMA, role: 'judge', round });

      // The Judge MUST decide. An abstain (answerable:no) or a reply without a
      // decision cannot be read as a silent pass — escalate to the human.
      const decision = out?.decision;
      if (!decision || out?.answerable === 'no') {
        log(`judge r${round}: no decision from the sub-agent — HALT for human review`);
        return {
          decision: 'HALT',
          lockable: false,
          halted: true,
          reasons: ['judge sub-agent could not produce a decision after retry — HALT for human review'],
          blocking: [],
          stamp,
          promptSent: prompt,
        };
      }

      const verdict = {
        decision,
        lockable: decision === 'CONVERGED',
        reasons: Array.isArray(out.reasons) ? out.reasons : [],
        blocking: Array.isArray(out.blocking) ? out.blocking : [],
        stamp,
        promptSent: prompt,
      };
      log(`judge r${round}: ${decision} (${stamp.cross_model ? `cross-model: ${stamp.model}` : `same-model persona: ${stamp.model}`})`);
      return verdict;
    },
  };
}
