// docs.mjs — Crucible's docs & version-control layer (Wave 10).
//
// MASTER-PLAN §12 (Docs & version control): a Crucible-planned project carries a
// LIVING-DOC set under git. Wave 10 owns the WRITERS for that set — the artifacts
// Crucible generates/maintains alongside the Foreman doc-trio (Wave 8) and pushes
// at the approval gates (Wave 9's remote). Two tiers:
//
//   v1 CORE (always):
//     · CLAUDE.md       — the SHARP orientation doc (live truth pointer); stays terse
//     · CLAUDE_hist.md  — the dated HISTORY the sharp doc offloads to (the §12 split)
//     · DECISION-LOG.md — MADR/DACI: a decision table, one named Approver, APPEND-ONLY
//                         (supersede, never edit)
//     · GRASSCATCHER.md — the idea-catcher backlog (out-of-scope ideas, with provenance)
//     · plans/{intake,proto,debates,research}/ — the working-doc tree (scaffolded)
//
//   OPTIONAL (a flag, default OFF — D13(a): "no altitude tiers in v1"):
//     · RTM.md          — requirements-traceability matrix (criterion → waves → tests)
//     · viz/            — Mermaid diagrams (dependency graph, …)
//     · SUMMARY.md      — the investor-brief
//
// The two-tier rule is the whole behavioural contract of this wave: the core set is
// ALWAYS written; the optional docs appear ONLY when `optional:true` is passed. The
// default is OFF, so a plain run emits exactly the v1 core (PM is the lighter path).
//
// The append-only logs (DECISION-LOG, GRASSCATCHER) get `append*` helpers so the
// "maintain" half of the wave intent is real: a new decision/idea is inserted as a
// fresh table row, never by editing an existing one (MADR's supersede-don't-edit).
//
// Every writer here is a pure string renderer + a thin fs writer, mirroring Wave-8's
// stage2 doc-trio writers — deterministic output the tests assert byte-shape on.

import fs from 'node:fs';
import path from 'node:path';

import { HaltError } from './crucible-lib.mjs';

// ---------------------------------------------------------------------------
// The doc-set layout (filenames + the plans/ subtree).
// ---------------------------------------------------------------------------

/** The v1 CORE living docs — always written. */
export const CORE_DOC_FILENAMES = {
  claude: 'CLAUDE.md',
  claudeHist: 'CLAUDE_hist.md',
  decisionLog: 'DECISION-LOG.md',
  grasscatcher: 'GRASSCATCHER.md',
};

/** The OPTIONAL docs — written only when the flag is set (default OFF). */
export const OPTIONAL_DOC_FILENAMES = {
  rtm: 'RTM.md',
  summary: 'SUMMARY.md',
};

/** The working-doc subtree scaffolded under `plans/`. */
export const PLANS_SUBDIRS = ['intake', 'proto', 'debates', 'research'];

/** The optional Mermaid-diagram directory + its default dependency-graph file. */
export const VIZ_DIR = 'viz';
export const VIZ_DEPENDENCY_FILE = 'dependency.mmd';

// ---------------------------------------------------------------------------
// (1) CLAUDE.md / CLAUDE_hist.md — the sharp / history SPLIT (§12).
// ---------------------------------------------------------------------------

/**
 * Render the SHARP orientation doc. It stays terse on purpose — the live-truth
 * pointer plus the few things a fresh coding-agent session needs; everything dated
 * offloads to CLAUDE_hist.md (the §12 split keeps the sharp doc from bloating).
 *
 * @param {object} o
 * @param {string}  o.projectName
 * @param {string}  o.northStar
 * @param {string} [o.whatItIs='']         one-line "what this is"
 * @param {string[]}[o.keyFiles=[]]        "path — purpose" pointers
 * @param {string[]}[o.standingRules=[]]   the always-on rules
 */
export function renderClaudeMd({ projectName = 'project', northStar, whatItIs = '', keyFiles = [], standingRules = [] } = {}) {
  const lines = [
    `# CLAUDE.md — ${projectName}`,
    '',
    `Orientation for any coding-agent session opened in this project. Read first. Kept SHARP — dated history lives in \`${CORE_DOC_FILENAMES.claudeHist}\`.`,
    '',
    '## North Star',
    '',
    String(northStar),
    '',
  ];
  if (whatItIs) lines.push('## What this is', '', whatItIs, '');
  if (keyFiles.length) {
    lines.push('## Key files', '');
    for (const f of keyFiles) lines.push(`- ${f}`);
    lines.push('');
  }
  if (standingRules.length) {
    lines.push('## Standing rules', '');
    for (const r of standingRules) lines.push(`- ${r}`);
    lines.push('');
  }
  return lines.join('\n');
}

/**
 * Render the dated HISTORY doc the sharp CLAUDE.md offloads to. Newest-first.
 *
 * @param {object} o
 * @param {string}  o.projectName
 * @param {Array<{date:string, note:string}>}[o.entries=[]]
 */
export function renderClaudeHist({ projectName = 'project', entries = [] } = {}) {
  const lines = [
    `# ${projectName} — History (CLAUDE_hist.md)`,
    '',
    'Dated history offloaded from the sharp `CLAUDE.md`. Newest first; append, never rewrite.',
    '',
  ];
  if (!entries.length) {
    lines.push('_(no history entries yet)_', '');
  } else {
    for (const e of entries) {
      lines.push(`## ${String(e.date ?? '').trim() || 'undated'}`, '', String(e.note ?? '').trim(), '');
    }
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// (2) DECISION-LOG.md — MADR/DACI, append-only (supersede, never edit).
// ---------------------------------------------------------------------------

const DECISION_HEADER = '| # | Date | Decision | Approver | Status |';
const DECISION_SEP = '|---|---|---|---|---|';

/** Format one decision as a markdown table row (cells pipe-escaped). */
function decisionRow({ id, date, decision, approver, status = 'Accepted' }) {
  return `| ${cell(id)} | ${cell(date)} | ${cell(decision)} | ${cell(approver)} | ${cell(status)} |`;
}

/**
 * Render the MADR/DACI decision log. Each row = one decision with a single named
 * Approver (DACI). The doc is APPEND-ONLY: supersede a decision with a new row, never
 * edit an existing one (that's what `appendDecision` enforces in the maintain path).
 *
 * @param {object} o
 * @param {string}  o.projectName
 * @param {Array<{id,date,decision,approver,status}>}[o.decisions=[]]
 */
export function renderDecisionLog({ projectName = 'project', decisions = [] } = {}) {
  const lines = [
    `# ${projectName} — Decision Log (ADR index)`,
    '',
    'MADR-style. Each decision has one named Approver (DACI). **Append-only; supersede, do not edit.**',
    '',
    DECISION_HEADER,
    DECISION_SEP,
  ];
  for (const d of decisions) lines.push(decisionRow(d));
  lines.push('');
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// (3) GRASSCATCHER.md — the out-of-scope idea backlog.
// ---------------------------------------------------------------------------

const GRASS_HEADER = '| # | Date | Idea | Origin | Why out-of-scope | Suggested home | Status |';
const GRASS_SEP = '|---|---|---|---|---|---|---|';

/** Format one grasscatcher idea as a markdown table row. */
function grassRow({ n, date, idea, origin, why, home, status = 'parked' }) {
  return `| ${cell(n)} | ${cell(date)} | ${cell(idea)} | ${cell(origin)} | ${cell(why)} | ${cell(home)} | ${cell(status)} |`;
}

/**
 * Render the Grasscatcher backlog. Out-of-scope ideas are PARKED here with full
 * provenance (nothing good is dropped); refinement ideas do NOT go here (those
 * sharpen the North Star via the decision log).
 *
 * @param {object} o
 * @param {string}  o.projectName
 * @param {Array<{n,date,idea,origin,why,home,status}>}[o.items=[]]
 */
export function renderGrasscatcher({ projectName = 'project', items = [] } = {}) {
  const lines = [
    `# ${projectName} — Grasscatcher (idea-catcher backlog)`,
    '',
    'Out-of-scope ideas surfaced during planning, parked for future consideration. **Nothing good is dropped.** Refinement ideas do NOT go here — those sharpen the North Star (see `DECISION-LOG.md`).',
    '',
    GRASS_HEADER,
    GRASS_SEP,
  ];
  for (const it of items) lines.push(grassRow(it));
  lines.push('');
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// (4) OPTIONAL docs (flag default OFF) — RTM, Mermaid viz, SUMMARY.
// ---------------------------------------------------------------------------

/**
 * Render the requirements-traceability matrix: each North-Star criterion mapped to
 * the waves that serve it and the tests that verify it (the inclusion test, made
 * auditable). Optional — altitude-gated off in v1 (D13(a)).
 *
 * @param {object} o
 * @param {string}  o.projectName
 * @param {Array<{criterion:string, waves:(string|number)[]|string, tests:string[]|string}>}[o.rows=[]]
 */
export function renderRTM({ projectName = 'project', rows = [] } = {}) {
  const lines = [
    `# ${projectName} — Requirements Traceability Matrix`,
    '',
    'Each North-Star criterion → the waves that serve it → the tests that verify it.',
    '',
    '| Criterion | Waves | Tests |',
    '|---|---|---|',
  ];
  for (const r of rows) {
    const waves = Array.isArray(r.waves) ? r.waves.join(', ') : (r.waves ?? '');
    const tests = Array.isArray(r.tests) ? r.tests.join(', ') : (r.tests ?? '');
    lines.push(`| ${cell(r.criterion)} | ${cell(waves)} | ${cell(tests)} |`);
  }
  lines.push('');
  return lines.join('\n');
}

/**
 * Render a Mermaid dependency graph from the planned waves. `dependsOn` names the
 * prior wave by TITLE (Stage-2's shape); edges are drawn only when a dependency
 * resolves to a known wave. Optional viz output.
 *
 * @param {object} o
 * @param {Array<{n:number, title:string, dependsOn?:string|null}>}[o.waves=[]]
 */
export function renderMermaidDependency({ waves = [] } = {}) {
  const byTitle = new Map(waves.map((w) => [String(w.title), w]));
  const lines = ['graph TD'];
  for (const w of waves) {
    lines.push(`  W${w.n}["Wave ${w.n} — ${mermaidLabel(w.title)}"]`);
  }
  for (const w of waves) {
    if (w.dependsOn && byTitle.has(String(w.dependsOn))) {
      const dep = byTitle.get(String(w.dependsOn));
      lines.push(`  W${dep.n} --> W${w.n}`);
    }
  }
  return lines.join('\n') + '\n';
}

/**
 * Render the investor-brief SUMMARY. Optional output (altitude-gated off in v1).
 *
 * @param {object} o
 * @param {string}  o.projectName
 * @param {string}  o.northStar
 * @param {string} [o.elevatorPitch='']
 * @param {string[]}[o.criteria=[]]
 */
export function renderSummary({ projectName = 'project', northStar, elevatorPitch = '', criteria = [] } = {}) {
  const lines = [
    `# ${projectName} — Summary`,
    '',
    `**North Star:** ${northStar}`,
    '',
  ];
  if (elevatorPitch) lines.push(elevatorPitch, '');
  if (criteria.length) {
    lines.push('## What success looks like', '');
    for (const c of criteria) lines.push(`- ${c}`);
    lines.push('');
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// (5) The writer — emits the CORE set always; the OPTIONAL set only on the flag.
// ---------------------------------------------------------------------------

/**
 * Write the living-doc set into `outputDir`. ALWAYS writes the v1 core (the four core
 * docs + the scaffolded `plans/{intake,proto,debates,research}/` tree). Writes the
 * OPTIONAL docs (RTM.md, viz/, SUMMARY.md) ONLY when `optional:true` — the default is
 * OFF (D13(a): no altitude tiers in v1).
 *
 * @param {object} o
 * @param {string}  o.outputDir
 * @param {string}  o.projectName
 * @param {string}  o.northStar
 * @param {object} [o.claude={}]           extra renderClaudeMd fields (whatItIs/keyFiles/standingRules)
 * @param {Array}  [o.histEntries=[]]
 * @param {Array}  [o.decisions=[]]
 * @param {Array}  [o.grasscatcherItems=[]]
 * @param {boolean}[o.optional=false]       THE FLAG — default OFF
 * @param {string[]}[o.criteria=[]]         shared by RTM/SUMMARY
 * @param {Array}  [o.rtmRows=[]]
 * @param {Array}  [o.vizWaves=[]]          waves for the Mermaid dependency graph
 * @param {object} [o.summary={}]           extra renderSummary fields (elevatorPitch)
 * @param {Function}[o.log=()=>{}]
 * @returns {{dir:string, core:object, plansDirs:object, optional:(false|object)}}
 */
export function writeDocSet({
  outputDir,
  projectName = 'Crucible-planned project',
  northStar,
  claude = {},
  histEntries = [],
  decisions = [],
  grasscatcherItems = [],
  optional = false,
  criteria = [],
  rtmRows = [],
  vizWaves = [],
  summary = {},
  log = () => {},
} = {}) {
  if (!outputDir) throw new HaltError('writeDocSet requires an outputDir', 'pass the project output directory');
  if (!northStar) throw new HaltError('writeDocSet requires a North Star', 'the living docs embed the locked North Star');

  const dir = path.resolve(outputDir);
  fs.mkdirSync(dir, { recursive: true });

  // --- the v1 CORE set (always) ---
  const core = {
    claude: path.join(dir, CORE_DOC_FILENAMES.claude),
    claudeHist: path.join(dir, CORE_DOC_FILENAMES.claudeHist),
    decisionLog: path.join(dir, CORE_DOC_FILENAMES.decisionLog),
    grasscatcher: path.join(dir, CORE_DOC_FILENAMES.grasscatcher),
  };
  fs.writeFileSync(core.claude, renderClaudeMd({ projectName, northStar, ...claude }));
  fs.writeFileSync(core.claudeHist, renderClaudeHist({ projectName, entries: histEntries }));
  fs.writeFileSync(core.decisionLog, renderDecisionLog({ projectName, decisions }));
  fs.writeFileSync(core.grasscatcher, renderGrasscatcher({ projectName, items: grasscatcherItems }));

  // --- the plans/ working-doc tree (always) ---
  const plansRoot = path.join(dir, 'plans');
  const plansDirs = {};
  for (const sub of PLANS_SUBDIRS) {
    const p = path.join(plansRoot, sub);
    fs.mkdirSync(p, { recursive: true });
    plansDirs[sub] = p;
  }

  log(`docs: wrote core living-doc set + plans/{${PLANS_SUBDIRS.join(',')}}/ → ${dir}`);

  // --- the OPTIONAL set (only on the flag; default OFF) ---
  let optionalOut = false;
  if (optional) {
    const rtm = path.join(dir, OPTIONAL_DOC_FILENAMES.rtm);
    const summaryPath = path.join(dir, OPTIONAL_DOC_FILENAMES.summary);
    fs.writeFileSync(rtm, renderRTM({ projectName, rows: rtmRows }));
    fs.writeFileSync(summaryPath, renderSummary({ projectName, northStar, criteria, ...summary }));

    const vizDir = path.join(dir, VIZ_DIR);
    fs.mkdirSync(vizDir, { recursive: true });
    const vizDependency = path.join(vizDir, VIZ_DEPENDENCY_FILE);
    fs.writeFileSync(vizDependency, renderMermaidDependency({ waves: vizWaves }));

    optionalOut = { rtm, summary: summaryPath, vizDir, vizFiles: { dependency: vizDependency } };
    log('docs: optional flag SET — also wrote RTM.md, viz/, SUMMARY.md');
  }

  return { dir, core, plansDirs, optional: optionalOut };
}

// ---------------------------------------------------------------------------
// (6) The "maintain" path — append-only inserts into the two logs.
// ---------------------------------------------------------------------------

/**
 * Append a decision ROW to an existing DECISION-LOG.md — never edits a prior row
 * (MADR supersede-don't-edit). Inserts after the last existing table row of the
 * decision table, preserving any prose that follows the table.
 *
 * @param {string} filePath
 * @param {{id,date,decision,approver,status?}} decision
 * @returns {string} the file's new content
 */
export function appendDecision(filePath, decision) {
  return insertTableRowFile(filePath, DECISION_SEP, decisionRow(decision), 'DECISION-LOG.md');
}

/**
 * Append an idea ROW to an existing GRASSCATCHER.md (append-only, same discipline).
 *
 * @param {string} filePath
 * @param {{n,date,idea,origin,why,home,status?}} item
 * @returns {string} the file's new content
 */
export function appendGrasscatcherItem(filePath, item) {
  return insertTableRowFile(filePath, GRASS_SEP, grassRow(item), 'GRASSCATCHER.md');
}

// ---------------------------------------------------------------------------
// Shared helpers.
// ---------------------------------------------------------------------------

/** Stringify a table cell, escaping pipes + collapsing newlines so the row stays intact. */
function cell(v) {
  return String(v ?? '').replace(/\r?\n/g, ' ').replace(/\|/g, '\\|').trim();
}

/** Sanitize a label for a Mermaid node (quotes/brackets would break the syntax). */
function mermaidLabel(s) {
  return String(s ?? '').replace(/["[\]]/g, '');
}

/**
 * Insert `row` into the FIRST markdown table of a file, after its last contiguous
 * data row (the table whose separator line equals `sepLine`). Append-only by
 * construction — existing rows are untouched. HALTs if the file or its table is
 * missing (a maintain call against a doc that was never generated).
 */
function insertTableRowFile(filePath, sepLine, row, docName) {
  if (!filePath) throw new HaltError(`append requires a ${docName} path`, `pass the path to the generated ${docName}`);
  if (!fs.existsSync(filePath)) {
    throw new HaltError(`${docName} does not exist yet`, `generate it with writeDocSet first, then append`);
  }
  const content = fs.readFileSync(filePath, 'utf8');
  const lines = content.split('\n');
  const sepIdx = lines.findIndex((l) => l.trim() === sepLine);
  if (sepIdx === -1) {
    throw new HaltError(`could not find the table in ${docName}`, `${docName} is malformed — regenerate it`);
  }
  // Advance past the contiguous data rows that follow the separator.
  let insertAt = sepIdx + 1;
  while (insertAt < lines.length && lines[insertAt].trim().startsWith('|')) insertAt++;
  lines.splice(insertAt, 0, row);
  const next = lines.join('\n');
  fs.writeFileSync(filePath, next);
  return next;
}
