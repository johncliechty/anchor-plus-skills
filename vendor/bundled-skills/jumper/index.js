import fs from 'node:fs';
import os from 'node:os';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import {
  runAgent,
  loadModelFamilies,
  familyToDriverName,
  normalizeRole,
  isVerificationRole,
} from '../../../trio/drivers/index.mjs';
import {
  lookinAppendix,
  superviseSeat,
  trailFromFile,
} from '../../../trio/drivers/swarm-lookin.mjs';
import { applySeamPass } from '../gandalf/runtime/seam-pass.mjs';
import { createCommissionLedger } from '../gandalf/seam/commission-ledger.mjs';
import {
  runLiveRefutation,
  buildLiveRefuterAgent,
  DEFAULT_REFUTER_ROUTES,
  DRAFTER_FAMILY,
  REFUTER_FAMILY,
  familyFromDriver,
  SelfRefutationHalt,
} from '../gandalf/runtime/live-refuter.mjs';
// 2026-08-19 (journal 0031, third RefuterBudgetHalt tournament kill after 0003/0012):
// the compose seam CAPS refuter demand at the budget instead of letting gandalf's
// HALT destroy the whole paid tournament. firesRefuter/REFUTER_BUDGET_R are the same
// primitives runLiveRefutation uses, so the cap counts exactly what the HALT counts.
import {
  firesRefuter,
  REFUTER_BUDGET_R,
  RefuterBudgetHalt,
} from '../gandalf/seam/refute.mjs';

// Re-export family map for hermetic Gate-3 seating smokes (B3-G3-LITE-SEATING).
export { familyFromDriver };

const JUMPER_SEATING_SCHEMA = 'jumper.seating.v1';
const SEAT_FAMILIES = new Set(['claude', 'gemini', 'grok', 'chatgpt']);
const FIXED_CODING_IDS = new Set([
  'coding:gandalf-draft',
  'coding:synthesizer:peterson-input',
  'coding:peterson',
  'coding:synthesizer:hesse-input',
  'coding:gep',
]);

function combinedSignal(...signals) {
  const live = signals.filter((signal) => signal && typeof signal === 'object');
  if (live.length === 0) return undefined;
  if (live.length === 1) return live[0];
  return AbortSignal.any(live);
}

function throwIfAborted(signal) {
  if (!signal?.aborted) return;
  throw signal.reason instanceof Error
    ? signal.reason
    : new DOMException('The Jumper dispatch was aborted', 'AbortError');
}

function dispatchOrder(id) {
  const fixed = new Map([
    ['coding:gandalf-draft', 0],
    ['coding:synthesizer:peterson-input', 1],
    ['coding:peterson', 2],
    ['coding:synthesizer:hesse-input', 3],
    ['coding:gep', 1_000_000],
  ]);
  if (fixed.has(id)) return fixed.get(id);
  const candidate = /^coding:r(\d+):c(\d+):(hesse|synthesizer-dirac|dirac|gate12)$/.exec(id);
  if (candidate) {
    const phase = { hesse: 0, 'synthesizer-dirac': 1, dirac: 2, gate12: 3 }[candidate[3]];
    return 10_000 + Number(candidate[1]) * 1_000 + Number(candidate[2]) * 10 + phase;
  }
  const verdict = /^gate3:r(\d+):c(\d+):verdict$/.exec(id);
  if (verdict) return Number(verdict[1]) * 1_000 + Number(verdict[2]);
  return 2_000_000;
}

function cloneDispatchSlots(slots) {
  return [...slots]
    .sort((a, b) => dispatchOrder(a.dispatch_id) - dispatchOrder(b.dispatch_id)
      || a.dispatch_id.localeCompare(b.dispatch_id))
    .map((slot) => ({
      dispatch_id: slot.dispatch_id,
      logical_attempts: slot.logical_attempts.map(({ ordinal, receipt }) => ({
        ordinal,
        receipt: normalizeTrioSeatReceipt(receipt),
      })),
    }));
}

function modelSlots(slots) {
  return slots.map((slot) => ({
    dispatch_id: slot.dispatch_id,
    logical_attempts: slot.logical_attempts.map(({ ordinal, receipt }) => {
      const served = receipt?.served;
      return {
        ordinal,
        driver: served?.driver ?? null,
        family: served?.family ?? null,
        model: served?.model ?? null,
      };
    }),
  }));
}

function receiptFamily(receipt) {
  return typeof receipt?.served?.family === 'string'
    ? receipt.served.family.trim().toLowerCase()
    : null;
}

function validDispatchId(kind, dispatchId) {
  if (typeof dispatchId !== 'string' || dispatchId.length === 0 || dispatchId.length > 240) return false;
  if (kind === 'ping') return dispatchId === 'gate3:ping';
  if (kind === 'verdict') return /^gate3:r[1-9]\d*:c[1-9]\d*:verdict$/.test(dispatchId);
  if (kind === 'coding') {
    return FIXED_CODING_IDS.has(dispatchId)
      || /^coding:r[1-9]\d*:c[1-9]\d*:(hesse|synthesizer-dirac|dirac|gate12)$/.test(dispatchId);
  }
  return false;
}

function cloneReceipt(receipt) {
  if (receipt == null) return null;
  try { return structuredClone(receipt); }
  catch { return null; }
}

const TRIO_TOP_KEYS = [
  'schema', 'ok', 'status', 'label', 'role', 'verification', 'structured',
  'requested', 'served', 'attempts', 'failover', 'error',
];
const TRIO_ATTEMPT_KEYS = [
  'ordinal', 'kind', 'requested', 'ok', 'status', 'served',
  'transport_attempts', 'error',
];
const TRIO_TRANSPORT_KEYS = [
  'ordinal', 'kind', 'label', 'ok', 'status', 'provider_status', 'served', 'error',
];
const TRIO_REQUESTED_KEYS = ['driver', 'family', 'model'];
const TRIO_SERVED_KEYS = [
  'driver', 'family', 'model', 'family_attested', 'model_attested',
];
const TRIO_FAILOVER_KEYS = ['allowed', 'used', 'blocked_reason'];
const TRIO_ERROR_KEYS = ['code', 'message'];
const REQUESTED_FAMILIES = new Set([...SEAT_FAMILIES, 'unknown']);
const TOP_STATUSES = new Set([
  'success', 'success_after_failover', 'seat_unavailable',
  'verification_fail_closed', 'aborted',
]);
const DISPATCH_STATUSES = new Set([
  'success', 'success_after_schema_reprompt', 'schema_exhausted',
  'seat_unavailable', 'aborted',
]);
const TRANSPORT_STATUSES = new Set([
  'accepted', 'schema_rejected', 'seat_unavailable', 'aborted',
]);

function hasExactKeys(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function isDenseTuple(value, min = 1, max = 2) {
  return Array.isArray(value)
    && value.length >= min
    && value.length <= max
    && Array.from({ length: value.length }, (_, index) => Object.hasOwn(value, index))
      .every(Boolean);
}

function isBoundedString(value) {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= 240
    && value === value.trim()
    && !/[\u0000-\u001f\u007f]/.test(value);
}

function isErrorInfo(value) {
  return hasExactKeys(value, TRIO_ERROR_KEYS)
    && isBoundedString(value.code)
    && typeof value.message === 'string'
    && value.message.length <= 500
    && !/[\u0000-\u001f\u007f]/.test(value.message);
}

function isRequested(value) {
  return hasExactKeys(value, TRIO_REQUESTED_KEYS)
    && isBoundedString(value.driver)
    && REQUESTED_FAMILIES.has(value.family)
    && (value.model === null || typeof value.model === 'string');
}

function isServed(value) {
  return hasExactKeys(value, TRIO_SERVED_KEYS)
    && isBoundedString(value.driver)
    && (value.family === null || SEAT_FAMILIES.has(value.family))
    && (value.model === null || typeof value.model === 'string')
    && typeof value.family_attested === 'boolean'
    && typeof value.model_attested === 'boolean'
    && value.family_attested === (value.family !== null)
    && (value.model_attested
      ? typeof value.model === 'string' && value.model.length > 0
      : value.model === null);
}

function sameRequested(left, right) {
  return left.driver === right.driver
    && left.family === right.family
    && left.model === right.model;
}

function sameServed(left, right) {
  return left !== null && right !== null
    && left.driver === right.driver
    && left.family === right.family
    && left.model === right.model
    && left.family_attested === right.family_attested
    && left.model_attested === right.model_attested;
}

function isTransportAttempt(value, ordinal) {
  if (!hasExactKeys(value, TRIO_TRANSPORT_KEYS)
      || value.ordinal !== ordinal
      || value.kind !== (ordinal === 1 ? 'initial' : 'schema_reprompt')
      || !isBoundedString(value.label)
      || typeof value.ok !== 'boolean'
      || !TRANSPORT_STATUSES.has(value.status)
      || !(value.provider_status === null || typeof value.provider_status === 'string')
      || !(value.served === null || isServed(value.served))
      || !(value.error === null || isErrorInfo(value.error))
      || value.ok !== (value.status === 'accepted')) return false;
  if (value.status === 'accepted') return value.served !== null && value.error === null;
  if (value.status === 'schema_rejected') {
    return value.served !== null
      && value.error?.code === 'schema_nonconforming';
  }
  return value.error !== null;
}

function isDispatcherAttempt(value, ordinal, verification) {
  if (!hasExactKeys(value, TRIO_ATTEMPT_KEYS)
      || value.ordinal !== ordinal
      || value.kind !== (ordinal === 1 ? 'primary' : 'fallback')
      || !isRequested(value.requested)
      || typeof value.ok !== 'boolean'
      || !DISPATCH_STATUSES.has(value.status)
      || !(value.served === null || isServed(value.served))
      || !(value.error === null || isErrorInfo(value.error))
      || !isDenseTuple(value.transport_attempts)
      || !Array.from(value.transport_attempts)
        .every((child, index) => isTransportAttempt(child, index + 1))) {
    return false;
  }
  if (value.transport_attempts.length === 2
      && value.transport_attempts[0].status !== 'schema_rejected') return false;
  const last = value.transport_attempts[value.transport_attempts.length - 1];
  if (value.ok) {
    const expected = value.transport_attempts.length === 2
      ? 'success_after_schema_reprompt'
      : 'success';
    return value.status === expected
      && last.status === 'accepted'
      && value.served !== null
      && sameServed(value.served, last.served)
      && value.error === null;
  }
  if (value.served !== null || value.error === null) return false;
  if (value.status === 'aborted') return last.status === 'aborted';
  if (value.status === 'schema_exhausted') {
    return value.transport_attempts.length === 2
      && Array.from(value.transport_attempts)
        .every((child) => child.status === 'schema_rejected');
  }
  if (value.status !== 'seat_unavailable'
      || last.status === 'aborted'
      || (value.transport_attempts.length === 2
        && Array.from(value.transport_attempts)
          .every((child) => child.status === 'schema_rejected'))) return false;
  if (last.status !== 'accepted') return true;
  return verification
    && (!last.served.family_attested || !last.served.model_attested)
    && value.error.code === 'served_unattested';
}

function isTrioSeatReceipt(value) {
  if (!hasExactKeys(value, TRIO_TOP_KEYS)
      || value.schema !== 'trio.seat.v1'
      || typeof value.ok !== 'boolean'
      || !TOP_STATUSES.has(value.status)
      || !isBoundedString(value.label)
      || !(value.role === null || typeof value.role === 'string')
      || normalizeRole({ role: value.role, label: value.label }) !== value.role
      || typeof value.verification !== 'boolean'
      || value.verification !== isVerificationRole({ role: value.role, label: value.label })
      || typeof value.structured !== 'boolean'
      || !isRequested(value.requested)
      || !(value.served === null || isServed(value.served))
      || !isDenseTuple(value.attempts)
      || !Array.from(value.attempts).every((attempt, index) =>
        isDispatcherAttempt(attempt, index + 1, value.verification))
      || !sameRequested(value.requested, value.attempts[0].requested)
      || !hasExactKeys(value.failover, TRIO_FAILOVER_KEYS)
      || typeof value.failover.allowed !== 'boolean'
      || typeof value.failover.used !== 'boolean'
      || !['verification_seat', 'no_capable_fallback', null].includes(value.failover.blocked_reason)
      || !(value.error === null || isErrorInfo(value.error))) return false;

  if (!value.structured && Array.from(value.attempts).some((attempt) =>
    attempt.transport_attempts.length !== 1
      || Array.from(attempt.transport_attempts)
        .some((child) => child.status === 'schema_rejected')
      || ['success_after_schema_reprompt', 'schema_exhausted'].includes(attempt.status))) return false;
  if (value.failover.allowed !== !value.verification
      || value.failover.used !== (value.attempts.length === 2)) return false;
  if (value.verification) {
    if (value.attempts.length !== 1
        || value.failover.blocked_reason !== 'verification_seat') return false;
  } else {
    const expectedBlocked = value.attempts.length === 1
      && !value.attempts[0].ok
      && value.attempts[0].status !== 'aborted'
      && value.status === 'seat_unavailable'
      ? 'no_capable_fallback'
      : null;
    if (value.failover.blocked_reason !== expectedBlocked) return false;
  }
  if (value.attempts.length === 2) {
    if (value.verification
        || value.attempts[0].ok
        || !['schema_exhausted', 'seat_unavailable'].includes(value.attempts[0].status)) return false;
  }

  const finalAttempt = value.attempts[value.attempts.length - 1];
  const expectedStatuses = value.attempts.length === 2
    ? [finalAttempt.ok ? 'success_after_failover'
      : (finalAttempt.status === 'aborted' ? 'aborted' : 'seat_unavailable')]
    : (finalAttempt.ok ? ['success']
      : (finalAttempt.status === 'aborted' ? ['aborted']
        : (value.verification ? ['verification_fail_closed'] : ['seat_unavailable', 'aborted'])));
  if (!expectedStatuses.includes(value.status)
      || value.ok !== ['success', 'success_after_failover'].includes(value.status)) return false;
  if (value.ok) {
    return value.served !== null
      && sameServed(value.served, finalAttempt.served)
      && value.error === null
      && (!value.verification
        || (value.served.family_attested && value.served.model_attested));
  }
  return value.served === null
    && value.error !== null;
}

function normalizeTrioSeatReceipt(receipt) {
  const cloned = cloneReceipt(receipt);
  return isTrioSeatReceipt(cloned) ? cloned : null;
}

function receiptSupportsIndependence(receipt, verification) {
  return receipt?.schema === 'trio.seat.v1'
    && receipt.ok === true
    && receipt.verification === verification
    && receipt.failover?.used === false
    && receipt.served?.family_attested === true
    && receipt.served?.model_attested === true
    && typeof receipt.served?.driver === 'string'
    && receipt.served.driver.trim().length > 0
    && SEAT_FAMILIES.has(receiptFamily(receipt))
    && typeof receipt.served?.model === 'string'
    && receipt.served.model.trim().length > 0;
}

/**
 * Mutable run-local ledger whose snapshots are the exact `jumper.seating.v1`
 * contract. Attempts settle once; a late callback cannot overwrite an aborted
 * or failed logical receipt.
 */
export class JumperSeatingLedger {
  constructor() {
    this.coding = [];
    this.ping = null;
    this.verdicts = [];
  }

  _collection(kind) {
    if (kind === 'coding') return this.coding;
    if (kind === 'verdict') return this.verdicts;
    if (kind === 'ping') {
      if (!this.ping) this.ping = { dispatch_id: 'gate3:ping', logical_attempts: [] };
      return [this.ping];
    }
    throw new TypeError(`unknown Jumper seating collection ${JSON.stringify(kind)}`);
  }

  begin(kind, dispatchId) {
    if (!validDispatchId(kind, dispatchId)) {
      throw new TypeError(`invalid Jumper ${kind} dispatch ID ${JSON.stringify(dispatchId)}`);
    }
    const collection = this._collection(kind);
    let slot = collection.find((entry) => entry.dispatch_id === dispatchId);
    if (!slot) {
      slot = { dispatch_id: dispatchId, logical_attempts: [] };
      collection.push(slot);
    }
    if (slot.logical_attempts.length >= 2) {
      throw new RangeError(`Jumper dispatch ${dispatchId} cannot exceed two logical attempts`);
    }
    const attempt = {
      ordinal: slot.logical_attempts.length + 1,
      receipt: null,
      settled: false,
    };
    slot.logical_attempts.push(attempt);
    return { kind, dispatch_id: dispatchId, ordinal: attempt.ordinal, attempt };
  }

  settle(ref, receipt = null) {
    if (!ref?.attempt || ref.attempt.settled) return false;
    ref.attempt.receipt = normalizeTrioSeatReceipt(receipt);
    ref.attempt.settled = true;
    return true;
  }

  snapshot() {
    const coding = cloneDispatchSlots(this.coding);
    const verdicts = cloneDispatchSlots(this.verdicts);
    const ping = this.ping ? cloneDispatchSlots([this.ping])[0] : null;
    const models = {
      coding: modelSlots(coding),
      gate3: {
        ping: ping ? modelSlots([ping])[0] : null,
        verdicts: modelSlots(verdicts),
      },
    };
    const codingAttempts = coding.flatMap((slot) => slot.logical_attempts);
    const verdictAttempts = verdicts.flatMap((slot) => slot.logical_attempts);
    const pingAttempts = ping?.logical_attempts ?? [];
    const codingFamilies = new Set();
    const gate3Families = new Set();
    const codingOk = codingAttempts.length > 0 && codingAttempts.every(({ receipt }) => {
      const ok = receiptSupportsIndependence(receipt, false);
      if (ok) codingFamilies.add(receiptFamily(receipt));
      return ok;
    });
    const gate3Ok = verdictAttempts.length > 0
      && [...pingAttempts, ...verdictAttempts].every(({ receipt }) => {
        const ok = receiptSupportsIndependence(receipt, true);
        if (ok) gate3Families.add(receiptFamily(receipt));
        return ok;
      });
    const disjoint = [...codingFamilies].every((family) => !gate3Families.has(family));
    return {
      schema: JUMPER_SEATING_SCHEMA,
      coding,
      gate3: { ping, verdicts },
      models,
      cross_model: codingOk && gate3Ok && disjoint,
    };
  }
}

export function createJumperSeatingLedger() {
  return new JumperSeatingLedger();
}

/** Run one logical Trio dispatch while collecting its final receipt on success or error. */
export async function runJumperDispatch({
  ledger,
  kind,
  dispatchId,
  runAgent: dispatchAgent,
  args,
  signal = null,
} = {}) {
  if (!(ledger instanceof JumperSeatingLedger)) {
    throw new TypeError('runJumperDispatch requires a JumperSeatingLedger');
  }
  if (typeof dispatchAgent !== 'function') {
    throw new TypeError('runJumperDispatch requires runAgent');
  }
  const ref = ledger.begin(kind, dispatchId);
  const upstreamReceipt = args?.onReceipt;
  try {
    const result = await dispatchAgent({
      ...args,
      signal: combinedSignal(signal, args?.signal),
      onReceipt: async (receipt) => {
        ledger.settle(ref, receipt);
        if (typeof upstreamReceipt === 'function') await upstreamReceipt(receipt);
      },
    });
    ledger.settle(ref, null);
    return result;
  } catch (error) {
    ledger.settle(ref, error?.receipt ?? null);
    throw error;
  }
}

export function createJumperDispatchAgent({ ledger, kind, dispatchId, runAgent: baseAgent, signal = null }) {
  return (args) => runJumperDispatch({
    ledger,
    kind,
    dispatchId,
    runAgent: baseAgent,
    args,
    signal,
  });
}

/** Per-supervisor-generation heartbeat isolation with a fresh mtime baseline. */
export function createCandidateHeartbeatTracker({
  runId,
  round,
  candidate,
  heartbeatDir = path.join(os.tmpdir(), 'jumper-lookin'),
} = {}) {
  let active = null;
  return {
    activate(attempt) {
      const dir = path.resolve(heartbeatDir, String(runId));
      fs.mkdirSync(dir, { recursive: true });
      active = {
        path: path.join(dir, `r${round}-c${candidate}-attempt${attempt + 1}.json`),
        baseline: Date.now(),
      };
      return { ...active };
    },
    getTrail() {
      if (!active) return null;
      const trail = trailFromFile(active.path);
      return trail && Number.isFinite(trail.mtime) && trail.mtime >= active.baseline
        ? trail
        : null;
    },
    current() { return active ? { ...active } : null; },
  };
}

// 2026-07: the REAL Gandalf protocol, embedded into the commission prompt the way
// Anchor's integration does it — gandalf's SKILL.md is not auto-discoverable by a
// spawned CLI sub-agent, so without this the "RUN Gandalf" instruction made the
// sub-agent IMPROVISE a Gandalf-shaped answer instead of running the protocol.
const _GANDALF_SKILL_MD = path.join(
  path.dirname(fileURLToPath(import.meta.url)), '..', 'gandalf', 'SKILL.md');
const _MAX_PROTOCOL_BYTES = 64 * 1024;
function readGandalfProtocol() {
  try {
    return fs.readFileSync(_GANDALF_SKILL_MD, 'utf8').slice(0, _MAX_PROTOCOL_BYTES);
  } catch {
    return ''; // honest degrade: the commission still runs, minus the embedded protocol
  }
}

/**
 * Persistent Synthesizer Subagent (Intuition & Oversight).
 * Guided by the 'Parable of the Oranges' lens, it oversees the ideation phases,
 * exercises proactive foresight, and injects steering flags into the Tripartite Engine.
 */
export class Synthesizer {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
    this.history = [];
  }

  /**
   * Receives state updates and runs intuitive oversight to generate steering flags.
   * @param {object} state - Current state of the Tripartite Engine.
   * @returns {Promise<{analysis: string, steeringFlags: string[]}>}
   */
  async update(state, options = {}) {
    this.history.push(state);

    const monitoring = options.monitoringAppendix || lookinAppendix();
    const systemPrompt = `You are the Jumper Persistent Synthesizer subagent.
Your role is to oversee the ideation process across three phases (Peterson Query, Hesse Glass Bead, Dirac Transfer).
You leverage frontier-model intuition to catch blind spots, synthesize cross-domain connections, and inject "steering flags" into the Tripartite Engine.

CRITICAL INSTRUCTION (The Oranges-Lens / Proactive Foresight):
You are explicitly guided by the Parable of the Oranges. You must exercise deeply contextual foresight.
${monitoring}
${options.nudge ? `CURRENT LOOK-IN NUDGE: ${options.nudge}` : ''}
Do NOT passively watch the frameworks execute or just list literal next steps.
Instead, anticipate the true underlying needs, look 2-3 steps ahead, and identify high-value, non-obvious connections across domains.

When provided with a state update, analyze it and output a set of steering flags.
Steering flags are directives or hints that steer the engine (e.g., suggesting a foreign domain to explore, highlighting a hidden contradiction, or pointing to a deeper systemic need).

You steer, but never decide. You cannot bypass the Tripartite Engine or the Kill-Filter. Keep your steering flags focused on enabling divergent thinking and structural integrity.`;

    // W2 (2026-07-11): send ONLY the immediately-previous state, never the whole
    // accumulated history — each state embeds full gandalfRead/peterson/hesse
    // payloads, so resending `history` compounded token bloat on every update.
    const prevState = this.history.length > 1 ? this.history[this.history.length - 2] : null;
    const prompt = `System Prompt:
${systemPrompt}

Current State of the Ideation Engine:
${JSON.stringify(state, null, 2)}

Previous State (immediately prior phase only — earlier history is not resent):
${JSON.stringify(prevState, null, 2)}

Provide your synthesis and output the steering flags.
Format your output as a JSON object with:
- "analysis": your reasoning and observations using the Parable of the Oranges lens.
- "steeringFlags": an array of strings, each being a steering flag containing non-literal, deep cross-domain guidance or foresight.`;

    const schema = {
      type: "object",
      properties: {
        analysis: { type: "string" },
        steeringFlags: {
          type: "array",
          items: { type: "string" }
        }
      },
      required: ["analysis", "steeringFlags"]
    };

    const customRunAgent = options.runAgent || this.runAgent || runAgent;

    const response = await customRunAgent({
      prompt,
      schema,
      driver: this.driver,
      freshContext: true,
      label: "Synthesizer",
      role: "synthesizer",
      signal: options.signal,
    });

    return response;
  }
}

// ─── W7 cross-family HALTs ─────────────────────────────────────────────────────
/** Thrown when Jumper's Gate-3 kill-filter verifier would resolve to the DRAFTER/ideation family
 *  (self-review). A NAMED class so a run HALTs honestly instead of a drafter grading its own idea —
 *  a same-family gate shares the generator's blind spots and earns no independent cross-family origin. */
export class JumperSelfReviewHalt extends Error {
  constructor(verifierFamily, drafterFamily, driver) {
    super(
      `Jumper Gate-3 self-review HALT: the adversarial verifier resolves to driver ${JSON.stringify(driver)} ` +
      `(family ${JSON.stringify(verifierFamily)}), which is the DRAFTER/ideation family ${JSON.stringify(drafterFamily)}. ` +
      `Gate 3 MUST run on a NON-drafter family selected by Anchor preferences. Route Gate 3 to a different ` +
      `family (JUMPER_GATE3_DRIVER / options.gate3Driver) or change the drafter driver.`
    );
    this.name = 'JumperSelfReviewHalt';
    this.verifier_family = verifierFamily;
    this.drafter_family = drafterFamily;
    this.driver = driver;
  }
}

/** Thrown when the selected cross-family Gate-3 verifier is unreachable. Jumper
 *  HALTs honestly rather than SILENTLY falling back to a same-family (self-review) gate — down verifier
 *  ⇒ HALT, never same-family self-review. */
export class JumperCrossFamilyDegradeHalt extends Error {
  constructor(driver, cause) {
    super(
      `Jumper Gate-3 cross-family HALT: the cross-family verifier (driver ${JSON.stringify(driver)}) was ` +
      `unreachable (${cause?.message ?? cause}). Refusing to fall back to a same-family self-review gate — ` +
      `the run HALTs honestly. Restore the cross-family backend or set JUMPER_GATE3_DRIVER to another ` +
      `non-drafter family.`
    );
    this.name = 'JumperCrossFamilyDegradeHalt';
    this.driver = driver;
    this.cause = cause;
    this.receipt = cause?.receipt ?? null;
  }
}

/**
 * Production-entry Gate-3 seating resolve (B3-G3 / W5).
 *
 * Same policy KillFilter uses at runtime: coding family → drafter, review family → Gate-3
 * verifier (unless JUMPER_GATE3_DRIVER / options.gate3Driver retargets the driver). LITE may
 * lean ideaRounds but never collapses this independence check.
 *
 * JUMPER_GATE3_DRIVER may retarget the verifier family; it must NEVER invent a
 * skip-independence / self-review mode. An injected gate3Agent is the only explicit
 * allowed override (hermetic tests / independent verifier stub).
 *
 * @param {{
 *   drafterDriver?: string | null,
 *   gate3Driver?: string | null,
 *   gate3Agent?: Function | null,
 *   env?: NodeJS.ProcessEnv,
 *   assertIndependent?: boolean,
 * }} [opts]
 * @returns {{
 *   drafterDriverName: string,
 *   drafterFamily: string,
 *   gate3DriverName: string,
 *   gate3Family: string | null,
 *   hasInjectedAgent: boolean,
 *   independent: boolean,
 *   substrate: string,
 *   prefsCoding: string,
 *   prefsReview: string,
 * }}
 */
export function resolveGate3Seating({
  drafterDriver = null,
  gate3Driver = null,
  gate3Agent = null,
  env = process.env,
  assertIndependent = true,
} = {}) {
  // Prefs: coding family for drafter/default; review family for Gate-3 verifier (unless pinned).
  // The shared resolver owns field-wise settings -> mirror -> historical-default
  // precedence. Malformed persisted state is a HALT, never an excuse to silently
  // substitute the historical families here.
  const fams = loadModelFamilies(env);
  const prefsCoding = fams.coding;
  const prefsReview = fams.review;
  const prefsCodingDriver = familyToDriverName(fams.coding) || 'claude';
  const prefsReviewDriver = familyToDriverName(fams.review) || 'gemini-cli';

  const drafterDriverName = drafterDriver || prefsCodingDriver;
  const drafterFamily = familyFromDriver(drafterDriverName) || prefsCoding;
  // Env/option may retarget the verifier driver; default is review-family (cross-family).
  // No env invents skip-independence — only a different family (or injected agent) is independent.
  const gate3DriverName =
    gate3Driver ?? env?.JUMPER_GATE3_DRIVER ?? prefsReviewDriver;
  const gate3Family = familyFromDriver(gate3DriverName) || prefsReview;
  const hasInjectedAgent = typeof gate3Agent === 'function';
  // Injected agent = explicit allowed override (already an independent verifier surface).
  // Driver seating is independent only when families differ.
  const independent =
    hasInjectedAgent || (!!gate3Family && gate3Family !== drafterFamily);

  const seating = {
    drafterDriverName,
    drafterFamily,
    gate3DriverName,
    gate3Family,
    hasInjectedAgent,
    independent: !!independent,
    substrate: `cross-family:${gate3DriverName}`,
    prefsCoding,
    prefsReview,
  };

  // Self-review guard applies to DRIVER seating (production / gate3Driver / prefs).
  // An injected gate3Agent is already an independent verifier — do not re-litigate
  // prefs coding===review against that injection.
  if (
    assertIndependent &&
    !hasInjectedAgent &&
    (!gate3Family || gate3Family === drafterFamily)
  ) {
    throw new JumperSelfReviewHalt(gate3Family, drafterFamily, gate3DriverName);
  }
  return seating;
}

/**
 * Grade a Gandalf RAW draft through the LIVE cross-family refuter lane (W7) — the mirror of gandalf's
 * `runHostLive`. ONE shared per-run ledger (invariant 1): a live (or injected-stub) Gemini refuter MINTS
 * claim-bound commissions into it, and `applySeamPass` RESOLVES against the SAME ledger, so a genuinely
 * cross-family-refuted, surviving elevation reaches GROUNDED with cross_model:true — DERIVED from the
 * unforgeable ledger, never self-asserted. Honest floor: absent a real refuter, elevations stay
 * SPECULATIVE (never a same-family self-review). Preserves the injected-agent seam (`refuterAgent` /
 * `ledger`) for deterministic tests; a self-review route is a hard HALT.
 *
 * @param {object} rawDraft  the model's raw Gandalf draft ({reasoning, verdict, ..., elevations[]})
 * @param {object} [options] refuterAgent, ledger, refuterRoutes, drafterFamily, refuterFamily, liveRefuter, log
 * @returns {Promise<object>} the conformant advisor output
 */
async function gradeGandalfDraftCrossFamily(rawDraft, options = {}) {
  const elevations = Array.isArray(rawDraft?.elevations) ? rawDraft.elevations : [];
  // Omit refuterRoutes → buildLiveRefuterAgent honors coding/review family prefs.
  const routes = options.refuterRoutes; // undefined unless caller pins
  const drafterFamily = options.drafterFamily; // undefined → prefs CODING_FAMILY
  const refuterFamily = options.refuterFamily || REFUTER_FAMILY;
  // INVARIANT 1 — ONE shared per-run ledger for BOTH the minter and the gate. A split ledger would make
  // every genuine cross-family mint a false negative (the gate can never authenticate an id it did not
  // see minted). `runLiveRefutation` mints into `ledger.mintCommission`; `applySeamPass` resolves via the
  // SAME `ledger.resolveCommission`.
  const ledger = options.ledger || createCommissionLedger();
  const resolveCommission = ledger.resolveCommission;

  // No elevations ⇒ nothing fires the refuter ⇒ a single deterministic grade (single-family floor).
  if (elevations.length === 0) {
    return applySeamPass(rawDraft, { resolveCommission });
  }

  // Resolve the refuter agent: an injected stub (tests) or the live prefs-aware cross-family agent.
  let refuterAgent = options.refuterAgent || null;
  if (!refuterAgent && options.liveRefuter !== false) {
    try {
      refuterAgent = await buildLiveRefuterAgent({ routes, drafterFamily, env: process.env });
    } catch (err) {
      // A self-review route is a HARD HALT (never silently self-review); any other build failure (agy
      // down / transport) honestly degrades to the SPECULATIVE floor below (no false cross-family grant).
      if (err instanceof SelfRefutationHalt) throw err;
      refuterAgent = null;
    }
  }
  if (refuterAgent && options.signal) {
    const underlyingRefuter = refuterAgent;
    refuterAgent = (prompt, agentOptions = {}) => underlyingRefuter(prompt, {
      ...agentOptions,
      signal: combinedSignal(options.signal, agentOptions.signal),
    });
  }
  if (!refuterAgent) {
    return applySeamPass(rawDraft, { resolveCommission }); // honest floor — no independent refuter ran
  }

  // Dispatch the live/stub refuter; mint claim-bound commissions into the SHARED ledger, then grade the
  // refuted draft against the SAME ledger's resolver — cross_model / GROUNDED are DERIVED here.
  // P1 2026-07-25 (journals 0003/0012): forward the refuter budget — the prereg R=3
  // ceiling HALTed whole tournaments (6 firing elevations > 3) with no dial to turn;
  // standalone gandalf has --budget but the compose seam never passed one through.
  //
  // 2026-08-19 (journal 0031 — THIRD tournament killed by RefuterBudgetHalt): the dial
  // was not enough; a run that omits --budget still died with output:null, destroying
  // the paid draft AND the tournament it feeds. Per the Elegance Law ("a guardrail is
  // never the whole product of a turn"), the JUMPER compose seam now CAPS demand at the
  // budget: the first `budget` firing elevations (draft order) are refuted for real;
  // the excess are HELD OUT of the refuter call and flow through the seam pass with NO
  // provenance, so gandalf's own machinery floors them to SPECULATIVE with the
  // "no independent refutation ran" stamp — explicitly stamped, never silently dropped,
  // never granted a tier. The output additionally carries `refutation_capped` naming
  // the numbers. Standalone gandalf keeps its HALT unchanged.
  const effectiveBudget = Number.isInteger(options.refuterBudget) && options.refuterBudget > 0
    ? options.refuterBudget : REFUTER_BUDGET_R;
  const firingIdx = [];
  elevations.forEach((e, i) => {
    if (e !== null && typeof e === 'object' && !Array.isArray(e) && firesRefuter(e)) firingIdx.push(i);
  });
  const log = typeof options.log === 'function' ? options.log : () => {};
  let refutationDraft = rawDraft;
  let heldOut = [];
  let capStamp = null;
  if (firingIdx.length > effectiveBudget) {
    const keep = new Set(firingIdx.slice(0, effectiveBudget));
    const firing = new Set(firingIdx);
    const refutable = [];
    elevations.forEach((e, i) => {
      if (firing.has(i) && !keep.has(i)) heldOut.push(e);
      else refutable.push(e);
    });
    refutationDraft = { ...rawDraft, elevations: refutable };
    capStamp = {
      requested: firingIdx.length,
      budget: effectiveBudget,
      refuted: effectiveBudget,
      floored_speculative: firingIdx.length - effectiveBudget,
      note: 'refutation capped at budget — excess firing elevations floored to SPECULATIVE with the '
        + '"no independent refutation ran" stamp (not silently dropped, not a HALT); pass --budget N to refute more',
    };
    log(`jumper: gandalf refutation CAPPED at budget (${firingIdx.length} firing > R=${effectiveBudget}) — `
      + `${heldOut.length} elevation(s) floored SPECULATIVE, run continues (journal 0031)`);
  }
  let draft;
  try {
    ({ draft } = await runLiveRefutation(refutationDraft, {
      agent: refuterAgent, ledger, routes, drafterFamily, refuterFamily, log: options.log,
      budget: effectiveBudget,
    }));
  } catch (err) {
    // Belt: the cap above makes this unreachable for RefuterBudgetHalt, but if the
    // firing count ever disagrees with gandalf's, NEVER destroy the paid draft —
    // skip refutation entirely (all elevations floor SPECULATIVE) and stamp why.
    if (!(err instanceof RefuterBudgetHalt)) throw err;
    log(`jumper: RefuterBudgetHalt intercepted at the compose seam (${err.requested} > R=${err.budget}) — `
      + 'refutation skipped, all elevations floored SPECULATIVE, run continues');
    const graded = applySeamPass(rawDraft, { resolveCommission });
    graded.refutation_capped = {
      requested: err.requested, budget: err.budget, refuted: 0,
      floored_speculative: elevations.length,
      note: 'RefuterBudgetHalt intercepted — no refutation ran; every elevation floored to SPECULATIVE (honest floor, not a HALT)',
    };
    return graded;
  }
  const mergedDraft = capStamp
    ? { ...draft, elevations: [...(Array.isArray(draft.elevations) ? draft.elevations : []), ...heldOut] }
    : draft;
  const graded = applySeamPass(mergedDraft, { resolveCommission });
  if (capStamp) graded.refutation_capped = capStamp;
  return graded;
}

/**
 * Programmatic interface to run the Gandalf skill on a given problem statement or artifact.
 * Prompts the model to generate a RAW draft, then grades it through the LIVE cross-family refuter lane
 * (W7): a Gandalf elevation can reach GROUNDED only via a genuine (Gemini) refutation minted into a
 * shared per-run ledger. Absent a real refuter, elevations honestly floor to SPECULATIVE.
 *
 * @param {string|object} problemState - The problem state or artifact to analyze.
 * @param {object} options - Custom driver / agent runners + refuter injection (useful for testing).
 * @returns {Promise<object>} The conformant advisor output schema.
 */
export async function runGandalf(problemState, options = {}) {
  const driver = options.driver || null;
  const customRunAgent = options.runAgent || runAgent;
  
  const protocol = readGandalfProtocol();
  const prompt = `You are invoking the Gandalf skill as a deep-think advisor lane for Jumper.
RUN the Gandalf protocol below EXACTLY as written (do NOT improvise your own version) over the
problem state/artifact, and return ONLY its RAW draft JSON object per the RAW-DRAFT contract —
do NOT self-assign honesty tiers/stamps (the deterministic seam pass grades those).
${protocol ? `\n=== THE GANDALF PROTOCOL (SKILL.md, verbatim) ===\n${protocol}\n=== END PROTOCOL ===\n` : '\n(protocol file unavailable — follow the RAW-DRAFT contract shape below)\n'}
Problem/Artifact to analyze:
${typeof problemState === 'string' ? problemState : JSON.stringify(problemState, null, 2)}`;

  const response = await customRunAgent({
    prompt,
    schema: {
      type: "object",
      properties: {
        reasoning: { type: "string" },
        verdict: { type: "string" },
        findings: { type: "array" },
        nitpicks: { type: "array" },
        elevations: { type: "array" }
      },
      required: ["reasoning", "verdict", "findings", "nitpicks", "elevations"]
    },
    driver,
    freshContext: true,
    label: "GandalfDraft",
    role: "gandalf",
    signal: options.signal,
  });

  // W7: the composed Gandalf deep-think lane inherits the cross-family refuter — a Gandalf elevation
  // can reach GROUNDED only via a genuine (Gemini) refutation minted into a shared per-run ledger.
  return gradeGandalfDraftCrossFamily(response, options);
}

/**
 * Phase 1: Peterson Query (Deconstruction & Probe).
 * Uses the SCAMPER framework to question the current state of the problem,
 * maps anomalous data, and identifies core contradictions from Gandalf's diagnosis.
 */
export class PetersonQuery {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
  }

  /**
   * Deconstructs the problem using Gandalf's advice and SCAMPER framework.
   * @param {object} gandalfRead - The structured advisor read output from runGandalf.
   * @param {object} [options] - Additional run options, including steeringFlags.
   * @returns {Promise<object>} The deconstructed problem map.
   */
  async run(gandalfRead, options = {}) {
    const steeringFlags = options.steeringFlags || [];
    const customRunAgent = options.runAgent || this.runAgent || runAgent;

    const systemPrompt = `You are Jumper Phase 1: Peterson Query (Deconstruction & Probe).
Your role is to deconstruct a problem using the SCAMPER framework, mapping anomalous data, challenging assumptions, and identifying core contradictions.

SCAMPER framework details:
- Substitute: What components, processes, or materials can be replaced?
- Combine: How can this problem/process be combined with other things?
- Adapt: What existing solutions or patterns from other domains can be adapted?
- Modify/Magnify: What elements can be magnified, minimized, or modified?
- Put to another use: How else could we use these constraints/features?
- Eliminate: What can we remove, simplify, or streamline?
- Reverse/Rearrange: What if we reversed the process or rearranged the components?

Analyze the structured Gandalf advisor diagnosis provided. Map any anomalous data points or unverified assumptions, and clearly define at least one core contradiction.`;

    const prompt = `System Prompt:
${systemPrompt}

Structured Gandalf Advisor Read:
${JSON.stringify(gandalfRead, null, 2)}

${options.monitoringAppendix ? `${options.monitoringAppendix}\n` : ''}${options.nudge ? `CURRENT LOOK-IN NUDGE: ${options.nudge}\n` : ''}
${steeringFlags.length > 0 ? `Active Steering Flags from Synthesizer:\n${steeringFlags.map(flag => `- ${flag}`).join('\n')}\n` : ''}
Provide your deconstructed problem map.
Format your output as a JSON object with:
- "anomalousData": array of strings mapping anomalous data points, hidden assumptions, or systemic vulnerabilities.
- "scamperAnalysis": object containing deconstruction analysis for each SCAMPER category:
  - "substitute": string
  - "combine": string
  - "adapt": string
  - "modify": string
  - "putToOtherUse": string
  - "eliminate": string
  - "reverse": string
- "coreContradictions": array of objects, each containing:
  - "description": clear description of a core conflict/contradiction (e.g. performance vs safety, statelessness vs durability).
  - "conflictingDemands": summary of the conflicting demands.`;

    const schema = {
      type: "object",
      properties: {
        anomalousData: {
          type: "array",
          items: { type: "string" }
        },
        scamperAnalysis: {
          type: "object",
          properties: {
            substitute: { type: "string" },
            combine: { type: "string" },
            adapt: { type: "string" },
            modify: { type: "string" },
            putToOtherUse: { type: "string" },
            eliminate: { type: "string" },
            reverse: { type: "string" }
          },
          required: ["substitute", "combine", "adapt", "modify", "putToOtherUse", "eliminate", "reverse"]
        },
        coreContradictions: {
          type: "array",
          items: {
            type: "object",
            properties: {
              description: { type: "string" },
              conflictingDemands: { type: "string" }
            },
            required: ["description", "conflictingDemands"]
          }
        }
      },
      required: ["anomalousData", "scamperAnalysis", "coreContradictions"]
    };

    const response = await customRunAgent({
      prompt,
      schema,
      driver: options.driver || this.driver,
      freshContext: true,
      label: "PetersonQuery",
      role: "deconstruct",
      signal: options.signal,
    });

    return response;
  }
}

export async function petersonQuery(gandalfRead, options = {}) {
  const query = new PetersonQuery(options);
  return query.run(gandalfRead, options);
}

/**
 * Phase 2: Hesse Glass Bead (Analogical Transfer).
 * Maps the Peterson Query deconstructed problem map onto a completely foreign domain structure.
 */
export class HesseGlassBead {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
  }

  /**
   * Maps the Peterson Query deconstructed problem map onto a foreign domain structure.
   * @param {object} problemMap - The deconstructed problem map from PetersonQuery.
   * @param {object} [options] - Additional run options, including steeringFlags.
   * @returns {Promise<object>} The analogical mapping.
   */
  async run(problemMap, options = {}) {
    const steeringFlags = options.steeringFlags || [];
    const customRunAgent = options.runAgent || this.runAgent || runAgent;

    const systemPrompt = `You are Jumper Phase 2: Hesse Glass Bead (Analogical Transfer).
Your role is to map a deconstructed problem map onto a completely foreign domain structure (e.g., mapping a software issue to a biological system, Renaissance art, music theory, or geological formations) to facilitate lateral, analogical thinking.

You must maintain structural integrity: ensure that the relationships, elements, and core contradictions in the original domain map logically and accurately onto the target foreign domain.

Analyze the deconstructed problem map provided (which includes anomalous data points, SCAMPER analysis, and core contradictions) and construct an analogical mapping.`;

    const prompt = `System Prompt:
${systemPrompt}

Deconstructed Problem Map:
${JSON.stringify(problemMap, null, 2)}

${options.monitoringAppendix ? `${options.monitoringAppendix}\n` : ''}${options.nudge ? `CURRENT LOOK-IN NUDGE: ${options.nudge}\n` : ''}
${steeringFlags.length > 0 ? `Active Steering Flags from Synthesizer:\n${steeringFlags.map(flag => `- ${flag}`).join('\n')}\n` : ''}
Provide your analogical mapping.
Format your output as a JSON object with:
- "foreignDomain": name of the target domain (e.g. "Renaissance Fresco Painting Techniques", "Biological Cell Membrane Structures", etc.).
- "analogyReasoning": detailed explanation of how this domain abstraction is relevant and how it helps reframe the problem.
- "structuralMapping": array of objects, each containing:
  - "originalElement": the element or relationship from the source problem/system.
  - "foreignElement": the corresponding element or relationship in the target foreign domain.
  - "mappingRationale": explanation of the structural similarity.
- "mappedContradictions": array of objects, each containing:
  - "originalContradiction": the contradiction description from the original problem.
  - "foreignContradiction": the corresponding contradiction expressed in the terms/constraints of the foreign domain.
  - "structuralParallel": explanation of why they share the same underlying structure.`;

    const schema = {
      type: "object",
      properties: {
        foreignDomain: { type: "string" },
        analogyReasoning: { type: "string" },
        structuralMapping: {
          type: "array",
          items: {
            type: "object",
            properties: {
              originalElement: { type: "string" },
              foreignElement: { type: "string" },
              mappingRationale: { type: "string" }
            },
            required: ["originalElement", "foreignElement", "mappingRationale"]
          }
        },
        mappedContradictions: {
          type: "array",
          items: {
            type: "object",
            properties: {
              originalContradiction: { type: "string" },
              foreignContradiction: { type: "string" },
              structuralParallel: { type: "string" }
            },
            required: ["originalContradiction", "foreignContradiction", "structuralParallel"]
          }
        }
      },
      required: ["foreignDomain", "analogyReasoning", "structuralMapping", "mappedContradictions"]
    };

    const response = await customRunAgent({
      prompt,
      schema,
      driver: options.driver || this.driver,
      freshContext: true,
      label: "HesseGlassBead",
      role: "analogy",
      signal: options.signal,
    });

    return response;
  }
}

export async function hesseGlassBead(problemMap, options = {}) {
  const bead = new HesseGlassBead(options);
  return bead.run(problemMap, options);
}

/**
 * Phase 3: Dirac Transfer (TRIZ Symmetry).
 * Uses TRIZ principles of invention to resolve the contradictions identified in Phase 1,
 * using the analogical insights generated in Phase 2.
 */
export class DiracTransfer {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
  }

  /**
   * Resolves the contradictions using TRIZ principles and the analogical insights.
   * @param {object} analogicalMapping - The analogical mapping from HesseGlassBead.
   * @param {array|object} [coreContradictionsOrOptions] - Core contradictions or options.
   * @param {object} [options] - Additional run options, including steeringFlags.
   * @returns {Promise<object>} The structurally elegant resolution.
   */
  async run(analogicalMapping, coreContradictionsOrOptions = {}, options = {}) {
    let coreContradictions = [];
    let runOptions = {};
    if (Array.isArray(coreContradictionsOrOptions)) {
      coreContradictions = coreContradictionsOrOptions;
      runOptions = options;
    } else {
      runOptions = { ...coreContradictionsOrOptions, ...options };
      coreContradictions = runOptions.coreContradictions || [];
    }

    const steeringFlags = runOptions.steeringFlags || [];
    const customRunAgent = runOptions.runAgent || this.runAgent || runAgent;

    const systemPrompt = `You are Jumper Phase 3: Dirac Transfer (Symmetry & Resolution).
Your role is to resolve the contradictions using TRIZ principles and the analogical insights from Phase 2.

TRIZ principles details:
TRIZ (Theory of Inventive Problem Solving) provides 40 principles to resolve physical and technical contradictions without compromise. Examples include:
- Segmentation (dividing an object/system into independent parts)
- Asymmetry (changing the shape or design to be asymmetrical)
- Merging/Consolidation (bringing identical or similar objects closer)
- Universality (making a part perform multiple functions)
- Nested Doll / Matryoshka (one object inside another)
- 'The other way round' (inverting the action or process)
- Dynamicity (allowing characteristics to change for optimal performance)
- Feedback (introducing control/feedback loops)
- Intermediary/Mediator (using an intermediate carrier or process)
- Discarding and recovering (making elements disappear or regenerate)

Analyze the analogical mapping (which includes foreignDomain, analogyReasoning, structuralMapping, and mappedContradictions) and any provided core contradictions. Output a structurally elegant resolution mapped back to the original domain.

THE INSTANTIATION LAW (journal 0028 RC-1 — six zero-survivor runs traced here):
your transfer is judged by what it DELIVERS. When the original problem statement
asks for concrete terminal artifacts (names, images, designs, strings, plans),
you must END by INSTANTIATING them — concrete, nameable, ready to hand to the
requester. A framework, methodology, grammar, or design-language WITHOUT its
instantiated artifacts is a FAILED transfer.`;

    const prompt = `System Prompt:
${systemPrompt}

${runOptions.problem ? `Original Problem Statement (the deliverable contract — your output must satisfy it, including any stated success criterion):
${runOptions.problem}

` : ''}Analogical Mapping from Phase 2:
${JSON.stringify(analogicalMapping, null, 2)}

Core Contradictions:
${JSON.stringify(coreContradictions, null, 2)}

${runOptions.monitoringAppendix ? `${runOptions.monitoringAppendix}\n` : ''}${runOptions.nudge ? `CURRENT LOOK-IN NUDGE: ${runOptions.nudge}\n` : ''}
${steeringFlags.length > 0 ? `Active Steering Flags from Synthesizer:\n${steeringFlags.map(flag => `- ${flag}`).join('\n')}\n` : ''}
Provide your symmetrical resolution.
Format your output as a JSON object with:
- "trizPrinciplesApplied": array of strings listing the TRIZ principles applied (e.g. ["Segmentation", "Feedback"]).
- "analogicalResolution": description of how the contradiction was resolved within the foreign analogical domain.
- "symmetricalResolution": the elegant solution mapped back to the original domain, resolving the core contradictions.
- "resolutionReasoning": the technical or structural reasoning explaining how the resolution achieves symmetry and resolves the contradictions without compromise.
- "deliverable": the INSTANTIATED terminal artifact(s) the original problem statement asks for — the actual named things (the concrete image scenes, the candidate strings, the specific designs), never a framework alone. When the problem asks for N artifacts, deliver N.`;

    const schema = {
      type: "object",
      properties: {
        trizPrinciplesApplied: {
          type: "array",
          items: { type: "string" }
        },
        analogicalResolution: { type: "string" },
        symmetricalResolution: { type: "string" },
        resolutionReasoning: { type: "string" },
        deliverable: { type: "string" }
      },
      required: ["trizPrinciplesApplied", "analogicalResolution", "symmetricalResolution", "resolutionReasoning", "deliverable"]
    };

    const response = await customRunAgent({
      prompt,
      schema,
      driver: runOptions.driver || this.driver,
      freshContext: true,
      label: "DiracTransfer",
      role: "triz",
      signal: runOptions.signal,
    });

    return response;
  }
}

export async function diracTransfer(analogicalMapping, coreContradictionsOrOptions = {}, options = {}) {
  let ctorOptions = {};
  if (Array.isArray(coreContradictionsOrOptions)) {
    ctorOptions = options;
  } else {
    ctorOptions = { ...coreContradictionsOrOptions, ...options };
  }
  const transfer = new DiracTransfer(ctorOptions);
  return transfer.run(analogicalMapping, coreContradictionsOrOptions, options);
}

/**
 * The 3-Gate Kill-Filter (Anti-Hallucination Guardrails).
 * Every generated idea must survive three gates:
 * 1. Existence Proof
 * 2. Glass Bead Syntax Test
 * 3. Dirac Structural Symmetry Test (Adversarial Gate)
 *
 * B3 Decision A (load-bearing): when `killGates` is supplied (depth-locked path),
 * happy-path stage count (gateLogs length on full pass) MUST equal knobs.killGates.
 * Never silently thin stages below the resolved floor.
 */
export class KillFilter {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
    /** @type {number | null} expected stage count from depth knobs (Decision A) */
    this.killGates = Number.isInteger(options.killGates) ? options.killGates : null;
  }

  /**
   * Runs the 3-Gate Kill-Filter on the concept/solution.
   * If any gate fails, the concept is rejected and logged.
   *
   * @param {object} concept - The concept/solution to test.
   * @param {object} [options] - Additional runtime options, including driver + killGates.
   * @returns {Promise<object>} The filter result.
   */
  async run(concept, options = {}) {
    const runOptions = { ...options };
    const customRunAgent = runOptions.runAgent || this.runAgent || runAgent;
    const driver = runOptions.driver || this.driver;
    // Decision A: expected stage count from depth-locked knobs (CLI passes killGates).
    const expectedKillGates = Number.isInteger(runOptions.killGates)
      ? runOptions.killGates
      : (Number.isInteger(this.killGates) ? this.killGates : 3);
    const gateLogs = [];

    // --- GATES 1+2: ONE MERGED CALL (W2, 2026-07-11) ---
    // Both are same-family cheap pre-filters over the SAME concept (existence proof;
    // analogy integrity) and were two strictly-sequential calls. One call, two
    // independently-judged verdicts in the schema — the gateLogs shape, the
    // failedAtGate attribution (1 before 2), and the short-circuit BEFORE the
    // cross-family Gate 3 are all unchanged. Saves 1 call + 1 sequential round per
    // candidate (×N in portfolio mode).
    const hasMapping = concept.analogicalMapping && typeof concept.analogicalMapping === 'object' &&
      Object.keys(concept.analogicalMapping).length > 0;

    const systemPromptGate12 = `You are Jumper Kill-Filter Gates 1+2 (one pass, two INDEPENDENT verdicts).
GATE 1 — Existence Proof: verify the concept is theoretically possible and does not violate the fundamental axioms or laws of its target domain (impossible physics, non-existent APIs, contradictory requirements ⇒ reject gate 1).
GATE 2 — Glass Bead Syntax Test: evaluate whether the analogical mapping holds logical and structural integrity, or is merely a forced, shallow metaphor (elements/relationships/contradictions must map logically to the foreign domain's constraints).
Judge each gate ON ITS OWN MERITS — a concept may pass one and fail the other.`;

    const promptGate12 = `System Prompt:
${systemPromptGate12}

${concept.problem ? `Original Problem Statement (what the requester asked to receive):
${concept.problem}

` : ''}Concept to evaluate:
Deliverable: ${concept.deliverable || '(none provided)'}
Symmetrical Resolution: ${concept.symmetricalResolution || ''}
Resolution Reasoning: ${concept.resolutionReasoning || ''}

Analogical Mapping:
${hasMapping ? JSON.stringify(concept.analogicalMapping, null, 2) : '(missing — gate 2 auto-fails deterministically; judge gate 1 only)'}

Core Contradictions:
${JSON.stringify(concept.coreContradictions || [], null, 2)}

Format your output as a JSON object with:
- "gate1": { "passed": boolean, "reasoning": string }  (existence proof)
- "gate2": { "passed": boolean, "reasoning": string }  (analogy integrity${hasMapping ? '' : ' — mapping missing, return passed:false'})`;

    const gateVerdict = {
      type: "object",
      properties: { passed: { type: "boolean" }, reasoning: { type: "string" } },
      required: ["passed", "reasoning"]
    };
    const schemaGate12 = {
      type: "object",
      properties: { gate1: gateVerdict, gate2: gateVerdict },
      required: ["gate1", "gate2"]
    };

    const res12 = await customRunAgent({
      prompt: promptGate12,
      schema: schemaGate12,
      driver,
      freshContext: true,
      label: "KillFilterGate1and2",
      role: "gate",
      signal: runOptions.signal,
    });
    const res1 = res12?.gate1 ?? { passed: false, reasoning: "Gate 1 verdict missing from the merged reply." };
    // The missing-mapping fail stays DETERMINISTIC — never delegated to the model.
    const res2 = hasMapping
      ? (res12?.gate2 ?? { passed: false, reasoning: "Gate 2 verdict missing from the merged reply." })
      : { passed: false, reasoning: "Gate 2 failed: analogical mapping is missing or invalid." };

    gateLogs.push({ gate: 1, name: "Existence Proof", passed: res1.passed, reasoning: res1.reasoning });
    if (!res1.passed) {
      return { passed: false, failedAtGate: 1, rejectionReason: res1.reasoning, gateLogs };
    }

    gateLogs.push({ gate: 2, name: "Glass Bead Syntax Test", passed: res2.passed, reasoning: res2.reasoning });
    if (!res2.passed) {
      return { passed: false, failedAtGate: 2, rejectionReason: res2.reasoning, gateLogs };
    }

    // --- GATE 3: DIRAC STRUCTURAL SYMMETRY TEST (ADVERSARIAL GATE) ---
    const systemPromptGate3 = `You are Jumper Kill-Filter Gate 3: Dirac Structural Symmetry Test (Adversarial Subagent).
Your sole purpose is to act as an independent, highly critical adversary. You must actively hunt for LLM hallucinations, logical gaps, hand-waving, unstated assumptions, and structural asymmetries in the proposed resolution.
Be ruthless. Reject any concept that contains vague steps, unresolved contradictions, or is not practically applicable. Only let concepts pass if they are structurally sound, concrete, and viable.
Specifically, evaluate the structural symmetry of the resolution and check for unresolved contradictions by comparing it against the original core contradictions and the analogical mappings.
THE DELIVERABLE TEST (journal 0028 RC-1): judge the concept's DELIVERABLE against the original problem statement's requirements, including any stated success criterion. If the problem asks for concrete terminal artifacts and the deliverable is a framework, methodology, grammar, or design-language without instantiated artifacts, that is a BLOCKER — reject. Judge the instantiated artifacts themselves, not the scaffold that produced them.`;

    const promptGate3 = `System Prompt:
${systemPromptGate3}

${concept.problem ? `Original Problem Statement (the deliverable contract):
${concept.problem}

` : ''}Concept to evaluate:
Deliverable: ${concept.deliverable || '(none provided)'}
Symmetrical Resolution: ${concept.symmetricalResolution || ''}
Resolution Reasoning: ${concept.resolutionReasoning || ''}
Triz Principles Applied: ${JSON.stringify(concept.trizPrinciplesApplied || [])}

Core Contradictions:
${JSON.stringify(concept.coreContradictions || [])}

Analogical Mapping:
${JSON.stringify(concept.analogicalMapping || {})}

Evaluate this resolved concept. Actively look for logic gaps, hallucinated APIs/technologies, asymmetry, or practical applicability issues.
Format your output as a JSON object with:
- "passed": boolean (true only if you verify the concept is structurally sound, complete, and practically applicable without logic gaps or hallucinations; false if you identify any blocker or gap).
- "reasoning": detailed explanation of your finding, explicitly calling out any logic gaps, hallucinations, or reasons for rejection.`;

    const schemaGate3 = {
      type: "object",
      properties: {
        passed: { type: "boolean" },
        reasoning: { type: "string" }
      },
      required: ["passed", "reasoning"]
    };

    // 2026-07 (W7) + B3 W5: Gate 3 is the ADVERSARIAL gate — real independence means a DIFFERENT
    // model family by DEFAULT, not opt-in. Production seating is resolveGate3Seating (prefs → driver;
    // JUMPER_GATE3_DRIVER may retarget family but never invent skip-independence). LITE depth lock
    // may lean ideaRounds but never collapses this check. Self-review → JumperSelfReviewHalt;
    // down cross-family backend → JumperCrossFamilyDegradeHalt (never silent self-review).
    const seating = resolveGate3Seating({
      drafterDriver: driver || null,
      gate3Driver: runOptions.gate3Driver ?? null,
      gate3Agent: runOptions.gate3Agent ?? null,
      env: runOptions.env || process.env,
      assertIndependent: true,
    });
    const { gate3DriverName, substrate: gate3Substrate } = seating;

    // The verifier agent: an injected role-routed stub (tests) wins; else, when a custom runAgent seam
    // is injected, route Gate 3 through it with the cross-family driver (keeps deterministic tests in
    // control); production uses the shared Trio dispatcher with the resolved review-family driver.
    let res3;
    try {
      const legacyGate3Agent = runOptions.gate3Agent
        ? async (agentArgs) => runOptions.gate3Agent(agentArgs.prompt, {
          role: agentArgs.role,
          label: agentArgs.label,
          schema: agentArgs.schema,
          signal: agentArgs.signal,
        })
        : null;
      const gate3Dispatch = runOptions.gate3RunAgent || legacyGate3Agent || customRunAgent;
      res3 = await gate3Dispatch({
        prompt: promptGate3,
        schema: schemaGate3,
        driver: gate3DriverName,
        model: runOptions.gate3Model ?? null,
        freshContext: true,
        label: "KillFilterGate3",
        role: "gate3",
        signal: runOptions.signal,
      });
    } catch (err) {
      if (err instanceof JumperSelfReviewHalt || err instanceof SelfRefutationHalt) throw err;
      // Down cross-family verifier ⇒ HALT honestly (never a same-family self-review fallback).
      throw new JumperCrossFamilyDegradeHalt(gate3DriverName, err);
    }

    // 0028 RC-2: a nonconforming Gate-3 reply (no boolean `passed`, or the
    // driver's transport-failure ABSTAIN object) is NOT a verdict. Two retry
    // candidates that had PASSED gates 1–2 were recorded as "KILLED at gate 3,
    // rejectionReason: null" without ever being judged. Same honesty law as
    // agy-down: HALT, never a silent kill.
    if (typeof res3?.passed !== "boolean" || res3?.transport_failed) {
      throw new JumperCrossFamilyDegradeHalt(
        gate3DriverName,
        new Error(
          "gate-3 reply nonconforming (no boolean `passed` after driver retry) — " +
          "transport failure, not a verdict; rerun when the cross-family seat is healthy",
        ),
      );
    }

    gateLogs.push({
      gate: 3,
      name: "Dirac Structural Symmetry Test",
      substrate: gate3Substrate,
      passed: res3.passed,
      reasoning: res3.reasoning ?? "(gate 3 returned no reasoning — nonconforming reply)"
    });

    if (!res3.passed) {
      return {
        passed: false,
        failedAtGate: 3,
        rejectionReason: res3.reasoning ?? "(gate 3 returned passed:false with no reasoning — nonconforming reply)",
        gateLogs,
        stageCount: gateLogs.length,
        killGates: expectedKillGates,
      };
    }

    // Happy path: Decision A — stage count must equal knobs.killGates (never thin).
    const stageCount = gateLogs.length;
    if (stageCount !== expectedKillGates) {
      return {
        passed: false,
        failedAtGate: null,
        rejectionReason:
          `Kill-filter stage count ${stageCount} !== knobs.killGates ${expectedKillGates} ` +
          `(Decision A: never thin kill stages)`,
        gateLogs,
        stageCount,
        killGates: expectedKillGates,
      };
    }

    return {
      passed: true,
      failedAtGate: null,
      rejectionReason: null,
      gateLogs,
      stageCount,
      killGates: expectedKillGates,
    };
  }
}

export async function killFilter(concept, options = {}) {
  const filter = new KillFilter(options);
  return filter.run(concept, options);
}

/**
 * Jumper Brainstorming Engine.
 * Integrates PetersonQuery, HesseGlassBead, DiracTransfer, Synthesizer, and KillFilter.
 */
export class Jumper {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
  }

  /**
   * Runs the complete ideation pipeline and generates a Grounding Execution Protocol.
   *
   * 2026-07 portfolio mode: pass `fanOut: N` (N ≥ 2) to generate N analogical
   * mappings (sphere-diversified, concurrent), one TRIZ resolution per mapping,
   * and run the Kill-Filter as a TOURNAMENT — the result then carries
   * `survivors[]` (ranked, GEP attached to the top one) + `killLog[]` instead of
   * a single take-it-or-leave-it concept. `retryOnKill: true` additionally
   * replays phases 2-3 ONCE with the rejection reasons injected as steering
   * flags when everything died. Default (`fanOut` absent/1) is the historical
   * single-candidate pipeline, unchanged.
   *
   * @param {string|object} problemState - Initial problem statement/intent.
   * @param {object} [options] - Options (driver, runAgent, fanOut, retryOnKill, gate3Driver).
   * @returns {Promise<object>} Pipeline execution results.
   */
  async run(problemState, options = {}) {
    const ledger = options.seatingLedger instanceof JumperSeatingLedger
      ? options.seatingLedger
      : createJumperSeatingLedger();
    try {
      const result = await this._runPipeline(problemState, { ...options, seatingLedger: ledger });
      return { ...result, seating: ledger.snapshot() };
    } catch (caught) {
      const err = caught && typeof caught === 'object' ? caught : new Error(String(caught));
      const seating = ledger.snapshot();
      err.seating = seating;
      if (err.jumperPartial && typeof err.jumperPartial === 'object') {
        err.jumperPartial = { ...err.jumperPartial, seating };
      }
      throw err;
    }
  }

  async _runPipeline(problemState, options = {}) {
    const runOptions = { ...options };
    const seatingLedger = runOptions.seatingLedger;
    const customRunAgent = runOptions.runAgent || this.runAgent || runAgent;
    const driver = runOptions.driver || this.driver;
    const rootSignal = runOptions.signal;
    const runId = runOptions.runId || `${Date.now()}-${process.pid}-${randomUUID()}`;
    const codingAgent = (dispatchId, signal = rootSignal, baseAgent = customRunAgent) =>
      createJumperDispatchAgent({
        ledger: seatingLedger,
        kind: 'coding',
        dispatchId,
        runAgent: baseAgent,
        signal,
      });
    const verdictAgent = (dispatchId, signal = rootSignal) => {
      const baseAgent = runOptions.gate3Agent
        ? async (agentArgs) => runOptions.gate3Agent(agentArgs.prompt, {
          role: agentArgs.role,
          label: agentArgs.label,
          schema: agentArgs.schema,
          signal: agentArgs.signal,
        })
        : customRunAgent;
      return createJumperDispatchAgent({
        ledger: seatingLedger,
        kind: 'verdict',
        dispatchId,
        runAgent: baseAgent,
        signal,
      });
    };
    // W2 (2026-07-11): the PORTFOLIO is the default — NORTH-STAR.md:7 promises "a
    // portfolio … not a single take-it-or-leave-it idea", and fan-out costs only ~2
    // extra sequential rounds (branches parallelize). Explicit `fanOut: 1` selects
    // the legacy single-candidate pipeline.
    const fanOut = runOptions.fanOut === 1 ? 1
      : Number.isInteger(runOptions.fanOut) && runOptions.fanOut > 1 ? Math.min(runOptions.fanOut, 5)
      : 3;

    const synthesizer = new Synthesizer({ driver });

    // P1 2026-07-25 (journals 0005/0004/0007/0011/0014): stage heartbeats. Sparse
    // logging made a healthy long run indistinguishable from a hang and caused a
    // false-DONE by the cadence agent. `options.log` is the sink (CLI wires stderr).
    const hb = typeof runOptions.log === 'function' ? runOptions.log : () => {};

    // Step 1: Run Gandalf to get structured advice. Thread the run options through so the composed
    // deep-think lane inherits the cross-family refuter injection (refuterAgent/ledger/routes) too (W7).
    hb('jumper: gandalf:start');
    const gandalfRead = await runGandalf(problemState, {
      ...runOptions,
      driver,
      signal: rootSignal,
      runAgent: codingAgent('coding:gandalf-draft'),
    });
    hb('jumper: gandalf:done');
    // 2026-08-19 (journal 0031): surface the compose-seam refutation cap in the FINAL
    // output — the stamp must ride the artifact the caller reads, not just stderr.
    const capSpread = gandalfRead?.refutation_capped
      ? { refutation_capped: gandalfRead.refutation_capped } : {};

    // Step 2: Update synthesizer and get steering flags
    const synth1 = await synthesizer.update({
      problem: problemState,
      currentPhase: 'Peterson Query (Input)',
      gandalfRead
    }, {
      signal: rootSignal,
      runAgent: codingAgent('coding:synthesizer:peterson-input'),
    });
    const flags1 = synth1?.steeringFlags || [];

    // Step 3: Run Phase 1 - Peterson Query
    const queryEngine = new PetersonQuery({ driver });
    const petersonResult = await queryEngine.run(gandalfRead, {
      ...runOptions,
      signal: rootSignal,
      steeringFlags: flags1,
      runAgent: codingAgent('coding:peterson'),
    });

    // Step 4: Update synthesizer and get steering flags for Phase 2
    const synth2 = await synthesizer.update({
      problem: problemState,
      currentPhase: 'Hesse Glass Bead (Input)',
      problemMap: petersonResult
    }, {
      signal: rootSignal,
      runAgent: codingAgent('coding:synthesizer:hesse-input'),
    });
    // W2: flags carry only the CURRENT round's steering (flags1 already steered
    // Peterson; re-accumulating them inflated every downstream prompt for no lift).
    const flags2 = synth2?.steeringFlags || [];

    const beadEngine = new HesseGlassBead({ driver });
    const transferEngine = new DiracTransfer({ driver });
    // B3 W3: thread killGates from depth-locked CLI so Decision A stage count can match knobs.
    const filterEngine = new KillFilter({
      driver,
      killGates: Number.isInteger(runOptions.killGates) ? runOptions.killGates : undefined,
    });

    // Sphere hints force GENUINE domain diversity across the fan-out (each
    // sibling is blind to the others, so diversity is assigned, not hoped for).
    const SPHERES = [
      'the natural sciences (biology, physics, chemistry, geology, ecology)',
      'the arts and humanities (music theory, architecture, painting, literature, history)',
      'social/rule systems (economics, law, games, logistics, ritual)',
      'engineered physical systems (mechanics, materials, civil/aero/naval engineering)',
      'information/communication systems outside software (linguistics, cryptography history, signalling)',
    ];

    // One candidate = hesse (with an optional sphere hint) -> [synthesizer] -> dirac -> concept.
    // W2 (2026-07-11): the per-candidate Synthesizer interlude runs ONLY on the legacy
    // single-candidate path (no sphere hint). In fan-out it is DROPPED: (a) the sphere
    // hint already does the steering that call existed for; (b) all N parallel
    // candidates shared ONE Synthesizer whose history mixed sibling states into every
    // prompt — nondeterministic sibling contamination that broke the "each sibling is
    // blind to the others" invariant; (c) it was 1 sequential call per candidate.
    const buildCandidate = async ({
      round,
      candidate,
      sphereHint,
      extraFlags = [],
      checkpoint,
      nudge = null,
      attemptSignal = rootSignal,
      heartbeatPath = null,
    }) => {
      const phaseSignal = combinedSignal(rootSignal, attemptSignal);
      const monitoringAppendix = heartbeatPath
        ? lookinAppendix({ heartbeatPath, northStar: 'finish this candidate phase without losing committed Hesse/Dirac work' })
        : null;
      const hesseFlags = [...flags2, ...extraFlags,
        ...(sphereHint ? [`Choose your foreign domain from ${sphereHint} — sibling candidates cover other spheres; do not stray from yours.`] : [])];
      if (!checkpoint.hesse) {
        const hesseResult = await beadEngine.run(petersonResult, {
          ...runOptions,
          signal: phaseSignal,
          steeringFlags: hesseFlags,
          monitoringAppendix,
          nudge,
          runAgent: codingAgent(`coding:r${round}:c${candidate}:hesse`, phaseSignal),
        });
        throwIfAborted(phaseSignal);
        checkpoint.hesse = hesseResult;
      }
      const hesseResult = checkpoint.hesse;
      let flags3 = extraFlags;
      if (!sphereHint) {
        if (!checkpoint.synthesizerDirac) {
          const synth3 = await synthesizer.update({
            problem: problemState,
            currentPhase: 'Dirac Transfer (Input)',
            analogicalMapping: hesseResult
          }, {
            signal: phaseSignal,
            monitoringAppendix,
            nudge,
            runAgent: codingAgent(`coding:r${round}:c${candidate}:synthesizer-dirac`, phaseSignal),
          });
          throwIfAborted(phaseSignal);
          checkpoint.synthesizerDirac = synth3;
        }
        flags3 = [...(checkpoint.synthesizerDirac?.steeringFlags || []), ...extraFlags];
      }
      // 0028 RC-1: thread the VERBATIM problem into Phase 3 and the candidate —
      // before this, no phase after Gandalf knew what the user asked to receive,
      // so every transfer terminated in a framework instead of an artifact.
      if (!checkpoint.dirac) {
        const diracResult = await transferEngine.run(hesseResult, petersonResult.coreContradictions, {
          ...runOptions,
          signal: phaseSignal,
          steeringFlags: flags3,
          problem: problemState,
          monitoringAppendix,
          nudge,
          runAgent: codingAgent(`coding:r${round}:c${candidate}:dirac`, phaseSignal),
        });
        throwIfAborted(phaseSignal);
        checkpoint.dirac = diracResult;
      }
      checkpoint.concept ||= {
        ...checkpoint.dirac,
        analogicalMapping: hesseResult,
        coreContradictions: petersonResult.coreContradictions,
        problem: problemState,
      };
      return checkpoint.concept;
    };

    // ---- PORTFOLIO MODE (fanOut > 1): tournament over N candidates ----
    if (fanOut > 1) {
      const runTournament = async (round, extraFlags = []) => {
        const candidateCheckpoints = Array.from({ length: fanOut }, () => ({}));
        const candidatePromises = Array.from({ length: fanOut }, (_, i) => {
          const candidate = i + 1;
          const checkpoint = candidateCheckpoints[i];
          const heartbeat = createCandidateHeartbeatTracker({
            runId,
            round,
            candidate,
            heartbeatDir: runOptions.heartbeatDir,
          });
          hb(`jumper: sphere:${candidate}/${fanOut} candidate start`);
          return superviseSeat({
            ...(runOptions.supervision || {}),
            strictAbortJoin: true,
            getTrail: () => heartbeat.getTrail(),
            run: ({ attempt, nudge, signal: attemptSignal }) => {
              const active = heartbeat.activate(attempt);
              return buildCandidate({
                round,
                candidate,
                sphereHint: SPHERES[i % SPHERES.length],
                extraFlags,
                checkpoint,
                nudge,
                attemptSignal,
                heartbeatPath: active.path,
              });
            },
          }).then((concept) => {
            hb(`jumper: sphere:${candidate}/${fanOut} candidate built (${concept?.analogicalMapping?.foreignDomain ?? '?'})`);
            return concept;
          });
        });
        const candidateSettled = await Promise.allSettled(candidatePromises);
        const candidates = candidateSettled
          .filter((entry) => entry.status === 'fulfilled')
          .map((entry) => entry.value);
        const buildFailure = candidateSettled.find((entry) => entry.status === 'rejected');
        if (buildFailure) {
          const err = buildFailure.reason;
          if (err && typeof err === 'object' && !err.jumperPartial) {
            err.jumperPartial = {
              stage: 'candidate-build',
              honesty_stamp: 'NOT FULLY VETTED — candidate construction HALTed; completed phase artifacts are preserved',
              ...capSpread,
              candidates,
              phase_artifacts: candidateCheckpoints.map((entry, i) => ({
                round,
                candidate: i + 1,
                hesse: entry.hesse ?? null,
                synthesizer_dirac: entry.synthesizerDirac ?? null,
                dirac: entry.dirac ?? null,
              })),
            };
          }
          throw err;
        }
        // 2026-08-19 (journal 0031): a mid-kill-filter HALT (e.g. agy down at Gate 3 →
        // JumperCrossFamilyDegradeHalt) must NEVER destroy the paid candidates — attach
        // them to the error so the CLI can emit an honest "not fully vetted" partial
        // instead of output:null ("a guardrail is never the whole product of a turn").
        const judgePromises = candidates.map(async (concept, i) => {
          const candidate = i + 1;
          hb(`jumper: killfilter:candidate ${candidate}/${candidates.length} start`);
          const filter = await filterEngine.run(concept, {
            ...runOptions,
            signal: rootSignal,
            runAgent: codingAgent(`coding:r${round}:c${candidate}:gate12`),
            gate3RunAgent: verdictAgent(`gate3:r${round}:c${candidate}:verdict`),
          });
          hb(`jumper: killfilter:candidate ${candidate}/${candidates.length} ${filter.passed ? 'PASSED all gates' : `KILLED at gate ${filter.failedAtGate}`}`);
          return { concept, filter };
        });
        const judgeSettled = await Promise.allSettled(judgePromises);
        const judgeFailure = judgeSettled.find((entry) => entry.status === 'rejected');
        if (judgeFailure) {
          const err = judgeFailure.reason;
          if (err && typeof err === 'object' && !err.jumperPartial) {
            err.jumperPartial = {
              stage: 'kill-filter',
              honesty_stamp: 'NOT FULLY VETTED — the engine HALTed during the kill-filter; '
                + 'the raw candidates are preserved, but no partial portfolio is represented as fully gate-approved',
              ...capSpread,
              candidates,
            };
          }
          throw err;
        }
        const judged = judgeSettled.map((entry) => entry.value);
        return {
          survivors: judged.filter((j) => j.filter.passed),
          killed: judged.filter((j) => !j.filter.passed),
        };
      };

      let { survivors, killed } = await runTournament(1);
      let retried = false;
      let firstRoundKilled = [];
      if (!survivors.length && runOptions.retryOnKill) {
        // One bounded retry: the rejections become steering flags (the loop
        // learns WHY everything died before trying again). Never more than once.
        retried = true;
        firstRoundKilled = killed;
        const lessons = killed.map((k) => `A prior candidate was KILLED at gate ${k.filter.failedAtGate}: ${String(k.filter.rejectionReason || '').slice(0, 300)}`);
        ({ survivors, killed } = await runTournament(2, lessons));
      }

      // 0028 RC-3: the killLog covers EVERY round — the retry used to discard
      // round 1's kills, so the output claimed 3 kills when 6 candidates died.
      const toKillEntry = (round) => (k) => ({
        round,
        failedAtGate: k.filter.failedAtGate,
        rejectionReason: k.filter.rejectionReason,
        gateLogs: k.filter.gateLogs,
        foreignDomain: k.concept?.analogicalMapping?.foreignDomain ?? null,
      });
      const killLog = [
        ...firstRoundKilled.map(toKillEntry(1)),
        ...killed.map(toKillEntry(retried ? 2 : 1)),
      ];

      if (!survivors.length) {
        // 2026-08-25 (John-ratified card; journals 0025/0027): on a zero-survivor run the
        // engine's most reliable value — gate-endorsed content and named blockers in the
        // kill log — used to be hand-extracted by the session. The stamp marks the killLog
        // itself as the deliverable (VERBATIM — a summarizing seat would blur the
        // kill-filter's promise); the runner surfaces it as first-class output.
        return {
          passed: false, fanOut, retried, survivors: [], killLog,
          salvage_stamp: 'SALVAGE — no survivor; the killLog below IS the deliverable of this run: verbatim gate-endorsed content and named blockers from every killed candidate (unranked, individually gate-attested, not vetted as a whole)',
          ...capSpread,
        };
      }

      // Rank: all survivors passed all 3 gates; order by richer structural
      // mappings first (a deeper analogy is the better raw material).
      survivors.sort((a, b) =>
        (b.concept?.analogicalMapping?.structuralMapping?.length ?? 0) -
        (a.concept?.analogicalMapping?.structuralMapping?.length ?? 0));
      const top = survivors[0];
      const gep = await this._generateGEP(
        top.concept,
        codingAgent('coding:gep'),
        driver,
        rootSignal,
      );
      return {
        passed: true,
        fanOut,
        retried,
        ...capSpread,
        concept: top.concept,
        gateLogs: top.filter.gateLogs,
        groundingExecutionProtocol: gep,
        survivors: survivors.map((s, i) => ({
          rank: i + 1,
          foreignDomain: s.concept?.analogicalMapping?.foreignDomain ?? null,
          concept: s.concept,
          gateLogs: s.filter.gateLogs,
        })),
        killLog,
      };
    }

    // ---- LEGACY SINGLE-CANDIDATE PATH (fanOut = 1; unchanged behavior) ----
    const buildLegacyCandidate = (round, extraFlags = []) => buildCandidate({
      round,
      candidate: 1,
      sphereHint: null,
      extraFlags,
      checkpoint: {},
      attemptSignal: rootSignal,
    });
    const judgeLegacyCandidate = (concept, round) => filterEngine.run(concept, {
      ...runOptions,
      signal: rootSignal,
      runAgent: codingAgent(`coding:r${round}:c1:gate12`),
      gate3RunAgent: verdictAgent(`gate3:r${round}:c1:verdict`),
    });
    const concept = await buildLegacyCandidate(1);
    const filterResult = await judgeLegacyCandidate(concept, 1);

    if (!filterResult.passed) {
      if (runOptions.retryOnKill) {
        const lesson = `A prior candidate was KILLED at gate ${filterResult.failedAtGate}: ${String(filterResult.rejectionReason || '').slice(0, 300)}`;
        const concept2 = await buildLegacyCandidate(2, [lesson]);
        const filter2 = await judgeLegacyCandidate(concept2, 2);
        if (filter2.passed) {
          const gep2 = await this._generateGEP(
            concept2,
            codingAgent('coding:gep'),
            driver,
            rootSignal,
          );
          return { passed: true, retried: true, ...capSpread, concept: concept2, gateLogs: filter2.gateLogs, groundingExecutionProtocol: gep2 };
        }
      }
      return {
        passed: false,
        failedAtGate: filterResult.failedAtGate,
        rejectionReason: filterResult.rejectionReason,
        gateLogs: filterResult.gateLogs,
        ...capSpread,
        concept
      };
    }

    // Step 9: Format the output into the Grounding Execution Protocol
    const gepResult = await this._generateGEP(
      concept,
      codingAgent('coding:gep'),
      driver,
      rootSignal,
    );

    return {
      passed: true,
      ...capSpread,
      concept,
      gateLogs: filterResult.gateLogs,
      groundingExecutionProtocol: gepResult
    };
  }

  /** Grounding Execution Protocol generation (shared by both pipeline modes). */
  async _generateGEP(concept, customRunAgent, driver, signal = null) {
    const systemPromptGEP = `You are Jumper Grounding Execution Protocol Generator.
Your role is to format the approved symmetrical resolution into a Grounding Execution Protocol: a concrete, step-by-step test plan to validate the idea in reality.

Determine the domain type (e.g., software, empirical/scientific, art/philosophy) and output:
1. For Software/Engineering: A proof-of-concept architecture, unit test definitions, or a minimal viable implementation plan.
2. For Empirical/Scientific: A formal experiment design, defined variables, and success metrics.
3. For Art/Philosophy: A concrete phenomenological demonstration, a rigorous logical proof, or a specific creative output.

Ensure the steps are concrete, verifiable, and directly test the generated idea.`;

    const promptGEP = `System Prompt:
${systemPromptGEP}

Approved Concept:
Symmetrical Resolution: ${concept.symmetricalResolution}
Resolution Reasoning: ${concept.resolutionReasoning}
TRIZ Principles Applied: ${JSON.stringify(concept.trizPrinciplesApplied || [])}
Analogical Mapping from Hesse Glass Bead:
${JSON.stringify(concept.analogicalMapping, null, 2)}

Generate the Grounding Execution Protocol to validate this resolution.`;

    const schemaGEP = {
      type: "object",
      properties: {
        domainType: { type: "string" },
        validationSetup: { type: "string" },
        concreteSteps: {
          type: "array",
          items: {
            type: "object",
            properties: {
              stepNumber: { type: "integer" },
              description: { type: "string" },
              verificationMethod: { type: "string" }
            },
            required: ["stepNumber", "description", "verificationMethod"]
          }
        },
        successMetrics: {
          type: "array",
          items: { type: "string" }
        },
        risksAndMitigations: {
          type: "array",
          items: { type: "string" }
        }
      },
      required: ["domainType", "validationSetup", "concreteSteps", "successMetrics", "risksAndMitigations"]
    };

    return customRunAgent({
      prompt: promptGEP,
      schema: schemaGEP,
      driver,
      freshContext: true,
      label: "GroundingExecutionProtocol",
      role: "ground",
      signal,
    });
  }
}

export async function jumper(problemState, options = {}) {
  const engine = new Jumper(options);
  return engine.run(problemState, options);
}
