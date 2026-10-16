// Track B6 W2 — ceremony emitters gated by ceremonyLevel only.
//
// Ceremony thins UI chrome / explain verbosity under LITE.
// Ceremony MUST NEVER gate or early-return the reaper decision / proof-of-death path
// (that lives in reaper-path.mjs).

import { ceremonyLevelOrdinal } from 'fil<path>';
import { resolveZombieHunterBand } from './triage-band.mjs';

/**
 * Named ceremony emitter kinds (non-decision chrome only).
 * @type {ReadonlyArray<string>}
 */
export const CEREMONY_EMITTER_KINDS = Object.freeze([
  'extra_ui_panel',
  'ownership_ui_chrome',
  'non_decision_banner',
  'explain_verbosity',
  'deep_brief',
]);

/**
 * Which emitter kinds fire at each ceremony level (lower = leaner).
 * LITE: ownership badge chrome only (minimal).
 * SPIKE-FIRST: + non_decision_banner.
 * FULL: all emitters.
 */
const EMITTERS_BY_ORDINAL = Object.freeze({
  0: Object.freeze(['ownership_ui_chrome']), // lite
  1: Object.freeze(['ownership_ui_chrome', 'non_decision_banner', 'explain_verbosity']), // spike-first
  2: Object.freeze([
    'extra_ui_panel',
    'ownership_ui_chrome',
    'non_decision_banner',
    'explain_verbosity',
    'deep_brief',
  ]), // full
});

/**
 * @returns {ReadonlyArray<string>}
 */
export function listCeremonyEmitters() {
  return CEREMONY_EMITTER_KINDS;
}

/**
 * Resolve ceremonyLevel from lock opts (sole resolve) or explicit override.
 * @param {object} [opts]
 * @returns {string}
 */
export function resolveCeremonyLevel(opts = {}) {
  if (opts.ceremonyLevel != null && String(opts.ceremonyLevel).trim()) {
    return String(opts.ceremonyLevel).trim().toLowerCase().replace(/_/g, '-');
  }
  const band = resolveZombieHunterBand(opts);
  return band.ceremonyLevel;
}

/**
 * Whether a ceremony emitter kind should fire at the given ceremonyLevel.
 * Unknown level → leanest (lite) posture (fail SAFE on chrome, not on safety).
 *
 * @param {string} kind
 * @param {string} ceremonyLevel
 * @returns {boolean}
 */
export function shouldEmitCeremony(kind, ceremonyLevel) {
  const ord = ceremonyLevelOrdinal(ceremonyLevel);
  const allowed = EMITTERS_BY_ORDINAL[ord == null ? 0 : ord] || EMITTERS_BY_ORDINAL[0];
  return allowed.includes(String(kind || ''));
}

/**
 * Emit one ceremony event if ceremonyLevel permits.
 * Returns a structured receipt (hermetic call-count friendly). Never throws.
 *
 * @param {string} kind
 * @param {object} [payload]
 * @param {object} [opts] — ceremonyLevel | depth/env for sole resolve
 * @returns {Readonly<{ kind: string, emitted: boolean, ceremonyLevel: string, reason: string }>}
 */
export function emitCeremony(kind, payload = {}, opts = {}) {
  const ceremonyLevel = resolveCeremonyLevel(opts);
  const ok = shouldEmitCeremony(kind, ceremonyLevel);
  return Object.freeze({
    kind: String(kind || ''),
    emitted: ok,
    ceremonyLevel,
    reason: ok ? 'CEREMONY_EMIT' : 'CEREMONY_THINNED',
    payload: payload && typeof payload === 'object' ? payload : {},
  });
}

/**
 * Run all named ceremony emitters; returns receipts + count (LITE leaner than FULL).
 * @param {object} [payload]
 * @param {object} [opts]
 * @returns {Readonly<{ ceremonyLevel: string, emissions: ReadonlyArray<object>, emittedCount: number, kindsEmitted: ReadonlyArray<string> }>}
 */
export function emitAllCeremony(payload = {}, opts = {}) {
  const ceremonyLevel = resolveCeremonyLevel(opts);
  const emissions = CEREMONY_EMITTER_KINDS.map((kind) =>
    emitCeremony(kind, payload, { ...opts, ceremonyLevel }),
  );
  const kindsEmitted = emissions.filter((e) => e.emitted).map((e) => e.kind);
  return Object.freeze({
    ceremonyLevel,
    emissions: Object.freeze(emissions),
    emittedCount: kindsEmitted.length,
    kindsEmitted: Object.freeze(kindsEmitted),
  });
}

export { ceremonyLevelOrdinal };
