/**
 * DELTA-COVERAGE GATE — a wave that adds a SURFACE must add a test that names it.
 *
 * WHY (foreman journal 0091, 2026-07-27). Foreman built the Ecgberht steward and
 * the run went GREEN. It delivered 8 HTTP routes, 13 functions and ~670 lines of
 * Python + JS **with not one test file mentioning it**. Six real defects were
 * found later, by reading.
 *
 * The gate could not see it, and the reason is uncomfortable: wave acceptance
 * measured "the deliverable exists" and "the suite is green". A wave that adds a
 * surface and no tests satisfies BOTH trivially — the existing suite stays green
 * *precisely because* the new code is untested. So "0 tests for 670 new lines"
 * and "full coverage" produced the same verdict.
 *
 * This is deliberately NOT a global coverage percentage. A percentage is gameable
 * and stays comfortably green while an entire subsystem is bare — that is exactly
 * what happened. The unit of judgement is the DELTA: what did this wave add, and
 * does anything test it by name?
 *
 * Pure predicates over a file list — no I/O, no git spawn, no model. The caller
 * supplies changed files (Foreman already knows them); this decides.
 */

/** Path shapes that constitute a SURFACE — the things users and callers reach. */
export const SURFACE_SIGNALS = Object.freeze([
  { id: 'http-route', re: /route[_-]?table|routes?\.(py|mjs|js|ts)$|urls\.py$/i },
  { id: 'handler', re: /handlers?\.(py|mjs|js|ts)$|_gui\.py$|server\.(py|mjs|js|ts)$/i },
  { id: 'cli', re: /(^|\/)(bin|cli)\//i },
  { id: 'persistence', re: /(store|repo|repository|persist|ledger|registry|db|schema)/i },
  { id: 'frontend', re: /\.(jsx?|tsx?|vue|svelte)$|static\//i },
]);

/** Does this path look like a test? */
export function isTestPath(p) {
  return /(^|\/)(tests?|spec|__tests__)\//i.test(p) || /\.(test|spec)\.[a-z]+$/i.test(p) ||
    /(^|\/)test_[^/]+\.py$/i.test(p);
}

/** Strip directories/extensions down to identifier-ish tokens for name matching. */
function tokensFor(p) {
  const base = String(p).split(/[\\/]/).pop() || '';
  const stem = base.replace(/\.[a-z0-9]+$/i, '').replace(/^test_/, '');
  return stem
    .split(/[^a-zA-Z0-9]+/)
    .filter((t) => t.length >= 4)
    .map((t) => t.toLowerCase());
}

/**
 * Classify a wave's changed files.
 * @param {string[]} changedFiles
 */
export function classifyDelta(changedFiles = []) {
  const files = (changedFiles || []).map(String);
  const tests = files.filter(isTestPath);
  const sources = files.filter((f) => !isTestPath(f));
  const surfaces = [];
  for (const f of sources) {
    const sig = SURFACE_SIGNALS.find((s) => s.re.test(f));
    if (sig) surfaces.push({ file: f, kind: sig.id });
  }
  return { files, tests, sources, surfaces };
}

/**
 * THE GATE. A wave that adds a surface must add or touch a test that plausibly
 * names it. Returns a BLOCKER (not a nit) when it does not.
 *
 * `testMentions` lets the caller supply the actual text of the wave's test files
 * for a stronger check (does any test literally mention the route/handler?).
 * Absent that, the check falls back to filename-token overlap.
 *
 * @param {object} o
 * @param {string[]} o.changedFiles
 * @param {string} [o.testMentions='']   concatenated text of the wave's tests
 * @param {string[]} [o.repoTestConvention=[]]  existing stub-gate test paths, if known
 * @returns {{pass:boolean, severity:'BLOCKER'|'OK', detail:string, uncovered:object[]}}
 */
export function checkDeltaCoverage({ changedFiles = [], testMentions = '', repoTestConvention = [] } = {}) {
  const { tests, surfaces } = classifyDelta(changedFiles);

  if (surfaces.length === 0) {
    return { pass: true, severity: 'OK', uncovered: [], detail: 'wave adds no surface; delta-coverage not applicable' };
  }

  const mentions = String(testMentions).toLowerCase();
  const testTokens = new Set(tests.flatMap(tokensFor));

  const uncovered = surfaces.filter(({ file }) => {
    const toks = tokensFor(file);
    if (toks.some((t) => mentions.includes(t))) return false;   // a test names it
    if (toks.some((t) => testTokens.has(t))) return false;      // a test file is named for it
    return true;
  });

  if (uncovered.length === 0) {
    return {
      pass: true,
      severity: 'OK',
      uncovered: [],
      detail: `${surfaces.length} surface change(s), each named by a test in this wave`,
    };
  }

  const conventionNote = repoTestConvention.length
    ? ` This repo's convention is a stub gate per subsystem (e.g. ${repoTestConvention[0]}); a new subsystem without one is an INCOMPLETE wave.`
    : '';

  return {
    pass: false,
    severity: 'BLOCKER',
    uncovered,
    detail:
      `${uncovered.length} surface change(s) with no test naming them: ` +
      uncovered.map((u) => `${u.file} (${u.kind})`).join(', ') +
      `. A suite that stays green because the new code is UNTESTED is not evidence.` +
      conventionNote,
  };
}

/**
 * The wire-up assertions worth emitting by default for any wave adding routes.
 * These are static-text checks needing no server boot — roughly five tests that
 * would have permanently protected the steward surface.
 */
export const DEFAULT_WIREUP_ASSERTIONS = Object.freeze([
  'every declared route reaches a handler that exists',
  'every handler is reachable by at least one route (no dead code that reads as a feature)',
  'every endpoint the frontend calls is declared',
  'every route carries the expected auth policy',
  'each failure path returns its documented status code AND user-visible text',
]);

/** Render the obligation as plan-ready text, so waves emit it rather than improvise. */
export function renderDeltaCoverageRequirement(surfaces = []) {
  if (!surfaces.length) return '';
  const kinds = [...new Set(surfaces.map((s) => s.kind))].join(', ');
  return [
    `## Delta-coverage requirement (foreman journal 0091)`,
    '',
    `This wave adds ${surfaces.length} surface change(s) (${kinds}). It is INCOMPLETE until a`,
    `test names each one. Emit at minimum:`,
    '',
    ...DEFAULT_WIREUP_ASSERTIONS.map((a) => `- [ ] ${a}`),
    '',
    'Failure-path tests assert the STATUS CODE and the USER-VISIBLE TEXT: the recurring',
    'defect in this codebase is a confident wrong answer ("no projects", "queue 0"),',
    'not a crash, and a happy-path test cannot see it.',
  ].join('\n');
}
