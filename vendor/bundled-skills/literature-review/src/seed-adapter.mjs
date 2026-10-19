// src/seed-adapter.mjs — Wave 10: the CLI boundary adapter that normalizes every seed
// input form — a scalar --seed, repeated --seed, and a --seed-list JSON file — into
// ONE canonical seed list, with STRICT identifier validation applied HERE, before any
// child-process handoff (the mandatory Wave-6 checkpoint: a malformed identifier is
// rejected with a named reason and contributes nothing downstream).
//
// Division of labor (pinned):
//   - classifySeedSpec does CLASSIFICATION ONLY — it decides which identifier slot a
//     spec string names (doi / pmid / arxiv / title). Its inline patterns mirror the
//     shared strict formats but are NOT the validation;
//   - the SHARED trio module (trio-shared/brownfield-intake/seedIdentity.mjs) does the
//     STRICT validation and normalization, under the pinned precedence DOI -> PMID ->
//     arXiv-id -> normalized-title-hash with NO silent fallthrough (a supplied-but-
//     malformed higher-precedence identifier rejects the seed; it never degrades).
//
// Spec-string grammar (snapshot-frozen by test/seed-dedupe-determinism.test.mjs):
//   doi:<id>[|<title>]     pmid:<id>[|<title>]     arxiv:<id>[|<title>]
//   title:<title>                                  (everything after the prefix)
//   https://doi.org/<id>[|<title>]                 https://arxiv.org/abs/<id>[|<title>]
//   bare 10.NNNN/suffix -> doi;  bare 1-8 digits -> pmid;  bare arXiv id -> arxiv;
//   anything else       -> a title-only seed (identity = normalized-title-hash).
// A seed given without a |title carries its identifier string as its display title.
// Legacy `--seed <pdf-url>` inputs (any other http(s) URL) are REJECTED by name —
// Wave 10 replaced the single pdf-url seed with identifier seeds.

import fs from 'node:fs';

import { loadSharedSeedIdentity } from './seed-identity.mjs';

export const SEED_ADAPTER_VERSION = 'litreview-seed-adapter/1';

// Classification patterns (classification only — strict validation is the shared module's).
const BARE_DOI = /^10\.\d{4,9}\/\S+$/;
const BARE_PMID = /^[1-9]\d{0,7}$/;
const BARE_ARXIV = /^(\d{4}\.\d{4,5}(v\d+)?|[a-z]+(?:[.-][a-z]+)*\/\d{7}(v\d+)?)$/i;
const DOI_URL = /^https?:\/\/(dx\.)?doi\.org\//i;
const ARXIV_URL = /^https?:\/\/arxiv\.org\/abs\//i;
const ANY_URL = /^https?:\/\//i;

/**
 * Classify ONE seed spec string into the raw identifier-slot object the shared
 * deriveSeedIdentity consumes ({ doi? | pmid? | arxiv? | title }). Total: returns
 * pass/fail, never throws on bad data.
 *
 * @param {string} spec
 * @returns {{ ok: true, raw: { doi?: string, pmid?: string, arxiv?: string, title: string } }
 *   | { ok: false, reason: string }}
 */
export function classifySeedSpec(spec) {
  if (typeof spec !== 'string' || spec.trim() === '') {
    return { ok: false, reason: 'seed spec must be a non-empty string' };
  }
  const trimmed = spec.trim();

  // `title:` first, against the FULL spec — a title may legitimately contain '|'.
  if (trimmed.toLowerCase().startsWith('title:')) {
    const title = trimmed.slice('title:'.length).trim();
    if (title === '') return { ok: false, reason: `seed spec "${spec}" has an empty title` };
    return { ok: true, raw: { title } };
  }

  const pipe = trimmed.indexOf('|');
  const head = (pipe === -1 ? trimmed : trimmed.slice(0, pipe)).trim();
  const titlePart = pipe === -1 ? null : trimmed.slice(pipe + 1).trim() || null;
  const title = titlePart ?? head;
  const lower = head.toLowerCase();

  if (lower.startsWith('doi:')) return { ok: true, raw: { doi: head.slice(4).trim(), title } };
  if (lower.startsWith('pmid:')) return { ok: true, raw: { pmid: head.slice(5).trim(), title } };
  if (lower.startsWith('arxiv:')) return { ok: true, raw: { arxiv: head.slice(6).trim(), title } };
  if (DOI_URL.test(head)) return { ok: true, raw: { doi: head, title } };
  if (ARXIV_URL.test(head)) return { ok: true, raw: { arxiv: head, title } };
  if (ANY_URL.test(head)) {
    return {
      ok: false,
      reason:
        `seed spec "${spec}" is a URL that names no identifier — the single --seed <pdf-url> ` +
        'path was REPLACED in Wave 10 by identifier seeds; supply doi:/pmid:/arxiv:/title: ' +
        '(or a doi.org / arxiv.org/abs identifier URL)',
    };
  }
  if (BARE_DOI.test(head)) return { ok: true, raw: { doi: head, title } };
  if (BARE_PMID.test(head)) return { ok: true, raw: { pmid: head, title } };
  if (BARE_ARXIV.test(head)) return { ok: true, raw: { arxiv: head, title } };

  // No identifier recognized anywhere: the ENTIRE spec is a title-only seed.
  return { ok: true, raw: { title: trimmed } };
}

/**
 * Normalize EVERY CLI seed input form into ONE canonical, strictly-validated seed
 * list: repeated/scalar --seed spec strings first (in argv order), then --seed-list
 * entries (in file order). Every malformed input lands in `rejected` with a named
 * reason and is never forwarded — `ok` is true iff nothing was rejected, and only an
 * all-valid list should ever reach a child process.
 *
 * Seed-list entries may be spec strings, `{ doi?|pmid?|arxiv?, title, abstract? }`
 * objects, or already-shaped `{ idType, id, title, abstract? }` objects. A caller-
 * supplied abstract is preserved on the validated seed (high-signal derive context —
 * the shared intake keeps it the same way).
 *
 * @param {object} options
 * @param {string[]} [options.seedSpecs] The --seed values, in argv order.
 * @param {string|null} [options.seedListPath] The --seed-list JSON file path.
 * @returns {Promise<{ ok: boolean, seeds: ReadonlyArray<object>,
 *   rejected: Array<{ seed: unknown, reason: string }> }>}
 */
export async function normalizeSeedInput({ seedSpecs = [], seedListPath = null } = {}) {
  if (!Array.isArray(seedSpecs) || seedSpecs.some((s) => typeof s !== 'string')) {
    throw new TypeError('normalizeSeedInput: seedSpecs must be an array of strings');
  }
  const si = await loadSharedSeedIdentity();

  const entries = seedSpecs.map((spec) => ({ entry: spec }));
  const rejected = [];
  if (seedListPath !== null) {
    let listed;
    try {
      listed = JSON.parse(fs.readFileSync(seedListPath, 'utf8'));
    } catch (err) {
      return {
        ok: false,
        seeds: Object.freeze([]),
        rejected: [
          { seed: seedListPath, reason: `--seed-list ${seedListPath} is not readable JSON: ${err.message}` },
        ],
      };
    }
    if (!Array.isArray(listed)) {
      return {
        ok: false,
        seeds: Object.freeze([]),
        rejected: [
          { seed: seedListPath, reason: `--seed-list ${seedListPath} must contain a JSON ARRAY of seed specs/objects` },
        ],
      };
    }
    for (const entry of listed) entries.push({ entry });
  }

  const seeds = [];
  for (const { entry } of entries) {
    let res;
    let abstract = null;
    if (typeof entry === 'string') {
      const classified = classifySeedSpec(entry);
      if (!classified.ok) {
        rejected.push({ seed: entry, reason: classified.reason });
        continue;
      }
      res = si.deriveSeedIdentity(classified.raw);
    } else if (typeof entry === 'object' && entry !== null && !Array.isArray(entry)) {
      abstract = typeof entry.abstract === 'string' ? entry.abstract : null;
      res = typeof entry.idType === 'string' ? si.validateSeed(entry) : si.deriveSeedIdentity(entry);
    } else {
      rejected.push({ seed: entry, reason: 'seed-list entries must be spec strings or seed objects' });
      continue;
    }
    if (!res.ok) {
      rejected.push(res.rejection);
      continue;
    }
    seeds.push(Object.freeze(abstract === null ? { ...res.seed } : { ...res.seed, abstract }));
  }

  return { ok: rejected.length === 0, seeds: Object.freeze(seeds), rejected };
}
