/**
 * Wave 13 — Gate-surfacing as a first-class path.
 *
 * A HALT / gate question from a commissioned run is a named status event
 * (gate_surface), not an ambient log line. Proven on a deliberately
 * gate-heavy REAL Crucible commission from the EXTERNALLY-OBSERVABLE class
 * (wave-local real-run gate `gate/w13-real-run.mjs`), measured against the
 * Wave-5 gate budget.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import { appendOutboxRecord } from './status-outbox.mjs';
import { ingestStatusEvents, makeFixtureProducer } from './status-ingestion.mjs';
import { writeFileAtomicSync } from './durable-write.mjs';

/** Event kind for first-class gate surfacing. */
export const GATE_SURFACE_KIND = 'gate_surface';

/**
 * Wave-5 gate budget reference (wall-clock ceilings used as the comparison
 * baseline for Wave-13 gate-surfacing latency).
 * researchPrime LITE replay ≤ 10m; Jumper LITE ≤ 45m — gate surface itself
 * must land far under that (sub-minute class for the event emit).
 */
export const W5_GATE_BUDGET_MS = Object.freeze({
  researchPrime_LITE_ms: 10 * 60 * 1000,
  jumper_LITE_ms: 45 * 60 * 1000,
  /** Gate-surface event itself must land within this (first-class path). */
  gate_surface_budget_ms: 60 * 1000,
});

/**
 * Build a gate_surface outbox/seam event.
 *
 * @param {{
 *   gate_id: string,
 *   run_id: string,
 *   step_id?: string,
 *   question?: string,
 *   halt_class?: string,
 *   skill?: string,
 *   seq?: number,
 *   client_event_id?: string,
 *   wall_at?: string,
 * }} fields
 */
export function buildGateSurfaceEvent(fields) {
  if (!fields?.gate_id || !fields?.run_id) {
    return {
      ok: false,
      error: 'gate_id_and_run_id_required',
    };
  }
  return {
    ok: true,
    event: {
      kind: GATE_SURFACE_KIND,
      gate_id: fields.gate_id,
      run_id: fields.run_id,
      step_id: fields.step_id ?? null,
      question: fields.question ?? null,
      halt_class: fields.halt_class ?? 'EXTERNALLY-OBSERVABLE',
      skill: fields.skill ?? 'crucible',
      wall_at: fields.wall_at ?? new Date().toISOString(),
      client_event_id:
        fields.client_event_id || `gate:${fields.run_id}:${fields.gate_id}`,
      ...(fields.seq != null ? { seq: fields.seq } : {}),
    },
  };
}

/**
 * Emit a gate_surface into the run outbox (producer side).
 * @param {string} worktreeRoot
 * @param {object} fields
 * @param {{ producer?: string }} [opts]
 */
export function emitGateSurfaceToOutbox(worktreeRoot, fields, opts = {}) {
  const built = buildGateSurfaceEvent(fields);
  if (!built.ok) return built;
  return appendOutboxRecord(worktreeRoot, built.event, {
    producer: opts.producer || 'anchor',
  });
}

/**
 * Ingest a gate_surface through the seam (host-less or after outbox drain).
 * @param {string} projectPath
 * @param {object} fields
 * @param {{ who?: string, at?: string, seed?: object|null }} [opts]
 */
export function surfaceGateThroughSeam(projectPath, fields, opts = {}) {
  const built = buildGateSurfaceEvent({ ...fields, seq: fields.seq ?? 1 });
  if (!built.ok) return built;
  const t0 = Date.now();
  const producer = makeFixtureProducer([built.event], { id: 'anchor' });
  const ingested = ingestStatusEvents(producer, {
    projectPath,
    who: opts.who || 'gate-surface',
    at: opts.at,
    seed: opts.seed,
    skip_index: true,
  });
  const elapsed = Date.now() - t0;
  const withinBudget = elapsed <= W5_GATE_BUDGET_MS.gate_surface_budget_ms;

  return {
    ok: ingested.ok !== false && withinBudget,
    first_class: true,
    kind: GATE_SURFACE_KIND,
    gate_id: fields.gate_id,
    run_id: fields.run_id,
    elapsed_ms: elapsed,
    budget_ms: W5_GATE_BUDGET_MS.gate_surface_budget_ms,
    within_budget: withinBudget,
    w5_budget_reference: W5_GATE_BUDGET_MS,
    answered_through_standard_path: true,
    ingested,
  };
}

/**
 * Record a wave-local real-run gate result (operator gate, not standing suite).
 * @param {string} skillRoot
 * @param {object} record
 */
export function writeW13RealRunRecord(skillRoot, record) {
  const outPath = path.join(skillRoot, 'artifacts', 'w13-real-run-record.json');
  const body = {
    schema: 'ecgberht-w13-real-run-record-v0',
    written_by: 'gate/w13-real-run.mjs',
    ...record,
    recorded_at: record.recorded_at || new Date().toISOString(),
  };
  // Redact host-absolute user homes if any slipped in
  const text = JSON.stringify(body, null, 2).replace(
    /([A-Za-z]:)?[\\/]Users[\\/][^\\/"'\s]+/gi,
    '<redacted-user-home>',
  );
  writeFileAtomicSync(outPath, `${text}\n`);
  return { ok: true, path: outPath };
}

/**
 * Read Wave-5 budget artifact for comparison (if present).
 * @param {string} skillRoot
 */
export function loadW5GateBudgetReference(skillRoot) {
  const p = path.join(skillRoot, 'artifacts', 'w5-real-run-record.json');
  if (!fs.existsSync(p)) {
    return { ok: true, present: false, budget: W5_GATE_BUDGET_MS };
  }
  try {
    const raw = JSON.parse(fs.readFileSync(p, 'utf8'));
    return {
      ok: true,
      present: true,
      record: raw,
      budget: W5_GATE_BUDGET_MS,
    };
  } catch {
    return { ok: true, present: false, budget: W5_GATE_BUDGET_MS };
  }
}
