/**
 * Form packs as DATA (F4: no hard-code, no schema 2, no migration) — W3.
 *
 * The pack SCHEMA is defined here; every pack is a JSON file under packs/
 * (beat vocabulary, interval coordinate, closed predicate catalog with ONE
 * cardinality per predicate, structural-record template, checklist, doctrine
 * terms with collisions whitelisted, pick-a-side points, value-normaliser
 * rules, source cites by file and heading). The engine reads the project's
 * pack NAME from <root>/chekhov/config.json and NEVER from code — a
 * source-grep gate holds no pack name and no beat vocabulary in lib/.
 *
 * The story-time coordinate is declared by the pack; the implemented algebra
 * is the two-level dotted coordinate (book.chapter): overlap, contains, and
 * an open "scope end". An unknown coordinate is refused, never guessed.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const PACK_SCHEMA = 1;

export class PackError extends Error {
  constructor(code, message) {
    super(message || code);
    this.code = code;
  }
}

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));

/** The skill's own packs/ directory (relative to lib/; overridable in tests). */
export function defaultPacksDir() {
  return path.join(MODULE_DIR, '..', 'packs');
}

export function configPath(root) {
  return path.join(root, 'chekhov', 'config.json');
}

const CARDINALITIES = new Set(['single', 'multi']);
const IMPLEMENTED_COORDINATES = new Set(['book.chapter']);

/** The value-normaliser rule registry. An unknown rule name is refused. */
const NORMALISER_RULES = {
  'case-fold': (v) => v.toLowerCase(),
  'article-strip': (v) => v.replace(/^(the|a|an)\s+/i, ''),
};

/** Validate a full pack (or a stub holding only beat names) against the schema. */
export function validatePack(pack) {
  if (!pack || typeof pack !== 'object') throw new PackError('invalid_pack', 'pack is not an object');
  if (!('schema' in pack)) throw new PackError('unversioned_pack', 'pack has no schema field');
  if (pack.schema !== PACK_SCHEMA) {
    throw new PackError('unknown_pack_schema', `unknown pack schema: ${JSON.stringify(pack.schema)} (known: ${PACK_SCHEMA})`);
  }
  if (typeof pack.name !== 'string' || !pack.name) throw new PackError('invalid_pack', 'pack has no name');

  if (pack.stub === true) {
    // A stub ships only the beat names as data (completed in a later wave).
    if (!Array.isArray(pack.beats) || !pack.beats.length || pack.beats.some((b) => typeof b !== 'string')) {
      throw new PackError('invalid_pack', `stub pack ${pack.name} must hold the beat names`);
    }
    return pack;
  }

  if (typeof pack.coordinate !== 'string') throw new PackError('invalid_pack', `pack ${pack.name}: coordinate missing`);
  if (!IMPLEMENTED_COORDINATES.has(pack.coordinate)) {
    throw new PackError('unknown_coordinate', `pack ${pack.name}: coordinate ${pack.coordinate} is not implemented — refused, never guessed`);
  }

  const table = pack.beat_table;
  if (!table || !Array.isArray(table.per_book) || !table.per_book.length) {
    throw new PackError('invalid_pack', `pack ${pack.name}: beat_table.per_book missing`);
  }
  for (const beat of table.per_book) {
    if (typeof beat.name !== 'string' || typeof beat.structural !== 'boolean') {
      throw new PackError('invalid_pack', `pack ${pack.name}: each beat needs name and structural`);
    }
  }

  const catalog = pack.predicate_catalog;
  if (!catalog || typeof catalog !== 'object' || !Object.keys(catalog).length) {
    throw new PackError('invalid_pack', `pack ${pack.name}: predicate_catalog missing`);
  }
  for (const [pred, spec] of Object.entries(catalog)) {
    if (!spec || !CARDINALITIES.has(spec.cardinality)) {
      throw new PackError('invalid_pack', `pack ${pack.name}: predicate ${pred} needs exactly one cardinality (single|multi)`);
    }
  }

  if (!pack.structural_template || typeof pack.structural_template !== 'object') {
    throw new PackError('invalid_pack', `pack ${pack.name}: structural_template missing`);
  }
  if (!Array.isArray(pack.checklist)) throw new PackError('invalid_pack', `pack ${pack.name}: checklist missing`);
  const dt = pack.doctrine_terms;
  if (!dt || !Array.isArray(dt.terms) || !Array.isArray(dt.collisions_whitelisted)) {
    throw new PackError('invalid_pack', `pack ${pack.name}: doctrine_terms.terms and collisions_whitelisted required`);
  }
  if (!Array.isArray(pack.pick_a_side_points) || !pack.pick_a_side_points.length) {
    throw new PackError('invalid_pack', `pack ${pack.name}: pick_a_side_points missing`);
  }
  if (!Array.isArray(pack.value_normaliser)) {
    throw new PackError('invalid_pack', `pack ${pack.name}: value_normaliser missing`);
  }
  for (const rule of pack.value_normaliser) {
    if (!(rule in NORMALISER_RULES)) {
      throw new PackError('unknown_normaliser_rule', `pack ${pack.name}: unknown value-normaliser rule ${rule}`);
    }
  }
  if (!Array.isArray(pack.sources) || !pack.sources.length || pack.sources.some((s) => !s.file || !s.heading)) {
    throw new PackError('invalid_pack', `pack ${pack.name}: sources must cite by file and heading`);
  }
  return pack;
}

/** Read a pack file by name from a packs dir; validated, never trusted raw. */
export function readPack(name, packsDir = defaultPacksDir()) {
  const file = path.join(packsDir, name, 'pack.json');
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (e) {
    throw new PackError('pack_missing', `pack ${name} not found at ${path.join(name, 'pack.json')}: ${e.code}`);
  }
  let pack;
  try {
    pack = JSON.parse(raw);
  } catch {
    throw new PackError('pack_unreadable', `pack ${name}: pack.json does not parse`);
  }
  return validatePack(pack);
}

/**
 * The ONLY way the engine learns which pack a project uses: the name in
 * <root>/chekhov/config.json. Missing config or missing pack is a refusal.
 */
export function loadProjectPack(root, { packsDir } = {}) {
  let raw;
  try {
    raw = fs.readFileSync(configPath(root), 'utf8');
  } catch (e) {
    throw new PackError('config_missing', `chekhov/config.json not found in root: ${e.code}`);
  }
  let config;
  try {
    config = JSON.parse(raw);
  } catch {
    throw new PackError('config_unreadable', 'chekhov/config.json does not parse');
  }
  if (typeof config.pack !== 'string' || !config.pack) {
    throw new PackError('config_missing', 'chekhov/config.json names no pack');
  }
  return readPack(config.pack, packsDir);
}

// ---------------------------------------------------------------------------
// Interval algebra for the two-level dotted coordinate (book.chapter).
// Timed intervals retain {from,to}; explicit project/unspecified scopes have
// no endpoints. Unspecified never proves overlap or permission. Formal repair0016.
// ---------------------------------------------------------------------------

export function parseCoord(coord) {
  if (typeof coord !== 'string' || !/^\d+\.\d+$/.test(coord)) {
    throw new PackError('invalid_coord', `invalid story-time coordinate: ${JSON.stringify(coord)} (expected book.chapter)`);
  }
  const [book, chapter] = coord.split('.').map(Number);
  return [book, chapter];
}

export function coordCompare(a, b) {
  const [ab, ac] = parseCoord(a);
  const [bb, bc] = parseCoord(b);
  return ab - bb || ac - bc;
}

function endOf(interval) {
  return interval.to === null || interval.to === undefined || interval.to === 'end' ? null : interval.to;
}

export function validateInterval(interval) {
  if (!interval || typeof interval !== 'object' || Array.isArray(interval)) {
    throw new PackError('invalid_interval', `invalid interval: ${JSON.stringify(interval)}`);
  }
  if (Object.hasOwn(interval, 'scope')) {
    if (!['project', 'unspecified'].includes(interval.scope) || Object.keys(interval).length !== 1) {
      throw new PackError('invalid_interval', `invalid explicit scope: ${JSON.stringify(interval)}`);
    }
    return interval;
  }
  if (!interval.from) throw new PackError('invalid_interval', `invalid interval: ${JSON.stringify(interval)}`);
  parseCoord(interval.from);
  const to = endOf(interval);
  if (to !== null && coordCompare(interval.from, to) > 0) {
    throw new PackError('invalid_interval', `interval runs backwards: ${interval.from}..${to}`);
  }
  return interval;
}

export function intervalContainsCoord(interval, coord) {
  validateInterval(interval);
  parseCoord(coord);
  if (interval.scope === 'unspecified') return false;
  if (interval.scope === 'project') return true;
  if (coordCompare(coord, interval.from) < 0) return false;
  const to = endOf(interval);
  return to === null || coordCompare(coord, to) <= 0;
}

export function intervalOverlaps(a, b) {
  validateInterval(a);
  validateInterval(b);
  if (a.scope === 'unspecified' || b.scope === 'unspecified') return false;
  if (a.scope === 'project' || b.scope === 'project') return true;
  const aTo = endOf(a);
  const bTo = endOf(b);
  if (aTo !== null && coordCompare(b.from, aTo) > 0) return false;
  if (bTo !== null && coordCompare(a.from, bTo) > 0) return false;
  return true;
}

/** a contains b: every coordinate of b lies inside a. */
export function intervalContains(a, b) {
  validateInterval(a);
  validateInterval(b);
  if (a.scope === 'unspecified' || b.scope === 'unspecified') return false;
  if (a.scope === 'project') return true;
  if (b.scope === 'project') return false;
  if (coordCompare(b.from, a.from) < 0) return false;
  const aTo = endOf(a);
  const bTo = endOf(b);
  if (aTo === null) return true;
  if (bTo === null) return false;
  return coordCompare(bTo, aTo) <= 0;
}

// ---------------------------------------------------------------------------
// The closed predicate catalog and value comparison.
// ---------------------------------------------------------------------------

export function cardinalityOf(pack, predicate) {
  const spec = pack.predicate_catalog && pack.predicate_catalog[predicate];
  return spec ? spec.cardinality : null;
}

/**
 * Validate a claim {entity, predicate, object} against the CLOSED catalog.
 * An unknown predicate is a refusal — {ok:false, refusal:'unknown_predicate'}
 * — and the caller writes nothing.
 */
export function validateClaim(pack, claim) {
  if (!claim || typeof claim !== 'object' || !claim.entity || !claim.predicate) {
    return { ok: false, refusal: 'invalid_claim' };
  }
  if (!cardinalityOf(pack, claim.predicate)) {
    return { ok: false, refusal: 'unknown_predicate', predicate: claim.predicate };
  }
  return { ok: true };
}

/** Apply the pack's value-normaliser rules (data-named, order as declared). */
export function normaliseValue(pack, value) {
  if (typeof value !== 'string') return value;
  let v = value;
  for (const rule of pack.value_normaliser || []) {
    const fn = NORMALISER_RULES[rule];
    if (!fn) throw new PackError('unknown_normaliser_rule', `unknown value-normaliser rule ${rule}`);
    v = fn(v);
  }
  return v;
}

/**
 * Compare two fact claims under the catalog. Same entity + same predicate +
 * overlapping intervals + single cardinality + different normalised values ⇒
 * a conflict carrying the two RECORDED values. Age is compared as the two
 * recorded ages with their intervals like any other single-valued predicate:
 * no conversion (age vs birth_year is simply not comparable).
 */
export function compareClaims(pack, a, b) {
  if (a.value.entity !== b.value.entity || a.value.predicate !== b.value.predicate) {
    return { comparable: false };
  }
  validateInterval(a.interval);
  validateInterval(b.interval);
  if (a.interval.scope === 'unspecified' || b.interval.scope === 'unspecified') {
    return { comparable: false, reason: 'scope-unspecified' };
  }
  if (!intervalOverlaps(a.interval, b.interval)) {
    return { comparable: true, conflict: false, reason: 'intervals-disjoint' };
  }
  if (cardinalityOf(pack, a.value.predicate) === 'multi') {
    return { comparable: true, conflict: false, reason: 'multi-valued' };
  }
  const av = normaliseValue(pack, a.value.object);
  const bv = normaliseValue(pack, b.value.object);
  if (av === bv) return { comparable: true, conflict: false, reason: 'values-agree' };
  return {
    comparable: true,
    conflict: true,
    entity: a.value.entity,
    predicate: a.value.predicate,
    values: [a.value.object, b.value.object],
    ids: [a.id, b.id],
  };
}
