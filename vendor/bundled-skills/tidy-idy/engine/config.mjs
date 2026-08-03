// engine/config.mjs — Wave 1: `.tidy-idy.toml`, strictly additive.
//
// Two rules, both testable:
//   1. STRICTLY ADDITIVE. The config vocabulary contains no key that can remove
//      or narrow a built-in protected pattern. Subtractive-looking keys are not
//      "ignored" (which would be a silent lie to the user who wrote them) —
//      they are a PARSE ERROR naming the key.
//   2. PARSE ERRORS ARE A FAILED STAGE, never a silent fallback to defaults.
//      A malformed config means we do not know what the user asked for, and a
//      hygiene tool that guesses in that situation is the failure mode the whole
//      plan is written against.
//
// The parser is a deliberately small TOML subset (the skill ships as a bare
// folder with no package.json, so no dependency is available): comments, table
// headers, string / integer / float / boolean / string-array values, and
// multi-line arrays. Anything outside the subset is a loud parse error rather
// than a quiet misreading.

import fs from 'node:fs/promises';
import path from 'node:path';

export const CONFIG_FILENAME = '.tidy-idy.toml';

/** Thrown for any malformed or subtractive config. Carries the line number. */
export class ConfigParseError extends Error {
  constructor(message, { line = null, key = null, file = null } = {}) {
    super(message);
    this.name = 'ConfigParseError';
    this.line = line;
    this.key = key;
    this.file = file;
  }
}

/**
 * Keys that would narrow the protected set. Present in the vocabulary ONLY so
 * that writing one produces an explicit refusal rather than silent no-op.
 */
export const SUBTRACTIVE_KEYS = Object.freeze([
  'unprotect', 'unprotect_patterns', 'allow_remove', 'allow_removal',
  'remove_protected', 'disable_protection', 'protection_off', 'override_protected',
  'exclude_protected', 'clear_protected', 'replace_protected', 'ignore_protected',
]);

/** Tables and keys the config vocabulary actually understands. */
const SCHEMA = {
  protect: { patterns: 'string[]' },
  exclude: { patterns: 'string[]' },
  limits: { max_files: 'integer', max_bytes: 'integer', max_file_bytes: 'integer' },
  run: { mode: 'string' },
  // Wave 2. `[secrets] allow` is the per-path false-positive override from owned
  // decision #9. It does NOT narrow the protected set — protection and secret
  // triage are different predicates, and this key cannot reach protection.mjs at
  // all — so strict additivity is untouched. It is deliberately a CONFIG EDIT
  // that takes effect on the NEXT run rather than a click-through, because
  // "commit this thing that looks like a live credential" should cost a
  // reviewable line in a file, not one button press.
  secrets: { allow: 'string[]' },
  // Wave 5. The pre-scan cost gate's per-project thresholds and extra generic
  // exclusions. `enabled = false` turns the GATE off (the run then uses full
  // scope); it cannot turn PROTECTION off — different predicate, different
  // module, and this key cannot reach protection.mjs at all, so strict
  // additivity is untouched. `exclude_patterns` only ever ADDS exclusions.
  cost: { enabled: 'boolean', max_files: 'integer', max_bytes: 'integer', exclude_patterns: 'string[]' },
  // Wave 5. The tool-owned panel server's lifecycle knobs.
  panel: { idle_timeout_seconds: 'integer', heartbeat_gap_seconds: 'integer', port: 'integer' },
  // Wave 7. The investigator terminal's default engine (claude | gemini | grok).
  // It is ONLY a launch-spec command-template selector — it cannot reach
  // protection, secret triage, or any Apply decision, so strict additivity is
  // untouched. Another engine is a new ENGINE_TEMPLATES row plus this value; the
  // panel's per-click toggle overrides it per launch.
  investigator: { engine: 'string' },
};

function parseScalar(raw, lineNo) {
  const v = raw.trim();
  if (/^"([^"\\]|\\.)*"$/.test(v)) return JSON.parse(v);
  if (/^'[^']*'$/.test(v)) return v.slice(1, -1);
  if (v === 'true') return true;
  if (v === 'false') return false;
  if (/^[+-]?\d+$/.test(v)) return Number.parseInt(v, 10);
  if (/^[+-]?\d*\.\d+$/.test(v)) return Number.parseFloat(v);
  throw new ConfigParseError(`unsupported value \`${v}\` (line ${lineNo}) — .tidy-idy.toml supports strings, integers, floats, booleans and string arrays`, { line: lineNo });
}

function parseArray(body, lineNo) {
  const out = [];
  let i = 0;
  while (i < body.length) {
    const ch = body[i];
    if (ch === ',' || /\s/.test(ch)) { i++; continue; }
    if (ch === '"' || ch === "'") {
      const quote = ch;
      let j = i + 1;
      let buf = '';
      while (j < body.length && body[j] !== quote) {
        if (quote === '"' && body[j] === '\\') { buf += body[j] + body[j + 1]; j += 2; continue; }
        buf += body[j];
        j++;
      }
      if (j >= body.length) throw new ConfigParseError(`unterminated string in array (line ${lineNo})`, { line: lineNo });
      out.push(quote === '"' ? JSON.parse(`"${buf}"`) : buf);
      i = j + 1;
      continue;
    }
    // Non-string array member: read to the next comma and scalar-parse it.
    let j = i;
    while (j < body.length && body[j] !== ',') j++;
    out.push(parseScalar(body.slice(i, j), lineNo));
    i = j;
  }
  return out;
}

/**
 * Parse a `.tidy-idy.toml` document. Throws ConfigParseError on anything it
 * does not understand — including a subtractive key.
 *
 * @param {string} text
 * @param {{file?: string}} [opts]
 * @returns {object} nested plain object, e.g. {protect: {patterns: [...]}}
 */
export function parseTidyIdyToml(text, opts = {}) {
  const file = opts.file || CONFIG_FILENAME;
  const result = {};
  let table = null;
  const lines = String(text).split(/\r?\n/);

  for (let n = 0; n < lines.length; n++) {
    let line = lines[n];
    const lineNo = n + 1;
    // Strip comments that are not inside a string.
    let inStr = null;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (inStr) {
        if (c === '\\' && inStr === '"') { i++; continue; }
        if (c === inStr) inStr = null;
      } else if (c === '"' || c === "'") inStr = c;
      else if (c === '#') { line = line.slice(0, i); break; }
    }
    line = line.trim();
    if (!line) continue;

    const tableMatch = /^\[([A-Za-z0-9_.-]+)\]$/.exec(line);
    if (tableMatch) {
      const name = tableMatch[1];
      assertNotSubtractive(name, lineNo, file);
      if (!Object.prototype.hasOwnProperty.call(SCHEMA, name)) {
        throw new ConfigParseError(`unknown table [${name}] (line ${lineNo}) in ${file} — known tables: ${Object.keys(SCHEMA).join(', ')}`, { line: lineNo, key: name, file });
      }
      table = name;
      result[name] = result[name] || {};
      continue;
    }

    const eq = line.indexOf('=');
    if (eq === -1) {
      throw new ConfigParseError(`malformed line ${lineNo} in ${file}: \`${line}\` — expected \`key = value\` or a [table] header`, { line: lineNo, file });
    }
    const key = line.slice(0, eq).trim();
    let valueText = line.slice(eq + 1).trim();
    assertNotSubtractive(key, lineNo, file);

    if (!table) {
      throw new ConfigParseError(`key \`${key}\` at line ${lineNo} in ${file} sits outside any [table] — .tidy-idy.toml has no top-level keys`, { line: lineNo, key, file });
    }
    const expected = SCHEMA[table][key];
    if (!expected) {
      throw new ConfigParseError(`unknown key \`${table}.${key}\` (line ${lineNo}) in ${file} — known keys for [${table}]: ${Object.keys(SCHEMA[table]).join(', ')}`, { line: lineNo, key: `${table}.${key}`, file });
    }

    let value;
    if (valueText.startsWith('[')) {
      // Multi-line array support: keep consuming lines until brackets balance.
      let depth = 0;
      let buf = '';
      let m = n;
      let done = false;
      while (m < lines.length && !done) {
        const seg = m === n ? valueText : lines[m];
        for (const c of seg) {
          if (c === '[') { depth++; if (depth === 1) continue; }
          if (c === ']') { depth--; if (depth === 0) { done = true; break; } }
          buf += c;
        }
        if (!done) { buf += '\n'; m++; }
      }
      if (!done) throw new ConfigParseError(`unterminated array for \`${table}.${key}\` starting at line ${lineNo} in ${file}`, { line: lineNo, key, file });
      n = m;
      value = parseArray(buf, lineNo);
      if (expected === 'string[]') {
        for (const v of value) {
          if (typeof v !== 'string') {
            throw new ConfigParseError(`\`${table}.${key}\` must be an array of strings (line ${lineNo}) in ${file}`, { line: lineNo, key, file });
          }
        }
      }
    } else {
      value = parseScalar(valueText, lineNo);
      if (expected === 'string[]') {
        throw new ConfigParseError(`\`${table}.${key}\` must be an array of strings (line ${lineNo}) in ${file}`, { line: lineNo, key, file });
      }
      if (expected === 'integer' && !Number.isInteger(value)) {
        throw new ConfigParseError(`\`${table}.${key}\` must be an integer (line ${lineNo}) in ${file}`, { line: lineNo, key, file });
      }
      if (expected === 'boolean' && typeof value !== 'boolean') {
        throw new ConfigParseError(`\`${table}.${key}\` must be true or false (line ${lineNo}) in ${file}`, { line: lineNo, key, file });
      }
    }
    result[table][key] = value;
  }

  return result;
}

function assertNotSubtractive(name, lineNo, file) {
  const lowered = String(name).toLowerCase();
  for (const bad of SUBTRACTIVE_KEYS) {
    if (lowered === bad || lowered.endsWith(`.${bad}`)) {
      throw new ConfigParseError(
        `\`${name}\` (line ${lineNo}) in ${file} would narrow the built-in protected set. ` +
        '.tidy-idy.toml is STRICTLY ADDITIVE: it can add protected patterns and exclusions, never remove them. ' +
        'Refusing the whole config rather than silently ignoring the key.',
        { line: lineNo, key: name, file });
    }
  }
}

/**
 * Load the config for a root. Returns {config, present, path}. A missing file
 * is NOT an error (defaults apply); a malformed one throws ConfigParseError,
 * which the pipeline turns into a failed stage.
 */
export async function loadConfig(rootPath, { readFile = fs.readFile } = {}) {
  const file = path.join(rootPath, CONFIG_FILENAME);
  let text;
  try {
    text = await readFile(file, 'utf8');
  } catch (err) {
    if (err && (err.code === 'ENOENT' || err.code === 'ENOTDIR')) {
      return { config: {}, present: false, path: file };
    }
    throw new ConfigParseError(`could not read ${file}: ${err.message}`, { file });
  }
  return { config: parseTidyIdyToml(text, { file }), present: true, path: file };
}
