// stage1.mjs — Crucible's Stage 1: the Master Plan protocol (Wave 7).
//
// Stage 1 turns a LOCKED North Star (the Stage-0 deliverable) into an approved,
// PHASED Master Plan — the "what & why", with enough concrete near-term specifics
// to seed the Stage-2 implementation plan (MASTER-PLAN §4 Stage 1). It runs the
// Shark-Tank refinement loop end-to-end and ends at the user-approval HALT gate
// (the user is the convergence authority). The flow, in order:
//
//   1. ORANGES BRAINSTORM, in the MANDATORY order assumption-mapping → premortem
//      (§4.1). Map the load-bearing assumptions FIRST, run a premortem AGAINST
//      those assumptions, THEN brainstorm widely with Oranges foresight. The order
//      is structural: the premortem is handed the assumptions, the ideation is
//      handed both — so "two steps ahead" reasoning is seeded by named failure
//      modes, not generated in a vacuum.
//   2. BATCH idea-triage (§4.1): refinements that serve the North Star INTEGRATE ·
//      out-of-scope ideas go to the GRASSCATCHER (parked, not dropped) · redundant/
//      no-value ideas DROP. Batched (the whole brainstorm at once, then summarized
//      — §9), and routed by the inclusion test (a non-tracing idea is out-of-scope).
//   3. A PHASED PLAN with concrete near-term specifics and the rest DEFERRED
//      EXPLICITLY (§4.2) — the plan absorbs ONLY the integrated ideas, never the
//      Grasscatchered ones.
//   4. The SHARK-TANK LOOP (Waves 2–4): sharkfood → fix → sharkfood → … until dry,
//      the Synthesizer (Wave 3) issuing direction between rounds (it steers, never
//      decides), a fresh-eyes cold pass before the lock, the Judge deciding, and the
//      convergence gate (Wave 4) gating dry-round + Judge + drift + fresh-eyes.
//   5. The user-approval HALT gate — reusing the canonical
//      HALT_GATES['stage1->stage2'] ('master-plan-approval') so this gate and the
//      engine's state-machine boundary name the SAME gate.
//
// REUSE, NOT REINVENT: every adversarial/steering/deciding mechanic is the Wave 2–5
// machinery, reached through the Wave-1 `agent()` seam — Stage 1 ORCHESTRATES the
// loop, it does not re-implement Sharks, the Synthesizer, the Judge, the gates, or
// researchPrime.

import fs from 'node:fs';
import path from 'node:path';

import { HaltError, haltForHuman, HALT_GATES } from './crucible-lib.mjs';
import { startStatusHeartbeat } from './status-heartbeat.mjs';
import { runSharkTank } from './shark-tank.mjs';
import { installProcessLifetimeGuards, withPhaseProgress } from '../../drivers/process-lifetime.mjs';
import {
  makeSynthesizer,
  freshEyesColdPass,
  freshEyesIsolationOracle,
  reconcileFreshEyes,
} from './synthesizer.mjs';
import { makeJudge } from './judge.mjs';
import { evaluateConvergenceGate } from './gates.mjs';
import { resolveBandProfile, bandProfileStamp } from './band-profile.mjs';

// ---------------------------------------------------------------------------
// (1) The Oranges brainstorm — MANDATORY order: assumption-mapping → premortem
//     → ideation. Every prompt embeds the North Star verbatim (§9).
//     LITE (cf-slick / journal 0022): single-pass constraints+approach instead
//     of the full three-call Oranges stack (still NS-embedded; still inclusion).
// ---------------------------------------------------------------------------

/** The load-bearing assumptions the whole plan rests on (mapped FIRST). */
export const ASSUMPTION_SCHEMA = {
  type: 'object',
  required: ['assumptions'],
  properties: {
    assumptions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['assumption'],
        properties: {
          id: { type: 'string' },
          assumption: { type: 'string' },
          criticality: { enum: ['high', 'medium', 'low'] },
          basis: { type: 'string' },
        },
      },
    },
  },
};

/** The premortem: how the plan fails, run AGAINST the mapped assumptions. */
export const PREMORTEM_SCHEMA = {
  type: 'object',
  required: ['failureModes'],
  properties: {
    failureModes: {
      type: 'array',
      items: {
        type: 'object',
        required: ['mode'],
        properties: {
          id: { type: 'string' },
          mode: { type: 'string' },
          cause: { type: 'string' },
          assumptionRef: { type: ['string', 'null'] },
          mitigation: { type: 'string' },
        },
      },
    },
  },
};

/**
 * The brainstorm ideas. Each carries the inclusion-test verdict
 * (`traces_to_north_star` + which criterion) and an optional `disposition` the
 * batch-triage honors (else triage infers it from the inclusion test).
 */
export const BRAINSTORM_IDEAS_SCHEMA = {
  type: 'object',
  required: ['ideas'],
  properties: {
    ideas: {
      type: 'array',
      items: {
        type: 'object',
        required: ['idea'],
        properties: {
          id: { type: 'string' },
          idea: { type: 'string' },
          traces_to_north_star: { enum: ['yes', 'no'] },
          criterion: { type: ['string', 'null'] },
          tag: { enum: ['refinement', 'out-of-scope'] },
          disposition: { enum: ['integrate', 'grasscatcher', 'drop'] },
          note: { type: 'string' },
        },
      },
    },
  },
};

function assumptionPrompt({ northStar, criteria, research }) {
  return [
    `You are the Crucible STAGE-1 ASSUMPTION-MAPPING step (the FIRST step of the brainstorm,`,
    `before the premortem). Surface the LOAD-BEARING assumptions the plan toward this North`,
    `Star would silently rest on — the ones that, if wrong, sink it. Reason in the Oranges`,
    `spirit: probe for what is actually assumed two steps downstream, not just the obvious.`,
    ``,
    `=== THE NORTH STAR (verbatim) ===`,
    String(northStar),
    `=== END NORTH STAR ===`,
    criteria.length ? `\n=== SUCCESS CRITERIA ===\n${criteria.map((c, i) => `(${i + 1}) ${c}`).join('\n')}\n=== END CRITERIA ===` : '',
    research ? `\n=== FRESH RESEARCH INPUT ===\n${typeof research === 'string' ? research : JSON.stringify(research)}\n=== END RESEARCH ===` : '',
    ``,
    `Emit: assumptions [{id, assumption, criticality (high|medium|low), basis}].`,
  ].join('\n');
}

function premortemPrompt({ northStar, assumptions }) {
  return [
    `You are the Crucible STAGE-1 PREMORTEM step. It is some time in the future and the plan`,
    `FAILED. Working AGAINST the mapped assumptions below, name how it failed: the failure`,
    `modes, their cause, the assumption each falsifies, and a mitigation. Press hardest where`,
    `a high-criticality assumption turns out to be wrong.`,
    ``,
    `=== THE NORTH STAR (verbatim) ===`,
    String(northStar),
    `=== END NORTH STAR ===`,
    ``,
    `=== MAPPED ASSUMPTIONS (the premortem runs against THESE) ===`,
    assumptions.length
      ? assumptions.map((a, i) => `(${i + 1}) [${a.criticality || '?'}] ${a.assumption}`).join('\n')
      : '(none mapped)',
    `=== END ASSUMPTIONS ===`,
    ``,
    `Emit: failureModes [{id, mode, cause, assumptionRef, mitigation}].`,
  ].join('\n');
}

function ideationPrompt({ northStar, criteria, assumptions, premortem, research }) {
  return [
    `You are the Crucible STAGE-1 BRAINSTORM. Brainstorm WIDELY toward this North Star with`,
    `Oranges foresight (think 2–3 steps ahead; add justified value; show the receipt), now`,
    `INFORMED by the mapped assumptions and the premortem's failure modes. For each idea,`,
    `apply the INCLUSION TEST honestly: does it trace to a North-Star criterion?`,
    ``,
    `=== THE NORTH STAR (verbatim) ===`,
    String(northStar),
    `=== END NORTH STAR ===`,
    criteria.length ? `\n=== SUCCESS CRITERIA ===\n${criteria.map((c, i) => `(${i + 1}) ${c}`).join('\n')}\n=== END CRITERIA ===` : '',
    ``,
    `=== PREMORTEM FAILURE MODES (mitigate these) ===`,
    premortem.length ? premortem.map((f, i) => `(${i + 1}) ${f.mode} — ${f.mitigation || ''}`).join('\n') : '(none)',
    `=== END FAILURE MODES ===`,
    research ? `\n=== FRESH RESEARCH INPUT ===\n${typeof research === 'string' ? research : JSON.stringify(research)}\n=== END RESEARCH ===` : '',
    ``,
    `Emit: ideas (a list of objects with fields: id, idea, traces_to_north_star, criterion, tag).`,
    `An idea that does NOT trace to a criterion is out-of-scope (it will be parked in the`,
    `Grasscatcher, not absorbed) — label it honestly rather than inflating its relevance.`,
  ].join('\n');
}

/** Map the load-bearing assumptions (the FIRST brainstorm step). */
export async function runAssumptionMap({ agent, northStar, criteria = [], research = null, log = () => {} } = {}) {
  requireAgent(agent, 'runAssumptionMap');
  const out = (await agent(assumptionPrompt({ northStar, criteria, research }), { label: 'stage1:assumptions', schema: ASSUMPTION_SCHEMA })) || {};
  const assumptions = Array.isArray(out.assumptions) ? out.assumptions : [];
  log(`stage1 assumption-map: ${assumptions.length} assumption(s)`);
  return assumptions;
}

/** Run the premortem AGAINST the mapped assumptions (the SECOND brainstorm step). */
export async function runPremortem({ agent, northStar, assumptions = [], log = () => {} } = {}) {
  requireAgent(agent, 'runPremortem');
  const out = (await agent(premortemPrompt({ northStar, assumptions }), { label: 'stage1:premortem', schema: PREMORTEM_SCHEMA })) || {};
  const failureModes = Array.isArray(out.failureModes) ? out.failureModes : [];
  log(`stage1 premortem: ${failureModes.length} failure mode(s)`);
  return failureModes;
}

/**
 * Run the full Oranges brainstorm in the MANDATORY order (§4.1): map assumptions,
 * premortem against them, THEN ideate informed by both. The order is enforced by
 * data flow — the premortem receives the assumptions, the ideation receives both —
 * so it cannot silently run out of order.
 *
 * @param {object} o
 * @param {Function} o.agent                  the Wave-1 agent seam
 * @param {string}   o.northStar
 * @param {string[]}[o.criteria=[]]
 * @param {?(string|object)} [o.research=null]  researchPrime briefing (flows in up-front)
 * @param {Function}[o.log=()=>{}]
 * @returns {Promise<{assumptions:object[], premortem:object[], ideas:object[]}>}
 */
/**
 * @param {object} o
 * @param {boolean} [o.lite=false]  when true, single agent call (LITE band — journal 0022)
 */
export async function runBrainstorm({
  agent, northStar, criteria = [], research = null, lite = false, log = () => {},
} = {}) {
  requireAgent(agent, 'runBrainstorm');
  if (!northStar) throw new HaltError('runBrainstorm requires a locked North Star', 'lock the North Star in Stage 0 first');

  if (lite) {
    // LITE: one Oranges-aware pass — constraints + top approaches + light assumptions.
    // Does NOT delete the North Star embed or inclusion test; collapses 3 serial
    // multi-minute calls into 1 (journal 0026: thrash was serial Grok brainstorm).
    const prompt = [
      `You are Crucible STAGE-1 LITE planning (nimble path). The North Star is LOCKED.`,
      `In ONE response: (1) list 2–5 load-bearing assumptions, (2) 1–3 failure modes,`,
      `(3) 3–8 concrete approaches/ideas that serve the North Star (inclusion test: each`,
      `must trace to a criterion). Think 2–3 steps ahead (Oranges) but do NOT run a full`,
      `wide brainstorm — this is a small/clear effort.`,
      ``,
      `=== THE NORTH STAR (verbatim) ===`,
      String(northStar),
      `=== END NORTH STAR ===`,
      criteria?.length ? `Criteria: ${criteria.join(' · ')}` : '',
      research ? `Research brief (optional):\n${typeof research === 'string' ? research : JSON.stringify(research).slice(0, 2000)}` : '',
      ``,
      `Emit JSON matching the schema: assumptions[], failureModes[], ideas[]`,
      `(each idea: idea, traces_to_north_star yes/no, criterion optional).`,
    ].filter(Boolean).join('\n');
    const out = (await agent(prompt, { label: 'stage1:lite-brainstorm', schema: {
      type: 'object',
      required: ['assumptions', 'ideas'],
      properties: {
        assumptions: { type: 'array', items: { type: 'object' } },
        failureModes: { type: 'array', items: { type: 'object' } },
        ideas: { type: 'array', items: { type: 'object' } },
      },
    } })) || {};
    const assumptions = Array.isArray(out.assumptions) ? out.assumptions : [];
    // Same shape as runPremortem: bare array of failure modes (buildPhasedPlan uses .map)
    const premortem = Array.isArray(out.failureModes) ? out.failureModes : [];
    const ideas = Array.isArray(out.ideas) ? out.ideas : [];
    log(`stage1 LITE brainstorm: ${ideas.length} idea(s) · ${assumptions.length} assumption(s) · ${premortem.length} failure mode(s) (single-pass)`);
    return { assumptions, premortem, ideas, lite: true };
  }

  // FULL / SPIKE: MANDATORY ORDER: assumption mapping → premortem → ideation.
  const assumptions = await runAssumptionMap({ agent, northStar, criteria, research, log });
  const premortem = await runPremortem({ agent, northStar, assumptions, log });
  const out = (await agent(ideationPrompt({ northStar, criteria, assumptions, premortem, research }), { label: 'stage1:ideas', schema: BRAINSTORM_IDEAS_SCHEMA })) || {};
  const ideas = Array.isArray(out.ideas) ? out.ideas : [];
  log(`stage1 brainstorm: ${ideas.length} idea(s) (after assumption-map → premortem)`);
  return { assumptions, premortem, ideas, lite: false };
}

// ---------------------------------------------------------------------------
// (2) Batch idea-triage — integrate / Grasscatcher / drop, by the inclusion test.
// ---------------------------------------------------------------------------

export const TRIAGE_DISPOSITIONS = { INTEGRATE: 'integrate', GRASSCATCHER: 'grasscatcher', DROP: 'drop' };

/**
 * The triage disposition of one idea. An explicit `disposition` from the brainstorm
 * wins; otherwise the INCLUSION TEST routes it: an out-of-scope / non-tracing idea
 * goes to the Grasscatcher (parked, never dropped silently), an explicitly redundant
 * idea drops, everything else (a refinement that serves the North Star) integrates.
 */
export function triageDisposition(idea) {
  const explicit = String(idea?.disposition || '').toLowerCase();
  if (Object.values(TRIAGE_DISPOSITIONS).includes(explicit)) return explicit;

  const tracesField = idea?.traces_to_north_star;
  const traces = String(tracesField || '').toLowerCase() === 'yes';
  // Out-of-scope by tag, OR a stated non-tracing verdict ⇒ park in the Grasscatcher.
  if (idea?.tag === 'out-of-scope' || (tracesField != null && !traces)) {
    return TRIAGE_DISPOSITIONS.GRASSCATCHER;
  }
  if (idea?.drop === true) return TRIAGE_DISPOSITIONS.DROP;
  return TRIAGE_DISPOSITIONS.INTEGRATE;
}

/**
 * BATCH-triage the whole brainstorm at once (§4.1/§9): route every idea to
 * integrate / Grasscatcher / drop, then summarize. The phased plan absorbs ONLY the
 * `integrate` bucket — the Grasscatchered ideas are parked (optionally appended to a
 * GRASSCATCHER.md) and never silently absorbed.
 *
 * @param {object} o
 * @param {object[]} [o.ideas=[]]
 * @param {?string} [o.grasscatcherPath=null]   when set, parked ideas are appended here
 * @param {Function}[o.log=()=>{}]
 * @returns {{integrate:object[], grasscatcher:object[], dropped:object[],
 *            batch:true, grasscatcherPath:?string}}
 */
export function triageIdeas({ ideas = [], grasscatcherPath = null, log = () => {} } = {}) {
  const integrate = [];
  const grasscatcher = [];
  const dropped = [];
  for (const idea of ideas || []) {
    const disp = triageDisposition(idea);
    if (disp === TRIAGE_DISPOSITIONS.GRASSCATCHER) grasscatcher.push(idea);
    else if (disp === TRIAGE_DISPOSITIONS.DROP) dropped.push(idea);
    else integrate.push(idea);
  }
  let writtenPath = null;
  if (grasscatcherPath && grasscatcher.length) writtenPath = appendGrasscatcher(grasscatcherPath, grasscatcher);
  log(`stage1 triage (batch): ${integrate.length} integrate · ${grasscatcher.length} → Grasscatcher · ${dropped.length} drop`);
  return { integrate, grasscatcher, dropped, batch: true, grasscatcherPath: writtenPath };
}

/** Append parked ideas to a GRASSCATCHER.md (creating it); returns the path. */
export function appendGrasscatcher(grasscatcherPath, parked) {
  const lines = ['', `## Stage-1 triage — parked (out-of-scope; revisit if the North Star is amended)`, ''];
  for (const idea of parked) {
    lines.push(`- ${idea.idea || idea.id || JSON.stringify(idea)}${idea.note ? ` — ${idea.note}` : ''}`);
  }
  const block = lines.join('\n') + '\n';
  fs.mkdirSync(path.dirname(path.resolve(grasscatcherPath)), { recursive: true });
  fs.appendFileSync(grasscatcherPath, block);
  return grasscatcherPath;
}

// ---------------------------------------------------------------------------
// (3) The phased plan — concrete near-term specifics + the rest deferred (§4.2).
// ---------------------------------------------------------------------------

/** A phased plan: each phase names its near-term specifics and what it DEFERS. */
export const PHASED_PLAN_SCHEMA = {
  type: 'object',
  required: ['phases'],
  properties: {
    summary: { type: 'string' },
    phases: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name'],
        properties: {
          name: { type: 'string' },
          rationale: { type: 'string' },
          nearTermSpecifics: { type: 'array', items: { type: 'string' } },
          deferred: { type: 'array', items: { type: 'string' } },
        },
      },
    },
  },
};

function phasedPlanPrompt({ northStar, criteria, ideas, assumptions, premortem }) {
  return [
    `You are the Crucible STAGE-1 PHASED-PLAN step. Refine the INTEGRATED ideas into a`,
    `phased plan toward this North Star. Front-load CONCRETE near-term specifics — enough to`,
    `seed a Stage-2 implementation plan — and DEFER the rest EXPLICITLY (name what is deferred,`,
    `do not silently omit it). Every phase must serve a North-Star criterion (the inclusion test).`,
    ``,
    `=== THE NORTH STAR (verbatim) ===`,
    String(northStar),
    `=== END NORTH STAR ===`,
    criteria.length ? `\n=== SUCCESS CRITERIA ===\n${criteria.map((c, i) => `(${i + 1}) ${c}`).join('\n')}\n=== END CRITERIA ===` : '',
    ``,
    `=== INTEGRATED IDEAS (the plan absorbs THESE; Grasscatchered ideas are excluded) ===`,
    ideas.length ? ideas.map((d, i) => `(${i + 1}) ${d.idea || d.id}`).join('\n') : '(none)',
    `=== END INTEGRATED IDEAS ===`,
    ``,
    `=== PREMORTEM MITIGATIONS TO BUILD IN ===`,
    premortem.length ? premortem.map((f, i) => `(${i + 1}) ${f.mitigation || f.mode}`).join('\n') : '(none)',
    `=== END MITIGATIONS ===`,
    ``,
    `Emit: summary, phases [{name, rationale, nearTermSpecifics, deferred}].`,
  ].join('\n');
}

/**
 * Build the phased Master Plan from the integrated ideas. HALTs (never silently
 * passes) if the pass yields no phases, or no near-term specifics at all — a phased
 * plan with nothing concrete cannot seed the Stage-2 implementation plan (§4.2).
 *
 * @param {object} o
 * @param {Function} o.agent
 * @param {string}   o.northStar
 * @param {string[]}[o.criteria=[]]
 * @param {object[]}[o.ideas=[]]          the INTEGRATED ideas (post-triage)
 * @param {object[]}[o.assumptions=[]]
 * @param {object[]}[o.premortem=[]]
 * @param {Function}[o.log=()=>{}]
 */
export async function buildPhasedPlan({ agent, northStar, criteria = [], ideas = [], assumptions = [], premortem = [], log = () => {} } = {}) {
  requireAgent(agent, 'buildPhasedPlan');
  if (!northStar) throw new HaltError('buildPhasedPlan requires a locked North Star', 'lock the North Star in Stage 0 first');
  const out = (await agent(phasedPlanPrompt({ northStar, criteria, ideas, assumptions, premortem }), { label: 'stage1:phased-plan', schema: PHASED_PLAN_SCHEMA })) || {};
  const phases = (Array.isArray(out.phases) ? out.phases : []).map((p) => ({
    name: p.name,
    rationale: p.rationale ?? '',
    nearTermSpecifics: Array.isArray(p.nearTermSpecifics) ? p.nearTermSpecifics : [],
    deferred: Array.isArray(p.deferred) ? p.deferred : [],
  }));
  if (!phases.length) throw haltForHuman('Stage-1 phased-plan pass produced no phases', 'rerun-phased-plan');
  if (!phases.some((p) => p.nearTermSpecifics.length)) {
    throw haltForHuman('Stage-1 phased plan has no near-term specifics to seed the implementation plan (§4.2)', 'rerun-phased-plan');
  }
  const plan = {
    northStar,
    criteria,
    summary: out.summary ?? '',
    phases,
    integratedIdeaCount: ideas.length,
  };
  log(`stage1 phased plan: ${phases.length} phase(s), ${phases.reduce((n, p) => n + p.nearTermSpecifics.length, 0)} near-term specific(s)`);
  return plan;
}

/** Render the phased plan to the markdown draft the Shark Tank reviews. */
export function renderMasterPlanDraft(plan) {
  const lines = [
    `# Master Plan (draft)`,
    '',
    `**North Star:** ${plan.northStar}`,
    '',
  ];
  if (plan.criteria?.length) {
    lines.push('## Success criteria', ...plan.criteria.map((c) => `- ${c}`), '');
  }
  if (plan.summary) lines.push(plan.summary, '');
  for (let i = 0; i < plan.phases.length; i++) {
    const p = plan.phases[i];
    lines.push(`## Phase ${i + 1} — ${p.name}`);
    if (p.rationale) lines.push('', p.rationale);
    if (p.nearTermSpecifics.length) lines.push('', '**Near-term specifics:**', ...p.nearTermSpecifics.map((s) => `- ${s}`));
    if (p.deferred.length) lines.push('', '**Deferred (explicitly):**', ...p.deferred.map((s) => `- ${s}`));
    lines.push('');
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// (4) The Shark-Tank loop — sharkfood → fix → … until dry, then Judge + gate.
// ---------------------------------------------------------------------------

/** What the between-round draft revision returns (the "fix" step). */
const REVISE_SCHEMA = {
  type: 'object',
  required: ['draft', 'changelog'],
  properties: {
    draft: { type: 'string' },
    changelog: { type: 'array', items: { type: 'string' } },
  },
};

/** Above this draft size, revise returns raw MARKDOWN (a document need not be a JSON
 * string — serializing a ~100KB draft into a JSON string is the fragility that stalled
 * Item-F Stage-1c with repeated "reply was not valid JSON" retries). Small drafts stay
 * schema-first so the structured changelog briefing survives. (EI1, 2026-07-17) */
export const REVISE_MARKDOWN_BYTES = 20000;

/** A markdown-first revise must not catastrophically SHRINK the draft. Without the schema's
 * full-`draft` field, a model may return a DELTA ("edited only Phase X; rest carried forward
 * UNCHANGED, not reproduced here") — which the raw-markdown parse would accept as the WHOLE
 * plan, silently losing it (observed Stage-1e r5: 111KB → 16KB). A revised draft below this
 * fraction of the prior is treated as a non-compliant partial and REJECTED — keep the prior
 * draft (the round makes no change rather than losing the plan). (EI1 guard, 2026-07-17) */
export const REVISE_MIN_KEEP_RATIO = 0.5;

function revisePrompt({ northStar, draft, verdict, direction, markdownFirst = false }) {
  return [
    `You are the Crucible STAGE-1 draft-revision step. Address the BLOCKING findings from the`,
    `last Shark Tank and the Synthesizer's direction, WITHOUT drifting from the North Star.`,
    `Return the revised Master-Plan draft in full.`,
    ``,
    `=== THE NORTH STAR (verbatim) ===`,
    String(northStar),
    `=== END NORTH STAR ===`,
    ``,
    `=== BLOCKING FINDINGS TO RESOLVE ===`,
    (verdict.blockers || []).length
      ? verdict.blockers.map((b, i) => `(${i + 1}) [${b.severity}] ${b.message || b.id}`).join('\n')
      : '(none — refine per the direction)',
    `=== END FINDINGS ===`,
    ``,
    `=== SYNTHESIZER DIRECTION ===`,
    direction ? `lean=${direction.lean}; press: ${direction.probingBrief || ''}` : '(none)',
    `=== END DIRECTION ===`,
    ``,
    `=== CURRENT DRAFT ===`,
    String(draft),
    `=== END DRAFT ===`,
    ``,
    markdownFirst
      ? `You must use Search/Replace blocks to modify the draft. Do NOT output the entire draft.\n`
        + `Each block must look exactly like this:\n`
        + `<<<<\n`
        + `[exact lines to replace, including leading whitespace]\n`
        + `====\n`
        + `[new lines]\n`
        + `>>>>\n`
        + `The lines in the top half must EXACTLY match the current draft. A partial or truncated reply is REJECTED and the round is lost.\n`
        + `(This draft is large; the structured changelog is omitted this round to avoid fragile large-JSON serialization.)`
      : `Emit: draft (the full revised draft), changelog (what you changed).\n`
        + `If and ONLY if you cannot escape the draft into valid JSON, emit ONLY the revised draft`
        + ` enclosed in \`\`\`markdown ... \`\`\` fences — the structured changelog is dropped that round.`,
  ].join('\n');
}

/** 0013 structural lint: a corrupted merge (e.g. a `$`-pattern splice in String.replace)
 * interleaves whole copies of the plan into itself. Detect the two signatures — a repeated
 * top-level H1 heading, or leftover search/replace block markers — so a corrupted revision
 * is rejected and the prior draft kept. Exported for tests. */
export function detectDraftCorruption(text) {
  const s = String(text);
  const counts = new Map();
  for (const line of s.split(/\r?\n/)) {
    const t = line.trim();
    if (/^#\s/.test(t)) counts.set(t, (counts.get(t) || 0) + 1);
  }
  for (const [h, n] of counts) {
    if (n >= 2) return `top-level heading repeated ${n}x: "${h.slice(0, 60)}"`;
  }
  if (/^(<<<<|>>>>)\s*$/m.test(s)) return 'leftover search/replace block markers in draft';
  return null;
}

/** Exported for tests (the schema-first / raw-text fallback contract). */
export async function reviseDraft({ agent, northStar, draft, verdict, direction, round, depth = null, family = null, log = () => {} }) {
  // EI1 (2026-07-17): a LARGE draft is revised MARKDOWN-FIRST — a document need not be a JSON
  // string, and serializing a ~100KB draft into JSON is the fragility that stalled Stage-1c
  // (repeated "reply was not valid JSON" retries). Small drafts stay schema-first so the
  // structured changelog briefing survives. The raw-markdown parse below recovers the draft
  // either way; a null/empty reply keeps the prior draft (never lose a round's work).
  //
  // P1 2026-07-25 (journal 0040 verbatim ask; corroborated 0043/0053/0056/0058/0060/
  // 0070-e1/0075-e4/0076-e4): the path is now chosen by BAND/FAMILY/DELTA, not byte
  // count alone. LITE drafts run 8-17KB — always under the byte threshold — so LITE
  // always took the fragile schema-JSON path and paid full rounds for 0 changes
  // ("reply was not valid JSON" → retry → ABSTAIN). Grok seats parse worst; and a
  // round with <=2 blocking findings takes the search/replace PATCH path regardless
  // of size (0068: an 8.5-minute full re-emit of a 39KB draft produced "1 change(s)").
  const findingCount = Array.isArray(verdict?.blockers) ? verdict.blockers.length : null;
  const markdownFirst =
    Buffer.byteLength(String(draft)) >= REVISE_MARKDOWN_BYTES ||
    String(depth ?? '').toUpperCase() === 'LITE' ||
    String(family ?? '').toLowerCase().includes('grok') ||
    (Number.isInteger(findingCount) && findingCount > 0 && findingCount <= 2);
  const prompt = revisePrompt({ northStar, draft, verdict, direction, markdownFirst });
  const out = markdownFirst
    ? await agent(prompt, { label: `stage1:revise:r${round}` })                       // schema-less → raw markdown
    : await agent(prompt, { label: `stage1:revise:r${round}`, schema: REVISE_SCHEMA });
  let revised = draft;
  let changelog;
  if (!markdownFirst && out && typeof out === 'object' && typeof out.draft === 'string') {
    // The structured contract: { draft, changelog } (small-draft schema-first path).
    revised = out.draft;
    changelog = Array.isArray(out.changelog) ? out.changelog : [];
  } else {
    // Raw-markdown parse — the PRIMARY path for large drafts (EI1), the FALLBACK for small
    // (journal 0002): take the ```markdown fenced block, else the trimmed text. A null/empty
    // reply keeps the prior draft (never lose a round's work to a dead seam).
    const text = typeof out === 'string' ? out : (out && typeof out.draft === 'string' ? out.draft : '');
    
    if (markdownFirst) {
      changelog = [];
      const regex = /<<<<\r?\n([\s\S]*?)\r?\n====\r?\n([\s\S]*?)\r?\n>>>>/g;
      let match;
      let matchedAny = false;
      while ((match = regex.exec(text)) !== null) {
        matchedAny = true;
        const search = match[1];
        const replace = match[2];
        if (revised.includes(search)) {
          // Function replacement: model output may contain `$`-patterns ($`, $', $&) that
          // String.replace would expand into surrounding-document splices (journal 0013 —
          // the draft ended as ~3 interleaved copies of itself).
          revised = revised.replace(search, () => replace);
          changelog.push('Applied a search/replace patch');
        } else {
          changelog.push('FAILED patch: search text not found in draft');
          // Try a trimmed fallback just in case
          if (search.trim() && revised.includes(search.trim())) {
             revised = revised.replace(search.trim(), () => replace.trim());
             changelog.push('Applied patch using trimmed fallback');
          }
        }
      }
      if (!matchedAny) {
        // Fallback in case the model ignored instructions and output the whole draft anyway
        const m = text.match(/```(?:markdown)?\s*([\s\S]*?)```/i);
        if (m) revised = m[1].trim();
        else if (text.trim() && text.length > draft.length * 0.5) revised = text.trim();
        changelog.push('(Fell back to parsing whole draft, no search/replace blocks found)');
      }
    } else {
      const m = text.match(/```(?:markdown)?\s*([\s\S]*?)```/i);
      if (m) revised = m[1].trim();
      else if (text.trim()) revised = text.trim();
      changelog = revised !== draft
        ? ['(Raw markdown parsed, changelog omitted)']
        : [];
      log(`stage1 revise r${round}: structured reply unavailable — raw-text fallback (changelog omitted)`);
    }
  }
  // 0013 structural guard: reject a revision that interleaved copies of the plan into
  // itself (splice corruption) — only when the PRIOR draft was clean, so a legitimately
  // unusual draft can still be revised.
  if (revised !== draft) {
    const corruption = detectDraftCorruption(revised);
    if (corruption && !detectDraftCorruption(draft)) {
      log(`stage1 revise r${round}: REJECTED corrupted revision (${corruption}) — keeping prior draft (0013 guard)`);
      revised = draft;
      changelog = [];
    }
  }
  // EI1 completeness guard (2026-07-17): never let a markdown-first revise SHRINK the plan
  // catastrophically (a model returning a delta/partial instead of the full draft — observed
  // Stage-1e r5: 111KB→16KB). Below REVISE_MIN_KEEP_RATIO of the prior ⇒ non-compliant partial
  // ⇒ KEEP the prior draft (no change this round rather than losing the plan).
  if (markdownFirst && revised !== draft) {
    const priorLen = Buffer.byteLength(String(draft));
    const newLen = Buffer.byteLength(String(revised));
    if (priorLen >= REVISE_MARKDOWN_BYTES && newLen < priorLen * REVISE_MIN_KEEP_RATIO) {
      log(`stage1 revise r${round}: markdown-first reply was ${Math.round((100 * newLen) / priorLen)}% of the prior draft — NON-COMPLIANT PARTIAL, keeping prior draft (completeness guard)`);
      revised = draft;
      changelog = [];
    }
  }
  log(`stage1 revise r${round}: draft revised (${changelog.length} change(s))${markdownFirst ? ' [markdown-first]' : ''}`);
  // 2026-07: the changelog is no longer discarded — the next round's Sharks get
  // it (with the blocker register) so refutation focuses on new ground.
  return { draft: revised, changelog };
}

/**
 * Drive the Shark-Tank refinement loop to a model-side convergence verdict.
 *
 * Each round: (optional) per-round researchPrime ONLY on a genuinely new candidate
 * (the Wave-5 cost-guard) → a Shark Tank (Wave 2) → the Synthesizer issues direction
 * (Wave 3, steers/never decides). A BLOCKED round triggers a draft "fix" and another
 * round. A DRY round triggers the lock checks: a fresh-eyes cold pass (a NEW, no-
 * context instance — Wave 3), the Judge's decision (Wave 3), and the convergence gate
 * (Wave 4). When the gate is model-side lockable the loop returns; otherwise it runs
 * one more challenge round. The round cap is a safety ceiling — hitting it HALTs.
 *
 * @param {object} o
 * @param {Function} o.agent
 * @param {string}   o.northStar
 * @param {string[]}[o.criteria=[]]
 * @param {string}   o.draft                          the initial Master-Plan draft
 * @param {?object} [o.research=null]                 the Wave-5 coordinator
 * @param {?object} [o.synthesizer=null]              an injected Synthesizer (else built here)
 * @param {?object} [o.judge=null]                    an injected Judge (else built here)
 * @param {?object} [o.routes=null]                   the run's role routes — lets the built Judge
 *                                                    stamp enhanced/cross_model from where the
 *                                                    judge role ACTUALLY dispatches (T7)
 * @param {string[]}[o.acceptanceCriteria=[]]         the Judge's oracle
 * @param {number}  [o.roundCap=5]                     §8 safety ceiling
 * @param {number}  [o.startRound=1]
 * @param {number|null} [o.additionalRounds=null]     when set, run exactly this many
 *                                                    more rounds from startRound (explicit
 *                                                    extend). When null, effort-scoped
 *                                                    cap applies: total rounds from 1 may
 *                                                    not exceed roundCap (resume with
 *                                                    startRound=6 + roundCap=5 → 0 remaining).
 * @param {number}  [o.humanLockableAfterDry=1]        consecutive dry rounds with no ≥2-agree
 *   ELEGANCE rule 5 (2026-08-15): ONE genuinely-dry round ends a review loop — never a
 *   streak, which pays reviewers to keep finding filler. The first dry-held round goes
 *   to the USER (the convergence authority) instead of buying a second identical round.
 *   Overridable per run for callers who deliberately want the old double-check.
 *                                                    Shark blockers before human-lockable HALT
 *                                                    (Judge/fresh-eyes hold without multi-Shark
 *                                                    substance). 0 disables. Default 2.
 * @param {number}  [o.sharkRoles=3]                   concurrent Shark seats (LITE uses 2)
 * @param {?string} [o.artifactsDir=null]             Shark-Tank round artifacts dir
 * @param {string}  [o.capPendingAction='stage1-round-cap']  the HALT's pending_action
 *                                                    (Stage 2 reuses this loop under
 *                                                    its own name)
 * @param {Function}[o.log=()=>{}]
 */
export async function runMasterPlanLoop({
  agent,
  northStar,
  criteria = [],
  draft,
  research = null,
  synthesizer = null,
  judge = null,
  routes = null,
  acceptanceCriteria = [],
  roundCap = undefined,
  startRound = 1,
  additionalRounds = null,
  humanLockableAfterDry = 1,
  sharkRoles = undefined,
  /** When set, applies band profile defaults for roundCap/sharkRoles (cf-slick). */
  depth = null,
  artifactsDir = null,
  capPendingAction = 'stage1-round-cap',
  statusLog = null,
  statusLabel = 'Crucible plan',
  log = () => {},
} = {}) {
  requireAgent(agent, 'runMasterPlanLoop');
  // If callers still pass depth into the loop (legacy launchers), honor band profile.
  if (depth != null) {
    const band = resolveBandProfile(depth);
    if (roundCap === undefined) roundCap = band.roundCap;
    if (sharkRoles === undefined) sharkRoles = band.sharkRoles;
    log(`loop band from depth=${band.depth}: roundCap=${roundCap} sharks=${sharkRoles}`);
  }
  if (roundCap === undefined) roundCap = 5;
  if (sharkRoles === undefined) sharkRoles = 3;
  const synth = synthesizer || makeSynthesizer({ agent, northStar, log });
  // T7 (2026-07-11): when the caller supplies the run's ROUTES, the Judge's
  // selection/stamp is DERIVED from where the judge role actually dispatches —
  // a route to a non-author family stamps enhanced/cross_model honestly.
  const jdg = judge || makeJudge({ agent, routes, log });
  // P1 2026-07-25: derive the revise seat's FAMILY and an honest per-seat substrate
  // stamp from the live routes (journal 0070-e1 item 3: the status table hardcoded
  // "(agy 5:1)" while every seat was grok — the prose lied about the substrate).
  const famOf = (r) => {
    const d = String(r?.family ?? r?.driver ?? '').toLowerCase();
    if (!d) return null;
    if (d.includes('gemini')) return 'gemini';
    if (d.includes('grok')) return 'grok';
    return 'claude';
  };
  const reviseFamily = famOf(routes?.revise) ?? famOf(routes?.default) ??
    String(process.env.CODING_FAMILY ?? '').toLowerCase() ?? null;
  const seatStamp = routes
    ? `sharks∥(${famOf(routes.review) ?? famOf(routes.shark) ?? famOf(routes.default) ?? 'claude'}) + ` +
      `judge(${famOf(routes.judge) ?? famOf(routes.default) ?? 'claude'}) + synthesizer(${famOf(routes.synthesizer) ?? famOf(routes.default) ?? 'claude'})`
    : 'sharks∥ + judge + synthesizer (single-agent seam — no routes bound)';
  const bounds = resolveLoopBounds({ startRound, roundCap, additionalRounds });
  if (bounds.remaining === 0) {
    const err = haltForHuman(
      `effort round budget exhausted (startRound=${startRound}, roundCap=${roundCap}, ` +
        `already counted ${bounds.already} round(s) toward the effort) — refusing to silently ` +
        `open another full cap on resume. Pass additionalRounds=N to explicitly extend, or ` +
        `approve the best draft under human-lockable if Sharks were dry.`,
      'stage1-effort-round-cap',
    );
    err.best_draft = { draft, roundsRun: bounds.already, openFindings: [], effortCap: true };
    throw err;
  }
  log(`loop bounds: rounds ${bounds.startRound}..${bounds.endExclusive - 1} ` +
    `(remaining=${bounds.remaining}, already=${bounds.already}, mode=${bounds.mode})`);

  let currentDraft = draft;
  let priorBlockerIds = [];
  let lastChangelog = null;   // the reviser's own changelog, fed to the next round's Sharks
  let directed = false;       // has the Director ever spoken? (anti-anchoring spine needs one position)
  const rounds = [];
  const SHARK_QUORUM_RETRIES = 2; // re-review a round with <2 parseable reviewers before HALTing (transient reviewer-transport failures)

  // 2026-07-11: the 10-min Status heartbeat — off unless the caller passes a
  // statusLog (so tests/dogfood stay silent). The supervising session tails the
  // log and relays to chat (see SKILL.md "How to run"). Snapshot reads live state.
  const heartbeat = startStatusHeartbeat({
    logPath: statusLog,
    label: statusLabel,
    snapshot: () => {
      const last = rounds.length ? rounds[rounds.length - 1] : null;
      const openBlk = last ? (last.verdict.blockers || []).length : 0;
      return {
        effort: `${statusLabel} (effort cap ${roundCap}; remaining ${bounds.remaining})`,
        doing: `Shark-Tank round ${rounds.length + 1} · ${rounds.length ? (last.verdict.dry ? 'dry — checking lock' : 'blocked — revising') : 'first review'}`,
        status: `${rounds.length} this invoke / ${bounds.remaining} budgeted`,
        tests: last ? `last round: ${last.verdict.verdict}` : '—',
        blocker: openBlk ? `${openBlk} open blocker(s) this round` : 'none',
        procs: seatStamp,
        eta: `<= ${Math.max(0, bounds.remaining - rounds.length)} more round(s) this window`,
        todo: 'converge or human-lockable HALT, then the user-approval gate',
      };
    },
  });

  let dryHeldStreak = 0;
  try {
  for (let round = bounds.startRound; round < bounds.endExclusive; round++) {
    // P1 2026-07-25 (Stage-1 durability): persist the CURRENT draft + round marker at
    // every round start — a process death mid-loop (the 9-death cluster) now loses at
    // most one round; the operator recovers from BEST-DRAFT.md instead of nothing.
    if (artifactsDir) {
      try {
        fs.mkdirSync(artifactsDir, { recursive: true });
        fs.writeFileSync(path.join(artifactsDir, 'BEST-DRAFT.md'), String(currentDraft));
        const pPath = path.join(artifactsDir, 'stage1-progress.json');
        const tmp = `${pPath}.tmp`;
        fs.writeFileSync(tmp, JSON.stringify({
          phase: 'shark-round', round, status: 'start', ts: new Date().toISOString(), pid: process.pid,
        }, null, 2) + '\n', 'utf8');
        fs.renameSync(tmp, pPath);
      } catch { /* best-effort — never crash the loop on durability bookkeeping */ }
    }
    // Per-round research only on a genuinely NEW candidate (Wave-5 cost-guard).
    let analystBrief = null;
    if (research && typeof research.perRound === 'function') {
      await research.perRound({ candidate: currentDraft, round });
      analystBrief = research.forAnalyst ? research.forAnalyst() : null;
    }

    const nSharks = Math.max(2, Math.min(3, Number(sharkRoles) || 3));
    let verdict = await runSharkTank({
      agent, northStar, draft: currentDraft, round, priorBlockerIds,
      research: analystBrief, artifactsDir, log,
      sharkRoles: nSharks,
      changelog: lastChangelog && lastChangelog.length ? lastChangelog.join('\n') : null,
    });
    // Quorum guard (2026-07-17): a round needs >=2 parseable reviews to be trustworthy — a
    // BLOCKER requires >=2 Sharks to agree, so <2 answering reviewers can NEVER surface one and
    // a "dry" verdict would be a FALSE convergence. Re-review the SAME draft (no revise) on
    // transient reviewer-transport failures, then HALT honestly rather than lock on an
    // under-reviewed round. ONE abstain (2 answered) is tolerated — it still forms a quorum.
    for (let q = 0; verdict.inconclusive && q < SHARK_QUORUM_RETRIES; q++) {
      log(`shark-tank round ${round}: only ${verdict.answered}/${nSharks} reviewers parseable — re-reviewing (${q + 1}/${SHARK_QUORUM_RETRIES}) before trusting the round`);
      verdict = await runSharkTank({
        agent, northStar, draft: currentDraft, round, priorBlockerIds,
        research: analystBrief, artifactsDir, log,
        sharkRoles: nSharks,
        changelog: lastChangelog && lastChangelog.length ? lastChangelog.join('\n') : null,
      });
    }
    if (verdict.inconclusive) {
      if (artifactsDir) {
        try {
          fs.mkdirSync(artifactsDir, { recursive: true });
          fs.writeFileSync(path.join(artifactsDir, 'BEST-DRAFT.md'), String(currentDraft));
        } catch { /* the HALT payload still carries the draft */ }
      }
      const qerr = haltForHuman(
        `shark quorum not met at round ${round}: only ${verdict.answered} of ${nSharks} reviewers returned a parseable review after ${SHARK_QUORUM_RETRIES} re-reviews — the reviewer transport (agy/Gemini) appears degraded. HALTing rather than converging on an under-reviewed round; the current draft is preserved.`,
        'stage1-shark-quorum',
      );
      qerr.best_draft = { draft: currentDraft, roundsRun: rounds.length, openFindings: [] };
      throw qerr;
    }

    if (!verdict.dry) {
      // BLOCKED — the Synthesizer steers the revision (its one consumed output),
      // record the blockers (anti-oscillation), fix the draft, loop.
      dryHeldStreak = 0;
      const direction = await synth.direct({ round, verdict, research: research?.forSynthesizer?.() ?? null });
      directed = true;
      rounds.push({ round, verdict, direction });
      priorBlockerIds = [...new Set([...priorBlockerIds, ...verdict.blockers.map((b) => b.id)])];
      const rev = await reviseDraft({ agent, northStar, draft: currentDraft, verdict, direction, round, depth, family: reviseFamily, log });
      currentDraft = rev.draft;
      lastChangelog = rev.changelog;
      if (artifactsDir) {
        try {
          fs.mkdirSync(artifactsDir, { recursive: true });
          fs.writeFileSync(path.join(artifactsDir, 'BEST-DRAFT.md'), String(currentDraft));
        } catch { /* best-effort */ }
      }
      continue;
    }

    // DRY — T7/T11 (2026-07-11): the Synthesizer call is SKIPPED on a round that
    // locks — its direction is only ever consumed by the NEXT revision, so calling
    // it unconditionally wasted one guaranteed call per converging loop. Exception:
    // if the Director has never spoken (first-round-dry), take its single steer so
    // the anti-anchoring reconcile below compares against a real standing position.
    let direction = null;
    if (!directed) {
      direction = await synth.direct({ round, verdict, research: research?.forSynthesizer?.() ?? null });
      directed = true;
    }

    // Run the anti-anchoring fresh-eyes cold pass BEFORE the lock (Wave 3).
    const cold = await freshEyesColdPass({ agent, transcripts: verdict.reviews, northStar, log });
    const oracle = freshEyesIsolationOracle({ cold, directorSnapshot: synth.snapshot() });
    const reconcile = reconcileFreshEyes({ directorPosition: synth.position(), freshEyes: cold.assessment });

    // The Judge DECIDES from the injected evidence (Wave 3).
    const judgeVerdict = await jdg.decide({ northStar, findings: verdict.findings, acceptanceCriteria, freshEyes: cold.assessment, round });

    // The convergence gate (Wave 4): dry-round + Judge + drift + fresh-eyes (advisory-unless-BLOCKER, T7).
    const gate = evaluateConvergenceGate({ tally: verdict, judgeVerdict, freshEyes: cold.assessment, approved: false });
    rounds.push({ round, verdict, direction });
    if (gate.modelSideLockable) {
      log(`stage1 loop: model-side convergence at round ${round} (${rounds.length} round(s) run)`);
      return {
        converged: true,
        modelSideLockable: true,
        humanLockable: false,
        rounds,
        roundsRun: rounds.length,
        lastVerdict: verdict,
        draft: currentDraft,
        freshEyes: cold,
        oracle,
        reconcile,
        judgeVerdict,
        gate,
        synthesizerStamp: synth.stamp,
        judgeStamp: jdg.stamp,
      };
    }

    // ---- human-lockable (2026-07-22 Phase A) --------------------------------
    // Journals 0007–0012: sharks DRY with zero ≥2-agree blockers, yet Judge /
    // fresh-eyes hold through the full cap (~30 calls of no multi-Shark substance).
    // North Star: USER is convergence authority; ≥2-agree is the Shark bar.
    // After N consecutive dry holds with no multi-Shark blockers, HALT for the
    // human instead of burning the rest of the cap. Never auto-locks.
    const hl = assessHumanLockable({ tally: verdict, dryHeldStreak: dryHeldStreak + 1 });
    if (hl.eligible) dryHeldStreak += 1;
    else dryHeldStreak = 0;
    const threshold = Number.isInteger(humanLockableAfterDry) ? humanLockableAfterDry : 1;
    if (threshold > 0 && dryHeldStreak >= threshold) {
      log(`stage1 loop: human-lockable after ${dryHeldStreak} consecutive dry hold(s) ` +
        `(${hl.reason}) — HALTing for the user (convergence authority), not burning more rounds`);
      const openFindings = (verdict.findings || []).filter((f) => !f.demoted);
      const bestDraft = {
        draft: currentDraft,
        roundsRun: rounds.length,
        openFindings,
        priorBlockerIds,
        lastDirection: direction,
        humanLockable: true,
      };
      if (artifactsDir) {
        try {
          fs.mkdirSync(artifactsDir, { recursive: true });
          fs.writeFileSync(path.join(artifactsDir, 'BEST-DRAFT.md'), String(currentDraft));
          fs.writeFileSync(path.join(artifactsDir, 'OPEN-FINDINGS.json'),
            JSON.stringify(openFindings, null, 2) + '\n');
          fs.writeFileSync(path.join(artifactsDir, 'HUMAN-LOCKABLE.json'),
            JSON.stringify({
              humanLockable: true,
              dryHeldStreak,
              reason: hl.reason,
              judgeDecision: judgeVerdict?.decision ?? null,
              gateReasons: gate.reasons || [],
              roundsRun: rounds.length,
            }, null, 2) + '\n');
        } catch { /* best-effort */ }
      }
      // THE SPEAKING LAW (ELEGANCE.md Part III; journal 0090 — this exact ask took
      // FOUR attempts because it narrated waves/gates instead of the decision).
      // The sentence John reads describes the DECISION; the machinery stays in the
      // err fields + HUMAN-LOCKABLE.json on disk. Tests pin only 'human-lockable'.
      const openCount = (verdict.findings || []).filter((f) => !f.demoted).length;
      const err = haltForHuman(
        `human-lockable: The plan is ready for your call. The reviewers have stopped ` +
          `finding problems they agree on${openCount ? `, though ${openCount} single-reviewer ` +
          `concern(s) stay listed for your eyes (OPEN-FINDINGS.json)` : ''}. ` +
          `Approving locks this draft as the Master Plan; challenging costs another review ` +
          `round. Recommendation: approve — the concerns left are single-reviewer catches, ` +
          `worth a read but none met the two-reviewer bar; challenge instead if one of them ` +
          `names something you care about. The full draft is on disk (BEST-DRAFT.md). ` +
          `Approve, challenge, or tell me something else?`,
        'stage1-human-lockable',
      );
      err.best_draft = bestDraft;
      err.humanLockable = true;
      err.loop = {
        converged: false,
        modelSideLockable: false,
        humanLockable: true,
        rounds,
        roundsRun: rounds.length,
        lastVerdict: verdict,
        draft: currentDraft,
        freshEyes: cold,
        judgeVerdict,
        gate,
      };
      throw err;
    }

    // Dry, but the Judge or a BLOCKER-bearing fresh-eyes pass held the lock —
    // run one more challenge round. The loop continues, so the Synthesizer's
    // steer IS consumed here: take it now if this round skipped it (T7/T11).
    log(`stage1 loop: dry round ${round} held (${gate.reasons.join('; ') || reconcile.reason}) — challenge round` +
      (dryHeldStreak ? ` (human-lockable streak ${dryHeldStreak}/${threshold || 'off'})` : ''));
    if (!direction) {
      direction = await synth.direct({ round, verdict, research: research?.forSynthesizer?.() ?? null });
      rounds[rounds.length - 1].direction = direction;
    }
    priorBlockerIds = [...new Set([...priorBlockerIds, ...verdict.blockers.map((b) => b.id)])];
    const rev = await reviseDraft({ agent, northStar, draft: currentDraft, verdict, direction, round, depth, family: reviseFamily, log });
    currentDraft = rev.draft;
    lastChangelog = rev.changelog;
    if (artifactsDir) {
      try {
        fs.mkdirSync(artifactsDir, { recursive: true });
        fs.writeFileSync(path.join(artifactsDir, 'BEST-DRAFT.md'), String(currentDraft));
      } catch { /* best-effort */ }
    }
  }

  // The cap is a safety ceiling, not a success condition — HALT to the user (§8).
  //
  // T5 (2026-07-11): the HALT no longer DISCARDS the run. The one full live run
  // (zombie-hunter, journal 0001) burned ~30 model calls into this cap and
  // emitted NOTHING — the user had to hand-stitch the emit path from exported
  // internals; the journal itself proposed this fix. The BEST DRAFT + the open
  // findings now (a) ride on the HaltError so the orchestrator/user always gets
  // them, and (b) are persisted to artifactsDir when one is set. The user stays
  // the convergence authority — this is still a HALT, never an auto-lock.
  const lastRound = rounds.length ? rounds[rounds.length - 1] : null;
  const openFindings = lastRound
    ? (lastRound.verdict.findings || []).filter((f) => !f.demoted)
    : [];
  const bestDraft = {
    draft: currentDraft,
    roundsRun: rounds.length,
    openFindings,
    priorBlockerIds,
    lastDirection: lastRound ? lastRound.direction : null,
  };
  if (artifactsDir) {
    try {
      fs.mkdirSync(artifactsDir, { recursive: true });
      fs.writeFileSync(path.join(artifactsDir, 'BEST-DRAFT.md'), String(currentDraft));
      fs.writeFileSync(path.join(artifactsDir, 'OPEN-FINDINGS.json'),
        JSON.stringify(openFindings, null, 2) + '\n');
      log(`loop cap: best draft + ${openFindings.length} open finding(s) persisted to ${artifactsDir}`);
    } catch (e) {
      log(`loop cap: could not persist best draft (${e.message}) — the HALT payload still carries it`);
    }
  }
  const err = haltForHuman(
    `hit the round cap (${roundCap}; effort window ${bounds.startRound}..${bounds.endExclusive - 1}) without converging — ` +
      `the safety ceiling tripped; the best draft (${rounds.length} round(s) of refinement) and ${openFindings.length} open ` +
      `finding(s) are attached${artifactsDir ? ` and persisted to ${artifactsDir}` : ''} — nothing was discarded. ` +
      `If Sharks were dry with only agreement=1 nits, treat as human-lockable and approve explicitly, or re-run with additionalRounds.`,
    capPendingAction,
  );
  err.best_draft = bestDraft;
  // Cap-exit also surfaces humanLockable when the last round was dry + no multi-agree blockers.
  if (lastRound?.verdict) {
    const hlCap = assessHumanLockable({ tally: lastRound.verdict, dryHeldStreak: 1 });
    if (hlCap.eligible) {
      err.humanLockable = true;
      err.best_draft.humanLockable = true;
    }
  }
  throw err;
  } finally {
    // Fires on BOTH exits — the converged `return` inside the loop and the
    // cap-HALT `throw` — so the final table lands and the timer is always cleared.
    heartbeat.stop();
  }
}

// ---------------------------------------------------------------------------
// (5) The user-approval HALT gate — the canonical stage1->stage2 boundary.
// ---------------------------------------------------------------------------

/**
 * The Stage-1 → Stage-2 approval gate. The user is the convergence authority: even a
 * model-side-converged Master Plan does NOT advance on its own. Without approval this
 * HALTs (reusing HALT_GATES['stage1->stage2'] = 'master-plan-approval', so this gate
 * and the engine's state-machine boundary name the SAME gate). With approval and a
 * model-side-lockable loop it returns the approved Master Plan.
 *
 * @param {object} o
 * @param {object}  o.loop                  the runMasterPlanLoop result
 * @param {object} [o.plan=null]            the structured phased plan (carried through)
 * @param {boolean}[o.approved=false]       the user's approval
 * @param {Function}[o.log=()=>{}]
 */
export function approveMasterPlan({ loop, plan = null, approved = false, log = () => {} } = {}) {
  // Model-side lock OR explicit human-lockable (dry sharks, no ≥2-agree blockers;
  // user is still the only authority that can stamp the lock).
  const modelOk = loop && loop.modelSideLockable;
  const humanOk = loop && loop.humanLockable;
  if (!loop || (!modelOk && !humanOk)) {
    throw haltForHuman(
      'Stage 1 has not converged model-side and is not marked human-lockable — cannot approve the Master Plan yet',
      'stage1-not-converged',
    );
  }
  const gate = HALT_GATES['stage1->stage2'];
  if (!approved) {
    log(humanOk && !modelOk
      ? 'stage1: human-lockable Master Plan — HALT for the user to approve (Sharks dry; no multi-Shark blockers)'
      : 'stage1: Master Plan converged model-side — HALT for the user to approve (the convergence authority)');
    throw haltForHuman(
      humanOk && !modelOk
        ? 'human-lockable plan ready — sharks dry with no ≥2-agree blockers; approve to lock (you are the convergence authority)'
        : gate.reason,
      humanOk && !modelOk ? 'stage1-human-lockable-approval' : gate.name,
    );
  }
  log(humanOk && !modelOk
    ? 'stage1: Master Plan APPROVED under human-lockable — ready for Stage 2'
    : 'stage1: Master Plan APPROVED — ready for Stage 2');
  return {
    approved: true,
    gate: gate.name,
    masterPlan: loop.draft,
    plan,
    roundsRun: loop.roundsRun,
    humanLockable: Boolean(humanOk && !modelOk),
  };
}

// ---------------------------------------------------------------------------
// Phase A (2026-07-22): effort-scoped round window + human-lockable assessment
// ---------------------------------------------------------------------------

/**
 * Resolve which rounds this invocation may run.
 *
 * Default (effort-scoped): rounds already spent toward the effort are
 * `startRound - 1`. Remaining = max(0, roundCap - already). Resume with
 * startRound=6 and roundCap=5 therefore yields 0 remaining (no silent second
 * full cap — journal 0011).
 *
 * Explicit extend: pass `additionalRounds=N` to run N more rounds from startRound
 * regardless of the effort total (user-authorized extension only).
 *
 * @returns {{startRound:number, endExclusive:number, remaining:number, already:number, mode:string}}
 */
export function resolveLoopBounds({ startRound = 1, roundCap = 5, additionalRounds = null } = {}) {
  const start = Math.max(1, Number(startRound) || 1);
  const cap = Math.max(0, Number(roundCap) || 0);
  if (additionalRounds != null) {
    const add = Math.max(0, Number(additionalRounds) || 0);
    return {
      startRound: start,
      endExclusive: start + add,
      remaining: add,
      already: start - 1,
      mode: 'additional-rounds',
    };
  }
  const already = start - 1;
  const remaining = Math.max(0, cap - already);
  return {
    startRound: start,
    endExclusive: start + remaining,
    remaining,
    already,
    mode: 'effort-scoped',
  };
}

/**
 * Dry Shark round with no multi-Shark (≥2-agree) blockers — eligible for the
 * human-lockable streak. Does NOT auto-lock; only informs when to stop burning rounds.
 *
 * @param {{tally: object, dryHeldStreak?: number}} o
 */
export function assessHumanLockable({ tally = null, dryHeldStreak = 0 } = {}) {
  if (!tally || !tally.dry) {
    return { eligible: false, reason: 'round not dry' };
  }
  // blockers on the tally are already multi-agree (shark-tank filters agreement>=2)
  const blockers = Array.isArray(tally.blockers) ? tally.blockers : [];
  if (blockers.length > 0) {
    return { eligible: false, reason: `${blockers.length} multi-Shark BLOCKER(s) still open` };
  }
  const multi = (tally.findings || []).filter((f) =>
    f && !f.demoted && Number(f.agreement) >= 2 &&
    /^(BLOCKER|MAJOR)$/i.test(String(f.severity || '')));
  if (multi.length > 0) {
    return { eligible: false, reason: `${multi.length} multi-agree MAJOR/BLOCKER finding(s) open` };
  }
  return {
    eligible: true,
    reason: 'sharks dry; no ≥2-agree BLOCKER/MAJOR — Judge/fresh-eyes may hold, but multi-Shark bar is met',
    dryHeldStreak,
  };
}

// ---------------------------------------------------------------------------
// The Stage-1 orchestration — brainstorm → triage → phased plan → loop → approve.
// ---------------------------------------------------------------------------

/**
 * Run Stage 1 end-to-end. Requires a LOCKED North Star (the Stage-0 deliverable).
 * Brainstorms (assumption-map → premortem → ideate), batch-triages, builds the phased
 * plan from the integrated ideas, runs the Shark-Tank loop to model-side convergence,
 * then HALTs at the user-approval gate. With approval it returns the approved Master
 * Plan; without it (or on a blocking HALT inside the loop) it HALTs for the human.
 *
 * @param {object} o
 * @param {Function} o.agent                  the Wave-1 agent seam
 * @param {string}   o.northStar              the LOCKED North Star
 * @param {string[]}[o.criteria=[]]
 * @param {?object} [o.research=null]         the Wave-5 coordinator (research once up-front)
 * @param {string[]}[o.acceptanceCriteria=[]] the Judge's oracle
 * @param {boolean} [o.approved=false]        the user's Master-Plan approval
 * @param {number}  [o.roundCap=5]
 * @param {?string} [o.depth=null]            the user-CONFIRMED Stage-0 triage depth
 *                                            ('LITE' shrinks the default roundCap to 2;
 *                                            an explicit roundCap always wins)
 * @param {?string} [o.grasscatcherPath=null] where parked ideas are appended
 * @param {?string} [o.artifactsDir=null]     Shark-Tank round artifacts dir
 * @param {Function}[o.log=()=>{}]
 * @returns {Promise<{brainstorm:object, triage:object, plan:object, loop:object, approval:object}>}
 */
/**
 * P1 2026-07-25 — Stage-1 durability (the 9-death cluster: journals 0020/0021/0023/
 * 0024/0025/0027/0064/0066/0075). Stage-2 got the full lifetime treatment on
 * 2026-07-24 (wave 3 / 0075); Stage-1 — where most of the deaths actually happened —
 * had NO guards, no last-crash.json, no HALT.json, and only one progress stamp
 * (post-triage, from 0065). Mirror of writeStage2HaltJson; best-effort, never throws.
 */
export function writeStage1HaltJson(dir, {
  reason = 'stage1 halted',
  lastStep = null,
  humanLockable = false,
  artifacts = {},
  pendingAction = 'stage1-process-death',
  extra = {},
} = {}) {
  if (!dir) return null;
  try {
    fs.mkdirSync(dir, { recursive: true });
    const payload = {
      skill: 'crucible',
      stage: 1,
      reason: String(reason).slice(0, 2000),
      last_step: lastStep,
      human_lockable: !!humanLockable,
      pending_action: pendingAction,
      artifacts: artifacts && typeof artifacts === 'object' ? artifacts : {},
      pid: process.pid,
      ts: new Date().toISOString(),
      ...extra,
    };
    const haltPath = path.join(dir, 'HALT.json');
    const tmp = `${haltPath}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(payload, null, 2) + '\n', 'utf8');
    fs.renameSync(tmp, haltPath);
    return payload;
  } catch {
    return null;
  }
}

export async function runStage1({
  agent,
  northStar,
  criteria = [],
  research = null,
  acceptanceCriteria = [],
  approved = false,
  roundCap = undefined,
  depth = null,
  /** SPIKE-FIRST: path or string result of the pre-plan probe (Wave D). */
  spikeProbe = null,
  /** When true, allow SPIKE-FIRST without probe (tests only). */
  allowSpikeWithoutProbe = false,
  grasscatcherPath = null,
  artifactsDir = null,
  statusLog = null,
  routes = null,
  log = () => {},
} = {}) {
  requireAgent(agent, 'runStage1');
  if (!northStar) {
    throw new HaltError('runStage1 requires a locked North Star', 'Stage 1 starts from the Stage-0 North-Star lock');
  }
  // cf-slick 2026-07-22: depth → band profile (LITE is real ceremony collapse, not
  // only roundCap 5→2 — journals 0022/0026/0028). Explicit roundCap still wins.
  const band = resolveBandProfile(depth);
  if (roundCap === undefined) roundCap = band.roundCap;
  log(`stage1: depth=${band.depth} → ${band.label} · roundCap=${roundCap} · liteBrainstorm=${band.skipFullOrangesBrainstorm} · sharks=${band.sharkRoles}`);
  log(`stage1: band stamp ${JSON.stringify(bandProfileStamp(band))}`);

  // P1 2026-07-25: full lifetime guards for Stage-1 (the 9-death cluster). Every
  // agent-call boundary stamps progress; process death writes last-crash.json +
  // HALT.json pointing at the durable artifacts — never a silent freeze again.
  const stateDir = artifactsDir ? path.resolve(artifactsDir) : null;
  const progressPath = stateDir ? path.join(stateDir, 'stage1-progress.json') : null;
  const live = { lastStep: 'init' };
  let guards = null;
  if (stateDir) {
    try { fs.mkdirSync(stateDir, { recursive: true }); } catch { /* */ }
    guards = installProcessLifetimeGuards({
      log: (m) => { try { log(m); } catch { /* */ } },
      crashPath: path.join(stateDir, 'last-crash.json'),
      heartbeatPath: path.join(stateDir, 'heartbeat.json'),
      label: 'crucible-stage1',
      onFatal: (payload) => {
        try {
          const bestDraft = path.join(stateDir, 'BEST-DRAFT.md');
          writeStage1HaltJson(stateDir, {
            reason: `process death (${payload?.kind || 'fatal'}): ${String(payload?.message || '').slice(0, 400)}`,
            lastStep: live.lastStep,
            humanLockable: fs.existsSync(bestDraft),
            artifacts: {
              last_crash: path.join(stateDir, 'last-crash.json'),
              progress: progressPath,
              best_draft: fs.existsSync(bestDraft) ? bestDraft : null,
              triage: fs.existsSync(path.join(stateDir, 'stage1-triage.json'))
                ? path.join(stateDir, 'stage1-triage.json') : null,
            },
          });
        } catch { /* never crash the crash handler */ }
      },
    });
  }
  const phased = (phase, fn) => {
    live.lastStep = phase;
    return withPhaseProgress({ phase: `stage1-${phase}`, log, progressPath, guards, fn });
  };

  // SPIKE-FIRST mid path: probe before plan ceremony (cf-slick Wave D).
  if (band.requireSpikeProbe && !allowSpikeWithoutProbe) {
    const raw = spikeProbe != null ? String(spikeProbe).trim() : '';
    if (!raw) {
      throw haltForHuman(
        'SPIKE-FIRST band requires a spikeProbe (existing file path or multi-line findings, ≥40 chars) before Stage-1 — ' +
          'run a bounded probe, record the result, then re-invoke (or re-band to LITE/FULL).',
        'stage1-spike-probe-required',
      );
    }
    // Path-like: must exist. Short string "ok" is rejected (Shark: probe theater).
    const pathLike = /[\\/]|\.md$|\.txt$|\.json$/i.test(raw) || raw.length < 200;
    if (pathLike && (raw.includes('\\') || raw.includes('/') || /\.(md|txt|json)$/i.test(raw))) {
      try {
        if (!fs.existsSync(path.resolve(raw))) {
          throw haltForHuman(
            `SPIKE-FIRST spikeProbe path does not exist: ${raw}`,
            'stage1-spike-probe-required',
          );
        }
      } catch (e) {
        if (e && e.halt_for_human) throw e;
        throw haltForHuman(`SPIKE-FIRST spikeProbe path unreadable: ${raw}`, 'stage1-spike-probe-required');
      }
    } else if (raw.length < 40) {
      throw haltForHuman(
        'SPIKE-FIRST spikeProbe string is too short to be a real probe result (min 40 chars) — refuse probe theater.',
        'stage1-spike-probe-required',
      );
    }
    log(`stage1: SPIKE probe accepted (${raw.slice(0, 120)})`);
  }

  // researchPrime ONCE up-front when the band asks for it (LITE skips by default).
  if (band.researchUpfront && research && typeof research.upfront === 'function') {
    await research.upfront({ northStar });
  }
  const upfrontBrief = research?.forSynthesizer?.() ?? null;

  // (1) Oranges brainstorm — FULL order, or LITE single-pass. (0066's death was
  // PRE-assumption-map — earlier than the one 0065 stamp covered — so every
  // agent-call boundary is now wrapped.)
  const brainstorm = await phased('oranges-brainstorm', () => runBrainstorm({
    agent, northStar, criteria, research: upfrontBrief, log,
    lite: !!band.skipFullOrangesBrainstorm,
  }));

  // (2) Batch idea-triage — the plan absorbs ONLY the integrated bucket.
  const triage = triageIdeas({ ideas: brainstorm.ideas, grasscatcherPath, log });

  // F-H sleep fix (0064/F042–F045): durable progress stamp AFTER Oranges + triage and
  // BEFORE the long phased-plan agent call (observed kill window). If the process dies
  // mid-draft, operators see stage1-progress.json + last log line, not a silent freeze.
  if (artifactsDir) {
    try {
      fs.mkdirSync(artifactsDir, { recursive: true });
      const progress = {
        phase: 'post-triage',
        ts: new Date().toISOString(),
        integrate: triage.integrate?.length ?? 0,
        grasscatcher: triage.grasscatcher?.length ?? 0,
        dropped: triage.dropped?.length ?? 0,
        next: 'buildPhasedPlan',
      };
      const pPath = path.join(artifactsDir, 'stage1-progress.json');
      const tmp = `${pPath}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(progress, null, 2) + '\n', 'utf8');
      fs.renameSync(tmp, pPath);
      fs.writeFileSync(
        path.join(artifactsDir, 'stage1-triage.json'),
        JSON.stringify({
          integrate: triage.integrate,
          grasscatcher: triage.grasscatcher,
          dropped: triage.dropped,
        }, null, 2) + '\n',
        'utf8',
      );
      log(`stage1: durable progress stamped (post-triage → phased-plan; integrate=${progress.integrate})`);
    } catch (e) {
      log(`!! stage1 progress stamp failed (non-fatal): ${e?.message || e}`);
    }
  }
  log(`stage1: building phased plan from ${triage.integrate?.length ?? 0} integrated idea(s)…`);

  // (3) The phased plan from the integrated ideas.
  let plan;
  try {
    plan = await phased('phased-plan', () => buildPhasedPlan({
      agent, northStar, criteria,
      ideas: triage.integrate, assumptions: brainstorm.assumptions, premortem: brainstorm.premortem, log,
    }));
    if (artifactsDir) {
      try {
        const pPath = path.join(artifactsDir, 'stage1-progress.json');
        fs.writeFileSync(pPath, JSON.stringify({
          phase: 'phased-plan-done',
          ts: new Date().toISOString(),
          phases: plan?.phases?.length ?? 0,
          next: 'master-plan-loop',
        }, null, 2) + '\n', 'utf8');
      } catch { /* best-effort */ }
    }
  } catch (e) {
    if (artifactsDir) {
      try {
        fs.writeFileSync(path.join(artifactsDir, 'stage1-progress.json'), JSON.stringify({
          phase: 'phased-plan-error',
          ts: new Date().toISOString(),
          error: String(e?.message || e).slice(0, 800),
        }, null, 2) + '\n', 'utf8');
      } catch { /* best-effort */ }
    }
    log(`!! stage1 phased-plan failed: ${e?.message || e}`);
    throw e;
  }

  // (4) The Shark-Tank loop to model-side convergence.
  const loop = await phased('shark-loop', () => runMasterPlanLoop({
    agent, northStar, criteria,
    draft: renderMasterPlanDraft(plan),
    research, acceptanceCriteria, roundCap, artifactsDir, log,
    sharkRoles: band.sharkRoles,
    statusLog, statusLabel: `Crucible Stage 1 (${band.depth})`,
    routes,
  }));

  // (5) The user-approval HALT gate (master-plan-approval).
  live.lastStep = 'approval';
  const approval = approveMasterPlan({ loop, plan, approved, log });

  return { brainstorm, triage, plan, loop, approval, band: bandProfileStamp(band) };
}

// ---------------------------------------------------------------------------
// Shared guard.
// ---------------------------------------------------------------------------

function requireAgent(agent, who) {
  if (typeof agent !== 'function') {
    throw new HaltError(`${who} requires an agent() function`, `pass the Wave-1 seam: ${who}({ agent: makeAgentSeam(...).agent })`);
  }
}
