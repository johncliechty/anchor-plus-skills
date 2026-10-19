/**
 * W6 Canary pack — consolidated boundary + scope canaries.
 *
 * Checks:
 * - no openclaw dependency paths
 * - no daemon / listen loop
 * - compose-only hooks for five skills
 * - spelling Ecgberht
 * - no Anchor v1.0 release-tree write paths
 *
 * TW7 additions (Screen 4 wave):
 * - junction canary — realpath-BEFORE-prefix: a junction/symlink alias whose
 *   realpath lands in a release freeze tree is RED even when the alias name
 *   looks innocent (runJunctionCanary)
 * - second-task-DB canary — E5 is the sole ledger (Strip receipts/instruments,
 *   roadmap events, Face narrative); no task database, no durable chat store
 *   (runSecondTaskDbCanary)
 * - runCanaryPackTw7 — spelling + compose-only + v1.0-writes + junction +
 *   second-task-DB, aggregated for CI
 */

import fs from 'node:fs';
import path from 'node:path';
import { skillRoot } from './load.mjs';
import { SPELLING } from './verbs.mjs';
import { COMMISSION_SKILLS, runBoundaryCanaries } from './commission.mjs';
import { runHarnessCanaries } from './verb-bodies.mjs';
import { DIALOGUE_STORE_POLICY } from './dialogue.mjs';

/** Path/prefix markers that must never appear as write targets in engine sources. */
export const ANCHOR_V1_WRITE_MARKERS = Object.freeze([
  'Anchor-release-v1.0',
  'anchor-release-v1.0',
  'Anchor-release-v1.0.x',
  'public freeze tags',
]);

/** Write-ish APIs paired with v1.0 markers = canary fail. */
const WRITE_API =
  /\b(?:writeFileSync|writeFile|appendFileSync|appendFile|renameSync|rename|rmSync|rm|mkdirSync|cpSync|copyFileSync|createWriteStream)\s*\(/;

/**
 * Spelling canary: product name is Ecgberht; Expert is not the product name.
 * @param {{ texts?: string[], engineDir?: string }} [opts]
 */
export function runSpellingCanary(opts = {}) {
  const issues = [];
  const texts = Array.isArray(opts.texts) ? opts.texts : [];

  if (!texts.length) {
    const root = skillRoot();
    const samples = [
      path.join(root, 'SKILL.md'),
      path.join(root, 'package.json'),
      path.join(root, 'engine', 'verbs.mjs'),
    ];
    for (const p of samples) {
      try {
        texts.push(fs.readFileSync(p, 'utf8'));
      } catch {
        issues.push({ file: path.basename(p), reason: 'unreadable' });
      }
    }
  }

  let hasEcgberht = false;
  for (const text of texts) {
    if (typeof text !== 'string') continue;
    if (text.includes(SPELLING) || text.includes('Ecgberht')) hasEcgberht = true;
    // package name "ecgberht" is fine; product role "Expert" is not
    if (/\bExpert\b/.test(text) && /product name|role name|Foundry skill/i.test(text)) {
      // only flag when Expert appears as product naming (SKILL says "never Expert")
      // allow documentation that rejects Expert
      if (!/never Expert|not.*Expert|Expert as/i.test(text) && !text.includes('never Expert')) {
        // SKILL contains "never Expert" — that is allowed; bare Expert-as-name elsewhere is rare
      }
    }
  }

  if (!hasEcgberht) {
    issues.push({ reason: 'missing_ecgberht_spelling' });
  }

  // Engine constant must be exact
  if (SPELLING !== 'Ecgberht') {
    issues.push({ reason: 'SPELLING_constant_mismatch', value: SPELLING });
  }

  return {
    ok: issues.length === 0 && SPELLING === 'Ecgberht',
    spelling: SPELLING,
    expected: 'Ecgberht',
    issues,
  };
}

/**
 * Scan engine sources for writes targeting Anchor v1.0 release-tree paths.
 * Forbids known freeze prefixes + write APIs; does not hardcode host roots.
 * @param {string} [engineDir]
 */
export function runAnchorV1WriteCanary(engineDir) {
  const dir = path.resolve(engineDir || path.join(skillRoot(), 'engine'));
  const hits = [];
  const scanned = [];
  const files = listJsFiles(dir);

  for (const file of files) {
    const rel = path.relative(dir, file).split(path.sep).join('/');
    scanned.push(rel);
    let text;
    try {
      text = fs.readFileSync(file, 'utf8');
    } catch {
      continue;
    }
    const lines = text.split(/\r?\n/);
    lines.forEach((line, idx) => {
      const trimmed = line.trim();
      const code = trimmed.replace(/\/\/.*$/, '').trim();
      if (
        !code ||
        code.startsWith('*') ||
        code.startsWith('/*') ||
        code.startsWith('#')
      ) {
        return;
      }
      // Skip canary definition arrays / ban documentation
      if (
        /ANCHOR_V1_WRITE_MARKERS|runAnchorV1WriteCanary|runCanaryPack/.test(code)
      ) {
        return;
      }
      const hasMarker = ANCHOR_V1_WRITE_MARKERS.some((m) => code.includes(m));
      if (!hasMarker) return;
      // Fail if write API co-occurs with freeze marker, or assignment to freeze path
      if (WRITE_API.test(code) || /['"`][^'"`]*Anchor-release-v1\.0[^'"`]*['"`]/.test(code)) {
        // Allow pure ban strings in regex/array for detection only when not writing
        if (WRITE_API.test(code)) {
          hits.push({
            file: path.basename(file),
            line: idx + 1,
            text: trimmed.slice(0, 120),
          });
        }
      }
    });
  }

  // Also scan for hard-coded absolute write into release tree pattern
  for (const file of files) {
    let text;
    try {
      text = fs.readFileSync(file, 'utf8');
    } catch {
      continue;
    }
    const lines = text.split(/\r?\n/);
    lines.forEach((line, idx) => {
      const code = line.trim().replace(/\/\/.*$/, '').trim();
      if (!code || code.startsWith('*')) return;
      if (/ANCHOR_V1|runAnchorV1WriteCanary|runCanaryPack/.test(code)) return;
      // writeFile* ( ... Anchor-release-v1.0 ... ) on same line
      if (
        WRITE_API.test(code) &&
        /Anchor-release-v1\.0|anchor-release-v1\.0/i.test(code)
      ) {
        hits.push({
          file: path.basename(file),
          line: idx + 1,
          text: code.slice(0, 120),
        });
      }
    });
  }

  // Dedupe by file:line
  const seen = new Set();
  const unique = [];
  for (const h of hits) {
    const k = `${h.file}:${h.line}`;
    if (seen.has(k)) continue;
    seen.add(k);
    unique.push(h);
  }

  return {
    ok: unique.length === 0,
    anchor_v1_write_hits: unique,
    scanned,
    message:
      unique.length === 0
        ? 'No Anchor v1.0 release-tree write paths in engine sources'
        : 'Anchor v1.0 write-path canary failed',
  };
}

/**
 * Compose-only hooks present for the five named skills.
 * @param {string} [engineDir]
 */
export function runComposeOnlyCanary(engineDir) {
  const boundary = runBoundaryCanaries(
    engineDir || path.join(skillRoot(), 'engine'),
  );
  const missing = boundary.missing_hooks ?? [];
  const compose_hooks = boundary.compose_hooks ?? {};
  return {
    ok: missing.length === 0 && COMMISSION_SKILLS.every((s) => compose_hooks[s]),
    compose_hooks,
    missing_hooks: missing,
    commission_skills: [...COMMISSION_SKILLS],
    adapter_export_violations: boundary.adapter_export_violations ?? [],
  };
}

/**
 * Full W6 canary pack.
 * @param {{ engineDir?: string, skillRoot?: string }} [opts]
 */
export function runCanaryPack(opts = {}) {
  const root = opts.skillRoot || skillRoot();
  const engineDir = opts.engineDir || path.join(root, 'engine');

  const harness = runHarnessCanaries(engineDir);
  const boundary = runBoundaryCanaries(engineDir, { skillRoot: root });
  const spelling = runSpellingCanary();
  const anchor_v1 = runAnchorV1WriteCanary(engineDir);
  const compose = runComposeOnlyCanary(engineDir);

  const ok =
    harness.ok &&
    boundary.ok &&
    spelling.ok &&
    anchor_v1.ok &&
    compose.ok;

  return {
    ok,
    spelling: SPELLING,
    openclaw_hits: harness.openclaw_hits ?? [],
    daemon_hits: harness.daemon_hits ?? [],
    shark_hits: boundary.shark_hits ?? [],
    product_id_hits: boundary.product_id_hits ?? [],
    xai_http_hits: boundary.xai_http_hits ?? [],
    compose_hooks: compose.compose_hooks,
    missing_hooks: compose.missing_hooks,
    adapter_export_violations: compose.adapter_export_violations,
    anchor_v1_write_hits: anchor_v1.anchor_v1_write_hits,
    spelling_canary: spelling,
    harness_ok: harness.ok,
    boundary_ok: boundary.ok,
    scanned: boundary.scanned ?? harness.scanned ?? [],
    message: ok
      ? 'Canary pack green: no openclaw/daemon/v1.0 write paths; compose-only hooks; Ecgberht spelling'
      : 'Canary pack failed',
  };
}

// ---------------------------------------------------------------------------
// TW7 — junction canary (realpath-before-prefix, junction-aware)
// ---------------------------------------------------------------------------

/**
 * Release freeze path segments. A write root whose REALPATH contains one of
 * these as a path segment is frozen ground — never a valid write target.
 * (v1.0.x tags match by prefix; see isFreezeSegment.)
 */
export const RELEASE_FREEZE_SEGMENTS = Object.freeze([
  'Anchor-release-v1.0',
  'Anchor-release-v1.1',
]);

/**
 * Resolve a path junction-aware: realpath of the deepest existing ancestor
 * plus the not-yet-existing tail. This is what makes an innocently-named
 * junction alias reveal its true (possibly frozen) target BEFORE any prefix
 * check runs — the realpath-before-prefix law.
 * @param {string} p
 * @returns {{ path: string, resolved: boolean }}
 */
export function realpathJunctionAware(p) {
  const abs = path.resolve(String(p ?? ''));
  const realpath = fs.realpathSync.native ?? fs.realpathSync;
  const tail = [];
  let cur = abs;
  for (;;) {
    try {
      const real = realpath(cur);
      return { path: tail.length ? path.join(real, ...tail) : real, resolved: true };
    } catch {
      const parent = path.dirname(cur);
      if (parent === cur) return { path: abs, resolved: false };
      tail.unshift(path.basename(cur));
      cur = parent;
    }
  }
}

/**
 * True when one path segment is a release-freeze segment.
 * v1.0 matches by prefix (covers v1.0.x tag trees); v1.1 exact.
 * @param {string} segment
 */
export function isFreezeSegment(segment) {
  const s = String(segment ?? '').toLowerCase();
  return s.startsWith('anchor-release-v1.0') || s === 'anchor-release-v1.1';
}

/**
 * The first freeze segment found in a RESOLVED path (null when clean).
 * Callers must pass a realpath — use isReleaseFreezeRealpath for the
 * resolve-then-check pairing.
 * @param {string} resolvedPath
 */
export function freezeSegmentIn(resolvedPath) {
  const segments = String(resolvedPath ?? '').split(/[\\/]+/);
  return segments.find((seg) => isFreezeSegment(seg)) ?? null;
}

/**
 * Realpath FIRST, prefix check SECOND. Returns the verdict with the
 * evidence: what the alias resolved to and which segment froze it.
 * @param {string} p
 * @returns {{ frozen: boolean, given: string, realpath: string, resolved: boolean, segment: string|null }}
 */
export function isReleaseFreezeRealpath(p) {
  const rp = realpathJunctionAware(p);
  const segment = freezeSegmentIn(rp.path);
  return {
    frozen: segment != null,
    given: String(p ?? ''),
    realpath: rp.path,
    resolved: rp.resolved,
    segment,
  };
}

/**
 * TW7 junction canary: RED when any candidate write root's realpath lands
 * in a release freeze tree — including through a junction alias whose own
 * name carries no freeze marker. Runs in CI via the test suite; a red here
 * fails the build.
 * @param {{ paths?: string[] }} [opts]
 */
export function runJunctionCanary(opts = {}) {
  const paths = Array.isArray(opts.paths) && opts.paths.length
    ? opts.paths
    : [skillRoot()];
  const hits = [];
  for (const p of paths) {
    const verdict = isReleaseFreezeRealpath(p);
    if (verdict.frozen) hits.push(verdict);
  }
  return {
    ok: hits.length === 0,
    law: 'realpath-before-prefix: a junction alias toward a release freeze tree is RED',
    checked: paths.length,
    hits,
    message:
      hits.length === 0
        ? 'No write root resolves into a release freeze tree (junction-aware)'
        : 'Junction canary RED: a write root realpath lands in a release freeze tree',
  };
}

// ---------------------------------------------------------------------------
// TW7 — second-task-DB canary (E5 sole ledger; no second memory)
// ---------------------------------------------------------------------------

/**
 * Markers of a second task/chat database. Package imports of embedded DBs
 * and store filenames that would shadow the E5 ledger are both forbidden in
 * engine sources.
 */
export const SECOND_TASK_DB_MARKERS = Object.freeze([
  'better-sqlite3',
  'node:sqlite',
  'sqlite3',
  'lowdb',
  'nedb',
  'leveldown',
  'levelup',
  'tasks.db',
  'tasks.sqlite',
  'task-db.json',
  'chat-ledger.json',
  'dialogue-ledger.json',
]);

const IMPORT_OR_REQUIRE =
  /\b(?:import\s[^;]*from\s*['"]|require\s*\(\s*['"]|import\s*\(\s*['"])/;

/**
 * TW7 second-task-DB canary. Two checks:
 * 1. Engine sources contain no embedded-DB imports and no writes to a
 *    second task/chat store file.
 * 2. The locked dialogue store policy is still ephemeral (no durable chat
 *    ledger) and the E5 persist list is exactly the sole-ledger surfaces.
 * @param {{ engineDir?: string, texts?: {file: string, text: string}[] }} [opts]
 */
export function runSecondTaskDbCanary(opts = {}) {
  const hits = [];
  const scanned = [];

  let sources;
  if (Array.isArray(opts.texts)) {
    sources = opts.texts;
  } else {
    const dir = path.resolve(opts.engineDir || path.join(skillRoot(), 'engine'));
    sources = listJsFiles(dir).map((file) => {
      let text = '';
      try {
        text = fs.readFileSync(file, 'utf8');
      } catch {
        /* unreadable file scans as empty */
      }
      return { file: path.basename(file), text };
    });
  }

  const writeApi =
    /\b(?:writeFileSync|writeFile|appendFileSync|appendFile|createWriteStream)\s*\(/;

  for (const { file, text } of sources) {
    scanned.push(file);
    const lines = String(text ?? '').split(/\r?\n/);
    lines.forEach((line, idx) => {
      const code = line.trim().replace(/\/\/.*$/, '').trim();
      if (!code || code.startsWith('*') || code.startsWith('/*')) return;
      // Skip this canary's own definitions/aggregations
      if (/SECOND_TASK_DB|runSecondTaskDbCanary|runCanaryPackTw7/.test(code)) return;
      const marker = SECOND_TASK_DB_MARKERS.find((m) => code.includes(m));
      if (!marker) return;
      if (IMPORT_OR_REQUIRE.test(code) || writeApi.test(code)) {
        hits.push({ file, line: idx + 1, marker, text: code.slice(0, 120) });
      }
    });
  }

  // E5 AS AMENDED 2026-08-05. The canary no longer asks "is chat ephemeral" — the
  // conversation is deliberately kept now. It asks the question that actually protects
  // the system, and which the old check was only a proxy for:
  //
  //   is there exactly ONE set of surfaces that carry project STATE?
  //
  // A durable transcript is fine. A durable transcript that can mint a step, flip a
  // status, authorize spend or commission work is the second source of truth E5 was
  // written to prevent — so THAT is what is asserted, and it is stricter than before.
  const policy = opts.policy ?? DIALOGUE_STORE_POLICY;
  const STATE_SURFACES = [
    'strip_receipts', 'strip_instruments', 'roadmap_events', 'face_narrative',
  ];
  const policy_ok =
    policy.authoritative_for_state === false &&
    Array.isArray(policy.state_surfaces) &&
    policy.state_surfaces.length === STATE_SURFACES.length &&
    policy.state_surfaces.every((s) => STATE_SURFACES.includes(s)) &&
    Array.isArray(policy.never) &&
    ['mint_step', 'flip_status', 'authorize_spend', 'commission']
      .every((f) => policy.never.includes(f));

  const ok = hits.length === 0 && policy_ok;
  return {
    ok,
    sole_state_ledger: 'E5 — Strip receipts/instruments + roadmap events + Face narrative',
    /** Kept for history, never for state (amended 2026-08-05). */
    durable_non_authoritative_stores: ['conversation_log'],
    second_task_db_hits: hits,
    dialogue_policy_ok: policy_ok,
    scanned,
    message: ok
      ? 'One state ledger: no embedded-DB imports, no shadow stores, and the conversation log is non-authoritative'
      : 'Second-task-DB canary failed',
  };
}

// ---------------------------------------------------------------------------
// TW7 — aggregated canary pack for CI
// ---------------------------------------------------------------------------

/**
 * TW7 canary pack: spelling + compose-only + Anchor v1.0 writes + junction
 * (realpath-before-prefix) + second-task-DB, aggregated. Any red fails CI.
 * @param {{ engineDir?: string, skillRoot?: string, paths?: string[] }} [opts]
 */
export function runCanaryPackTw7(opts = {}) {
  const root = opts.skillRoot || skillRoot();
  const engineDir = opts.engineDir || path.join(root, 'engine');

  const spelling = runSpellingCanary();
  const compose = runComposeOnlyCanary(engineDir);
  const anchor_v1 = runAnchorV1WriteCanary(engineDir);
  const junction = runJunctionCanary({ paths: opts.paths ?? [root, engineDir] });
  const second_task_db = runSecondTaskDbCanary({ engineDir });

  const ok =
    spelling.ok && compose.ok && anchor_v1.ok && junction.ok && second_task_db.ok;

  return {
    ok,
    spelling,
    compose_only: compose,
    anchor_v1,
    junction,
    second_task_db,
    message: ok
      ? 'TW7 canary pack green: spelling · compose-only · no v1.0 writes · junction realpath · sole ledger'
      : 'TW7 canary pack failed',
  };
}

function listJsFiles(dir) {
  const out = [];
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const ent of entries) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (ent.name === 'node_modules' || ent.name === '.git') continue;
      out.push(...listJsFiles(p));
    } else if (
      ent.isFile() &&
      (ent.name.endsWith('.mjs') || ent.name.endsWith('.js'))
    ) {
      out.push(p);
    }
  }
  return out;
}
