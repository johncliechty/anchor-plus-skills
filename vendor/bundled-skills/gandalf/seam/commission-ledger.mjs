// Gandalf advisor — the unforgeable orchestrator-minted commission-id LEDGER (Wave W2a).
//
// THE MECHANISM the anti-laundering honor-system scaffold (seam/anti-laundering.mjs) was waiting
// for. In Increment 1 `resolveCommissionId` could only ever return UNRESOLVABLE_NO_LEDGER — there
// was no oracle of authenticity, so the content-binding canaries B2' (a forged / unresolvable
// commission-id FAILS) and B7' (a commissioned result is BOUND to the id that produced it) were
// stamped BLOCKED-this-cycle and NON-GATING. This module is the real ledger: an orchestrator-minted,
// cryptographically-bound commission-id that a random / forged / tampered id can NEVER satisfy.
//
// Modeled on ramanujan's Wave-4/Wave-9 artifact mint (src/adjudication.mjs `computeNonce` /
// `mintArtifact` / `consumeArtifact`): the id is bound to its CONTENT by a keyed hash, and resolve
// re-derives that binding from the presented bytes to confirm authenticity — a forged or cross-claim
// id fails the re-derivation. Two independent guarantees make an id unforgeable:
//   1. CONTENT-BINDING (HMAC). The id embeds the canonical tuple and an HMAC-SHA256 signature over it
//      keyed by a per-run secret. Tamper any field (a different result_digest) and the signature no
//      longer verifies. Fabricate a random id and it carries no valid signature. Neither can be
//      produced without the mint's secret.
//   2. MINTED-THIS-RUN (ledger membership). resolve additionally requires the id to have actually
//      been minted by THIS ledger this run — an id from a different run/secret is rejected even if it
//      were otherwise well-formed. This is the durable "orchestrator-minted, resolvable" property.
//
// Stdlib-only (node:crypto), deterministic-testable: within one process, mint->resolve round-trips
// exactly; a forged/random/tampered/cross-ledger id deterministically resolves to null.
//
// Public surface:
//   COMMISSION_ID_PREFIX               — the versioned id prefix ('gcl1')
//   canonicalCommissionTuple(tuple)    — the exact bytes the signature binds (fixed key order)
//   createCommissionLedger({secret?})  — an isolated ledger { mintCommission, resolveCommission, ... }
//   mintCommission(tuple)              — mint on the module-default per-run ledger
//   resolveCommission(id)              — resolve on the module-default per-run ledger
//   resetLedger()                      — clear + rotate the module-default ledger for cross-run reuse

import crypto from 'node:crypto';

/** The versioned commission-id prefix (gandalf-commission-ledger v1). */
export const COMMISSION_ID_PREFIX = 'gcl1';

// The segment delimiter. A literal '.' is absent from the base64url alphabet (A-Za-z0-9-_), from the
// lowercase-hex signature (0-9a-f), and from the prefix 'gcl1', so an id splits back into its three
// parts unambiguously.
const SEP = '.';

function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim() !== '';
}

/** The canonical, stable serialization of the bound tuple (FIXED key order) — the exact bytes the
 *  HMAC signs, so mint and resolve agree byte-for-byte regardless of caller key order. Pure. */
export function canonicalCommissionTuple({ drafter_family, refuter_family, result_digest } = {}) {
  return JSON.stringify({
    drafter_family: String(drafter_family),
    refuter_family: String(refuter_family),
    result_digest: String(result_digest),
  });
}

function isWellFormedTuple(t) {
  return (
    t !== null &&
    typeof t === 'object' &&
    !Array.isArray(t) &&
    isNonEmptyString(t.drafter_family) &&
    isNonEmptyString(t.refuter_family) &&
    isNonEmptyString(t.result_digest)
  );
}

function b64urlEncode(str) {
  return Buffer.from(str, 'utf8').toString('base64url');
}
function b64urlDecode(str) {
  return Buffer.from(str, 'base64url').toString('utf8');
}

function hmacHex(secret, msg) {
  return crypto.createHmac('sha256', secret).update(msg, 'utf8').digest('hex');
}

/** Constant-time equality of two equal-length hex strings; false (never throws) on any mismatch of
 *  type or length so a forged signature cannot leak timing OR crash resolve. */
function timingSafeHexEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length || a.length === 0) {
    return false;
  }
  try {
    return crypto.timingSafeEqual(Buffer.from(a, 'utf8'), Buffer.from(b, 'utf8'));
  } catch {
    return false;
  }
}

/**
 * Create an ISOLATED commission ledger backed by a per-run secret. Each ledger mints ids only its own
 * `resolveCommission` will honor (content-binding secret + minted-this-run membership). Pass an
 * explicit `secret` for a reproducible fixture; omit it for a fresh random per-run secret.
 *
 * @param {{secret?: string|Buffer}} [opts]
 * @returns {{ mintCommission: Function, resolveCommission: Function, isMinted: Function, size: Function }}
 */
export function createCommissionLedger({ secret } = {}) {
  let runSecret =
    secret != null
      ? Buffer.from(secret instanceof Buffer ? secret : String(secret), 'utf8')
      : crypto.randomBytes(32);
  const issued = new Set(); // ids minted by THIS ledger this run

  /**
   * Mint a commission-id CRYPTOGRAPHICALLY BOUND to (drafter_family, refuter_family, result_digest).
   * The id = `gcl1.base64url(canonicalTuple).HMAC-SHA256(secret, canonicalTuple)` — it cannot be
   * fabricated for a tuple without the mint's secret. Throws on a malformed tuple (never mints a
   * partial/forgeable id).
   *
   * @param {{drafter_family:string, refuter_family:string, result_digest:string}} tuple
   * @returns {string} the minted commission-id
   */
  function mintCommission({ drafter_family, refuter_family, result_digest } = {}) {
    const tuple = { drafter_family, refuter_family, result_digest };
    if (!isWellFormedTuple(tuple)) {
      throw new Error(
        'commission-ledger: mintCommission requires non-empty drafter_family, refuter_family, and result_digest strings'
      );
    }
    const payload = canonicalCommissionTuple(tuple);
    const mac = hmacHex(runSecret, payload);
    const id = `${COMMISSION_ID_PREFIX}${SEP}${b64urlEncode(payload)}${SEP}${mac}`;
    issued.add(id);
    return id;
  }

  /**
   * Resolve a commission-id to the tuple it is bound to, or `null` for any id this ledger did not
   * authentically mint. Returns null when the id is: not a string / wrong prefix / malformed; carries a
   * signature that does not re-derive from its embedded tuple (a forged or TAMPERED id — e.g. a swapped
   * result_digest); or was not minted by THIS ledger this run (a random or cross-run/cross-secret id).
   *
   * @param {string} id
   * @returns {{drafter_family:string, refuter_family:string, result_digest:string} | null}
   */
  function resolveCommission(id) {
    if (typeof id !== 'string' || id.length === 0) return null;
    const parts = id.split(SEP);
    if (parts.length !== 3 || parts[0] !== COMMISSION_ID_PREFIX) return null;
    let payload;
    try {
      payload = b64urlDecode(parts[1]);
    } catch {
      return null;
    }
    // (1) CONTENT-BINDING: re-derive the HMAC over the presented tuple bytes. A forged id or a tampered
    //     tuple (any field changed) yields a different signature and fails here.
    const expectedMac = hmacHex(runSecret, payload);
    if (!timingSafeHexEqual(expectedMac, parts[2])) return null;
    // (2) MINTED-THIS-RUN: it must have actually been minted by THIS ledger (orchestrator-minted,
    //     resolvable). An id from another run/secret is rejected even if otherwise well-formed.
    if (!issued.has(id)) return null;
    let tuple;
    try {
      tuple = JSON.parse(payload);
    } catch {
      return null;
    }
    if (!isWellFormedTuple(tuple)) return null;
    return {
      drafter_family: tuple.drafter_family,
      refuter_family: tuple.refuter_family,
      result_digest: tuple.result_digest,
    };
  }

  /** Predicate: was `id` minted by THIS ledger this run? Pure; never throws. */
  function isMinted(id) {
    return typeof id === 'string' && issued.has(id);
  }

  /** The number of ids minted by this ledger this run. */
  function size() {
    return issued.size;
  }

  /** Reset the ledger for reuse across runs: clear the minted-this-run membership AND rotate the
   *  per-run secret. After reset(), every previously-minted id resolves to null (its signature no
   *  longer re-derives under the new secret AND it is no longer in `issued`) — a clean per-run state
   *  with no leak from the prior run. Pure side-effect on this closure; returns nothing. */
  function reset() {
    issued.clear();
    runSecret = crypto.randomBytes(32);
  }

  return { mintCommission, resolveCommission, isMinted, size, reset };
}

// The module-default ledger: a single per-run secret minted once at import (never persisted), so a
// forged id from any other process/run cannot resolve here. Callers that need an isolated/reproducible
// ledger use createCommissionLedger({ secret }).
const _defaultLedger = createCommissionLedger();

/** Mint a commission-id on the module-default per-run ledger. See createCommissionLedger().mintCommission. */
export function mintCommission(tuple) {
  return _defaultLedger.mintCommission(tuple);
}

/** Resolve a commission-id on the module-default per-run ledger. See createCommissionLedger().resolveCommission. */
export function resolveCommission(id) {
  return _defaultLedger.resolveCommission(id);
}

/** Reset the module-default ledger (clear its minted-this-run set + rotate its secret) for any caller
 *  that must REUSE the singleton across runs without leaking a prior run's minted ids. The runtime host
 *  (runtime/seam-pass.applySeamPass) does NOT rely on this — it instantiates a FRESH per-run ledger via
 *  createCommissionLedger() so there is no shared singleton state to leak. See createCommissionLedger().reset. */
export function resetLedger() {
  _defaultLedger.reset();
}
