// Cross-family SEAT resolution from the Anchor dashboard prefs (2026-09-04, John: "use the models that
// are selected in the Anchor dashboard").
//
// THE RULE (Skill Foundry AGENTS.md → "Skill tiers", UNIVERSAL SEATING LAW; amendment John 2026-09-04):
// the cross-family verifier seat is whichever configured family in Anchor's prefs (`review_family`
// first — the check seat — then `coding_family`) is NOT the author's own family. Gemini is used ONLY
// when a pref names it; it is never the default. When every configured family equals the author's,
// there is no cross-family seat: the caller stamps `cross_model:false` honestly (or takes the
// generator-independent ollama fallback) — a same-family check is never presented as cross-family.
//
// Prefs come from ONE place: the trio drivers' `loadModelFamilies` (Anchor data-dir settings.json →
// ~/.anchor/model_prefs.json → historical default), dynamic-imported from the pinned driver index so
// this skill never re-implements the read. Tests inject `loadModelFamilies` and never touch disk.
//
// A seat is only usable when tools.manifest.json carries a tool entry for that family (driver_ref +
// run_export + model) — the manifest is the pinned transport table; an unpinned family is reported,
// not guessed.

import { pathToFileURL } from 'node:url';

/** The pinned trio driver index (the ONE family→driver mechanism on this host). */
export const DEFAULT_TRIO_DRIVERS_REF = '<path>';

/** The families a seat may resolve to (mirrors trio drivers' VALID_MODEL_FAMILIES). */
export const SEAT_FAMILIES = Object.freeze(['claude', 'gemini', 'grok', 'chatgpt']);

/** The historical author of every claim this engine verifies (the Claude Code session). */
export const DEFAULT_AUTHOR_FAMILY = 'claude';

const lower = (f) => (typeof f === 'string' ? f.trim().toLowerCase() : '');

/**
 * Pick the seat family from the two dashboard knobs. Pure.
 *   chooseSeat({ coding:'chatgpt', review:'claude' }, 'claude') -> chatgpt   (John's case, 2026-09-04)
 *   chooseSeat({ coding:'claude',  review:'grok'   }, 'claude') -> grok
 *   chooseSeat({ coding:'claude',  review:'claude' }, 'claude') -> null (single-family, honest stamp)
 *   chooseSeat({ coding:'claude',  review:'gemini' }, 'claude') -> gemini (only because a pref names it)
 * @returns {{ family: string|null, cross_model: boolean, candidates: string[], reason: string }}
 */
export function chooseSeat({ coding, review } = {}, author = DEFAULT_AUTHOR_FAMILY) {
  const a = lower(author) || DEFAULT_AUTHOR_FAMILY;
  const candidates = [lower(review), lower(coding)].filter((f) => SEAT_FAMILIES.includes(f));
  const family = candidates.find((f) => f !== a) || null;
  if (!family) {
    return Object.freeze({
      family: null,
      cross_model: false,
      candidates,
      reason: `single-family: every configured family (${candidates.join(', ') || 'none'}) is the author's own (${a}) — no cross-family seat; stamp cross_model:false`,
    });
  }
  return Object.freeze({
    family,
    cross_model: true,
    candidates,
    reason: `${family} is the configured ${family === lower(review) ? 'review_family' : 'coding_family'} and is not the author's family (${a})`,
  });
}

/**
 * Read the dashboard prefs through the trio drivers (injectable). Never guesses: an unreadable or
 * missing driver index yields `{ coding:null, review:null, source:'unavailable: …' }` and the seat
 * resolves to null with that reason.
 */
export async function loadFamilies({ env = process.env, driversRef = DEFAULT_TRIO_DRIVERS_REF, loadModelFamilies } = {}) {
  try {
    const loader = typeof loadModelFamilies === 'function'
      ? loadModelFamilies
      : (await import(pathToFileURL(driversRef).href)).loadModelFamilies;
    if (typeof loader !== 'function') throw new Error(`${driversRef} does not export loadModelFamilies`);
    const fams = loader(env) || {};
    return Object.freeze({ coding: lower(fams.coding) || null, review: lower(fams.review) || null, source: fams.source || 'prefs' });
  } catch (e) {
    return Object.freeze({ coding: null, review: null, source: `unavailable: ${e && e.message ? e.message : String(e)}` });
  }
}

/**
 * Resolve the cross-family seat: prefs → family → the manifest's pinned transport for it.
 * @returns {Promise<{ family: string|null, model: string|null, driver_ref: string|null, run_export: string|null,
 *   tool: object|null, cross_model: boolean, author: string, prefs: object, reason: string }>}
 */
export async function resolveCrossFamilySeat({ manifest, env = process.env, author = DEFAULT_AUTHOR_FAMILY, driversRef, loadModelFamilies } = {}) {
  const prefs = await loadFamilies({ env, driversRef, loadModelFamilies });
  const pick = chooseSeat(prefs, author);
  const base = { author: lower(author) || DEFAULT_AUTHOR_FAMILY, prefs, candidates: pick.candidates };
  if (!pick.family) {
    return Object.freeze({ ...base, family: null, model: null, driver_ref: null, run_export: null, tool: null, cross_model: false, reason: pick.reason });
  }
  const tool = manifest && manifest.tools ? manifest.tools[pick.family] : null;
  if (!tool || typeof tool.driver_ref !== 'string' || typeof tool.run_export !== 'string') {
    return Object.freeze({
      ...base, family: null, model: null, driver_ref: null, run_export: null, tool: null, cross_model: false,
      reason: `prefs select ${pick.family} but tools.manifest.json has no pinned transport for it (tools.${pick.family}.driver_ref + run_export) — not guessed`,
    });
  }
  return Object.freeze({
    ...base,
    family: pick.family,
    model: tool.model || null,
    driver_ref: tool.driver_ref,
    run_export: tool.run_export,
    tool,
    cross_model: true,
    reason: pick.reason,
  });
}
