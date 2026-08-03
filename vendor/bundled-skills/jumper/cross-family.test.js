// cross-family.test.js — W7: Jumper is genuinely cross-family.
//
//  (1) the Gate-3 kill-filter routes to a NON-drafter (Gemini) family BY DEFAULT (not opt-in) and HALTs
//      honestly when the verifier would resolve to the drafter/ideation family (self-review);
//  (2) the composed Gandalf deep-think lane inherits the LIVE cross-family refuter — a firing elevation,
//      given a stub Gemini refuter, mints a claim-bound commission into a SHARED per-run ledger and
//      reaches GROUNDED with cross_model:true; a DOWN refuter honestly floors it to SPECULATIVE (no
//      cross-family grant, never a same-family self-review).
//
// A STUB role-routed agent is injected throughout — ZERO live `agy` calls (the live proof is the human's).

// Hermeticity pin (P1 2026-07-25): host model prefs (e.g. coding=review=grok in
// ~/.anchor/model_prefs.json) made Gate-3 seating resolve SAME-family, so the
// engine's (correct) JumperSelfReviewHalt failed 9 suite tests on such hosts.
// Pin independent families — env outranks the prefs file — so the suite is
// hermetic everywhere. The engine refusal itself stays covered by the tests
// that pin same-family deliberately.
process.env.CODING_FAMILY = 'claude';
process.env.REVIEW_FAMILY = 'gemini';

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { KillFilter, runGandalf, JumperSelfReviewHalt } from './index.js';

// ── Gate 3: cross-family by default ──────────────────────────────────────────────────────────────────

const VALID_CONCEPT = {
  symmetricalResolution: 'A durable, memory-mapped dedupe cache with active eviction.',
  resolutionReasoning: 'Separates stateless routing from the transient dedupe state.',
  trizPrinciplesApplied: ['Segmentation'],
  analogicalMapping: { foreignDomain: 'Cell membrane transport', analogyReasoning: 'gated selective flow' },
  coreContradictions: [{ description: 'stateless vs stateful', conflictingDemands: 'both' }],
};

/** A drafter (Claude-seat) seam that passes gates 1 & 2 (one merged call) and records every call it saw. */
function drafterSeam() {
  const calls = [];
  const agent = async (opts) => {
    calls.push({ label: opts.label, driver: opts.driver, role: opts.role });
    if (opts.label === 'KillFilterGate1and2') {
      return {
        gate1: { passed: true, reasoning: 'gate 1 ok' },
        gate2: { passed: true, reasoning: 'gate 2 ok' },
      };
    }
    return { passed: true, reasoning: `${opts.label} ok` };
  };
  return { agent, calls };
}

test('W7 Gate-3: routes to a Gemini (non-drafter) family BY DEFAULT via a dedicated role-routed agent', async () => {
  const { agent: drafterAgent, calls: drafterCalls } = drafterSeam(); // drafter driver defaults to claude
  const gate3Calls = [];
  const gate3Agent = async (prompt, opts) => {
    gate3Calls.push(opts);
    return { passed: true, reasoning: 'cross-family adversary found no structural gap' };
  };

  const filter = new KillFilter({ runAgent: drafterAgent });
  const result = await filter.run(VALID_CONCEPT, { gate3Agent }); // no gate3Driver set ⇒ DEFAULT cross-family

  assert.equal(result.passed, true);
  assert.equal(result.gateLogs.length, 3);
  // Gate 3 ran on the injected cross-family agent (NOT the drafter seam), under the 'gate' role.
  assert.equal(gate3Calls.length, 1, 'Gate 3 dispatched to the cross-family agent exactly once');
  assert.equal(gate3Calls[0].role, 'gate');
  assert.equal(gate3Calls[0].label, 'KillFilterGate3');
  // The substrate log stamps the cross-family default (Gemini).
  assert.equal(result.gateLogs[2].substrate, 'cross-family:gemini-cli');
  // Gates 1 & 2 ran on the drafter seam as ONE merged call; the drafter seam NEVER ran Gate 3 (no self-review).
  assert.ok(drafterCalls.some((c) => c.label === 'KillFilterGate1and2'));
  assert.ok(!drafterCalls.some((c) => c.label === 'KillFilterGate3'));
});

test('W7 Gate-3: self-review HALTs — a verifier resolving to the drafter (claude) family is refused', async () => {
  const { agent: drafterAgent } = drafterSeam();
  const filter = new KillFilter({ runAgent: drafterAgent, driver: 'claude' });
  await assert.rejects(
    // verifier driver forced to claude = the drafter family ⇒ self-review ⇒ HALT (before any dispatch).
    filter.run(VALID_CONCEPT, { gate3Driver: 'claude' }),
    JumperSelfReviewHalt,
  );
});

// ── Gandalf deep-think lane: inherits the live cross-family refuter ───────────────────────────────────

// A concrete named defeater (a falsifying observation, never a confidence word).
const DEFEATER =
  'A replay benchmark on the production workload that reproduces a lost acked write after a mid-flush crash.';

/** A Gandalf raw draft carrying ONE high-value elevation that FIRES the refuter (value_if_true:high)
 *  with its own named defeater but NO tier/provenance — exactly the raw shape the model emits. */
function firingDraft() {
  return {
    reasoning: 'A deep-think advisor pass emitting a high-value elevation for live cross-family refutation.',
    verdict: 'grade against the live cross-family refuter',
    findings: [],
    nitpicks: [],
    elevations: [{
      id: 'e-live',
      value_if_true: 'high',
      rung: 'CORROBORATED',
      reasoning: 'Adopt ordered durable commit then apply (WAL recovery ordering).',
      verdict: 'adopt the WAL recovery ordering',
      what_would_refute_it:
        'A replay benchmark showing the WAL ordering still loses the last acked write after a mid-flush crash.',
    }],
  };
}

test('W7 Gandalf lane: a firing elevation + a SURVIVING stub Gemini refuter reaches GROUNDED (cross_model:true) via a shared per-run ledger', async () => {
  const draftAgent = async () => firingDraft(); // label 'GandalfDraft'
  const refuterCalls = [];
  const refuterAgent = async (prompt, opts) => {
    refuterCalls.push(opts);
    return { defeater: DEFEATER, survived: true, verdict: 'the claim survived the replay attempt' };
  };

  const out = await runGandalf('WAL durability problem', { runAgent: draftAgent, refuterAgent });

  assert.equal(refuterCalls.length, 1, 'the cross-family refuter was dispatched for the one firing elevation');
  assert.equal(refuterCalls[0].role, 'refuter', 'the dispatch used the refuter role');
  assert.equal(out.cross_model, true, 'a genuine ledger-bound cross-family refutation DERIVES cross_model:true');
  assert.equal(out.elevations.length, 1);
  assert.equal(out.elevations[0].tier, 'GROUNDED', 'the surviving cross-family elevation reaches GROUNDED');
  assert.equal(out.elevations[0].cross_family_refuted, true);
});

test('W7 Gandalf lane honest-degrade: a DOWN refuter floors the elevation to SPECULATIVE — no cross-family grant', async () => {
  const draftAgent = async () => firingDraft();
  const refuterAgent = async () => {
    throw new Error('Gemini/agy transport failed — refuse to return a non-attested cross-family result');
  };

  const out = await runGandalf('WAL durability problem', { runAgent: draftAgent, refuterAgent });

  assert.equal(out.cross_model, false, 'a down refuter can never lift cross_model');
  assert.equal(out.elevations.length, 1);
  assert.equal(out.elevations[0].tier, 'SPECULATIVE', 'the elevation floors to the honest SPECULATIVE tier');
  assert.equal(out.elevations[0].cross_family_refuted ?? false, false);
});
