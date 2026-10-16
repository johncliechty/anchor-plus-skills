/**
 * THE STEP FINDINGS LEDGER (2026-08-07, John's design correction).
 *
 * "When researchPrime gets done it doesn't just stash it — it's going to
 * provide detail for the next parts of the scaffolding." This is where that
 * detail lives: per-step, append-only, source-attributed facts fed by the
 * reflection turn after every run (and readable by the rail's step-detail
 * click and the conversation context).
 *
 * Deliberately NOT the elaboration store: elaboration answers feed the closed
 * commissionability predicate (deliverable / acceptance / constraints);
 * findings are open campaign FACTS ("old weights Quizzes 50/40/10", "only 4 of
 * 13 decks exist"). Durable, never authoritative for step status.
 */

import fs from 'node:fs';
import path from 'node:path';

import { withFileLock, writeFileAtomicSync, LOCK_TIMEOUT_MS } from './durable-write.mjs';

export const STEP_FINDINGS_SCHEMA = 'ecgberht-step-findings-v0';
export const STEP_FINDINGS_REL = path.join('.ecgberht', 'step-findings.json');

/** Bound per step — a campaign accumulates, it does not hoard. */
export const MAX_FINDINGS_PER_STEP = 200;

export function stepFindingsPath(projectPath) {
  return path.join(path.resolve(projectPath), STEP_FINDINGS_REL);
}

/**
 * Read the findings store. Missing → empty-but-valid; corrupt → honest unknown.
 * @param {string} projectPath
 */
export function readStepFindings(projectPath) {
  const file = stepFindingsPath(projectPath);
  if (!fs.existsSync(file)) {
    return { ok: true, exists: false, steps: {} };
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    return { ok: true, exists: true, steps: parsed.steps ?? {} };
  } catch (e) {
    return { ok: false, error: 'step_findings_unreadable', detail: String(e?.message ?? e), steps: {} };
  }
}

/**
 * Append findings to a step. Best-effort, append-only, source-attributed.
 * @param {string} projectPath
 * @param {{ step_id: string, findings: string[], source?: string, at?: string }} opts
 */
export function appendStepFindings(projectPath, opts = {}) {
  const step_id = String(opts.step_id ?? '').trim();
  const list = (Array.isArray(opts.findings) ? opts.findings : [])
    .map((f) => String(f ?? '').trim()).filter(Boolean);
  if (!step_id || !list.length) return { ok: true, appended: 0 };
  const file = stepFindingsPath(projectPath);
  const at = opts.at ?? new Date().toISOString();
  const source = String(opts.source ?? 'steward').trim();
  try {
    return withFileLock(
      file,
      () => {
        const current = readStepFindings(projectPath);
        if (!current.ok) return { ...current, appended: 0 };
        const steps = current.steps;
        const rows = Array.isArray(steps[step_id]) ? steps[step_id] : [];
        for (const f of list) {
          // A byte-identical finding from the same source is not new knowledge.
          if (rows.some((r) => r.finding === f && r.source === source)) continue;
          rows.push({ finding: f, source, at });
        }
        steps[step_id] = rows.slice(-MAX_FINDINGS_PER_STEP);
        fs.mkdirSync(path.dirname(file), { recursive: true });
        writeFileAtomicSync(file, `${JSON.stringify(
          { schema: STEP_FINDINGS_SCHEMA, authoritative_for_status: false, steps },
          null, 2)}\n`);
        return { ok: true, appended: list.length, step_id };
      },
      { timeoutMs: LOCK_TIMEOUT_MS },
    );
  } catch (e) {
    return { ok: false, appended: 0, error: String(e?.message ?? e) };
  }
}

/**
 * Findings for one step, newest last. Empty array when none.
 * @param {string} projectPath
 * @param {string} stepId
 */
export function findingsForStep(projectPath, stepId) {
  const read = readStepFindings(projectPath);
  if (!read.ok) return [];
  return Array.isArray(read.steps[stepId]) ? read.steps[stepId] : [];
}
