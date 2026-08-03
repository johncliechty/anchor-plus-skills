// transport.mjs — Foreman Wave 7: TYPED transport-failure handling.
//
// Two pre-registered measurements live here, both PURE + deterministic so they
// are verifiable without a live model call:
//
//   (1) the EXIT-CLASS TAXONOMY — `classifyExit()` maps EVERY possible outcome of
//       a spawned sub-agent child (`claude -p`, or any transport) onto ONE of a
//       fixed, named set of classes. The function is TOTAL: it never returns
//       null/undefined and never an unnamed class, so "every exit is classified —
//       no unclassified exit" (the wave-7 Given/When/Then) holds by construction.
//
//   (2) the PER-CALL TELEMETRY SCHEMA — `TELEMETRY_FIELDS` + `validateTelemetry()`
//       pin the shape of each per-call record the live runner emits, and
//       `makeTelemetryRecord()` builds a schema-valid record (including the SR-5
//       attestation triple). The live runner validates every record before it is
//       recorded, so a drifted/half-formed telemetry row is a loud error, not a
//       silent gap in the calibration data.
//
// Nothing here spawns a process or touches the network; the live wiring (timeout,
// kill-on-exit, the run lock) lives in proc-guard.mjs and run-live.mjs.

import { ATTEST_FIELDS, attestStamp, hasAttestation } from '../../drivers/attest.mjs';

// ---------------------------------------------------------------------------
// (1) Exit-class taxonomy.
// ---------------------------------------------------------------------------

/**
 * The fixed, exhaustive set of sub-agent exit classes. Every spawned child's
 * outcome maps onto exactly one of these. `unknown` is the TOTALITY backstop —
 * it is still a NAMED class (so the exit is "classified"), but a value of
 * `unknown` means the taxonomy missed a real-world shape and should be widened;
 * the tests assert no realistic input ever reaches it.
 */
export const EXIT_CLASSES = Object.freeze({
  OK: 'ok',                               // clean result envelope, is_error === false
  ERROR_RESULT: 'error-result',           // result envelope present but is_error truthy (CLI-reported failure)
  TIMEOUT_KILLED: 'timeout-killed',       // our per-call timeout SIGKILLed the child
  SIGNAL_KILLED: 'signal-killed',         // killed by a signal we did not raise (external SIGTERM/SIGKILL/OOM)
  NO_RESULT_ENVELOPE: 'no-result-envelope', // exited 0 but emitted no result envelope (truncated/interrupted stream)
  NONZERO_EXIT: 'nonzero-exit',           // process exit code != 0 with no usable result envelope
  SPAWN_FAILED: 'spawn-failed',           // spawn itself threw (ENOENT: transport binary missing, EACCES, …)
  UNKNOWN: 'unknown',                     // totality backstop — see note above
});

const ALL_CLASSES = Object.freeze(new Set(Object.values(EXIT_CLASSES)));

/** True iff `c` is one of the named exit classes (i.e. the exit was classified). */
export function isExitClass(c) {
  return typeof c === 'string' && ALL_CLASSES.has(c);
}

// Which classes are RECOVERABLE — a retry of the SAME call could plausibly
// succeed (transient transport faults). Non-recoverable classes reflect a real
// failure (a genuine non-zero exit, a CLI-reported error) or a config fault
// (the transport binary is missing) where a blind retry would just repeat it.
const RECOVERABLE = Object.freeze(new Set([
  EXIT_CLASSES.TIMEOUT_KILLED,
  EXIT_CLASSES.SIGNAL_KILLED,
  EXIT_CLASSES.NO_RESULT_ENVELOPE,
]));

/**
 * Classify a finished (or failed-to-start) child process.
 *
 * The branch order encodes priority: a spawn that never started, then OUR
 * timeout (which itself raises SIGKILL — checked before the generic signal
 * branch so a timeout reads as `timeout-killed`, not `signal-killed`), then an
 * external signal, then the result-envelope verdict, then the bare exit code.
 *
 * @param {object} o
 * @param {Error|null}   [o.spawnError]  the error if spawn threw (else null)
 * @param {boolean}      [o.timedOut]    true iff OUR per-call timeout fired
 * @param {?number}      [o.code]        process exit code (null when signal-killed)
 * @param {?string}      [o.signal]      the signal name if killed by one (else null)
 * @param {?object}      [o.finalEnv]    the parsed `result` envelope, or null if none arrived
 * @returns {{class:string, recoverable:boolean, detail:string}}  always a NAMED class
 */
export function classifyExit({ spawnError = null, timedOut = false, code = null, signal = null, finalEnv = null } = {}) {
  const out = (cls, detail) => ({ class: cls, recoverable: RECOVERABLE.has(cls), detail });

  if (spawnError) {
    return out(EXIT_CLASSES.SPAWN_FAILED,
      `spawn failed: ${spawnError.code || spawnError.name || 'error'}: ${spawnError.message || String(spawnError)}`);
  }
  if (timedOut) {
    return out(EXIT_CLASSES.TIMEOUT_KILLED,
      `per-call timeout fired; child SIGKILLed${signal ? ` (close signal ${signal})` : ''}`);
  }
  if (signal) {
    return out(EXIT_CLASSES.SIGNAL_KILLED, `child terminated by signal ${signal} (not our timeout)`);
  }
  if (finalEnv) {
    if (finalEnv.is_error === false) return out(EXIT_CLASSES.OK, 'clean result envelope (is_error=false)');
    return out(EXIT_CLASSES.ERROR_RESULT,
      `result envelope reports is_error=${JSON.stringify(finalEnv.is_error)}` +
      (finalEnv.subtype ? ` (${finalEnv.subtype})` : ''));
  }
  if (code === 0) {
    return out(EXIT_CLASSES.NO_RESULT_ENVELOPE, 'exited 0 but no result envelope arrived (truncated/interrupted stream)');
  }
  if (Number.isInteger(code) && code !== 0) {
    return out(EXIT_CLASSES.NONZERO_EXIT, `process exited ${code} with no usable result envelope`);
  }
  // Totality backstop: neither a signal, nor a usable code, nor an envelope.
  return out(EXIT_CLASSES.UNKNOWN, `unclassifiable outcome (code=${JSON.stringify(code)}, signal=${JSON.stringify(signal)})`);
}

// ---------------------------------------------------------------------------
// (2) Per-call telemetry schema.
// ---------------------------------------------------------------------------

/**
 * The canonical per-call telemetry schema. Each field is `{type, nullable}`; the
 * three SR-5 attestation fields (model_served/model_attested/degraded) are folded
 * in from ATTEST_FIELDS and validated for internal consistency via hasAttestation.
 */
export const TELEMETRY_FIELDS = Object.freeze({
  label:             { type: 'string',  nullable: false }, // the sub-agent call label
  exit_class:        { type: 'string',  nullable: false }, // one of EXIT_CLASSES (taxonomy 1)
  recoverable:       { type: 'boolean', nullable: false }, // would a retry plausibly succeed?
  timed_out:         { type: 'boolean', nullable: false }, // did OUR per-call timeout fire?
  cli_status:        { type: 'number',  nullable: true },  // process exit code (null if signal-killed)
  signal:            { type: 'string',  nullable: true },  // close signal name, else null
  ok:                { type: 'boolean', nullable: false }, // clean success (exit_class === ok)
  duration_ms:       { type: 'number',  nullable: true },  // wall-clock for the call
  tools:             { type: 'number',  nullable: false }, // tool_use count observed
  output_tokens:     { type: 'number',  nullable: true },
  cost_usd:          { type: 'number',  nullable: true },  // subscription-equiv estimate, not a metered charge
  permission_denials:{ type: 'number',  nullable: true },
});

/** The required telemetry keys = schema fields + the three SR-5 attestation fields. */
export const TELEMETRY_KEYS = Object.freeze([...Object.keys(TELEMETRY_FIELDS), ...ATTEST_FIELDS]);

/**
 * Validate a per-call telemetry record against the schema. Returns the record on
 * success; throws on any breach (a drifted/half-formed row must be loud, never a
 * silent gap in the calibration data).
 */
export function validateTelemetry(rec) {
  if (rec === null || typeof rec !== 'object' || Array.isArray(rec)) {
    throw new TypeError('telemetry record is not a plain object');
  }
  for (const [key, spec] of Object.entries(TELEMETRY_FIELDS)) {
    if (!(key in rec)) throw new TypeError(`telemetry record missing required field: ${key}`);
    const v = rec[key];
    if (v === null) {
      if (!spec.nullable) throw new TypeError(`telemetry field ${key} must not be null`);
      continue;
    }
    if (typeof v !== spec.type) {
      throw new TypeError(`telemetry field ${key} has wrong type: expected ${spec.type}, got ${typeof v}`);
    }
  }
  if (!isExitClass(rec.exit_class)) {
    throw new TypeError(`telemetry field exit_class is not a known taxonomy class: ${JSON.stringify(rec.exit_class)}`);
  }
  if (!hasAttestation(rec)) {
    throw new TypeError('telemetry record carries no well-formed SR-5 attestation triple');
  }
  return rec;
}

/**
 * Build a schema-valid per-call telemetry record from an observed call. Folds the
 * exit-class taxonomy and the SR-5 attestation stamp in, so the live runner emits
 * one consistent shape. Throws (via validateTelemetry) if the assembled record is
 * somehow not well-formed — a defensive self-check on the runner's own bookkeeping.
 *
 * @param {object} o
 * @param {string}  o.label
 * @param {object}  o.classification  the result of classifyExit()
 * @param {?number} [o.cli_status]
 * @param {?string} [o.signal]
 * @param {?number} [o.duration_ms]
 * @param {number}  [o.tools]
 * @param {?number} [o.output_tokens]
 * @param {?number} [o.cost_usd]
 * @param {?number} [o.permission_denials]
 * @param {?string} [o.servedModel]   the SERVED model id read from the envelope (never argv)
 * @returns {object} a validated telemetry record
 */
export function makeTelemetryRecord({
  label, classification, cli_status = null, signal = null, duration_ms = null,
  tools = 0, output_tokens = null, cost_usd = null, permission_denials = null, servedModel = null,
}) {
  const rec = {
    label,
    exit_class: classification.class,
    recoverable: !!classification.recoverable,
    timed_out: classification.class === EXIT_CLASSES.TIMEOUT_KILLED,
    cli_status,
    signal,
    ok: classification.class === EXIT_CLASSES.OK,
    duration_ms,
    tools,
    output_tokens,
    cost_usd,
    permission_denials,
    ...attestStamp(servedModel), // SR-5: degraded triple when the envelope exposed no served model
  };
  return validateTelemetry(rec);
}
