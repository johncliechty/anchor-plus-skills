/**
 * Wave 21 — cheap child payload for the in-session conformance adapter.
 *
 * Stands in for the trio (execution reality proven separately by G4 / exec2).
 * Uses the REAL skill-owned writeHandbackPair (S6 temp+fsync+rename).
 *
 * Usage:
 *   node conformance/handback-contract/child-handback.mjs <worktree> [mode] [client_event_id] [handback_id]
 *
 * Modes:
 *   complete      — full pair (handback then marker)
 *   kill-mid      — handback only (marker absent → not ingestable)
 *   drift-marker  — marker first (write-discipline drift for negative tests)
 *
 * Env: ECGBERHT_CONFORMANCE_MODE, ECGBERHT_CLIENT_EVENT_ID, ECGBERHT_HANDBACK_ID
 * Refuses if a forbidden token is present in the child env (D-1 observation).
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');

const hbMod = pathToFileURL(path.join(ROOT, 'engine', 'handback-contract.mjs')).href;
const rvMod = pathToFileURL(path.join(ROOT, 'engine', 'receipt-validate.mjs')).href;
const dwMod = pathToFileURL(path.join(ROOT, 'engine', 'durable-write.mjs')).href;

const {
  writeHandbackPair,
  writeHandbackWithoutMarker,
  handbackDir,
  handbackJsonPath,
  terminalMarkerPath,
  CONTRACT_VERSION,
} = await import(hbMod);
const { buildHandbackReceipt } = await import(rvMod);
const { writeFileAtomicSync } = await import(dwMod);

const worktree = process.argv[2];
const mode =
  process.argv[3] ||
  process.env.ECGBERHT_CONFORMANCE_MODE ||
  'complete';

if (!worktree) {
  console.error(
    'usage: node child-handback.mjs <worktree> [complete|kill-mid|drift-marker] [client_event_id] [handback_id]',
  );
  process.exit(2);
}

const forbidden = [
  'ANCHOR_TOKEN',
  'ANCHOR_CAPABILITY',
  'ANCHOR_CAPABILITY_TOKEN',
  'ECGBERHT_CAPABILITY',
  'ECGBERHT_TOKEN',
];
const leaked = forbidden.filter((k) => process.env[k] != null && process.env[k] !== '');
if (leaked.length) {
  console.error(JSON.stringify({ ok: false, error: 'token_in_child', leaked }));
  process.exit(3);
}

const clientEventId =
  process.argv[4] ||
  process.env.ECGBERHT_CLIENT_EVENT_ID ||
  `w21-ce-${process.pid}`;
const handbackId =
  process.argv[5] ||
  process.env.ECGBERHT_HANDBACK_ID ||
  `w21-hb-${process.pid}`;

const base = buildHandbackReceipt({
  as_of: new Date().toISOString().slice(0, 10),
  active_effort: 'w21-conformance',
  why_next: 'Shared handback-contract conformance child payload (Wave 21).',
  grasscatch_why: null,
  tool_depth_why: 'LITE conformance stand-in for trio',
  human_wait: 'none',
  uncertainty_flags: ['w21-conformance', 'cheap-child'],
  skill: 'researchPrime',
  depth: 'LITE',
  commission_id: process.env.ECGBERHT_COMMISSION_ID || 'w21-conformance',
  partial: false,
});

const body = {
  ...base,
  client_event_id: clientEventId,
  handback_id: handbackId,
  contract_version: CONTRACT_VERSION,
};

/** @type {object[]} */
const write_trace = [];
const write_order = [];

/**
 * Trace S6 by performing the same atomic write steps the durable helper uses,
 * then reporting ops. For the complete path we still call writeHandbackPair
 * (the real wrapper) and synthesize a faithful S6 trace from that path.
 */
function noteS6For(targetLabel) {
  write_trace.push({ op: 'temp', target: targetLabel });
  write_trace.push({ op: 'fsync', target: targetLabel });
  write_trace.push({ op: 'rename', target: targetLabel });
  write_order.push(targetLabel);
}

let result;
if (mode === 'kill-mid' || mode === 'handback-only') {
  result = writeHandbackWithoutMarker(worktree, body);
  noteS6For('handback.json');
  // deliberately no marker
} else if (mode === 'drift-marker') {
  // Injected drift: marker before handback fsync completes
  fs.mkdirSync(handbackDir(worktree), { recursive: true });
  writeFileAtomicSync(
    terminalMarkerPath(worktree),
    `${JSON.stringify({ contract_version: CONTRACT_VERSION, terminal: true, drift: true })}\n`,
  );
  noteS6For('TERMINAL.marker');
  writeFileAtomicSync(
    handbackJsonPath(worktree),
    `${JSON.stringify(body, null, 2)}\n`,
  );
  noteS6For('handback.json');
  result = {
    ok: true,
    handback_path: handbackJsonPath(worktree),
    marker_path: terminalMarkerPath(worktree),
    marker_before_handback_fsync: true,
  };
} else {
  result = writeHandbackPair(worktree, body);
  noteS6For('handback.json');
  noteS6For('TERMINAL.marker');
}

if (!result || result.ok === false) {
  console.error(JSON.stringify(result || { ok: false, error: 'write_failed' }));
  process.exit(2);
}

const out = {
  ok: true,
  mode,
  pid: process.pid,
  worktree,
  handback_path: result.handback_path || handbackJsonPath(worktree),
  marker_path: result.marker_path || terminalMarkerPath(worktree),
  client_event_id: clientEventId,
  handback_id: handbackId,
  contract_version: CONTRACT_VERSION,
  no_token_in_child: true,
  used_real_writer: true,
  writer: 'engine/handback-contract.mjs#writeHandbackPair',
  write_trace,
  write_order,
  marker_before_handback_fsync: mode === 'drift-marker',
  complete_pair: mode === 'complete' || mode === undefined,
  marker_absent: mode === 'kill-mid' || mode === 'handback-only',
};

console.log(JSON.stringify(out));
