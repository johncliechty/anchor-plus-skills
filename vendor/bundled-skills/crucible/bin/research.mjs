// research.mjs — Crucible's researchPrime integration (Wave 5).
//
// Wires research into framing + the Shark-Tank rounds, COST-GUARDED so a long
// refinement loop does not re-run a heavyweight 16-step pipeline on every round
// (MASTER-PLAN §5/§7, IMPLEMENTATION-PLAN Wave 5):
//   - ONCE UP-FRONT: a single weakness / best-in-class scan at the start. Calling
//     `upfront()` again is idempotent — it never re-invokes researchPrime.
//   - PER-ROUND ONLY ON A GENUINELY NEW CANDIDATE: `perRound({candidate})` invokes
//     researchPrime only when the candidate is NEW (its normalized identity has not
//     been researched). A repeated/unchanged candidate is SKIPPED — the novelty
//     cost-guard. (Identity reuses Wave-2's `normalizeTopic`, so "same idea, new
//     wording" still counts as not-new.)
//   - TIER-3 DEEP-ARCHAEOLOGY LANE: `deepArchaeology({projectDir})` delegates the
//     brownfield Stage-0 deep dive to a researchPrime lane — Crucible CALLS, it never
//     re-implements the pipeline (MASTER-PLAN §5 Tier 3). Also cost-guarded per dir.
//
// Findings FLOW TO CONSUMERS: the Analyst Shark (persona = researchPrime) and the
// persistent Synthesizer. `forAnalyst()` returns a briefing the Shark-Tank embeds
// into the Analyst's prompt (and only the Analyst's); `forSynthesizer()` returns
// the payload the Synthesizer's `direct({research})` embeds.
//
// REUSE, NOT REINVENT: researchPrime is reached through an INJECTED transport
// (`runResearch`), exactly the seam shape of Wave-1's `agent()` and Wave-4's
// `spawn` — the live binding (researchPrime skill/CLI) is provided by the
// orchestrator / Wave 9; tests inject a stub and drive the full cost-guard logic
// with zero subprocesses.

import { HaltError } from './crucible-lib.mjs';
import { normalizeTopic } from './shark-tank.mjs';

// ---------------------------------------------------------------------------
// Normalized researchPrime result schema (what the transport returns).
// ---------------------------------------------------------------------------

/**
 * One normalized researchPrime run: the run-dir + deliverable pointers (provenance)
 * and the findings, each carrying a confidence label in researchPrime's own
 * vocabulary so the Analyst/Synthesizer can weigh evidence quality, not volume.
 */
export const RESEARCH_SCHEMA = {
  type: 'object',
  required: ['findings'],
  properties: {
    runDir: { type: ['string', 'null'] },
    deliverable: { type: ['string', 'null'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          claim: { type: 'string' },
          confidence: { enum: ['OBSERVED', 'CORROBORATED', 'CLAIMED', 'UNVERIFIED'] },
          source: { type: 'string' },
        },
      },
    },
  },
};

// ---------------------------------------------------------------------------
// The live transport (the seam). Mirrors agent.mjs: env-gated so it can never
// fire by accident, and it CALLS researchPrime (never re-implements it) by running
// the researchPrime lane through the injected `agent` sub-agent seam.
// ---------------------------------------------------------------------------

/** Build the prompt that asks a sub-agent to run the researchPrime lane for `spec`. */
export function researchSpecPrompt(spec) {
  return [
    `You are invoking the researchPrime skill as a research lane for Crucible. RUN`,
    `researchPrime — do NOT re-implement its pipeline — over the brief below and return`,
    `its normalized findings (each with a confidence label + source).`,
    ``,
    `=== RESEARCH BRIEF ===`,
    JSON.stringify(spec, null, 2),
    `=== END BRIEF ===`,
  ].join('\n');
}

/**
 * Default researchPrime transport. There is no standalone researchPrime CLI to spawn,
 * so the live path CALLS researchPrime through the injected `agent` seam — and only
 * when explicitly enabled (CRUCIBLE_RESEARCH_LIVE=1), exactly like agent.mjs's
 * env-gated live seam. Otherwise it HALTs telling you to inject a `runResearch`
 * transport (tests/orchestrator).
 *
 * @param {object}   spec                        the research brief
 * @param {object}  [o]
 * @param {?Function}[o.agent=null]              the Wave-1 agent seam (the live carrier)
 * @param {object}  [o.env=process.env]
 * @param {Function}[o.log=()=>{}]
 */
export function defaultRunResearch(spec, { agent = null, env = process.env, log = () => {} } = {}) {
  if (env.CRUCIBLE_RESEARCH_LIVE !== '1' || typeof agent !== 'function') {
    throw new HaltError(
      'live researchPrime seam is not bound',
      'inject a runResearch transport — makeResearch({ runResearch }) — or pass an agent seam and set ' +
        'CRUCIBLE_RESEARCH_LIVE=1 so Crucible can CALL researchPrime as a sub-agent lane (it never re-implements the pipeline)',
    );
  }
  log(`research: invoking researchPrime lane (mode=${spec.mode}) via the agent seam`);
  return agent(researchSpecPrompt(spec), { label: `research:${spec.mode}`, schema: RESEARCH_SCHEMA });
}

// ---------------------------------------------------------------------------
// Finding formatting for the two consumers.
// ---------------------------------------------------------------------------

/** A compact, evidence-quality-first rendering of findings (confidence + source). */
export function summarizeFindings(findings) {
  if (!findings.length) return '(no research findings)';
  return findings
    .map((f, i) => {
      const conf = f.confidence ? `[${f.confidence}] ` : '';
      const src = f.source ? ` (src: ${f.source})` : '';
      return `(${i + 1}) ${conf}${f.claim || f.id || JSON.stringify(f)}${src}`;
    })
    .join('\n');
}

// ---------------------------------------------------------------------------
// The research coordinator.
// ---------------------------------------------------------------------------

/**
 * Build the cost-guarded researchPrime coordinator.
 *
 * @param {object}   [o]
 * @param {?Function}[o.runResearch=null]  injected transport `(spec)=>Promise<result>`
 *                                         (omit to use the env-gated live default)
 * @param {?Function}[o.agent=null]        the Wave-1 agent seam — only used by the live default
 * @param {object}  [o.env=process.env]
 * @param {Function}[o.log=()=>{}]
 */
export function makeResearch({ runResearch = null, agent = null, env = process.env, log = () => {} } = {}) {
  const run = runResearch || ((spec) => defaultRunResearch(spec, { agent, env, log }));

  const seen = new Set(); // normalized candidate keys already researched (the cost guard)
  const allFindings = []; // every finding gathered, in arrival order (flows to consumers)
  const invocations = []; // an audit trail of each researchPrime call actually made
  let upfrontDone = false;

  /** Canonicalize a candidate (string or object) into a wording-insensitive novelty key. */
  function candidateKey(candidate) {
    const text = typeof candidate === 'string' ? candidate : JSON.stringify(candidate ?? '');
    return normalizeTopic(text);
  }

  /** Actually call researchPrime for `spec`, accumulate its findings, and record it. */
  async function invoke(spec, { kind, round = null }) {
    const result = (await run(spec)) || {};
    const findings = Array.isArray(result.findings) ? result.findings : [];
    allFindings.push(...findings);
    const rec = {
      kind,
      round,
      key: spec.key ?? null,
      findingCount: findings.length,
      runDir: result.runDir ?? null,
      deliverable: result.deliverable ?? null,
    };
    invocations.push(rec);
    log(`research ${kind}${round != null ? ` r${round}` : ''}: ${findings.length} finding(s)`);
    return { invoked: true, ...rec, findings, result };
  }

  return {
    /**
     * researchPrime ONCE up-front (the initial weakness / best-in-class scan).
     * Idempotent: a second call NEVER re-invokes researchPrime.
     *
     * @param {object} o
     * @param {?string}[o.northStar]   the candidate North Star (greenfield)
     * @param {?string}[o.intent]      the raw intent, when no North Star yet
     * @param {string[]}[o.subQuestions=[]]
     */
    async upfront({ northStar = null, intent = null, subQuestions = [] } = {}) {
      if (upfrontDone) {
        log('research upfront: already ran — not re-invoking (idempotent)');
        return { invoked: false, reason: 'upfront-already-done', findings: [] };
      }
      upfrontDone = true;
      const key = candidateKey(northStar ?? intent ?? '');
      if (key) seen.add(key); // the up-front candidate is now "seen" — a per-round repeat is a no-op
      return invoke({ mode: 'upfront', northStar, intent, subQuestions, key }, { kind: 'upfront' });
    },

    /**
     * Per-round research — invoked ONLY when `candidate` is genuinely new (the
     * novelty cost-guard). An unchanged/repeated candidate is SKIPPED (no re-invoke).
     *
     * @param {object} o
     * @param {string|object} o.candidate   the round's current candidate (North Star / draft)
     * @param {number} [o.round=0]
     */
    async perRound({ candidate, round = 0 } = {}) {
      const key = candidateKey(candidate);
      if (!key) {
        log(`research perRound r${round}: empty candidate — SKIP`);
        return { invoked: false, reason: 'empty-candidate', key: '', findings: [] };
      }
      if (seen.has(key)) {
        log(`research perRound r${round}: candidate not new — SKIP (novelty cost-guard)`);
        return { invoked: false, reason: 'no-new-candidate', key, findings: [] };
      }
      seen.add(key);
      return invoke({ mode: 'per-round', candidate, round, key }, { kind: 'per-round', round });
    },

    /**
     * Tier-3 deep-archaeology lane for brownfield Stage 0 — delegate the deep dive
     * to researchPrime (Crucible calls, never re-implements the pipeline). Cost-guarded
     * per project dir so a re-entered Stage 0 does not re-excavate the same tree.
     *
     * @param {object} o
     * @param {string} o.projectDir   the brownfield project under archaeology
     * @param {?number}[o.round=null]
     */
    async deepArchaeology({ projectDir, round = null } = {}) {
      if (!projectDir) {
        throw new HaltError(
          'deepArchaeology requires a projectDir',
          'pass the brownfield project directory to excavate: research.deepArchaeology({ projectDir })',
        );
      }
      const key = `archaeology:${candidateKey(projectDir)}`;
      if (seen.has(key)) {
        log(`research deepArchaeology: ${projectDir} already excavated — SKIP (cost-guard)`);
        return { invoked: false, reason: 'archaeology-already-run', key, findings: [] };
      }
      seen.add(key);
      return invoke({ mode: 'tier3-archaeology', projectDir, round, key }, { kind: 'tier3-archaeology', round });
    },

    /** Every finding gathered so far (a copy). */
    getFindings() {
      return [...allFindings];
    },

    /** The audit trail of researchPrime calls actually made (a copy). */
    getInvocations() {
      return invocations.map((r) => ({ ...r }));
    },

    /**
     * The payload the Synthesizer's `direct({research})` embeds — a structured
     * object so the Director sees the findings + an evidence-quality summary.
     */
    forSynthesizer() {
      return { kind: 'research', findings: this.getFindings(), summary: summarizeFindings(allFindings) };
    },

    /**
     * The briefing the Shark-Tank embeds into the ANALYST Shark's prompt (persona =
     * researchPrime). Returns null when there is nothing to brief, so the round embeds
     * no empty research block.
     */
    forAnalyst() {
      if (!allFindings.length) return null;
      return summarizeFindings(allFindings);
    },
  };
}
