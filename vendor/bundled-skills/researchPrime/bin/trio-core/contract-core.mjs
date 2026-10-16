// bin/trio-core/contract-core.mjs — the trio-core's shared CONTRACT primitives.
//
// IMPLEMENTATION-PLAN Wave 2 calls for splitting the shared core (the engine-agnostic contract
// layer) away from the engine "stages". The contract primitives the plan names for the `-core`
// are exactly { HaltError, REVIEW_SCHEMA, stamp }. This module IS that `-core` surface for
// researchPrime: it re-exports those three from their SINGLE upstream copy in the trio — never
// a fork — so researchPrime's own code (and the deferred Crucible/Foreman adoption) imports
// them by one canonical specifier (`#trio-core/contract-core`, mapped in package.json) instead
// of scattering `../../foreman/...` / `../../crucible/...` reaches across the tree.
//
// The ONE external dependency stays declared in ONE place: every upstream specifier below is
// resolved against `TRIO_ROOT` from bin/contract.mjs (overridable via RP_TRIO_ROOT for a
// hermetic, version-pinned checkout). Top-level await is used so the re-exported bindings carry
// the real upstream values; if an upstream module moves or renames a symbol, this fails LOUD at
// import (surfaced by the contract / canonical-copy tests), exactly the NO-GO signal Wave 1
// established — never a silent fork.

import { TRIO_ROOT } from '../contract.mjs';

const foremanLib = await import(new URL('foreman/bin/foreman-lib.mjs', TRIO_ROOT));
const waveWorkflow = await import(new URL('foreman/bin/wave-workflow.js', TRIO_ROOT));
const judge = await import(new URL('crucible/bin/judge.mjs', TRIO_ROOT));

function requireSymbol(ns, name, where) {
  const ref = ns[name];
  if (ref === undefined) {
    throw new Error(
      `trio-core contract surface broken: "${name}" is absent from ${where} ` +
        `(upstream moved/renamed it). researchPrime imports — never forks — so this is a ` +
        `NO-GO signal to re-point the specifier, not a license to copy the symbol locally.`,
    );
  }
  return ref;
}

/** HALT-for-human signalling — the single upstream class from foreman-lib (no fork). */
export const HaltError = requireSymbol(foremanLib, 'HaltError', 'foreman/bin/foreman-lib.mjs');

/** Reviewer-output schema — the single upstream value from foreman's wave-workflow. */
export const REVIEW_SCHEMA = requireSymbol(waveWorkflow, 'REVIEW_SCHEMA', 'foreman/bin/wave-workflow.js');

/** Per-role provenance stamp ("stamp") — the single upstream function from crucible's judge. */
export const stampRole = requireSymbol(judge, 'stampRole', 'crucible/bin/judge.mjs');
