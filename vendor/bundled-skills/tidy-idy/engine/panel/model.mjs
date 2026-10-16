// engine/panel/model.mjs — Wave 6: the panel's whole view, as data.
//
// THE MODEL IS THE PANEL. The HTML renderer is a dumb projection of this object
// and the JSON endpoint returns this same object, which is what makes the
// claim "the panel renders the envelope verbatim" testable: a test asserts on
// the model, not on markup, and any divergence between what the page shows and
// what the API says would require the model to be built twice — which it is not.
//
// THE MODEL NEVER CONTAINS THE CAPABILITY TOKEN. Not in a header, not in a
// nested "auth" object, not anywhere. The token is embedded by the renderer,
// once, into the redeemed bootstrap page and into nothing else. The GET-audit
// test crawls every endpoint and asserts token bytes never appear; that test
// only stays honest if this object is token-free by construction.

import { deriveBanners, canCelebrate, runAgeMs, formatAge, AGE_AMBER_MS } from './banners.mjs';
import { buildTiles } from './tiles.mjs';
import { APPLY_STATE } from './apply-state.mjs';

export const PANEL_MODEL_VERSION = 1;

/**
 * @param {{envelope: object, identity: object, runNumber?: number|null,
 *   archive?: object|null, runIndex?: Array|null, costGate?: object|null,
 *   trash?: object|null, applyState?: object|null, staleness?: object|null,
 *   lock?: object|null, supersededBy?: object|null, investigator?: object|null,
 *   now?: Function}} opts
 */
export function buildPanelModel({
  envelope,
  identity,
  runNumber = null,
  archive = null,
  runIndex = null,
  costGate = null,
  trash = null,
  applyState = null,
  staleness = null,
  lock = null,
  supersededBy = null,
  investigator = null,
  now = () => new Date(),
} = {}) {
  const banners = deriveBanners(envelope, { staleness, now });
  const {
    tiles, groups, counts, bulkApprovable, notices,
    actionSections, verdicts, kept,
  } = buildTiles(envelope);

  const ageMs = runAgeMs(envelope, now);
  const state = (applyState && applyState.state) || APPLY_STATE.PENDING;
  const headMoved = Boolean(staleness && staleness.headMoved);

  const applyBlocked = applyDisabledReason({ state, headMoved, supersededBy, counts });

  const executiveSummary = buildExecutiveSummary({
    envelope,
    identity,
    verdicts: verdicts || counts,
    counts,
    actionSections: actionSections || [],
    clean: canCelebrate(envelope),
    cleanBlockers: envelope.cleanBlockers || [],
    banners,
  });

  return {
    panelModelVersion: PANEL_MODEL_VERSION,
    generatedAt: now().toISOString(),

    // ---- human-facing one-page exec summary (always open in the panel) ----
    executiveSummary,

    // ---- WHICH PROJECT, unmistakably ------------------------------------
    header: {
      project: identity.name,
      absolutePath: identity.path,
      label: identity.label,
      git: identity.git && identity.git.present
        ? {
          present: true,
          branch: identity.git.branch || 'detached',
          shortSha: identity.git.shortSha || null,
          dirtyCount: identity.git.dirtyCount,
          summary: `${identity.git.branch || 'detached'} @ ${identity.git.shortSha || '(no commits)'}${Number.isInteger(identity.git.dirtyCount) ? ` — ${identity.git.dirtyCount} dirty path(s)` : ''}`,
        }
        : { present: false, branch: null, shortSha: null, dirtyCount: null, summary: 'no repository — removals apply through the reversible Trash' },
      run: {
        number: runNumber,
        id: envelope.runId,
        startedAt: envelope.startedAt || null,
        endedAt: envelope.endedAt || null,
        ageMs,
        ageLabel: ageMs === null ? 'unknown age' : `${formatAge(ageMs)} ago`,
        /** Amber is a STATENESS signal, not decoration. */
        ageLevel: ageMs !== null && ageMs >= AGE_AMBER_MS ? 'amber' : 'fresh',
      },
      // North-Star / heuristic / advisory — the three claims a reader must not
      // have to infer from the findings.
      badges: modeBadges(envelope),
      status: envelope.status,
      terminalStatusNote: 'terminal status is the WORST stage status — there is no averaging and no "mostly fine"',
    },

    // ---- honesty ----------------------------------------------------------
    banners,
    clean: {
      /** The one place the panel is allowed to celebrate. */
      celebrate: canCelebrate(envelope),
      blockers: [...(envelope.cleanBlockers || [])],
      source: 'envelope.isClean — computed in engine/envelope.mjs and nowhere else',
    },

    // ---- evidence / triage ------------------------------------------------
    groups,
    /** Mockup A action sections (removals / save / reorg / …) with folder sets. */
    actionSections: actionSections || [],
    /** Verdict pill counts for the summary strip. */
    verdicts: verdicts || {
      removals: counts.removals || 0,
      save: counts.save || 0,
      reorg: counts.reorg || 0,
      keep: counts.keep || 0,
      total: counts.total || 0,
    },
    kept: kept || { count: 0, protected: 0, note: '', withheld: [] },
    tiles,
    counts,
    notices,
    stages: (envelope.stages || []).map((s) => ({
      stage: s.stage,
      status: s.status,
      coverage: s.coverage,
      findings: (s.findings || []).length,
      errors: (s.errors || []).map((e) => ({ name: e.name || 'Error', message: e.message })),
      notes: s.notes || [],
    })),
    errors: (envelope.errors || []).map((e) => ({ stage: e.stage, name: e.name || 'Error', message: e.message })),
    protectionWithheld: envelope.protectionWithheld || [],
    exclusionLog: envelope.exclusionLog || [],

    // ---- the Apply control plane, as the UI sees it ------------------------
    apply: {
      runId: envelope.runId,
      state,
      oneApplyPerRun: true,
      attempts: (applyState && applyState.attempts) || 0,
      result: (applyState && applyState.result) || null,
      lastRefusal: (applyState && applyState.lastRefusal) || null,
      bulkEnabled: !applyBlocked,
      disabledReason: applyBlocked,
      bulkApprovable,
      endpoint: '/api/apply',
      method: 'POST',
      tokenTransport: 'the capability token travels in the x-tidy-idy-token HEADER — never in a URL, a query string or a cookie',
    },

    staleness: staleness || { headMoved: false, snapshotHead: null, currentHead: null, checked: false },
    supersededBy: supersededBy || null,

    // ---- the Tidy-Idy button's own debounce -------------------------------
    lock: lock || { held: false },
    rescan: { endpoint: '/api/rescan', method: 'POST', note: 'a re-scan is read-only and cheap; it mints a new run and a new set of finding IDs' },

    costGate: costGate || envelope.costGate || null,
    verdictCache: envelope.verdictCache || null,

    // ---- the Trash view ---------------------------------------------------
    trash: trash || { runs: [], totalHeld: 0 },

    // ---- previous runs, newest first --------------------------------------
    previousRuns: (runIndex || []).map((r) => ({
      runNumber: r.runNumber,
      runId: r.runId,
      runDir: r.runDir,
      status: r.status,
      isClean: r.isClean,
      findings: r.findings,
      costGated: r.costGated,
      launchedBy: r.launchedBy,
      endedAt: r.endedAt,
      archivedAt: r.archivedAt,
      current: r.runId === envelope.runId,
    })),
    archive: archive || null,

    // ---- slots (investigator active; reorg lives in actionSections tiles) --
    slots: {
      reorg: buildReorgSlot(counts.reorg || 0),
      investigator: buildInvestigatorSlot({ investigator, archive, envelope, identity, runNumber }),
    },
  };
}

/**
 * Reorg is first-class in actionSections when proposals exist. This slot only
 * remains as a thin pointer so older tests/APIs still see `slots.reorg`.
 */
function buildReorgSlot(reorgCount = 0) {
  if (reorgCount > 0) {
    return {
      reserved: false,
      active: true,
      wave: 'live',
      title: 'Reorg proposals',
      count: reorgCount,
      note: `${reorgCount} reorg proposal(s) are listed in the Reorganization section above — approve each move there.`,
    };
  }
  return {
    reserved: false,
    active: false,
    wave: 'live',
    title: 'Reorg proposals',
    count: 0,
    note: 'no reorg proposals this run (leaf/asset directory moves with reference-scan evidence appear here when found)',
  };
}

/** The default engine choices the panel offers when the launcher supplies none. */
export const INVESTIGATOR_ENGINE_CHOICES = Object.freeze([
  { id: 'claude', label: 'Claude' },
  { id: 'gemini', label: 'Gemini' },
  { id: 'grok', label: 'Grok' },
]);

/** The per-run briefing filename — mirrors briefing.mjs's BRIEFING_FILENAME (drift-checked by test). */
const BRIEFING_FILENAME = 'briefing.md';

/**
 * The investigator tile — ACTIVE as of Wave 7, no longer merely reserved. Pure
 * data: the launcher passes engine choices, default engine, and the briefing
 * path (all computed in engine/launch/investigator.mjs), so the panel never
 * imports the launch surface. Falls back to sane defaults when built without a
 * launcher (e.g. a direct model test).
 */
function buildInvestigatorSlot({ investigator, archive, envelope, identity, runNumber }) {
  const defaultEngine = (investigator && investigator.defaultEngine) || 'claude';
  const choices = (investigator && investigator.engines) || INVESTIGATOR_ENGINE_CHOICES;
  const engines = choices.map((c) => ({ id: c.id, label: c.label, default: c.id === defaultEngine }));
  const briefingPath = (investigator && investigator.briefingPath)
    || (archive && archive.dir ? `${archive.dir}/${BRIEFING_FILENAME}` : null);
  return {
    reserved: false,
    active: true,
    wave: 'Wave 7',
    title: 'Investigate with an agent',
    note: 'opens a project-tied agent terminal (cwd = this project) seeded with THIS run\'s briefing — the tidy-idy skill is inlined into the briefing when it is not resolvable in the launch environment, so a clean machine gets a readable briefing instead of an unresolved-skill failure',
    endpoint: '/api/investigate',
    method: 'POST',
    defaultEngine,
    engines,
    briefing: {
      filename: BRIEFING_FILENAME,
      path: briefingPath,
      note: 'engine-agnostic markdown, distinct from this JSON model — project root, run summary, findings with absolute paths and evidence, and suggested first questions',
    },
    runId: envelope.runId,
    runNumber,
    project: { name: identity.name, path: identity.path },
  };
}

function modeBadges(envelope) {
  const badges = [];
  badges.push(envelope.mode === 'north-star'
    ? { id: 'north-star', label: 'North-Star mode', tone: 'strong', note: 'findings argue against a stated objective document' }
    : { id: 'heuristic', label: 'heuristic mode', tone: 'weak', note: 'no North-Star document — findings rest on raw file evidence; every candidate is default-unchecked' });
  if (!(envelope.git && envelope.git.present)) {
    badges.push({ id: 'advisory', label: 'advisory — no git', tone: 'weak', note: 'removals apply through the reversible Trash; `git init` is an optional upgrade, never a gate' });
  }
  const gate = envelope.costGate;
  if (gate && gate.gated) badges.push({ id: 'cost-gated', label: 'cost-gated scope', tone: 'weak', note: 'this run was auto-degraded and never blocked awaiting input' });
  return badges;
}

/** Why bulk-Apply is off, in the user's words — or null when it is on. */
function applyDisabledReason({ state, headMoved, supersededBy, counts }) {
  if (state === APPLY_STATE.DONE) return 'this run has already been applied — one Apply per run; re-scan to pick up whatever is left';
  if (state === APPLY_STATE.APPLYING) return 'an Apply for this run is in flight';
  if (supersededBy) return `this run has been superseded by a newer completed run (run ${supersededBy.runNumber}) for this project — re-open the panel from the newest run`;
  if (headMoved) return 'HEAD moved since this scan — every finding describes a tree that no longer exists; re-scan (it is cheap)';
  if (!counts.bulkApprovable) return 'nothing in this run is bulk-approvable — quarantined, heuristic and BLOCKED tiles are excluded from bulk by design';
  return null;
}

/**
 * One-page executive summary for the panel top.
 * Plain English, bullet-first, no jargon — what was found + what to do next.
 * Derives only from counts/sets already on the model (never paraphrases judges).
 */
export function buildExecutiveSummary({
  envelope,
  identity,
  verdicts = {},
  counts = {},
  actionSections = [],
  clean = false,
  cleanBlockers = [],
  banners = [],
} = {}) {
  const project = (identity && (identity.name || identity.label)) || 'this project';
  const removals = Number(verdicts.removals ?? counts.removals ?? 0) || 0;
  const save = Number(verdicts.save ?? counts.save ?? 0) || 0;
  const reorg = Number(verdicts.reorg ?? counts.reorg ?? 0) || 0;
  const keep = Number(verdicts.keep ?? counts.keep ?? 0) || 0;
  const secrets = Number(verdicts.secrets ?? counts.blocked ?? 0) || 0;
  const bulk = Number(counts.bulkApprovable ?? 0) || 0;
  const scanned = verdicts.scanned != null ? Number(verdicts.scanned) : null;
  const totalFindings = Number(verdicts.total ?? counts.total ?? 0) || 0;

  const found = [];
  const recommendations = [];

  if (scanned != null && Number.isFinite(scanned)) {
    found.push(`Scanned about ${scanned} file(s) in ${project}.`);
  } else {
    found.push(`Reviewed ${project} for cleanup candidates.`);
  }

  if (clean && totalFindings === 0 && removals === 0 && save === 0 && reorg === 0) {
    found.push('No cleanup actions proposed — the tree looks tidy for this run.');
    recommendations.push('Nothing to Apply. You can close the panel or re-scan later if the project changes.');
  } else {
    if (removals > 0) {
      const rmSection = actionSections.find((s) => s.id === 'removals');
      const groupN = (rmSection && rmSection.sets || []).filter((s) => (s.tiles || []).length > 1).length;
      const bulkRm = (rmSection && rmSection.sets || []).reduce(
        (n, set) => n + (set.bulkApprovableCount || (set.tiles || []).filter((t) => t.bulkApprovable).length),
        0,
      );
      const groupHint = groupN > 0
        ? ` grouped into ${groupN} similar set(s) so you can approve whole clusters`
        : '';
      found.push(
        `Proposes removing or archiving ${removals} item(s)${bulkRm ? ` (${bulkRm} bulk-approvable)` : ''}${groupHint}.`,
      );
      // Top group labels (max 3) for a scannable "what kind of junk" line.
      const topGroups = (rmSection && rmSection.sets || [])
        .filter((s) => s.label && (s.tiles || []).length >= 2)
        .slice(0, 3)
        .map((s) => s.label);
      if (topGroups.length) {
        found.push(`Biggest removal clusters: ${topGroups.join('; ')}.`);
      }
      recommendations.push(
        'Open “Proposed removals”, expand the grouped clusters that look right, use “Select all bulk-approvable in this group”, then Apply once at the bottom.',
      );
    } else {
      found.push('No removals proposed this run.');
    }

    if (save > 0) {
      found.push(`${save} file(s) are not saved in git yet — work that could be lost if left untracked.`);
      recommendations.push('Open “Not saved / not in git” and approve anything you want preserved (add & commit on Apply).');
    }

    if (reorg > 0) {
      found.push(`${reorg} folder-move proposal(s) (reorganization).`);
      recommendations.push('Open “Reorganization proposals” and approve each move you want — each is listed with before → after.');
    }

    if (secrets > 0) {
      found.push(`${secrets} path(s) look secret-shaped and are BLOCKED from any approve control.`);
      recommendations.push('Do not try to force-approve secret-flagged items — relocate or gitignore them outside this panel.');
    }

    if (keep > 0) {
      found.push(`About ${keep} path(s) had no actionable finding (kept / protected).`);
    }

    if (bulk > 0 && removals === 0 && save === 0) {
      recommendations.push(`${bulk} item(s) are bulk-approvable — expand the matching section(s) and Apply when ready.`);
    }
  }

  if ((cleanBlockers || []).length) {
    found.push(`Not marked clean: ${(cleanBlockers || []).slice(0, 2).join('; ')}${cleanBlockers.length > 2 ? '…' : ''}.`);
  }

  const amberBanners = (banners || []).filter((b) => b.level === 'amber' || b.level === 'red');
  if (amberBanners.length) {
    found.push(`Note: ${amberBanners[0].title || amberBanners[0].kind || 'a warning banner is shown below'}.`);
  }

  if (!recommendations.length && totalFindings > 0) {
    recommendations.push('Expand the sections below that match the counts, decide what to keep or remove, then Apply once.');
  }
  if (!recommendations.length) {
    recommendations.push('Sections below start closed — expand only what you need. Nothing changes until you click Apply.');
  } else {
    recommendations.push('All detail sections start closed. Nothing is deleted or committed until you click Apply.');
  }

  // Cap to a short one-page shape (≤ ~10 bullets total).
  const foundCapped = found.slice(0, 6);
  const recsCapped = recommendations.slice(0, 5);
  const bullets = [...foundCapped, ...recsCapped];

  let lede;
  if (clean && totalFindings === 0) {
    lede = `${project} looks clean this run — no cleanup decisions required.`;
  } else if (removals > 0 || save > 0 || reorg > 0) {
    const bits = [];
    if (removals) bits.push(`${removals} remove`);
    if (save) bits.push(`${save} unsaved`);
    if (reorg) bits.push(`${reorg} reorg`);
    lede = `Tidy-Idy found work for you in ${project}: ${bits.join(', ')}. Review the grouped lists below, then Apply once.`;
  } else {
    lede = `Tidy-Idy finished reviewing ${project}. Summary of findings and next steps:`;
  }

  return {
    title: 'At a glance',
    lede,
    found: foundCapped,
    recommendations: recsCapped,
    bullets,
    footer: 'Counts match the pills above. Expand a section only when you want the detail.',
  };
}

export default { buildPanelModel, PANEL_MODEL_VERSION, buildExecutiveSummary };
