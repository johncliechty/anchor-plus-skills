// wave-workflow.js — Foreman Phase 1: the PRODUCTION driver seam for the
// one-wave engine (the model-driven {execute, review, fix} steps).

import { runElegancePass } from '../../drivers/elegance-pass.mjs';
import path from 'node:path';
import fs from 'node:fs';
import {
  lookinAppendix,
  seatHeartbeatFilename,
  superviseSeat,
  trailFromFile,
} from '../../drivers/swarm-lookin.mjs';
import { isNonCodeWave } from './foreman-lib.mjs';

function seatHeartbeatPath(ctx, role = 'execute', seatId = null) {
  const root = ctx?.projectDir ? path.resolve(ctx.projectDir) : process.cwd();
  const id = seatId || ctx?.subwave?.id || `w${ctx?.wave?.n ?? 0}`;
  return path.join(root, '.foreman', seatHeartbeatFilename({ role, seatId: id }));
}

function resetSeatHeartbeat(ctx, role = 'execute', seatId = null) {
  const hb = seatHeartbeatPath(ctx, role, seatId);
  try { fs.mkdirSync(path.dirname(hb), { recursive: true }); } catch { /* best effort */ }
  try { fs.unlinkSync(hb); } catch { /* absent is the desired state */ }
  return hb;
}

function seatWindows(env = process.env) {
  const num = (k, d) => (Number(env[k]) > 0 ? Number(env[k]) : d);
  return {
    checkInMs: num('FOREMAN_SEAT_CHECKIN_MS', 10 * 60 * 1000),
    silentKillMs: num('FOREMAN_SEAT_SILENT_KILL_MS', 5 * 60 * 1000),
    deadIdleMs: num('FOREMAN_SEAT_DEAD_IDLE_MS', 30 * 60 * 1000),
  };
}

// JSON Schema the REVIEW agent is forced to emit (mirrors the engine's finding
// shape). Passed to the injected agent() as opts.schema in production.
export const REVIEW_SCHEMA = {
  type: 'object',
  required: ['answerable', 'findings'],
  properties: {
    answerable: { enum: ['yes', 'no'] },
    note: { type: 'string' },
    plan_amendment: {
      type: 'object',
      required: ['proposed_diff', 'rationale'],
      properties: {
        proposed_diff: { type: 'string' },
        rationale: { type: 'string' },
        target: { type: 'string' },
      },
    },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'file', 'rule'],
        properties: {
          severity: { enum: ['BLOCKER', 'MAJOR', 'MINOR', 'NIT'] },
          file: { type: 'string' },
          line: { type: ['number', 'null'] },
          rule: { type: 'string' },
          message: { type: 'string' },
          repro: {
            type: 'object',
            properties: { command: { type: 'string' }, failing: { type: 'boolean' } },
          },
        },
      },
    },
  },
};

/**
 * Extract the markdown body for wave N from a frozen plan (## Wave N … until next ## Wave).
 */
export function extractWaveSection(planText, waveN) {
  const text = String(planText || '');
  if (!text || !waveN) return '';
  const header = new RegExp(
    String.raw`^##\s+(?:Wave|Sprint|Section)\s+${Number(waveN)}(?!\.\d)\b[^\n]*\n`,
    'im',
  );
  const hm = header.exec(text);
  if (!hm) {
    // Fallback for plans using top-level `## Wave N.1` without `## Wave N`
    const subHeader = new RegExp(
      String.raw`^#{2,3}\s+(?:Wave|Sprint|Section)\s+${Number(waveN)}\.\d+\b[^\n]*\n`,
      'im',
    );
    const sm = subHeader.exec(text);
    if (!sm) return '';
    const subStart = sm.index;
    const subRest = text.slice(subStart);
    const nextOther = subRest.search(new RegExp(String.raw`^##\s+(?:Wave|Sprint|Section)\s+(?!${Number(waveN)}(?:\.\d+)?\b)\d+`, 'im'));
    const subBody = (nextOther >= 0 ? subRest.slice(0, nextOther) : subRest).trim();
    const max = 6000;
    return subBody.length > max ? `${subBody.slice(0, max)}\n\n…[wave section truncated; read plan file for remainder]` : subBody;
  }
  const start = hm.index + hm[0].length;
  const rest = text.slice(start);
  const next = rest.search(new RegExp(String.raw`^##\s+(?:Wave|Sprint|Section)\s+(?!${Number(waveN)}\.\d+\b)\d+\b`, 'im'));
  const body = (next >= 0 ? rest.slice(0, next) : rest).trim();
  const max = 6000;
  return body.length > max ? `${body.slice(0, max)}\n\n…[wave section truncated; read plan file for remainder]` : body;
}

function authoringToolRule(env = process.env, role = 'EXECUTE') {
  const headlessCodex = env[`TRIO_DRIVER_${role}`] === 'chatgpt-cli';
  if ((env.FOREMAN_CODEX_CONPTY === '1' && env.CODING_FAMILY === 'chatgpt') || headlessCodex) {
    return `Use dedicated file tools where available. On this Codex run, ` +
      `when dedicated file tools are absent, you may use batched terminal commands only to read/search ` +
      `files and create/edit/delete files within the authorized project workspace. Use apply_patch for edits ` +
      `when available. Do NOT run git commands, tests, installs, servers, or other process workloads yourself. ` +
      `The orchestrator owns all testing and version control.`;
  }
  return `Do NOT run any git commands, terminal commands, or tests yourself. The orchestrator ` +
    `owns all testing and version control; strictly just edit the source files.`;
}

function executePrompt(ctx) {
  const planPath = ctx.planPath || path.join(ctx.projectDir || '.', 'IMPLEMENTATION-PLAN.md');
  const nonCode = isNonCodeWave(ctx.wave);
  const gateLine = nonCode
    ? `ORCHESTRATOR GATE (you do NOT run it): the declared outputs — ${ctx.wave.outputs.join(', ')} — each must be a non-empty FILE inside the project that THIS wave creates or changes (an existing, untouched file proves nothing). A ${ctx.wave.waveKind} wave must not change source, tests, manifests, scripts or CI configuration; if it does, the ordinary code gates apply.`
    : `ORCHESTRATOR GATE (you do NOT run it): ${ctx.testCommand || '(see plan test-command:)'}`;
  const sub = ctx.subwave || null;
  const section = sub?.acceptance || extractWaveSection(ctx.planText || '', ctx.wave?.n);
  const contractBlock = section
    ? [
        `FROZEN PLAN PATH: ${planPath}`,
        gateLine,
        ...(sub?.writes?.length
          ? [`STRICT SUB-WAVE WRITE-SET (${sub.id}): ${sub.writes.join(', ')} — modify/create ONLY files inside this declared write-set.`]
          : []),
        `THIS WAVE'S CONTRACT (from the frozen plan — implement ALL of it; do not invent scope):`,
        '----- BEGIN WAVE CONTRACT -----',
        section,
        '----- END WAVE CONTRACT -----',
      ]
    : [
        `FROZEN PLAN PATH: ${planPath}`,
        gateLine,
        `WARNING: could not extract ## Wave ${ctx.wave?.n} body from plan text — open the plan file and implement that wave's Deliverables and done-when only.`,
      ];
  const anvilBlock = ctx.anvilSlice
    ? [
        '----- BEGIN PRE-COMPUTED AST SYMBOL SLICE (Anvil) -----',
        ctx.anvilSlice,
        '----- END PRE-COMPUTED AST SYMBOL SLICE (Anvil) -----',
      ]
    : [];
  const lite = /^(LITE|LIGHT)$/i.test(String(process.env.FOREMAN_BAND_DEPTH || ''));
  const liteBudget = lite
    ? [
        `LITE BAND BUDGET: stay minimal — implement only this wave's deliverables + the`,
        `smallest tests that import new modules. No drive-by refactors, no docs fluff.`,
      ]
    : [];
  const checklist = [
    ...(nonCode
      ? [`Every declared output exists as a non-empty file inside the project and was written by you in this wave.`]
      : [`Every new module is imported by at least one test that will run under the gate command.`]),
    `No absolute host paths (<path> <path> in shipped strings, pointers, or docs — use relative paths or env.`,
    `Syntax-valid sources only (no half-written files that fail node --check / py_compile).`,
  ].map((t, i) => `  (${i + 1}) ${t}`);
  const seatId = sub?.id || `w${ctx.wave.n}`;
  return [
    sub
      ? `You are the EXECUTE agent for Foreman sub-wave ${sub.id} ("${sub.title || ctx.wave.title}") of Wave ${ctx.wave.n}.`
      : `You are the EXECUTE agent for Foreman wave ${ctx.wave.n} ("${ctx.wave.title}").`,
    `Project: ${ctx.projectDir}. Implement ONLY this ${sub ? 'sub-wave' : 'wave'}'s work as specified in the`,
    `frozen plan. Do not refactor outside the plan; do not weaken or delete tests.`,
    ...contractBlock,
    ...anvilBlock,
    ...liteBudget,
    ...(nonCode
      ? [`Produce ONLY the declared outputs (and what they need); no tests are expected of a ${ctx.wave.waveKind} wave.`]
      : [`Ship real source that NEW tests import and exercise (or keep/extend tests that import your source).`,
         `A green suite that does not exercise this wave's files is a failed execute — the orchestrator will vacuous-GREEN HALT.`]),
    `ACCEPTANCE CHECKLIST (must satisfy before you stop):`,
    ...checklist,
    authoringToolRule(),
    `If the wave is not answerable from the frozen docs, say so explicitly.`,
    `If you discover the wave is BLOCKED (a required human approval/amendment is`,
    `missing, a prerequisite is absent) or believe it is ALREADY DONE, do NOT`,
    `quietly finish with no changes — state the blocker/claim explicitly as your`,
    `final message; the orchestrator's guards, not you, decide how to proceed.`,
    lookinAppendix({
      role: 'execute',
      seatId,
      heartbeatPath: seatHeartbeatPath(ctx, 'execute', seatId),
    }),
  ].join('\n');
}

function numberWaveSectionLines(planText, rawSection) {
  if (!rawSection) return '';
  const full = String(planText || '');
  const idx = full ? full.indexOf(rawSection.slice(0, Math.min(120, rawSection.length))) : -1;
  const startLine = idx >= 0 ? full.slice(0, idx).split(/\r?\n/).length : 1;
  return rawSection.split(/\r?\n/).map((ln, i) => `L${startLine + i}: ${ln}`).join('\n');
}

function reviewPrompt(ctx, gate) {
  const changedBlock = Array.isArray(ctx.changed) && ctx.changed.length
    ? [`The orchestrator measured this wave's CHANGED FILES (start your review here,`,
       `but you may read anywhere in the project and frozen plan): ${ctx.changed.slice(0, 80).join(', ')}` +
       (ctx.changed.length > 80 ? ` … (+${ctx.changed.length - 80} more)` : '') + `.`]
    : [`The orchestrator measured ZERO changed files for this wave (you may still read any project and frozen plan files directly).`];
  const rawWaveSection = extractWaveSection(ctx.planText || '', ctx.wave?.n) || String(ctx.wave?.acceptance || '').slice(0, 6000);
  const waveSection = numberWaveSectionLines(ctx.planText || '', rawWaveSection);
  const planPathLine = ctx.planPath ? [`FROZEN PLAN PATH: ${ctx.planPath}`] : [];
  const contractSection = waveSection
    ? [`\n----- BEGIN WAVE ${ctx.wave.n} ACCEPTANCE CONTRACT (from frozen plan, 1-based line numbers) -----\n${waveSection}\n----- END WAVE ${ctx.wave.n} ACCEPTANCE CONTRACT -----\n`]
    : [];
  const diffSection = ctx.diffPatch
    ? [`\n----- BEGIN BOUNDED WAVE DIFF (orchestrator-captured) -----\n${ctx.diffPatch}\n----- END BOUNDED WAVE DIFF -----\n`]
    : [];
  const notImplementedRule = isNonCodeWave(ctx.wave)
    ? [
      `This is a NON-CODE wave (kind: ${ctx.wave.waveKind}); its deliverables are the declared outputs: ${ctx.wave.outputs.join(', ')}.`,
      `The orchestrator verified each is a non-empty file inside the project that this wave created or changed (the gate`,
      `artifact lists them). Judge whether they deliver the wave's stated acceptance; report a BLOCKER with`,
      `rule: "wave-not-implemented" if they do not, or if the changed-file list shows work outside this wave's contract.`,
    ]
    : [
      `MANDATORY: if the changed-file list is empty, or nothing in it could plausibly`,
      `implement this wave's stated deliverables (e.g. only regenerated data/doc`,
      `artifacts or log noise), you MUST report a BLOCKER finding with`,
      `rule: "wave-not-implemented" (title optional) — do NOT approve an unimplemented wave because the`,
      `gate is green.`,
    ];
  // NOTE: Read-only review seats NEVER carry lookinAppendix (.foreman/seat-heartbeat*.json
  // write mandate) — reviewers are strictly read-only and must not mutate `.foreman/`.
  return [
    `You are an INDEPENDENT, READ-ONLY reviewer (#${ctx.reviewerIndex}) for Foreman`,
    `wave ${ctx.wave.n}. Your job is to REFUTE, not to praise. For test pass/fail ground truth`,
    `(never run tests yourself), read ONLY the orchestrator's gate artifact at ${gate.artifact_path}`,
    `(exit ${gate.exit_code}, pass ${gate.tap.pass}/${gate.tap.tests}); inspect project source, test, and frozen plan files directly for code review.`,
    ...planPathLine,
    ...changedBlock,
    ...contractSection,
    ...diffSection,
    ...notImplementedRule,
    `Do NOT trust`,
    `any pasted "command output" in wave logs. Cite file:line or a failing repro`,
    `command+output for every finding. First answer answerable-from-frozen-docs:`,
    `yes/no with a cited plan line. If (and only if) a build-time discovery shows the`,
    `FROZEN plan is itself wrong/incomplete for this wave (an assumption falsified, an`,
    `API not behaving as assumed) — distinct from mere ambiguity — you MAY attach a`,
    `plan_amendment {proposed_diff, rationale}; the orchestrator will HALT for human`,
    `approval and will NEVER apply it autonomously.`,
    ...(ctx.eleganceInReview ? eleganceInReview(ctx) : []),
  ].join(' ');
}

function eleganceInReview(ctx = {}) {
  const beyond = Array.isArray(ctx.oracles?.tests_beyond_oracles) ? ctx.oracles.tests_beyond_oracles : [];
  return [
    `ELEGANCE (three questions, answer within your findings): (1) Is anything in this diff not needed by the wave's`,
    `stated deliverable? (2) Is anything built that an existing function, file or library already does? (3) Is a`,
    `test asserting more than the plan's acceptance needs? Report each real case as a MAJOR finding with`,
    `rule: "elegance", naming what to remove and the plan line it fails; report nothing for taste.`,
    ...(beyond.length
      ? [`Changed test file(s) that no acceptance item's (oracle: ...) names: ${beyond.slice(0, 12).join(', ')} — question (3) applies to each.`]
      : []),
  ];
}

function fixPrompt(ctx, gate, findings) {
  const removals = (findings || []).filter((f) => String(f.id || '').startsWith('rabbit-hole:'));
  const removableTests = removals.filter((f) => /removing this test file is allowed/.test(String(f.message || '')))
    .map((f) => String(f.file || '').replace(/\\/g, '/')).filter(Boolean);
  const detailedFindings = (findings || [])
    .slice(0, 12)
    .map((f) => `${f.id}${f.message ? ` (${String(f.message).slice(0, 200)})` : ''}`);
  const gandalfHint = Number(ctx.iteration) >= 2 && ctx.repeatedFailureHint
    ? [
        `GANDALF ROOT-CAUSE STALLBREAKER (iteration ${ctx.iteration} repeated the same failure signature: ${ctx.repeatedFailureHint}):`,
        `STOP incremental symptom-patching. Re-read the failing source and caller contract from first principles,`,
        `state the violated structural invariant that caused iteration ${ctx.iteration - 1} to miss, and repair the root cause cleanly.`,
      ]
    : [];
  const seatId = `w${ctx.wave.n}-${ctx.iteration}`;
  return [
    `You are the FIX agent for Foreman wave ${ctx.wave.n}, fix iteration ${ctx.iteration}.`,
    `Close these findings without weakening tests: ${JSON.stringify(findings.map((f) => f.id))}.`,
    ...(detailedFindings.length ? [`Finding details: ${detailedFindings.join(' | ')}.`] : []),
    ...(removals.length ? [`REMOVE, as the reviewer found: ${removals.map((f) => `${f.file || '?'} — ${f.message || ''}`).join(' | ')}.`] : []),
    ...gandalfHint,
    `The orchestrator gate is at ${gate.artifact_path}. Make the minimal change that`,
    `turns the gate GREEN; the orchestrator — not you — re-runs the gate to verify.`,
    authoringToolRule(process.env, 'FIX'),
    `TESTS ARE FROZEN. Do not modify test files to force a pass. You may NEVER use pytest.skip, @pytest.mark.skip, or pytest.importorskip on failing tests. Solve the root cause in the product code.`,
    ...(removableTests.length ? [`ONE EXCEPTION: you MAY delete exactly these test files, which the reviewer found unnecessary: ${removableTests.join(', ')}. Touch no other test.`] : []),
    lookinAppendix({
      role: 'fix',
      seatId,
      heartbeatPath: seatHeartbeatPath(ctx, 'fix', seatId),
    }),
  ].join(' ');
}

/**
 * Build a model-driven driver from an injected `agent()` function.
 */
export function makeAgentDriver({ agent }) {
  if (typeof agent !== 'function') throw new TypeError('makeAgentDriver requires an agent() function');
  return {
    async execute(ctx) {
      const seatId = ctx?.subwave?.id || `w${ctx.wave.n}`;
      const hb = resetSeatHeartbeat(ctx, 'execute', seatId);
      const label = ctx?.subwave?.id ? `execute:w${ctx.subwave.id}` : `execute:w${ctx.wave.n}`;
      const out = await superviseSeat({
        run: () => agent(executePrompt(ctx), { label, role: 'execute' }),
        getTrail: () => trailFromFile(hb),
        ...seatWindows(),
      });
      if (out && typeof out === 'object' && out.agent_failed) {
        return { note: `agent execute DIED (${out.exit_class})`, agent_failed: out };
      }
      return { note: 'agent execute complete', raw: out };
    },
    async review(ctx, gate) {
      const win = seatWindows();
      const out = await superviseSeat({
        run: () => agent(reviewPrompt(ctx, gate), {
          label: `review:w${ctx.wave.n}#${ctx.reviewerIndex}`,
          schema: REVIEW_SCHEMA,
          role: 'review',
        }),
        getTrail: () => null,
        checkInMs: win.deadIdleMs,
        silentKillMs: win.silentKillMs,
        deadIdleMs: win.deadIdleMs,
      });
      return {
        reviewer: `reviewer-${ctx.reviewerIndex}`,
        answerable: out?.answerable,
        note: out?.note,
        ...(out?.transport_failed ? { transport_failed: true } : {}),
        ...(out?.plan_amendment ? { plan_amendment: out.plan_amendment } : {}),
        findings: out?.findings,
      };
    },
    async elegance(ctx, gate) {
      const changed = (Array.isArray(ctx.changed) ? ctx.changed : [])
        .map((f) => String(f)).filter((f) => f && !f.endsWith(' (deleted)'));
      const elements = changed.map((f, i) => ({
        id: `F${i + 1}`, text: f,
        kind: /(^|\/)(test|tests|spec|fixtures?)(\/|$)|\.test\.|_test\.|test_/i.test(f) ? 'malleability' : 'element',
        detail: `changed in wave ${ctx.wave.n}`,
      }));
      const section = waveSectionText(ctx.planText, ctx.wave.n);
      return runElegancePass({
        elements,
        northStar: northStarFromPlan(ctx.planText),
        criteria: [],
        provenance: { records: [`the frozen implementation plan, wave ${ctx.wave.n} section`], proposerWritten: [] },
        agent: (p, o = {}) => agent(p, { ...o, label: `${o.label || 'elegance'}:w${ctx.wave.n}` }),
        context: `wave ${ctx.wave.n}${ctx.wave.title ? ` "${ctx.wave.title}"` : ''} — ${elements.length} changed file(s); gate ${gate?.tap?.pass ?? '?'}/${gate?.tap?.tests ?? '?'}` +
          (section ? `\nPLAN SECTION:\n${section.slice(0, 2500)}` : ''),
        log: typeof ctx.log === 'function' ? ctx.log : () => {},
        profile: ctx.profile || null,
      });
    },
    async fix(ctx, gate, findings) {
      const seatId = `w${ctx.wave.n}-${ctx.iteration}`;
      const hb = resetSeatHeartbeat(ctx, 'fix', seatId);
      const out = await superviseSeat({
        run: () => agent(fixPrompt(ctx, gate, findings), { label: `fix:w${ctx.wave.n}.${ctx.iteration}`, role: 'fix' }),
        getTrail: () => trailFromFile(hb),
        ...seatWindows(),
      });
      if (out && typeof out === 'object' && out.agent_failed) {
        return { note: `agent fix DIED (${out.exit_class})`, agent_failed: out };
      }
      return { note: 'agent fix complete', raw: out };
    },
  };
}

export const _internals = { executePrompt, reviewPrompt, fixPrompt, extractWaveSection, seatHeartbeatPath };
export default makeAgentDriver;

export function northStarFromPlan(planText) {
  const t = String(planText || '');
  const m = t.match(/\*\*North Star:\*\*\s*([\s\S]{0,1500}?)(?:\n\s*\n|$)/);
  return m ? m[1].trim() : t.slice(0, 600);
}

export function waveSectionText(planText, waveN) {
  const lines = String(planText || '').split(/\r?\n/);
  const head = /^#{1,6}\s*(?:wave|sprint|section)\s*(\d+)(?!\.\d)\b/i;
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(head);
    if (!m) continue;
    if (start >= 0) return lines.slice(start, i).join('\n');
    if (Number(m[1]) === Number(waveN)) start = i;
  }
  return start >= 0 ? lines.slice(start).join('\n') : '';
}
