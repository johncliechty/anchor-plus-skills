// checklist.mjs — Crucible's 5-gate Skill Productionization Checklist (Wave 11).
//
// MASTER-PLAN §1 defines Crucible's North Star by FIVE success criteria; the
// "Skill Productionization Checklist (5 gates)" (DESCRIPTION / IMPLEMENTATION-PLAN
// Wave 11) is the production-readiness gate that checks the engine actually meets
// each one. So the five gates ARE the five North-Star criteria, made checkable
// against the evidence the dogfood self-run (bin/self-run.mjs) produces:
//
//   G1 (criterion 1) Foreman-ready output — the emitted doc-trio passes the machine
//        well-formedness gate (locate-plan exit 0, ZERO HALTs) and every wave carries
//        testable acceptance criteria (a done-when).
//   G2 (criterion 2) Convergence + approval — the Shark Tank draws no new blood (a
//        real finding tallied in one round → a SUBSEQUENT dry round) and the user
//        approves (the user is the convergence authority).
//   G3 (criterion 3) Zero untracked drift — post-lock drift detection is active and
//        every surfaced item is tracked (flag / HALT / Grasscatcher); none silently
//        absorbed.
//   G4 (criterion 4) Autonomous between gates + checkpoint/resume — the run HALTs only
//        at a defined user gate and resumes from a checkpoint that the durable
//        Foreman primitives validated on read.
//   G5 (criterion 5) Independence honored — fresh-context Sharks + a context-free Judge,
//        with a per-role model STAMP on every model-side role (degraded-and-stamped
//        when no other family is reachable).
//
// This module is REAL EXECUTED SOURCE (it satisfies Foreman's vacuous-GREEN guard for
// Wave 11): each gate is a pure predicate over the self-run's evidence, and
// `runProductionizationChecklist` aggregates them into a single pass/fail tally. The
// SKILL.md manifest checker lives here too (a skill is not productionized without a
// well-formed manifest), exercised directly by the wave's tests.

import fs from 'node:fs';

import { HaltError, haltForHuman } from './crucible-lib.mjs';

// ---------------------------------------------------------------------------
// The five gates (= the five North-Star criteria).
// ---------------------------------------------------------------------------

/** The canonical 5-gate definition. `criterion` is the MASTER-PLAN §1 success criterion. */
export const PRODUCTIONIZATION_GATES = [
  { id: 'G1', criterion: 1, title: 'Foreman-ready output — locate-plan accepts the doc-trio with zero HALTs; every wave has acceptance criteria' },
  { id: 'G2', criterion: 2, title: 'Convergence + approval — the Shark Tank draws no new blood (finding → dry round) and the user approves' },
  { id: 'G3', criterion: 3, title: 'Zero untracked drift — post-lock drift is tracked (flag / HALT / Grasscatcher), none silently absorbed' },
  { id: 'G4', criterion: 4, title: 'Autonomous between gates with checkpoint/resume — HALTs only at a user gate; resumes from a validated checkpoint' },
  { id: 'G5', criterion: 5, title: 'Independence honored — fresh-context Sharks + Judge; a per-role model stamp on every role (degraded-and-stamped)' },
];

function gateMeta(id) {
  return PRODUCTIONIZATION_GATES.find((g) => g.id === id);
}

/** Assemble one gate result, carrying its definition so a report is self-describing. */
function result(id, pass, detail, evidence = null) {
  const meta = gateMeta(id);
  return { id, criterion: meta.criterion, title: meta.title, pass: !!pass, detail, evidence };
}

// ---------------------------------------------------------------------------
// G1 — Foreman-ready output (criterion 1).
// ---------------------------------------------------------------------------

/**
 * Gate 1: the emitted doc-trio passes the machine well-formedness gate (locate-plan
 * exit 0 = zero HALTs) AND every wave carries a testable acceptance criterion (a
 * one-line done-when, D16). A FAIL here means Foreman would HALT on the handoff.
 *
 * @param {object}  o
 * @param {?object} o.wellFormedness   a runWellFormednessGate() result ({pass,status,...})
 * @param {object[]}[o.waves=[]]        the emitted waves (each must have a done-when)
 */
export function checkForemanReadyOutput({ wellFormedness, waves = [] } = {}) {
  const gatePass = !!wellFormedness && wellFormedness.pass === true && wellFormedness.status === 0;
  const haveWaves = Array.isArray(waves) && waves.length > 0;
  const everyWaveHasDoneWhen = haveWaves && waves.every((w) => w && String(w.doneWhen || '').trim());
  const pass = gatePass && everyWaveHasDoneWhen;

  const detail = pass
    ? `well-formedness gate PASS (exit 0, zero HALTs); all ${waves.length} wave(s) carry a done-when`
    : !gatePass
      ? `well-formedness gate did not pass (pass=${wellFormedness?.pass ?? 'n/a'}, exit=${wellFormedness?.status ?? 'n/a'})`
      : `${waves.filter((w) => !String(w?.doneWhen || '').trim()).length} wave(s) missing a done-when`;
  return result('G1', pass, detail, { status: wellFormedness?.status ?? null, waveCount: waves.length });
}

// ---------------------------------------------------------------------------
// G2 — Convergence + approval (criterion 2).
// ---------------------------------------------------------------------------

/**
 * Gate 2: convergence is PROVEN, not assumed — a real finding was tallied in one
 * round and a SUBSEQUENT round was dry (the Shark Tank drew no new blood), and the
 * user approved (the convergence authority).
 *
 * @param {object}  o
 * @param {object}  o.convergence   {findingRound:{round,blockers}, dryRound:{round}, proved}
 * @param {?object} o.approval      {approved:boolean}
 */
export function checkConvergenceApproval({ convergence, approval } = {}) {
  const fr = convergence?.findingRound;
  const dr = convergence?.dryRound;
  const findingTallied = !!fr && Number(fr.blockers) > 0;
  const laterDryRound = !!dr && !!fr && Number(dr.round) > Number(fr.round);
  const approved = approval?.approved === true;
  const pass = findingTallied && laterDryRound && approved;

  const detail = pass
    ? `finding tallied at round ${fr.round} (${fr.blockers} blocker[s]) → dry round ${dr.round}; user approved`
    : !findingTallied
      ? 'no real finding was ever tallied — convergence cannot be demonstrated from a vacuous run'
      : !laterDryRound
        ? 'no dry round followed the finding (the Shark Tank still drew blood)'
        : 'the user has not approved (the user is the convergence authority)';
  return result('G2', pass, detail, { findingRound: fr ?? null, dryRound: dr ?? null, approved });
}

// ---------------------------------------------------------------------------
// G3 — Zero untracked drift (criterion 3).
// ---------------------------------------------------------------------------

/**
 * Gate 3: post-lock drift detection is ACTIVE and every surfaced item was TRACKED
 * (flagged, HALTed, or routed to the Grasscatcher) — zero silently absorbed.
 *
 * @param {object}  o
 * @param {object}  o.drift   {active:boolean, surfaced:object[], untracked:number}
 */
export function checkNoUntrackedDrift({ drift } = {}) {
  const active = drift?.active === true;
  const untracked = Number(drift?.untracked ?? (Array.isArray(drift?.surfaced) ? drift.surfaced.filter((s) => !s?.tracked).length : NaN));
  const pass = active && untracked === 0;

  const detail = pass
    ? `drift detection active; ${Array.isArray(drift?.surfaced) ? drift.surfaced.length : 0} surfaced item(s), 0 untracked`
    : !active
      ? 'drift detection is not active post-lock (the anti-drift pillar is not engaged)'
      : `${untracked} surfaced item(s) were not tracked (silent drift)`;
  return result('G3', pass, detail, { active, untracked });
}

// ---------------------------------------------------------------------------
// G4 — Autonomous between gates + checkpoint/resume (criterion 4).
// ---------------------------------------------------------------------------

/**
 * Gate 4: the run HALTed only at a defined user gate, persisted a checkpoint with the
 * exact pending action, and RESUMED from it — and the checkpoint was validated on read
 * (the durable Foreman primitives, not a best-effort parse).
 *
 * @param {object}  o
 * @param {object}  o.checkpointResume  {halted, gate, pendingAction, checkpointPath, validated, resumed}
 */
export function checkAutonomousResume({ checkpointResume } = {}) {
  const cr = checkpointResume || {};
  const haltedAtGate = cr.halted === true && !!cr.pendingAction;
  const validated = cr.validated === true;
  const resumed = cr.resumed === true;
  const pass = haltedAtGate && validated && resumed;

  const detail = pass
    ? `HALTed at the "${cr.pendingAction}" user gate, wrote + re-validated the checkpoint, and resumed`
    : !haltedAtGate
      ? 'did not HALT at a defined user gate (no pending_action recorded)'
      : !validated
        ? 'the checkpoint did not validate on read (durable resume not proven)'
        : 'the run did not resume after the HALT';
  return result('G4', pass, detail, { pendingAction: cr.pendingAction ?? null, validated, resumed });
}

// ---------------------------------------------------------------------------
// G5 — Independence honored + stamped (criterion 5).
// ---------------------------------------------------------------------------

/** A valid per-role stamp names the role + model + mode and records cross_model honestly. */
function validStamp(s) {
  return !!s
    && typeof s.role === 'string' && s.role.length > 0
    && typeof s.model === 'string' && s.model.length > 0
    && typeof s.mode === 'string' && s.mode.length > 0
    && typeof s.cross_model === 'boolean'
    // Independence is only genuinely cross-model in Enhanced mode; a Default-mode stamp
    // claiming cross_model is a provenance lie, not honored independence.
    && (s.mode !== 'default' || s.cross_model === false);
}

/**
 * Gate 5: independence is honored AND recorded. Every model-side role carries a valid
 * per-role stamp; at minimum the Judge and the Synthesizer are stamped. Default mode
 * (no other family reachable) is fine — it must be degraded-AND-stamped, not silent.
 *
 * @param {object}  o
 * @param {object[]}o.stamps   per-role stamps (stampRole results), e.g. [synthesizer, judge]
 */
export function checkIndependence({ stamps = [] } = {}) {
  const list = Array.isArray(stamps) ? stamps.filter(Boolean) : [];
  const roles = new Set(list.map((s) => s.role));
  const allValid = list.length > 0 && list.every(validStamp);
  const hasJudge = roles.has('Judge');
  const hasSynth = roles.has('Synthesizer');
  const pass = allValid && hasJudge && hasSynth;

  const detail = pass
    ? `${list.length} role stamp(s) present + valid (${[...roles].join(', ')}); ${list.every((s) => !s.cross_model) ? 'degraded-and-stamped (Default mode)' : 'cross-model honored'}`
    : !allValid
      ? 'a model-side role is missing a valid per-role stamp (independence not recorded)'
      : `missing a required role stamp (Judge:${hasJudge}, Synthesizer:${hasSynth})`;
  return result('G5', pass, detail, { roles: [...roles] });
}

// ---------------------------------------------------------------------------
// The checklist — run all five gates and tally.
// ---------------------------------------------------------------------------

/**
 * Run the full 5-gate Skill Productionization Checklist over the self-run's evidence.
 * Pure (no I/O): every input is evidence the self-run already produced. Returns the
 * per-gate results + the aggregate tally.
 *
 * @param {object}  o
 * @param {?object} o.wellFormedness     G1: a runWellFormednessGate() result
 * @param {object[]}[o.waves=[]]          G1: the emitted waves
 * @param {object}  o.convergence        G2: {findingRound, dryRound, proved}
 * @param {?object} o.approval           G2: {approved}
 * @param {object}  o.drift              G3: {active, surfaced, untracked}
 * @param {object}  o.checkpointResume   G4: {halted, pendingAction, validated, resumed}
 * @param {object[]}o.stamps             G5: per-role stamps
 * @returns {{gates:object[], passed:number, total:number, allPass:boolean}}
 */
export function runProductionizationChecklist({
  wellFormedness,
  waves = [],
  convergence,
  approval,
  drift,
  checkpointResume,
  stamps = [],
} = {}) {
  const gates = [
    checkForemanReadyOutput({ wellFormedness, waves }),
    checkConvergenceApproval({ convergence, approval }),
    checkNoUntrackedDrift({ drift }),
    checkAutonomousResume({ checkpointResume }),
    checkIndependence({ stamps }),
  ];
  const passed = gates.filter((g) => g.pass).length;
  return { gates, passed, total: gates.length, allPass: passed === gates.length };
}

/** Render the checklist tally as a human-readable block (for the self-run transcript). */
export function renderChecklist(checklist) {
  const lines = [`Skill Productionization Checklist — ${checklist.passed}/${checklist.total} gate(s) pass`];
  for (const g of checklist.gates) {
    lines.push(`  ${g.pass ? '✓' : '✗'} ${g.id} (criterion ${g.criterion}): ${g.detail}`);
  }
  return lines.join('\n');
}

/**
 * Assert the checklist passed — HALTs for human with the failing gates named if not.
 * Used by the productionization entrypoint so a partial pass never reads as "done".
 */
export function assertProductionized(checklist) {
  if (!checklist.allPass) {
    const failed = checklist.gates.filter((g) => !g.pass).map((g) => `${g.id} (${g.detail})`).join('; ');
    throw haltForHuman(
      `Skill Productionization Checklist FAILED: ${checklist.passed}/${checklist.total} gate(s) pass — ${failed}`,
      'productionization-checklist-failed',
    );
  }
  return checklist;
}

// ---------------------------------------------------------------------------
// SKILL.md manifest checker — a skill is not productionized without a well-formed
// manifest (the invocation contract). A small, dependency-free frontmatter reader.
// ---------------------------------------------------------------------------

/**
 * Parse a `---`-delimited YAML-ish frontmatter block + body. Only the flat scalar
 * fields the manifest needs are read (`name`, `description`), with support for the
 * common multi-line block scalar (`description: >-` / `|`) so a folded description
 * parses. Returns `{ ok, fields, body }`; `ok:false` when no frontmatter is present.
 */
export function parseSkillFrontmatter(text) {
  const src = String(text ?? '');
  const m = src.match(/^﻿?---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!m) return { ok: false, fields: {}, body: src };

  const block = m[1];
  const body = m[2] ?? '';
  const fields = {};
  const lines = block.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const kv = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (!kv) continue;
    const key = kv[1];
    let val = kv[2];
    // A block scalar (`>-`, `>`, `|`, `|-`) gathers the more-indented lines that follow.
    if (/^[|>][+-]?\s*$/.test(val.trim())) {
      const gathered = [];
      let j = i + 1;
      while (j < lines.length && (lines[j].trim() === '' || /^\s+/.test(lines[j]))) {
        gathered.push(lines[j].trim());
        j++;
      }
      val = gathered.join(' ').trim();
      i = j - 1;
    }
    fields[key] = val.trim();
  }
  return { ok: true, fields, body };
}

/**
 * Check a SKILL.md manifest: it must exist, carry frontmatter with a non-empty `name`
 * and `description`, and have a non-empty body (the human-readable orientation). This
 * is the skill's invocation contract — checked, never assumed.
 *
 * @param {object} o
 * @param {string} o.skillPath   path to SKILL.md
 * @returns {{pass:boolean, name:?string, description:?string, detail:string}}
 */
export function checkSkillManifest({ skillPath } = {}) {
  if (!skillPath) throw new HaltError('checkSkillManifest requires a skillPath', 'pass the path to SKILL.md');
  if (!fs.existsSync(skillPath)) {
    return { pass: false, name: null, description: null, detail: `SKILL.md not found at ${skillPath}` };
  }
  const text = fs.readFileSync(skillPath, 'utf8');
  const fm = parseSkillFrontmatter(text);
  if (!fm.ok) {
    return { pass: false, name: null, description: null, detail: 'SKILL.md has no `---` frontmatter block' };
  }
  const name = fm.fields.name || null;
  const description = fm.fields.description || null;
  const hasBody = /\S/.test(fm.body) && /^#/m.test(fm.body);
  const pass = !!name && !!description && hasBody;
  const detail = pass
    ? `manifest OK (name="${name}", ${description.length}-char description, body present)`
    : !name
      ? 'frontmatter missing `name`'
      : !description
        ? 'frontmatter missing `description`'
        : 'body is empty or has no heading';
  return { pass, name, description, detail };
}
