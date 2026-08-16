/**
 * Wave 5 — G5 HALT inventory + classification.
 *
 * Every human gate on the real Crucible / Foreman / researchPrime / Gandalf
 * commission path at file:line, classed:
 *   EXTERNALLY-OBSERVABLE | REQUIRES-TRIO-CHANGE | INVISIBLE
 *
 * Paths are SKILL-REPO RELATIVE (not Ecgberht-repo absolute). Resolved under
 * the skill install root (e.g. the host's skills directory). Host homes are
 * never embedded. Citations verified against skill sources on this host.
 *
 * The documented gated-lane fragility `job_runner.py:574-578` is ABSORBED into
 * the class of any skill whose commission path rides a gated lane.
 * INVISIBLE-HALT profiles are named and excluded in the Face.
 */

export const HALT_INVENTORY_SCHEMA = 'ecgberht-halt-inventory-v0';

export const HALT_CLASSES = Object.freeze([
  'EXTERNALLY-OBSERVABLE',
  'REQUIRES-TRIO-CHANGE',
  'INVISIBLE',
]);

/**
 * Path roots for citations — relative skill/host trees only (no host homes).
 * `skill` = install root of that skill; `anchor` = Anchor host repo root.
 */
export const HALT_PATH_ROOTS = Object.freeze({
  researchPrime: { kind: 'skill', skill: 'researchPrime', note: 'paths relative to researchPrime skill root' },
  Crucible: { kind: 'skill', skill: 'crucible', note: 'paths relative to crucible skill root' },
  Foreman: { kind: 'skill', skill: 'foreman', note: 'paths relative to foreman skill root' },
  Gandalf: { kind: 'skill', skill: 'gandalf', note: 'paths relative to gandalf skill root' },
  Jumper: { kind: 'skill', skill: 'jumper', note: 'paths relative to jumper skill root' },
  '*': {
    kind: 'anchor_host',
    note: 'job_runner.py paths are relative to the Anchor host repo root (reference host)',
  },
});

/** Documented gated-lane fragility absorbed into gated-lane skills. */
export const GATED_LANE_FRAGILITY = Object.freeze({
  path: 'job_runner.py',
  path_root: 'anchor_host',
  lines: '574-578',
  line_start: 574,
  line_end: 578,
  symbol: 'launch_guarded stdin handling (GATED)',
  summary:
    'GATED (plan/build, claude only) stdin=PIPE AskUserQuestion plain-text-after-auto-dismiss path is inherently FRAGILE — best-effort continuation, not guaranteed.',
  absorbed_into:
    'class of any skill whose commission path rides a gated lane (PLAN/BUILD)',
  class: 'REQUIRES-TRIO-CHANGE',
  verified: true,
});

/**
 * Human gates on the real commission paths (relative skill/host paths; no host homes).
 * `line` points at the primary symbol / throw / doc heading cited; verified.
 */
export const HALT_GATES = Object.freeze([
  // ── researchPrime ──────────────────────────────────────────────────
  {
    id: 'rp-plan-review-gate',
    skill: 'researchPrime',
    path: 'bin/plan-gate.mjs',
    path_root: 'skill:researchPrime',
    line: 72,
    symbol: 'runPlanReviewGate',
    description:
      'Phase-1 plan review APPROVE/EDIT/ABORT human gate before execution spend',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'rp-approval-provider',
    skill: 'researchPrime',
    path: 'bin/approval-provider.mjs',
    path_root: 'skill:researchPrime',
    line: 95,
    symbol: 'requireApproval (no grant → HaltError)',
    description:
      'HaltError when no valid approval provider grant (no human channel, no token)',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'rp-gate-loader-g1-g2',
    skill: 'researchPrime',
    path: 'bin/gate-loader.mjs',
    path_root: 'skill:researchPrime',
    line: 28,
    symbol: 'loadGate (gate1Decision/gate2Decision APPROVE checks)',
    description: 'Gate 1 / Gate 2 must be APPROVE or execution is blocked',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'rp-preregistration-halt',
    skill: 'researchPrime',
    path: 'IMPLEMENTATION-PLAN.md',
    path_root: 'skill:researchPrime',
    line: 30,
    symbol: 'preregistration-RED HALT-for-human (I6)',
    description:
      'Preregistration RED ⇒ Foreman HALTs; human commits thresholds; resume (I6)',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },

  // ── Crucible ───────────────────────────────────────────────────────
  {
    id: 'crucible-haltForHuman',
    skill: 'Crucible',
    path: 'bin/crucible-lib.mjs',
    path_root: 'skill:crucible',
    line: 203,
    symbol: 'haltForHuman',
    description: 'HALT-for-human primitive with pending_action on checkpoint',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'crucible-stage0-north-star-lock',
    skill: 'Crucible',
    path: 'bin/crucible-lib.mjs',
    path_root: 'skill:crucible',
    line: 181,
    symbol: "HALT_GATES['stage0->stage1']",
    description: 'Stage 0 framing done — lock the North Star (you-approve)',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'crucible-stage1-master-plan-approval',
    skill: 'Crucible',
    path: 'bin/crucible-lib.mjs',
    path_root: 'skill:crucible',
    line: 185,
    symbol: "HALT_GATES['stage1->stage2']",
    description: 'Master Plan converged — approve to proceed (you-approve)',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'crucible-stage2-impl-plan-approval',
    skill: 'Crucible',
    path: 'bin/crucible-lib.mjs',
    path_root: 'skill:crucible',
    line: 189,
    symbol: "HALT_GATES['stage2->done']",
    description:
      'Implementation Plan converged — approve to hand off to Foreman (you-approve)',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'crucible-advance-without-approval',
    skill: 'Crucible',
    path: 'bin/crucible-lib.mjs',
    path_root: 'skill:crucible',
    line: 276,
    symbol: 'makeStateMachine.advance',
    description:
      'advance({approved:false}) throws boundary HALT — human is convergence authority',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'crucible-gated-lane-fragility',
    skill: 'Crucible',
    path: 'job_runner.py',
    path_root: 'anchor_host',
    line: 574,
    symbol: 'launch_guarded GATED stdin=PIPE AskUserQuestion path',
    description:
      'PLAN commissions ride the gated lane — absorb job_runner.py:574-578 fragility',
    class: 'REQUIRES-TRIO-CHANGE',
    gated_lane: true,
    absorbs_fragility: true,
  },

  // ── Foreman ────────────────────────────────────────────────────────
  {
    id: 'foreman-HaltError',
    skill: 'Foreman',
    path: 'bin/foreman-lib.mjs',
    path_root: 'skill:foreman',
    line: 26,
    symbol: 'HaltError',
    description: 'Recoverable HALT-for-human; CLIs map to exit code 3',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'foreman-locate-docs-missing',
    skill: 'Foreman',
    path: 'bin/foreman-lib.mjs',
    path_root: 'skill:foreman',
    line: 64,
    symbol: 'locateDocs',
    description: '0 or >1 doc candidates → HALT (never guess which plan)',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'foreman-parse-waves',
    skill: 'Foreman',
    path: 'bin/foreman-lib.mjs',
    path_root: 'skill:foreman',
    line: 162,
    symbol: 'parseWaves',
    description: 'No parseable wave structure → HALT',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'foreman-budget-nonconvergence',
    skill: 'Foreman',
    path: 'SKILL.md',
    path_root: 'skill:foreman',
    line: 210,
    symbol: '§6 Halt-for-human conditions',
    description:
      'Budget / iter / wall-clock / non-convergence / ambiguity / vacuous-GREEN HALTs',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'foreman-pending-action',
    skill: 'Foreman',
    path: 'SKILL.md',
    path_root: 'skill:foreman',
    line: 262,
    symbol: 'checkpoint.pending_action',
    description: 'Exact recommended next action on halt for human resume',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'foreman-gated-lane-fragility',
    skill: 'Foreman',
    path: 'job_runner.py',
    path_root: 'anchor_host',
    line: 574,
    symbol: 'launch_guarded GATED stdin=PIPE AskUserQuestion path',
    description:
      'BUILD commissions ride the gated lane — absorb job_runner.py:574-578 fragility',
    class: 'REQUIRES-TRIO-CHANGE',
    gated_lane: true,
    absorbs_fragility: true,
  },

  // ── Gandalf ────────────────────────────────────────────────────────
  {
    id: 'gandalf-sleep-gate',
    skill: 'Gandalf',
    path: 'LESSONS.md',
    path_root: 'skill:gandalf',
    line: 8,
    symbol: 'anti-drift sleep gate',
    description:
      'Deterministic canary sleep gate — human re-lock only on escalated drift (not mid-run ask)',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
  {
    id: 'gandalf-principle-d-advisory',
    skill: 'Gandalf',
    path: 'LESSONS.md',
    path_root: 'skill:gandalf',
    line: 30,
    symbol: 'PRINCIPLE-D',
    description:
      'LLM/cross-family judge is ADVISORY only — never part of the sleep gate (invisible to product loop if mis-wired)',
    class: 'INVISIBLE',
    gated_lane: false,
    invisible_profile: 'gandalf-advisory-judge-as-gate',
  },

  // ── Jumper (commission candidate; ideation) ────────────────────────
  {
    id: 'jumper-killgates-floor-halt',
    skill: 'Jumper',
    path: 'SKILL.md',
    path_root: 'skill:jumper',
    line: 35,
    symbol: 'killGates floor / JumperKillGatesFloorHalt',
    description:
      'Ideation HALT surfaces when killGates floor refused or 3-gate kill-filter rejects; grounding fails honestly',
    class: 'EXTERNALLY-OBSERVABLE',
    gated_lane: false,
  },
]);

/**
 * INVISIBLE-HALT profiles — named and excluded in the Face (never shown as
 * healthy absence; never silently omitted from exclusion lists).
 */
export const INVISIBLE_HALT_PROFILES_EXCLUDED_IN_FACE = Object.freeze([
  {
    id: 'gandalf-advisory-judge-as-gate',
    skill: 'Gandalf',
    reason:
      'Advisory judge/oracle must never be presented as a Face human gate; PRINCIPLE-D isolation',
  },
  {
    id: 'gated-lane-plain-text-reask',
    skill: '*',
    reason:
      'job_runner.py:574-578 AskUserQuestion plain-text re-ask is not a Face-visible confirm surface; excluded from Face gate chrome',
  },
]);

const CLASS_RANK = Object.freeze({
  'EXTERNALLY-OBSERVABLE': 0,
  'REQUIRES-TRIO-CHANGE': 1,
  INVISIBLE: 2,
});

/**
 * Worst class among a skill's gates (INVISIBLE > REQUIRES-TRIO-CHANGE > EXTERNALLY-OBSERVABLE).
 * Gated-lane absorption: any skill with a gated_lane gate inherits that class.
 *
 * @param {string} skill
 * @param {object[]} [gates]
 * @returns {'EXTERNALLY-OBSERVABLE'|'REQUIRES-TRIO-CHANGE'|'INVISIBLE'}
 */
export function skillHaltClass(skill, gates = HALT_GATES) {
  const mine = gates.filter((g) => g.skill === skill);
  if (!mine.length) return 'INVISIBLE';
  let worst = 'EXTERNALLY-OBSERVABLE';
  for (const g of mine) {
    const c = g.class;
    if ((CLASS_RANK[c] ?? 0) > (CLASS_RANK[worst] ?? 0)) worst = c;
  }
  return worst;
}

/**
 * Build the full halt-inventory artifact body (pure).
 * @param {{ gates?: object[] }} [opts]
 */
export function buildHaltInventory(opts = {}) {
  const gates = opts.gates ?? HALT_GATES.map((g) => ({ ...g }));
  const skills = [
    ...new Set(gates.map((g) => g.skill).filter((s) => s && s !== '*')),
  ].sort();
  const skill_classes = {};
  for (const skill of skills) {
    skill_classes[skill] = skillHaltClass(skill, gates);
  }
  return {
    schema: HALT_INVENTORY_SCHEMA,
    path_roots: { ...HALT_PATH_ROOTS },
    gated_lane_fragility: { ...GATED_LANE_FRAGILITY },
    gates,
    skill_classes,
    invisible_halt_profiles_excluded_in_face: [
      ...INVISIBLE_HALT_PROFILES_EXCLUDED_IN_FACE,
    ],
    notes: [
      'Paths are skill-repo relative (path_root) or Anchor-host relative for job_runner.py — never host-home absolute.',
      'Gated-lane fragility job_runner.py:574-578 is absorbed into PLAN/BUILD skills (Crucible/Foreman) as REQUIRES-TRIO-CHANGE.',
      'INVISIBLE profiles are named here and excluded in the Face — never rendered as empty/healthy.',
    ],
  };
}
