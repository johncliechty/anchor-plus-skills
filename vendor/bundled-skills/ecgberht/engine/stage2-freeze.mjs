/**
 * W6 Stage-2-ready freeze set.
 *
 * Locks: file tree, schemas, fixture matrix, verb contracts, heal law,
 * A1 discovery rules, non-goals — depth remains LITE skill+engine MVP.
 * Sufficient for Foreman without re-litigating architecture/scope.
 */

import fs from 'node:fs';
import path from 'node:path';
import { loadJsonRelative, skillRoot } from './load.mjs';
import { CLOSED_VERBS, PRIMARY_VERBS, VERB_ALIASES, SPELLING } from './verbs.mjs';
import { HEAL_LAW, HEAL_LAW_NOTES } from './heal.mjs';
import { ENV_STRIP_ROOTS, JUNK_DIR_NAMES } from './discovery.mjs';
import {
  GRASSCATCHER_DEFERRED_LABELS,
  normalizeGrasscatcherLedger,
  auditGrasscatcherLedger,
} from './grasscatcher-ledger.mjs';

export const STAGE2_FREEZE_SCHEMA = 'ecgberht-stage2-freeze-v0';
export const FREEZE_DEPTH = 'LITE';

/**
 * Load freeze fixture from pack.
 * @returns {object}
 */
export function loadStage2Freeze() {
  return loadJsonRelative('fixtures', 'stage2-freeze.json');
}

/**
 * Locked freeze artifact set (runtime + fixture merge).
 * @param {object} [opts]
 */
export function getStage2FreezeSet(opts = {}) {
  const fixture = opts.fixture ?? loadStage2Freeze();
  const ledger = normalizeGrasscatcherLedger(opts.ledger ?? null);

  return {
    ok: true,
    schema: fixture.schema ?? STAGE2_FREEZE_SCHEMA,
    spelling: SPELLING,
    depth: FREEZE_DEPTH,
    description:
      fixture.description ??
      'Stage-2-ready freeze set for LITE skill+engine MVP',
    locked_file_tree: [...(fixture.locked_file_tree ?? [])],
    schemas: [...(fixture.schemas ?? [])],
    fixture_matrix: [...(fixture.fixture_matrix ?? [])],
    verb_contracts: {
      closed_list: [...CLOSED_VERBS],
      primary: [...PRIMARY_VERBS],
      aliases: { ...VERB_ALIASES },
      unknown_verb:
        fixture.verb_contracts?.unknown_verb ??
        'structured refuse (error: unknown_verb); no open plugin dispatch',
      fixture_closed: fixture.verb_contracts?.closed_list ?? null,
    },
    heal_law: {
      ...HEAL_LAW,
      notes: [...HEAL_LAW_NOTES],
    },
    a1_discovery_rules: {
      registry: false,
      env: ENV_STRIP_ROOTS,
      roots: fixture.a1_discovery_rules?.roots ?? [
        'CLI --roots',
        `env ${ENV_STRIP_ROOTS}`,
      ],
      first_match: fixture.a1_discovery_rules?.first_match ?? [
        'strip.json',
        'ECGBERHT.md Strip fence',
      ],
      scan_depth:
        fixture.a1_discovery_rules?.scan_depth ??
        'listed roots + one level of subdirs',
      junk: [...JUNK_DIR_NAMES].slice(0, 8),
      empty_roots: 'structured empty result',
    },
    non_goals: uniqueStrings([
      ...(fixture.non_goals ?? []),
      ...GRASSCATCHER_DEFERRED_LABELS,
    ]),
    grasscatcher_ledger: {
      item_ids: ledger.item_ids,
      deferred_labels: ledger.deferred_labels,
      count: ledger.items.length,
    },
    north_star_criteria: [...(fixture.north_star_criteria ?? [])],
  };
}

/**
 * Validate freeze set against live pack tree + engine contracts.
 * @param {{ freeze?: object, root?: string }} [opts]
 */
export function validateStage2Freeze(opts = {}) {
  const root = opts.root || skillRoot();
  const freeze = opts.freeze ?? getStage2FreezeSet();
  const missing_files = [];
  const issues = [];

  for (const rel of freeze.locked_file_tree) {
    const p = path.join(root, ...rel.split('/'));
    if (!fs.existsSync(p)) {
      missing_files.push(rel);
    }
  }

  // Verb contracts match live exports
  const closedLive = [...CLOSED_VERBS].sort().join(',');
  const closedFreeze = [...freeze.verb_contracts.closed_list].sort().join(',');
  if (closedLive !== closedFreeze) {
    issues.push({
      kind: 'verb_contract_mismatch',
      live: freeze.verb_contracts.closed_list,
      expected: [...CLOSED_VERBS],
    });
  }

  if (freeze.depth !== 'LITE' && freeze.depth !== FREEZE_DEPTH) {
    issues.push({ kind: 'depth_not_lite', depth: freeze.depth });
  }

  if (freeze.heal_law.face_wins !== 'narrative') {
    issues.push({ kind: 'heal_law_face' });
  }
  if (freeze.heal_law.strip_wins !== 'append_only_clocks') {
    issues.push({ kind: 'heal_law_strip' });
  }
  if (freeze.heal_law.chat_invents_truth !== false) {
    issues.push({ kind: 'heal_law_chat' });
  }
  if (freeze.heal_law.silent_strip_rewrite !== false) {
    issues.push({ kind: 'heal_law_silent_strip' });
  }

  if (freeze.a1_discovery_rules.registry !== false) {
    issues.push({ kind: 'a1_must_not_use_registry' });
  }

  const ledgerAudit = auditGrasscatcherLedger();
  if (!ledgerAudit.ok) {
    issues.push({
      kind: 'grasscatcher_ledger_incomplete',
      missing_ids: ledgerAudit.missing_ids,
      missing_labels: ledgerAudit.missing_labels,
    });
  }

  // Non-goals must name the plan deferrals
  const nonGoalSet = new Set(
    (freeze.non_goals ?? []).map((s) => String(s).toLowerCase()),
  );
  const missing_non_goals = GRASSCATCHER_DEFERRED_LABELS.filter(
    (label) => !nonGoalSet.has(label.toLowerCase()),
  );
  if (missing_non_goals.length) {
    issues.push({ kind: 'non_goals_incomplete', missing_non_goals });
  }

  const ok =
    missing_files.length === 0 &&
    issues.length === 0 &&
    freeze.spelling === SPELLING &&
    freeze.depth === FREEZE_DEPTH;

  return {
    ok,
    missing_files,
    issues,
    depth: freeze.depth,
    spelling: freeze.spelling,
    locked_file_count: freeze.locked_file_tree.length,
    schema_count: freeze.schemas.length,
    fixture_count: freeze.fixture_matrix.length,
    non_goal_count: freeze.non_goals.length,
    ledger_audit: ledgerAudit,
    message: ok
      ? 'Stage-2 freeze set valid: tree, schemas, verbs, heal law, A1, non-goals, LITE depth'
      : 'Stage-2 freeze validation failed',
  };
}

/**
 * Export freeze summary suitable for docs / Face pointer (no host paths).
 */
export function freezeSummaryForDocs() {
  const freeze = getStage2FreezeSet();
  return {
    spelling: freeze.spelling,
    depth: freeze.depth,
    schema: freeze.schema,
    verb_count: freeze.verb_contracts.closed_list.length,
    primary_verbs: freeze.verb_contracts.primary,
    heal_law: {
      face_wins: freeze.heal_law.face_wins,
      strip_wins: freeze.heal_law.strip_wins,
      crisis: freeze.heal_law.crisis,
      silence: freeze.heal_law.silence,
    },
    a1: {
      registry: freeze.a1_discovery_rules.registry,
      env: freeze.a1_discovery_rules.env,
      scan_depth: freeze.a1_discovery_rules.scan_depth,
    },
    non_goals: freeze.non_goals,
    grasscatcher_count: freeze.grasscatcher_ledger.count,
    locked_file_count: freeze.locked_file_tree.length,
  };
}

function uniqueStrings(arr) {
  const out = [];
  const seen = new Set();
  for (const s of arr) {
    const k = String(s);
    if (seen.has(k.toLowerCase())) continue;
    seen.add(k.toLowerCase());
    out.push(k);
  }
  return out;
}
