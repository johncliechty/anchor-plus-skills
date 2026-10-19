/**
 * Stage 2 approved emit — human-lockable BEST-DRAFT → Foreman doc-trio.
 * cwd/handoff: planning/sleep-2026-07-28/stage2/ ONLY.
 */
import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const CRUCIBLE_BIN = 'C:\\dev\\trio\\crucible\\bin';
const { writeDocTrio, renderDescriptionDoc, renderExecutionLog } = await import(
  pathToFileURL(path.join(CRUCIBLE_BIN, 'stage2.mjs')).href
);

const OUT = 'C:\\dev\\Anchor\\planning\\sleep-2026-07-28\\stage2';
const ART = path.join(OUT, 'artifacts');
const draftPath = path.join(ART, 'BEST-DRAFT.md');

const northStar =
  'On branch v1.2, John can open, run, stop, and restart real Anchor work — including Doctor ' +
  'diagnose and session attach — without meeting a dead control, a silent zero, a mislabelled ' +
  'empty, or a preview that dumps raw binary. Every surface that claims health, usage, or ' +
  'diagnose either works end-to-end or fails with a named, user-visible state (unknown ≠ empty ' +
  '≠ zero). Cost never fabricates dollars. Nothing in this effort ships to v1.1.x collaborators. ' +
  'Steward conversational proof is a post-build validation session (S1), not a silent claim of ' +
  'this build.';

const criteria = [
  'Dead controls eliminated for Retry, Diagnose, and exactly one restart control per restart context.',
  'Attach honesty: timeout classified; no double-print; Retry viable or cannot-retry.',
  'Usage/time/cost after rollup evidence; cost_state never 0⇒subscription; never $0.00 as fact.',
  'Doctor real diagnose + banner payload + per-seat depth labels.',
  'Stop summary + per-context restart contracts.',
  'File preview human-friendly; no raw binary as text.',
  'Projects collapsed by default; dual-profile verify.',
  'Cadence from live telemetry with as_of/staleness.',
  'Failure-state tables unknown≠empty; scoped pytest -v; render+node --check; delta-coverage.',
  'Handoff only under planning/sleep-2026-07-28/stage2/; commits+EXECUTION-LOG; root Foreman artifacts untouched.',
];

let plan = readFileSync(draftPath, 'utf8');
// Money-safe project default: wave-scoped gates are in deliverables; suite default is sleep-dated tests only.
// Never bare full suite (Anchor money history).
plan = plan.replace(
  /^test-command:\s*.+$/m,
  'test-command: python -m pytest -v tests/ -k "2026_07_29" --tb=line',
);
// UTF-8 clean write via writeDocTrio (enforces hardening)

const description = renderDescriptionDoc({
  title: 'Anchor sleep cycle 2026-07-28 (v1.2)',
  northStar,
  criteria,
  summary:
    'Honesty-first defect remediation on branch v1.2: evidence before wiring, named failure states ' +
    '(unknown ≠ empty ≠ zero), cost never fabricated, dead controls forbidden. Emit isolation under ' +
    'planning/sleep-2026-07-28/stage2/ only. John approved Stage 2 after human-lockable Shark halt ' +
    '("Optimize not lying").',
});

// Count waves for execution log
const waveCount = (plan.match(/^## Wave \d+/gm) || []).length;
const executionLog = renderExecutionLog({
  title: 'Anchor sleep cycle 2026-07-28 (v1.2)',
  waveCount,
});

console.log('[emit] writeDocTrio →', OUT, 'waves~', waveCount);
const docTrio = writeDocTrio({
  outputDir: OUT,
  plan,
  description,
  executionLog,
  depth: 'FULL',
  tier: 'Standard',
  log: (m) => console.log('[emit]', m),
  enforceHardening: true,
  addsSurface: true,
});

// Ensure description filename is DESCRIPTION.md (DEFAULT)
// Fix scripts/run-all-tests.mjs for Anchor pytest money-safe
const runAll = path.join(OUT, 'scripts', 'run-all-tests.mjs');
writeFileSync(runAll, `#!/usr/bin/env node
// Anchor sleep cycle — money-safe default gate: only tests matching 2026_07_29
// (per-wave gate-command: lines in IMPLEMENTATION-PLAN.md are authoritative when Foreman scopes them)
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const r = spawnSync(
  process.platform === 'win32' ? 'python' : 'python3',
  ['-m', 'pytest', '-v', 'tests/', '-k', '2026_07_29', '--tb=line'],
  { cwd: repoRoot, stdio: 'inherit', shell: false, env: process.env },
);
process.exit(r.status == null ? 1 : r.status);
`, 'utf8');

// Approval stamp
writeFileSync(path.join(OUT, 'STAGE2-APPROVED.json'), JSON.stringify({
  stage: 2,
  status: 'approved',
  approved_at: new Date().toISOString(),
  approved_by: 'john',
  decision: 'approved (optimize not lying)',
  plan: 'IMPLEMENTATION-PLAN.md',
  wave_count: waveCount,
  emit_dir: OUT,
  hardening: docTrio.hardening || null,
}, null, 2) + '\n', 'utf8');

// Well-formedness / handoff gate
console.log('[emit] well-formedness gate…');
const gateMod = await import(pathToFileURL(path.join(CRUCIBLE_BIN, 'gates.mjs')).href);
const gate = gateMod.runWellFormednessGate({
  projectDir: OUT,
  artifactsDir: ART,
  log: (m) => console.log('[gate]', m),
});
writeFileSync(path.join(ART, 'well-formedness-gate.json'), JSON.stringify(gate, null, 2) + '\n', 'utf8');
console.log('[emit] well-formedness pass=', !!gate.pass, 'status=', gate.status);

// Copy BEST-DRAFT alongside for audit
copyFileSync(draftPath, path.join(OUT, 'BEST-DRAFT-APPROVED.md'));

if (!gate.pass) {
  console.error('[emit] FAIL well-formedness — see artifacts');
  process.exit(3);
}
console.log('[emit] OK handoff ready at', OUT);
process.exit(0);
