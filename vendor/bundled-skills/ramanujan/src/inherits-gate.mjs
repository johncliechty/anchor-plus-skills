// Wave 2 — Inheritance presence/interface gate (A0.5a).
//
// Ramanujan COMPOSES inherited modules (Phase-0 handoff/journal/sleep + the atomic
// durability substrate they persist through; the Gandalf v1 commission seam; the three
// research dive engines) — it never reimplements them (NS8). Nothing downstream may
// build on an inherited seam that has silently moved, been version-bumped, or changed
// its export shape. This gate is the Phase-A entry check that the Stage-1 Shark demanded:
// it reads inherits.manifest.json, then for EVERY entry it
//   (1) RESOLVES the path,
//   (2) VERSION-checks it (against the owning package.json, when a semver is pinned),
//   (3) interface-SHAPE-checks it (named exports + their types for modules; required
//       top-level keys for JSON artifacts),
// and FAILS FAST (non-zero), naming the offending logical_name, on any mismatch.
//
// It then ROUND-TRIPS a counter/spent-nonce value through the durability-substrate entry
// across a SIMULATED RELOAD (write -> drop in-memory state -> fresh read from disk), so a
// later wave's across-restart replay test cannot pass against an in-memory stub: the
// substrate is proven to persist to disk here.
//
// Dependency-free (node built-ins only) so it runs on a fresh checkout via `node --test test/`
// and as a CLI.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Default manifest location (repo root, one level up from src/). */
export const DEFAULT_MANIFEST_PATH = path.join(__dirname, '..', 'inherits.manifest.json');

/** The role marker on the manifest entry the durability round-trip exercises. */
export const DURABILITY_ROLE = 'durability-substrate';

// ---------------------------------------------------------------------------
// Manifest loading + path/version resolution helpers.
// ---------------------------------------------------------------------------

/** Read + parse the manifest. Throws (with a clear message) on missing/invalid JSON. */
export function loadManifest(manifestPath = DEFAULT_MANIFEST_PATH) {
  let raw;
  try {
    raw = fs.readFileSync(manifestPath, 'utf8');
  } catch (e) {
    throw new Error(`inherits manifest unreadable at ${manifestPath}: ${e.message}`);
  }
  let obj;
  try {
    obj = JSON.parse(raw);
  } catch (e) {
    throw new Error(`inherits manifest is not valid JSON (${manifestPath}): ${e.message}`);
  }
  if (!obj || typeof obj !== 'object' || !Array.isArray(obj.entries)) {
    throw new Error(`inherits manifest must be an object with an "entries" array (${manifestPath})`);
  }
  return obj;
}

/** Absolute path of an entry, resolved RELATIVE TO THE MANIFEST FILE. */
export function resolveEntryPath(manifestPath, entry) {
  return path.resolve(path.dirname(manifestPath), entry.path);
}

/**
 * Walk up from `startDir` looking for the nearest package.json; return its `version`
 * string (or null if no package.json with a version is found before the filesystem root).
 */
export function findPackageVersion(startDir) {
  let dir = startDir;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const pkgPath = path.join(dir, 'package.json');
    if (fs.existsSync(pkgPath)) {
      try {
        const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
        if (typeof pkg.version === 'string') return pkg.version;
      } catch {
        // unreadable/invalid package.json — keep walking up
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) return null; // hit the filesystem root
    dir = parent;
  }
}

/** typeof-with-array-distinction, matching the manifest's `type` vocabulary. */
function shapeOf(value) {
  if (Array.isArray(value)) return 'array';
  if (value === null) return 'null';
  return typeof value;
}

// ---------------------------------------------------------------------------
// Per-entry check: resolve -> version -> interface shape.
// ---------------------------------------------------------------------------

/**
 * Check a single manifest entry. Returns { logical_name, kind, ok, failures, resolvedPath,
 * exports? }. `failures` is a list of human-readable reasons (empty iff ok). `exports` (for
 * a successfully-imported module) is the live module namespace, so callers (e.g. the
 * durability round-trip) can reuse the resolved seam without importing it twice.
 */
export async function checkEntry(manifestPath, entry) {
  const logical_name = entry.logical_name || '(unnamed entry)';
  const failures = [];
  const resolvedPath = resolveEntryPath(manifestPath, entry);

  // (1) RESOLVE.
  if (!fs.existsSync(resolvedPath)) {
    failures.push(`unresolvable path: ${entry.path} -> ${resolvedPath} (does not exist)`);
    return { logical_name, kind: entry.kind, ok: false, failures, resolvedPath };
  }

  let moduleNs = null;

  if (entry.kind === 'module') {
    // Import once (file:// URL so Windows absolute paths with spaces/backslashes load).
    try {
      moduleNs = await import(pathToFileURL(resolvedPath).href);
    } catch (e) {
      failures.push(`failed to import module: ${e.message}`);
      return { logical_name, kind: entry.kind, ok: false, failures, resolvedPath };
    }
    // (3) interface SHAPE — every declared export must exist with the declared type.
    for (const exp of entry.exports || []) {
      if (!(exp.name in moduleNs)) {
        failures.push(`missing export: ${exp.name}`);
        continue;
      }
      if (exp.type) {
        const actual = shapeOf(moduleNs[exp.name]);
        if (actual !== exp.type) {
          failures.push(`export ${exp.name} has wrong shape: expected ${exp.type}, got ${actual}`);
        }
      }
    }
  } else if (entry.kind === 'json') {
    let parsed;
    try {
      parsed = JSON.parse(fs.readFileSync(resolvedPath, 'utf8'));
    } catch (e) {
      failures.push(`failed to read/parse JSON artifact: ${e.message}`);
      return { logical_name, kind: entry.kind, ok: false, failures, resolvedPath };
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      failures.push('JSON artifact is not a top-level object');
    } else {
      for (const key of entry.keys || []) {
        if (!(key.name in parsed)) failures.push(`missing key: ${key.name}`);
        else if (key.type) {
          const actual = shapeOf(parsed[key.name]);
          if (actual !== key.type) {
            failures.push(`key ${key.name} has wrong shape: expected ${key.type}, got ${actual}`);
          }
        }
      }
    }
  } else {
    failures.push(`unknown entry kind: ${JSON.stringify(entry.kind)} (expected "module" or "json")`);
  }

  // (2) VERSION — pinned semver must match the owning package.json's version.
  const v = entry.version || { from: 'none' };
  if (v.from === 'packageJson') {
    const actual = findPackageVersion(path.dirname(resolvedPath));
    if (actual === null) {
      failures.push('version check failed: no owning package.json with a version was found');
    } else if (actual !== v.expected) {
      failures.push(`version mismatch: expected ${v.expected}, got ${actual}`);
    }
  } else if (v.from === 'none' || v.from === undefined) {
    // No semver pinned for this inherited artifact (no upstream package.json / version
    // export). Path + interface shape are still enforced above.
  } else {
    failures.push(`unknown version.from: ${JSON.stringify(v.from)}`);
  }

  return {
    logical_name,
    kind: entry.kind,
    ok: failures.length === 0,
    failures,
    resolvedPath,
    exports: moduleNs,
  };
}

// ---------------------------------------------------------------------------
// Durability round-trip: prove the inherited substrate persists to disk.
// ---------------------------------------------------------------------------

/**
 * Round-trip a counter + spent-nonce set THROUGH the inherited durability substrate,
 * simulating two process restarts (each "process" reloads ONLY from disk, holding no
 * in-memory state from the previous one). Returns a structured result; `ok` is true iff
 * the value survived the first reload intact AND a monotone bump survived a second reload.
 *
 * The nonce state is parked on a schema-valid Foreman checkpoint (extra fields are
 * preserved by the atomic writer/validating reader) — this REUSES the inherited store,
 * it does not introduce a new one (P9 "reuse, no new store").
 */
export function roundTripDurability(substrate, dir) {
  for (const fn of ['newCheckpoint', 'writeCheckpointAtomic', 'readCheckpoint']) {
    if (typeof substrate[fn] !== 'function') {
      return { ok: false, reason: `durability substrate is missing ${fn}()` };
    }
  }
  const file = path.join(dir, 'ramanujan-nonce-store.checkpoint.json');

  // --- process A: mint + persist an initial counter/spent value ---
  const a = substrate.newCheckpoint({ plan_path: file, total_waves: 1 });
  a.nonce_state = { counter: 41, spent: ['nonce:claimX:dom:0001'] };
  substrate.writeCheckpointAtomic(file, a);

  // --- process B (simulated restart): reload ONLY from disk ---
  const b = substrate.readCheckpoint(file);
  const intact =
    !!b.nonce_state &&
    b.nonce_state.counter === 41 &&
    Array.isArray(b.nonce_state.spent) &&
    b.nonce_state.spent.includes('nonce:claimX:dom:0001');

  // issue the next nonce: monotone bump + record spent, then persist again
  b.nonce_state.counter += 1;
  b.nonce_state.spent.push('nonce:claimX:dom:0002');
  substrate.writeCheckpointAtomic(file, b);

  // --- process C (second simulated restart): reload again ---
  const c = substrate.readCheckpoint(file);
  const monotone =
    !!c.nonce_state &&
    c.nonce_state.counter === 42 &&
    Array.isArray(c.nonce_state.spent) &&
    c.nonce_state.spent.length === 2 &&
    c.nonce_state.spent.includes('nonce:claimX:dom:0002');

  return {
    ok: Boolean(intact && monotone),
    intact,
    monotone,
    file,
    reloaded_counter: c.nonce_state ? c.nonce_state.counter : null,
    reloaded_spent: c.nonce_state ? c.nonce_state.spent : null,
  };
}

// ---------------------------------------------------------------------------
// The whole gate.
// ---------------------------------------------------------------------------

/**
 * Run the full A0.5a gate against `manifestPath`. Resolves/version/shape-checks every
 * entry, then round-trips the durability substrate across a simulated reload in `tmpDir`
 * (a caller-supplied scratch dir; one is created under os.tmpdir() if omitted).
 *
 * Returns { ok, entries:[...], durability:{...}, failures:[...] }. `ok` is true iff every
 * entry passed AND the durability round-trip succeeded. `failures` is a flat list of
 * "logical_name: reason" strings (so a non-zero exit can name every offender at once).
 */
export async function runGate(manifestPath = DEFAULT_MANIFEST_PATH, { tmpDir } = {}) {
  const failures = [];
  let manifest;
  try {
    manifest = loadManifest(manifestPath);
  } catch (e) {
    return { ok: false, entries: [], durability: null, failures: [`manifest: ${e.message}`] };
  }

  const entries = [];
  let durabilityExports = null;
  for (const entry of manifest.entries) {
    const result = await checkEntry(manifestPath, entry);
    entries.push(result);
    for (const f of result.failures) failures.push(`${result.logical_name}: ${f}`);
    if (entry.role === DURABILITY_ROLE && result.ok) durabilityExports = result.exports;
  }

  // Durability round-trip (the done-when's second arm).
  let durability = null;
  const durabilityEntry = manifest.entries.find((e) => e.role === DURABILITY_ROLE);
  if (!durabilityEntry) {
    failures.push(`(manifest): no entry marked role="${DURABILITY_ROLE}" — cannot round-trip durability`);
  } else if (!durabilityExports) {
    // its own entry already failed; the round-trip can't run, but don't double-report.
    durability = { ok: false, reason: 'durability-substrate entry did not resolve/shape-check' };
  } else {
    let scratch = tmpDir;
    let createdScratch = false;
    if (!scratch) {
      scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w2-'));
      createdScratch = true;
    }
    try {
      durability = roundTripDurability(durabilityExports, scratch);
    } catch (e) {
      durability = { ok: false, reason: `durability round-trip threw: ${e.message}` };
    } finally {
      if (createdScratch) {
        try { fs.rmSync(scratch, { recursive: true, force: true }); } catch { /* best-effort */ }
      }
    }
    if (!durability.ok) {
      failures.push(`${durabilityEntry.logical_name}: durability round-trip failed (${durability.reason || JSON.stringify(durability)})`);
    }
  }

  return { ok: failures.length === 0, entries, durability, failures };
}

/** Map a gate result to a process exit code (0 = green, 1 = any failure). */
export function verdictExitCode(result) {
  return result.ok ? 0 : 1;
}

// ---------------------------------------------------------------------------
// CLI: `node src/inherits-gate.mjs [manifestPath]` — exit 0 green, non-zero on any failure.
// ---------------------------------------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const manifestPath = process.argv[2] ? path.resolve(process.argv[2]) : DEFAULT_MANIFEST_PATH;
  const result = await runGate(manifestPath);
  if (result.ok) {
    console.log(
      `OK: ${result.entries.length} inherited entr${result.entries.length === 1 ? 'y' : 'ies'} resolve + version + interface-shape check; ` +
      `durability round-trips (counter ${result.durability.reloaded_counter}, ${result.durability.reloaded_spent.length} spent nonces).`,
    );
    process.exit(0);
  } else {
    console.error('FAIL: inheritance gate found problems:');
    for (const f of result.failures) console.error(`  - ${f}`);
    process.exit(1);
  }
}
