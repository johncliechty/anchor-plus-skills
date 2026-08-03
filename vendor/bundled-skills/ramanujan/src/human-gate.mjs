// Wave 5 — F5: human GATE -> the GROUNDED rung (attested, >=OBSERVED-class).
//
// LIFT A FORMALIZATION TO **GROUNDED** — the TOP rung, strictly above OBSERVED — only when a human is the
// convergence authority FOR that formalization. The human is NOT a verifier of last resort that can wish a
// claim true: GROUNDED sits ON TOP of a HARD tool certification and adds a second, out-of-band gate. Two
// gates, both required, no unguarded window (DESCRIPTION-INC2 §Residuals "GROUNDED rung" + §v2.1 Wave-5):
//
//   (a) A >=OBSERVED-class certification.  The claim must ALREADY have earned OBSERVED from the Lean kernel
//       + bounded SMT faithfulness (lean-certifier.adjudicateObserved). The gate consumes the OBSERVED
//       adjudication RESULT directly — so GROUNDED is structurally downstream of a real tool PASS.
//   (b) An ATTESTED human ASSENT artifact.  A signed assent BOUND to that OBSERVED artifact: signed by an
//       OUT-OF-BAND private key the model side never holds (an Ed25519 signature the gate verifies against
//       a TRUSTED public keyring), single-use (replay-rejected), and bound to THIS claim's OBSERVED
//       lean+z3 artifact hash. This is the SAME trust-root pattern as the adjudication artifacts (the
//       forging capability lives out-of-band) — so Foreman CANNOT stub a no-op assent verifier: a missing
//       / unsigned / wrong-key / wrong-binding / replayed assent never verifies.
//
// THE OVERRIDE LAW (the headline). HUMAN ASSENT CAN NEVER OVERRIDE A TOOL REJECTION. The gate checks the
// tool tier FIRST: if the OBSERVED adjudication did NOT grant OBSERVED (rejected / withheld / flagged),
// then a presented assent is a DETECTED override attempt (FLAG), and an absent assent simply leaves the
// claim where the tool left it (WITHHELD) — a human can NEVER staple a green tag onto a tool-rejected claim.
//
// THE TRUST-ROOT (anti-no-op, §v2.1 Wave-5). The attestation signer holds an OUT-OF-BAND private key
// (AssentSigner — the human's signer; the model side never holds it). The gate is constructed with only
// the PUBLIC keyring (key_id -> public key). Verification is a real Ed25519 `crypto.verify` — fail-CLOSED:
// no keyring / unknown key_id / a signature the trusted key did not produce => the lift is REFUSED. A
// "no-op" assent (no signature, a fabricated signature, or a signature from an untrusted key) cannot pass.
//
// REPLAY REJECTION (P9-F). The assent carries a single-use nonce; the gate CONSUMES it through an injected
// single-use replay guard. A re-presented assent (same nonce) is rejected. An un-exercised replay guard
// WITHHOLDS the lift (a stubbed single-use check is no check) — the same fail-closed posture as the canary.
//
// ROUTER-AGNOSTIC BY DESIGN. This module imports ONLY the A1 ledger constants + the OBSERVED-status alphabet
// from lean-certifier — never verify-router — so there is no import cycle. `verify-router` imports THIS
// module and wires the adjudication + lift behind its async `routeHumanGate` seam. Pure node built-ins
// (node:crypto Ed25519) + the project's own modules. Runs under `node --test test/`.

import crypto from 'node:crypto';

import { RUNG, compareRungs } from './claim-ledger.mjs';
import { OBSERVED_STATUS } from './lean-certifier.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** A 64-char lowercase hex (a SHA-256 digest). */
export const HEX64 = /^[0-9a-f]{64}$/;

/** A lowercase-hex string (an Ed25519 signature, rendered hex). */
const HEXSTR = /^[0-9a-f]+$/;

/** The human-attested apex rung (the locked TOP rung, strictly above OBSERVED). */
export const GROUNDED_RUNG = RUNG.GROUNDED;

/** The signing algorithm for the assent attestation (asymmetric — the model side never holds the key). */
export const ASSENT_ALGORITHM = 'ed25519';

/** The positive assent token an assent artifact must carry to lift (anything else is not a lift). */
export const ASSENT_TOKEN = 'ASSENT';

/** The GROUNDED family-of-record: the two tool certifiers + the out-of-band human attestation. */
export const GROUNDED_FAMILY = 'lean-kernel+z3-bounded-faithfulness+human-attestation';

/** The EXACT field set of the attested assent artifact. */
export const ASSENT_ARTIFACT_FIELDS = Object.freeze([
  'claim_id',
  'observed_binding',
  'assent',
  'attestor',
  'key_id',
  'nonce',
  'signature',
]);

/** The fields covered by the signature (everything except the signature itself). */
export const ASSENT_PAYLOAD_FIELDS = Object.freeze(['claim_id', 'observed_binding', 'assent', 'attestor', 'key_id', 'nonce']);

/** The GROUNDED adjudication outcome alphabet. */
export const GROUNDED_STATUS = Object.freeze({
  GROUNDED: 'GROUNDED', // PASS: a >=OBSERVED tool artifact AND a valid attested assent bound to it -> lift granted
  WITHHELD: 'WITHHELD', // fail-safe: no OBSERVED yet, or no/non-positive assent, or an un-exercised replay guard
  FLAG: 'FLAG', // a DETECTED defect: forged / replayed / cross-claim / wrong-binding assent, or an override attempt
});

/** A typed error so a gate wiring/usage bug (or a hard-fault) is distinguishable. */
export class HumanGateError extends Error {
  constructor(message, extra = {}) {
    super(message);
    this.name = 'HumanGateError';
    Object.assign(this, extra);
  }
}

// ---------------------------------------------------------------------------
// Canonical hashing + the OBSERVED binding.
// ---------------------------------------------------------------------------

const sha256Hex = (text) => crypto.createHash('sha256').update(String(text), 'utf8').digest('hex');

/** Deterministic, sorted-key JSON for hashing/signing (so the binding/signature are reproducible). */
function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value === undefined ? null : value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(',')}}`;
}

/**
 * The binding hash that ties an assent to ONE specific OBSERVED certification: SHA-256 of the canonical
 * OBSERVED `artifact_ref` (the lean+z3 artifact the OBSERVED lift was bound to — statement_hash,
 * lean_version, olean_hash, smt2_hash, z3_version, differential_result, battery provenance, ...). An
 * assent minted against a DIFFERENT claim's OBSERVED artifact re-hashes to a different binding => caught.
 */
export function observedBindingHash(artifactRef) {
  if (!artifactRef || typeof artifactRef !== 'object' || Array.isArray(artifactRef)) {
    throw new HumanGateError('observedBindingHash requires the OBSERVED adjudication artifact_ref object');
  }
  return sha256Hex(canonicalJson(artifactRef));
}

/** The canonical bytes the attestation signs/verifies (the assent payload minus the signature). */
function canonicalAssentPayload(a) {
  const subset = {};
  for (const f of ASSENT_PAYLOAD_FIELDS) subset[f] = a[f];
  return canonicalJson(subset);
}

// ---------------------------------------------------------------------------
// Keys + the out-of-band signer (the trust-root: the model side never holds the private key).
// ---------------------------------------------------------------------------

/** Generate an Ed25519 assent key pair. The PRIVATE key stays out-of-band (with the human signer). */
export function generateAssentKeyPair() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync(ASSENT_ALGORITHM);
  return { publicKey, privateKey };
}

/**
 * The out-of-band assent SIGNER (the human's attestor). Holds the PRIVATE key the model side never sees;
 * the gate holds only the matching PUBLIC key. sign() mints an assent artifact BOUND to a given OBSERVED
 * tool result — it refuses to mint without an OBSERVED result, so an assent can never even be produced for
 * a non-certified claim (defence-in-depth on top of the gate's override law).
 */
export class AssentSigner {
  #privateKey;
  #keyId;
  #attestor;

  /** @param {{ privateKey:crypto.KeyObject, keyId:string, attestor:string }} o */
  constructor({ privateKey, keyId, attestor } = {}) {
    if (!privateKey) throw new HumanGateError('AssentSigner requires the out-of-band private key (the model side never holds it)');
    if (typeof keyId !== 'string' || keyId.length === 0) throw new HumanGateError('AssentSigner requires a non-empty keyId');
    if (typeof attestor !== 'string' || attestor.length === 0) throw new HumanGateError('AssentSigner requires a non-empty attestor identity');
    this.#privateKey = privateKey;
    this.#keyId = keyId;
    this.#attestor = attestor;
  }

  get keyId() {
    return this.#keyId;
  }

  get attestor() {
    return this.#attestor;
  }

  /**
   * Sign an assent for `claim`, BOUND to `observed` (a >=OBSERVED adjudication result), with a unique
   * single-use `nonce`. Returns the frozen ASSENT_ARTIFACT_FIELDS artifact. `assent` defaults to the
   * positive ASSENT_TOKEN. Throws unless `observed` is a genuine OBSERVED result (an assent cannot be
   * minted for a claim the tool tier did not certify).
   */
  sign({ claim, observed, nonce, assent = ASSENT_TOKEN } = {}) {
    if (!claim || typeof claim.id !== 'string') throw new HumanGateError('AssentSigner.sign requires the claim being attested (with id)');
    if (!observed || observed.status !== OBSERVED_STATUS.OBSERVED || !observed.artifact_ref) {
      throw new HumanGateError('AssentSigner.sign requires an OBSERVED tool result to bind to — human assent never overrides a tool rejection');
    }
    if (typeof nonce !== 'string' || nonce.length === 0) throw new HumanGateError('AssentSigner.sign requires a non-empty single-use nonce');
    const base = {
      claim_id: claim.id,
      observed_binding: observedBindingHash(observed.artifact_ref),
      assent,
      attestor: this.#attestor,
      key_id: this.#keyId,
      nonce,
    };
    const signature = crypto.sign(null, Buffer.from(canonicalAssentPayload(base), 'utf8'), this.#privateKey).toString('hex');
    return Object.freeze({ ...base, signature });
  }
}

// ---------------------------------------------------------------------------
// The single-use replay guard (P9-F: a re-presented assent is rejected).
// ---------------------------------------------------------------------------

/**
 * An in-memory single-use store for assent nonces. consume() marks a nonce SPENT and returns true the
 * FIRST time; a re-presented nonce returns false. (A durable adapter — the inherited Phase-0 substrate,
 * as the adjudication nonce store uses — can wrap the same `consume(nonce)` interface for cross-restart
 * single-use; the gate only requires the interface, not this concrete class.)
 */
export class AssentReplayGuard {
  #spent = new Set();

  isSpent(nonce) {
    return this.#spent.has(nonce);
  }

  /** Single-use consume: true the first time a nonce is seen, false on any re-presentation. */
  consume(nonce) {
    if (typeof nonce !== 'string' || nonce.length === 0) return false;
    if (this.#spent.has(nonce)) return false;
    this.#spent.add(nonce);
    return true;
  }
}

// ---------------------------------------------------------------------------
// Assent artifact validation + keyring / signature helpers.
// ---------------------------------------------------------------------------

/** Shape-check an assent artifact. STRUCTURAL only (it does not verify the signature — that is the gate's job). */
export function validateAssentArtifact(artifact) {
  const failures = [];
  if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) {
    return { ok: false, failures: ['assent artifact is not an object'] };
  }
  for (const f of ASSENT_ARTIFACT_FIELDS) if (!(f in artifact)) failures.push(`missing field: ${f}`);
  for (const k of Object.keys(artifact)) if (!ASSENT_ARTIFACT_FIELDS.includes(k)) failures.push(`unexpected field: ${k}`);
  if (typeof artifact.claim_id !== 'string' || artifact.claim_id.length === 0) failures.push('claim_id must be a non-empty string');
  if (typeof artifact.observed_binding !== 'string' || !HEX64.test(artifact.observed_binding)) failures.push('observed_binding must be a 64-hex SHA-256');
  if (typeof artifact.assent !== 'string' || artifact.assent.length === 0) failures.push('assent must be a non-empty string');
  if (typeof artifact.attestor !== 'string' || artifact.attestor.length === 0) failures.push('attestor must be a non-empty string');
  if (typeof artifact.key_id !== 'string' || artifact.key_id.length === 0) failures.push('key_id must be a non-empty string');
  if (typeof artifact.nonce !== 'string' || artifact.nonce.length === 0) failures.push('nonce must be a non-empty string');
  if (typeof artifact.signature !== 'string' || !HEXSTR.test(artifact.signature)) failures.push('signature must be a non-empty hex string');
  return { ok: failures.length === 0, failures };
}

/** Resolve a TRUSTED public key by key_id from the keyring (a function, a Map, or a plain object). null if absent. */
function resolvePublicKey(keyring, keyId) {
  if (!keyring || typeof keyId !== 'string' || keyId.length === 0) return null;
  if (typeof keyring === 'function') return keyring(keyId) || null;
  if (keyring instanceof Map) return keyring.get(keyId) || null;
  if (typeof keyring === 'object') return keyring[keyId] || null;
  return null;
}

/** Verify the Ed25519 attestation over the canonical assent payload. Total: any error => false (fail-closed). */
function verifyAssentSignature(artifact, publicKey) {
  try {
    return crypto.verify(null, Buffer.from(canonicalAssentPayload(artifact), 'utf8'), publicKey, Buffer.from(artifact.signature, 'hex'));
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// The GROUNDED adjudication (override law + binding + signature + single-use).
// ---------------------------------------------------------------------------

const grnWithheld = (reason, extra = {}) => Object.freeze({ status: GROUNDED_STATUS.WITHHELD, ok: false, flagged: false, reason, ...extra });
const grnFlag = (reason, extra = {}) => Object.freeze({ status: GROUNDED_STATUS.FLAG, ok: false, flagged: true, reason, ...extra });

/**
 * Adjudicate the GROUNDED lift for `claim`. Returns a frozen result whose `status` is one of GROUNDED_STATUS:
 *   GROUNDED — a >=OBSERVED-class tool result AND a valid attested assent bound to it (signature verifies
 *              against the trusted keyring; binding matches THIS claim's OBSERVED artifact; nonce consumed).
 *   WITHHELD — fail-safe (NOT a defect): the tool tier has not granted OBSERVED and no assent was presented;
 *              OR OBSERVED is granted but no/non-positive assent (the claim stays OBSERVED); OR the replay
 *              guard was not exercised (an un-exercised single-use check is treated as stubbed).
 *   FLAG     — a DETECTED defect: an override attempt (an assent presented on a non-OBSERVED tool result —
 *              human assent NEVER overrides a tool rejection), a forged signature, a wrong/untrusted key,
 *              a cross-claim / wrong-binding assent, a replayed assent, or a malformed assent artifact.
 *
 * @param {{ claim:object, observed:object, assent?:object, keyring?:Function|Map|object, replayGuard?:{consume:Function} }} o
 *   observed     — the lean-certifier OBSERVED adjudication RESULT (status + artifact_ref). The gate sits
 *                  ON this real tool result; it never re-derives or trusts a bare "is OBSERVED" boolean.
 *   assent       — the attested assent artifact (AssentSigner.sign output), or null/undefined for none.
 *   keyring      — the TRUSTED public keyring (key_id -> public key). The model side holds only public keys.
 *   replayGuard  — a single-use store with consume(nonce)->boolean (AssentReplayGuard or a durable adapter).
 */
export function adjudicateGrounded({ claim, observed, assent, keyring, replayGuard } = {}) {
  if (!claim || typeof claim.id !== 'string') {
    throw new HumanGateError('adjudicateGrounded requires the claim being attested (with id)');
  }
  const toolObserved = Boolean(observed && observed.status === OBSERVED_STATUS.OBSERVED && observed.artifact_ref);

  // (1) THE OVERRIDE LAW. Human assent can NEVER override a tool rejection/withhold. If the tool tier did
  //     NOT certify OBSERVED, a presented assent is a DETECTED override attempt (FLAG); an absent assent
  //     simply leaves the claim where the tool left it (WITHHELD).
  if (!toolObserved) {
    const toolStatus = observed && observed.status ? observed.status : 'none';
    if (assent != null) {
      return grnFlag(
        `human assent cannot lift a claim the tool tier did not certify OBSERVED (tool status: ${toolStatus}) — ` +
          'a human attestation NEVER overrides a tool rejection/withhold',
      );
    }
    return grnWithheld(
      `GROUNDED requires a >=OBSERVED-class Lean+z3 certification first (tool status: ${toolStatus}) — the claim is not yet OBSERVED`,
    );
  }

  // The tool tier granted OBSERVED. GROUNDED additionally requires a valid attested human assent.
  // (2) Absent assent => stays OBSERVED (a fail-safe WITHHELD, not a defect).
  if (assent == null) {
    return grnWithheld('no attested assent supplied — the claim stays OBSERVED (GROUNDED needs a human attestation on top of the OBSERVED tool artifact)');
  }

  // (3) Structural validation of the assent artifact.
  const v = validateAssentArtifact(assent);
  if (!v.ok) return grnFlag(`malformed assent artifact: ${v.failures.join('; ')}`);

  // (4) The assent must be POSITIVE. A recorded non-assent (e.g. a dissent) is not a lift — stays OBSERVED.
  if (assent.assent !== ASSENT_TOKEN) {
    return grnWithheld(`assent artifact does not carry a positive ${ASSENT_TOKEN} (recorded ${JSON.stringify(assent.assent)}) — the claim stays OBSERVED`);
  }

  // (5) BINDING (anti-replay / anti-cross-claim). The assent must name THIS claim AND bind to THIS
  //     OBSERVED artifact (recompute the binding from the tool result's artifact_ref).
  if (assent.claim_id !== claim.id) {
    return grnFlag(`assent artifact is bound to claim ${JSON.stringify(assent.claim_id)}, not ${JSON.stringify(claim.id)} (cross-claim / replay)`);
  }
  const expectedBinding = observedBindingHash(observed.artifact_ref);
  if (assent.observed_binding !== expectedBinding) {
    return grnFlag(
      "assent artifact observed_binding does not match THIS claim's OBSERVED lean+z3 artifact " +
        '(replayed / bound to a different certification)',
    );
  }

  // (6) SIGNATURE (the trust-root). Verify the Ed25519 attestation against the TRUSTED public key named by
  //     key_id. FAIL-CLOSED: no keyring / unknown key_id / a signature the trusted key did not produce =>
  //     REFUSED. A no-op assent verifier cannot be stubbed (the out-of-band signer never produced it).
  const publicKey = resolvePublicKey(keyring, assent.key_id);
  if (!publicKey) {
    return grnFlag(
      `assent attestor key_id ${JSON.stringify(assent.key_id)} is not in the trusted keyring ` +
        '(untrusted / absent attestation key — fail-closed)',
    );
  }
  if (!verifyAssentSignature(assent, publicKey)) {
    return grnFlag(
      'forged assent artifact: the attestation signature does not verify against the trusted attestor key ' +
        '(the out-of-band signer never produced it)',
    );
  }

  // (7) SINGLE-USE / replay rejection. Consume the assent nonce; a re-presented assent fails. FAIL-CLOSED:
  //     an un-exercised replay guard WITHHOLDS (a stubbed single-use check is no check).
  if (!replayGuard || typeof replayGuard.consume !== 'function') {
    return grnWithheld(
      'assent replay guard not exercised (no single-use store supplied) — GROUNDED withheld ' +
        '(an un-exercised single-use check is treated as stubbed)',
    );
  }
  if (!replayGuard.consume(assent.nonce, claim.id)) {
    return grnFlag('replayed assent artifact: the assent nonce was already consumed (single-use) — a re-presented attestation is rejected');
  }

  // BOTH gates passed: a >=OBSERVED tool certification AND a valid, bound, single-use human attestation.
  return Object.freeze({
    status: GROUNDED_STATUS.GROUNDED,
    ok: true,
    flagged: false,
    family: GROUNDED_FAMILY,
    reason:
      `GROUNDED: a >=OBSERVED-class Lean+z3 certification AND a valid attested human assent bound to it ` +
      `(attestor ${assent.attestor}, key ${assent.key_id}; Ed25519 signature verified; single-use nonce consumed)`,
    artifact_ref: observed.artifact_ref,
    attestation: Object.freeze({
      attestor: assent.attestor,
      key_id: assent.key_id,
      observed_binding: assent.observed_binding,
      nonce: assent.nonce,
    }),
  });
}

// ---------------------------------------------------------------------------
// The lift — the SOLE promote() to GROUNDED (structurally unreachable without BOTH gates).
// ---------------------------------------------------------------------------

/**
 * Lift `claim` to GROUNDED, bound to a GROUNDED adjudication result. HARD-FAULTS (throws HumanGateError) on
 * anything other than a GROUNDED result — so the GROUNDED rung is STRUCTURALLY UNREACHABLE without BOTH a
 * >=OBSERVED-class tool artifact AND a valid attested assent bound to it. promote() is strictly-upward only;
 * if the claim already sits at GROUNDED the lift is a HOLD (idempotent — never lowers a stronger rung).
 */
export function liftToGrounded(ledger, claim, result) {
  if (!ledger || typeof ledger.promote !== 'function' || typeof ledger.rungOf !== 'function') {
    throw new HumanGateError('liftToGrounded requires an A1 ClaimLedger');
  }
  if (!result || result.status !== GROUNDED_STATUS.GROUNDED) {
    throw new HumanGateError(
      'liftToGrounded HARD-FAULT: GROUNDED is structurally unreachable without a GROUNDED adjudication result ' +
        '(a >=OBSERVED-class tool artifact AND a valid attested assent bound to it)',
      { status: result && result.status },
    );
  }
  const id = claim.id;
  if (compareRungs(GROUNDED_RUNG, ledger.rungOf(id)) <= 0) {
    return ledger.get(id); // already at GROUNDED — HOLD (sticky), never lower it.
  }
  return ledger.promote(id, GROUNDED_RUNG, {
    family: result.family || GROUNDED_FAMILY,
    reason: result.reason,
    by: 'human-gate',
  });
}
