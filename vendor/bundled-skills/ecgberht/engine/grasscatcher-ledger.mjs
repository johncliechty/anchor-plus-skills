/**
 * W6 Grasscatcher ledger — permanent scope deferrals (product non-goals).
 *
 * Distinct from campaign soft-vet / grasscatch verb receipts:
 * - soft-vet parks an idea for a campaign (append Strip receipt)
 * - this ledger freezes MVP non-goals so scope cannot silently expand
 *
 * Each item carries receipt shape (deferred, why, suggested_later_owner,
 * handback_shape) and is never implemented as an MVP verb or engine surface.
 */

import { loadJsonRelative, skillRoot } from './load.mjs';
import {
  RECEIPT_SCHEMA_ID,
  buildGrasscatchReceipt,
  validateReceipt,
} from './receipt-validate.mjs';
import { SPELLING } from './verbs.mjs';

export const GRASSCATCHER_LEDGER_SCHEMA = 'ecgberht-grasscatcher-ledger-v0';

/** Locked deferred product scopes (Master Plan non-goals + foresight). */
export const GRASSCATCHER_DEFERRED_IDS = Object.freeze([
  'openclaw-harness-product',
  'calendar-email-oauth',
  'anchor-v1-0-x-release-edits',
  'default-chat-gateway',
  'family-finances-domain',
  'anchor-1-1-portfolio-ui',
  'launch-tree-merge',
]);

/** Human labels matching plan wording. */
export const GRASSCATCHER_DEFERRED_LABELS = Object.freeze([
  'OpenClaw harness product',
  'calendar/email OAuth',
  'Anchor v1.0.x release edits',
  'default chat gateway',
  'Family-Finances domain',
  'Anchor 1.1 portfolio UI',
  'launch-tree merge',
]);

/** Fields every ledger receipt envelope must carry. */
export const LEDGER_RECEIPT_FIELDS = Object.freeze([
  'deferred',
  'grasscatch_why',
  'suggested_later_owner',
  'handback_shape',
  'uncertainty_flags',
]);

/**
 * Load the frozen ledger fixture (relative pack path only).
 * @returns {object}
 */
export function loadGrasscatcherLedger() {
  return loadJsonRelative('fixtures', 'grasscatcher-ledger.json');
}

/**
 * Normalize ledger items from fixture or inject.
 * @param {object} [raw]
 * @returns {{ ok: boolean, schema: string, spelling: string, items: object[], receipt_shape: object, depth: string }}
 */
export function normalizeGrasscatcherLedger(raw = null) {
  const source = raw && typeof raw === 'object' ? raw : loadGrasscatcherLedger();
  const items = Array.isArray(source.items)
    ? source.items.map((it) => ({
        id: String(it.id ?? ''),
        deferred: String(it.deferred ?? ''),
        why: String(it.why ?? it.grasscatch_why ?? ''),
        suggested_later_owner: it.suggested_later_owner ?? null,
        category: it.category ?? null,
        non_goal: it.non_goal !== false,
      }))
    : [];

  return {
    ok: true,
    schema: source.schema ?? GRASSCATCHER_LEDGER_SCHEMA,
    spelling: source.spelling ?? SPELLING,
    depth: source.depth ?? 'LITE',
    mvp_status: source.mvp_status ?? 'deferred',
    receipt_shape: source.receipt_shape ?? defaultReceiptShape(),
    items,
    item_ids: items.map((i) => i.id),
    deferred_labels: items.map((i) => i.deferred),
  };
}

function defaultReceiptShape() {
  return {
    schema: RECEIPT_SCHEMA_ID,
    kind: 'grasscatch',
    required_fields: [...LEDGER_RECEIPT_FIELDS],
    handback_shape: {
      when: 'post_mvp',
      return_via: 'strip_receipt',
      needs: [
        'active_effort',
        'why_next',
        'grasscatch_why',
        'tool_depth_why',
        'human_wait',
        'uncertainty_flags',
      ],
    },
  };
}

/**
 * Assert ledger covers every locked deferred id/label (plan contract).
 * @param {object} [ledger] normalized or raw
 * @returns {{ ok: boolean, missing_ids: string[], missing_labels: string[], extra_ids: string[] }}
 */
export function auditGrasscatcherLedger(ledger = null) {
  const norm = ledger && Array.isArray(ledger.items)
    ? ledger
    : normalizeGrasscatcherLedger(ledger);
  const ids = new Set(norm.item_ids ?? norm.items.map((i) => i.id));
  const labels = new Set(
    (norm.deferred_labels ?? norm.items.map((i) => i.deferred)).map((s) =>
      String(s).toLowerCase(),
    ),
  );

  const missing_ids = GRASSCATCHER_DEFERRED_IDS.filter((id) => !ids.has(id));
  const missing_labels = GRASSCATCHER_DEFERRED_LABELS.filter(
    (label) => !labels.has(label.toLowerCase()),
  );
  const known = new Set(GRASSCATCHER_DEFERRED_IDS);
  const extra_ids = [...ids].filter((id) => id && !known.has(id));

  return {
    ok: missing_ids.length === 0 && missing_labels.length === 0,
    missing_ids,
    missing_labels,
    extra_ids,
    item_count: norm.items.length,
    schema: norm.schema,
  };
}

/**
 * Build a structured grasscatch receipt for one ledger item.
 * @param {string|object} idOrItem
 * @param {object} [overrides]
 */
export function receiptForLedgerItem(idOrItem, overrides = {}) {
  const ledger = normalizeGrasscatcherLedger();
  let item = null;
  if (typeof idOrItem === 'string') {
    item = ledger.items.find((i) => i.id === idOrItem || i.deferred === idOrItem);
  } else if (idOrItem && typeof idOrItem === 'object') {
    item = idOrItem;
  }
  if (!item) {
    return {
      ok: false,
      error: 'unknown_ledger_item',
      id: typeof idOrItem === 'string' ? idOrItem : null,
      known_ids: [...GRASSCATCHER_DEFERRED_IDS],
    };
  }

  const receipt = buildGrasscatchReceipt({
    kind: 'grasscatch',
    deferred: item.deferred,
    why: item.why,
    suggested_later_owner: item.suggested_later_owner,
    active_effort: overrides.active_effort ?? 'W6 Grasscatcher ledger',
    uncertainty_flags: overrides.uncertainty_flags ?? ['scope_deferred', 'non_goal'],
    tool_depth_why: overrides.tool_depth_why ?? 'MVP LITE — not an engine surface',
    handback_shape:
      overrides.handback_shape ?? ledger.receipt_shape?.handback_shape ?? defaultReceiptShape().handback_shape,
    as_of: overrides.as_of,
  });

  const validated = validateReceipt(receipt);
  return {
    ok: validated.ok,
    ledger_id: item.id,
    non_goal: item.non_goal !== false,
    receipt: validated.receipt ?? receipt,
    validation: validated,
    issues: validated.issues ?? [],
  };
}

/**
 * Build receipts for every ledger item; fail if any lack receipt shape.
 * @param {object} [opts]
 * @returns {{ ok: boolean, receipts: object[], failures: object[] }}
 */
export function buildAllLedgerReceipts(opts = {}) {
  const ledger = normalizeGrasscatcherLedger(opts.ledger ?? null);
  const receipts = [];
  const failures = [];
  for (const item of ledger.items) {
    const built = receiptForLedgerItem(item, opts);
    if (!built.ok) {
      failures.push(built);
    } else {
      receipts.push(built);
    }
  }
  return {
    ok: failures.length === 0 && receipts.length === ledger.items.length,
    receipts,
    failures,
    count: receipts.length,
  };
}

/**
 * Labels for Face/Strip docs surfaces (string list only — not actionable verbs).
 * @returns {string[]}
 */
export function grasscatcherLabelsForStrip() {
  return [...GRASSCATCHER_DEFERRED_LABELS];
}

/**
 * Confirm deferred items are not exposed as closed verbs or commission skills.
 * @param {{ closedVerbs?: string[], commissionSkills?: string[] }} [surfaces]
 */
export function assertNotMvpSurfaces(surfaces = {}) {
  const closed = (surfaces.closedVerbs ?? []).map((v) => String(v).toLowerCase());
  const skills = (surfaces.commissionSkills ?? []).map((s) => String(s).toLowerCase());
  const violations = [];

  for (const label of GRASSCATCHER_DEFERRED_LABELS) {
    const slug = label.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    if (closed.includes(slug) || closed.includes(label.toLowerCase())) {
      violations.push({ kind: 'closed_verb', label });
    }
  }
  // Explicit forbidden surface tokens
  const forbiddenVerbTokens = [
    'openclaw',
    'oauth',
    'chat-gateway',
    'family-finances',
    'launch-tree',
    'anchor-release',
  ];
  for (const token of forbiddenVerbTokens) {
    if (closed.some((v) => v.includes(token))) {
      violations.push({ kind: 'closed_verb_token', token });
    }
    if (skills.some((s) => s.includes(token))) {
      violations.push({ kind: 'commission_skill_token', token });
    }
  }

  return {
    ok: violations.length === 0,
    violations,
    skill_root: skillRoot(),
  };
}
