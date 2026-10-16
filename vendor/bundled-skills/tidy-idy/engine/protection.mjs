// engine/protection.mjs — Wave 1: the deny-by-default protection predicate.
//
// This module is the ONE place that decides whether a path may ever be offered
// for removal. It runs BEFORE findings are emitted (the pipeline filters every
// stage's findings through it), and Wave 3's Apply executor re-runs it as
// defense in depth — same module, second call site, so the two can never drift.
//
// Two properties are load-bearing and are asserted by tests:
//   1. DENY BY DEFAULT — governance/capture surfaces, tests, entry points and
//      the generic classes below are protected whether or not anyone configured
//      anything.
//   2. STRICTLY ADDITIVE — `.tidy-idy.toml` can only ADD protected patterns.
//      No config key can remove or narrow the built-in set, so
//      protected(defaults) ⊆ protected(defaults + config) for ANY config.
//      (engine/config.mjs rejects subtractive keys at parse time; this module
//      never subtracts even if handed one.)

import { firstMatch, toPosixRel } from './glob.mjs';

/**
 * The built-in protected set, as {pattern, class, why} records so a withheld
 * path can be logged with the REASON it was withheld rather than an opaque
 * boolean. Ordered most-specific-first only for nicer logs; matching is a
 * disjunction, so order cannot change the verdict.
 */
export const BUILTIN_PROTECTED = Object.freeze([
  // — governance / North-Star surfaces (a hygiene tool must never eat the
  //   document it judges alignment against)
  { pattern: 'NORTH-STAR.md', class: 'north-star', why: 'North-Star document' },
  { pattern: 'INTENT.md', class: 'north-star', why: 'North-Star document' },
  { pattern: 'SKILL.md', class: 'north-star', why: 'skill definition' },
  { pattern: 'MASTER-PLAN.md', class: 'north-star', why: 'frozen plan document' },
  { pattern: 'IMPLEMENTATION-PLAN.md', class: 'north-star', why: 'frozen plan document' },
  { pattern: 'AGENTS.md', class: 'governance', why: 'agent instruction surface' },
  { pattern: 'CLAUDE.md', class: 'governance', why: 'agent instruction surface' },
  { pattern: 'LESSONS.md', class: 'governance', why: 'capture surface' },
  { pattern: 'CHANGELOG.md', class: 'governance', why: 'release history' },
  { pattern: 'README.md', class: 'docs', why: 'project README' },
  { pattern: 'README', class: 'docs', why: 'project README' },
  { pattern: 'LICENSE', class: 'legal', why: 'licence file' },
  { pattern: 'LICENSE.*', class: 'legal', why: 'licence file' },
  { pattern: 'COPYING', class: 'legal', why: 'licence file' },
  { pattern: 'NOTICE', class: 'legal', why: 'licence file' },

  // — capture / journal surfaces
  { pattern: 'journal/**', class: 'journal', why: 'run-capture journal' },
  { pattern: '**/journal/**', class: 'journal', why: 'run-capture journal' },
  { pattern: 'LOG.md', class: 'journal', why: 'execution log' },

  // — tests (removing a test is how a tool makes itself look correct)
  { pattern: 'test/**', class: 'tests', why: 'test directory' },
  { pattern: 'tests/**', class: 'tests', why: 'test directory' },
  { pattern: '**/test/**', class: 'tests', why: 'test directory' },
  { pattern: '**/tests/**', class: 'tests', why: 'test directory' },
  { pattern: '**/__tests__/**', class: 'tests', why: 'test directory' },
  { pattern: 'spike/**', class: 'tests', why: 'gate spike harness' },
  { pattern: '*.test.*', class: 'tests', why: 'test file' },
  { pattern: '*.spec.*', class: 'tests', why: 'test file' },
  { pattern: 'conftest.py', class: 'tests', why: 'test fixture module' },

  // — executable entry points / engine source
  { pattern: 'bin/**', class: 'entry-point', why: 'executable entry point' },
  { pattern: '**/bin/**', class: 'entry-point', why: 'executable entry point' },
  { pattern: 'engine/**', class: 'entry-point', why: 'engine source' },
  { pattern: 'scripts/**', class: 'entry-point', why: 'operational script' },

  // — generic classes (docs, config, CI, build)
  { pattern: 'docs/**', class: 'docs', why: 'documentation directory' },
  { pattern: '**/docs/**', class: 'docs', why: 'documentation directory' },
  { pattern: '.github/**', class: 'ci', why: 'CI / repository automation' },
  { pattern: '.gitlab-ci.yml', class: 'ci', why: 'CI configuration' },
  { pattern: '.circleci/**', class: 'ci', why: 'CI configuration' },
  { pattern: 'Makefile', class: 'build', why: 'build entry point' },
  { pattern: 'Dockerfile', class: 'build', why: 'build entry point' },
  { pattern: 'docker-compose*.yml', class: 'build', why: 'build entry point' },
  { pattern: 'package.json', class: 'config', why: 'package manifest' },
  { pattern: 'package-lock.json', class: 'config', why: 'dependency lockfile' },
  { pattern: 'pnpm-lock.yaml', class: 'config', why: 'dependency lockfile' },
  { pattern: 'yarn.lock', class: 'config', why: 'dependency lockfile' },
  { pattern: 'pyproject.toml', class: 'config', why: 'package manifest' },
  { pattern: 'requirements*.txt', class: 'config', why: 'dependency manifest' },
  { pattern: 'tsconfig*.json', class: 'config', why: 'compiler configuration' },
  { pattern: '.gitignore', class: 'config', why: 'repository configuration' },
  { pattern: '.gitattributes', class: 'config', why: 'repository configuration' },
  { pattern: '.editorconfig', class: 'config', why: 'editor configuration' },
  { pattern: '.env.example', class: 'config', why: 'configuration template' },
  { pattern: '.tidy-idy.toml', class: 'config', why: "tidy-idy's own configuration" },
]);

/** Patterns excluded from scanning entirely (never read, never a finding). */
export const BUILTIN_EXCLUSIONS = Object.freeze([
  'node_modules/**',
  '**/node_modules/**',
  '.git/**',
  '**/.git/**',
  '.venv/**',
  'venv/**',
  '__pycache__/**',
  '**/__pycache__/**',
  'dist/**',
  'build/**',
  '.next/**',
  'target/**',
  '.tidy-idy/**',
  // Wave 5: the tool's own per-run report archive. Excluded for the same reason
  // reportDir is — a run must not scan, hash, or judge its own previous output,
  // and an archive that grew into the next run's finding set would make the tool
  // its own biggest source of "junk".
  'reports/tidy/**',
  '**/reports/tidy/**',
]);

export const BUILTIN_PROTECTED_PATTERNS = Object.freeze(BUILTIN_PROTECTED.map((r) => r.pattern));

/**
 * Build the protection predicate for a run.
 *
 * @param {object} [config] parsed .tidy-idy.toml (see engine/config.mjs)
 * @returns {{
 *   patterns: string[], exclusions: string[],
 *   classify(rel: string): {protected: boolean, pattern: string|null, class: string|null, why: string|null},
 *   isProtected(rel: string): boolean,
 *   isExcluded(rel: string): boolean,
 *   filter(findings: object[]): {kept: object[], withheld: object[]}
 * }}
 */
export function makeProtection(config = {}) {
  const added = (config.protect && config.protect.patterns) || [];
  const addedExclusions = (config.exclude && config.exclude.patterns) || [];

  // UNION only — this is the code-level guarantee behind the monotonicity
  // property test. There is no branch in this module that can drop a builtin.
  const records = [
    ...BUILTIN_PROTECTED,
    ...added.map((pattern) => ({ pattern: String(pattern), class: 'config', why: 'added by .tidy-idy.toml' })),
  ];
  const patterns = records.map((r) => r.pattern);
  const exclusions = [...BUILTIN_EXCLUSIONS, ...addedExclusions.map(String)];

  function classify(rel) {
    const posix = toPosixRel(rel);
    for (const r of records) {
      if (firstMatch([r.pattern], posix)) {
        return { protected: true, pattern: r.pattern, class: r.class, why: r.why };
      }
    }
    return { protected: false, pattern: null, class: null, why: null };
  }

  function isProtected(rel) {
    return classify(rel).protected;
  }

  function isExcluded(rel) {
    return firstMatch(exclusions, rel) !== null;
  }

  /**
   * Filter a stage's findings before emission. Only ACTIONABLE findings (ones
   * that could lead to a path being removed or moved) are subject to
   * protection; advisory/proposal findings about a protected file are still
   * allowed through so the panel can say "this looks stale" without ever
   * offering the delete button.
   */
  function filter(findings) {
    const kept = [];
    const withheld = [];
    for (const f of findings || []) {
      const rel = f && (f.path || f.rel || f.filepath);
      const actionable = !f || f.action === undefined ? true : ACTIONABLE_ACTIONS.has(f.action);
      if (!rel || !actionable) { kept.push(f); continue; }
      const verdict = classify(rel);
      if (verdict.protected) {
        withheld.push({
          path: toPosixRel(rel),
          action: f.action || 'remove',
          stage: f.stage || null,
          pattern: verdict.pattern,
          class: verdict.class,
          why: `PROTECTED (${verdict.class}) — ${verdict.why}; never offered for ${f.action || 'removal'}`,
        });
      } else {
        kept.push(f);
      }
    }
    return { kept, withheld };
  }

  return { patterns, exclusions, records, classify, isProtected, isExcluded, filter };
}

/** Finding actions that can destroy or relocate a path. */
export const ACTIONABLE_ACTIONS = new Set(['remove', 'move', 'reorg', 'trash']);

/** The default (no-config) predicate, for callers that need a quick answer. */
export const DEFAULT_PROTECTION = makeProtection();

/** Convenience: is this path protected under the built-in set alone? */
export function isProtectedByDefault(rel) {
  return DEFAULT_PROTECTION.isProtected(rel);
}
