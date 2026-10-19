/**
 * Portable Trio dependency locations for Ramanujan.
 *
 * These environment variables select an installation location only. They do
 * not select a model, provider family, effort, or any model-preference store.
 * No recursive search, author-machine path, network import, or silent fallback
 * from a broken explicit override is permitted.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SYMBOLS = Object.freeze({
  'trio:claude': 'claude.mjs',
  'trio:chatgpt-cli': 'chatgpt-cli.mjs',
  'trio:grok-cli': 'grok-cli.mjs',
  'trio:gemini-cli': 'gemini-cli.mjs',
  'trio:index': 'index.mjs',
});

export class TrioLocationError extends Error {
  constructor(message, code = 'trio_location_unavailable') {
    super(message);
    this.name = 'TrioLocationError';
    this.code = code;
  }
}

function reject(message, code) {
  throw new TrioLocationError(message, code);
}

function localFileURL(value, { allowModuleQuery = false } = {}) {
  let url;
  try { url = new URL(value); }
  catch { reject('Trio references must be absolute local paths or local file URLs.', 'invalid_trio_reference'); }
  if (url.protocol !== 'file:' || (url.hostname && url.hostname.toLowerCase() !== 'localhost')
      || url.username || url.password || (!allowModuleQuery && (url.search || url.hash))) {
    reject('Trio references must be local file URLs without network hosts, credentials, queries, or fragments.', 'invalid_trio_reference');
  }
  // An import cache-buster does not change installation-relative locations.
  url.search = '';
  url.hash = '';
  return url;
}

function localAbsolutePath(reference) {
  if (typeof reference !== 'string' || !reference || reference.trim() !== reference
      || /[\x00-\x1f\x7f]/.test(reference)) {
    reject('Trio references must be nonempty absolute local paths or local file URLs.', 'invalid_trio_reference');
  }
  let resolved = reference;
  if (/^file:/i.test(reference)) {
    try { resolved = fileURLToPath(localFileURL(reference)); }
    catch (error) {
      if (error instanceof TrioLocationError) throw error;
      reject('The Trio file URL cannot be decoded as a local filesystem path.', 'invalid_trio_reference');
    }
  }
  if (!path.isAbsolute(resolved) || /^[\\/]{2}/.test(resolved)
      || /[\x00-\x1f\x7f]/.test(resolved)) {
    reject('Trio references must be absolute local filesystem paths; relative paths and network shares are not accepted.', 'invalid_trio_reference');
  }
  return path.normalize(resolved);
}

function existingFile(filename) {
  try { return fs.statSync(filename).isFile(); }
  catch { return false; }
}

function probe(filename, exists) {
  let present;
  try { present = exists(filename); }
  catch { reject('The configured Trio installation could not be inspected. Check its location and read permissions.', 'trio_location_unreadable'); }
  if (typeof present !== 'boolean') {
    reject('The Trio location probe must return a synchronous boolean.', 'invalid_trio_probe');
  }
  return present;
}

function optionsFor(options) {
  const exists = options?.exists ?? existingFile;
  if (typeof exists !== 'function') reject('The Trio location probe is unavailable.', 'invalid_trio_probe');
  return { exists, moduleURL: options?.moduleURL ?? import.meta.url };
}

function requireExisting(filename, exists, kind) {
  if (!probe(filename, exists)) {
    reject(
      kind === 'index'
        ? 'The explicit Trio index location does not contain a readable file. Fix RAMANUJAN_TRIO_INDEX, TRIO_DRIVERS_INDEX, or ANCHOR_TRIO_DIR; automatic layouts will not override it.'
        : 'The referenced Trio driver is not installed beside the selected index, or the explicit driver file is missing. Install the complete Trio drivers package or fix the driver reference.',
      kind === 'index' ? 'trio_index_missing' : 'trio_driver_missing',
    );
  }
  return filename;
}

/**
 * Return the absolute index filename. The optional exists/moduleURL arguments
 * support hermetic installation-layout tests; normal callers need only env.
 *
 * Precedence: explicit index overrides, ANCHOR_TRIO_DIR, known source checkout,
 * sibling installed Trio skill, then the shared installed skills-root drivers.
 */
export function resolveTrioIndex(env = process.env, options = {}) {
  if (!env || typeof env !== 'object') reject('Trio installation environment must be an object.', 'invalid_trio_reference');
  const { exists, moduleURL } = optionsFor(options);
  for (const name of ['RAMANUJAN_TRIO_INDEX', 'TRIO_DRIVERS_INDEX']) {
    if (env[name] !== undefined && env[name] !== null) {
      return requireExisting(localAbsolutePath(env[name]), exists, 'index');
    }
  }
  if (env.ANCHOR_TRIO_DIR !== undefined && env.ANCHOR_TRIO_DIR !== null) {
    return requireExisting(path.join(localAbsolutePath(env.ANCHOR_TRIO_DIR), 'drivers', 'index.mjs'), exists, 'index');
  }
  const base = localFileURL(moduleURL, { allowModuleQuery: true });
  const candidates = [...new Set([
    '../../../../trio/drivers/index.mjs',
    '../../trio/drivers/index.mjs',
    '../../drivers/index.mjs',
  ].map(relative => localAbsolutePath(new URL(relative, base).href)))];
  for (const candidate of candidates) {
    if (probe(candidate, exists)) return candidate;
  }
  reject(
    'Trio drivers were not found in the supported installation layouts. Install Trio beside the Foundry skills, or set RAMANUJAN_TRIO_INDEX / TRIO_DRIVERS_INDEX to its index.mjs file or ANCHOR_TRIO_DIR to its package directory.',
    'trio_index_missing',
  );
}

/** Resolve only fixed Trio symbols or legacy explicit local driver filenames. */
export function resolveDriverReference(reference, env = process.env, options = {}) {
  const { exists } = optionsFor(options);
  if (typeof reference === 'string' && reference.startsWith('trio:')) {
    if (!Object.hasOwn(SYMBOLS, reference)) {
      reject('Unsupported Trio driver symbol. Use trio:claude, trio:chatgpt-cli, trio:grok-cli, trio:gemini-cli, or trio:index.', 'invalid_trio_symbol');
    }
    const index = resolveTrioIndex(env, options);
    if (reference === 'trio:index') return index;
    const driver = path.join(path.dirname(index), SYMBOLS[reference]);
    return requireExisting(driver, exists, 'driver');
  }
  // Explicit legacy driver locations remain compatible, but never become
  // relative traversal, a model-family override, or an automatic network import.
  return requireExisting(localAbsolutePath(reference), exists, 'driver');
}
