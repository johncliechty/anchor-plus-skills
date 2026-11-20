/**
 * DELTA-COVERAGE GATE — a wave that adds a SURFACE must add a test that names it.
 *
 * WHY (foreman journal 0091, 2026-07-27). Foreman built the Ecgberht steward and
 * the run went GREEN. It delivered 8 HTTP routes, 13 functions and ~670 lines of
 * Python + JS **with not one test file mentioning it**. Six real defects were
 * found later, by reading.
 *
 * Pure predicates over a file list — no I/O, no git spawn, no model. The caller
 * supplies changed files (Foreman already knows them); this decides.
 */

/** Directories ignored across delta-coverage classification and test discovery. */
export const IGNORE_DIRS = new Set([
  '.git', '.foreman', '.anchor', '.ecgberht', '.claude', '.codex', '.gemini',
  'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
  '.venv', 'venv', 'dist', 'build', 'bundle', 'bundle_staging', 'coverage',
]);

/** Non-code / binary / documentation / scratch extensions that are never executable surfaces. */
export const NON_CODE_EXTS = new Set([
  '.md', '.markdown', '.rst', '.txt', '.json', '.jsonl', '.yaml', '.yml', '.toml',
  '.ini', '.cfg', '.conf', '.lock', '.log', '.csv', '.tsv',
  '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp', '.bmp', '.pdf',
  '.docx', '.pptx', '.xlsx', '.ics',
  '.sqlite', '.sqlite3', '.sqlite-wal', '.sqlite-shm', '.db-wal', '.db-shm', '.wal', '.shm',
  '.bak', '.orig', '.tmp', '.swp', '.pyc', '.pyo',
]);

/** Path shapes that constitute a SURFACE — the things users and callers reach. */
export const SURFACE_SIGNALS = Object.freeze([
  { id: 'http-route', re: /route[_-]?table|routes?\.(py|mjs|cjs|js|ts|tsx|jsx)$|urls\.py$/i },
  { id: 'handler', re: /handlers?\.(py|mjs|cjs|js|ts|tsx|jsx)$|_gui\.py$|server\.(py|mjs|cjs|js|ts|tsx|jsx)$/i },
  { id: 'cli', re: /(^|\/)(bin|cli)\//i },
  { id: 'persistence', re: /(store|repo|repository|persist|ledger|registry|db|schema)/i },
  { id: 'frontend', re: /\.(jsx?|tsx?|vue|svelte)$|(^|\/)static\/.*\.(mjs|cjs|js|ts|jsx|tsx|html|htm|css)$/i },
]);

/** Normalize path separators and detect deleted / dotfile / ignored-dir / non-code entries. */
export function isIgnoredForDeltaCoverage(rawPath) {
  const s = String(rawPath || '').trim();
  if (!s) return true;
  if (/\s+\(deleted\)$/i.test(s)) return true;
  const norm = s.replace(/\\/g, '/').replace(/^\.\//, '').replace(/^\/+/, '');
  if (!norm) return true;
  const parts = norm.split('/');
  for (const seg of parts) {
    if (!seg) continue;
    if (IGNORE_DIRS.has(seg) || IGNORE_DIRS.has(seg.toLowerCase())) return true;
    // Dotfiles / dot-directories (.provider-schema-*, .env, .gitignore, .foreman/*, etc.)
    if (seg.startsWith('.')) return true;
  }
  const base = parts[parts.length - 1].toLowerCase();
  if (base.startsWith('_scratch')) return true;
  // Compound non-code / sqlite sidecar suffixes first
  for (const ext of NON_CODE_EXTS) {
    if (base.endsWith(ext)) return true;
  }
  return false;
}

/** Does this path look like a test? */
export function isTestPath(p) {
  const s = String(p || '').replace(/\\/g, '/');
  if (/\s+\(deleted\)$/i.test(s)) return false;
  return /(^|\/)(tests?|spec|__tests__)\//i.test(s) ||
    /\.(test|spec)\.[a-z0-9]+$/i.test(s) ||
    /(^|\/)test_[^/]+\.py$/i.test(s) ||
    /(^|\/)[^/]+_test\.py$/i.test(s);
}

/** Order candidate test paths so dedicated `tests/` and `test/` trees come first. */
export function prioritizeTestFiles(paths = []) {
  const valid = (paths || [])
    .map((p) => String(p || '').replace(/\\/g, '/'))
    .filter((p) => p && !isIgnoredForDeltaCoverage(p));
  const rank = (p) => {
    if (/^(tests?|__tests__|spec)\//i.test(p)) return 0;
    if (/\/(tests?|__tests__|spec)\//i.test(p)) return 1;
    if (isTestPath(p)) return 2;
    return 3;
  };
  return [...valid].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

/**
 * Strip directories and compound extensions (`.test.mjs`, `.spec.ts`, `.d.ts`, etc.)
 * down to identifier tokens for name matching.
 */
export function tokensFor(p) {
  const clean = String(p || '').replace(/\s+\(deleted\)$/i, '');
  const base = clean.split(/[\\/]/).pop() || '';
  // Strip compound extensions such as `.test.mjs`, `.spec.ts`, `.d.ts`, `.min.js`, then final `.ext`
  let stem = base
    .replace(/(?:\.(?:test|spec|d|min|bundle|generated))+\.[a-z0-9]+$/i, '')
    .replace(/\.[a-z0-9]+$/i, '');
  stem = stem.replace(/^test_/i, '').replace(/_(?:test|spec)$/i, '');
  // Split camelCase as well as snake/kebab separators
  const expanded = stem
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2');
  const STOP = new Set(['test', 'tests', 'spec', 'specs']);
  const toks = expanded
    .split(/[^a-zA-Z0-9]+/)
    .map((t) => t.toLowerCase())
    .filter((t) => t.length >= 4 && !STOP.has(t));
  if (toks.length) return [...new Set(toks)];
  // Short-stem fallback (journal 0105): e.g. `f1.js`, `db.py` -> whole stem
  const whole = stem.toLowerCase();
  return whole && !STOP.has(whole) ? [whole] : [];
}

/** Build identifier-boundary token set from test text so accidental substrings never false-match. */
export function extractIdentifierMentions(text = '') {
  const raw = String(text || '');
  if (!raw) return new Set();
  const words = new Set();
  const decamel = raw
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .toLowerCase();
  for (const w of decamel.split(/[^a-z0-9]+/)) {
    if (w) words.add(w);
  }
  // Also retain intact snake_case / kebab-case identifiers
  const compounds = raw.toLowerCase().match(/[a-z0-9]+(?:[_-][a-z0-9]+)+/g) || [];
  for (const c of compounds) {
    words.add(c);
    for (const part of c.split(/[_-]+/)) {
      if (part) words.add(part);
    }
  }
  return words;
}

/**
 * Classify a wave's changed files (filtering deletions, dotfiles, ignored dirs, and non-code files).
 * @param {string[]} changedFiles
 */
export function classifyDelta(changedFiles = []) {
  const rawFiles = (changedFiles || []).map((f) => String(f || '').replace(/\\/g, '/'));
  const files = rawFiles.filter((f) => !isIgnoredForDeltaCoverage(f));
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
 */
export function checkDeltaCoverage({ changedFiles = [], testMentions = '', repoTestConvention = [] } = {}) {
  const { files, tests, surfaces } = classifyDelta(changedFiles);
  const scanned = { files, tests };

  if (surfaces.length === 0) {
    return { pass: true, severity: 'OK', uncovered: [], scanned, detail: 'wave adds no surface; delta-coverage not applicable' };
  }

  const mentionWords = extractIdentifierMentions(testMentions);
  const prioritizedTests = prioritizeTestFiles(tests);
  const testTokens = new Set(prioritizedTests.flatMap(tokensFor));

  const mentionHas = (t) => mentionWords.has(String(t || '').toLowerCase());

  const uncovered = surfaces.filter(({ file }) => {
    const toks = tokensFor(file);
    if (toks.some(mentionHas)) return false;                    // a test names it on an identifier boundary
    if (toks.some((t) => testTokens.has(t))) return false;      // a test file is named for it
    return true;
  });

  if (uncovered.length === 0) {
    return {
      pass: true,
      severity: 'OK',
      uncovered: [],
      scanned,
      detail: `${surfaces.length} surface change(s), each named by a test in this wave`,
    };
  }

  const listCap = (arr, n = 12) =>
    arr.length <= n ? arr.join(', ') : `${arr.slice(0, n).join(', ')} +${arr.length - n} more (full list in the wave's delta-coverage.json)`;

  const conventionNote = repoTestConvention.length
    ? ` This repo's convention is a stub gate per subsystem (e.g. ${repoTestConvention[0]}); a new subsystem without one is an INCOMPLETE wave.`
    : '';

  return {
    pass: false,
    severity: 'BLOCKER',
    uncovered,
    scanned,
    detail:
      `${uncovered.length} surface change(s) with no test naming them: ` +
      uncovered.map((u) => `${u.file} (${u.kind})`).join(', ') +
      `. A suite that stays green because the new code is UNTESTED is not evidence.` +
      conventionNote +
      ` SCANNED — changed files (${files.length}): ${listCap(files)}; test files read for mentions (${tests.length}): ${tests.length ? listCap(tests) : 'NONE in this wave'}.`,
  };
}

export const DEFAULT_WIREUP_ASSERTIONS = Object.freeze([
  'every declared route reaches a handler that exists',
  'every handler is reachable by at least one route (no dead code that reads as a feature)',
  'every endpoint the frontend calls is declared',
  'every route carries the expected auth policy',
  'each failure path returns its documented status code AND user-visible text',
]);

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
