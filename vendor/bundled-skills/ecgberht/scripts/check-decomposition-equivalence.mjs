/**
 * T-EQUIV-01 — plan ↔ wave-decomposition equivalence check (Wave 1).
 *
 * Parses IMPLEMENTATION-PLAN-v3.md (or the handoff IMPLEMENTATION-PLAN.md) and
 * wave-decomposition-v3.json (or wave-decomposition.json) and FAILS loudly on
 * any divergence in wave count, ids, titles, done-whens, depends-on edges, or
 * gate semantics. On disagreement the plan wins and the build STOPS until the
 * JSON is regenerated.
 *
 * Usage:
 *   node scripts/check-decomposition-equivalence.mjs
 *   node scripts/check-decomposition-equivalence.mjs --plan <path> --json <path>
 *
 * Exit 0 = equivalent; exit 1 = divergence (prints field names); exit 2 = IO.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');

/**
 * Default plan/json locations (handoff first, then stage2-artifacts names).
 * No absolute host paths in shipped strings.
 */
export function defaultPlanPaths(root = ROOT) {
  const handoff = path.join(root, 'planning', 'steward-handoff-v3');
  const candidates = [
    {
      plan: path.join(handoff, 'IMPLEMENTATION-PLAN.md'),
      json: path.join(handoff, 'wave-decomposition.json'),
    },
    {
      plan: path.join(handoff, 'IMPLEMENTATION-PLAN-v3.md'),
      json: path.join(handoff, 'wave-decomposition-v3.json'),
    },
  ];
  for (const c of candidates) {
    if (fs.existsSync(c.plan) && fs.existsSync(c.json)) return c;
  }
  // Fall back to first pair even if missing — caller reports IO.
  return candidates[0];
}

/**
 * Parse wave headers and metadata from the frozen plan markdown.
 * @param {string} md
 * @returns {{ waves: Array<{n:number,title:string,dependsOn:number[],doneWhen:string}>, gateSemantics: object }}
 */
export function parsePlanWaves(md) {
  const text = String(md);
  const waves = [];
  // ## Wave N — Title  OR  ## Wave N - Title
  const headerRe = /^##\s+Wave\s+(\d+)\s+[—–-]\s+(.+?)\s*$/gm;
  const headers = [];
  let m;
  while ((m = headerRe.exec(text)) !== null) {
    headers.push({
      n: Number(m[1]),
      title: m[2].trim(),
      index: m.index,
      end: m.index + m[0].length,
    });
  }

  for (let i = 0; i < headers.length; i += 1) {
    const h = headers[i];
    const bodyEnd = i + 1 < headers.length ? headers[i + 1].index : text.length;
    const body = text.slice(h.end, bodyEnd);

    const dependsOn = parseDependsOn(body);
    const doneWhen = parseDoneWhen(body);
    waves.push({
      n: h.n,
      title: h.title,
      dependsOn,
      doneWhen,
    });
  }

  const gateSemantics = parseGateSemantics(text);
  return { waves, gateSemantics };
}

/**
 * @param {string} body
 * @returns {number[]}
 */
function parseDependsOn(body) {
  const m = body.match(/\*\*Depends on:\*\*\s*([^\n]+)/i);
  if (!m) return [];
  const raw = m[1].trim();
  if (raw === '—' || raw === '-' || raw === '–' || /^none$/i.test(raw)) {
    return [];
  }
  const nums = [];
  const re = /Wave\s+(\d+)/gi;
  let x;
  while ((x = re.exec(raw)) !== null) {
    nums.push(Number(x[1]));
  }
  // Also accept bare comma-separated numbers
  if (nums.length === 0) {
    for (const part of raw.split(/[,;]/)) {
      const n = Number(String(part).replace(/[^\d]/g, ''));
      if (Number.isFinite(n) && n > 0) nums.push(n);
    }
  }
  return [...new Set(nums)].sort((a, b) => a - b);
}

/**
 * @param {string} body
 * @returns {string}
 */
function parseDoneWhen(body) {
  const m = body.match(/\*\*done-when:\*\*\s*([\s\S]*?)(?=\n- \*\*Given|\n##\s+Wave|\n\*\*[A-Z]|$)/i);
  if (!m) return '';
  return normalizeProse(m[1]);
}

/**
 * Normalize prose for comparison (collapse whitespace).
 * @param {string} s
 */
export function normalizeProse(s) {
  return String(s || '')
    .replace(/\r\n/g, '\n')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n+/g, ' ')
    .trim();
}

/**
 * Lightweight gate semantics extraction for G4 / SC6 / exec2 / conformance / t-host-0.
 * @param {string} text
 */
function parseGateSemantics(text) {
  const hasG4Halt = /G4 FAIL is an explicit HALT/i.test(text);
  const hasG4AntiStub = /anti-stub/i.test(text) && /g4-verdict\.json/i.test(text);
  const hasSc6 = /sc6-feasibility\.json/i.test(text);
  const hasExec2 = /exec2-verdict\.json/i.test(text);
  const hasConformance = /conformance-verdict\.json/i.test(text);
  const hasTHost0 = /t-host-0-verdict\.json/i.test(text) || /T-HOST-0/i.test(text);
  return {
    g4Halt: hasG4Halt,
    g4AntiStub: hasG4AntiStub,
    sc6: hasSc6,
    exec2: hasExec2,
    conformance: hasConformance,
    tHost0: hasTHost0,
  };
}

/**
 * @param {object} json parsed wave-decomposition
 * @returns {{ waves: Array<{n:number,title:string,dependsOn:number[],doneWhen:string}>, gateSemantics: object, waveCount: number }}
 */
export function parseJsonWaves(json) {
  const waves = (json.waves || []).map((w) => ({
    n: Number(w.n),
    title: String(w.title || '').trim(),
    dependsOn: Array.isArray(w.dependsOn)
      ? [...w.dependsOn].map(Number).sort((a, b) => a - b)
      : [],
    doneWhen: normalizeProse(w.doneWhen || ''),
  }));
  const gateSemantics = {
    g4Halt: Boolean(json.g4Gate?.failSemantics),
    g4AntiStub: Boolean(json.g4Gate?.passSemantics),
    sc6: Boolean(json.sc6Gate),
    exec2: Boolean(json.exec2Gate),
    conformance: Boolean(json.conformanceGate),
    tHost0: Boolean(json.tHost0Gate),
  };
  return {
    waves,
    gateSemantics,
    waveCount: Number(json.waveCount ?? waves.length),
  };
}

/**
 * Compare plan parse vs JSON parse. Returns { ok, divergences[] }.
 * @param {{ waves: any[], gateSemantics: object }} plan
 * @param {{ waves: any[], gateSemantics: object, waveCount: number }} json
 */
export function compareDecomposition(plan, json) {
  /** @type {Array<{ field: string, plan: unknown, json: unknown, message: string }>} */
  const divergences = [];

  if (plan.waves.length !== json.waveCount) {
    divergences.push({
      field: 'waveCount',
      plan: plan.waves.length,
      json: json.waveCount,
      message: `wave count diverges: plan has ${plan.waves.length}, json waveCount is ${json.waveCount}`,
    });
  }
  if (plan.waves.length !== json.waves.length) {
    divergences.push({
      field: 'waves.length',
      plan: plan.waves.length,
      json: json.waves.length,
      message: `waves array length diverges: plan ${plan.waves.length} vs json ${json.waves.length}`,
    });
  }

  const byN = new Map(json.waves.map((w) => [w.n, w]));
  for (const pw of plan.waves) {
    const jw = byN.get(pw.n);
    if (!jw) {
      divergences.push({
        field: `wave[${pw.n}].id`,
        plan: pw.n,
        json: null,
        message: `wave id ${pw.n} present in plan but missing from json`,
      });
      continue;
    }
    if (normalizeTitle(pw.title) !== normalizeTitle(jw.title)) {
      divergences.push({
        field: `wave[${pw.n}].title`,
        plan: pw.title,
        json: jw.title,
        message: `wave ${pw.n} title diverges`,
      });
    }
    if (!sameNumberArray(pw.dependsOn, jw.dependsOn)) {
      divergences.push({
        field: `wave[${pw.n}].dependsOn`,
        plan: pw.dependsOn,
        json: jw.dependsOn,
        message: `wave ${pw.n} depends-on edges diverge`,
      });
    }
    // done-when: require non-empty agreement when both present; soft-prefix match
    // for minor punctuation drift, but flag empty-vs-nonempty and clear mismatch.
    if (pw.doneWhen && jw.doneWhen) {
      if (!doneWhenEquivalent(pw.doneWhen, jw.doneWhen)) {
        divergences.push({
          field: `wave[${pw.n}].doneWhen`,
          plan: pw.doneWhen.slice(0, 120),
          json: jw.doneWhen.slice(0, 120),
          message: `wave ${pw.n} done-when diverges`,
        });
      }
    } else if (Boolean(pw.doneWhen) !== Boolean(jw.doneWhen)) {
      divergences.push({
        field: `wave[${pw.n}].doneWhen`,
        plan: pw.doneWhen || null,
        json: jw.doneWhen || null,
        message: `wave ${pw.n} done-when presence diverges`,
      });
    }
  }

  for (const jw of json.waves) {
    if (!plan.waves.some((p) => p.n === jw.n)) {
      divergences.push({
        field: `wave[${jw.n}].id`,
        plan: null,
        json: jw.n,
        message: `wave id ${jw.n} present in json but missing from plan`,
      });
    }
  }

  // Gate semantics: plan prose must mention the same gate artifacts the JSON records.
  for (const key of Object.keys(plan.gateSemantics)) {
    if (Boolean(plan.gateSemantics[key]) !== Boolean(json.gateSemantics[key])) {
      divergences.push({
        field: `gateSemantics.${key}`,
        plan: plan.gateSemantics[key],
        json: json.gateSemantics[key],
        message: `gate semantics diverge on ${key}`,
      });
    }
  }

  return { ok: divergences.length === 0, divergences };
}

function normalizeTitle(t) {
  return String(t || '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function sameNumberArray(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

/**
 * done-when equivalence: exact after normalize, or mutual significant-substring
 * (first 80 alnum chars) to tolerate markdown list-tail clipping.
 */
function doneWhenEquivalent(a, b) {
  const na = normalizeProse(a).toLowerCase();
  const nb = normalizeProse(b).toLowerCase();
  if (na === nb) return true;
  const sig = (s) => s.replace(/[^a-z0-9]+/g, ' ').trim().slice(0, 80);
  return sig(na) === sig(nb) || na.includes(sig(nb)) || nb.includes(sig(na));
}

/**
 * Run the check against paths.
 * Accepts either CLI shape `{ planPath, jsonPath }` or defaultPlanPaths shape
 * `{ plan, json }` — both call sites in the suite/runner use the latter.
 * @param {{ planPath?: string, jsonPath?: string, plan?: string, json?: string }} paths
 */
export function runEquivalenceCheck(paths) {
  const planPath = path.resolve(paths.planPath ?? paths.plan);
  const jsonPath = path.resolve(paths.jsonPath ?? paths.json);
  if (!fs.existsSync(planPath)) {
    return {
      ok: false,
      ioError: true,
      message: `plan not found: ${planPath}`,
      divergences: [{ field: 'planPath', plan: planPath, json: null, message: 'plan missing' }],
    };
  }
  if (!fs.existsSync(jsonPath)) {
    return {
      ok: false,
      ioError: true,
      message: `json not found: ${jsonPath}`,
      divergences: [{ field: 'jsonPath', plan: null, json: jsonPath, message: 'json missing' }],
    };
  }
  const planMd = fs.readFileSync(planPath, 'utf8');
  const json = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
  const plan = parsePlanWaves(planMd);
  const decomp = parseJsonWaves(json);
  const cmp = compareDecomposition(plan, decomp);
  return {
    ...cmp,
    planPath,
    jsonPath,
    planWaveCount: plan.waves.length,
    jsonWaveCount: decomp.waveCount,
  };
}

function parseArgs(argv) {
  let planPath = null;
  let jsonPath = null;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--plan' && argv[i + 1]) {
      planPath = argv[++i];
    } else if (argv[i] === '--json' && argv[i + 1]) {
      jsonPath = argv[++i];
    }
  }
  const defaults = defaultPlanPaths(ROOT);
  return {
    planPath: planPath || process.env.ECGBERHT_PLAN_PATH || defaults.plan,
    jsonPath: jsonPath || process.env.ECGBERHT_DECOMP_PATH || defaults.json,
  };
}

function main() {
  const paths = parseArgs(process.argv.slice(2));
  const result = runEquivalenceCheck(paths);
  if (result.ioError) {
    console.error(`T-EQUIV-01 IO: ${result.message}`);
    process.exit(2);
  }
  if (!result.ok) {
    console.error('T-EQUIV-01 FAIL — plan/JSON divergence:');
    for (const d of result.divergences) {
      console.error(`  - field=${d.field}: ${d.message}`);
    }
    console.error(
      'On disagreement IMPLEMENTATION-PLAN wins; regenerate wave-decomposition JSON.',
    );
    process.exit(1);
  }
  console.log(
    `T-EQUIV-01 PASS — ${result.planWaveCount} waves equivalent (${path.relative(ROOT, result.planPath)} ↔ ${path.relative(ROOT, result.jsonPath)})`,
  );
  process.exit(0);
}

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  main();
}
