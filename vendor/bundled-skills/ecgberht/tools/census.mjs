#!/usr/bin/env node
/**
 * W2 - the portfolio census: inventory-v1 measured against the REAL portfolio.
 *
 * WHY. Wave 4 has to name numeric caps and Wave 3 has to write failure rows per class.
 * Both are guesses unless somebody counts first, and a guess that ships as a cap is a
 * refusal path nobody can predict. So this tool walks registered roots through the frozen
 * inventory-v1 discovery paths and reports, per class:
 *
 *     discovered = parsed + unparseable + unclassified
 *
 * That equation is asserted here, not assumed. It is the whole reason UNCLASSIFIED is a
 * bucket rather than a filter: a file the table does not name still shows up in the count
 * with its path, so "we ingest a closed set" and "we lost track of that file" can never be
 * the same observation.
 *
 * Skipped-with-hazard is reported on its OWN axis. A reparse point that was not followed
 * is not an unparseable file and must not be folded into one - the moment a hazard can
 * hide inside an integrity code, the NG-2 guarantees become unmeasurable.
 *
 * Stdlib only, zero runtime dependencies, and it writes nothing unless asked with --out.
 *
 * Usage:
 *   node tools/census.mjs --root <path> [--root <path> ...] [--json|--markdown]
 *                         [--out <file>] [--max-entries N]
 *   STEWARD_CENSUS_ROOTS="<path>;<path>" node tools/census.mjs
 */

import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import {
  HAZARDS_BEYOND_AXIS,
  INVENTORY_CLASSES,
  INVENTORY_V1,
  INVENTORY_VERSION,
  PATH_HAZARD_AXIS,
  PRESENCE,
  UNCLASSIFIED,
  classNameForRelPath,
  inventoryEntryFor,
  parseInventoryFile,
  probeLegacyCarriers,
  walkRoot,
} from '../engine/portfolio/inventory.mjs';

/** The census report's declared schema id. */
export const CENSUS_SCHEMA = 'portfolio-census-v0';

/** Env vars consulted for roots, in order. No absolute path is ever baked into this file. */
export const ROOT_ENV_VARS = Object.freeze(['STEWARD_CENSUS_ROOTS', 'ECGBERHT_STRIP_ROOTS']);

/** Named exit statuses. A census that cannot run says why rather than printing zeros. */
export const CENSUS_STATUS = Object.freeze({
  OK: 'CENSUS_OK',
  NO_ROOTS: 'CENSUS_NO_ROOTS',
  TOTALITY_VIOLATED: 'CENSUS_TOTALITY_VIOLATED',
});

const MS_PER_DAY = 86400000;

// -- counters -----------------------------------------------------------------

/** @returns {object} a zeroed per-class counter block */
function emptyCounts() {
  return {
    discovered: 0,
    parsed: 0,
    unparseable: 0,
    unclassified: 0,
    skipped: 0,
    records: 0,
    reasons: {},
    hazards: {},
  };
}

/** @returns {Record<string, object>} one counter block per class plus the UNCLASSIFIED bucket */
function emptyPerClass() {
  const per = {};
  for (const name of [...INVENTORY_CLASSES, UNCLASSIFIED]) per[name] = emptyCounts();
  return per;
}

/** @param {object} counts @param {string} key */
function bump(counts, field, key) {
  counts[field][key] = (counts[field][key] ?? 0) + 1;
}

// -- growth -------------------------------------------------------------------

/** @param {unknown} ts @returns {number|null} epoch ms, or null when unusable */
export function toEpochMs(ts) {
  if (typeof ts === 'number' && Number.isFinite(ts)) return ts;
  if (typeof ts !== 'string' || ts.trim() === '') return null;
  const parsed = Date.parse(ts);
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * Volume and growth for one class, in a form W4 can cite numerically.
 *
 * Honest about its own basis: with fewer than two dated items there is no rate, and this
 * says so with a named reason rather than reporting a confident zero.
 *
 * @param {Array<number>} stamps epoch ms values
 * @param {number} items total items observed (dated or not)
 * @returns {object}
 */
export function growthFrom(stamps, items) {
  const dated = stamps.filter((s) => typeof s === 'number' && Number.isFinite(s)).sort((a, b) => a - b);
  if (items === 0) {
    return { items: 0, dated: 0, first: null, last: null, window_days: null, per_day: null, projected_365d: null, basis: 'NO_ITEMS_OBSERVED' };
  }
  if (dated.length < 2) {
    return {
      items,
      dated: dated.length,
      first: dated.length ? new Date(dated[0]).toISOString() : null,
      last: dated.length ? new Date(dated[dated.length - 1]).toISOString() : null,
      window_days: null,
      per_day: null,
      projected_365d: null,
      basis: 'TOO_FEW_DATED_ITEMS',
    };
  }
  const first = dated[0];
  const last = dated[dated.length - 1];
  const rawDays = (last - first) / MS_PER_DAY;
  const windowDays = Math.round(rawDays * 100) / 100;
  const denominator = rawDays < 1 ? 1 : rawDays;
  const perDay = Math.round((items / denominator) * 100) / 100;
  return {
    items,
    dated: dated.length,
    first: new Date(first).toISOString(),
    last: new Date(last).toISOString(),
    window_days: windowDays,
    per_day: perDay,
    projected_365d: Math.round(perDay * 365),
    basis: rawDays < 1 ? 'WINDOW_UNDER_ONE_DAY_RATE_IS_AN_UPPER_BOUND' : 'OBSERVED_TS_SPAN',
  };
}

// -- the census ---------------------------------------------------------------

/**
 * Walk the given roots against inventory-v1 and count everything.
 *
 * @param {{
 *   roots?: string[], labels?: string[], maxEntries?: number,
 *   fs?: object, readdir?: Function, parse?: Function, probe?: Function
 * }} [opts]
 * @returns {object} the census report
 */
export function runCensus(opts = {}) {
  const roots = (Array.isArray(opts.roots) ? opts.roots : []).filter(Boolean);
  const parseFile = opts.parse ?? parseInventoryFile;
  const probe = opts.probe ?? probeLegacyCarriers;

  const perClass = emptyPerClass();
  const stamps = {};
  for (const name of INVENTORY_CLASSES) stamps[name] = [];

  const rootReports = [];
  const unclassifiedPaths = [];
  const unparseable = [];
  const hazardRows = [];
  const gateItems = [];

  for (let i = 0; i < roots.length; i += 1) {
    const label = Array.isArray(opts.labels) && opts.labels[i] ? opts.labels[i] : path.basename(path.resolve(roots[i]));
    const walk = walkRoot(roots[i], {
      fs: opts.fs,
      readdir: opts.readdir,
      maxEntries: opts.maxEntries,
      label,
    });

    const rootCounts = emptyPerClass();

    for (const file of walk.files) {
      const className = file.class ?? UNCLASSIFIED;
      const counts = perClass[className];
      const rootCount = rootCounts[className];
      counts.discovered += 1;
      rootCount.discovered += 1;

      // file.hazards is deliberately NOT counted here: every one of those rows also lives
      // in walk.hazards below, and counting both would double the histogram.

      if (className === UNCLASSIFIED) {
        counts.unclassified += 1;
        rootCount.unclassified += 1;
        unclassifiedPaths.push({ root: label, path: file.rel });
        continue;
      }

      const result = parseFile(className, file.abs);
      if (result.ok) {
        counts.parsed += 1;
        rootCount.parsed += 1;
        counts.records += result.record_count;
        rootCount.records += result.record_count;
        for (const record of result.records) {
          const ts = toEpochMs(record.ts ?? record.registered_at ?? null);
          if (ts !== null) stamps[className].push(ts);
        }
      } else {
        counts.unparseable += 1;
        rootCount.unparseable += 1;
        bump(counts, 'reasons', result.reason);
        bump(rootCount, 'reasons', result.reason);
        unparseable.push({
          root: label,
          path: file.rel,
          class: className,
          reason: result.reason,
          detail: result.detail ?? null,
        });
      }
    }

    for (const hazard of walk.hazards) {
      const className = hazard.path === '.' ? UNCLASSIFIED : classNameForRelPath(hazard.path);
      bump(perClass[className], 'hazards', hazard.code);
      bump(rootCounts[className], 'hazards', hazard.code);
      if (hazard.skipped) {
        perClass[className].skipped += 1;
        rootCounts[className].skipped += 1;
      }
      hazardRows.push({ root: label, ...hazard });
    }

    if (walk.presence === PRESENCE.LIVE) {
      gateItems.push(...probe(walk.root, opts.fs ?? fs).map((m) => ({ ...m, root: label })));
    }

    rootReports.push({
      label,
      presence: walk.presence,
      reason: walk.reason,
      entries_seen: walk.entries_seen,
      truncated: walk.truncated,
      files_discovered: walk.files.length,
      excluded: walk.excluded,
      hazard_count: walk.hazards.length,
      per_class: rootCounts,
      order_length: walk.order.length,
    });
  }

  // Gate item: a frozen class the real portfolio never produced a single file for. Silence
  // here would let W4 set a cap for a class it never measured.
  for (const name of INVENTORY_CLASSES) {
    if (perClass[name].discovered === 0) {
      const entry = inventoryEntryFor(name);
      gateItems.push({
        code: 'CLASS_UNOBSERVED',
        class: name,
        expected_path: entry ? entry.spec : null,
        observed_carrier: null,
        observed_items: 0,
        detail:
          `No file was discovered at ${entry ? entry.spec : name} under any walked root. ` +
          'The discovery path is unproven against the real portfolio: ratify or amend it, ' +
          'do not assume it.',
      });
    }
  }

  // Gate item: hazards this wave had to name that STATUS-v1's frozen path-hazard axis does
  // not yet carry. W3 either adopts them or renames them; W2 does not decide it silently.
  const observedCodes = new Set(hazardRows.map((h) => h.code));
  for (const code of HAZARDS_BEYOND_AXIS) {
    if (!observedCodes.has(code)) continue;
    gateItems.push({
      code: 'HAZARD_CODE_OUTSIDE_AXIS',
      class: null,
      expected_path: null,
      observed_carrier: code,
      observed_items: hazardRows.filter((h) => h.code === code).length,
      detail:
        `${code} was emitted by the NG-2 walk but is not one of the three path-hazard codes ` +
        `frozen for STATUS-v1 (${PATH_HAZARD_AXIS.join(', ')}). W3 must adopt or rename it; ` +
        'it is not laundered into a neighbouring code here.',
    });
  }

  const totals = { discovered: 0, parsed: 0, unparseable: 0, unclassified: 0, skipped: 0, records: 0 };
  const perClassTotality = {};
  for (const [name, counts] of Object.entries(perClass)) {
    for (const field of ['discovered', 'parsed', 'unparseable', 'unclassified', 'skipped', 'records']) {
      totals[field] += counts[field];
    }
    const accounted = counts.parsed + counts.unparseable + counts.unclassified;
    perClassTotality[name] = { discovered: counts.discovered, accounted, ok: accounted === counts.discovered };
  }
  const totalityOk =
    totals.parsed + totals.unparseable + totals.unclassified === totals.discovered &&
    Object.values(perClassTotality).every((t) => t.ok);

  const growth = {};
  for (const name of INVENTORY_CLASSES) {
    growth[name] = growthFrom(stamps[name], perClass[name].records);
  }

  return {
    schema: CENSUS_SCHEMA,
    inventory_version: INVENTORY_VERSION,
    status: totalityOk ? CENSUS_STATUS.OK : CENSUS_STATUS.TOTALITY_VIOLATED,
    roots: rootReports,
    per_class: perClass,
    totals,
    totality: {
      equation: 'parsed + unparseable + unclassified == discovered',
      ok: totalityOk,
      per_class: perClassTotality,
      left: totals.parsed + totals.unparseable + totals.unclassified,
      right: totals.discovered,
    },
    hazards: hazardRows,
    unclassified_paths: unclassifiedPaths,
    unparseable,
    growth,
    gate_items: gateItems,
  };
}

// -- rendering ----------------------------------------------------------------

/** @param {object} counts @returns {string} */
function reasonSummary(counts) {
  const entries = Object.entries(counts.reasons).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return entries.length ? entries.map(([r, n]) => `${r} x${n}`).join(', ') : '-';
}

/**
 * @param {object} report @returns {string} the plain-text report
 */
export function renderCensusText(report) {
  const lines = [];
  lines.push(`portfolio census (${report.schema}) against ${report.inventory_version}`);
  lines.push('');

  for (const root of report.roots) {
    const note = root.presence === PRESENCE.LIVE ? '' : ` (${root.reason})`;
    lines.push(`root ${root.label}: ${root.presence}${note} - ${root.entries_seen} entries seen${root.truncated ? ' [TRUNCATED]' : ''}`);
  }
  lines.push('');

  lines.push('class                discovered  parsed  unparseable  unclassified  skipped  records');
  for (const [name, counts] of Object.entries(report.per_class)) {
    lines.push(
      [
        name.padEnd(20),
        String(counts.discovered).padStart(10),
        String(counts.parsed).padStart(7),
        String(counts.unparseable).padStart(12),
        String(counts.unclassified).padStart(13),
        String(counts.skipped).padStart(8),
        String(counts.records).padStart(8),
      ].join(''),
    );
  }
  const withReasons = Object.entries(report.per_class).filter(([, c]) => Object.keys(c.reasons).length);
  if (withReasons.length) {
    lines.push('');
    lines.push('unparseable reasons by class:');
    for (const [name, counts] of withReasons) lines.push(`  ${name.padEnd(16)} ${reasonSummary(counts)}`);
  }

  lines.push('');
  lines.push(
    `totality: ${report.totality.equation} -> ${report.totality.left} == ${report.totality.right} : ` +
      `${report.totality.ok ? 'HOLDS' : 'VIOLATED'}`,
  );
  lines.push('');

  lines.push('volume and growth (the numbers W4 cites):');
  for (const [name, g] of Object.entries(report.growth)) {
    lines.push(
      `  ${name.padEnd(16)} items=${g.items} window_days=${g.window_days ?? 'n/a'} ` +
        `per_day=${g.per_day ?? 'n/a'} projected_365d=${g.projected_365d ?? 'n/a'} basis=${g.basis}`,
    );
  }

  if (report.hazards.length) {
    lines.push('');
    lines.push('hazards (named, never silent):');
    for (const h of report.hazards) {
      lines.push(`  ${h.code} ${h.root}:${h.path}${h.target ? ` -> ${h.target}` : ''}${h.skipped ? ' [skipped]' : ''}`);
    }
  }

  if (report.unparseable.length) {
    lines.push('');
    lines.push('unparseable (with reason):');
    for (const u of report.unparseable) {
      lines.push(`  ${u.class} ${u.root}:${u.path} - ${u.reason}${u.detail ? ` (${u.detail})` : ''}`);
    }
  }

  if (report.unclassified_paths.length) {
    lines.push('');
    lines.push('unclassified (carried, never dropped):');
    for (const u of report.unclassified_paths) lines.push(`  ${u.root}:${u.path}`);
  }

  if (report.gate_items.length) {
    lines.push('');
    lines.push('GATE ITEMS - a mismatch is written up, never silently absorbed:');
    for (const g of report.gate_items) {
      lines.push(`  [${g.code}] ${g.class ?? '-'}: ${g.detail}`);
    }
  }

  lines.push('');
  lines.push(`status: ${report.status}`);
  return lines.join('\n');
}

/**
 * @param {object} report @returns {string} a markdown table block for census.md
 */
export function renderCensusMarkdown(report) {
  const lines = [];
  lines.push('| class | discovered | parsed | unparseable | unclassified | skipped | records |');
  lines.push('|---|---:|---:|---:|---:|---:|---:|');
  for (const [name, counts] of Object.entries(report.per_class)) {
    lines.push(
      `| ${name} | ${counts.discovered} | ${counts.parsed} | ${counts.unparseable} | ` +
        `${counts.unclassified} | ${counts.skipped} | ${counts.records} |`,
    );
  }
  lines.push(
    `| **total** | **${report.totals.discovered}** | **${report.totals.parsed}** | ` +
      `**${report.totals.unparseable}** | **${report.totals.unclassified}** | ` +
      `**${report.totals.skipped}** | **${report.totals.records}** |`,
  );
  lines.push('');
  lines.push(
    `Totality: \`${report.totality.equation}\` -> ${report.totality.left} == ${report.totality.right} ` +
      `(**${report.totality.ok ? 'holds' : 'VIOLATED'}**).`,
  );
  lines.push('');
  lines.push('| class | items | window (days) | items/day | projected 365d | basis |');
  lines.push('|---|---:|---:|---:|---:|---|');
  for (const [name, g] of Object.entries(report.growth)) {
    lines.push(
      `| ${name} | ${g.items} | ${g.window_days ?? 'n/a'} | ${g.per_day ?? 'n/a'} | ` +
        `${g.projected_365d ?? 'n/a'} | ${g.basis} |`,
    );
  }
  if (report.gate_items.length) {
    lines.push('');
    lines.push('| gate item | class | detail |');
    lines.push('|---|---|---|');
    for (const g of report.gate_items) {
      lines.push(`| ${g.code} | ${g.class ?? '-'} | ${g.detail.replace(/\|/g, '/')} |`);
    }
  }
  return lines.join('\n');
}

// -- CLI ----------------------------------------------------------------------

/** @param {string} value @returns {string[]} */
function splitRoots(value) {
  return String(value)
    .split(path.delimiter)
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * @param {string[]} argv
 * @param {Record<string, string|undefined>} [env]
 * @returns {{roots: string[], json: boolean, markdown: boolean, out: string|null, maxEntries: number|undefined, help: boolean, errors: string[]}}
 */
export function parseCensusArgs(argv = [], env = {}) {
  const parsed = { roots: [], json: false, markdown: false, out: null, maxEntries: undefined, help: false, errors: [] };
  const tokens = [...argv];

  for (let i = 0; i < tokens.length; i += 1) {
    const t = tokens[i];
    if (t === '--help' || t === '-h') { parsed.help = true; continue; }
    if (t === '--json') { parsed.json = true; continue; }
    if (t === '--markdown' || t === '--md') { parsed.markdown = true; continue; }
    if (t === '--root' || t === '--roots' || t === '-R') {
      const next = tokens[i + 1];
      if (!next || next.startsWith('-')) { parsed.errors.push(`${t} needs a path`); continue; }
      parsed.roots.push(...splitRoots(next));
      i += 1;
      continue;
    }
    if (t.startsWith('--root=') || t.startsWith('--roots=')) {
      parsed.roots.push(...splitRoots(t.slice(t.indexOf('=') + 1)));
      continue;
    }
    if (t === '--out') {
      const next = tokens[i + 1];
      if (!next || next.startsWith('-')) { parsed.errors.push('--out needs a path'); continue; }
      parsed.out = next;
      i += 1;
      continue;
    }
    if (t.startsWith('--out=')) { parsed.out = t.slice('--out='.length); continue; }
    if (t === '--max-entries') {
      const next = Number(tokens[i + 1]);
      if (!Number.isInteger(next) || next <= 0) { parsed.errors.push('--max-entries needs a positive integer'); }
      else { parsed.maxEntries = next; i += 1; }
      continue;
    }
    if (t.startsWith('--max-entries=')) {
      const next = Number(t.slice('--max-entries='.length));
      if (!Number.isInteger(next) || next <= 0) parsed.errors.push('--max-entries needs a positive integer');
      else parsed.maxEntries = next;
      continue;
    }
    parsed.errors.push(`unknown argument: ${t}`);
  }

  if (parsed.roots.length === 0) {
    for (const name of ROOT_ENV_VARS) {
      if (env[name]) { parsed.roots.push(...splitRoots(env[name])); break; }
    }
  }

  return parsed;
}

/** @returns {string} */
export function censusHelp() {
  const paths = INVENTORY_V1.map((e) => `    ${e.class.padEnd(16)} ${e.spec}`).join('\n');
  return [
    'tools/census.mjs - walk registered roots against inventory-v1 and count everything.',
    '',
    '  --root <path>        a registered project root (repeatable; OS-delimited lists allowed)',
    '  --json               emit the full report as JSON',
    '  --markdown           emit the census.md table block',
    '  --out <file>         write the chosen rendering to a file as well as stdout',
    '  --max-entries <n>    bound the walk (default is the module cap)',
    '',
    `  roots may also come from ${ROOT_ENV_VARS.join(' or ')} (OS path-delimiter separated).`,
    '',
    `  ${INVENTORY_VERSION} discovery paths:`,
    paths,
  ].join('\n');
}

/**
 * @param {string[]} argv @param {object} [env] @param {{log?: Function, error?: Function}} [io]
 * @returns {number} the process exit code
 */
export function main(argv = [], env = process.env, io = {}) {
  const log = io.log ?? console.log;
  const error = io.error ?? console.error;
  const args = parseCensusArgs(argv, env);

  if (args.help) { log(censusHelp()); return 0; }
  for (const e of args.errors) error(`census: ${e}`);
  if (args.errors.length) { error(censusHelp()); return 2; }

  if (args.roots.length === 0) {
    error(`census: ${CENSUS_STATUS.NO_ROOTS} - no roots given.`);
    error(censusHelp());
    return 2;
  }

  const report = runCensus({ roots: args.roots, maxEntries: args.maxEntries });
  const rendered = args.json
    ? JSON.stringify(report, null, 2)
    : args.markdown
      ? renderCensusMarkdown(report)
      : renderCensusText(report);

  log(rendered);
  if (args.out) {
    fs.writeFileSync(args.out, `${rendered}\n`, 'utf8');
    error(`census: wrote ${args.out}`);
  }

  return report.totality.ok ? 0 : 3;
}

const invokedDirectly =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (invokedDirectly) {
  process.exit(main(process.argv.slice(2), process.env));
}
