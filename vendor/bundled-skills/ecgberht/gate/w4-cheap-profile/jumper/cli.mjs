/**
 * Wave-4/5 cheap commission profile — LITE Jumper CLI entry (Stage-2
 * authorized budget; standing-suite anti-stub evidence).
 *
 * Path shape is intentional and anti-stub-honest:
 *   gate/w4-cheap-profile/jumper/cli.mjs
 * The directory segment is exactly `jumper` so G4 cmdline checks match
 * by path SEGMENT (TRIO_CLI_ENTRY_TOKENS includes `jumper`).
 *
 * Mirrors researchPrime cheap profile: real OS process, durable handback
 * pair under the skill-owned contract — parent recorder still must observe
 * (pid, proc_create_time) live-then-terminal.
 *
 * Usage:
 *   node gate/w4-cheap-profile/jumper/cli.mjs <worktree> [client_event_id] [handback_id]
 */

import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
// gate/w4-cheap-profile/jumper → repo root is ../../../
const ROOT = path.resolve(HERE, '..', '..', '..');

const hbMod = pathToFileURL(path.join(ROOT, 'engine', 'handback-contract.mjs')).href;
const rvMod = pathToFileURL(path.join(ROOT, 'engine', 'receipt-validate.mjs')).href;

const { writeHandbackPair } = await import(hbMod);
const { buildHandbackReceipt } = await import(rvMod);

const worktree = process.argv[2];
if (!worktree) {
  console.error('usage: node …/jumper/cli.mjs <worktree> [client_event_id] [handback_id]');
  process.exit(2);
}

const forbidden = ['ANCHOR_TOKEN', 'ANCHOR_CAPABILITY', 'ANCHOR_CAPABILITY_TOKEN'];
const leaked = forbidden.filter((k) => process.env[k] != null && process.env[k] !== '');
if (leaked.length) {
  console.error(JSON.stringify({ ok: false, error: 'token_in_child', leaked }));
  process.exit(3);
}

const clientEventId =
  process.argv[3] ||
  process.env.ECGBERHT_CLIENT_EVENT_ID ||
  `w5-jumper-ce-${Date.now()}`;
const handbackId =
  process.argv[4] ||
  process.env.ECGBERHT_HANDBACK_ID ||
  `w5-jumper-hb-${Date.now()}`;

const base = buildHandbackReceipt({
  as_of: new Date().toISOString().slice(0, 10),
  active_effort: 'w5-jumper-cheap-profile',
  why_next: 'Cheap Jumper commission profile handback for multi-skill SC6 evidence.',
  grasscatch_why: null,
  tool_depth_why: 'LITE Jumper cheap profile (SC6 second commissionable skill).',
  human_wait: 'none',
  uncertainty_flags: ['w5-jumper', 'cheap-profile', 'sc6'],
  skill: 'Jumper',
  depth: 'LITE',
  commission_id: process.env.ECGBERHT_COMMISSION_ID || 'w5-jumper-prove',
  partial: false,
});

const hb = {
  ...base,
  client_event_id: clientEventId,
  handback_id: handbackId,
};

const r = writeHandbackPair(worktree, hb);
if (!r.ok) {
  console.error(JSON.stringify(r));
  process.exit(2);
}

console.log(
  JSON.stringify({
    ok: true,
    handback_path: r.handback_path,
    marker_path: r.marker_path,
    client_event_id: r.client_event_id,
    handback_id: r.handback_id,
    skill: 'Jumper',
    pid: process.pid,
    no_token_in_child: true,
  }),
);
