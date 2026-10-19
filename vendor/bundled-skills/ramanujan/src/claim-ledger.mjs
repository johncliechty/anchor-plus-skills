// Wave 3 — Typed CLAIM ledger + promote() (A1).
//
// The shared spine every pillar emits into. A claim is a TYPED assertion carried at a
// RUNG on the evidence ladder
//
//     REFUTED < UNVERIFIED < CLAIMED < PLAUSIBILITY-CORROBORATED < CORROBORATED < OBSERVED < GROUNDED
//
// (Increment-2 / Wave 3 inserted PLAUSIBILITY-CORROBORATED strictly BELOW the locked OBSERVED and
// ABOVE the locked CLAIMED — the weaker SOFT-SEMANTIC-CHECK tier earned by a cross-family panel
// quorum (DESCRIPTION-INC2 §v2.1 "rung ordinal"). It does NOT alias or reorder the existing
// CORROBORATED rung, which remains the stronger cross-model-corroborated proof rung.
// Increment-2 / Wave 5 appended GROUNDED as the new TOP rung, strictly ABOVE OBSERVED: the
// human-attested apex reachable ONLY with a >=OBSERVED-class Lean+z3 artifact AND a valid attested
// human assent bound to it — human-gated, NOT autonomously reachable. See human-gate.mjs.)
//
// plus a BELIEF-TAG that is a DETERMINISTIC PROJECTION of that rung (a pure, total
// function of the rung alone — see beliefForRung). The belief tag is the dialogue-facing
// label: OBSERVED and GROUNDED both project to the settled tag VERIFIED. OBSERVED is the highest
// rung THE AUTONOMOUS tier reaches (a literal finite computation bound to a re-executable
// out-of-model subprocess artifact; the artifact gate itself is Wave 4); GROUNDED sits above it but
// is NOT autonomously reachable — it additionally requires an out-of-band human attestation (Wave 5).
//
// Two invariants this module enforces, both demanded by the done-when:
//
//   1. STICKY semantics (anti-sycophancy). A claim's rung never DROPS through the public
//      API, and re-assertion of an already-recorded claim NEVER changes its rung — the
//      ledger holds the rung and refuses to flip it on mere re-assertion. (Given a
//      VERIFIED claim, re-assertion without re-verification holds the rung — no flip.)
//
//   2. promote() is the SOLE rung-RAISER. assert() admits a new claim only at or below the
//      floor rung (UNVERIFIED); it can never raise a rung. The only path that lifts a claim
//      to a higher rung is promote(), which raises strictly upward and records provenance
//      (the verifier-family stamp). Snapshots handed out by get()/all() are deep-frozen
//      clones, so external code cannot reach in and set a rung behind promote()'s back.
//
// In-memory by construction: Wave 4 wires the durable adjudication-artifact substrate and
// gates promote()-to-OBSERVED on a fresh artifact. This wave is the ladder + projection +
// sticky semantics + promote() only — node built-ins only, runs under `node --test test/`.

// ---------------------------------------------------------------------------
// The rung ladder (ordered, REFUTED lowest -> GROUNDED highest).
// ---------------------------------------------------------------------------

/** The rung ladder, weakest -> strongest. Index == rank. */
export const RUNGS = Object.freeze([
  'REFUTED',
  'UNVERIFIED',
  'CLAIMED',
  'PLAUSIBILITY-CORROBORATED', // Inc-2/Wave-3 soft cross-family check — strictly below OBSERVED, above CLAIMED.
  'CORROBORATED',
  'OBSERVED',
  'GROUNDED', // Inc-2/Wave-5 human-attested apex — strictly ABOVE OBSERVED (>=OBSERVED artifact + attested assent).
]);

/** Symbolic rung constants (name -> name) so callers spell rungs without string literals. */
export const RUNG = Object.freeze(Object.fromEntries(RUNGS.map((r) => [r, r])));

const RUNG_RANK = Object.freeze(Object.fromEntries(RUNGS.map((r, i) => [r, i])));

/**
 * The FLOOR rung: the highest rung at which assert() may admit a claim. Anything stronger
 * MUST be earned through promote(). New claims emitted by the pillars enter here (Wave-15
 * "every emitted claim is at UNVERIFIED until the router verifies it").
 */
export const FLOOR_RUNG = RUNG.UNVERIFIED;

/** True iff `x` is one of the five ladder rungs. */
export function isRung(x) {
  return typeof x === 'string' && Object.prototype.hasOwnProperty.call(RUNG_RANK, x);
}

function assertRung(r, label = 'rung') {
  if (!isRung(r)) {
    throw new Error(`invalid ${label}: ${JSON.stringify(r)} (expected one of ${RUNGS.join(' < ')})`);
  }
  return r;
}

/** Numeric rank of a rung (0 = REFUTED .. 6 = GROUNDED). Throws on a non-rung. */
export function rungRank(r) {
  assertRung(r);
  return RUNG_RANK[r];
}

/** Compare two rungs by rank: <0 if a is weaker, 0 if equal, >0 if a is stronger. */
export function compareRungs(a, b) {
  return rungRank(a) - rungRank(b);
}

// ---------------------------------------------------------------------------
// Belief-tag = deterministic projection of the rung.
// ---------------------------------------------------------------------------

/** The belief tags a rung can project to (the dialogue-/human-facing labels). */
export const BELIEF = Object.freeze({
  REFUTED: 'REFUTED',
  CONJECTURAL: 'CONJECTURAL',
  CORROBORATED: 'CORROBORATED',
  VERIFIED: 'VERIFIED',
});

// The projection table. Deterministic + TOTAL over the six rungs:
//   REFUTED                  -> REFUTED       (disproven)
//   UNVERIFIED               -> CONJECTURAL   (not settled; must abstain/route)
//   CLAIMED                  -> CONJECTURAL   (single-family ceiling for proof/conceptual; still not settled)
//   PLAUSIBILITY-CORROBORATED-> CORROBORATED  (soft cross-family semantic check — grounded out-of-model
//                                              but NOT a proof oracle and NOT autonomously settled; the
//                                              finer "soft vs. strong" distinction lives in the rung +
//                                              the verifier's soft-check stamp, not the belief tag)
//   CORROBORATED             -> CORROBORATED  (grounded by out-of-model corroboration; Increment-2 territory)
//   OBSERVED                 -> VERIFIED      (the autonomously-settled tag, via the firewall / Lean artifact)
//   GROUNDED                 -> VERIFIED      (the human-attested apex on top of a >=OBSERVED artifact; settled-
//                                              class but NOT autonomous — it requires an out-of-band human assent)
const BELIEF_BY_RUNG = Object.freeze({
  REFUTED: BELIEF.REFUTED,
  UNVERIFIED: BELIEF.CONJECTURAL,
  CLAIMED: BELIEF.CONJECTURAL,
  'PLAUSIBILITY-CORROBORATED': BELIEF.CORROBORATED,
  CORROBORATED: BELIEF.CORROBORATED,
  OBSERVED: BELIEF.VERIFIED,
  GROUNDED: BELIEF.VERIFIED,
});

/** The belief tag for a rung — a pure, total function of the rung alone. Throws on a non-rung. */
export function beliefForRung(r) {
  assertRung(r);
  return BELIEF_BY_RUNG[r];
}

/**
 * Whether a belief tag is strong enough for a pillar to assert as SETTLED. Only VERIFIED
 * qualifies (Wave-19 "dialogue asserts-as-settled ONLY VERIFIED claims"); everything else
 * must abstain/route or be flagged disproven.
 */
export function isAssertableAsSettled(belief) {
  return belief === BELIEF.VERIFIED;
}

// ---------------------------------------------------------------------------
// Typed claims.
// ---------------------------------------------------------------------------

/** The claim-type vocabulary (Wave-16 classifies into these; the ledger only stores + validates). */
export const CLAIM_TYPES = Object.freeze(['computational', 'proof-bearing', 'conceptual']);

function assertClaimType(t) {
  if (typeof t !== 'string' || !CLAIM_TYPES.includes(t)) {
    throw new Error(`invalid claim type: ${JSON.stringify(t)} (expected one of ${CLAIM_TYPES.join(', ')})`);
  }
  return t;
}

function assertId(id) {
  if (typeof id !== 'string' || id.length === 0) {
    throw new Error(`claim id must be a non-empty string (got ${JSON.stringify(id)})`);
  }
  return id;
}

// ---------------------------------------------------------------------------
// Snapshot helpers — callers only ever see deep-frozen clones, so they cannot
// mutate a rung behind promote()'s back.
// ---------------------------------------------------------------------------

function deepFreeze(obj) {
  if (obj && typeof obj === 'object' && !Object.isFrozen(obj)) {
    Object.freeze(obj);
    for (const v of Object.values(obj)) deepFreeze(v);
  }
  return obj;
}

function snapshot(record) {
  return deepFreeze(structuredClone(record));
}

// ---------------------------------------------------------------------------
// The ledger.
// ---------------------------------------------------------------------------

export class ClaimLedger {
  // Internal records are private so the rung can ONLY move through promote().
  #claims = new Map();
  // A per-ledger monotone sequence number — deterministic event ordering without wall-clock.
  #seq = 0;

  #nextSeq() {
    this.#seq += 1;
    return this.#seq;
  }

  /**
   * Assert a typed claim into the ledger.
   *
   *   - NEW claim: created at `rung` (default FLOOR_RUNG = UNVERIFIED). assert() may admit a
   *     claim only AT OR BELOW the floor (REFUTED or UNVERIFIED); requesting any stronger rung
   *     throws — raising a rung is promote()'s sole responsibility.
   *   - EXISTING claim (re-assertion): STICKY. The rung is held unchanged (no flip), regardless
   *     of any `rung` passed. The `statement`/`meta` fields may be refreshed; a conflicting
   *     `type` throws (claim identity is fixed). A 're-assert' event is appended for audit.
   *
   * @param {{id:string, type:string, statement?:string, rung?:string, meta?:object}} claim
   * @returns {object} a deep-frozen snapshot of the (possibly newly created) claim record.
   */
  assert(claim) {
    if (!claim || typeof claim !== 'object') {
      throw new Error('assert() requires a claim object {id, type, ...}');
    }
    const id = assertId(claim.id);
    const existing = this.#claims.get(id);

    if (existing) {
      // STICKY re-assertion: never touch the rung/belief.
      if (claim.type !== undefined && claim.type !== existing.type) {
        throw new Error(
          `re-assert of "${id}" changes its type ${JSON.stringify(existing.type)} -> ${JSON.stringify(claim.type)}; claim identity is fixed`,
        );
      }
      if (typeof claim.statement === 'string') existing.statement = claim.statement;
      if (claim.meta !== undefined) existing.meta = structuredClone(claim.meta);
      const seq = this.#nextSeq();
      existing.updated_seq = seq;
      existing.history.push({
        seq,
        event: 're-assert',
        rung: existing.rung,
        belief: existing.belief,
        held: true,
      });
      return snapshot(existing);
    }

    // NEW claim.
    const type = assertClaimType(claim.type);
    const rung = claim.rung === undefined ? FLOOR_RUNG : assertRung(claim.rung, 'initial rung');
    if (rungRank(rung) > rungRank(FLOOR_RUNG)) {
      throw new Error(
        `assert() cannot admit "${id}" at ${rung}: new claims enter at or below ${FLOOR_RUNG}. Use promote() to raise a rung.`,
      );
    }
    const seq = this.#nextSeq();
    const belief = beliefForRung(rung);
    const record = {
      id,
      type,
      statement: typeof claim.statement === 'string' ? claim.statement : '',
      rung,
      belief,
      meta: claim.meta !== undefined ? structuredClone(claim.meta) : {},
      created_seq: seq,
      updated_seq: seq,
      history: [{ seq, event: 'assert', rung, belief, held: false }],
    };
    this.#claims.set(id, record);
    return snapshot(record);
  }

  /**
   * promote() — the SOLE rung-RAISER.
   *
   * Raises an existing claim to a STRICTLY HIGHER rung and re-projects its belief tag,
   * recording the verifier-family stamp + reason for the lift. A promotion that is not
   * strictly upward (equal or lower target) throws — promote() can never hold or demote, so
   * it is unambiguously the only way a rung goes up.
   *
   * NOTE: this wave does not gate promote()-to-OBSERVED on an adjudication artifact — that is
   * Wave 4 (which makes promote()-to-VERIFIED hard-fault to ABSTAIN absent a fresh artifact).
   *
   * @param {string} id
   * @param {string} toRung   the (strictly higher) target rung.
   * @param {{family?:string, reason?:string, by?:string, meta?:object}} [opts]
   * @returns {object} a deep-frozen snapshot of the promoted claim record.
   */
  promote(id, toRung, opts = {}) {
    assertId(id);
    const record = this.#claims.get(id);
    if (!record) {
      throw new Error(`promote(): no claim "${id}" in the ledger`);
    }
    assertRung(toRung, 'target rung');
    const cmp = compareRungs(toRung, record.rung);
    if (cmp <= 0) {
      throw new Error(
        `promote() must raise the rung: target ${toRung} is not above current ${record.rung} for "${id}" ` +
          `(promote() is the sole rung-raiser; it cannot hold or demote)`,
      );
    }

    const fromRung = record.rung;
    const seq = this.#nextSeq();
    record.rung = toRung;
    record.belief = beliefForRung(toRung);
    record.updated_seq = seq;
    record.history.push({
      seq,
      event: 'promote',
      from: fromRung,
      rung: toRung,
      belief: record.belief,
      family: typeof opts.family === 'string' ? opts.family : null,
      reason: typeof opts.reason === 'string' ? opts.reason : null,
      by: typeof opts.by === 'string' ? opts.by : null,
    });
    return snapshot(record);
  }

  /** Whether a claim id is recorded. */
  has(id) {
    return this.#claims.has(assertId(id));
  }

  /** A deep-frozen snapshot of a claim record, or undefined if absent. */
  get(id) {
    const record = this.#claims.get(assertId(id));
    return record ? snapshot(record) : undefined;
  }

  /** The current rung of a claim. Throws if the claim is absent. */
  rungOf(id) {
    const record = this.#claims.get(assertId(id));
    if (!record) throw new Error(`rungOf(): no claim "${id}" in the ledger`);
    return record.rung;
  }

  /** The current (projected) belief tag of a claim. Throws if the claim is absent. */
  beliefOf(id) {
    const record = this.#claims.get(assertId(id));
    if (!record) throw new Error(`beliefOf(): no claim "${id}" in the ledger`);
    return record.belief;
  }

  /** Number of claims recorded. */
  get size() {
    return this.#claims.size;
  }

  /** All recorded claim ids (insertion order). */
  ids() {
    return [...this.#claims.keys()];
  }

  /** Deep-frozen snapshots of every claim (insertion order). */
  all() {
    return [...this.#claims.values()].map(snapshot);
  }
}
