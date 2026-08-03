// Wave 13 — No-inline-reimplementation BOUNDARY CANARY (B3).
//
// NS8 has a boundary that THE HONESTY LAW depends on: Ramanujan COMPOSES researchPrime / Gandalf, it
// never re-implements them. A re-implementation is not merely redundant — it is a laundering surface
// (a self-authored "research"/"situate" object could mint independent-origin credit that the
// inherited seam would refuse). This canary is the TRIPWIRE that keeps the composition boundary real.
//
// It checks the boundary TWO independent ways, and the done-when requires BOTH to fire on a violation:
//
//   (1) IMPORT-GRAPH. Each declared BOUNDARY TARGET (the modules that exist solely to compose the
//       inherited research/situate seam — src/commission-emitters.mjs) MUST carry a static import
//       EDGE resolving to the manifest-pinned `gandalf-commission-seam` path. A module that purports
//       to commission research but imports no inherited seam is reimplementing it inline.
//
//   (2) FORBIDDEN-SYMBOL. NO module under src/ may locally DEFINE a seam-owned function
//       (commissionResearchPrime / composeSituate / … ) or a researchPrime-engine identifier. A
//       LOCAL DEFINITION (`function X` / `const X =` / `class X`) of such a symbol IS an inline
//       reimplementation. Importing or re-exporting the inherited symbol is fine and never flagged.
//
// GREEN on the genuine spine; on the planted inline reimplementation (ctx.plant === 'inline-reimpl'
// — a module that defines its own commissionResearchPrime/composeSituate and imports no seam) BOTH
// arms trip and the build fails (non-zero). Runs under `node --test test/` and as a CLI.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadManifest, resolveEntryPath, DEFAULT_MANIFEST_PATH } from './inherits-gate.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC_DIR = __dirname;

/** This wave's single canary name (kept as a list to mirror the Wave-6/12 suite shape). */
export const BOUNDARY_CANARY_NAMES = Object.freeze(['no-inline-boundary']);

/** Logical name of the inherited seam in inherits.manifest.json (the import-graph anchor). */
export const INHERITED_SEAM_LOGICAL_NAME = 'gandalf-commission-seam';

/** The modules REQUIRED to carry an import edge to the inherited seam (NS8 composition surface). */
export const BOUNDARY_TARGETS = Object.freeze(['commission-emitters.mjs']);

/** Seam-owned symbols whose LOCAL DEFINITION signals an inline reimplementation of the inherited
 *  Gandalf/researchPrime commission seam. (Importing / re-exporting these is allowed.) */
export const FORBIDDEN_INLINE_SYMBOLS = Object.freeze([
  'commissionResearchPrime',
  'composeSituate',
  'independentOriginCredit',
  'needsVerificationHandoff',
  'shouldFireSituate',
  'abstractEffort',
  'isWellFormedStructureMap',
]);

/** Path to the planted inline-reimplementation fixture. It lives under test/fixtures as a `.txt`
 *  (so it is NEVER imported, run, or scanned as a src module — the repo-wide forbidden-symbol scan
 *  stays fully un-exempted, including this canary's own module). The canary reads it as source text. */
export const PLANTED_INLINE_REIMPL_PATH = path.join(
  __dirname, '..', 'test', 'fixtures', 'inline-reimpl-commission.fixture.txt',
);

/** The planted inline reimplementation (NS8 violation): it re-defines the seam-owned commission
 *  functions INSTEAD of importing the inherited seam — and even self-CORROBORATES, the laundering
 *  the boundary forbids. Used by the ctx.plant === 'inline-reimpl' arm to prove the canary trips. */
export const PLANTED_INLINE_REIMPL = fs.readFileSync(PLANTED_INLINE_REIMPL_PATH, 'utf8');

// ---------------------------------------------------------------------------
// Assertion helper — mirrors the Wave-6/12 canary shape exactly.
// ---------------------------------------------------------------------------

function A(name, ok, detail) {
  return { name, ok: Boolean(ok), detail: ok ? undefined : detail };
}

function summarize(name, assertions) {
  const failures = assertions
    .filter((a) => !a.ok)
    .map((a) => `${a.name}${a.detail ? `: ${a.detail}` : ''}`);
  return { name, ok: failures.length === 0, assertions, failures };
}

// ---------------------------------------------------------------------------
// Static import-graph extraction + forbidden-definition detection (source scan).
// ---------------------------------------------------------------------------

/**
 * Extract the static module specifiers `source` imports / re-exports from. Covers `import … from
 * 'x'`, `export … from 'x'`, and bare `import 'x'`. Dynamic `import(...)` is intentionally NOT an
 * edge for the boundary's import-graph arm: a composition boundary must be a STATIC, analyzable edge.
 */
export function extractStaticImports(source) {
  const specs = [];
  const fromRe = /\b(?:import|export)\b[^;]*?\bfrom\s*['"]([^'"]+)['"]/g;
  const bareRe = /\bimport\s*['"]([^'"]+)['"]/g;
  let m;
  while ((m = fromRe.exec(source)) !== null) specs.push(m[1]);
  while ((m = bareRe.exec(source)) !== null) specs.push(m[1]);
  return specs;
}

/**
 * Find which of `symbols` are LOCALLY DEFINED in `source` (an inline reimplementation). A definition
 * is a binding declaration — `function NAME` (incl. async/generator), `const|let|var NAME =`, or
 * `class NAME`. A property access (`seam.NAME`), a named import (`import { NAME }`), and a re-export
 * (`export { NAME } from …`) are NOT definitions and are never flagged.
 */
export function findInlineDefinitions(source, symbols = FORBIDDEN_INLINE_SYMBOLS) {
  const hits = [];
  for (const name of symbols) {
    const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const def = new RegExp(
      `(?:^|[^.\\w])(?:export\\s+)?(?:default\\s+)?` +
        `(?:async\\s+)?function\\s*\\*?\\s+${esc}\\b` + // function / async / generator
        `|(?:^|[^.\\w])(?:export\\s+)?(?:const|let|var)\\s+${esc}\\b\\s*=` + // const/let/var binding
        `|(?:^|[^.\\w])(?:export\\s+)?class\\s+${esc}\\b`, // class
      'm',
    );
    if (def.test(source)) hits.push(name);
  }
  return hits;
}

/**
 * Check one boundary target's source against the boundary.
 *
 * @param {{source:string, modulePath:string, seamAbsPath:string, requireSeamImport?:boolean}} o
 * @returns frozen { modulePath, importedSpecifiers, importsSeam, forbiddenDefs, ok }
 */
export function checkBoundaryModule({ source, modulePath, seamAbsPath, requireSeamImport = true }) {
  const specs = extractStaticImports(source);
  const moduleDir = path.dirname(modulePath);
  const resolved = specs
    .filter((s) => s.startsWith('.')) // only relative specifiers can resolve to a repo path
    .map((s) => path.resolve(moduleDir, s));
  const importsSeam = resolved.some((r) => path.resolve(r) === path.resolve(seamAbsPath));
  const forbiddenDefs = findInlineDefinitions(source);
  const ok = (requireSeamImport ? importsSeam : true) && forbiddenDefs.length === 0;
  return Object.freeze({
    modulePath,
    importedSpecifiers: Object.freeze(specs),
    importsSeam,
    forbiddenDefs: Object.freeze(forbiddenDefs),
    ok,
  });
}

/** List the .mjs modules under src/ (the repo-wide forbidden-symbol scan domain). */
function listSrcModules() {
  return fs
    .readdirSync(SRC_DIR)
    .filter((f) => f.endsWith('.mjs'))
    .map((f) => path.join(SRC_DIR, f));
}

// ===========================================================================
// THE NO-INLINE BOUNDARY CANARY.
// ===========================================================================

/**
 * Run the boundary canary. GREEN on the genuine spine; trips (both arms) on the planted inline
 * reimplementation (ctx.plant === 'inline-reimpl').
 *
 * @param {{plant?: 'inline-reimpl', manifestPath?: string}} [ctx]
 * @returns { name, ok, assertions, failures }
 */
export function canaryNoInlineBoundary(ctx = {}) {
  const plant = ctx.plant;
  const assertions = [];

  // Resolve the inherited seam's absolute path from the manifest (single source of truth).
  const manifestPath = ctx.manifestPath || DEFAULT_MANIFEST_PATH;
  const manifest = loadManifest(manifestPath);
  const seamEntry = manifest.entries.find((e) => e.logical_name === INHERITED_SEAM_LOGICAL_NAME);
  const seamAbsPath = seamEntry ? resolveEntryPath(manifestPath, seamEntry) : null;

  assertions.push(A(
    'manifest pins the inherited gandalf-commission-seam (the import-graph anchor exists)',
    Boolean(seamEntry) && Boolean(seamAbsPath) && fs.existsSync(seamAbsPath),
    `gandalf-commission-seam unresolved in the manifest (entry=${Boolean(seamEntry)}, path=${seamAbsPath})`,
  ));

  // -------------------------------------------------------------------------
  // (1) GENUINE: each declared boundary target imports the seam AND declares no inline reimpl.
  // -------------------------------------------------------------------------
  for (const rel of BOUNDARY_TARGETS) {
    const modulePath = path.join(SRC_DIR, rel);
    const source = fs.readFileSync(modulePath, 'utf8');
    const r = checkBoundaryModule({ source, modulePath, seamAbsPath });

    assertions.push(A(
      `genuine: boundary target ${rel} carries a static import EDGE to the inherited seam (import-graph)`,
      r.importsSeam,
      `${rel} does not statically import ${seamAbsPath}; imports=${JSON.stringify(r.importedSpecifiers)}`,
    ));
    assertions.push(A(
      `genuine: boundary target ${rel} declares NO inline reimplementation of a seam-owned symbol (forbidden-symbol)`,
      r.forbiddenDefs.length === 0,
      `${rel} locally defines seam-owned symbol(s): ${JSON.stringify(r.forbiddenDefs)}`,
    ));
  }

  // -------------------------------------------------------------------------
  // (2) REPO-WIDE: no src module locally defines a seam-owned symbol (forbidden-symbol, everywhere).
  // -------------------------------------------------------------------------
  for (const modulePath of listSrcModules()) {
    const rel = path.basename(modulePath);
    const source = fs.readFileSync(modulePath, 'utf8');
    const defs = findInlineDefinitions(source);
    assertions.push(A(
      `repo-wide: ${rel} inline-reimplements no seam-owned symbol`,
      defs.length === 0,
      `${rel} locally defines seam-owned symbol(s): ${JSON.stringify(defs)} (import the inherited seam instead)`,
    ));
  }

  // -------------------------------------------------------------------------
  // (3) PLANTED inline reimplementation — added as a boundary target. BOTH arms must reject it, so
  //     the canary trips (the done-when: fails the build via import-graph + forbidden-symbol).
  // -------------------------------------------------------------------------
  if (plant === 'inline-reimpl') {
    const plantedPath = path.join(SRC_DIR, 'contextualize-inline-reimpl.PLANTED.mjs');
    const r = checkBoundaryModule({ source: PLANTED_INLINE_REIMPL, modulePath: plantedPath, seamAbsPath });

    // import-graph arm: the planted module imports NO seam => it must be rejected here.
    assertions.push(A(
      'planted: an inline reimplementation carries a static import EDGE to the inherited seam (import-graph)',
      r.importsSeam,
      'planted inline reimplementation imports no inherited seam (import-graph arm correctly has no edge to assert)',
    ));
    // forbidden-symbol arm: the planted module DEFINES seam-owned symbols => it must be rejected here.
    assertions.push(A(
      'planted: an inline reimplementation declares NO inline reimplementation of a seam-owned symbol (forbidden-symbol)',
      r.forbiddenDefs.length === 0,
      `planted inline reimplementation locally defines seam-owned symbol(s): ${JSON.stringify(r.forbiddenDefs)}`,
    ));
  }

  return summarize('no-inline-boundary', assertions);
}

// ---------------------------------------------------------------------------
// The (single-canary) suite + exit code, mirroring the Wave-6/12 runner contract.
// ---------------------------------------------------------------------------

/**
 * Run the boundary-canary suite (clean by default).
 * @param {{plant?: 'inline-reimpl', manifestPath?: string}} [ctx]
 * @returns { ok, canaries:[{name, ok, assertions, failures}], failures:[ "no-inline-boundary: …" ] }
 */
export function runNoInlineBoundaryCanary(ctx = {}) {
  const result = canaryNoInlineBoundary(ctx);
  return {
    ok: result.ok,
    canaries: [result],
    failures: result.failures.map((f) => `no-inline-boundary: ${f}`),
  };
}

/** Map a suite result to a process exit code (0 = green, non-zero on a tripped canary). */
export function boundaryCanaryExitCode(result) {
  return result.ok ? 0 : 1;
}

// ---------------------------------------------------------------------------
// CLI: `node src/boundary-canary.mjs` — exit 0 green / 1 on a tripped canary.
// ---------------------------------------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = runNoInlineBoundaryCanary();
  if (result.ok) {
    const a = result.canaries.reduce((s, c) => s + c.assertions.length, 0);
    console.log(`OK: no-inline boundary canary green (${a} pinned assertions).`);
    process.exit(0);
  } else {
    console.error('FAIL: no-inline boundary canary tripped:');
    for (const f of result.failures) console.error(`  - ${f}`);
    process.exit(1);
  }
}
