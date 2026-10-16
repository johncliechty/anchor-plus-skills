/**
 * Compose-only commission adapters (W5).
 * researchPrime / Crucible / Foreman / Gandalf / Jumper — spawn/handback contracts only.
 * Zero in-process Shark Tank or Foreman wave loop. Seats from Anchor prefs.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  resolveSeats,
  isProductionSeatSafe,
  findProductModelIds,
} from './seating.mjs';
import {
  validateReceipt,
  buildHandbackReceipt,
  RECEIPT_SCHEMA_ID,
  HANDBACK_REQUIRED_FIELDS,
} from './receipt-validate.mjs';
import { runHarnessCanaries } from './verb-bodies.mjs';

/** Five named skills — compose hooks only. */
export const COMMISSION_SKILLS = Object.freeze([
  'researchPrime',
  'Crucible',
  'Foreman',
  'Gandalf',
  'Jumper',
]);

/** Canonical lowercase → display name. */
const SKILL_ALIASES = Object.freeze({
  researchprime: 'researchPrime',
  research_prime: 'researchPrime',
  research: 'researchPrime',
  crucible: 'Crucible',
  foreman: 'Foreman',
  gandalf: 'Gandalf',
  jumper: 'Jumper',
});

/**
 * Normalize specialist skill name to one of the five, or null.
 * @param {*} name
 * @returns {string|null}
 */
export function normalizeCommissionSkill(name) {
  if (name == null || name === '') return null;
  const raw = String(name).trim();
  if (COMMISSION_SKILLS.includes(raw)) return raw;
  const key = raw.toLowerCase().replace(/\s+/g, '');
  const spaced = raw.toLowerCase().replace(/\s+/g, '_');
  return SKILL_ALIASES[key] ?? SKILL_ALIASES[spaced] ?? SKILL_ALIASES[raw.toLowerCase()] ?? null;
}

/**
 * Build a compose-only spawn contract for one specialist skill.
 * Does NOT run Shark Tank, wave loops, or any in-process specialist engine.
 *
 * @param {{
 *   skill: string,
 *   depth_cell?: string|null,
 *   depth?: string|null,
 *   active_effort?: string|null,
 *   receipt_envelope?: object|null,
 *   receipt?: object|null,
 *   project_cwd?: string|null,
 *   seats?: object|null,
 *   prefs?: object|null,
 *   env?: object,
 *   commission_id?: string|null,
 * }} input
 * @returns {object}
 */
export function buildCommission(input = {}) {
  const skill = normalizeCommissionSkill(input.skill);
  if (!skill) {
    return {
      ok: false,
      error: 'unknown_commission_skill',
      message: `Commission skill must be one of: ${COMMISSION_SKILLS.join(', ')}`,
      compose_only: true,
      allowed_skills: [...COMMISSION_SKILLS],
    };
  }

  const seats =
    input.seats && typeof input.seats === 'object'
      ? input.seats
      : resolveSeats({
          prefs: input.prefs ?? null,
          env: input.env,
          prefsPath: input.prefsPath,
          exists: input.exists,
          readFile: input.readFile,
        });

  if (seats.ok === false) {
    return {
      ok: false,
      error: seats.error ?? 'seat_resolution_failed',
      message: seats.message ?? 'Seat resolution failed for commission',
      compose_only: true,
      skill,
      seats,
    };
  }

  if (!isProductionSeatSafe(seats)) {
    return {
      ok: false,
      error: 'unsafe_production_seat',
      message:
        'Production seats must be subscription CLIs only (no product IDs, no XAI_API_KEY HTTP path)',
      compose_only: true,
      skill,
      seats,
    };
  }

  const depth_cell = input.depth_cell ?? input.depth ?? null;
  const active_effort = input.active_effort ?? null;
  const receipt_envelope =
    input.receipt_envelope ?? input.receipt ?? null;
  const commission_id =
    input.commission_id ??
    `ecgberht-commission-${skill}-${Date.now().toString(36)}`;

  // Spawn contract only — caller (host/orchestrator) may invoke the named skill.
  // Ecgberht never reimplements specialist loops here.
  return {
    ok: true,
    compose_only: true,
    kind: 'compose_spawn',
    skill,
    depth_cell,
    active_effort,
    receipt_envelope,
    commission_id,
    project_cwd: input.project_cwd ?? null,
    seats: {
      coding_family: seats.coding_family,
      review_family: seats.review_family,
      default_cli: seats.default_cli ?? null,
      coding_driver: seats.coding_driver,
      review_driver: seats.review_driver,
      cross_model: seats.cross_model,
      subscription_only: true,
      xai_http_seat: false,
      product_model_ids: [],
    },
    // Explicit negatives: adapters are hooks, not engines
    in_process_shark_tank: false,
    in_process_wave_loop: false,
    spawns_specialist: true,
    executes_in_process: false,
    product_model_ids: findProductModelIds(seats),
  };
}

/**
 * Interpret a specialist handback into a structured receipt path.
 * Missing required fields → receipt-validate fails (via validateHandback).
 *
 * @param {*} handback
 * @param {{ skill?: string, depth_cell?: string|null, commission_id?: string|null, as_of?: string }} [meta]
 */
export function interpretHandback(handback, meta = {}) {
  if (handback == null || typeof handback !== 'object' || Array.isArray(handback)) {
    return {
      ok: false,
      error: 'handback_not_object',
      message: 'Handback must be a structured object',
      receipt: null,
    };
  }

  const receipt = buildHandbackReceipt({
    as_of: handback.as_of ?? meta.as_of,
    active_effort: handback.active_effort,
    why_next: handback.why_next,
    grasscatch_why:
      handback.grasscatch_why !== undefined ? handback.grasscatch_why : null,
    tool_depth_why: handback.tool_depth_why,
    human_wait: handback.human_wait,
    uncertainty_flags: handback.uncertainty_flags,
    skill: handback.skill ?? meta.skill ?? null,
    depth: handback.depth ?? handback.depth_cell ?? meta.depth_cell ?? null,
    commission_id: handback.commission_id ?? meta.commission_id ?? null,
    partial: handback.partial === true,
  });

  const validated = validateReceipt(receipt);
  return {
    ok: validated.ok,
    error: validated.ok ? null : validated.error,
    message: validated.ok
      ? 'Handback validated as structured receipt'
      : validated.message,
    issues: validated.issues ?? [],
    receipt: validated.ok ? validated.receipt : receipt,
    validation: validated,
  };
}

/**
 * Validate a handback receipt (direct or via build).
 * @param {*} handback
 */
export function validateHandback(handback) {
  if (handback && handback.kind === 'handback') {
    return validateReceipt(handback);
  }
  return interpretHandback(handback).validation ?? validateReceipt(handback);
}

/**
 * Factory: named compose-only adapter for one skill.
 * @param {string} skillName
 */
function makeAdapter(skillName) {
  const skill = normalizeCommissionSkill(skillName);
  return Object.freeze({
    skill,
    compose_only: true,
    /** Spawn/handback contract only — never runs specialist engines in-process. */
    buildCommission(input = {}) {
      return buildCommission({ ...input, skill });
    },
    interpretHandback(handback, meta = {}) {
      return interpretHandback(handback, { ...meta, skill });
    },
    interpretExit(code, handback, meta = {}) {
      const hb = interpretHandback(handback, { ...meta, skill });
      if (code !== 0) {
        return {
          ok: false,
          status: 'fail',
          exit_code: code,
          compose_only: true,
          skill,
          handback: hb,
        };
      }
      if (!hb.ok) {
        return {
          ok: false,
          status: 'fail',
          exit_code: code,
          compose_only: true,
          skill,
          handback: hb,
          error: 'handback_receipt_invalid',
        };
      }
      const partial = handback?.partial === true;
      return {
        ok: true,
        status: partial ? 'partial' : 'success',
        exit_code: code,
        compose_only: true,
        skill,
        handback: hb,
      };
    },
  });
}

/** Five named compose-only adapters. */
export const COMMISSION_ADAPTERS = Object.freeze({
  researchPrime: makeAdapter('researchPrime'),
  Crucible: makeAdapter('Crucible'),
  Foreman: makeAdapter('Foreman'),
  Gandalf: makeAdapter('Gandalf'),
  Jumper: makeAdapter('Jumper'),
});

export const commissionResearchPrime = (input) =>
  COMMISSION_ADAPTERS.researchPrime.buildCommission(input);
export const commissionCrucible = (input) =>
  COMMISSION_ADAPTERS.Crucible.buildCommission(input);
export const commissionForeman = (input) =>
  COMMISSION_ADAPTERS.Foreman.buildCommission(input);
export const commissionGandalf = (input) =>
  COMMISSION_ADAPTERS.Gandalf.buildCommission(input);
export const commissionJumper = (input) =>
  COMMISSION_ADAPTERS.Jumper.buildCommission(input);

/**
 * Look up a named adapter (compose hook).
 * @param {string} skillName
 * @returns {object|null}
 */
export function getCommissionAdapter(skillName) {
  const skill = normalizeCommissionSkill(skillName);
  if (!skill) return null;
  return COMMISSION_ADAPTERS[skill] ?? null;
}

/**
 * Export names that must NEVER appear as implemented specialist engines.
 * Used by boundary canaries (definition sites only).
 */
export const FORBIDDEN_REIMPLEMENT_EXPORTS = Object.freeze([
  'runSharkTank',
  'runForemanWaves',
  'runWaveLoop',
  'executeWaveLoop',
  'runInProcessSharkTank',
]);

/**
 * Boundary canaries: openclaw / daemon / Shark-tank reimplementation / compose hooks.
 * @param {string} engineDir
 * @param {{ skillRoot?: string }} [opts]
 */
export function runBoundaryCanaries(engineDir, opts = {}) {
  const harness = runHarnessCanaries(engineDir);
  const shark_hits = [];
  const product_id_hits = [];
  const xai_http_hits = [];
  const scanned = [...(harness.scanned || [])];

  const dir = path.resolve(engineDir);
  const files = listEngineSources(dir);

  // Definition / assignment of forbidden reimplementation entrypoints
  const reimplDef =
    /(?:export\s+)?(?:async\s+)?function\s+(runSharkTank|runForemanWaves|runWaveLoop|executeWaveLoop|runInProcessSharkTank)\b|(?:export\s+const|const|let|var)\s+(runSharkTank|runForemanWaves|runWaveLoop|executeWaveLoop|runInProcessSharkTank)\s*=/;

  // Product model IDs in non-comment code (assignment / property value context)
  const productIdAssign =
    /(?:model(?:_?id|_?name)?|MODEL)\s*[:=]\s*['"`][^'"`]*(?:claude-(?:opus|sonnet|haiku)|claude-3|gemini-[\d.]+|grok-[234])[^'"`]*['"`]/i;

  // Production seat using XAI_API_KEY as live seat path (not ban documentation)
  const xaiSeatUse =
    /(?:process\.env\.XAI_API_KEY|env\.XAI_API_KEY)\s*(?:=|\|\||\?\?|&&)/;

  for (const file of files) {
    const rel = path.relative(dir, file).split(path.sep).join('/');
    if (!scanned.includes(rel)) scanned.push(rel);
    let text;
    try {
      text = fs.readFileSync(file, 'utf8');
    } catch {
      continue;
    }
    const lines = text.split(/\r?\n/);
    lines.forEach((line, idx) => {
      const trimmed = line.trim();
      const code = trimmed.replace(/\/\/.*$/, '').trim();
      if (
        !code ||
        code.startsWith('*') ||
        code.startsWith('/*') ||
        code.startsWith('#')
      ) {
        return;
      }
      // Skip pure string arrays that list forbidden names for canary detection
      if (
        /FORBIDDEN_REIMPLEMENT_EXPORTS|PRODUCT_MODEL_ID_PATTERNS|runBoundaryCanaries/.test(
          code,
        )
      ) {
        return;
      }
      if (reimplDef.test(code)) {
        shark_hits.push({
          file: path.basename(file),
          line: idx + 1,
          text: trimmed.slice(0, 120),
        });
      }
      if (productIdAssign.test(code)) {
        product_id_hits.push({
          file: path.basename(file),
          line: idx + 1,
          text: trimmed.slice(0, 120),
        });
      }
      if (xaiSeatUse.test(code)) {
        xai_http_hits.push({
          file: path.basename(file),
          line: idx + 1,
          text: trimmed.slice(0, 120),
        });
      }
    });
  }

  // Compose hooks present for the five named skills
  const compose_hooks = {};
  for (const skill of COMMISSION_SKILLS) {
    const adapter = COMMISSION_ADAPTERS[skill];
    compose_hooks[skill] = Boolean(
      adapter &&
        adapter.compose_only === true &&
        typeof adapter.buildCommission === 'function' &&
        typeof adapter.interpretHandback === 'function',
    );
  }
  const missing_hooks = COMMISSION_SKILLS.filter((s) => !compose_hooks[s]);

  // Adapters must not export forbidden reimplementation names
  const adapter_export_violations = [];
  for (const skill of COMMISSION_SKILLS) {
    const adapter = COMMISSION_ADAPTERS[skill];
    for (const bad of FORBIDDEN_REIMPLEMENT_EXPORTS) {
      if (adapter && typeof adapter[bad] === 'function') {
        adapter_export_violations.push({ skill, export: bad });
      }
    }
  }

  const ok =
    harness.ok &&
    shark_hits.length === 0 &&
    product_id_hits.length === 0 &&
    xai_http_hits.length === 0 &&
    missing_hooks.length === 0 &&
    adapter_export_violations.length === 0;

  return {
    ok,
    openclaw_hits: harness.openclaw_hits ?? [],
    daemon_hits: harness.daemon_hits ?? [],
    shark_hits,
    product_id_hits,
    xai_http_hits,
    compose_hooks,
    missing_hooks,
    adapter_export_violations,
    commission_skills: [...COMMISSION_SKILLS],
    scanned,
    receipt_schema_id: RECEIPT_SCHEMA_ID,
    handback_required_fields: [...HANDBACK_REQUIRED_FIELDS],
    message: ok
      ? 'Boundary canaries green: compose-only hooks, no openclaw/daemon/shark reimpl, no product-ID seats'
      : 'Boundary canary failed',
  };
}

function listEngineSources(dir) {
  const out = [];
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const ent of entries) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (ent.name === 'node_modules' || ent.name === '.git') continue;
      out.push(...listEngineSources(p));
    } else if (ent.isFile() && /\.(mjs|js|cjs)$/.test(ent.name)) {
      out.push(p);
    }
  }
  return out;
}
