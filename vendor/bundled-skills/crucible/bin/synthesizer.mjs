// synthesizer.mjs — Crucible's persistent Deep-Think DIRECTOR (Wave 3).
//
// The Synthesizer is a reasoning model in a dedicated, persistent role, SEPARATE
// from the Sharks (MASTER-PLAN §7). It STEERS the refinement; it does NOT decide.
//   - Persistence (simplified): it carries the LAST ROUND VERBATIM plus a short
//     running DIRECTION LOG (open disputes · risk register · probing brief).
//   - Oranges suggesting: after each round it proactively suggests what's missing
//     or needed two steps downstream (the "two steps ahead" ethos).
//   - Director ≠ decider: the decider of convergence is the Judge (bin/judge.mjs)
//     + the user. This object has NO decide/lock/converge/reconcile method — by
//     construction it cannot grade its own homework.
//   - Anti-anchoring: ONE fresh-eyes COLD PASS before each lock — a *new*, no-
//     context Synthesizer instance reads the transcripts cold. Material divergence
//     is routed to the Judge / a challenge round (`reconcileFreshEyes`), NEVER
//     reconciled by the anchored Director.
//
// Every Synthesizer prompt embeds the current North Star verbatim (the §9 anti-
// drift rule), and the role carries a per-role model STAMP (reused from judge.mjs).

import { HaltError } from './crucible-lib.mjs';
import { stampRole } from './judge.mjs';
import { makeReliableAgent } from '../../drivers/reliability.mjs';

export const SYNTHESIZER_ROLE = 'Synthesizer';

// A process-local sequence so every constructed instance has a unique id — the
// fresh-eyes COLD PASS must be a demonstrably DIFFERENT instance from the Director.
let SYNTH_SEQ = 0;

// ---------------------------------------------------------------------------
// Schemas — the Director's direction and the fresh-eyes cold-pass assessment.
// ---------------------------------------------------------------------------

/** One round of direction from the Director (advisory — it steers, never decides). */
export const DIRECTION_SCHEMA = {
  type: 'object',
  required: ['lean'],
  properties: {
    lean: { enum: ['lockable', 'not-lockable', 'unknown'] },
    openDisputes: { type: 'array', items: { type: 'string' } },
    riskRegister: { type: 'array', items: { type: 'string' } },
    probingBrief: { type: 'string' },
    // Oranges suggesting: what's missing / needed two steps downstream.
    suggestions: { type: 'array', items: { type: 'string' } },
  },
};

/** The fresh-eyes cold pass's INDEPENDENT assessment (no prior context). */
export const FRESH_EYES_SCHEMA = {
  type: 'object',
  required: ['lean'],
  properties: {
    lean: { enum: ['lockable', 'not-lockable', 'unknown'] },
    concerns: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { enum: ['BLOCKER', 'MAJOR', 'MINOR', 'NIT'] },
          // P1 2026-07-25 (journal 0011 item 4): a BLOCKER concern holds the lock
          // ONLY when accountable — it must name the North-Star criterion it blocks
          // (criterion) or share a topic with a Shark finding (corroboration). A
          // bare-vibe BLOCKER is advisory for the Judge and the human, not a veto.
          criterion: { type: 'string' },
          topic: { type: 'string' },
          note: { type: 'string' },
        },
      },
    },
    note: { type: 'string' },
  },
};

// ---------------------------------------------------------------------------
// Prompts — every one embeds the North Star verbatim (§9).
// ---------------------------------------------------------------------------

function directionPrompt({ northStar, lastRound, journal, research }) {
  return [
    `You are the Crucible SYNTHESIZER — a persistent Deep-Think DIRECTOR. You STEER the`,
    `refinement; you DO NOT decide convergence (the Judge + the user decide that). Read`,
    `the LAST ROUND verbatim and your running direction log, then issue direction for the`,
    `next round and — in the Oranges spirit — proactively SUGGEST what is missing or`,
    `needed two steps downstream. Reason by EVIDENCE QUALITY, not which side is louder.`,
    ``,
    `=== THE NORTH STAR (verbatim) ===`,
    String(northStar ?? '(none yet)'),
    `=== END NORTH STAR ===`,
    ``,
    `=== LAST ROUND (verbatim) ===`,
    JSON.stringify(lastRound ?? null, null, 2),
    `=== END LAST ROUND ===`,
    ``,
    `=== YOUR RUNNING DIRECTION LOG (${journal.length} prior entr${journal.length === 1 ? 'y' : 'ies'}) ===`,
    journal.length
      ? journal.map((e, i) => `#${i + 1} r${e.round} lean=${e.lean} disputes=[${(e.openDisputes || []).join('; ')}]`).join('\n')
      : '(empty — this is the first direction)',
    `=== END DIRECTION LOG ===`,
    research ? `\n=== FRESH RESEARCH INPUT ===\n${typeof research === 'string' ? research : JSON.stringify(research)}\n=== END RESEARCH ===` : '',
    ``,
    `Emit: lean (lockable|not-lockable|unknown), openDisputes, riskRegister, probingBrief`,
    `(what the next round must press hardest on), suggestions (Oranges: what's missing /`,
    `needed two steps ahead).`,
  ].join('\n');
}

function freshEyesPrompt({ northStar, transcripts }) {
  return [
    `You are a FRESH-EYES Synthesizer instance with NO prior context: you have never seen`,
    `this project before and hold NO position. Read the round transcript(s) COLD and form`,
    `an INDEPENDENT assessment — do not try to agree with anyone. If you see a lock-blocking`,
    `problem, say so plainly.`,
    ``,
    `=== THE NORTH STAR (verbatim) ===`,
    String(northStar ?? '(none)'),
    `=== END NORTH STAR ===`,
    ``,
    `=== ROUND TRANSCRIPT(S) (the ONLY context you are given) ===`,
    typeof transcripts === 'string' ? transcripts : JSON.stringify(transcripts, null, 2),
    `=== END TRANSCRIPTS ===`,
    ``,
    `Emit: lean (lockable|not-lockable|unknown), concerns [{severity, criterion, topic, note}], note.`,
    `For a BLOCKER concern: criterion MUST name the North-Star criterion it blocks (verbatim`,
    `or by number) and topic MUST be a short stable slug for the issue — a BLOCKER that names`,
    `no criterion and matches no Shark finding is recorded as ADVISORY, not a lock-veto.`,
  ].join('\n');
}

// ---------------------------------------------------------------------------
// The Synthesizer (the Director).
// ---------------------------------------------------------------------------

/**
 * Build the persistent Director. It holds the last round verbatim + a running
 * direction log and issues advisory direction. It deliberately exposes NO
 * decision authority (no decide/lock/converge/reconcile) — Director ≠ decider.
 *
 * @param {object} o
 * @param {Function}  o.agent                  the Wave-1 agent seam
 * @param {?string}  [o.northStar=null]        embedded verbatim in every prompt (§9)
 * @param {string}   [o.model='claude']        the reasoning model filling the role
 * @param {string}   [o.family='claude']
 * @param {string}   [o.mode='default']        'default' | 'enhanced'
 * @param {Function} [o.log=()=>{}]
 */
export function makeSynthesizer({ agent, northStar = null, model = 'claude', family = 'claude', mode = 'default', log = () => {} } = {}) {
  if (typeof agent !== 'function') {
    throw new HaltError(
      'makeSynthesizer requires an agent() function',
      'pass the Wave-1 seam: makeSynthesizer({ agent: makeAgentSeam(...).agent })',
    );
  }

  const instanceId = `synthesizer#${++SYNTH_SEQ}`;
  const stamp = stampRole({ role: SYNTHESIZER_ROLE, model, family, mode });

  // Wave 1: reliability-wrap the injected seam at its injection point, so the
  // Director's steering call gets typed retry + round-aware idempotency.
  // Transparent on the success path (one inner call, opts unchanged).
  const reliableAgent = makeReliableAgent({ agent });

  // Persistent state (simplified persistence per §7).
  const journal = []; // the running direction log
  let lastRound = null; // the last round, stored VERBATIM

  /** The Director's currently-held position, synthesized from the direction log. */
  function position() {
    const last = journal[journal.length - 1];
    if (!last) return { lean: 'unknown', openDisputes: [], summary: 'no direction issued yet' };
    // Accumulate every open dispute raised across the log (the running register).
    const openDisputes = [...new Set(journal.flatMap((e) => e.openDisputes || []))];
    return { lean: last.lean, openDisputes, summary: last.probingBrief || '' };
  }

  return {
    role: SYNTHESIZER_ROLE,
    instanceId,
    stamp,
    // Director ≠ decider — explicit, and asserted by the gate test.
    isDecider: false,

    position,

    /** A snapshot of the persistent state (for the fresh-eyes isolation oracle). */
    snapshot() {
      return { instanceId, journal: journal.map((e) => ({ ...e })), lastRound, position: position() };
    },

    /**
     * Read the just-completed round, store it VERBATIM, append a direction-log
     * entry, and return ADVISORY direction (Oranges suggesting included). This is
     * steering only — `advisory:true, decides:false` is part of the contract.
     *
     * @param {object} o
     * @param {number}  [o.round=0]
     * @param {object}   o.verdict             the Shark-Tank round verdict (stored verbatim)
     * @param {?string} [o.northStar]          overrides the instance North Star for this call
     * @param {?(string|object)} [o.research=null]
     */
    async direct({ round = 0, verdict, northStar: ns = null, research = null } = {}) {
      lastRound = { round, verdict }; // LAST ROUND VERBATIM
      const star = ns ?? northStar;
      const out = await reliableAgent(directionPrompt({ northStar: star, lastRound, journal, research }), {
        label: `synthesizer:direct:r${round}`,
        schema: DIRECTION_SCHEMA,
        role: 'synthesizer',
        round,
      });
      const entry = {
        round,
        lean: out?.lean ?? 'unknown',
        openDisputes: Array.isArray(out?.openDisputes) ? out.openDisputes : [],
        riskRegister: Array.isArray(out?.riskRegister) ? out.riskRegister : [],
        probingBrief: out?.probingBrief ?? '',
        suggestions: Array.isArray(out?.suggestions) ? out.suggestions : [],
      };
      journal.push(entry);
      log(`synthesizer direction r${round}: lean=${entry.lean}, ${entry.openDisputes.length} dispute(s), ${entry.suggestions.length} suggestion(s)`);
      // Advisory by contract — the Director steers, the Judge + user decide.
      return { ...entry, kind: 'direction', advisory: true, decides: false, stamp };
    },
  };
}

// ---------------------------------------------------------------------------
// The fresh-eyes COLD PASS — a NEW, no-context instance.
//
// Deliberately a free function (NOT a method on the Director): the anchored
// Director must never run or reconcile its own anti-anchoring pass. It spins up a
// brand-new Synthesizer with an EMPTY journal and feeds it ONLY the transcripts —
// none of the Director's direction log — so the assessment is genuinely cold.
// ---------------------------------------------------------------------------

/**
 * Run the fresh-eyes cold pass. Returns the cold instance's id, its journal AT THE
 * MOMENT IT READ (which MUST be empty — the isolation invariant), the exact prompt
 * it was given (so the oracle can prove no Director context leaked in), and its
 * independent assessment.
 *
 * @param {object} o
 * @param {Function}        o.agent
 * @param {string|object}   o.transcripts          the round transcript(s) — the only context
 * @param {?string}        [o.northStar=null]
 * @param {string}         [o.model='claude']
 * @param {string}         [o.family='claude']
 * @param {string}         [o.mode='default']
 * @param {Function}       [o.log=()=>{}]
 */
export async function freshEyesColdPass({ agent, transcripts, northStar = null, model = 'claude', family = 'claude', mode = 'default', log = () => {} } = {}) {
  // A NEW Synthesizer with an empty journal — never the anchored Director.
  const cold = makeSynthesizer({ agent, northStar, model, family, mode, log });
  const journalAtStart = cold.snapshot().journal; // MUST be [] — the isolation invariant
  const promptSent = freshEyesPrompt({ northStar, transcripts });
  // Wave 1: the cold pass's own injected call is reliability-wrapped here too.
  const reliableAgent = makeReliableAgent({ agent });
  const out = await reliableAgent(promptSent, { label: `synthesizer:fresh-eyes:${cold.instanceId}`, schema: FRESH_EYES_SCHEMA, role: 'synthesizer' });
  const assessment = {
    lean: out?.lean ?? 'unknown',
    concerns: Array.isArray(out?.concerns) ? out.concerns : [],
    note: out?.note ?? '',
  };
  log(`fresh-eyes cold pass ${cold.instanceId}: lean=${assessment.lean}, ${assessment.concerns.length} concern(s)`);
  return { instanceId: cold.instanceId, journalAtStart, promptSent, assessment, stamp: cold.stamp };
}

/**
 * Isolation oracle: prove the fresh-eyes cold pass received NO prior context.
 * Confirms (1) the cold instance's journal was empty when it read, (2) it was a
 * DIFFERENT instance from the Director, and (3) none of the Director's direction-
 * log text leaked into the cold prompt.
 *
 * @param {object} o
 * @param {object}  o.cold                 the freshEyesColdPass result
 * @param {?object}[o.directorSnapshot]    the Director's snapshot() (for leak/identity checks)
 * @returns {{isolated:boolean, violations:string[], leaked:string[]}}
 */
export function freshEyesIsolationOracle({ cold, directorSnapshot = null }) {
  const violations = [];
  if (!cold) {
    return { isolated: false, violations: ['no cold-pass result to inspect'], leaked: [] };
  }
  if ((cold.journalAtStart?.length ?? -1) !== 0) {
    violations.push(`cold instance journal was not empty (len=${cold.journalAtStart?.length}) — it carried prior context`);
  }
  if (directorSnapshot && cold.instanceId === directorSnapshot.instanceId) {
    violations.push('cold pass reused the Director instance instead of a fresh, no-context one');
  }
  // Leak check: no Director direction-log text may appear in the cold prompt.
  const prompt = cold.promptSent || '';
  const leaked = [];
  for (const e of directorSnapshot?.journal || []) {
    const texts = [e.probingBrief, ...(e.openDisputes || []), ...(e.riskRegister || []), ...(e.suggestions || [])];
    for (const t of texts) {
      if (t && String(t).length > 3 && prompt.includes(t)) leaked.push(t);
    }
  }
  if (leaked.length) {
    violations.push(`Director context leaked into the cold prompt: ${leaked.slice(0, 3).join(' | ')}`);
  }
  return { isolated: violations.length === 0, violations, leaked };
}

/**
 * Reconcile the fresh-eyes pass against the Director's position — a FREE function,
 * deliberately not a Director method, so the anchored Director never reconciles
 * its own anti-anchoring pass. Material divergence (the cold pass surfaces a lock-
 * blocking problem the Director did not hold) is SURFACED TO THE JUDGE; a non-
 * material divergence recommends one more challenge round.
 *
 * @param {object} o
 * @param {{lean:string}} o.directorPosition
 * @param {{lean:string, concerns?:object[]}} o.freshEyes
 * @returns {{diverged:boolean, material:boolean, route:'judge'|'challenge-round'|'concur', reason:string}}
 */
export function reconcileFreshEyes({ directorPosition, freshEyes }) {
  const dLean = directorPosition?.lean ?? 'unknown';
  const fLean = freshEyes?.lean ?? 'unknown';
  const diverged = dLean !== fLean;
  const freshBlocker = (freshEyes?.concerns || []).some((c) => ['BLOCKER', 'MAJOR'].includes(String(c?.severity || '').toUpperCase()));
  // Material = the cold pass raises a lock-blocking divergence the Director didn't hold.
  const material = (diverged && fLean === 'not-lockable') || freshBlocker;
  const route = material ? 'judge' : diverged ? 'challenge-round' : 'concur';
  return {
    diverged,
    material,
    route,
    reason: material
      ? 'fresh-eyes cold pass materially diverges — surfaced to the Judge (the decider), never reconciled by the anchored Director'
      : diverged
        ? 'fresh-eyes diverges non-materially — recommend one more challenge round'
        : 'fresh-eyes concurs with the Director',
  };
}
