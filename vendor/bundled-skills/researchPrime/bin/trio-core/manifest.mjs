// bin/trio-core/manifest.mjs — the canonical registry of every SHARED specifier researchPrime
// crosses, plus the resolvers crit-6 ("each imported module resolves to a single canonical
// path") is asserted against.
//
// This module lives in the ROOT package scope (researchPrime-upgrade/package.json), so the
// package `imports` map (`#trio-core/*`) and the package `exports` self-reference
// (`researchprime-upgrade/trio-core/*`) BOTH resolve here. That is the point: the shared
// specifier is resolved via the package map, NOT a `../../` relative reach (IMPLEMENTATION-PLAN
// Wave 2). test/canonical-copy.test.mjs (which sits in a different package scope) calls the
// resolvers below rather than resolving `#`-specifiers itself.

import { fileURLToPath } from 'node:url';
import { realpathSync } from 'node:fs';
import { TRIO_ROOT, TRIO_MODULES } from '../contract.mjs';

// ── The trio-core shared modules researchPrime OWNS (this plan BUILDS them) ──────────────────
// Each row pins the SAME on-disk module by two independent package-map routes — the internal
// `imports` alias and the public `exports` subpath — so the canonical-copy test can prove the
// two routes land on one file (one canonical copy, importable by the deferred adopters via
// `exports`, never forked).
export const TRIO_CORE_MODULES = [
  {
    name: 'independence-accounting',
    importsSpecifier: '#trio-core/independence-accounting.mjs',
    exportsSpecifier: 'researchprime-upgrade/trio-core/independence-accounting',
  },
  {
    name: 'contract-core',
    importsSpecifier: '#trio-core/contract-core.mjs',
    exportsSpecifier: 'researchprime-upgrade/trio-core/contract-core',
  },
];

// ── The upstream trio modules researchPrime IMPORTS (never forks) ────────────────────────────
// Pinned through the single TRIO_ROOT (overridable via RP_TRIO_ROOT) — the one declared external
// dependency. `TRIO_MODULES` is the Wave-1 frozen map (bin/contract.mjs).
export const TRIO_UPSTREAM_MODULES = Object.entries(TRIO_MODULES).map(([name, spec]) => ({ name, spec }));

/** Resolve a specifier (URL string) to its absolute, symlink-resolved on-disk path. */
function toRealPath(resolvedUrl) {
  return realpathSync(fileURLToPath(resolvedUrl));
}

/**
 * Resolve a package-map specifier (`#trio-core/...` or the `researchprime-upgrade/...` export)
 * to a single on-disk path. import.meta.resolve runs in THIS module's (root) package scope.
 * @param {string} specifier
 * @returns {string} absolute realpath
 */
export function resolvePackageSpecifier(specifier) {
  return toRealPath(import.meta.resolve(specifier));
}

/**
 * Resolve an upstream trio specifier (relative to TRIO_ROOT) to a single on-disk path.
 * @param {string} spec  e.g. 'foreman/bin/foreman-lib.mjs'
 * @returns {string} absolute realpath
 */
export function resolveUpstreamSpecifier(spec) {
  return toRealPath(new URL(spec, TRIO_ROOT));
}

/** This repo's root directory (one level up from bin/), realpath-normalized. */
export function repoRoot() {
  return realpathSync(fileURLToPath(new URL('../../', import.meta.url)));
}
