// gates.mjs — Crucible's two-gate machinery + drift detector (Wave 4).
//
// MASTER-PLAN §8 draws a hard line between TWO kinds of gate. Wave 4 builds both,
// plus the post-lock drift detector, and proves a full round→tally→gate cycle this
// early (not deferred to the end):
//
//   1. WELL-FORMEDNESS gate (machine, §8). Crucible does NOT re-implement Foreman's
//      contract resolver — it SPAWNS Foreman's `locate-plan.mjs --json` as a separate
//      process and gates on its EXIT CODE (0 = the doc-trio is Foreman-ingestible).
//      Spawning (not importing) makes the result a FORGE-PROOF artifact: the captured
//      exit code + stdout + stderr is real subprocess evidence Crucible can't fake.
//      A spawn failure (ENOENT) or any non-zero exit is captured and reported as FAIL
//      — never a crash, never a silent pass.
//
//   2. QUALITY / CONVERGENCE gate (judgment, §6/§8). Lockable only when the round is
//      DRY, the Judge (bin/judge.mjs) decides CONVERGED, there are no unresolved
//      MAJOR drift flags, and the fresh-eyes pass concurs. Even then the USER is the
//      final authority: model-side-lockable HALTs for human approval rather than
//      self-locking.
//
//   3. DRIFT DETECTOR (§9). Runs ONLY after the North-Star lock (Stage-0 gaps are the
//      brainstorm seed and are exempt). A new idea surfacing = drift; it's classified
//      and offered as TWO options (recommend one): (A) out-of-scope → Grasscatcher,
//      or (B) refinement → a logged, user-approved North-Star amendment. Tiered:
//      minor = flag + offer; MAJOR = HALT + offer.

import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';

import { HaltError, haltForHuman } from './crucible-lib.mjs';

// Foreman's contract resolver, resolved relative to THIS file (Crucible is a sibling
// of Foreman at <path> ↔ <path> so it points at the real Foreman
// CLI regardless of the process cwd. We SPAWN it — never import/fork it.
const HERE = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_LOCATE_PLAN = path.resolve(HERE, '../../foreman/bin/locate-plan.mjs');

// ---------------------------------------------------------------------------
// (1) The well-formedness gate — spawn Foreman's resolver, gate on exit 0.
// ---------------------------------------------------------------------------

/**
 * Run the machine well-formedness gate by SPAWNING Foreman's `locate-plan.mjs --json`
 * over a project dir and gating on its exit code. Captures the raw exit/stdout/stderr
 * as a forge-proof artifact. NEVER throws on a bad doc-trio or a spawn failure — both
 * are reported as `pass:false` so the caller decides (a HALT lives one level up).
 *
 * Exit-code contract (locate-plan.mjs): 0 = resolved, 3 = HALT-for-human (missing/
 * ambiguous doc · no waves · no test command), 2 = internal error, null = the spawn
 * itself failed (e.g. ENOENT on the node binary).
 *
 * @param {object} o
 * @param {string}   [o.projectDir=process.cwd()]      dir whose doc-trio is checked
 * @param {string}   [o.locatePlanPath=DEFAULT_LOCATE_PLAN]
 * @param {?string}  [o.artifactsDir=null]             when set, writes the forge-proof artifact
 * @param {string}   [o.node=process.execPath]         the node binary to spawn
 * @param {Function} [o.spawn=spawnSync]               injectable transport (tests stub ENOENT)
 * @param {Function} [o.log=()=>{}]
 * @returns {{pass:boolean, status:?number, stdout:string, stderr:string,
 *            report:?object, spawnError:?object, command:string, artifactPath:?string}}
 */
export function runWellFormednessGate({
  projectDir = process.cwd(),
  locatePlanPath = DEFAULT_LOCATE_PLAN,
  artifactsDir = null,
  node = process.execPath,
  spawn = spawnSync,
  log = () => {},
} = {}) {
  const args = [locatePlanPath, '--json', projectDir];
  const r = spawn(node, args, { encoding: 'utf8' }) || {};

  const spawnError = r.error
    ? { code: r.error.code ?? null, message: String(r.error.message ?? r.error) }
    : null;
  const status = spawnError ? null : (r.status ?? null);
  const stdout = String(r.stdout ?? '');
  const stderr = spawnError ? String(r.error.message ?? r.error) : String(r.stderr ?? '');
  const pass = !spawnError && status === 0;

  // On PASS the resolver's JSON report is on stdout; surface it (parse-failure is a
  // FAIL, not a crash — a "passing" gate that emits unparseable JSON is malformed).
  let report = null;
  if (pass) {
    try {
      report = JSON.parse(stdout);
    } catch (e) {
      log(`well-formedness gate: exit 0 but stdout was not valid JSON — treating as FAIL (${e.message})`);
      return finishWellFormedness({
        pass: false, status, stdout, stderr: stderr || `exit 0 but unparseable JSON report: ${e.message}`,
        report: null, spawnError, args, node, artifactsDir, log,
      });
    }
  }

  if (spawnError) {
    log(`well-formedness gate: spawn FAILED (${spawnError.code || 'error'}: ${spawnError.message}) — reported as FAIL, no crash`);
  } else {
    log(`well-formedness gate: ${pass ? 'PASS' : `FAIL (exit ${status})`}`);
  }
  return finishWellFormedness({ pass, status, stdout, stderr, report, spawnError, args, node, artifactsDir, log });
}

/** Assemble the result and (optionally) persist the forge-proof artifact. */
function finishWellFormedness({ pass, status, stdout, stderr, report, spawnError, args, node, artifactsDir, log }) {
  const command = [node, ...args].join(' ');
  const result = { pass, status, stdout, stderr, report, spawnError, command, artifactPath: null };
  if (artifactsDir) {
    result.artifactPath = writeGateArtifact(artifactsDir, 'well-formedness-gate.json', {
      gate: 'well-formedness',
      pass, status, command, spawnError, stderr,
      // The full captured stdout IS the forge-proof evidence — store it verbatim.
      stdout, report,
    });
    log(`well-formedness gate: forge-proof artifact → ${result.artifactPath}`);
  }
  return result;
}

// ---------------------------------------------------------------------------
// (2) The quality / convergence gate — dry-round + Judge + user-approval HALT.
// ---------------------------------------------------------------------------

/**
 * Evaluate the quality/convergence gate. Lockable model-side ONLY when every model-
 * side condition holds (§6 "Lockable when"): the round is DRY, the Judge (if supplied)
 * decided CONVERGED, there are no unresolved MAJOR drift flags, and the fresh-eyes
 * pass concurs. Model-side-lockable does NOT lock — the USER is the final authority,
 * so it HALTs for human approval. With `approved:true` it returns the CONVERGED lock.
 *
 * @param {object} o
 * @param {{dry?:boolean, newBlockers?:object[]}} o.tally    the Shark-Tank round tally
 * @param {?{lockable?:boolean, decision?:string}} [o.judgeVerdict=null]
 * @param {?{lean?:string}} [o.freshEyes=null]               the fresh-eyes cold pass
 * @param {object[]} [o.driftFlags=[]]                       post-lock drift flags ({tier,resolved})
 * @param {boolean}  [o.approved=false]                      the user's final approval
 * @returns {{verdict:string, lockable:boolean, modelSideLockable:boolean,
 *            halted:boolean, reasons:string[], halt?:HaltError}}
 */
export function evaluateConvergenceGate({
  tally,
  judgeVerdict = null,
  freshEyes = null,
  driftFlags = [],
  approved = false,
} = {}) {
  const reasons = [];

  const dry = !!tally?.dry;
  if (!dry) reasons.push(`round not dry — ${tally?.newBlockers?.length ?? '?'} new BLOCKER(s) open`);

  // The Judge is optional in the gate signature (so it composes), but when supplied
  // it must have decided CONVERGED — a NOT_CONVERGED/CHALLENGE/HALT keeps the loop open.
  const judgeLockable = judgeVerdict ? judgeVerdict.lockable === true : true;
  if (judgeVerdict && !judgeLockable) reasons.push(`Judge did not converge (${judgeVerdict.decision ?? '?'})`);

  // Only UNRESOLVED MAJOR drift flags block the lock (minor flags are advisory).
  const unresolvedMajorDrift = (driftFlags || []).filter(
    (d) => d && !d.resolved && String(d.tier || '').toUpperCase() === 'MAJOR',
  );
  if (unresolvedMajorDrift.length) reasons.push(`${unresolvedMajorDrift.length} unresolved MAJOR drift flag(s)`);

  // T7 (2026-07-11): fresh-eyes is ADVISORY-unless-BLOCKER. The old rule made the
  // lock a 3-of-3 unanimity (dry AND Judge AND fresh-eyes lean) — three lock-holders
  // with no tie-break, which produced the observed live oscillation (findings
  // 22→17→20 across 4 dry rounds, ~30 calls into the cap). Now a non-lockable lean
  // HOLDS the lock only when it names a concrete BLOCKER-severity concern; a bare
  // "not-lockable" vibe is recorded as advisory for the Judge and the human, not a
  // veto. The Judge (cross-family when routed) + the dry round remain the deciders;
  // the USER remains the final authority either way.
  const freshBlockingConcerns = (freshEyes && freshEyes.lean !== 'lockable' && Array.isArray(freshEyes.concerns))
    ? freshEyes.concerns.filter((c) => c && typeof c === 'object' && /^blocker$/i.test(String(c.severity ?? '')))
    : [];
  // P1 2026-07-25 (journal 0011 item 4 — never actioned, then 0012/0046/0047-b3/0049/
  // 0052/0055/0060/0061/0067 all burned their caps on it): ONE cold-pass persona's
  // BLOCKER label was an unappealable veto outvoting a fully dry 3-Shark tank. A
  // BLOCKER concern now holds the lock only when ACCOUNTABLE: it names the North-Star
  // criterion it blocks (criterion), or its topic is corroborated by a non-demoted
  // Shark finding in this round's tally. An unaccountable BLOCKER is recorded as
  // advisory for the Judge and the human — the ≥2-agree Shark bar, the Judge, and the
  // user gate are untouched (this only downgrades a single unaccountable persona).
  const normTopic = (s) => String(s ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const tallyTopics = new Set(
    (Array.isArray(tally?.findings) ? tally.findings : [])
      .filter((f) => f && !f.demoted)
      .flatMap((f) => [normTopic(f.topic), normTopic(f.id), normTopic(f.claim_id)])
      .filter(Boolean),
  );
  const isAccountable = (c) => {
    if (typeof c.criterion === 'string' && c.criterion.trim()) return true;
    const t = normTopic(c.topic ?? c.claim_id ?? c.id);
    return !!t && tallyTopics.has(t);
  };
  const accountableBlockers = freshBlockingConcerns.filter(isAccountable);
  const advisoryBlockers = freshBlockingConcerns.filter((c) => !isAccountable(c));
  const freshHolds = accountableBlockers.length > 0;
  if (freshHolds) {
    reasons.push(`fresh-eyes pass raises ${accountableBlockers.length} accountable BLOCKER concern(s) (lean=${freshEyes?.lean ?? '?'})`);
  }
  if (advisoryBlockers.length) {
    reasons.push(`advisory: ${advisoryBlockers.length} fresh-eyes BLOCKER concern(s) name no North-Star criterion and match no Shark finding — recorded for the Judge and the human, not a veto (0011 item 4)`);
  }
  if (!freshHolds && !advisoryBlockers.length && freshEyes && freshEyes.lean !== 'lockable') {
    reasons.push(`advisory: fresh-eyes lean=${freshEyes?.lean ?? '?'} with no BLOCKER concern — recorded, not a veto`);
  }

  const modelSideLockable = dry && judgeLockable && unresolvedMajorDrift.length === 0 && !freshHolds;

  if (!modelSideLockable) {
    return { verdict: 'NOT_CONVERGED', lockable: false, modelSideLockable: false, halted: false, reasons };
  }

  // Model-side ready — but the user is the convergence authority. Without approval,
  // HALT for human rather than self-locking.
  if (!approved) {
    const halt = haltForHuman(
      'convergence reached model-side (dry round · Judge CONVERGED · no unresolved drift · fresh-eyes concurs) — approve to lock',
      'user-approval',
    );
    return {
      verdict: 'AWAITING_APPROVAL',
      lockable: false,
      modelSideLockable: true,
      halted: true,
      // T7: advisory notes (e.g. a non-lockable fresh-eyes lean with no BLOCKER)
      // ride along — recorded for the human, never silently dropped.
      reasons: [...reasons, 'model-side lockable; awaiting the user (final authority) to approve the lock'],
      halt,
    };
  }

  return {
    verdict: 'CONVERGED',
    lockable: true,
    modelSideLockable: true,
    halted: false,
    reasons: ['model-side lockable and user-approved — lock'],
  };
}

// ---------------------------------------------------------------------------
// (3) The drift detector — post-lock, tiered, two-option resolution (§9).
// ---------------------------------------------------------------------------

export const DRIFT_TIERS = { MAJOR: 'MAJOR', MINOR: 'MINOR' };

const SEV_RANK = { BLOCKER: 4, MAJOR: 3, MINOR: 2, NIT: 1 };

/**
 * The tier of a surfaced change: BLOCKER/MAJOR severity ⇒ MAJOR (HALT + offer);
 * anything lighter ⇒ MINOR (flag + offer).
 */
export function driftTier(change) {
  const sev = String(change?.severity || '').toUpperCase();
  return (SEV_RANK[sev] || 0) >= SEV_RANK.MAJOR ? DRIFT_TIERS.MAJOR : DRIFT_TIERS.MINOR;
}

/**
 * Classify a surfaced change into the recommended resolution OPTION (§9):
 *   (A) out-of-scope → Grasscatcher (with a suggested future home), or
 *   (B) refinement → sharpen the North Star (a logged, user-approved amendment).
 * A change tagged `refinement` OR tracing to a North-Star criterion is option B;
 * otherwise (out-of-scope / non-tracing) it is option A.
 */
export function classifyDriftOption(change) {
  const traces = String(change?.traces_to_north_star || '').toLowerCase() === 'yes';
  const tag = change?.tag;
  const isRefinement = tag === 'refinement' || (traces && tag !== 'out-of-scope');
  if (isRefinement) {
    return {
      option: 'B',
      resolution: 'north-star-amendment',
      requires_user_approval: true,
      detail: 'refinement that serves the objective — sharpen the North Star via a logged, user-approved amendment',
    };
  }
  return {
    option: 'A',
    resolution: 'grasscatcher',
    suggested_home: change?.suggested_home || 'GRASSCATCHER.md',
    detail: 'out-of-scope — park in the Grasscatcher with a suggested future home',
  };
}

/**
 * Detect drift for a single surfaced change/idea.
 *
 * Drift detection runs ONLY after the North-Star lock — pre-lock, Stage-0 gaps are
 * the brainstorm seed and are exempt (returns inactive). After the lock, a surfaced
 * idea is drift: it is tiered (minor flag vs MAJOR HALT) and presented with the two
 * resolution options, the classifier's recommendation marked. MAJOR drift carries a
 * HALT-for-human (the §11 MAJOR-drift gate).
 *
 * @param {object}  change                         a surfaced finding/idea ({severity,tag,traces_to_north_star,topic,message})
 * @param {object} [o]
 * @param {boolean}[o.locked=false]                has the North Star been locked?
 * @returns {{drift:boolean, active:boolean, tier?:string, action?:'HALT'|'FLAG',
 *            recommended?:'A'|'B', resolution?:string, options?:object[],
 *            reason:string, halt?:HaltError}}
 */
export function detectDrift(change, { locked = false } = {}) {
  if (!locked) {
    return {
      drift: false,
      active: false,
      reason: 'pre-lock: drift detection runs only after the North-Star lock (Stage-0 gaps are the brainstorm seed and are exempt)',
    };
  }

  const tier = driftTier(change);
  const choice = classifyDriftOption(change);
  const action = tier === DRIFT_TIERS.MAJOR ? 'HALT' : 'FLAG';

  const options = [
    {
      id: 'A',
      label: 'out-of-scope → Grasscatcher',
      resolution: 'grasscatcher',
      suggested_home: change?.suggested_home || 'GRASSCATCHER.md',
      recommended: choice.option === 'A',
    },
    {
      id: 'B',
      label: 'refinement → sharpen the North Star (logged amendment, user-approved)',
      resolution: 'north-star-amendment',
      requires_user_approval: true,
      recommended: choice.option === 'B',
    },
  ];

  const label = change?.topic || change?.message || 'a new idea surfaced after the lock';
  const result = {
    drift: true,
    active: true,
    tier,
    action,
    recommended: choice.option,
    resolution: choice.resolution,
    options,
    reason: `${tier} drift: ${label} — ${tier === DRIFT_TIERS.MAJOR ? 'HALT + offer two options' : 'flag + offer two options'} (recommend ${choice.option})`,
  };
  if (tier === DRIFT_TIERS.MAJOR) {
    // MAJOR drift HALTs for human: the §11 MAJOR-drift gate. pending_action carries
    // the recommended resolution so the orchestrator can re-prompt precisely.
    result.halt = haltForHuman(`MAJOR drift after lock: ${label}`, `drift-resolution:${choice.option}`);
  }
  return result;
}

// ---------------------------------------------------------------------------
// Shared artifact writer.
// ---------------------------------------------------------------------------

/** Write a gate artifact to `dir/name` (creating `dir`); returns the path. */
export function writeGateArtifact(dir, name, payload) {
  if (!dir) throw new HaltError('writeGateArtifact requires a dir', 'pass an artifactsDir');
  fs.mkdirSync(dir, { recursive: true });
  const p = path.join(dir, name);
  fs.writeFileSync(p, JSON.stringify(payload, null, 2));
  return p;
}
