#!/usr/bin/env node
// slim.mjs — S6 of the slim plan (2026-10-10, John's Q3): Crucible's SLIM profile.
//
// John: "a really efficient slimmed foreman so it's got a slimmed Crucible ... orchestrator one pass plan one internal
// review ... simple elegance check. Then it's presented to the user they can iterate it. Then it's locked."
//
// AT MOST THREE model calls, ONE human gate, and an honest record of who did what (final review 10-10, findings 3, 7, 8):
//   1. slim:plan         (role synthesizer - the drafting family) - a short North Star + a one-pass plan: pillars and,
//                        for each wave, ONE oracle per acceptance item, in the Foreman plan format.
//   2. shark:slim-review (role shark - the review family) - one adversarial review with the three elegance questions
//                        folded in. The hardening lint (property gates, no model call) runs beside it on the plan's
//                        REAL acceptance text (foreman-lib parseWaves carries it) and again after any revision.
//   3. slim:revise       (only when the review asks for changes) - one revision answering every BLOCKER/MAJOR.
// Provenance is what the seats' receipts SAY (trio.seat.v1, through onReceipt), never the route table: the review is
// called independent only when its attested served family differs from the family that actually drafted (a failover
// shows in the receipt); the same family is the installed honest policy, cross_model:false; a caller that REQUIRES
// independence is refused instead of being served a same-family review. The handoff is the whole Foreman contract -
// DESCRIPTION.md, IMPLEMENTATION-PLAN.md, EXECUTION-LOG.md, foreman.config.json (the North Star rides along) - and is
// validated by Foreman's own contract resolver (locate-plan, spawned), not by headings. Nothing written here claims an
// approval: the ONE gate is the human's. LITE/FULL Crucible (stage0-2) is unchanged; this is the separate, smaller path
// for reversible, fixed-scope work (Tier M).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { haltForHuman } from './crucible-lib.mjs';
import { checkPropertyGates } from './hardening-gate.mjs';
import { runWellFormednessGate } from './gates.mjs';
import { parseWaves, isNonCodeWave } from '../../foreman/bin/foreman-lib.mjs';

export const SLIM_MAX_MODEL_CALLS = 3;
export const SLIM_DOC_FILENAMES = Object.freeze({ description: 'DESCRIPTION.md', plan: 'IMPLEMENTATION-PLAN.md', execution_log: 'EXECUTION-LOG.md' });
export const SLIM_LABELS = Object.freeze({ draft: 'slim:plan', review: 'shark:slim-review', revise: 'slim:revise' });

export const REVIEW_SCHEMA = {
  type: 'object',
  required: ['verdict', 'findings'],
  properties: {
    verdict: { type: 'string', enum: ['APPROVE', 'REVISE'] },
    findings: {
      type: 'array',
      items: {
        type: 'object', required: ['severity', 'issue'],
        properties: { severity: { type: 'string', enum: ['BLOCKER', 'MAJOR', 'MINOR'] }, issue: { type: 'string' }, fix: { type: 'string' } },
      },
    },
  },
};

export function planPrompt(task, context = '') {
  return [
    'You are Crucible in its SLIM profile: plan this work in ONE pass, small and buildable by Foreman.',
    `The work: ${task}`,
    context ? `Context you may rely on:\n${context}` : '',
    'Write markdown with exactly these parts:',
    '# North Star  — at most 8 lines: `Objective: ...`, 2-4 success criteria, the non-goals.',
    '## Pillars  — 2-4 bullets: what the solution rests on.',
    'Then the waves, each `## Wave N — <title>` (N = 1, 2, ... in order), each with:',
    '  Done when: one bullet per acceptance item, EACH ending in `(oracle: <what proves it>)` — a command, an observable',
    '  fact, or a test file path. Name a test file (test/<name>.test.mjs, tests/test_<name>.py) ONLY for an item that',
    '  needs one: Foreman REQUIRES every named test file to exist before the wave can pass. Nothing else counts as a test.',
    '  A wave that makes no code (docs, a landing page, a verification, a render, data) adds',
    '  `kind: docs|landing|verification|render|data` and `outputs: <the files it must create or change>` instead of',
    '  tests; such a wave may not change source, tests, manifests, scripts or CI configuration.',
    'Add one line `test-command: <command>` when ANY wave makes code (Foreman refuses a code plan without it); a plan',
    'whose every wave is non-code needs none. Keep to the fewest waves that do the work. No preamble, no closing remarks.',
  ].filter(Boolean).join('\n');
}

export function reviewPrompt(task, plan, lint) {
  const missing = lintLines(lint);
  return [
    'You are an INDEPENDENT adversarial reviewer of a slim plan. REFUTE, do not praise. Read only what is below.',
    `The work it must deliver: ${task}`,
    '--- PLAN ---', plan, '--- END PLAN ---',
    missing.length
      ? `The hardening lint (crucible journal 0080) found property claims with no mechanical gate in any wave's acceptance text: ${missing.join('; ')}. A claim the plan makes without a gate is a MAJOR finding.`
      : 'The hardening lint found no property claim without a gate.',
    'Report each real defect (a wave that cannot be built or proven, an oracle that proves nothing, a missing',
    'acceptance item, a non-goal violated, a non-code wave that would need code) as BLOCKER or MAJOR, with the smallest fix.',
    'ELEGANCE (three questions, answer within your findings): (1) Is anything planned that the North Star does not',
    'need? (2) Is anything built that an existing function, file or library already does? (3) Is a test asked for',
    'beyond what an acceptance item needs? Report each real case as MAJOR. Nothing for taste.',
    'verdict: APPROVE when nothing BLOCKER/MAJOR remains, else REVISE.',
  ].filter(Boolean).join('\n');
}

export function revisePrompt(task, plan, findings) {
  return [
    'You are Crucible in its SLIM profile. Revise this plan to answer EVERY finding below; change nothing else.',
    `The work: ${task}`,
    '--- PLAN ---', plan, '--- END PLAN ---',
    'Findings to answer:', ...findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.issue}${f.fix ? ' — fix: ' + f.fix : ''}`),
    'Return the whole revised plan in the same markdown format (same parts, same `(oracle: ...)` grammar). No preamble.',
  ].join('\n');
}

const text = (x) => (typeof x === 'string' ? x : String(x?.text ?? x?.markdown ?? x?.plan ?? ''));

/** The North Star block of a slim plan (the "# North Star" section, heading included). */
export function northStarOf(plan) {
  const m = /^#\s+North Star[^\n]*\n([\s\S]*?)(?=^##?\s)/m.exec(plan);
  return m ? m[0].trim() : '';
}

/** The hardening lint over the plan and the waves' REAL acceptance text (final review 10-10, finding 8): parseWaves
 *  carries each wave's acceptance, and checkPropertyGates reads exactly that - one representation. */
export function lintOf(plan, waves) {
  return checkPropertyGates({ plan, waves });
}
const lintLines = (lint) => (lint?.missing || []).map((m) => `${m.id}: missing ${(m.unmet || []).join(', ')}`);

/** Validate the one review: an empty, malformed, verdict-less or failed answer never approves (final review 10-10). */
export function validateReview(raw) {
  const where = 'slim-review-invalid: check the review seat (the review family), then run the slim plan again';
  let obj = raw;
  if (typeof raw === 'string') { try { obj = JSON.parse(raw); } catch { obj = null; } }
  if (raw == null || raw === '' || !obj || typeof obj !== 'object' || Array.isArray(obj)) {
    throw haltForHuman(`slim review came back ${raw == null || raw === '' ? 'empty' : 'malformed (not a review object)'} — nothing was reviewed`, where);
  }
  if (obj.agent_failed || obj.transport_failed || obj.error) {
    throw haltForHuman(`slim review failed: ${obj.detail || obj.note || obj.error || 'the review seat reported a failure'} — nothing was reviewed`, where);
  }
  const verdict = String(obj.verdict ?? '').trim().toUpperCase();
  if (!['APPROVE', 'REVISE'].includes(verdict)) {
    throw haltForHuman(`slim review has no verdict (got ${JSON.stringify(obj.verdict ?? null)}; expected APPROVE or REVISE)`, where);
  }
  if (!Array.isArray(obj.findings)) throw haltForHuman('slim review has no findings list (an empty list means none)', where);
  const findings = obj.findings.map((f) => {
    const severity = String(f?.severity ?? '').trim().toUpperCase();
    const issue = typeof f?.issue === 'string' ? f.issue.trim() : '';
    if (!f || typeof f !== 'object' || !issue || !['BLOCKER', 'MAJOR', 'MINOR'].includes(severity)) {
      throw haltForHuman(`slim review has a malformed finding (${JSON.stringify(f ?? null).slice(0, 120)}): each needs a severity BLOCKER|MAJOR|MINOR and an issue`, where);
    }
    return { severity, issue, fix: typeof f.fix === 'string' ? f.fix.trim() : '' };
  });
  return { verdict, findings };
}

/**
 * What the seats' receipts SAID (trio.seat.v1 via onReceipt): the family that answered (the served family when
 * attested, else the driver of the last attempt - so a failover shows), the model, and whether the review was
 * independent of the draft. `independent` is null when no receipt said (a stub, or a seat that never answered) -
 * never claimed, then.
 */
export function provenanceOf(receipts = {}) {
  const seat = (label) => {
    const r = receipts[label];
    if (!r || typeof r !== 'object') return null;
    const last = Array.isArray(r.attempts) && r.attempts.length ? r.attempts[r.attempts.length - 1] : null;
    return {
      label, role: r.role ?? null, status: r.status ?? null, ok: r.ok === true,
      family: r.served?.family || last?.requested?.family || r.requested?.family || null,
      requested_family: r.requested?.family ?? null,
      model: r.served?.model ?? null,
      family_attested: r.served?.family_attested === true,
      model_attested: r.served?.model_attested === true,
      failover_used: r.failover?.used === true || Boolean(last && Number(last.ordinal) > 1),
    };
  };
  const draft = seat(SLIM_LABELS.draft);
  const review = seat(SLIM_LABELS.review);
  const revise = seat(SLIM_LABELS.revise);
  let independent = null;
  if (draft && review && draft.family && review.family) {
    independent = review.ok && review.family_attested && review.family !== draft.family;
  }
  return { draft, review, revise, independent, cross_model: independent === true };
}

/** One honest clause on who reviewed - never "the other family" unless the receipts say so. */
export function describeReview(prov, families = null) {
  const r = prov?.review;
  const d = prov?.draft;
  if (!r || !r.family) return 'one review ran (no receipt named its family — not claimed independent)';
  const model = r.model ? `${r.model}${r.model_attested ? '' : ', model unattested'}` : 'model not named';
  if (prov.independent === true) {
    return `one review by ${r.family} (${model}), independent of the drafting family ${d?.family ?? families?.coding ?? '?'}`;
  }
  if (!d?.family) {
    return `one review by ${r.family} (${model}) — the drafting family is not on record, so independence is not claimed: cross_model:false`;
  }
  if (d.family !== r.family) {
    return `one review by ${r.family} (${model}; family unattested) — independence not proven: cross_model:false`;
  }
  return `one review by ${r.family} (${model}) — the SAME family that drafted${d.failover_used ? ' (the draft failed over)' : ''}: cross_model:false`;
}

function titleOf(task, northStar) {
  const m = /^Objective:\s*(.+)$/mi.exec(northStar || '');
  const t = (m ? m[1] : String(task)).trim().split(/\r?\n/)[0].replace(/[.\s]+$/, '');
  return t.length > 80 ? t.slice(0, 77) + '…' : t;
}

/** REVIEW.md: the verdict, the findings, who did what (from the receipts), the lint before and after. */
export function renderSlimReview({ review, revised, lint, lintBefore, provenance, calls, families = null }) {
  const seat = (s) => (s
    ? `${s.family ?? '?'} (${s.model ?? 'model not named'}; family ${s.family_attested ? 'attested' : 'unattested'}, model ${s.model_attested ? 'attested' : 'unattested'}${s.failover_used ? ', FAILED OVER' : ''}; ${s.status ?? '?'})`
    : 'no receipt');
  return [
    '# Slim review', '',
    `verdict: ${review.verdict}${revised ? ' (plan revised once to answer it)' : ''}`, '',
    ...(review.findings.length ? review.findings.map((f) => `- [${f.severity}] ${f.issue}${f.fix ? ' — fix: ' + f.fix : ''}`) : ['- no findings']), '',
    '## Who did what (from the seats\' receipts)', '',
    `- draft: ${seat(provenance?.draft)}`,
    `- review: ${seat(provenance?.review)}`,
    ...(provenance?.revise ? [`- revision: ${seat(provenance.revise)}`] : []),
    `- independent review: ${provenance?.independent === true ? 'yes' : provenance?.independent === false ? `NO — ${describeReview(provenance, families)}` : 'not claimed (no receipt named the families)'}`,
    `- cross_model: ${provenance?.cross_model === true}`, '',
    '## Hardening lint (crucible journal 0080, over the waves\' acceptance text)', '',
    `- before review: ${lintBefore?.pass ? 'clean' : lintLines(lintBefore).join('; ')}`,
    ...(revised ? [`- after revision: ${lint?.pass ? 'clean' : lintLines(lint).join('; ')}`] : []), '',
    `model calls: ${calls} of at most ${SLIM_MAX_MODEL_CALLS}`, '',
  ].join('\n');
}

/**
 * The Foreman handoff: the doc trio + foreman.config.json (so locateDocs resolves via config, never the *.md
 * heuristic), the North Star beside them, and REVIEW.md with the honest provenance. Written directly rather than
 * through stage2's writeDocTrio, which would inject the Stage-2 hardening boilerplate and a run-all-tests script a
 * slim plan did not ask for. No file here claims an approval.
 */
export function writeSlimHandoff({ outDir, plan, northStar, task, waves, review, revised, lint, lintBefore, provenance, calls, depth = 'LITE', tier = 'standard', title = null, families = null }) {
  const dir = path.resolve(outDir);
  fs.mkdirSync(dir, { recursive: true });
  const name = title || titleOf(task, northStar);
  const files = {
    dir,
    description: path.join(dir, SLIM_DOC_FILENAMES.description),
    plan: path.join(dir, SLIM_DOC_FILENAMES.plan),
    execution_log: path.join(dir, SLIM_DOC_FILENAMES.execution_log),
    north_star: path.join(dir, 'NORTH-STAR.md'),
    review: path.join(dir, 'REVIEW.md'),
    config: path.join(dir, 'foreman.config.json'),
  };
  fs.writeFileSync(files.plan, plan.trimEnd() + '\n', 'utf8');
  fs.writeFileSync(files.north_star, (northStar || `# North Star\n(not stated separately — see ${SLIM_DOC_FILENAMES.plan})`) + '\n', 'utf8');
  fs.writeFileSync(files.description, [
    `# ${name} — Description`, '',
    northStar || '# North Star\n(see the implementation plan)', '',
    '## The work', '', String(task).trim(), '',
    '## Waves', '',
    ...waves.map((w) => `- Wave ${w.n} — ${w.title || '(untitled)'}: ${isNonCodeWave(w)
      ? `${w.waveKind} wave, outputs ${w.outputs.join(', ')}`
      : `code wave, ${(w.oracles || []).length} acceptance item(s) with an oracle`}`), '',
    '## Provenance', '',
    `Planned by Crucible's slim profile (one draft, one review, at most one revision; ${calls} model call(s)). ` +
      `Review: ${describeReview(provenance, families)}; verdict ${review.verdict}${revised ? ', plan revised once to answer it' : ''}. ` +
      `Hardening lint: ${lint.pass ? 'clean' : lintLines(lint).join('; ')}.`, '',
    'Not yet approved: the implementation-plan-approval gate is the human\'s. Foreman builds only what the human approves.', '',
  ].join('\n'), 'utf8');
  fs.writeFileSync(files.execution_log, [
    `# ${name} — Execution Log`, '',
    `Foreman records per-wave build outcomes below. ${waves.length} wave(s) planned.`, '',
    '## Waves', '',
    '_(no waves built yet — Foreman appends a GREEN/HALT entry per wave)_', '',
  ].join('\n'), 'utf8');
  fs.writeFileSync(files.review, renderSlimReview({ review, revised, lint, lintBefore, provenance, calls, families }), 'utf8');
  fs.writeFileSync(files.config, JSON.stringify({
    profile: 'slim',
    triage_track: depth,
    triage: { depth, tier, source: 'slim' },
    docs: { ...SLIM_DOC_FILENAMES },
  }, null, 2) + '\n', 'utf8');
  return files;
}

/**
 * Run the slim profile. `agent(prompt, {label, role, schema, onReceipt})` is the Crucible agent seam (live: the
 * role-routed agent from buildLiveCrucibleAgent; tests: a stub). Returns the plan, the review, the provenance, the
 * written handoff and `gate` - the ONE HALT-for-human (the caller throws or shows it). Throws a HaltError when the
 * plan is not buildable, the review is unusable, independence was required but not proven, or the handoff fails
 * Foreman's contract; the error carries `slim: { calls, provenance }` so a stop is journaled with its receipts.
 */
export async function runSlim({
  agent, task, context = '', outDir = null, log = () => {},
  requireIndependentReview = false,
  families = null,          // { coding, review } from buildLiveCrucibleAgent (Anchor prefs); null when unknown (stubs)
  depth = 'LITE', tier = 'standard',
  wellFormedness = null,    // injectable handoff validator; default spawns Foreman's locate-plan (gates.mjs)
  title = null,
} = {}) {
  if (typeof agent !== 'function') throw new TypeError('runSlim requires an agent');
  if (!task || !String(task).trim()) throw new TypeError('runSlim requires a task');
  // the installed same-family policy: allowed and stamped cross_model:false - unless independence is REQUIRED
  if (requireIndependentReview && families?.coding && families.coding === families.review) {
    throw haltForHuman(
      `slim: an independent review is required but the coding and review families are both "${families.coding}" — refusing to run a same-family review as independent`,
      'slim-independent-review-unavailable: set a different review family (Anchor model prefs), or run without --require-independent (the record then says cross_model:false)');
  }
  const receipts = {};       // label -> trio.seat.v1 receipt: what the seat SAID it was served by (a failed seat's too)
  let calls = 0;
  const call = async (prompt, opts) => {
    if (calls >= SLIM_MAX_MODEL_CALLS) throw new Error('slim profile: model-call budget exhausted');
    calls += 1;
    try {
      return await agent(prompt, { ...opts, onReceipt: (r) => { receipts[opts.label] = r; } });
    } catch (e) {
      if (e && typeof e === 'object' && e.receipt) receipts[opts.label] = e.receipt;
      throw e;
    }
  };
  try {
    const draftRaw = await call(planPrompt(task, context), { label: SLIM_LABELS.draft, role: 'synthesizer' });
    if (draftRaw && typeof draftRaw === 'object' && (draftRaw.agent_failed || draftRaw.transport_failed)) {
      throw haltForHuman(`slim plan: the drafting seat failed (${draftRaw.detail || draftRaw.note || 'no answer'})`,
        'slim-draft-failed: check the drafting seat, then run the slim plan again');
    }
    let plan = text(draftRaw).trim();
    if (!plan) throw haltForHuman('slim plan came back empty', 'slim-draft-empty: check the drafting seat, then run the slim plan again');
    let waves = parseWaves(plan);                 // HaltError when Foreman could not build it - before any review is spent
    const lintBefore = lintOf(plan, waves);
    let lint = lintBefore;

    const review = validateReview(await call(reviewPrompt(task, plan, lint), { label: SLIM_LABELS.review, role: 'shark', schema: REVIEW_SCHEMA }));
    let provenance = provenanceOf(receipts);
    if (requireIndependentReview && provenance.independent !== true) {
      const r = provenance.review;
      const d = provenance.draft;
      throw haltForHuman(
        `slim: an independent review is required but ${r?.family
          ? `the review was served by ${r.family}${d?.family ? ` and the draft by ${d.family}` : ''}${r.family_attested ? '' : ' (family unattested)'}`
          : 'no receipt names the review family'} — not independent`,
        'slim-independent-review-unavailable: check the review seat and the model prefs, then run the slim plan again');
    }

    const serious = review.findings.filter((f) => f.severity === 'BLOCKER' || f.severity === 'MAJOR');
    let revised = false;
    if (review.verdict === 'REVISE' || serious.length) {
      const next = text(await call(revisePrompt(task, plan, serious.length ? serious : review.findings), { label: SLIM_LABELS.revise, role: 'synthesizer' })).trim();
      if (!next) {
        throw haltForHuman('slim revision came back empty — the reviewed plan stands unrevised and is NOT handed on',
          'slim-revise-empty: check the drafting seat, then run the slim plan again');
      }
      waves = parseWaves(next);                   // a revision Foreman could not build is refused, never handed on
      plan = next;
      revised = true;
      lint = lintOf(plan, waves);                 // recomputed on the revised acceptance text (final review 10-10, finding 8)
      provenance = provenanceOf(receipts);
    }

    const northStar = northStarOf(plan);
    let files = null;
    let handoff = null;
    if (outDir) {
      files = writeSlimHandoff({ outDir, plan, northStar, task, waves, review, revised, lint, lintBefore, provenance, calls, depth, tier, title, families });
      // "validate the production handoff, not just headings": Foreman's OWN contract resolver over the written dir
      const check = typeof wellFormedness === 'function' ? wellFormedness : runWellFormednessGate;
      handoff = check({ projectDir: files.dir, artifactsDir: files.dir, log });
      if (!handoff || handoff.pass !== true) {
        throw haltForHuman(
          `slim handoff is not buildable by Foreman's contract resolver: ${String(handoff?.stderr || '').trim() || 'the well-formedness gate did not pass'}`,
          'slim-handoff-unbuildable: fix the plan (a code wave needs `test-command:`, every wave a `## Wave N` heading), then run the slim plan again');
      }
    }
    const who = describeReview(provenance, families);
    log(`slim: ${calls} model call(s) · review ${review.verdict}${revised ? ', revised once' : ''} · ${who} · lint ${lint.pass ? 'clean' : lintLines(lint).join('; ')}`);
    const gate = haltForHuman(
      `Your call: approve this slim plan (its North Star is at the top) and hand it to the builder? ${who}` +
      `${revised ? '; the plan was revised once to answer it' : ''}. ` +
      (lint.pass ? 'Hardening lint: clean. ' : `Hardening lint still names ${lint.missing.length} claim(s) without a gate: ${lintLines(lint).join('; ')}. `) +
      'Approve, edit, or tell me something else?',
      'implementation-plan-approval (slim: the one gate)');
    return {
      plan, northStar, waves, review, findings: review.findings, revised, calls, lint, lintBefore, provenance,
      independent: provenance.independent, cross_model: provenance.cross_model,
      outDir: files?.dir ?? null, files, handoff, gate,
    };
  } catch (e) {
    if (e && typeof e === 'object') e.slim = { calls, provenance: provenanceOf(receipts) };
    throw e;
  }
}

/**
 * The Skill Foundry "Run capture" record (AGENTS.md): the machine layer of Crucible's two-layer journal, written by
 * the engine for every real slim run; the NNNN human entry stays human-written (`--journal-ref` pairs them). The
 * models list is what the receipts said - a halted run keeps the receipts of the seats that did answer.
 */
export function slimRunRecord({ started, t0, task, depth, tier, requireIndependent = false, contextFile = null, result = null, failure = null, journalRef = null }) {
  const prov = result?.provenance ?? failure?.slim?.provenance ?? null;
  const models = [];
  for (const [role, s] of [['draft', prov?.draft], ['review', prov?.review], ['revision', prov?.revise]]) {
    if (s) models.push({ role, family: s.family, model_served: s.model, model_attested: s.model_attested, family_attested: s.family_attested, status: s.status, failover_used: s.failover_used });
  }
  const files = result?.files;
  return {
    skill: 'crucible', tier: 'slim',
    started, ended: new Date().toISOString(),
    input: task,
    params: { profile: 'slim', depth, tier, require_independent: !!requireIndependent, context_file: contextFile,
      calls: result?.calls ?? failure?.slim?.calls ?? 0, max_calls: SLIM_MAX_MODEL_CALLS },
    output: files ? [files.plan, files.description, files.execution_log, files.config, files.review] : [],
    result: result
      ? `gate: implementation-plan-approval — review ${result.review.verdict}${result.revised ? ', revised once' : ''}; ${describeReview(prov)}; lint ${result.lint?.pass ? 'clean' : 'open'}`
      : `HALT: ${failure?.message || failure || 'unknown'}${failure?.pending_action ? ' — ' + failure.pending_action : ''}`,
    cross_model: prov?.cross_model === true,
    models,
    duration_s: Math.round((Date.now() - (t0 ?? Date.now())) / 1000),
    journal_ref: journalRef,
  };
}

/** Write the run record under crucible/journal/runs (CRUCIBLE_RUNS_DIR or `runsDir` redirect it). Never throws. */
export function writeSlimRunRecord(record, { runsDir = null } = {}) {
  try {
    const skillDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    const dir = runsDir || process.env.CRUCIBLE_RUNS_DIR || path.join(skillDir, 'journal', 'runs');
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, `${String(record.started).replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`);
    fs.writeFileSync(file, JSON.stringify(record, null, 2) + '\n', 'utf8');
    return file;
  } catch { return null; }   // the record is never worth a crash; the CLI says aloud when it is missing
}

// ---------------------------------------------------------------- CLI
// node crucible/bin/slim.mjs <outDir> --task "<the work>" [--context-file <path>] [--project <dir>]
//      [--depth LITE|FULL] [--tier standard|heavy] [--require-independent] [--journal-ref NNNN-slug] [--title "<name>"]
function isMain() {
  try { return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(process.argv[1] || ''); } catch { return false; }
}

if (isMain()) {
  const argv = process.argv.slice(2);
  const VALUE_FLAGS = new Set(['--task', '--context-file', '--depth', '--tier', '--journal-ref', '--title', '--project']);
  const flag = (n) => { const i = argv.indexOf(n); return i >= 0 && i + 1 < argv.length ? argv[i + 1] : null; };
  const outDir = argv.find((a, i) => !a.startsWith('--') && !(i > 0 && VALUE_FLAGS.has(argv[i - 1])));
  const task = flag('--task');
  const requireIndependent = argv.includes('--require-independent');
  if (!outDir || !task) {
    process.stderr.write('usage: node crucible/bin/slim.mjs <outDir> --task "<the work>" [--context-file <path>] [--project <dir>] ' +
      '[--depth LITE|FULL] [--tier standard|heavy] [--require-independent] [--journal-ref NNNN-slug] [--title "<name>"]\n');
    process.exit(2);
  }
  const started = new Date().toISOString();
  const t0 = Date.now();
  const depth = String(flag('--depth') || 'LITE').toUpperCase();
  const tier = String(flag('--tier') || 'standard').toLowerCase();
  const contextFile = flag('--context-file');
  const log = (s) => console.log(s);
  let r = null;
  let failure = null;
  try {
    const context = contextFile ? fs.readFileSync(contextFile, 'utf8') : '';
    // the live, role-routed agent: drafting on the coding family, review on the review family (Anchor prefs); the
    // builder refuses a same-family review only when independence is REQUIRED (the installed policy otherwise allows
    // it, stamped cross_model:false)
    const { buildLiveCrucibleAgent } = await import('./enhanced.mjs');
    const built = await buildLiveCrucibleAgent({ env: process.env, target: flag('--project') || process.cwd(), log, requireCrossFamily: requireIndependent });
    log(`slim: drafting family ${built.families.coding} · review family ${built.families.review}${built.families.coding === built.families.review ? ' (same family: cross_model:false)' : ''}`);
    r = await runSlim({ agent: built.agent, task, context, outDir, log, requireIndependentReview: requireIndependent, families: built.families, depth, tier, title: flag('--title') });
    console.log(`SLIM_PLAN ${r.files.plan}`);
    console.log(`GATE ${r.gate.message}`);
  } catch (e) {
    failure = e;
    console.error(`slim plan stopped: ${e?.message || e}${e?.pending_action ? ' — ' + e.pending_action : ''}`);
  }
  const recordPath = writeSlimRunRecord(slimRunRecord({ started, t0, task, depth, tier, requireIndependent, contextFile, result: r, failure, journalRef: flag('--journal-ref') }));
  console.log(recordPath ? `slim: run record ${recordPath}` : 'slim: !! run record NOT written (journal/runs unwritable)');
  process.exit(failure ? 3 : 0);
}
