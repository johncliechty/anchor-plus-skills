// Stage-1 driver — Honest Spend Telemetry v2 (Crucible FULL, all-Claude Heavy).
// Launched in the background by the driving session; status rides
// _crucible-status.log (the LOCKED table via the engine heartbeat).
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const CRUCIBLE = 'file:///C:/Users/john/.claude/skills/crucible/bin';

const { makeAgentSeam } = await import(`${CRUCIBLE}/agent.mjs`);
const { runStage1 } = await import(`${CRUCIBLE}/stage1.mjs`);

const northStar = readFileSync(join(HERE, 'NORTH-STAR.md'), 'utf8');
const criteria = [
  'Swarm spend visible going forward: --session-id pinned, owner+reconcile finalize, CAS-arbitrated',
  'Interactive spend surfaces as a SEPARATE rollup line; __doctor__ excluded everywhere',
  'Hermetic finalize skips WITHOUT consuming the finalize-once CAS (regression-tested)',
  'History recovered via deterministic worktree-dirname backfill, usage_state=measured-backfill, never overwrites live-measured',
  'Dollars = labeled subscription-equivalent estimate from a maintained pricing table; envelope $ distinct',
  'Honest counting: cost-less members no longer inflate the sessions count',
];

const artifactsDir = join(HERE, 'stage1-artifacts');
mkdirSync(artifactsDir, { recursive: true });

const { agent } = makeAgentSeam({
  target: 'C:/dev/Anchor',
  log: (m) => console.log(m),
});

try {
  const result = await runStage1({
    agent,
    northStar,
    criteria,
    depth: 'FULL',
    grasscatcherPath: join(HERE, 'GRASSCATCHER.md'),
    artifactsDir,
    statusLog: join(HERE, '_crucible-status.log'),
    log: (m) => console.log(m),
  });
  writeFileSync(join(HERE, 'MASTER-PLAN-DRAFT.md'),
    (result.loop && result.loop.draft) || (result.plan && JSON.stringify(result.plan, null, 2)) || '(no draft)');
  writeFileSync(join(HERE, 'stage1-result.json'), JSON.stringify({
    approved: result.approval ? result.approval.approved : false,
    roundsRun: result.loop ? result.loop.roundsRun : null,
  }, null, 2));
  console.log('STAGE1-DONE');
} catch (err) {
  // The user-approval HALT is the EXPECTED terminal state of an unattended
  // Stage-1 run (the user approves in chat, never in-process). Persist
  // everything the halt carries; per-round drafts are already in
  // stage1-artifacts/ (T5 — the loop persists best draft + open findings).
  const dump = { name: err.name, message: err.message, todo: err.todo || null };
  for (const k of ['draft', 'openFindings', 'roundsRun', 'converged', 'state']) {
    if (err[k] !== undefined) dump[k] = err[k];
  }
  writeFileSync(join(HERE, 'stage1-result.json'), JSON.stringify(dump, null, 2));
  if (typeof err.draft === 'string' && err.draft.length) {
    writeFileSync(join(HERE, 'MASTER-PLAN-DRAFT.md'), err.draft);
  }
  const expected = /approval|master-plan-approval/i.test(String(err.message));
  console.log(expected ? 'STAGE1-HALTED-FOR-APPROVAL' : `STAGE1-ERROR: ${err.message}`);
  process.exit(expected ? 0 : 1);
}
