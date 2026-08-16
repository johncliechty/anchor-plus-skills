/**
 * THE CONVERSATIONAL STEWARD (2026-08-04).
 *
 * WHY THIS MODULE EXISTS. The chamber compiled talk through ELEVEN closed acts matched by
 * regex (`dialogue.mjs` ACT_TABLE). Free-form speech matched none of them, so describing a
 * project — the one thing North Star SC1 says must produce a scaffolding — dead-ended on
 * "Ecgberht could not compile that to a closed act". The scaffolding path added later
 * (`deriveStagesFromDictation`) kept ones opening with a verb from a CLOSED LIST, which
 * returns 0 stages on John's real writing (his verbs are revise/keep/integrate/replace/
 * open/add/refresh). Widening the list just moves the failure to the next project.
 *
 * THE DESIGN ERROR IT FIXES. Two invariants drove the original build and BOTH ARE GOOD:
 *   E5 — chat is NEVER persisted (Strip receipts + roadmap events + Face are the sole ledger)
 *   the steward never invents — unknown is spoken as unknown; nothing written unconfirmed
 * The implementation conflated "don't persist chat" with "don't use a model to understand
 * what he said". Those are ORTHOGONAL. A model can hold the conversation and propose
 * structure while only confirmed receipts persist. This module is that separation.
 *
 * HOW THE CONVERSATION HOLDS TOGETHER ACROSS TURNS — without a chat ledger. The bridge is
 * spawned fresh per request and dies, so turn 2 would know nothing of turn 1. Three sources
 * rebuild the context each turn, and NONE of them is a persisted transcript:
 *   1. the open `scaffold_proposal` event on the spine — the scaffolding-so-far. It is
 *      already an admitted spine kind, so a re-proposal is normal history, not a restart.
 *   2. the ephemeral turns the CALLER holds in memory (browser page / test) and replays.
 *      They die with the session and are asserted never to reach an event.
 *   3. Face + roadmap projection + Strip — the campaign itself.
 *
 * WHAT STAYS DETERMINISTIC. The control verbs — carry on / park that / confirm commission /
 * switch seat — still compile through the closed act table. A model must NEVER decide to
 * spend or to write. Everything else John says goes to the seat.
 *
 * ENGINE LAW: nothing under engine/ may import child_process or call spawn*(). The seat
 * call arrives as an INJECTED `seatCall` hook; the real transport lives in
 * scripts/seat-call.mjs, outside engine/.
 *
 * Stdlib only. No host-absolute user homes in shipped strings.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  compileUtterance,
  ACT_TABLE,
  matchesDestructive,
} from './dialogue.mjs';
import { SPELLING } from './verbs.mjs';
import { loadProjectSurfaces, FACE_FILE_NAME } from './face-strip.mjs';
import { loadProjectRoadmap } from './roadmap.mjs';
import {
  proposeScaffolding,
  findOpenScaffoldProposal,
  DEFAULT_ORANGES_PROMPTS,
  requireProjectFace,
} from './scaffolding.mjs';
import {
  debitSessionEnvelope,
  readEnvelopeState,
  ENVELOPE_CODE,
} from './session-envelope.mjs';
import { resolveSeats, isProductionSeatSafe, findProductModelIds } from './seating.mjs';
import { priceCompile } from './cost-model.mjs';
import { SEAT_ROLE } from './seat-tiers.mjs';
import {
  appendConversationTurns,
  readConversationLog,
  appendStewardFeedback,
} from './conversation-log.mjs';
import { noteStewardEffort } from './portfolio-ledger.mjs';
import {
  reconstructStepDetail,
  evaluateCommissionability,
  deriveTargetedQuestions,
  recordElaborationAnswers,
} from './progressive-elaboration.mjs';
import { SKILL_PRIMERS_COMPACT } from './skill-primers.mjs';
import { readStepFindings } from './step-findings.mjs';

// ── Schema / policy ────────────────────────────────────────────────────────

export const CONVERSE_SCHEMA = 'ecgberht-steward-conversation-v0';

/**
 * The conversation policy, frozen so a test can assert it rather than trust prose.
 * `model_reads_utterance: true` is the whole point of this module; `chat_persisted:
 * false` is the E5 invariant it must not break.
 */
export const CONVERSE_POLICY = Object.freeze({
  model_reads_utterance: true,
  chat_persisted: false,
  control_verbs_deterministic: true,
  model_may_write: false,
  model_may_spend: false,
  invents_when_unsure: false,
});

// ── Failure states (honest unknown ≠ empty) ────────────────────────────────

export const CONVERSE_CODE = Object.freeze({
  NO_FACE: 'CONVERSE_NO_FACE',
  NO_ENVELOPE: 'CONVERSE_NO_ENVELOPE',
  BUDGET_REACHED: 'CONVERSE_BUDGET_REACHED',
  SEAT_UNSAFE: 'CONVERSE_SEAT_UNSAFE',
  SEAT_UNREACHABLE: 'CONVERSE_SEAT_UNREACHABLE',
  REPLY_UNPARSEABLE: 'CONVERSE_REPLY_UNPARSEABLE',
  REPLY_EMPTY: 'CONVERSE_REPLY_EMPTY',
  PROPOSAL_INVALID: 'CONVERSE_PROPOSAL_INVALID',
  ORANGES_GENERIC: 'CONVERSE_ORANGES_GENERIC',
  DESTRUCTIVE: 'CONVERSE_DESTRUCTIVE',
});

export const CONVERSE_TEXT = Object.freeze({
  [CONVERSE_CODE.NO_FACE]:
    'No project Face yet — set the goal first; the conversation anchors to it.',
  [CONVERSE_CODE.NO_ENVELOPE]:
    'Talking to the steward costs a model call, and there is no confirmed session budget yet. Confirm one and we can talk.',
  [CONVERSE_CODE.BUDGET_REACHED]:
    "We've reached the session budget, so I stopped rather than keep spending. Raise it and we carry on.",
  [CONVERSE_CODE.SEAT_UNSAFE]:
    'The configured seat is not safe for production use — nothing was sent and nothing was spent.',
  [CONVERSE_CODE.SEAT_UNREACHABLE]:
    "I could not reach the steward's seat, so I could not think about that properly. Nothing was written.",
  [CONVERSE_CODE.REPLY_UNPARSEABLE]:
    'The seat answered in a shape I could not read. Rather than guess at what it meant, I am telling you: nothing was written.',
  [CONVERSE_CODE.REPLY_EMPTY]:
    'The seat came back empty. Nothing was written — say that again and I will try once more.',
  [CONVERSE_CODE.PROPOSAL_INVALID]:
    'The proposed scaffolding did not survive validation, so I am not offering it to you as if it were sound.',
  [CONVERSE_CODE.ORANGES_GENERIC]:
    'The proposal came back with placeholder foresight instead of real anticipation — refused rather than dressed up.',
  [CONVERSE_CODE.DESTRUCTIVE]:
    `${SPELLING} will not compile destructive free-form talk. Nothing was deleted and nothing was written.`,
});

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function converseFailure(code, extra = {}) {
  const text = CONVERSE_TEXT[code] ?? CONVERSE_TEXT[CONVERSE_CODE.SEAT_UNREACHABLE];
  return {
    ok: false,
    error: extra.error ?? String(code).toLowerCase().replace(/_/g, '-'),
    code,
    status_code: code,
    say: text,
    text,
    message: text,
    user_text: text,
    conversational: true,
    ledger_write: false,
    dialogue_persisted: false,
    ...extra,
  };
}

// ── Routing: control verbs stay deterministic ──────────────────────────────

/**
 * Longest utterance (in words) that may compile to a CONTROL act.
 *
 * WHY A LENGTH GUARD. Not every act pattern is ^-anchored — `park (that|this|the)
 * (idea|thought)` and `show (me )?(the )?detail` match ANYWHERE in the text. John dictates
 * whole paragraphs, so a 300-word project description containing "...and show me the
 * detail on that later..." would compile to a control act and never reach the steward at
 * all. A control verb is a SHORT deliberate instruction; a paragraph is talk.
 */
export const ACT_MAX_WORDS = 8;

/**
 * @param {string} text
 * @returns {number}
 */
function wordCount(text) {
  const s = String(text ?? '').trim();
  return s ? s.split(/\s+/).length : 0;
}

/**
 * Decide where an utterance goes: the closed act table, or the seat.
 *
 * Deterministic and zero-model — the routing law itself is never a model decision, and it
 * lives HERE (engine) rather than in the browser so the bridge and the UI cannot drift
 * apart about what counts as a control verb.
 *
 * @param {string} text
 * @param {{ session?: object }} [ctx]
 * @returns {{ lane: 'act'|'converse'|'refuse', compiled?: object, reason?: string }}
 */
export function routeUtterance(text, ctx = {}) {
  const trimmed = String(text ?? '').trim();
  if (!trimmed) return { lane: 'refuse', reason: 'empty_utterance' };

  if (wordCount(trimmed) <= ACT_MAX_WORDS) {
    // A SHORT utterance is command-shaped, so the destructive guard belongs here:
    // "delete all projects" must never compile to a verb.
    if (matchesDestructive(trimmed)) {
      return { lane: 'refuse', reason: 'destructive_free_form' };
    }
    const compiled = compileUtterance(trimmed, ctx);
    if (compiled.compiled) return { lane: 'act', compiled };
  }

  // WHY THE DESTRUCTIVE GUARD DOES NOT RUN ON THE CONVERSE LANE (found in the
  // 2026-08-04 multi-turn smoke). John's real refinement was "...and DROP the separate
  // 'lock the decisions' stage, fold those decisions into the syllabus stage" —
  // DESTRUCTIVE_PATTERNS contains /\bdrop\b/, so the steward answered "Ecgberht will
  // not compile destructive free-form talk" to an ordinary editorial instruction. He
  // will say drop / remove / get rid of constantly while shaping a scaffolding.
  //
  // The guard's threat model is "free-form talk must never compile to a DESTRUCTIVE
  // VERB". On this lane nothing executes: the seat runs read-only (SEAT_ALLOWED_TOOLS),
  // the model has no write authority, and every proposal still needs a human
  // hash-bound confirm. So there is nothing here for the guard to protect, and applying
  // it anyway breaks the conversation it was meant to make safe.
  return { lane: 'converse' };
}

// ── Context assembly (what the steward knows when it answers) ──────────────

/**
 * Load the durable context for a turn. All three sources are the EXISTING ledger —
 * this function opens no new store and creates no second memory.
 *
 * @param {string} projectPath
 * @returns {{ ok: boolean, face?: object, roadmap?: object, strip?: object, open_proposal?: object|null }}
 */
export function loadStewardContext(projectPath) {
  const face = requireProjectFace(projectPath);
  if (!face.ok) return { ok: false, code: CONVERSE_CODE.NO_FACE, face_check: face };

  const surfaces = loadProjectSurfaces(projectPath);
  const loaded = loadProjectRoadmap(projectPath);
  const roadmap = loaded.exists && loaded.ok ? loaded.roadmap : null;

  // loadProjectSurfaces returns the PARSED Face document ({ok, narrative, raw,
  // strip_fence}), so the narrative is read straight off it.
  const narrative = surfaces.face?.narrative ?? null;

  const projection = Array.isArray(roadmap?.roadmap_projection)
    ? roadmap.roadmap_projection : [];

  // THE STEP IN HAND, AND WHAT IT STILL NEEDS.
  //
  // This is what makes the steward walk alongside rather than hand over a document.
  // John: "I don't want to have to scaffold it all and go do the detail stuff later —
  // I could if I want to, but I don't have to." So detail is not demanded up front; it
  // is asked for one step at a time, when that step becomes the work.
  //
  // All three calls are PURE reads — no probe is written just because he opened the
  // chamber. The steward asks in its own voice, in the conversation; answers land as
  // typed elaboration events only when he actually answers.
  const active = findActiveStep(projection);
  let stepGaps = [];
  if (active && roadmap) {
    const detail = reconstructStepDetail(roadmap, active.step_id ?? active.id);
    if (detail && detail.ok !== false) {
      const predicate = evaluateCommissionability(detail);
      if (!predicate.ready) stepGaps = deriveTargetedQuestions(predicate, detail);
    }
  }

  // LIVE COMMISSIONED RUNS (2026-08-06, from John's day-one use). The seat could
  // not see run state, so it DISAVOWED a genuinely running Gandalf ("your Go
  // never reached the machinery") one turn after the machinery confirmed it.
  // The host's run records are the truth; read them so "is it running?" gets a
  // real answer. Read-only, best-effort, never authoritative for the roadmap.
  const commission_runs = readCommissionRuns(surfaces.project_path);

  // The step findings ledger — what runs and reflection have FED each step
  // (2026-08-07). Read for context; never authoritative for status.
  const findings = readStepFindings(surfaces.project_path);
  const step_findings = findings.ok ? findings.steps : {};

  // The DURABLE conversation — how the plan got where it is, in his words and the
  // steward's. Read for RECALL only; project state above still comes from the Face,
  // roadmap and Strip, and the ledger always wins (see conversation-log.mjs).
  const history = readConversationLog(surfaces.project_path, { limit: 20 });

  return {
    ok: true,
    project_path: surfaces.project_path,
    narrative,
    strip: surfaces.strip ?? null,
    roadmap,
    projection,
    active_step: active,
    step_gaps: stepGaps,
    open_proposal: roadmap ? findOpenScaffoldProposal(roadmap) : null,
    commission_runs,
    step_findings,
    history: history.ok ? history.turns : [],
    history_unreadable: history.ok ? false : true,
  };
}

/**
 * The host's commission run records (.anchor/commission-runs/*.json), newest
 * first, as small honest projections. Missing dir → empty; unreadable file →
 * skipped. Never a transcript, never a worktree path.
 * @param {string} projectPath
 */
export function readCommissionRuns(projectPath) {
  const rows = [];
  try {
    const dir = path.join(path.resolve(projectPath), '.anchor', 'commission-runs');
    if (!fs.existsSync(dir)) return rows;
    for (const name of fs.readdirSync(dir)) {
      if (!name.endsWith('.json')) continue;
      try {
        const rec = JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8'));
        rows.push({
          skill: rec.skill ?? null,
          step_id: rec.step_id ?? null,
          outcome: rec.outcome ?? null,
          at: rec.at ?? null,
          elapsed_s: rec.elapsed_s ?? null,
          session_id: rec.session_id ?? null,
          needs: rec.report?.needs ?? null,
          say: rec.report?.say ?? null,
        });
      } catch { /* skip unreadable record */ }
    }
    rows.sort((a, b) => String(b.at ?? '').localeCompare(String(a.at ?? '')));
  } catch { /* dir unreadable → empty */ }
  return rows;
}

/**
 * The step the conversation is currently ABOUT.
 *
 * A running step wins; otherwise the first step not yet done — which is what "we are
 * here now" means on a campaign that has started but has nothing in flight. Null when
 * there are no confirmed steps at all (the scaffolding conversation).
 *
 * @param {Array} projection
 * @returns {object|null}
 */
export function findActiveStep(projection) {
  const steps = Array.isArray(projection) ? projection : [];
  if (!steps.length) return null;
  const running = steps.find((s) => s.status === 'running' || s.status === 'in_progress');
  if (running) return running;
  return steps.find((s) => s.status !== 'done' && s.status !== 'cancelled') ?? null;
}

/**
 * The steward's standing instruction. Kept as a named constant so the prompt is
 * reviewable as a product decision, not buried in a template literal.
 *
 * The Parable of the Oranges clause is load-bearing: John asked for a steward that thinks
 * two or three steps ahead and surfaces what he has NOT asked yet.
 */
/**
 * THE TALKING INSTRUCTION — used on every ordinary turn, by the CONVERSATIONAL tier.
 *
 * It cannot produce a scaffolding. That is deliberate and it fixes the first thing John
 * hit in real use: he opened the steward, it silently read his files, and threw a
 * finished eight-stage plan at him without asking a single question. A talking model
 * that has no way to emit a plan cannot do that. When it judges a plan is warranted it
 * says so (`wants_plan`), and the FRONTIER tier frames it as a separate turn.
 */
export const STEWARD_TALK_INSTRUCTION = [
  `You are ${SPELLING}, John's project steward. You are a collaborator, not a form.`,
  '',
  'WHERE YOU ARE — this shapes everything:',
  '- John talks to you in the steward\'s chamber (a browser panel), NOT a terminal.',
  '  You are one reply in that conversation. NEVER mention permission modes, plan',
  '  mode, Shift+Tab, /config, toggles, tools you do or do not have, or anything',
  '  about your own harness. None of it exists for him.',
  '- You personally cannot commit, write files, journal, or launch anything — and',
  '  that is fine, because the STEWARD\'S MACHINERY does those things when John',
  '  confirms. NEVER claim you did or will do such an act, and NEVER say work has',
  '  started — nothing starts inside a talk turn. When he tells you to run a skill',
  '  (Gandalf, Crucible, researchPrime, Foreman, Jumper), set "wants_commission"',
  '  below: the machinery then shows him the commission card, one Go from running.',
  '  Never ask him to unlock you; his confirm IS the go — never ask for a second.',
  '- Feedback he gives about the steward itself goes in your "journal" field',
  '  (below) — the machinery writes it durably. Only then may you say "journaled".',
  '- A turn opening "About the step …" (any quoting) comes from the roadmap',
  '  rail\'s step panel. Whatever detail follows is ALREADY saved on that',
  '  step\'s ledger — never offer to save it. Your job is the REFINEMENT:',
  '  react to it against what the step needs, tighten it, and ask the one',
  '  question that would make the step commissionable.',
  '',
  'HOW YOU WORK:',
  '- He brainstorms out loud. Talk with him. Ask about what genuinely blocks the NEXT',
  '  step — never about everything at once.',
  '- You are DRIVING this, not just answering. Say what you think the next concrete move',
  '  is and offer to make it. Do not wait to be asked.',
  '- If you do not know something, say so. Never invent a fact, a stage, or a date.',
  '',
  'BE SHORT. This is the rule he cares about most:',
  '- Answer in AT MOST 120 words. A reply that needs more than that is a reply that has',
  '  not decided what matters.',
  '- ONE question per turn. Ask the one that unblocks the next step; hold the rest.',
  '- Asked "what next?", name ONE thing — the next concrete move — not a catalogue.',
  '- No headers, no bullet walls, no restating what he just said back to him.',
  '',
  'THE PARABLE OF THE ORANGES:',
  'Think two or three steps ahead and surface what he has NOT asked yet — the hidden cost,',
  'the decision that gets expensive if deferred. One such observation per turn, at most.',
  '',
  SKILL_PRIMERS_COMPACT,
  'When you set wants_commission, also COMPOSE the directive: what that engine',
  'should do, grounded in everything this campaign has learned — never "run it',
  'because it is next on the list".',
  '',
  'REPLY FORMAT — reply with ONLY a JSON object, no prose outside it, no code fence:',
  '{',
  '  "say": "<your reply, in your voice, at most 120 words>",',
  '  "asks": ["<the ONE open question, if any>"],',
  '  "wants_plan": false | true,',
  '  "plan_brief": "<if wants_plan: one line on what the plan should cover>",',
  '  "answers": {} | {"<element>": "<what he just told you about the step in hand>"},',
  '  "journal": ["<feedback he gave about the STEWARD ITSELF — its UI, its flow,',
  '               its behaviour — one entry per point, his gist. Omit when none.>"],',
  '  "wants_commission": false | true,',
  '  "commission_skill": "<if wants_commission and he NAMED a skill: that name>",',
  '  "commission_directive": "<if wants_commission: the composed brief for that',
  '                           engine, grounded in what is known — 60-150 words,',
  '                           formatted as 3-6 short lines each starting with',
  '                           \'- \' so John can scan it at a glance>",',
  '  "project_create": null | {"name": "<project name>", "folder": "<the full',
  '                            folder path he gave>"}',
  '}',
  '',
  'PORTFOLIO TURNS: a turn beginning "PORTFOLIO:" comes from the High Seat —',
  'John steering ALL projects, not this one campaign. When such a turn asks to',
  'start/register/create a project, fill project_create with the name and',
  'folder EXACTLY as he gave them (ask for the folder when missing — never',
  'guess a path); the machinery shows him a confirm card and an existing',
  'folder starts brownfield with a first Gandalf read on its own. You cannot',
  'yet move, copy, or gather files into a folder — when he asks for that, say',
  'so plainly and suggest he put the material in the folder first.',
  '',
  'Set "wants_plan" true ONLY when the conversation has earned a scaffolding — he has',
  'asked for one, or you have enough and have told him you are about to frame it. It is',
  'a slow, expensive step. Talking is the default; planning is the exception —',
  'with ONE exception the other way (John, 2026-08-06): when he opens with a RICH',
  'project description, he wants the coarse map FIRST and the questions after.',
  'Do not interrogate him before showing a map he can react to.',
].join('\n');

/**
 * THE PLANNING INSTRUCTION — used only when a scaffolding is actually to be produced,
 * by the FRONTIER tier. This is the turn worth waiting for.
 */
export const STEWARD_PLAN_INSTRUCTION = [
  `You are ${SPELLING}, John's project steward, framing a campaign scaffolding.`,
  '',
  'You are one reply in the chamber conversation, not a terminal session: never',
  'mention permission modes, tools, or your harness, and never claim to have',
  'written or launched anything — the steward\'s machinery writes when John',
  'confirms, and his confirm IS the go signal.',
  '',
  '- A scaffolding is COARSE and deliberately incomplete. Stages get their detail later,',
  '  by talking, when each becomes the step in hand. Do not demand detail up front.',
  '- Prefer FEWER, larger stages. Six is usually plenty; twelve is a symptom.',
  '- Never invent a fact, a date, or a constraint he did not give you.',
  '',
  'THE PARABLE OF THE ORANGES — this is why he wants you:',
  'Each stage carries foresight SPECIFIC to that stage: the hidden cost, the decision',
  'that gets expensive if deferred, the thing that will be true next year. Generic',
  'prompts ("what would he ask next?") are a failure and will be refused.',
  '',
  'REPLY FORMAT — reply with ONLY a JSON object, no prose outside it, no code fence:',
  '{',
  '  "say": "<at most 80 words: what you framed and the one thing to react to>",',
  '  "proposal": {',
  '    "kind": "scaffolding" | "next_stage",',
  '    "goal": "<the campaign goal in one line>",',
  '    "stages": [',
  '      {"name": "<stage name>", "done_when": "<what makes it done>",',
  '       "step_type": "RESEARCH" | "PLAN" | "BUILD" | "REVIEW" | null,',
  '       "oranges": ["<specific foresight for THIS stage>"]}',
  '    ],',
  '    "foresight": ["<campaign-level: what bites later>"]',
  '  }',
  '}',
  '',
  'step_type says which KIND of work the stage is, so the steward can later',
  'commission the right skill for it (RESEARCH→investigate · PLAN→design/decide',
  '· BUILD→make the thing · REVIEW→assess). Set it when the stage clearly is one',
  'of those; null when it is genuinely none of them. Never guess.',
].join('\n');

/**
 * Build the full prompt for one turn. PURE — deterministic given its inputs, so a test can
 * assert the prompt without a model, and the recorded-reply gate can assert the prompt did
 * not drift out from under its recording.
 *
 * @param {{ narrative?: object|null, projection?: Array, open_proposal?: object|null, strip?: object|null }} context
 * @param {string} utterance
 * @param {{ turns?: Array<{role: string, text: string}> }} [opts]
 * @returns {string}
 */
export function buildStewardPrompt(context = {}, utterance = '', opts = {}) {
  const instruction = opts.planning ? STEWARD_PLAN_INSTRUCTION : STEWARD_TALK_INSTRUCTION;
  const lines = [instruction, '', '--- CAMPAIGN CONTEXT ---'];

  const n = context.narrative ?? {};
  lines.push(`North star: ${nonEmptyOr(n.north_star, '(not set)')}`);
  lines.push(`Active effort: ${nonEmptyOr(n.active_effort, '(none)')}`);
  if (nonEmptyOr(n.human_wait, '')) lines.push(`Waiting on John: ${n.human_wait}`);

  const projection = Array.isArray(context.projection) ? context.projection : [];
  const stepFindings = context.step_findings ?? {};
  if (projection.length) {
    lines.push('', 'Confirmed roadmap steps (already written — do not re-propose these):');
    for (const step of projection) {
      const sid = step.step_id ?? step.id;
      const facts = Array.isArray(stepFindings[sid]) ? stepFindings[sid] : [];
      lines.push(`- [${step.status ?? 'unknown'}] ${step.name ?? step.step_id}`
        + (facts.length ? ` · ${facts.length} finding${facts.length === 1 ? '' : 's'} on file` : ''));
    }
    // WHAT THE CAMPAIGN HAS LEARNED (conditional — absent when nothing fed).
    // The glue John asked for: run findings inform the NEXT move, so the seat
    // sees them where it reasons, not stashed in a report nobody re-reads.
    const learned = [];
    for (const step of projection) {
      const sid = step.step_id ?? step.id;
      const facts = Array.isArray(stepFindings[sid]) ? stepFindings[sid] : [];
      for (const f of facts.slice(-4)) {
        learned.push(`- [${sid}] ${f.finding}${f.source ? ` (${f.source})` : ''}`);
      }
    }
    if (learned.length) {
      lines.push('', 'WHAT THE CAMPAIGN HAS LEARNED (from finished runs — use it to aim the next move):');
      lines.push(...learned.slice(0, 16));
    }
  } else {
    lines.push('', 'Confirmed roadmap steps: none yet.');
  }

  // LIVE RUNS ride the prompt so "is it running?" is answered from RECORDS,
  // never guessed. Deliberately CONDITIONAL: no runs → no block → prompts
  // without runs stay byte-identical (the recorded acceptance tape holds).
  const runs = Array.isArray(context.commission_runs) ? context.commission_runs : [];
  if (runs.length) {
    lines.push('', '--- COMMISSIONED RUNS (host records — the truth about what is running) ---');
    for (const r of runs.slice(0, 5)) {
      lines.push(
        `- ${r.skill ?? 'skill'} for step '${r.step_id ?? '?'}': ${r.outcome}`
        + (r.outcome === 'running' ? ` (launched ${r.at ?? '?'} — a live session is working now)` : '')
        + (r.needs ? ` — waiting on John: ${r.needs}` : ''),
      );
    }
    lines.push(
      'Answer any "is it running / what is happening" question FROM THIS LIST.',
      'A running entry means the machinery genuinely launched it — never deny or',
      're-propose a run this list already shows. John can watch a running session',
      'via its green Running strip in the chamber ("Open the session").',
    );
  }

  // ONCE THE CAMPAIGN IS RUNNING the conversation changes shape: it stops being about
  // the whole scaffolding and becomes about the step in hand. This is the difference
  // between a one-shot planner and a steward — John asked for detail to get filled in
  // by talking, step by step, rather than demanded up front.
  const active = context.active_step;
  if (active) {
    const gaps = Array.isArray(context.step_gaps) ? context.step_gaps : [];
    lines.push(
      '',
      `THE STEP IN HAND: "${active.name}" (${active.status}).`,
      active.done_when ? `Its done-when: ${active.done_when}` : '',
      active.oranges_annotations?.length
        ? `Foresight already recorded for it: ${active.oranges_annotations.join(' · ')}`
        : '',
      'Ask only for what THIS step needs to move — not for the whole campaign\'s detail.',
      'If it is finished, say what you think was learned and propose the next stage',
      '(set proposal.kind to "next_stage").',
    );
  }
  const done = projection.filter((s) => s.status === 'done').length;
  if (projection.length && done === projection.length) {
    lines.push('', 'Every confirmed step is done — the campaign needs its next stage.');
  }

  // The scaffolding-so-far. This is what makes turn N+1 a REFINEMENT rather than a
  // restart — without it he would have to re-describe the project every time.
  const open = context.open_proposal;
  if (open && Array.isArray(open.steps) && open.steps.length) {
    lines.push('', 'SCAFFOLDING YOU ALREADY PROPOSED (not yet confirmed — he is reacting to this):');
    open.steps.forEach((s, i) => {
      lines.push(`${i + 1}. ${s.name}${s.done_when ? ` — done when: ${s.done_when}` : ''}`);
    });
    lines.push(
      'If he is refining it, return the WHOLE revised scaffolding, not just the changed part.',
    );
  }

  // THE DURABLE HISTORY — earlier sessions, so the steward can explain how the plan got
  // here rather than only what it currently is. Read for recall; never for state.
  const history = Array.isArray(context.history) ? context.history : [];
  if (history.length) {
    lines.push('', '--- EARLIER CONVERSATION ON THIS PROJECT (history, not state) ---');
    for (const t of history) {
      const who = t?.role === 'steward' ? SPELLING : 'John';
      const text = String(t?.text ?? '').trim();
      if (text) lines.push(`${who}${t.at ? ` [${String(t.at).slice(0, 10)}]` : ''}: ${text}`);
    }
    lines.push(
      'That history is a RECORD OF WHAT WAS SAID, not the current plan. Where it '
      + 'disagrees with the confirmed roadmap above, the roadmap is right.',
    );
  }
  if (context.history_unreadable) {
    lines.push('', 'NOTE: the earlier conversation history could not be read. Say so if it matters.');
  }

  // Turns from the live session the caller is holding — replayed for immediacy. They
  // land in the durable log once the turn succeeds.
  const turns = Array.isArray(opts.turns) ? opts.turns : [];
  if (turns.length) {
    lines.push('', '--- THIS SESSION SO FAR ---');
    for (const t of turns) {
      const who = t?.role === 'steward' ? SPELLING : 'John';
      const text = String(t?.text ?? '').trim();
      if (text) lines.push(`${who}: ${text}`);
    }
  }

  // THE ANSWER LAW (steward-e1 W2, E1). Deliberately CONDITIONAL — like the
  // COMMISSIONED RUNS block above: no enforceable bound (or no question this
  // turn) → no block → every existing prompt stays byte-identical and the
  // recorded acceptance tapes hold. The ids are DETERMINISTIC (computed by
  // the Anchor sibling's committed bound, never here) — the seat answers the
  // question; it never decides what counts as one.
  const e1 = opts.e1;
  const e1Questions = (e1 && e1.enforceable === true && Array.isArray(e1.questions))
    ? e1.questions.filter((q) => q && q.question_id) : [];
  if (e1Questions.length) {
    lines.push(
      '',
      '--- ANSWER LAW (E1 — the ratified bound) ---',
      `John's turn carries ${e1Questions.length} direct question(s), each with a machine id.`,
      '',
      'THIS SUPERSEDES THE REPLY FORMAT ABOVE FOR THIS TURN. The reply format',
      'enumerates its keys and says "reply with ONLY a JSON object", so a reply',
      'that honours it literally omits the key below and is then REFUSED — the',
      'answer you wrote is discarded and John sees a block instead of it. The',
      'object you return is the one described above WITH this key added:',
      '',
      '  "answer_references": [{"question_id": "<id, verbatim from the list below>",',
      '                         "answer_text": "<your explicit answer to that question>"}]',
      '',
      'One entry per id below, covering EVERY id. The engine structurally',
      'refuses to close a turn while any listed id lacks an answer-reference —',
      'never walk away from one. Answer the question in "say" as you normally',
      'would; answer_references is the machine-readable receipt, not a',
      'substitute for talking to him.',
    );
    for (const q of e1Questions) {
      lines.push(`- ${q.question_id}: "${String(q.text ?? '').trim()}"`);
    }
  }

  lines.push('', '--- JOHN JUST SAID ---', String(utterance ?? '').trim());
  return lines.join('\n');
}

function nonEmptyOr(v, fallback) {
  const s = v == null ? '' : String(v).trim();
  return s || fallback;
}

/**
 * Money for humans, with enough precision to be TRUE.
 *
 * The envelope's unit is synthetic and a compile can cost fractions of a cent, so a
 * flat toFixed(2) renders a real budget as "$0.00 of $0.00" — a number that tells John
 * nothing and reads like a bug. Small values get more places.
 *
 * @param {number} n
 * @returns {string}
 */
export function formatSpend(n) {
  const v = Number(n) || 0;
  if (v !== 0 && Math.abs(v) < 0.01) return `$${v.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')}`;
  return `$${v.toFixed(2)}`;
}

// ── Reply parsing (strict — a bad reply is refused, never guessed at) ──────

/**
 * Pull a JSON object out of a seat reply.
 *
 * The probe showed `claude -p` returns bare JSON, but a seat may fence it or add a
 * sentence around it. We accept those, and REFUSE anything else — a reply we cannot read
 * is reported honestly rather than salvaged into a plausible-looking plan.
 *
 * @param {string} raw
 * @returns {object|null}
 */
export function extractReplyJson(raw) {
  const text = String(raw ?? '').trim();
  if (!text) return null;

  const fenced = text.match(/```(?:json)?\s*\r?\n([\s\S]*?)```/i);
  const candidates = [];
  if (fenced && fenced[1]) candidates.push(fenced[1].trim());
  candidates.push(text);

  const firstBrace = text.indexOf('{');
  const lastBrace = text.lastIndexOf('}');
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    candidates.push(text.slice(firstBrace, lastBrace + 1));
  }

  for (const c of candidates) {
    try {
      const parsed = JSON.parse(c);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
    } catch {
      // try the next candidate — never fabricate
    }
  }
  return null;
}

/**
 * True when every stage's oranges are just the generic defaults (or empty).
 *
 * WHY THIS IS A FAILURE, not a warning. The Oranges annotations are the single thing John
 * named as non-negotiable ("the steward thinks 2-3 steps ahead and surfaces what he hasn't
 * asked yet"). A proposal that echoes DEFAULT_ORANGES_PROMPTS back is a model that did not
 * do the work, and shipping it would LOOK like the feature while being the old placeholder.
 *
 * @param {Array<{oranges?: Array}>} stages
 * @returns {boolean}
 */
export function orangesAreGeneric(stages) {
  const list = Array.isArray(stages) ? stages : [];
  if (!list.length) return true;
  const defaults = new Set(DEFAULT_ORANGES_PROMPTS.map((s) => String(s).trim().toLowerCase()));
  return list.every((s) => {
    const o = Array.isArray(s?.oranges) ? s.oranges : [];
    const real = o
      .map((x) => String(x ?? '').trim())
      .filter(Boolean)
      .filter((x) => !defaults.has(x.toLowerCase()));
    return real.length === 0;
  });
}

/**
 * Validate + normalize a seat reply into the steward's typed shape.
 *
 * @param {string|object} raw
 * @returns {{ ok: true, reply: object } | ReturnType<typeof converseFailure>}
 */
export function parseStewardReply(raw) {
  const obj = typeof raw === 'object' && raw !== null ? raw : extractReplyJson(raw);
  if (!obj) return converseFailure(CONVERSE_CODE.REPLY_UNPARSEABLE, { raw_preview: previewOf(raw) });

  const say = String(obj.say ?? '').trim();
  if (!say) return converseFailure(CONVERSE_CODE.REPLY_EMPTY, { raw_preview: previewOf(raw) });

  const asks = Array.isArray(obj.asks)
    ? obj.asks.map((a) => String(a ?? '').trim()).filter(Boolean)
    : [];

  const p = obj.proposal;
  if (p == null || p === false) {
    // Still talking. This is the conversation working, NOT a failure.
    //
    // `wants_plan` is how the CONVERSATIONAL tier hands off: it cannot write a
    // scaffolding itself (see STEWARD_TALK_INSTRUCTION), so when the conversation has
    // earned one it says so and the FRONTIER tier frames it as a separate turn.
    return {
      ok: true,
      reply: {
        say,
        asks,
        proposal: null,
        gathering: true,
        // E1 (steward-e1 W2): the seat's typed answers to John's direct
        // question ids ride through VERBATIM shape-checked — the
        // turn-completion hook validates coverage, never invents one.
        answer_references: Array.isArray(obj.answer_references)
          ? obj.answer_references : [],
        wants_plan: obj.wants_plan === true,
        plan_brief: String(obj.plan_brief ?? '').trim() || null,
        // Detail he gave about the step in hand, captured AS HE TALKS rather than
        // demanded up front. Recorded as typed elaboration events by converse().
        answers: (obj.answers && typeof obj.answers === 'object' && !Array.isArray(obj.answers))
          ? obj.answers : null,
        // Steward feedback — written durably by converse(); never a claimed act.
        journal: (Array.isArray(obj.journal) ? obj.journal : [])
          .map((j) => String(j ?? '').trim()).filter(Boolean),
        // "Start Gandalf" routes to the commission card — the model must never
        // say work started (it cannot start anything); it signals instead.
        wants_commission: obj.wants_commission === true,
        commission_skill: String(obj.commission_skill ?? '').trim() || null,
        commission_directive: String(obj.commission_directive ?? '').trim() || null,
        // High Seat portfolio turns: a spoken "start a project" lands as a
        // typed, confirmable act — name + folder exactly as John gave them.
        project_create: (obj.project_create && typeof obj.project_create === 'object'
          && String(obj.project_create.folder ?? '').trim())
          ? {
            name: String(obj.project_create.name ?? '').trim() || null,
            folder: String(obj.project_create.folder ?? '').trim(),
          }
          : null,
      },
    };
  }
  if (typeof p !== 'object' || Array.isArray(p)) {
    return converseFailure(CONVERSE_CODE.PROPOSAL_INVALID, { error: 'proposal_not_object' });
  }

  const kind = p.kind === 'next_stage' ? 'next_stage' : 'scaffolding';
  const goal = String(p.goal ?? '').trim();

  const stages = (Array.isArray(p.stages) ? p.stages : [])
    .map((s) => {
      if (typeof s === 'string') return { name: s.trim(), oranges: [] };
      if (!s || typeof s !== 'object') return null;
      const name = String(s.name ?? '').trim();
      if (!name) return null;
      // Only the four commissionable kinds ride through — anything else the
      // model invents is dropped rather than written to the ledger.
      const stepType = String(s.step_type ?? '').trim().toUpperCase();
      return {
        name,
        done_when: nonEmptyOr(s.done_when, '') || undefined,
        oranges: (Array.isArray(s.oranges) ? s.oranges : [])
          .map((o) => String(o ?? '').trim())
          .filter(Boolean),
        step_type: ['RESEARCH', 'PLAN', 'BUILD', 'REVIEW'].includes(stepType)
          ? stepType
          : undefined,
      };
    })
    .filter(Boolean);

  if (!stages.length) {
    return converseFailure(CONVERSE_CODE.PROPOSAL_INVALID, { error: 'proposal_no_stages' });
  }
  if (!goal) {
    return converseFailure(CONVERSE_CODE.PROPOSAL_INVALID, { error: 'proposal_no_goal' });
  }
  if (orangesAreGeneric(stages)) {
    return converseFailure(CONVERSE_CODE.ORANGES_GENERIC, { error: 'oranges_generic' });
  }

  const foresight = (Array.isArray(p.foresight) ? p.foresight : [])
    .map((f) => String(f ?? '').trim())
    .filter(Boolean);

  return {
    ok: true,
    reply: {
      say,
      asks,
      gathering: false,
      // E1 (steward-e1 W2): a proposal turn discharges John's question ids
      // the same way a talking turn does — through typed answer-references.
      answer_references: Array.isArray(obj.answer_references)
        ? obj.answer_references : [],
      proposal: { kind, goal, stages, foresight },
    },
  };
}

function previewOf(raw) {
  return String(raw ?? '').trim().slice(0, 200);
}

// ── Seat-output hygiene ────────────────────────────────────────────────────

/**
 * Keep ONLY the seat metadata we actually need, and prove it carries no vendor product
 * model IDs.
 *
 * WHY. The transport probe (2026-08-04) showed a real reply carries
 * `modelUsage: {"claude-fable-5": …}`. `seating.findProductModelIds` forbids product IDs
 * on seat stamps, so passing raw seat metadata into a durable event would trip a canary
 * later, far from its cause. Constructing a whitelist is safer than scrubbing a blob.
 *
 * @param {object} meta
 * @returns {{ ok: boolean, usage: object, product_model_ids: string[] }}
 */
export function sanitizeSeatMeta(meta = {}) {
  const usage = {
    tokens: Number(meta?.tokens) || 0,
    cost_usd: Number(meta?.cost_usd) || 0,
    duration_ms: Number(meta?.duration_ms) || 0,
    seat_family: typeof meta?.seat_family === 'string' ? meta.seat_family : null,
    driver: typeof meta?.driver === 'string' ? meta.driver : null,
  };
  const hits = findProductModelIds(usage);
  return { ok: hits.length === 0, usage, product_model_ids: hits };
}

// ── E1 turn-completion hook (steward-e1 W2 — the W8 row, engine leg) ───────
//
// The criterion: a steward turn structurally CANNOT close while a RATIFIED
// direct question id lacks a typed answer-reference. The BOUND (the
// deterministic question parse, the F7 ratification reader) is OWNED by the
// Anchor sibling's chamber_e1_bound.py — it is never re-implemented here.
// The caller (anchor_gui → seal-chamber-bridge --e1) computes the question
// ids + the ratification state THERE and injects them as `opts.e1`; this
// hook only validates typed answer-reference COVERAGE and refuses the close.
//
// FAIL CLOSED, by name: an absent / unratified / altered bound payload
// yields an `unenforceable` verdict carrying its named finding — never a
// silent clean pass — while the turn itself is NOT blocked (a steward turn
// is never blocked against a bound John has not signed; the F7 artifact's
// own law). Only a signed, enforceable bound may block.

export const E1_FINDING = Object.freeze({
  BLOCKED: 'E1-TURN-CLOSE-BLOCKED',
  UNRATIFIED: 'E1-BOUND-UNRATIFIED',
  ARTIFACT_MISSING: 'E1-F7-ARTIFACT-MISSING',
});

export const E1_DECISION = Object.freeze({
  CLOSE: 'close',
  BLOCK: 'block',
  UNENFORCEABLE: 'unenforceable',
});

// The deterministic id shape chamber_e1_bound.question_id mints (qNN-<12 hex>).
const E1_QUESTION_ID_RE = /^q\d{2,}-[0-9a-f]{12}$/;

/**
 * The VALID typed answer-references a parsed reply carries. A seat-provided
 * partial `{question_id, answer_text}` is completed with the machinery-owned
 * fields (`schema_version` / `answered_in`); an entry that still fails the
 * typed shape (bad id, empty answer) is DROPPED — an invalid reference must
 * never look answered.
 * @param {object} reply parsed steward reply (inner object)
 * @returns {Array<{schema_version:number,question_id:string,answered_in:string,answer_text:string}>}
 */
export function normalizeAnswerReferences(reply) {
  const raw = Array.isArray(reply?.answer_references) ? reply.answer_references : [];
  const out = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const qid = String(entry.question_id ?? '').trim();
    const text = String(entry.answer_text ?? '').trim();
    if (!E1_QUESTION_ID_RE.test(qid) || !text) continue;
    out.push({
      schema_version: 1,
      question_id: qid,
      answered_in: String(entry.answered_in ?? 'steward-reply').trim() || 'steward-reply',
      answer_text: text,
    });
  }
  return out;
}

/**
 * THE TURN-COMPLETION HOOK (engine leg). Pure — no fs, no model, no clock.
 * @param {object} reply parsed steward reply (inner object)
 * @param {object|null} e1 the bound payload the bridge boundary injected
 * @returns {{decision:string, enforced:boolean, finding:string|null, reason:string|null,
 *            unanswered:Array, answered:Array}}
 */
export function enforceTurnCompletion(reply, e1) {
  if (!e1 || typeof e1 !== 'object') {
    return {
      decision: E1_DECISION.UNENFORCEABLE, enforced: false,
      finding: E1_FINDING.ARTIFACT_MISSING,
      reason: 'no ratified bound rode this turn (the --e1 payload is absent) '
        + '— fail closed by name, never silently open',
      unanswered: [], answered: [],
    };
  }
  if (e1.enforceable !== true) {
    return {
      decision: E1_DECISION.UNENFORCEABLE, enforced: false,
      finding: String(e1.finding ?? E1_FINDING.UNRATIFIED),
      reason: String(e1.reason ?? 'the E1 bound is not ratified — '
        + 'enforcement fails closed until John\'s signature is on disk'),
      unanswered: [], answered: [],
    };
  }
  const questions = Array.isArray(e1.questions) ? e1.questions : [];
  const answered = normalizeAnswerReferences(reply);
  const answeredIds = new Set(answered.map((r) => r.question_id));
  const unanswered = questions
    .filter((q) => q && q.question_id && !answeredIds.has(q.question_id))
    .map((q) => ({
      question_id: q.question_id, text: q.text ?? null,
      kind: q.kind ?? null, rule: q.rule ?? null,
    }));
  if (unanswered.length) {
    return {
      decision: E1_DECISION.BLOCK, enforced: true,
      finding: E1_FINDING.BLOCKED,
      reason: 'a ratified direct question id lacks a typed answer-reference '
        + '— the engine refuses to close this turn (E1, per the F7-signed bound)',
      unanswered, answered,
    };
  }
  return {
    decision: E1_DECISION.CLOSE, enforced: true,
    finding: null, reason: null, unanswered: [], answered,
  };
}

// ── The turn ───────────────────────────────────────────────────────────────

/**
 * One conversational turn.
 *
 * Order matters and is deliberate:
 *   route (deterministic, free) → context → envelope PRE-check (refuse BEFORE spending)
 *   → seat call (injected) → parse → debit ONCE → propose through the existing spine.
 *
 * A proposal is emitted through `proposeScaffolding`, so it lands as the SAME typed
 * `scaffold_proposal` event the confirm path already knows how to hash-bind and batch
 * confirm. Nothing here writes steps; confirming remains a separate, explicit human act.
 *
 * @param {string} projectPath
 * @param {{
 *   utterance: string,
 *   turns?: Array<{role: string, text: string}>,
 *   seatCall?: (prompt: string, ctx: object) => Promise<{ok: boolean, text?: string, meta?: object, reason?: string}>,
 *   seats?: object,
 *   prefs?: object,
 *   env?: object,
 *   session?: object,
 *   client_event_id?: string,
 *   auth?: object,
 *   at?: string,
 * }} opts
 */
export async function converse(projectPath, opts = {}) {
  const utterance = String(opts.utterance ?? '');

  // 1. Control verbs never reach a model, and never spend.
  const routed = routeUtterance(utterance, { session: opts.session });
  if (routed.lane === 'refuse') {
    return converseFailure(
      routed.reason === 'destructive_free_form'
        ? CONVERSE_CODE.DESTRUCTIVE
        : CONVERSE_CODE.REPLY_EMPTY,
      { error: routed.reason, routed: routed.lane },
    );
  }
  if (routed.lane === 'act') {
    return {
      ok: true,
      lane: 'act',
      compiled: routed.compiled,
      say: `Understood that as: ${routed.compiled.label ?? routed.compiled.act}.`,
      model_called: false,
      spent: false,
      ledger_write: false,
      dialogue_persisted: false,
    };
  }

  // 2. The conversation anchors to a Face.
  const context = loadStewardContext(projectPath);
  if (!context.ok) {
    return converseFailure(CONVERSE_CODE.NO_FACE, { face_check: context.face_check });
  }

  // 3. Seat must be safe BEFORE we send anything anywhere.
  const seats = opts.seats ?? resolveSeats({ prefs: opts.prefs, env: opts.env });
  if (!seats.ok || !isProductionSeatSafe(seats)) {
    return converseFailure(CONVERSE_CODE.SEAT_UNSAFE, {
      error: seats.error ?? 'seat_unsafe',
      seat_message: seats.message ?? null,
    });
  }

  // 4. BACKGROUND ALLOWANCE (John, 2026-08-05). Talking used to require confirming a
  //    budget before the steward would say anything: "I really don't want to do that.
  //    Might have like a background amount of effort and if it hits there then it can
  //    say hey we've hit this threshold do you want to carry on."
  //
  //    So an allowance opens ON ITS OWN the first time he talks. The law it replaces is
  //    "nothing spent without prior confirmation"; the law it keeps is the one that
  //    matters — the steward STOPS at the cap and asks, and cannot go past it without
  //    him saying so. Reaching the cap is a checkpoint (see BUDGET_REACHED below).
  let envState = readEnvelopeState(projectPath, {});
  if ((!envState.ok || !envState.live) && envState.code !== ENVELOPE_CODE.EXHAUSTED) {
    const opened = opts.openAllowance
      ? opts.openAllowance(projectPath)
      : { ok: false, skipped: 'no_opener_injected' };
    if (opened.ok) envState = readEnvelopeState(projectPath, {});
  }
  if (!envState.ok || !envState.live) {
    // A REACHED CAP IS A CHECKPOINT, NOT A WALL (John, 2026-08-04). Say what has
    // actually been spent and offer to carry on, rather than a bare refusal — the
    // decision to go past it is his, and it stays a human confirmation.
    if (envState.code === ENVELOPE_CODE.EXHAUSTED) {
      // readEnvelopeState nests the numbers under `balance` — reading them off the
      // top level silently yields undefined, and the checkpoint would have told John
      // "$0.00 of $0.00 spent", which is worse than no number at all.
      const bal = envState.balance ?? envState;
      const spent = Number(bal.spent_usd) || 0;
      const cap = bal.max_spend_usd;
      const onSpend = bal.bound !== 'compiles';
      return converseFailure(CONVERSE_CODE.BUDGET_REACHED, {
        code: CONVERSE_CODE.BUDGET_REACHED,
        status_code: CONVERSE_CODE.BUDGET_REACHED,
        bound: bal.bound ?? 'spend',
        spent_usd: spent,
        max_spend_usd: cap ?? null,
        envelope: envState,
        can_raise: onSpend,
        say: onSpend
          ? `We've reached the session budget — ${formatSpend(spent)} of `
            + `${formatSpend(cap ?? 0)} spent. I've stopped rather than keep `
            + 'spending. Tell me to carry on and I will, or raise the cap and we keep going.'
          : 'We\'ve reached this session\'s turn limit. Confirm a fresh budget and we carry on.',
      });
    }
    const code =
      envState.code === ENVELOPE_CODE.EXPIRED ? ENVELOPE_CODE.EXPIRED
      : CONVERSE_CODE.NO_ENVELOPE;
    return converseFailure(CONVERSE_CODE.NO_ENVELOPE, {
      code,
      status_code: code,
      envelope: envState,
    });
  }

  // 5. The seat call itself — injected, because engine/ may not spawn.
  //    The E1 bound payload (opts.e1, computed by the Anchor owner and
  //    injected at the bridge boundary) rides into the prompt's conditional
  //    ANSWER LAW block and into the turn-completion hook below.
  const prompt = buildStewardPrompt(context, utterance, { turns: opts.turns, e1: opts.e1 });
  if (typeof opts.seatCall !== 'function') {
    return converseFailure(CONVERSE_CODE.SEAT_UNREACHABLE, { error: 'no_seat_call_injected' });
  }

  // AFFORDABILITY, not just liveness. `live` only means "not yet over the cap" — an
  // envelope with a few cents left is live while the NEXT debit would be refused. Left
  // as-is the steward would spend a real model call and only then discover it could not
  // record the spend: money out, ledger silent. Stop at the checkpoint BEFORE the call.
  const balance = envState.balance ?? {};
  const remaining = balance.remaining_usd;
  if (remaining != null && Number.isFinite(Number(remaining))) {
    const estimate = Number(priceCompile(prompt, { seat: 'compile' }).cost_usd) || 0;
    if (estimate > Number(remaining)) {
      const spent = Number(balance.spent_usd) || 0;
      const cap = Number(balance.max_spend_usd) || 0;
      return converseFailure(CONVERSE_CODE.BUDGET_REACHED, {
        code: CONVERSE_CODE.BUDGET_REACHED,
        status_code: CONVERSE_CODE.BUDGET_REACHED,
        bound: 'spend',
        spent_usd: spent,
        max_spend_usd: cap,
        estimated_next_usd: estimate,
        can_raise: true,
        say:
          `This next turn would take us past the session budget — ${formatSpend(spent)} of `
          + `${formatSpend(cap)} spent already. I've stopped rather than run it. `
          + 'Raise the cap and I will carry straight on.',
      });
    }
  }

  const callSeat = async (text, role) => {
    try {
      return await opts.seatCall(text, {
        seat_family: seats.coding_family,
        driver: seats.coding_driver,
        role,
        // Only the planning turn is granted read-only project access.
        project_path: context.project_path,
      });
    } catch (e) {
      return { ok: false, reason: 'seat_call_threw', detail: String(e?.message ?? e) };
    }
  };

  // TALK FIRST, ALWAYS. The conversational tier holds the exchange and cannot write a
  // scaffolding — so the steward can never open by dumping a finished plan on him.
  let seatResult = await callSeat(prompt, SEAT_ROLE.CONVERSATIONAL);
  if (!seatResult || seatResult.ok !== true || !String(seatResult.text ?? '').trim()) {
    return converseFailure(CONVERSE_CODE.SEAT_UNREACHABLE, {
      error: 'seat_call_failed',
      reason: seatResult?.reason ?? 'no_reply',
      detail: seatResult?.detail,
    });
  }

  // 6. Parse strictly. An unreadable reply is reported, never salvaged.
  let parsed = parseStewardReply(seatResult.text);
  if (!parsed.ok) return { ...parsed, seat_reached: true };

  // PLAN SECOND, RARELY. Only when the conversation earned it does the FRONTIER tier
  // run — the slow, deep, expensive turn — and only that turn may frame a scaffolding.
  let planUsage = null;
  if (parsed.reply.wants_plan === true) {
    const planPrompt = buildStewardPrompt(context, utterance, {
      turns: opts.turns,
      planning: true,
      plan_brief: parsed.reply.plan_brief,
      e1: opts.e1,
    });
    const planResult = await callSeat(planPrompt, SEAT_ROLE.FRONTIER);
    if (planResult?.ok === true && String(planResult.text ?? '').trim()) {
      const planParsed = parseStewardReply(planResult.text);
      if (planParsed.ok && planParsed.reply.proposal) {
        // Keep the talking turn's voice; take the frontier turn's plan.
        // E1: the talking turn's answer-references survive the merge — a
        // question the first turn answered must not become unanswered
        // because the frontier turn framed a plan.
        const talkRefs = Array.isArray(parsed.reply.answer_references)
          ? parsed.reply.answer_references : [];
        const planRefs = Array.isArray(planParsed.reply.answer_references)
          ? planParsed.reply.answer_references : [];
        parsed = {
          ok: true,
          reply: {
            ...planParsed.reply,
            asks: parsed.reply.asks,
            gathering: false,
            answer_references: planRefs.length ? planRefs : talkRefs,
          },
        };
        planUsage = planResult.meta ?? null;
      }
    }
    // A failed planning turn is NOT a failed turn: he still gets the conversation, and
    // the steward says plainly that the framing did not come back rather than inventing
    // one. Falling through leaves `parsed` as the talking reply.
  }

  const meta = sanitizeSeatMeta({
    ...(seatResult.meta ?? {}),
    // A planning turn's tokens are the bulk of the spend — count both, or the debit
    // under-reports what was actually used.
    tokens: (Number(seatResult.meta?.tokens) || 0) + (Number(planUsage?.tokens) || 0),
    // Real dollars, both turns. The planning turn is the expensive one.
    cost_usd: (Number(seatResult.meta?.cost_usd) || 0) + (Number(planUsage?.cost_usd) || 0),
    seat_family: seats.coding_family,
    driver: seats.coding_driver,
  });
  // ACT on the check rather than merely computing it. An unread `ok` is a guard that
  // looks like protection and provides none — the exact shape this project has shipped
  // three times. If a vendor product model id reached the whitelist anyway, drop the
  // identity fields so nothing durable can carry one, and say so out loud.
  if (!meta.ok) {
    meta.usage.seat_family = null;
    meta.usage.driver = null;
    meta.usage.scrubbed_product_model_ids = meta.product_model_ids.length;
  }
  const reply = parsed.reply;

  // ── THE E1 TURN-COMPLETION HOOK (steward-e1 W2 — the W8 row) ─────────────
  // The turn attempts to close HERE. Under a RATIFIED bound, an open
  // question id with no typed answer-reference structurally blocks the
  // close with a named finding; an unratified/absent bound fails CLOSED by
  // name on the verdict (never a silent clean pass) without blocking. The
  // seat call already happened, so the spend is debited honestly either way
  // — a blocked turn never hides money that left.
  const turnClose = enforceTurnCompletion(reply, opts.e1 ?? null);
  if (turnClose.decision === E1_DECISION.BLOCK) {
    const debit = debitSessionEnvelope(projectPath, {
      kind: 'compile',
      text: prompt,
      tokens: meta.usage.tokens || undefined,
      cost_usd: meta.usage.cost_usd,
      auth: opts.auth,
      client_event_id: opts.client_event_id ? `${opts.client_event_id}-blocked` : undefined,
    });
    return {
      ok: true,
      lane: 'converse',
      turn_blocked: true,
      blocked: {
        finding: turnClose.finding,
        unanswered: turnClose.unanswered,
        // Nothing is lost: the reply is HELD, not delivered as a closed
        // turn — the drawn refusal state (V5 AG-BLOCKED-TURN) is what John
        // sees, so the cure never looks like "are you working".
        held_say: reply.say,
        message: 'The engine refused to close this turn: a direct question '
          + 'from John still lacks a typed answer-reference.',
      },
      turn_close: turnClose,
      say: 'The engine refused to close this turn: a direct question from '
        + 'John still lacks a typed answer-reference.',
      model_called: true,
      seat: { family: seats.coding_family, driver: seats.coding_driver },
      usage: meta.usage,
      debit: debit.ok ? { debited: true, shown: debit.shown } : { debited: false, ...debit },
      steps_written: false,
      ledger_write: false,
      dialogue_persisted: false,
    };
  }

  // Record the exchange. Durable, append-only, and NEVER authoritative: this is how
  // John reads back why the plan changed, not where the plan currently stands.
  const recordTurns = (proposalHash, stageCount = 0) => {
    const appended = appendConversationTurns(
      projectPath,
      [{ role: 'john', text: utterance }, { role: 'steward', text: reply.say }],
      { proposal_hash: proposalHash ?? null, at: opts.at },
    );
    // Portfolio memory: WHAT THE STEWARD DID, never what the project is. Best-effort —
    // the steward's own bookkeeping must not break a turn John cares about.
    noteStewardEffort({
      kind: proposalHash ? 'scaffold_proposed' : 'conversation',
      project_path: projectPath,
      project_id: opts.project_id ?? context.strip?.project_id ?? null,
      at: opts.at,
      summary: proposalHash
        ? `Proposed a ${stageCount}-stage scaffolding`
        : 'Talked through the project; no proposal yet',
    });
    if (reply.asks?.length) {
      noteStewardEffort({
        kind: 'question_raised',
        project_path: projectPath,
        project_id: opts.project_id ?? context.strip?.project_id ?? null,
        at: opts.at,
        summary: reply.asks[0],
      });
    }
    return appended;
  };

  // STEWARD FEEDBACK LANDS FOR REAL. The seat used to SAY "journaled" with no
  // hands (fabricated act, caught live 2026-08-06); now the reply's typed
  // journal entries are written durably here, and only this makes it true.
  let journaled = null;
  if (Array.isArray(reply.journal) && reply.journal.length) {
    const fed = appendStewardFeedback(projectPath, reply.journal, { at: opts.at });
    journaled = fed.ok
      ? { entries: fed.appended }
      : { entries: 0, error: fed.error };
  }

  // DETAIL ACCRUES BY TALKING. When he answered something the step in hand was missing,
  // it lands as a typed elaboration_answer on the spine — so the plan fills in as the
  // conversation goes, and he never has to sit down and scaffold it all up front.
  let elaborated = null;
  if (reply.answers && context.active_step && Object.keys(reply.answers).length) {
    const rec = recordElaborationAnswers(projectPath, {
      step_id: context.active_step.step_id ?? context.active_step.id,
      answers: reply.answers,
      who: opts.who ?? 'john',
      at: opts.at,
    });
    elaborated = rec.ok
      ? { recorded: Object.keys(reply.answers), step_id: rec.step_id ?? null }
      : { recorded: [], error: rec.error ?? rec.code };
  }

  // 7. No proposal yet — still gathering. Debit the call that was actually made.
  if (!reply.proposal) {
    const logged = recordTurns(null);
    const debit = debitSessionEnvelope(projectPath, {
      kind: 'compile',
      text: prompt,
      tokens: meta.usage.tokens || undefined,
      cost_usd: meta.usage.cost_usd,
      auth: opts.auth,
      client_event_id: opts.client_event_id ? `${opts.client_event_id}-turn` : undefined,
    });
    return {
      ok: true,
      lane: 'converse',
      say: reply.say,
      asks: reply.asks,
      gathering: true,
      proposal: null,
      // E1 (steward-e1 W2): every converse close carries its turn-close
      // verdict — an unenforceable bound rides BY NAME, never silently open.
      turn_close: turnClose,
      model_called: true,
      seat: { family: seats.coding_family, driver: seats.coding_driver },
      usage: meta.usage,
      debit: debit.ok ? { debited: true, shown: debit.shown } : { debited: false, ...debit },
      // Said explicitly rather than left undefined: a talking turn writes no steps, and
      // a caller checking `steps_written === false` deserves a true answer, not absence.
      steps_written: false,
      elaborated,
      journaled,
      // The chamber shows the commission card on this signal — the model
      // routes "start Gandalf" here instead of pretending work began.
      wants_commission: reply.wants_commission === true,
      commission_skill: reply.commission_skill ?? null,
      commission_directive: reply.commission_directive ?? null,
      // Spoken project management from the High Seat: the host renders the
      // confirm card; nothing is created until John clicks it.
      project_create: reply.project_create ?? null,
      ledger_write: false,
      // The transcript IS now kept (durable, non-authoritative). Say so honestly
      // rather than leaving a stale `false` that misdescribes what happened.
      dialogue_persisted: logged.ok === true,
      conversation_log: logged.ok
        ? { appended: logged.appended, total: logged.total }
        : { appended: 0, error: logged.error ?? logged.code },
    };
  }

  // 8. A proposal — emitted through the EXISTING spine path so the confirm side
  //    (hash-bound, batch, single writer) is reused byte-for-byte.
  const proposed = proposeScaffolding(projectPath, {
    goal: reply.proposal.goal,
    stages: reply.proposal.stages.map((s) => ({
      name: s.name,
      done_when: s.done_when,
      oranges: s.oranges,
      ...(s.step_type ? { step_type: s.step_type } : {}),
    })),
    tokens: meta.usage.tokens || undefined,
    cost_usd: meta.usage.cost_usd,
    auth: opts.auth,
    client_event_id: opts.client_event_id ? `${opts.client_event_id}-propose` : undefined,
    at: opts.at,
  });

  if (!proposed.ok) {
    return {
      ...proposed,
      lane: 'converse',
      say: reply.say,
      asks: reply.asks,
      model_called: true,
      conversational: true,
    };
  }

  // Tagged with the proposal hash, so the reasoning can be read alongside the exact
  // scaffolding version it produced — the "how did we get here" John asked for.
  const logged = recordTurns(proposed.proposal_hash, proposed.proposal.steps.length);

  return {
    ok: true,
    lane: 'converse',
    say: reply.say,
    asks: reply.asks,
    gathering: false,
    // E1 (steward-e1 W2): the proposal close carries its verdict too.
    turn_close: turnClose,
    conversation_log: logged.ok
      ? { appended: logged.appended, total: logged.total }
      : { appended: 0, error: logged.error ?? logged.code },
    proposal: proposed.proposal,
    proposal_hash: proposed.proposal_hash,
    proposal_id: proposed.proposal_id,
    proposal_kind: reply.proposal.kind,
    foresight: reply.proposal.foresight,
    step_count: proposed.proposal.steps.length,
    model_called: true,
    seat: { family: seats.coding_family, driver: seats.coding_driver },
    usage: meta.usage,
    debit: proposed.debit,
    steps_written: false,
    elaborated,
    journaled,
    ledger_write: false,
    dialogue_persisted: logged.ok === true,
    confirm_hint: 'Nothing is written yet — confirm and these become the campaign roadmap.',
  };
}

/**
 * Structural proof that a converse result carries no chat transcript into anything
 * durable. Used by the E5 test rather than trusting the prose above.
 *
 * @param {object} result
 * @returns {{ ok: boolean, leaked: string[] }}
 */
export function assertNoChatLeak(result) {
  const leaked = [];
  const walk = (v, trail) => {
    if (v == null) return;
    if (Array.isArray(v)) {
      v.forEach((item, i) => walk(item, `${trail}[${i}]`));
      return;
    }
    if (typeof v === 'object') {
      for (const [k, child] of Object.entries(v)) {
        if (/^(turns|transcript|chat|history|messages)$/i.test(k)) {
          leaked.push(trail ? `${trail}.${k}` : k);
        }
        walk(child, trail ? `${trail}.${k}` : k);
      }
    }
  };
  walk(result, '');
  return { ok: leaked.length === 0, leaked };
}

export { FACE_FILE_NAME, ACT_TABLE };
