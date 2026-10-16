/**
 * Wave 2 — fixture-internal failure states (honesty table).
 *
 * unknown is DISTINCT from empty. Every surface that can fail names one of
 * these codes; prose never collapses "unknown" into "nothing there."
 */

/** @typedef {'compile-failed'|'confirm-refused'|'stub-handback-invalid'|'reflection-blocked'|'empty'|'unknown'} FixtureFailureCode */

/**
 * Named failure table. Each row is a distinct honest outcome.
 * `empty` = store readable and legitimately vacant.
 * `unknown` = store or state cannot be read / determined — never render as empty.
 */
export const FIXTURE_FAILURE_STATES = Object.freeze([
  Object.freeze({
    code: 'compile-failed',
    status: 'FIXTURE_COMPILE_FAILED',
    prose:
      'Typed NL description could not compile to coarse scaffolding — proposal refused; no ledger write.',
  }),
  Object.freeze({
    code: 'confirm-refused',
    status: 'FIXTURE_CONFIRM_REFUSED',
    prose:
      'Batch confirm refused (missing who, hash mismatch, or auth denial) — nothing confirmed, nothing spent.',
  }),
  Object.freeze({
    code: 'stub-handback-invalid',
    status: 'FIXTURE_STUB_HANDBACK_INVALID',
    prose:
      'Stub executor returned a handback that failed structured validation — named invalid, not absorbed as success.',
  }),
  Object.freeze({
    code: 'reflection-blocked',
    status: 'FIXTURE_REFLECTION_BLOCKED',
    prose:
      'Validated handback present but reflection/proposal emission blocked (missing prior facts) — blocked, not silent.',
  }),
  Object.freeze({
    code: 'empty',
    status: 'FIXTURE_EMPTY',
    prose: 'Fixture ledger is readable and contains no events yet.',
  }),
  Object.freeze({
    code: 'unknown',
    status: 'FIXTURE_UNKNOWN',
    prose:
      'Fixture ledger state cannot be determined — reported as unknown, never as empty.',
  }),
]);

/** Codes only (for allow-lists). */
export const FIXTURE_FAILURE_CODES = Object.freeze(
  FIXTURE_FAILURE_STATES.map((r) => r.code),
);

/**
 * Look up a failure row by code.
 * @param {string} code
 * @returns {(typeof FIXTURE_FAILURE_STATES)[number]|null}
 */
export function failureStateFor(code) {
  return FIXTURE_FAILURE_STATES.find((r) => r.code === code) ?? null;
}

/**
 * Build a named failure result. Always carries code + status + prose.
 * @param {FixtureFailureCode} code
 * @param {object} [extra]
 */
export function makeFailure(code, extra = {}) {
  const row = failureStateFor(code);
  if (!row) {
    return {
      ok: false,
      code: 'unknown',
      status: 'FIXTURE_UNKNOWN',
      prose: failureStateFor('unknown').prose,
      message: `Unknown failure code '${code}' — reported as unknown, not empty.`,
      ...extra,
    };
  }
  return {
    ok: false,
    code: row.code,
    status: row.status,
    prose: row.prose,
    message: row.prose,
    ...extra,
  };
}

/**
 * Honesty invariant: empty and unknown must never share a status string.
 * @returns {boolean}
 */
export function emptyDistinctFromUnknown() {
  const empty = failureStateFor('empty');
  const unknown = failureStateFor('unknown');
  return (
    empty != null &&
    unknown != null &&
    empty.code !== unknown.code &&
    empty.status !== unknown.status &&
    empty.prose !== unknown.prose
  );
}
