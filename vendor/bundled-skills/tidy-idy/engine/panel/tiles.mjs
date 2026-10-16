// engine/panel/tiles.mjs — Wave 6: findings become tiles, verbatim.
//
// A TILE IS A RENDERING OF A FINDING, NOT A RESTATEMENT OF ONE. The rule this
// file exists to enforce: every claim on a tile is either copied byte-for-byte
// off the finding, or is explicitly labelled as this panel's own derivation.
// There is no third category, and in particular there is no place where the
// panel summarises a judge.
//
// The four safety-load-bearing tile properties:
//
//   • THE SECRET-BLOCKED CLASS HAS NO APPROVAL CONTROL AT ALL. Not a disabled
//     one — `controls` is empty. Owned decision #9 is enforced in three layers
//     (the finding carries approvable:false, Wave-3's resolveApprovals refuses
//     the ID, and there is no control here to click), and this is the layer a
//     human can see.
//
//   • QUARANTINE (size/binary) TILES ARE INDIVIDUALLY CONFIRMABLE AND EXCLUDED
//     FROM BULK. A 40MB blob or a binary is exactly the thing nobody reviewed
//     properly in a bulk sweep, so it may only be approved on its own.
//
//   • HEURISTIC CANDIDATES ARE DEFAULT-UNCHECKED AND NEVER BULK. Default-checked
//     heuristics would make bulk-approve mean "delete whatever looked old".
//
//   • AN APPROVAL IS THE FINDING'S FULL IDENTITY. Every approvable tile carries
//     {id, action, path, contentHash} because Wave-3's Apply refuses anything
//     less — so the tile a human read is provably the tile they approved.

import { toPosixRel } from '../glob.mjs';

export const TILE_CLASS = Object.freeze({
  REMOVAL: 'removal',
  HEURISTIC: 'heuristic-removal',
  SAVE: 'save',
  SECRET: 'secret-blocked',
  QUARANTINE: 'quarantine',
  BOOTSTRAP: 'bootstrap',
  COMPRESSION: 'compression',
  ALIGNMENT: 'alignment-suspect',
  REORG: 'reorg',
  OTHER: 'other',
});

/** Display order, worst-consequence-first so nobody scrolls past a BLOCKED tile. */
export const TILE_ORDER = [
  TILE_CLASS.SECRET,
  TILE_CLASS.REMOVAL,
  TILE_CLASS.HEURISTIC,
  TILE_CLASS.QUARANTINE,
  TILE_CLASS.SAVE,
  TILE_CLASS.COMPRESSION,
  TILE_CLASS.REORG,
  TILE_CLASS.BOOTSTRAP,
  TILE_CLASS.ALIGNMENT,
  TILE_CLASS.OTHER,
];

const CONTROL = Object.freeze({
  APPROVE: 'approve',
  CONFIRM_INDIVIDUALLY: 'confirm-individually',
});

/** Which finding class a tile belongs to. Kind first, action as the fallback. */
export function classifyFinding(f) {
  if (!f) return TILE_CLASS.OTHER;
  switch (f.kind) {
    case 'secret-blocked': return TILE_CLASS.SECRET;
    case 'heuristic-candidate': return TILE_CLASS.HEURISTIC;
    case 'removal-candidate': return TILE_CLASS.REMOVAL;
    case 'save-candidate': return f.quarantine ? TILE_CLASS.QUARANTINE : TILE_CLASS.SAVE;
    case 'compression-proposal': return TILE_CLASS.COMPRESSION;
    case 'alignment-suspect': return TILE_CLASS.ALIGNMENT;
    case 'bootstrap-proposal':
    case 'bootstrap': return TILE_CLASS.BOOTSTRAP;
    case 'reorg-proposal': return TILE_CLASS.REORG;
    default: break;
  }
  if (f.action === 'blocked') return TILE_CLASS.SECRET;
  if (f.action === 'remove' || f.action === 'trash') return TILE_CLASS.REMOVAL;
  if (f.action === 'save') return TILE_CLASS.SAVE;
  return TILE_CLASS.OTHER;
}

/** Min tiles under one parent before we collapse them into a folder set. */
export const FOLDER_SET_MIN = 3;
/** Min tiles sharing an extension/pattern before collapsing into a pattern set. */
export const PATTERN_SET_MIN = 5;
/**
 * Removals/archive: group aggressively so the operator sorts bulk junk fast.
 * 2+ same pattern or same folder → one expandable card (not a wall of singles).
 */
export const REMOVAL_FOLDER_SET_MIN = 2;
export const REMOVAL_PATTERN_SET_MIN = 2;
export const REMOVAL_TOPLEVEL_SET_MIN = 2;
/** Flat list preview: first N full cards; rest behind "show all". */
export const FLAT_PREVIEW_MAX = 8;

/**
 * Build the tile model for one run.
 *
 * Mockup A groups by ACTION the human takes (removals / save / reorg / …),
 * not by raw engine stage. Class groups remain for API/tests; actionSections
 * drive the human triage UI.
 */
export function buildTiles(envelope) {
  const tiles = (envelope.findings || []).map((f) => {
    const t = buildTile(f, envelope);
    t.summaryWhy = summaryWhy(t);
    t.basename = basenameOf(t.path);
    t.folder = parentFolder(t.path);
    t.patternKey = patternKey(t);
    return t;
  });

  const groups = TILE_ORDER
    .map((cls) => ({
      class: cls,
      title: GROUP_TITLE[cls] || cls,
      subtitle: GROUP_SUBTITLE[cls] || null,
      tiles: tiles.filter((t) => t.class === cls),
    }))
    .filter((g) => g.tiles.length > 0);

  const bulkApprovable = tiles.filter((t) => t.bulkApprovable);

  const removals = tiles.filter((t) => t.class === TILE_CLASS.REMOVAL || t.class === TILE_CLASS.HEURISTIC);
  const saves = tiles.filter((t) => t.class === TILE_CLASS.SAVE || t.class === TILE_CLASS.QUARANTINE);
  const reorgs = tiles.filter((t) => t.class === TILE_CLASS.REORG);
  const secrets = tiles.filter((t) => t.class === TILE_CLASS.SECRET);
  const other = tiles.filter((t) => ![
    TILE_CLASS.REMOVAL, TILE_CLASS.HEURISTIC, TILE_CLASS.SAVE, TILE_CLASS.QUARANTINE,
    TILE_CLASS.REORG, TILE_CLASS.SECRET,
  ].includes(t.class));

  // Mockup A verdict pills — action counts, not stage counts.
  const scanned = Number(envelope.stages?.find?.((s) => s.stage === 'scan' || s.stage === 'topology')?.coverage?.scanned)
    || Number(envelope.topology?.inScope?.length)
    || null;
  const findingPaths = new Set(tiles.map((t) => t.path).filter(Boolean));
  const keptEstimate = scanned != null
    ? Math.max(0, scanned - findingPaths.size)
    : (envelope.protectionWithheld || []).length;

  const verdicts = {
    removals: removals.length,
    save: saves.length,
    reorg: reorgs.length,
    keep: keptEstimate,
    secrets: secrets.length,
    total: tiles.length,
    scanned,
  };

  // Mockup A always shows reorg (even when empty) so humans see the full
  // decision surface. Removals/save always show when zero so the page shape is stable.
  // Removals use aggressive grouping (pattern → top-level folder → parent folder)
  // so remove/archive candidates cluster for easy operator sort-out.
  const actionSections = [
    {
      id: 'removals',
      title: '🗑 Proposed removals — need your OK',
      badge: 'deleted + git-committed · undo = git revert',
      tone: 'rm',
      alwaysShow: true,
      emptyNote: 'No removals proposed this run.',
      sets: humanSets(removals, {
        min: REMOVAL_FOLDER_SET_MIN,
        patternMin: REMOVAL_PATTERN_SET_MIN,
        topLevelMin: REMOVAL_TOPLEVEL_SET_MIN,
        preferTopLevel: true,
      }),
    },
    {
      id: 'save',
      title: '💾 Not saved / not in git — should be preserved?',
      badge: 'add & commit · nothing is written until you Apply',
      tone: 'save',
      alwaysShow: true,
      emptyNote: 'Everything of interest is already held by git (or nothing untracked).',
      sets: humanSets(saves),
    },
    {
      id: 'reorg',
      title: '📁 Reorganization proposals',
      badge: 'before → after · you approve each move',
      tone: 'org',
      alwaysShow: true,
      emptyNote: 'No reorg proposals this run — folder layout left as-is.',
      sets: humanSets(reorgs, { forceFlat: true }),
    },
    {
      id: 'secrets',
      title: 'BLOCKED — secret-flagged',
      badge: 'no approval control exists for this class',
      tone: 'secret',
      alwaysShow: false,
      emptyNote: null,
      sets: humanSets(secrets),
    },
    {
      id: 'other',
      title: 'Other findings',
      badge: null,
      tone: 'other',
      alwaysShow: false,
      emptyNote: null,
      sets: humanSets(other),
    },
  ].filter((s) => s.alwaysShow || s.sets.some((set) => set.tiles.length > 0));

  return {
    tiles,
    groups,
    actionSections,
    verdicts,
    bulkApprovable: bulkApprovable.map((t) => t.approval),
    counts: {
      total: tiles.length,
      approvable: tiles.filter((t) => t.approvable).length,
      bulkApprovable: bulkApprovable.length,
      blocked: secrets.length,
      quarantined: tiles.filter((t) => t.class === TILE_CLASS.QUARANTINE).length,
      removals: removals.length,
      save: saves.length,
      reorg: reorgs.length,
      keep: keptEstimate,
      byClass: Object.fromEntries(TILE_ORDER.map((c) => [c, tiles.filter((t) => t.class === c).length]).filter(([, n]) => n > 0)),
    },
    /** Read-only notices: things the run saw that are not approvable findings. */
    notices: quarantineNotices(envelope),
    kept: {
      count: keptEstimate,
      protected: (envelope.protectionWithheld || []).length,
      note: keptEstimate > 0
        ? `${keptEstimate} path(s) had no actionable finding this run (protected classes and clean paths never appear as removals).`
        : 'No separate kept-count could be estimated for this run.',
      withheld: (envelope.protectionWithheld || []).slice(0, 40).map((w) => ({
        path: w.path || w.rel || null,
        reason: w.reason || w.why || w.rule || null,
      })),
    },
  };
}

/**
 * Human-friendly set collapse: pattern buckets first (e.g. 40× .log), then
 * folder sets, then a flat remainder. Large runs stay scannable (Mockup A).
 * @param {object[]} tiles
 * @param {{forceFlat?: boolean, min?: number, patternMin?: number}} opts
 */
export function humanSets(tiles, opts = {}) {
  return folderSets(tiles, opts);
}

/**
 * Stable pattern key for bulk similar junk (extension, Office lock files, copies).
 */
export function patternKey(tile) {
  const base = String(tile.basename || basenameOf(tile.path) || '');
  const lower = base.toLowerCase();
  if (lower.startsWith('~$')) return 'office-lock';
  if (/\(copy\)/i.test(base) || /\bcopy\b/i.test(base)) return 'name-copy';
  if (/\.bak$/i.test(base) || /\.old$/i.test(base) || /\.tmp$/i.test(base)) return 'backup-ext';
  if (/\.log$/i.test(base)) return 'ext:.log';
  if (/\.zip$/i.test(base) || /\.7z$/i.test(base) || /\.rar$/i.test(base)) return 'archive-ext';
  const m = lower.match(/(\.[a-z0-9]{1,8})$/);
  if (m && tile.class === TILE_CLASS.HEURISTIC) return `heuristic-ext:${m[1]}`;
  if (m && tile.class === TILE_CLASS.REMOVAL) return `removal-ext:${m[1]}`;
  return null;
}

const PATTERN_LABEL = {
  'office-lock': 'Office lock / temp files (~$…)',
  'name-copy': 'Name looks like a duplicate “(copy)”',
  'backup-ext': 'Backup / temp extensions (.bak / .old / .tmp)',
  'ext:.log': 'Log files (.log)',
  'archive-ext': 'Archive files (.zip / .7z / …)',
};

/**
 * Collapse many tiles under the same parent folder (or pattern) into a set card.
 * Order for removals (preferTopLevel): pattern → top-level dir → parent folder → flat.
 * That clusters "remove/archive this whole area" so the operator sorts bulk junk fast.
 * @param {object[]} tiles
 * @param {{forceFlat?: boolean, min?: number, patternMin?: number, topLevelMin?: number, preferTopLevel?: boolean}} opts
 */
export function folderSets(tiles, {
  forceFlat = false,
  min = FOLDER_SET_MIN,
  patternMin = PATTERN_SET_MIN,
  topLevelMin = REMOVAL_TOPLEVEL_SET_MIN,
  preferTopLevel = false,
} = {}) {
  if (!tiles.length) return [];
  if (forceFlat) {
    return [{
      kind: 'flat',
      folder: null,
      tiles,
      label: null,
      previewMax: FLAT_PREVIEW_MAX,
      collapsedDefault: tiles.length > FLAT_PREVIEW_MAX,
    }];
  }
  if (tiles.length < min && !preferTopLevel) {
    return [{
      kind: 'flat',
      folder: null,
      tiles,
      label: null,
      previewMax: FLAT_PREVIEW_MAX,
      collapsedDefault: false,
    }];
  }

  // 1) Pattern buckets (cross-folder similar junk) — biggest human win on huge runs.
  const byPattern = new Map();
  const noPattern = [];
  for (const t of tiles) {
    const key = t.patternKey || patternKey(t);
    if (!key) {
      noPattern.push(t);
      continue;
    }
    if (!byPattern.has(key)) byPattern.set(key, []);
    byPattern.get(key).push(t);
  }
  const sets = [];
  let leftover = [...noPattern];
  for (const [key, list] of [...byPattern.entries()].sort((a, b) => b[1].length - a[1].length)) {
    if (list.length >= patternMin) {
      const label = PATTERN_LABEL[key]
        || (key.startsWith('removal-ext:') ? `Removal candidates ending in ${key.slice('removal-ext:'.length)}` : null)
        || (key.startsWith('heuristic-ext:') ? `Heuristic hits ending in ${key.slice('heuristic-ext:'.length)}` : null)
        || `${list.length} similar items (${key})`;
      sets.push({
        kind: 'pattern',
        pattern: key,
        folder: null,
        tiles: list,
        label: `${list.length}× ${label}`,
        bulkApprovableCount: list.filter((t) => t.bulkApprovable).length,
        collapsedDefault: true,
        previewMax: FLAT_PREVIEW_MAX,
        compact: true,
      });
    } else {
      leftover.push(...list);
    }
  }

  // 2) Optional top-level directory buckets (e.g. everything under docs/, tmp/, …).
  //    Groups whole remove/archive areas even when each subfolder is small.
  if (preferTopLevel && leftover.length) {
    const byTop = new Map();
    for (const t of leftover) {
      const top = topLevelFolder(t.path);
      if (!byTop.has(top)) byTop.set(top, []);
      byTop.get(top).push(t);
    }
    const stillLoose = [];
    for (const [top, list] of [...byTop.entries()].sort((a, b) => b[1].length - a[1].length)) {
      if (list.length >= topLevelMin && top !== '(project root)') {
        sets.push({
          kind: 'toplevel',
          folder: top,
          tiles: list,
          label: `${list.length} items under ${top}/ (whole area)`,
          bulkApprovableCount: list.filter((t) => t.bulkApprovable).length,
          collapsedDefault: true,
          previewMax: FLAT_PREVIEW_MAX,
          compact: list.length >= 4,
        });
      } else {
        stillLoose.push(...list);
      }
    }
    leftover = stillLoose;
  }

  // 3) Parent-folder buckets on the remainder.
  const byParent = new Map();
  for (const t of leftover) {
    const folder = parentFolder(t.path);
    if (!byParent.has(folder)) byParent.set(folder, []);
    byParent.get(folder).push(t);
  }
  const loose = [];
  for (const [folder, list] of [...byParent.entries()].sort((a, b) => b[1].length - a[1].length)) {
    if (list.length >= min) {
      sets.push({
        kind: 'folder',
        folder,
        tiles: list,
        label: folder === '(project root)'
          ? `${list.length} items in project root`
          : `${list.length} items under ${folder}/`,
        bulkApprovableCount: list.filter((t) => t.bulkApprovable).length,
        collapsedDefault: list.length >= min,
        previewMax: FLAT_PREVIEW_MAX,
        compact: list.length >= 6,
      });
    } else {
      loose.push(...list);
    }
  }
  if (loose.length) {
    // Still try one "remaining removals" bag when preferTopLevel and many leftovers.
    if (preferTopLevel && loose.length >= min) {
      sets.push({
        kind: 'flat',
        folder: null,
        tiles: loose,
        label: `${loose.length} other removal candidates`,
        bulkApprovableCount: loose.filter((t) => t.bulkApprovable).length,
        previewMax: FLAT_PREVIEW_MAX,
        collapsedDefault: true,
      });
    } else {
      sets.push({
        kind: 'flat',
        folder: null,
        tiles: loose,
        label: null,
        previewMax: FLAT_PREVIEW_MAX,
        collapsedDefault: loose.length > FLAT_PREVIEW_MAX,
      });
    }
  }
  // Largest groups first so the operator sees bulk clusters immediately.
  sets.sort((a, b) => (b.tiles || []).length - (a.tiles || []).length);
  return sets.length ? sets : [{
    kind: 'flat', folder: null, tiles, label: null,
    previewMax: FLAT_PREVIEW_MAX, collapsedDefault: false,
  }];
}

/** First path segment under the project root (e.g. docs/foo → docs). */
export function topLevelFolder(path) {
  if (!path) return '(project root)';
  const p = String(path).replace(/\\/g, '/').replace(/^\.\//, '');
  const i = p.indexOf('/');
  if (i <= 0) return '(project root)';
  return p.slice(0, i);
}

export function parentFolder(path) {
  if (!path) return '(project root)';
  const p = String(path).replace(/\\/g, '/');
  const i = p.lastIndexOf('/');
  if (i <= 0) return '(project root)';
  return p.slice(0, i);
}

/** One-line human summary — decision-first, evidence stays behind a toggle. */
export function summaryWhy(tile) {
  const e = tile.evidence || {};
  // W4 fail-closed: incomplete reorg scan outranks a stage-stamped why that may
  // claim "zero references" — never imply 0 hits when hitCount is missing.
  if (tile.class === TILE_CLASS.REORG) {
    const m = e.move || {};
    const from = m.from || tile.path;
    const to = m.to || (e.after && e.after.root) || '?';
    const raw = e.referenceScan && e.referenceScan.hitCount;
    if (raw == null || !Number.isFinite(Number(raw))) {
      return `Move ${from} → ${to} · reference scan missing — not bulk-approvable.`;
    }
    if (tile.why) return String(tile.why);
    return `Move ${from} → ${to} · ${Number(raw)} reference hit(s) in the tree.`;
  }
  if (tile.why) return String(tile.why);
  if (tile.class === TILE_CLASS.REMOVAL) {
    const j = e.judge && e.judge.decision;
    const claim = e.attacker && e.attacker.claim;
    if (j && claim) return `Judge: ${j}. ${truncate(claim, 160)}`;
    if (j) return `Judge: ${j}`;
    return 'Removal candidate from adversarial review.';
  }
  if (tile.class === TILE_CLASS.HEURISTIC) {
    const hs = e.heuristics || [];
    if (hs.length) return `Heuristic signals: ${hs.join(', ')} — evidence only, not a final verdict.`;
    return 'Heuristic candidate — review evidence before removing.';
  }
  if (tile.class === TILE_CLASS.SAVE || tile.class === TILE_CLASS.QUARANTINE) {
    if (e.porcelain) return `Git does not fully hold this path yet (${String(e.porcelain).slice(0, 80)}).`;
    if (tile.class === TILE_CLASS.QUARANTINE) return `Quarantined (${e.quarantine || 'size/binary'}) — inspect yourself before saving.`;
    return 'Untracked or uncommitted content — commit if you need to keep it.';
  }
  if (tile.class === TILE_CLASS.SECRET) {
    return 'Secret-flagged — blocked from save/LLM; remediation only, no approve control.';
  }
  return tile.badges && tile.badges.length ? tile.badges.join(' · ') : 'See evidence for details.';
}

function truncate(s, n) {
  const t = String(s || '').replace(/\s+/g, ' ').trim();
  return t.length <= n ? t : `${t.slice(0, n - 1)}…`;
}

function basenameOf(path) {
  if (!path) return '(unknown)';
  const p = String(path).replace(/\\/g, '/');
  const i = p.lastIndexOf('/');
  return i < 0 ? p : p.slice(i + 1);
}

const GROUP_TITLE = {
  [TILE_CLASS.SECRET]: 'BLOCKED — secret-flagged',
  [TILE_CLASS.REMOVAL]: 'Removals',
  [TILE_CLASS.HEURISTIC]: 'Heuristic candidates',
  [TILE_CLASS.QUARANTINE]: 'Quarantined (size / binary)',
  [TILE_CLASS.SAVE]: 'SAVE — content git does not hold yet',
  [TILE_CLASS.COMPRESSION]: 'Context compression proposals',
  [TILE_CLASS.REORG]: 'Reorg proposals',
  [TILE_CLASS.BOOTSTRAP]: 'Bootstrap (optional upgrade)',
  [TILE_CLASS.ALIGNMENT]: 'Alignment suspects (informational)',
  [TILE_CLASS.OTHER]: 'Other findings',
};

const GROUP_SUBTITLE = {
  [TILE_CLASS.SECRET]: 'no approval control exists for this class, bulk or individual — the remediations below are the only routes forward',
  [TILE_CLASS.HEURISTIC]: 'default-unchecked and excluded from bulk-approve: this is evidence, not a verdict',
  [TILE_CLASS.QUARANTINE]: 'individually confirmable only — never bulk-approved, because nobody reviews a 40MB blob in a sweep',
  [TILE_CLASS.REORG]: 'leaf/asset-directory moves shown as before→after trees with a whole-tree reference-scan hit count; zero-hit moves are approvable, non-zero-hit moves are advisory and applyable only through their own explicit override',
};

/** One finding → one tile. */
export function buildTile(f, envelope = {}) {
  const cls = classifyFinding(f);
  const approvable = isApprovable(f, cls);
  const bulk = approvable && isBulkApprovable(f, cls);

  const tile = {
    id: f.id || null,
    class: cls,
    kind: f.kind || null,
    stage: f.stage || null,
    action: f.action || null,
    path: f.path ? toPosixRel(f.path) : null,
    absolutePath: f.absolutePath || null,
    approvable,
    bulkApprovable: bulk,
    defaultChecked: f.defaultChecked === true,
    /** The FULL identity an Apply POST must round-trip. */
    approval: approvable && f.id
      ? { id: f.id, action: f.action, path: toPosixRel(f.path), contentHash: f.contentHash ?? null }
      : null,
    controls: approvable
      ? [bulk ? CONTROL.APPROVE : CONTROL.CONFIRM_INDIVIDUALLY]
      : [],
    badges: badgesFor(f, cls),
    why: f.why || null,
    undo: f.undo || null,
    advisory: f.advisory || null,
    trackingClass: f.trackingClass || null,
    stale: Boolean(f.stale),
    evidence: {},
  };

  switch (cls) {
    case TILE_CLASS.SECRET: {
      // ZERO approval controls. Not disabled — absent.
      tile.controls = [];
      tile.approvable = false;
      tile.bulkApprovable = false;
      tile.approval = null;
      tile.evidence = {
        // Rule + location only. The matched bytes never leave the machine, and
        // the masked form is the finding's own, not a re-masking here.
        triggers: (f.triggers || []).map((t) => ({ rule: t.rule || t.name || null, where: t.where || t.location || null, line: t.line ?? null, kind: t.kind || null })),
        maskedTriggerText: f.maskedTriggerText || null,
        blockedFrom: f.blockedFrom || ['save', 'llm-context'],
        remediation: normaliseRemediation(f.remediation),
        quarantine: f.quarantine || null,
        readError: f.readError || null,
      };
      break;
    }

    case TILE_CLASS.REMOVAL: {
      const ev = f.evidence || {};
      tile.evidence = {
        // VERBATIM, both of them. If the attacker pass produced nothing for this
        // file the tile says so rather than implying the case was made.
        attacker: ev.attacker
          ? { claim: ev.attacker.case_for_removal ?? ev.attacker.claim ?? null, strength: ev.attacker.strength ?? null, verbatim: true }
          : { claim: null, strength: null, verbatim: false, note: "the attacker pass recorded no case for this file (it failed, or returned no entry) — the judge decided on file contents and the reason for suspicion alone" },
        judge: { decision: ev.decision || null, rationale: ev.rationale || null, verbatim: true },
        confidence: ev.attacker && ev.attacker.strength
          ? { value: ev.attacker.strength, source: "the attacker's own strength rating, verbatim" }
          : { value: null, source: null, note: 'no confidence signal was recorded for this verdict' },
        eligibility: ev.eligibility || null,
        porcelain: f.porcelain || null,
        removalClass: f.removalClass || null,
        debateScope: f.debateScope || null,
      };
      break;
    }

    case TILE_CLASS.HEURISTIC: {
      tile.evidence = {
        heuristics: f.heuristics || [],
        // Raw and verbatim: the timestamp, the hash, the zero hit count — so a
        // human can disagree with the inference rather than with a conclusion.
        raw: f.evidence || {},
        note: f.evidenceNote || null,
      };
      break;
    }

    case TILE_CLASS.SAVE:
    case TILE_CLASS.QUARANTINE: {
      tile.evidence = {
        // git's own line, quoted — never a paraphrase.
        porcelain: f.porcelain || null,
        porcelainRecord: f.porcelainRecord || null,
        dirtyOverlap: f.dirtyOverlap || null,
        hasStagedChanges: Boolean(f.hasStagedChanges),
        stagedWarning: f.stagedWarning || null,
        contentHash: f.contentHash ?? null,
        op: f.op || null,
        quarantine: f.quarantine || null,
      };
      if (cls === TILE_CLASS.QUARANTINE) {
        tile.confirmIndividually = {
          required: true,
          why: f.quarantine === 'binary'
            ? 'this file is binary — the panel will not render a diff of it, so approving it means you inspected the file yourself'
            : 'this file is past the render cap — the panel will not render its content, so approving it means you inspected the file yourself',
        };
      }
      break;
    }

    case TILE_CLASS.BOOTSTRAP: {
      tile.evidence = { plan: f.plan || null, steps: f.steps || [], secrets: f.secrets || null, undo: f.undo || null };
      break;
    }

    case TILE_CLASS.COMPRESSION: {
      tile.evidence = { before: f.before ?? null, after: f.after ?? null, diff: f.diff || null, ratio: f.ratio ?? null, note: f.note || null };
      break;
    }

    case TILE_CLASS.REORG: {
      const scan = f.referenceScan || {};
      const scanComplete = reorgReferenceScanComplete(f);
      const rawHit = scanComplete ? Number(scan.hitCount) : null;
      // W3 / SC2: before/after + referenceScan are projectable fields only —
      // render.mjs places the tree-diff + hit chip as PRIMARY card chrome
      // (outside details.evidence). No field invention here.
      tile.evidence = {
        // The before→after tree the human approves is a judgement about visible
        // structure — both sides are the finding's own, verbatim.
        move: f.move || (f.path && f.to ? { from: f.path, to: f.to } : null),
        before: f.before || null,
        after: f.after || null,
        members: f.members || [],
        memberClasses: f.memberClasses || [],
        // The whole-tree reference scan, verbatim: the exact hit count and the
        // lines that reference the directory, so approval is evidence-based.
        // Incomplete scan keeps hitCount null (never coerced to 0).
        referenceScan: {
          hitCount: scanComplete ? rawHit : null,
          hits: scan.hits || [],
          truncated: Boolean(scan.truncated),
          scannedFiles: scan.scannedFiles ?? null,
          scope: scan.scope || null,
        },
        referenceUnsafe: f.referenceUnsafe || null,
      };
      // W4 fail-closed + Amendment C.i: non-zero hits, incomplete scan, or
      // stage-stamped overrideRequired → individual 'Apply anyway' only.
      // Do not rely solely on f.bulkApprovable (stage may omit it).
      const forceOverride = f.overrideRequired
        || !scanComplete
        || (rawHit != null && rawHit > 0)
        || Boolean(f.referenceUnsafe)
        || f.bulkApprovable === false;
      if (forceOverride) {
        tile.bulkApprovable = false;
        tile.controls = [CONTROL.CONFIRM_INDIVIDUALLY];
        const whyIncomplete = !scanComplete
          ? 'reference scan missing or incomplete — not bulk-approvable; apply only with an explicit per-proposal override'
          : null;
        tile.confirmIndividually = {
          required: true,
          override: true,
          label: (f.referenceUnsafe && f.referenceUnsafe.overrideLabel) || "Apply anyway — I'll fix the references",
          why: (f.referenceUnsafe && f.referenceUnsafe.reason)
            || whyIncomplete
            || `its reference scan found ${rawHit ?? scan.hitCount ?? 'some'} hit(s), so moving it could break a reference — apply only if you will fix them yourself`,
        };
        // The override travels on the approval so the server-side apply can tell
        // an explicit per-proposal 'Apply anyway' from an ordinary approval — a
        // non-zero-hit / incomplete-scan move is refused unless this flag is present.
        if (tile.approval) tile.approval.override = true;
      }
      break;
    }

    default: {
      tile.evidence = { raw: f.evidence || null, note: f.note || null };
      break;
    }
  }

  return tile;
}

function isApprovable(f, cls) {
  if (cls === TILE_CLASS.SECRET) return false;
  if (f.approvable === false) return false;
  if (!f.id) return false;
  return APPROVABLE_ACTIONS.has(f.action);
}

const APPROVABLE_ACTIONS = new Set(['remove', 'trash', 'save', 'move', 'reorg', 'propose-content', 'propose-bootstrap', 'bootstrap']);

/**
 * W4 fail-closed: a reorg finding is bulk-approvable ONLY when a numeric
 * zero-hit reference scan is present. Missing scan, non-numeric hitCount,
 * non-zero hits, overrideRequired, or referenceUnsafe → never bulk.
 * Stage may omit bulkApprovable:false; the control path must still refuse.
 */
function reorgReferenceScanComplete(f) {
  const scan = f && f.referenceScan;
  if (scan == null) return false;
  const raw = scan.hitCount;
  return raw != null && Number.isFinite(Number(raw));
}

function isBulkApprovable(f, cls) {
  if (cls === TILE_CLASS.SECRET) return false;
  if (cls === TILE_CLASS.QUARANTINE) return false;
  if (cls === TILE_CLASS.HEURISTIC) return false;
  if (cls === TILE_CLASS.BOOTSTRAP) return false;
  if (f.bulkApprovable === false) return false;
  if (f.quarantine) return false;
  if (cls === TILE_CLASS.REORG) {
    if (!reorgReferenceScanComplete(f)) return false;
    const n = Number(f.referenceScan.hitCount);
    if (n !== 0) return false;
    if (f.overrideRequired) return false;
    if (f.referenceUnsafe) return false;
  }
  return true;
}

function badgesFor(f, cls) {
  const badges = [];
  if (f.label) badges.push(f.label);
  if (f.removalClass) badges.push(`class=${f.removalClass}`);
  if (f.trackingClass) badges.push(f.trackingClass);
  if (f.quarantine) badges.push(`quarantined: ${f.quarantine}`);
  if (f.hasStagedChanges) badges.push('has STAGED changes');
  if (f.stale) badges.push('STALE — re-run');
  if (f.advisory) badges.push('advisory (no git)');
  if (cls === TILE_CLASS.REORG) {
    // Fail closed: missing scan object OR non-numeric hitCount is not "0 hits".
    if (!reorgReferenceScanComplete(f)) {
      badges.push('reference scan incomplete');
      badges.push('override required — not bulk');
    } else {
      const n = Number(f.referenceScan.hitCount);
      badges.push(n === 0 ? '0 reference hits' : `${n} reference hit(s)`);
      if (f.overrideRequired || n > 0 || f.referenceUnsafe) {
        badges.push('override required — not bulk');
      }
    }
  }
  if (cls === TILE_CLASS.SECRET) badges.push('BLOCKED — no approval control');
  if (f.defaultChecked === false && cls !== TILE_CLASS.SECRET) badges.push('default-unchecked');
  return badges;
}

/** Remediations, always as a list, always per class. */
function normaliseRemediation(r) {
  if (!r) return [];
  if (Array.isArray(r)) return r;
  if (Array.isArray(r.options)) return r.options;
  if (typeof r === 'object') return [r];
  return [{ note: String(r) }];
}

/**
 * Size/binary paths the triage stage quarantined that produced NO finding. They
 * are read-only notices, deliberately not tiles: there is nothing to approve,
 * and inventing a control for them would be inventing a capability.
 */
export function quarantineNotices(envelope) {
  const triage = (envelope.stages || []).find((s) => s.stage === 'triage');
  const list = (triage && triage.data && triage.data.quarantined) || [];
  const withTiles = new Set((envelope.findings || []).filter((f) => f.quarantine).map((f) => toPosixRel(f.path)));
  return list
    .filter((q) => !withTiles.has(toPosixRel(q.path)))
    .map((q) => ({
      path: toPosixRel(q.path),
      quarantine: q.quarantine,
      size: q.size ?? null,
      approvable: false,
      note: 'quarantined by size/binary and produced no actionable finding — listed so the run cannot look emptier than it was',
    }));
}

export default { buildTiles, buildTile, classifyFinding, quarantineNotices, TILE_CLASS, TILE_ORDER };
