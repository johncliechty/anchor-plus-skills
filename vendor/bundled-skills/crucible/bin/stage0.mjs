// stage0.mjs — Crucible's Stage 0: Intake & Framing (Wave 6).
//
// Stage 0 turns a raw intent (greenfield) or a messy existing project (brownfield)
// into a CANDIDATE North Star the user then confirms/edits and LOCKS (MASTER-PLAN
// §4/§5). It is the single most reliable anti-drift mechanism: drift detection
// begins ONLY after the lock (§9), so getting the candidate right here is load-
// bearing. Two paths, both ending at the North-Star-lock HALT gate:
//
//   GREENFIELD — an Oranges-style framing pass (the Parable of the Oranges, §3b):
//     probe for the REAL goal, bring best-in-class expertise, think 2–3 steps ahead,
//     show the receipt. Produces a candidate North Star + testable criteria +
//     Non-Goals + a risk taxonomy + a foresight brief.
//
//   BROWNFIELD — a TIERED ingest (§5) that SCALES TO THE INPUT (the inclusion test),
//     then framing reverse-engineers the candidate North Star from the AS-IS:
//       · Tier 1 (docs/notes only, default): inventory & DEDUPE conflicting plan
//         versions → latest truth; a manifest in plans/intake/. No archaeology.
//       · Tier 2 (has a repo): + a DONE-VS-CLAIMED read — reproduce-first (does it
//         build/run?) + a test-coverage sweep (no test ⇒ label Inferred-untested,
//         never Confirmed).
//       · Tier 3 (large/contested): DELEGATE deep archaeology to a researchPrime lane
//         (Crucible CALLS Wave-5's research coordinator, never re-implements the
//         16-step pipeline).
//
// Throughout, every ingest item carries a Confirmed / Inferred / Gap label that
// GATES (§5): a Gap touching a North-Star criterion BLOCKS the lock; an irresolvable
// or people-only Gap HALTs at the checkpoint (it does NOT silently become a RAID
// assumption). salvage-vs-rewrite is a USER-answered gate question — Crucible
// surfaces the facts/trade-offs but NEVER scores it (it lacks the org facts; the
// common "40%" rewrite heuristic is UNVERIFIED).
//
// REUSE, NOT REINVENT: framing/ingest reach models through the Wave-1 `agent()`
// seam; Tier-3 archaeology reaches researchPrime through Wave-5's coordinator; the
// lock reuses crucible-lib's `haltForHuman` + the canonical `HALT_GATES` entry, so
// stage0's lock and the engine's state-machine boundary agree on the gate name.

import fs from 'node:fs';
import path from 'node:path';

import { HaltError, haltForHuman, HALT_GATES } from './crucible-lib.mjs';

// ---------------------------------------------------------------------------
// Complexity triage (C3) — FIRST step of Stage 0.
//
// Phase-1 wire (2026-07-22): body lives in @foundry/triage crucible-wire so
// recommend() is the single rubric. This module injects HaltError via
// haltForHuman and re-exports the legacy COMPLEXITY_BANDS tokens for tests.
// ---------------------------------------------------------------------------

import { importFoundryTriage } from '../../drivers/foundry-triage-resolve.mjs';
const {
  assessComplexity: wireAssessComplexity,
  COMPLEXITY_BANDS: WIRE_COMPLEXITY_BANDS,
  resolveStage0TriageLock,
  NS01_WAVE3_STAMP,
} = await importFoundryTriage('crucible-wire.mjs');

export const COMPLEXITY_BANDS = WIRE_COMPLEXITY_BANDS;
export { resolveStage0TriageLock, NS01_WAVE3_STAMP };

/**
 * Stage-0 complexity triage — delegates to @foundry/triage crucible-wire.
 * @param {object} [intake]
 * @returns {{band:string, depth:string, rationale:string, defaultedToFull:boolean,
 *            signals:object, halt:HaltError, nsTier?:string, nsDepth?:string}}
 */
export function assessComplexity(intake = {}) {
  return wireAssessComplexity(intake, { haltForHuman });
}

// ---------------------------------------------------------------------------
// Tier selection — scale the ingest to the input (the inclusion test, §5).
// ---------------------------------------------------------------------------

export const TIERS = {
  GREENFIELD: 'greenfield',
  TIER1: 'tier1',
  TIER2: 'tier2',
  TIER3: 'tier3',
};

/**
 * Choose the Stage-0 path from the input. Greenfield (no existing project) skips
 * ingest entirely. Brownfield picks the lightest tier that fits, by §5's precedence:
 * large/contested ⇒ Tier 3 (delegate archaeology); else a repo ⇒ Tier 2 (reproduce +
 * coverage); else docs/notes only ⇒ Tier 1 (inventory & dedupe, NO archaeology).
 *
 * @param {object} [input]
 * @param {string} [input.kind]        'greenfield' | 'brownfield' (else inferred)
 * @param {string} [input.repoDir]     a brownfield project repo (⇒ at least Tier 2)
 * @param {string} [input.projectDir]  alias for repoDir
 * @param {Array}  [input.docs]        docs/notes (⇒ Tier 1 when no repo)
 * @param {boolean}[input.large]       large codebase (⇒ Tier 3)
 * @param {boolean}[input.contested]   conflicting/contested history (⇒ Tier 3)
 * @returns {{tier:string, reason:string}}
 */
export function selectTier(input = {}) {
  const inp = input || {};
  const hasProject = !!(inp.repoDir || inp.projectDir || inp.docs || inp.brownfield);
  const greenfield = inp.kind === 'greenfield' || (inp.kind !== 'brownfield' && !hasProject);
  if (greenfield) {
    return { tier: TIERS.GREENFIELD, reason: 'no existing project — greenfield Oranges framing only (no ingest)' };
  }
  if (inp.large || inp.contested) {
    return { tier: TIERS.TIER3, reason: 'large/contested brownfield — delegate deep archaeology to a researchPrime lane (Tier 3)' };
  }
  if (inp.repoDir || inp.projectDir) {
    return { tier: TIERS.TIER2, reason: 'brownfield with a repo — reproduce-first + test-coverage done-vs-claimed (Tier 2)' };
  }
  return { tier: TIERS.TIER1, reason: 'docs/notes only — inventory & dedupe to latest truth (Tier 1, no archaeology)' };
}

// ---------------------------------------------------------------------------
// Greenfield framing — the Oranges pass. Every prompt is North-Star-bound by
// construction (it PRODUCES the candidate North Star).
// ---------------------------------------------------------------------------

/** The candidate framing the user will confirm/edit and lock (a proposal, never decided here). */
export const FRAMING_SCHEMA = {
  type: 'object',
  required: ['northStar', 'criteria'],
  properties: {
    northStar: { type: 'string' },
    criteria: { type: 'array', items: { type: 'string' } },
    nonGoals: { type: 'array', items: { type: 'string' } },
    riskTaxonomy: {
      type: 'array',
      items: {
        type: 'object',
        properties: { risk: { type: 'string' }, mitigation: { type: 'string' } },
      },
    },
    foresightBrief: { type: 'string' },
  },
};

function framingPrompt({ intent, asIs = null }) {
  return [
    `You are the Crucible STAGE-0 framing pass, in the spirit of the Parable of the Oranges:`,
    `do NOT plan the literal request — probe for the REAL goal, bring best-in-class expertise,`,
    `think 2–3 steps ahead, add justified value, and show the receipt. Produce a CANDIDATE`,
    `North Star: a PROPOSAL the user will confirm/edit and LOCK. You steer; you do not decide it.`,
    ``,
    `=== THE INTENT ===`,
    String(intent ?? '(none)'),
    `=== END INTENT ===`,
    asIs
      ? `\n=== AS-IS (reverse-engineered from the existing project) ===\n${typeof asIs === 'string' ? asIs : JSON.stringify(asIs, null, 2)}\n=== END AS-IS ===`
      : '',
    ``,
    `Emit: northStar (one crisp sentence — the real outcome, not the literal ask),`,
    `criteria (TESTABLE success criteria), nonGoals (what this is explicitly NOT),`,
    `riskTaxonomy [{risk, mitigation}], foresightBrief (what will be needed 2–3 steps`,
    `downstream — the auth wall, the data to capture now).`,
  ].join('\n');
}

/**
 * Run the framing pass and return the normalized candidate framing. Greenfield when
 * `asIs` is null; brownfield framing passes the AS-IS so the North Star is
 * reverse-engineered from it (§4). HALTs if no candidate North Star comes back —
 * a framing pass that yields nothing to lock is a wiring failure, not a silent pass.
 *
 * @param {object} o
 * @param {Function} o.agent              the Wave-1 agent seam
 * @param {string}   o.intent
 * @param {?(string|object)} [o.asIs=null]  the brownfield ingest manifest (reverse-engineering)
 * @param {Function} [o.log=()=>{}]
 */
export async function runFraming({ agent, intent, asIs = null, log = () => {} } = {}) {
  if (typeof agent !== 'function') {
    throw new HaltError('runFraming requires an agent() function', 'pass the Wave-1 seam: runFraming({ agent })');
  }
  const out = (await agent(framingPrompt({ intent, asIs }), { label: 'stage0:framing', schema: FRAMING_SCHEMA })) || {};
  if (!out.northStar) {
    throw haltForHuman('Stage-0 framing produced no candidate North Star', 'rerun-framing');
  }
  const framing = {
    northStar: out.northStar,
    criteria: Array.isArray(out.criteria) ? out.criteria : [],
    nonGoals: Array.isArray(out.nonGoals) ? out.nonGoals : [],
    riskTaxonomy: Array.isArray(out.riskTaxonomy) ? out.riskTaxonomy : [],
    foresightBrief: out.foresightBrief ?? '',
    reverseEngineered: !!asIs, // brownfield framing is reverse-engineered from the AS-IS
  };
  log(
    `stage0 framing: candidate North Star + ${framing.criteria.length} criteri${framing.criteria.length === 1 ? 'on' : 'a'}, ` +
      `${framing.riskTaxonomy.length} risk(s)${framing.reverseEngineered ? ' (reverse-engineered)' : ''}`,
  );
  return framing;
}

// ---------------------------------------------------------------------------
// Tiered brownfield ingest (§5). Confirmed / Inferred / Gap labels that GATE.
// ---------------------------------------------------------------------------

export const INGEST_LABELS = { CONFIRMED: 'Confirmed', INFERRED: 'Inferred', GAP: 'Gap' };

/** What the inventory sub-agent returns — items carrying the gating label. */
export const INGEST_SCHEMA = {
  type: 'object',
  required: ['items'],
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        required: ['label'],
        properties: {
          id: { type: 'string' },
          fact: { type: 'string' },
          label: { enum: ['Confirmed', 'Inferred', 'Gap'] },
          // A Gap's gating attributes (§5): does it touch a North-Star criterion, and
          // is it resolvable or a people-only question?
          touchesCriterion: { type: ['boolean', 'string'] },
          resolvable: { type: 'boolean' },
          peopleOnly: { type: 'boolean' },
          // For the Tier-2 coverage sweep: is this claim backed by a test?
          tested: { type: ['boolean', 'null'] },
          note: { type: 'string' },
        },
      },
    },
    // Tier 1 dedupe: the conflicting plan versions seen, so the manifest records why
    // a "latest truth" was chosen.
    versions: { type: 'array', items: { type: 'string' } },
  },
};

/** The Tier-2 reproduce-first probe: does the project actually build/run? */
export const REPRODUCE_SCHEMA = {
  type: 'object',
  properties: {
    reproduces: { type: ['boolean', 'null'] },
    note: { type: 'string' },
  },
};

function inventoryPrompt({ input, tier }) {
  return [
    `You are the Crucible STAGE-0 brownfield ingest (${tier}). Inventory the existing`,
    `project and, where multiple plan versions conflict, DEDUPE to the LATEST TRUTH.`,
    `Label EVERY item Confirmed / Inferred / Gap, honestly:`,
    `  · Confirmed = directly evidenced (and, where code is involved, test-backed).`,
    `  · Inferred  = reasonable but unverified (e.g. claimed-but-untested code).`,
    `  · Gap       = unknown/missing. For each Gap also state: touchesCriterion (does it`,
    `    bear on a North-Star success criterion?), resolvable, peopleOnly (only a person`,
    `    can answer it — an org fact Crucible cannot infer).`,
    `Do NOT turn a Gap into a silent assumption.`,
    ``,
    `=== THE INPUT ===`,
    JSON.stringify(input ?? {}, null, 2),
    `=== END INPUT ===`,
    ``,
    `Emit: items [{id, fact, label, touchesCriterion?, resolvable?, peopleOnly?, tested?}],`,
    `versions (the conflicting plan versions you deduped).`,
  ].join('\n');
}

function reproducePrompt({ projectDir }) {
  return [
    `You are the Crucible STAGE-0 Tier-2 DONE-VS-CLAIMED probe. REPRODUCE FIRST: does the`,
    `project at the path below actually build/run? Running/tested code is the only thing`,
    `that earns "Confirmed"; a claim with no test is at most "Inferred-untested".`,
    ``,
    `=== PROJECT ===`,
    String(projectDir ?? '(none)'),
    `=== END PROJECT ===`,
    ``,
    `Emit: reproduces (true|false|null), note.`,
  ].join('\n');
}

/**
 * Run the tiered brownfield ingest and return a manifest of Confirmed/Inferred/Gap
 * items (written to `intakeDir` when supplied — `plans/intake/`).
 *
 *   T1: inventory + dedupe.
 *   T2: T1 + reproduce-first; any Confirmed-but-untested item is downgraded to
 *       Inferred ("Inferred-untested") — running/tested code earns Confirmed (§5).
 *   T3: T1/T2 + DELEGATE deep archaeology to the researchPrime lane (Wave 5); its
 *       findings fold in as Inferred items.
 *
 * @param {object} o
 * @param {string}   o.tier                  TIERS.TIER1|TIER2|TIER3
 * @param {object}  [o.input={}]
 * @param {Function} o.agent                 the Wave-1 agent seam
 * @param {?object} [o.research=null]        the Wave-5 coordinator (required for Tier 3)
 * @param {?string} [o.intakeDir=null]       where the manifest is written (plans/intake/)
 * @param {Function}[o.log=()=>{}]
 */
export async function runIngest({ tier, input = {}, agent, research = null, intakeDir = null, log = () => {} } = {}) {
  if (typeof agent !== 'function') {
    throw new HaltError('runIngest requires an agent() function', 'pass the Wave-1 seam: runIngest({ agent })');
  }
  if (tier === TIERS.GREENFIELD) {
    throw new HaltError('runIngest is brownfield-only', 'greenfield has no ingest — call runFraming directly');
  }
  const projectDir = input.repoDir || input.projectDir || null;

  // T1 (and the base of every higher tier): inventory & dedupe → labeled items.
  const inv = (await agent(inventoryPrompt({ input, tier }), { label: `stage0:ingest:${tier}:inventory`, schema: INGEST_SCHEMA })) || {};
  let items = Array.isArray(inv.items) ? inv.items.map((i) => ({ ...i })) : [];
  const versions = Array.isArray(inv.versions) ? inv.versions : [];

  // T2/T3: reproduce-first + test-coverage sweep. A Confirmed item with no test is
  // downgraded to Inferred — no test, no Confirmed.
  let reproduces = null;
  if (tier === TIERS.TIER2 || tier === TIERS.TIER3) {
    const rep = (await agent(reproducePrompt({ projectDir }), { label: `stage0:ingest:${tier}:reproduce`, schema: REPRODUCE_SCHEMA })) || {};
    reproduces = typeof rep.reproduces === 'boolean' ? rep.reproduces : null;
    items = items.map((i) =>
      i.label === INGEST_LABELS.CONFIRMED && i.tested === false
        ? { ...i, label: INGEST_LABELS.INFERRED, note: 'Inferred-untested (no test backs this claim)' }
        : i,
    );
  }

  // T3: DELEGATE deep archaeology to researchPrime (Crucible calls, never re-implements).
  let archaeologyRun = false;
  if (tier === TIERS.TIER3) {
    if (!research || typeof research.deepArchaeology !== 'function') {
      throw new HaltError(
        'Tier-3 ingest requires the researchPrime deep-archaeology lane',
        'pass research: makeResearch(...) so Stage 0 can delegate the deep dive (it never re-implements the pipeline)',
      );
    }
    const dig = (await research.deepArchaeology({ projectDir })) || {};
    archaeologyRun = !!dig.invoked;
    for (const f of dig.findings || []) {
      items.push({
        id: f.id || `arch:${items.length}`,
        fact: f.claim || '',
        label: INGEST_LABELS.INFERRED, // archaeology findings are evidence, not ground truth
        source: f.source || 'researchPrime',
        from: 'tier3-archaeology',
      });
    }
  }

  const manifest = {
    tier,
    brownfield: true,
    projectDir,
    versions,
    items,
    reproduces,
    archaeologyRun,
    generatedFrom: 'stage0:ingest',
  };
  manifest.manifestPath = intakeDir ? writeIntakeManifest(intakeDir, manifest) : null;
  log(
    `stage0 ingest ${tier}: ${items.length} item(s)` +
      `${reproduces != null ? `, reproduces=${reproduces}` : ''}` +
      `${archaeologyRun ? ', archaeology delegated' : ''}`,
  );
  return manifest;
}

/** Write the intake manifest to `intakeDir/manifest.json` (creating the dir); returns the path. */
export function writeIntakeManifest(intakeDir, manifest) {
  if (!intakeDir) throw new HaltError('writeIntakeManifest requires an intakeDir', 'pass plans/intake/');
  fs.mkdirSync(intakeDir, { recursive: true });
  const p = path.join(intakeDir, 'manifest.json');
  fs.writeFileSync(p, JSON.stringify(manifest, null, 2));
  return p;
}

// ---------------------------------------------------------------------------
// The Confirmed/Inferred/Gap gate (§5) — labels that actually GATE the lock.
// ---------------------------------------------------------------------------

/**
 * Evaluate the ingest labels against the lock. Two kinds of Gap block (§5):
 *   · a Gap TOUCHING a North-Star criterion blocks the lock, and
 *   · an IRRESOLVABLE or PEOPLE-ONLY Gap HALTs at the checkpoint (it must not
 *     silently become a RAID assumption).
 * Either kind ⇒ not lockable, carrying a HALT the caller throws.
 *
 * @param {object} o
 * @param {object[]} [o.items=[]]
 * @param {boolean}  [o.brownfield=true]   tags the result so the lock knows a salvage answer is owed
 * @returns {{lockable:boolean, brownfield:boolean, blocking:object[],
 *            criterionGaps:object[], irresolvableGaps:object[], halt:?HaltError}}
 */
export function evaluateIngestGate({ items = [], brownfield = true } = {}) {
  const gaps = (items || []).filter((i) => i && i.label === INGEST_LABELS.GAP);
  const criterionGaps = gaps.filter((g) => !!g.touchesCriterion);
  const irresolvableGaps = gaps.filter((g) => g.resolvable === false || g.peopleOnly === true);
  const blocking = [...new Set([...criterionGaps, ...irresolvableGaps])];
  const lockable = blocking.length === 0;

  let halt = null;
  if (!lockable) {
    const reasons = [];
    if (criterionGaps.length) reasons.push(`${criterionGaps.length} Gap(s) touch a North-Star criterion`);
    if (irresolvableGaps.length) reasons.push(`${irresolvableGaps.length} irresolvable/people-only Gap(s)`);
    // The pending action distinguishes the two HALT reasons so the orchestrator can
    // re-prompt precisely (resolve the criterion gap vs surface a people-only gap).
    const pending = criterionGaps.length ? 'resolve-criterion-gap' : 'surface-people-only-gap';
    halt = haltForHuman(
      `Stage 0 cannot lock: ${reasons.join('; ')} — a criterion-touching Gap blocks the lock; ` +
        `an irresolvable/people-only Gap HALTs rather than becoming a silent RAID assumption`,
      pending,
    );
  }
  return { lockable, brownfield, blocking, criterionGaps, irresolvableGaps, halt };
}

// ---------------------------------------------------------------------------
// salvage-vs-rewrite — a USER gate question, NEVER scored (§5).
// ---------------------------------------------------------------------------

/** A compact Confirmed/Inferred/Gap tally for the salvage question's surfaced facts. */
function summarizeAsIs(asIs) {
  const items = (asIs && Array.isArray(asIs.items)) ? asIs.items : [];
  const tally = { Confirmed: 0, Inferred: 0, Gap: 0 };
  for (const i of items) if (tally[i?.label] != null) tally[i.label] += 1;
  return {
    confirmed: tally.Confirmed,
    inferred: tally.Inferred,
    gaps: tally.Gap,
    reproduces: asIs?.reproduces ?? null,
  };
}

/**
 * Build the salvage-vs-rewrite question. It is a USER decision: Crucible surfaces the
 * facts/trade-offs but NEVER scores it (it lacks the org facts; the common "40%"
 * rewrite heuristic is UNVERIFIED). The returned object is explicit about that —
 * `scored:false` is part of the contract the lock checks.
 */
export function salvageVsRewriteQuestion({ asIs = null } = {}) {
  return {
    kind: 'user-gate-question',
    scored: false, // NEVER scored by Crucible
    question:
      'Salvage the existing implementation, or rewrite from scratch? This is your call — ' +
      'Crucible surfaces the facts and trade-offs but does not score it.',
    facts: summarizeAsIs(asIs),
    note:
      'Crucible never scores salvage-vs-rewrite (it lacks the org facts; the common "40%" ' +
      'rewrite heuristic is UNVERIFIED). Decide, then pass salvageAnswer to lock.',
  };
}

// ---------------------------------------------------------------------------
// The North-Star-lock HALT gate. Drift detection begins AFTER this (§9).
// ---------------------------------------------------------------------------

/**
 * The Stage-0 → Stage-1 lock gate. It HALTs (rather than locking) when:
 *   1. the ingest labels block (a criterion-touching or irresolvable/people-only Gap),
 *   2. brownfield and the salvage-vs-rewrite question is unanswered (a user decision),
 *   3. the user has not yet approved the lock — the user is the convergence authority.
 * Only with a clean gate + an answered salvage question (brownfield) + approval does it
 * lock and report `driftDetectionActive:true` (drift detection starts here, not before).
 *
 * Reuses the canonical `HALT_GATES['stage0->stage1']` entry, so this lock and the
 * engine's state-machine boundary name the SAME gate ('north-star-lock').
 *
 * @param {object} o
 * @param {object}   o.framing                       the candidate framing (must carry a northStar)
 * @param {?object} [o.ingestGate=null]              evaluateIngestGate() result (brownfield)
 * @param {?string} [o.salvageAnswer=null]           the user's salvage-vs-rewrite answer (brownfield)
 * @param {boolean} [o.approved=false]               the user's lock approval
 * @param {Function}[o.log=()=>{}]
 * @returns {{locked:true, gate:string, northStar:string, criteria:string[], driftDetectionActive:true}}
 */
export function lockNorthStar({ framing, ingestGate = null, salvageAnswer = null, approved = false, log = () => {} } = {}) {
  if (!framing || !framing.northStar) {
    throw new HaltError('lockNorthStar requires a candidate North Star', 'run framing first (runFraming)');
  }
  // 1. Confirmed/Inferred/Gap labels gate FIRST — a blocking Gap HALTs.
  if (ingestGate && !ingestGate.lockable) {
    log('stage0 lock: ingest labels block the lock — HALT');
    throw ingestGate.halt;
  }
  // 2. salvage-vs-rewrite is a user decision — brownfield must answer before locking.
  if (ingestGate && ingestGate.brownfield && !salvageAnswer) {
    throw haltForHuman(
      'salvage-vs-rewrite is a user-answered gate question — Crucible surfaces the facts/trade-offs but never scores it',
      'salvage-vs-rewrite',
    );
  }
  // 3. The North-Star lock is itself a you-approve HALT gate.
  const gate = HALT_GATES['stage0->stage1'];
  if (!approved) {
    log('stage0 lock: framing ready — HALT for the user to lock the North Star');
    throw haltForHuman(gate.reason, gate.name);
  }
  log('stage0 lock: North Star LOCKED — drift detection is now active');
  return {
    locked: true,
    gate: gate.name,
    northStar: framing.northStar,
    criteria: framing.criteria ?? [],
    driftDetectionActive: true, // §9: drift detection begins AFTER the lock
  };
}

// ---------------------------------------------------------------------------
// The Stage-0 orchestration — framing/ingest → labels gate → lock.
// ---------------------------------------------------------------------------

/**
 * Run Stage 0 end-to-end. Greenfield: frame → lock. Brownfield: tiered ingest →
 * reverse-engineered framing → labels gate → salvage question → lock. The lock is a
 * HALT gate: without approval (or with a blocking Gap / unanswered salvage question)
 * it HALTs, after the framing/ingest artifacts have been persisted for the human to
 * review. With approval and a clean gate it returns the locked result.
 *
 * @param {object} o
 * @param {string}   o.intent
 * @param {object}  [o.input={}]              the tier-selection input
 * @param {Function} o.agent                  the Wave-1 agent seam
 * @param {?object} [o.research=null]         the Wave-5 coordinator (Tier 3)
 * @param {?string} [o.intakeDir=null]        plans/intake/
 * @param {?string} [o.salvageAnswer=null]    the user's salvage-vs-rewrite answer (brownfield)
 * @param {boolean} [o.approved=false]        the user's lock approval
 * @param {Function}[o.log=()=>{}]
 * @returns {{tier:string, greenfield:boolean, framing:object, ingest:?object,
 *            ingestGate:?object, salvage:?object, lock:object}}
 */
export async function runStage0({
  intent,
  input = {},
  agent,
  research = null,
  intakeDir = null,
  salvageAnswer = null,
  approved = false,
  log = () => {},
} = {}) {
  // NS-01 completion (2026-08-25, John-ratified card; journal 0087): Stage-0 SIZES THE
  // JOB ITSELF, first line of the run — the band AUTO-APPLIES and ANNOUNCES itself,
  // never asks (a confirm question would be a fourth gate; Elegance rule 3 — the wire's
  // confirm-halt is deliberately not thrown). An unsizable intake defaults FULL LOUDLY,
  // so 0087's silent-FULL tax on small work cannot recur unseen.
  const triage = assessComplexity({ intent, ...(input || {}) });
  if (triage.defaultedToFull) {
    log(`stage0 band: FULL (DEFAULTED — triage could not size this intake: ${triage.rationale || 'no sizing signals'}) — auto-applied, announced not asked`);
  } else {
    log(`stage0 band: ${triage.band} (auto — ${triage.rationale || 'triage recommendation'}; tier=${triage.nsTier}) — auto-applied, announced not asked`);
  }
  // 2026-08-25 hardening (review finding): the auto-band must also CREATE THE LOCK
  // RECORD — Stage-2's handoff emit fail-closes on a missing lock, so an auto-banded
  // run would poison the Foreman handoff downstream. The lock records the auto-apply
  // honestly (decision=confirm of the shared recommendation; rationale carries AUTO).
  try {
    const locked = resolveStage0TriageLock({
      complexity: triage,
      confirmedDepth: triage.nsDepth,
      confirmedTier: triage.nsTier,
      decision: 'confirm',
      rationale: `stage0 AUTO-BAND (announced, not asked; Elegance rule 3): ${triage.rationale || 'shared triage recommendation'}`,
    });
    triage.lock = locked.lock;
  } catch (e) {
    log(`stage0 band: lock record NOT created (${e?.message || e}) — handoff emit will refuse until a lock exists (fail-closed, loud)`);
  }

  const sel = selectTier(input);
  const greenfield = sel.tier === TIERS.GREENFIELD;
  log(`stage0: ${sel.tier} — ${sel.reason}`);

  let ingest = null;
  let ingestGate = null;
  let salvage = null;
  let asIs = null;
  if (!greenfield) {
    ingest = await runIngest({ tier: sel.tier, input, agent, research, intakeDir, log });
    asIs = ingest;
    ingestGate = evaluateIngestGate({ items: ingest.items, brownfield: true });
    salvage = salvageVsRewriteQuestion({ asIs: ingest }); // a USER question, never scored
  }

  const framing = await runFraming({ agent, intent, asIs, log });

  // The lock gate — HALTs on a blocking Gap, an unanswered salvage question, or
  // (the normal path) for the user to lock. Drift detection begins after it.
  const lock = lockNorthStar({ framing, ingestGate, salvageAnswer, approved, log });

  // `triage` rides the result so launchers route stage1/stage2 depth from the engine's
  // own sizing (triage.depth) instead of a hand-set value — never a second rubric.
  return { tier: sel.tier, greenfield, framing, ingest, ingestGate, salvage, lock, triage };
}
