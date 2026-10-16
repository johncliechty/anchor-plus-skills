// engine/secret-triage.mjs — Wave 2: the UNIVERSAL pre-LLM gate.
//
// Three properties define this module, and each one exists because the obvious
// cheaper version of it is a placebo:
//
//   1. IT RUNS BEFORE ANY LLM STAGE, OVER EVERY CANDIDATE. Not "before SAVE" —
//      before analyze, before the debate, before compression. A gate that only
//      guards the SAVE class still ships the key to a model in the analysis
//      prompt, which is the leak it was supposed to prevent.
//
//   2. IT SCANS PATH *AND* CONTENT, AND CONTENT IS SCANNED IN FULL. The LLM
//      stages skip files over a size cap and skip binaries; a scanner that
//      inherited those limits would miss an AWS key 30MB into a log — so this
//      module STREAMS the whole file, binary included, and is explicitly EXEMPT
//      from the read cap. The path rule is independent of content entirely: a
//      zero-byte or unreadable file named `id_rsa` is flagged on its name, since
//      "we could not read it" is not evidence that it is safe.
//
//   3. NO SECRET BYTES LEAVE IT. A trigger records the RULE and the LOCATION —
//      "AWS access key ID pattern at line 3" — and never the matched text, not
//      even partially masked. A four-character prefix of a live key is still key
//      material in a prompt, so nothing derived from the match is carried at all.
//      assertNoSecretBytes() makes that assertion mechanically checkable.
//
// Size and binary flags are a different, softer thing: QUARANTINE, not a block.
// Those findings stay approvable individually and are excluded from bulk
// approve, because "this is a 40MB file" is a reason to look, not a reason to
// refuse.

import fsp from 'node:fs/promises';
import path from 'node:path';
import { firstMatch, toPosixRel } from './glob.mjs';

/** Files above this many bytes are quarantined from the LLM stages (not blocked). */
export const LLM_READ_CAP_BYTES = 500 * 1024;

/** Streaming scan geometry. The overlap is what stops a token that straddles a
 *  chunk boundary from being invisible to every chunk. */
const CHUNK_BYTES = 256 * 1024;
const OVERLAP_BYTES = 4 * 1024;

/**
 * Secret-shaped NAMES. These fire with no content at all — a zero-byte
 * `id_rsa`, an unreadable `secrets/prod.pem`, a `.env` we lack permission to
 * open are all flagged.
 */
export const PATH_RULES = Object.freeze([
  { rule: 'ssh-private-key-name', patterns: ['id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', '**/id_rsa', '**/id_dsa', '**/id_ecdsa', '**/id_ed25519'], description: 'file name is a conventional SSH private key' },
  { rule: 'pem-key-material', patterns: ['*.pem', '*.key', '*.p12', '*.pfx', '*.jks', '*.keystore', '*.asc', '*.ppk'], description: 'file extension is conventional key/certificate material' },
  { rule: 'dotenv', patterns: ['.env', '.env.*', '**/.env', '**/.env.*'], description: 'file name is a dotenv environment file, which conventionally holds credentials' },
  { rule: 'secrets-directory', patterns: ['secrets/**', '**/secrets/**', 'secret/**', '**/secret/**', '.secrets/**', '**/.secrets/**'], description: 'path sits inside a directory named for secrets' },
  { rule: 'credentials-file', patterns: ['credentials', '**/credentials', '.aws/credentials', '**/.aws/credentials', '.npmrc', '**/.npmrc', '.pypirc', '**/.pypirc', '.netrc', '**/.netrc', '*.kdbx'], description: 'file name is a conventional credential store' },
  { rule: 'service-account-key', patterns: ['service-account*.json', '**/service-account*.json', '*serviceaccount*.json', '**/*-key.json'], description: 'file name matches a cloud service-account key export' },
]);

/**
 * Names that LOOK secret-shaped but are documented placeholders. They are
 * exempted from the PATH rules only — their CONTENT is still scanned, so an
 * `.env.example` someone pasted a real key into is still caught.
 */
export const PATH_RULE_EXEMPTIONS = Object.freeze([
  '.env.example', '**/.env.example', '.env.sample', '**/.env.sample',
  '.env.template', '**/.env.template', '.env.defaults', '**/.env.defaults',
  '*.pub', '**/*.pub',
]);

/** Content patterns. Deliberately anchored/lengthed to keep noise down. */
export const CONTENT_RULES = Object.freeze([
  { rule: 'private-key-header', re: /-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----/, description: 'PEM private-key header' },
  // The anchors are against the TOKEN'S OWN ALPHABET ([A-Z0-9]), not \b. A key
  // ID pasted into a lowercase blob — a log line, a base64-ish payload, minified
  // output — has no \b in front of it, and `\b` would silently miss it. Anchoring
  // on [A-Z0-9] still refuses to match a fragment of a LONGER uppercase token,
  // which is the noise the boundary was there to suppress.
  { rule: 'aws-access-key-id', re: /(?<![A-Z0-9])(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}(?![A-Z0-9])/, description: 'AWS access key ID' },
  { rule: 'aws-secret-access-key', re: /aws_secret_access_key\s*[:=]\s*["']?[A-Za-z0-9/+=]{40}\b/i, description: 'AWS secret access key assignment' },
  { rule: 'openai-key', re: /\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b/, description: 'OpenAI-style API key' },
  { rule: 'anthropic-key', re: /\bsk-ant-[A-Za-z0-9_-]{20,}\b/, description: 'Anthropic API key' },
  { rule: 'github-token', re: /\bgh[pousr]_[A-Za-z0-9]{36,}\b/, description: 'GitHub personal access / OAuth token' },
  { rule: 'google-api-key', re: /\bAIza[0-9A-Za-z_-]{35}\b/, description: 'Google API key' },
  { rule: 'slack-token', re: /\bxox[abopsr]-[A-Za-z0-9-]{10,}\b/, description: 'Slack token' },
  { rule: 'stripe-key', re: /\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b/, description: 'Stripe secret key' },
  { rule: 'jwt', re: /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/, description: 'JSON Web Token' },
  { rule: 'ssh-private-key-body', re: /\bPuTTY-User-Key-File-\d/, description: 'PuTTY private key body' },
]);

/**
 * Assignments whose VALUE is judged by entropy. A password of "changeme" is not
 * a credential leak; 40 random base64 characters assigned to `api_key` is.
 */
const ASSIGNMENT_RE = /(?:^|[^A-Za-z0-9_])((?:api[_-]?key|secret|secret[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|private[_-]?key|password|passwd|pwd|token))\s*[:=]\s*["']?([A-Za-z0-9+/=_-]{20,})["']?/i;

/** Shannon entropy in bits/character. */
export function shannonEntropy(s) {
  if (!s || s.length === 0) return 0;
  const counts = new Map();
  for (const ch of s) counts.set(ch, (counts.get(ch) || 0) + 1);
  let h = 0;
  for (const n of counts.values()) {
    const p = n / s.length;
    h -= p * Math.log2(p);
  }
  return h;
}

/** Above this, a 20+ character assignment value reads as generated, not typed. */
export const ENTROPY_THRESHOLD = 3.6;

function pathRuleFor(rel) {
  const p = toPosixRel(rel);
  if (firstMatch(PATH_RULE_EXEMPTIONS, p)) return null;
  for (const r of PATH_RULES) {
    const hit = firstMatch(r.patterns, p);
    if (hit) return { rule: r.rule, pattern: hit, description: r.description };
  }
  return null;
}

/**
 * Scan one file's bytes IN FULL, streaming, regardless of size or binaryness.
 * Returns triggers carrying rule + line number only.
 */
async function scanContent(absPath, { fs = fsp } = {}) {
  const triggers = [];
  const seen = new Set();
  let binary = false;
  let bytes = 0;
  let handle = null;

  const record = (rule, description, line, cls) => {
    if (seen.has(rule)) return;
    seen.add(rule);
    triggers.push({ rule, class: cls, description, line });
  };

  try {
    handle = await fs.open(absPath, 'r');
    const buf = Buffer.allocUnsafe(CHUNK_BYTES);
    let carry = '';
    let carryLines = 0;
    let position = 0;
    let firstChunk = true;

    for (;;) {
      const { bytesRead } = await handle.read(buf, 0, CHUNK_BYTES, position);
      if (bytesRead <= 0) break;
      bytes += bytesRead;
      position += bytesRead;
      const slice = buf.subarray(0, bytesRead);
      if (firstChunk && slice.includes(0)) binary = true;
      firstChunk = false;

      // latin1 keeps a 1:1 byte↔char mapping, so a pattern is found at the same
      // place in a binary blob as in a text file and no byte is lost to a
      // decoder's replacement character.
      const text = carry + slice.toString('latin1');
      const baseLine = carryLines;

      for (const r of CONTENT_RULES) {
        const m = r.re.exec(text);
        if (m) record(r.rule, r.description, baseLine + countLines(text, m.index), 'content');
      }
      const am = ASSIGNMENT_RE.exec(text);
      if (am && shannonEntropy(am[2]) >= ENTROPY_THRESHOLD) {
        record('high-entropy-assignment',
          `a value assigned to \`${am[1]}\` is ${am[2].length} characters of high-entropy text`,
          baseLine + countLines(text, am.index), 'entropy');
      }

      if (bytesRead < CHUNK_BYTES) break;
      // Carry the tail forward so a token straddling the boundary is still seen
      // whole by the next pass.
      const keepFrom = Math.max(0, text.length - OVERLAP_BYTES);
      carryLines = baseLine + countLines(text, keepFrom);
      carry = text.slice(keepFrom);
    }
    return { triggers, binary, bytes, error: null };
  } catch (err) {
    // Unreadable is a COVERAGE GAP, never an all-clear. The caller keeps any
    // path-rule trigger and records the error.
    return { triggers, binary, bytes, error: err && err.message ? err.message : String(err) };
  } finally {
    if (handle) { try { await handle.close(); } catch { /* nothing to do */ } }
  }
}

function countLines(text, index) {
  let n = 0;
  for (let i = 0; i < index && i < text.length; i++) if (text.charCodeAt(i) === 10) n++;
  return n + 1;
}

/**
 * Triage one path.
 *
 * @param {{rootPath: string, rel: string, fs?: object, size?: number|null, allow?: string[]}} opts
 * @returns {Promise<object>} the verdict (see the module header for the contract)
 */
export async function triageFile({ rootPath, rel, fs = fsp, size = null, allow = [] }) {
  const p = toPosixRel(rel);
  const abs = path.join(path.resolve(rootPath), p);

  let stSize = size;
  if (stSize === null || stSize === undefined) {
    try {
      const st = await fs.stat(abs);
      stSize = st.size;
    } catch { stSize = null; }
  }

  const triggers = [];
  const nameHit = pathRuleFor(p);
  if (nameHit) {
    triggers.push({
      rule: nameHit.rule,
      class: 'path',
      description: `${nameHit.description} (matched \`${nameHit.pattern}\`)`,
      line: null,
    });
  }

  const scan = await scanContent(abs, { fs });
  triggers.push(...scan.triggers);

  // The .tidy-idy.toml override is deliberate, auditable and NEXT-RUN only: it
  // does not un-flag anything, it records that a human already adjudicated this
  // path so the block is not enforced.
  const overridden = Boolean(firstMatch(allow || [], p));
  const flagged = triggers.length > 0;

  const effectiveSize = stSize === null ? scan.bytes : stSize;
  const oversize = effectiveSize !== null && effectiveSize > LLM_READ_CAP_BYTES;

  return {
    path: p,
    absolutePath: abs,
    size: effectiveSize,
    binary: scan.binary,
    oversize,
    /** Quarantine ≠ block: individually confirmable, out of bulk-approve. */
    quarantine: scan.binary ? 'binary' : (oversize ? 'size' : null),
    flagged,
    overridden,
    /** The gate's verdict for the LLM stages: blocked content never reaches one. */
    blockedFromLlm: flagged && !overridden,
    blockedFromSave: flagged && !overridden,
    triggers,
    maskedTriggerText: describeTriggers(triggers),
    readError: scan.error,
    scannedBytes: scan.bytes,
    scanExemptFromReadCap: true,
  };
}

/**
 * Triage many paths. This is the gate the pipeline runs before any LLM stage.
 *
 * @param {{rootPath: string, paths: string[], fs?: object, sizes?: object, allow?: string[]}} opts
 * @returns {Promise<Map<string, object>>}
 */
export async function triageAll({ rootPath, paths = [], fs = fsp, sizes = {}, allow = [] }) {
  const out = new Map();
  for (const rel of paths) {
    const p = toPosixRel(rel);
    const known = sizes && sizes[p] ? sizes[p].size : null;
    out.set(p, await triageFile({ rootPath, rel: p, fs, size: known, allow }));
  }
  return out;
}

/** A human sentence naming WHAT fired and WHERE — never the matched text. */
export function describeTriggers(triggers) {
  if (!triggers || triggers.length === 0) return null;
  return triggers
    .map((t) => (t.line ? `${t.description} at line ${t.line}` : t.description))
    .join('; ');
}

/**
 * The per-class remediation. The distinction is the whole point of Amendment
 * B's carried finding: a bare add-to-.gitignore does NOT stop an
 * ALREADY-TRACKED file from being committed — git ignores ignore rules for
 * paths already in the index — so offering one for a tracked secret is a
 * placebo. A tracked secret gets the `git rm --cached` untrack op instead.
 *
 * @param {{path: string, trackingClass: string, triggers?: object[]}} opts
 */
export function buildRemediation({ path: rel, trackingClass, triggers = [] }) {
  const p = toPosixRel(rel);
  const relocation = `move \`${p}\` outside the repository (or into a secret store / your OS keychain) and reference it by environment variable — the safest fix, and the only one that removes the file from this tree entirely`;
  const configOverride = {
    file: '.tidy-idy.toml',
    snippet: `[secrets]\nallow = ["${p}"]`,
    effect: 'takes effect on the NEXT run only — a deliberate, auditable config edit, never a click-through',
  };

  if (trackingClass === 'tracked-clean' || trackingClass === 'tracked-modified'
    || trackingClass === 'staged' || trackingClass === 'unmerged') {
    return {
      trackingClass,
      bareGitignoreOffered: false,
      bareGitignoreRefusedBecause:
        'git honours .gitignore only for paths it is not already tracking, so writing an ignore line for an ALREADY-TRACKED file changes nothing about whether it commits — offering it would be a placebo',
      ops: [{
        kind: 'untrack',
        approvable: true,
        command: `git rm --cached -- ${p}`,
        gitignoreLine: p,
        summary: `untrack \`${p}\` (git rm --cached) and add it to .gitignore`,
        declaresClassTransition: { from: 'tracked', to: 'untracked' },
        tileMustState: [
          'this is an INDEX-CLASS change: the file stops being tracked and stays on disk, untracked',
          'HISTORY REWRITE IS OUT OF SCOPE — every commit that already contains this file still contains it; rotate the credential and, if needed, rewrite history with a dedicated tool',
        ],
      }],
      relocation,
      configOverride,
      historyRewrite: 'out of scope for tidy-idy — the credential should be treated as compromised and rotated',
      triggerSummary: describeTriggers(triggers),
    };
  }

  return {
    trackingClass,
    bareGitignoreOffered: true,
    ops: [{
      kind: 'add-to-gitignore',
      approvable: true,
      gitignoreLine: p,
      summary: `add \`${p}\` to .gitignore so it can never be staged by accident`,
      declaresClassTransition: { from: 'untracked', to: 'ignored' },
      tileMustState: [
        'the file itself is untouched on disk; only .gitignore changes',
        'this works precisely because git is not already tracking this path',
      ],
    }],
    relocation,
    configOverride,
    historyRewrite: 'not applicable — git has never held this file',
    triggerSummary: describeTriggers(triggers),
  };
}

/**
 * Mechanical proof that a value carries no secret bytes. Used by the tests that
 * assert the assembled LLM context is clean, and cheap enough to call on the
 * findings themselves.
 *
 * @param {any} value anything JSON-serialisable
 * @param {string[]} secrets the literal secret strings that must not appear
 * @returns {{clean: boolean, hits: string[]}}
 */
export function assertNoSecretBytes(value, secrets = []) {
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  const hits = [];
  for (const s of secrets) {
    if (!s) continue;
    if (text.includes(s)) { hits.push(s); continue; }
    // Partial disclosure counts too: a prefix of a live key is still key
    // material. Anything longer than 8 characters of the secret is a hit.
    for (let len = s.length - 1; len >= 8; len--) {
      if (text.includes(s.slice(0, len))) { hits.push(`${s.slice(0, 4)}… (${len}-char prefix)`); break; }
    }
  }
  return { clean: hits.length === 0, hits };
}

export default { triageFile, triageAll, buildRemediation, assertNoSecretBytes, PATH_RULES, CONTENT_RULES };
