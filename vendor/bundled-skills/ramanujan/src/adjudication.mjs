// Wave 4 — Out-of-model adjudication-artifact substrate (A1.5).
//
// THE HONESTY LAW's autonomous arm: the ONLY way a claim reaches the OBSERVED rung
// (belief VERIFIED) is by presenting a fresh, single-use, claim-bound ADJUDICATION
// ARTIFACT minted by the out-of-model dispatcher — propose != adjudicate. This module is
// the P9 provenance-binding SUBSTRATE that makes that gate real:
//
//   1. THE ARTIFACT CONTRACT.  artifact = { claim_id, domain, nonce, stdout_hash,
//      exit_code, runtime_fingerprint } where runtime_fingerprint = { node_major,
//      canonicalization_version }. validateArtifact() shape-checks it; canonicalStdoutHash()
//      is the out-of-band RE-HASH primitive (SHA-256 of canonical, sorted-key, exact-number
//      stdout) the Wave-6/Wave-9 canary re-executes against. (Wave 4 does NOT spawn the
//      firewall subprocess — that, and the positive re-execution path, are Wave 9. Here the
//      substrate is generator-agnostic: the caller supplies the stdout_hash a real subprocess
//      will later produce.)
//
//   2. THE DURABLE SINGLE-USE NONCE.  nonce = SHA-256(claim_id ++ domain ++ monotone-counter).
//      The counter is DURABLE + monotone across restarts, persisted to the INHERITED Phase-0
//      durability substrate (foreman-lib's atomic write-tmp+fsync+rename / validating read) —
//      reuse, NO new store (P9). A nonce is usable iff it is durably recorded as ISSUED and
//      not yet SPENT and its (claim_id,domain,counter) re-hash matches. consume() is the
//      single-use gate: it marks the nonce SPENT (durably) so any re-presentation — same-claim,
//      cross-claim, or across-restart — is rejected.
//
//      WRITE-ORDERING (the crash-safety invariant). mint() builds the new state, then the
//      DURABLE FLUSH is ordered BEFORE the nonce is published in memory OR returned to the
//      caller. So a process death AFTER the nonce is computed but BEFORE the flush leaves NO
//      usable replayable nonce on restart: the issued-record is the validity record, and it
//      only exists once it is on disk. (Proven by the crash-mid-mint fixture.)
//
//   3. THE DISPATCHER (sole writer of family-of-record).  AdjudicationDispatcher mints the
//      artifact and is the ONLY component that supplies the verifier-family stamp; the gate
//      derives the family-of-record from the dispatcher, never from a caller argument.
//
//   4. THE GATE.  adjudicatedPromoteToVerified() is the autonomous tier's ONLY path to OBSERVED.
//      Absent a dispatcher/minter, or given a malformed / replayed / cross-claim / never-durably-
//      minted artifact, it HARD-FAULTS to ABSTAIN and leaves the ledger untouched (CONJECTURAL).
//      Only a valid fresh artifact promotes the claim to OBSERVED, stamping the dispatcher's
//      family-of-record. (The Wave-3 ClaimLedger.promote() low-level mechanism is unchanged;
//      this gate is the artifact-bound layer the router/pillars use.)
//
// Wave-4's gate is NEGATIVE-ONLY: it proves the rejections + the hard-fault. The POSITIVE
// computational path (a real firewall subprocess whose stdout re-executes to an identical
// content hash -> VERIFIED) is DEFERRED to Wave 9.
//
// Dependency-free apart from the inherited durability substrate (resolved via the pinned
// inherits.manifest.json) and the Wave-3 ledger. Runs under `node --test test/`.

import crypto from 'node:crypto';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

import { RUNG, BELIEF } from './claim-ledger.mjs';
import {
  loadManifest,
  resolveEntryPath,
  DURABILITY_ROLE,
  DEFAULT_MANIFEST_PATH,
} from './inherits-gate.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** The P9 adjudication-artifact field set (order is informational). */
export const ARTIFACT_FIELDS = Object.freeze([
  'claim_id',
  'domain',
  'nonce',
  'stdout_hash',
  'exit_code',
  'runtime_fingerprint',
]);

/**
 * The canonicalization version recorded in every artifact's runtime fingerprint. Bumped only
 * when the canonical-stdout serialization changes, so a re-hash across a version skew is
 * DETECTED (compared), never silently hashed-around.
 */
export const CANONICALIZATION_VERSION = 1;

/** Gate verdicts. ABSTAIN is the honest hard-fault; VERIFIED is the adjudicated promotion. */
export const VERDICT = Object.freeze({ ABSTAIN: 'ABSTAIN', VERIFIED: 'VERIFIED' });

/** A 64-char lowercase hex (a SHA-256 digest). */
const HEX64 = /^[0-9a-f]{64}$/;

// ---------------------------------------------------------------------------
// Runtime fingerprint + canonical re-hash primitive.
// ---------------------------------------------------------------------------

/** The runtime fingerprint stamped into an artifact: { node_major, canonicalization_version }. */
export function runtimeFingerprint() {
  return {
    node_major: Number(String(process.versions.node).split('.')[0]),
    canonicalization_version: CANONICALIZATION_VERSION,
  };
}

/**
 * Canonical serialization for re-hashing: sorted object keys, exact numbers (BigInt rendered
 * as a decimal string so no float ever appears), recursive. A plain string passes through
 * unchanged (it is treated as the raw subprocess stdout).
 */
export function canonicalize(value) {
  if (typeof value === 'string') return value;
  return JSON.stringify(sortDeep(value));
}

function sortDeep(v) {
  if (typeof v === 'bigint') return v.toString();
  if (Array.isArray(v)) return v.map(sortDeep);
  if (v && typeof v === 'object') {
    const out = {};
    for (const k of Object.keys(v).sort()) out[k] = sortDeep(v[k]);
    return out;
  }
  return v;
}

/**
 * The out-of-band RE-HASH: SHA-256 of the canonical (sorted-key, exact-number) subprocess
 * stdout. The Wave-9 firewall subprocess produces the stdout; the Wave-6/Wave-9 canary re-runs
 * the child on the same input and compares this hash. Wave 4 exposes the primitive so the
 * artifact's stdout_hash is a real digest, even though Wave 4 itself spawns nothing.
 */
export function canonicalStdoutHash(stdout) {
  return crypto.createHash('sha256').update(canonicalize(stdout), 'utf8').digest('hex');
}

// ---------------------------------------------------------------------------
// Artifact contract.
// ---------------------------------------------------------------------------

/**
 * Shape-check a P9 artifact. Returns { ok, failures } (failures empty iff ok). Validation is
 * STRUCTURAL only — it does not re-execute the subprocess (that is the canary's job) nor check
 * nonce freshness (that is the store's job).
 */
export function validateArtifact(artifact) {
  const failures = [];
  if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) {
    return { ok: false, failures: ['artifact is not an object'] };
  }
  for (const f of ARTIFACT_FIELDS) {
    if (!(f in artifact)) failures.push(`missing field: ${f}`);
  }
  if (typeof artifact.claim_id !== 'string' || artifact.claim_id.length === 0) {
    failures.push('claim_id must be a non-empty string');
  }
  if (typeof artifact.domain !== 'string' || artifact.domain.length === 0) {
    failures.push('domain must be a non-empty string');
  }
  if (typeof artifact.nonce !== 'string' || !HEX64.test(artifact.nonce)) {
    failures.push('nonce must be a 64-hex SHA-256 string');
  }
  if (typeof artifact.stdout_hash !== 'string' || !HEX64.test(artifact.stdout_hash)) {
    failures.push('stdout_hash must be a 64-hex SHA-256 string');
  }
  if (!Number.isInteger(artifact.exit_code)) {
    failures.push('exit_code must be an integer');
  }
  const rf = artifact.runtime_fingerprint;
  if (!rf || typeof rf !== 'object' || Array.isArray(rf)) {
    failures.push('runtime_fingerprint must be an object { node_major, canonicalization_version }');
  } else {
    if (!Number.isInteger(rf.node_major)) failures.push('runtime_fingerprint.node_major must be an integer');
    if (!Number.isInteger(rf.canonicalization_version)) {
      failures.push('runtime_fingerprint.canonicalization_version must be an integer');
    }
  }
  return { ok: failures.length === 0, failures };
}

// ---------------------------------------------------------------------------
// Nonce derivation.
// ---------------------------------------------------------------------------

// A control-char (ASCII Unit Separator, 0x1f) delimiter so distinct (claim_id, domain) pairs can
// never collide (a claim_id ending in the separator could otherwise alias another pair); it never
// appears in a normal id. Built from a char code so the source stays clean ASCII.
const SEP = String.fromCharCode(0x1f);

/** The per-(claim_id, domain) counter key. */
export function nonceKey(claim_id, domain) {
  return `${claim_id}${SEP}${domain}`;
}

/**
 * The claim-bound nonce: SHA-256(claim_id ++ domain ++ counter). Deterministic, so the store can
 * re-derive it from the recorded (claim_id, domain, counter) to confirm a presented nonce truly
 * binds to that triple (a cross-claim nonce will not re-derive).
 */
export function computeNonce(claim_id, domain, counter) {
  if (typeof claim_id !== 'string' || claim_id.length === 0) throw new Error('computeNonce: claim_id must be a non-empty string');
  if (typeof domain !== 'string' || domain.length === 0) throw new Error('computeNonce: domain must be a non-empty string');
  if (!Number.isInteger(counter) || counter < 1) throw new Error('computeNonce: counter must be a positive integer');
  return crypto.createHash('sha256').update(`${claim_id}${SEP}${domain}${SEP}${counter}`, 'utf8').digest('hex');
}

// ---------------------------------------------------------------------------
// The durable single-use nonce store (on the inherited Phase-0 substrate).
// ---------------------------------------------------------------------------

/** A fresh, empty nonce state. */
function emptyState() {
  return { counters: {}, valid: {}, spent: [] };
}

/** Normalize a loaded nonce_state, tolerating partial/legacy shapes. */
function normalizeState(s) {
  return {
    counters: s && s.counters && typeof s.counters === 'object' ? { ...s.counters } : {},
    valid: s && s.valid && typeof s.valid === 'object' ? structuredClone(s.valid) : {},
    spent: Array.isArray(s && s.spent) ? [...s.spent] : [],
  };
}

/**
 * Resolve the inherited durability substrate from the pinned inherits.manifest.json (the entry
 * marked role="durability-substrate"). REUSES the inherited store — no new persistence layer
 * is introduced (P9 "reuse, no new store"). Returns the live module namespace.
 */
export async function loadDurabilitySubstrate(manifestPath = DEFAULT_MANIFEST_PATH) {
  const manifest = loadManifest(manifestPath);
  const entry = manifest.entries.find((e) => e.role === DURABILITY_ROLE);
  if (!entry) throw new Error(`inherits manifest has no entry with role="${DURABILITY_ROLE}"`);
  const resolved = resolveEntryPath(manifestPath, entry);
  const ns = await import(pathToFileURL(resolved).href);
  for (const fn of ['newCheckpoint', 'writeCheckpointAtomic', 'readCheckpoint']) {
    if (typeof ns[fn] !== 'function') throw new Error(`durability substrate is missing ${fn}()`);
  }
  return ns;
}

export class DurableNonceStore {
  #substrate;
  #file;
  #state;

  /**
   * @param {object} substrate  the inherited durability module ({ newCheckpoint,
   *                             writeCheckpointAtomic, readCheckpoint }).
   * @param {string} file        the checkpoint file the nonce_state is parked on.
   * @param {object} [state]     initial nonce state (defaults to empty).
   */
  constructor(substrate, file, state = emptyState()) {
    for (const fn of ['newCheckpoint', 'writeCheckpointAtomic', 'readCheckpoint']) {
      if (!substrate || typeof substrate[fn] !== 'function') {
        throw new Error(`DurableNonceStore requires a durability substrate with ${fn}()`);
      }
    }
    if (typeof file !== 'string' || file.length === 0) throw new Error('DurableNonceStore requires a file path');
    this.#substrate = substrate;
    this.#file = file;
    this.#state = normalizeState(state);
  }

  /**
   * Open the store for `file`, RELOADING any persisted nonce_state from disk (an across-restart
   * load reads ONLY from disk — it holds no in-memory state from a prior process). If the file
   * is absent the store starts empty.
   */
  static load(substrate, file) {
    let state = emptyState();
    if (fs.existsSync(file)) {
      const cp = substrate.readCheckpoint(file); // validating read — HALTs on a torn file
      if (cp && cp.nonce_state) state = cp.nonce_state;
    }
    return new DurableNonceStore(substrate, file, state);
  }

  /** Persist a candidate state DURABLY via the inherited atomic writer (the flush boundary). */
  #flush(candidateState) {
    const cp = this.#substrate.newCheckpoint({ plan_path: this.#file, total_waves: 1 });
    cp.nonce_state = candidateState;
    this.#substrate.writeCheckpointAtomic(this.#file, cp); // write-tmp + fsync + atomic rename
  }

  /**
   * Mint a fresh single-use nonce for (claim_id, domain). Bumps the durable monotone counter,
   * records the nonce as ISSUED (valid), and FLUSHES to disk BEFORE publishing it in memory or
   * returning it — so the nonce is usable only once its issued-record is durable.
   *
   * @param {string} claim_id
   * @param {string} domain
   * @param {{beforeFlush?:(info:{nonce:string,counter:number})=>void}} [hooks]
   *        beforeFlush runs at the durability boundary (after the nonce is computed, before the
   *        flush) — the crash-mid-mint fixture throws here to model a process death in that
   *        window. If it throws, no state is mutated and nothing is persisted.
   * @returns {{nonce:string, counter:number}}
   */
  mint(claim_id, domain, hooks = {}) {
    const key = nonceKey(claim_id, domain);
    const counter = (this.#state.counters[key] || 0) + 1;
    const nonce = computeNonce(claim_id, domain, counter);

    const candidate = normalizeState(this.#state);
    candidate.counters[key] = counter;
    candidate.valid[nonce] = { claim_id, domain, counter };

    // --- DURABILITY BOUNDARY: the nonce is NOT usable until the flush below lands. ---
    if (typeof hooks.beforeFlush === 'function') hooks.beforeFlush({ nonce, counter });
    this.#flush(candidate);       // ordered-BEFORE the in-memory publish + the return
    this.#state = candidate;      // publish only after the durable flush succeeded
    return { nonce, counter };
  }

  /**
   * Is this nonce currently usable for (claim_id, domain)? True iff it is durably ISSUED, not
   * yet SPENT, its recorded binding matches (claim_id, domain), and it re-derives from the
   * recorded counter (so a forged or cross-claim nonce fails).
   */
  isValid(nonce, claim_id, domain) {
    const binding = this.#state.valid[nonce];
    if (!binding) return false;
    if (this.#state.spent.includes(nonce)) return false;
    if (binding.claim_id !== claim_id || binding.domain !== domain) return false;
    return computeNonce(claim_id, domain, binding.counter) === nonce;
  }

  /**
   * Single-use CONSUME: if the nonce is valid for (claim_id, domain), mark it SPENT durably
   * (flush ordered-before reporting success) and return true; otherwise return false WITHOUT
   * any state change. A second consume of the same nonce — same process, or after a restart
   * (the spent set reloads from disk) — returns false.
   */
  consume(nonce, claim_id, domain) {
    if (!this.isValid(nonce, claim_id, domain)) return false;
    const candidate = normalizeState(this.#state);
    delete candidate.valid[nonce];
    candidate.spent.push(nonce);
    this.#flush(candidate);   // durable single-use record ordered-before success
    this.#state = candidate;
    return true;
  }

  /** Last-issued monotone counter for (claim_id, domain) (0 if none). */
  counterFor(claim_id, domain) {
    return this.#state.counters[nonceKey(claim_id, domain)] || 0;
  }

  /** Whether a nonce has been consumed (audit). */
  isSpent(nonce) {
    return this.#state.spent.includes(nonce);
  }

  /** The checkpoint file this store persists through. */
  get file() {
    return this.#file;
  }
}

// ---------------------------------------------------------------------------
// The dispatcher — the SOLE writer of family-of-record.
// ---------------------------------------------------------------------------

export class AdjudicationDispatcher {
  #store;
  #family;

  /**
   * @param {{store:DurableNonceStore, family:string}} o  family = the verifier-family-of-record
   *        this dispatcher stamps (e.g. 'firewall-subprocess'). It is the ONLY source of the
   *        family stamp; no caller of the gate supplies one.
   */
  constructor({ store, family } = {}) {
    if (!(store instanceof DurableNonceStore)) throw new Error('AdjudicationDispatcher requires a DurableNonceStore');
    if (typeof family !== 'string' || family.length === 0) throw new Error('AdjudicationDispatcher requires a non-empty family-of-record');
    this.#store = store;
    this.#family = family;
  }

  /** The family-of-record this dispatcher (and only it) writes. */
  get family() {
    return this.#family;
  }

  /**
   * Mint a fresh adjudication artifact for (claim_id, domain). The caller supplies the
   * stdout_hash a real subprocess produces (Wave 9 computes it from the firewall child; Wave 4
   * callers pass a real digest, e.g. via canonicalStdoutHash). Returns a frozen artifact.
   *
   * @param {string} claim_id
   * @param {string} domain
   * @param {{stdout_hash:string, exit_code?:number}} payload
   * @param {object} [hooks]  forwarded to store.mint (crash-mid-mint injection).
   */
  mintArtifact(claim_id, domain, { stdout_hash, exit_code = 0 } = {}, hooks = {}) {
    if (typeof stdout_hash !== 'string' || !HEX64.test(stdout_hash)) {
      throw new Error('mintArtifact requires a 64-hex stdout_hash (the subprocess re-hash)');
    }
    if (!Number.isInteger(exit_code)) throw new Error('mintArtifact requires an integer exit_code');
    const { nonce } = this.#store.mint(claim_id, domain, hooks);
    return Object.freeze({
      claim_id,
      domain,
      nonce,
      stdout_hash,
      exit_code,
      runtime_fingerprint: runtimeFingerprint(),
    });
  }

  /**
   * Validate + single-use CONSUME an artifact's nonce against this dispatcher's store. Returns
   * true iff the nonce was fresh, valid, bound to (artifact.claim_id, artifact.domain), and
   * unspent — and, on true, the nonce is now durably spent.
   */
  consumeArtifact(artifact) {
    if (!artifact || typeof artifact !== 'object') return false;
    return this.#store.consume(artifact.nonce, artifact.claim_id, artifact.domain);
  }
}

// ---------------------------------------------------------------------------
// The gate — the autonomous tier's only path to OBSERVED (belief VERIFIED).
// ---------------------------------------------------------------------------

function abstain(reason, extra = {}) {
  return Object.freeze({
    verdict: VERDICT.ABSTAIN,
    promoted: false,
    belief: BELIEF.CONJECTURAL, // the claim is NOT settled; route out-of-model (Wave 7)
    routed: true,
    reason,
    ...extra,
  });
}

/**
 * Adjudicated promote-to-VERIFIED. The ONLY autonomous path that lifts a claim to OBSERVED.
 *
 * HARD-FAULTS to ABSTAIN (leaving the ledger untouched) when:
 *   - no dispatcher / minter is present (the headline NEGATIVE case);
 *   - the artifact is malformed;
 *   - the artifact is not bound to this claim_id;
 *   - the nonce is not fresh+valid (replayed same-claim, cross-claim, across-restart, or never
 *     durably minted — i.e. a crash-mid-mint nonce).
 *
 * On a valid fresh artifact it consumes the single-use nonce and promotes the claim to OBSERVED,
 * stamping the dispatcher's family-of-record (only the dispatcher writes it). Wave-4 verifies the
 * negative arm; the positive computational path (real subprocess re-execution) is Wave 9.
 *
 * @param {import('./claim-ledger.mjs').ClaimLedger} ledger
 * @param {string} claim_id
 * @param {{artifact?:object, dispatcher?:AdjudicationDispatcher}} [o]
 * @returns {object} a frozen verdict { verdict, promoted, belief, ... }.
 */
export function adjudicatedPromoteToVerified(ledger, claim_id, { artifact, dispatcher } = {}) {
  if (!ledger || typeof ledger.promote !== 'function') {
    throw new Error('adjudicatedPromoteToVerified requires a ClaimLedger');
  }

  // (1) No minter present => hard-fault to ABSTAIN (the NEGATIVE test). propose != adjudicate:
  //     with nothing out-of-model to mint/consume an artifact, the autonomous tier cannot settle.
  if (!dispatcher || typeof dispatcher.consumeArtifact !== 'function' || typeof dispatcher.family !== 'string') {
    return abstain('no adjudication dispatcher/minter present — cannot reach VERIFIED');
  }

  // (2) Structural artifact check.
  const v = validateArtifact(artifact);
  if (!v.ok) return abstain(`artifact malformed: ${v.failures.join('; ')}`);

  // (3) The artifact must be bound to THIS claim.
  if (artifact.claim_id !== claim_id) {
    return abstain(`artifact claim_id ${JSON.stringify(artifact.claim_id)} != promotion target ${JSON.stringify(claim_id)}`);
  }

  // (4) Freshness / single-use: consume the durable nonce. Rejects same-claim replay (spent),
  //     cross-claim replay (binding/re-derive mismatch), across-restart replay (spent set
  //     reloaded from disk), and crash-mid-mint nonces (never durably issued).
  if (!dispatcher.consumeArtifact(artifact)) {
    return abstain('artifact nonce is not fresh — replayed (same/cross-claim), spent across a restart, or never durably minted');
  }

  // (5) Adjudicated: promote to OBSERVED, stamping the dispatcher's family-of-record (sole writer).
  const claim = ledger.promote(claim_id, RUNG.OBSERVED, {
    family: dispatcher.family,
    reason: 'adjudicated out-of-model artifact (single-use nonce consumed)',
    by: 'adjudication-dispatcher',
    meta: { artifact },
  });

  return Object.freeze({
    verdict: VERDICT.VERIFIED,
    promoted: true,
    belief: BELIEF.VERIFIED,
    routed: false,
    family: dispatcher.family,
    claim,
  });
}
