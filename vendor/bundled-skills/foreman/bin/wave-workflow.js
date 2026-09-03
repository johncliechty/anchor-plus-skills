// wave-workflow.js — Foreman Phase 1: the PRODUCTION driver seam for the
// one-wave engine (the model-driven {execute, review, fix} steps).
//
// ---------------------------------------------------------------------------
// DESIGN FINDING (Phase 1, recorded in Foreman-Execution-Log.md as finding L):
//   The plan §2 says "single engine = the native Workflow tool." Building this
//   adapter surfaced that a Workflow-tool *script* has, by spec, "No filesystem
//   or Node.js API access." But the §5 orchestrator-run gate MUST (a) spawn the
//   discovered build+test command and (b) write a gate-artifact file that
//   sub-agents cannot write. Neither is possible inside a Workflow-tool script.
//   => The faithful realization of §5 keeps the ORCHESTRATOR + GATE + STATE in a
//      Node process (bin/wave-engine.mjs). The Workflow tool, if used at all, can
//      only drive the *model* steps (execute/review/fix) — never the gate. This
//      adapter therefore exposes those three steps behind an INJECTED `agent()`
//      function, so the Node orchestrator can call the model however it likes
//      (Workflow agent(), the Agent tool, or a scripted stand-in for tests).
//      Wiring a live agent end-to-end is Phase 2 work; Phase 1 ships the
//      deterministic orchestrator + the scripted driver, and this seam.
// ---------------------------------------------------------------------------
//
// This file is plain Node (NOT a Workflow-tool script): it has no top-level
// `agent()`/`parallel()` globals and does no I/O itself. `makeAgentDriver`
// returns a driver with the exact shape bin/wave-engine.mjs expects, given an
// injected async `agent(prompt, opts)` whose return contract matches Workflow's
// `agent()` (text by default; the validated object when a `schema` is passed).

import path from 'node:path';
import fs from 'node:fs';
import { lookinAppendix, superviseSeat, trailFromFile } from '../../drivers/swarm-lookin.mjs';

// 2026-09-01 (Gate 5 wave 1, proven live): every Foreman seat was supervised with NO heartbeat
// trail and the supervisor's defaults (90 s check-in + 60 s grace), so "silence is death"
// degenerated into a 3-minute WALL-CLOCK kill of seats that were working (27 tool calls at
// 180 s), respawned once, killed again, run THREW. The seat is told to write a heartbeat; the
// orchestrator must READ it from the same path — and reset it per seat so a stale file from the
// previous seat cannot count as this seat's silence. Windows are sized to real build work; the
// driver's per-call timeout (45 min) stays the dead-process backstop.
function seatHeartbeatPath(ctx) {
  const root = ctx?.projectDir ? path.resolve(ctx.projectDir) : process.cwd();
  return path.join(root, '.foreman', 'seat-heartbeat.json');
}
function resetSeatHeartbeat(ctx) {
  const hb = seatHeartbeatPath(ctx);
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
    // F3 (§6): when the frozen plan is wrong/incomplete for THIS wave (distinct
    // from `answerable: no` ambiguity), a reviewer may attach a concrete proposed
    // resolution — a PROPOSED DIFF to the plan doc + a rationale. The engine HALTs
    // with this in pending_action for one-click human approval; it is NEVER applied
    // autonomously.
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
 * Sleep 0076 package 1 — execute must see deliverables/done-when, not only the title.
 * @param {string} planText
 * @param {number} waveN
 * @returns {string}
 */
export function extractWaveSection(planText, waveN) {
  const text = String(planText || '');
  if (!text || !waveN) return '';
  // Two-step parse: JS has no Python \Z, and /$/m matches every line end (would
  // truncate the body to the first line). Find this wave's header, then cut at the
  // next ## Wave/Sprint/Section or EOF.
  const header = new RegExp(
    String.raw`^##\s+(?:Wave|Sprint|Section)\s+${Number(waveN)}\b[^\n]*\n`,
    'im',
  );
  const hm = header.exec(text);
  if (!hm) return '';
  const start = hm.index + hm[0].length;
  const rest = text.slice(start);
  const next = rest.search(/^##\s+(?:Wave|Sprint|Section)\s+\d+\b/im);
  const body = (next >= 0 ? rest.slice(0, next) : rest).trim();
  // Cap so the agent prompt stays within argv/context comfort (full plan stays on disk).
  const max = 6000;
  return body.length > max ? `${body.slice(0, max)}\n\n…[wave section truncated; read plan file for remainder]` : body;
}

function executePrompt(ctx) {
  const planPath = ctx.planPath || path.join(ctx.projectDir || '.', 'IMPLEMENTATION-PLAN.md');
  const testCommand = ctx.testCommand || '(see plan test-command:)';
  const section = extractWaveSection(ctx.planText || '', ctx.wave?.n);
  const contractBlock = section
    ? [
        `FROZEN PLAN PATH: ${planPath}`,
        `ORCHESTRATOR GATE (you do NOT run it): ${testCommand}`,
        `THIS WAVE'S CONTRACT (from the frozen plan — implement ALL of it; do not invent scope):`,
        '----- BEGIN WAVE CONTRACT -----',
        section,
        '----- END WAVE CONTRACT -----',
      ]
    : [
        `FROZEN PLAN PATH: ${planPath}`,
        `ORCHESTRATOR GATE (you do NOT run it): ${testCommand}`,
        `WARNING: could not extract ## Wave ${ctx.wave?.n} body from plan text — open the plan file and implement that wave's Deliverables and done-when only.`,
      ];
  const lite = /^(LITE|LIGHT)$/i.test(String(process.env.FOREMAN_BAND_DEPTH || ''));
  const liteBudget = lite
    ? [
        `LITE BAND BUDGET: stay minimal — implement only this wave's deliverables + the`,
        `smallest tests that import new modules. No drive-by refactors, no docs fluff.`,
      ]
    : [];
  return [
    `You are the EXECUTE agent for Foreman wave ${ctx.wave.n} ("${ctx.wave.title}").`,
    `Project: ${ctx.projectDir}. Implement ONLY this wave's work as specified in the`,
    `frozen plan. Do not refactor outside the plan; do not weaken or delete tests.`,
    ...contractBlock,
    ...liteBudget,
    `Ship real source that NEW tests import and exercise (or keep/extend tests that import your source).`,
    `A green suite that does not exercise this wave's files is a failed execute — the orchestrator will vacuous-GREEN HALT.`,
    // 0082 P3.15–16 acceptance checklist
    `ACCEPTANCE CHECKLIST (must satisfy before you stop):`,
    `  (1) Every new module is imported by at least one test that will run under the gate command.`,
    `  (2) No absolute host paths (C:\\Users\\..., <path> in shipped strings, pointers, or docs — use relative paths or env.`,
    `  (3) Syntax-valid sources only (no half-written files that fail node --check / py_compile).`,
    `Do NOT run any git commands, terminal commands, or tests yourself. The orchestrator`,
    `owns all testing and version control; strictly just edit the source files.`,
    `If the wave is not answerable from the frozen docs, say so explicitly.`,
    `If you discover the wave is BLOCKED (a required human approval/amendment is`,
    `missing, a prerequisite is absent) or believe it is ALREADY DONE, do NOT`,
    `quietly finish with no changes — state the blocker/claim explicitly as your`,
    `final message; the orchestrator's guards, not you, decide how to proceed.`,
    lookinAppendix({ heartbeatPath: seatHeartbeatPath(ctx) }),
  ].join('\n');
}

function reviewPrompt(ctx, gate) {
  // 2026-07 efficiency: the orchestrator already measured the wave's changed
  // files — hand them over so the reviewer's budget goes to REFUTATION instead
  // of re-discovering the diff with dozens of Glob/Grep calls. The reviewer
  // remains free to read anything else in the tree.
  const changedBlock = Array.isArray(ctx.changed) && ctx.changed.length
    ? [`The orchestrator measured this wave's CHANGED FILES (start your review here,`,
       `but you may read anywhere): ${ctx.changed.slice(0, 80).join(', ')}` +
       (ctx.changed.length > 80 ? ` … (+${ctx.changed.length - 80} more)` : '') + `.`]
    : [`The orchestrator measured ZERO changed files for this wave.`];
  // 2026-07-04 (wave-6 false-GO fix): an empty/deliverable-free diff is a
  // mandatory blocker, not something a reviewer may wave through — a green gate
  // over an unchanged tree proves nothing about the wave.
  const notImplementedRule = [
    `MANDATORY: if the changed-file list is empty, or nothing in it could plausibly`,
    `implement this wave's stated deliverables (e.g. only regenerated data/doc`,
    `artifacts or log noise), you MUST report a BLOCKER finding titled`,
    `"wave-not-implemented" — do NOT approve an unimplemented wave because the`,
    `gate is green.`,
  ];
  return [
    `You are an INDEPENDENT, READ-ONLY reviewer (#${ctx.reviewerIndex}) for Foreman`,
    `wave ${ctx.wave.n}. Your job is to REFUTE, not to praise. The ground-truth gate`,
    `was run by the orchestrator; read ONLY its artifact at ${gate.artifact_path}`,
    `(exit ${gate.exit_code}, pass ${gate.tap.pass}/${gate.tap.tests}).`,
    ...changedBlock,
    ...notImplementedRule,
    `Do NOT trust`,
    `any pasted "command output" in wave logs. Cite file:line or a failing repro`,
    `command+output for every finding. First answer answerable-from-frozen-docs:`,
    `yes/no with a cited plan line. If (and only if) a build-time discovery shows the`,
    `FROZEN plan is itself wrong/incomplete for this wave (an assumption falsified, an`,
    `API not behaving as assumed) — distinct from mere ambiguity — you MAY attach a`,
    `plan_amendment {proposed_diff, rationale}; the orchestrator will HALT for human`,
    `approval and will NEVER apply it autonomously.`,
    lookinAppendix({ heartbeatPath: seatHeartbeatPath(ctx) }),
  ].join(' ');
}

function fixPrompt(ctx, gate, findings) {
  return [
    `You are the FIX agent for Foreman wave ${ctx.wave.n}, fix iteration ${ctx.iteration}.`,
    `Close these findings without weakening tests: ${JSON.stringify(findings.map((f) => f.id))}.`,
    `The orchestrator gate is at ${gate.artifact_path}. Make the minimal change that`,
    `turns the gate GREEN; the orchestrator — not you — re-runs the gate to verify.`,
    `Do NOT run any git commands, terminal commands, or tests yourself. The orchestrator owns all testing and version control.`,
    `TESTS ARE FROZEN. Do not modify test files to force a pass. You may NEVER use pytest.skip, @pytest.mark.skip, or pytest.importorskip on failing tests. Solve the root cause in the product code.`,
    lookinAppendix({ heartbeatPath: seatHeartbeatPath(ctx) }),
  ].join(' ');
}

/**
 * Build a model-driven driver from an injected `agent()` function.
 * @param {{agent: (prompt:string, opts?:object)=>Promise<any>}} deps
 * @returns {{execute:Function, review:Function, fix:Function}}
 */
export function makeAgentDriver({ agent }) {
  if (typeof agent !== 'function') throw new TypeError('makeAgentDriver requires an agent() function');
  return {
    // Each call carries its `role` so per-role model routing (CLAUDE_MODEL_<ROLE> /
    // TRIO_MODEL_<ROLE>, resolved inside the drivers) is reachable on the build path:
    // execute/fix pin to the strongest coder, review can fan out to another family.
    async execute(ctx) {
      const hb = resetSeatHeartbeat(ctx);
      const out = await superviseSeat({
        run: () => agent(executePrompt(ctx), { label: `execute:w${ctx.wave.n}`, role: 'execute' }),
        getTrail: () => trailFromFile(hb),
        ...seatWindows(),
      });
      // 0102: a dead agent (typed { agent_failed } marker from the transport) must
      // never be labeled "complete" — forward the failure so the engine HALTs.
      if (out && typeof out === 'object' && out.agent_failed) {
        return { note: `agent execute DIED (${out.exit_class})`, agent_failed: out };
      }
      return { note: 'agent execute complete', raw: out };
    },
    async review(ctx, gate) {
      const hb = resetSeatHeartbeat(ctx);
      const out = await superviseSeat({
        run: () => agent(reviewPrompt(ctx, gate), {
          label: `review:w${ctx.wave.n}#${ctx.reviewerIndex}`,
          schema: REVIEW_SCHEMA,
          role: 'review',
        }),
        getTrail: () => trailFromFile(hb),
        ...seatWindows(),
      });
      return {
        reviewer: `reviewer-${ctx.reviewerIndex}`,
        answerable: out?.answerable ?? 'yes',
        note: out?.note,
        // T10a: drivers stamp transport_failed on unparseable-after-retry (with
        // answerable:'no'). Forward it so wave-engine degrades the seat BEFORE the
        // §4.7 ambiguity gate — stripping it turned every review JSON hiccup into a
        // false [taxonomy:ambiguity] HALT (live: W16 2026-07-29, sleep stage2).
        ...(out?.transport_failed ? { transport_failed: true } : {}),
        // F3: forward a well-formed plan-amendment proposal (diff + rationale) so
        // the engine can raise the PLAN-AMENDMENT-PROPOSAL halt; absent otherwise.
        ...(out?.plan_amendment ? { plan_amendment: out.plan_amendment } : {}),
        // `claim` is intentionally absent: in production the judge reads only the
        // orchestrator gate, never reviewer prose, so there is nothing to forge.
        findings: Array.isArray(out?.findings) ? out.findings : [],
      };
    },
    async fix(ctx, gate, findings) {
      const hb = resetSeatHeartbeat(ctx);
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

export const _internals = { executePrompt, reviewPrompt, fixPrompt, extractWaveSection };
export default makeAgentDriver;
