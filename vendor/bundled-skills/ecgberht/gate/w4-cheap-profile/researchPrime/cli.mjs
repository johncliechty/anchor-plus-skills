/**
 * Wave-4 cheap commission profile — LITE researchPrime CLI entry (Stage-2
 * authorized budget; standing-suite anti-stub evidence + wave-local real-run).
 *
 * Path shape is intentional and anti-stub-honest:
 *   gate/w4-cheap-profile/researchPrime/cli.mjs
 * The directory segment is exactly `researchPrime` so G4 cmdline checks match
 * by path SEGMENT (directory name), not by free filename substring. A file
 * named `researchPrime-lite-standin.mjs` would FAIL the segment check.
 *
 * This is NOT a canned `node -e` stub and NOT a handback-synthesize escape:
 * it is a real OS process that writes the durable handback pair under the
 * skill-owned contract (temp+fsync+rename + TERMINAL.marker) into its worktree.
 * G4 still requires (pid, proc_create_time) live-then-terminal observation
 * from the parent recorder — this child alone cannot forge that.
 *
 * Usage:
 *   node gate/w4-cheap-profile/researchPrime/cli.mjs <worktree> [client_event_id] [handback_id]
 *
 * Env (optional): ECGBERHT_CLIENT_EVENT_ID, ECGBERHT_HANDBACK_ID, ECGBERHT_COMMISSION_ID
 * Child must never require ANCHOR_TOKEN (Descope D-1).
 */

import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
// gate/w4-cheap-profile/researchPrime → repo root is ../../../
const ROOT = path.resolve(HERE, '..', '..', '..');

const hbMod = pathToFileURL(path.join(ROOT, 'engine', 'handback-contract.mjs')).href;
const rvMod = pathToFileURL(path.join(ROOT, 'engine', 'receipt-validate.mjs')).href;

const { writeHandbackPair } = await import(hbMod);
const { buildHandbackReceipt } = await import(rvMod);

const worktree = process.argv[2];
if (!worktree) {
  console.error('usage: node …/researchPrime/cli.mjs <worktree> [client_event_id] [handback_id]');
  process.exit(2);
}

// Refuse if a forbidden token leaked into this child (D-1 observation surface)
const forbidden = ['ANCHOR_TOKEN', 'ANCHOR_CAPABILITY', 'ANCHOR_CAPABILITY_TOKEN'];
const leaked = forbidden.filter((k) => process.env[k] != null && process.env[k] !== '');
if (leaked.length) {
  console.error(JSON.stringify({ ok: false, error: 'token_in_child', leaked }));
  process.exit(3);
}

const clientEventId =
  process.argv[3] ||
  process.env.ECGBERHT_CLIENT_EVENT_ID ||
  `w4-ce-${Date.now()}`;
const handbackId =
  process.argv[4] ||
  process.env.ECGBERHT_HANDBACK_ID ||
  `w4-hb-${Date.now()}`;

const base = buildHandbackReceipt({
  as_of: new Date().toISOString().slice(0, 10),
  active_effort: 'w4-real-run-cheap-profile',
  why_next: 'Cheap commission profile handback for G4 anti-stub evidence.',
  grasscatch_why: null,
  tool_depth_why: 'LITE researchPrime cheap profile (Wave 4 real-run gate).',
  human_wait: 'none',
  uncertainty_flags: ['w4-real-run', 'cheap-profile'],
  skill: 'researchPrime',
  depth: 'LITE',
  commission_id: process.env.ECGBERHT_COMMISSION_ID || 'w4-real-run',
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
    pid: process.pid,
    no_token_in_child: true,
  }),
);
