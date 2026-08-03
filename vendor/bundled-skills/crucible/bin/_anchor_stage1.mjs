import { writeFileSync } from 'node:fs';
import { buildLiveCrucibleAgent } from './enhanced.mjs';
import { runStage1 } from './stage1.mjs';

const OUT = '<path>';

// Seats from coding/review family prefs — no hardcoded Claude/model ids.

const northStar =
  "Transform the integrated Anchor system (the Anchor app + the researchPrime/Crucible/Foreman trio + the " +
  "foundry skills + their operating conventions) from a single-user, single-machine tool into a package a " +
  "trusted collaborator can obtain and run on their own Windows/macOS/Linux machine, such that: (1) they " +
  "receive it as a scrubbed, self-contained bundle that never carries the author's personal or proprietary " +
  "data; (2) onboarding brings up a working, secure-by-default instance with zero manual token handling; " +
  "(3) the instance is safe to run and safe to expose (no unauthenticated data-read or code-execution " +
  "surface); (4) the agent trio behaves identically to the author's (same governance, status discipline, " +
  "skill-immutability); and (5) none of this regresses the durability, honesty, and safety engineering the " +
  "system already has. Non-goals: the WAL inversion (deferred), multi-user/multi-tenant on one instance, " +
  "OS-level agent sandboxing, a frontend rewrite, cloud hosting, an observability stack, re-architecting the " +
  "trio/foundry skills' internals.";

const criteria = [
  "Secure-by-default: a freshly-onboarded instance behind a loopback reverse proxy returns 401 to a tokenless request on every data-plane, terminal, and dir-browse route, and the bypassPermissions build lane is unreachable without the token; no unauthenticated read/filesystem-enumeration/code-execution surface remains.",
  "Zero-friction token: the author and each collaborator never manually find or type a token — auto-provisioned + persisted locally at onboard, auto-used by the local browser, survives restarts.",
  "No-leak distribution: the only share channel is a scrubbed bundle containing none of the author's personal/proprietary files or git history; import anchor_gui inside the staged bundle boots (smoke-gated).",
  "Works-on-arrival cross-platform: a collaborator on Windows and macOS/Linux goes bundle -> onboard -> live dashboard via one documented path; missing prerequisites surface as one upfront actionable message.",
  "Identical agent behavior: trio + foundry skills run under the same governance — 10-min status format, skills read-only/foundry-only-edit, driver-init self-configures to the host's engines.",
  "No durability regression: the durability cluster (CLI+secondary atomic writes, cross-process lock, torn-index rebuild-from-pointers, boot-reaper owner-set) is closed and covered; existing telemetry/narration/reaper-safety invariants hold.",
  "Money-safe + clean: the test suite cannot spend real money without explicit opt-in (fail-closed); shipped tree free of dev debris and dependency-doc contradictions.",
];

console.log('[anchor-stage1] building live agent from coding/review family prefs...');
const { agent, tracker, routes } = await buildLiveCrucibleAgent({});
console.log('[anchor-stage1] agent built; routes=', JSON.stringify(routes));
console.log('[anchor-stage1] starting runStage1 (FULL depth)...');

try {
  const result = await runStage1({
    agent,
    northStar,
    criteria,
    depth: 'FULL',
    artifactsDir: OUT + '/stage1-artifacts',
    statusLog: OUT + '/_crucible-status.log',
    routes,
    log: (m) => console.log('[stage1]', m),
  });
  writeFileSync(OUT + '/stage1-result.json', JSON.stringify(result, null, 2));
  const plan = result.plan || {};
  const loop = result.loop || {};
  const md = [
    '# Master Plan (DRAFT) — Anchor securely & easily shareable',
    '', '_Crucible Stage 1 output (FULL depth, Heavy cross-family). Draft for your approval._', '',
    '## Convergence',
    '- converged: ' + JSON.stringify(loop.converged ?? loop.status ?? 'see stage1-result.json'),
    '- rounds: ' + JSON.stringify(loop.rounds ?? loop.round ?? 'n/a'),
    '- open findings: ' + JSON.stringify((loop.openFindings || loop.findings || []).length ?? 'n/a'),
    '- families reached: ' + JSON.stringify([...(tracker.families ? tracker.families() : [])]),
    '',
    '## Phased plan',
    '```json',
    JSON.stringify(plan, null, 2),
    '```',
  ].join('\n');
  writeFileSync(OUT + '/MASTER-PLAN-DRAFT.md', md);
  console.log('[anchor-stage1] DONE — wrote MASTER-PLAN-DRAFT.md + stage1-result.json');
} catch (e) {
  writeFileSync(OUT + '/stage1-ERROR.txt', String(e && e.stack || e));
  console.log('[anchor-stage1] HALT/ERROR:', e && e.message);
  console.log('[anchor-stage1] (a round-cap HALT is normal — best draft + open findings are persisted in stage1-artifacts/)');
}
