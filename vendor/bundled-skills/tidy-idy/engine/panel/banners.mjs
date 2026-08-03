// engine/panel/banners.mjs — Wave 6: the honesty banners.
//
// THE BANNER IS THE PANEL'S CONSCIENCE. Every other surface in this tool can be
// read as a claim about what IS in the tree; a banner is a claim about what the
// RUN DID AND DID NOT DO, which is the thing a human cannot check by looking.
//
// Two properties, both structural rather than promised:
//
//   1. A BANNER NAMES THE THING. Not "some analysis was incomplete" but
//      "reorg analysis crashed — removal findings complete, reorg findings
//      missing". A vague banner is worse than none: it teaches the reader to
//      skip banners.
//
//   2. CELEBRATORY-CLEAN COMES FROM `envelope.isClean` AND NOWHERE ELSE.
//      `canCelebrate()` is a one-line delegation to the Wave-1 computed
//      property, so there is no second definition of "clean" in the renderer
//      that could drift from the envelope's. A run that failed a stage, skipped
//      a path, or tripped the tripwire cannot reach the green banner, no matter
//      what its finding count is.
//
// Everything here is a PURE FUNCTION of the envelope. The renderer cannot
// produce a banner the envelope does not support, because the renderer does not
// author banners at all.

import { STATUS, coverageComplete } from '../envelope.mjs';

export const BANNER_LEVEL = Object.freeze({
  RED: 'red',
  AMBER: 'amber',
  INFO: 'info',
  GREEN: 'green',
});

/**
 * What a stage is called in a sentence a human reads. A stage named `debate`
 * produces REMOVAL findings; saying "debate findings missing" would make the
 * reader translate, and a reader who is translating is a reader who is guessing.
 */
export const STAGE_NOUN = Object.freeze({
  preflight: 'preflight',
  topology: 'topology',
  snapshot: 'snapshot',
  scan: 'scan',
  triage: 'secret',
  analyze: 'alignment',
  heuristic: 'heuristic',
  debate: 'removal',
  save: 'SAVE',
  compress: 'compression',
  reorg: 'reorg',
  config: 'configuration',
});

export function stageNoun(stage) {
  return STAGE_NOUN[stage] || String(stage);
}

/** Older than this and the run-age chip turns amber. */
export const AGE_AMBER_MS = 15 * 60 * 1000;

/**
 * Derive every banner this envelope justifies, worst first.
 *
 * @param {object} envelope
 * @param {{staleness?: object|null, now?: Function}} [opts]
 * @returns {object[]}
 */
export function deriveBanners(envelope, { staleness = null, now = () => new Date() } = {}) {
  const banners = [];
  const stages = envelope.stages || [];

  const producedFindings = stages
    .filter((s) => s.status === STATUS.OK && (s.findings || []).length > 0)
    .map((s) => stageNoun(s.stage));

  // ---- 1. crashed stages -------------------------------------------------
  for (const s of stages.filter((x) => x.status === STATUS.FAILED)) {
    const complete = producedFindings.length
      ? `${[...new Set(producedFindings)].join(' and ')} findings complete`
      : 'no other stage produced findings';
    banners.push({
      level: BANNER_LEVEL.RED,
      kind: 'stage-crashed',
      stage: s.stage,
      title: `${stageNoun(s.stage)} analysis crashed`,
      message: `${s.stage} analysis crashed — ${complete}, ${stageNoun(s.stage)} findings missing`,
      missing: [`${stageNoun(s.stage)} findings`],
      // Verbatim. A paraphrased error is a second chance to be wrong about what
      // went wrong.
      errors: (s.errors || []).map((e) => ({ name: e.name || 'Error', message: e.message })),
      coverageNote: (s.coverage && s.coverage.note) || null,
    });
  }

  // ---- 2. partial stages -------------------------------------------------
  for (const s of stages.filter((x) => x.status === STATUS.PARTIAL)) {
    const c = s.coverage || {};
    banners.push({
      level: BANNER_LEVEL.AMBER,
      kind: 'stage-partial',
      stage: s.stage,
      title: `${stageNoun(s.stage)} analysis is PARTIAL`,
      message: `${s.stage} completed only partially — ${Number(c.skipped || 0)} path(s) skipped and ${Number(c.errored || 0)} error(s); ${stageNoun(s.stage)} findings are incomplete, not empty`,
      missing: [`an unknown number of ${stageNoun(s.stage)} findings`],
      errors: (s.errors || []).map((e) => ({ name: e.name || 'Error', message: e.message })),
      coverageNote: c.note || null,
    });
  }

  // ---- 3. coverage gaps in stages that still call themselves ok -----------
  for (const s of stages) {
    if (s.status !== STATUS.OK) continue; // already banner-ed above
    if (coverageComplete(s.coverage)) continue;
    const c = s.coverage || {};
    banners.push({
      level: BANNER_LEVEL.AMBER,
      kind: 'coverage-gap',
      stage: s.stage,
      title: `${stageNoun(s.stage)} did not look at everything`,
      message: `${s.stage} reports status=ok but its coverage is incomplete — ${Number(c.skipped || 0)} skipped, ${Number(c.errored || 0)} errored. A partial tree is never reported as the whole thing.`,
      missing: [`${Number(c.skipped || 0) + Number(c.errored || 0)} path(s) this stage never resolved`],
      coverageNote: c.note || null,
    });
  }

  // ---- 4. the zero-write tripwire ----------------------------------------
  const violations = (envelope.tripwire && envelope.tripwire.tier1Violations) || [];
  if (violations.length) {
    banners.push({
      level: BANNER_LEVEL.RED,
      kind: 'tripwire',
      stage: null,
      title: 'the read-only guarantee was VIOLATED during analysis',
      message: `${violations.length} zero-write tripwire violation(s) were recorded — the analysis wrote outside its report directory. Treat every finding below as untrusted until this is explained.`,
      missing: [],
      violations,
    });
  }

  // ---- 5. the cost gate ---------------------------------------------------
  const gate = envelope.costGate || null;
  if (gate && gate.gated) {
    banners.push({
      level: BANNER_LEVEL.AMBER,
      kind: 'cost-gated',
      stage: null,
      title: 'cost-gated — full run needs confirmation',
      message: (gate.banner && gate.banner.message)
        || 'this run completed in AUTO-DEGRADED scope: the tree was large enough that a full pass would have burned unbounded LLM spend, so exclusions were applied and the LLM stages were narrowed. The run never blocked awaiting input.',
      missing: ['the excluded subtrees were never analysed at full depth'],
      degradation: gate.degradation || null,
      action: {
        id: 'confirm-full-run',
        label: 'Confirm and re-run at full scope',
        endpoint: '/api/confirm-full-run',
        method: 'POST',
      },
    });
  }

  // ---- 6. the secret gate --------------------------------------------------
  const blockedCount = (envelope.findings || []).filter((f) => f.kind === 'secret-blocked').length;
  if (blockedCount) {
    banners.push({
      level: BANNER_LEVEL.AMBER,
      kind: 'secret-blocked',
      stage: 'triage',
      title: `${blockedCount} path(s) hard-blocked by the pre-LLM secret gate`,
      message: `${blockedCount} path(s) were withheld from every LLM stage and from the SAVE class. They have NO approval control in this panel by construction — the remediation on each tile is the only route forward.`,
      missing: [`${blockedCount} path(s) were never analysed by a model`],
    });
  }

  // ---- 7. advisory / heuristic mode ---------------------------------------
  if (!(envelope.git && envelope.git.present)) {
    banners.push({
      level: BANNER_LEVEL.INFO,
      kind: 'advisory-no-git',
      stage: null,
      title: 'advisory — no git repository at this root',
      message: 'there is no repository here, so approved removals move into the reversible Trash (undo = restore-from-Trash) rather than into a commit. `git init` (Bootstrap) is an optional upgrade the preflight proposes, never a gate.',
      missing: [],
    });
  }
  if (envelope.mode === 'heuristic') {
    banners.push({
      level: BANNER_LEVEL.INFO,
      kind: 'heuristic-mode',
      stage: null,
      title: 'heuristic mode — no North-Star document',
      message: 'no North-Star document was found, so removal findings rest on raw file evidence rather than on an argued relationship to a stated objective. Every heuristic candidate is default-unchecked and excluded from bulk-approve.',
      missing: [],
    });
  }

  // ---- 8. staleness --------------------------------------------------------
  if (staleness && staleness.headMoved) {
    banners.push({
      level: BANNER_LEVEL.AMBER,
      kind: 'head-moved',
      stage: null,
      title: 'HEAD moved since this scan',
      message: `the branch has advanced from ${short(staleness.snapshotHead)} to ${short(staleness.currentHead)} since this run's snapshot. Bulk-Apply is disabled: every finding below describes a tree that no longer exists. Re-scan is cheap.`,
      missing: [],
      action: { id: 'rescan', label: 'Re-scan now', endpoint: '/api/rescan', method: 'POST' },
    });
  }

  const ageMs = runAgeMs(envelope, now);
  if (ageMs !== null && ageMs >= AGE_AMBER_MS) {
    banners.push({
      level: BANNER_LEVEL.AMBER,
      kind: 'run-age',
      stage: null,
      title: `this report is ${formatAge(ageMs)} old`,
      message: `the run finished ${formatAge(ageMs)} ago. Findings are claims about the tree AS IT WAS THEN; Apply revalidates every one of them and drops whatever changed, so an old report cannot silently act on new bytes — but a re-scan will show you more.`,
      missing: [],
      action: { id: 'rescan', label: 'Re-scan now', endpoint: '/api/rescan', method: 'POST' },
    });
  }

  // ---- 9. the verdict, last ------------------------------------------------
  if (canCelebrate(envelope)) {
    banners.push({
      level: BANNER_LEVEL.GREEN,
      kind: 'clean',
      stage: null,
      title: 'Clean',
      message: 'every stage completed with COMPLETE coverage, no tripwire violation, and zero findings. This is the only condition under which this panel says clean.',
      missing: [],
    });
  } else {
    banners.push({
      level: BANNER_LEVEL.INFO,
      kind: 'not-clean',
      stage: null,
      title: 'not a clean verdict',
      message: 'this run is not clean. Exactly why:',
      missing: [],
      blockers: [...(envelope.cleanBlockers || [])],
    });
  }

  return banners;
}

/**
 * The ONLY clean predicate the panel has. Delegates to the Wave-1 computed
 * property — there is deliberately no second definition here to drift from it.
 */
export function canCelebrate(envelope) {
  return envelope != null && envelope.isClean === true;
}

/** How long ago the run ended, in ms — or null when the envelope does not say. */
export function runAgeMs(envelope, now = () => new Date()) {
  const ended = envelope && (envelope.endedAt || envelope.startedAt);
  if (!ended) return null;
  const t = new Date(ended).getTime();
  if (!Number.isFinite(t)) return null;
  return Math.max(0, now().getTime() - t);
}

export function formatAge(ms) {
  if (!Number.isFinite(ms)) return 'unknown';
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function short(sha) {
  return sha ? String(sha).slice(0, 7) : '(none)';
}

export default { deriveBanners, canCelebrate, runAgeMs, formatAge, stageNoun, BANNER_LEVEL, STAGE_NOUN, AGE_AMBER_MS };
