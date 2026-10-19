/**
 * Roots manifest + `chekhov roots` (operator-only) — W1.
 *
 * The four project roots are FIXED in roots.json (frozen plan). This module:
 *   - extracts the TEXT of a zip-backed root when the folder is missing
 *     (binary globs excluded at extraction — the roots are TEXT-only);
 *   - initialises each root as its OWN git repository (top-level == root);
 *   - writes .gitignore/.gitattributes excluding mp4, mp3, m4a, wav, zip and
 *     other binaries;
 *   - records the SHA-256 of the two zips in roots.json and marks them
 *     read-only;
 *   - writes the host WRITE-DENIAL rules into each project's
 *     .claude/settings.json, derived from lib/manifest.mjs MANAGED_PATTERNS
 *     (one source) — the only agent path into a managed file is the engine;
 *   - ensures the one-line consumer paragraph in each project CLAUDE.md.
 *
 * The Temp scratchpad copy is NEVER referenced — a test greps lib/ and
 * roots.json for any such path.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { MANAGED_PATTERNS } from './manifest.mjs';

const LIB_DIR = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_ROOTS_MANIFEST = path.join(LIB_DIR, '..', 'roots.json');
export const DEFAULT_JOURNAL = path.join(LIB_DIR, '..', 'journal', '0001-scaffold.md');

/** Binary globs kept OUT OF GIT in every root (.gitignore/.gitattributes). */
export const BINARY_GLOBS = Object.freeze([
  '*.mp4', '*.mp3', '*.m4a', '*.wav', '*.zip',
  '*.7z', '*.rar', '*.mov', '*.avi', '*.mkv', '*.flac', '*.ogg', '*.aiff',
  '*.m4b', '*.aac', '*.wma', '*.epub', '*.mobi',
  '*.docx', '*.doc', '*.pdf', '*.pptx', '*.xlsx',
  '*.jpg', '*.jpeg', '*.png', '*.gif', '*.heic', '*.tif', '*.tiff',
  '*.exe', '*.dll', '*.iso',
]);

/**
 * Globs excluded at ZIP EXTRACTION: media, archives, executables, and
 * node_modules dependency trees (not project text; their .bin symlinks
 * cannot be created by Windows tar). The docx, pdf and image documents DO
 * extract — W2 migrates the docx in-root (they stay on disk, outside git
 * via BINARY_GLOBS); the audio course and video stay where they are (in
 * the zip), per KEEP/CHANGE/DELETE.
 */
export const EXTRACT_EXCLUDE_GLOBS = Object.freeze([
  '*.mp4', '*.mp3', '*.m4a', '*.wav', '*.zip',
  '*.7z', '*.rar', '*.mov', '*.avi', '*.mkv', '*.flac', '*.ogg', '*.aiff',
  '*.m4b', '*.aac', '*.wma',
  '*.exe', '*.dll', '*.iso',
  'node_modules',
]);

function escapeRe(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

const GITIGNORE_BEGIN = '# --- chekhov roots (text-only; managed by chekhov roots) ---';
const GITIGNORE_END = '# --- end chekhov roots ---';

export function loadRoots(manifestPath = DEFAULT_ROOTS_MANIFEST) {
  return JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
}

export function saveRoots(manifest, manifestPath = DEFAULT_ROOTS_MANIFEST) {
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
}

function run(cmd, args, opts = {}) {
  return spawnSync(cmd, args, {
    encoding: 'utf8',
    windowsHide: true,
    shell: false,
    timeout: opts.timeout || 120000,
    ...opts,
  });
}

/** bsdtar (reads zip). Git Bash's GNU tar cannot; prefer System32 on Windows. */
export function tarBin() {
  if (process.platform === 'win32') {
    const sys = path.join(process.env.SystemRoot || 'C:/Windows', 'System32', 'tar.exe');
    if (fs.existsSync(sys)) return sys;
  }
  return 'tar';
}

export function sha256FileStreamless(abs) {
  return crypto.createHash('sha256').update(fs.readFileSync(abs)).digest('hex');
}

/** Extract only TEXT from a zip whose top folder equals basename(rootPath). */
export function extractZipTextOnly(zipPath, rootPath) {
  const parent = path.dirname(rootPath);
  const args = ['-xf', zipPath, '-C', parent];
  for (const glob of EXTRACT_EXCLUDE_GLOBS) args.push(`--exclude=${glob}`);
  const r = run(tarBin(), args, { timeout: 600000 });
  if (r.status !== 0) {
    throw new Error(`zip extraction failed for ${path.basename(zipPath)}: ${r.stderr || r.error || r.status}`);
  }
  if (!fs.existsSync(rootPath)) {
    throw new Error(`zip ${path.basename(zipPath)} did not produce the root folder ${path.basename(rootPath)}`);
  }
  return rootPath;
}

function gitToplevel(dir) {
  const r = run('git', ['-C', dir, 'rev-parse', '--show-toplevel']);
  if (r.status !== 0) return null;
  return String(r.stdout || '').trim();
}

function samePath(a, b) {
  const na = path.resolve(a).replace(/\\/g, '/');
  const nb = path.resolve(b).replace(/\\/g, '/');
  return process.platform === 'win32' ? na.toLowerCase() === nb.toLowerCase() : na === nb;
}

function ensureOwnGitRepo(rootPath) {
  const top = gitToplevel(rootPath);
  if (top && samePath(top, rootPath)) return 'already-toplevel';
  let r = run('git', ['init'], { cwd: rootPath });
  if (r.status !== 0) {
    // An interrupted earlier init can leave a stale .git/config.lock that
    // blocks every re-init forever; idempotency requires clearing it once.
    const staleLock = path.join(rootPath, '.git', 'config.lock');
    if (fs.existsSync(staleLock)) {
      fs.rmSync(staleLock);
      r = run('git', ['init'], { cwd: rootPath });
    }
  }
  if (r.status !== 0) throw new Error(`git init failed in ${rootPath}: ${r.stderr || r.error}`);
  const after = gitToplevel(rootPath);
  if (!after || !samePath(after, rootPath)) {
    throw new Error(`git top-level for ${rootPath} is ${after}, not the root itself`);
  }
  return 'initialised';
}

function ensureGitignore(rootPath) {
  const target = path.join(rootPath, '.gitignore');
  const block = [
    GITIGNORE_BEGIN,
    ...BINARY_GLOBS,
    'chekhov/session.json.tmp-*',
    GITIGNORE_END,
    '',
  ].join('\n');
  let text = '';
  try {
    text = fs.readFileSync(target, 'utf8');
  } catch {
    /* new file */
  }
  if (text.includes(GITIGNORE_BEGIN)) {
    const re = new RegExp(`${escapeRe(GITIGNORE_BEGIN)}[\\s\\S]*?${escapeRe(GITIGNORE_END)}\\n?`);
    text = text.replace(re, block);
  } else {
    text = text.length && !text.endsWith('\n') ? `${text}\n${block}` : `${text}${block}`;
  }
  fs.writeFileSync(target, text, 'utf8');
}

function ensureGitattributes(rootPath) {
  const target = path.join(rootPath, '.gitattributes');
  const lines = BINARY_GLOBS.map((g) => `${g} binary`);
  const block = [GITIGNORE_BEGIN, ...lines, GITIGNORE_END, ''].join('\n');
  let text = '';
  try {
    text = fs.readFileSync(target, 'utf8');
  } catch {
    /* new file */
  }
  if (text.includes(GITIGNORE_BEGIN)) {
    const re = new RegExp(`${escapeRe(GITIGNORE_BEGIN)}[\\s\\S]*?${escapeRe(GITIGNORE_END)}\\n?`);
    text = text.replace(re, block);
  } else {
    text = text.length && !text.endsWith('\n') ? `${text}\n${block}` : `${text}${block}`;
  }
  fs.writeFileSync(target, text, 'utf8');
}

/** The host write-denial rules, DERIVED from MANAGED_PATTERNS (one source). */
export function denyRulesForManagedFiles() {
  const rules = [];
  for (const p of MANAGED_PATTERNS) {
    for (const tool of ['Write', 'Edit', 'MultiEdit']) {
      rules.push(`${tool}(${p.glob})`);
    }
  }
  return rules;
}

function ensureWriteDenial(rootPath) {
  const dir = path.join(rootPath, '.claude');
  const target = path.join(dir, 'settings.json');
  fs.mkdirSync(dir, { recursive: true });
  let doc = {};
  try {
    doc = JSON.parse(fs.readFileSync(target, 'utf8'));
  } catch {
    /* new file */
  }
  if (!doc.permissions || typeof doc.permissions !== 'object') doc.permissions = {};
  const deny = new Set(Array.isArray(doc.permissions.deny) ? doc.permissions.deny : []);
  for (const rule of denyRulesForManagedFiles()) deny.add(rule);
  doc.permissions.deny = [...deny];
  fs.writeFileSync(target, `${JSON.stringify(doc, null, 2)}\n`, 'utf8');
}

/** The ONE consumer line a host ever learns (RIDER 6). */
export function consumerLine(projectId) {
  return `run \`chekhov ${projectId}\` and follow it.`;
}

function ensureConsumerParagraph(rootPath, projectId) {
  const target = path.join(rootPath, 'CLAUDE.md');
  const heading = '## Chekhov (the writing skill)';
  const paragraph = consumerLine(projectId);
  let text = '';
  try {
    text = fs.readFileSync(target, 'utf8');
  } catch {
    /* new file */
  }
  if (text.includes(heading)) {
    // Replace the paragraph under the heading with the one line.
    const re = new RegExp(`${escapeRe(heading)}[\\s\\S]*?(?=\\n#|$)`);
    text = text.replace(re, `${heading}\n\n${paragraph}\n`);
  } else {
    const lead = text.length ? `${text.replace(/\n*$/, '\n\n')}` : '# Project\n\n';
    text = `${lead}${heading}\n\n${paragraph}\n`;
  }
  fs.writeFileSync(target, text, 'utf8');
}

/**
 * Initialise every root in the manifest. Idempotent: extraction only when the
 * folder is missing; git init only when the root is not already its own
 * top-level; blocks and rules are merged, never duplicated.
 */
export function initRoots(manifestPath = DEFAULT_ROOTS_MANIFEST, opts = {}) {
  const manifest = loadRoots(manifestPath);
  const results = {};
  for (const [id, def] of Object.entries(manifest.roots)) {
    if (opts.only && !opts.only.includes(id)) continue;
    const rootPath = def.path;
    const result = { id, path: rootPath, actions: [] };
    if (!fs.existsSync(rootPath)) {
      if (def.zip && fs.existsSync(def.zip)) {
        extractZipTextOnly(def.zip, rootPath);
        result.actions.push('extracted-text-from-zip');
      } else {
        result.error = `root missing and no zip to extract: ${rootPath}`;
        results[id] = result;
        continue;
      }
    }
    result.actions.push(ensureOwnGitRepo(rootPath));
    ensureGitignore(rootPath);
    ensureGitattributes(rootPath);
    ensureWriteDenial(rootPath);
    ensureConsumerParagraph(rootPath, id);
    result.actions.push('gitignore', 'gitattributes', 'write-denial', 'consumer-line');
    if (def.zip && fs.existsSync(def.zip)) {
      const sha256 = sha256FileStreamless(def.zip);
      manifest.zips[id] = { path: def.zip, sha256, read_only: true };
      try {
        fs.chmodSync(def.zip, 0o444);
      } catch {
        manifest.zips[id].read_only = false;
      }
      result.actions.push('zip-checksum-recorded');
    }
    results[id] = result;
  }
  saveRoots(manifest, manifestPath);
  return { manifest, results };
}

/**
 * `chekhov roots --check-remote` — read the foundry remote's visibility once
 * through the gh CLI (no token ever lives in code) and journal the result.
 * Not private (or unknown) ⇒ fixture promote labels every fixture
 * reconstructed-deidentified.
 */
export function checkRemote(opts = {}) {
  const manifestPath = opts.manifestPath || DEFAULT_ROOTS_MANIFEST;
  const journalPath = opts.journalPath || DEFAULT_JOURNAL;
  const cwd = opts.cwd || path.join(LIB_DIR, '..');
  let visibility = 'unknown';
  let raw = null;
  const r = run('gh', ['repo', 'view', '--json', 'isPrivate'], { cwd, timeout: 20000 });
  if (r.status === 0 && r.stdout) {
    try {
      raw = JSON.parse(r.stdout);
      if (raw.isPrivate === true) visibility = 'private';
      else if (raw.isPrivate === false) visibility = 'public';
    } catch {
      visibility = 'unknown';
    }
  }
  const manifest = loadRoots(manifestPath);
  manifest.remote_visibility = visibility;
  saveRoots(manifest, manifestPath);
  const line = `\n- remote visibility (gh repo view --json isPrivate): ${visibility.toUpperCase()}${visibility !== 'private' ? ' — fixtures will be labelled reconstructed-deidentified' : ''} (${new Date().toISOString().slice(0, 10)})\n`;
  try {
    fs.appendFileSync(journalPath, line, 'utf8');
  } catch {
    /* journal missing: the visibility still lands in roots.json */
  }
  return { visibility, raw };
}
