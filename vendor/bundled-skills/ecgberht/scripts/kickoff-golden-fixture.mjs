/**
 * Gate 5 / Wave 7 - Phase 4.1: the NODE-WRITES side of the cross-language golden
 * contract for the Anchor pass-through reader.
 *
 * This script builds one deterministic kickoff fixture through the REAL engine seams
 * (never hand-written store bytes): open v1 -> confirm v1 -> open a higher v2 draft ->
 * run the Wave 4 projection writer. The result on disk is exactly what Ecgberht
 * persists in production:
 *
 *   <target>/.ecgberht/kickoff/events.jsonl   - the store (read ONLY by this golden
 *                                               harness, never by the Anchor reader)
 *   <target>/.ecgberht/kickoff/projection.json - the read-model the Anchor canary loads
 *   <target>/kickoff-passthrough.golden.txt    - the EXPECTED pass-through rendering,
 *                                               derived from the projection FILE bytes
 *
 * renderKickoffPassthrough here and render_kickoff_passthrough in Anchor's
 * steward_cockpit/kickoff_reader.py are the SAME template in two languages - that
 * duplication IS the contract under test: the Anchor reader's rendering must be
 * byte-equal to the golden file this script writes, or the contract has drifted.
 *
 * Deterministic on purpose: every `at` and client_event_id is pinned, so two runs
 * produce byte-identical projection and golden bytes (the repeat-invocation gate).
 * All timestamps and ids are fixture data; no clock, no randomness, no host paths.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  confirmKickoffProposal,
  kickoffEventsPath,
  openKickoffProposal,
} from '../engine/kickoff-lifecycle.mjs';
import {
  kickoffProjectionPath,
  writeKickoffProjection,
} from '../engine/kickoff-projection.mjs';

/** The expected-rendering golden file, at the project root - OUTSIDE the engine-owned store dir. */
export const GOLDEN_RENDER_FILE = 'kickoff-passthrough.golden.txt';

const SEAT = Object.freeze({ seat_family: 'chatgpt', driver: 'chatgpt-cli' });
const AT_OPEN = '2026-09-01T09:00:00Z';
const AT_CONFIRM = '2026-09-01T09:05:00Z';
const AT_DRAFT = '2026-09-01T09:10:00Z';

/** The confirmed v1 bundle: two components and one join, so every projection field is exercised. */
function confirmedBundle() {
  return {
    kind: 'kickoff',
    goal: 'Let a person review and confirm a project kickoff in the cockpit.',
    success_signals: ['A confirmed kickoff survives a service restart and renders unchanged.'],
    work_product: {
      id: 'kickoff-flow',
      name: 'Kickoff flow',
      components: [
        { id: 'engine', name: 'Canonical engine contract', done_when: 'Lineage replays from kickoff records.' },
        { id: 'cockpit', name: 'Cockpit review surface' },
      ],
    },
    integration: {
      summary: 'The cockpit renders and confirms the engine-owned proposal.',
      relationships: [
        {
          kind: 'feeds',
          component_ids: ['engine', 'cockpit'],
          description: 'The cockpit reads the engine projection and sends only the confirmation receipt.',
        },
      ],
      proof: {
        observable: 'The same proposal hash is shown before and after restart.',
        method: 'Confirm through the cockpit, restart the service, and compare the rendered hash.',
      },
    },
    plan_entries: [
      {
        id: 'restart-slice',
        name: 'Prove one restart-safe review and confirmation',
        component_ids: ['engine', 'cockpit'],
        end_to_end_slice: true,
      },
      {
        id: 'failure-states',
        name: 'Make stale and corrupt lineage visible',
        component_ids: ['engine'],
        end_to_end_slice: false,
      },
    ],
    first_slice_id: 'restart-slice',
  };
}

/** The higher OPEN v2 draft: a different one-sitting goal, never applied. */
function draftBundle() {
  return {
    kind: 'kickoff',
    goal: 'Fold restart proof and failure visibility into one cockpit walkthrough.',
    success_signals: ['One walkthrough shows both restart safety and refusal rows.'],
    work_product: {
      id: 'walkthrough',
      name: 'Cockpit walkthrough',
      components: [{ id: 'walkthrough', name: 'The walkthrough' }],
    },
    plan_entries: [
      {
        id: 'walk-once',
        name: 'Walk the confirmed flow end to end once',
        component_ids: ['walkthrough'],
        end_to_end_slice: true,
      },
    ],
    first_slice_id: 'walk-once',
  };
}

/**
 * The pass-through rendering: every byte comes verbatim from projection fields or from
 * this fixed template. NOTHING is derived - no recomputed hash, no re-sorted list, no
 * consulted store. Mirrored byte-for-byte by render_kickoff_passthrough in Anchor's
 * steward_cockpit/kickoff_reader.py; change BOTH or the golden test fails.
 *
 * @param {object} projection a parsed projection.json document (state 'confirmed')
 * @returns {string}
 */
export function renderKickoffPassthrough(projection) {
  const confirmed = projection.confirmed;
  const lines = [
    `# Kickoff - confirmed v${confirmed.version}`,
    '',
    String(confirmed.rendered_prose).replace(/\n+$/, ''),
    '',
    `Confirmed by ${confirmed.who} at ${confirmed.confirmed_at}.`,
    `Record sha256 ${confirmed.proposal_hash}.`,
    `Receipt sha256 ${confirmed.receipt_hash}.`,
  ];
  const draft = projection.open_draft;
  if (draft) {
    lines.push(
      '',
      `Draft v${draft.version} (${draft.proposal_hash}) - draft, not applied: ${draft.goal}`,
      'This draft is not authoritative; the confirmed kickoff above stays in force.',
    );
  }
  lines.push('');
  return lines.join('\n');
}

/**
 * Build the fixture into targetDir through the real engine seams and write the golden
 * expected rendering DERIVED FROM THE PROJECTION FILE BYTES - the same document the
 * Anchor reader will load, so both languages start from identical input.
 *
 * @param {string} targetDir
 * @returns {object} ok row with every path the golden test needs, or the engine's own
 *   failure row tagged with the step that refused
 */
export function writeKickoffGoldenFixture(targetDir) {
  const root = path.resolve(targetDir);
  fs.mkdirSync(root, { recursive: true });

  const opened = openKickoffProposal(root, {
    proposal: confirmedBundle(),
    ...SEAT,
    client_event_id: 'golden-turn-1',
    at: AT_OPEN,
  });
  if (!opened.ok) return { ...opened, step: 'open_v1' };

  const receipt = confirmKickoffProposal(root, {
    who: 'john',
    proposal_hash: opened.proposal_hash,
    rendered_prose_hash: opened.rendered_prose_hash,
    at: AT_CONFIRM,
  });
  if (!receipt.ok) return { ...receipt, step: 'confirm_v1' };

  const draft = openKickoffProposal(root, {
    proposal: draftBundle(),
    ...SEAT,
    client_event_id: 'golden-turn-2',
    at: AT_DRAFT,
  });
  if (!draft.ok) return { ...draft, step: 'open_v2' };

  const written = writeKickoffProjection(root);
  if (!written.ok) return { ...written, step: 'write_projection' };

  const projectionPath = kickoffProjectionPath(root);
  const raw = fs.readFileSync(projectionPath, 'utf8');
  const projection = JSON.parse(raw);
  const expected = renderKickoffPassthrough(projection);
  const expectedPath = path.join(root, GOLDEN_RENDER_FILE);
  fs.writeFileSync(expectedPath, expected, 'utf8');

  return {
    ok: true,
    project_dir: root,
    projection_path: projectionPath,
    expected_render_path: expectedPath,
    events_path: kickoffEventsPath(root),
    confirmed_version: projection.confirmed.version,
    confirmed_proposal_hash: projection.confirmed.proposal_hash,
    receipt_hash: projection.confirmed.receipt_hash,
    open_draft: projection.open_draft,
  };
}

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  const target = process.argv[2];
  if (!target) {
    console.error('usage: node scripts/kickoff-golden-fixture.mjs <target-dir>');
    process.exit(2);
  }
  const result = writeKickoffGoldenFixture(target);
  console.log(JSON.stringify(result));
  process.exit(result.ok ? 0 : 1);
}
