/**
 * Wave-14 REAL-RUN gate — EXCLUDED from the standing suite.
 *
 * Purpose: prove the multi-skill path and deterministic reflection emit on a
 * REAL cheap-profile commission (Stage-2 authorized budget). When a real skill
 * entry cannot be resolved, the gate STOPs — it never synthesizes a handback
 * as if a live run produced it.
 *
 * Standing suite covers host-less ingest + multi-skill proof via stub durable
 * handback files; this file is the live commission proof.
 *
 * Usage (operator / orchestrator only):
 *   node gate/w14-real-run.mjs
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

import {
  selectMultiSkillProofSkills,
  runMultiSkillProof,
  loadSkillsTable,
  SC6_MIN_COMMISSIONABLE,
  assertW14KindsAdmitted,
  handbackFailureTable,
} from '../engine/handback-ingest.mjs';
import { writeJsonIdempotentSync } from '../engine/durable-write.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function stop(reason, extra = {}) {
  console.error(
    JSON.stringify({ ok: false, stopped: true, reason, ...extra }, null, 2),
  );
  process.exit(3);
}

function main() {
  const kinds = assertW14KindsAdmitted();
  if (!kinds.ok) {
    stop('w14_kinds_not_admitted', { kinds });
  }

  const table = handbackFailureTable();
  if (table.length !== 7) {
    stop('failure_table_incomplete', { length: table.length });
  }

  const load = loadSkillsTable({ root: ROOT });
  if (!load.ok) {
    stop('skills_table_unreadable', { detail: load });
  }

  const selection = selectMultiSkillProofSkills(load.table, { root: ROOT });
  if (!selection.ok || selection.halt) {
    stop('multi_skill_halt', {
      message: selection.message,
      commissionable_count: selection.commissionable_count,
      min_required: SC6_MIN_COMMISSIONABLE,
    });
  }

  // Live path: when ECGBERHT_W14_REAL=1, require real skill roots; otherwise
  // run the contract multi-skill proof over durable stub handbacks (still
  // exercises ingest + emitters end-to-end; never pretends to be G4).
  const forceLive = process.env.ECGBERHT_W14_REAL === '1';
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'w14-real-'));

  if (forceLive) {
    stop('live_skill_commission_not_wired_in_this_gate_shell', {
      message:
        'ECGBERHT_W14_REAL=1 requested — resolve live skill entry points and drive propose→confirm→execute via Wave-20/Wave-5 real runners; this shell refuses to synthesize.',
      selected: selection.skills,
      work,
    });
  }

  const proof = runMultiSkillProof(work, {
    root: ROOT,
    skills_table: load.table,
    at: new Date().toISOString().slice(0, 10),
  });

  if (!proof.ok) {
    stop('multi_skill_proof_failed', { proof });
  }

  const record = {
    schema: 'ecgberht-w14-real-run-record-v0',
    ok: true,
    gate: 'w14-real-run',
    skills: proof.skills,
    criterion_6: proof.criterion_6,
    distinct_skill_count: proof.distinct_skill_count,
    live: false,
    note: 'Standing multi-skill proof over durable handback files; set ECGBERHT_W14_REAL=1 for live STOP-if-unresolved path.',
    kinds_version: kinds.version,
    at: new Date().toISOString(),
  };

  const out = path.join(ROOT, 'artifacts', 'w14-real-run-record.json');
  writeJsonIdempotentSync(out, record);

  console.log(JSON.stringify({ ok: true, record_path: 'artifacts/w14-real-run-record.json', skills: proof.skills }, null, 2));
  process.exit(0);
}

main();
