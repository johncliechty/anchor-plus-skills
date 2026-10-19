/**
 * Gate 5 / Wave 1 - the kickoff proposal RECORD: what the model authored, nothing more.
 *
 * WHY THIS FILE EXISTS. Journal 0095 caught the steward padding a one-sitting effort
 * with stages and done-conditions the model never wrote. The old compiler answered
 * that with a CLASSIFIER that tried to recognise padding by its wording - a guard that
 * could only ever catch the padding it had already seen. That classifier is deleted.
 * The Master Plan (locked 2026-09-01) replaces it with an INVARIANT: the compiler
 * GENERATES NOTHING. Every content string in the record is a string the model
 * authored; every section is one the model supplied. A simple effort therefore
 * collapses honestly to one goal, one component, one plan entry, no integration -
 * not because a rule says "collapse", but because there is nothing else to emit.
 *
 * WHAT LIVES HERE, in one module so the three laws cannot drift apart:
 *
 *   1. THE RECORD. `kickoff_proposal_v0`: goal, plain finished state (may be empty),
 *      one work product with its components, optional integration, coarse plan entries
 *      with one marked first slice, version, prior-confirmed hash, source turn,
 *      provenance, and the two authority flags. No `constraints` field - the
 *      elegance pass cut it (a constraint is prose in the finished state).
 *
 *   2. PROVENANCE BY REFUSAL. A kickoff synthesis is model-authored. The host that
 *      made the seat call asserts the seat lineage (family + driver); the compiler
 *      never stamps `authored_by: 'model'` on an input nobody vouched for. No lineage,
 *      or any `zero_model` stamp, and the input DOES NOT COMPILE - a named row, and
 *      nothing written. The proof is the refusal, not the hash.
 *
 *   3. CANONICAL BYTES AND ONE RENDERER. Hashes are taken over sorted-key UTF-8 JSON
 *      with no floats (a float is a value that may not re-serialize to the same
 *      bytes; it is refused by name). Exactly one function turns the record into the
 *      prose John reads, so `render(record) === shown_prose` is a fact about this
 *      file rather than a hope about every caller. The proposal event stores the
 *      record AND its hash AND the rendered prose AND its hash; confirmation (Wave 2)
 *      binds both.
 *
 * Failure states carry a status code AND user-visible text, with `unknown` and
 * `empty` as separate rows (kickoffFailureTable).
 *
 * Source is ASCII on purpose (the repo's mojibake sweep). Stdlib only.
 */

import crypto from 'node:crypto';

export const KICKOFF_PROPOSAL_SCHEMA = 'ecgberht-kickoff-proposal-v0';
export const KICKOFF_PROPOSAL_KIND = 'kickoff_proposal';
export const KICKOFF_SOURCE = 'steward_conversation';

export const KICKOFF_RELATIONSHIP_KINDS = Object.freeze([
  'feeds',
  'depends_on',
  'assembles_with',
  'validates',
  'integrates',
]);

/**
 * Keys a kickoff input may never carry: each is a scaffold vocabulary the record
 * replaced. Presence refuses; nothing is stripped and re-interpreted.
 */
export const KICKOFF_FORBIDDEN_FIELDS = Object.freeze(['steps', 'stages', 'annotations', 'oranges']);

export const KICKOFF_CODE = Object.freeze({
  // proposal surface (this wave)
  INVALID: 'KICKOFF_PROPOSAL_INVALID',
  PROVENANCE_REQUIRED: 'KICKOFF_PROVENANCE_REQUIRED',
  PROVENANCE_ZERO_MODEL: 'KICKOFF_PROVENANCE_ZERO_MODEL',
  CANONICAL_REFUSED: 'KICKOFF_CANONICAL_REFUSED',
  // render surface (this wave)
  NONE_YET: 'KICKOFF_NONE_YET',
  STATE_UNKNOWN: 'KICKOFF_STATE_UNKNOWN',
  // lifecycle (engine/kickoff-lifecycle.mjs owns the Wave 2 table; engine/kickoff.mjs
  // speaks the roadmap-ledger subset)
  CORRUPT: 'KICKOFF_LINEAGE_CORRUPT',
  STALE: 'KICKOFF_CONFIRM_STALE',
  HASH_MISMATCH: 'KICKOFF_CONFIRM_HASH_MISMATCH',
  WHO_REQUIRED: 'KICKOFF_WHO_REQUIRED',
  AUTH_REFUSED: 'KICKOFF_AUTH_REFUSED',
  ROADMAP_UNREADABLE: 'KICKOFF_ROADMAP_UNREADABLE',
  WRITE_FAILED: 'KICKOFF_WRITE_FAILED',
  PLAN_CONFLICT: 'KICKOFF_PLAN_CONFLICT',
  NOTHING_CONFIRMED: 'KICKOFF_NOT_CONFIRMED',
  // Wave 2 lifecycle states on the events.jsonl store
  OPEN_UNCONFIRMED: 'KICKOFF_OPEN_UNCONFIRMED',
  CONFIRMED: 'KICKOFF_CONFIRMED',
  EVENTS_UNREADABLE: 'KICKOFF_EVENTS_UNREADABLE',
  EVENTS_BOUND_EXCEEDED: 'KICKOFF_EVENTS_BOUND_EXCEEDED',
});

/** User-visible text per code. `<error>` is filled from the failure's error field. */
export const KICKOFF_TEXT = Object.freeze({
  [KICKOFF_CODE.INVALID]:
    'That is not a usable kickoff bundle (<error>) - not compiled; nothing written.',
  [KICKOFF_CODE.PROVENANCE_REQUIRED]:
    'This proposal carries no model provenance (which seat authored it) - not compiled; nothing written.',
  [KICKOFF_CODE.PROVENANCE_ZERO_MODEL]:
    'This proposal is stamped zero_model / not model-authored; a kickoff synthesis comes from the model seat - not compiled; nothing written.',
  [KICKOFF_CODE.CANONICAL_REFUSED]:
    'The proposal carries a value that cannot be serialized reproducibly (<error>) - refused rather than hashed.',
  [KICKOFF_CODE.NONE_YET]: 'No kickoff proposal yet - nothing to show.',
  [KICKOFF_CODE.STATE_UNKNOWN]:
    'Kickoff state unknown - reported as unknown, not guessed.',
  [KICKOFF_CODE.CORRUPT]:
    'The kickoff lineage on disk does not add up (<error>) - refused rather than reinterpreted.',
  [KICKOFF_CODE.STALE]:
    'That proposal is no longer the open version - confirm refused; review the current one.',
  [KICKOFF_CODE.HASH_MISMATCH]:
    'The proposal changed since it was shown - confirm refused; review it again.',
  [KICKOFF_CODE.WHO_REQUIRED]: 'A confirmation must say who confirmed - refused.',
  [KICKOFF_CODE.AUTH_REFUSED]: 'Confirm refused at the auth seam - nothing written.',
  [KICKOFF_CODE.ROADMAP_UNREADABLE]:
    'The project ledger is unreadable - refused rather than guessed.',
  [KICKOFF_CODE.WRITE_FAILED]: 'The kickoff write did not land (<error>) - nothing partial kept.',
  [KICKOFF_CODE.PLAN_CONFLICT]:
    'A plan entry id collides with a step that did not come from this kickoff - refused.',
  [KICKOFF_CODE.NOTHING_CONFIRMED]: 'No kickoff has been confirmed yet.',
  [KICKOFF_CODE.OPEN_UNCONFIRMED]:
    'A kickoff proposal is open and not yet confirmed - nothing authoritative has changed; review and confirm it.',
  [KICKOFF_CODE.CONFIRMED]:
    'This kickoff is confirmed - exactly the reviewed proposal is authoritative; a repeated confirmation writes nothing new.',
  [KICKOFF_CODE.EVENTS_UNREADABLE]:
    'The kickoff event store is unreadable (<error>) - refused rather than guessed.',
  [KICKOFF_CODE.EVENTS_BOUND_EXCEEDED]:
    'The kickoff event store is larger than its named read bound (<error>) - refused rather than read unbounded.',
});

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function kickoffFailure(code, extra = {}) {
  const known = Object.hasOwn(KICKOFF_TEXT, code);
  let text = known ? KICKOFF_TEXT[code] : KICKOFF_TEXT[KICKOFF_CODE.STATE_UNKNOWN];
  const error = extra.error ?? String(code).toLowerCase();
  if (text.includes('<error>')) text = text.replace(/<error>/g, String(error));
  return {
    ok: false,
    code,
    status_code: code,
    error,
    text,
    user_text: text,
    authoritative: false,
    ...extra,
  };
}

/**
 * Machine-readable failure-state table for the proposal and render surfaces.
 * `unknown` and `empty-but-valid` are SEPARATE rows. Every row is speakable by
 * this module's own functions; a row nothing can produce is not listed.
 *
 * @returns {ReadonlyArray<{state: string, surface: string, status_code: string, user_text: string}>}
 */
export function kickoffFailureTable() {
  const row = (state, surface, code) => Object.freeze({
    state,
    surface,
    status_code: code,
    user_text: KICKOFF_TEXT[code],
  });
  return Object.freeze([
    row('dependency-missing / provenance-missing', 'proposal', KICKOFF_CODE.PROVENANCE_REQUIRED),
    row('provenance-zero-model', 'proposal', KICKOFF_CODE.PROVENANCE_ZERO_MODEL),
    row('dependency-returns-garbage / proposal-invalid', 'proposal', KICKOFF_CODE.INVALID),
    row('serialization-refused', 'proposal', KICKOFF_CODE.CANONICAL_REFUSED),
    row('backing-store-unreadable', 'proposal', KICKOFF_CODE.ROADMAP_UNREADABLE),
    row('empty-but-valid', 'render', KICKOFF_CODE.NONE_YET),
    row('unknown', 'render', KICKOFF_CODE.STATE_UNKNOWN),
  ]);
}

// -- small helpers ---------------------------------------------------------------

const nonEmpty = (value) => typeof value === 'string' && value.trim().length > 0;
const cleanText = (value) => String(value ?? '').trim();
const isObject = (value) => value != null && typeof value === 'object' && !Array.isArray(value);
const HEX64 = /^[a-f0-9]{64}$/;

function idFrom(value, fallback, index = 0) {
  const supplied = cleanText(value).toLowerCase();
  if (/^[a-z][a-z0-9-]{0,63}$/.test(supplied)) return supplied;
  const slug = cleanText(fallback)
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 58);
  const base = /^[a-z]/.test(slug) ? slug : `item-${slug || index + 1}`;
  return `${base}${index > 0 && !slug ? `-${index + 1}` : ''}`.slice(0, 64);
}

function strings(values) {
  return (Array.isArray(values) ? values : []).map(cleanText).filter(Boolean);
}

// -- canonical bytes -------------------------------------------------------------

function emitCanonical(value, out, at) {
  if (value === null) {
    out.push('null');
    return null;
  }
  switch (typeof value) {
    case 'string':
      out.push(JSON.stringify(value));
      return null;
    case 'boolean':
      out.push(value ? 'true' : 'false');
      return null;
    case 'number':
      if (!Number.isSafeInteger(value)) return { error: 'non_integer_number', at };
      out.push(String(value));
      return null;
    case 'object':
      break;
    default:
      return { error: `unsupported_value:${typeof value}`, at };
  }
  if (Array.isArray(value)) {
    out.push('[');
    for (let i = 0; i < value.length; i += 1) {
      if (i > 0) out.push(',');
      if (value[i] === undefined) return { error: 'undefined_in_array', at: `${at}[${i}]` };
      const refused = emitCanonical(value[i], out, `${at}[${i}]`);
      if (refused) return refused;
    }
    out.push(']');
    return null;
  }
  const proto = Object.getPrototypeOf(value);
  if (proto !== Object.prototype && proto !== null) return { error: 'non_plain_object', at };
  const keys = Object.keys(value).filter((key) => value[key] !== undefined).sort();
  out.push('{');
  for (let i = 0; i < keys.length; i += 1) {
    if (i > 0) out.push(',');
    out.push(JSON.stringify(keys[i]), ':');
    const refused = emitCanonical(value[keys[i]], out, `${at}.${keys[i]}`);
    if (refused) return refused;
  }
  out.push('}');
  return null;
}

/**
 * Sorted-key, UTF-8, no-float JSON bytes. Keys are sorted by UTF-16 code unit at every
 * depth; undefined properties are omitted; a non-integer number, an undefined array
 * element, or a non-plain object is refused by name rather than coerced.
 *
 * @param {*} value
 * @returns {{ok: true, text: string, bytes: Buffer} | object}
 */
export function canonicalKickoffBytes(value) {
  const out = [];
  const refused = emitCanonical(value, out, '$');
  if (refused) {
    return kickoffFailure(KICKOFF_CODE.CANONICAL_REFUSED, { error: refused.error, at: refused.at });
  }
  const text = out.join('');
  return { ok: true, text, bytes: Buffer.from(text, 'utf8') };
}

/** @param {Buffer|string} bytes @returns {string} sha256 hex */
export function sha256Hex(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

/**
 * Hash of a payload's canonical bytes. Throws (code KICKOFF_CANONICAL_REFUSED) when
 * the payload cannot be canonicalized - a stored record with a float in it is corrupt,
 * not hashable.
 */
export function hashKickoffPayload(payload) {
  const canonical = canonicalKickoffBytes(payload);
  if (!canonical.ok) {
    const err = new TypeError(`kickoff payload is not canonical: ${canonical.error} at ${canonical.at}`);
    err.code = KICKOFF_CODE.CANONICAL_REFUSED;
    throw err;
  }
  return sha256Hex(canonical.bytes);
}

// -- the record ------------------------------------------------------------------

/**
 * The hashed body of a proposal: the record minus its own id and hash. SELECTS fields
 * from the proposal; stamps nothing (a tampered envelope must fail validation, not be
 * silently restored).
 */
export function kickoffHashBody(proposal) {
  const work = isObject(proposal.work_product) ? proposal.work_product : {};
  const integration = proposal.integration;
  return {
    schema: proposal.schema,
    kind: proposal.kind,
    version: Number(proposal.version),
    prior_confirmed_hash: proposal.prior_confirmed_hash ?? null,
    goal: proposal.goal,
    success_signals: [...(proposal.success_signals ?? [])],
    work_product: {
      id: work.id,
      name: work.name,
      components: (work.components ?? []).map((component) => ({
        id: component.id,
        name: component.name,
        done_when: component.done_when ?? null,
      })),
    },
    integration: integration == null
      ? null
      : {
        summary: integration.summary,
        relationships: (integration.relationships ?? []).map((relationship) => ({
          kind: relationship.kind,
          component_ids: [...(relationship.component_ids ?? [])],
          description: relationship.description,
        })),
        proof: {
          observable: integration.proof?.observable,
          method: integration.proof?.method,
        },
      },
    plan_entries: (proposal.plan_entries ?? []).map((entry) => ({
      id: entry.id,
      name: entry.name,
      component_ids: [...(entry.component_ids ?? [])],
      end_to_end_slice: entry.end_to_end_slice === true,
      done_when: entry.done_when ?? null,
    })),
    first_slice_id: proposal.first_slice_id,
    source_turn: {
      kind: proposal.source_turn?.kind,
      client_event_id: proposal.source_turn?.client_event_id ?? null,
      at: proposal.source_turn?.at ?? null,
    },
    provenance: {
      authored_by: proposal.provenance?.authored_by,
      source: proposal.provenance?.source,
      seat_family: proposal.provenance?.seat_family ?? null,
      driver: proposal.provenance?.driver ?? null,
      model_id_recorded: proposal.provenance?.model_id_recorded,
    },
    requires_confirm: proposal.requires_confirm,
    confirmed: proposal.confirmed,
  };
}

export function recomputeKickoffHash(proposal) {
  return hashKickoffPayload(kickoffHashBody(proposal));
}

/**
 * Provenance is asserted by the HOST that made the seat call, never read off the
 * model's reply. Missing lineage refuses; any zero_model / non-model stamp refuses.
 *
 * @param {{provenance?: object, seat_family?: string, driver?: string}} opts
 */
export function resolveKickoffProvenance(opts = {}) {
  const given = isObject(opts.provenance) ? opts.provenance : {};
  const stampedNotModel = given.zero_model === true
    || opts.zero_model === true
    || (given.authored_by != null && cleanText(given.authored_by) !== 'model');
  if (stampedNotModel) {
    return kickoffFailure(KICKOFF_CODE.PROVENANCE_ZERO_MODEL, { error: 'provenance_not_model_authored' });
  }
  const seatFamily = cleanText(opts.seat_family ?? given.seat_family);
  const driver = cleanText(opts.driver ?? given.driver);
  if (!seatFamily || !driver) {
    return kickoffFailure(KICKOFF_CODE.PROVENANCE_REQUIRED, {
      error: 'provenance_missing',
      missing: [!seatFamily ? 'seat_family' : null, !driver ? 'driver' : null].filter(Boolean),
    });
  }
  return {
    ok: true,
    provenance: {
      authored_by: 'model',
      source: KICKOFF_SOURCE,
      seat_family: seatFamily,
      driver,
      model_id_recorded: false,
    },
  };
}

/** The content rules: what a bundle must have to be one, and nothing it did not earn. */
export function validateKickoffContent(content) {
  if (!isObject(content)) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'content_not_object' });
  }
  if (!nonEmpty(content.goal)) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'goal_missing' });
  }
  if (!Array.isArray(content.success_signals)
      || content.success_signals.some((signal) => !nonEmpty(signal))) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'success_signals_invalid' });
  }

  const workProduct = content.work_product;
  const components = Array.isArray(workProduct?.components) ? workProduct.components : [];
  if (!isObject(workProduct) || !nonEmpty(workProduct.id) || !nonEmpty(workProduct.name)
      || components.length === 0) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'work_product_invalid' });
  }
  const componentIds = new Set();
  for (const component of components) {
    if (!isObject(component) || !nonEmpty(component.id) || !nonEmpty(component.name)
        || componentIds.has(component.id)) {
      return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'component_invalid_or_duplicate' });
    }
    if (component.done_when != null && !nonEmpty(component.done_when)) {
      return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'component_done_when_invalid' });
    }
    componentIds.add(component.id);
  }

  if (components.length === 1 && content.integration != null) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'single_component_integration_must_be_null' });
  }
  if (components.length > 1) {
    const integration = content.integration;
    if (!isObject(integration) || !nonEmpty(integration.summary)
        || !Array.isArray(integration.relationships) || integration.relationships.length === 0
        || !isObject(integration.proof) || !nonEmpty(integration.proof.observable)
        || !nonEmpty(integration.proof.method)) {
      return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'integration_required_for_multiple_components' });
    }
    const covered = new Set();
    for (const relationship of integration.relationships) {
      const ids = Array.isArray(relationship?.component_ids)
        ? [...new Set(relationship.component_ids)] : [];
      if (!KICKOFF_RELATIONSHIP_KINDS.includes(relationship?.kind)
          || ids.length < 2 || !nonEmpty(relationship.description)
          || ids.some((id) => !componentIds.has(id))) {
        return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'integration_relationship_invalid' });
      }
      ids.forEach((id) => covered.add(id));
    }
    if ([...componentIds].some((id) => !covered.has(id))) {
      return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'integration_relationships_do_not_cover_components' });
    }
  }

  const entries = Array.isArray(content.plan_entries) ? content.plan_entries : [];
  if (!entries.length) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'plan_entries_missing' });
  }
  const entryIds = new Set();
  let sliceCount = 0;
  for (const entry of entries) {
    const refs = Array.isArray(entry?.component_ids) ? entry.component_ids : null;
    if (!isObject(entry) || !nonEmpty(entry.id) || entryIds.has(entry.id)
        || !nonEmpty(entry.name) || refs === null || refs.some((id) => !componentIds.has(id))) {
      return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'plan_entry_invalid' });
    }
    if (entry.done_when != null && !nonEmpty(entry.done_when)) {
      return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'plan_entry_done_when_invalid' });
    }
    if (entry.end_to_end_slice === true) sliceCount += 1;
    entryIds.add(entry.id);
  }
  if (sliceCount === 0) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'end_to_end_slice_missing' });
  }
  const first = entries.find((entry) => entry.id === content.first_slice_id);
  if (!first || first.end_to_end_slice !== true) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'first_slice_id_invalid' });
  }
  return { ok: true };
}

/**
 * Normalize a model reply into the bundle CONTENT - trim, resolve ids the seat wrote in
 * a grammar the id rule rejects (journal 0097: every reference is written against the
 * AUTHORED id, so a rename is remembered and resolved through one table), and validate.
 * No provenance, no hash, no envelope: this is the parse step. Nothing is invented; an
 * omitted done_when stays omitted (null), an omitted integration stays null.
 *
 * @returns {{ok: true, content: object} | object}
 */
export function normalizeKickoffInput(input) {
  if (!isObject(input)) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'proposal_input_not_object' });
  }
  if (Object.hasOwn(input, 'zero_model')) {
    return kickoffFailure(KICKOFF_CODE.PROVENANCE_ZERO_MODEL, { error: 'forbidden_kickoff_field:zero_model' });
  }
  for (const forbidden of KICKOFF_FORBIDDEN_FIELDS) {
    if (Object.hasOwn(input, forbidden)) {
      return kickoffFailure(KICKOFF_CODE.INVALID, { error: `forbidden_kickoff_field:${forbidden}` });
    }
  }

  const work = isObject(input.work_product) ? input.work_product : {};
  const rawComponents = Array.isArray(work.components) ? work.components : [];
  const componentIdMap = new Map();
  const components = rawComponents.map((component, index) => {
    const id = idFrom(component?.id, component?.name, index);
    const rawKey = cleanText(component?.id).toLowerCase();
    if (rawKey && !componentIdMap.has(rawKey)) componentIdMap.set(rawKey, id);
    return {
      id,
      name: cleanText(component?.name),
      done_when: nonEmpty(component?.done_when) ? cleanText(component.done_when) : null,
    };
  });
  const mapComponentRef = (ref) => {
    const key = cleanText(ref).toLowerCase();
    return componentIdMap.get(key) ?? key;
  };

  const rawEntries = Array.isArray(input.plan_entries) ? input.plan_entries : [];
  const entryIdMap = new Map();
  const planEntries = rawEntries.map((entry, index) => {
    const id = idFrom(entry?.id, entry?.name, index);
    const rawKey = cleanText(entry?.id).toLowerCase();
    if (rawKey && !entryIdMap.has(rawKey)) entryIdMap.set(rawKey, id);
    return {
      id,
      name: cleanText(entry?.name),
      component_ids: [...new Set(strings(entry?.component_ids).map(mapComponentRef))],
      end_to_end_slice: entry?.end_to_end_slice === true,
      done_when: nonEmpty(entry?.done_when) ? cleanText(entry.done_when) : null,
    };
  });

  let integration = null;
  if (isObject(input.integration)) {
    integration = {
      summary: cleanText(input.integration.summary),
      relationships: (Array.isArray(input.integration.relationships)
        ? input.integration.relationships : []).map((relationship) => ({
        kind: cleanText(relationship?.kind),
        component_ids: [...new Set(strings(relationship?.component_ids).map(mapComponentRef))],
        description: cleanText(relationship?.description),
      })),
      proof: {
        observable: cleanText(input.integration.proof?.observable),
        method: cleanText(input.integration.proof?.method),
      },
    };
  }

  const firstSliceRef = cleanText(input.first_slice_id).toLowerCase();
  const firstSlice = (firstSliceRef && (entryIdMap.get(firstSliceRef) ?? firstSliceRef))
    || planEntries.find((entry) => entry.end_to_end_slice)?.id
    || '';

  const content = {
    goal: cleanText(input.goal),
    success_signals: strings(input.success_signals),
    work_product: {
      id: idFrom(work.id, work.name),
      name: cleanText(work.name),
      components,
    },
    integration,
    plan_entries: planEntries,
    first_slice_id: firstSlice,
  };
  const valid = validateKickoffContent(content);
  if (!valid.ok) return valid;
  return { ok: true, content };
}

/** Validate a full, renderable record: envelope + content + hash. */
export function validateKickoffProposal(proposal) {
  if (!isObject(proposal)) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'proposal_not_object' });
  }
  if (proposal.schema !== KICKOFF_PROPOSAL_SCHEMA || proposal.kind !== KICKOFF_PROPOSAL_KIND) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'proposal_wrong_schema_or_kind' });
  }
  if (!Number.isInteger(proposal.version) || proposal.version < 1) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'proposal_version_invalid' });
  }
  if (proposal.prior_confirmed_hash != null && !HEX64.test(String(proposal.prior_confirmed_hash))) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'prior_confirmed_hash_invalid' });
  }
  if (Object.hasOwn(proposal, 'material_constraints') || Object.hasOwn(proposal, 'constraints')) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'constraints_field_not_in_record' });
  }
  const content = validateKickoffContent(proposal);
  if (!content.ok) return content;
  if (!isObject(proposal.source_turn) || proposal.source_turn.kind !== KICKOFF_SOURCE) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'source_turn_invalid' });
  }
  const provenance = proposal.provenance;
  if (!isObject(provenance) || provenance.zero_model === true || provenance.authored_by !== 'model') {
    return kickoffFailure(KICKOFF_CODE.PROVENANCE_ZERO_MODEL, { error: 'provenance_not_model_authored' });
  }
  if (provenance.source !== KICKOFF_SOURCE || provenance.model_id_recorded !== false
      || !nonEmpty(provenance.seat_family) || !nonEmpty(provenance.driver)) {
    return kickoffFailure(KICKOFF_CODE.PROVENANCE_REQUIRED, { error: 'provenance_missing' });
  }
  if (proposal.requires_confirm !== true || proposal.confirmed !== false) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'proposal_authority_flags_invalid' });
  }
  const canonical = canonicalKickoffBytes(kickoffHashBody(proposal));
  if (!canonical.ok) return canonical;
  const expected = sha256Hex(canonical.bytes);
  if (proposal.proposal_hash != null && proposal.proposal_hash !== expected) {
    return kickoffFailure(KICKOFF_CODE.INVALID, {
      error: 'proposal_hash_corrupt',
      expected_hash: expected,
      provided_hash: proposal.proposal_hash,
    });
  }
  return { ok: true, expected_hash: expected };
}

/**
 * Compile a model-authored input into the record, its hash, and its rendered prose.
 * Provenance is checked FIRST: a provenance-less or zero_model input is refused before
 * its content is read. No writes.
 *
 * @param {object} input the model's bundle (goal, success_signals, work_product, ...)
 * @param {object} [opts] version, prior_confirmed_hash, source_turn_id, source_turn_at,
 *   at, and the host-asserted provenance (seat_family + driver, or provenance: {...})
 * @returns {{ok: true, proposal: object, proposal_hash: string, rendered_prose: string,
 *   rendered_prose_hash: string} | object}
 */
export function compileKickoffProposal(input, opts = {}) {
  const provenance = resolveKickoffProvenance(opts);
  if (!provenance.ok) return provenance;
  const normalized = normalizeKickoffInput(input);
  if (!normalized.ok) return normalized;

  const version = Number(opts.version ?? input.version);
  if (!Number.isInteger(version) || version < 1) {
    return kickoffFailure(KICKOFF_CODE.INVALID, { error: 'proposal_version_invalid' });
  }
  const priorConfirmedHash = opts.prior_confirmed_hash !== undefined
    ? opts.prior_confirmed_hash
    : input.prior_confirmed_hash ?? null;
  const source = isObject(input.source_turn) ? input.source_turn : {};

  const body = {
    schema: KICKOFF_PROPOSAL_SCHEMA,
    kind: KICKOFF_PROPOSAL_KIND,
    version,
    prior_confirmed_hash: priorConfirmedHash ?? null,
    ...normalized.content,
    source_turn: {
      kind: KICKOFF_SOURCE,
      client_event_id: cleanText(opts.source_turn_id ?? source.client_event_id) || null,
      at: cleanText(opts.source_turn_at ?? source.at ?? opts.at) || null,
    },
    provenance: provenance.provenance,
    requires_confirm: true,
    confirmed: false,
  };
  const canonical = canonicalKickoffBytes(body);
  if (!canonical.ok) return canonical;
  const proposalHash = sha256Hex(canonical.bytes);
  const proposal = {
    ...body,
    proposal_id: `kickoff-v${version}-${proposalHash.slice(0, 12)}`,
    proposal_hash: proposalHash,
  };
  const valid = validateKickoffProposal(proposal);
  if (!valid.ok) return valid;
  const rendered = renderKickoffProposal(proposal);
  if (!rendered.ok) return rendered;
  return {
    ok: true,
    proposal,
    proposal_hash: proposalHash,
    rendered_prose: rendered.prose,
    rendered_prose_hash: rendered.prose_hash,
  };
}

// -- the one renderer ------------------------------------------------------------

const RELATIONSHIP_WORDS = Object.freeze({
  feeds: 'feeds',
  depends_on: 'depends on',
  assembles_with: 'assembles with',
  validates: 'validates',
  integrates: 'integrates',
});

/**
 * THE renderer: record -> the prose John reviews. Deterministic, LF-only, one trailing
 * newline; labelled in human words (Outcome / Finished when / Parts of <deliverable> /
 * Plan / First slice / How the parts join / Seen when) and never in schema vocabulary.
 * Every content field of the record appears in the prose. Renders only what the
 * record carries: no finished state, no "Finished when"; no integration, no join
 * section; no done_when, no condition. Nothing is described that was not authored.
 *
 * @param {object|null|undefined} record
 * @returns {{ok: true, prose: string, prose_hash: string} | object}
 */
export function renderKickoffProposal(record) {
  if (record == null) {
    return kickoffFailure(KICKOFF_CODE.NONE_YET, { error: 'no_kickoff_proposal' });
  }
  if (!isObject(record) || record.kind !== KICKOFF_PROPOSAL_KIND
      || record.schema !== KICKOFF_PROPOSAL_SCHEMA || !isObject(record.work_product)) {
    return kickoffFailure(KICKOFF_CODE.STATE_UNKNOWN, { error: 'not_a_kickoff_proposal' });
  }
  const components = Array.isArray(record.work_product.components)
    ? record.work_product.components : [];
  const nameOf = new Map(components.map((component) => [component.id, component.name]));
  const entries = Array.isArray(record.plan_entries) ? record.plan_entries : [];
  const lines = [];

  lines.push(`Outcome: ${record.goal}`);
  const signals = Array.isArray(record.success_signals) ? record.success_signals : [];
  if (signals.length) {
    lines.push('Finished when:');
    for (const signal of signals) lines.push(`- ${signal}`);
  }
  lines.push(`Parts of ${record.work_product.name}:`);
  for (const component of components) {
    lines.push(component.done_when
      ? `- ${component.name} -- done when ${component.done_when}`
      : `- ${component.name}`);
  }
  lines.push('Plan:');
  entries.forEach((entry, index) => {
    let line = `${index + 1}. ${entry.name}`;
    if (entry.end_to_end_slice === true) line += ' (end-to-end)';
    const refs = Array.isArray(entry.component_ids) ? entry.component_ids : [];
    if (components.length > 1 && refs.length) {
      line += ` [${refs.map((id) => nameOf.get(id) ?? id).join(', ')}]`;
    }
    if (entry.done_when) line += ` -- done when ${entry.done_when}`;
    lines.push(line);
  });
  const first = entries.find((entry) => entry.id === record.first_slice_id);
  if (first) lines.push(`First slice: ${first.name}`);
  if (isObject(record.integration)) {
    const integration = record.integration;
    lines.push(`How the parts join: ${integration.summary}`);
    for (const relationship of integration.relationships ?? []) {
      const names = (relationship.component_ids ?? []).map((id) => nameOf.get(id) ?? id);
      const word = RELATIONSHIP_WORDS[relationship.kind] ?? relationship.kind;
      lines.push(`- ${names.join(' + ')} (${word}): ${relationship.description}`);
    }
    lines.push(`Seen when: ${integration.proof?.observable} -- ${integration.proof?.method}`);
  }

  const prose = `${lines.join('\n')}\n`;
  return { ok: true, prose, prose_hash: sha256Hex(Buffer.from(prose, 'utf8')) };
}
