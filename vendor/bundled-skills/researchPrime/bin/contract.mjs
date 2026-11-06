// bin/contract.mjs — Wave 1 frozen contract surface + import GO/NO-GO spike.
//
// researchPrime's upgrade IMPORTS, never forks, the trio's machinery
// (MASTER-PLAN "Architecture"; DESCRIPTION "What is being built"). This module is the
// REAL source that the contract test exercises: it pins the exact on-disk modules and
// the exact SYMBOLS researchPrime crosses out of each one, performs the smoke import
// from researchPrime's own directory, and verifies every crossed symbol is present with
// the expected kind.
//
// GO/NO-GO (IMPLEMENTATION-PLAN Wave 1 / MASTER-PLAN Phase 0): if the smoke import
// succeeds and every crossed symbol resolves, the trio surface is GO and researchPrime
// builds on it directly. If any crossed symbol is missing/renamed, the contract test
// goes RED — that is the NO-GO signal routing to Phase 0.5 (owned trio-core extraction),
// NOT a license to fork. This module is the single source of truth for the crossed-symbol
// list (recorded in human-readable form in CONTRACT-SURFACE.md).

import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

// ── Trio root: the ONE pinned external dependency ─────────────────────────────
// researchPrime imports the trio's LIVE source, which lives OUTSIDE this repo — so that
// location is the single external dependency the contract takes on. Rather than scatter
// five hard-coded `../../` escapes (each an implicit, unpinned reach out of the repo), the
// dependency is pinned in ONE place: TRIO_ROOT. By default it resolves to the sibling tree
// under the shared parent (C:/dev/{crucible,foreman}), relative to this file (bin/), so the
// smoke import still proves the trio loads "from researchPrime/" exactly as Wave 1 requires.
// A hermetic build (CI, a pinned checkout) can override the root via RP_TRIO_ROOT to point
// at an exact, version-pinned copy instead of relying on the ambient sibling layout — the
// non-hermetic default is then a convenience, not a hard-wired assumption.
export const TRIO_ROOT = process.env.RP_TRIO_ROOT
  ? pathToFileURL(path.resolve(process.env.RP_TRIO_ROOT) + path.sep)
  : new URL('../../', import.meta.url);

// ── Module map ───────────────────────────────────────────────────────────────
// Specifiers are resolved RELATIVE TO TRIO_ROOT (above), so changing the pin moves all
// five modules together and the smoke import follows.
export const TRIO_MODULES = {
  'shark-tank': 'crucible/bin/shark-tank.mjs',
  synthesizer: 'crucible/bin/synthesizer.mjs',
  judge: 'crucible/bin/judge.mjs',
  enhanced: 'crucible/bin/enhanced.mjs',
  'foreman-lib': 'foreman/bin/foreman-lib.mjs',
};

// ── Crossed-symbol list (the FROZEN contract surface) ─────────────────────────
// Each entry is a symbol researchPrime's engine depends on, tagged with the kind we
// expect ('function' covers classes too) and the lever/gate it serves so the dependency
// is auditable. Adding a new dependency on the trio = adding it here (and the test then
// guards it). `kind: 'value'` = a non-callable export (a schema/role/registry constant).
export const CROSSED_SYMBOLS = {
  // G3 ≥2-agree heterogeneous reviewers · G5 convergence-until-dry · G6 finding identity
  'shark-tank': [
    { name: 'runSharkTank', kind: 'function', serves: 'G3/G5 multi-round ≥2-agree loop' },
    { name: 'makeSharkDriver', kind: 'function', serves: 'reviewer driver seam' },
    { name: 'tallyFindings', kind: 'function', serves: 'G3 ≥2-agree quorum tally' },
    { name: 'normalizeFindingId', kind: 'function', serves: 'G6 stable finding identity' },
    { name: 'angleForShark', kind: 'function', serves: 'G3 reviewer heterogeneity' },
    { name: 'SHARK_SCHEMA', kind: 'value', serves: 'reviewer output schema' },
    { name: 'SHARK_ROLES', kind: 'value', serves: 'heterogeneous reviewer roster' },
  ],
  // Active Deep-Think Synthesizer (steers, files a separate brief)
  synthesizer: [
    { name: 'makeSynthesizer', kind: 'function', serves: 'active Synthesizer' },
    { name: 'freshEyesColdPass', kind: 'function', serves: 'isolated cold pass' },
    { name: 'reconcileFreshEyes', kind: 'function', serves: 'Synthesizer reconciliation' },
    { name: 'SYNTHESIZER_ROLE', kind: 'value', serves: 'role stamp' },
    { name: 'DIRECTION_SCHEMA', kind: 'value', serves: 'steering output schema' },
  ],
  // G4 separate context-free Judge
  judge: [
    { name: 'makeJudge', kind: 'function', serves: 'G4 separate Judge' },
    { name: 'selectJudgeModel', kind: 'function', serves: 'G4 cross-context selection' },
    { name: 'stampRole', kind: 'function', serves: 'role/provenance stamp' },
    { name: 'JUDGE_ROLE', kind: 'value', serves: 'role stamp' },
    { name: 'JUDGE_SCHEMA', kind: 'value', serves: 'Judge verdict schema' },
  ],
  // Cross-family verification seam (2026-07-05 W6: the API-key Enhanced-mode provisioner —
  // detectAndProvision/provisionRoles/makeCrossModelProbe/selectSynthesizerModel/MODEL_REGISTRY —
  // was RETIRED and replaced by the shared agy-based cross-family seam; the contract now pins that).
  enhanced: [
    { name: 'buildLiveCrucibleAgent', kind: 'function', serves: 'role-routed cross-family agent (Gemini verify / Claude steer)' },
    { name: 'assertCrossFamilyRouting', kind: 'function', serves: 'fail-closed self-review guard' },
    { name: 'makeReachedFamilyTracker', kind: 'function', serves: 'reached-backend substrate attestation' },
  ],
  // Checkpoint/resume · budget pre-flight · HALT signalling
  'foreman-lib': [
    { name: 'HaltError', kind: 'function', serves: 'HALT-for-human signalling' },
    { name: 'makeBudget', kind: 'function', serves: 'budget pre-flight' },
    { name: 'newCheckpoint', kind: 'function', serves: 'checkpoint create' },
    { name: 'readCheckpoint', kind: 'function', serves: 'resume read' },
    { name: 'writeCheckpointAtomic', kind: 'function', serves: 'durable checkpoint write' },
    { name: 'validateCheckpoint', kind: 'function', serves: 'checkpoint integrity' },
  ],
};

// Resolve a module specifier against the pinned trio root (so resolution tracks the pin).
function resolveSpec(spec) {
  return new URL(spec, TRIO_ROOT);
}

/**
 * Smoke-import every trio module from researchPrime's directory.
 * @returns {Promise<Record<string, object>>} map of module key → its namespace object.
 * Rejects (propagating the loader error) if any module fails to load — that rejection IS
 * the NO-GO signal the contract test surfaces.
 */
export async function importTrioSurface() {
  const surface = {};
  for (const [key, spec] of Object.entries(TRIO_MODULES)) {
    surface[key] = await import(resolveSpec(spec));
  }
  return surface;
}

/**
 * Verify the imported surface against the frozen crossed-symbol list.
 * @param {Record<string, object>} surface output of importTrioSurface()
 * @returns {{ ok: boolean, missing: Array<{module:string,name:string,kind:string,reason:string}> }}
 * `missing` is empty on GO; each entry is a renamed/dropped/mis-kinded symbol on NO-GO.
 */
export function verifyContractSurface(surface) {
  const missing = [];
  for (const [mod, symbols] of Object.entries(CROSSED_SYMBOLS)) {
    const ns = surface[mod];
    if (!ns) {
      missing.push({ module: mod, name: '*', kind: 'namespace', reason: 'module did not import' });
      continue;
    }
    for (const { name, kind } of symbols) {
      if (!(name in ns) || ns[name] === undefined) {
        missing.push({ module: mod, name, kind, reason: 'symbol absent' });
        continue;
      }
      // Strict, symmetric kind check. 'function' must be callable; 'value' must be a
      // present, non-callable export ('function' covers classes too, so a class tagged
      // 'value' is correctly rejected, and a null export is not a real value). An unknown
      // declared kind is a bug in CROSSED_SYMBOLS itself — fail loudly rather than let a
      // typo'd kind ('values', 'val', …) silently pass every check.
      const actual = ns[name] === null ? 'null' : typeof ns[name];
      if (kind === 'function') {
        if (actual !== 'function') {
          missing.push({ module: mod, name, kind, reason: `expected function, got ${actual}` });
        }
      } else if (kind === 'value') {
        if (actual === 'function' || actual === 'null') {
          missing.push({ module: mod, name, kind, reason: `expected value, got ${actual}` });
        }
      } else {
        missing.push({ module: mod, name, kind, reason: `unknown declared kind: ${kind}` });
      }
    }
  }
  return { ok: missing.length === 0, missing };
}

/**
 * Run the full GO/NO-GO spike: import + verify. Returns a structured verdict.
 * @returns {Promise<{ go: boolean, modules: string[], crossedCount: number, missing: object[] }>}
 */
export async function runImportSpike() {
  const surface = await importTrioSurface();
  const { ok, missing } = verifyContractSurface(surface);
  const crossedCount = Object.values(CROSSED_SYMBOLS).reduce((n, s) => n + s.length, 0);
  return { go: ok, modules: Object.keys(TRIO_MODULES), crossedCount, missing };
}

// Convenience for human inspection / CLI: `node bin/contract.mjs`.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const verdict = await runImportSpike();
  console.log(JSON.stringify(verdict, null, 2));
  process.exit(verdict.go ? 0 : 1);
}
