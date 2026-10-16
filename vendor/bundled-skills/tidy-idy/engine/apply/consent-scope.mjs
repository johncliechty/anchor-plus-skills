// engine/apply/consent-scope.mjs — Wave 3: the CONSENT-SCOPE INVARIANT.
//
//   An approved operation mutates only the state its tile named. No Apply ever
//   changes any path's git tracking class (tracked / untracked / ignored /
//   absent), or writes .gitignore or index state, beyond the operation the tile
//   declared.
//
// The failure this exists to make impossible is the helpful side effect: a
// REMOVE that also drops an ignore rule "while we're here", a SAVE that also
// untracks something, a Bootstrap-ish `git add -A` sneaking into a findings
// Apply. Each is defensible in isolation and each is a thing the human did not
// consent to, which is the only test that matters.
//
// The assertion is mechanical: capture every in-scope path's porcelain=v2 class
// BEFORE the Apply and AFTER it, and require every difference to be covered by a
// transition some approved tile explicitly declared (see plan.mjs's
// `declaredTransitions`). An undeclared difference is a violation by definition —
// there is no allow-list of "benign" ones.

import { loadPorcelain, TRACKING } from '../porcelain.mjs';
import { toPosixRel } from '../glob.mjs';

/** Paths whose class is not the user's business — the tool's own state dir. */
const IGNORED_PREFIXES = ['.tidy-idy/', '.git/'];

function isToolPath(rel) {
  return IGNORED_PREFIXES.some((p) => rel === p.slice(0, -1) || rel.startsWith(p));
}

/**
 * Every path's tracking class right now, as a plain object.
 *
 * Includes tracked-and-clean paths (which `git status` never mentions) by
 * reading the index too — otherwise a file that went from tracked-clean to
 * untracked would look like "absent → untracked", i.e. the exact class change
 * this invariant is meant to catch would be invisible.
 */
export async function capturePorcelainClasses({ git }) {
  if (!git) return {};
  const view = await loadPorcelain({ git, state: {} });
  if (!view) return {};

  const classes = {};
  for (const p of view.tracked) {
    const rel = toPosixRel(p);
    if (!isToolPath(rel)) classes[rel] = TRACKING.TRACKED_CLEAN;
  }
  for (const rec of view.records) {
    const rel = toPosixRel(rec.path);
    if (!isToolPath(rel)) classes[rel] = rec.trackingClass;
  }
  return classes;
}

/**
 * Diff two class captures against what the approved tiles declared.
 *
 * A path with ANY declared transition is accepted (and the observed transition
 * is recorded next to the declared one, so a reviewer can see both). A path with
 * none is a violation. That is precisely the invariant's wording: identical
 * pre/post class EXCEPT paths whose approved finding explicitly declared the
 * class transition.
 *
 * @param {{before: object, after: object, declared: object[]}} opts
 */
export function diffPorcelainClasses({ before = {}, after = {}, declared = [] } = {}) {
  const declaredByPath = new Map();
  for (const t of declared || []) {
    const rel = toPosixRel(t.path);
    if (!declaredByPath.has(rel)) declaredByPath.set(rel, []);
    declaredByPath.get(rel).push(t);
  }

  const paths = new Set([...Object.keys(before), ...Object.keys(after)]);
  const changes = [];
  const violations = [];

  for (const rel of paths) {
    const from = before[rel] || 'absent';
    const to = after[rel] || 'absent';
    if (from === to) continue;

    const decl = declaredByPath.get(rel) || null;
    const change = { path: rel, observed: { from, to }, declared: decl };
    changes.push(change);
    if (!decl) {
      violations.push({
        ...change,
        message: `CONSENT-SCOPE VIOLATION: '${rel}' changed git tracking class ${from} → ${to} but no approved tile declared that transition — the Apply mutated state nobody consented to`,
      });
    }
  }

  return {
    ok: violations.length === 0,
    changes,
    violations,
    note: violations.length
      ? `${violations.length} undeclared tracking-class change(s)`
      : `${changes.length} tracking-class change(s), every one declared by an approved tile`,
  };
}

/** Capture-diff in one call, for the Apply executor's post-step check. */
export async function assertConsentScope({ git, before, declared }) {
  const after = await capturePorcelainClasses({ git });
  return { ...diffPorcelainClasses({ before, after, declared }), before, after };
}

export default { capturePorcelainClasses, diffPorcelainClasses, assertConsentScope };
