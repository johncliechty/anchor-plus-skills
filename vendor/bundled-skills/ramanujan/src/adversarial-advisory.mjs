// Wave 18 — In-process adversarial advisory layer (C4).
//
// The DIALOGUE/SOLVE pillars want a skeptical second opinion on a claim BEFORE it is asserted as
// settled — a Gandalf-style outside-view challenge and a researchPrime-style verification-minded
// critique — without leaving the process and without a cross-family certifier (those are the
// out-of-model EMIT path of Wave 13 / the positive arm of Increment-2). This module is that
// IN-PROCESS critic. It runs a single-family, in-process ADVERSARIAL CRITIQUE plus a
// FAITHFULNESS-RESTATEMENT discipline over a claim and records the result as ADVISORY NOTES.
//
// THE ONE LOAD-BEARING INVARIANT (the done-when). An advisory critique writes the NOTES field and can
// NEVER change a rung. This is guaranteed STRUCTURALLY, not by convention: the advisor mutates the
// ledger through the A1 STICKY re-assert (ClaimLedger.assert) ONLY — which merges meta and physically
// HOLDS the rung — and never touches promote() (the sole rung-raiser) or any out-of-model adjudication
// gate. So even a malicious critique that asks for a rung lift (a `rung`/`promote` field) is inert: the
// advisor never reads such a field into a rung decision. A defensive post-check re-reads the rung and
// throws if it somehow moved, documenting the intent.
//
// WHY IN-PROCESS, AND WHY ONLY ADVISORY. The critique is single-family (cross_model:false), so under
// THE HONESTY LAW it earns NO independent-origin credit and cannot corroborate or settle anything —
// propose != adjudicate. Its entire warrant is to ANNOTATE: surface concerns/objections, restate the
// claim faithfully, and flag a restatement divergence. The honest lift (and the cross-family
// corroboration / proof certification) remains the Wave-7 VERIFY router's job via an out-of-model
// artifact; this layer is the abstain-arm annotation that rides alongside it (NS4 faithfulness here is
// the abstain/advisory arm only — its positive, certified arm is Increment-2).
//
//   CRITIQUE  -> a list of { source, severity, message } advisory observations (Gandalf + researchPrime
//                in-process sources). Severity is INFO/CONCERN/OBJECTION — none of them settle.
//   RESTATE   -> the faithfulness-restatement discipline: echo the claim back as a restatement and
//                classify the restatement as RESTATED / DIVERGENCE_FLAGGED / NOT_RESTATED. Single-family
//                and in-process, so a "faithful" outcome is ADVISORY ONLY (never a certification).
//   WRITE     -> merge an `adversarial_advisory` record + append the human-facing strings into the
//                claim's `meta.notes` (THE NOTES FIELD) via a sticky re-assert. Rung untouched.
//
// Pure node built-ins + the project's own A1 ledger. Runs under `node --test test/`.
//
// NOTE (boundary canary, Wave 13): this module deliberately defines NO seam-owned commission symbol
// (commissionResearchPrime / composeSituate / …) — it is the IN-PROCESS critique annotation surface,
// distinct from the Wave-13 commission EMITTERS that compose the inherited Gandalf seam. It dispatches
// nothing and emits no commission envelope; it only writes NOTES.

import { ClaimLedger, RUNG, BELIEF } from './claim-ledger.mjs';

// ---------------------------------------------------------------------------
// Vocabulary (frozen — pinned, not tunable).
// ---------------------------------------------------------------------------

/** The single-family origin marker for every record this layer writes. In-process and single-family,
 *  so it earns no independent-origin credit (cross_model:false) and can never settle a claim. */
export const ADVISORY_FAMILY = 'in-process-adversarial-advisory';

/** The two in-process critique SOURCES this layer runs — a Gandalf-style outside-view challenge and a
 *  researchPrime-style verification-minded critique. Both are advisory; neither dispatches or settles. */
export const ADVISORY_SOURCE = Object.freeze({
  GANDALF: 'gandalf-in-process',
  RESEARCHPRIME: 'researchprime-in-process',
});

/** The advisory severities a critique entry can carry. Ordered weakest -> strongest for readers, but
 *  NONE of them changes a rung — severity is a presentation hint on an advisory note, never a verdict. */
export const CRITIQUE_SEVERITY = Object.freeze({
  INFO: 'info',
  CONCERN: 'concern',
  OBJECTION: 'objection',
});

const SEVERITIES = new Set(Object.values(CRITIQUE_SEVERITY));
const SOURCES = new Set(Object.values(ADVISORY_SOURCE));

/** The faithfulness-restatement outcomes (the NS4 abstain-arm, ADVISORY ONLY).
 *   RESTATED          — a restatement was produced and preserves the claim (advisory; NOT certified).
 *   DIVERGENCE_FLAGGED — a restatement was produced but DIVERGES from the claim (an advisory warning).
 *   NOT_RESTATED      — no usable restatement was produced (the discipline could not run). */
export const FAITHFULNESS = Object.freeze({
  RESTATED: 'restated',
  DIVERGENCE_FLAGGED: 'divergence-flagged',
  NOT_RESTATED: 'not-restated',
});

/** The pinned ADVISORY token-overlap floor for the restatement discipline: a restatement whose
 *  normalized token Jaccard overlap with the original is below this is flagged as a divergence. This is
 *  a heuristic ANNOTATION threshold only — it never gates a rung (faithfulness certification is
 *  Increment-2). */
export const FAITHFULNESS_OVERLAP_THRESHOLD = 0.5;

// ---------------------------------------------------------------------------
// The faithfulness-restatement discipline (pure).
// ---------------------------------------------------------------------------

function normalizeText(s) {
  return typeof s === 'string' ? s.toLowerCase().replace(/\s+/g, ' ').trim() : '';
}

function tokenize(s) {
  const n = normalizeText(s);
  return n === '' ? [] : n.split(/[^a-z0-9]+/).filter((t) => t.length > 0);
}

function jaccard(aTokens, bTokens) {
  const a = new Set(aTokens);
  const b = new Set(bTokens);
  if (a.size === 0 && b.size === 0) return 1;
  let inter = 0;
  for (const t of a) if (b.has(t)) inter += 1;
  const union = a.size + b.size - inter;
  return union === 0 ? 0 : inter / union;
}

/**
 * THE FAITHFULNESS-RESTATEMENT DISCIPLINE (pure, advisory-only). Given the claim's original statement
 * and a candidate restatement, classify the restatement:
 *   - no/empty restatement                       -> NOT_RESTATED
 *   - normalized restatement === normalized claim -> RESTATED (a verbatim echo: trivially faithful)
 *   - token Jaccard overlap >= the pinned floor   -> RESTATED (advisory; NOT a certification)
 *   - overlap below the floor                     -> DIVERGENCE_FLAGGED (an advisory warning)
 *
 * @param {string} originalStatement
 * @param {string|null|undefined} restatement
 * @param {{threshold?:number}} [opts]
 * @returns frozen { outcome, original, restatement, overlap, message }
 */
export function restatementDiscipline(originalStatement, restatement, { threshold = FAITHFULNESS_OVERLAP_THRESHOLD } = {}) {
  const original = typeof originalStatement === 'string' ? originalStatement : '';
  const restated = typeof restatement === 'string' ? restatement : '';

  if (restated.trim() === '') {
    return Object.freeze({
      outcome: FAITHFULNESS.NOT_RESTATED,
      original,
      restatement: null,
      overlap: 0,
      message: 'faithfulness discipline could not run: no restatement was produced (advisory only — never certifies faithfulness)',
    });
  }

  if (normalizeText(original) !== '' && normalizeText(original) === normalizeText(restated)) {
    return Object.freeze({
      outcome: FAITHFULNESS.RESTATED,
      original,
      restatement: restated,
      overlap: 1,
      message: 'restatement is a verbatim echo of the claim (advisory restatement only; single-family — faithfulness NOT certified, Increment-2 for the positive arm)',
    });
  }

  const overlap = jaccard(tokenize(original), tokenize(restated));
  if (overlap >= threshold) {
    return Object.freeze({
      outcome: FAITHFULNESS.RESTATED,
      original,
      restatement: restated,
      overlap,
      message: `restatement preserves the claim (token overlap ${overlap.toFixed(3)} >= ${threshold}); ADVISORY only — single-family in-process restatement does not certify faithfulness (Increment-2)`,
    });
  }

  return Object.freeze({
    outcome: FAITHFULNESS.DIVERGENCE_FLAGGED,
    original,
    restatement: restated,
    overlap,
    message: `restatement DIVERGES from the claim (token overlap ${overlap.toFixed(3)} < ${threshold}) — advisory faithfulness concern; flag only, never changes the rung`,
  });
}

// ---------------------------------------------------------------------------
// Critique normalization.
// ---------------------------------------------------------------------------

/** Normalize one critique entry to a frozen { source, severity, message }. Rejects a missing message.
 *  Any extra fields a caller smuggles in (e.g. a `rung` or `promote` request) are DROPPED here — the
 *  advisor never reads them, so a critique can never carry a rung decision into the ledger. */
function normalizeCritique(raw, index) {
  if (!raw || typeof raw !== 'object') {
    throw new Error(`critique #${index} must be an object { source?, severity?, message } (got ${JSON.stringify(raw)})`);
  }
  if (typeof raw.message !== 'string' || raw.message.trim() === '') {
    throw new Error(`critique #${index} must carry a non-empty message`);
  }
  const source = SOURCES.has(raw.source) ? raw.source : ADVISORY_SOURCE.GANDALF;
  const severity = SEVERITIES.has(raw.severity) ? raw.severity : CRITIQUE_SEVERITY.CONCERN;
  return Object.freeze({ source, severity, message: raw.message });
}

// ---------------------------------------------------------------------------
// The default in-process critic.
// ---------------------------------------------------------------------------

/**
 * The built-in, deterministic in-process critic. Given a claim snapshot it returns a Gandalf-source
 * outside-view critique, a researchPrime-source verification critique keyed on the claim type, and a
 * verbatim faithful RESTATEMENT (the discipline's default candidate). All advisory; settles nothing.
 *
 * @param {object} claim — a claim snapshot ({ id, type, statement, rung, ... }).
 * @returns {{critiques:Array<{source,severity,message}>, restatement:(string|null)}}
 */
export function defaultAdversarialCritic(claim) {
  const critiques = [
    {
      source: ADVISORY_SOURCE.GANDALF,
      severity: CRITIQUE_SEVERITY.CONCERN,
      message:
        'outside-view (in-process): this critique is single-family (cross_model:false), so it earns NO independent-origin credit — advisory only; it cannot corroborate, settle, or route this claim to VERIFIED.',
    },
  ];

  if (claim.type === 'proof-bearing') {
    critiques.push({
      source: ADVISORY_SOURCE.RESEARCHPRIME,
      severity: CRITIQUE_SEVERITY.OBJECTION,
      message:
        'verification critique: a proof-bearing claim has no autonomous verifier in Increment-1; this in-process critique is advisory and cannot lift the rung — an out-of-model certifier (Lean/SMT, Increment-2) is required to settle it.',
    });
  } else if (claim.type === 'conceptual') {
    critiques.push({
      source: ADVISORY_SOURCE.RESEARCHPRIME,
      severity: CRITIQUE_SEVERITY.CONCERN,
      message:
        'verification critique: a conceptual claim cannot be settled by in-process analogy; this critique is advisory and routes nothing — cross-family corroboration (Increment-2) is the certifying arm.',
    });
  } else {
    critiques.push({
      source: ADVISORY_SOURCE.RESEARCHPRIME,
      severity: CRITIQUE_SEVERITY.INFO,
      message:
        'verification critique: a computational claim settles ONLY through the firewall subprocess artifact; this in-process critique mints no artifact and therefore changes nothing — advisory only.',
    });
  }

  // The faithfulness-restatement discipline's default candidate: a verbatim restatement of the claim.
  const restatement = typeof claim.statement === 'string' && claim.statement.trim() !== '' ? claim.statement : null;
  return { critiques, restatement };
}

// ---------------------------------------------------------------------------
// The advisor.
// ---------------------------------------------------------------------------

function isLedgerLike(l) {
  return (
    l &&
    typeof l.assert === 'function' &&
    typeof l.get === 'function' &&
    typeof l.has === 'function' &&
    typeof l.rungOf === 'function'
  );
}

/**
 * The IN-PROCESS adversarial advisor. Bound to an A1 ledger; each critique() runs the in-process
 * critique + faithfulness-restatement discipline over one claim and records the result as ADVISORY
 * NOTES — writing the claim's NOTES field ONLY and HOLDING its rung (structurally — it only ever calls
 * the sticky assert()).
 */
export class AdversarialAdvisor {
  #ledger;
  #critic;

  /**
   * @param {{ledger:ClaimLedger, critic?:Function}} o
   *   ledger — the shared A1 ledger the critiqued claim lives in.
   *   critic — the in-process critic (defaults to defaultAdversarialCritic). Receives a claim snapshot
   *            and returns { critiques, restatement }. Any rung-shaped field it returns is ignored.
   */
  constructor({ ledger, critic = defaultAdversarialCritic } = {}) {
    if (!isLedgerLike(ledger)) {
      throw new Error('AdversarialAdvisor requires an A1 ClaimLedger ({assert, get, has, rungOf})');
    }
    if (typeof critic !== 'function') {
      throw new Error('AdversarialAdvisor critic (when given) must be a function');
    }
    this.#ledger = ledger;
    this.#critic = critic;
  }

  /** The bound ledger. */
  get ledger() {
    return this.#ledger;
  }

  #resolveClaim(claimOrId) {
    if (typeof claimOrId === 'string') {
      if (!this.#ledger.has(claimOrId)) {
        throw new Error(`critique(): no claim "${claimOrId}" in the ledger — assert it first`);
      }
      return this.#ledger.get(claimOrId);
    }
    if (!claimOrId || typeof claimOrId !== 'object' || typeof claimOrId.id !== 'string') {
      throw new Error('critique(): pass an existing claim id, or a spec { id, type, statement? }');
    }
    if (!this.#ledger.has(claimOrId.id)) {
      // Admit a brand-new claim at the floor (UNVERIFIED) so the advisory has something to annotate.
      this.#ledger.assert({ id: claimOrId.id, type: claimOrId.type, statement: claimOrId.statement, meta: claimOrId.meta });
    }
    return this.#ledger.get(claimOrId.id);
  }

  /**
   * Run an in-process adversarial critique + faithfulness-restatement over a claim and write the
   * result as ADVISORY NOTES. The rung is HELD (the C4 invariant) — this method never calls promote().
   *
   * @param {string|{id:string, type?:string, statement?:string}} claimOrId
   * @param {{critiques?:Array, restatement?:string|null, critic?:Function}} [opts]
   *   critiques   — extra critique entries to APPEND to the critic's output ({source?, severity?, message}).
   *   restatement — override the restatement fed to the faithfulness discipline (else the critic's).
   *   critic      — override the bound critic for this call only.
   * @returns frozen result (see below): rung_before/after (equal), the appended notes, the full NOTES
   *   field, and the advisory record. `rung_changed` is ALWAYS false.
   */
  critique(claimOrId, { critiques: extraCritiques = [], restatement, critic } = {}) {
    const claim = this.#resolveClaim(claimOrId);
    const id = claim.id;

    // --- snapshot the rung BEFORE (the thing we must hold) ---
    const rung_before = claim.rung;
    const belief_before = claim.belief;

    // --- run the in-process critic ---
    const runCritic = typeof critic === 'function' ? critic : this.#critic;
    const base = runCritic(claim) || {};
    const baseCritiques = Array.isArray(base.critiques) ? base.critiques : [];
    const allRaw = [...baseCritiques, ...(Array.isArray(extraCritiques) ? extraCritiques : [extraCritiques])];
    const normCritiques = allRaw.map((c, i) => normalizeCritique(c, i));

    // --- the faithfulness-restatement discipline (caller override wins, else the critic's) ---
    const candidateRestatement = restatement !== undefined ? restatement : base.restatement;
    const faithfulness = restatementDiscipline(claim.statement, candidateRestatement);

    // --- assemble the advisory record (single-family, advisory-only, settles nothing) ---
    const advisory = Object.freeze({
      layer: 'C4-adversarial-advisory',
      family: ADVISORY_FAMILY,
      cross_model: false,
      independent_origin: false, // single-family => no independent-origin credit (anti-laundering)
      advisory: true,
      settles: false,
      routes_to_verified: false,
      dispatched: false, // in-process: nothing is dispatched / commissioned out
      can_change_rung: false,
      critiques: Object.freeze(normCritiques),
      faithfulness,
      rung_observed: rung_before, // READ-ONLY: the rung at critique time, never written back as a change
      belief_observed: belief_before,
    });

    // --- the human-facing NOTES strings this critique appends ---
    const added_notes = Object.freeze([
      ...normCritiques.map((c) => `[${c.severity}] (${c.source}) ${c.message}`),
      `[faithfulness:${faithfulness.outcome}] ${faithfulness.message}`,
    ]);

    // --- WRITE: merge into meta.notes (THE NOTES FIELD) + the structured record, via the STICKY
    //     re-assert. assert() merges meta and HOLDS the rung — it physically cannot raise one. ---
    const priorNotes = Array.isArray(claim.meta?.notes) ? claim.meta.notes : [];
    const mergedMeta = {
      ...(claim.meta || {}),
      notes: [...priorNotes, ...added_notes],
      adversarial_advisory: advisory,
    };
    this.#ledger.assert({ id, type: claim.type, meta: mergedMeta });

    // --- snapshot the rung AFTER and HARD-GUARD the invariant (it cannot have moved) ---
    const after = this.#ledger.get(id);
    if (after.rung !== rung_before) {
      throw new Error(
        `C4 invariant violated: advisory critique changed the rung of "${id}" ${rung_before} -> ${after.rung}. ` +
          'The advisory layer must write NOTES only and never change a rung.',
      );
    }

    return Object.freeze({
      claim_id: id,
      rung_before,
      rung_after: after.rung,
      belief_before,
      belief_after: after.belief,
      rung_changed: after.rung !== rung_before, // ALWAYS false (the C4 done-when)
      notes_written: true,
      added_notes,
      notes: Object.freeze([...(after.meta?.notes || [])]),
      advisory,
    });
  }
}

/** Convenience: run one in-process advisory critique over a claim in a bound (or fresh) ledger. */
export function runAdvisoryCritique(claimOrId, { ledger, critic, critiques, restatement } = {}) {
  const l = isLedgerLike(ledger) ? ledger : new ClaimLedger();
  return new AdversarialAdvisor({ ledger: l, critic }).critique(claimOrId, { critiques, restatement });
}

// ---------------------------------------------------------------------------
// THE PINNED FIXTURE — a claim already at a non-floor rung, to prove the rung is HELD across a critique.
// ---------------------------------------------------------------------------

/**
 * Build a fresh ledger holding one claim promoted to a given rung (default CLAIMED — the single-family
 * proof/conceptual ceiling), and run an in-process advisory critique over it. The returned result
 * proves the done-when: NOTES updated, rung HELD. Used by the Wave-18 test and as a self-check.
 *
 * @param {{id?:string, type?:string, statement?:string, atRung?:string}} [o]
 * @returns {{ledger:ClaimLedger, result:object}}
 */
export function runAdvisoryFixture({
  id = 'c4::advisory-fixture',
  type = 'proof-bearing',
  statement = 'a proof-bearing claim carried at CLAIMED that an in-process critique annotates but must not move',
  atRung = RUNG.CLAIMED,
} = {}) {
  const ledger = new ClaimLedger();
  ledger.assert({ id, type, statement });
  if (atRung !== RUNG.UNVERIFIED && atRung !== RUNG.REFUTED) {
    ledger.promote(id, atRung, { family: 'test-setup', reason: 'fixture: place the claim above the floor before critiquing' });
  }
  const result = new AdversarialAdvisor({ ledger }).critique(id);
  return { ledger, result };
}

void BELIEF; // (referenced in docs; belief is a pure projection of the held rung — unchanged here)
