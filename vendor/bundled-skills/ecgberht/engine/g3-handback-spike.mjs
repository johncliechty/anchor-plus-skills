/**
 * Wave 5 — G3 handback-validation spike.
 *
 * receipt-validate.mjs passes a real trio handback, refuses a corrupted one.
 * Both paths are covered by tests; this module is the checked-in spike runner
 * that emits a verbatim verdict artifact.
 *
 * "Real" = the checked-in skill-lane conformant fixture (and, when present,
 * on-disk G4 handback body) — NOT a spike-local synthetic receipt. That closes
 * the self-built / synthesized-handback review finding.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateReceipt } from './receipt-validate.mjs';
import { validateHandbackBody } from './handback-contract.mjs';
import { writeFileAtomicSync, withFileLock } from './durable-write.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(ENGINE_DIR, '..');

export const G3_SPIKE_SCHEMA = 'ecgberht-g3-handback-spike-v0';
export const G3_VERDICT_REL = path.join(
  'artifacts',
  'g3-handback-spike-verdict.json',
);

/** Checked-in skill-lane conformant handback (Wave 4 contract fixture). */
export const CONFORMANT_HANDBACK_REL = path.join(
  'fixtures',
  'handback-contract',
  'conformant-handback.json',
);

/** Checked-in torn/incomplete handback for refuse path. */
export const TORN_HANDBACK_REL = path.join(
  'fixtures',
  'handback-contract',
  'torn-handback.json',
);

/**
 * Load fixture trio handbacks if present (relative fixtures/).
 * @param {string} [root]
 */
export function loadFixtureHandbacks(root = DEFAULT_ROOT) {
  const okPath = path.join(root, CONFORMANT_HANDBACK_REL);
  const tornPath = path.join(root, TORN_HANDBACK_REL);
  return {
    conformant: fs.existsSync(okPath)
      ? JSON.parse(fs.readFileSync(okPath, 'utf8'))
      : null,
    torn: fs.existsSync(tornPath)
      ? JSON.parse(fs.readFileSync(tornPath, 'utf8'))
      : null,
    conformant_path: CONFORMANT_HANDBACK_REL.split(path.sep).join('/'),
    torn_path: TORN_HANDBACK_REL.split(path.sep).join('/'),
  };
}

/**
 * Real trio handback for G3: prefer checked-in conformant fixture.
 * Falls back only when the fixture is absent (tests may inject opts.real).
 *
 * @param {string} [root]
 * @param {object} [extra] shallow-merge overrides (never used to invent a body when fixture exists)
 * @returns {{ handback: object, source: string, source_path: string|null }}
 */
export function loadRealTrioHandback(root = DEFAULT_ROOT, extra = {}) {
  const fixtures = loadFixtureHandbacks(root);
  if (fixtures.conformant && typeof fixtures.conformant === 'object') {
    return {
      handback: { ...fixtures.conformant, ...extra },
      source: 'fixtures/handback-contract/conformant-handback.json',
      source_path: fixtures.conformant_path,
    };
  }
  // Last resort: refuse to invent a "real" body — caller must supply opts.real
  return {
    handback: null,
    source: 'missing-conformant-fixture',
    source_path: fixtures.conformant_path,
  };
}

/**
 * @deprecated Use loadRealTrioHandback — kept as a thin alias for tests that
 * still import buildRealTrioHandback; returns the fixture body or throws.
 * @param {object} [extra]
 */
export function buildRealTrioHandback(extra = {}) {
  const loaded = loadRealTrioHandback(DEFAULT_ROOT, extra);
  if (!loaded.handback) {
    throw new Error(
      'G3: conformant handback fixture missing — cannot synthesize a "real" trio handback',
    );
  }
  return loaded.handback;
}

/**
 * Corrupt a handback so validation must refuse (drop required fields / monologue).
 * @param {object} handback
 * @param {'drop-fields'|'monologue'|'bad-kind'|'torn-fixture'} [mode]
 * @param {string} [root]
 */
export function corruptHandback(handback, mode = 'drop-fields', root = DEFAULT_ROOT) {
  if (mode === 'monologue') {
    return 'this is free-form monologue with no receipt shape at all';
  }
  if (mode === 'bad-kind') {
    return { ...handback, kind: 'not-a-real-kind' };
  }
  if (mode === 'torn-fixture') {
    const fixtures = loadFixtureHandbacks(root);
    if (fixtures.torn) return fixtures.torn;
  }
  const bad = { ...handback };
  delete bad.active_effort;
  delete bad.why_next;
  delete bad.tool_depth_why;
  return bad;
}

/**
 * Run G3 spike: pass real (fixture) handback, refuse corrupted.
 * @param {{
 *   real?: object,
 *   corrupted?: *,
 *   root?: string,
 * }} [opts]
 */
export function runG3HandbackSpike(opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  let real = opts.real;
  let real_source = 'injected';
  let real_source_path = null;
  if (!real) {
    const loaded = loadRealTrioHandback(root);
    real = loaded.handback;
    real_source = loaded.source;
    real_source_path = loaded.source_path;
  }

  const fail_reasons = [];
  if (!real || typeof real !== 'object') {
    fail_reasons.push('real_handback_unavailable');
    return {
      schema: G3_SPIKE_SCHEMA,
      verdict: 'FAIL',
      real: {
        ok: false,
        receipt_ok: false,
        contract_ok: false,
        skill: null,
        handback_id: null,
        source: real_source,
        source_path: real_source_path,
      },
      corrupted: {
        refused: false,
        receipt_ok: null,
        error: null,
      },
      fail_reasons,
      validator: 'receipt-validate.mjs + handback-contract validateHandbackBody',
    };
  }

  const corrupted =
    opts.corrupted ??
    corruptHandback(real, 'drop-fields', root);

  const realReceipt = validateReceipt(real);
  const realContract = validateHandbackBody(real);
  const realOk = realReceipt.ok === true && realContract.ok === true;

  const badReceipt = validateReceipt(corrupted);
  const badOk = badReceipt.ok === true;
  const refuseOk = badOk === false;

  if (!realOk) fail_reasons.push('real_handback_failed_validation');
  if (!refuseOk) fail_reasons.push('corrupted_handback_was_accepted');

  const verdict = fail_reasons.length === 0 ? 'PASS' : 'FAIL';

  return {
    schema: G3_SPIKE_SCHEMA,
    verdict,
    real: {
      ok: realOk,
      receipt_ok: realReceipt.ok === true,
      contract_ok: realContract.ok === true,
      skill: real.skill ?? null,
      handback_id: real.handback_id ?? null,
      source: real_source,
      source_path: real_source_path,
      synthesized: false,
    },
    corrupted: {
      refused: refuseOk,
      receipt_ok: badOk,
      error: badReceipt.error ?? badReceipt.issues?.[0] ?? null,
    },
    fail_reasons,
    validator: 'receipt-validate.mjs + handback-contract validateHandbackBody',
  };
}

/**
 * @param {string} [root]
 */
export function g3VerdictPath(root = DEFAULT_ROOT) {
  return path.join(root, G3_VERDICT_REL);
}

/**
 * @param {object} [verdict]
 * @param {{ root?: string }} [opts]
 */
export function writeG3SpikeVerdict(verdict, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const body = verdict ?? runG3HandbackSpike({ root });
  const outPath = g3VerdictPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const payload = {
    ...body,
    written_by: 'g3-handback-spike.mjs',
  };
  withFileLock(outPath, () => {
    writeFileAtomicSync(outPath, `${JSON.stringify(payload, null, 2)}\n`);
  });
  return outPath;
}
