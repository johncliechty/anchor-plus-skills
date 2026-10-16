// bin/engine.mjs — Wave 5 engine skeleton (REUSE, not fork).
//
// This is researchPrime's verification-loop orchestrator (MASTER-PLAN Phase B / IMPLEMENTATION-PLAN
// Wave 5 done-when): the REAL `bin/` source that
//   (a) IMPORTS the frozen trio surface (bin/contract.mjs → the five trio modules, never forks them),
//   (b) IMPORTS the shared independence-accounting module (Wave 2) and routes GATE-1 through it as the
//       single origin/quorum counter,
//   (c) OWNS the ledger (the run's append-only step history) and the ladder (the evidence-level state),
//   (d) runs the verification loop via a SCRIPTED DRIVER built from an injected `agent()` seam — the
//       same injection contract the trio uses (crucible/shark-tank.mjs `makeSharkDriver({ agent })`).
//
// It is a SKELETON: every gate-slot is traversed in a fixed, documented call-order, but each slot's
// behavior is a no-op that later waves fill in (Wave 6 fills G1/G2/G7; Wave 7 fills G3–G9). What Wave 5
// LOCKS is the engine's spine — the slot order, the owned ledger/ladder, and crash-durable
// checkpoint/resume — so the evidenced gates drop into a proven harness rather than a fresh one.
//
// ── Two distinct "ledgers" (avoid the name collision) ─────────────────────────────────────────────
// The engine's owned **run ledger** here is the per-run, append-only record of which gate-slot ran in
// which round (the thing the call-order + resume gates read). It is NOT the cross-run **ρ-calibration
// ledger** of Wave 9 (that persistent reviewer-error-correlation store is a separate module built later).
//
// ── Reuse-not-fork for durability ─────────────────────────────────────────────────────────────────
// Checkpoint/resume reuses Foreman's durable checkpoint primitives (newCheckpoint / writeCheckpointAtomic
// / readCheckpoint / validateCheckpoint) from the imported trio surface — the engine does NOT re-implement
// atomic IO. The engine's owned state (run ledger + ladder + cursor) rides in a namespaced `rp_engine`
// extension on the checkpoint object; validateCheckpoint checks only the required fields, so the extension
// round-trips through the SAME atomic writer/reader. One durable format, reused, carrying engine-owned data.

import { importTrioSurface } from './contract.mjs';
// GATE-1's sole counter, resolved via the package `imports` map (#trio-core/*) — the single canonical
// path (crit 6), NOT a `../../` reach.
import { meetsQuorum, STATIC_QUORUM_FLOOR } from '#trio-core/independence-accounting.mjs';

// (a) IMPORT THE FROZEN TRIO SURFACE. Loading this module loads the whole crossed surface — exactly the
// Wave-5 done-when ("the orchestrator imports the frozen trio surface"). Foreman's durability primitives
// are destructured from it (reuse, not fork); the full surface is re-exported for inspection/tests.
export const TRIO_SURFACE = await importTrioSurface();
const { HaltError, newCheckpoint, writeCheckpointAtomic, readCheckpoint } = TRIO_SURFACE['foreman-lib'];

/** Bump when the shape of the `rp_engine` checkpoint extension changes (resume compatibility guard). */
export const ENGINE_SCHEMA_VERSION = 1;

// ── The gate-slots, in real call-order ─────────────────────────────────────────────────────────────
// The canonical, ordered list of verification gate-slots the loop traverses each round. This ORDER is
// the spine Wave 5 locks; the no-op loop traverses exactly it, and the call-order gate asserts the
// driver invokes the slots in precisely this sequence. Later waves fill each slot's BEHAVIOR without
// reordering the spine (a wave that must reorder updates this list and the gate together).
//
// The order is a single round's pipeline: gather fresh evidence (G1/G2) and audit the ladder (G7), run
// the heterogeneous reviewers (G3), count their independent origins through the shared module (GATE-1),
// stabilize finding identity (G6), adjudicate (G4), conditionally debate (G9), fuse cross-lineage origins
// (G8, Enhanced/flagged-inert), then test convergence (G5). `fills` records which wave makes it live.
export const GATE_ONE_ID = 'gate1-origins';
export const GATE_SLOTS = Object.freeze([
  { id: 'g1-cove',             gate: 'G1',     serves: 'CoVe fresh-fetch independence (accuracy)',            fills: 'Wave 6' },
  { id: 'g2-self-consistency', gate: 'G2',     serves: 'self-consistency multiplicity (precision-only, I5)',  fills: 'Wave 6' },
  { id: 'g7-invariant',        gate: 'G7',     serves: 'invariant / evidence-ladder audit (downgrade-only, I4)', fills: 'Wave 6' },
  { id: 'g3-reviewers',        gate: 'G3',     serves: 'heterogeneous ≥2-agree reviewers',                    fills: 'Wave 7' },
  { id: GATE_ONE_ID,           gate: 'GATE-1', serves: 'independent-origins quorum (shared module, I3)',      fills: 'Wave 2/6' },
  { id: 'g6-finding-identity', gate: 'G6',     serves: 'stable finding identity / oscillation guard',         fills: 'Wave 7' },
  { id: 'g4-judge',            gate: 'G4',     serves: 'separate context-free Judge',                         fills: 'Wave 7' },
  { id: 'g9-debate',           gate: 'G9',     serves: 'conditional debate on conflicting origins',           fills: 'Wave 7' },
  { id: 'g8-fusion',           gate: 'G8',     serves: 'cross-lineage origin fusion (Enhanced, flagged-inert)', fills: 'Wave 7' },
  { id: 'g5-convergence',      gate: 'G5',     serves: 'convergence-until-dry round control (I7)',            fills: 'Wave 7' },
]);

// ── The owned RUN LEDGER ────────────────────────────────────────────────────────────────────────────
/**
 * Build the engine's owned run ledger: an append-only record of every gate-slot the loop completed,
 * keyed `<round>:<slot>`. It is the source of truth for "what already ran" — both the call-order gate
 * (the ordered step list) and resume (a completed step is never re-run) read it. Appending a step that
 * is already present THROWS: a completed step re-running is a contract breach, caught here at the data
 * layer regardless of any caller bug.
 * @param {Array<object>} [initial] prior entries to restore (from a resumed checkpoint)
 */
export function makeLedger(initial = []) {
  const entries = Array.isArray(initial) ? initial.map((e) => ({ ...e })) : [];
  const keyOf = (round, slot) => `${round}:${slot}`;
  const seen = new Set(entries.map((e) => keyOf(e.round, e.slot)));
  return {
    append(entry) {
      const key = keyOf(entry.round, entry.slot);
      if (seen.has(key)) {
        throw new HaltError(
          `run ledger: step ${key} already recorded — a completed gate-slot must never re-run`,
        );
      }
      const rec = { seq: entries.length, ...entry };
      entries.push(rec);
      seen.add(key);
      return rec;
    },
    /** Has this exact <round>:<slot> already completed? (the resume skip predicate) */
    hasStep(round, slot) { return seen.has(keyOf(round, slot)); },
    /** The ordered list of `<round>:<slot>` keys, in completion order (the call-order witness). */
    steps() { return entries.map((e) => keyOf(e.round, e.slot)); },
    entries() { return entries.map((e) => ({ ...e })); },
    size() { return entries.length; },
    /** A plain-array snapshot for persistence. */
    snapshot() { return entries.map((e) => ({ ...e })); },
  };
}

// ── The owned EVIDENCE LADDER ───────────────────────────────────────────────────────────────────────
/**
 * Build the engine's owned evidence ladder — a monotone-up-by-pointer level (the spine G7/I4 sits on).
 *
 * I4 (G7 downgrade-only): the audit can RAISE a level ONLY with a NEW fetched pointer — raising with no
 * pointer, or with a pointer already used, THROWS (re-used evidence is not new evidence). DOWNGRADING
 * needs no new pointer (an audit may always lower its claim). Wave 5 owns and persists this; Wave 6 wires
 * the G7 audit that exercises it.
 * @param {{level?:number, pointers?:string[]}} [initial] state to restore (from a resumed checkpoint)
 */
export function makeLadder(initial = null) {
  let level = 0;
  const pointers = [];
  const seenPtr = new Set();
  if (initial && typeof initial === 'object') {
    level = Number.isInteger(initial.level) && initial.level >= 0 ? initial.level : 0;
    for (const p of initial.pointers ?? []) { pointers.push(p); seenPtr.add(p); }
  }
  return {
    level() { return level; },
    pointers() { return [...pointers]; },
    /** Raise the level by one — REQUIRES a fresh, never-before-seen fetched pointer (I4). */
    raise(pointer) {
      const p = typeof pointer === 'string' ? pointer.trim() : '';
      if (!p) {
        throw new HaltError('ladder.raise requires a fresh fetched pointer (I4: no level-up without a new pointer)');
      }
      if (seenPtr.has(p)) {
        throw new HaltError('ladder.raise: pointer already used — a re-used pointer is not new evidence (I4)', p);
      }
      pointers.push(p);
      seenPtr.add(p);
      level += 1;
      return level;
    },
    /** Downgrade the level (no new pointer needed; never below 0). */
    lower(by = 1) {
      const n = Number.isInteger(by) && by > 0 ? by : 1;
      level = Math.max(0, level - n);
      return level;
    },
    snapshot() { return { level, pointers: [...pointers] }; },
  };
}

// ── GATE-1: independent-origins quorum, via the shared module (the SOLE counter) ────────────────────
/**
 * Compute GATE-1's origin/quorum verdict for a round, delegating to the Wave-2 shared
 * independence-accounting module — the one true place origins are counted (I3). The engine never
 * re-implements the count; it routes through `meetsQuorum`. In the skeleton the round carries no
 * reviewers yet (later waves populate them), so origins=0 and the static ≥2 floor is unmet — a real,
 * if vacuous, use of the module wired into the loop.
 * @param {{reviewers?:Array<object>, rhoHat?:?number, attestedLineages?:Iterable<string>}} ctx
 * @returns {{origins:number, required:number, met:boolean}}
 */
export function gateOneQuorum(ctx = {}) {
  return meetsQuorum(ctx.reviewers ?? [], {
    rhoHat: ctx.rhoHat ?? null,
    staticFloor: STATIC_QUORUM_FLOOR,
    attestedLineages: ctx.attestedLineages,
  });
}

// ── The scripted driver (the `agent()` seam) ────────────────────────────────────────────────────────
function gatePrompt(slot, ctx) {
  // Skeleton prompt: deterministic, side-effect-free. Later waves replace this per-slot with the real
  // gate prompt; the seam shape (a string prompt + an opts object) stays fixed.
  return [
    `[researchPrime engine — gate ${slot.gate} (${slot.id})]`,
    `round ${ctx.round ?? 0}: ${slot.serves}`,
    `(skeleton no-op — behavior filled in ${slot.fills})`,
  ].join('\n');
}

/**
 * Build the engine driver from an injected `agent()` — the SAME injection contract as the trio's
 * `makeSharkDriver({ agent })`. The driver is the only thing that invokes `agent`, so the loop's
 * call-order is exactly the order `runGate` is called. `agent(prompt, opts)` receives the slot and round
 * on `opts` so a scripted/spy agent can witness which slot is running.
 * @param {{agent:(prompt:string,opts?:object)=>Promise<any>}} deps
 */
export function makeEngineDriver({ agent } = {}) {
  if (typeof agent !== 'function') {
    throw new HaltError(
      'makeEngineDriver requires an agent() function',
      'pass the scripted seam: makeEngineDriver({ agent })',
    );
  }
  return {
    async runGate(slot, ctx = {}) {
      const out = await agent(gatePrompt(slot, ctx), {
        label: `gate:${slot.id}:r${ctx.round ?? 0}`,
        slot,
        round: ctx.round ?? 0,
      });
      return { slot: slot.id, gate: slot.gate, out: out ?? null };
    },
  };
}

// ── Checkpoint plumbing (reusing Foreman's durable primitives) ──────────────────────────────────────
function newEngineCheckpoint({ planPath, maxRounds }) {
  // Reuse Foreman's schema-valid checkpoint; map its wave fields onto verification ROUNDS and carry the
  // engine's owned state in the `rp_engine` extension (tolerated by validateCheckpoint — extra fields are
  // not rejected). current_wave = round, total_waves = maxRounds, iteration = completed steps this run.
  const cp = newCheckpoint({ plan_path: planPath, total_waves: maxRounds, reviewer_count: 0 });
  cp.intra_wave_step = 'gate';
  cp.rp_engine = {
    schema_version: ENGINE_SCHEMA_VERSION,
    slots: GATE_SLOTS.map((s) => s.id),
    ledger: [],
    ladder: { level: 0, pointers: [] },
    cursor: { round: 1, slotIndex: 0 },
  };
  return cp;
}

function syncCheckpoint(cp, { ledger, ladder, round, slotIndex, status }) {
  cp.current_wave = round;
  cp.iteration = ledger.size();
  cp.rp_engine.ledger = ledger.snapshot();
  cp.rp_engine.ladder = ladder.snapshot();
  cp.rp_engine.cursor = { round, slotIndex };
  if (status) {
    cp.status = status;
    cp.intra_wave_step = status === 'done' ? 'done' : 'gate';
  }
  return cp;
}

// ── The loop ────────────────────────────────────────────────────────────────────────────────────────
/**
 * Run the verification loop skeleton: traverse every gate-slot, in order, for each round, via the
 * scripted driver. Crash-durable and resumable.
 *
 *   - statePath set        → persist a durable checkpoint (reused Foreman atomic writer) after EVERY
 *                            completed step, so a crash mid-loop leaves a resumable checkpoint.
 *   - resume:true          → restore the run ledger/ladder/cursor from statePath and CONTINUE; a
 *                            completed step (present in the restored ledger) is NEVER re-run.
 *
 * @param {object} o
 * @param {(prompt:string,opts?:object)=>Promise<any>} o.agent  the scripted seam (required)
 * @param {object}  [o.item]       run input seeding the round context (e.g. `{ reviewers }`)
 * @param {?string} [o.statePath]  durable checkpoint path; null ⇒ ephemeral (no persistence/resume)
 * @param {boolean} [o.resume]     restore + continue from statePath
 * @param {number}  [o.maxRounds]  skeleton default 1 (a single no-op round; multi-round is Wave 7's G5)
 * @param {string}  [o.planPath]   recorded in the checkpoint for provenance
 * @param {(m:string)=>void} [o.log]
 * @returns {Promise<{status:string, rounds:number, steps:string[], ledger:object[], ladder:object, surfaceModules:string[]}>}
 */
export async function runEngine({
  agent,
  item = {},
  statePath = null,
  resume = false,
  maxRounds = 1,
  planPath = 'IMPLEMENTATION-PLAN.md',
  log = () => {},
} = {}) {
  const driver = makeEngineDriver({ agent });

  let cp;
  if (resume) {
    if (!statePath) {
      throw new HaltError('runEngine: resume requires a statePath to read the checkpoint from');
    }
    cp = readCheckpoint(statePath); // validates schema; HALTs on torn/invalid (reused primitive)
    if (!cp.rp_engine || cp.rp_engine.schema_version !== ENGINE_SCHEMA_VERSION) {
      throw new HaltError(
        'runEngine: checkpoint is missing or has an incompatible rp_engine extension',
        JSON.stringify(cp.rp_engine ?? null),
      );
    }
    maxRounds = cp.total_waves;
  } else {
    cp = newEngineCheckpoint({ planPath, maxRounds });
    if (statePath) writeCheckpointAtomic(statePath, cp);
  }

  const ledger = makeLedger(cp.rp_engine.ledger);
  const ladder = makeLadder(cp.rp_engine.ladder);
  const startRound = cp.rp_engine.cursor.round ?? 1;

  for (let round = startRound; round <= maxRounds; round++) {
    const ctx = { round, reviewers: item.reviewers ?? [], item, ladder };
    for (let slotIndex = 0; slotIndex < GATE_SLOTS.length; slotIndex++) {
      const slot = GATE_SLOTS[slotIndex];
      if (ledger.hasStep(round, slot.id)) continue; // resume: a completed step is never re-run
      const driven = await driver.runGate(slot, ctx);
      // GATE-1 routes through the shared independence-accounting module (the sole origin counter).
      const quorum = slot.id === GATE_ONE_ID ? gateOneQuorum(ctx) : null;
      ledger.append({ round, slot: slot.id, gate: slot.gate, result: driven.out, quorum });
      // Persist AFTER the append so the durable checkpoint only ever names truly-completed steps.
      if (statePath) {
        writeCheckpointAtomic(statePath, syncCheckpoint(cp, { ledger, ladder, round, slotIndex: slotIndex + 1 }));
      }
      log(`gate ${round}:${slot.id} (${slot.gate}) traversed`);
    }
    // Skeleton convergence: a no-op round goes dry immediately (real G5 convergence-until-dry is Wave 7).
  }

  if (statePath) {
    writeCheckpointAtomic(
      statePath,
      syncCheckpoint(cp, { ledger, ladder, round: maxRounds, slotIndex: GATE_SLOTS.length, status: 'done' }),
    );
  }

  return {
    status: 'done',
    rounds: maxRounds,
    steps: ledger.steps(),
    ledger: ledger.snapshot(),
    ladder: ladder.snapshot(),
    surfaceModules: Object.keys(TRIO_SURFACE),
  };
}
