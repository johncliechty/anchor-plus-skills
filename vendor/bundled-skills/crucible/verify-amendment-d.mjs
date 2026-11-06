// Focused cross-family adversarial verification of AMENDMENT D (standalone tool +
// thin Anchor caller) on the Tidy-Idy GUI plan. One Shark round (3 concurrent
// Gemini 3.1 Pro High Sharks) refuting that the launch-ownership inversion
// preserves every safety invariant. routes-fix in (sharks -> gemini-cli).
import fs from 'node:fs';
import path from 'node:path';
import { buildLiveCrucibleAgent } from './bin/enhanced.mjs';
import { runSharkTank } from './bin/shark-tank.mjs';

const outputDir = 'C:/dev/plans/2026-07-tidy-idy-gui';
const statusLog = path.join(outputDir, '_amend-d-status.log');
const artifactsDir = path.join(outputDir, 'artifacts-amend-d');
fs.mkdirSync(artifactsDir, { recursive: true });
const log = (m) => { const s = typeof m === 'string' ? m : JSON.stringify(m); fs.appendFileSync(statusLog, s + '\n'); console.log(s); };

const northStar = fs.readFileSync(path.join(outputDir, 'NORTH-STAR.md'), 'utf-8');

// The concrete change under attack: the re-scoped Wave 5 + the invariants that
// MUST survive the ownership inversion.
const plan = fs.readFileSync(path.join(outputDir, 'IMPLEMENTATION-PLAN.md'), 'utf-8');
const wave5 = plan.slice(plan.indexOf('## Wave 6 — Wave 5 —'), plan.indexOf('## Wave 7 — Wave 6 —'));

const draft = `# AMENDMENT D under adversarial review — Standalone tool + thin Anchor caller

## What changed (the ONLY change; everything else in the vetted plan is frozen)
The launch was RE-HOMED. Previously Anchor owned the launch: Anchor's button -> Anchor's job_runner -> Anchor's completion hook opened the panel. Now the TIDY-IDY TOOL owns a single canonical run-and-open-panel entry point (\`tidy-idy <folder>\`, CLI/cowork, any folder inside or outside Anchor), and Anchor's button is ONE THIN CALLER of it (dispatch via job_runner + open the tool's panel). See the re-scoped Wave 5 below.

## The re-scoped Wave 5 (verbatim)
${wave5}

## Invariants that MUST still hold after the inversion (attack these)
1. LOCK: exactly one tidy run per project root at a time — a standalone CLI run and an Anchor-button run over the same root must serialize. (Previously the lock was "registered as a job_runner resource claim"; now the tool owns the lockfile and job_runner registration is additive.)
2. PROJECT-SCOPING / TRIPWIRE: a run reads/writes nothing outside its target root, whether or not Anchor is present.
3. ARCHIVE: per-project reports/tidy/<run-NNN>/ is never overwritten; newest-first index; identical whether launched by CLI or button.
4. COST-GATE: never blocks a headless run; auto-degrades; identical on both launch paths.
5. APPROVAL / APPLY CONTROL PLANE (Wave 6): the capability token is minted in the panel-server's memory and never hits disk/URL/log; Origin/Referer checks; one Apply per run. Does a CLI-launched panel (no Anchor around) still get a correctly-scoped, single-use token and a trustworthy Origin check? Is the localhost bootstrap-nonce open-panel step safe when the opener is a bare CLI rather than Anchor?
6. ONE-CODE-PATH PARITY: the button truly adds no second launch/panel/archive logic — no divergence where the Anchor path and the CLI path can drift and one loses an invariant the other keeps.
7. REVERSIBILITY (git commit + Trash): unaffected by who launched — confirm nothing in the inversion weakens it.

## Your job
Refute the claim: "AMENDMENT D re-homes launch ownership to the tool WITHOUT losing or weakening any safety invariant, and without creating a second divergent code path." Find any invariant the inversion breaks, leaves ambiguous, or silently relies on Anchor for. A finding must trace to a North-Star criterion. If you cannot break it, say so (answerable:'no', zero findings) — do not invent bloat.`;

async function main() {
  process.env.CRUCIBLE_AGENT_LIVE = '1';
  process.env.GEMINI_MODEL = 'Gemini 3.1 Pro (High)';
  process.env.TRIO_TIER = 'heavy';
  log(`[amend-D verify] ${new Date().toISOString()} — 1 Shark round, Gemini 3.1 Pro High, routes-fix in`);

  const { agent, routes: CRUCIBLE_ROUTES } = await buildLiveCrucibleAgent({
    env: process.env, target: outputDir, log,
  });

  const verdict = await runSharkTank({ agent, northStar, draft, round: 0, artifactsDir, log });
  const out = {
    verdict: verdict.verdict, dry: verdict.dry,
    blockers: verdict.blockers.map((b) => ({ id: b.id, severity: b.severity, agreement: b.agreement, raisedBy: b.raisedBy, criterion: b.criterion, message: b.message })),
    findings: verdict.findings.map((f) => ({ id: f.id, agreement: f.agreement, raisedBy: f.raisedBy, message: f.message })),
    demoted: verdict.demoted.map((d) => d.id),
    servedModels: verdict.reviews.map((r) => ({ reviewer: r.reviewer, answerable: r.answerable, served: r.servedModel || r.served || null })),
  };
  fs.writeFileSync(path.join(outputDir, '_amend-d-verdict.json'), JSON.stringify(out, null, 2), 'utf8');
  log(`[amend-D verify] DONE — ${verdict.verdict}, ${verdict.blockers.length} blocker(s), ${verdict.findings.length} finding(s)`);
}

main().catch((e) => { log(`[amend-D ERROR] ${e && e.stack || e}`); process.exit(1); });
