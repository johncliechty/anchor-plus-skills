/**
 * W6 Verification pack — consolidated North Star unit suite helpers.
 *
 * Exercises (without replacing per-wave tests):
 * - write authority Face vs Strip
 * - strip-first rank
 * - A1 discovery
 * - dispatch outcomes + LITE bias
 * - override requires receipt
 * - receipt-validate
 * - refuse-unknown
 * - seating prefs mock without product IDs
 *
 * Returns structured results for the canary/verification gate.
 */

import {
  rewriteFaceNarrative,
  mutateStripInPlace,
  appendStripInstrument,
} from './write-authority.mjs';
import {
  rankPortfolioStripFirst,
  rankRequiredFullFace,
  stripProjectionForRank,
} from './rank.mjs';
import { discoverStrips, parseRootsFromEnv } from './discovery.mjs';
import {
  lookupDispatch,
  suggestDepthFromStrip,
  applyDepthOverride,
  DEFAULT_BIAS,
  DISPATCH_OUTCOMES,
} from './dispatch-table.mjs';
import {
  validateReceipt,
  buildOverrideReceipt,
  buildDepthReceipt,
  RECEIPT_SCHEMA_ID,
  OVERRIDE_REASON_FIELDS,
} from './receipt-validate.mjs';
import {
  refuseUnknownVerb,
  isClosedVerb,
  SPELLING,
  CLOSED_VERBS,
} from './verbs.mjs';
import { resolveSeats, findProductModelIds, isProductionSeatSafe } from './seating.mjs';
import { runCanaryPack } from './canary-pack.mjs';
import {
  auditGrasscatcherLedger,
  buildAllLedgerReceipts,
  assertNotMvpSurfaces,
} from './grasscatcher-ledger.mjs';
import { validateStage2Freeze, getStage2FreezeSet } from './stage2-freeze.mjs';
import { COMMISSION_SKILLS } from './commission.mjs';

function baseStrip(overrides = {}) {
  return {
    schema: 'ecgberht-strip-v0',
    project_id: 'w6-verify',
    phase: 'planning',
    active_effort: 'W6',
    human_wait: 'none',
    capacity: 'known',
    negative_heartbeat: {
      no_attention_needed: false,
      why: null,
      until: null,
    },
    anti_starvation_age_days: 0,
    grasscatch: [],
    uncertainty_flags: [],
    tool_depth_cell: 'LITE',
    next_recommended: 'Close verification pack',
    why_next: 'W6 contract',
    as_of: '2026-07-24',
    instruments: [],
    receipts: [],
    ...overrides,
  };
}

/**
 * Write authority: Face rewrite ok; Strip in-place clock mutation rejected.
 */
export function verifyWriteAuthority() {
  const face = rewriteFaceNarrative(
    {
      north_star: 'old',
      active_effort: 'W5',
      why_next: 'prior',
      human_wait: 'none',
    },
    {
      north_star: 'LITE skill+engine',
      active_effort: 'W6',
      why_next: 'freeze scope',
    },
  );
  const face_pass =
    face.ok === true &&
    face.narrative?.north_star === 'LITE skill+engine' &&
    face.narrative?.active_effort === 'W6';

  const strip = baseStrip({ as_of: '2026-07-20' });
  const mut = mutateStripInPlace(strip, { as_of: '2026-07-24' });
  const strip_reject =
    mut.ok === false && mut.error === 'strip_in_place_mutation_rejected';

  const appended = appendStripInstrument(strip, {
    kind: 'heartbeat',
    as_of: '2026-07-24',
    note: 'w6 verify',
  });
  const append_ok = appended.ok === true;

  return {
    name: 'write_authority',
    ok: face_pass && strip_reject && append_ok,
    face_rewrite: face_pass,
    strip_inplace_rejected: strip_reject,
    strip_append_ok: append_ok,
    mut_error: mut.error ?? null,
  };
}

/**
 * Strip-first rank never requires full Face; unknown capacity → penalty/LITE bias.
 */
export function verifyStripFirstRank() {
  const known = baseStrip({
    project_id: 'a-known',
    capacity: 'known',
    anti_starvation_age_days: 2,
    next_recommended: 'ship',
  });
  const unknown = baseStrip({
    project_id: 'b-unknown',
    capacity: 'unknown',
    uncertainty_flags: ['capacity_unknown'],
    anti_starvation_age_days: 10,
    next_recommended: 'probe',
  });

  const ranked = rankPortfolioStripFirst([known, unknown], { top_k: 2 });
  const needsFace = rankRequiredFullFace(ranked);
  const no_full_face =
    needsFace === false &&
    ranked.face_loads_for_rank === 0 &&
    ranked.face_required_for_rank === false;

  const list = Array.isArray(ranked.ranked) ? ranked.ranked : [];
  const unkRow = list.find((r) => r.project_id === 'b-unknown');
  const capacity_flag_seen = Boolean(
    unkRow &&
      (unkRow.flags?.capacity_unknown === true ||
        unkRow.flags?.lite_bias === true ||
        unkRow.capacity === 'unknown'),
  );
  const all_face_unloaded = list.every((r) => r.face_loaded === false);

  // Projections built without Face
  const projOk = stripProjectionForRank(unknown)?.capacity === 'unknown';

  const ok =
    ranked.ok === true &&
    no_full_face &&
    capacity_flag_seen &&
    all_face_unloaded &&
    projOk &&
    list.length === 2;

  return {
    name: 'strip_first_rank',
    ok: Boolean(ok),
    rank_required_full_face: needsFace,
    no_full_face_for_portfolio: no_full_face,
    capacity_unknown_flagged: capacity_flag_seen,
    ranked_count: list.length,
  };
}

/**
 * A1 discovery: empty roots → structured empty; env parse works.
 */
export function verifyA1Discovery(opts = {}) {
  const parsed = parseRootsFromEnv('');
  const empty = discoverStrips({
    roots: [],
    envValue: '',
    env: opts.env ?? {},
  });

  const empty_ok =
    empty.ok === true &&
    empty.empty === true &&
    Array.isArray(empty.strips) &&
    empty.strips.length === 0 &&
    empty.registry === false;

  const roots_parsed = Array.isArray(parsed) && parsed.length === 0;

  return {
    name: 'a1_discovery',
    ok: Boolean(empty_ok && roots_parsed),
    empty_roots_structured: Boolean(empty_ok),
    env_parse_empty: roots_parsed,
    empty_result: {
      ok: empty.ok,
      empty: empty.empty,
      count: empty.strips?.length ?? 0,
      registry: empty.registry,
    },
  };
}

/**
 * Dispatch LITE bias + capacity unknown flag.
 */
export function verifyDispatchLiteBias() {
  const liteCell = lookupDispatch({
    phase: 'planning',
    uncertainty: 'low',
    human_wait: 'none',
    cost: 'low',
  });
  const lite_ok = liteCell.ok === true && liteCell.outcome === 'LITE';

  const unknownStrip = baseStrip({
    capacity: 'unknown',
    uncertainty_flags: ['capacity_unknown'],
    phase: 'planning',
  });
  const suggested = suggestDepthFromStrip(unknownStrip);
  const not_silent_full =
    suggested.flags?.silent_full_green === false &&
    suggested.outcome !== 'FULL';
  const bias_ok =
    suggested.ok === true &&
    (suggested.outcome === 'LITE' || suggested.flags?.lite_bias === true) &&
    suggested.flags?.capacity_unknown === true;

  return {
    name: 'dispatch_lite_bias',
    ok: Boolean(lite_ok && bias_ok && not_silent_full),
    default_bias: DEFAULT_BIAS,
    lite_cell_outcome: liteCell.outcome,
    capacity_unknown_outcome: suggested.outcome,
    not_silent_full,
    outcomes_closed: DISPATCH_OUTCOMES.includes('LITE'),
  };
}

/**
 * Override without receipt fails; with who/when/why/from→to passes.
 */
export function verifyOverrideRequiresReceipt() {
  const bare = validateReceipt({
    schema: RECEIPT_SCHEMA_ID,
    kind: 'override',
    as_of: '2026-07-24',
  });
  const bare_fails = bare.ok === false;

  const withReason = buildOverrideReceipt({
    who: 'operator',
    when: '2026-07-24',
    why: 'need FULL for ship gate',
    from: 'LITE',
    to: 'FULL',
  });
  const good_ok = validateReceipt(withReason).ok === true;

  const applied = applyDepthOverride('LITE', 'FULL', {
    who: 'operator',
    when: '2026-07-24',
    why: 'need FULL for ship gate',
  });
  const applied_ok = applied.ok === true && applied.outcome === 'FULL';

  const incomplete = applyDepthOverride('LITE', 'FULL', { why: 'nope' });
  const incomplete_fails =
    incomplete.ok === false && incomplete.error === 'override_receipt_required';

  return {
    name: 'override_requires_receipt',
    ok: Boolean(bare_fails && good_ok && applied_ok && incomplete_fails),
    bare_fails,
    structured_passes: good_ok,
    apply_with_reason: applied_ok,
    incomplete_rejected: incomplete_fails,
    override_fields: [...OVERRIDE_REASON_FIELDS],
  };
}

/**
 * receipt-validate monologue vs structured depth receipt.
 */
export function verifyReceiptValidate() {
  const monologue = validateReceipt('just some prose without structure');
  const mono_fail = monologue.ok === false;

  const depth = buildDepthReceipt({
    outcome: 'LITE',
    tool_depth_why: 'table LITE bias',
    capacity: 'known',
    uncertainty_flags: [],
  });
  const depth_ok = validateReceipt(depth).ok === true;

  return {
    name: 'receipt_validate',
    ok: mono_fail && depth_ok,
    monologue_invalid: mono_fail,
    depth_receipt_valid: depth_ok,
  };
}

/**
 * refuse-unknown structured error.
 */
export function verifyRefuseUnknown() {
  const r = refuseUnknownVerb('openclaw-spawn');
  const ok =
    r.ok === false &&
    r.error === 'unknown_verb' &&
    r.spelling === SPELLING &&
    Array.isArray(r.closed_verbs) &&
    !isClosedVerb('openclaw-spawn');

  return {
    name: 'refuse_unknown',
    ok: Boolean(ok),
    error: r.error,
    spelling: r.spelling,
  };
}

/**
 * Seating prefs mock without product IDs.
 */
export function verifySeatingPrefsMock() {
  const seats = resolveSeats({
    prefs: {
      coding_family: 'claude',
      review_family: 'gemini',
      default_cli: 'claude',
    },
  });
  const productIds = findProductModelIds(seats);
  const ok =
    seats.ok === true &&
    seats.subscription_only === true &&
    seats.xai_http_seat === false &&
    productIds.length === 0 &&
    isProductionSeatSafe(seats) &&
    seats.cross_model === true &&
    seats.coding_driver === 'claude' &&
    seats.review_driver === 'gemini-cli';

  const same = resolveSeats({
    prefs: { coding_family: 'grok', review_family: 'grok' },
  });
  const same_ok =
    same.ok === true &&
    same.cross_model === false &&
    same.coding_driver === 'grok-cli';

  return {
    name: 'seating_prefs_mock',
    ok: Boolean(ok && same_ok),
    cross_model: seats.cross_model,
    same_family_cross_model: same.cross_model,
    product_model_ids: productIds,
    coding_driver: seats.coding_driver,
    review_driver: seats.review_driver,
  };
}

/**
 * Run the full consolidated verification suite + canaries + ledger + freeze.
 * @param {object} [opts]
 */
export function runVerificationPack(opts = {}) {
  const checks = [
    verifyWriteAuthority(),
    verifyStripFirstRank(),
    verifyA1Discovery(opts),
    verifyDispatchLiteBias(),
    verifyOverrideRequiresReceipt(),
    verifyReceiptValidate(),
    verifyRefuseUnknown(),
    verifySeatingPrefsMock(),
  ];

  const canaries = runCanaryPack(opts);
  const ledgerAudit = auditGrasscatcherLedger();
  const ledgerReceipts = buildAllLedgerReceipts();
  const notMvp = assertNotMvpSurfaces({
    closedVerbs: [...CLOSED_VERBS],
    commissionSkills: [...COMMISSION_SKILLS],
  });
  const freeze = validateStage2Freeze();
  const freezeSet = getStage2FreezeSet();

  const unit_ok = checks.every((c) => c.ok);
  const ok =
    unit_ok &&
    canaries.ok &&
    ledgerAudit.ok &&
    ledgerReceipts.ok &&
    notMvp.ok &&
    freeze.ok;

  return {
    ok,
    spelling: SPELLING,
    depth: freezeSet.depth,
    unit_checks: checks,
    unit_ok,
    canaries,
    grasscatcher_ledger: {
      audit: ledgerAudit,
      receipts: {
        ok: ledgerReceipts.ok,
        count: ledgerReceipts.count,
      },
      not_mvp_surfaces: notMvp,
    },
    stage2_freeze: freeze,
    failed: [
      ...checks.filter((c) => !c.ok).map((c) => c.name),
      ...(canaries.ok ? [] : ['canary_pack']),
      ...(ledgerAudit.ok ? [] : ['grasscatcher_ledger_audit']),
      ...(ledgerReceipts.ok ? [] : ['grasscatcher_ledger_receipts']),
      ...(notMvp.ok ? [] : ['grasscatcher_not_mvp']),
      ...(freeze.ok ? [] : ['stage2_freeze']),
    ],
    message: ok
      ? 'Verification pack green: North Star unit suite, canaries, Grasscatcher ledger, Stage-2 freeze'
      : 'Verification pack failed',
  };
}
