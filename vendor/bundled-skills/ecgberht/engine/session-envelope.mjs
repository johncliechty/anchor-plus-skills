/**
 * Wave 8 — Session envelope: one confirmed budget BEFORE any authoring spend.
 *
 * NAMED NUMERIC BOUNDS (whichever first hard-stops):
 *   ENVELOPE_MAX_SPEND_USD = 5.00
 *   ENVELOPE_MAX_COMPILES  = 25
 *   ENVELOPE_TTL_MINUTES   = 240
 *
 * Justified against Wave-5 calibration by the MACHINE-CHECKED relation
 *   ENVELOPE_MAX_SPEND_USD >= 3 × p90(compile_cost)
 * (T-BND-08 imports cost-model.json + the calibration record).
 *
 * Confirm is HASH-BOUND (TOCTOU): payload carries content hash of the rendered
 * budget terms; mismatch → confirm-hash-mismatch, nothing minted.
 * Idempotence: client_event_id (T-IDEM-08) — double submit mints exactly one.
 *
 * Spend path: only inside a live envelope; every debit priced by the
 * deterministic Wave-5 cost model and individually SHOWN. TTL is measured
 * against a MONOTONIC (or seq-anchored) clock — wall-clock skew cannot
 * silently extend or expire an envelope.
 *
 * Auth at debit (NS criterion 9): debit calls authorize('debit', ctx) — an
 * INJECTED host hook. The engine contains no ANCHOR_TOKEN logic.
 *
 * Commissions are NOT covered by the envelope (own confirmation still required).
 * No-live-envelope (gate decision 4): ONLY the model-authored NL-polish
 * reflection compile queues; deterministic receipt + next-stage proposal
 * are NEVER queued (zero-spend — Wave 14).
 *
 * Durability (S4): writeFileAtomicSync + withFileLock; T-DUR-S4 two-process
 * debit race past the bound — exactly one succeeds.
 *
 * Stdlib only. No host-absolute user homes in shipped strings.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import {
  writeFileAtomicSync,
  withFileLock,
  LOCK_TIMEOUT_MS,
} from './durable-write.mjs';
import {
  ENVELOPE_MAX_SPEND_USD,
  priceCompile,
  priceTokens,
  envelopeCoversP90,
} from './cost-model.mjs';
import {
  publishAttention,
  ATTENTION_CALL_SITES,
} from './attention.mjs';
import {
  normalizeClaimedWho,
  recordSpendConfirmationWho,
  CREDENTIAL_CLASS_NONE,
} from './identity-policy.mjs';
import { authorize } from './authorize.mjs';

// ── Named bounds (T-BND-08) ────────────────────────────────────────────────

export { ENVELOPE_MAX_SPEND_USD };

/** Named compile count bound — hard-stop when reached. */
export const ENVELOPE_MAX_COMPILES = 25;

/** Named TTL (minutes) — hard-stop when mono/seq clock exceeds mint + TTL. */
export const ENVELOPE_TTL_MINUTES = 240;

/** TTL in milliseconds (mono clock units). */
export const ENVELOPE_TTL_MS = ENVELOPE_TTL_MINUTES * 60 * 1000;

// ── Named durability helpers (S4 — removal-proof T-DUR-S4) ─────────────────

/** Named lock helper — Durable-store map S4. */
export const ENVELOPE_LOCK_HELPER = 'withFileLock';

/** Named atomic write — Durable-store map S4. */
export const ENVELOPE_ATOMIC_WRITE = 'writeFileAtomicSync';

/** Relative store path under the project root. */
export const ENVELOPE_LEDGER_REL = path.join('.ecgberht', 'envelope-ledger.json');

/** Schema id for the session-envelope ledger. */
export const ENVELOPE_SCHEMA_ID = 'ecgberht-session-envelope-v0';

/** Schema id for rendered budget terms (hash input). */
export const ENVELOPE_TERMS_SCHEMA = 'ecgberht-envelope-terms-v0';

/** Idempotence key name (T-IDEM-08). */
export const ENVELOPE_IDEMPOTENCE_KEY = 'client_event_id';

/** Spend kinds debited through the envelope (compile / reflection). */
export const ENVELOPE_SPEND_KINDS = Object.freeze([
  'compile',
  'reflection',
  'nl_polish_reflection_compile',
]);

/**
 * Gate decision 4 — kinds that emit with ZERO spend and NEVER queue when
 * there is no live envelope (deterministic handback path — Wave 14).
 */
export const ZERO_SPEND_NEVER_QUEUE_KINDS = Object.freeze([
  'deterministic_reflection_receipt',
  'deterministic_next_stage_proposal',
]);

/**
 * Gate decision 4 — the ONLY model-authored path that may queue without a
 * live envelope (S13, typed event in-ledger).
 */
export const QUEUE_WITHOUT_ENVELOPE_KIND = 'nl_polish_reflection_compile';

// ── Failure states (envelope surface) ──────────────────────────────────────

export const ENVELOPE_CODE = Object.freeze({
  ABSENT: 'ENVELOPE_ABSENT',
  EXHAUSTED: 'ENVELOPE_EXHAUSTED',
  EXPIRED: 'ENVELOPE_EXPIRED',
  CONFIRM_HASH_MISMATCH: 'ENVELOPE_CONFIRM_HASH_MISMATCH',
  AUTH_REFUSED: 'ENVELOPE_AUTH_REFUSED',
  LEDGER_UNREADABLE: 'ENVELOPE_LEDGER_UNREADABLE',
  NONE_YET: 'ENVELOPE_NONE_YET',
  STATE_UNKNOWN: 'ENVELOPE_STATE_UNKNOWN',
});

export const ENVELOPE_TEXT = Object.freeze({
  [ENVELOPE_CODE.ABSENT]:
    'No confirmed session envelope — spend refused; confirm a budget to proceed.',
  [ENVELOPE_CODE.EXHAUSTED]:
    'Session budget exhausted — hard stop; confirm a fresh envelope to continue.',
  [ENVELOPE_CODE.EXPIRED]:
    'Session envelope expired — hard stop; confirm a fresh envelope to continue.',
  [ENVELOPE_CODE.CONFIRM_HASH_MISMATCH]:
    'The budget shown changed before you confirmed — refused; review the current terms.',
  [ENVELOPE_CODE.AUTH_REFUSED]:
    'Credential invalid at spend time — nothing debited.',
  [ENVELOPE_CODE.LEDGER_UNREADABLE]:
    'Envelope ledger unreadable — spend refused rather than run blind.',
  [ENVELOPE_CODE.NONE_YET]:
    'No envelopes confirmed yet this session.',
  [ENVELOPE_CODE.STATE_UNKNOWN]:
    'Envelope balance unknown (ledger gap) — spend refused until repaired.',
});

/**
 * @param {string} code ENVELOPE_CODE value
 * @param {object} [extra]
 */
export function envelopeFailure(code, extra = {}) {
  const text = ENVELOPE_TEXT[code] ?? ENVELOPE_TEXT[ENVELOPE_CODE.STATE_UNKNOWN];
  return {
    ok: false,
    error: extra.error ?? String(code).toLowerCase().replace(/_/g, '-'),
    code,
    status: code,
    status_code: code,
    text,
    message: text,
    user_text: text,
    envelope: true,
    spent: false,
    debited: false,
    ...extra,
  };
}

/**
 * Full failure-state table for the envelope surface (honest unknown ≠ empty).
 * @returns {ReadonlyArray<{state: string, status_code: string, user_text: string}>}
 */
export function envelopeFailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'envelope-absent',
      status_code: ENVELOPE_CODE.ABSENT,
      user_text: ENVELOPE_TEXT[ENVELOPE_CODE.ABSENT],
    }),
    Object.freeze({
      state: 'envelope-exhausted',
      status_code: ENVELOPE_CODE.EXHAUSTED,
      user_text: ENVELOPE_TEXT[ENVELOPE_CODE.EXHAUSTED],
    }),
    Object.freeze({
      state: 'envelope-expired',
      status_code: ENVELOPE_CODE.EXPIRED,
      user_text: ENVELOPE_TEXT[ENVELOPE_CODE.EXPIRED],
    }),
    Object.freeze({
      state: 'confirm-hash-mismatch',
      status_code: ENVELOPE_CODE.CONFIRM_HASH_MISMATCH,
      user_text: ENVELOPE_TEXT[ENVELOPE_CODE.CONFIRM_HASH_MISMATCH],
    }),
    Object.freeze({
      state: 'auth-refused at debit',
      status_code: ENVELOPE_CODE.AUTH_REFUSED,
      user_text: ENVELOPE_TEXT[ENVELOPE_CODE.AUTH_REFUSED],
    }),
    Object.freeze({
      state: 'backing-store-unreadable',
      status_code: ENVELOPE_CODE.LEDGER_UNREADABLE,
      user_text: ENVELOPE_TEXT[ENVELOPE_CODE.LEDGER_UNREADABLE],
    }),
    Object.freeze({
      state: 'empty-but-valid',
      status_code: ENVELOPE_CODE.NONE_YET,
      user_text: ENVELOPE_TEXT[ENVELOPE_CODE.NONE_YET],
    }),
    Object.freeze({
      state: 'unknown',
      status_code: ENVELOPE_CODE.STATE_UNKNOWN,
      user_text: ENVELOPE_TEXT[ENVELOPE_CODE.STATE_UNKNOWN],
    }),
  ]);
}

// ── Clocks (monotonic-or-seq-anchored TTL) ─────────────────────────────────

/**
 * Default monotonic clock in milliseconds (hrtime, not wall clock).
 * Wall-clock skew cannot move this value.
 * @returns {number}
 */
export function defaultMonoMs() {
  return Number(process.hrtime.bigint() / 1_000_000n);
}

/**
 * Resolve clocks from options. Wall clock is display-only; mono drives TTL.
 * @param {{ monoNow?: () => number, wallNow?: () => string|number }} [opts]
 */
export function resolveClocks(opts = {}) {
  const monoNow =
    typeof opts.monoNow === 'function' ? opts.monoNow : defaultMonoMs;
  const wallNow =
    typeof opts.wallNow === 'function'
      ? opts.wallNow
      : () => new Date().toISOString();
  return { monoNow, wallNow };
}

// ── Hash / terms (TOCTOU) ──────────────────────────────────────────────────

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    const out = {};
    for (const k of Object.keys(value).sort()) {
      out[k] = sortKeys(value[k]);
    }
    return out;
  }
  return value;
}

/**
 * Content hash of a payload (canonical JSON, sha256 hex).
 * @param {object} payload
 * @returns {string}
 */
export function hashEnvelopePayload(payload) {
  const canonical = JSON.stringify(sortKeys(payload));
  return crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
}

/**
 * Render the budget terms John confirms. Deterministic — hash input.
 * @param {object} [overrides]
 * @returns {object}
 */
export function renderBudgetTerms(overrides = {}) {
  return {
    schema: ENVELOPE_TERMS_SCHEMA,
    max_spend_usd: ENVELOPE_MAX_SPEND_USD,
    max_compiles: ENVELOPE_MAX_COMPILES,
    ttl_minutes: ENVELOPE_TTL_MINUTES,
    currency: 'synthetic_usd',
    disclaimer:
      'SYNTHETIC-BUT-DETERMINISTIC — subscription CLIs; dollar figures are accounting units only',
    covers: ['compile', 'orchestrator_reflection'],
    does_not_cover: ['commission'],
    hard_stop: 'whichever_first',
    ...overrides,
  };
}

/**
 * Hash of the currently rendered budget terms (for confirm payloads).
 * @param {object} [overrides]
 * @returns {{ terms: object, terms_hash: string }}
 */
export function currentBudgetTermsHash(overrides = {}) {
  const terms = renderBudgetTerms(overrides);
  return { terms, terms_hash: hashEnvelopePayload(terms) };
}

// ── Ledger IO ──────────────────────────────────────────────────────────────

/**
 * Absolute path of the envelope ledger under a project root.
 * @param {string} projectRoot
 */
export function envelopeLedgerPath(projectRoot) {
  return path.join(path.resolve(projectRoot), ENVELOPE_LEDGER_REL);
}

/**
 * Empty ledger shape (empty-but-valid ≠ unknown).
 * @returns {object}
 */
export function emptyEnvelopeLedger() {
  return {
    schema: ENVELOPE_SCHEMA_ID,
    envelopes: [],
    events: [],
    queued: [],
    next_seq: 1,
  };
}

/**
 * @param {string} sourceText
 */
export function assertEnvelopeDurableHelpersPresent(sourceText) {
  const missing = [];
  if (!sourceText.includes('writeFileAtomicSync')) missing.push('writeFileAtomicSync');
  if (!sourceText.includes('withFileLock')) missing.push('withFileLock');
  if (!sourceText.includes('authorize')) missing.push('authorize');
  if (!/authorize\s*\(\s*['"]debit['"]/.test(sourceText)) {
    missing.push("authorize('debit')");
  }
  return { ok: missing.length === 0, missing };
}

/**
 * Criterion-9 companion: engine modules must not read ANCHOR_TOKEN from env.
 * String mentions in comments/docs/policy records are allowed; env access is not.
 * @param {string} sourceText
 * @returns {{ ok: boolean, hits: string[] }}
 */
export function assertNoAnchorTokenEnvRead(sourceText) {
  const patterns = [
    /process\.env\.ANCHOR_TOKEN\b/,
    /process\.env\[['"]ANCHOR_TOKEN['"]\]/,
    /env\.ANCHOR_TOKEN\b/,
    /env\[['"]ANCHOR_TOKEN['"]\]/,
    /getenv\s*\(\s*['"]ANCHOR_TOKEN['"]\s*\)/,
  ];
  const hits = [];
  for (const re of patterns) {
    if (re.test(sourceText)) hits.push(re.source);
  }
  return { ok: hits.length === 0, hits };
}

function readLedgerFile(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return { ok: true, exists: false, value: null };
    }
    const raw = fs.readFileSync(filePath, 'utf8');
    if (!raw || !String(raw).trim()) {
      return { ok: true, exists: true, value: null, empty: true };
    }
    const value = JSON.parse(raw);
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return { ok: false, unreadable: true, detail: 'not-an-object' };
    }
    return { ok: true, exists: true, value };
  } catch (e) {
    return {
      ok: false,
      unreadable: true,
      detail: String(e?.message ?? e),
    };
  }
}

function writeLedgerLocked(filePath, ledger, opts = {}) {
  const dir = path.dirname(filePath);
  try {
    withFileLock(
      filePath,
      () => {
        fs.mkdirSync(dir, { recursive: true });
        writeFileAtomicSync(filePath, `${JSON.stringify(ledger, null, 2)}\n`);
      },
      {
        timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS,
        onTimeout: (info) => {
          const err = new Error(ENVELOPE_TEXT[ENVELOPE_CODE.STATE_UNKNOWN]);
          err.code = 'ELOCKTIMEOUT';
          err.envelope_info = info;
          return err;
        },
      },
    );
    return { ok: true, path: filePath, sot_written: true, locked: true };
  } catch (e) {
    if (e && (e.code === 'ELOCKTIMEOUT' || e.code === ENVELOPE_CODE.STATE_UNKNOWN)) {
      return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
        error: 'lock-contended',
        detail: String(e?.message ?? e),
      });
    }
    return envelopeFailure(ENVELOPE_CODE.LEDGER_UNREADABLE, {
      error: 'write-failed',
      detail: String(e?.message ?? e),
    });
  }
}

/**
 * Load ledger under lock for a mutate cycle. Caller must write back.
 * @param {string} projectRoot
 * @param {(ledger: object) => object} mutator returns next ledger or throws
 * @param {object} [opts]
 */
function withEnvelopeLedger(projectRoot, mutator, opts = {}) {
  const filePath = envelopeLedgerPath(projectRoot);
  const dir = path.dirname(filePath);
  try {
    return withFileLock(
      filePath,
      () => {
        const read = readLedgerFile(filePath);
        if (!read.ok) {
          return envelopeFailure(ENVELOPE_CODE.LEDGER_UNREADABLE, {
            error: 'ledger-unreadable',
            detail: read.detail,
          });
        }
        const base =
          read.exists && read.value
            ? {
                ...emptyEnvelopeLedger(),
                ...read.value,
                envelopes: Array.isArray(read.value.envelopes)
                  ? [...read.value.envelopes]
                  : [],
                events: Array.isArray(read.value.events)
                  ? [...read.value.events]
                  : [],
                queued: Array.isArray(read.value.queued)
                  ? [...read.value.queued]
                  : [],
              }
            : emptyEnvelopeLedger();

        const result = mutator(base);
        if (!result || result.ok === false) {
          return result;
        }
        if (result.skip_write) {
          return result;
        }
        const nextLedger = result.ledger ?? base;
        fs.mkdirSync(dir, { recursive: true });
        writeFileAtomicSync(
          filePath,
          `${JSON.stringify(nextLedger, null, 2)}\n`,
        );
        return { ...result, ledger: nextLedger, path: filePath, sot_written: true };
      },
      {
        timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS,
        onTimeout: (info) => {
          const err = new Error(ENVELOPE_TEXT[ENVELOPE_CODE.STATE_UNKNOWN]);
          err.code = 'ELOCKTIMEOUT';
          err.envelope_info = info;
          return err;
        },
      },
    );
  } catch (e) {
    if (e && e.code === 'ELOCKTIMEOUT') {
      return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
        error: 'lock-contended',
        detail: String(e?.message ?? e),
      });
    }
    return envelopeFailure(ENVELOPE_CODE.LEDGER_UNREADABLE, {
      error: 'ledger-io',
      detail: String(e?.message ?? e),
    });
  }
}

// ── Live balance / expiry ──────────────────────────────────────────────────

/**
 * Is the envelope past its mono-anchored TTL?
 * Wall clock is ignored for the decision.
 *
 * @param {object} env
 * @param {number} nowMonoMs
 * @returns {boolean}
 */
export function isEnvelopeExpired(env, nowMonoMs) {
  if (!env || env.minted_mono_ms == null) return true;
  const mint = Number(env.minted_mono_ms);
  const now = Number(nowMonoMs);
  if (!Number.isFinite(mint) || !Number.isFinite(now)) return true;
  return now - mint >= ENVELOPE_TTL_MS;
}

/**
 * Remaining capacity (spend + compile counts). Expired → not live.
 * @param {object} env
 * @param {number} nowMonoMs
 */
/**
 * Resolve a stored bound, where an explicit `null` means UNLIMITED.
 *
 * WHY (John, 2026-08-04). The compile-count bound was sized for a
 * compile-a-description surface, not for a conversation: "the number of chat turns is
 * as long as the user wants to chat with the steward — that should not be a problem."
 * So a conversational envelope mints with `max_compiles: null` and the DOLLAR cap
 * becomes the real governor, which is the bound he actually wants to feel.
 *
 * `??` cannot express this on its own — a stored null would fall through to the
 * default and silently re-impose the old limit.
 *
 * @param {*} value
 * @param {number} fallback
 * @returns {number} the bound, or Infinity when unlimited
 */
export function boundOrUnlimited(value, fallback) {
  if (value === null) return Number.POSITIVE_INFINITY;
  if (value === undefined) return Number(fallback);
  const n = Number(value);
  return Number.isFinite(n) ? n : Number(fallback);
}

/** JSON-safe rendering of a possibly-infinite bound (Infinity serialises to null). */
function reportBound(n) {
  return Number.isFinite(n) ? n : null;
}

export function envelopeBalance(env, nowMonoMs) {
  if (!env) {
    return {
      live: false,
      reason: 'absent',
      code: ENVELOPE_CODE.ABSENT,
    };
  }
  if (isEnvelopeExpired(env, nowMonoMs)) {
    return {
      live: false,
      reason: 'expired',
      code: ENVELOPE_CODE.EXPIRED,
      spent_usd: Number(env.spent_usd) || 0,
      compile_count: Number(env.compile_count) || 0,
    };
  }
  const spent = Number(env.spent_usd) || 0;
  const compiles = Number(env.compile_count) || 0;
  const maxSpend = boundOrUnlimited(env.max_spend_usd, ENVELOPE_MAX_SPEND_USD);
  const maxCompiles = boundOrUnlimited(env.max_compiles, ENVELOPE_MAX_COMPILES);
  if (spent >= maxSpend || compiles >= maxCompiles) {
    return {
      live: false,
      reason: 'exhausted',
      code: ENVELOPE_CODE.EXHAUSTED,
      // WHICH bound stopped it — so the surface can say "you have spent $X of $Y"
      // and offer to raise it, instead of a bare refusal.
      bound: spent >= maxSpend ? 'spend' : 'compiles',
      spent_usd: spent,
      compile_count: compiles,
      max_spend_usd: reportBound(maxSpend),
      max_compiles: reportBound(maxCompiles),
      remaining_usd: Number.isFinite(maxSpend) ? Math.max(0, maxSpend - spent) : null,
      remaining_compiles: Number.isFinite(maxCompiles)
        ? Math.max(0, maxCompiles - compiles) : null,
    };
  }
  return {
    live: true,
    spent_usd: spent,
    compile_count: compiles,
    remaining_usd: Number.isFinite(maxSpend) ? maxSpend - spent : null,
    remaining_compiles: Number.isFinite(maxCompiles) ? maxCompiles - compiles : null,
    max_spend_usd: reportBound(maxSpend),
    max_compiles: reportBound(maxCompiles),
    unlimited_compiles: !Number.isFinite(maxCompiles),
    mono_remaining_ms: Math.max(0, ENVELOPE_TTL_MS - (nowMonoMs - Number(env.minted_mono_ms))),
  };
}

/**
 * Latest envelope on the ledger (or null).
 * @param {object} ledger
 */
export function latestEnvelope(ledger) {
  const list = ledger?.envelopes;
  if (!Array.isArray(list) || list.length === 0) return null;
  return list[list.length - 1];
}

/**
 * Read-only view of the current envelope state for a project.
 * @param {string} projectRoot
 * @param {{ monoNow?: () => number }} [opts]
 */
export function readEnvelopeState(projectRoot, opts = {}) {
  const { monoNow } = resolveClocks(opts);
  const filePath = envelopeLedgerPath(projectRoot);
  const read = readLedgerFile(filePath);
  if (!read.ok) {
    return envelopeFailure(ENVELOPE_CODE.LEDGER_UNREADABLE, {
      error: 'ledger-unreadable',
      detail: read.detail,
    });
  }
  if (!read.exists || !read.value) {
    return {
      ok: true,
      empty: true,
      code: ENVELOPE_CODE.NONE_YET,
      status_code: ENVELOPE_CODE.NONE_YET,
      text: ENVELOPE_TEXT[ENVELOPE_CODE.NONE_YET],
      message: ENVELOPE_TEXT[ENVELOPE_CODE.NONE_YET],
      envelope: null,
      live: false,
    };
  }
  const ledger = read.value;
  if (!Array.isArray(ledger.envelopes)) {
    return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
      error: 'ledger-gap',
      detail: 'envelopes array missing',
    });
  }
  if (ledger.envelopes.length === 0) {
    return {
      ok: true,
      empty: true,
      code: ENVELOPE_CODE.NONE_YET,
      status_code: ENVELOPE_CODE.NONE_YET,
      text: ENVELOPE_TEXT[ENVELOPE_CODE.NONE_YET],
      message: ENVELOPE_TEXT[ENVELOPE_CODE.NONE_YET],
      envelope: null,
      live: false,
      ledger,
    };
  }
  const env = latestEnvelope(ledger);
  const bal = envelopeBalance(env, monoNow());
  return {
    ok: true,
    empty: false,
    envelope: env,
    balance: bal,
    live: bal.live === true,
    code: bal.live ? null : bal.code,
    ledger,
  };
}

// ── Confirm (hash-bound, idempotent) ───────────────────────────────────────

/**
 * Confirm a session envelope once at session open.
 *
 * Payload MUST carry terms_hash matching the rendered budget terms (TOCTOU).
 * Idempotent on client_event_id (T-IDEM-08).
 *
 * @param {string} projectRoot
 * @param {{
 *   who: string|object,
 *   terms_hash: string,
 *   client_event_id: string,
 *   credential_class?: string,
 *   terms_overrides?: object,
 *   monoNow?: () => number,
 *   wallNow?: () => string|number,
 *   at?: string,
 * }} opts
 */
export function confirmSessionEnvelope(projectRoot, opts = {}) {
  const clientEventId = opts.client_event_id;
  if (!clientEventId || typeof clientEventId !== 'string' || !clientEventId.trim()) {
    return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
      error: 'client_event_id-required',
      message: 'Envelope confirm requires client_event_id (T-IDEM-08).',
    });
  }

  const who = normalizeClaimedWho(opts.who);
  if (!who) {
    return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
      error: 'who-required',
      message:
        'Envelope confirm requires a claimed identity — unattributed is never substituted.',
    });
  }

  const { terms, terms_hash: expectedHash } = currentBudgetTermsHash(
    opts.terms_overrides ?? {},
  );
  const presentedHash = opts.terms_hash == null ? '' : String(opts.terms_hash);
  if (!presentedHash || presentedHash !== expectedHash) {
    return envelopeFailure(ENVELOPE_CODE.CONFIRM_HASH_MISMATCH, {
      error: 'confirm-hash-mismatch',
      presented_hash: presentedHash || null,
      expected_hash: expectedHash,
    });
  }

  const credential_class =
    opts.credential_class == null || opts.credential_class === ''
      ? CREDENTIAL_CLASS_NONE
      : String(opts.credential_class);

  const whoRec = recordSpendConfirmationWho({
    who,
    credential_class,
    kind: 'envelope_confirm',
    at: opts.at,
  });
  if (!whoRec.ok) {
    return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
      error: whoRec.code,
      message: whoRec.message,
    });
  }

  const { monoNow, wallNow } = resolveClocks(opts);
  const mono = monoNow();
  const wall = opts.at ?? wallNow();

  return withEnvelopeLedger(projectRoot, (ledger) => {
    // Idempotence: same client_event_id → return existing mint, no second envelope
    const prior = ledger.envelopes.find(
      (e) => e && e.client_event_id === clientEventId,
    );
    if (prior) {
      return {
        ok: true,
        idempotent: true,
        already_confirmed: true,
        envelope: prior,
        skip_write: true,
        client_event_id: clientEventId,
        message: `Envelope already confirmed (client_event_id=${clientEventId}); no second mint.`,
      };
    }

    const seq = Number(ledger.next_seq) || 1;
    const envelope_id = `env-${expectedHash.slice(0, 12)}-${seq}`;
    const envelope = {
      envelope_id,
      client_event_id: clientEventId,
      seq,
      who,
      credential_class,
      terms_hash: expectedHash,
      terms,
      // Mint from the CONFIRMED TERMS, not the module constants (2026-08-04).
      // The terms are what the human confirmed and they are covered by the hash, so a
      // user-set dollar cap — or `max_compiles: null` for "talk as long as I want" —
      // is bound to their confirmation rather than silently overridden by a default.
      max_spend_usd: terms.max_spend_usd,
      max_compiles: terms.max_compiles,
      ttl_minutes: ENVELOPE_TTL_MINUTES,
      minted_mono_ms: mono,
      minted_at_wall: wall,
      spent_usd: 0,
      compile_count: 0,
      debits: [],
      confirmation: whoRec.confirmation,
    };

    const event = {
      kind: 'envelope_confirmed',
      envelope_id,
      client_event_id: clientEventId,
      who,
      terms_hash: expectedHash,
      max_spend_usd: ENVELOPE_MAX_SPEND_USD,
      max_compiles: ENVELOPE_MAX_COMPILES,
      ttl_minutes: ENVELOPE_TTL_MINUTES,
      at: wall,
      mono_ms: mono,
      seq,
    };

    const next = {
      ...ledger,
      schema: ENVELOPE_SCHEMA_ID,
      envelopes: [...ledger.envelopes, envelope],
      events: [...ledger.events, event],
      next_seq: seq + 1,
    };

    return {
      ok: true,
      idempotent: false,
      already_confirmed: false,
      envelope,
      event,
      ledger: next,
      client_event_id: clientEventId,
      message: describeEnvelopeTerms(terms, who.claimed),
    };
  });
}

/**
 * Human-readable terms line, honest about an unlimited bound.
 * @param {object} terms
 * @param {string} whoClaimed
 */
export function describeEnvelopeTerms(terms = {}, whoClaimed = 'you') {
  const spend = Number(terms.max_spend_usd ?? ENVELOPE_MAX_SPEND_USD);
  const compiles = terms.max_compiles;
  const turnsPart =
    compiles === null ? 'unlimited turns' : `${Number(compiles)} turns`;
  return (
    `Session budget confirmed by ${whoClaimed} — $${spend.toFixed(2)} / ${turnsPart} / `
    + `${Number(terms.ttl_minutes ?? ENVELOPE_TTL_MINUTES)} min. `
    + 'I stop and check with you when the spend cap is reached.'
  );
}

/**
 * RAISE the live envelope's spend cap — the human "go past it" act.
 *
 * WHY THIS EXISTS (John, 2026-08-04): "the user should be able also to tell the steward
 * to go past the envelope". Hitting a cap mid-conversation should be a CHECKPOINT, not a
 * wall — the steward stops, reports what it has spent, and John decides whether to carry
 * on. That decision is still a human confirmation, so the law ("nothing spent without
 * human confirmation") holds: the cap moves only because he said so, and the move is
 * recorded on the ledger with who and when.
 *
 * Raising is deliberately one-directional per call and always explicit — there is no
 * auto-extend, because an envelope that silently grows is not a budget.
 *
 * @param {string} projectRoot
 * @param {{ who: string|object, max_spend_usd: number, client_event_id?: string, at?: string,
 *           monoNow?: () => number, wallNow?: () => string|number }} opts
 */
export function raiseSessionEnvelope(projectRoot, opts = {}) {
  const who = normalizeClaimedWho(opts.who);
  if (!who) {
    return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
      error: 'who-required',
      message: 'Raising the budget is a human decision — pass who.',
    });
  }
  const nextMax = Number(opts.max_spend_usd);
  if (!Number.isFinite(nextMax) || nextMax <= 0) {
    return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
      error: 'bad-max-spend',
      message: 'Raising the budget needs a positive dollar cap.',
    });
  }
  const { monoNow, wallNow } = resolveClocks(opts);
  const mono = monoNow();
  const wall = opts.at ?? wallNow();
  const clientEventId = opts.client_event_id ?? `envelope-raise-${mono}`;

  return withEnvelopeLedger(projectRoot, (ledger) => {
    if (!Array.isArray(ledger.envelopes) || ledger.envelopes.length === 0) {
      return envelopeFailure(ENVELOPE_CODE.ABSENT, { error: 'envelope-absent' });
    }
    const prior = ledger.events?.find((e) => e && e.client_event_id === clientEventId);
    if (prior) {
      return { ok: true, idempotent: true, skip_write: true, client_event_id: clientEventId,
               message: 'Budget already raised (idempotent).' };
    }

    const idx = ledger.envelopes.length - 1;
    const env = { ...ledger.envelopes[idx] };
    const currentMax = boundOrUnlimited(env.max_spend_usd, ENVELOPE_MAX_SPEND_USD);
    if (Number.isFinite(currentMax) && nextMax <= currentMax) {
      return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
        error: 'not-a-raise',
        message:
          `The cap is already $${currentMax.toFixed(2)} — raising to `
          + `$${nextMax.toFixed(2)} would not lift it.`,
      });
    }

    // A TTL-expired envelope is not raised back to life: expiry is a different
    // question from budget, and reviving it here would quietly bypass the clock.
    if (isEnvelopeExpired(env, mono)) {
      return envelopeFailure(ENVELOPE_CODE.EXPIRED, {
        error: 'envelope-expired',
        message: 'This session budget has expired — confirm a fresh one rather than raising it.',
      });
    }

    env.max_spend_usd = nextMax;
    env.raises = [...(env.raises ?? []), {
      who, from_usd: Number.isFinite(currentMax) ? currentMax : null,
      to_usd: nextMax, at: wall, mono_ms: mono, client_event_id: clientEventId,
    }];

    const event = {
      kind: 'envelope_raised',
      envelope_id: env.envelope_id,
      client_event_id: clientEventId,
      who,
      from_usd: Number.isFinite(currentMax) ? currentMax : null,
      to_usd: nextMax,
      at: wall,
      mono_ms: mono,
    };
    const envelopes = [...ledger.envelopes];
    envelopes[idx] = env;

    return {
      ok: true,
      idempotent: false,
      envelope: env,
      event,
      ledger: { ...ledger, envelopes, events: [...ledger.events, event] },
      client_event_id: clientEventId,
      max_spend_usd: nextMax,
      spent_usd: Number(env.spent_usd) || 0,
      message:
        `Budget raised to $${nextMax.toFixed(2)} by ${who.claimed} — carrying on.`,
    };
  });
}

// ── Debit (authorize hook + cost model + live check) ───────────────────────

/**
 * Price a spend unit via the Wave-5 cost model (shown, not re-authorized).
 * @param {{ kind?: string, text?: string|object, tokens?: number, seat?: string }} input
 */
export function priceEnvelopeSpend(input = {}) {
  if (input.tokens != null) {
    return priceTokens(input.tokens, {
      seat: input.seat,
      rate_key: input.kind === 'reflection' ? 'default' : 'compile',
    });
  }
  return priceCompile(input.text ?? input.compileInput ?? '', {
    seat: input.seat ?? 'compile',
  });
}

/**
 * Debit the live session envelope for a compile or reflection spend.
 *
 * Calls authorize('debit', ctx) — injected host hook (NS criterion 9).
 * Never reads ANCHOR_TOKEN. Prices through the deterministic cost model.
 * Each successful debit is SHOWN on the receipt.
 *
 * @param {string} projectRoot
 * @param {{
 *   kind?: string,
 *   text?: string|object,
 *   tokens?: number,
 *   seat?: string,
 *   auth?: object,
 *   monoNow?: () => number,
 *   wallNow?: () => string|number,
 *   client_event_id?: string,
 *   shown?: boolean,
 * }} opts
 */
export function debitSessionEnvelope(projectRoot, opts = {}) {
  // AUTH AT DEBIT VIA THE INJECTED AUTHORIZER HOOK — never a token check here.
  const authCtx = opts.auth && typeof opts.auth === 'object' ? opts.auth : {};
  const authDecision = authorize('debit', authCtx);
  if (!authDecision || authDecision.ok !== true) {
    return envelopeFailure(ENVELOPE_CODE.AUTH_REFUSED, {
      error: 'auth-refused',
      auth: authDecision ?? { ok: false, code: 'auth-missing-decision' },
      spent: false,
      debited: false,
    });
  }

  // REAL COST WINS (John, 2026-08-05: "$5 is way too low ... it's really not priced
  // well"). The synthetic accounting unit made a dollar cap meaningless — a compile
  // "cost" $0.00005 while the seat actually billed cents. When the caller knows the
  // real number (the conversational path gets `total_cost_usd` back from the seat),
  // that is what is debited, so a $50 cap means $50.
  const realCost = Number(opts.cost_usd);
  const hasRealCost = Number.isFinite(realCost) && realCost >= 0;
  const pricing = hasRealCost
    ? {
      cost_usd: realCost,
      tokens: Number(opts.tokens) || 0,
      rate_key: 'measured',
      rate_usd_per_1k: null,
      synthetic: false,
      disclaimer: 'MEASURED — reported by the seat transport for this call',
    }
    : priceEnvelopeSpend(opts);
  const cost = Number(pricing.cost_usd) || 0;
  const kind = opts.kind ?? 'compile';
  const { monoNow, wallNow } = resolveClocks(opts);
  const mono = monoNow();
  const wall = wallNow();

  return withEnvelopeLedger(projectRoot, (ledger) => {
    if (!Array.isArray(ledger.envelopes)) {
      return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
        error: 'ledger-gap',
      });
    }
    if (ledger.envelopes.length === 0) {
      return envelopeFailure(ENVELOPE_CODE.ABSENT, {
        error: 'envelope-absent',
      });
    }

    const idx = ledger.envelopes.length - 1;
    const env = { ...ledger.envelopes[idx] };
    const bal = envelopeBalance(env, mono);
    if (!bal.live) {
      if (bal.code === ENVELOPE_CODE.EXPIRED) {
        return envelopeFailure(ENVELOPE_CODE.EXPIRED, {
          error: 'envelope-expired',
          balance: bal,
        });
      }
      if (bal.code === ENVELOPE_CODE.EXHAUSTED) {
        return envelopeFailure(ENVELOPE_CODE.EXHAUSTED, {
          error: 'envelope-exhausted',
          balance: bal,
        });
      }
      return envelopeFailure(ENVELOPE_CODE.ABSENT, {
        error: 'envelope-absent',
        balance: bal,
      });
    }

    // Would this debit push past a bound?
    const nextSpent = (Number(env.spent_usd) || 0) + cost;
    const nextCompiles = (Number(env.compile_count) || 0) + 1;
    const maxSpend = boundOrUnlimited(env.max_spend_usd, ENVELOPE_MAX_SPEND_USD);
    const maxCompiles = boundOrUnlimited(env.max_compiles, ENVELOPE_MAX_COMPILES);
    // Exhausted means already at/over bound; refuse when the debit cannot fit
    // under remaining capacity. A debit that would exceed spend bound refuses
    // (hard stop). Compile count increments per debit unit.
    if (
      (Number(env.spent_usd) || 0) >= maxSpend
      || (Number(env.compile_count) || 0) >= maxCompiles
    ) {
      return envelopeFailure(ENVELOPE_CODE.EXHAUSTED, {
        error: 'envelope-exhausted',
        balance: bal,
      });
    }
    // If remaining spend is zero-ish and cost > remaining, still allow when
    // remaining > 0? Plan: exhaustion hard-stops. Refuse when nextSpent would
    // exceed max (strict) OR when compile count would exceed max.
    if (nextCompiles > maxCompiles) {
      return envelopeFailure(ENVELOPE_CODE.EXHAUSTED, {
        error: 'envelope-exhausted',
        balance: bal,
        bound: 'compiles',
      });
    }
    if (nextSpent > maxSpend + 1e-12) {
      return envelopeFailure(ENVELOPE_CODE.EXHAUSTED, {
        error: 'envelope-exhausted',
        balance: bal,
        bound: 'spend',
      });
    }

    const debitSeq = (env.debits?.length ?? 0) + 1;
    const shown = {
      kind,
      cost_usd: cost,
      tokens: pricing.tokens,
      rate_key: pricing.rate_key,
      rate_usd_per_1k: pricing.rate_usd_per_1k,
      // Honest about which currency this receipt is in: a measured debit must not
      // claim to be a synthetic accounting unit, or the ledger lies about real money.
      synthetic: pricing.synthetic !== false,
      disclaimer: pricing.disclaimer,
      at: wall,
      mono_ms: mono,
      debit_seq: debitSeq,
      client_event_id: opts.client_event_id ?? null,
    };

    const debitRecord = {
      ...shown,
      auth_provenance:
        authDecision.provenance
        ?? authDecision.code
        ?? 'injected-authorizer',
      auth_code: authDecision.code ?? null,
    };

    env.spent_usd = Math.round(nextSpent * 1e8) / 1e8;
    env.compile_count = nextCompiles;
    env.debits = [...(env.debits ?? []), debitRecord];

    const event = {
      kind: 'envelope_debit',
      envelope_id: env.envelope_id,
      debit: debitRecord,
      spent_usd: env.spent_usd,
      compile_count: env.compile_count,
      at: wall,
      mono_ms: mono,
    };

    const envelopes = [...ledger.envelopes];
    envelopes[idx] = env;
    const next = {
      ...ledger,
      envelopes,
      events: [...ledger.events, event],
    };

    return {
      ok: true,
      debited: true,
      spent: true,
      shown,
      debit: debitRecord,
      envelope: env,
      event,
      ledger: next,
      pricing,
      auth: {
        ok: true,
        code: authDecision.code,
        provenance:
          authDecision.provenance
          ?? authDecision.code
          ?? 'injected-authorizer',
        seam: 'debit',
      },
      message:
        `Debit shown: ${kind} $${cost.toFixed(8)} synthetic `
        + `(spent $${env.spent_usd} / ${env.compile_count} compiles).`,
    };
  });
}

// ── Commissions NOT covered ────────────────────────────────────────────────

/**
 * Commissions are explicitly NOT covered by the session envelope.
 * A live envelope does not authorize a commission — own confirm required.
 * @returns {false}
 */
export function envelopeCoversCommission() {
  return false;
}

/**
 * Assert commission still needs its own confirmation inside a live envelope.
 * @param {{ envelope_live?: boolean, commission_confirmed?: boolean }} opts
 */
export function commissionRequiresOwnConfirmation(opts = {}) {
  const envelope_live = opts.envelope_live === true;
  const commission_confirmed = opts.commission_confirmed === true;
  return {
    ok: true,
    envelope_covers_commission: false,
    envelope_live,
    commission_confirmed,
    allowed: commission_confirmed === true,
    message: envelope_live && !commission_confirmed
      ? 'Live envelope does not authorize a commission — confirm the commission separately.'
      : commission_confirmed
        ? 'Commission has its own confirmation.'
        : 'Commission requires confirmation (envelope does not cover commissions).',
  };
}

// ── No-live-envelope path (gate decision 4) ────────────────────────────────

/**
 * Resolve what happens when spend is requested with no live envelope.
 *
 * ONLY `nl_polish_reflection_compile` queues as a typed event (S13).
 * Deterministic receipt + next-stage proposal are NEVER queued (zero-spend).
 * All other spend refuses as envelope-absent.
 *
 * @param {string} kind
 * @param {{ live?: boolean }} [state]
 */
export function resolveNoLiveEnvelopePath(kind, state = {}) {
  const live = state.live === true;
  if (live) {
    return {
      ok: true,
      action: 'debit',
      queue: false,
      kind,
      message: 'Live envelope — spend debits the budget (shown).',
    };
  }

  if (ZERO_SPEND_NEVER_QUEUE_KINDS.includes(kind)) {
    return {
      ok: true,
      action: 'emit_zero_spend',
      queue: false,
      kind,
      zero_spend: true,
      message:
        'Deterministic handback path — zero model, zero spend; never queued (gate decision 4).',
    };
  }

  if (kind === QUEUE_WITHOUT_ENVELOPE_KIND) {
    return {
      ok: true,
      action: 'queue',
      queue: true,
      kind,
      message:
        'No live envelope — NL-polish reflection compile queued as a typed event (S13).',
    };
  }

  return envelopeFailure(ENVELOPE_CODE.ABSENT, {
    error: 'envelope-absent',
    action: 'refuse',
    queue: false,
    kind,
  });
}

/**
 * Queue the model-authored NL-polish reflection compile as a typed event
 * when there is no live envelope. Does NOT debit. Deterministic receipt /
 * next-stage proposal must NOT call this.
 *
 * @param {string} projectRoot
 * @param {{ payload?: object, client_event_id?: string, monoNow?: () => number, wallNow?: () => string|number }} [opts]
 */
export function queueNlPolishReflectionCompile(projectRoot, opts = {}) {
  const pathDecision = resolveNoLiveEnvelopePath(QUEUE_WITHOUT_ENVELOPE_KIND, {
    live: false,
  });
  if (!pathDecision.queue) {
    return envelopeFailure(ENVELOPE_CODE.STATE_UNKNOWN, {
      error: 'queue-refused',
      detail: pathDecision,
    });
  }

  const { monoNow, wallNow } = resolveClocks(opts);
  const queued = withEnvelopeLedger(projectRoot, (ledger) => {
    const event = {
      kind: 'nl_polish_reflection_compile_queued',
      spend_kind: QUEUE_WITHOUT_ENVELOPE_KIND,
      client_event_id: opts.client_event_id ?? null,
      payload: opts.payload ?? null,
      at: wallNow(),
      mono_ms: monoNow(),
      zero_spend: true,
      queued: true,
    };
    const next = {
      ...ledger,
      events: [...ledger.events, event],
      queued: [...ledger.queued, event],
    };
    return {
      ok: true,
      queued: true,
      event,
      ledger: next,
      message: pathDecision.message,
    };
  });

  // T-ATT-CS5: queued NL-polish compile pending → publish at queue append.
  let attention_publish = null;
  if (queued?.ok && opts.skip_attention_publish !== true) {
    attention_publish = publishAttention(projectRoot, {
      // T-ATT-CS5
      call_site: ATTENTION_CALL_SITES.NL_POLISH_QUEUE,
      who: opts.who || 'session-envelope',
      at: queued.event?.at,
      skip_index: true,
      ledgerView: {
        nl_polish_queued: true,
        events: [{ kind: 'nl_polish_reflection_compile_queued', ...(queued.event || {}) }],
        at: queued.event?.at,
      },
      home: opts.home,
      env: opts.env,
      project_id: opts.project_id,
      skip_brief_cache: opts.skip_brief_cache === true,
    });
  }

  return {
    ...queued,
    attention_publish,
  };
}

/**
 * Attempt a spend-like action: debit if live, else apply gate-decision-4 path.
 *
 * @param {string} projectRoot
 * @param {{ kind: string, text?: string|object, tokens?: number, auth?: object, monoNow?: () => number, wallNow?: () => string|number, client_event_id?: string, payload?: object }} opts
 */
export function attemptEnvelopeSpend(projectRoot, opts = {}) {
  const kind = opts.kind ?? 'compile';
  const state = readEnvelopeState(projectRoot, opts);
  if (!state.ok && state.code === ENVELOPE_CODE.LEDGER_UNREADABLE) {
    return state;
  }
  if (!state.ok && state.code === ENVELOPE_CODE.STATE_UNKNOWN) {
    return state;
  }

  const live = state.live === true;
  const pathDecision = resolveNoLiveEnvelopePath(kind, { live });

  if (pathDecision.action === 'debit') {
    return debitSessionEnvelope(projectRoot, opts);
  }
  if (pathDecision.action === 'emit_zero_spend') {
    return {
      ok: true,
      action: 'emit_zero_spend',
      queue: false,
      zero_spend: true,
      kind,
      debited: false,
      spent: false,
      message: pathDecision.message,
    };
  }
  if (pathDecision.action === 'queue') {
    return queueNlPolishReflectionCompile(projectRoot, opts);
  }
  return pathDecision;
}

// ── T-BND-08: machine-checked bound vs calibration ─────────────────────────

/**
 * T-BND-08 — import cost-model.json + calibration; check
 * ENVELOPE_MAX_SPEND_USD >= 3 × p90(compile_cost).
 *
 * @param {{
 *   costModel?: object,
 *   calibration?: object,
 *   costModelPath?: string,
 *   calibrationPath?: string,
 *   skillRoot?: string,
 * }} [opts]
 */
export function checkEnvelopeBoundRelation(opts = {}) {
  let costModel = opts.costModel;
  let calibration = opts.calibration;

  if (!costModel && opts.costModelPath) {
    costModel = JSON.parse(fs.readFileSync(opts.costModelPath, 'utf8'));
  }
  if (!calibration && opts.calibrationPath) {
    calibration = JSON.parse(fs.readFileSync(opts.calibrationPath, 'utf8'));
  }

  // Prefer explicit skillRoot relative artifacts when provided
  if (opts.skillRoot) {
    const root = opts.skillRoot;
    if (!costModel) {
      const p = path.join(root, 'artifacts', 'cost-model.json');
      if (fs.existsSync(p)) {
        costModel = JSON.parse(fs.readFileSync(p, 'utf8'));
      }
    }
    if (!calibration) {
      const p = path.join(root, 'artifacts', 'compile-cost-calibration.json');
      if (fs.existsSync(p)) {
        calibration = JSON.parse(fs.readFileSync(p, 'utf8'));
      }
    }
  }

  const p90 =
    calibration?.p90
    ?? calibration?.envelope_relation?.p90
    ?? costModel?.calibration?.p90
    ?? costModel?.calibration?.envelope_relation?.p90
    ?? null;

  if (p90 == null || !Number.isFinite(Number(p90))) {
    return {
      ok: false,
      test_id: 'T-BND-08',
      error: 'calibration-p90-missing',
      message: 'T-BND-08 requires p90(compile_cost) from the calibration record.',
    };
  }

  const relation = envelopeCoversP90(Number(p90), ENVELOPE_MAX_SPEND_USD);
  return {
    ok: relation.ok === true,
    test_id: 'T-BND-08',
    relation: relation.relation,
    envelope_max_spend_usd: ENVELOPE_MAX_SPEND_USD,
    envelope_max_compiles: ENVELOPE_MAX_COMPILES,
    envelope_ttl_minutes: ENVELOPE_TTL_MINUTES,
    p90: relation.p90,
    required: relation.required,
    cost_model_schema: costModel?.schema ?? null,
    calibration_n: calibration?.n ?? costModel?.calibration?.n ?? null,
    message: relation.ok
      ? `T-BND-08 holds: ${ENVELOPE_MAX_SPEND_USD} >= 3 × ${relation.p90}`
      : `T-BND-08 FAIL: envelope ${ENVELOPE_MAX_SPEND_USD} < required ${relation.required}`,
  };
}
