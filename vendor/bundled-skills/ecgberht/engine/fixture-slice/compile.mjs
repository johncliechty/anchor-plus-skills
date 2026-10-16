/**
 * Wave 2 — typed NL description → coarse scaffolding with Oranges annotations.
 *
 * DETERMINISTIC, ZERO-MODEL. Compiles a structured description into a
 * proposed multi-stage scaffolding (coarse steps + Oranges prompts).
 * Chat is never persisted; only the typed proposal event lands on the
 * fixture ledger when the caller appends it.
 */

import crypto from 'node:crypto';
import { makeFailure } from './failure-states.mjs';

export const SCAFFOLDING_PROPOSAL_SCHEMA = 'ecgberht-fixture-scaffolding-v0';

/**
 * Coarse Oranges annotations attached to each proposed step — anticipatory
 * prompts the steward would surface (criterion 1 shape), not model output.
 */
export const DEFAULT_ORANGES_PROMPTS = Object.freeze([
  'What would John ask next about this stage?',
  'What artifact must exist before the stage can close?',
  'What decision, if any, requires a human gate?',
]);

/**
 * Deterministic content hash of a proposal payload (foreshadows hash-bound confirm).
 * @param {object} payload
 * @returns {string}
 */
export function contentHash(payload) {
  const canonical = JSON.stringify(sortKeys(payload));
  return crypto.createHash('sha256').update(canonical).digest('hex');
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    const out = {};
    for (const k of Object.keys(value).sort()) {
      out[k] = sortKeys(value[k]);
    }
    return out;
  }
  return value;
}

/**
 * Compile a typed NL / structured description into a scaffolding proposal.
 *
 * Accepts either:
 * - `{ goal, stages: string[] | {name, done_when?}[] }` (preferred typed form)
 * - `{ description: string }` free-form with lines like "Stage: …" or "1. …"
 *
 * @param {object} input
 * @returns {{ ok: true, proposal: object } | { ok: false, code: string, message: string }}
 */
export function compileDescription(input = {}) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return makeFailure('compile-failed', {
      error: 'description_not_object',
      message: 'Description must be a typed object (goal + stages) or carry a description string.',
    });
  }

  const goal =
    nonEmpty(input.goal) ? String(input.goal).trim()
    : nonEmpty(input.description) ? firstLine(String(input.description))
    : null;

  if (!goal) {
    return makeFailure('compile-failed', {
      error: 'goal_missing',
      message: 'Compile refused — no goal in the typed description.',
    });
  }

  let stages = normalizeStages(input.stages);
  if (!stages.length && nonEmpty(input.description)) {
    stages = parseStagesFromProse(String(input.description));
  }
  if (!stages.length) {
    return makeFailure('compile-failed', {
      error: 'stages_missing',
      message: 'Compile refused — no stages could be compiled from the description.',
    });
  }

  const steps = stages.map((s, i) => {
    const step_id = s.step_id ?? `stage-${i + 1}`;
    const name = s.name;
    const done_when = s.done_when ?? `Stage '${name}' meets its done-when.`;
    const oranges = Array.isArray(s.oranges) && s.oranges.length
      ? s.oranges.map(String)
      : [...DEFAULT_ORANGES_PROMPTS];
    return {
      step_id,
      name,
      status: 'proposed',
      done_when,
      oranges_annotations: oranges,
      order: i + 1,
    };
  });

  const body = {
    schema: SCAFFOLDING_PROPOSAL_SCHEMA,
    kind: 'scaffolding_proposal',
    goal,
    steps,
    oranges: {
      law: 'anticipatory-prompts-zero-model',
      per_step: true,
      default_prompts: [...DEFAULT_ORANGES_PROMPTS],
    },
    requires_batch_confirm: true,
    confirmed: false,
    zero_model: true,
    fixture_only: true,
  };
  const proposal_hash = contentHash(body);
  const proposal = {
    ...body,
    proposal_hash,
    proposal_id: `fixture-scaffold-${proposal_hash.slice(0, 12)}`,
  };

  return { ok: true, proposal };
}

/**
 * Append a scaffolding_proposed event to the fixture ledger.
 * @param {import('./ledger.mjs').FixtureLedger} ledger
 * @param {object} proposal
 */
export function emitScaffoldingProposed(ledger, proposal) {
  return ledger.append({
    kind: 'scaffolding_proposed',
    proposal_id: proposal.proposal_id,
    proposal_hash: proposal.proposal_hash,
    goal: proposal.goal,
    steps: proposal.steps,
    oranges: proposal.oranges,
    requires_batch_confirm: true,
    confirmed: false,
    zero_model: true,
    fixture_only: true,
  });
}

function nonEmpty(v) {
  return v != null && String(v).trim() !== '';
}

function firstLine(text) {
  const line = String(text).split(/\r?\n/).find((l) => l.trim());
  return line ? line.trim() : null;
}

function normalizeStages(stages) {
  if (!Array.isArray(stages) || !stages.length) return [];
  const out = [];
  for (let i = 0; i < stages.length; i++) {
    const s = stages[i];
    if (typeof s === 'string' && s.trim()) {
      out.push({ name: s.trim() });
      continue;
    }
    if (s && typeof s === 'object' && nonEmpty(s.name)) {
      out.push({
        step_id: s.step_id ?? s.id ?? undefined,
        name: String(s.name).trim(),
        done_when: s.done_when ?? s.doneWhen ?? undefined,
        oranges: s.oranges ?? s.oranges_annotations,
      });
    }
  }
  return out;
}

/**
 * Best-effort deterministic stage parse from prose:
 * lines matching "Stage: X", "N. X", or "- X".
 * @param {string} prose
 */
function parseStagesFromProse(prose) {
  const lines = String(prose).split(/\r?\n/);
  const out = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    let m =
      line.match(/^stage\s*[:\-]\s*(.+)$/i) ||
      line.match(/^\d+[.)]\s+(.+)$/) ||
      line.match(/^[-*]\s+(.+)$/);
    if (m && m[1].trim()) {
      out.push({ name: m[1].trim() });
    }
  }
  return out;
}
