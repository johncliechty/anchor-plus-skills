// Wave 5 — Inheritance CONFORMANCE gate (A0.5b).
//
// Wave 2 (A0.5a) proved each inherited seam is PRESENT and has the right interface SHAPE
// (its declared exports exist with the declared types / its JSON keys exist). That is a
// necessary but NOT sufficient guarantee: a seam can resolve, version-check, and shape-check
// while still BEHAVING in a way that violates the contract Ramanujan's spine relies on (a
// gandalf seam that self-CORROBORATES, a "durability" substrate that does not actually
// persist across a restart, a research deliverable that never converged). Those are exactly
// the failures an interface gate is blind to.
//
// This wave is the BEHAVIORAL gate. For every inherited seam it runs a CONFORMANCE FIXTURE
// that EXERCISES the seam against the REAL A1 ledger (src/claim-ledger.mjs) + the A1.5
// adjudication substrate (src/adjudication.mjs) and the A3 VERIFY-router CONTRACT (the
// pinned behavioural expectations the Wave-7 router places on each seam — emit-not-dispatch
// commission envelopes, the single-family honesty cap, a converged research deliverable),
// with PINNED PER-SEAM contract assertions. The A3 router itself is built in Wave 7; here we
// pin the contract it will compose against, so a non-conforming seam is caught at the Phase-B
// boundary rather than deep inside a pillar.
//
//   done-when: each inherited seam passes its conformance fixture; a planted non-conforming
//   seam fails the gate NON-ZERO, NAMING the seam; gates Phase B+.
//
// Dependency-free apart from the project's own A1/A1.5 modules and the inherited seams it
// resolves through the pinned inherits.manifest.json. Runs under `node --test test/` and as a
// CLI (exit 0 green / non-zero on any non-conformance).

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import {
  loadManifest,
  resolveEntryPath,
  DEFAULT_MANIFEST_PATH,
} from './inherits-gate.mjs';
import {
  ClaimLedger,
  RUNG,
  BELIEF,
  isRung,
  beliefForRung,
} from './claim-ledger.mjs';
import {
  DurableNonceStore,
  AdjudicationDispatcher,
  adjudicatedPromoteToVerified,
  canonicalStdoutHash,
  VERDICT,
} from './adjudication.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Assertion helper — every conformance fixture returns a flat list of these.
// ---------------------------------------------------------------------------

/** A single pinned contract assertion. `ok` false => the seam does not conform. */
function A(name, ok, detail) {
  return { name, ok: Boolean(ok), detail: ok ? undefined : detail };
}

// A stable, real 64-hex stdout hash a Wave-9 firewall subprocess would emit (Wave 5 supplies
// it directly — Wave 5 spawns nothing; it exercises the nonce/ledger substrate, not the child).
const STDOUT_HASH = canonicalStdoutHash({ result: '6', op: 'sum_{k=1}^{3} k' });

// A monotone scratch-file counter so each durability exercise gets its own "disk".
let confFileSeq = 0;

// ===========================================================================
// Per-seam conformance fixtures. Each: async (seam, ctx) => { assertions: [...] }.
// `seam` is the resolved live value (module namespace for kind:module, parsed object
// for kind:json). `ctx` carries { scratchDir, manifestPath, entry }.
// ===========================================================================

// --- phase0-durability: the A1.5 adjudication substrate persists THROUGH this seam ----------
//
// The strongest "against the real A1 ledger" exercise: drive the Wave-4 DurableNonceStore +
// AdjudicationDispatcher + adjudicatedPromoteToVerified + a real ClaimLedger ON this seam, and
// assert the BEHAVIOUR the spine depends on — an adjudicated promotion reaches OBSERVED, a
// replay ABSTAINs, and (the durability-specific part) a durably-minted nonce + its monotone
// counter SURVIVE a simulated restart. An in-memory "durability" stub passes Wave 2's shape
// check but FAILS the survive-restart assertions here.
async function conformDurability(seam, ctx) {
  const assertions = [];
  for (const fn of ['newCheckpoint', 'writeCheckpointAtomic', 'readCheckpoint', 'validateCheckpoint']) {
    if (typeof seam[fn] !== 'function') {
      assertions.push(A(`exposes ${fn}()`, false, `durability seam is missing ${fn}()`));
    }
  }
  if (assertions.length) return { assertions };

  const file = path.join(ctx.scratchDir, `conf-durability-${confFileSeq++}.checkpoint.json`);

  // 1. A real adjudicated promotion runs end-to-end on this seam (A1 ledger reaches OBSERVED).
  const store = DurableNonceStore.load(seam, file);
  const dispatcher = new AdjudicationDispatcher({ store, family: 'firewall-subprocess' });
  const ledger = new ClaimLedger();
  ledger.assert({ id: 'C', type: 'computational' });
  const art = dispatcher.mintArtifact('C', 'arithmetic', { stdout_hash: STDOUT_HASH, exit_code: 0 });
  const promoted = adjudicatedPromoteToVerified(ledger, 'C', { artifact: art, dispatcher });
  assertions.push(A(
    'A1 adjudicated promotion reaches OBSERVED through the seam',
    promoted.verdict === VERDICT.VERIFIED && ledger.rungOf('C') === RUNG.OBSERVED && ledger.beliefOf('C') === BELIEF.VERIFIED,
    `expected VERIFIED/OBSERVED; got verdict=${promoted.verdict}, rung=${ledger.rungOf('C')}`,
  ));

  // 2. Same-process single-use: re-presenting the consumed artifact ABSTAINs.
  const replay = adjudicatedPromoteToVerified(ledger, 'C', { artifact: art, dispatcher });
  assertions.push(A(
    'same-process replay ABSTAINs (single-use nonce)',
    replay.verdict === VERDICT.ABSTAIN,
    `expected ABSTAIN on replay; got ${replay.verdict}`,
  ));

  // 3. DURABILITY: a freshly-minted (un-consumed) nonce survives a simulated restart as still
  //    VALID — proving the issued-record is on disk, not in process memory. (An in-memory stub
  //    loses it here.)
  const file2 = path.join(ctx.scratchDir, `conf-durability-${confFileSeq++}.checkpoint.json`);
  const s1 = DurableNonceStore.load(seam, file2);
  const { nonce } = s1.mint('D', 'arithmetic');
  const restarted = DurableNonceStore.load(seam, file2); // restart: reload ONLY from disk
  assertions.push(A(
    'a durably-minted nonce survives a restart as still-valid',
    restarted.isValid(nonce, 'D', 'arithmetic') === true,
    'the minted nonce did not survive a simulated restart — the substrate is not durable',
  ));

  // 4. DURABILITY: the monotone counter does not reset across a restart.
  assertions.push(A(
    'the monotone counter survives a restart (no reset)',
    restarted.counterFor('D', 'arithmetic') === 1 && restarted.mint('D', 'arithmetic').counter === 2,
    `expected counter 1 then 2 after restart; got ${restarted.counterFor('D', 'arithmetic')}`,
  ));

  // 5. The torn-write defence A1's substrate relies on: validateCheckpoint rejects a malformed
  //    checkpoint, and readCheckpoint refuses to best-effort-parse torn JSON.
  let rejectedMalformed = false;
  try { seam.validateCheckpoint({ not: 'a checkpoint' }); } catch { rejectedMalformed = true; }
  assertions.push(A('validateCheckpoint rejects a malformed checkpoint', rejectedMalformed,
    'validateCheckpoint accepted a non-checkpoint object'));

  const tornFile = path.join(ctx.scratchDir, `conf-torn-${confFileSeq++}.json`);
  fs.writeFileSync(tornFile, '{ "current_wave": 1, '); // truncated / torn JSON
  let rejectedTorn = false;
  try { seam.readCheckpoint(tornFile); } catch { rejectedTorn = true; }
  assertions.push(A('readCheckpoint refuses torn JSON', rejectedTorn,
    'readCheckpoint best-effort-parsed a torn file instead of refusing'));

  return { assertions };
}

// --- gandalf-commission-seam: the A3 ABSTAIN/route arm EMITS a commission envelope ----------
//
// The A3 router's honest-abstain arm (Wave 7) routes a conceptual/proof claim OUT of model by
// EMITTING a typed researchPrime commission ENVELOPE — it never dispatches inline, and on the
// single-family substrate it earns NO independent-origin credit, so a SITUATE finding caps at
// CLAIMED (which projects to CONJECTURAL — NOT settled). These are the pinned A3×honesty-law
// behaviours; a seam that self-CORROBORATES violates the contract.
async function conformGandalfCommission(seam) {
  const assertions = [];

  // emit (never dispatch): a commission envelope is minted as a pure value carrying its fields.
  const envelope = seam.commissionResearchPrime({ question: 'Is this the strongest known frame?' });
  assertions.push(A(
    'commissionResearchPrime emits a typed researchPrime envelope',
    envelope && typeof envelope === 'object' && envelope.skill === 'researchPrime' &&
      typeof envelope.question === 'string' && 'researchprime_commission_id' in envelope,
    `envelope malformed: ${JSON.stringify(envelope)}`,
  ));

  // single-family ⇒ NO independent-origin credit (the anti-laundering honesty rule).
  assertions.push(A(
    'a single-family commission earns NO independent-origin credit',
    envelope.cross_model === false && envelope.independent_origin === false &&
      seam.independentOriginCredit(envelope) === false,
    `expected independent_origin=false on a same-family commission; got ${envelope.independent_origin}`,
  ));

  // ...and the seam honours an explicit cross-family flag (it is not hard-wired to false).
  const xfam = seam.commissionResearchPrime({ question: 'q', cross_model: true });
  assertions.push(A(
    'an explicit cross_model commission earns independent-origin credit',
    seam.independentOriginCredit(xfam) === true,
    'cross_model:true did not earn independent-origin credit',
  ));

  // a composed SITUATE finding caps at CLAIMED (no self-CORROBORATED) and that rung is a valid
  // A1 ladder rung projecting to CONJECTURAL (a routed finding is NOT asserted as settled).
  const finding = seam.composeSituate({
    id: 'sit-1',
    abstraction: seam.abstractEffort('an effort to situate'),
    commission: envelope,
    structure_map: {
      answer: 'the target structure mirrors the source under these relations',
      correspondences: [
        { source_relation: 'a divides b', target_relation: 'x divides y' },
        { source_relation: 'b bounds c', target_relation: 'y bounds z' },
      ],
    },
    outside_view_base_rate: '1 in 5 such frames hold',
    facts_verified: false,
  });
  const capRung = seam.SITUATE_SELF_MAX_RUNG;
  assertions.push(A(
    'a same-family SITUATE finding caps at CLAIMED (no self-CORROBORATED)',
    finding.rung === capRung && capRung === 'CLAIMED',
    `expected rung CLAIMED; got ${finding.rung} (cap=${capRung})`,
  ));
  assertions.push(A(
    'the cap rung is a valid A1 ladder rung that projects to CONJECTURAL (not settled)',
    isRung(capRung) && beliefForRung(capRung) === BELIEF.CONJECTURAL,
    `cap rung ${capRung} is not a valid A1 rung / does not project to CONJECTURAL`,
  ));

  // unverified facts are ROUTED OUT via a researchPrime needs_verification handoff (the A3
  // advisory payload), never asserted real.
  assertions.push(A(
    'an unverified finding carries a researchPrime needs_verification handoff (route-out)',
    seam.needsVerificationHandoff(finding) === true,
    'an unverified SITUATE finding did not carry a needs_verification route-out',
  ));

  return { assertions };
}

// --- phase0-handoff: a clean stage handoff round-trips + holds the line on drift ------------
//
// The pillars hand typed state across stage boundaries through this seam (NS5 anti-drift). The
// router/orchestrator rely on it round-tripping byte-identical, validating a clean handoff, and
// REFUSING one that drifts the locked North Star or carries open questions.
async function conformHandoff(seam, ctx) {
  const assertions = [];
  const repoRoot = path.dirname(ctx.manifestPath);
  const northStar = 'NORTH STAR: do not drift.';
  const handoff = {
    stage: 'A0.5b->B',
    north_star: northStar,
    artifact_refs: [ctx.manifestPath], // an absolute path that resolves on disk
    open_questions: [],
  };

  // round-trip: emit -> parse -> re-emit byte-identical.
  const doc = seam.emitHandoff(handoff);
  const reparsed = seam.parseHandoff(doc);
  const reEmitted = seam.emitHandoff(reparsed);
  assertions.push(A(
    'a handoff round-trips byte-identical (emit -> parse -> re-emit)',
    reEmitted === doc && reparsed.stage === handoff.stage && reparsed.north_star === northStar,
    'handoff did not round-trip byte-identical',
  ));

  // a clean handoff validates.
  const clean = seam.validateHandoff({ handoff, upstreamNorthStar: northStar, baseDir: repoRoot });
  assertions.push(A(
    'a clean, schema-valid, drift-free handoff validates',
    clean.ok === true,
    `clean handoff failed validation: ${JSON.stringify(clean.results && clean.results.filter((r) => !r.ok))}`,
  ));

  // a drifted North Star is REFUSED (anti-drift).
  const drifted = seam.validateHandoff({ handoff, upstreamNorthStar: northStar + ' (tampered)', baseDir: repoRoot });
  assertions.push(A(
    'a North-Star drift is refused',
    drifted.ok === false,
    'a handoff whose north_star drifted from the locked upstream still validated',
  ));

  // an under-specified handoff (open questions) is REFUSED.
  const open = seam.validateHandoff({
    handoff: { ...handoff, open_questions: ['unresolved?'] },
    upstreamNorthStar: northStar,
    baseDir: repoRoot,
  });
  assertions.push(A(
    'an under-specified handoff (open questions) is refused',
    open.ok === false,
    'a handoff with open questions still validated',
  ));

  return { assertions };
}

// --- phase0-journal: the 7-field journal the oracle's sleep-loop (E2) consumes ---------------
async function conformJournal(seam) {
  const assertions = [];
  assertions.push(A(
    'the journal schema is the pinned 7 fields',
    Array.isArray(seam.JOURNAL_FIELDS) && seam.JOURNAL_FIELDS.length === 7,
    `expected 7 journal fields; got ${seam.JOURNAL_FIELDS && seam.JOURNAL_FIELDS.length}`,
  ));

  const good = {
    id: 'j1', skill: 'ramanujan@0.1.0', situation: 'comprehension', context: 'fixture-A',
    observation: 'laddered claim landed at expected rung', outcome: 'canary-pass',
    provenance: 'genuine-execution',
  };
  assertions.push(A(
    'a well-formed 7-field entry validates',
    seam.validateEntry(good).ok === true,
    `a well-formed entry failed: ${seam.validateEntry(good).detail}`,
  ));

  const { id, ...missingId } = good;
  assertions.push(A(
    'a missing required field fails validation',
    seam.validateEntry(missingId).ok === false && seam.validateEntry(missingId).missing.includes('id'),
    'a journal entry missing its id still validated',
  ));

  assertions.push(A(
    'a bad provenance value fails validation',
    seam.validateEntry({ ...good, provenance: 'fabricated' }).ok === false &&
      seam.validateEntry({ ...good, provenance: 'fabricated' }).badProvenance === true,
    'a journal entry with an out-of-vocabulary provenance still validated',
  ));

  return { assertions };
}

// --- phase0-sleep: cross-context-corroborated distill + no-regression / anti-drift gates -----
async function conformSleep(seam) {
  const assertions = [];

  // cross-context corroboration: the SAME situation seen in DISTINCT contexts yields a candidate.
  const genuine = (id, situation, context) => ({
    id, skill: 's@1', situation, context, observation: `obs-${id}`, outcome: 'canary-pass',
    provenance: 'genuine-execution',
  });
  const crossContext = seam.distill([
    genuine('a', 'recurring', 'ctx-1'),
    genuine('b', 'recurring', 'ctx-2'),
  ]);
  assertions.push(A(
    'a cross-context-corroborated cluster distills to a candidate',
    crossContext.candidates.length === 1 && crossContext.candidates[0].situation === 'recurring',
    `expected 1 cross-context candidate; got ${crossContext.candidates.length}`,
  ));

  // same-context-only is REJECTED (R5): repetition in one context does not corroborate.
  const sameContext = seam.distill([
    genuine('c', 'lonely', 'ctx-1'),
    genuine('d', 'lonely', 'ctx-1'),
  ]);
  assertions.push(A(
    'a same-context-only cluster is rejected, not shipped',
    sameContext.candidates.length === 0 &&
      sameContext.rejected.some((r) => r.situation === 'lonely' && r.reason === 'same-context-only'),
    'a same-context-only cluster was not rejected',
  ));

  // seeded provenance never clusters (provenance-distrust).
  const seeded = seam.clusterEntries([
    { id: 'e', situation: 'x', context: 'c1', provenance: 'seeded' },
    { id: 'f', situation: 'x', context: 'c2', provenance: 'seeded' },
  ]);
  assertions.push(A(
    'seeded entries never cluster (provenance-distrust)',
    seeded.size === 0,
    'seeded entries were clustered',
  ));

  // no-regression eval gate + anti-drift North-Star gate behave.
  const revision = { evaluate: (x) => x + 1 };
  const ev = seam.evalGate(revision, [{ name: 'inc', input: 1, expected: 2 }]);
  assertions.push(A('the eval gate passes a non-regressing revision', ev.ok === true,
    `eval gate blocked a passing revision: ${JSON.stringify(ev.regressions)}`));

  const drift = seam.northStarGate({ evaluate: () => 'did-the-forbidden-thing' }, [
    { id: 'no-goal', input: null, drifts: (o) => o === 'did-the-forbidden-thing' },
  ]);
  assertions.push(A('the North-Star gate rejects a drift onto a non-goal', drift.ok === false,
    'the North-Star gate let a non-goal drift through'));

  return { assertions };
}

// --- dive-1/2/3 deliverables: the research engines the pillars compose -----------------------
//
// The A3 router composes a research deliverable only when it CONVERGED and carries the
// honesty-law stamp block the router reads. Wave 2 checked the keys exist; this checks the
// VALUES/sub-shape the router contract relies on.
async function conformDiveDeliverable(seam) {
  const assertions = [];
  assertions.push(A(
    'the deliverable carries a non-null deliverable payload',
    seam && typeof seam === 'object' && seam.deliverable !== undefined && seam.deliverable !== null,
    'deliverable payload is missing/null',
  ));
  assertions.push(A(
    'convergence is reported and the engine CONVERGED',
    seam.convergence && typeof seam.convergence === 'object' && seam.convergence.converged === true,
    `expected convergence.converged === true; got ${seam.convergence && seam.convergence.converged}`,
  ));
  assertions.push(A(
    'the honesty stamp block carries the law fields the router reads',
    seam.honesty && typeof seam.honesty === 'object' && !Array.isArray(seam.honesty) &&
      'suspicious' in seam.honesty && 'singleFamily' in seam.honesty && 'stamp' in seam.honesty,
    `honesty block missing required fields: ${JSON.stringify(seam.honesty)}`,
  ));
  assertions.push(A(
    'tier is a non-empty string',
    typeof seam.tier === 'string' && seam.tier.length > 0,
    `tier is not a non-empty string: ${JSON.stringify(seam.tier)}`,
  ));
  assertions.push(A(
    'thresholds carry the N/K/M ladder',
    seam.thresholds && typeof seam.thresholds === 'object' &&
      ['N', 'K', 'M'].every((k) => Number.isFinite(seam.thresholds[k])),
    `thresholds missing N/K/M: ${JSON.stringify(seam.thresholds)}`,
  ));
  return { assertions };
}

// ---------------------------------------------------------------------------
// The fixture registry — one conformance fixture per pinned inherited seam.
// ---------------------------------------------------------------------------

/** logical_name -> conformance fixture (async (seam, ctx) => { assertions }). */
export const CONFORMANCE_FIXTURES = Object.freeze({
  'phase0-durability': conformDurability,
  'gandalf-commission-seam': conformGandalfCommission,
  'phase0-handoff': conformHandoff,
  'phase0-journal': conformJournal,
  'phase0-sleep': conformSleep,
  'dive-1-understand-firewall': conformDiveDeliverable,
  'dive-2-solve-verify': conformDiveDeliverable,
  'dive-3-interactive-partner': conformDiveDeliverable,
});

// ---------------------------------------------------------------------------
// Seam resolution (live value: module namespace or parsed JSON).
// ---------------------------------------------------------------------------

/** Resolve a manifest entry to its live seam value. Throws on an unresolvable/unknown entry. */
export async function resolveSeam(manifestPath, entry) {
  const resolved = resolveEntryPath(manifestPath, entry);
  if (!fs.existsSync(resolved)) throw new Error(`path does not exist: ${resolved}`);
  if (entry.kind === 'module') return import(pathToFileURL(resolved).href);
  if (entry.kind === 'json') return JSON.parse(fs.readFileSync(resolved, 'utf8'));
  throw new Error(`unknown entry kind: ${JSON.stringify(entry.kind)}`);
}

// ---------------------------------------------------------------------------
// The gate.
// ---------------------------------------------------------------------------

/**
 * Run the A0.5b conformance gate against `manifestPath`. For every manifest entry it resolves
 * the seam (or takes an override) and runs that seam's conformance fixture, collecting pinned
 * contract assertions. Returns { ok, seams:[{logical_name, ok, assertions, failures}],
 * failures:[ "logical_name: reason", ... ] }; `ok` is true iff EVERY seam conformed. Every
 * failure is prefixed with the offending seam's logical_name (so a non-zero exit names it).
 *
 * @param {string} [manifestPath]
 * @param {{
 *   overrides?: Record<string, any>,  // logical_name -> a substitute seam value (for planted
 *                                      //   non-conforming-seam tests); resolved seam used otherwise.
 *   scratchDir?: string,              // scratch dir for the durability fixture (one is made if omitted)
 * }} [opts]
 */
export async function runConformanceGate(manifestPath = DEFAULT_MANIFEST_PATH, { overrides = {}, scratchDir } = {}) {
  const failures = [];
  const seams = [];
  let manifest;
  try {
    manifest = loadManifest(manifestPath);
  } catch (e) {
    return { ok: false, seams: [], failures: [`manifest: ${e.message}`] };
  }

  let scratch = scratchDir;
  let createdScratch = false;
  if (!scratch) {
    scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w5-'));
    createdScratch = true;
  }

  try {
    for (const entry of manifest.entries) {
      const name = entry.logical_name || '(unnamed entry)';
      const fixture = CONFORMANCE_FIXTURES[name];

      if (!fixture) {
        const reason = 'no conformance fixture registered for this seam';
        failures.push(`${name}: ${reason}`);
        seams.push({ logical_name: name, ok: false, assertions: [], failures: [reason] });
        continue;
      }

      // Resolve the seam value (an override takes precedence — the planted-seam mechanism).
      let seam;
      let resolveErr = null;
      if (Object.prototype.hasOwnProperty.call(overrides, name)) {
        seam = overrides[name];
      } else {
        try {
          seam = await resolveSeam(manifestPath, entry);
        } catch (e) {
          resolveErr = e.message;
        }
      }
      if (resolveErr) {
        const reason = `unresolvable — ${resolveErr} (run the A0.5a presence gate)`;
        failures.push(`${name}: ${reason}`);
        seams.push({ logical_name: name, ok: false, assertions: [], failures: [reason] });
        continue;
      }

      // Run the fixture; a throw is a deterministic non-conformance, not a gate crash.
      let assertions;
      try {
        const ctx = { scratchDir: scratch, manifestPath, entry };
        const out = await fixture(seam, ctx);
        assertions = (out && Array.isArray(out.assertions)) ? out.assertions : [];
      } catch (e) {
        assertions = [A('conformance fixture threw', false, e.message)];
      }

      const seamFailures = assertions
        .filter((a) => !a.ok)
        .map((a) => `${a.name}${a.detail ? `: ${a.detail}` : ''}`);
      for (const f of seamFailures) failures.push(`${name}: ${f}`);
      seams.push({ logical_name: name, ok: seamFailures.length === 0, assertions, failures: seamFailures });
    }
  } finally {
    if (createdScratch) {
      try { fs.rmSync(scratch, { recursive: true, force: true }); } catch { /* best-effort */ }
    }
  }

  return { ok: failures.length === 0, seams, failures };
}

/** Map a gate result to a process exit code (0 = green, non-zero on any non-conformance). */
export function verdictExitCode(result) {
  return result.ok ? 0 : 1;
}

// ---------------------------------------------------------------------------
// CLI: `node src/conformance-gate.mjs [manifestPath]` — exit 0 green / 1 on any non-conformance.
// ---------------------------------------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const manifestPath = process.argv[2] ? path.resolve(process.argv[2]) : DEFAULT_MANIFEST_PATH;
  const result = await runConformanceGate(manifestPath);
  if (result.ok) {
    const n = result.seams.length;
    const a = result.seams.reduce((s, x) => s + x.assertions.length, 0);
    console.log(`OK: ${n} inherited seam${n === 1 ? '' : 's'} conform to the A1/A3 contract (${a} pinned assertions).`);
    process.exit(0);
  } else {
    console.error('FAIL: inheritance conformance gate found non-conforming seam(s):');
    for (const f of result.failures) console.error(`  - ${f}`);
    process.exit(1);
  }
}
