/**
 * Structured receipt validation against schema/receipt.schema.json.
 * Monologue-only payloads are invalid. No free-form accept.
 *
 * W4: override requires who/when/why/from→to; soft-vet/grasscatch/depth/handback
 * carry deferred, why, suggested_later_owner, uncertainty_flags, tool_depth_why.
 * W5: commission handback requires active_effort, why_next, grasscatch_why,
 * tool_depth_why, human_wait, uncertainty_flags (grasscatch_why may be null).
 * TW4: seat_hop (non-event seat switch) requires who/when/from→to;
 * face_confirm ("Still the goal") requires who + when (Face-only receipt).
 */

import { loadReceiptSchema } from './load.mjs';

export const RECEIPT_SCHEMA_ID = 'ecgberht-receipt-v0';

/** Kinds locked in schema/receipt.schema.json */
export const RECEIPT_KINDS = Object.freeze([
  'soft-vet',
  'grasscatch',
  'depth',
  'handback',
  'heartbeat',
  'override',
  'seen',
  'commission_abnormal',
  'seat_hop',
  'face_confirm',
]);

/**
 * TW4 seat hop receipt: who/when/from→to all required. A hop is a
 * NON-EVENT (no re-brief); the receipt is the transition document.
 */
export const SEAT_HOP_RECEIPT_FIELDS = Object.freeze([
  'who',
  'when',
  'from',
  'to',
]);

/** TW4 Face confirm receipt ("Still the goal") — Face-only acknowledgement. */
export const FACE_CONFIRM_RECEIPT_FIELDS = Object.freeze(['who', 'when']);

/**
 * TW3 (M2): abnormal job exit receipt — a dead terminal must never persist
 * as silent green. All four fields are required.
 */
export const COMMISSION_ABNORMAL_FIELDS = Object.freeze([
  'who',
  'when',
  'last_known_state',
  'why_known',
]);

/** TW2 seen receipt: locked shape {kind, who, when, altitude}. */
export const SEEN_ALTITUDES = Object.freeze(['project', 'portfolio']);

/** Override reason fields (human override of table outcome). */
export const OVERRIDE_REASON_FIELDS = Object.freeze([
  'who',
  'when',
  'why',
  'from',
  'to',
]);

/**
 * W5 handback required structured fields.
 * grasscatch_why may be null (key must be present); others non-empty / array.
 */
export const HANDBACK_REQUIRED_FIELDS = Object.freeze([
  'active_effort',
  'why_next',
  'grasscatch_why',
  'tool_depth_why',
  'human_wait',
  'uncertainty_flags',
]);

/**
 * True when value looks like unstructured prose with no receipt shape.
 * @param {*} value
 */
export function isMonologueOnly(value) {
  if (typeof value === 'string') {
    const t = value.trim();
    if (!t) return true;
    // Plain prose / free-form text is monologue
    if (!t.startsWith('{') && !t.startsWith('[')) return true;
    try {
      JSON.parse(t);
      return false;
    } catch {
      return true;
    }
  }
  if (value == null) return true;
  if (typeof value !== 'object' || Array.isArray(value)) return true;
  // Object without schema/kind is monologue-shaped
  if (!value.schema && !value.kind && !value.as_of) return true;
  return false;
}

function nonEmpty(v) {
  return v != null && v !== '';
}

/**
 * Validate a structured receipt against the locked receipt schema (stdlib checks).
 * @param {*} input receipt object or JSON string
 * @param {{ schema?: object }} [opts]
 * @returns {{ ok: true, receipt: object, schema_id: string } | { ok: false, error: string, message: string, issues?: string[] }}
 */
export function validateReceipt(input, opts = {}) {
  let receipt = input;

  if (typeof input === 'string') {
    if (isMonologueOnly(input)) {
      return {
        ok: false,
        error: 'monologue_only_invalid',
        message:
          'Receipt is monologue-only prose; structured receipt schema is required (schema/kind/as_of).',
        issues: ['monologue_only'],
      };
    }
    try {
      receipt = JSON.parse(input);
    } catch (e) {
      return {
        ok: false,
        error: 'receipt_json_parse',
        message: String(e?.message ?? e),
        issues: ['json_parse'],
      };
    }
  }

  if (isMonologueOnly(receipt)) {
    return {
      ok: false,
      error: 'monologue_only_invalid',
      message:
        'Receipt is monologue-only or missing structure; structured receipt schema is required.',
      issues: ['monologue_only'],
    };
  }

  const schema = opts.schema ?? loadReceiptSchema();
  const issues = [];

  if (receipt.schema !== RECEIPT_SCHEMA_ID && receipt.schema !== schema.$id) {
    issues.push(`schema must be ${RECEIPT_SCHEMA_ID}`);
  }
  if (typeof receipt.kind !== 'string' || !receipt.kind) {
    issues.push('kind is required string');
  } else if (!RECEIPT_KINDS.includes(receipt.kind)) {
    issues.push(`kind must be one of: ${RECEIPT_KINDS.join(', ')}`);
  }
  if (typeof receipt.as_of !== 'string' || !receipt.as_of.trim()) {
    issues.push('as_of is required string');
  }

  // Soft-vet / grasscatch: deferred item, why, optional owner + uncertainty flags
  if (receipt.kind === 'soft-vet' || receipt.kind === 'grasscatch') {
    const deferred = receipt.deferred ?? receipt.what_deferred;
    const why = receipt.grasscatch_why ?? receipt.why ?? receipt.reason;
    if (!nonEmpty(deferred)) {
      issues.push('soft-vet/grasscatch receipt requires deferred (what deferred)');
    }
    if (!nonEmpty(why)) {
      issues.push('soft-vet/grasscatch receipt requires why / grasscatch_why');
    }
    // suggested_later_owner and uncertainty_flags are schema fields (may be null/[])
    if (
      receipt.suggested_later_owner !== undefined &&
      receipt.suggested_later_owner !== null &&
      typeof receipt.suggested_later_owner !== 'string'
    ) {
      issues.push('suggested_later_owner must be string or null');
    }
    if (
      receipt.uncertainty_flags !== undefined &&
      !Array.isArray(receipt.uncertainty_flags)
    ) {
      issues.push('uncertainty_flags must be an array when present');
    }
  }

  // Depth receipt: tool_depth_why required; uncertainty flags when present
  if (receipt.kind === 'depth') {
    const why =
      receipt.tool_depth_why ?? receipt.why ?? receipt.depth_why ?? null;
    if (!nonEmpty(why)) {
      issues.push('depth receipt requires tool_depth_why');
    }
    if (
      receipt.uncertainty_flags !== undefined &&
      !Array.isArray(receipt.uncertainty_flags)
    ) {
      issues.push('uncertainty_flags must be an array when present');
    }
  }

  // Override without reason fields fails hard (who/when/why/from→to)
  if (receipt.kind === 'override') {
    const ov = receipt.override;
    if (!ov || typeof ov !== 'object') {
      issues.push(
        'override receipt requires override object with who/when/why/from/to',
      );
    } else {
      for (const key of OVERRIDE_REASON_FIELDS) {
        if (!nonEmpty(ov[key])) {
          issues.push(`override.${key} required`);
        }
      }
    }
  }

  // Seen (TW2): brief-view delta anchor — requires who / when / altitude
  if (receipt.kind === 'seen') {
    if (!nonEmpty(receipt.who)) {
      issues.push('seen receipt requires who');
    }
    if (!nonEmpty(receipt.when) && !nonEmpty(receipt.as_of)) {
      issues.push('seen receipt requires when (or as_of)');
    }
    if (!SEEN_ALTITUDES.includes(receipt.altitude)) {
      issues.push(`seen receipt altitude must be one of: ${SEEN_ALTITUDES.join(', ')}`);
    }
  }

  // Seat hop (TW4): non-event seat switch — who/when/from→to all required
  if (receipt.kind === 'seat_hop') {
    for (const key of SEAT_HOP_RECEIPT_FIELDS) {
      if (!nonEmpty(receipt[key])) {
        issues.push(`seat_hop receipt requires ${key}`);
      }
    }
  }

  // Face confirm (TW4 "Still the goal"): Face-only acknowledgement
  if (receipt.kind === 'face_confirm') {
    if (!nonEmpty(receipt.who)) {
      issues.push('face_confirm receipt requires who');
    }
    if (!nonEmpty(receipt.when) && !nonEmpty(receipt.as_of)) {
      issues.push('face_confirm receipt requires when (or as_of)');
    }
  }

  // Commission abnormal (TW3/M2): who/when/last_known_state/why_known required
  if (receipt.kind === 'commission_abnormal') {
    for (const key of COMMISSION_ABNORMAL_FIELDS) {
      if (!nonEmpty(receipt[key])) {
        issues.push(`commission_abnormal receipt requires ${key}`);
      }
    }
  }

  // Handback: full structured contract (W5 commission path)
  if (receipt.kind === 'handback') {
    for (const key of ['active_effort', 'why_next', 'human_wait', 'tool_depth_why']) {
      if (!nonEmpty(receipt[key])) {
        issues.push(`handback requires ${key}`);
      }
    }
    // grasscatch_why must be present; null is allowed (no grasscatch deferral)
    if (receipt.grasscatch_why === undefined) {
      issues.push('handback requires grasscatch_why (string or null)');
    } else if (
      receipt.grasscatch_why !== null &&
      typeof receipt.grasscatch_why !== 'string'
    ) {
      issues.push('handback grasscatch_why must be string or null');
    }
    if (!Array.isArray(receipt.uncertainty_flags)) {
      issues.push('handback requires uncertainty_flags array');
    }
  }

  if (issues.length) {
    return {
      ok: false,
      error: 'receipt_schema_invalid',
      message: `Receipt failed structured validation: ${issues.join('; ')}`,
      issues,
      schema_id: RECEIPT_SCHEMA_ID,
    };
  }

  return {
    ok: true,
    receipt,
    schema_id: RECEIPT_SCHEMA_ID,
    monologue: false,
  };
}

/**
 * Build a soft-vet / grasscatch receipt envelope with locked fields.
 * @param {{ deferred: string, why: string, handback_shape?: object|string|null, suggested_later_owner?: string|null, as_of?: string, kind?: string, active_effort?: string|null, uncertainty_flags?: string[], tool_depth_why?: string|null }} fields
 */
export function buildGrasscatchReceipt(fields = {}) {
  const kind = fields.kind === 'soft-vet' ? 'soft-vet' : 'grasscatch';
  const as_of = fields.as_of ?? new Date().toISOString().slice(0, 10);
  return {
    schema: RECEIPT_SCHEMA_ID,
    kind,
    as_of,
    deferred: fields.deferred ?? null,
    what_deferred: fields.deferred ?? null,
    grasscatch_why: fields.why ?? null,
    why: fields.why ?? null,
    handback_shape: fields.handback_shape ?? {
      when: 'later',
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
    suggested_later_owner: fields.suggested_later_owner ?? null,
    active_effort: fields.active_effort ?? null,
    uncertainty_flags: Array.isArray(fields.uncertainty_flags)
      ? [...fields.uncertainty_flags]
      : [],
    tool_depth_why: fields.tool_depth_why ?? null,
  };
}

/**
 * Build a depth / depth-suggest receipt (table outcome + why).
 * @param {{ outcome: string, tool_depth_why: string, as_of?: string, uncertainty_flags?: string[], capacity?: string|null, active_effort?: string|null, dimensions?: object, flags?: object }} fields
 */
export function buildDepthReceipt(fields = {}) {
  const as_of = fields.as_of ?? new Date().toISOString().slice(0, 10);
  return {
    schema: RECEIPT_SCHEMA_ID,
    kind: 'depth',
    as_of,
    outcome: fields.outcome ?? null,
    tool_depth_why: fields.tool_depth_why ?? fields.why ?? null,
    why: fields.tool_depth_why ?? fields.why ?? null,
    uncertainty_flags: Array.isArray(fields.uncertainty_flags)
      ? [...fields.uncertainty_flags]
      : [],
    capacity: fields.capacity ?? null,
    active_effort: fields.active_effort ?? null,
    dimensions: fields.dimensions ?? null,
    flags: fields.flags ?? null,
    suggested_later_owner: fields.suggested_later_owner ?? null,
    deferred: fields.deferred ?? null,
  };
}

/**
 * Build a human override receipt (table outcome changed with structured reason).
 * @param {{ who: string, when: string, why: string, from: string, to: string, as_of?: string, tool_depth_why?: string|null, uncertainty_flags?: string[] }} fields
 */
export function buildOverrideReceipt(fields = {}) {
  const as_of = fields.as_of ?? fields.when ?? new Date().toISOString().slice(0, 10);
  const override = {
    who: fields.who ?? null,
    when: fields.when ?? as_of,
    why: fields.why ?? null,
    from: fields.from ?? null,
    to: fields.to ?? null,
  };
  return {
    schema: RECEIPT_SCHEMA_ID,
    kind: 'override',
    as_of,
    override,
    tool_depth_why:
      fields.tool_depth_why ??
      (override.from && override.to
        ? `human override ${override.from}→${override.to}: ${override.why ?? ''}`
        : null),
    uncertainty_flags: Array.isArray(fields.uncertainty_flags)
      ? [...fields.uncertainty_flags]
      : [],
    active_effort: fields.active_effort ?? null,
  };
}

/**
 * Build a commission handback receipt with W5 required structured fields.
 * @param {{
 *   active_effort?: string|null,
 *   why_next?: string|null,
 *   grasscatch_why?: string|null,
 *   tool_depth_why?: string|null,
 *   human_wait?: string|null,
 *   uncertainty_flags?: string[],
 *   as_of?: string,
 *   skill?: string|null,
 *   depth?: string|null,
 *   commission_id?: string|null,
 *   partial?: boolean,
 * }} fields
 */
export function buildHandbackReceipt(fields = {}) {
  const as_of = fields.as_of ?? new Date().toISOString().slice(0, 10);
  return {
    schema: RECEIPT_SCHEMA_ID,
    kind: 'handback',
    as_of,
    active_effort: fields.active_effort ?? null,
    why_next: fields.why_next ?? null,
    // key always present; null means no grasscatch deferral on this handback
    grasscatch_why:
      fields.grasscatch_why !== undefined ? fields.grasscatch_why : null,
    tool_depth_why: fields.tool_depth_why ?? null,
    human_wait: fields.human_wait ?? null,
    uncertainty_flags: Array.isArray(fields.uncertainty_flags)
      ? [...fields.uncertainty_flags]
      : fields.uncertainty_flags === undefined
        ? []
        : fields.uncertainty_flags,
    skill: fields.skill ?? null,
    depth: fields.depth ?? fields.depth_cell ?? null,
    commission_id: fields.commission_id ?? null,
    partial: fields.partial === true,
  };
}

/**
 * Build a commission_abnormal receipt (TW3/M2 abnormal job exit).
 * who/when/last_known_state/why_known are the required core — a crash,
 * timeout, kill, orphan, or reap must land this receipt (never silent green).
 * @param {{
 *   who: string,
 *   when?: string,
 *   last_known_state: string,
 *   why_known: string,
 *   as_of?: string,
 *   terminal?: string|null,
 *   job_id?: string|null,
 *   commission_id?: string|null,
 *   step_id?: string|null,
 *   skill?: string|null,
 *   exit_code?: number|null,
 *   signal?: string|null,
 * }} fields
 */
export function buildCommissionAbnormalReceipt(fields = {}) {
  const as_of =
    fields.as_of ?? fields.when ?? new Date().toISOString().slice(0, 10);
  return {
    schema: RECEIPT_SCHEMA_ID,
    kind: 'commission_abnormal',
    as_of,
    who: fields.who ?? null,
    when: fields.when ?? as_of,
    last_known_state: fields.last_known_state ?? null,
    why_known: fields.why_known ?? null,
    terminal: fields.terminal ?? null,
    job_id: fields.job_id ?? null,
    commission_id: fields.commission_id ?? null,
    step_id: fields.step_id ?? null,
    skill: fields.skill ?? null,
    exit_code: fields.exit_code ?? null,
    signal: fields.signal ?? null,
  };
}
