/**
 * Record REAL seat replies for the offline acceptance lane.
 *
 * The gate cannot make a live model call (no auth, minutes per turn), but stubbing the
 * model would be exactly the vacuous guard this project has shipped three times. So the
 * gate replays a REAL reply captured here, and the replay is bound to the hash of the
 * prompt that produced it — if the prompt builder drifts, the gate FAILS rather than
 * passing against a stale tape.
 *
 * Run:  node scripts/record-steward-fixture.mjs
 * (costs two real seat calls; only needed when the prompt or the fixture changes)
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { confirmStandUp } from '../engine/stand-up.mjs';
import {
  confirmSessionEnvelope,
  currentBudgetTermsHash,
} from '../engine/session-envelope.mjs';
import { converse } from '../engine/steward-conversation.mjs';
import { makeSeatCall } from './seat-call.mjs';
import {
  FIXTURE_NORTH_STAR,
  FIXTURE_REFINEMENT,
  readAppendixA,
  fixtureTurns,
} from '../test/helpers/steward-fixture.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT_DIR = path.join(ROOT, 'test', 'fixtures');

const dir = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'ecg-record-')), 'proj');
fs.mkdirSync(dir, { recursive: true });
confirmStandUp({ project_path: dir, north_star: FIXTURE_NORTH_STAR, who: 'john' });

const overrides = { max_compiles: null, max_spend_usd: 50 };
const { terms_hash } = currentBudgetTermsHash(overrides);
confirmSessionEnvelope(dir, {
  who: 'john', terms_hash, terms_overrides: overrides,
  client_event_id: 'record-env', credential_class: 'none',
});

// ONE TAPE for the whole session — every seat call in both turns, keyed by prompt
// hash. A turn can make two calls (talk, then plan); per-turn files could only hold
// the last one to write.
process.env.ECGBERHT_SEAT_RECORD = path.join(OUT_DIR, 'steward-session.json');
// FROZEN CLOCK — conversation-log dates ride the prompt; a wall-clock
// recording rots at midnight (found 2026-08-07 when yesterday's tape started
// refusing). The same instant is passed by the acceptance tests via --as-of.
const FIXTURE_AS_OF = '2026-08-06T12:00:00.000Z';
const t1 = await converse(dir, {
  utterance: readAppendixA(),
  at: FIXTURE_AS_OF,
  seatCall: makeSeatCall(),
  client_event_id: 'record-t1',
});
process.stdout.write(`turn 1: ok=${t1.ok} stages=${t1.step_count ?? 0} ${t1.code ?? ''}\n`);
if (!t1.ok) process.exit(1);

const t2 = await converse(dir, {
  utterance: FIXTURE_REFINEMENT,
  turns: fixtureTurns(t1.say),
  at: FIXTURE_AS_OF,
  seatCall: makeSeatCall(),
  client_event_id: 'record-t2',
});
process.stdout.write(`turn 2: ok=${t2.ok} stages=${t2.step_count ?? 0} ${t2.code ?? ''}\n`);
if (!t2.ok) process.exit(1);

process.stdout.write(`recorded -> ${OUT_DIR}\n`);
process.stdout.write(`turn2 stages: ${t2.proposal.steps.map((s) => s.name).join(' | ')}\n`);
