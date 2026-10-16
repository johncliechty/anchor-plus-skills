/**
 * Wave-19 REAL-RUN gate — EXCLUDED from the standing suite.
 *
 * Wave-0 kill gate on a fresh project under enforced auth (when the auth-ON
 * lane supplies a token), importing T-HOST-0 + conformance verdicts from
 * artifacts/. Uses the cheap multi-skill durable-handback path for the
 * standing campaign proof; set ECGBERHT_W19_REAL=1 to require live skill
 * commissions (STOP if unresolved — never synthesizes G4-class evidence).
 *
 * Usage (operator / orchestrator only):
 *   node gate/w19-real-run.mjs
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

import {
  evaluateKillGate,
  writeKillGateReport,
  writeCriteriaTraceabilityReport,
  T_HOST_0_VERDICT_REL,
  CONFORMANCE_VERDICT_REL,
  KILL_GATE_CODE,
  loadSkillsTable,
  selectKillGateSkills,
  SC6_MIN_COMMISSIONABLE,
  assertNoAnchorTokenInEngine,
} from '../engine/index.mjs';
import { writeJsonIdempotentSync } from '../engine/durable-write.mjs';
import {
  mintAuthOnEnv,
  authPreflight,
  expectedToken,
} from '../scripts/lane-bootstrap.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function stop(reason, extra = {}) {
  console.error(
    JSON.stringify({ ok: false, stopped: true, reason, ...extra }, null, 2),
  );
  process.exit(3);
}

function main() {
  const forceLive = process.env.ECGBERHT_W19_REAL === '1';
  if (forceLive) {
    stop('live_skill_commission_not_wired_in_this_gate_shell', {
      message:
        'ECGBERHT_W19_REAL=1 requested — resolve live skill entry points and drive propose→confirm→execute via Wave-20/Wave-5 real runners; this shell refuses to synthesize live G4/exec2 evidence.',
    });
  }

  // Token grep (criterion 9) — always
  const tokenGrep = assertNoAnchorTokenInEngine({ root: ROOT });
  if (!tokenGrep.ok) {
    stop('anchor_token_in_engine', tokenGrep);
  }

  // Skills table
  const load = loadSkillsTable({ root: ROOT });
  if (!load.ok) {
    stop('skills_table_unreadable', { detail: load });
  }
  const selection = selectKillGateSkills({
    root: ROOT,
    skills_table: load.table,
  });
  if (!selection.ok || selection.halt) {
    stop('multi_skill_halt', {
      message: selection.message,
      commissionable_count: selection.commissionable_count,
      min_required: SC6_MIN_COMMISSIONABLE,
    });
  }

  // Auth-ON when possible
  const env = { ...process.env };
  let auth = null;
  let authPre = { ok: true, skipped: true };
  let enforce = false;
  try {
    mintAuthOnEnv(env);
    authPre = authPreflight(env);
    if (authPre.ok) {
      enforce = true;
      auth = {
        token: expectedToken(env),
        principal: 'john',
      };
      // Mirror into process.env for any seam that reads lane env (tests only)
      process.env.ANCHOR_TOKEN = env.ANCHOR_TOKEN;
      process.env.ANCHOR_AUTH_MODE = env.ANCHOR_AUTH_MODE;
    }
  } catch {
    authPre = { ok: false, message: 'auth mint failed' };
  }

  // Host verdicts: require real artifacts when present; else STOP (do not
  // silently green criteria 14/15 with fixtures in the real-run gate).
  const tHostPath = path.join(ROOT, T_HOST_0_VERDICT_REL);
  const confPath = path.join(ROOT, CONFORMANCE_VERDICT_REL);
  let t_host_0 = null;
  let conformance = null;
  try {
    if (fs.existsSync(tHostPath)) {
      t_host_0 = JSON.parse(fs.readFileSync(tHostPath, 'utf8'));
    }
    if (fs.existsSync(confPath)) {
      conformance = JSON.parse(fs.readFileSync(confPath, 'utf8'));
    }
  } catch (e) {
    stop('verdict_unreadable', { error: String(e?.message ?? e) });
  }

  // Real-run gate: if Waves 21/22 have not written verdicts yet, STOP with
  // the named shortfall — never inject PASS fixtures to green the kill gate.
  if (!t_host_0 || t_host_0.verdict !== 'PASS') {
    stop('t_host_0_required', {
      message:
        'artifacts/t-host-0-verdict.json missing or not PASS — Wave 22 must land before Wave 19 greens (criterion 14).',
      path: T_HOST_0_VERDICT_REL,
      present: !!t_host_0,
      verdict: t_host_0?.verdict ?? null,
    });
  }
  if (
    !conformance ||
    conformance.executors?.insession !== 'PASS' ||
    conformance.executors?.anchor !== 'PASS'
  ) {
    stop('conformance_required', {
      message:
        'artifacts/conformance-verdict.json missing or not both-PASS — Wave 21 must land before Wave 19 greens (criterion 15).',
      path: CONFORMANCE_VERDICT_REL,
      present: !!conformance,
      executors: conformance?.executors ?? null,
    });
  }

  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'w19-real-'));
  const report = evaluateKillGate({
    root: ROOT,
    projectPath: work,
    skills_table: load.table,
    enforce_auth: enforce,
    auth_preflight: authPre,
    auth,
    t_host_0,
    conformance,
    who: 'john',
    at: new Date().toISOString().slice(0, 10),
  });

  writeCriteriaTraceabilityReport({ root: ROOT });
  writeKillGateReport(report, { root: ROOT });

  const record = {
    schema: 'ecgberht-w19-real-run-record-v0',
    ok: report.ok === true,
    gate: 'w19-real-run',
    green: report.green === true,
    code: report.code,
    skills: selection.skills,
    auth_enforced: enforce,
    t_host_0: t_host_0.verdict,
    conformance: {
      contract_version: conformance.contract_version,
      executors: conformance.executors,
    },
    failures: report.failures,
    live: false,
    work: '<tmpdir>',
    at: new Date().toISOString(),
  };

  const recordPath = path.join(ROOT, 'artifacts', 'w19-real-run-record.json');
  fs.mkdirSync(path.dirname(recordPath), { recursive: true });
  writeJsonIdempotentSync(recordPath, record);

  if (!report.ok) {
    console.error(JSON.stringify({ ok: false, report: record }, null, 2));
    process.exit(1);
  }

  console.log(
    JSON.stringify(
      {
        ok: true,
        code: KILL_GATE_CODE.GREEN,
        skills: selection.skills,
        criteria: '1-15',
        t_host_0: 'PASS',
        conformance: 'BOTH_PASS',
      },
      null,
      2,
    ),
  );
  process.exit(0);
}

main();
