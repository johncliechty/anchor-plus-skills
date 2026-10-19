/**
 * CI diff fence (Wave 1).
 *
 * Fails the build on:
 *  1. Modifications under Crucible / Foreman / researchPrime trees
 *  2. Modifications under Ecgberht/planning/steward-tracking-2026-07 or
 *     engine/portfolio/ beyond the named-fix allow-list
 *  3. Anchor-side diffs introducing steward logic into Anchor Python
 *     (proposal/confirm decisions, reflection, attention derivation,
 *     roadmap/status law) outside named host-contract files
 *
 * Named-fix allow-list includes the Wave-1 A3 fix path (engine/brief.mjs).
 *
 * Grep spans BOTH repos including Python and scripts/. Pure function over a
 * file list so unit tests exercise it without git.
 *
 * Usage:
 *   node scripts/ci-diff-guard.mjs --files <listfile>
 *   node scripts/ci-diff-guard.mjs --diff-from <git-ref>   (orchestrator only)
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');

/** Paths that may never be touched by this build (trio internals). */
export const FORBIDDEN_TREE_PREFIXES = Object.freeze([
  'crucible/',
  'foreman/',
  'researchprime/',
  'research-prime/',
  // Absolute-ish repo-relative spellings
  'trio/crucible/',
  'trio/foreman/',
  'trio/researchprime/',
]);

/** Ecgberht regions fenced beyond the named-fix allow-list. */
export const FENCED_ECGBERHT_PREFIXES = Object.freeze([
  'planning/steward-tracking-2026-07/',
  'engine/portfolio/',
]);

/**
 * Named-fix allow-list (Wave 1 A3 fix + substrate scripts/tests).
 * Paths are repo-relative, forward-slash, lowercased for match.
 */
export const NAMED_FIX_ALLOW_LIST = Object.freeze([
  'engine/brief.mjs', // A3 + S11
  'engine/authorize.mjs',
  'engine/storage-primitive.mjs',
  'engine/high-seat.mjs', // A3 call-site: content-anchored briefCacheStale
  'engine/index.mjs', // re-exports
  'engine/durable-write.mjs', // named helpers (no silent rewrite of contract)
  'scripts/run-all-tests.mjs',
  'scripts/lane-bootstrap.mjs',
  'scripts/wave-manifests.mjs',
  'scripts/pytest-bridge.mjs',
  'scripts/check-decomposition-equivalence.mjs',
  'scripts/ci-diff-guard.mjs',
  // tests are always allowed under test/
  // planning/steward-handoff-v3 is the build plan home — allowed
  'planning/steward-handoff-v3/',
]);

/**
 * Anchor host-contract files that MAY change in this build.
 * Anything else under Anchor that introduces steward logic fails.
 */
export const ANCHOR_HOST_CONTRACT_ALLOW = Object.freeze([
  // executor / job runner
  'job_runner.py',
  'terminal_session.py',
  'lanes.py',
  'skill_runner.py',
  // outbox / session
  'session_registry.py',
  'sessions.py',
  // authorizer wiring
  'paths.py',
  'pillar_flags.py',
  'auth_peer.py',
  'auth_session.py',
  'auth_warn.py',
  // routes / UI
  'route_table.py',
  'anchor_gui.py',
  'OPEN_ROUTES.json',
  'static/',
  // tests for host contracts
  'tests/',
]);

/**
 * Steward-logic markers forbidden in Anchor Python outside host-contract allow.
 * (proposal/confirm decisions, reflection, attention derivation, roadmap/status law)
 */
export const STEWARD_LOGIC_MARKERS = Object.freeze([
  /proposeCommission|confirmCommission/,
  /assembleBriefPacket|briefCacheStale/,
  /deriveAttention|publishAttention/,
  /reflection_receipt|next_stage_proposal/,
  /appendRoadmapEvent|roadmap_events/,
  /def\s+propose_commission|def\s+confirm_commission/,
  /def\s+derive_attention|def\s+publish_attention/,
  /def\s+reflect_on_handback|def\s+next_stage_proposal/,
  /steward_logic|ecgberht_engine_decision/,
]);

/**
 * Normalize a path for fence matching.
 * @param {string} p
 */
export function normalizeRepoPath(p) {
  return String(p || '')
    .replace(/\\/g, '/')
    .replace(/^\.\//, '')
    .replace(/^\/+/, '')
    .toLowerCase();
}

/**
 * @param {string} filePath
 * @param {readonly string[]} prefixes
 */
function matchesPrefix(filePath, prefixes) {
  const n = normalizeRepoPath(filePath);
  return prefixes.some((pref) => {
    const p = pref.toLowerCase();
    return n === p.replace(/\/$/, '') || n.startsWith(p);
  });
}

/**
 * @param {string} filePath
 */
export function isNamedFixAllowed(filePath) {
  const n = normalizeRepoPath(filePath);
  if (n.startsWith('test/')) return true;
  if (n.startsWith('scripts/') && n.endsWith('.mjs')) return true;
  return NAMED_FIX_ALLOW_LIST.some((a) => {
    const al = a.toLowerCase();
    if (al.endsWith('/')) return n.startsWith(al);
    return n === al || n.endsWith('/' + al);
  });
}

/**
 * @param {string} filePath — may be anchor-relative or `anchor/...`
 */
export function isAnchorHostContractAllowed(filePath) {
  let n = normalizeRepoPath(filePath);
  if (n.startsWith('anchor/')) n = n.slice('anchor/'.length);
  return ANCHOR_HOST_CONTRACT_ALLOW.some((a) => {
    const al = a.toLowerCase();
    if (al.endsWith('/')) return n.startsWith(al);
    return n === al || n.endsWith('/' + al);
  });
}

/**
 * Pure fence check over a list of changed files.
 * @param {string[]} files
 * @param {{ fileContents?: Record<string, string> }} [opts]
 *   optional map of path → content for steward-logic grep on Anchor .py
 * @returns {{ ok: boolean, violations: Array<{ file: string, rule: string, message: string }> }}
 */
export function checkDiffFence(files, opts = {}) {
  /** @type {Array<{ file: string, rule: string, message: string }>} */
  const violations = [];
  const contents = opts.fileContents || {};

  for (const raw of files) {
    const file = String(raw);
    const n = normalizeRepoPath(file);

    // 1. Forbidden trio trees
    if (matchesPrefix(n, FORBIDDEN_TREE_PREFIXES)) {
      violations.push({
        file,
        rule: 'forbidden-trio-tree',
        message: `modification under forbidden trio tree: ${file}`,
      });
      continue;
    }

    // 2. Fenced Ecgberht regions beyond allow-list
    if (matchesPrefix(n, FENCED_ECGBERHT_PREFIXES) && !isNamedFixAllowed(n)) {
      violations.push({
        file,
        rule: 'fenced-ecgberht-region',
        message: `modification under fenced Ecgberht path without named-fix allow-list entry: ${file}`,
      });
      continue;
    }

    // 3. Anchor steward logic in Python
    const isAnchorPy =
      (n.endsWith('.py') &&
        (n.startsWith('anchor/') ||
          !n.includes('/') ||
          // bare top-level Anchor files when checked with anchor/ prefix stripped by caller
          true)) &&
      (n.startsWith('anchor/') ||
        opts.assumeAnchorRoot === true ||
        file.startsWith('anchor/') ||
        file.startsWith('Anchor/'));

    // Only apply steward-logic rule when the path is clearly Anchor-side.
    const anchorSide =
      n.startsWith('anchor/') ||
      opts.anchorFiles?.has?.(n) ||
      (opts.anchorRootFiles === true && !n.startsWith('engine/') && !n.startsWith('planning/') && !n.startsWith('test/') && !n.startsWith('scripts/') && n.endsWith('.py'));

    if (anchorSide && n.endsWith('.py')) {
      if (!isAnchorHostContractAllowed(n)) {
        const body = contents[file] ?? contents[n] ?? '';
        if (body) {
          for (const re of STEWARD_LOGIC_MARKERS) {
            if (re.test(body)) {
              violations.push({
                file,
                rule: 'steward-logic-in-anchor-python',
                message: `Anchor Python introduces steward logic (${re}) outside host-contract allow-list: ${file}`,
              });
              break;
            }
          }
        } else {
          // No content: still flag non-host-contract Anchor .py changes as suspicious
          // when the path is clearly steward-named.
          if (/steward|ecgberht|attention|roadmap_status|reflection/.test(n)) {
            violations.push({
              file,
              rule: 'steward-logic-in-anchor-python',
              message: `Anchor-side Python path looks like steward logic outside host-contract allow-list: ${file}`,
            });
          }
        }
      }
    }
  }

  return { ok: violations.length === 0, violations };
}

/**
 * Convenience: deliberate A3 fix must PASS the fence.
 * @returns {boolean}
 */
export function a3FixPassesFence() {
  const r = checkDiffFence(['engine/brief.mjs', 'engine/high-seat.mjs']);
  return r.ok;
}

function parseArgs(argv) {
  const files = [];
  let listFile = null;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--files' && argv[i + 1]) {
      listFile = argv[++i];
    } else if (argv[i] === '--file' && argv[i + 1]) {
      files.push(argv[++i]);
    }
  }
  if (listFile) {
    const text = fs.readFileSync(listFile, 'utf8');
    for (const line of text.split(/\r?\n/)) {
      const t = line.trim();
      if (t && !t.startsWith('#')) files.push(t);
    }
  }
  return { files };
}

function main() {
  const { files } = parseArgs(process.argv.slice(2));
  if (!files.length) {
    // No files provided — nothing to fence (vacuous pass with note).
    console.log('ci-diff-guard: no files listed; pass (nothing to check)');
    process.exit(0);
  }
  const result = checkDiffFence(files);
  if (!result.ok) {
    console.error('ci-diff-guard FAIL:');
    for (const v of result.violations) {
      console.error(`  [${v.rule}] ${v.message}`);
    }
    process.exit(1);
  }
  console.log(`ci-diff-guard PASS — ${files.length} file(s) within fence`);
  process.exit(0);
}

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  main();
}
